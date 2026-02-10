"""Filing-level extraction orchestrator with per-document error tolerance.

Iterates over filings that need PDF text extraction, extracts each document
using the tiered extraction service, writes markdown files with YAML frontmatter,
and updates database state.  Unlike the downloader (all-or-nothing), extraction
tolerates individual document failures -- a filing is marked "success" if at
least one document is successfully extracted.  One filing's failure does not
block others -- the orchestrator continues to the next filing.

Public API:
    extract_filings(session, extraction_settings)
        -> ExtractionBatchResult
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from cer_scraper.config.settings import ExtractionSettings
from cer_scraper.db.models import Filing
from cer_scraper.db.state import get_filings_for_extraction, mark_step_complete
from cer_scraper.extractor.markdown import should_extract, write_markdown_file
from cer_scraper.extractor.service import extract_document

logger = logging.getLogger(__name__)

__all__ = ["extract_filings", "ExtractionBatchResult"]


@dataclass
class ExtractionBatchResult:
    """Aggregated outcome of extracting text for multiple filings."""

    filings_attempted: int = 0
    filings_succeeded: int = 0
    filings_failed: int = 0
    filings_skipped: int = 0
    total_docs_extracted: int = 0
    total_docs_failed: int = 0
    errors: list[str] = field(default_factory=list)


def _extract_filing_documents(
    session,
    filing: Filing,
    settings: ExtractionSettings,
) -> tuple[bool, str | None, int, int]:
    """Extract text from all downloaded documents in a single filing.

    Iterates over the filing's documents, skipping those not downloaded or
    already extracted.  For each eligible document, runs the tiered extraction
    service, writes a markdown file alongside the PDF, and updates the
    Document record in the database.

    Unlike the downloader, individual document failures do NOT fail the
    entire filing.  A filing is considered successful if at least one
    document was extracted.

    Args:
        session: Active SQLAlchemy session (for Document attribute updates).
        filing: Filing object with eagerly loaded documents.
        settings: Extraction configuration (thresholds, OCR settings).

    Returns:
        Tuple of (has_any_success, error_summary, success_count, fail_count).
    """
    success_count = 0
    fail_count = 0
    error_messages: list[str] = []

    documents = filing.documents
    if not documents:
        logger.info(
            "Filing %s has no documents to extract, skipping", filing.filing_id
        )
        return (True, None, 0, 0)

    for idx, doc in enumerate(documents, start=1):
        # Skip documents that were not successfully downloaded
        if doc.download_status != "success":
            logger.debug(
                "Skipping document %d/%d for filing %s: not downloaded (status=%s)",
                idx,
                len(documents),
                filing.filing_id,
                doc.download_status,
            )
            continue

        # Build paths
        pdf_path = Path(doc.local_path)
        md_path = pdf_path.with_suffix(".md")

        # Idempotency: skip if markdown already exists with content
        if not should_extract(md_path):
            logger.info(
                "Skipping document %d/%d for filing %s: already extracted (%s)",
                idx,
                len(documents),
                filing.filing_id,
                md_path.name,
            )
            success_count += 1
            continue

        # Run tiered extraction
        result = extract_document(pdf_path, settings)

        if result.success:
            # Write markdown file alongside the PDF
            write_markdown_file(
                md_path,
                result.markdown,
                result.method.value,
                result.page_count,
                result.char_count,
                pdf_path.name,
            )

            # Update Document record in database
            doc.extraction_status = "success"
            doc.extraction_method = result.method.value
            doc.extracted_text = result.markdown
            doc.char_count = result.char_count
            doc.page_count = result.page_count

            success_count += 1
            logger.info(
                "Extracted document %d/%d for filing %s: %s (%d chars, %d pages)",
                idx,
                len(documents),
                filing.filing_id,
                result.method.value,
                result.char_count,
                result.page_count,
            )
        else:
            # Mark individual document as failed but continue
            doc.extraction_status = "failed"
            doc.extraction_error = result.error

            fail_count += 1
            error_msg = (
                f"Document {idx}/{len(documents)} failed: {result.error}"
            )
            error_messages.append(error_msg)
            logger.warning(
                "Failed to extract document %d/%d for filing %s: %s",
                idx,
                len(documents),
                filing.filing_id,
                result.error,
            )

    has_any_success = success_count > 0
    error_summary = "; ".join(error_messages) if error_messages else None

    return (has_any_success, error_summary, success_count, fail_count)


def extract_filings(
    session,
    extraction_settings: ExtractionSettings,
) -> ExtractionBatchResult:
    """Extract text from PDFs for all filings pending extraction.

    Queries filings that have been downloaded but not yet extracted, then
    processes each one independently.  Per-filing error isolation ensures
    one filing failure does not block others.

    Args:
        session: Active SQLAlchemy session.
        extraction_settings: Extraction configuration.

    Returns:
        ExtractionBatchResult with aggregated statistics.
    """
    batch = ExtractionBatchResult()
    max_retries = 3

    try:
        filings = get_filings_for_extraction(session, max_retries)

        if not filings:
            logger.info("No filings pending extraction")
            return batch

        logger.info("Found %d filings pending extraction", len(filings))

        for filing in filings:
            batch.filings_attempted += 1

            try:
                logger.info(
                    "Extracting filing %s (%d documents)",
                    filing.filing_id,
                    len(filing.documents),
                )

                has_success, error_msg, doc_ok, doc_fail = (
                    _extract_filing_documents(session, filing, extraction_settings)
                )

                if has_success:
                    mark_step_complete(
                        session, filing.filing_id, "extracted", "success"
                    )
                    session.commit()
                    batch.filings_succeeded += 1
                    batch.total_docs_extracted += doc_ok
                    batch.total_docs_failed += doc_fail
                    logger.info(
                        "Filing %s extraction complete: %d docs OK, %d failed",
                        filing.filing_id,
                        doc_ok,
                        doc_fail,
                    )
                else:
                    error = error_msg or "No documents successfully extracted"
                    mark_step_complete(
                        session,
                        filing.filing_id,
                        "extracted",
                        "failed",
                        error=error,
                    )
                    session.commit()
                    batch.filings_failed += 1
                    batch.total_docs_failed += doc_fail
                    batch.errors.append(
                        f"Filing {filing.filing_id}: {error}"
                    )
                    logger.warning(
                        "Filing %s extraction failed: %s",
                        filing.filing_id,
                        error,
                    )

            except Exception:
                logger.exception(
                    "Unexpected error processing filing %s", filing.filing_id
                )
                try:
                    session.rollback()
                    mark_step_complete(
                        session,
                        filing.filing_id,
                        "extracted",
                        "failed",
                        error="Unexpected error",
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
        logger.exception("Fatal error in extraction orchestrator")
        batch.errors.append("Fatal error in extraction orchestrator")

    logger.info(
        "Extraction batch complete: %d attempted, %d succeeded, %d failed, "
        "%d docs extracted, %d docs failed",
        batch.filings_attempted,
        batch.filings_succeeded,
        batch.filings_failed,
        batch.total_docs_extracted,
        batch.total_docs_failed,
    )

    return batch
