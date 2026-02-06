# Domain Pitfalls

**Domain:** Government regulatory website scraping, PDF document extraction, LLM analysis pipeline
**Project:** CER REGDOCS Scraper and Analysis Pipeline
**Researched:** 2026-02-05
**Overall Confidence:** MEDIUM (based on training data patterns for government scraping, PDF extraction, and LLM pipelines; CER REGDOCS-specific details could not be verified live)

---

## Critical Pitfalls

Mistakes that cause rewrites, data loss, or complete pipeline failure.

---

### Pitfall 1: Treating the JavaScript-Rendered Site as Static HTML

**What goes wrong:** The CER REGDOCS site (apps.cer-rec.gc.ca/REGDOCS) is JavaScript-rendered. Developers use `requests` + `BeautifulSoup` and get empty/partial HTML back. The filing list, search results, and document metadata are loaded dynamically via JavaScript after page load. A naive HTTP GET returns a shell page with no data.

**Why it happens:** Python's `requests` library does not execute JavaScript. The initial HTML response contains a JS application bootstrap, not the actual content. Developers see the page works in a browser and assume the HTML source contains the data.

**Consequences:**
- Scraper returns zero results or garbage data
- Silent failure: the scraper "succeeds" but extracts nothing useful
- Complete rewrite to use browser automation or API discovery

**Prevention:**
1. **First, investigate whether REGDOCS has a REST/JSON API behind the JavaScript frontend.** Most modern government JS-rendered sites use an internal API that the frontend calls. Inspect Network tab in browser DevTools for XHR/fetch requests to find the underlying API endpoints. If an API exists, call it directly with `requests` -- this is far more reliable than browser automation.
2. If no usable API exists, use Playwright (preferred over Selenium) for browser automation. Playwright has better async support, auto-wait semantics, and more reliable headless operation.
3. **Never skip the API investigation step.** Using Playwright when a JSON API exists adds enormous complexity for no benefit.

**Detection (warning signs):**
- Scraper returns empty lists or HTML with no filing data
- Response HTML contains `<script>` tags and `<div id="app">` but no actual content
- Response size is suspiciously small (a few KB for what should be a page of results)

**Phase mapping:** Phase 1 (foundation) -- this must be resolved before anything else works.

**Confidence:** HIGH -- this is a well-established pattern for JS-rendered government sites.

---

### Pitfall 2: No Deduplication Strategy from Day One

**What goes wrong:** The scraper runs every 2 hours and re-scrapes the same filings repeatedly. Without deduplication, the pipeline re-downloads PDFs, re-analyzes documents with Claude, re-sends notification emails -- burning API credits, wasting compute, and flooding inboxes.

**Why it happens:** Developers focus on "get it working first" and plan to add deduplication later. But the choice of deduplication key (filing ID, URL, content hash, or combination) affects the entire data model. Retrofitting deduplication onto a running pipeline means dealing with already-duplicated data.

**Consequences:**
- Claude API costs multiply (re-analyzing the same PDFs)
- Email recipients get duplicate notifications, eroding trust in the system
- Database/storage bloat with redundant data
- Subtle bugs where a filing appears "new" due to minor metadata changes (timestamp, URL parameter)

**Prevention:**
1. Define the deduplication key in the data model from the start. For REGDOCS, this is likely a combination of filing/document ID and version number (if REGDOCS versions documents).
2. Maintain a persistent registry (SQLite is sufficient for this scale) of processed filing IDs with timestamps.
3. The scraper's first operation after fetching listings should be: filter out already-processed IDs.
4. Use a content hash (SHA-256 of PDF bytes) as a secondary dedup check -- catches re-uploads of the same document under a new ID.
5. Store the dedup registry atomically: mark a filing as "processed" only AFTER all downstream steps (download, analyze, notify) succeed.

**Detection:**
- Email recipients complain about duplicate notifications
- Claude API bill is unexpectedly high
- Storage grows linearly with time even when filing volume is flat

