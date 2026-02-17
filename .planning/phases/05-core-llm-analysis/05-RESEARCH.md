# Phase 5: Core LLM Analysis - Research

**Researched:** 2026-02-16
**Domain:** Claude Code CLI subprocess invocation, prompt engineering, structured JSON output
**Confidence:** HIGH

## Summary

Phase 5 integrates Claude Code CLI (`claude -p`) as a subprocess to analyze extracted filing text, producing structured JSON with entity extraction, document classification, summaries, and key facts. The research covers two integration approaches (subprocess vs Python SDK), the CLI's JSON output format, prompt template design, and how to get validated structured output from the analysis.

The primary decision is between raw `subprocess.Popen` with `claude -p` and the official `claude-agent-sdk` Python package (v0.1.37). The SDK provides a cleaner async API with built-in structured output validation via `--json-schema` / `output_format`, typed message classes, and proper error types. However, the existing codebase is entirely synchronous. Using subprocess keeps the architecture simple and consistent. The SDK would require wrapping async calls in `asyncio.run()`.

**Primary recommendation:** Use `subprocess.Popen` with `claude -p --output-format json --max-turns 1 --no-session-persistence` for the simplest, most reliable integration. Disable all tools since this is pure text analysis. Parse the JSON response for the `result` field, then validate the analysis JSON within it using a Pydantic model. Reserve the SDK for future phases if richer interaction is needed.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Entity extraction scope:**
- Extract: companies/organizations, facilities, locations, and regulatory references (permit numbers, order numbers, proceeding IDs, legislation citations)
- No people entities -- companies are sufficient for user's needs
- Companies tagged with roles: applicant, intervener, regulator, contractor, etc.
- Structured relationships between entities (e.g., "Company A applied to export gas from Facility B in Location C") as a separate section in the output

**Document classification:**
- CER-specific taxonomy: Application, Order, Decision, Compliance Filing, Correspondence, Notice, Conditions Compliance, Financial Submission, Safety Report, Environmental Assessment
- Primary type + secondary tags (e.g., primary: "Application", tags: ["export", "natural-gas"])
- Confidence expressed as numeric 0-100%
- Brief justification included (1-2 sentences explaining why the classification was chosen)

