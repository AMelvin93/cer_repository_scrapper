# Requirements: CER REGDOCS Scraper & Analyzer

**Defined:** 2026-02-05
**Core Value:** Every CER filing gets captured, analyzed in depth, and delivered to the user's inbox — no filings slip through the cracks.

## v1 Requirements

### Scraping

- [ ] **SCRP-01**: Scrape REGDOCS recent filings page and extract filing metadata (date, applicant, type, proceeding number, PDF URLs)
- [ ] **SCRP-02**: Discover internal REGDOCS API endpoints via Playwright network interception before falling back to DOM parsing
- [ ] **SCRP-03**: Implement polite scraping with 1-3 second delays between requests, proper User-Agent header, and robots.txt respect

### PDF Processing

- [ ] **PDF-01**: Download all PDFs for each filing with retry logic (3 attempts, exponential backoff) to organized local folders
- [ ] **PDF-02**: Extract text from machine-generated PDFs using PyMuPDF
- [ ] **PDF-03**: Fall back to pdfplumber for table-heavy documents where PyMuPDF produces garbled output
- [ ] **PDF-04**: OCR fallback using Tesseract for scanned/image PDFs with extraction validation

### LLM Analysis

- [ ] **LLM-01**: Run deep-dive analysis on each filing via Claude Code CLI (`claude -p`) subprocess with timeout and error handling
- [ ] **LLM-02**: Extract entities (companies, facilities, people, locations) from filing text
- [ ] **LLM-03**: Classify document type (application, compliance report, order, decision, correspondence, etc.)
- [ ] **LLM-04**: Summarize regulatory implications (impact on industry, affected parties, next steps)
- [ ] **LLM-05**: Extract deadlines and key dates (comment periods, hearing dates, compliance deadlines)
- [ ] **LLM-06**: Assess sentiment/tone (urgent, adversarial, routine) for prioritization
- [ ] **LLM-07**: Extract 2-3 key quotes for quick email scanning
- [ ] **LLM-08**: Rate filing impact on 1-5 scale
- [ ] **LLM-09**: Handle long documents (200+ pages) by chunking into sections, analyzing each, and synthesizing

### Notifications

- [ ] **NOTF-01**: Send one HTML email per filing via Gmail (app password) with full analysis, metadata, and REGDOCS link
- [ ] **NOTF-02**: Support configurable email templates for customizing format and content

### Operations

- [ ] **OPS-01**: Track processed filings in SQLite to prevent reprocessing across runs
- [ ] **OPS-02**: Run on 2-hour schedule via Windows Task Scheduler
- [ ] **OPS-03**: Structured logging with timestamps, filing IDs, per-step success/failure, and file rotation
- [ ] **OPS-04**: External heartbeat monitoring (Healthchecks.io) that alerts if scraper stops running
- [ ] **OPS-05**: Per-filing error isolation — one failure doesn't crash the entire run
- [ ] **OPS-06**: Configuration via .env file for secrets and config file for settings

## v2 Requirements

### Cross-Filing Intelligence

- **XFIL-01**: Detect relationships between filings by proceeding number
- **XFIL-02**: Build proceeding timelines across related filings
- **XFIL-03**: Multi-document daily synthesis summarizing all filings processed that day

### Enhanced Notifications

- **ENOTF-01**: Email delivery confirmation and retry for failed sends
- **ENOTF-02**: Daily digest email option as alternative to per-filing

### Enhanced Scraping

- **ESCRP-01**: Pagination handling for Last Week and Last Month views
- **ESCRP-02**: Advanced search filtering by company, proceeding type, or date range

## Out of Scope

| Feature | Reason |
|---------|--------|
| Web dashboard / UI | Email-only delivery for v1 — avoids massive scope increase |
| Database server (PostgreSQL/MySQL) | SQLite handles 10-50/day for decades — server DB is overkill |
| Multi-user support | Single-user tool — no value in authentication |
| Cloud deployment | Design locally first, deployment environment TBD |
| Real-time monitoring (<2 hours) | CER doesn't offer webhooks, regulatory timescales don't need sub-2-hour polling |
| Custom LLM fine-tuning | Prompt engineering is sufficient and much faster to iterate |
| Containerization (Docker) | Adds deployment complexity for single-machine tool |
| API-based LLM calls | Using Claude Code CLI to leverage existing subscription |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| SCRP-01 | — | Pending |
| SCRP-02 | — | Pending |
| SCRP-03 | — | Pending |
| PDF-01 | — | Pending |
| PDF-02 | — | Pending |
| PDF-03 | — | Pending |
| PDF-04 | — | Pending |
| LLM-01 | — | Pending |
| LLM-02 | — | Pending |
| LLM-03 | — | Pending |
| LLM-04 | — | Pending |
| LLM-05 | — | Pending |
| LLM-06 | — | Pending |
| LLM-07 | — | Pending |
| LLM-08 | — | Pending |
| LLM-09 | — | Pending |
| NOTF-01 | — | Pending |
| NOTF-02 | — | Pending |
| OPS-01 | — | Pending |
| OPS-02 | — | Pending |
| OPS-03 | — | Pending |
| OPS-04 | — | Pending |
| OPS-05 | — | Pending |
| OPS-06 | — | Pending |

**Coverage:**
- v1 requirements: 24 total
- Mapped to phases: 0
- Unmapped: 24 ⚠️

---
*Requirements defined: 2026-02-05*
*Last updated: 2026-02-05 after initial definition*
