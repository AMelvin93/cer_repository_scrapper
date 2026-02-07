# Phase 2: REGDOCS Scraper - Research

**Researched:** 2026-02-07
**Domain:** Web scraping, Playwright network interception, CER REGDOCS site structure
**Confidence:** MEDIUM (site structure requires runtime discovery; library choices HIGH confidence)

## Summary

Phase 2 builds a scraper that discovers and retrieves filing metadata from the Canada Energy Regulator's REGDOCS website. The REGDOCS site is built on OpenText Content Server (formerly Livelink) and uses JavaScript-driven dynamic content loading -- the "Recent Filings" page shows a "Loading..." placeholder until JavaScript populates filing data via background network requests. This confirms that Playwright network interception is the correct approach: the browser must execute JavaScript to trigger the API calls, and Playwright can capture those calls to discover endpoint patterns.

The standard stack uses Playwright (sync API) for browser automation and network interception, httpx for direct API calls once endpoints are discovered, BeautifulSoup4 with lxml for DOM parsing fallback, tenacity for retry logic with exponential backoff, and Python's built-in urllib.robotparser for robots.txt compliance. Pydantic models validate scraped data before it reaches the SQLAlchemy state store.

The core technical risk is that REGDOCS' internal API structure is unknown and must be discovered at runtime. The "Loading..." behavior on filing pages strongly suggests XHR/fetch calls to internal endpoints that return structured data (likely JSON). Playwright's `page.on("response")` event listener will capture these calls during page navigation, and the scraper will parse the response bodies to extract filing metadata. If no usable API endpoints are found, the fallback DOM parsing path uses BeautifulSoup on the fully-rendered Playwright page content.

**Primary recommendation:** Use Playwright sync API for browser automation (simpler than async for this use case), capture all network responses during RecentFilings page navigation to discover API endpoints, then use httpx for subsequent direct API calls. Structure the scraper as a two-strategy system: API-first with DOM-parsing fallback, both producing the same Pydantic `ScrapedFiling` output model.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Use Playwright automated network interception to discover REGDOCS API endpoints at runtime
- Discover endpoints fresh every run (no caching of discovered endpoints between runs)
- If interception finds no usable API endpoints, retry 2-3 times with different page navigations before falling back to DOM parsing
- Both API and DOM parsing paths should be robust, first-class strategies -- either could serve as primary depending on what REGDOCS exposes
- Configurable lookback period for how far back each run searches (default TBD during planning)
- Configurable filing type filter -- default to all types, allow include/exclude list in config
- Configurable applicant/company and proceeding number filters in config
- Deduplication: check state store before processing; skip filings already processed successfully
- Randomized delays between 1-3 seconds per request to appear natural
- 3 retries with exponential backoff on HTTP errors/timeouts, then log failure and move on
- Zero-filing warning after 3 consecutive runs -- log warning only (monitoring/alerting deferred to Phase 10)
- Validation checks after each scrape: verify expected fields present and values in reasonable ranges; log detailed errors if validation fails (detects site structure changes)
- Skip filings entirely if they have no document URLs -- nothing to analyze means nothing to report
- Capture all document URLs associated with a filing (multiple PDFs, appendices, etc.)
- Capture URLs for all document types (PDFs, Word docs, Excel, etc.) -- not just PDFs
- Filings with at least one document URL but missing other metadata: store with placeholders (e.g., "Unknown" applicant) -- LLM analysis may extract missing info from document content