**Analysis output structure:**
- Top-level JSON fields: summary (2-3 sentence plain-language overview), entities (role-tagged, with relationships), classification (primary + tags + confidence + justification), key_facts (bullet-point list of most important details)
- Storage: both JSON file (analysis.json in filing's documents folder) AND database column on the Filing record
- Prompt template: plain text with {variables} (Python .format() placeholders) -- no Jinja2 dependency
- Full analysis metadata: model used, prompt version hash, processing time, input/output token counts, timestamp

**Multi-document handling:**
- One analysis per filing (not per document) -- concatenate all document texts
- Documents clearly delimited with headers in prompt: "--- Document 1: filename.pdf (N pages) ---"
- Proceed with available documents if some failed extraction -- note missing docs in metadata
- No hard length limit -- attempt analysis regardless of size; if Claude CLI times out or errors, mark as needing Phase 7 long-document handling

### Claude's Discretion
- Exact prompt wording and structure (within the constraints above)
- CLI invocation details (subprocess management, stdin vs file piping)
- JSON schema naming conventions and nesting depth
- How to handle edge cases (empty filing text, single-page filings, non-English content)
- Prompt version hashing approach

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope
</user_constraints>

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `claude` CLI | 2.1.44+ | LLM inference via subprocess | Already installed; project requirement specifies `claude -p` |
| `subprocess` (stdlib) | Python 3.11+ | Process spawning and management | Standard library; avoids async complexity in sync codebase |
| `pydantic` | 2.x (via pydantic-settings) | JSON output schema validation | Already a dependency; provides `model_validate_json()` |
| `hashlib` (stdlib) | Python 3.11+ | Prompt version hashing (SHA-256) | Standard library; deterministic content hashing |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `json` (stdlib) | Python 3.11+ | JSON parsing/serialization | Parse CLI output, write analysis.json |
| `time` (stdlib) | Python 3.11+ | Duration measurement | `time.monotonic()` for processing time |
| `pathlib` (stdlib) | Python 3.11+ | File path manipulation | Template paths, output paths |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `subprocess.Popen` | `claude-agent-sdk` (v0.1.37) | SDK provides typed messages, structured output validation, and error classes, but requires async (`asyncio.run()`) which conflicts with sync codebase. SDK is better for multi-turn or interactive use. |
| `subprocess.Popen` | `claude-agent-sdk` + `asyncio.run()` wrapper | Adds complexity for single-turn analysis. Could revisit for Phase 7 (long-doc chunking) if multi-turn interaction is needed. |
| Python `.format()` | Jinja2 | User explicitly chose `.format()` placeholders. Jinja2 adds dependency for no benefit in this use case. |

**Installation:**
No new packages needed. All tools are already available (subprocess/json/hashlib are stdlib; pydantic is via pydantic-settings).

## Architecture Patterns

### Recommended Project Structure

```
src/cer_scraper/
    analyzer/
        __init__.py          # Filing-level analysis orchestrator (like extractor/__init__.py)
        service.py           # Core analysis service: invoke CLI, parse response
        prompt.py            # Prompt template loading, variable substitution, version hashing
        schemas.py           # Pydantic models for analysis output validation
        types.py             # Shared types (AnalysisResult dataclass)
config/
    analysis.yaml            # Analysis settings (model, timeout, template path)
    prompts/
        filing_analysis.txt  # The prompt template file
```

### Pattern 1: Subprocess Invocation (Recommended)

**What:** Invoke `claude -p` as a subprocess, pipe the prompt via stdin, capture JSON output.

**When to use:** Single-turn text analysis where the entire input fits in one prompt.

**Example:**
```python
# Source: Official CLI docs + Windows guide (verified)
import subprocess
import sys
import json

def invoke_claude(prompt_text: str, model: str, timeout: int) -> dict:
    """Invoke Claude CLI and return parsed JSON response."""
    cmd = [
        "claude", "-p",
        "--output-format", "json",
        "--model", model,
        "--max-turns", "1",
        "--no-session-persistence",
        "--tools", "",           # Disable all tools -- pure analysis
    ]

    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        creationflags=creation_flags,
    )

    stdout, stderr = proc.communicate(input=prompt_text, timeout=timeout)

    if proc.returncode != 0:
        raise RuntimeError(f"Claude CLI failed (exit {proc.returncode}): {stderr}")

    response = json.loads(stdout)
    return response
```

**CLI JSON Response Format (verified from official docs):**
```json
{
  "type": "result",
  "subtype": "success",
  "total_cost_usd": 0.0034,
  "is_error": false,
  "duration_ms": 2847,
  "duration_api_ms": 1923,
  "num_turns": 1,
  "result": "The actual analysis text here...",
  "session_id": "abc-123-def"
}
```

Key fields:
- `result`: The text response (contains the analysis JSON as a string)
- `is_error`: Whether execution failed
- `total_cost_usd`: API cost
- `duration_ms`: Total wall-clock time
- `duration_api_ms`: API response time only
- `num_turns`: Conversation turns executed
- `session_id`: Unique session identifier

### Pattern 2: Prompt via Stdin (Not File)

**What:** Pass the full prompt (system instructions + filing text) via stdin rather than command-line arguments or file piping.

**When to use:** Always. Stdin avoids command-line length limits (critical on Windows where the limit is ~8191 chars), handles special characters safely, and keeps the invocation simple.

**Why not `--system-prompt-file`:** The system prompt file would need to be generated per filing (since it includes the filing text). Using stdin for the entire prompt is simpler. The prompt template already includes instructions + filing text as one unit.

### Pattern 3: Two-Level JSON Parsing

**What:** The CLI returns a JSON envelope containing a `result` field. The `result` field itself contains the analysis JSON as a string that needs a second parse.

**When to use:** Always when using `--output-format json`.

**Example:**
```python
# Step 1: Parse CLI envelope
envelope = json.loads(stdout)
if envelope.get("is_error"):
    raise AnalysisError(envelope.get("result", "Unknown error"))

# Step 2: Parse analysis JSON from result field
raw_analysis = envelope["result"]
# Claude may wrap JSON in markdown code fences
raw_analysis = strip_code_fences(raw_analysis)
analysis = AnalysisOutput.model_validate_json(raw_analysis)
```

### Pattern 4: Pydantic Validation for Analysis Output

**What:** Define a Pydantic model matching the expected analysis schema. Use `model_validate_json()` to parse and validate Claude's response.

**When to use:** Always. Provides type safety, automatic validation, and clear error messages when the LLM output doesn't match expectations.

**Example:**
```python
from pydantic import BaseModel, Field

class EntityRef(BaseModel):
    name: str
    type: str  # "company", "facility", "location", "regulatory_reference"
    role: str | None = None  # "applicant", "intervener", "regulator", etc.

class Relationship(BaseModel):
    subject: str
    predicate: str
    object: str
    context: str | None = None

class Classification(BaseModel):
    primary_type: str
    tags: list[str] = Field(default_factory=list)
    confidence: int = Field(ge=0, le=100)
    justification: str

class AnalysisOutput(BaseModel):
    summary: str
    entities: list[EntityRef]
    relationships: list[Relationship]
    classification: Classification
    key_facts: list[str]
```

### Pattern 5: Prompt Template with .format()

**What:** Store the prompt as a plain text file with `{variable}` placeholders. Load and format at runtime.

**Example template structure:**
```text
You are an expert regulatory analyst specializing in Canadian Energy Regulator (CER) filings.

Analyze the following filing and return your analysis as a JSON object with this exact structure:
{json_schema_description}

Filing metadata:
- Filing ID: {filing_id}
- Date: {filing_date}
- Applicant: {applicant}
- Filing Type: {filing_type}

Documents ({num_documents} total, {num_missing} unavailable):

{document_text}

Return ONLY the JSON object, no other text.
```

### Pattern 6: Prompt Version Hashing

**What:** Compute SHA-256 hash of the prompt template content (before variable substitution) to track which prompt version produced each analysis.

**Example:**
```python
import hashlib

def get_prompt_version(template_path: Path) -> str:
    content = template_path.read_text(encoding="utf-8")
    return hashlib.sha256(content.encode()).hexdigest()[:12]
```

### Anti-Patterns to Avoid

- **Passing filing text via command-line argument:** Windows has an ~8191 char command-line limit. Always use stdin.
- **Using `--system-prompt` for the full prompt:** The system prompt flag is for short instructions. Long prompts via stdin are more reliable. Use `--system-prompt` only for a brief role description if separating system from user content.
- **Omitting `--tools ""` or `--max-turns 1`:** Without disabling tools, Claude Code may attempt to use Bash, Read, etc. during analysis. Without max-turns, it could enter multi-turn tool use. Both waste time and money for pure text analysis.
- **Not handling code fences in response:** Claude often wraps JSON in ```json ... ``` markdown fences even when asked not to. Always strip them.
- **Storing only analysis.json without the DB column:** The user explicitly wants BOTH file AND database storage. Missing either breaks the requirement.
- **Omitting `encoding="utf-8"` on Windows:** The default encoding on Windows may not be UTF-8, causing crashes on non-ASCII characters (common in regulatory filings with French text, accented names, etc.).
- **Using `--system-prompt` with very long text on Windows:** Per the Windows guide, complex system prompts can cause tool permissions to silently fail. Put detailed instructions in stdin instead.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JSON output validation | Custom parsing with try/except + manual field checks | Pydantic `model_validate_json()` | Handles type coercion, optional fields, nested objects, clear error messages |
| Code fence stripping | Regex for specific patterns | Simple strip function for ```json prefix/suffix | Claude's formatting varies; a simple strip handles all cases |
| Subprocess encoding on Windows | Assume defaults work | Explicit `encoding="utf-8"` + `CREATE_NEW_PROCESS_GROUP` | Windows defaults are not UTF-8; process group prevents hangs |
| Prompt template engine | Custom template parser | Python `.format()` or `.format_map()` | User decision; stdlib is sufficient for `{variable}` replacement |
| Content hashing | Custom versioning scheme | `hashlib.sha256(content).hexdigest()[:12]` | Deterministic, collision-resistant, standard |

**Key insight:** The main complexity is not in any individual component but in the robust handling of Claude's text output. The LLM may return slightly varied JSON formatting, include code fences, or occasionally produce invalid JSON. Pydantic validation + code fence stripping handles 99% of cases. The remaining 1% should be caught as analysis failures and retried.

## Common Pitfalls

### Pitfall 1: Claude CLI Cannot Run Inside Claude Code

**What goes wrong:** If the pipeline is ever run from within a Claude Code session (e.g., during development/testing), the CLI refuses to start with "Claude Code cannot be launched inside another Claude Code session."

**Why it happens:** The `CLAUDECODE` environment variable is set in Claude Code sessions, and nested sessions are blocked.

**How to avoid:** When invoking via subprocess, explicitly unset the `CLAUDECODE` environment variable in the subprocess environment:
```python
import os
env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
proc = subprocess.Popen(cmd, ..., env=env)
```

**Warning signs:** Error message about nested sessions during testing.

### Pitfall 2: JSON Inside JSON Parsing

**What goes wrong:** The CLI's `--output-format json` returns a JSON envelope where the `result` field is a string. If the prompt asks Claude to return JSON, that JSON is embedded as a string within the envelope. Naive `json.loads(stdout)["result"]` gives a string, not a dict.

**Why it happens:** Two levels of serialization: CLI envelope wraps the LLM's text response.

**How to avoid:** Always do two parse steps: (1) parse the CLI envelope, (2) parse the `result` string as JSON. Handle the case where `result` is wrapped in markdown code fences.

**Warning signs:** Getting a string where you expected a dict; `json.JSONDecodeError` on the `result` field.

### Pitfall 3: Windows Process Hanging

**What goes wrong:** On Windows, subprocess.Popen without `CREATE_NEW_PROCESS_GROUP` can hang indefinitely, especially if the child process spawns grandchild processes.

**Why it happens:** Windows process tree management differs from Unix. Without the creation flag, signal handling and process cleanup behave unexpectedly.

**How to avoid:** Always set `creationflags=subprocess.CREATE_NEW_PROCESS_GROUP` on Windows (guarded by `sys.platform == "win32"`).

**Warning signs:** Pipeline hangs after Claude CLI invocation; no timeout error despite timeout parameter.

### Pitfall 4: Timeout Not Killing Process

**What goes wrong:** `proc.communicate(timeout=N)` raises `TimeoutExpired` but does NOT kill the process. The Claude CLI process continues running in the background, consuming resources and API credits.

**Why it happens:** Python's `communicate(timeout=...)` only stops waiting; it doesn't terminate the process.

**How to avoid:**
```python
try:
    stdout, stderr = proc.communicate(input=prompt_text, timeout=timeout)
except subprocess.TimeoutExpired:
    proc.kill()
    proc.communicate()  # Clean up pipes
    raise AnalysisTimeoutError(f"Analysis timed out after {timeout}s")
```

**Warning signs:** Multiple `claude` processes visible in task manager; unexpected API charges.

### Pitfall 5: Missing UTF-8 Encoding on Windows

**What goes wrong:** Non-ASCII characters in filing text (French names, accented characters, special regulatory symbols) cause encoding errors or garbled output.

**Why it happens:** Windows default encoding is often `cp1252` or `mbcs`, not UTF-8. The CER deals with bilingual (English/French) content.

**How to avoid:** Always specify `encoding="utf-8"` in `subprocess.Popen()` and `text=True`.

**Warning signs:** `UnicodeEncodeError`, garbled characters in analysis output, failures on French-language filings.

### Pitfall 6: Empty or Minimal Filing Text

**What goes wrong:** A filing with no successfully extracted documents or very short text produces a meaningless analysis that still "succeeds."

**Why it happens:** Claude will analyze whatever text it receives, even if it's just headers or boilerplate.

**How to avoid:** Check total text length before invoking Claude. If combined document text is below a minimum threshold (e.g., < 100 chars of meaningful content), skip analysis and mark as "insufficient_text" rather than wasting an API call.

**Warning signs:** Analysis outputs with generic summaries like "This filing contains limited information."

### Pitfall 7: Tool Permissions on Windows

**What goes wrong:** If `--tools` and `--allowedTools` are not both specified and consistent, Claude Code may fail with cryptic errors or attempt to use tools.

**Why it happens:** Per the Windows guide, using only `--tools` without matching `--allowedTools` can cause permission errors.

**How to avoid:** For pure analysis with no tools: use `--tools ""` to disable all tools. This makes `--allowedTools` irrelevant since no tools are available.

**Warning signs:** Unexpected tool use in analysis output; permission-related error messages.

## Code Examples

### Complete Analysis Service

```python
# Source: Synthesized from CLI reference docs + Windows subprocess guide
import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

@dataclass
class AnalysisResult:
    """Result of analyzing a single filing."""
    success: bool
    analysis_json: dict | None = None
    raw_response: str = ""
    model: str = ""
    prompt_version: str = ""
    processing_time_seconds: float = 0.0
    cost_usd: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    error: str | None = None
    needs_chunking: bool = False  # Flag for Phase 7

def invoke_claude_cli(
    prompt_text: str,
    model: str = "sonnet",
    timeout: int = 300,
) -> dict:
    """Invoke Claude CLI as subprocess and return parsed JSON envelope."""
    cmd = [
        "claude", "-p",
        "--output-format", "json",
        "--model", model,
        "--max-turns", "1",
        "--no-session-persistence",
        "--tools", "",
    ]

    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP

    # Remove CLAUDECODE env var to prevent nested session error
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        creationflags=creation_flags,
        env=env,
    )

    try:
        stdout, stderr = proc.communicate(input=prompt_text, timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()  # Clean up
        raise

    if proc.returncode != 0:
        raise RuntimeError(
            f"Claude CLI exited with code {proc.returncode}: {stderr.strip()}"
        )

    return json.loads(stdout)
```

### Code Fence Stripping

```python
import re

_CODE_FENCE_RE = re.compile(
    r"^\s*```(?:json)?\s*\n?(.*?)\n?\s*```\s*$",
    re.DOTALL,
)

def strip_code_fences(text: str) -> str:
    """Remove markdown code fences wrapping JSON output."""
    text = text.strip()
    match = _CODE_FENCE_RE.match(text)
    if match:
        return match.group(1).strip()
    return text
```

### Prompt Template Loading

```python
import hashlib
from pathlib import Path

def load_prompt_template(template_path: Path) -> tuple[str, str]:
    """Load prompt template and compute version hash.

    Returns:
        Tuple of (template_content, version_hash).
    """
    content = template_path.read_text(encoding="utf-8")
    version = hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]
    return content, version

