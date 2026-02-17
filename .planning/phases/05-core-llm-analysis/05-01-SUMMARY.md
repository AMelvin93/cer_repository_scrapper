---
phase: 05-core-llm-analysis
plan: 01
subsystem: analyzer
tags: [pydantic, schemas, llm, claude-cli, prompt-template, sqlalchemy]

# Dependency graph
requires:
  - phase: 04-pdf-text-extraction
    provides: Filing.status_extracted, Document.extracted_text columns
  - phase: 01-foundation-configuration
    provides: Settings pattern (YAML + env var), state query pattern, Filing model
provides:
  - AnalysisResult dataclass with full metadata fields
  - Pydantic schemas (AnalysisOutput, EntityRef, Relationship, Classification) for validating LLM JSON output
  - AnalysisSettings config class with YAML + ANALYSIS_ env prefix
  - Prompt template with all required placeholders for filing analysis
  - Filing.analysis_json column for storing analysis output
  - get_filings_for_analysis state query
affects: [05-02, 05-03, 06-deep-analysis, 07-long-documents, 08-email-delivery]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "analyzer/ package follows extractor/ structure (types.py, schemas.py, __init__.py)"
    - "AnalysisSettings follows established settings_customise_sources hook pattern"
    - "get_filings_for_analysis follows get_filings_for_extraction pattern with selectinload"
    - "Prompt template uses Python .format() placeholders (no Jinja2)"

key-files:
  created:
    - src/cer_scraper/analyzer/__init__.py
    - src/cer_scraper/analyzer/types.py
    - src/cer_scraper/analyzer/schemas.py
    - config/analysis.yaml
    - config/prompts/filing_analysis.txt
  modified:
    - src/cer_scraper/config/settings.py
    - src/cer_scraper/db/models.py
    - src/cer_scraper/db/state.py

key-decisions:
  - "AnalysisResult uses dataclass (not Pydantic) matching ExtractionResult pattern -- lightweight, no validation overhead for internal type"
  - "Prompt template uses double braces for literal JSON braces in examples to avoid .format() conflicts"
  - "analysis_json column placed after url and before status fields in Filing model"

patterns-established:
  - "analyzer/ package skeleton: __init__.py (orchestrator placeholder), types.py, schemas.py"
  - "CER document taxonomy as docstring on AnalysisOutput (Application, Order, Decision, etc.)"

# Metrics
duration: 3.2min
completed: 2026-02-17
---

# Phase 5 Plan 01: Analysis Foundation Summary

**Pydantic schemas for CER filing analysis (entities, relationships, classification with confidence), AnalysisSettings config, prompt template with 8 placeholders, and get_filings_for_analysis state query**

## Performance

- **Duration:** 3.2 min
- **Started:** 2026-02-17T02:47:25Z
- **Completed:** 2026-02-17T02:50:36Z
- **Tasks:** 2
- **Files modified:** 8

## Accomplishments
- AnalysisOutput Pydantic schema validates LLM JSON with summary, entities (typed + role-tagged), relationships (subject-predicate-object), classification (confidence 0-100 with justification), and key_facts
- AnalysisSettings loads from config/analysis.yaml with ANALYSIS_ env prefix, defaults to sonnet model with 300s timeout
- Prompt template at config/prompts/filing_analysis.txt with CER-specific taxonomy and edge case handling instructions
- Filing.analysis_json Text column added to persist full analysis JSON
- get_filings_for_analysis returns extracted-but-not-analyzed filings with eagerly loaded documents

## Task Commits

Each task was committed atomically:

1. **Task 1: Analysis config, schemas, types, and prompt template** - `8ddca7f` (feat)
2. **Task 2: Filing model extension and state query for analysis** - `c6a4122` (feat)

## Files Created/Modified
- `src/cer_scraper/analyzer/__init__.py` - Package marker with module docstrings for future modules
- `src/cer_scraper/analyzer/types.py` - AnalysisResult dataclass with success, analysis_json, metadata fields
- `src/cer_scraper/analyzer/schemas.py` - EntityRef, Relationship, Classification, AnalysisOutput Pydantic models
- `src/cer_scraper/config/settings.py` - Added AnalysisSettings class (model, timeout, min_text_length, template_path)
- `config/analysis.yaml` - Commented defaults for analysis settings
- `config/prompts/filing_analysis.txt` - Prompt template with filing_id, document_text, json_schema_description, etc.
- `src/cer_scraper/db/models.py` - Added analysis_json Text column to Filing, updated docstring
- `src/cer_scraper/db/state.py` - Added get_filings_for_analysis function, updated module docstring

## Decisions Made
- AnalysisResult uses dataclass (not Pydantic) matching ExtractionResult pattern -- lightweight, no validation overhead for internal type
- Prompt template uses double braces `{{` and `}}` for literal JSON braces in example text to avoid .format() conflicts
- analysis_json column placed after url and before status fields in Filing model, matching the pattern of Phase 4 extraction columns on Document
- EntityRef.role is Optional (None if role cannot be determined from text)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- All types, schemas, and configuration ready for Plan 02 (Claude CLI service + prompt builder)
- AnalysisOutput schema provides the validation contract for LLM responses
- get_filings_for_analysis query ready for Plan 03 orchestrator
- Prompt template ready for variable substitution in prompt.py module

## Self-Check: PASSED

---
*Phase: 05-core-llm-analysis*
*Completed: 2026-02-17*
