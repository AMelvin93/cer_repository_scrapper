# Feature Landscape

**Domain:** Regulatory document scraping, monitoring, and LLM-powered analysis (CER REGDOCS)
**Researched:** 2026-02-05
**Confidence:** MEDIUM (based on training data for regulatory scraping patterns; web verification unavailable)

---

## Table Stakes

Features the tool MUST have or it fails its core purpose. Missing any of these means the scraper cannot reliably do its job.

### Scraping and Document Acquisition

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **REGDOCS listing page scraper** | Core function -- must parse the CER filing list to discover new documents | Medium | REGDOCS uses server-rendered HTML with pagination. Need to handle the search/listing interface. May need to handle JavaScript-rendered content (check if SSR or requires browser). |
| **PDF download pipeline** | Most CER filings are PDFs -- cannot analyze what you cannot download | Low-Medium | Straightforward HTTP download but must handle: large files (some filings are 100+ pages), timeouts, partial downloads, content-type validation. |
| **Filing metadata extraction** | Need structured data (date, applicant, filing type, document title, proceeding) before analysis | Medium | Parse from listing page HTML. CER REGDOCS shows: filing date, document type, applicant/company name, proceeding/hearing number, document title, file ID. |
| **Deduplication / already-processed tracking** | Without this, every 2-hour cycle re-processes everything -- wastes API calls, sends duplicate emails | Low-Medium | Must persist a record of processed filing IDs. Simple approach: SQLite or JSON file mapping filing ID to processed status. Filing IDs from REGDOCS are unique. |
| **Scheduled execution (2-hour cycle)** | Core requirement -- must check automatically without manual intervention | Low | Cron job, Windows Task Scheduler, or Python scheduler (e.g., `schedule` library). Keep the runner simple -- cron/Task Scheduler is more reliable than in-process scheduling for a long-running service. |
| **Error recovery and retry logic** | Network failures, CER site downtime, PDF download failures -- must not crash and lose state | Medium | Must handle: connection timeouts, HTTP 5xx from CER, partial PDF downloads, malformed HTML. Retry with exponential backoff. Never lose track of what was/wasn't processed. |
| **Basic logging** | Must know what happened when it ran -- debugging blind scraping is painful | Low | Structured logging with timestamps, filing IDs, success/failure status. Log to file with rotation. |

### PDF Processing

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **PDF text extraction** | Cannot analyze a PDF without extracting its text content | Medium | Use `pdfplumber` or `PyMuPDF (fitz)`. CER filings are typically text-based PDFs (not scanned images), but some may be scanned. Handle both gracefully. |
| **Large PDF handling** | Some regulatory filings are 200+ pages -- must not OOM or timeout | Medium | Stream/chunk processing. For LLM analysis, may need to split into sections or summarize progressively. Claude context window is large but not infinite. |
| **PDF download verification** | Corrupted/truncated PDFs will silently produce garbage analysis | Low | Verify file size > 0, validate PDF header bytes, attempt to open with PDF library before analysis. |

### LLM Analysis

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **Entity extraction** | Core analysis deliverable -- who, what companies, what facilities are mentioned | Medium | Claude handles this well via prompting. Structure output as JSON for downstream use. Entities: companies, people, facilities, pipelines, geographic locations. |
| **Document classification** | Must categorize filing type (application, compliance, order, letter, evidence, etc.) | Low-Medium | Prompt-based classification. CER has known document types. Provide taxonomy in prompt. |
| **Regulatory implications summary** | Core value -- "what does this filing mean?" in plain language | Medium | This is the primary value-add. Prompt must be tuned to extract: what action is being requested, what the regulatory impact is, who is affected. |
| **Deadline/date extraction** | Regulatory filings often contain response deadlines, hearing dates, compliance dates | Medium | Dates in regulatory docs are critical. Extract and structure: comment deadlines, hearing dates, compliance milestones, effective dates. |
| **Structured output format** | Analysis must be machine-parseable for email formatting and potential future use | Low-Medium | Define a consistent JSON schema for analysis output. All fields optional (not every filing has deadlines, etc.) but schema is fixed. |