def build_prompt(
    template: str,
    filing_id: str,
    filing_date: str,
    applicant: str,
    filing_type: str,
    document_text: str,
    num_documents: int,
    num_missing: int,
    json_schema_description: str,
) -> str:
    """Build the analysis prompt from template and filing data."""
    return template.format(
        filing_id=filing_id,
        filing_date=filing_date or "Unknown",
        applicant=applicant or "Unknown",
        filing_type=filing_type or "Unknown",
        document_text=document_text,
        num_documents=num_documents,
        num_missing=num_missing,
        json_schema_description=json_schema_description,
    )
```

### Filing Text Assembly

```python
def assemble_filing_text(
    documents: list,  # list of Document ORM objects
) -> tuple[str, int, int]:
    """Concatenate extracted document texts with delimiters.

    Returns:
        Tuple of (combined_text, num_included, num_missing).
    """
    parts = []
    included = 0
    missing = 0

    for idx, doc in enumerate(documents, start=1):
        if doc.extraction_status == "success" and doc.extracted_text:
            header = (
                f"--- Document {idx}: {doc.filename or 'unknown.pdf'} "
                f"({doc.page_count or '?'} pages) ---"
            )
            parts.append(f"{header}\n\n{doc.extracted_text}")
            included += 1
        else:
            missing += 1

    combined = "\n\n".join(parts)
    return combined, included, missing
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Raw subprocess only | `claude-agent-sdk` Python package available | Feb 2026 (v0.1.37) | Provides typed messages, structured output validation, async API. Not needed for single-turn sync use. |
| `--output-format text` | `--output-format json` with envelope metadata | Available since CLI 1.x | Get cost, duration, token counts in structured response |
| Custom JSON enforcement | `--json-schema` CLI flag | Late 2025 / early 2026 | Schema-validated output from CLI directly. Status: documented in SDK docs, may need verification for raw CLI. |
| No session persistence control | `--no-session-persistence` flag | CLI 2.x | Prevents session saving, reduces disk I/O and cleanup needs |

