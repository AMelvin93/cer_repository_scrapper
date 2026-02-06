# CER REGDOCS Filing Monitor

Automated pipeline that scrapes the Canada Energy Regulator's [REGDOCS](https://apps.cer-rec.gc.ca/REGDOCS) website for recent regulatory filings, downloads PDFs, runs deep-dive analysis on each filing via Claude Code CLI, and delivers per-filing email reports.

## How It Works

```
Scrape REGDOCS  -->  Download PDFs  -->  Extract Text  -->  Analyze with Claude  -->  Email Report
     (2)               (3)                 (4)               (5-7)                    (8)
```

Each filing is tracked through the full pipeline with per-step status (scraped, downloaded, extracted, analyzed, emailed). Failures are isolated per filing so one bad PDF never blocks the rest. The pipeline runs every 2 hours via Windows Task Scheduler and only processes new/incremental filings.

## Current Status

**Phase 1 of 10 complete** -- foundation infrastructure is in place.

| Phase | Description | Status |
|-------|-------------|--------|
| 1. Foundation & Configuration | SQLite state tracking, logging, config system | Done |
| 2. REGDOCS Scraper | Discover API endpoints, extract filing metadata | Planned |
| 3. PDF Download & Storage | Download PDFs with retry logic | Planned |
| 4. PDF Text Extraction | PyMuPDF + pdfplumber + Tesseract OCR fallbacks | Planned |
| 5. Core LLM Analysis | Claude CLI integration, entity extraction, classification | Planned |
| 6. Deep Analysis Features | Implications, deadlines, sentiment, quotes, impact scores | Planned |
| 7. Long Document Handling | Chunking and synthesis for 200+ page documents | Planned |
| 8. Email Notifications | Gmail HTML reports with configurable templates | Planned |
| 9. Pipeline Orchestration | End-to-end wiring with per-filing error isolation | Planned |
| 10. Scheduling & Monitoring | Task Scheduler + Healthchecks.io heartbeat | Planned |

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager

## Quick Start

```bash
# Clone the repo
git clone https://github.com/your-user/cer_repository_scrapper.git
cd cer_repository_scrapper

# Install dependencies
uv sync

# Copy and fill in your secrets
cp .env.example .env
# Edit .env with your Gmail credentials

# Run the application
uv run python main.py
```

On first run this creates:
- `data/state.db` -- SQLite database tracking all filing state
- `logs/pipeline.log` -- JSON-formatted rotating log file

## Configuration

Settings are split across YAML files (committed, no secrets) and a `.env` file (gitignored, secrets only).

### Config Files

| File | Purpose |
|------|---------|
| `config/scraper.yaml` | REGDOCS URL, request delays, pages to scrape, user agent |
| `config/email.yaml` | SMTP host, port, TLS setting |
| `config/pipeline.yaml` | Database path, log rotation, analysis timeout, retry limit |

### Environment Variables

Secrets go in `.env` (see `.env.example`):

```bash
EMAIL_SENDER_ADDRESS=your.email@gmail.com
EMAIL_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx    # Gmail app password
EMAIL_RECIPIENT_ADDRESS=recipient@example.com
```

Any setting from the YAML files can be overridden via environment variables using the appropriate prefix:

```bash
SCRAPER_DELAY_SECONDS=5.0     # Override scraper.yaml delay_seconds
PIPELINE_DB_PATH=custom.db    # Override pipeline.yaml db_path
```

## Project Structure

```
cer_repository_scrapper/
    src/cer_scraper/
        __init__.py              # Package root (v0.1.0)
        config/
            __init__.py          # load_all_settings()
            settings.py          # ScraperSettings, EmailSettings, PipelineSettings
        db/
            __init__.py          # Package exports
            models.py            # Filing, Document, Analysis, RunHistory (SQLAlchemy 2.0)
            engine.py            # get_engine(), init_db(), get_session_factory()
            state.py             # get_unprocessed_filings(), mark_step_complete(), etc.
        logging/
            __init__.py          # setup_logging export
            setup.py             # Dual-handler: JSON file + text console
    config/
        scraper.yaml             # Scraping settings
        email.yaml               # Email settings (no secrets)
        pipeline.yaml            # Pipeline operational settings
    main.py                      # Application entry point
    .env.example                 # Secret template
    pyproject.toml               # Dependencies and build config
```

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.11+ |
| Package Manager | uv |
| ORM | SQLAlchemy 2.0 (Mapped[], DeclarativeBase) |
| Database | SQLite |
| Configuration | pydantic-settings with YAML + .env sources |
| Logging | python-json-logger (JSON file) + stdlib (text console) |
| Scraping | Playwright (Phase 2) |
| PDF Extraction | PyMuPDF + pdfplumber + Tesseract (Phases 3-4) |
| LLM Analysis | Claude Code CLI (`claude -p`) (Phases 5-7) |
| Email | Gmail SMTP with app password (Phase 8) |
| Scheduling | Windows Task Scheduler (Phase 10) |
| Monitoring | Healthchecks.io (Phase 10) |

## Data Model

The SQLite database tracks filings through each pipeline stage:

- **filings** -- Core filing metadata (ID, date, applicant, type, proceeding number) with per-step status columns and retry tracking
- **documents** -- Individual PDFs linked to filings with download status
- **analyses** -- LLM analysis output linked to filings
- **run_history** -- Audit trail of pipeline runs

## License

Private project.