**Phase mapping:** Phase 1 (foundation) -- the state tracking database must exist before the first production run.

**Confidence:** HIGH -- deduplication is the most universal pitfall in periodic scraping systems.

---

### Pitfall 3: PDF Extraction Assuming Uniform Document Structure

**What goes wrong:** CER regulatory documents vary wildly: some are OCR-scanned images, some are machine-generated PDFs, some are multi-hundred-page environmental assessments with tables/charts/appendices, some are 2-page letters. A single extraction approach fails on some subset.

**Why it happens:** Developers test with a few representative PDFs and build an extraction pipeline that works for those. In production, the pipeline encounters:
- Scanned/image PDFs (no extractable text layer)
- PDFs with complex table layouts that extract as garbled text
- PDFs with headers/footers that inject noise into every page
- Encrypted or password-protected PDFs (some government filings)
- Extremely large PDFs (100+ pages) that exceed memory or LLM context

**Consequences:**
- Silent analysis failures: Claude receives garbled text and produces nonsensical analysis
- Pipeline crashes on unexpected PDF types
- OCR PDFs return empty strings, treated as "no content" instead of triggering OCR fallback

**Prevention:**
1. **Classify PDFs before extracting.** Check if text layer exists (try `pdfplumber` or `PyMuPDF` extraction; if result is empty or near-empty, flag as image/scanned).
2. **Implement a tiered extraction strategy:**
   - Tier 1: Direct text extraction (`pdfplumber` for structured content, `PyMuPDF` for speed)
   - Tier 2: OCR fallback (`pytesseract` + `pdf2image`, or a cloud OCR service) for scanned docs
   - Tier 3: Skip with logged warning for encrypted/corrupted PDFs
3. **Validate extraction output.** If extracted text is shorter than expected (e.g., < 100 chars for a 50-page PDF), flag for manual review or OCR retry.
4. **Handle large documents specially.** For PDFs over ~50 pages, extract and analyze in chunks rather than feeding everything to Claude at once.

**Detection:**
- Analysis output says "I cannot determine..." or provides generic non-answers
- Extracted text contains mostly whitespace or garbage characters
- Processing time spikes for certain documents

**Phase mapping:** Phase 2 (PDF processing) -- but the classification/validation logic should be designed in Phase 1 architecture.

**Confidence:** HIGH -- PDF variability is the most commonly reported failure in regulatory document processing.

---

### Pitfall 4: LLM Context Window Overflow and Truncation

**What goes wrong:** Regulatory PDFs can be extremely long. A 200-page environmental assessment might produce 100K+ tokens of text. Feeding this to Claude via `claude -p` either silently truncates the input, produces degraded analysis (the model focuses on the beginning/end and misses middle content), or fails outright.

**Why it happens:** Developers test with short filings (5-10 pages), everything works. In production, a 150-page PDF arrives and the analysis is meaningless because the model never "saw" the critical section on page 87.

**Consequences:**
- Critical information missed in long documents
- Analysis quality degrades silently (no error, just worse output)
- Inconsistent analysis quality: short docs analyzed well, long docs analyzed poorly
- Users lose trust when analysis misses obvious points from the document

**Prevention:**
1. **Measure token count before sending to Claude.** Use `tiktoken` or a simple character-based estimate (1 token ~ 4 chars for English) to check if content fits within context.
2. **Implement chunking for long documents:** Split into logical sections (by heading, by page range), analyze each chunk, then synthesize. This is more reliable than hoping the model handles 100K tokens well.
3. **Prioritize content extraction.** For regulatory documents, the executive summary, decision section, and conditions sections are usually most valuable. Extract these sections specifically rather than dumping the entire document.
4. **Include document length in analysis metadata** so downstream consumers know if the analysis covered the full document or a subset.
5. **Set explicit expectations in the Claude prompt** about document length: "This is a {page_count}-page document. Focus on sections X, Y, Z."

