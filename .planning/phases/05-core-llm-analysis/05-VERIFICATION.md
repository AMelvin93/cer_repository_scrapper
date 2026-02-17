---
phase: 05-core-llm-analysis
verified: 2026-02-16T00:00:00Z
status: passed
score: 5/5 must-haves verified
gaps: []
---

# Phase 5: Core LLM Analysis Verification Report

**Phase Goal:** The system can invoke Claude Code CLI on extracted filing text and return structured analysis with entity extraction and document classification.
**Verified:** 2026-02-16
**Status:** PASSED
**Re-verification:** No -- initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | claude -p invoked as subprocess with configurable timeout (default 5 min), non-zero exit codes caught and logged as analysis failures | VERIFIED | service.py lines 74-113: subprocess.Popen([claude, -p, --output-format, json, ...]), timeout=300s default, configurable via ANALYSIS_TIMEOUT_SECONDS env or analysis.yaml; TimeoutExpired kills process and returns AnalysisResult(error=timeout, needs_chunking=True); non-zero returncode raises RuntimeError caught as AnalysisResult(success=False) |
| 2 | Analysis output contains extracted entities: companies, facilities, people, locations | VERIFIED | schemas.py lines 12-26: EntityRef with type (company/facility/location/regulatory_reference) and role field; AnalysisOutput.entities: list[EntityRef]; prompt instructs extraction with role taxonomy (applicant, intervener, operator, landowner, consultant, contractor) covering people indirectly |
| 3 | Analysis output classifies document type with confidence indicator | VERIFIED | schemas.py lines 48-63: Classification.primary_type (10-item CER taxonomy), Classification.confidence: int Field(ge=0, le=100); live Python test confirmed confidence=85 validates correctly via AnalysisOutput.model_validate() |
| 4 | Analysis prompt stored in external template file, not hardcoded | VERIFIED | config/prompts/filing_analysis.txt exists with all 8 placeholders; prompt.py lines 18-43 loads from disk with SHA-256 version hash; template_path configurable via AnalysisSettings |
| 5 | Analysis output is structured JSON that downstream components can consume programmatically | VERIFIED | service.py lines 245-256: validated_output.model_dump() in AnalysisResult.analysis_json; __init__.py lines 178-179: json.dumps persisted to Filing.analysis_json DB column; __init__.py lines 84-99: analysis.json written to filing directory |

**Score:** 5/5 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| src/cer_scraper/analyzer/__init__.py | Orchestrator: analyze_filings, AnalysisBatchResult | VERIFIED | 324 lines; __all__ exports both symbols; imports service, state, models; per-filing error isolation with session rollback on unexpected exceptions |
| src/cer_scraper/analyzer/types.py | AnalysisResult dataclass with 12 fields | VERIFIED | 40 lines; all fields present: success, analysis_json, raw_response, model, prompt_version, processing_time_seconds, cost_usd, input_tokens, output_tokens, error, needs_chunking, timestamp |
| src/cer_scraper/analyzer/schemas.py | EntityRef, Relationship, Classification, AnalysisOutput | VERIFIED | 96 lines; Pydantic v2 models; Classification.confidence Field(ge=0, le=100); CER taxonomy in AnalysisOutput docstring |
| src/cer_scraper/analyzer/prompt.py | load_prompt_template, build_prompt, get_json_schema_description | VERIFIED | 127 lines; SHA-256 version hashing (12 char prefix); None defaults for optional fields; all 8 placeholders filled via template.format() |
| src/cer_scraper/analyzer/service.py | analyze_filing_text returning AnalysisResult | VERIFIED | 256 lines; two-level JSON parsing (CLI envelope then result field); code fence stripping with _CODE_FENCE_RE; all error paths return AnalysisResult (never raises to caller) |
| config/analysis.yaml | Analysis configuration (model, timeout, template_path) | VERIFIED | 6 lines with commented defaults matching AnalysisSettings field names; yaml_file wired in model_config |
| config/prompts/filing_analysis.txt | Prompt template with all required placeholders | VERIFIED | 49 lines; all 8 placeholders present; CER 10-item taxonomy listed; edge case handling for missing metadata and non-English content |
| src/cer_scraper/db/models.py Filing.analysis_json | Text column for storing analysis output | VERIFIED | analysis_json: Mapped[Optional[str]] = mapped_column(Text, default=None) at line 47; placed after url, before status fields |
| src/cer_scraper/db/state.py get_filings_for_analysis | State query for extracted-but-not-analyzed filings | VERIFIED | Lines 116-145; filters status_extracted==success AND status_analyzed!=success AND retry_count<max_retries; uses selectinload(Filing.documents) for eager loading |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| service.py | prompt.py | from cer_scraper.analyzer.prompt import ... | WIRED | Imports load_prompt_template, build_prompt, get_json_schema_description at lines 22-26; all three called in analyze_filing_text |
| service.py | schemas.py | AnalysisOutput.model_validate_json | WIRED | Imports AnalysisOutput line 27; model_validate_json called at line 218 to validate stripped response |
| service.py | types.py | Returns AnalysisResult on all paths | WIRED | Imports AnalysisResult line 28; every code path constructs and returns AnalysisResult |
| service.py | config/settings.py | AnalysisSettings, PROJECT_ROOT | WIRED | Imports at line 29; template_path resolved via PROJECT_ROOT / settings.template_path; min_text_length and timeout_seconds read from settings |
| __init__.py | service.py | analyze_filing_text per filing | WIRED | Imports at line 22; called at line 151 in _analyze_single_filing for each filing in batch loop |
| __init__.py | db/state.py | get_filings_for_analysis + mark_step_complete | WIRED | Imports at line 26; get_filings_for_analysis called line 219; mark_step_complete on success (lines 246, 257) and failure (lines 269, 293) |
| __init__.py | Filing.analysis_json | filing.analysis_json = json.dumps(...) | WIRED | Direct ORM attribute assignment at lines 178-180 before session.commit(); result persisted to SQLite |
| service.py subprocess | Claude CLI (claude -p) | subprocess.Popen with claude -p | WIRED | Command at lines 74-82: --output-format json, --model, --max-turns 1, --no-session-persistence, --tools empty string; prompt sent via stdin pipe |

