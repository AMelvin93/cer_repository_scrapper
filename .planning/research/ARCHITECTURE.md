# Architecture Patterns: CER REGDOCS Scraper & Analyzer

**Domain:** Web scraping + LLM document analysis pipeline
**Researched:** 2026-02-05
**Overall confidence:** MEDIUM (based on training data; external verification tools unavailable)

---

## Recommended Architecture

**Pattern: Sequential Pipeline with State Tracking**

This system is a classic ETL-style pipeline (Extract, Transform, Load) with an LLM analysis stage bolted on. The key insight: this is NOT a complex distributed system. It processes 10-50 filings/day on a 2-hour cycle, so ~5-25 filings per run. That volume demands reliability and simplicity, not concurrency frameworks.

The architecture has **six discrete components** connected by a **shared local filesystem** and a **state store** (SQLite). Each component has a single responsibility and a clean interface.

```
                        +------------------+
                        |    Scheduler     |
                        |  (APScheduler /  |
                        |   cron / loop)   |
                        +--------+---------+
                                 |
                                 | triggers every ~2 hours
                                 v
                        +------------------+
                        |   Orchestrator   |
                        |  (Pipeline Core) |
                        +--------+---------+
                                 |
              +------------------+------------------+
              |                  |                   |
              v                  v                   v
     +--------+------+  +-------+-------+  +--------+------+
     |    Scraper     |  |   State Store |  |   Notifier    |
     | (Playwright +  |  |   (SQLite)    |  |   (Gmail)     |
     |  page parser)  |  +-------+-------+  +--------+------+
     +--------+------+          ^                    ^
              |                  |                    |
              | filing metadata  | read/write         | analysis results
              v                  | state              |
     +--------+------+          |            +--------+------+
     |   Downloader   |  -------+            |   Analyzer    |
     |  (PDF fetch +  |                      | (Claude CLI   |
     |  file mgmt)    |                      |  subprocess)  |
     +--------+------+                       +---------------+
              |                                      ^
              | PDF file paths                       |
              +--------------------------------------+
```

### Pipeline Execution Flow (Per Run)

```
1. Scheduler triggers Orchestrator
2. Orchestrator calls Scraper
3. Scraper → navigates REGDOCS, extracts filing metadata (IDs, titles, PDF URLs)
4. Orchestrator queries State Store → filters out already-processed filings
5. For each NEW filing:
   a. Downloader → fetches PDFs to local folder
   b. Analyzer → runs Claude CLI on each PDF, captures analysis text
   c. Notifier → sends Gmail with analysis results
   d. State Store → marks filing as processed
6. Orchestrator logs summary of run
```

---

## Component Boundaries

| Component | Responsibility | Inputs | Outputs | Talks To |
|-----------|---------------|--------|---------|----------|
| **Scheduler** | Triggers pipeline runs on interval | Clock / cron | Trigger signal | Orchestrator |
| **Orchestrator** | Coordinates pipeline steps, handles errors, logs runs | Trigger signal | Run summary / logs | All components |
| **Scraper** | Navigates REGDOCS, extracts filing metadata | REGDOCS URL config | List of `Filing` objects (id, title, date, pdf_urls, filing_url) | Playwright browser |
| **State Store** | Tracks processed filings, prevents reprocessing | Filing IDs to check/mark | Processed status, history | SQLite DB file |
| **Downloader** | Fetches PDF files to organized local folders | `Filing` objects with PDF URLs | Local file paths for each PDF | HTTP (requests/httpx) |
| **Analyzer** | Runs Claude CLI analysis on PDFs, captures output | PDF file paths + analysis prompt | Structured analysis text per filing | Claude CLI subprocess |
| **Notifier** | Sends per-filing email with analysis results | Filing metadata + analysis text | Email sent confirmation | Gmail SMTP |

---

## Detailed Component Design

### 1. Scheduler

**What it does:** Triggers the pipeline on a 2-hour interval.

**Design options (ranked):**

| Option | When to Use | Complexity |
|--------|-------------|------------|
| Simple `while True` + `time.sleep()` | Prototype / Phase 1 | Trivial |
| `APScheduler` (BackgroundScheduler) | Production-ready interval scheduling | Low |
| OS-level cron / Task Scheduler | When running as system service | Low (external) |

