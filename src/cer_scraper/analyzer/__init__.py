"""Filing-level analysis orchestrator with per-filing error isolation.

Iterates over filings that need LLM analysis, assembles document text with
delimiter headers, invokes the Claude CLI analysis service, and persists
results to both disk (analysis.json) and database (Filing.analysis_json).
Unlike the extractor (per-document tolerance), analysis operates at the
filing level -- one filing's failure does not block others.  Filings with
no extracted documents are skipped (vacuous success), not failed.

Public API:
    analyze_filings(session, analysis_settings)
        -> AnalysisBatchResult
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from cer_scraper.analyzer.service import analyze_filing_text
from cer_scraper.analyzer.types import AnalysisResult
from cer_scraper.config.settings import AnalysisSettings
from cer_scraper.db.models import Filing
from cer_scraper.db.state import get_filings_for_analysis, mark_step_complete

logger = logging.getLogger(__name__)

__all__ = ["analyze_filings", "AnalysisBatchResult"]


@dataclass
class AnalysisBatchResult:
    """Aggregated outcome of analysing multiple filings."""

    filings_attempted: int = 0
    filings_succeeded: int = 0
    filings_failed: int = 0
    filings_skipped: int = 0
    total_cost_usd: float = 0.0
    errors: list[str] = field(default_factory=list)


def assemble_filing_text(
    documents: list,
) -> tuple[str, int, int]:
    """Concatenate extracted document texts with delimiter headers.

    Iterates over a filing's Document ORM objects.  For each document with
    ``extraction_status == "success"`` and non-empty ``extracted_text``,
    builds a delimited section::

        --- Document 1: report.pdf (42 pages) ---

        <extracted text>

    Documents without successful extraction are counted as missing.

    Args:
        documents: List of Document ORM objects (eagerly loaded).

    Returns:
        Tuple of (combined_text, included_count, missing_count).
    """
    parts: list[str] = []
    included = 0
    missing = 0

    for idx, doc in enumerate(documents, start=1):
        if doc.extraction_status == "success" and doc.extracted_text:
            filename = doc.filename or "unknown.pdf"
            pages = doc.page_count or "?"
            header = f"--- Document {idx}: {filename} ({pages} pages) ---"
            parts.append(f"{header}\n\n{doc.extracted_text}")
            included += 1
        else:
            missing += 1

    combined = "\n\n".join(parts)
    return (combined, included, missing)


def _save_analysis_json(filing_dir: Path, analysis_json: dict) -> None:
    """Write analysis JSON to the filing's directory on disk.

    Saves ``analysis.json`` alongside the downloaded documents.  This
    satisfies the locked decision: storage in both JSON file and database.

    Args:
        filing_dir: Path to the filing's document directory.
        analysis_json: Validated analysis output dict.
    """
    output_path = filing_dir / "analysis.json"
    output_path.write_text(
        json.dumps(analysis_json, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Saved analysis JSON to %s", output_path)


def _get_filing_dir(filing: Filing) -> Path | None:
    """Determine the filing's document directory from its downloaded files.

    Looks for the first document with a ``local_path`` and returns its
    parent directory.  Returns None if no document has a local path.

    Args:
        filing: Filing ORM object with eagerly loaded documents.

    Returns:
        Path to the filing directory, or None.
    """
    for doc in filing.documents:
        if doc.local_path:
            return Path(doc.local_path).parent
    return None


def _analyze_single_filing(
    session,
    filing: Filing,
    settings: AnalysisSettings,
) -> tuple[bool, str | None, bool]:
    """Analyze a single filing and persist the result.

    Assembles document text, calls the analysis service, saves results
    to disk and database.

    Args:
        session: Active SQLAlchemy session.
        filing: Filing ORM object with eagerly loaded documents.
        settings: Analysis configuration.

    Returns:
        Tuple of (success, error_message, was_skipped).
    """
    combined_text, included_count, missing_count = assemble_filing_text(
        filing.documents
    )

    # No extracted documents -- vacuous success, skip
    if included_count == 0:
        logger.info(
            "Filing %s has no extracted documents, skipping analysis",
            filing.filing_id,
        )
        return (True, None, True)

    # Invoke Claude CLI analysis
    result: AnalysisResult = analyze_filing_text(
        filing_id=filing.filing_id,
        filing_date=str(filing.date or ""),
        applicant=filing.applicant or "",
        filing_type=filing.filing_type or "",
        document_text=combined_text,
        num_documents=included_count,
        num_missing=missing_count,
        settings=settings,
    )

    if result.success:
        # Persist to disk (best-effort -- disk failure should not fail analysis)
        filing_dir = _get_filing_dir(filing)
        if filing_dir and result.analysis_json:
            try:
                _save_analysis_json(filing_dir, result.analysis_json)
            except OSError:
                logger.warning(
                    "Filing %s: failed to save analysis.json to disk",
                    filing.filing_id,
                    exc_info=True,
                )

        # Persist to database
        filing.analysis_json = json.dumps(
            result.analysis_json, ensure_ascii=False
        )
        return (True, None, False)

    # Insufficient text -- skip, not failure
    if result.error == "insufficient_text":
        logger.info(
            "Filing %s: insufficient text for analysis, skipping",
            filing.filing_id,
        )
        return (True, None, True)

    # Actual failure
    logger.warning(
        "Filing %s analysis failed: %s", filing.filing_id, result.error
    )
    return (False, result.error, False)


def analyze_filings(
    session,
    analysis_settings: AnalysisSettings,
) -> AnalysisBatchResult:
    """Analyze all filings pending LLM analysis.

    Queries filings that have been extracted but not yet analyzed, then
    processes each one independently.  Per-filing error isolation ensures
    one filing failure does not block others.

    Args:
        session: Active SQLAlchemy session.
        analysis_settings: LLM analysis configuration.

    Returns:
        AnalysisBatchResult with aggregated statistics.
    """
    batch = AnalysisBatchResult()
    max_retries = 3

    try:
        filings = get_filings_for_analysis(session, max_retries)

        if not filings:
            logger.info("No filings pending analysis")
            return batch

        logger.info("Found %d filings pending analysis", len(filings))

        for filing in filings:
            batch.filings_attempted += 1

            try:
                logger.info(
                    "Analyzing filing %s (%d documents)",
                    filing.filing_id,
                    len(filing.documents),
                )

                success, error_msg, was_skipped = _analyze_single_filing(
                    session, filing, analysis_settings
                )

                if success and was_skipped:
                    # Vacuous success -- no documents or insufficient text
                    mark_step_complete(
                        session, filing.filing_id, "analyzed", "success"
                    )
                    session.commit()
                    batch.filings_skipped += 1
                    logger.info(
                        "Filing %s analysis skipped (vacuous success)",
                        filing.filing_id,
                    )

                elif success:
                    mark_step_complete(
                        session, filing.filing_id, "analyzed", "success"
                    )
                    session.commit()
                    batch.filings_succeeded += 1
                    logger.info(
                        "Filing %s analysis complete",
                        filing.filing_id,
                    )

                else:
                    error = error_msg or "Analysis failed"
                    mark_step_complete(
                        session,
                        filing.filing_id,
                        "analyzed",
                        "failed",
                        error=error,
                    )
                    session.commit()
                    batch.filings_failed += 1
                    batch.errors.append(
                        f"Filing {filing.filing_id}: {error}"
                    )
                    logger.warning(
                        "Filing %s analysis failed: %s",
                        filing.filing_id,
                        error,
                    )

            except Exception:
                logger.exception(
                    "Unexpected error analyzing filing %s", filing.filing_id
                )
                try:
                    session.rollback()
                    mark_step_complete(
                        session,
                        filing.filing_id,
                        "analyzed",
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
        logger.exception("Fatal error in analysis orchestrator")
        batch.errors.append("Fatal error in analysis orchestrator")

    logger.info(
        "Analysis batch complete: %d attempted, %d succeeded, %d failed, "
        "%d skipped, $%.4f total cost",
        batch.filings_attempted,
        batch.filings_succeeded,
        batch.filings_failed,
        batch.filings_skipped,
        batch.total_cost_usd,
    )

    return batch