### Claude's Discretion
- Partial metadata handling: define minimum required fields vs. placeholder strategy
- Specific Playwright interception implementation details
- Exact exponential backoff timing
- Default lookback period value
- robots.txt parsing implementation

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope
</user_constraints>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| playwright | >=1.58.0 | Browser automation, network interception | Only reliable way to capture JS-loaded API calls from SPAs; Chromium headless mode; Python sync and async APIs |
| httpx | >=0.28.1 | Direct HTTP client for discovered API endpoints | Modern async-capable HTTP client; cleaner API than requests; built-in timeout support |
| beautifulsoup4 | >=4.14.3 | DOM parsing fallback strategy | Industry standard HTML parser; pairs with lxml for speed |
| lxml | >=5.0.0 | Fast HTML parser backend for BeautifulSoup | Significantly faster than html.parser; handles malformed HTML |
| tenacity | >=9.1.3 | Retry logic with exponential backoff | De facto Python retry library; decorator-based; supports async |
| pydantic | >=2.0 | Scraper output validation | Already in project (via pydantic-settings); validates scraped data before DB insertion |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| urllib.robotparser | stdlib | robots.txt parsing and compliance | Every run, before any requests; checks if scraping is allowed |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| httpx | requests | requests lacks native async; httpx is more modern with similar API |
| beautifulsoup4 | selectolax/parsel | BS4 is more widely known, better documented; performance difference irrelevant at this scale |
| tenacity | hand-rolled retry | tenacity handles edge cases (jitter, logging, async) that hand-rolled misses |
| Playwright sync | Playwright async | Sync is simpler for this use case; scraper is inherently sequential (one page at a time with delays) |

**Installation:**
```bash
uv add playwright httpx beautifulsoup4 lxml tenacity
uv run playwright install chromium
```

Note: `pydantic` is already available (transitive dependency of `pydantic-settings`). The `playwright install chromium` command downloads the Chromium browser binary (~150MB) which is required for headless browsing.

## Architecture Patterns

### Recommended Project Structure
```
src/cer_scraper/
    scraper/
        __init__.py          # Public API: scrape_recent_filings()
        discovery.py         # Playwright network interception, endpoint discovery
        api_client.py        # httpx-based API client for discovered endpoints
        dom_parser.py        # BeautifulSoup DOM parsing fallback
        models.py            # Pydantic models: ScrapedFiling, ScrapedDocument
        robots.py            # robots.txt compliance checker
        rate_limiter.py      # Delay/throttle logic (randomized 1-3s)
```

### Pattern 1: Two-Strategy Scraper with Shared Output Model

**What:** Both the API discovery path and DOM parsing path produce the same `ScrapedFiling` Pydantic model. The orchestrator tries API-first, falls back to DOM parsing, and the downstream code never knows which strategy produced the data.

**When to use:** Always -- this is the core architecture.

**Example:**
```python
# src/cer_scraper/scraper/models.py
from pydantic import BaseModel, Field
from datetime import date
from typing import Optional

class ScrapedDocument(BaseModel):
    """A single document URL discovered during scraping."""
    url: str
    filename: Optional[str] = None
    content_type: Optional[str] = None  # e.g., "application/pdf", "application/msword"

class ScrapedFiling(BaseModel):
    """Validated output from either API or DOM scraping strategy."""
    filing_id: str
    date: Optional[date] = None
    applicant: Optional[str] = None
    filing_type: Optional[str] = None
    proceeding_number: Optional[str] = None
    title: Optional[str] = None
    url: Optional[str] = None
    documents: list[ScrapedDocument] = Field(default_factory=list)

    @property
    def has_documents(self) -> bool:
        return len(self.documents) > 0
```

### Pattern 2: Network Interception for API Discovery

**What:** Use Playwright's `page.on("response")` to capture all XHR/fetch responses during page navigation, filter for JSON responses, and identify API endpoints that return filing data.

**When to use:** First strategy on every run.

