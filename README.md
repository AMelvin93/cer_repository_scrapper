# CER REGDOCS Filing Monitor

Automated pipeline that scrapes the Canada Energy Regulator's [REGDOCS](https://apps.cer-rec.gc.ca/REGDOCS) website for recent regulatory filings, downloads PDFs, extracts text, and runs deep-dive analysis on each filing via Claude Code CLI.

## How It Works

```
Scrape REGDOCS  -->  Enrich Details  -->  Download PDFs  -->  Extract Text  -->  Analyze with Claude
     (2)                (2)                  (3)                (4)               (5-6)
```

Each filing is tracked through the full pipeline with per-step status (scraped, downloaded, extracted, analyzed). Failures are isolated per filing so one bad PDF never blocks the rest.

## Current Status

**Phases 1-6 of 10 complete** -- scraping, downloading, extraction, and LLM analysis (including deep analysis) are fully functional.

| Phase | Description | Status |
|-------|-------------|--------|
| 1. Foundation & Configuration | SQLite state tracking, logging, config system | Done |
| 2. REGDOCS Scraper | DOM parsing, detail page enrichment, document URL discovery | Done |
| 3. PDF Download & Storage | Download PDFs with TLS workarounds, retry logic, all-or-nothing per filing | Done |
| 4. PDF Text Extraction | pymupdf4llm with Tesseract OCR fallback, quality validation | Done |
| 5. Core LLM Analysis | Claude CLI integration, entity extraction, classification | Done |
| 6. Deep Analysis Features | Regulatory implications, deadlines, sentiment, quotes, impact scores | Done |
| 7. Long Document Handling | Chunking and synthesis for 200+ page documents | Planned |
| 8. Email Notifications | Gmail HTML reports with configurable templates | Planned |
| 9. Pipeline Orchestration | End-to-end wiring with per-filing error isolation | Planned |
| 10. Scheduling & Monitoring | Task Scheduler + Healthchecks.io heartbeat | Planned |

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) (for analysis phases)
- Tesseract OCR (optional, for scanned PDF fallback)

## Quick Start

```bash
# Clone the repo
git clone https://github.com/your-user/cer_repository_scrapper.git
cd cer_repository_scrapper

# Install dependencies
uv sync

# Install Playwright browser (required for scraping)
uv run playwright install chromium

# Copy and fill in your secrets
cp .env.example .env
# Edit .env with your Gmail credentials

# Run the application
uv run python main.py
```

On first run this creates:
- `data/state.db` -- SQLite database tracking all filing state
- `logs/pipeline.log` -- JSON-formatted rotating log file
- `data/filings/` -- Downloaded PDFs, extracted markdown, and analysis JSON per filing

## Configuration

Settings are split across YAML files (committed, no secrets) and a `.env` file (gitignored, secrets only).

### Config Files

