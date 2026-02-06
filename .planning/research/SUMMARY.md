# Project Research Summary

**Project:** CER REGDOCS Scraper & Analyzer
**Domain:** Regulatory document monitoring and LLM-powered analysis pipeline
**Researched:** 2026-02-05
**Confidence:** MEDIUM

## Executive Summary

This project is a regulatory document monitoring pipeline that scrapes the CER (Canada Energy Regulator) REGDOCS site for new filings, downloads PDFs, extracts text, analyzes content using Claude CLI, and delivers summaries via email. The domain pattern is well-established: it's an ETL pipeline with an LLM analysis layer. At the projected volume (10-50 filings/day, 2-hour polling cycle), the recommended approach favors reliability and simplicity over concurrency and scale.

The critical architectural decision is treating this as a sequential pipeline with per-filing error isolation and state tracking via SQLite. The highest technical risk is the REGDOCS scraping layer: the site is JavaScript-rendered, and research recommends first investigating whether internal JSON APIs exist (via Playwright network interception) before falling back to full browser automation. Playwright should be the discovery tool, not the steady-state scraper. The second-highest risk is PDF text extraction variability—CER documents range from machine-generated PDFs to scanned images to 200+ page environmental assessments, requiring tiered extraction (direct text → OCR fallback → chunking for large docs) and LLM context management.

The recommended stack is modern and minimal: Playwright for initial API discovery and JS rendering fallback, httpx for direct HTTP once APIs are found, PyMuPDF for fast PDF text extraction with pdfplumber as fallback for table-heavy docs, Claude CLI via subprocess for analysis, standard library smtplib for Gmail notifications, and Windows Task Scheduler (not in-process scheduling). Critical pitfalls to avoid: no deduplication strategy from day one, treating JS-rendered sites as static HTML, assuming uniform PDF structure, LLM context overflow on long documents, and all-or-nothing pipeline failures where one bad PDF blocks 49 good filings.

## Key Findings

### Recommended Stack

The stack prioritizes Python-native, async-capable libraries with minimal dependencies. The architecture uses a two-phase approach for scraping: Playwright to discover the underlying AJAX/JSON API endpoints that power the JS-rendered REGDOCS site, then switch to direct httpx requests for speed and reliability. Browser automation is the fallback, not the primary path.

**Core technologies:**
- **Playwright (>=1.49)**: Browser automation for JS-rendered content and API discovery. Use network interception to capture XHR requests and reverse-engineer internal endpoints. Launch once per run, reuse across navigations.
- **httpx (>=0.27)**: Async HTTP client for direct API calls and PDF downloads once endpoints are discovered. Replaces Playwright for routine data fetching—faster, more reliable, lower resource usage.
- **PyMuPDF/fitz (>=1.24)**: Primary PDF text extraction. Fastest Python PDF library, handles most CER filings which are text-based PDFs.
- **pdfplumber (>=0.11)**: Fallback for table-heavy PDFs where PyMuPDF produces garbled layouts. Better structured table extraction.
- **Claude CLI (claude -p)**: LLM analysis via subprocess. Uses existing subscription, no per-token API billing. Requires timeout management (5 min/filing), stdin piping for long content, and exit code validation.
- **smtplib + email (stdlib)**: Gmail SMTP with app passwords. Zero dependencies, sufficient for 10-50 emails/day. No need for Gmail API OAuth complexity in a single-user tool.
- **Windows Task Scheduler**: Trigger script every 2 hours. More reliable than in-process scheduling—script runs, processes filings, exits. No idle Python process consuming memory. Task survives crashes and restarts.
- **SQLite (stdlib)**: State tracking for processed filing IDs. Atomic writes, zero config, handles thousands of records easily. Tracks: filing ID, processed timestamp, analysis status, email sent, error messages.

**Post-install requirement:** `playwright install chromium` downloads ~150MB Chromium binary (one-time setup).

### Expected Features

The feature set divides cleanly into table stakes (system fails without them), differentiators (add value but not strictly required), and anti-features (scope creep to avoid).

