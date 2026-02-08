"""Single-PDF download service with streaming, Content-Type validation,
retry logic, and cleanup on failure.

Downloads a single PDF URL to a local file using streaming chunked writes
through a .tmp intermediate file. On success the .tmp file is renamed to
the final .pdf path; on any failure the .tmp file is deleted to prevent
corrupt partial files from accumulating on disk.

Retry is handled by tenacity: 3 attempts with exponential backoff, retrying
only on transient HTTP and transport errors.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import httpx
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from cer_scraper.config.settings import PipelineSettings

logger = logging.getLogger(__name__)


@dataclass
class DownloadResult:
    """Outcome of a single PDF download attempt."""

    success: bool
    bytes_downloaded: int = 0
    error: str | None = None


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TransportError)),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def _download_with_retry(
    url: str,
    dest_path: Path,
    settings: PipelineSettings,
    http_client: httpx.Client,
) -> DownloadResult:
    """Core download logic wrapped with tenacity retry.

    Streams the response body to a .tmp file, validates Content-Type and
    file size, then renames to the final path on success.

    Raises httpx.HTTPStatusError or httpx.TransportError on transient
    failures so tenacity can retry.
    """
    tmp_path = dest_path.with_suffix(".pdf.tmp")

    try:
        with http_client.stream(
            "GET",
            url,
            timeout=settings.download_timeout_seconds,
            follow_redirects=True,
        ) as response:
            response.raise_for_status()

            # --- Content-Type check ---
            content_type = response.headers.get("content-type", "")
            if "text/html" in content_type.lower():
                return DownloadResult(
                    success=False,
                    bytes_downloaded=0,
                    error="Response is HTML, not a PDF binary",
                )

            # --- Content-Length pre-check ---
            content_length = response.headers.get("content-length")
            if content_length is not None:
                try:
                    declared_size = int(content_length)
                except ValueError:
                    declared_size = 0
                if declared_size > settings.max_pdf_size_bytes:
                    return DownloadResult(
                        success=False,
                        bytes_downloaded=0,
                        error=(
                            f"PDF exceeds max size limit "
                            f"({declared_size} bytes > "
                            f"{settings.max_pdf_size_bytes} bytes)"
                        ),
                    )

            # --- Streaming write ---
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            bytes_written = 0

            with open(tmp_path, "wb") as f:
                for chunk in response.iter_bytes(
                    chunk_size=settings.download_chunk_size,
                ):
                    bytes_written += len(chunk)

                    # Runtime size guard
                    if bytes_written > settings.max_pdf_size_bytes:
                        logger.warning(
                            "Download of %s exceeded max size during streaming "
                            "(%d bytes > %d bytes), aborting",
                            url,
                            bytes_written,
                            settings.max_pdf_size_bytes,
                        )
                        # Clean up tmp inside this block, then return failure
                        f.close()
                        if tmp_path.exists():
                            tmp_path.unlink()
                        return DownloadResult(
                            success=False,
                            bytes_downloaded=bytes_written,
                            error=(
                                f"PDF exceeds max size limit during streaming "
                                f"({bytes_written} bytes > "
                                f"{settings.max_pdf_size_bytes} bytes)"
                            ),
                        )

                    f.write(chunk)
                    logger.debug(
                        "Downloaded %d bytes so far for %s",
                        bytes_written,
                        dest_path.name,
                    )

        # --- Success: rename .tmp -> .pdf ---
        tmp_path.rename(dest_path)
        logger.info(
            "Downloaded %s (%d bytes) to %s",
            url,
            bytes_written,
            dest_path,
        )
        return DownloadResult(success=True, bytes_downloaded=bytes_written)

    except (httpx.HTTPStatusError, httpx.TransportError):
        # Let tenacity retry these
        raise

    except Exception:
        # Unexpected errors: log and return failure (don't retry)
        logger.exception("Unexpected error downloading %s", url)
        return DownloadResult(
            success=False,
            bytes_downloaded=0,
            error=f"Unexpected error downloading {url}",
        )

    finally:
        # Always clean up .tmp on failure (successful path already renamed it)
        if tmp_path.exists():
            try:
                tmp_path.unlink()
                logger.debug("Cleaned up temp file %s", tmp_path)
            except OSError:
                logger.warning("Failed to clean up temp file %s", tmp_path)


def download_pdf(
    url: str,
    dest_path: Path,
    settings: PipelineSettings,
    http_client: httpx.Client,
) -> DownloadResult:
    """Download a single PDF from *url* to *dest_path*.

    Parameters
    ----------
    url:
        Direct PDF URL or REGDOCS ``/Item/View/{ID}`` viewer URL.
    dest_path:
        Local filesystem path where the final ``.pdf`` should be saved.
    settings:
        Pipeline configuration (provides size limits, chunk size, timeout).
    http_client:
        An ``httpx.Client`` whose lifecycle is managed by the caller.

    Returns
    -------
    DownloadResult
        Carries ``success``, ``bytes_downloaded``, and optional ``error``.
    """
    logger.info("Starting download: %s -> %s", url, dest_path)

    try:
        return _download_with_retry(url, dest_path, settings, http_client)
    except (httpx.HTTPStatusError, httpx.TransportError) as exc:
        # All retries exhausted
        logger.error(
            "Download failed after retries for %s: %s",
            url,
            exc,
        )
        return DownloadResult(
            success=False,
            bytes_downloaded=0,
            error=f"Download failed after retries: {exc}",
        )