**Example:**
```python
# src/cer_scraper/scraper/discovery.py
from playwright.sync_api import sync_playwright, Response
import json
import logging

logger = logging.getLogger(__name__)

def discover_api_endpoints(base_url: str, user_agent: str) -> list[dict]:
    """Navigate REGDOCS and capture API responses containing filing data."""
    captured_responses: list[dict] = []

    def handle_response(response: Response) -> None:
        """Callback for page.on('response') -- captures JSON API responses."""
        content_type = response.headers.get("content-type", "")
        if "json" in content_type or "xml" in content_type:
            try:
                body = response.json()
                captured_responses.append({
                    "url": response.url,
                    "status": response.status,
                    "body": body,
                })
                logger.info("Captured API response: %s (status %d)", response.url, response.status)
            except Exception:
                pass  # Not valid JSON despite content-type

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=user_agent)
        page = context.new_page()
        page.on("response", handle_response)

        # Navigate to Recent Filings -- triggers JS to load data
        page.goto(f"{base_url}/Search/RecentFilings?p=1")
        page.wait_for_load_state("networkidle")

        # Also try other time periods to capture different endpoints
        page.goto(f"{base_url}/Search/RecentFilings?p=2")
        page.wait_for_load_state("networkidle")

        browser.close()

    return captured_responses
```

### Pattern 3: DOM Parsing Fallback

**What:** If no API endpoints are discovered, parse the fully-rendered HTML from Playwright's page content using BeautifulSoup.

**When to use:** When API discovery fails after retries.

**Example:**
```python
# src/cer_scraper/scraper/dom_parser.py
from bs4 import BeautifulSoup
from .models import ScrapedFiling, ScrapedDocument
import logging

logger = logging.getLogger(__name__)

def parse_filings_from_html(html: str) -> list[ScrapedFiling]:
    """Parse filing metadata from rendered REGDOCS HTML."""
    soup = BeautifulSoup(html, "lxml")
    filings: list[ScrapedFiling] = []

    # Actual selectors must be discovered at runtime -- these are patterns
    for row in soup.select("table tr, .filing-item, [data-filing-id]"):
        # Extract metadata from DOM elements
        # Selectors will be determined during implementation based on actual page structure
        pass

    return filings
```

### Pattern 4: Scraper Configuration Extension

**What:** Extend the existing `ScraperSettings` pydantic-settings model with new fields for Phase 2 requirements.

**When to use:** Configuration for all scraper behavior.

**Example:**
```python
# New fields to add to ScraperSettings in config/settings.py
class ScraperSettings(BaseSettings):
    # Existing fields...
    base_url: str = "https://apps.cer-rec.gc.ca/REGDOCS"
    recent_filings_path: str = "/Search/RecentFilings"
    delay_seconds: float = 2.0           # existing -- still used as base
    pages_to_scrape: int = 1
    user_agent: str = "CER-Filing-Monitor/1.0"

    # New Phase 2 fields
    delay_min_seconds: float = 1.0       # Minimum random delay
    delay_max_seconds: float = 3.0       # Maximum random delay
    lookback_period: str = "week"        # "day", "week", "month"
    max_retries: int = 3                 # HTTP retry count
    backoff_base: float = 2.0            # Exponential backoff base
    backoff_max: float = 30.0            # Max backoff delay in seconds
    discovery_retries: int = 3           # API discovery attempts before DOM fallback
    filing_type_include: list[str] = []  # Empty = all types
    filing_type_exclude: list[str] = []  # Exclude these types
    applicant_filter: list[str] = []     # Filter by applicant (empty = all)
    proceeding_filter: list[str] = []    # Filter by proceeding number (empty = all)
```

### Pattern 5: Deduplication via State Store

**What:** Check `filing_exists()` in the state store before processing each scraped filing. This integrates directly with the Phase 1 state store.

**When to use:** After scraping, before creating new Filing records.

