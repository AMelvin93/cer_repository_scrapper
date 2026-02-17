# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-05)

**Core value:** Every CER filing gets captured, analyzed in depth, and delivered to the user's inbox -- no filings slip through the cracks.
**Current focus:** Phase 6 - Deep Analysis Features (In progress)

## Current Position

Phase: 6 of 10 (Deep Analysis Features)
Plan: 1 of 2 in current phase
Status: In progress
Last activity: 2026-02-17 -- Completed 06-01-PLAN.md (schema extension and prompt infrastructure)

Progress: [█████] 1/2 Phase 6 plans
Overall:  [████████████████] 16/17 known plans complete (Phases 1-5 done, Phase 6 in progress)

## Performance Metrics

**Velocity:**
- Total plans completed: 16
- Average duration: 2.8 min
- Total execution time: 45.3 min

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-foundation-configuration | 4/4 | 10.4 min | 2.6 min |
| 02-regdocs-scraper | 3/3 | 12.4 min | 4.1 min |
| 03-pdf-download-storage | 2/2 | 4.2 min | 2.1 min |
| 04-pdf-text-extraction | 3/3 | 8.6 min | 2.9 min |
| 05-core-llm-analysis | 3/3 | 7.5 min | 2.5 min |
| 06-deep-analysis-features | 1/2 | 2.2 min | 2.2 min |