**Detection:**
- Analysis of long documents is vague or generic compared to short documents
- Analysis doesn't mention content that appears in the middle/end of long documents
- Token usage is capped at maximum for many documents (indicating truncation)

**Phase mapping:** Phase 2 (analysis pipeline) -- must be designed before the analysis prompt is finalized.

**Confidence:** HIGH -- context window management is a known challenge with LLM document analysis.

---

### Pitfall 5: No Graceful Degradation -- All-or-Nothing Pipeline

**What goes wrong:** The pipeline is built as a linear chain: scrape -> download PDFs -> extract text -> analyze -> email. If any step fails, the entire run fails. A single corrupt PDF blocks all other filings. An email server timeout means successfully analyzed filings don't get reported until the next run.

**Why it happens:** Linear pipelines are the natural first implementation. Error handling is planned for "later" but never adequately implemented because the happy path works in testing.

**Consequences:**
- One bad PDF blocks 49 good filings from being processed
- Transient failures (network timeout) cascade to permanent failure of that run
- The 2-hour window passes with nothing processed because of one error
- Filings accumulate in a backlog that grows with each failed run

**Prevention:**
1. **Process each filing independently.** Wrap individual filing processing in try/except. Log failures, continue to next filing.
2. **Implement per-filing state tracking** with states: `discovered`, `downloaded`, `extracted`, `analyzed`, `notified`. Each filing progresses independently.
3. **Separate the notification step.** Batch all successfully-analyzed filings into a single notification email. Don't send per-filing emails.
4. **Implement retry with backoff for transient failures.** Track retry count per filing. After N retries, mark as `failed` and alert.
5. **Design for partial success.** A run that processes 48/50 filings and reports 2 failures is a good run, not a failed run.

**Detection:**
- Logs show "run failed" when only one filing was problematic
- Filing backlog grows over time
- Users report gaps in notifications (missing filings that were on the site)

**Phase mapping:** Phase 1 (architecture) -- the per-filing state machine must be in the initial design.

**Confidence:** HIGH -- this is the most common architectural mistake in batch processing pipelines.

---

## Moderate Pitfalls

Mistakes that cause delays, degraded reliability, or significant technical debt.

---

### Pitfall 6: Rate Limiting and Anti-Bot Measures on Government Sites

**What goes wrong:** The scraper hammers the CER REGDOCS site with rapid requests, triggering rate limiting, IP blocking, or WAF (Web Application Firewall) responses. Government sites increasingly deploy Cloudflare, AWS WAF, or similar protections.

**Why it happens:** Developers test with single requests that work fine. In production, fetching 50 filing pages plus PDFs in rapid succession looks like a bot attack.

**Consequences:**
- IP gets blocked (temporarily or permanently)
- Requests return 403/429 status codes or CAPTCHA pages
- The site operators notice and potentially block the user agent or IP range
- Data gaps during blocking periods

**Prevention:**
1. **Respect `robots.txt`** -- check what the CER site allows. Government sites often have permissive `robots.txt` but it is still important to respect.
2. **Implement polite delays:** 1-3 seconds between page requests, 2-5 seconds between PDF downloads. This is sufficient for 50 filings -- the whole run still completes in minutes.
3. **Use realistic headers:** Set a proper `User-Agent` string that identifies your scraper (e.g., `CER-REGDOCS-Monitor/1.0 (contact@example.com)`). Paradoxically, identifying yourself is less likely to trigger blocks than using a generic or missing User-Agent.
4. **Implement exponential backoff on 429/503 responses.** Back off, wait, retry.
5. **Cache aggressively.** Don't re-download PDFs you already have. Don't re-fetch listing pages more often than your 2-hour cycle.
6. **If using Playwright:** Reuse a single browser session rather than launching/closing for each request.

**Detection:**
- HTTP 403 or 429 responses in logs
- Scraper returns fewer results than expected
- Response bodies contain CAPTCHA HTML or "access denied" messages

**Phase mapping:** Phase 1 (scraping) -- bake polite behavior into the initial scraper implementation.