**Example:**
```python
from cer_scraper.db.state import filing_exists, create_filing
from cer_scraper.db.models import Document

def persist_new_filings(session, scraped_filings: list[ScrapedFiling]) -> int:
    """Store only new filings in the database. Returns count of new filings."""
    new_count = 0
    for sf in scraped_filings:
        if filing_exists(session, sf.filing_id):
            continue
        filing = create_filing(
            session,
            filing_id=sf.filing_id,
            date=sf.date,
            applicant=sf.applicant or "Unknown",
            filing_type=sf.filing_type,
            proceeding_number=sf.proceeding_number,
            title=sf.title,
            url=sf.url,
        )
        # Create Document records for each document URL
        for doc in sf.documents:
            document = Document(
                filing_id=filing.id,
                document_url=doc.url,
                filename=doc.filename,
                content_type=doc.content_type,
            )
            session.add(document)
        session.commit()
        new_count += 1
    return new_count
```

### Anti-Patterns to Avoid
- **Hardcoded CSS selectors without validation:** REGDOCS can change its DOM structure at any time. Always validate that expected elements exist before extracting data, and log clear errors when selectors fail.
- **Blocking on API discovery:** Don't make the entire scraper fail if API discovery returns nothing. The DOM parsing path must be equally robust.
- **Ignoring network idle state:** Don't scrape the page immediately after goto(). The page shows "Loading..." initially -- you must wait for `networkidle` or content-specific selectors.
- **Sharing Playwright browser across runs:** Launch and close the browser within each scrape run. Don't keep a persistent browser instance between pipeline runs.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Retry with backoff | Custom while-loop retry | tenacity `@retry` decorator | Handles jitter, logging, exception filtering, max attempts; battle-tested |
| robots.txt parsing | Custom text parser | `urllib.robotparser.RobotFileParser` | Stdlib, handles all directive types, well-tested |
| HTML parsing | Regex on HTML strings | BeautifulSoup4 with lxml | HTML is not regular; BS4 handles malformed markup correctly |
| Browser automation | Raw Selenium/CDP | Playwright | Modern API, auto-waits, built-in network interception, faster than Selenium |
| Data validation | Manual dict checks | Pydantic BaseModel | Type coercion, validation errors, serialization all handled |
| HTTP client | urllib3 directly | httpx | Higher-level API, async support, timeout handling, connection pooling |
| Random delays | `time.sleep(random.uniform())` everywhere | Centralized rate limiter function | Single place to change delay logic, logging, testability |

**Key insight:** The biggest hand-rolling risk is retry logic. A naive retry loop misses: jitter (thundering herd), proper backoff calculation, exception type filtering, logging before retry, and async support. Use tenacity.

## Common Pitfalls

### Pitfall 1: Race Condition in Network Interception
**What goes wrong:** Setting up `page.on("response")` after `page.goto()` means early API responses are missed.
**Why it happens:** The page starts loading immediately on goto(), and fast responses arrive before the listener is registered.
**How to avoid:** Always register `page.on("response")` BEFORE calling `page.goto()`.
**Warning signs:** Intermittent empty API discovery results.

### Pitfall 2: Playwright Browser Not Installed
**What goes wrong:** `playwright install chromium` was never run, causing "Browser not found" errors.
**Why it happens:** pip/uv installs the Python package but not the browser binary.
**How to avoid:** Add `playwright install chromium` as a documented setup step. Consider checking browser availability at scraper startup and logging a clear error.
**Warning signs:** `BrowserType.launch: Executable doesn't exist` error.

### Pitfall 3: REGDOCS "Loading..." State
**What goes wrong:** Scraping returns empty results because the page content hasn't loaded yet.
**Why it happens:** REGDOCS uses JavaScript to dynamically populate filing data. The initial HTML contains only a "Loading..." placeholder.
**How to avoid:** Use `page.wait_for_load_state("networkidle")` and/or `page.wait_for_selector()` targeting filing content elements. Set a reasonable timeout (30s) with clear error messages.
**Warning signs:** All filings have empty metadata or zero filings found.