**Recent Trend:**
- Last 5 plans: 05-01 (3.2 min), 05-02 (2.2 min), 05-03 (2.1 min), 06-01 (2.2 min)
- Trend: Consistent sub-3-min execution for well-structured plans

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Roadmap]: 10 phases derived from 24 requirements at comprehensive depth
- [Roadmap]: Phase 8 (Email) depends on Phase 6, not Phase 7 -- long document handling enhances but does not block email delivery
- [01-01]: Used hatchling as build backend for clean src-layout support
- [01-01]: pydantic-settings[yaml] extra pulls in PyYAML as transitive dependency for Plan 02 config
- [01-02]: pydantic-settings 2.12.0 requires explicit settings_customise_sources hook for YAML source activation
- [01-02]: All config paths resolved to absolute via PROJECT_ROOT to prevent CWD-dependent failures
- [01-02]: Source priority: env vars > .env > YAML > defaults
- [01-03]: Used Base.metadata.create_all() instead of Alembic -- fresh project with no production data
- [01-03]: Resolved db_path to absolute path in get_engine() to avoid SQLite relative path issues
- [01-03]: Cleared existing handlers in setup_logging() to prevent duplicate output on re-initialization
- [01-04]: State unprocessed filter: status_emailed != success AND retry_count < max_retries
- [01-04]: Startup order: pipeline config -> logging -> remaining config -> database -> report
- [01-04]: All state mutations call session.commit() explicitly (SQLAlchemy does not auto-commit)
- [02-01]: ScrapedFiling uses field_validator to reject empty filing_id
- [02-01]: robots.txt missing/unreadable = allow scraping (standard practice)
- [02-01]: Rate limiter logs at DEBUG level to avoid noise in normal operation
- [02-01]: ScrapedDocument.content_type is Optional (MIME type not always available)
- [02-02]: DiscoveredEndpoint is a dataclass (not Pydantic) -- carries raw API bodies
- [02-02]: Filing heuristic uses key overlap (>=2 matching keys) plus URL pattern matching
- [02-02]: API client uses case-insensitive alias tables for resilient JSON field extraction
- [02-02]: datetime.date fully qualified in models.py to avoid Pydantic v2 field-name shadowing bug
- [02-03]: DOM parser uses 3 strategies (table, link, data-attribute) merged with dedup by filing_id
- [02-03]: ScrapeResult is a dataclass (not Pydantic) -- internal orchestrator output
- [02-03]: None/empty filing_type passes through type filters (for later LLM classification)
- [02-03]: Applicant filter uses case-insensitive substring matching; proceeding filter uses exact match
- [02-03]: Missing applicant/filing_type stored as "Unknown" placeholder
- [02-03]: Individual filing persistence failures don't crash batch (rollback + continue)
- [03-01]: Content-Type check rejects text/html but allows missing/ambiguous types
- [03-01]: Size limit enforced at two points: Content-Length header pre-check and streaming byte count
- [03-01]: tenacity retries only httpx.HTTPStatusError and TransportError (not all exceptions)
- [03-01]: .tmp file cleanup in finally block ensures no corrupt partial files remain on disk
- [03-02]: All-or-nothing download semantics: if any document fails, entire filing directory cleaned up
- [03-02]: Per-filing error isolation: one failure does not block other filings
- [03-02]: Rate limiter reused between PDF downloads within a filing
- [03-02]: Filing directory convention: {YYYY-MM-DD}_Filing-{id}/documents/doc_NNN.pdf
- [03-02]: Each filing committed independently to avoid long-running transactions
- [04-01]: ExtractionSettings follows same pattern as other settings classes: YAML + env var overrides with settings_customise_sources hook
- [04-01]: Document extraction columns (extraction_status/method/error, extracted_text, char_count, page_count) placed after content_type
- [04-01]: get_filings_for_extraction mirrors get_filings_for_download pattern with selectinload for eager document loading
- [04-02]: ExtractionResult/ExtractionMethod in types.py (not service.py) to avoid circular imports between extractor modules
- [04-02]: pymupdf4llm v0.2.9 has no use_ocr/ocr_language params; uses built-in per-page OCR detection automatically
- [04-02]: Repetition threshold set to 200 (not 50) -- common English trigrams exceed 50 per 10K chars in regulatory text
- [04-02]: pymupdf.layout module does not exist in pymupdf 1.26.7 -- pymupdf4llm works without it
- [04-02]: pytesseract added as dependency; Tesseract OCR binary must be installed separately on the system
- [04-03]: Individual document failures do not fail the filing (unlike downloader's all-or-nothing)
- [04-03]: Filing marked success if at least one document extracted
- [04-03]: max_retries hardcoded to 3 in orchestrator (matches PipelineSettings default)
- [04-03]: Filings with no documents treated as success (vacuous truth)
- [05-01]: AnalysisResult uses dataclass (not Pydantic) matching ExtractionResult pattern
- [05-01]: Prompt template uses double braces for literal JSON in .format() placeholders
- [05-01]: analysis_json column placed after url and before status fields in Filing model
- [05-01]: EntityRef.role is Optional (None if role cannot be determined from text)
- [05-02]: Prompt version hash uses first 12 hex chars of SHA-256 for compact traceability
- [05-02]: get_json_schema_description returns human-readable JSON example, not formal JSON Schema
- [05-02]: Code fence regex uses re.DOTALL for multiline matching
- [05-02]: Timeout returns needs_chunking=True to signal Phase 7
- [05-02]: analyze_filing_text never raises -- all error paths return AnalysisResult(success=False)
- [05-03]: Disk write failure on analysis.json does not fail the analysis -- database is authoritative store
- [05-03]: Filing directory resolved from first document's local_path parent
- [05-03]: insufficient_text treated as skip (vacuous success), not failure
- [05-03]: Cost accumulated from AnalysisResult.cost_usd into AnalysisBatchResult.total_cost_usd
- [06-01]: ExtractedDate.date uses str not datetime.date (CER filings have non-ISO temporal references)
- [06-01]: regulatory_implications is the only conditionally-null field (None for routine filings)
- [06-01]: All Phase 6 fields default to None/empty for backward compat with Phase 5 data

### Pending Todos

None.

### Blockers/Concerns

None.

## Session Continuity

Last session: 2026-02-17
Stopped at: Completed 06-01-PLAN.md (schema extension and prompt infrastructure)
Resume file: None
