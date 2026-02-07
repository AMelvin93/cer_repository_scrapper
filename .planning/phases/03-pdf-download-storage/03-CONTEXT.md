# Phase 3: PDF Download & Storage - Context

**Gathered:** 2026-02-07
**Status:** Ready for planning

<domain>
## Phase Boundary

Download every PDF associated with a scraped filing to organized local folders with resilience against transient network failures. Re-running the pipeline skips already-downloaded filings. Text extraction, analysis, and email delivery are separate phases.

</domain>

<decisions>
## Implementation Decisions

### Folder structure
- Top-level: `data/filings/{YYYY-MM-DD}_Filing-{ID}/` — date-prefixed for chronological browsing
- PDFs go in a `documents/` subfolder within each filing folder (leaves room for analysis output later)
- PDF filenames use sequential numbering: `doc_001.pdf`, `doc_002.pdf`, etc.
- No on-disk metadata file — all metadata (original filename, source URL, download timestamp) lives in SQLite only

### Download behavior
- Sequential downloads — one PDF at a time, no concurrency
- Stream to disk (chunked writes) — handles any file size with low memory usage
- Configurable maximum file size limit — skip PDFs above threshold and log a warning
- Reuse the existing scraper rate limiter (1-3 second delay) between PDF downloads

### Skip/dedup logic
- Database flag is source of truth for "already downloaded" — no filesystem checks on each run
- Claude's discretion: whether to verify file existence on disk as a self-healing check
- Assume REGDOCS PDFs are immutable — no update/change detection needed
- All-or-nothing per filing: filing marked as downloaded only when ALL its PDFs succeed; on failure, next run re-downloads the entire filing

### Failure handling
- 3 retries with exponential backoff per PDF download (matches ROADMAP success criteria)
- On exhausted retries: mark filing as `download_failed`, skip in this run, retry on next pipeline run (capped by state store's max_retries)
- Delete partial/incomplete files on failure — no corrupt PDFs left on disk
- One filing's failure does not block others — log error and continue to next filing

</decisions>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 03-pdf-download-storage*
*Context gathered: 2026-02-07*
