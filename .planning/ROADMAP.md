# Roadmap: CER REGDOCS Scraper & Analyzer

## Overview

This roadmap delivers an automated pipeline that scrapes the Canada Energy Regulator's REGDOCS website, downloads and extracts text from regulatory PDFs, runs deep-dive analysis on each filing via Claude Code CLI, and delivers per-filing email reports. The phases follow the natural data flow -- foundation and state tracking first, then scraping (highest risk), then PDF processing, then LLM analysis (second highest risk), then notifications, and finally operational hardening. Each phase produces testable output that validates the approach before building downstream components.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Foundation & Configuration** - State tracking, logging, and configuration infrastructure
- [ ] **Phase 2: REGDOCS Scraper** - Discover and scrape filing metadata from the CER website
- [ ] **Phase 3: PDF Download & Storage** - Download filing PDFs to organized local folders with retry logic
- [ ] **Phase 4: PDF Text Extraction** - Extract text from PDFs with tiered fallback strategy
- [ ] **Phase 5: Core LLM Analysis** - Validate Claude CLI integration with entity extraction and document classification
- [ ] **Phase 6: Deep Analysis Features** - Regulatory implications, deadlines, sentiment, quotes, and impact scoring
- [ ] **Phase 7: Long Document Handling** - Chunking and synthesis for large PDFs (200+ pages)
- [ ] **Phase 8: Email Notifications** - Gmail delivery with HTML templates and configurable formatting
- [ ] **Phase 9: Pipeline Orchestration** - End-to-end integration with per-filing error isolation
- [ ] **Phase 10: Scheduling & Monitoring** - Unattended 2-hour execution with external heartbeat monitoring

## Phase Details

### Phase 1: Foundation & Configuration
**Goal**: The project has a working data model, persistent state tracking, structured logging, and externalized configuration so that all downstream components build on a stable foundation.
**Depends on**: Nothing (first phase)
**Requirements**: OPS-01, OPS-03, OPS-06
**Success Criteria** (what must be TRUE):
  1. Running the application creates a SQLite database and a `processed_filings` table that persists across restarts
  2. Log output includes timestamps, log levels, and component names, and rotates to new files when size limits are reached
  3. Secrets (Gmail password, etc.) are read from a .env file and settings (URLs, delays, paths) are read from a config file -- neither is hardcoded
  4. A Filing data model exists with fields for filing ID, date, applicant, type, proceeding number, and PDF URLs
  5. Marking a filing as processed in the state store prevents it from appearing in "unprocessed" queries
**Plans**: 4 plans

Plans:
- [x] 01-01-PLAN.md -- Project scaffolding, package structure, and dependency installation
- [x] 01-02-PLAN.md -- Configuration system (pydantic-settings + YAML files + .env)
- [x] 01-03-PLAN.md -- Database models, engine/session factory, and logging setup
- [x] 01-04-PLAN.md -- Main.py entry point wiring and state store operations

### Phase 2: REGDOCS Scraper
**Goal**: The system can reliably retrieve recent filing metadata from the CER REGDOCS website, either via discovered API endpoints or Playwright DOM parsing.
**Depends on**: Phase 1
**Requirements**: SCRP-01, SCRP-02, SCRP-03
**Success Criteria** (what must be TRUE):
  1. Running the scraper returns a list of recent filings with date, applicant, type, proceeding number, and PDF URLs extracted from REGDOCS
  2. The scraper first attempts to use internal API endpoints (discovered via Playwright network interception) before falling back to DOM parsing
  3. Requests to REGDOCS include 1-3 second delays between pages, a descriptive User-Agent header, and respect robots.txt directives
  4. When REGDOCS returns zero filings for 3+ consecutive runs, the scraper logs a warning (site structure may have changed)
**Plans**: TBD

Plans:
- [ ] 02-01: TBD
- [ ] 02-02: TBD

### Phase 3: PDF Download & Storage
**Goal**: Every PDF associated with a scraped filing is downloaded to a well-organized local folder structure with resilience against transient network failures.
**Depends on**: Phase 2
**Requirements**: PDF-01
**Success Criteria** (what must be TRUE):
  1. PDFs are saved to folders organized by date and filing ID (e.g., `data/filings/2026-02-05_Filing-12345/documents/`)
  2. A failed download retries up to 3 times with exponential backoff before marking the filing as partially failed
  3. Re-running the pipeline for a filing that already has downloaded PDFs skips the download step (checks file existence and size)
**Plans**: TBD

Plans:
- [ ] 03-01: TBD

### Phase 4: PDF Text Extraction
**Goal**: Text content is reliably extracted from the full range of CER filing PDFs -- machine-generated, table-heavy, and scanned documents.
**Depends on**: Phase 3
**Requirements**: PDF-02, PDF-03, PDF-04
**Success Criteria** (what must be TRUE):
  1. Machine-generated PDFs produce clean text output via PyMuPDF
  2. Table-heavy documents that produce garbled output from PyMuPDF are automatically re-extracted using pdfplumber with preserved table structure
  3. Scanned/image PDFs with no text layer are processed through Tesseract OCR and the output is validated for reasonable character count relative to page count
  4. Extraction results are validated -- a 50-page PDF producing fewer than 100 characters triggers a warning and fallback attempt
**Plans**: TBD

Plans:
- [ ] 04-01: TBD
- [ ] 04-02: TBD