### Notification

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **Per-filing email via Gmail** | Core delivery mechanism -- user receives analysis results by email | Medium | Gmail API (OAuth2) or SMTP with app password. Gmail API is more reliable and avoids rate-limit issues with SMTP. Must handle: HTML formatting, attachment of analysis, rate limiting (10-50 emails/day is well within Gmail limits). |
| **Email formatting with analysis highlights** | Raw text dump is useless -- need structured, scannable email | Medium | HTML email template with sections: filing metadata, classification, key entities, regulatory implications, deadlines, sentiment. Must be readable on mobile. |
| **Email delivery confirmation / error handling** | Must know if email failed to send (quota, auth, network) | Low | Log success/failure per email. Retry failed sends on next cycle. Do not re-analyze -- just retry the send. |

### Storage

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **Local folder storage for PDFs** | Specified requirement -- keep downloaded PDFs organized locally | Low | Organize by date or filing ID. Convention: `downloads/YYYY-MM-DD/filing_id.pdf` or `downloads/filing_id/document.pdf`. |
| **Processing state persistence** | Must survive restarts -- know what has been processed, what failed, what is pending | Low-Medium | SQLite is the right tool here. Track: filing_id, discovery_time, download_status, analysis_status, email_status, error_messages. |
| **Analysis results storage** | Keep analysis output locally for reference, debugging, and potential re-sends | Low | Save JSON analysis alongside PDF. Enables re-sending emails without re-analyzing. |

---

## Differentiators

Features that add significant value but the tool functions without them. Build after core is solid.

### Enhanced Analysis

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Sentiment/tone analysis** | Understand if filing is adversarial, cooperative, routine, urgent | Low | Easy to add as another prompt field. Useful for prioritization. "This compliance order has an urgent/adversarial tone." |
| **Cross-filing relationship detection** | Link related filings (e.g., application + intervention + response) | High | Requires maintaining a knowledge graph of proceedings. Match by proceeding number, company name, topic. Very valuable but complex. Defer to v2+. |
| **Proceeding timeline construction** | Build a timeline of all filings in a proceeding | Medium-High | Group filings by proceeding ID, order chronologically, show narrative arc. Requires accumulating history over time. |
| **Key quote extraction** | Pull the most important 2-3 sentences from the filing | Low-Medium | Add to LLM prompt. Very useful for email scanning -- "the filing says X." |
| **Regulatory change impact scoring** | Rate 1-5 how impactful this filing is to industry/stakeholders | Low | Prompt-based scoring. Subjective but useful for prioritization. "Is this routine or significant?" |
| **Multi-document summarization** | Daily digest that summarizes ALL filings from the day, not just per-filing | Medium | Run after all filings processed. Synthesize across filings: "Today CER published 12 filings, 3 related to pipeline safety, 1 new application..." |

### Enhanced Scraping

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Incremental/smart polling** | Only fetch listing pages since last check, not full re-scan | Medium | REGDOCS may support date-range filtering in search. Use last-processed timestamp to narrow search window. Reduces load on CER servers and speeds up cycles. |
| **Rate limiting / polite scraping** | Avoid getting blocked by CER. Government sites sometimes throttle aggressively | Low | Add delays between requests (1-3 seconds). Set a proper User-Agent. Respect robots.txt. Essential for long-term reliability. |
| **Headless browser fallback** | If REGDOCS requires JavaScript for some content | High | Only needed if parts of REGDOCS are client-rendered. Start with `requests`/`httpx` + `BeautifulSoup`. Fall back to Playwright only if needed. Adds significant complexity. |
| **Attachment handling (non-PDF)** | Some filings include Excel spreadsheets, Word docs, ZIP archives | Medium | Extract text from .docx (python-docx), .xlsx (openpyxl), ignore binary formats. Adds coverage but most CER filings are PDF. |

### Enhanced Notification

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Daily digest email** | One consolidated email per day summarizing all filings | Medium | Alternative to per-filing emails. Some users prefer one email with 10-50 summaries vs 10-50 individual emails. Could offer both modes. |
| **Priority flagging in email subject** | "[HIGH] New Pipeline Application" vs "[LOW] Routine Compliance Update" | Low | Based on classification + impact scoring. Simple string prefix in subject line. |
| **Email with PDF attachment** | Attach the original PDF to the analysis email | Low | Easy technically but increases email size significantly. Make configurable. |

