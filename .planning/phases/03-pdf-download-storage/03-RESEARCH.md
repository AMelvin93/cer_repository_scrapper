# Phase 3: PDF Download & Storage - Research

**Researched:** 2026-02-07
**Domain:** HTTP file downloading, streaming I/O, retry logic, filesystem organization
**Confidence:** HIGH (existing stack covers all needs; patterns are well-established)

## Summary

Phase 3 downloads PDFs associated with scraped filings to organized local folders. The existing project already has httpx (HTTP client with streaming support), tenacity (retry with exponential backoff), and a rate limiter -- all the core libraries needed. No new dependencies are required.

The primary technical concern is the REGDOCS document URL format. The Phase 2 scraper captures URLs in two forms: (1) `/Item/View/{ID}` viewer page URLs and (2) direct file download URLs (`.pdf` extension). The `/Item/View/{ID}` URLs are REGDOCS HTML viewer pages, not direct PDF downloads. The downloader must handle both: for direct links, stream the file; for viewer URLs, follow redirects and check the `Content-Type` header to determine if the response is actually a PDF. If a viewer URL returns HTML instead of a PDF binary, the downloader should log a warning and treat it as a non-downloadable document (Phase 2 already captures the URL -- Phase 3 needs to handle the case where it cannot be directly downloaded). httpx's `follow_redirects=True` setting (already used in the existing API client) will help resolve server-side redirects.

The implementation reuses the project's established patterns: httpx.Client for HTTP, tenacity for per-PDF retry, the existing rate limiter for inter-download delays, SQLAlchemy Document model for tracking download state, and the mark_step_complete state store function for filing-level status. No new libraries are needed.