**Recommendation:** Start with a simple `while True` loop in `main.py` for Phase 1. Upgrade to APScheduler only if you need missed-run recovery or more sophisticated scheduling. For a 2-hour interval on a single machine, a sleep loop is perfectly adequate.

**Interface:**
```python
# main.py entry point
async def run_pipeline():
    """Single pipeline execution."""
    ...

def main():
    """Entry point with scheduling."""
    while True:
        asyncio.run(run_pipeline())
        time.sleep(7200)  # 2 hours
```

**Confidence:** HIGH -- this is a straightforward pattern.

---

### 2. Orchestrator (Pipeline Core)

**What it does:** The central coordinator. Calls components in sequence, handles errors per-filing so one failure does not crash the entire run, and logs results.

**Key design decisions:**

- **Per-filing error isolation:** If downloading/analyzing/emailing fails for one filing, log the error and continue to the next filing. Do NOT mark failed filings as processed (so they retry next run).
- **Idempotency:** The orchestrator checks state BEFORE processing, making each run safe to retry.
- **No parallelism needed:** At 5-25 filings per run, sequential processing is fine. Each filing takes ~30-60 seconds (mostly Claude CLI analysis time). Worst case: ~25 minutes per run. Well within the 2-hour window.

**Interface:**
```python
# pipeline/orchestrator.py
class PipelineOrchestrator:
    def __init__(self, scraper, downloader, analyzer, notifier, state_store, config):
        ...

    async def run(self) -> RunResult:
        """Execute one full pipeline run."""
        # 1. Scrape filings
        filings = await self.scraper.scrape_recent_filings()

        # 2. Filter to new filings only
        new_filings = self.state_store.filter_unprocessed(filings)

        # 3. Process each filing
        results = []
        for filing in new_filings:
            try:
                result = await self._process_filing(filing)
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to process {filing.id}: {e}")
                results.append(FilingResult(filing=filing, success=False, error=str(e)))

        return RunResult(total=len(filings), new=len(new_filings), results=results)

    async def _process_filing(self, filing: Filing) -> FilingResult:
        """Download, analyze, notify for a single filing."""
        pdf_paths = await self.downloader.download(filing)
        analysis = await self.analyzer.analyze(filing, pdf_paths)
        await self.notifier.send(filing, analysis)
        self.state_store.mark_processed(filing.id)
        return FilingResult(filing=filing, success=True, analysis=analysis)
```

**Confidence:** HIGH -- orchestrator pattern is well-established for ETL pipelines.

---

### 3. Scraper

**What it does:** Uses Playwright to navigate the REGDOCS site, extract filing metadata from the search results page, and optionally navigate to individual filing pages to get PDF download links.

**Architecture considerations:**

- **Two-phase scraping:** Phase 1 scrapes the filing list page to get filing IDs and basic metadata. Phase 2 navigates to each filing's detail page to extract PDF download URLs. These could be combined or separated depending on how much metadata is available on the list page.
- **Playwright lifecycle:** Browser launch is expensive (~1-2 seconds). Launch once per run, reuse for all page navigations, close at the end.
- **REGDOCS page structure:** The site at `apps.cer-rec.gc.ca/REGDOCS` renders content dynamically via JavaScript. The search results likely load via internal AJAX calls. There may be internal API endpoints (e.g., returning JSON) that Playwright could intercept, which would be more reliable than DOM scraping.

**Important architectural pattern -- API interception:**
```python
# If REGDOCS uses internal AJAX, intercept it for cleaner data
async def scrape_with_api_intercept(page):
    """Listen for XHR responses to capture structured data."""
    api_responses = []

    async def handle_response(response):
        if "/api/" in response.url or "Search" in response.url:
            if "application/json" in (response.headers.get("content-type", "")):
                api_responses.append(await response.json())

    page.on("response", handle_response)
    await page.goto(REGDOCS_URL)
    await page.wait_for_load_state("networkidle")
    # api_responses now contains structured JSON if available
```

