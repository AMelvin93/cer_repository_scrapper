# Phase 1: Foundation & Configuration - Context

**Gathered:** 2026-02-05
**Status:** Ready for planning

<domain>
## Phase Boundary

State tracking, logging, and configuration infrastructure for the CER REGDOCS scraper pipeline. This phase delivers the data model (Filing, Document, Analysis tables), persistent state store (SQLite), structured logging, and externalized configuration. No scraping, downloading, or analysis logic -- just the foundation that all downstream phases build on.

</domain>

<decisions>
## Implementation Decisions

### Configuration layout
- YAML format for config files
- Split into separate files per concern (scraper.yaml, email.yaml, etc.) inside a `config/` directory
- Secrets (Gmail app password, etc.) live exclusively in `.env` -- config files never contain or reference secrets
- Config files handle settings (URLs, delays, paths); `.env` handles credentials

### State tracking schema
- Per-step status tracking: each pipeline stage (scraped, downloaded, extracted, analyzed, emailed) tracked independently per filing
- Failure recording includes status, error message, and retry count -- enables smart retry logic (e.g., skip after N failures)
- Run history with timestamps preserved -- enables auditing when things were processed and how long they took
- SQLite database at `data/state.db`

### Logging behavior
- Logs go to both rotating files and console (stdout)
- Log files stored in top-level `logs/` directory

### Claude's Discretion
- Log format (structured JSON vs human-readable text)
- Log rotation policy (size-based vs time-based, retention count)
- Exact log level configuration per component

### Filing data model
- SQLAlchemy ORM for data access (declarative models, query builder)
- Normalized schema: separate `filings`, `documents`, and `analyses` tables with foreign keys
- `filings` table: filing ID, date, applicant, type, proceeding number, and metadata from REGDOCS
- `documents` table: linked to filings, tracks individual PDF URLs and download status
- `analyses` table: linked to filings, stores analysis output separately from raw filing data
- Migration approach at Claude's discretion (Alembic vs create_all)

</decisions>

<specifics>
## Specific Ideas

No specific requirements -- open to standard approaches. The user wants clean separation of concerns: config in `config/`, secrets in `.env`, data in `data/`, logs in `logs/`.

</specifics>

<deferred>
## Deferred Ideas

None -- discussion stayed within phase scope.

</deferred>

---

*Phase: 01-foundation-configuration*
*Context gathered: 2026-02-05*