**Primary recommendation:** Build a `downloader` subpackage under `src/cer_scraper/` with a single-responsibility download service that takes a Filing + its Documents from the database, downloads each PDF to `data/filings/{YYYY-MM-DD}_Filing-{ID}/documents/doc_NNN.pdf`, and updates Document/Filing records. Reuse httpx.Client with streaming, tenacity retry, and the existing rate limiter.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Folder structure: `data/filings/{YYYY-MM-DD}_Filing-{ID}/documents/` with PDFs named `doc_001.pdf`, `doc_002.pdf`, etc.
- No on-disk metadata file -- all metadata (original filename, source URL, download timestamp) lives in SQLite only
- Sequential downloads -- one PDF at a time, no concurrency
- Stream to disk (chunked writes) -- handles any file size with low memory usage
- Configurable maximum file size limit -- skip PDFs above threshold and log a warning
- Reuse the existing scraper rate limiter (1-3 second delay) between PDF downloads
- Database flag is source of truth for "already downloaded" -- no filesystem checks on each run
- Assume REGDOCS PDFs are immutable -- no update/change detection needed
- All-or-nothing per filing: filing marked as downloaded only when ALL its PDFs succeed; on failure, next run re-downloads the entire filing
- 3 retries with exponential backoff per PDF download
- On exhausted retries: mark filing as `download_failed`, skip in this run, retry on next pipeline run (capped by state store's max_retries)
- Delete partial/incomplete files on failure -- no corrupt PDFs left on disk
- One filing's failure does not block others -- log error and continue to next filing

### Claude's Discretion
- Whether to verify file existence on disk as a self-healing check (recommendation below)

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope
</user_constraints>

## Standard Stack

The phase requires NO new dependencies. Everything needed is already installed.

### Core (Already in Project)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| httpx | >=0.28.1 | HTTP client with streaming support | Already used for API requests; `Client.stream()` provides chunked download |
| tenacity | >=9.1.3 | Retry with exponential backoff | Already used in api_client.py; same pattern for download retries |
| SQLAlchemy | >=2.0.46 | ORM for Document/Filing state tracking | Already the project's persistence layer |

### Supporting (Already in Project)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pathlib (stdlib) | -- | Path construction, directory creation | Building folder paths, creating directories |
| rate_limiter module | -- | Inter-download delays | Reuse `wait_between_requests()` between downloads |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| httpx streaming | requests streaming | httpx already installed; no reason to add requests |
| tenacity | manual retry loop | tenacity already installed; cleaner code with decorator |
| pathvalidate | manual sanitization | Unnecessary since we use sequential `doc_NNN.pdf` filenames (no user-controlled filenames on disk) |

**Installation:** No new packages needed.

## Architecture Patterns

### Recommended Project Structure
```
src/cer_scraper/
    downloader/
        __init__.py         # Public API: download_filings_pdfs()
        service.py          # Core download logic: DownloadService class or functions
```

The `downloader/` subpackage mirrors the existing `scraper/` subpackage structure. Keep it small -- this phase has a focused scope.

### Pattern 1: Streaming Download with Size Guard
**What:** Use httpx.Client.stream() to download files in chunks, tracking bytes received and aborting if max size is exceeded.
**When to use:** Every PDF download.
**Example:**
```python
# Source: httpx official docs + rednafi.com pattern
from pathlib import Path
import httpx

def _download_single_pdf(
    client: httpx.Client,
    url: str,
    dest_path: Path,
    max_size_bytes: int,
    chunk_size: int = 65_536,  # 64KB chunks
) -> int:
    """Stream a PDF to disk. Returns bytes written. Raises on failure."""
    bytes_downloaded = 0

    with client.stream("GET", url) as response:
        response.raise_for_status()

        # Check Content-Length header if available (early rejection)
        content_length = response.headers.get("content-length")
        if content_length and int(content_length) > max_size_bytes:
            raise FileTooLargeError(
                f"Content-Length {content_length} exceeds max {max_size_bytes}"
            )

        # Verify response is actually a PDF (not an HTML viewer page)
        content_type = response.headers.get("content-type", "")
        if "text/html" in content_type:
            raise NotAPdfError(f"URL returned HTML, not PDF: {url}")

        # Stream to temporary file, then rename on success
        tmp_path = dest_path.with_suffix(".tmp")
        try:
            with open(tmp_path, "wb") as f:
                for chunk in response.iter_bytes(chunk_size):
                    bytes_downloaded += len(chunk)
                    if bytes_downloaded > max_size_bytes:
                        raise FileTooLargeError(
                            f"Download exceeded max size {max_size_bytes}"
                        )
                    f.write(chunk)
            # Atomic rename on success
            tmp_path.rename(dest_path)
        except Exception:
            # Clean up partial file on any error
            tmp_path.unlink(missing_ok=True)
            raise

    return bytes_downloaded
```

### Pattern 2: Per-PDF Retry with Tenacity
**What:** Wrap the single-PDF download in a tenacity retry decorator, matching the project's existing pattern from api_client.py.
**When to use:** Each individual PDF download attempt.
**Example:**
```python
# Source: existing api_client.py pattern + tenacity docs
from tenacity import (
    retry,
    stop_after_attempt,
    wait_random_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

@retry(
    stop=stop_after_attempt(3),
    wait=wait_random_exponential(multiplier=1, min=2, max=30),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    retry=retry_if_exception_type(
        (httpx.HTTPStatusError, httpx.TimeoutException, httpx.ConnectError)
    ),
)
def _download_with_retry(
    client: httpx.Client,
    url: str,
    dest_path: Path,
    max_size_bytes: int,
) -> int:
    return _download_single_pdf(client, url, dest_path, max_size_bytes)
```

### Pattern 3: All-or-Nothing Filing Download
**What:** Download all PDFs for a filing. If any fails after retries, clean up ALL downloaded files for that filing and mark it failed. Only mark success when all PDFs complete.
**When to use:** The filing-level orchestration loop.
**Example:**
```python
def _download_filing_pdfs(
    client: httpx.Client,
    session: Session,
    filing: Filing,
    documents: list[Document],
    base_dir: Path,
    max_size_bytes: int,
    rate_limiter_min: float,
    rate_limiter_max: float,
) -> bool:
    """Download all PDFs for a filing. Returns True if ALL succeed."""
    # Build folder path: data/filings/YYYY-MM-DD_Filing-{ID}/documents/
    date_str = filing.date.isoformat() if filing.date else "unknown-date"
    filing_dir = base_dir / f"{date_str}_Filing-{filing.filing_id}" / "documents"
    filing_dir.mkdir(parents=True, exist_ok=True)

    downloaded_paths: list[Path] = []

    for idx, doc in enumerate(documents, start=1):
        dest_path = filing_dir / f"doc_{idx:03d}.pdf"

        try:
            bytes_written = _download_with_retry(
                client, doc.document_url, dest_path, max_size_bytes
            )
            # Update Document record
            doc.local_path = str(dest_path)
            doc.file_size_bytes = bytes_written
            doc.download_status = "success"
            downloaded_paths.append(dest_path)

        except Exception as exc:
            logger.error(
                "Failed to download doc %d/%d for filing %s: %s",
                idx, len(documents), filing.filing_id, exc,
            )
            # Clean up ALL downloaded files for this filing
            for path in downloaded_paths:
                path.unlink(missing_ok=True)
            return False

        # Rate limit between downloads (not after the last one)
        if idx < len(documents):
            wait_between_requests(rate_limiter_min, rate_limiter_max)

    return True
```

### Pattern 4: Filing-Level Orchestration
**What:** Loop through filings needing download, attempt each, update state store.
**When to use:** Top-level entry point called by the pipeline.
**Example:**
```python
def download_filings_pdfs(
    session: Session,
    settings: ScraperSettings,
    pipeline_settings: PipelineSettings,
) -> DownloadResult:
    """Download PDFs for all filings with status_downloaded == 'pending'."""
    # Query filings needing download
    filings = _get_filings_needing_download(session)

    client = httpx.Client(
        headers={"User-Agent": settings.user_agent},
        timeout=httpx.Timeout(60.0),  # Longer timeout for file downloads
        follow_redirects=True,
    )

    try:
        for filing in filings:
            documents = filing.documents
            success = _download_filing_pdfs(
                client, session, filing, documents, base_dir, max_size, ...
            )
            if success:
                mark_step_complete(session, filing.filing_id, "downloaded")
            else:
                mark_step_complete(
                    session, filing.filing_id, "downloaded",
                    status="failed", error="PDF download failed after retries"
                )
    finally:
        client.close()
```

### Anti-Patterns to Avoid
- **Loading entire PDF into memory:** Never do `response.read()` or `response.content` for PDFs. Always stream with `iter_bytes()`.
- **Leaving .tmp files on failure:** Always clean up in a `finally` or `except` block. The `.tmp` -> final rename pattern ensures no corrupt PDFs exist.
- **Retrying at the filing level instead of per-PDF:** Retry each individual PDF download 3 times. Only fail the entire filing after a specific PDF exhausts its retries.
- **Using async httpx:** The project uses sync patterns throughout (Playwright sync API, sync httpx Client). Keep it consistent.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Retry with backoff | Manual retry loop with sleep | tenacity `@retry` decorator | Already in project; handles edge cases (jitter, logging, exception filtering) |
| Rate limiting | Custom sleep logic | `wait_between_requests()` from rate_limiter.py | Already exists, tested, configurable |
| HTTP streaming | Manual socket/urllib handling | `httpx.Client.stream()` with `iter_bytes()` | Already in project; handles chunked transfer, compression, redirects |
| Path creation | Manual os.makedirs | `Path.mkdir(parents=True, exist_ok=True)` | Idempotent, cross-platform, already used in engine.py |

**Key insight:** This phase is pure glue code connecting existing infrastructure (httpx, tenacity, rate limiter, SQLAlchemy models). The Document model already has `local_path`, `file_size_bytes`, and `download_status` columns. The Filing model already has `status_downloaded`. The building blocks are in place.

## Common Pitfalls

### Pitfall 1: REGDOCS View URLs Are Not Direct Downloads
**What goes wrong:** The scraper captures `/Item/View/{ID}` URLs which are HTML viewer pages, not direct PDF binary streams. Trying to download them as PDFs produces HTML files.
**Why it happens:** REGDOCS is a JavaScript-driven application. Document links on the filing list point to viewer pages, not direct download endpoints.
**How to avoid:** Check the `Content-Type` response header before writing to disk. If it's `text/html`, the URL is a viewer page and the PDF cannot be directly downloaded from that URL. Log a warning and mark as non-downloadable (or try appending a download parameter if one exists). The httpx client should use `follow_redirects=True` to handle any server-side redirects from viewer to download URLs.
**Warning signs:** Downloaded files are a few KB and contain HTML tags; all "PDFs" for a filing are exactly the same size.

### Pitfall 2: Partial Files Left on Disk After Failure
**What goes wrong:** Download fails mid-stream, leaving a truncated file that looks like a valid PDF but is corrupt.
**Why it happens:** Writing directly to the final filename means a crash during download leaves a partial file.
**How to avoid:** Write to a `.tmp` file first, then rename atomically on success. On any failure, delete the `.tmp` file. The all-or-nothing filing rule means cleaning up ALL previously downloaded files for the filing on any single PDF failure.
**Warning signs:** Files with much smaller size than expected; PDFs that can't be opened.

### Pitfall 3: Filing Date Is None
**What goes wrong:** Building the folder path `{YYYY-MM-DD}_Filing-{ID}` fails because `filing.date` is None (date wasn't extracted during scraping).
**Why it happens:** Phase 2 stores date as Optional -- some filings may not have a parseable date.
**How to avoid:** Use a fallback like `"unknown-date"` or `"0000-00-00"` when `filing.date` is None. Document this in the code.
**Warning signs:** KeyError or AttributeError when building folder paths.

### Pitfall 4: Windows Path Length Limits
**What goes wrong:** Filing ID + date + nested directory structure can exceed Windows MAX_PATH (260 characters) depending on where the project root is located.
**Why it happens:** The folder structure `data/filings/YYYY-MM-DD_Filing-{ID}/documents/doc_001.pdf` adds significant nesting. If PROJECT_ROOT is deep (e.g., `C:\Users\amelv\Repo\cer_repository_scrapper\`), the total path can get long.
**How to avoid:** Use `PROJECT_ROOT` to resolve the base directory (consistent with existing config pattern). Keep filing IDs as-is (they're typically short alphanumeric like "A96487"). The sequential `doc_NNN.pdf` naming keeps filenames short. If a filing ID is unexpectedly long, truncate it with a hash suffix.
**Warning signs:** `FileNotFoundError` or `OSError` on Windows when creating directories.

### Pitfall 5: SQLAlchemy Session Scope in Long Loops
**What goes wrong:** A single session used across many filing downloads accumulates objects in the identity map, potentially causing memory issues or stale reads.
**Why it happens:** SQLAlchemy's unit-of-work pattern tracks all loaded objects. In a loop downloading PDFs for many filings, the session grows.
**How to avoid:** Commit and optionally `session.expire_all()` after each filing. The existing code pattern (commit after each mark_step_complete) already handles this. Keep the session open for the full run but commit frequently.
**Warning signs:** Memory growth during long runs; stale data when checking download status.

### Pitfall 6: Content-Length Header Absent or Wrong
**What goes wrong:** Relying on `Content-Length` to pre-check file size fails because the header is missing, or the server sends a different amount of data.
**Why it happens:** Some servers don't include `Content-Length`, especially for chunked transfer encoding. Government servers may behave unpredictably.
**How to avoid:** Use Content-Length as an optimization (early rejection) but track actual bytes downloaded as the authoritative size check. The streaming loop already counts bytes for the max-size guard.
**Warning signs:** Downloads exceeding max size despite Content-Length check; or no Content-Length header at all.

## Code Examples

### httpx Client Streaming Download (Verified Pattern)
```python
# Source: httpx official docs (https://www.python-httpx.org/quickstart/)
# Adapted for project context

import httpx
from pathlib import Path

client = httpx.Client(
    headers={"User-Agent": "CER-Filing-Monitor/1.0"},
    timeout=httpx.Timeout(60.0),
    follow_redirects=True,
)

with client.stream("GET", url) as response:
    response.raise_for_status()
    with open(dest_path, "wb") as f:
        for chunk in response.iter_bytes(chunk_size=65_536):
            f.write(chunk)

client.close()
```

### Tenacity Retry (Existing Project Pattern)
```python
# Source: existing api_client.py in this project

@retry(
    stop=stop_after_attempt(3),
    wait=wait_random_exponential(multiplier=1, min=2, max=30),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    retry=retry_if_exception_type(
        (httpx.HTTPStatusError, httpx.TimeoutException, httpx.ConnectError)
    ),
)
def _download_with_retry(client, url, dest, max_size):
    ...
```

### Building Filing Directory Path
```python
# Source: project CONTEXT.md decisions
from pathlib import Path
from cer_scraper.config.settings import PROJECT_ROOT

def _build_filing_dir(filing: Filing) -> Path:
    date_str = filing.date.isoformat() if filing.date else "unknown-date"
    filing_dir = (
        PROJECT_ROOT
        / "data"
        / "filings"
        / f"{date_str}_Filing-{filing.filing_id}"
        / "documents"
    )
    filing_dir.mkdir(parents=True, exist_ok=True)
    return filing_dir
```

### Querying Filings Needing Download
```python
# Source: existing state.py patterns in this project

from sqlalchemy import select
from cer_scraper.db.models import Filing

def get_filings_needing_download(session: Session) -> list[Filing]:
    """Return filings that have been scraped but not yet downloaded."""
    stmt = select(Filing).where(
        Filing.status_scraped == "success",
        Filing.status_downloaded.in_(["pending", "failed"]),
        Filing.retry_count < max_retries,
    )
    return list(session.scalars(stmt).all())
```

### Cleanup on All-or-Nothing Failure
```python
# Source: project decisions (all-or-nothing per filing)
import shutil

def _cleanup_filing_dir(filing_dir: Path) -> None:
    """Remove all downloaded files for a filing on failure."""
    if filing_dir.exists():
        for pdf_file in filing_dir.glob("*.pdf"):
            pdf_file.unlink(missing_ok=True)
        for tmp_file in filing_dir.glob("*.tmp"):
            tmp_file.unlink(missing_ok=True)
        # Remove empty documents/ dir but keep parent for potential retry
        if not any(filing_dir.iterdir()):
            filing_dir.rmdir()
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| requests + manual retry | httpx + tenacity | 2023-2024 | httpx has native streaming; tenacity provides declarative retry |
| os.path for paths | pathlib.Path | Python 3.6+ | Cross-platform, cleaner API, mkdir(parents=True) |
| os.makedirs | Path.mkdir(parents=True, exist_ok=True) | Python 3.5+ | Idempotent, no try/except needed |

**Deprecated/outdated:**
- urllib/urllib2 for downloads: Use httpx (already in project)
- requests library: httpx is the modern replacement (already in project)

## Claude's Discretion: Self-Healing File Check Recommendation

The CONTEXT.md leaves it to Claude's discretion whether to verify file existence on disk as a self-healing check.

**Recommendation: Do NOT add self-healing file checks on every run.**

Rationale:
1. The database flag is already the source of truth (locked decision)
2. Filesystem checks add I/O overhead and complexity
3. If files get deleted externally, that's an operational issue (not a pipeline concern)
4. The all-or-nothing rule means we either have all files or none -- partial states shouldn't occur
5. If needed later, a separate "integrity check" command could be added (Phase 10 territory)

If the planner disagrees, a lightweight alternative: check file existence ONLY when a filing is marked as "downloaded=success" but somehow needs re-processing -- essentially a safety net before text extraction in Phase 4, not during download.

## Open Questions

1. **REGDOCS `/Item/View/` URLs vs direct PDFs**
   - What we know: Phase 2 captures document URLs including `/Item/View/{ID}` paths. These are viewer page URLs, not direct PDF binaries.
   - What's unclear: Whether REGDOCS has a direct download URL pattern (e.g., `/File/Download/{ID}` or a query parameter like `?download=true`). The site is JavaScript-heavy and resists static analysis.
   - Recommendation: The downloader should attempt to download each URL with `follow_redirects=True` and check `Content-Type`. If it gets `application/pdf` or `application/octet-stream`, save it. If it gets `text/html`, log a warning and mark the document as "not_downloadable". This gracefully handles both direct links and viewer URLs. A future improvement could use Playwright to visit the viewer page and extract the actual download link, but that adds significant complexity and is not needed for Phase 3 MVP.

2. **Timeout for large PDF downloads**
   - What we know: httpx.Timeout defaults to 5s for connect, 5s for read, etc.
   - What's unclear: How large REGDOCS PDFs can be (some regulatory filings may be 100+ pages / 50+ MB).
   - Recommendation: Use a generous timeout: `httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=10.0)`. The streaming approach means read timeout applies per-chunk, not total download time. Validate this assumption.

## Configuration Additions Needed

The downloader needs new configuration values. Add to existing `PipelineSettings` or create a new settings class:

```python
# Recommended additions to PipelineSettings or a new DownloadSettings
filings_dir: str = "data/filings"          # Base directory for filing downloads
max_pdf_size_bytes: int = 104_857_600      # 100 MB default max
download_chunk_size: int = 65_536          # 64 KB chunks
download_timeout_seconds: float = 60.0     # Per-request timeout
```

## Sources

### Primary (HIGH confidence)
- httpx official docs (https://www.python-httpx.org/quickstart/, https://www.python-httpx.org/api/) -- streaming API verified
- Existing project code: api_client.py -- tenacity retry pattern, httpx.Client usage
- Existing project code: rate_limiter.py -- wait_between_requests() API
- Existing project code: models.py -- Document model with local_path, file_size_bytes, download_status
- Existing project code: state.py -- mark_step_complete() for "downloaded" step

### Secondary (MEDIUM confidence)
- rednafi.com blog post on file size limiting during streaming downloads -- pattern verified against httpx docs
- httpx GitHub discussions on large file downloads -- chunk_size considerations

### Tertiary (LOW confidence)
- REGDOCS URL patterns -- `/Item/View/{ID}` behavior inferred from DOM parser regex and web scraping; not verified against live REGDOCS server response headers

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all libraries already installed and proven in Phase 2
- Architecture: HIGH -- follows established project patterns (scraper/ subpackage, state store integration)
- Download mechanics: HIGH -- httpx streaming is well-documented; tenacity retry is battle-tested in this project
- Pitfalls: HIGH -- derived from code analysis of existing models and common Python download patterns
- REGDOCS URL behavior: LOW -- `/Item/View/` response type is unverified; requires runtime testing

**Research date:** 2026-02-07
**Valid until:** 2026-03-07 (stable domain; httpx/tenacity APIs are mature)
