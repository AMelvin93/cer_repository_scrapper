"""Scraper package -- REGDOCS discovery, parsing, and document extraction.

Public API
----------
.. autofunction:: scrape_recent_filings

The orchestrator follows this 10-step flow:

1. robots.txt compliance check
2. API endpoint discovery (primary strategy)
3. DOM parsing fallback (if API discovery fails)
4. Validate scraped data
5. Apply config filters (filing type, applicant, proceeding)
6. Skip filings with no document URLs
7. Deduplicate against state store
8. Persist new filings to database
9. Check for consecutive zero-filing runs
10. Return ScrapeResult with detailed counts

Both API and DOM strategies produce :class:`ScrapedFiling` models, so
downstream code never knows which path produced the data.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from cer_scraper.config.settings import ScraperSettings
from cer_scraper.db.models import Document, RunHistory
from cer_scraper.db.state import create_filing, filing_exists
from cer_scraper.scraper.api_client import fetch_filings_from_api
from cer_scraper.scraper.discovery import DiscoveryResult, discover_api_endpoints
from cer_scraper.scraper.dom_parser import parse_filings_from_html
from cer_scraper.scraper.models import ScrapedDocument, ScrapedFiling
from cer_scraper.scraper.robots import check_robots_allowed

logger = logging.getLogger(__name__)

# Number of consecutive zero-filing runs before issuing a warning.
_ZERO_FILING_THRESHOLD = 3


@dataclass
class ScrapeResult:
    """Aggregated outcome of a single scrape run."""

    total_found: int = 0
    new_filings: int = 0
    skipped_existing: int = 0
    skipped_no_documents: int = 0
    skipped_filtered: int = 0
    strategy_used: str = "none"
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Filtering helpers
# ---------------------------------------------------------------------------

def _apply_filters(
    filings: list[ScrapedFiling],
    settings: ScraperSettings,
) -> tuple[list[ScrapedFiling], int]:
    """Apply config-based filters and return (kept, skipped_count).

    Filtering rules:
    - filing_type_include: if non-empty, keep only matching types (case-insensitive)
    - filing_type_exclude: if non-empty, remove matching types (case-insensitive)
    - applicant_filter: if non-empty, keep only filings whose applicant
      contains at least one filter string (case-insensitive substring match)
    - proceeding_filter: if non-empty, keep only filings whose proceeding_number matches

    Filings with None/empty filing_type pass through type filters (they are
    not excluded -- LLM may classify them later).
    """
    before_count = len(filings)
    filtered = list(filings)

    # Filing type include filter.
    if settings.filing_type_include:
        include_lower = {t.lower() for t in settings.filing_type_include}
        filtered = [
            f for f in filtered
            if f.filing_type is None
            or f.filing_type.strip() == ""
            or f.filing_type.lower() in include_lower
        ]
        removed = before_count - len(filtered)
        if removed:
            logger.info(
                "Filing type include filter removed %d filing(s) (keeping types: %s)",
                removed,
                settings.filing_type_include,
            )

    # Filing type exclude filter.
    if settings.filing_type_exclude:
        count_before = len(filtered)
        exclude_lower = {t.lower() for t in settings.filing_type_exclude}
        filtered = [
            f for f in filtered
            if f.filing_type is None
            or f.filing_type.strip() == ""
            or f.filing_type.lower() not in exclude_lower
        ]
        removed = count_before - len(filtered)
        if removed:
            logger.info(
                "Filing type exclude filter removed %d filing(s) (excluding types: %s)",
                removed,
                settings.filing_type_exclude,
            )

    # Applicant filter (case-insensitive substring match).
    if settings.applicant_filter:
        count_before = len(filtered)
        applicant_lower = [a.lower() for a in settings.applicant_filter]
        filtered = [
            f for f in filtered
            if f.applicant is None
            or f.applicant.strip() == ""
            or any(af in f.applicant.lower() for af in applicant_lower)
        ]
        removed = count_before - len(filtered)
        if removed:
            logger.info(
                "Applicant filter removed %d filing(s) (keeping applicants containing: %s)",
                removed,
                settings.applicant_filter,
            )

    # Proceeding number filter (exact match, case-insensitive).
    if settings.proceeding_filter:
        count_before = len(filtered)
        proceeding_lower = {p.lower() for p in settings.proceeding_filter}
        filtered = [
            f for f in filtered
            if f.proceeding_number is None
            or f.proceeding_number.strip() == ""
            or f.proceeding_number.lower() in proceeding_lower
        ]
        removed = count_before - len(filtered)
        if removed:
            logger.info(
                "Proceeding filter removed %d filing(s) (keeping proceedings: %s)",
                removed,
                settings.proceeding_filter,
            )

    total_skipped = before_count - len(filtered)
    return filtered, total_skipped


def _skip_no_documents(
    filings: list[ScrapedFiling],
) -> tuple[list[ScrapedFiling], int]:
    """Remove filings with no document URLs. Returns (kept, skipped_count)."""
    kept = [f for f in filings if f.has_documents]
    skipped = len(filings) - len(kept)
    if skipped:
        logger.info(
            "Skipped %d filing(s) with no document URLs", skipped
        )
    return kept, skipped


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_filings(filings: list[ScrapedFiling]) -> list[str]:
    """Run validation checks on scraped filings. Returns list of warning messages."""
    warnings: list[str] = []

    for f in filings:
        # filing_id is non-empty (Pydantic enforces this, but double-check).
        if not f.filing_id or not f.filing_id.strip():
            warnings.append(f"Filing has empty filing_id: {f!r}")

        # Check for reasonable date range if present.
        if f.date is not None:
            import datetime

            if f.date.year < 2000 or f.date > datetime.date.today() + datetime.timedelta(days=30):
                warnings.append(
                    f"Filing {f.filing_id} has suspicious date: {f.date}"
                )

    if warnings:
        for w in warnings:
            logger.warning("Validation: %s", w)
    else:
        logger.debug("Validation passed for %d filing(s)", len(filings))

    return warnings


# ---------------------------------------------------------------------------
# Zero-filing consecutive run tracking
# ---------------------------------------------------------------------------

def _check_consecutive_zero_runs(
    session: Session,
    threshold: int = _ZERO_FILING_THRESHOLD,
) -> bool:
    """Check if the last N runs all found zero new filings.

    Returns True if all recent runs had zero new filings (warning condition).
    """
    stmt = (
        select(RunHistory)
        .order_by(desc(RunHistory.started_at))
        .limit(threshold)
    )
    recent_runs = list(session.scalars(stmt).all())

    if len(recent_runs) < threshold:
        return False

    return all(run.new_filings == 0 for run in recent_runs)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _persist_filing(
    session: Session,
    filing: ScrapedFiling,
) -> bool:
    """Persist a single ScrapedFiling to the database.

    Creates a Filing record and associated Document records.
    Returns True on success, False on failure.
    """
    try:
        db_filing = create_filing(
            session,
            filing_id=filing.filing_id,
            date=filing.date,
            applicant=filing.applicant or "Unknown",
            filing_type=filing.filing_type or "Unknown",
            proceeding_number=filing.proceeding_number,
            title=filing.title,
            url=filing.url,
        )

        # Create Document records for each document URL.
        for doc in filing.documents:
            document = Document(
                filing_id=db_filing.id,
                document_url=doc.url,
                filename=doc.filename,
                content_type=doc.content_type,
            )
            session.add(document)

        session.commit()
        logger.debug(
            "Persisted filing %s with %d document(s)",
            filing.filing_id,
            len(filing.documents),
        )
        return True
    except Exception as exc:
        logger.warning(
            "Failed to persist filing %s: %s",
            filing.filing_id,
            exc,
        )
        try:
            session.rollback()
        except Exception:
            pass
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scrape_recent_filings(
    session: Session,
    settings: ScraperSettings,
) -> ScrapeResult:
    """Scrape recent filings from REGDOCS and persist new ones.

    Orchestration flow:
        1. Check robots.txt compliance
        2. Attempt API endpoint discovery (primary strategy)
        3. Fall back to DOM parsing if API discovery fails
        4. Validate scraped data
        5. Apply config filters (filing type, applicant, proceeding)
        6. Skip filings with no document URLs
        7. Deduplicate against state store
        8. Persist new filings to database
        9. Check for consecutive zero-filing runs
        10. Return ScrapeResult with counts

    This function never raises -- all errors are caught, logged, and returned
    in the :attr:`ScrapeResult.errors` list.

    Args:
        session: Active SQLAlchemy session for state store queries and persistence.
        settings: Scraper configuration (base URL, filters, delays, etc.).

    Returns:
        :class:`ScrapeResult` with detailed counts and strategy information.
    """
    result = ScrapeResult()

    try:
        # ---------------------------------------------------------------
        # Step 1: robots.txt check
        # ---------------------------------------------------------------
        logger.info("Scrape starting: checking robots.txt")
        allowed = check_robots_allowed(
            settings.base_url,
            settings.recent_filings_path,
            settings.user_agent,
        )
        if not allowed:
            logger.error(
                "robots.txt disallows scraping %s%s -- aborting",
                settings.base_url,
                settings.recent_filings_path,
            )
            result.errors.append("robots.txt disallows scraping")
            return result

        # ---------------------------------------------------------------
        # Step 2: API discovery (primary strategy)
        # ---------------------------------------------------------------
        filings: list[ScrapedFiling] = []
        discovery: DiscoveryResult | None = None

        logger.info("Attempting API endpoint discovery (primary strategy)")
        try:
            discovery = discover_api_endpoints(settings)
        except Exception as exc:
            logger.warning("API discovery raised unexpected error: %s", exc)
            discovery = DiscoveryResult()

        if discovery.success and discovery.filing_endpoints:
            logger.info(
                "API discovery succeeded: %d filing endpoint(s)",
                len(discovery.filing_endpoints),
            )
            try:
                filings = fetch_filings_from_api(
                    discovery.filing_endpoints,
                    discovery.cookies,
                    settings,
                )
                if filings:
                    result.strategy_used = "api"
                    logger.info(
                        "API client returned %d filing(s)", len(filings)
                    )
            except Exception as exc:
                logger.warning("API client raised unexpected error: %s", exc)
                filings = []

        # ---------------------------------------------------------------
        # Step 3: DOM parsing fallback
        # ---------------------------------------------------------------
        if not filings:
            logger.info(
                "API strategy produced zero filings -- falling back to DOM parsing"
            )
            rendered_html = ""

            # Use rendered HTML from discovery if available.
            if discovery and discovery.rendered_html:
                rendered_html = discovery.rendered_html
                logger.debug("Using rendered HTML from discovery (length: %d)", len(rendered_html))
            else:
                # Launch a quick Playwright session to get rendered HTML.
                logger.info("No rendered HTML available -- launching Playwright for DOM content")
                try:
                    from playwright.sync_api import sync_playwright

                    with sync_playwright() as pw:
                        browser = pw.chromium.launch(headless=True)
                        context = browser.new_context(user_agent=settings.user_agent)
                        page = context.new_page()
                        nav_url = f"{settings.base_url}{settings.recent_filings_path}?p=2"
                        page.goto(nav_url, timeout=30_000)
                        page.wait_for_load_state("networkidle", timeout=30_000)
                        rendered_html = page.content()
                        browser.close()
                except Exception as exc:
                    logger.warning("Playwright DOM fallback failed: %s", exc)
                    rendered_html = ""

            if rendered_html:
                try:
                    filings = parse_filings_from_html(rendered_html, settings.base_url)
                    if filings:
                        result.strategy_used = "dom"
                        logger.info(
                            "DOM parser returned %d filing(s)", len(filings)
                        )
                except Exception as exc:
                    logger.warning("DOM parser raised unexpected error: %s", exc)
                    filings = []

        # If both strategies failed.
        if not filings:
            logger.warning(
                "Both API and DOM strategies returned zero filings"
            )
            result.errors.append("Both API and DOM strategies returned zero filings")

        result.total_found = len(filings)

        # ---------------------------------------------------------------
        # Step 4: Validate scraped data
        # ---------------------------------------------------------------
        validation_warnings = _validate_filings(filings)
        result.errors.extend(validation_warnings)

        # ---------------------------------------------------------------
        # Step 5: Apply config filters
        # ---------------------------------------------------------------
        filings, skipped_filtered = _apply_filters(filings, settings)
        result.skipped_filtered = skipped_filtered

        # ---------------------------------------------------------------
        # Step 6: Skip filings with no documents
        # ---------------------------------------------------------------
        filings, skipped_no_docs = _skip_no_documents(filings)
        result.skipped_no_documents = skipped_no_docs

        # ---------------------------------------------------------------
        # Step 7: Deduplicate against state store
        # ---------------------------------------------------------------
        new_filings: list[ScrapedFiling] = []
        for f in filings:
            try:
                if filing_exists(session, f.filing_id):
                    result.skipped_existing += 1
                    logger.debug("Filing %s already exists -- skipping", f.filing_id)
                else:
                    new_filings.append(f)
            except Exception as exc:
                logger.warning(
                    "Error checking existence of filing %s: %s", f.filing_id, exc
                )
                result.errors.append(f"Dedup check failed for {f.filing_id}: {exc}")

        logger.info(
            "Deduplication: %d existing, %d new",
            result.skipped_existing,
            len(new_filings),
        )

        # ---------------------------------------------------------------
        # Step 8: Persist new filings
        # ---------------------------------------------------------------
        for f in new_filings:
            if _persist_filing(session, f):
                result.new_filings += 1
            else:
                result.errors.append(f"Failed to persist filing {f.filing_id}")

        # ---------------------------------------------------------------
        # Step 9: Zero-filing consecutive run tracking
        # ---------------------------------------------------------------
        if result.new_filings == 0:
            try:
                if _check_consecutive_zero_runs(session, _ZERO_FILING_THRESHOLD):
                    logger.warning(
                        "Zero new filings for %d consecutive runs -- "
                        "REGDOCS site structure may have changed",
                        _ZERO_FILING_THRESHOLD,
                    )
            except Exception as exc:
                logger.debug("Could not check consecutive zero runs: %s", exc)

        # ---------------------------------------------------------------
        # Step 10: Return result
        # ---------------------------------------------------------------
        logger.info(
            "Scrape complete: strategy=%s, total_found=%d, new=%d, "
            "skipped_existing=%d, skipped_no_docs=%d, skipped_filtered=%d, errors=%d",
            result.strategy_used,
            result.total_found,
            result.new_filings,
            result.skipped_existing,
            result.skipped_no_documents,
            result.skipped_filtered,
            len(result.errors),
        )

    except Exception as exc:
        # Top-level catch-all -- orchestrator must never crash the pipeline.
        logger.error("Scraper orchestrator caught unexpected error: %s", exc, exc_info=True)
        result.errors.append(f"Unexpected orchestrator error: {exc}")

    return result


__all__ = ["scrape_recent_filings", "ScrapeResult", "ScrapedFiling", "ScrapedDocument"]
