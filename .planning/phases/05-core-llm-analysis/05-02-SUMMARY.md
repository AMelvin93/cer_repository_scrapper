---
phase: 05-core-llm-analysis
plan: 02
subsystem: analyzer
tags: [claude-cli, subprocess, prompt-template, json-parsing, llm]

# Dependency graph
requires:
  - phase: 05-core-llm-analysis
    provides: AnalysisResult dataclass, AnalysisOutput Pydantic schema, AnalysisSettings config, prompt template
  - phase: 01-foundation-configuration
    provides: PROJECT_ROOT, settings pattern
provides:
  - load_prompt_template with SHA-256 version hashing
  - get_json_schema_description matching AnalysisOutput schema
  - build_prompt with all placeholder filling and None defaults
  - analyze_filing_text with Claude CLI subprocess invocation
  - Two-level JSON parsing (CLI envelope then analysis JSON)
  - Code fence stripping for LLM response cleanup
affects: [05-03, 07-long-documents]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Claude CLI invoked as subprocess with --output-format json, --max-turns 1, --tools empty, --no-session-persistence"
    - "CLAUDECODE env var stripped from subprocess environment to prevent nested sessions"
    - "Windows CREATE_NEW_PROCESS_GROUP flag for clean process management"
    - "Two-level JSON parsing: CLI envelope.result -> strip code fences -> model_validate_json"
    - "Prompt template SHA-256 version hash for analysis traceability"

key-files:
  created:
    - src/cer_scraper/analyzer/prompt.py
    - src/cer_scraper/analyzer/service.py
  modified: []

key-decisions:
  - "Prompt version hash uses first 12 hex chars of SHA-256 -- sufficient uniqueness, compact for storage"
  - "get_json_schema_description returns human-readable JSON example with inline comments, not formal JSON Schema -- optimized for LLM consumption"
  - "Code fence regex uses re.DOTALL for multiline matching of fenced JSON blocks"
  - "Timeout returns needs_chunking=True to signal Phase 7 long-document handling"

patterns-established:
  - "strip_code_fences as reusable utility for LLM response cleanup"
  - "analyze_filing_text returns AnalysisResult on all paths (never raises) -- caller always gets structured result"

# Metrics
duration: 2.2min
completed: 2026-02-17
---

# Phase 5 Plan 02: Core Analysis Service Summary

**Prompt template management with SHA-256 versioning and Claude CLI subprocess invocation with two-level JSON envelope parsing, code fence stripping, and full metadata extraction**

## Performance

- **Duration:** 2.2 min
- **Started:** 2026-02-17T02:54:11Z
- **Completed:** 2026-02-17T02:56:25Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Prompt template loads from disk with SHA-256 version hash for traceability across analysis runs
- Human-readable JSON schema description matches AnalysisOutput Pydantic model fields exactly (entities, relationships, classification, key_facts)
- Claude CLI invoked as subprocess with all required flags for single-turn JSON analysis
- Two-level JSON parsing correctly handles CLI envelope wrapping analysis JSON inside result field
- Code fences stripped before JSON validation to handle LLM formatting variations
- Full error handling: timeout kills process (returns needs_chunking), non-zero exit raises RuntimeError, invalid JSON caught, validation errors caught
- AnalysisResult returned on all code paths with full metadata (model, prompt version, processing time, cost, tokens, timestamp)

## Task Commits

Each task was committed atomically:

1. **Task 1: Prompt template management** - `f844000` (feat)
2. **Task 2: Claude CLI invocation service** - `e063c30` (feat)

## Files Created/Modified
- `src/cer_scraper/analyzer/prompt.py` - load_prompt_template, build_prompt, get_json_schema_description functions
- `src/cer_scraper/analyzer/service.py` - analyze_filing_text, strip_code_fences, _invoke_claude_cli functions

## Decisions Made
- Prompt version hash uses first 12 hex chars of SHA-256 -- sufficient uniqueness, compact for database storage
- get_json_schema_description returns human-readable JSON example with comments rather than formal JSON Schema spec -- LLMs respond better to examples than specifications
- Code fence regex uses re.DOTALL for multiline matching of ```json ... ``` blocks
- Timeout returns needs_chunking=True to signal Phase 7 that the document may be too long for single-pass analysis
- analyze_filing_text never raises exceptions -- all error paths return AnalysisResult(success=False, error=...) for uniform caller handling

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required. Claude CLI must be available on PATH (prerequisite for Phase 5).

## Next Phase Readiness
- prompt.py and service.py ready for Plan 03 orchestrator to call analyze_filing_text per filing
- AnalysisResult contains all metadata fields needed for database persistence
- Prompt versioning enables tracking which template version produced each analysis
- needs_chunking flag ready for Phase 7 long-document handling integration

## Self-Check: PASSED

---
*Phase: 05-core-llm-analysis*
*Completed: 2026-02-17*