### Operational

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Health check / heartbeat** | Know the scraper is still running and healthy | Low | Log a heartbeat entry each cycle. Optionally send a "still alive" email daily. |
| **Metrics / stats tracking** | How many filings processed, avg analysis time, error rates | Low-Medium | Track in SQLite. Useful for debugging and understanding system behavior over time. |
| **Configuration file** | Externalize settings (check interval, email recipients, download path, etc.) | Low | `.env` file or `config.yaml`. Avoid hardcoding paths, credentials, intervals. |
| **Graceful shutdown** | Handle Ctrl+C / SIGTERM without corrupting state | Low | Signal handlers that complete current filing before exiting. Important for data integrity. |
| **OCR fallback for scanned PDFs** | Handle scanned-image PDFs that have no extractable text | Medium-High | Use Tesseract OCR via `pytesseract`. Adds a heavy dependency. Most CER filings are text PDFs, so this is rare but important for completeness. |

---

## Anti-Features

Features to explicitly NOT build in v1. These are common mistakes, scope creep, or premature optimization.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| **Web dashboard / UI** | Massive scope increase. This is a backend automation tool, not a web app. Building a UI triples development time for v1. | Use email as the interface. Store results as files/SQLite for manual inspection. Build a UI only if the tool proves valuable and the email interface becomes limiting. |
| **User authentication / multi-tenancy** | Single-user tool. Adding auth adds complexity with zero value. | Hardcode the single user's email. Revisit only if multiple people need access. |
| **Full-text search across filings** | Requires building a search index (Elasticsearch, etc.). Overkill for 10-50 filings/day. | Use file system search or SQLite queries for ad-hoc lookups. |
| **Real-time / webhook-based monitoring** | CER REGDOCS does not offer webhooks or real-time feeds. Polling every 2 hours is the right approach. Trying to reduce latency below 2 hours adds complexity with no benefit. | Stick with scheduled polling. 2-hour granularity is appropriate for regulatory filings which move on days/weeks timescales. |
| **Filtering / topic selection** | Project spec says "all filings processed -- no filtering." Building a filtering system is wasted effort. | Process everything. If volume becomes unmanageable (unlikely at 10-50/day), add filtering later. |
| **Custom LLM fine-tuning** | Prompt engineering with Claude is sufficient for this use case. Fine-tuning is expensive, slow to iterate, and unnecessary. | Use well-crafted system prompts with few-shot examples. Iterate prompts based on output quality. |
| **Database server (PostgreSQL, MySQL)** | Overkill for single-user, 10-50 records/day. SQLite handles this volume for decades. | Use SQLite. It's zero-config, file-based, and handles concurrent reads well. Move to a server DB only if you add multi-user or need remote access. |
| **Containerization / Docker** | Adds deployment complexity for a tool that runs on one machine. | Run directly with Python + venv/uv. Containerize only if deploying to cloud or sharing with others. |
| **Filing content diffing / change tracking** | Detecting changes between filing versions is extremely complex and rarely needed. Most filings are unique documents, not revisions. | Track by filing ID. If CER updates a filing, treat the update as a new document. |
| **Browser extension or desktop app** | Wrong interface for a background automation tool. | Email is the right notification channel for this use case. |
| **Parallel/async PDF processing** | At 10-50 filings/day with 2-hour cycles, sequential processing is fast enough. Async adds debugging complexity. | Process filings sequentially in a simple loop. Each filing: download, extract, analyze, email. If a cycle takes >30 min (unlikely), then consider parallelism. |
| **LLM provider abstraction layer** | "Support OpenAI AND Claude AND Ollama" adds complexity. Pick one and commit. | Use Claude via CLI as specified. If switching providers later, refactor then -- not now. |

---

## Feature Dependencies

```
Filing Discovery (scraper)
  |
  v
Metadata Extraction -----> Deduplication Check (already processed?)
  |                              |
  | (new filing)                 | (skip if already done)
  v                              v
PDF Download -----------> PDF Verification
  |
  v
Text Extraction (pdfplumber/PyMuPDF)
  |
  v
LLM Analysis (Claude CLI)
  |-- Entity extraction
  |-- Classification
  |-- Regulatory implications
  |-- Deadline extraction
  |-- Sentiment (differentiator)
  |
  v
Analysis Storage (JSON + SQLite status)
  |
  v
Email Composition (HTML template)
  |
  v
Email Delivery (Gmail API/SMTP)
  |
  v
Status Update (mark filing as fully processed)
```

