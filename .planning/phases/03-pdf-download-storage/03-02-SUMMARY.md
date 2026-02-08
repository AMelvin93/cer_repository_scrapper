---
phase: 03-pdf-download-storage
plan: 02
subsystem: downloader
tags: [orchestrator, all-or-nothing, batch-download, rate-limiter, httpx]
requires:
  - phase-01 (config, database models, state store)
  - 03-01 (download_pdf service, PipelineSettings download fields)
provides:
  - download_filings() public API for batch PDF download
  - DownloadBatchResult dataclass for aggregated statistics
  - get_filings_for_download() state query with eager document loading
affects:
  - phase-04 (text extraction will process downloaded PDFs)
  - future pipeline runner (calls download_filings after scrape step)
tech-stack:
  added: []
  patterns:
    - "All-or-nothing download semantics with directory cleanup on failure"
    - "Per-filing error isolation (one failure does not block others)"
    - "Reused httpx.Client across all downloads for connection pooling"
    - "selectinload for eager relationship loading"
key-files:
  created:
    - src/cer_scraper/downloader/__init__.py (273 lines, filing-level orchestrator)
  modified:
    - src/cer_scraper/db/state.py (added get_filings_for_download)
    - src/cer_scraper/db/__init__.py (exported get_filings_for_download)
key-decisions:
  - "All-or-nothing semantics: if any document fails, entire filing directory is cleaned up via shutil.rmtree"
  - "Document records reset to download_status=failed on any failure within the filing"
  - "Rate limiter reused between PDF downloads within a filing (skips after last document)"
  - "Each filing committed independently to avoid long-running transactions"
  - "Top-level catch-all prevents orchestrator from crashing pipeline"
  - "Filing directory convention: {YYYY-MM-DD}_Filing-{id}/documents/doc_NNN.pdf"
duration: "2.1 min"
completed: "2026-02-08"
---

# Phase 03 Plan 02: Filing-Level Download Orchestrator Summary

Filing-level orchestrator with all-or-nothing download semantics, per-filing error isolation, and batch statistics via DownloadBatchResult

## Performance

- Execution time: ~2.1 minutes
- 2 tasks, both auto (no checkpoints)
- Zero deviations from plan

## Accomplishments

1. **Added `get_filings_for_download()` to state store** -- queries filings with status_scraped=success, status_downloaded!=success, under retry limit, with eagerly loaded documents via selectinload to avoid N+1 queries.

2. **Created the filing-level download orchestrator** (273 lines) with:
   - `DownloadBatchResult` dataclass tracking attempted/succeeded/failed/skipped filings, PDF count, bytes, and error messages
   - `_build_filing_dir()` producing `{YYYY-MM-DD}_Filing-{id}/documents/` paths (with unknown-date fallback)
   - `_download_filing()` iterating documents sequentially with `doc_001.pdf` naming, all-or-nothing cleanup via `shutil.rmtree` on any failure, document record updates on success
   - `download_filings()` public API that queries pending filings, creates a shared httpx.Client, processes each filing independently with per-filing commits, and returns aggregated batch result
   - Rate limiting between downloads via existing `wait_between_requests()`
   - Top-level catch-all error handling (orchestrator never crashes the pipeline)

## Task Commits

| Task | Name | Commit | Key Changes |
|------|------|--------|-------------|
| 1 | Add get_filings_for_download to state store | 4e3d633 | state.py + db/__init__.py: new query with selectinload |
| 2 | Create filing-level download orchestrator | 89a30a5 | downloader/__init__.py: 273-line orchestrator |

## Files Created

| File | Lines | Purpose |
|------|-------|---------|
| src/cer_scraper/downloader/__init__.py | 273 | Filing-level download orchestrator |

## Files Modified

| File | Changes |
|------|---------|
| src/cer_scraper/db/state.py | Added get_filings_for_download() with selectinload |
| src/cer_scraper/db/__init__.py | Exported get_filings_for_download |

## Decisions Made

1. **All-or-nothing semantics**: If any document in a filing fails to download, the entire filing directory tree is removed with `shutil.rmtree` and all document records are reset to `download_status="failed"`. This prevents partial downloads from being treated as complete.

2. **Per-filing error isolation**: Each filing is processed independently with its own try/except and commit. One filing's failure does not prevent other filings from being downloaded.

3. **Shared httpx.Client**: A single httpx.Client is created with context manager and reused across all downloads in a batch for connection pooling efficiency.

4. **Rate limiting between documents**: `wait_between_requests()` is called between consecutive document downloads within a filing, reusing the scraper's existing rate limiter with ScraperSettings delay parameters.

5. **Filing directory convention**: `{YYYY-MM-DD}_Filing-{filing_id}/documents/doc_001.pdf` with `unknown-date` fallback when filing.date is None.

6. **Per-filing commits**: Database commits happen after each filing (both document record updates and filing status update) to avoid long-running transactions.

## Deviations from Plan

None -- plan executed exactly as written.

## Issues

None.

## Next Phase Readiness

Phase 3 is now COMPLETE. The pipeline can:
- Scrape filings from REGDOCS (Phase 2)
- Download all PDFs for scraped filings with resilience (Phase 3)
- Skip filings already downloaded or over retry limit
- Handle failures gracefully with all-or-nothing semantics

Phase 4 (PDF text extraction) can begin -- it will read the downloaded PDFs from the `data/filings/` directory structure established in this plan.

## Self-Check: PASSED
