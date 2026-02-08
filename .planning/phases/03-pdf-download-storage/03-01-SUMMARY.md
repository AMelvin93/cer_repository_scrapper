---
phase: 03-pdf-download-storage
plan: 01
subsystem: downloader
tags: [httpx, tenacity, streaming, retry, pdf-download]
requires:
  - phase-01 (config, database models)
provides:
  - download_pdf() function for single-PDF download with retry
  - DownloadResult dataclass for outcome reporting
  - PipelineSettings download config fields
affects:
  - 03-02 (filing-level orchestrator will call download_pdf)
  - phase-04 (text extraction reads downloaded PDFs)
tech-stack:
  added: []
  patterns:
    - ".tmp rename pattern for atomic file writes"
    - "tenacity retry decorator for transient HTTP errors"
    - "httpx streaming response for memory-efficient large file download"
key-files:
  created:
    - src/cer_scraper/downloader/__init__.py
    - src/cer_scraper/downloader/service.py
  modified:
    - src/cer_scraper/config/settings.py
    - config/pipeline.yaml
key-decisions:
  - "Content-Type check rejects text/html but allows missing/ambiguous types"
  - "Size limit enforced at two points: Content-Length header pre-check and streaming byte count"
  - "tenacity retries only httpx.HTTPStatusError and TransportError (not all exceptions)"
  - ".tmp file cleanup in finally block ensures no corrupt partial files remain on disk"
duration: "2.1 min"
completed: 2026-02-07
---

# Phase 03 Plan 01: Download Config and PDF Service Summary

Streaming PDF download service with tenacity retry, .tmp rename pattern, Content-Type validation, and dual size-limit enforcement via httpx.Client.stream

## Performance

- **Duration:** ~2.1 minutes
- **Tasks:** 2/2 completed
- **Deviations:** 0

## Accomplishments

1. Extended PipelineSettings with four download configuration fields (filings_dir, max_pdf_size_bytes, download_chunk_size, download_timeout_seconds) loaded from pipeline.yaml with env var override support
2. Created the downloader package with a single-PDF download service implementing streaming chunked writes, Content-Type rejection for HTML responses, file size limits (header + streaming), .tmp-to-.pdf atomic rename, and tenacity retry (3 attempts, exponential backoff 2-30s)

## Task Commits

| Task | Name | Commit | Key Changes |
|------|------|--------|-------------|
| 1 | Add download configuration fields to PipelineSettings | cfa79d8 | settings.py + pipeline.yaml: 4 new fields |
| 2 | Create PDF download service | a677983 | downloader/__init__.py + service.py (213 lines) |

## Files Created

- `src/cer_scraper/downloader/__init__.py` -- Package init stub with docstring
- `src/cer_scraper/downloader/service.py` -- download_pdf() + DownloadResult dataclass (213 lines)

## Files Modified

- `src/cer_scraper/config/settings.py` -- Added filings_dir, max_pdf_size_bytes, download_chunk_size, download_timeout_seconds to PipelineSettings
- `config/pipeline.yaml` -- Added Phase 3 download settings block with defaults

## Decisions Made

1. **Content-Type validation strategy:** Reject responses containing `text/html` (REGDOCS viewer pages). Allow missing or ambiguous Content-Types to proceed with download since some servers don't set headers correctly.
2. **Dual size enforcement:** Check Content-Length header before download starts (fast rejection) AND track actual bytes during streaming (catches servers that lie about Content-Length or omit it).
3. **Retry scope:** tenacity retries only `httpx.HTTPStatusError` and `httpx.TransportError` -- unexpected errors (e.g., filesystem errors) are not retried since they won't resolve on their own.
4. **Temp file pattern:** Write to `.pdf.tmp`, rename to `.pdf` on success. The `finally` block ensures `.tmp` cleanup even on exceptions, preventing corrupt partial files.

## Deviations from Plan

None -- plan executed exactly as written.

## Issues Encountered

None.

## Next Phase Readiness

- Plan 03-02 (filing-level download orchestrator) can now call `download_pdf()` with an httpx.Client and PipelineSettings to download individual PDFs
- The DownloadResult dataclass provides structured outcome reporting for the orchestrator to update database state
- No blockers identified for Plan 02 execution

## Self-Check: PASSED