**Must have (table stakes):**
- **REGDOCS listing scraper with metadata extraction**: Parse filing date, applicant, document type, proceeding number, PDF URLs. Handle JS-rendered content and pagination.
- **PDF download pipeline with verification**: Handle large files (100+ pages), timeouts, content-type validation. Organized local storage by date/filing ID.
- **PDF text extraction with fallback**: PyMuPDF for text-based PDFs, pdfplumber for tables, validation for empty/garbled output (triggers OCR or skip).
- **LLM analysis via Claude CLI**: Entity extraction (companies, facilities, people), document classification (application/compliance/order), regulatory implications summary, deadline/date extraction. Structured JSON output.
- **Deduplication and state tracking**: SQLite tracking of processed filing IDs prevents reprocessing, duplicate emails, and wasted Claude CLI calls. Critical from day one.
- **Per-filing email notification**: HTML formatted with filing metadata, classification, entities, implications, deadlines. Distinctive sender/subject for whitelisting.
- **Error recovery and retry logic**: Per-filing try/except so one failure doesn't crash the run. Retry with exponential backoff for transient failures. Never lose track of processing state.
- **Scheduled 2-hour execution**: Windows Task Scheduler triggering `uv run python main.py`. More reliable than long-running process.
- **Structured logging with rotation**: Timestamps, filing IDs, success/failure per step. Log to file (RotatingFileHandler) for debugging unattended runs.

**Should have (competitive/enhancing):**
- **Sentiment/tone analysis**: Add prompt field to flag urgent/adversarial filings vs routine compliance. Low complexity, useful for prioritization.
- **Key quote extraction**: 2-3 most important sentences from filing for email scanning. Easy addition to LLM prompt.
- **Impact scoring (1-5)**: Prompt-based rating of filing significance. Subjective but useful.
- **Rate limiting and polite scraping**: 1-3 second delays between requests, proper User-Agent, respect robots.txt. Essential for long-term reliability.
- **Incremental polling**: Use date-range filtering if REGDOCS supports it. Only fetch since last check.
- **Daily digest option**: Alternative to per-filing emails for users preferring consolidated summaries.
- **Configuration externalization**: .env file for secrets, config.py for paths/URLs/intervals. Avoid hardcoding.

**Defer (v2+):**
- **Cross-filing relationship detection**: Link related filings by proceeding number. Requires knowledge graph. High complexity.
- **Proceeding timeline construction**: Build narrative arc across filings. Requires accumulated history.
- **Multi-document daily synthesis**: "Today's 12 filings summarized." Run after all filings processed.
- **OCR for scanned PDFs**: Tesseract fallback. Heavy dependency, rare use case (most CER filings are text PDFs).
- **Web dashboard/UI**: Massive scope increase. Email is the right interface for v1.
- **User authentication/multi-tenancy**: Single-user tool. No value in auth.
- **Real-time monitoring below 2-hour granularity**: CER doesn't offer webhooks. 2-hour polling is appropriate for regulatory timescales.

**Anti-features (do not build):**
- **Custom LLM fine-tuning**: Prompt engineering is sufficient. Fine-tuning is expensive and slow to iterate.
- **Database server (PostgreSQL/MySQL)**: SQLite handles 10-50/day for decades. Server DB is overkill.
- **Containerization**: Adds deployment complexity for single-machine tool. Run directly with uv.
- **Parallel/async PDF processing**: Sequential is fast enough at current volume. Async adds debugging complexity without benefit.

### Architecture Approach

The architecture is a sequential pipeline with state tracking—a classic ETL pattern with an LLM layer. Six components connected by shared filesystem and SQLite: Scheduler (triggers runs) → Orchestrator (coordinates) → Scraper (Playwright/httpx) → Downloader (PDF fetch) → Analyzer (Claude CLI subprocess) → Notifier (Gmail SMTP) ← → State Store (SQLite). Each component has single responsibility and clean interface. At 10-50 filings/day with 2-hour cycles (5-25 filings/run, ~30-60 seconds each), sequential processing completes in ~25 minutes worst case—well within the 2-hour window.

