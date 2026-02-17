"""Filing-level download orchestrator with all-or-nothing semantics.

Iterates over filings that need PDF downloads, downloads all their documents
sequentially using the download service, and updates database state.  If ANY
document in a filing fails, the entire filing directory is cleaned up and all
documents are reset (all-or-nothing).  One filing's failure does not block
others -- the orchestrator continues to the next filing.

Public API:
    download_filings(session, pipeline_settings, scraper_settings)
        -> DownloadBatchResult
"""

from __future__ import annotations

import logging
import shutil
import ssl
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from cer_scraper.config.settings import (
    PipelineSettings,
    PROJECT_ROOT,
    ScraperSettings,
)
from cer_scraper.db.models import Filing
from cer_scraper.db.state import get_filings_for_download, mark_step_complete
from cer_scraper.downloader.service import download_pdf
from cer_scraper.scraper.rate_limiter import wait_between_requests

logger = logging.getLogger(__name__)

__all__ = ["download_filings", "DownloadBatchResult"]


@dataclass
class DownloadBatchResult:
    """Aggregated outcome of downloading PDFs for multiple filings."""

    filings_attempted: int = 0
    filings_succeeded: int = 0
    filings_failed: int = 0
    filings_skipped: int = 0
    total_pdfs_downloaded: int = 0
    total_bytes: int = 0
    errors: list[str] = field(default_factory=list)


def _build_filing_dir(filing: Filing, base_dir: Path) -> Path:
    """Build the directory path for a filing's downloaded documents.

    Returns ``base_dir / "{YYYY-MM-DD}_Filing-{filing_id}" / "documents"``.
    If ``filing.date`` is ``None``, uses ``"unknown-date"`` as the date prefix.
    """
    if filing.date is not None:
        date_prefix = filing.date.strftime("%Y-%m-%d")
    else:
        date_prefix = "unknown-date"

    return base_dir / f"{date_prefix}_Filing-{filing.filing_id}" / "documents"


def _download_filing(
    filing: Filing,
    pipeline_settings: PipelineSettings,
    scraper_settings: ScraperSettings,
    http_client: httpx.Client,
) -> tuple[bool, str | None, int, int]:
    """Download all documents for a single filing.

    Returns:
        A tuple of (success, error_message, pdf_count, total_bytes).
        On failure, partial files are cleaned up and document records reset.
    """
    base_dir = (PROJECT_ROOT / pipeline_settings.filings_dir).resolve()
    filing_dir = _build_filing_dir(filing, base_dir)

    documents = filing.documents
    if not documents:
        logger.info(
            "Filing %s has no documents to download, skipping",
            filing.filing_id,
        )
        return (True, None, 0, 0)

    pdf_count = 0
    total_bytes = 0

    for idx, doc in enumerate(documents, start=1):
        filename = f"doc_{idx:03d}.pdf"
        dest_path = filing_dir / filename

        result = download_pdf(
            doc.document_url,
            dest_path,
            pipeline_settings,
            http_client,
        )

        if not result.success:
            error_msg = (
                f"Filing {filing.filing_id}: document {idx}/{len(documents)} "
                f"failed ({doc.document_url}): {result.error}"
            )
            logger.error(error_msg)

            # All-or-nothing: clean up entire filing directory
            parent_dir = filing_dir.parent
            if parent_dir.exists():
                shutil.rmtree(parent_dir, ignore_errors=True)
                logger.info(
                    "Cleaned up filing directory %s after failure",
                    parent_dir,
                )

            # Reset all document records for this filing
            for d in documents:
                d.download_status = "failed"
                d.local_path = None

            return (False, error_msg, 0, 0)

        # Update document record on success
        doc.local_path = str(dest_path)
        doc.file_size_bytes = result.bytes_downloaded
        doc.download_status = "success"
        pdf_count += 1
        total_bytes += result.bytes_downloaded

        # Rate limit between downloads (skip after the last one)
        if idx < len(documents):
            wait_between_requests(
                scraper_settings.delay_min_seconds,
                scraper_settings.delay_max_seconds,
            )

    return (True, None, pdf_count, total_bytes)


def download_filings(
    session,
    pipeline_settings: PipelineSettings,
    scraper_settings: ScraperSettings,
) -> DownloadBatchResult:
    """Download PDFs for all pending filings.

    Iterates over filings returned by ``get_filings_for_download()``,
    downloads each filing's documents sequentially, and updates database
    state.  Each filing is committed independently so one failure does not
    affect others.

    Parameters
    ----------
    session:
        Active SQLAlchemy session.
    pipeline_settings:
        Pipeline configuration (provides paths, size limits, timeout).
    scraper_settings:
        Scraper configuration (provides rate-limiter delay settings).

    Returns
    -------
    DownloadBatchResult
        Aggregated statistics and any error messages.
    """
    batch = DownloadBatchResult()

    try:
        filings = get_filings_for_download(
            session, pipeline_settings.max_retry_count
        )

        if not filings:
            logger.info("No filings pending download")
            return batch

        logger.info("Found %d filings pending download", len(filings))

        # REGDOCS requires SECLEVEL=1 cipher compatibility on Windows.
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.set_ciphers("DEFAULT@SECLEVEL=1")

        with httpx.Client(
            timeout=pipeline_settings.download_timeout_seconds,
            verify=ssl_ctx,
            follow_redirects=True,
        ) as http_client:
            for filing in filings:
                batch.filings_attempted += 1
                logger.info(
                    "Downloading filing %s (%d documents)",
                    filing.filing_id,
                    len(filing.documents),
                )

                try:
                    success, error_msg, pdf_count, total_bytes = (
                        _download_filing(
                            filing,
                            pipeline_settings,
                            scraper_settings,
                            http_client,
                        )
                    )

                    if success:
                        mark_step_complete(
                            session,
                            filing.filing_id,
                            "downloaded",
                            "success",
                        )
                        session.commit()
                        batch.filings_succeeded += 1
                        batch.total_pdfs_downloaded += pdf_count
                        batch.total_bytes += total_bytes
                        logger.info(
                            "Filing %s download complete: %d PDFs, %d bytes",
                            filing.filing_id,
                            pdf_count,
                            total_bytes,
                        )
                    else:
                        mark_step_complete(
                            session,
                            filing.filing_id,
                            "downloaded",
                            "failed",
                            error=error_msg,
                        )
                        session.commit()
                        batch.filings_failed += 1
                        batch.errors.append(error_msg or "Unknown error")
                        logger.error(
                            "Filing %s download failed: %s",
                            filing.filing_id,
                            error_msg,
                        )

                except Exception:
                    logger.exception(
                        "Unexpected error processing filing %s",
                        filing.filing_id,
                    )
                    try:
                        session.rollback()
                        mark_step_complete(
                            session,
                            filing.filing_id,
                            "downloaded",
                            "failed",
                            error="Unexpected error during download",
                        )
                    except Exception:
                        logger.exception(
                            "Failed to update status for filing %s",
                            filing.filing_id,
                        )
                    batch.filings_failed += 1
                    batch.errors.append(
                        f"Filing {filing.filing_id}: unexpected error"
                    )

    except Exception:
        logger.exception("Fatal error in download orchestrator")
        batch.errors.append("Fatal error in download orchestrator")

    logger.info(
        "Download batch complete: %d attempted, %d succeeded, %d failed, "
        "%d PDFs, %d bytes",
        batch.filings_attempted,
        batch.filings_succeeded,
        batch.filings_failed,
        batch.total_pdfs_downloaded,
        batch.total_bytes,
    )
    return batch