**Current best practice (as of Feb 2026):**
- Use `--output-format json` for metadata + parseable response
- Use `--max-turns 1` for single-turn analysis
- Use `--no-session-persistence` to avoid session file clutter
- Use `--tools ""` to disable tool use for pure text analysis
- Pipe prompt via stdin for Windows compatibility and large inputs

## Open Questions

1. **`--json-schema` flag availability in raw CLI**
   - What we know: The flag is documented in the CLI reference table and works via the SDK's `output_format` option.
   - What's unclear: Whether `--json-schema` works reliably with the raw CLI `claude -p` (not via the SDK). The CLI reference lists it but the SDK docs focus on the SDK usage.
   - Recommendation: Start with prompt-based JSON + Pydantic validation (proven reliable). The `--json-schema` flag can be tested during implementation and adopted if it works, providing an additional validation layer. LOW confidence on this flag working identically to SDK structured outputs.

2. **`--tools ""` (empty string) behavior**
   - What we know: The CLI docs say `--tools ""` disables all tools. Could not test directly (nested session restriction).
   - What's unclear: Whether empty string fully prevents tool use or if `--max-turns 1` alone is sufficient.
   - Recommendation: Use both `--tools ""` AND `--max-turns 1` as defense in depth. If `--tools ""` causes issues, fall back to `--max-turns 1` alone. MEDIUM confidence.