| File | Purpose |
|------|---------|
| `config/scraper.yaml` | REGDOCS URL, request delays, lookback period, retry config, filing filters |
| `config/email.yaml` | SMTP host, port, TLS setting |
| `config/pipeline.yaml` | Database path, log rotation, analysis timeout, retry limit |
| `config/prompts/filing_analysis.txt` | Prompt template for Claude CLI analysis |

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
ANALYSIS_MODEL=sonnet          # Override analysis model
```

## Project Structure

```
cer_repository_scrapper/
    src/cer_scraper/
        __init__.py              # Package root
        config/
            __init__.py          # load_all_settings()
            settings.py          # ScraperSettings, EmailSettings, PipelineSettings,
                                 #   ExtractionSettings, AnalysisSettings
        db/
            __init__.py          # Package exports
            models.py            # Filing, Document (SQLAlchemy 2.0)
            engine.py            # get_engine(), init_db(), get_session_factory()
            state.py             # create_filing(), get_unprocessed_filings(), etc.
        logging/
            __init__.py          # setup_logging export
            setup.py             # Dual-handler: JSON file + text console
        scraper/
            __init__.py          # scrape_recent_filings() public API
            models.py            # ScrapedFiling, ScrapedDocument (Pydantic)
            discovery.py         # Playwright network interception, API endpoint discovery
            detail_scraper.py    # Playwright detail page visits for document URL extraction
            api_client.py        # httpx client with tenacity retry for discovered endpoints
            dom_parser.py        # BeautifulSoup DOM parsing fallback (3 strategies)
            rate_limiter.py      # Randomized delay between requests
            robots.py            # robots.txt compliance checker
        downloader/
            __init__.py          # download_filings() public API
            service.py           # httpx download with TLS workaround, .tmp rename pattern
        extractor/
            __init__.py          # extract_filings() public API
            service.py           # Tiered extraction: pymupdf4llm -> Tesseract OCR
            pymupdf_extractor.py # Primary extractor via pymupdf4llm
            ocr_extractor.py     # Tesseract OCR fallback for scanned PDFs
            quality.py           # Text quality validation (repetition, charset checks)
            markdown.py          # Markdown file writer
            types.py             # ExtractionResult, ExtractionMethod shared types
        analyzer/
            __init__.py          # analyze_filings() public API
            service.py           # Claude CLI subprocess invocation
            prompt.py            # Prompt template loading and build_prompt()
            schemas.py           # AnalysisOutput, Classification, EntityRef,
                                 #   RegulatoryImplications, ExtractedDate,
                                 #   SentimentAssessment, RepresentativeQuote, ImpactScore
    config/
        scraper.yaml             # Scraping settings (delays, filters, lookback period)
        email.yaml               # Email settings (no secrets)
        pipeline.yaml            # Pipeline operational settings
        prompts/
            filing_analysis.txt  # LLM prompt template for filing analysis
    tests/
        smoke/                   # Live smoke tests (single-filing, safety-constrained)
            test_phases_01_04.py # Phases 1-4 baseline
            test_phases_01_05.py # Phases 1-5 baseline
            test_phases_01_06.py # Phases 1-6 baseline (current)
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
| Scraping | Playwright (discovery + detail pages) + httpx (API client) + BeautifulSoup4/lxml (DOM fallback) |
| Downloading | httpx with TLS `SECLEVEL=1` workaround for CER servers |
| Retry Logic | tenacity (exponential backoff with jitter) |
| PDF Extraction | pymupdf4llm (primary) + Tesseract OCR (fallback for scanned PDFs) |
| LLM Analysis | Claude Code CLI (`claude -p`) with structured JSON output |
| Email | Gmail SMTP with app password (Phase 8) |
| Scheduling | Windows Task Scheduler (Phase 10) |
| Monitoring | Healthchecks.io (Phase 10) |

## Scraper Architecture

The scraper uses a two-step approach since REGDOCS loads content dynamically via JavaScript:

```
scrape_recent_filings()
    │
    ├─ robots.txt check
    │
    ├─ Step 1: Listing Page (DOM parsing)
    │   ├─ Playwright navigates REGDOCS, captures rendered HTML
    │   └─ BeautifulSoup parses filing metadata (3 strategies: table, link, data-attribute)
    │
    ├─ Step 2: Detail Page Enrichment
    │   ├─ Playwright visits each filing's detail page
    │   └─ Extracts /File/Download/ document URLs
    │
    ├─ Validation & filtering (type, applicant, proceeding filters from config)
    ├─ Deduplication against state store
    └─ Persistence of new filings with document URLs
```

## Analysis Output

Each filing produces a structured JSON analysis with:

- **Classification** -- Primary filing type (Application, Order, Decision, etc.) with confidence score
- **Entities** -- Named entities (companies, regulators, pipelines) with roles
- **Relationships** -- Subject-predicate-object triples connecting entities
- **Key Facts** -- Concise bullet points summarizing the filing
- **Regulatory Implications** -- Impact summary and affected parties
- **Dates** -- Extracted deadlines, hearing dates, effective dates with temporal status
- **Sentiment** -- Tone assessment (routine/notable/urgent/adversarial/cooperative)
- **Quotes** -- Representative passages with source locations
- **Impact Score** -- 1-5 significance rating with justification

## Data Model

The SQLite database tracks filings through each pipeline stage:

- **filings** -- Core filing metadata (ID, date, applicant, type, proceeding number) with per-step status columns (`status_scraped`, `status_downloaded`, `status_extracted`, `status_analyzed`), retry tracking, and `analysis_json` storage
- **documents** -- Individual PDFs linked to filings with download path, extraction status, method, char/page counts

## License

Private project.