**Interface:**
```python
# scraper/regdocs_scraper.py
@dataclass
class Filing:
    id: str
    title: str
    date: datetime
    filing_url: str
    pdf_urls: list[str]
    applicant: str | None = None
    category: str | None = None

class RegdocsScraper:
    async def scrape_recent_filings(self) -> list[Filing]:
        """Scrape REGDOCS for recent filings with PDF links."""
        ...
```

**Confidence:** MEDIUM -- the exact page structure and whether internal APIs exist needs validation during implementation. The Playwright approach itself is HIGH confidence.

---

### 4. State Store

**What it does:** Tracks which filing IDs have been processed. Prevents re-downloading, re-analyzing, and re-emailing on subsequent runs.

**Why SQLite (not flat file):**
- Atomic writes (no corruption from crashes mid-run)
- Query capability (e.g., "what was processed in the last 24 hours?")
- Zero configuration, no server
- Ships with Python (`sqlite3` standard library)
- Handles the volume easily (thousands of rows = nothing for SQLite)

**Schema:**
```sql
CREATE TABLE processed_filings (
    filing_id TEXT PRIMARY KEY,
    title TEXT,
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    pdf_count INTEGER,
    analysis_status TEXT,  -- 'success', 'failed', 'partial'
    email_sent BOOLEAN DEFAULT FALSE,
    error_message TEXT
);

CREATE TABLE run_log (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    total_filings INTEGER,
    new_filings INTEGER,
    processed_ok INTEGER,
    processed_failed INTEGER
);
```

**Interface:**
```python
# storage/state_store.py
class StateStore:
    def __init__(self, db_path: Path):
        ...

    def is_processed(self, filing_id: str) -> bool: ...
    def filter_unprocessed(self, filings: list[Filing]) -> list[Filing]: ...
    def mark_processed(self, filing_id: str, status: str = "success"): ...
    def mark_failed(self, filing_id: str, error: str): ...
    def get_run_history(self, limit: int = 10) -> list[RunLog]: ...
```

**Confidence:** HIGH -- SQLite for local state tracking is a proven, standard pattern.

---

### 5. Downloader

**What it does:** Fetches PDF files from REGDOCS and saves them to an organized local folder structure.

**Folder structure:**
```
data/
  filings/
    2026-02-05_Filing-12345_Application-Title/
      filing_metadata.json        # Scraped metadata for reference
      documents/
        document_1.pdf
        document_2.pdf
    2026-02-05_Filing-12346_Another-Filing/
      ...
```

**Design decisions:**
- **Folder naming:** `{date}_{filing_id}_{sanitized_title}` -- human-browsable and programmatically addressable.
- **HTTP client:** Use `httpx` (async) rather than `requests` for consistency with the async Playwright scraper. However, PDF downloads are simple GET requests -- `requests` works fine too.
- **Retry logic:** PDFs from government sites occasionally timeout. Implement 3 retries with exponential backoff.
- **Deduplication:** Check if PDF already exists (by filename and size) before downloading.

**Interface:**
```python
# downloader/pdf_downloader.py
class PdfDownloader:
    def __init__(self, base_dir: Path, timeout: int = 60):
        ...

    async def download(self, filing: Filing) -> list[Path]:
        """Download all PDFs for a filing. Returns list of local file paths."""
        ...
```

**Confidence:** HIGH -- straightforward file download pattern.

---

### 6. Analyzer

**What it does:** Runs Claude Code CLI (`claude -p`) as a subprocess on each PDF, captures the analysis output as text.

**This is the most architecturally interesting component.** Key considerations:

- **Subprocess management:** Shell out to `claude -p` with the PDF path and a carefully crafted prompt. Capture stdout. Handle timeouts (large PDFs may take several minutes).
- **Prompt engineering:** The analysis prompt is a critical artifact. It should be stored as a template file, not hardcoded, so it can be iterated independently.
- **Multi-PDF filings:** Some filings have multiple PDFs. Options:
  - Analyze each PDF separately, combine results (recommended -- simpler, more reliable)
  - Concatenate PDFs and analyze once (risks context window limits)
- **Output format:** Request structured output (e.g., markdown with sections) from Claude CLI so the email formatter can parse it consistently.
- **Timeout handling:** Set a subprocess timeout (e.g., 5 minutes per PDF). If it times out, mark as failed and continue.