3. **Token count availability in JSON response**
   - What we know: The JSON envelope includes `duration_ms`, `duration_api_ms`, `total_cost_usd`, and `num_turns`. The SDK `ResultMessage` has a `usage` field.
   - What's unclear: Whether the raw CLI JSON envelope includes a `usage` object with `input_tokens` / `output_tokens` counts.
   - Recommendation: Parse `usage` if present, fall back to `None` if absent. The user wants token counts in metadata but they are not critical. MEDIUM confidence on availability.

4. **Model string for `--model` flag**
   - What we know: Accepts aliases like `sonnet` and `opus`, or full model IDs like `claude-sonnet-4-5-20250929`.
   - What's unclear: Which specific model the user prefers for analysis (cost vs quality tradeoff).
   - Recommendation: Default to `"sonnet"` in config (good balance of quality/cost/speed). Make it configurable via `analysis.yaml`. HIGH confidence on approach.

## Sources

### Primary (HIGH confidence)
- [CLI reference - Claude Code Docs](https://code.claude.com/docs/en/cli-reference) - All CLI flags, output format options, JSON response structure
- [Agent SDK Python reference](https://platform.claude.com/docs/en/agent-sdk/python) - `ClaudeAgentOptions`, `ResultMessage` fields, `OutputFormat` type
- [Structured outputs - Agent SDK](https://platform.claude.com/docs/en/agent-sdk/structured-outputs) - JSON Schema validation for structured output
- [Claude Code CLI guide - Blake Crosley](https://blakecrosley.com/en/guides/claude-code) - JSON envelope field reference (type, subtype, total_cost_usd, duration_ms, etc.)

### Secondary (MEDIUM confidence)
- [Running Claude Code from Windows CLI](https://dstreefkerk.github.io/2026-01-running-claude-code-from-windows-cli/) - Windows subprocess pattern, CREATE_NEW_PROCESS_GROUP, encoding issues, tool permission dual-flag requirement
- [claude-agent-sdk on PyPI](https://pypi.org/project/claude-agent-sdk/) - v0.1.37, Python >=3.10, installation method
- [Structured JSON outputs issue #180](https://github.com/anthropics/claude-agent-sdk-python/issues/180) - Confirmation that structured outputs are now supported

### Tertiary (LOW confidence)
- `--json-schema` raw CLI behavior (documented but not verified via testing due to nested session restriction)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Uses stdlib (subprocess, json, hashlib) + existing dependency (pydantic). No new packages.
- Architecture: HIGH - Follows established project patterns (extractor module structure, service/orchestrator/types pattern, YAML config).
- CLI invocation: HIGH - Verified from official docs and multiple guides. JSON response format confirmed.
- Pitfalls: HIGH - Windows subprocess issues well-documented; nested session restriction confirmed by direct testing.
- Prompt design: MEDIUM - Follows established LLM prompt patterns but template wording is Claude's discretion and will need iteration.
- Token counts in response: MEDIUM - Documented in SDK but unverified for raw CLI JSON output.

**Research date:** 2026-02-16
**Valid until:** 2026-03-16 (CLI is fast-moving; check for new flags/options monthly)