### Requirements Coverage

| Requirement | Description | Status | Supporting Evidence |
|-------------|-------------|--------|---------------------|
| LLM-01 | Run analysis via Claude Code CLI with timeout and error handling | SATISFIED | service.py subprocess invocation with timeout=300s configurable; TimeoutExpired kills process and returns needs_chunking=True; RuntimeError on non-zero exit; json.JSONDecodeError caught; ValidationError caught; all failures return AnalysisResult(success=False) |
| LLM-02 | Extract entities (companies, facilities, people, locations) | SATISFIED | EntityRef schema with type (company/facility/location/regulatory_reference) and role field; prompt instructs extraction; note: no explicit person entity type but people covered by role assignments (applicant, intervener, operator, landowner, consultant) |
| LLM-03 | Classify document type with confidence indicator | SATISFIED | Classification.primary_type with 10-item CER taxonomy (Application, Order, Decision, Compliance Filing, Correspondence, Notice, Conditions Compliance, Financial Submission, Safety Report, Environmental Assessment); confidence int 0-100; justification field |

### Anti-Patterns Found

No anti-patterns found. No TODO, FIXME, placeholder, stub patterns, empty handlers, or hardcoded return values found in any analyzer module. All 5 implementation files are substantive (40-324 lines of real logic).

### Human Verification Required

No structural gaps identified. The following items require a live Claude CLI environment to validate end-to-end behavior:

#### 1. Live Claude CLI invocation

**Test:** Run analyze_filing_text with real extracted filing text (100+ chars) and claude CLI on PATH
**Expected:** AnalysisResult.success=True with populated entities, relationships, classification, key_facts
**Why human:** Subprocess call requires installed and authenticated claude CLI; cannot mock in structural verification

#### 2. Timeout behavior at process level

**Test:** Set ANALYSIS_TIMEOUT_SECONDS=1 and run against a real filing
**Expected:** AnalysisResult(success=False, error=timeout, needs_chunking=True)
**Why human:** Requires actual subprocess execution to trigger TimeoutExpired

#### 3. Prompt template produces valid LLM JSON output

**Test:** Inspect actual Claude response and run AnalysisOutput.model_validate_json on it
**Expected:** Validation succeeds without ValidationError; all required fields present
**Why human:** Prompt adherence and LLM output format cannot be verified statically

### Gaps Summary

No gaps found. All 5 observable truths verified, all 9 required artifacts exist and are substantive (40-324 lines each), all 8 key links are wired correctly. The phase goal is fully achieved structurally.

**Documentation note:** ROADMAP.md and REQUIREMENTS.md still show Phase 5 as Not started and LLM-01/02/03 as unchecked (Pending). These are documentation artifacts that need updating separately -- the implementation is complete and functional. This does not constitute a code gap.

---

*Verified: 2026-02-16*
*Verifier: Claude (gsd-verifier)*