**Confidence:** MEDIUM -- CER-specific anti-bot measures could not be verified; general government site patterns apply.

---

### Pitfall 7: Gmail API / SMTP Deliverability and Quota Issues

**What goes wrong:** Email notifications land in spam, hit Gmail sending limits, or OAuth tokens expire silently.

**Why it happens:** Gmail has strict sending quotas (500 emails/day for personal, 2000 for Workspace), OAuth tokens expire after periods of inactivity, and Gmail's anti-spam heuristics may flag automated emails -- especially those with repetitive subjects or templated content.

**Consequences:**
- Notifications stop being delivered with no visible error (messages in spam)
- OAuth token expires, emails fail, and the operator doesn't notice for days
- Hitting quota limits means late filings in a busy day don't get notified

**Prevention:**
1. **Use Gmail API (not SMTP)** -- more reliable, better error reporting, and avoids many SMTP-specific issues.
2. **Store OAuth refresh tokens securely** and implement automatic token refresh. Test the refresh flow explicitly.
3. **Monitor for delivery failures.** After sending, check the Gmail API response for errors. Log every send attempt and result.
4. **Use a distinctive, consistent sender name and subject pattern** to help recipients whitelist the messages.
5. **Send digest emails, not per-filing emails.** Batching reduces email volume, avoids quota issues, and is a better UX. One email per run with all new filings.
6. **Implement a notification fallback.** If email fails, log to a local file or dashboard that can be checked manually.
7. **Test with actual Gmail account early** -- don't mock email in development and discover issues in production.

**Detection:**
- Recipients stop receiving notifications (check spam folder)
- Gmail API returns 401 (token expired) or 429 (rate limited) errors
- `sent` folder in Gmail doesn't show recent notifications

**Phase mapping:** Phase 3 (notifications) -- but OAuth setup should be validated in Phase 1.

**Confidence:** MEDIUM -- Gmail API specifics are well-known, but quota limits may have changed since training data.

---

### Pitfall 8: Scheduler Reliability -- Cron/Task Scheduler Silent Failures

**What goes wrong:** The 2-hour scheduled run stops executing and nobody notices. The scraper hasn't run for 3 days. No filings have been processed. No one was notified because the thing that sends notifications is the thing that stopped running.

**Why it happens:** Scheduled tasks fail silently for many reasons:
- Machine goes to sleep or restarts (if running on a personal computer)
- Cron daemon doesn't survive reboot (missing `@reboot` or systemd configuration)
- Windows Task Scheduler disables the task after too many failures
- Cloud scheduler (if used) has its own failure modes
- Python virtual environment path changes after an update

**Consequences:**
- Complete blind spot: the system designed to alert you about new filings cannot alert you that it itself has stopped working
- Data gaps that grow unnoticed
- Loss of trust when users realize filings were missed for days

**Prevention:**
1. **Implement a heartbeat/dead man's switch.** Use an external service (e.g., Healthchecks.io, UptimeRobot, or a simple cron monitoring service) that expects a ping every 2 hours. If the ping doesn't arrive, the external service alerts you via a DIFFERENT channel (SMS, different email, Slack webhook).
2. **Log every run start and end** with timestamps. Make it trivial to see "last successful run was at X."
3. **If running on a personal machine:** Use a cloud VM or container instead. Personal machines sleep, update, restart, and are unreliable for 24/7 scheduled tasks.
4. **If using cloud:** Use managed scheduling (Cloud Run jobs, AWS EventBridge, Azure Timer Functions) rather than a cron job on a VM.
5. **Start each run with a self-check:** "When was my last successful run? If it was more than 4 hours ago, process with extra lookback window to catch missed filings."

**Detection:**
- Gaps in the run log (no entries for hours or days)
- Heartbeat monitoring alerts
- Users manually check the site and find filings not in the system

**Phase mapping:** Phase 4 (deployment/operations) -- but the heartbeat design should be planned in Phase 1.

