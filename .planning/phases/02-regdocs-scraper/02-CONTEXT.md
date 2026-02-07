# Phase 2: REGDOCS Scraper - Context

**Gathered:** 2026-02-07
**Status:** Ready for planning

<domain>
## Phase Boundary

Discover and retrieve filing metadata from the CER REGDOCS website. The scraper returns filing dates, applicants, types, proceeding numbers, and document URLs. PDF downloading, text extraction, and analysis are separate phases.

</domain>

<decisions>
## Implementation Decisions

### Discovery strategy
- Use Playwright automated network interception to discover REGDOCS API endpoints at runtime
- Discover endpoints fresh every run (no caching of discovered endpoints between runs)
- If interception finds no usable API endpoints, retry 2-3 times with different page navigations before falling back to DOM parsing
- Both API and DOM parsing paths should be robust, first-class strategies — either could serve as primary depending on what REGDOCS exposes

### Filing scope & filtering
- Configurable lookback period for how far back each run searches (default TBD during planning)
- Configurable filing type filter — default to all types, allow include/exclude list in config
- Configurable applicant/company and proceeding number filters in config
- Deduplication: check state store before processing; skip filings already processed successfully

### Resilience & rate behavior
- Randomized delays between 1-3 seconds per request to appear natural
- 3 retries with exponential backoff on HTTP errors/timeouts, then log failure and move on
- Zero-filing warning after 3 consecutive runs — log warning only (monitoring/alerting deferred to Phase 10)
- Validation checks after each scrape: verify expected fields present and values in reasonable ranges; log detailed errors if validation fails (detects site structure changes)

### Data completeness
- Skip filings entirely if they have no document URLs — nothing to analyze means nothing to report
- Capture all document URLs associated with a filing (multiple PDFs, appendices, etc.)
- Capture URLs for all document types (PDFs, Word docs, Excel, etc.) — not just PDFs
- Filings with at least one document URL but missing other metadata: store with placeholders (e.g., "Unknown" applicant) — LLM analysis may extract missing info from document content

### Claude's Discretion
- Partial metadata handling: define minimum required fields vs. placeholder strategy
- Specific Playwright interception implementation details
- Exact exponential backoff timing
- Default lookback period value
- robots.txt parsing implementation

</decisions>

<specifics>
## Specific Ideas

- REGDOCS internal API structure is unknown — discovery is the core technical risk of this phase
- The scraper must work on Windows (Task Scheduler deployment target from Phase 10)
- User-Agent header should be descriptive (not impersonating a browser)
- robots.txt directives must be respected per roadmap requirements

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 02-regdocs-scraper*
*Context gathered: 2026-02-07*
