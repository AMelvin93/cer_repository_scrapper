"""Core analysis service: Claude CLI subprocess invocation and response parsing.

Invokes ``claude -p`` as a subprocess with single-turn JSON output,
parses the two-level JSON response (CLI envelope wrapping analysis JSON),
strips markdown code fences, validates against AnalysisOutput schema, and
returns an AnalysisResult with full metadata.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import re
import subprocess
import sys
import time

from pydantic import ValidationError

from cer_scraper.analyzer.prompt import (
    build_prompt,
    get_json_schema_description,
    load_prompt_template,
)
from cer_scraper.analyzer.schemas import AnalysisOutput
from cer_scraper.analyzer.types import AnalysisResult
from cer_scraper.config.settings import AnalysisSettings, PROJECT_ROOT

logger = logging.getLogger(__name__)

_CODE_FENCE_RE = re.compile(
    r"^\s*```(?:json)?\s*\n?(.*?)\n?\s*```\s*$", re.DOTALL
)


def strip_code_fences(text: str) -> str:
    """Remove markdown code fences wrapping JSON content.

    Handles ``\\`\\`\\`json ... \\`\\`\\``` and bare ``\\`\\`\\` ... \\`\\`\\```
    wrappers.  Returns the inner content stripped of whitespace.
    If no code fence is detected, returns the original text stripped.

    Args:
        text: Raw text that may be wrapped in code fences.

    Returns:
        The unwrapped content.
    """
    text = text.strip()
    match = _CODE_FENCE_RE.match(text)
    return match.group(1).strip() if match else text


def _invoke_claude_cli(
    prompt_text: str, model: str, timeout: int
) -> dict:
    """Invoke Claude CLI as a subprocess and return the JSON envelope.

    Args:
        prompt_text: The fully built prompt to send via stdin.
        model: Claude model alias (e.g. ``"sonnet"``, ``"opus"``).
        timeout: Maximum seconds to wait for the subprocess.

    Returns:
        Parsed JSON envelope dict from Claude CLI stdout.

    Raises:
        subprocess.TimeoutExpired: If the process exceeds *timeout*.
        RuntimeError: If the process exits with a non-zero code.
        json.JSONDecodeError: If stdout is not valid JSON.
    """
    cmd = [
        "claude",
        "-p",
        "--output-format", "json",
        "--model", model,
        "--max-turns", "1",
        "--no-session-persistence",
        "--tools", "",
    ]

    # Strip CLAUDECODE to prevent nested session errors
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

    # Windows-specific process creation flags
    kwargs: dict = {
        "stdin": subprocess.PIPE,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "env": env,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    logger.info("Invoking Claude CLI: model=%s, timeout=%ds", model, timeout)
    proc = subprocess.Popen(cmd, **kwargs)

    try:
        stdout, stderr = proc.communicate(input=prompt_text, timeout=timeout)
    except subprocess.TimeoutExpired:
        logger.error("Claude CLI timed out after %ds, killing process", timeout)
        proc.kill()
        proc.communicate()  # Clean up zombie process
        raise

    if proc.returncode != 0:
        msg = f"Claude CLI exited with code {proc.returncode}: {stderr.strip()}"
        logger.error(msg)
        raise RuntimeError(msg)

    logger.debug("Claude CLI stdout length: %d chars", len(stdout))
    return json.loads(stdout)


def analyze_filing_text(
    filing_id: str,
    filing_date: str | None,
    applicant: str | None,
    filing_type: str | None,
    document_text: str,
    num_documents: int,
    num_missing: int,
    settings: AnalysisSettings,
) -> AnalysisResult:
    """Analyze filing text via Claude CLI and return structured result.

    This is the main public function.  It loads the prompt template,
    fills placeholders with filing data, invokes the Claude CLI
    subprocess, and parses the two-level JSON response (CLI envelope
    wrapping analysis JSON).

    Args:
        filing_id: CER filing identifier (e.g. ``"C12345"``).
        filing_date: Filing date string, or None for "Unknown".
        applicant: Applicant name, or None for "Unknown".
        filing_type: Filing type label, or None for "Unknown".
        document_text: Concatenated extracted text from all documents.
        num_documents: Total number of documents in the filing.
        num_missing: Number of documents unavailable for analysis.
        settings: Analysis configuration (model, timeout, etc.).

    Returns:
        AnalysisResult with success/failure status and full metadata.
    """
    # --- Early exit for insufficient text ---
    if len(document_text.strip()) < settings.min_text_length:
        logger.warning(
            "Filing %s: text too short (%d chars < %d minimum)",
            filing_id,
            len(document_text.strip()),
            settings.min_text_length,
        )
        return AnalysisResult(success=False, error="insufficient_text")

    # --- Load prompt template ---
    template_path = PROJECT_ROOT / settings.template_path
    template, version_hash = load_prompt_template(template_path)

    # --- Build the prompt ---
    json_schema_description = get_json_schema_description()
    prompt = build_prompt(
        template=template,
        filing_id=filing_id,
        filing_date=filing_date,
        applicant=applicant,
        filing_type=filing_type,
        document_text=document_text,
        num_documents=num_documents,
        num_missing=num_missing,
        json_schema_description=json_schema_description,
    )

    # --- Invoke Claude CLI ---
    start = time.monotonic()
    try:
        envelope = _invoke_claude_cli(prompt, settings.model, settings.timeout_seconds)
    except subprocess.TimeoutExpired:
        return AnalysisResult(
            success=False,
            error="timeout",
            needs_chunking=True,
            prompt_version=version_hash,
        )
    except RuntimeError as e:
        return AnalysisResult(
            success=False,
            error=str(e),
            prompt_version=version_hash,
        )
    except json.JSONDecodeError:
        return AnalysisResult(
            success=False,
            error="invalid_cli_json",
            prompt_version=version_hash,
        )
    processing_time = time.monotonic() - start

    # --- Check for CLI-level error ---
    if envelope.get("is_error"):
        error_msg = envelope.get("result", "Unknown CLI error")
        logger.error("Filing %s: CLI error: %s", filing_id, error_msg)
        return AnalysisResult(
            success=False,
            error=f"cli_error: {error_msg}",
            prompt_version=version_hash,
            processing_time_seconds=processing_time,
        )

    # --- Extract and parse analysis JSON ---
    raw_result = envelope["result"]
    cleaned = strip_code_fences(raw_result)

    try:
        validated_output = AnalysisOutput.model_validate_json(cleaned)
    except (ValidationError, json.JSONDecodeError) as e:
        logger.error(
            "Filing %s: validation error: %s", filing_id, str(e)[:200]
        )
        return AnalysisResult(
            success=False,
            error=f"validation_error: {e}",
            raw_response=raw_result,
            prompt_version=version_hash,
            processing_time_seconds=processing_time,
        )

    # --- Extract usage metadata ---
    usage = envelope.get("usage", {})
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")

    logger.info(
        "Filing %s: analysis complete in %.1fs (model=%s, tokens=%s/%s)",
        filing_id,
        processing_time,
        settings.model,
        input_tokens,
        output_tokens,
    )

    return AnalysisResult(
        success=True,
        analysis_json=validated_output.model_dump(),
        raw_response=raw_result,
        model=settings.model,
        prompt_version=version_hash,
        processing_time_seconds=processing_time,
        cost_usd=envelope.get("total_cost_usd"),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
    )
