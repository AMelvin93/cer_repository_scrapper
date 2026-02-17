"""Shared types for the LLM analysis pipeline.

Defines AnalysisResult used across the analysis service, prompt builder,
and orchestration modules.
"""

from dataclasses import dataclass, field


@dataclass
class AnalysisResult:
    """Result of analyzing a single filing via Claude Code CLI.

    Attributes:
        success: Whether analysis produced valid, validated JSON output.
        analysis_json: The validated analysis output as a dict (None on failure).
        raw_response: Raw text response from Claude CLI (for debugging).
        model: Claude model alias used (e.g. "sonnet", "opus", "haiku").
        prompt_version: SHA-256 hash prefix of the prompt template file.
        processing_time_seconds: Wall-clock time for the analysis call.
        cost_usd: API cost reported by Claude CLI (None if unavailable).
        input_tokens: Input token count (None if unavailable).
        output_tokens: Output token count (None if unavailable).
        error: Error description if analysis failed.
        needs_chunking: Flag for Phase 7 long-document handling.
        timestamp: ISO 8601 timestamp of analysis completion.
    """

    success: bool
    analysis_json: dict | None = field(default=None)
    raw_response: str = ""
    model: str = ""
    prompt_version: str = ""
    processing_time_seconds: float = 0.0
    cost_usd: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    error: str | None = None
    needs_chunking: bool = False
    timestamp: str = ""