**Major components:**
1. **Orchestrator (Pipeline Core)**: Calls components in sequence, isolates per-filing errors (try/except around each filing so one failure doesn't crash batch), checks state before processing for idempotency, logs run summaries.
2. **Scraper (Playwright + API Interception)**: Two-phase approach—use Playwright network listeners to capture XHR/API calls that load filing data, document internal endpoints, then switch to direct httpx calls for routine scraping. Playwright is discovery tool + fallback, not primary path. Launch browser once per run, reuse, close in finally block.
3. **State Store (SQLite)**: Tracks processed filing IDs with timestamps, status (success/failed/partial), email sent flag, error messages. Schema: `processed_filings` table (filing_id PRIMARY KEY, title, processed_at, pdf_count, analysis_status, email_sent, error_message) and `run_log` table for run history.
4. **Downloader (httpx)**: Fetches PDFs to organized folders (`data/filings/2026-02-05_Filing-12345_Title/documents/`). Retry with exponential backoff (3 attempts). Check for existing files by name+size before downloading.
5. **Analyzer (Claude CLI subprocess)**: Shells out to `claude -p` with PDF path and analysis prompt. Timeout (300s), capture stdout/stderr, validate exit code (non-zero = failed), validate output structure. Store prompt as template file (analyzer/prompts/analysis_prompt.md) not hardcoded—prompt engineering is iterative. Handle multi-PDF filings by analyzing each separately and combining results.
6. **Notifier (Gmail SMTP)**: Standard library smtplib with app password (2FA required). HTML email template with metadata header, analysis sections, link to REGDOCS. 1-2 second delay between sends for politeness.

**Patterns to follow:**
- **Per-filing error isolation**: Wrap each filing in try/except. Log failure, mark as failed in state store, continue to next filing.
- **Idempotent runs**: Check state store before processing. Only mark processed after email send succeeds. Running twice with no new filings is a no-op.
- **Graceful Playwright lifecycle**: Launch once per run in async context manager, ensure cleanup even on failure.
- **Structured logging with context**: Every log entry includes filing ID, URL, step name, duration. Use RotatingFileHandler for unattended operation.

**Build order (dependency-driven):**
1. State Store + Config/Models (foundation, no external dependencies)
2. Scraper (highest risk—validates REGDOCS approach, must discover API vs DOM scraping)
3. Downloader (straightforward once URLs are available)
4. Analyzer (second highest risk—validates Claude CLI integration, subprocess management, prompt engineering)
5. Notifier (low risk, requires analysis output)
6. Orchestrator (integration layer, needs all components)
7. Scheduler (trivial wrapper, lowest risk)

### Critical Pitfalls

Research identified 14 pitfalls ranging from critical (cause rewrites) to minor (cause annoyance). The top five represent the highest technical risks for this specific domain.

1. **Treating JavaScript-rendered site as static HTML**: Using requests + BeautifulSoup on REGDOCS returns empty/partial data. The filing list loads via AJAX. Prevention: First investigate internal APIs via Playwright network interception (look for `/api/` or XHR endpoints returning JSON). If API exists, call directly with httpx—far more reliable than DOM scraping. Use Playwright only as fallback for genuinely JS-dependent pages. This must be resolved in Phase 1 or nothing else works.

2. **No deduplication strategy from day one**: Without persistent tracking of processed filing IDs, every 2-hour cycle reprocesses everything—wasted Claude credits, duplicate emails, storage bloat. Prevention: Define deduplication key (filing ID + version) in data model from start. SQLite table tracking processed IDs with timestamp. Mark processed only AFTER email succeeds. Use PDF content hash (SHA-256) as secondary check for re-uploads under new IDs. This is foundational—retrofit is painful.

3. **PDF extraction assuming uniform document structure**: CER filings vary wildly—OCR scans, machine PDFs, 200+ page assessments with tables, 2-page letters. Single extraction approach fails on some subset. Prevention: Tiered strategy—Tier 1 direct text extraction (PyMuPDF/pdfplumber), Tier 2 OCR fallback for scanned docs (pytesseract), Tier 3 skip with logged warning for encrypted/corrupted. Validate extraction output (if <100 chars for 50-page PDF, flag for review). Classify PDFs before extracting (check if text layer exists).

4. **LLM context window overflow and silent truncation**: 200-page PDFs produce 100K+ tokens. Feeding to Claude silently truncates or degrades analysis quality (model focuses on start/end, misses critical middle sections). Prevention: Measure token count pre-analysis (tiktoken or ~4 chars/token estimate). Chunk long documents by logical sections (heading-based or page ranges), analyze each, synthesize. Prioritize key sections (executive summary, decision, conditions). Include page count in prompt and metadata so consumers know coverage. Set expectations in prompt about document length.

5. **All-or-nothing pipeline where one failure blocks everything**: Linear scrape → download → extract → analyze → email chain where any step failure kills the entire run. One corrupt PDF blocks 49 good filings. Prevention: Per-filing state machine with independent processing. Try/except around each filing. Implement states: discovered → downloaded → extracted → analyzed → notified. Separate notification step (batch successful analyses, don't send per-filing during processing). Retry with backoff for transient failures. Track retry count. A run that processes 48/50 is successful, not failed.

**Moderate pitfalls worth noting:**
- **Rate limiting on government sites**: Polite delays (1-3s between requests), proper User-Agent, respect robots.txt, exponential backoff on 429/503.
- **Gmail deliverability and quota**: Use Gmail API over SMTP for reliability, monitor delivery failures, send digest emails not per-filing to reduce volume, test with real account early.
- **Scheduler silent failures**: Implement external heartbeat (Healthchecks.io or similar) that alerts if ping doesn't arrive every 2 hours. Log every run start/end. Self-check at run start (if last run >4 hours ago, expand lookback window).
- **REGDOCS site structure changes**: Sanity check—if zero results for 3+ consecutive runs, alert (CER has filings every day). Monitor response structure not just status codes. Use resilient selectors (data attributes, ARIA roles over CSS classes). Version selectors for quick swaps.
- **Storage without backup/versioning**: Structured storage from start (SQLite for metadata, date-based filesystem for PDFs). Never overwrite (use filing_id + timestamp in filenames). Store file hashes. Daily SQLite backup.

## Implications for Roadmap

Based on combined research, the recommended roadmap structure follows the dependency-driven build order identified in architecture research, prioritizes high-risk technical validation early, and defers differentiating features until core reliability is proven.

### Phase 1: Foundation & Scraper Validation
**Rationale:** State tracking and scraping are foundational. Scraping is the highest technical risk—if we can't reliably get filing data from REGDOCS, the project approach is invalid. Must validate the JS-rendering approach (API discovery vs DOM parsing) and deduplication strategy before building downstream components.

**Delivers:**
- SQLite state store with processed filing tracking
- Config management (.env for secrets, config.py for settings)
- Data models (Filing, ProcessedFiling dataclasses)
- REGDOCS scraper with API discovery via Playwright network interception
- Validation of scraping approach (API endpoints documented or fallback to DOM parsing)
- Basic logging infrastructure (RotatingFileHandler)

**Addresses:**
- Table stakes: REGDOCS listing scraper, metadata extraction, deduplication tracking
- Stack: Playwright, httpx, SQLite, python-dotenv
- Architecture: State Store, Config/Models, Scraper components

**Avoids:**
- Pitfall 1: JS-rendered site treated as static (investigate API first)
- Pitfall 2: No deduplication (build state tracking from day one)
- Pitfall 6: Rate limiting (polite delays baked into scraper)
- Pitfall 9: Site structure changes (sanity checks on zero results)

**Needs research:** No—Playwright API interception is well-documented. The research task is discovery (what endpoints exist), not learning (how to use Playwright).

### Phase 2: PDF Processing & Storage
**Rationale:** Can't analyze what can't be extracted. Must build tiered extraction (text → OCR fallback) and validate handling of PDF variability before integrating Claude. Downloader and extraction are medium risk—straightforward HTTP but must handle CER's document diversity.

**Delivers:**
- PDF downloader with retry logic and organized folder structure
- Tiered text extraction (PyMuPDF primary, pdfplumber for tables, OCR fallback)
- PDF classification (text-based vs scanned)
- Extraction validation (detect empty/garbled output)
- Local storage management with date-based organization

**Addresses:**
- Table stakes: PDF download pipeline, text extraction with fallback, local folder storage
- Stack: httpx, PyMuPDF, pdfplumber
- Architecture: Downloader, text extraction preparation for Analyzer

**Avoids:**
- Pitfall 3: Uniform PDF assumption (tiered extraction strategy)
- Pitfall 10: Storage without backup (structured folders, never overwrite)

**Needs research:** Possibly—if scanned PDFs are common, may need `/gsd:research-phase` on OCR tooling (Tesseract setup, accuracy on regulatory docs). Start without OCR, add if needed based on real filing samples.

### Phase 3: LLM Analysis Pipeline
**Rationale:** Second-highest technical risk. Must validate Claude CLI subprocess invocation, prompt engineering for regulatory analysis, timeout/error handling, and context window management for long documents. This phase proves the core value proposition (LLM analysis).

**Delivers:**
- Claude CLI subprocess wrapper with timeout, exit code validation
- Analysis prompt template (externalized markdown file)
- Token counting and chunking logic for large PDFs
- Structured analysis output (JSON schema: entities, classification, implications, deadlines)
- Multi-PDF filing handling (analyze each, combine results)

**Addresses:**
- Table stakes: LLM analysis (entity extraction, classification, implications, deadlines), structured output
- Stack: Claude CLI via subprocess
- Architecture: Analyzer component
- Differentiators: Sentiment analysis, key quotes (easy prompt additions)

**Avoids:**
- Pitfall 4: Context overflow (token counting, chunking, section prioritization)
- Pitfall 11: CLI invocation fragility (timeouts, exit codes, output validation)

**Needs research:** Likely yes—`/gsd:research-phase` on Claude CLI specifics: How does `claude -p` handle PDF paths? Does it need --file flag? What's the stdin piping approach for long content? What timeout characteristics? This is underdocumented and needs prototyping.

### Phase 4: Notification & Integration
**Rationale:** With scraping, extraction, and analysis working, wire everything together via the Orchestrator and add email delivery. This phase completes the end-to-end pipeline.

**Delivers:**
- Gmail SMTP notifier with HTML email templates
- Orchestrator coordinating all components
- Per-filing error isolation (try/except per filing)
- Idempotent run logic (check state before processing)
- Email formatting with analysis highlights, metadata, REGDOCS links

**Addresses:**
- Table stakes: Per-filing email notification, error recovery and retry, email delivery confirmation
- Stack: smtplib + email (stdlib)
- Architecture: Notifier, Orchestrator integration
- Differentiators: Daily digest option (alternative email mode)

**Avoids:**
- Pitfall 5: All-or-nothing pipeline (per-filing isolation in Orchestrator)
- Pitfall 7: Gmail deliverability (app password setup, HTML formatting for whitelisting)

**Needs research:** No—Gmail SMTP with app passwords is well-documented. Standard pattern.

### Phase 5: Scheduling & Monitoring
**Rationale:** Deploy for unattended operation. Add scheduling, operational monitoring (heartbeat), and hardening (graceful shutdown, metrics tracking).

**Delivers:**
- Windows Task Scheduler setup for 2-hour cycle
- External heartbeat monitoring (Healthchecks.io integration)
- Run history tracking in SQLite (run_log table)
- Health check and "still alive" confirmations
- Graceful shutdown handling (complete current filing before exit)

**Addresses:**
- Table stakes: Scheduled 2-hour execution
- Stack: Windows Task Scheduler
- Differentiators: Health check heartbeat, metrics tracking

**Avoids:**
- Pitfall 8: Scheduler silent failures (external heartbeat, lookback window on startup)
- Pitfall 12: Timezone edge cases (UTC internally, aware datetimes)
- Pitfall 13: Poor logging (structured logging from Phase 1, augmented here)

**Needs research:** No—Task Scheduler and heartbeat patterns are well-known.

### Phase Ordering Rationale

The order follows three principles:

1. **Dependency-driven**: Can't download without scraping. Can't analyze without extracting. Can't notify without analyzing. State tracking is needed before first production run.

2. **Risk-prioritized**: Build highest-risk components first (Scraper, Analyzer) to validate approach early. If REGDOCS scraping is fundamentally broken or Claude CLI integration is untenable, learn that in Phase 1-3, not Phase 5.

3. **Value-incremental**: Each phase produces testable output. Phase 1 proves we can get filing data. Phase 2 proves we can extract PDF text. Phase 3 proves Claude analysis works. Phase 4 delivers the full pipeline. Phase 5 makes it operational.

### Research Flags

**Needs deeper research during planning:**
- **Phase 1 (Scraper):** Not library research but discovery—must inspect live REGDOCS site with Playwright to map internal API endpoints, pagination behavior, metadata fields. First-order work item: "Use Playwright DevTools to capture all XHR/fetch calls when loading filing list. Document endpoint URLs, parameters, response structure." This informs whether Phase 1 ends with httpx-based API client or Playwright DOM scraper.

- **Phase 3 (Analyzer):** Likely needs `/gsd:research-phase` on Claude CLI invocation patterns. Training data doesn't cover `claude -p` subprocess specifics. Questions: PDF handling approach (path vs stdin), timeout characteristics, output format control, error codes. Recommend prototyping with sample PDFs early in Phase 3 planning.

**Standard patterns (skip research-phase):**
- **Phase 2 (PDF Processing):** PyMuPDF and pdfplumber usage is well-documented. Standard PDF extraction patterns apply. Only invoke research if OCR becomes needed—then research Tesseract accuracy on regulatory docs.

- **Phase 4 (Notifications):** Gmail SMTP with app passwords is thoroughly documented. Email HTML templates are standard web development. No research needed.

- **Phase 5 (Scheduling):** Windows Task Scheduler and external heartbeat monitoring (Healthchecks.io) are well-established patterns. No research needed.

### Deferred to Future Iterations

Research identified valuable features that should wait until core pipeline is proven:

**v2 candidates:**
- Cross-filing relationship detection (requires knowledge graph, complex)
- Proceeding timeline construction (needs accumulated history over weeks)
- Multi-document daily synthesis (run after all filings, summarize across)
- Full OCR pipeline (only if scanned PDFs prove common—most CER filings are text-based)

**Never build (anti-features):**
- Web dashboard UI (email interface is correct for this use case)
- Multi-user authentication (single-user tool)
- Real-time sub-2-hour monitoring (not needed for regulatory timescales)
- Custom LLM fine-tuning (prompt engineering sufficient)

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | MEDIUM | Recommendations (Playwright, PyMuPDF, httpx) are high confidence. Exact versions could not be verified—training data current through mid-2025. Using `>=` version specifiers in dependencies mitigates this. `uv add` will resolve latest compatible versions. Claude CLI subprocess approach is sound but invocation details need Phase 3 validation. |
| Features | MEDIUM | Feature classification (table stakes vs differentiators) based on regulatory scraping domain patterns from training data. CER REGDOCS-specific feature needs could not be verified (web tools unavailable). Recommendation: validate table stakes against actual REGDOCS filings in Phase 1. Volume assumption (10-50/day) from project context is HIGH confidence. |
| Architecture | MEDIUM-HIGH | Sequential pipeline pattern for ETL is HIGH confidence—well-established, appropriate for volume. Component boundaries and responsibilities are clear. Main uncertainty: REGDOCS page structure and API availability (LOW confidence—not verified). This affects Scraper implementation details but not overall architecture. Build order rationale is HIGH confidence—dependency-driven and risk-prioritized. |
| Pitfalls | HIGH (patterns), MEDIUM (CER-specific) | Critical pitfalls (JS rendering, no deduplication, PDF variability, context overflow, all-or-nothing failure) are HIGH confidence—these are universal scraping/LLM pipeline issues documented across training data. CER-specific details (rate limiting behavior, site update frequency, PDF format distribution) are LOW confidence—could not verify against live site. Mitigation strategies are HIGH confidence. |

**Overall confidence: MEDIUM**

The recommended approach (sequential pipeline, two-phase scraping, tiered PDF extraction, per-filing error isolation) is sound and based on well-established patterns. The stack choices are appropriate for the domain. The main gaps are CER REGDOCS-specific details that can only be resolved by actually inspecting the site and processing real filings—this is expected and addressable in Phase 1-2.

### Gaps to Address

**Gap 1: REGDOCS internal API structure**
- **What's unknown:** Does REGDOCS expose JSON/XML API endpoints behind the JS frontend? What are the endpoint URLs, parameters, authentication requirements, rate limits? Or is DOM parsing the only option?
- **How to address:** Phase 1 first work item is API discovery. Use Playwright with network interception to load the filing list page and capture all XHR/fetch requests. Document endpoint URLs, request parameters, response schemas. If usable API found, build httpx client. If not, fall back to Playwright DOM parsing. Budget 1-2 days for this discovery.
- **Impact if not addressed:** Risk building Playwright DOM scraper when a more reliable API exists, or building API client for non-existent API. Discovery must happen before committing to implementation approach.

**Gap 2: Claude CLI subprocess invocation details**
- **What's unknown:** How does `claude -p` accept PDF input? Does it read files by path mentioned in prompt text? Is there a --file or -f flag? For long content (large PDFs), should we pipe text via stdin or write to temp files? What are realistic timeout values? What exit codes indicate what failures?
- **How to address:** Phase 3 prototype task: create small test script that invokes `claude -p` with sample PDF in various ways (path in prompt, stdin piping, different flags). Measure timeout characteristics with different PDF sizes. Document working invocation pattern before building Analyzer. Consider reaching out to Anthropic docs or community if not documented.
- **Impact if not addressed:** Risk building Analyzer that hangs, truncates input, or misinterprets errors. This is second-highest technical risk after scraping.

**Gap 3: PDF format distribution in actual CER filings**
- **What's unknown:** What percentage of CER filings are text-based PDFs vs scanned images? How common are 100+ page documents? Are there encrypted/password-protected filings?
- **How to address:** Phase 2 validation task: manually download 20-30 recent filings from REGDOCS. Run PyMuPDF extraction, measure text length, identify scanned docs. This informs whether OCR fallback is needed for MVP or can be deferred. Measure page counts to validate token counting/chunking thresholds.
- **Impact if not addressed:** Risk over-engineering (building OCR when unnecessary) or under-engineering (skipping OCR when many filings are scanned). Sampling real filings provides empirical basis for extraction strategy.

**Gap 4: REGDOCS pagination and date range behavior**
- **What's unknown:** How many filings per page on the "Recent Filings" listing? Is there pagination or infinite scroll? What is the date range of "recent"—7 days? 30 days? 90 days? Can we filter by date range in search parameters?
- **How to address:** Phase 1 scraping task: manually inspect REGDOCS listing page, check URL parameters, test pagination controls. Document findings. This informs whether scraper needs multi-page navigation and whether incremental polling (date-range filtering) is feasible.
- **Impact if not addressed:** Risk scraping only page 1 of listings, missing filings. Or unnecessarily scraping many pages when date filtering could narrow scope.

**Gap 5: Gmail sending quotas and deliverability for automated emails**
- **What's unknown:** Current Gmail sending limits (training data says 500/day consumer, 2000/day Workspace—may have changed). Will HTML emails from script land in spam without SPF/DKIM? Is app password approach still supported?
- **How to address:** Phase 4 early task: set up Gmail app password, send test emails to personal account, check spam folder. Send burst of 10 emails to test rate limiting behavior. Document any deliverability issues. If spam is a problem, research email authentication requirements.
- **Impact if not addressed:** Risk production emails landing in spam, or hitting quota earlier than expected. Email is the only delivery mechanism—must work reliably.

## Sources

Research was conducted using training data through mid-2025. External web tools (WebSearch, WebFetch) were unavailable, so CER REGDOCS-specific details could not be verified against the live site.

### Primary (HIGH confidence)

**Domain patterns:**
- Regulatory document scraping and monitoring pipelines (government compliance systems, legal document processing)
- ETL pipeline architecture patterns (sequential processing, state tracking, error isolation)
- PDF text extraction approaches for mixed document types (machine-generated, scanned, table-heavy)
- LLM document analysis pipelines (chunking, context management, structured output)

**Technology stack:**
- Playwright for browser automation of JS-rendered sites (official docs, established best practices)
- PyMuPDF and pdfplumber for PDF text extraction (benchmarks, comparison studies)
- SQLite for local state tracking in Python applications (stdlib documentation, usage patterns)
- Gmail SMTP with app passwords (Google support documentation patterns)
- Windows Task Scheduler for periodic script execution (Windows documentation patterns)

**Confidence basis:** These are well-documented, widely-used technologies and patterns with stable APIs and extensive community knowledge. Training data includes official documentation, tutorial content, Stack Overflow discussions, and GitHub projects demonstrating these patterns.

### Secondary (MEDIUM confidence)

**Stack versions:**
- Playwright >=1.49, httpx >=0.27, PyMuPDF >=1.24, pdfplumber >=0.11, python-dotenv >=1.0
- Version recommendations based on training data through mid-2025. Using `>=` specifiers allows package manager to resolve latest compatible versions. Actual latest versions at install time may be higher.

**Feature expectations:**
- Table stakes vs differentiators classification based on regulatory scraping domain conventions
- Feature complexity estimates (low/medium/high) based on similar project patterns
- MVP scope recommendations based on 10-50 filings/day volume and 2-hour cycle constraints

**Confidence basis:** Multiple sources (documentation, community discussions, project examples) generally agree, but specifics couldn't be verified against current package repositories or CER REGDOCS requirements.

### Tertiary (LOW confidence - needs validation)

**CER REGDOCS-specific:**
- Whether REGDOCS site is JS-rendered (assumed based on modern government site patterns, but not verified)
- Whether internal API endpoints exist (common pattern but not confirmed for REGDOCS)
- PDF format distribution (text-based vs scanned) in CER filings (assumed mostly text-based per government filing norms)
- REGDOCS pagination structure and date range of "recent" filings
- CER site anti-bot measures and rate limiting behavior
- REGDOCS site update frequency and stability of HTML structure

**Confidence basis:** Inference from general government website patterns and regulatory filing system norms. These claims must be validated by inspecting the live CER REGDOCS site in Phase 1. The architectural approach (API discovery first, Playwright fallback) is designed specifically to handle this uncertainty.

**Validation approach:** Phase 1 includes explicit discovery tasks:
1. Load REGDOCS recent filings page with Playwright DevTools network tab open
2. Capture all XHR/fetch requests, document endpoint URLs and response formats
3. Test pagination and date filtering parameters
4. Sample 20-30 recent filings for PDF format analysis
5. Test polite scraping (delays, headers) and monitor for rate limit responses
6. Document findings to inform scraper implementation approach

---

**Research completed:** 2026-02-05
**Ready for roadmap:** Yes

**Next steps for orchestrator:**
1. Load this SUMMARY.md into roadmap creation context
2. Use phase suggestions (1-5) as starting point for roadmap structure
3. Reference research flags for phase planning—Phase 1 and Phase 3 need discovery/prototyping work items, other phases can proceed with standard patterns
4. Link pitfall mitigation strategies to specific phase requirements
5. Use stack recommendations to inform technology requirements per phase
6. Validate gaps (REGDOCS API structure, Claude CLI invocation, PDF sampling, pagination) are addressed in early phase work items