### Pitfall 4: OpenText Content Server Session/Cookie Requirements
**What goes wrong:** Direct API calls with httpx fail with 401/403 errors even after discovering valid endpoints.
**Why it happens:** REGDOCS (OpenText Content Server) may require session cookies or CSRF tokens for API access that were set during the Playwright browser session.
**How to avoid:** When switching from Playwright discovery to httpx API calls, extract cookies from the Playwright browser context and pass them to httpx. Consider doing everything within Playwright if cookie management is too complex.
**Warning signs:** API calls return HTML login pages or error responses instead of JSON.

### Pitfall 5: Stale Selectors After Site Update
**What goes wrong:** DOM parsing stops working after a REGDOCS site update changes the HTML structure.
**Why it happens:** CSS selectors are fragile -- any site redesign breaks them.
**How to avoid:** Implement the validation checks (required by user decision): verify expected fields present and values in reasonable ranges after each scrape. Log detailed errors if validation fails. The zero-filing warning (3 consecutive runs) also catches this.
**Warning signs:** Zero filings returned, partial metadata, validation errors in logs.

### Pitfall 6: robots.txt Typo on CER Site
**What goes wrong:** The CER's robots.txt at www.cer-rec.gc.ca contains "Dissallow" (misspelled) instead of "Disallow" for the catch-all rules.
**Why it happens:** Typo in the site's robots.txt file.
**How to avoid:** Python's `urllib.robotparser` will not recognize "Dissallow" as a valid directive, effectively treating those rules as non-existent. This means the parser will allow access to paths that were intended to be blocked. For our scraper, this is actually fine -- the REGDOCS app is at a different subdomain (apps.cer-rec.gc.ca) and the robots.txt there returns 404, meaning no restrictions. Still check `apps.cer-rec.gc.ca/robots.txt` every run for compliance.
**Warning signs:** None -- just document the behavior.

### Pitfall 7: Playwright on Windows -- Event Loop Conflicts
**What goes wrong:** Playwright sync API works fine, but if mixed with asyncio (e.g., if httpx is used with async), Windows may have event loop issues.
**Why it happens:** Windows uses `ProactorEventLoop` by default, and mixing sync Playwright with async httpx in the same thread can cause conflicts.
**How to avoid:** Use Playwright sync API and httpx sync API consistently. Don't mix sync and async patterns in the scraper. The scraper is inherently sequential (polite delays between requests), so async provides no benefit.
**Warning signs:** `RuntimeError: This event loop is already running` or similar asyncio errors.

## Code Examples

### Verified: Playwright Network Interception (from official docs)
```python
# Source: https://playwright.dev/python/docs/network
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        user_agent="CER-Filing-Monitor/1.0 (+https://github.com/user/repo)"
    )
    page = context.new_page()

    # Register listener BEFORE navigation
    captured = []
    page.on("request", lambda req: print(f">> {req.method} {req.url}"))
    page.on("response", lambda resp: captured.append(resp) if resp.ok else None)

    page.goto("https://apps.cer-rec.gc.ca/REGDOCS/Search/RecentFilings?p=1")
    page.wait_for_load_state("networkidle")

    # Process captured responses
    for resp in captured:
        ct = resp.headers.get("content-type", "")
        if "json" in ct:
            data = resp.json()
            print(f"JSON endpoint: {resp.url}")
            print(f"Data keys: {data.keys() if isinstance(data, dict) else 'array'}")

    # Get rendered HTML for DOM fallback
    html = page.content()

    browser.close()
```

### Verified: Tenacity Retry with Exponential Backoff (from official docs)
```python
# Source: https://tenacity.readthedocs.io/
import logging
from tenacity import (
    retry,
    stop_after_attempt,
    wait_random_exponential,
    before_sleep_log,
    retry_if_exception_type,
)
import httpx

logger = logging.getLogger(__name__)

@retry(
    stop=stop_after_attempt(3),
    wait=wait_random_exponential(multiplier=1, min=2, max=30),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TimeoutException)),
)
def fetch_api_endpoint(client: httpx.Client, url: str) -> dict:
    """Fetch JSON from a discovered API endpoint with retry logic."""
    response = client.get(url)
    response.raise_for_status()
    return response.json()
```

