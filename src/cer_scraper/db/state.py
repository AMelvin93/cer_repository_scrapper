"""State store operations for querying and updating filing pipeline state.

Provides functions for the pipeline to track progress through each stage:
    get_unprocessed_filings -- Filings that need processing (not emailed, under retry limit).
    get_filings_for_download -- Filings that need PDF downloads (scraped, not downloaded).
    get_filings_for_extraction -- Filings that need text extraction (downloaded, not extracted).
    get_filing_by_id -- Look up a filing by its REGDOCS filing_id.
    mark_step_complete -- Update a specific pipeline step's status.
    create_filing -- Insert a new filing record from scraper output.
    filing_exists -- Check if a filing_id is already in the database.

Every mutation calls session.commit() explicitly -- SQLAlchemy does NOT auto-commit
when the session closes, so changes would be silently lost without it.
"""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .models import Filing

logger = logging.getLogger(__name__)

VALID_STEPS = ("scraped", "downloaded", "extracted", "analyzed", "emailed")


def get_unprocessed_filings(
    session: Session, max_retries: int = 3
) -> list[Filing]:
    """Return filings that have not completed the full pipeline.

    A filing is considered unprocessed if:
        - status_emailed is not "success" (pipeline not complete), AND
        - retry_count is less than max_retries (not exhausted)

    Args:
        session: Active SQLAlchemy session.
        max_retries: Maximum retry count before excluding a filing.

    Returns:
        List of Filing objects needing processing.
    """
    stmt = select(Filing).where(
        Filing.status_emailed != "success",
        Filing.retry_count < max_retries,
    )
    return list(session.scalars(stmt).all())


def get_filings_for_download(
    session: Session, max_retries: int = 3
) -> list[Filing]:
    """Return filings that need PDF downloads.

    A filing needs download if:
        - status_scraped == "success" (scraping completed), AND
        - status_downloaded != "success" (not yet downloaded), AND
        - retry_count < max_retries (not exhausted)

    Eagerly loads the documents relationship so callers can iterate
    documents without additional queries.

    Args:
        session: Active SQLAlchemy session.
        max_retries: Maximum retry count before excluding a filing.

    Returns:
        List of Filing objects with eagerly loaded documents.
    """
    stmt = (
        select(Filing)
        .where(
            Filing.status_scraped == "success",
            Filing.status_downloaded != "success",
            Filing.retry_count < max_retries,
        )
        .options(selectinload(Filing.documents))
    )
    return list(session.scalars(stmt).all())


def get_filings_for_extraction(
    session: Session, max_retries: int = 3
) -> list[Filing]:
    """Return filings that need PDF text extraction.

    A filing needs extraction if:
        - status_downloaded == "success" (PDFs are on disk), AND
        - status_extracted != "success" (not yet extracted), AND
        - retry_count < max_retries (not exhausted)

    Eagerly loads the documents relationship so callers can iterate
    documents without additional queries.

    Args:
        session: Active SQLAlchemy session.
        max_retries: Maximum retry count before excluding a filing.

    Returns:
        List of Filing objects with eagerly loaded documents.
    """
    stmt = (
        select(Filing)
        .where(
            Filing.status_downloaded == "success",
            Filing.status_extracted != "success",
            Filing.retry_count < max_retries,
        )
        .options(selectinload(Filing.documents))
    )
    return list(session.scalars(stmt).all())


def get_filing_by_id(session: Session, filing_id: str) -> Filing | None:
    """Look up a filing by its REGDOCS filing_id.

    Args:
        session: Active SQLAlchemy session.
        filing_id: The REGDOCS filing identifier (not the database PK).

    Returns:
        The Filing object, or None if not found.
    """
    stmt = select(Filing).where(Filing.filing_id == filing_id)
    return session.scalars(stmt).first()


def mark_step_complete(
    session: Session,
    filing_id: str,
    step: str,
    status: str = "success",
    error: str | None = None,
) -> None:
    """Update the status of a specific pipeline step for a filing.

    Args:
        session: Active SQLAlchemy session.
        filing_id: The REGDOCS filing identifier.
        step: Pipeline step name (scraped, downloaded, extracted, analyzed, emailed).
        status: Status value to set (e.g., "success", "failed").
        error: Optional error message; if provided, also increments retry_count.

    Raises:
        ValueError: If step is not in VALID_STEPS.
    """
    if step not in VALID_STEPS:
        raise ValueError(
            f"Invalid step {step!r}. Must be one of: {VALID_STEPS}"
        )

    filing = get_filing_by_id(session, filing_id)
    if filing is None:
        raise ValueError(f"Filing {filing_id!r} not found")

    setattr(filing, f"status_{step}", status)

    if error is not None:
        filing.error_message = error
        filing.retry_count += 1

    session.commit()
    logger.debug(
        "Updated filing %s: status_%s = %s", filing_id, step, status
    )


def create_filing(session: Session, filing_id: str, **kwargs) -> Filing:
    """Create a new Filing record.

    Sets status_scraped to "success" since the filing was just discovered
    by the scraper. All other status fields default to "pending".

    Args:
        session: Active SQLAlchemy session.
        filing_id: The REGDOCS filing identifier.
        **kwargs: Additional Filing fields (applicant, filing_type, etc.).

    Returns:
        The newly created Filing object.
    """
    filing = Filing(filing_id=filing_id, status_scraped="success", **kwargs)
    session.add(filing)
    session.commit()
    logger.info("Created filing %s", filing_id)
    return filing


def filing_exists(session: Session, filing_id: str) -> bool:
    """Check whether a filing with the given filing_id exists.

    Uses a lightweight query selecting only the primary key.

    Args:
        session: Active SQLAlchemy session.
        filing_id: The REGDOCS filing identifier.

    Returns:
        True if the filing exists, False otherwise.
    """
    stmt = select(Filing.id).where(Filing.filing_id == filing_id)
    return session.scalars(stmt).first() is not None
