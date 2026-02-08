# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-05)

**Core value:** Every CER filing gets captured, analyzed in depth, and delivered to the user's inbox -- no filings slip through the cracks.
**Current focus:** Phase 3 - PDF Download & Storage (COMPLETE)

## Current Position

Phase: 3 of 10 (PDF Download & Storage)
Plan: 2 of 2 in current phase COMPLETE
Status: Phase complete
Last activity: 2026-02-08 -- Completed 03-02-PLAN.md (filing-level download orchestrator)

Progress: [██████████] 2/2 Phase 3 plans
Overall:  [█████████░] 9/9 known plans complete (Phases 1-3 done)

## Performance Metrics

**Velocity:**
- Total plans completed: 9
- Average duration: 3.0 min
- Total execution time: 27.0 min

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-foundation-configuration | 4/4 | 10.4 min | 2.6 min |
| 02-regdocs-scraper | 3/3 | 12.4 min | 4.1 min |
| 03-pdf-download-storage | 2/2 | 4.2 min | 2.1 min |

**Recent Trend:**
- Last 5 plans: 02-02 (5.9 min), 02-03 (4.1 min), 03-01 (2.1 min), 03-02 (2.1 min)
- Trend: Phase 3 completed quickly (both plans ~2 min each)

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

### Pending Todos

None.

### Blockers/Concerns

- [Phase 5]: Claude CLI subprocess invocation details underdocumented -- needs prototyping early in Phase 5

## Session Continuity

Last session: 2026-02-08
Stopped at: Completed 03-02-PLAN.md (filing-level download orchestrator) -- Phase 3 COMPLETE
Resume file: None