### Verified: robots.txt Compliance (from Python docs)
```python
# Source: https://docs.python.org/3/library/urllib.robotparser.html
import urllib.robotparser
import logging

logger = logging.getLogger(__name__)

def check_robots_txt(base_url: str, user_agent: str, target_path: str) -> bool:
    """Check if scraping the target URL is allowed by robots.txt."""
    rp = urllib.robotparser.RobotFileParser()
    robots_url = f"{base_url}/robots.txt"
    rp.set_url(robots_url)

    try:
        rp.read()
    except Exception as e:
        # robots.txt not found or unreadable -- assume allowed (standard practice)
        logger.warning("Could not read robots.txt at %s: %s", robots_url, e)
        return True

    target_url = f"{base_url}{target_path}"
    allowed = rp.can_fetch(user_agent, target_url)

    # Check for crawl delay directive
    crawl_delay = rp.crawl_delay(user_agent)
    if crawl_delay:
        logger.info("robots.txt specifies crawl delay: %s seconds", crawl_delay)

    return allowed
```

### Verified: httpx Client with Custom Headers
```python
# Source: https://www.python-httpx.org/
import httpx

def create_api_client(user_agent: str, timeout: float = 30.0) -> httpx.Client:
    """Create an httpx client configured for REGDOCS API calls."""
    return httpx.Client(
        headers={
            "User-Agent": user_agent,
            "Accept": "application/json",
        },
        timeout=httpx.Timeout(timeout),
        follow_redirects=True,
    )
```

### Zero-Filing Consecutive Run Tracking
```python
# Pattern for tracking consecutive zero-filing runs
# Uses the RunHistory table from Phase 1
from cer_scraper.db.models import RunHistory
from sqlalchemy import select, desc

def check_consecutive_zero_runs(session, threshold: int = 3) -> bool:
    """Check if the last N runs all found zero new filings."""
    stmt = (
        select(RunHistory)
        .order_by(desc(RunHistory.started_at))
        .limit(threshold)
    )
    recent_runs = list(session.scalars(stmt).all())

    if len(recent_runs) < threshold:
        return False

    return all(run.new_filings == 0 for run in recent_runs)
```

## REGDOCS Site Structure (Research Findings)

### Confirmed Facts (HIGH confidence)
- **Technology:** Built on OpenText Content Server (formerly Livelink/CS-10)
- **Base URL:** `https://apps.cer-rec.gc.ca/REGDOCS`
- **Recent Filings URL:** `/Search/RecentFilings?p=1` (p=1: today, p=2: week, p=3: month)
- **Filing page URL pattern:** `/Item/Filing/{filing_id}` (e.g., `/Item/Filing/C33255`)
- **Document view URL pattern:** `/Item/View/{document_id}` (e.g., `/Item/View/4642764`)
- **Dynamic loading:** Pages show "Loading..." initially; content populated via JavaScript
- **robots.txt:** 404 at `apps.cer-rec.gc.ca/robots.txt` (no restrictions for this subdomain)
- **robots.txt at www.cer-rec.gc.ca:** Exists but has typos ("Dissallow"), blocks specific bots by name, no crawl-delay set

### Confirmed URL Parameters (from observed search URLs)
| Parameter | Meaning | Example |
|-----------|---------|---------|
| `p` | Time period (RecentFilings) | 1=today, 2=week, 3=month |
| `sr` | Search results flag | `sr=1` |
| `loc` | Location/folder ID | `loc=4176267` |
| `srt` | Sort order | `srt=0` |
| `isc` | Include sub-categories | `isc=True` |
| `iscd` | Include sub-categories descendants | `iscd=True` |
| `filter` | Filter attribute | `filter=OTCreateDate`, `filter=OTFileType` |
| `ft` | File type code | `ft=75` |
| `rl` | Role filter | `rl=1` |
| `dn` | Document number | `dn=A3F5Q2` |

