"""httpx-based API client for querying discovered REGDOCS endpoints.

After :func:`~cer_scraper.scraper.discovery.discover_api_endpoints` identifies
filing-like API endpoints, this module fetches data from those endpoints using
httpx with cookies transferred from the Playwright browser context.  HTTP
errors are retried with exponential backoff via tenacity.

All public functions return data or an empty list -- they never raise on
network/parse errors so the caller can fall back to DOM parsing.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any

import httpx
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from cer_scraper.config.settings import ScraperSettings
from cer_scraper.scraper.discovery import DiscoveredEndpoint
from cer_scraper.scraper.models import ScrapedDocument, ScrapedFiling
from cer_scraper.scraper.rate_limiter import wait_between_requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Key aliases -- used for case-insensitive, resilient field extraction.
# Each tuple maps a target field to possible JSON key names.
# ---------------------------------------------------------------------------
_KEY_ALIASES: dict[str, tuple[str, ...]] = {
    "filing_id": (
        "id",
        "filing_id",
        "filingid",
        "nodeid",
        "fileid",
        "ID",
        "NodeID",
    ),
    "date": (
        "date",
        "filing_date",
        "filingdate",
        "otcreatedate",
        "createdate",
        "OTCreateDate",
        "CreateDate",
        "DateFiled",
        "dateFiled",
    ),
    "applicant": (
        "applicant",
        "company",
        "submitter",
        "name",
        "otname",
        "OTName",
        "Name",
        "Applicant",
        "Company",
    ),
    "filing_type": (
        "type",
        "filing_type",
        "filingtype",
        "subtype",
        "SubType",
        "Type",
        "DocumentType",
        "documentType",
    ),
    "proceeding_number": (
        "proceeding",
        "proceeding_number",
        "proceedingnumber",
        "ProceedingNumber",
        "Proceeding",
    ),
    "title": (
        "title",
        "name",
        "otname",
        "OTName",
        "Title",
        "Name",
        "DocumentTitle",
        "documentTitle",
    ),
    "url": (
        "url",
        "link",
        "href",
        "Url",
        "URL",
        "Link",
    ),
    "documents": (
        "documents",
        "attachments",
        "files",
        "documentUrls",
        "document_urls",
        "Documents",
        "Attachments",
    ),
}

# Keys that hint at individual document URLs within a filing item.
_DOC_URL_HINTS = ("url", "link", "document", "pdf", "href", "attachment")


# ---------------------------------------------------------------------------
# Retry-wrapped fetch function
# ---------------------------------------------------------------------------

@retry(
    stop=stop_after_attempt(3),
    wait=wait_random_exponential(multiplier=1, min=2, max=30),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    retry=retry_if_exception_type(
        (httpx.HTTPStatusError, httpx.TimeoutException, httpx.ConnectError)
    ),
)
def _fetch_endpoint(client: httpx.Client, url: str) -> dict:
    """GET *url* and return the parsed JSON body.

    Retries up to 3 times with random exponential backoff on HTTP errors,
    timeouts, and connection errors.
    """
    response = client.get(url)
    response.raise_for_status()
    return response.json()


# ---------------------------------------------------------------------------
# Resilient JSON -> ScrapedFiling parsing
# ---------------------------------------------------------------------------

def _get_field(item: dict[str, Any], field: str) -> Any | None:
    """Look up *field* in *item* using case-insensitive alias matching.

    Returns the first non-``None`` value found, or ``None``.
    """
    aliases = _KEY_ALIASES.get(field, ())
    # Build a case-insensitive lookup of the item's keys.
    lower_map: dict[str, str] = {k.lower(): k for k in item}

    for alias in aliases:
        # Try exact match first (faster).
        if alias in item and item[alias] is not None:
            return item[alias]
        # Fall back to case-insensitive match.
        original_key = lower_map.get(alias.lower())
        if original_key is not None and item[original_key] is not None:
            return item[original_key]
    return None


def _parse_date(raw: Any) -> datetime.date | None:
    """Best-effort conversion of *raw* to a :class:`datetime.date`."""
    if raw is None:
        return None
    if isinstance(raw, datetime.date):
        return raw
    raw_str = str(raw).strip()
    # Try common date formats.
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ",
                "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.datetime.strptime(raw_str[:len(fmt) + 2], fmt).date()
        except (ValueError, IndexError):
            continue
    # Last resort: take first 10 chars if they look like YYYY-MM-DD.
    if len(raw_str) >= 10 and raw_str[4] == "-" and raw_str[7] == "-":
        try:
            return datetime.date.fromisoformat(raw_str[:10])
        except ValueError:
            pass
    return None


def _extract_documents(
    item: dict[str, Any], base_url: str
) -> list[ScrapedDocument]:
    """Pull document URLs from an API response item."""
    docs: list[ScrapedDocument] = []

    # Strategy 1: explicit documents list.
    doc_list = _get_field(item, "documents")
    if isinstance(doc_list, list):
        for d in doc_list:
            if isinstance(d, dict):
                doc_url = None
                for k, v in d.items():
                    if any(hint in k.lower() for hint in _DOC_URL_HINTS):
                        if isinstance(v, str) and v:
                            doc_url = v
                            break
                if doc_url:
                    docs.append(
                        ScrapedDocument(
                            url=doc_url,
                            filename=d.get("filename") or d.get("name"),
                            content_type=d.get("content_type")
                            or d.get("contentType")
                            or d.get("mimeType"),
                        )
                    )
            elif isinstance(d, str) and d:
                docs.append(ScrapedDocument(url=d))

    # Strategy 2: scan top-level keys for document URL patterns.
    if not docs:
        for key, value in item.items():
            if any(hint in key.lower() for hint in _DOC_URL_HINTS):
                if isinstance(value, str) and value.startswith(("http", "/")):
                    docs.append(ScrapedDocument(url=value))

    return docs


def _parse_single_item(
    item: dict[str, Any], base_url: str
) -> ScrapedFiling | None:
    """Try to create a :class:`ScrapedFiling` from a single JSON item."""
    filing_id_raw = _get_field(item, "filing_id")
    if filing_id_raw is None:
        return None

    filing_id = str(filing_id_raw).strip()
    if not filing_id:
        return None

    # Build the filing URL if not directly available.
    filing_url = _get_field(item, "url")
    if not filing_url:
        filing_url = f"{base_url}/Item/Filing/{filing_id}"

    applicant_raw = _get_field(item, "applicant")
    # Avoid using the same value for both title and applicant when they
    # resolve to the same alias (e.g. both map to "Name"/"OTName").
    title_raw = _get_field(item, "title")
    if title_raw and applicant_raw and str(title_raw) == str(applicant_raw):
        # Keep title, let applicant fall back to None.
        applicant_raw = None

    documents = _extract_documents(item, base_url)

    logger.debug(
        "Parsed filing item: id=%s, date=%s, applicant=%s, type=%s, docs=%d",
        filing_id,
        _get_field(item, "date"),
        applicant_raw,
        _get_field(item, "filing_type"),
        len(documents),
    )

    return ScrapedFiling(
        filing_id=filing_id,
        date=_parse_date(_get_field(item, "date")),
        applicant=str(applicant_raw) if applicant_raw else None,
        filing_type=str(ft) if (ft := _get_field(item, "filing_type")) else None,
        proceeding_number=(
            str(pn) if (pn := _get_field(item, "proceeding_number")) else None
        ),
        title=str(title_raw) if title_raw else None,
        url=str(filing_url),
        documents=documents,
    )


def _parse_api_response(
    url: str, data: Any, base_url: str
) -> list[ScrapedFiling]:
    """Convert an arbitrary JSON response into a list of :class:`ScrapedFiling`.

    Resilient to unknown structures: looks for list-like collections in the
    response and attempts to extract filing metadata from each item.
    """
    items: list[dict[str, Any]] = []

    if isinstance(data, list):
        items = [i for i in data if isinstance(i, dict)]
    elif isinstance(data, dict):
        # Look for nested lists that might contain filings.
        for value in data.values():
            if isinstance(value, list) and len(value) > 0:
                candidates = [i for i in value if isinstance(i, dict)]
                if candidates:
                    items = candidates
                    break

    filings: list[ScrapedFiling] = []
    for item in items:
        try:
            filing = _parse_single_item(item, base_url)
            if filing is not None:
                filings.append(filing)
        except Exception as exc:
            logger.warning(
                "Failed to parse filing item from %s: %s", url, exc
            )
    return filings


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_filings_from_api(
    endpoints: list[DiscoveredEndpoint],
    cookies: dict[str, str],
    settings: ScraperSettings,
) -> list[ScrapedFiling]:
    """Fetch filing metadata from *endpoints* discovered by Playwright.

    Creates an httpx client with the browser's cookies for session
    continuity, queries each filing endpoint with retry logic, and
    parses responses into :class:`ScrapedFiling` models.

    Returns an empty list on complete failure -- never raises.
    """
    if not endpoints:
        logger.info("No filing endpoints to query; returning empty list")
        return []

    logger.info(
        "API client starting: %d endpoint(s) to query", len(endpoints)
    )

    all_filings: list[ScrapedFiling] = []

    client = httpx.Client(
        headers={
            "User-Agent": settings.user_agent,
            "Accept": "application/json",
        },
        cookies=cookies,
        timeout=httpx.Timeout(30.0),
        follow_redirects=True,
    )

    try:
        for idx, endpoint in enumerate(endpoints):
            logger.debug(
                "Querying endpoint %d/%d: %s",
                idx + 1,
                len(endpoints),
                endpoint.url,
            )
            try:
                data = _fetch_endpoint(client, endpoint.url)
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status in (401, 403):
                    logger.warning(
                        "API endpoint may require authentication. "
                        "Cookies may have expired. URL: %s (HTTP %d)",
                        endpoint.url,
                        status,
                    )
                else:
                    logger.warning(
                        "HTTP %d from %s after retries: %s",
                        status,
                        endpoint.url,
                        exc,
                    )
                continue
            except Exception as exc:
                logger.warning(
                    "Failed to fetch %s after retries: %s",
                    endpoint.url,
                    exc,
                )
                continue

            filings = _parse_api_response(
                endpoint.url, data, settings.base_url
            )
            logger.debug(
                "Endpoint %s yielded %d filing(s)", endpoint.url, len(filings)
            )
            all_filings.extend(filings)

            # Polite delay between endpoint requests.
            if idx < len(endpoints) - 1:
                wait_between_requests(
                    settings.delay_min_seconds,
                    settings.delay_max_seconds,
                )
    finally:
        client.close()

    logger.info(
        "API client complete: %d filing(s) from %d endpoint(s)",
        len(all_filings),
        len(endpoints),
    )
    return all_filings