**Confidence:** HIGH -- scheduler reliability is a universal problem for long-running automated systems.

---

### Pitfall 9: CER REGDOCS Site Structure Changes Breaking the Scraper

**What goes wrong:** The CER updates their REGDOCS site (new frontend framework, changed DOM structure, new URL patterns, or API endpoint changes). The scraper breaks silently -- it runs, finds zero new filings, and reports "nothing new" when in fact the site has dozens of new filings.

**Why it happens:** Government sites undergo periodic modernization. The CER has been actively modernizing their digital infrastructure. Frontend changes can happen without notice, especially for internal API endpoints that aren't considered part of a public interface.

**Consequences:**
- Scraper returns zero results but reports success (no errors, just no data)
- Data gaps that are indistinguishable from "quiet days" with no new filings
- Emergency rewrite of scraper selectors/parsers

**Prevention:**
1. **Implement a "sanity check" after each scrape.** If the scraper returns zero filings for more than N consecutive runs (e.g., 3 runs = 6 hours), trigger an alert. The CER site almost certainly has at least a few filings per day.
2. **Monitor response structure, not just status codes.** A 200 OK with completely different HTML is still a failure.
3. **Use resilient selectors.** Prefer data attributes, ARIA roles, and semantic HTML over brittle CSS class selectors that change with framework updates.
4. **If using an API endpoint:** Monitor the response schema. If expected fields disappear or types change, alert immediately.
5. **Version your scraper selectors/parsers** so you can quickly swap in new ones when the site changes.
6. **Maintain a "known good" reference response** (sanitized snapshot of a successful scrape result). Compare structure periodically.

**Detection:**
- Zero results for multiple consecutive runs
- Response HTML/JSON structure doesn't match expected schema
- New fields appear or expected fields disappear
- Scraper works in browser DevTools but not in automation (site serves different content to headless browsers)

**Phase mapping:** Phase 1 (scraping) -- sanity checks must be part of the initial scraper. Phase 4 (monitoring) for structural monitoring.

**Confidence:** MEDIUM -- CER-specific update frequency could not be verified, but government site changes are common.

---

### Pitfall 10: Storing PDFs and Analysis Results Without Backup or Versioning

**What goes wrong:** Downloaded PDFs are stored in a local directory. The disk fills up, or the directory is accidentally deleted, or a re-run overwrites files. Analysis results are stored in memory or temp files and lost between runs.

**Why it happens:** Storage seems trivial in early development. "Just save to a folder." But with 10-50 filings/day, each with a multi-MB PDF and analysis text, storage management becomes real within weeks.

**Consequences:**
- Lost PDFs require re-downloading (which may fail if the CER removes old filings)
- Lost analysis results require re-running Claude analysis (cost and time)
- No audit trail of what was analyzed and when
- Disk fills up and pipeline stops with cryptic errors

**Prevention:**
1. **Use structured storage from the start.** SQLite database for metadata and analysis results. File system with date-based directory structure for PDFs (`data/pdfs/2026/02/05/filing_12345.pdf`).
2. **Never overwrite.** Use filing ID + timestamp in filenames. If a document is re-published, keep both versions.
3. **Implement storage rotation.** After 90 days (or configurable), archive or delete old PDFs but keep metadata and analysis results permanently.
4. **Calculate and store file hashes.** SHA-256 of every downloaded PDF, stored in the database. Enables integrity checks and deduplication.
5. **Back up the SQLite database.** A simple daily copy to a second location. The database is small; PDFs are the bulk of storage.

**Detection:**
- Disk usage growing unchecked
- "File not found" errors when trying to reference historical analyses
- Duplicate filenames overwriting each other

**Phase mapping:** Phase 1 (data model) -- storage structure must be designed before the first filing is processed.

**Confidence:** HIGH -- storage management is a universal pitfall for data collection pipelines.

---

## Minor Pitfalls

Mistakes that cause annoyance, debugging difficulty, or minor degradation.

---

### Pitfall 11: Claude CLI (`claude -p`) Invocation Fragility