**Interface:**
```python
# analyzer/claude_analyzer.py
@dataclass
class AnalysisResult:
    filing_id: str
    summary: str
    full_analysis: str
    pdf_analyses: list[PdfAnalysis]  # One per PDF in the filing
    analysis_duration_seconds: float

@dataclass
class PdfAnalysis:
    pdf_path: Path
    pdf_name: str
    analysis_text: str
    success: bool
    error: str | None = None

class ClaudeAnalyzer:
    def __init__(self, prompt_template_path: Path, timeout_seconds: int = 300):
        ...

    async def analyze(self, filing: Filing, pdf_paths: list[Path]) -> AnalysisResult:
        """Run Claude CLI analysis on all PDFs for a filing."""
        ...

    async def _analyze_single_pdf(self, pdf_path: Path, filing_context: str) -> PdfAnalysis:
        """Run claude -p on a single PDF."""
        proc = await asyncio.create_subprocess_exec(
            "claude", "-p", prompt,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=self.timeout_seconds
        )
        ...
```

**Important note on Claude CLI invocation:** The exact CLI flags and how to pass PDF content need validation. Options include:
- Passing the PDF path in the prompt and relying on Claude CLI's file reading capability
- Piping PDF content via stdin
- Using `--file` or `-f` flags if available

This requires Phase 1 prototyping to determine the correct invocation pattern.

**Confidence:** MEDIUM -- Claude CLI subprocess approach is sound, but exact invocation details need validation.

---

### 7. Notifier

**What it does:** Sends one email per filing via Gmail SMTP with the analysis results.

**Design decisions:**
- **One email per filing:** As specified in requirements. At 10-50/day, this is manageable.
- **Email content:** Well-formatted HTML email with filing metadata header, analysis summary, full analysis body, and links to the original filing on REGDOCS.
- **Gmail SMTP with app password:** Standard `smtplib` + `email.mime` from Python stdlib. No third-party library needed.
- **Rate limiting:** Gmail has sending limits (~500/day for consumer, ~2000/day for Workspace). At 50 filings/day, well within limits. Add 1-2 second delay between sends to be safe.

**Interface:**
```python
# notifier/gmail_notifier.py
class GmailNotifier:
    def __init__(self, sender_email: str, app_password: str, recipient_email: str):
        ...

    async def send(self, filing: Filing, analysis: AnalysisResult) -> bool:
        """Send analysis email for a filing. Returns True if sent successfully."""
        ...

    def _format_email(self, filing: Filing, analysis: AnalysisResult) -> MIMEMultipart:
        """Format filing analysis into HTML email."""
        ...
```

**Confidence:** HIGH -- Gmail SMTP with app passwords is well-documented and stable.

---

## Data Flow Detail

### Data Types Moving Between Components

```
Scraper ──[list[Filing]]──> Orchestrator
                                |
                    State Store <──[filing_ids]──> filter
                                |
                          [list[Filing]] (new only)
                                |
                    +-----------+-----------+
                    |                       |
               Downloader              (waits)
                    |
              [list[Path]]  (PDF file paths)
                    |
               Analyzer
                    |
            [AnalysisResult]
                    |
               Notifier
                    |
              [email sent]
                    |
              State Store  (mark processed)
```

### Filing Data Model (Central Data Structure)

```python
@dataclass
class Filing:
    """Core data object that flows through the entire pipeline."""
    id: str                    # REGDOCS filing ID
    title: str                 # Filing title
    date: datetime             # Filing date
    filing_url: str            # URL to filing page on REGDOCS
    pdf_urls: list[str]        # URLs to download PDFs
    applicant: str | None      # Company/applicant name
    category: str | None       # Filing category (application, decision, etc.)
    description: str | None    # Brief description if available

@dataclass
class ProcessedFiling:
    """Filing enriched with processing results."""
    filing: Filing
    pdf_paths: list[Path]      # Local paths to downloaded PDFs
    analysis: AnalysisResult   # Claude analysis output
    email_sent: bool           # Whether notification was sent
    processed_at: datetime     # When processing completed
```

---

## Directory Structure