### Metadata Fields Available (from REGDOCS help page)
| Field | Description | In Filing Model |
|-------|-------------|-----------------|
| Filing ID | Unique identifier (e.g., C33255, A98873) | `filing_id` |
| Filing Date | Date document was filed | `date` |
| Applicant/Submitter | Company or person who filed | `applicant` |
| Filing/Document Type | Category (application, compliance report, etc.) | `filing_type` |
| Proceeding Number | Regulatory proceeding reference | `proceeding_number` |
| Document Name/Title | Descriptive title of the filing | `title` |
| Document URLs | Links to individual documents (PDF, Word, etc.) | via `documents` relationship |

### What Must Be Discovered at Runtime (MEDIUM confidence)
- Exact API endpoint URLs used by the JavaScript frontend
- JSON response structure (field names, nesting, pagination)
- Whether session cookies are required for API access
- Whether the API supports date-range filtering directly
- Actual CSS selectors for DOM parsing fallback (depends on rendered HTML structure)

### Default Lookback Period Recommendation
Use **"week"** (p=2) as the default lookback period. Rationale:
- "day" (p=1) may miss filings if the scraper runs less frequently than daily
- "month" (p=3) is too broad for a scraper running every 2 hours (Phase 10 target)
- "week" provides a good balance: catches filings even with 1-2 day gaps between runs
- With deduplication, re-scraping already-seen filings costs only a state store lookup

### Minimum Required Fields Recommendation
Define the minimum viable filing as:
- **Required:** `filing_id` (must be non-empty, must be unique)
- **Required:** At least one document URL (`documents` list must be non-empty -- per user decision, skip filings with no documents)
- **Placeholder-eligible:** `date`, `applicant`, `filing_type`, `proceeding_number`, `title`, `url`

Use these placeholders for missing metadata:
- `applicant`: "Unknown"
- `filing_type`: "Unknown"
- `proceeding_number`: None (nullable in DB)
- `title`: None (nullable in DB)
- `date`: None (nullable in DB)
- `url`: Constructed from filing_id if not directly available

### Exponential Backoff Timing Recommendation
Use tenacity `wait_random_exponential(multiplier=1, min=2, max=30)`:
- Retry 1: ~2-4 seconds wait
- Retry 2: ~4-8 seconds wait
- Retry 3: ~8-16 seconds wait (capped at 30)
- Jitter prevents thundering herd if multiple scraper instances ever run

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Selenium for browser automation | Playwright | 2020+ | Faster, auto-waits, built-in network interception, better API |
| requests for HTTP | httpx | 2022+ | Async support, HTTP/2, better timeout handling |
| Manual retry loops | tenacity decorators | 2018+ | Cleaner code, configurable strategies, logging hooks |
| BeautifulSoup with html.parser | BeautifulSoup with lxml | Long-standing | 5-10x faster parsing, better malformed HTML handling |

**Note on Playwright sync vs async:** Playwright 1.58+ supports both sync and async Python APIs equally well. For this scraper, sync is recommended because:
1. The scraper is inherently sequential (polite delays between requests)
2. No I/O concurrency benefit (only one request in flight at a time)
3. Simpler code, easier debugging, no async/await boilerplate
4. Avoids Windows event loop complications

## Open Questions

1. **REGDOCS API Response Structure**
   - What we know: The site loads content dynamically via JS, strongly suggesting background API calls
   - What's unclear: The exact endpoint URLs, response format, and authentication requirements
   - Recommendation: The discovery module must handle this at runtime. First implementation should log ALL captured responses verbosely to aid debugging.

2. **Pagination in API vs. DOM**
   - What we know: Recent Filings has p=1/2/3 for time periods, and search results likely have pagination
   - What's unclear: Whether the internal API has its own pagination parameters
   - Recommendation: Start with single-page scraping, add pagination support once API structure is understood