**Critical path:** Every feature in the main pipeline is sequential and blocking. A failure at any stage must be handled gracefully:
- Download failure: retry later, do not mark as processed
- Text extraction failure: log and skip (or attempt OCR if available), mark as extraction-failed
- LLM analysis failure: retry later, do not send email
- Email failure: retry later, do not re-analyze

**Independent features (can be built in any order):**
- Logging (should be first, used everywhere)
- Configuration file (should be early, avoids hardcoding)
- Health checks (anytime after core pipeline)
- Daily digest (after per-filing email works)
- Metrics (after SQLite tracking exists)

---

## MVP Recommendation

For MVP, build these features and ONLY these features:

### Must Have (MVP)

1. **REGDOCS listing scraper** -- discover new filings from the CER website
2. **Filing metadata extraction** -- parse structured data from listing
3. **Deduplication via SQLite** -- track processed filing IDs, skip duplicates
4. **PDF download with verification** -- download and validate PDFs
5. **PDF text extraction** -- extract text content from downloaded PDFs
6. **LLM analysis via Claude CLI** -- entity extraction, classification, implications, deadlines
7. **Structured analysis output** -- consistent JSON schema for results
8. **Per-filing HTML email via Gmail** -- formatted email with analysis highlights
9. **Error handling and retry** -- graceful failure handling at each pipeline stage
10. **Structured logging** -- know what happened during each run
11. **Local file storage** -- organized PDF and analysis output storage
12. **Scheduled execution** -- 2-hour polling cycle via cron or Task Scheduler

### Build Immediately After MVP

13. **Configuration file** -- externalize all hardcoded values
14. **Rate limiting / polite scraping** -- delays between requests, proper User-Agent
15. **Sentiment analysis** -- easy add to existing LLM prompt
16. **Key quote extraction** -- easy add to existing LLM prompt
17. **Health check heartbeat** -- daily "still alive" email or log entry

### Defer to v2+

- Cross-filing relationship detection
- Proceeding timeline construction
- Daily digest email
- OCR fallback
- Multi-document summarization
- Web dashboard
- Any filtering capability

---

## Volume and Performance Considerations

| Metric | Expected Value | Implication |
|--------|---------------|-------------|
| Filings per day | 10-50 | Sequential processing is fine. No need for async/parallel. |
| Check interval | 2 hours | ~12 checks/day. Most will find 1-5 new filings. |
| PDF size | 1-200 pages typical | Most under 50 pages. Large filings (200+) need chunking for LLM. |
| Emails per day | 10-50 | Well within Gmail limits (500/day for consumer, 2000/day for Workspace). |
| Storage growth | ~50-500 MB/month | Mostly PDFs. Negligible for local storage. No cleanup needed for years. |
| Claude CLI cost | ~$0.50-5.00/day | Depends on filing length and prompt complexity. Budget ~$150/month worst case. |
| Processing time per filing | 30-120 seconds | Download (5s) + extraction (2s) + LLM analysis (20-90s) + email (3s). Full cycle of 50 filings: ~100 minutes. Fits within 2-hour window. |

---

## Sources and Confidence

| Finding | Confidence | Basis |
|---------|------------|-------|
| CER REGDOCS is HTML-based with document listings | MEDIUM | Training data knowledge of Canadian government regulatory sites. Could not verify current site structure (web tools unavailable). |
| Most CER filings are text-based PDFs | MEDIUM | Consistent with government regulatory filing norms. Some scanned documents possible. |
| 10-50 filings/day volume | HIGH | Provided in project context. |
| Gmail API handles 10-50 emails/day easily | HIGH | Well within documented Gmail quotas. |
| Sequential processing fits 2-hour window | HIGH | Back-of-envelope calculation: 50 filings x 120 seconds = 100 minutes < 120 minutes. |
| pdfplumber/PyMuPDF for text extraction | HIGH | Well-established Python PDF libraries, widely used. |
| SQLite for state tracking | HIGH | Standard pattern for single-user local data at this volume. |

**Key uncertainty:** The exact structure of the CER REGDOCS listing pages (HTML structure, pagination, search parameters, any API endpoints) needs to be verified by actually inspecting the site. This is critical for the scraping implementation and should be the FIRST research task during development.