```
cer_repository_scrapper/
    main.py                          # Entry point + scheduler loop
    config.py                        # Configuration (env vars, paths, URLs)

    scraper/
        __init__.py
        regdocs_scraper.py           # Playwright-based REGDOCS scraper
        models.py                    # Filing dataclass and related models

    downloader/
        __init__.py
        pdf_downloader.py            # PDF download + file management

    analyzer/
        __init__.py
        claude_analyzer.py           # Claude CLI subprocess wrapper
        prompts/
            analysis_prompt.md       # Analysis prompt template (iterable)

    notifier/
        __init__.py
        gmail_notifier.py            # Gmail SMTP email sender
        templates/
            filing_email.html        # Email HTML template

    storage/
        __init__.py
        state_store.py               # SQLite state tracking
        migrations/                  # DB schema migrations (if needed later)

    pipeline/
        __init__.py
        orchestrator.py              # Pipeline coordination logic

    data/                            # Runtime data (gitignored)
        filings/                     # Downloaded PDFs organized by filing
        db/
            state.db                 # SQLite database
        logs/
            pipeline.log             # Run logs

    tests/
        test_scraper.py
        test_downloader.py
        test_analyzer.py
        test_notifier.py
        test_state_store.py
        test_orchestrator.py
```

---

## Configuration Architecture

**Pattern:** Single `config.py` that reads from environment variables with sensible defaults. Use a `.env` file for secrets (gitignored).

```python
# config.py
from pathlib import Path
from dataclasses import dataclass, field
import os

@dataclass
class Config:
    # REGDOCS
    regdocs_base_url: str = "https://apps.cer-rec.gc.ca/REGDOCS"
    regdocs_recent_filings_path: str = "/Search/RecentFilings"
    scrape_pages: int = 1  # How many pages of recent filings to scrape

    # Paths
    data_dir: Path = field(default_factory=lambda: Path("data"))
    db_path: Path = field(default_factory=lambda: Path("data/db/state.db"))

    # Analyzer
    analysis_prompt_path: Path = field(default_factory=lambda: Path("analyzer/prompts/analysis_prompt.md"))
    analysis_timeout_seconds: int = 300

    # Gmail
    gmail_sender: str = os.getenv("GMAIL_SENDER", "")
    gmail_app_password: str = os.getenv("GMAIL_APP_PASSWORD", "")
    gmail_recipient: str = os.getenv("GMAIL_RECIPIENT", "")

    # Scheduler
    run_interval_seconds: int = 7200  # 2 hours

    # Rate limiting
    scrape_delay_seconds: float = 2.0  # Delay between page navigations
    email_delay_seconds: float = 1.0   # Delay between email sends
```

**.env file (gitignored):**
```
GMAIL_SENDER=your.email@gmail.com
GMAIL_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
GMAIL_RECIPIENT=recipient@email.com
```

---

## Patterns to Follow

### Pattern 1: Per-Filing Error Isolation

**What:** Never let one filing's failure crash the pipeline or prevent other filings from being processed.

**Why:** Government PDFs can be malformed, sites can timeout, Claude CLI can hang. Each filing is independent.

**Implementation:**
```python
for filing in new_filings:
    try:
        await self._process_filing(filing)
    except Exception as e:
        logger.error(f"Filing {filing.id} failed: {e}")
        self.state_store.mark_failed(filing.id, str(e))
        continue  # Next filing
```

### Pattern 2: Idempotent Runs

**What:** Running the pipeline twice with no new filings should be a no-op. Running it after a partial failure should only process the filings that failed or were not reached.

**Why:** The 2-hour schedule means the pipeline runs 12 times/day. It must be safe to run repeatedly.

**Implementation:** Always check state store before processing. Only mark as processed AFTER successful email send.

### Pattern 3: Structured Logging

**What:** Every pipeline run produces structured log output showing what was found, what was new, what succeeded, what failed.

**Why:** When running unattended every 2 hours, you need to diagnose issues from logs alone.

**Implementation:**
```python
import logging

logger = logging.getLogger("cer_pipeline")

# At run start
logger.info(f"Pipeline run started", extra={"run_id": run_id})

# At run end
logger.info(f"Pipeline run complete", extra={
    "run_id": run_id,
    "total_filings": 42,
    "new_filings": 3,
    "processed_ok": 2,
    "processed_failed": 1,
    "duration_seconds": 145.3,
})
```