**What goes wrong:** The `claude -p` CLI invocation fails in ways that are hard to detect: the process hangs, returns a non-zero exit code that the pipeline doesn't check, or produces malformed output. The pipeline treats the empty/error output as valid analysis.

**Why it happens:** CLI tools have failure modes that are different from library calls: process timeouts, stdout/stderr interleaving, shell escaping issues with document text containing special characters, and authentication failures.

**Prevention:**
1. **Set explicit timeouts** on the subprocess call. A Claude analysis should complete within a known time bound (e.g., 120 seconds). Kill the process if it hangs.
2. **Check exit codes.** Non-zero exit code = failed analysis. Do not parse stdout on failure.
3. **Validate output structure.** If you expect JSON or a specific format, validate it. An empty string or error message is not valid analysis.
4. **Escape document content carefully** when passing via command line or stdin. Prefer piping content via stdin rather than passing as a command-line argument (argument length limits, shell escaping issues).
5. **Handle authentication failures** (expired API key, rate limits) as a distinct error type that should pause the pipeline, not retry indefinitely.

**Detection:**
- Analysis results that are empty, truncated, or contain error messages
- Subprocess timeout exceptions
- Inconsistent analysis quality across runs

**Phase mapping:** Phase 2 (analysis pipeline).

**Confidence:** MEDIUM -- `claude -p` specific behavior could not be verified against current documentation.

---

### Pitfall 12: Timezone and Scheduling Edge Cases

**What goes wrong:** The scraper runs on UTC but CER publishes filings in ET (Eastern Time). Filings published at 4:30 PM ET on a Friday are processed as Saturday filings. Date-based deduplication or filtering breaks around midnight in either timezone.

**Why it happens:** Government agencies operate in their local timezone. Server-side timestamps may differ from displayed dates. The 2-hour schedule interacts with timezone boundaries in subtle ways.

**Prevention:**
1. **Store all timestamps in UTC internally.** Convert to local time only for display/notification.
2. **Use timezone-aware datetime objects** everywhere. Never use naive datetimes.
3. **Don't filter filings by date on the client side.** Fetch everything since the last successful run, regardless of date, and let deduplication handle the rest.
4. **Test around DST transitions.** A 2-hour schedule that starts at the wrong time after a DST change is a common bug.

**Detection:**
- Missing filings around midnight ET
- Duplicate processing after DST transitions
- Date-based queries returning unexpected results

**Phase mapping:** Phase 1 (data model) -- timestamps and timezone handling are foundational.

**Confidence:** HIGH -- timezone bugs are universal in scheduled systems.

---

### Pitfall 13: Logging and Observability Afterthoughts

**What goes wrong:** When something fails at 3 AM, the only log is `ERROR: something went wrong`. No filing ID, no URL, no stack trace. Debugging requires reproducing the failure, which may be intermittent.

**Why it happens:** Logging is treated as print statements for debugging rather than as operational infrastructure. Structured logging is added "later."

**Prevention:**
1. **Use structured logging from the start.** Python's `logging` module with JSON formatter, or `structlog`. Include filing ID, URL, step name, and duration in every log entry.
2. **Log at the right level:** DEBUG for extraction details, INFO for filing processing progress, WARNING for retryable failures, ERROR for permanent failures.
3. **Include context in errors:** Not just "PDF download failed" but "PDF download failed for filing_id=12345, url=https://..., attempt=2/3, error=ConnectionTimeout after 30s."
4. **Log timing data.** How long did each step take? This reveals degradation before it becomes failure.
5. **Write logs to a file with rotation**, not just stdout. Use `logging.handlers.RotatingFileHandler`.

**Detection:**
- Inability to diagnose production failures from logs alone
- Log files growing unbounded
- No way to answer "when was filing X processed?"

**Phase mapping:** Phase 1 (foundation) -- logging infrastructure should be the first thing built.

**Confidence:** HIGH -- observability quality directly determines operational pain.

---