3. **REGDOCS Rate Limiting**
   - What we know: No rate limiting observed in robots.txt; user decision mandates 1-3s delays
   - What's unclear: Whether REGDOCS has server-side rate limiting that returns 429 responses
   - Recommendation: Implement the 1-3s random delays as specified; handle 429 responses in retry logic

4. **Cookie/Session Transfer from Playwright to httpx**
   - What we know: OpenText Content Server typically requires session tokens
   - What's unclear: Whether REGDOCS public-facing pages require authentication for API calls
   - Recommendation: Implement cookie extraction from Playwright context as a precaution. If API calls work without cookies, the extraction is a no-op.

## Sources

### Primary (HIGH confidence)
- [Playwright Python Official Docs - Network](https://playwright.dev/python/docs/network) -- Network interception patterns, page.on("response"), sync/async examples
- [Playwright Python Official Docs - Library](https://playwright.dev/python/docs/library) -- Getting started, sync/async setup, browser launch options
- [Playwright Python Official Docs - Response Class](https://playwright.dev/python/docs/api/class-response) -- Response.json(), .text(), .body(), .url, .status, .ok
- [Playwright Python Official Docs - BrowserContext](https://playwright.dev/python/docs/api/class-browsercontext) -- Context creation, user_agent, route(), events
- [Tenacity Official Docs](https://tenacity.readthedocs.io/) -- Retry decorators, exponential backoff, async support
- [Python stdlib urllib.robotparser](https://docs.python.org/3/library/urllib.robotparser.html) -- RobotFileParser API, can_fetch(), crawl_delay()
- [PyPI - playwright 1.58.0](https://pypi.org/project/playwright/) -- Latest version, Python 3.9+ support
- [PyPI - tenacity 9.1.3](https://pypi.org/project/tenacity/) -- Latest version, Python 3.10+ support
- [PyPI - httpx 0.28.1](https://pypi.org/project/httpx/) -- Latest version, Python 3.8+ support
- [PyPI - beautifulsoup4 4.14.3](https://pypi.org/project/beautifulsoup4/) -- Latest version, Python 3.7+ support

### Secondary (MEDIUM confidence)
- [CER REGDOCS Help Page](https://www.cer-rec.gc.ca/en/applications-hearings/regulatory-document/help-browsing-regulatory-documents.html) -- Filing metadata fields, time period filters, search functionality
- [CER REGDOCS Homepage](https://apps.cer-rec.gc.ca/REGDOCS) -- URL structure, navigation links, page layout
- [CER robots.txt](https://www.cer-rec.gc.ca/robots.txt) -- Bot blocking rules, typo in directives, no crawl-delay
- WebFetch of REGDOCS filing page C33255 -- Confirmed "Loading..." dynamic content pattern
- WebFetch of REGDOCS Recent Filings -- Confirmed error page / dynamic loading behavior

### Tertiary (LOW confidence)
- [OpenText Wikipedia](https://en.wikipedia.org/wiki/OpenText) -- REGDOCS-Livelink/Content Server connection (corroborated by CER help docs calling it "CS-10" and "Livelink")
- WebSearch: OpenText Content Server REST API patterns -- Suggests /api/v2/search endpoint, OTCSTicket auth; may not apply to REGDOCS' custom frontend

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- All libraries are mature, well-documented, version-verified on PyPI
- Architecture patterns: MEDIUM -- Two-strategy approach is sound, but exact implementation depends on runtime API discovery
- REGDOCS site structure: MEDIUM -- Confirmed dynamic loading and URL patterns, but internal API endpoints unknown
- Pitfalls: HIGH -- Common Playwright gotchas well-documented; REGDOCS-specific risks identified from site probing

**Research date:** 2026-02-07
**Valid until:** 2026-03-07 (30 days -- REGDOCS site structure could change, but library recommendations stable)