### Pattern 4: Graceful Playwright Lifecycle

**What:** Launch browser once per pipeline run, reuse across all page navigations, ensure cleanup even on failure.

**Why:** Browser launch is expensive. Leaked browser processes are a common scraper bug.

**Implementation:**
```python
async def scrape_recent_filings(self) -> list[Filing]:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            # ... all scraping work ...
        finally:
            await browser.close()
```

---

## Anti-Patterns to Avoid

### Anti-Pattern 1: God Orchestrator

**What:** Putting all logic (scraping, downloading, analyzing, emailing) into one giant function or class.

**Why bad:** Untestable, unmodifiable, error handling becomes spaghetti.

**Instead:** Each component is its own module with a clean interface. The orchestrator only coordinates.

### Anti-Pattern 2: In-Memory State Only

**What:** Tracking processed filings in a Python set/dict that is lost on restart.

**Why bad:** Every restart reprocesses everything. Users get duplicate emails. Claude CLI costs are wasted.

**Instead:** SQLite state store persists across restarts.

### Anti-Pattern 3: Monolithic Error Handling

**What:** Wrapping the entire pipeline in one try/except.

**Why bad:** One filing's PDF download failure kills analysis and notification for all other filings in the batch.

**Instead:** Per-filing try/except with individual failure tracking.

### Anti-Pattern 4: Hardcoded Analysis Prompts

**What:** Embedding the Claude analysis prompt as a string literal in the analyzer code.

**Why bad:** Prompt engineering is iterative. You will change the prompt 50 times. Editing Python code to change a prompt is error-prone and makes diffs noisy.

**Instead:** Store prompt as a markdown template file. Read at runtime.

### Anti-Pattern 5: Synchronous Playwright

**What:** Using `sync_playwright()` instead of `async_playwright()`.

**Why bad:** Blocks the entire process during page loads and navigation. While parallelism is not required at current volume, async allows the subprocess-based analyzer to coexist cleanly with the scraper in the same event loop.

**Instead:** Use `async_playwright()` and `asyncio` throughout.

---

## Build Order (Dependency-Driven)

The build order is determined by component dependencies. You cannot test downstream components without upstream ones working first.

```
Phase 1: Foundation (no external dependencies between components)
  [1] State Store (SQLite)     -- standalone, testable in isolation
  [2] Config + Models          -- data structures everything depends on

Phase 2: Data Acquisition (requires Config + Models)
  [3] Scraper (Playwright)     -- requires REGDOCS site access
  [4] Downloader (PDF fetch)   -- requires Scraper output format

Phase 3: Processing (requires downloaded PDFs)
  [5] Analyzer (Claude CLI)    -- requires actual PDF files to analyze

Phase 4: Delivery (requires analysis output)
  [6] Notifier (Gmail)         -- requires analysis results to email

Phase 5: Integration (requires all components)
  [7] Orchestrator             -- wires everything together
  [8] Scheduler                -- triggers orchestrator on interval
```

### Why This Order

| Order | Component | Depends On | Rationale |
|-------|-----------|------------|-----------|
| 1 | State Store | Nothing | Foundation. Can be built and tested with fake data. Every other component needs it. |
| 2 | Config + Models | Nothing | Data structures (`Filing`, `Config`) that every component imports. Must be stable early. |
| 3 | Scraper | Config, Models | First point of contact with external world. Validates that we CAN get data from REGDOCS. Highest technical risk component -- if scraping does not work, nothing else matters. |
| 4 | Downloader | Models, Scraper output | Straightforward once we have filing URLs. Low risk. |
| 5 | Analyzer | Models, downloaded PDFs | Requires actual PDFs to test. Validates Claude CLI integration. Second highest risk component (subprocess management, prompt engineering). |
| 6 | Notifier | Models, analysis output | Requires analysis results to format emails. Low risk. |
| 7 | Orchestrator | All components | Integration layer. Cannot be meaningfully built until components exist. |
| 8 | Scheduler | Orchestrator | Trivial wrapper. Last because it is the least risky and least interesting. |