### Pitfall 14: Hardcoding CER-Specific Values Instead of Configuration

**What goes wrong:** URLs, CSS selectors, analysis prompts, email addresses, schedule intervals, retry counts, and other parameters are hardcoded throughout the codebase. When any of these change, it requires a code change and redeployment.

**Why it happens:** Hardcoding is faster during initial development. "I'll make it configurable later."

**Prevention:**
1. **Use a single configuration file** (TOML, YAML, or `.env`) for all operational parameters.
2. **Especially externalize:** Site URL, CSS selectors / API endpoints, email recipients, schedule interval, retry counts and delays, Claude analysis prompt template, storage paths.
3. **Use Pydantic Settings or `python-dotenv`** for configuration management with validation and defaults.
4. **Separate secrets (API keys, OAuth tokens) from configuration** using environment variables or a secrets manager.

**Detection:**
- Changing an email recipient requires editing Python code
- Multiple places in code reference the same URL string
- Analysis prompt changes require redeployment

**Phase mapping:** Phase 1 (foundation) -- externalized configuration from the start.

**Confidence:** HIGH -- configuration management is a universal software engineering pitfall.

---

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation | Severity |
|-------------|---------------|------------|----------|
| Scraping (Phase 1) | JS rendering -- using requests on a JS-rendered site | Investigate API first; Playwright as fallback | Critical |
| Scraping (Phase 1) | No deduplication | Define dedup key in data model from day one | Critical |
| Scraping (Phase 1) | Rate limiting / blocking | Polite delays, realistic headers, backoff | Moderate |
| Scraping (Phase 1) | Hardcoded selectors break on site update | Sanity checks, resilient selectors, alerting | Moderate |
| PDF Processing (Phase 2) | Scanned/image PDFs with no text layer | Tiered extraction: text -> OCR -> skip with warning | Critical |
| PDF Processing (Phase 2) | Large PDFs overflow LLM context | Token counting, chunking, section prioritization | Critical |
| Analysis (Phase 2) | Claude CLI hangs or returns errors silently | Timeouts, exit code checks, output validation | Moderate |
| Notifications (Phase 3) | Gmail OAuth expiry / deliverability | Token refresh, digest emails, fallback channel | Moderate |
| Operations (Phase 4) | Scheduler stops silently | External heartbeat monitoring, lookback window | Moderate |
| Operations (Phase 4) | Storage fills up or data lost | Structured storage, rotation, backups | Moderate |
| Operations (Phase 4) | Cannot diagnose failures | Structured logging from Phase 1 | Minor (if addressed early) |

## Cross-Cutting Concerns

These pitfalls span multiple phases and should be considered throughout:

1. **The "quiet failure" theme:** Many of these pitfalls share a common pattern -- the system fails but reports success. Zero filings found (site changed), empty text extracted (scanned PDF), meaningless analysis (truncated input), email not delivered (spam filter). **Every step needs positive validation, not just error checking.**

2. **The "testing against production" trap:** The CER REGDOCS site is the only source of truth. There is no staging environment. Testing must account for this: use cached/saved responses for development, but validate against the live site regularly.

3. **The "it works on my machine" trap:** If this runs on a personal computer, sleep/hibernation, OS updates, and network changes will disrupt the schedule. Plan for a dedicated execution environment (cloud VM, container) from the architecture phase.

## Sources

- Training data patterns from government website scraping projects (MEDIUM confidence)
- General PDF extraction and LLM pipeline patterns (HIGH confidence for patterns, MEDIUM for specific library versions)
- Gmail API and scheduling patterns (HIGH confidence for patterns)
- CER REGDOCS site-specific details (LOW confidence -- could not verify live site structure, API availability, or current anti-bot measures)

**Note:** External research tools (WebSearch, WebFetch) were unavailable during this research session. CER REGDOCS-specific claims (JS rendering, API availability) should be verified against the live site before implementation. The recommendation to investigate the underlying API first is especially important and should be the very first task in development.
