# Technology Stack

**Project:** CER REGDOCS Scraper & Analyzer
**Researched:** 2026-02-05
**Overall Confidence:** MEDIUM (versions based on training data through mid-2025; verify with `uv add` at install time)

---

## Recommended Stack

### 1. Web Scraping (JS-Rendered Content)

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| **Playwright** | `>=1.49` | Browser automation for JS-rendered REGDOCS pages | Async-native, best Python support for JS-rendered sites, first-class Chromium/Firefox support, auto-wait for dynamic content, network interception for discovering AJAX endpoints | MEDIUM |
| **httpx** | `>=0.27` | Direct HTTP requests for discovered API endpoints and PDF downloads | Async support, HTTP/2, connection pooling. Once REGDOCS AJAX endpoints are reverse-engineered, httpx replaces Playwright for data fetching | MEDIUM |
| **BeautifulSoup4** | `>=4.12` | HTML/XML parsing of scraped content | De facto standard for HTML parsing, lightweight, pairs with httpx for non-JS pages | HIGH |

**Architecture note:** Use Playwright for initial discovery and any pages that truly require JS rendering. Reverse-engineer the REGDOCS AJAX API endpoints early (the filing list loads via XHR -- intercept those calls with Playwright's network monitoring, then switch to direct httpx requests for speed and reliability). Playwright should be the fallback, not the primary path for every request.

#### Why NOT These Alternatives

| Rejected | Why Not |
|----------|---------|
| **Selenium** | Heavier, slower, requires separate webdriver management. Playwright is the modern replacement with better async support and auto-waiting. Selenium is legacy for new projects in 2025+. |
| **requests** | No async support, no HTTP/2. httpx is the direct successor with the same API feel. |
| **Scrapy** | Overkill framework for a single-site scraper. Adds complexity (middlewares, pipelines, settings) without proportional benefit for 10-50 items/day. |
| **selenium-wire** | Combines two legacy tools. Playwright's built-in route/request interception is cleaner. |
| **DrissionPage** | Niche adoption, smaller community. Playwright has broader ecosystem support and documentation. |

---

### 2. PDF Text Extraction

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| **PyMuPDF (fitz)** | `>=1.24` | Primary PDF text extraction | Fastest PDF library in Python benchmarks. Handles text extraction, metadata, page-level operations. C-based MuPDF engine. Import as `fitz`. | MEDIUM |
| **pdfplumber** | `>=0.11` | Fallback for table-heavy PDFs | Better table extraction than PyMuPDF. Use when PyMuPDF text extraction produces garbled table layouts. | MEDIUM |

**Architecture note:** PyMuPDF is the primary extractor. For each PDF, extract text with PyMuPDF first. If the filing contains regulatory tables (rate schedules, condition compliance matrices), pdfplumber provides better structured table extraction. The extracted text is what gets passed to Claude CLI for analysis -- not the raw PDF.

#### Why NOT These Alternatives

| Rejected | Why Not |
|----------|---------|
| **PyPDF2 / pypdf** | Slower text extraction, worse handling of complex layouts. PyMuPDF is strictly superior for text extraction speed and quality. |
| **pdfminer.six** | Unmaintained/slow development. pdfplumber wraps pdfminer internally but provides a much better API. Use pdfplumber instead of raw pdfminer. |
| **Camelot** | Table extraction only, requires Ghostscript system dependency. pdfplumber covers table use cases without the system dep. |
| **OCR (Tesseract/EasyOCR)** | REGDOCS PDFs are digital-native (text-based), not scanned images. OCR adds latency and error for no benefit. Only consider if scanned PDFs are discovered. |

**Important:** Claude CLI (`claude -p`) can also read PDF files directly. The decision of whether to extract text first or pass PDFs directly should be validated in Phase 1. Text extraction gives you control over what context is sent and avoids token limits on large PDFs. Recommendation: extract text, then pass text to Claude CLI.

---

### 3. LLM Analysis (Claude Code CLI)

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| **Claude Code CLI** (`claude`) | Latest installed | Per-filing deep-dive analysis via `claude -p` | Already decided by project constraints. Uses existing subscription, no API key management, no per-token billing. | HIGH |
| **subprocess** (stdlib) | Python stdlib | Shell out to `claude -p` | Standard library, no dependency needed. Use `subprocess.run()` with timeout, capture stdout/stderr. | HIGH |

**Architecture note:** The CLI integration pattern is:

1. Prepare analysis prompt (filing metadata + extracted text)
2. Shell out: `subprocess.run(["claude", "-p", prompt_text], capture_output=True, timeout=300)`
3. Parse stdout as the analysis result
4. Handle timeouts and errors gracefully

**Key considerations:**
- **Rate limiting:** Claude CLI may have internal rate limits. Process filings sequentially, not in parallel.
- **Prompt size:** Large filings with many PDFs could exceed context. Chunk or summarize if total text exceeds ~100K characters.
- **Timeout:** Set generous timeouts (5 minutes per filing). LLM analysis is the slowest step.
- **Stdin vs args:** For long prompts, pipe text via stdin rather than command-line arguments (OS argument length limits).

#### What NOT to Do

| Anti-Pattern | Why Not |
|--------------|---------|
| **Anthropic Python SDK** | Project explicitly uses CLI to leverage subscription pricing, not API billing. |
| **Parallel CLI calls** | Risk hitting rate limits or overwhelming the system. Sequential is safer at 10-50/day volume. |
| **Passing raw PDF paths to CLI** | Loses control over context size. Extract text first, then pass relevant portions. |

---

### 4. Email Sending

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| **smtplib + email** (stdlib) | Python stdlib | Compose and send emails via Gmail SMTP | Standard library, zero dependencies. Gmail SMTP with app passwords is well-documented and stable. No need for a third-party library for single-recipient emails. | HIGH |

**Architecture note:**

- **Gmail App Password:** User creates an app-specific password in Google Account settings (requires 2FA enabled). Store in environment variable `GMAIL_APP_PASSWORD`.
- **SMTP settings:** `smtp.gmail.com:587` with STARTTLS.
- **Email format:** HTML email body with the analysis text, filing metadata in headers/subject line.
- **Connection reuse:** For multiple emails in one run, reuse the SMTP connection (login once, send multiple).

```
# Connection pattern
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
# Use starttls, authenticate with app password
```

#### Why NOT These Alternatives

| Rejected | Why Not |
|----------|---------|
| **Gmail API (OAuth2)** | Requires OAuth credential management, token refresh logic, Google Cloud project setup. Massively over-engineered for a single-user personal tool. App passwords are simpler and sufficient. |
| **SendGrid / Mailgun / SES** | Third-party service for a personal tool sending 10-50 emails/day. Unnecessary cost and complexity. Gmail is free at this volume. |
| **yagmail** | Convenience wrapper around smtplib, but adds a dependency for minimal benefit. The stdlib is straightforward enough. |
| **Flask-Mail / Django email** | Framework-specific. This is a script, not a web app. |

---

### 5. Scheduling (Periodic Execution on Windows)

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| **Windows Task Scheduler** | OS built-in | Trigger script every ~2 hours | Native OS scheduler. Most reliable for "run this script periodically on Windows." No Python process needs to stay alive between runs. | HIGH |
| **schedule** | `>=1.2` | Lightweight in-process scheduler (alternative) | Simple, readable API (`schedule.every(2).hours.do(job)`). Use only if running as a long-lived process is preferred over Task Scheduler. | MEDIUM |

**Primary recommendation: Windows Task Scheduler.** Here is why:

1. **Reliability:** OS-level scheduling survives Python crashes, updates, restarts.
2. **Resource efficiency:** Script runs, processes filings, exits. No idle Python process consuming memory between runs.
3. **Simplicity:** One scheduled task pointing to `uv run python main.py`. Done.
4. **Logging:** Task Scheduler has built-in history and error reporting.

**Setup:**
```
# Task Scheduler action:
Program: C:\Users\amelv\.local\bin\uv.exe
Arguments: run python C:\Users\amelv\Repo\cer_repository_scrapper\main.py
Start in: C:\Users\amelv\Repo\cer_repository_scrapper
Trigger: Every 2 hours, indefinitely
```

**Alternative (in-process):** If the user prefers a long-running process (e.g., for future containerization), use the `schedule` library with a main loop. But for Windows desktop use, Task Scheduler is superior.

#### Why NOT These Alternatives

| Rejected | Why Not |
|----------|---------|
| **APScheduler** | Powerful but heavy for this use case. Designed for complex scheduling (cron expressions, job stores, executors). Overkill when "every 2 hours" is the only requirement. |
| **Celery / Celery Beat** | Requires a message broker (Redis/RabbitMQ). Absurdly over-engineered for a single-user local script. |
| **cron** | Not available on Windows natively. Task Scheduler is the Windows equivalent. |
| **Windows Services (NSSM)** | Adds complexity of service management. Not needed for a periodic batch job. |

---

### 6. Data Management & State Tracking

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| **json** (stdlib) | Python stdlib | Track processed filing IDs, store metadata | Simple, human-readable, no dependencies. A single `processed_filings.json` file tracks what has been seen. | HIGH |
| **pathlib** (stdlib) | Python stdlib | File/directory management | Modern path handling, cross-platform (though targeting Windows). Stdlib. | HIGH |

**Architecture note:** State tracking is critical for the "only process new filings" requirement. Store a JSON file with:
- Filing ID (from REGDOCS URL)
- Timestamp when processed
- Status (success/failure)
- Email sent (boolean)

This is deliberately simple. A SQLite database is not warranted at 10-50 filings/day with local storage. If the project grows to need querying/filtering, upgrade to SQLite later.

#### Why NOT These Alternatives

| Rejected | Why Not |
|----------|---------|
| **SQLite** | Adds complexity for simple key-value tracking. JSON is sufficient for ~50 records/day appended to a list. Consider upgrading if querying needs emerge. |
| **TinyDB** | Dependency for JSON-file-as-database. The stdlib json module does the same thing for this scale. |
| **PostgreSQL / MySQL** | Massively over-engineered. Local filesystem storage is an explicit project constraint. |

---

### 7. Configuration Management

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| **python-dotenv** | `>=1.0` | Load `.env` file for secrets (Gmail password, etc.) | Standard pattern for secret management. Keeps secrets out of code. | HIGH |
| **dataclasses** (stdlib) | Python stdlib | Typed configuration objects | Stdlib, no dependency. Define a `Config` dataclass loaded from env vars. | HIGH |

**Secrets to manage:**
- `GMAIL_ADDRESS` - sender email
- `GMAIL_APP_PASSWORD` - app-specific password
- `RECIPIENT_EMAIL` - where to send reports
- `REGDOCS_BASE_URL` - base URL (for easy override)

---

### 8. Logging & Error Handling

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| **logging** (stdlib) | Python stdlib | Structured logging with file rotation | Stdlib, built-in rotation handler. Log to both console and file. | HIGH |

**Architecture note:** Since this runs as a periodic batch job (not a web server), logging to a rotating file is essential for debugging failures between runs. Use `RotatingFileHandler` with ~5MB max size and 3 backup files.

---

## Full Dependency List

### Runtime Dependencies

```toml
# pyproject.toml [project.dependencies]
dependencies = [
    "playwright>=1.49",
    "httpx>=0.27",
    "beautifulsoup4>=4.12",
    "pymupdf>=1.24",
    "pdfplumber>=0.11",
    "python-dotenv>=1.0",
]
```

### Optional (if in-process scheduling chosen)

```toml
# Only if NOT using Windows Task Scheduler
"schedule>=1.2",
```

### Post-Install Setup

```bash
# Install dependencies
uv add playwright httpx beautifulsoup4 pymupdf pdfplumber python-dotenv

# Install Playwright browser (Chromium only -- smaller download)
uv run playwright install chromium

# Create .env file
# GMAIL_ADDRESS=your@gmail.com
# GMAIL_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
# RECIPIENT_EMAIL=recipient@example.com
```

**Note on Playwright browsers:** `playwright install chromium` downloads ~150MB Chromium binary. This is a one-time setup. Only Chromium is needed (no Firefox/WebKit).

---

## Version Verification Status

**IMPORTANT:** Versions listed are based on training data (through mid-2025). The exact latest versions should be confirmed at install time. Using `>=` version specifiers allows uv to resolve the latest compatible version.

| Package | Listed Version | Verification Status |
|---------|---------------|-------------------|
| playwright | >=1.49 | MEDIUM -- was 1.49 as of late 2024. Likely higher now. uv will resolve latest. |
| httpx | >=0.27 | MEDIUM -- was 0.27.x as of mid-2025. |
| beautifulsoup4 | >=4.12 | HIGH -- stable, slow-moving library. |
| pymupdf | >=1.24 | MEDIUM -- was 1.24.x as of mid-2025. May be 1.25+. |
| pdfplumber | >=0.11 | MEDIUM -- was 0.11.x as of mid-2025. |
| python-dotenv | >=1.0 | HIGH -- stable, slow-moving. |
| schedule | >=1.2 | HIGH -- stable, slow-moving. |

**To verify at install time:**
```bash
uv add playwright httpx beautifulsoup4 pymupdf pdfplumber python-dotenv
uv pip list
```

---

## Architecture Decision: Playwright vs. Reverse-Engineered API

This is the highest-impact stack decision and deserves special attention.

### The REGDOCS Site Pattern

The CER REGDOCS filing list at `https://apps.cer-rec.gc.ca/REGDOCS/Search/RecentFilings` loads via JavaScript/AJAX. This means the HTML source contains a shell, and the actual filing data is fetched via XHR after page load.

### Recommended Approach (Two-Phase)

**Phase 1: Use Playwright to discover the API.**
1. Load the page with Playwright
2. Use `page.route()` or network event listeners to capture all XHR requests
3. Identify the actual data endpoint (likely a JSON or XML API under `/REGDOCS/api/` or similar)
4. Document the endpoint URL, parameters, response format

**Phase 2: Switch to direct httpx requests.**
1. Call the discovered API endpoint directly with httpx
2. Parse the JSON/XML response
3. Eliminates the need for a browser for routine scraping
4. Keep Playwright as a fallback for pages that genuinely need JS rendering (e.g., individual filing pages if they also use dynamic loading)

### Why This Matters

| Approach | Speed | Reliability | Resource Usage |
|----------|-------|-------------|----------------|
| Playwright for every request | Slow (~2-5s/page) | Medium (browser crashes, timeouts) | High (Chromium process) |
| Direct httpx to API | Fast (~0.1-0.5s/req) | High (simple HTTP) | Low (no browser) |

At 10-50 filings/day the performance difference is not critical, but reliability and simplicity are. Direct HTTP requests are always more reliable than browser automation when possible.

---

## Sources & Confidence Notes

- **Playwright:** Well-established as the leading Python browser automation library since 2022. Microsoft-maintained. Training data confidence is HIGH for the recommendation, MEDIUM for exact version.
- **httpx:** Established as the modern replacement for requests. Training data confidence HIGH.
- **PyMuPDF:** Consistently benchmarked as fastest Python PDF library. Training data confidence HIGH for recommendation.
- **Gmail SMTP + App Passwords:** Stable Google feature, well-documented. Training data confidence HIGH.
- **Windows Task Scheduler:** OS feature, not subject to version changes. Confidence HIGH.
- **python-dotenv:** Industry standard for `.env` loading. Confidence HIGH.

**Gaps:**
- Could not verify exact latest versions via PyPI at research time (external tools unavailable). Using `>=` version specifiers mitigates this.
- REGDOCS internal API structure is unknown -- must be discovered during implementation (Phase 1).
- Claude CLI (`claude -p`) stdin piping behavior and rate limits should be validated early in implementation.