### Risk-Ordered Build Justification

The order also reflects **risk mitigation** -- build the riskiest components first:

1. **Scraper (HIGH RISK):** The CER site is JS-rendered with no documented API. The scraping approach (DOM parsing vs API interception) can only be validated by actually examining the site with Playwright. If scraping fails fundamentally, the project approach needs to change.

2. **Analyzer (MEDIUM RISK):** Claude CLI subprocess invocation needs to be prototyped. Questions: How does `claude -p` handle PDF input? What are the timeout characteristics? What output format is most reliable?

3. **Everything else (LOW RISK):** SQLite state tracking, PDF downloading, Gmail sending, and pipeline orchestration are all well-established patterns with minimal uncertainty.

---

## Scalability Considerations

| Concern | At 10 filings/day (current) | At 100 filings/day | At 1000 filings/day |
|---------|---------------------------|--------------------|--------------------|
| Processing time | ~10 min/run | ~100 min/run (tight) | Exceeds 2hr window |
| Storage | ~50 MB/day | ~500 MB/day | Need cleanup policy |
| Email volume | Manageable | Approaching Gmail limits | Need email digest mode |
| Claude CLI cost | Subscription covers | May hit rate limits | Need API migration |
| SQLite | Fine | Fine | Fine (still tiny) |

**At current scale (10-50/day), sequential processing is correct.** Do not prematurely optimize with async queues, worker pools, or message brokers. If volume grows 10x, the main bottleneck will be Claude CLI analysis time, and the solution is parallelizing analyzer subprocess calls -- a localized change that does not require rearchitecting.

---

## Testing Strategy (Architecture Implications)

The component boundary design enables clean testing:

| Component | Test Approach | External Dependency |
|-----------|--------------|---------------------|
| State Store | Unit test with in-memory SQLite | None |
| Scraper | Integration test with Playwright against live site; unit test with saved HTML fixtures | CER website |
| Downloader | Unit test with mock HTTP; integration test with real PDF URL | HTTP |
| Analyzer | Unit test with mock subprocess; integration test with real Claude CLI + small PDF | Claude CLI |
| Notifier | Unit test with mock SMTP; manual integration test | Gmail SMTP |
| Orchestrator | Unit test with all mocked components | None |

**Key testing insight:** Save HTML snapshots of REGDOCS pages and PDF samples during development. Use these as test fixtures so tests do not depend on the live site.

---

## Sources and Confidence

| Claim | Confidence | Basis |
|-------|------------|-------|
| SQLite for local state tracking | HIGH | Standard pattern, Python stdlib support |
| Playwright async for JS rendering | HIGH | Well-established for this exact use case |
| Per-filing error isolation pattern | HIGH | Standard ETL pipeline pattern |
| Sequential processing sufficient at volume | HIGH | Simple math: 50 filings * 60s = 50 min < 120 min window |
| Claude CLI subprocess invocation details | MEDIUM | Approach is sound but exact flags need validation |
| REGDOCS page structure and API endpoints | LOW | Not verified -- needs Phase 1 exploration |
| Gmail sending limits | MEDIUM | Training data; should verify current limits |
| Directory structure recommendation | HIGH | Standard Python project layout |

**Overall Architecture Confidence: MEDIUM-HIGH** -- The pipeline pattern is proven and low-risk. The main uncertainty is the REGDOCS scraping layer (site structure unknown until explored) and Claude CLI integration details.

---

## Open Questions for Implementation

1. **Does REGDOCS expose internal API endpoints?** If yes, the scraper can use `httpx` for JSON API calls instead of DOM parsing, which is more reliable and faster. Explore with Playwright network interception in Phase 1.

2. **How does `claude -p` handle PDF files?** Can it read PDFs directly by path? Does it need the `--file` flag? What is the maximum PDF size it handles? Prototype in Phase 1.

3. **What metadata is available on the filing list page vs the detail page?** This determines whether the scraper needs one-phase or two-phase navigation. Explore in Phase 1.

4. **Pagination behavior on recent filings page?** How many filings per page? Is `?p=1` the correct pagination parameter? What is the date range of "recent"? Explore in Phase 1.
