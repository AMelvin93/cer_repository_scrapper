"""Playwright network interception for REGDOCS API endpoint discovery.

Navigates the REGDOCS Recent Filings page using a headless Chromium browser,
captures all JSON/XML network responses during page load, and classifies
which responses contain filing metadata. Exports discovered endpoints,
browser cookies (for httpx session continuity), and rendered HTML (for
DOM parser fallback).

Uses the sync Playwright API exclusively to avoid Windows event loop
conflicts (see 02-RESEARCH.md Pitfall 7).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Response, sync_playwright

from cer_scraper.config.settings import ScraperSettings
from cer_scraper.scraper.rate_limiter import wait_between_requests

logger = logging.getLogger(__name__)

# Heuristic field names that suggest filing/document metadata.
_FILING_HINT_KEYS = frozenset(
    {
        "id",
        "filing_id",
        "filingid",
        "nodeid",
        "date",
        "filing_date",
        "filingdate",
        "otcreatedate",
        "createdate",
        "applicant",
        "company",
        "submitter",
        "name",
        "otname",
        "type",
        "filing_type",
        "filingtype",
        "subtype",
        "proceeding",
        "proceeding_number",
        "proceedingnumber",
        "title",
    }
)

# URL path fragments that hint at filing/search endpoints.
_FILING_URL_PATTERNS = ("search", "filing", "document", "recent", "result")

# Lookback period string to REGDOCS ``p`` query parameter.
_LOOKBACK_MAP: dict[str, int] = {
    "day": 1,
    "week": 2,
    "month": 3,
}


@dataclass
class DiscoveredEndpoint:
    """A single API-like response captured during page navigation."""

    url: str
    method: str
    status_code: int
    content_type: str
    body: Any
    has_filing_data: bool


@dataclass
class DiscoveryResult:
    """Aggregated output from the endpoint discovery process."""

    endpoints: list[DiscoveredEndpoint] = field(default_factory=list)
    filing_endpoints: list[DiscoveredEndpoint] = field(default_factory=list)
    cookies: dict[str, str] = field(default_factory=dict)
    rendered_html: str = ""
    success: bool = False


def _looks_like_filing_data(body: Any, url: str) -> bool:
    """Heuristic: does *body* look like it contains filing metadata?

    Checks for list/array structures whose items have keys resembling
    filing fields, or URL path fragments associated with search/filing
    endpoints.
    """
    items: list[Any] = []

    if isinstance(body, list) and len(body) > 0:
        items = body
    elif isinstance(body, dict):
        # Check for nested list values (common API pagination wrappers).
        for value in body.values():
            if isinstance(value, list) and len(value) > 0:
                items = value
                break

    if not items:
        return False

    # Check first item for filing-like keys (case-insensitive).
    first = items[0]
    if isinstance(first, dict):
        lower_keys = {k.lower() for k in first}
        overlap = lower_keys & _FILING_HINT_KEYS
        if len(overlap) >= 2:
            return True

    # Fallback: check URL for filing-related patterns.
    url_lower = url.lower()
    for pattern in _FILING_URL_PATTERNS:
        if pattern in url_lower:
            return True

    return False


def discover_api_endpoints(settings: ScraperSettings) -> DiscoveryResult:
    """Navigate REGDOCS and capture API responses containing filing data.

    Launches a headless Chromium browser, registers a network response
    listener, navigates to the Recent Filings page, and captures all
    JSON/XML responses.  If no filing endpoints are found on the first
    attempt, retries with different lookback periods up to
    ``settings.discovery_retries`` times.

    Returns a :class:`DiscoveryResult` with discovered endpoints,
    browser cookies, and the last page's rendered HTML.
    """
    result = DiscoveryResult()
    captured: list[DiscoveredEndpoint] = []

    # --- response callback (registered BEFORE goto) ---
    def _handle_response(response: Response) -> None:
        content_type = response.headers.get("content-type", "")
        if "json" not in content_type and "xml" not in content_type:
            return
        try:
            body = response.json()
        except Exception:
            return  # Not valid JSON despite content-type header.

        has_filing = _looks_like_filing_data(body, response.url)
        endpoint = DiscoveredEndpoint(
            url=response.url,
            method=response.request.method,
            status_code=response.status,
            content_type=content_type,
            body=body,
            has_filing_data=has_filing,
        )
        captured.append(endpoint)
        logger.debug(
            "Captured %s %s (status %d, content-type %s, filing_data=%s)",
            endpoint.method,
            endpoint.url,
            endpoint.status_code,
            endpoint.content_type,
            has_filing,
        )

    # --- determine page navigation order ---
    primary_p = _LOOKBACK_MAP.get(settings.lookback_period, 2)
    # Build retry sequence: primary first, then the other periods.
    all_periods = [primary_p] + [p for p in (1, 2, 3) if p != primary_p]
    max_attempts = min(settings.discovery_retries, len(all_periods))

    base_url = f"{settings.base_url}{settings.recent_filings_path}"

    logger.info(
        "Starting REGDOCS API discovery (up to %d attempts, primary period p=%d)",
        max_attempts,
        primary_p,
    )

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(user_agent=settings.user_agent)
            page = context.new_page()

            # Register listener BEFORE any navigation (avoid race condition).
            page.on("response", _handle_response)

            for attempt_idx, period in enumerate(all_periods[:max_attempts]):
                nav_url = f"{base_url}?p={period}"
                logger.info(
                    "Discovery attempt %d/%d: navigating to %s",
                    attempt_idx + 1,
                    max_attempts,
                    nav_url,
                )
                try:
                    page.goto(nav_url, timeout=30_000)
                    page.wait_for_load_state("networkidle", timeout=30_000)
                except PlaywrightError as exc:
                    logger.warning(
                        "Navigation/wait failed for %s: %s", nav_url, exc
                    )

                # Check if we found filing endpoints already.
                filing_eps = [ep for ep in captured if ep.has_filing_data]
                if filing_eps:
                    logger.info(
                        "Found %d filing endpoint(s) on attempt %d",
                        len(filing_eps),
                        attempt_idx + 1,
                    )
                    break

                # No filing endpoints yet -- wait politely before retrying.
                if attempt_idx < max_attempts - 1:
                    logger.info(
                        "No filing endpoints found yet; retrying after delay"
                    )
                    wait_between_requests(
                        settings.delay_min_seconds,
                        settings.delay_max_seconds,
                    )

            # Extract cookies from browser context.
            result.cookies = {
                c["name"]: c["value"] for c in context.cookies()
            }

            # Capture rendered HTML from the last visited page.
            result.rendered_html = page.content()

            browser.close()

    except PlaywrightError as exc:
        error_msg = str(exc)
        if "Executable doesn't exist" in error_msg or "browserType.launch" in error_msg:
            logger.warning(
                "Chromium browser not installed. Run: uv run playwright install chromium"
            )
        else:
            logger.warning("Playwright error during discovery: %s", exc)
        return result
    except Exception as exc:
        logger.warning("Unexpected error during discovery: %s", exc)
        return result

    # Populate result.
    result.endpoints = list(captured)
    result.filing_endpoints = [ep for ep in captured if ep.has_filing_data]
    result.success = len(result.filing_endpoints) > 0

    if result.success:
        logger.info(
            "Discovery complete: %d total endpoints, %d filing endpoint(s)",
            len(result.endpoints),
            len(result.filing_endpoints),
        )
    else:
        logger.warning(
            "Discovery complete but no filing endpoints found "
            "(%d total endpoints captured). DOM fallback may be needed.",
            len(result.endpoints),
        )

    return result