### Phase 5: Core LLM Analysis
**Goal**: The system can invoke Claude Code CLI on extracted filing text and return structured analysis with entity extraction and document classification.
**Depends on**: Phase 4
**Requirements**: LLM-01, LLM-02, LLM-03
**Success Criteria** (what must be TRUE):
  1. `claude -p` is invoked as a subprocess with a configurable timeout (default 5 minutes) and non-zero exit codes are caught and logged as analysis failures
  2. Analysis output contains extracted entities: companies, facilities, people, and locations mentioned in the filing
  3. Analysis output classifies the document type (application, compliance report, order, decision, correspondence, etc.) with a confidence indicator
  4. The analysis prompt is stored in an external template file (not hardcoded) so it can be iterated without code changes
  5. Analysis output is structured JSON that downstream components (email, storage) can consume programmatically
**Plans**: TBD

Plans:
- [ ] 05-01: TBD
- [ ] 05-02: TBD

### Phase 6: Deep Analysis Features
**Goal**: Each filing analysis includes regulatory implications, key deadlines, sentiment assessment, representative quotes, and an impact score -- providing the depth that makes email reports actionable.
**Depends on**: Phase 5
**Requirements**: LLM-04, LLM-05, LLM-06, LLM-07, LLM-08
**Success Criteria** (what must be TRUE):
  1. Analysis output includes a regulatory implications section describing impact on industry, affected parties, and recommended next steps
  2. Key dates and deadlines (comment periods, hearing dates, compliance deadlines) are extracted and presented in a structured list
  3. Filing tone/sentiment is assessed (urgent, adversarial, routine, etc.) to support reader prioritization
  4. Two to three key quotes are extracted verbatim from the filing for quick scanning in the email report
  5. Each filing receives an impact rating on a 1-5 scale with a brief justification
**Plans**: TBD

Plans:
- [ ] 06-01: TBD
- [ ] 06-02: TBD

### Phase 7: Long Document Handling
**Goal**: Documents exceeding the Claude context window (200+ pages) are analyzed completely through section-based chunking and synthesis, with no silent truncation.
**Depends on**: Phase 6
**Requirements**: LLM-09
**Success Criteria** (what must be TRUE):
  1. Documents exceeding a configurable token threshold are split into logical sections (heading-based or page-range chunks) rather than fed whole to Claude
  2. Each chunk is analyzed independently and results are synthesized into a single coherent analysis that covers the full document
  3. The final analysis metadata indicates the document was chunked, how many sections were analyzed, and the total page count
**Plans**: TBD

Plans:
- [ ] 07-01: TBD

### Phase 8: Email Notifications
**Goal**: Each analyzed filing is delivered to the user's inbox as a well-formatted HTML email containing the full analysis, filing metadata, and a direct link to REGDOCS.
**Depends on**: Phase 6 (Phase 7 enhances but does not block)
**Requirements**: NOTF-01, NOTF-02
**Success Criteria** (what must be TRUE):
  1. An HTML email is sent via Gmail SMTP (app password) for each analyzed filing, containing metadata header, full analysis sections, and a clickable REGDOCS link
  2. Email subject lines include filing type, applicant, and date for easy inbox scanning
  3. Email templates are configurable -- the user can modify HTML layout and which analysis sections appear without changing code
  4. Failed email sends are logged with the error and do not crash the pipeline
**Plans**: TBD

Plans:
- [ ] 08-01: TBD
- [ ] 08-02: TBD

### Phase 9: Pipeline Orchestration
**Goal**: All components are wired into a single end-to-end pipeline that processes new filings from scrape to email, with per-filing error isolation so one failure never blocks the rest.
**Depends on**: Phase 8 (also benefits from Phase 7)
**Requirements**: OPS-05
**Success Criteria** (what must be TRUE):
  1. Running `main.py` executes the full pipeline: scrape -> check state -> download -> extract -> analyze -> email for each new filing
  2. A failure in any step for one filing (bad PDF, Claude timeout, email error) is logged and the pipeline continues to the next filing
  3. After a run with mixed successes and failures, the state store correctly reflects which filings succeeded, which failed, and which were skipped as already processed
  4. A run with no new filings completes quickly as a no-op with a log entry confirming no new filings found
**Plans**: TBD

Plans:
- [ ] 09-01: TBD
- [ ] 09-02: TBD

### Phase 10: Scheduling & Monitoring
**Goal**: The pipeline runs unattended every 2 hours and alerts the user if it stops running.
**Depends on**: Phase 9
**Requirements**: OPS-02, OPS-04
**Success Criteria** (what must be TRUE):
  1. A Windows Task Scheduler task triggers `uv run python main.py` every 2 hours
  2. Each successful run pings an external heartbeat service (Healthchecks.io) confirming the scraper is alive
  3. If no heartbeat ping is received for 4+ hours, the monitoring service sends an alert to the user
  4. The script starts, processes filings, and exits cleanly -- no long-running Python process between runs
**Plans**: TBD

Plans:
- [ ] 10-01: TBD
- [ ] 10-02: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4 -> 5 -> 6 -> 7 -> 8 -> 9 -> 10

| Phase | Plans Complete | Status | Completed |
|-------|---------------|--------|-----------|
| 1. Foundation & Configuration | 4/4 | Complete | 2026-02-05 |
| 2. REGDOCS Scraper | 0/TBD | Not started | - |
| 3. PDF Download & Storage | 0/TBD | Not started | - |
| 4. PDF Text Extraction | 0/TBD | Not started | - |
| 5. Core LLM Analysis | 0/TBD | Not started | - |
| 6. Deep Analysis Features | 0/TBD | Not started | - |
| 7. Long Document Handling | 0/TBD | Not started | - |
| 8. Email Notifications | 0/TBD | Not started | - |
| 9. Pipeline Orchestration | 0/TBD | Not started | - |
| 10. Scheduling & Monitoring | 0/TBD | Not started | - |
