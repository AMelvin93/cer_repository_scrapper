"""Playwright-based detail page scraper for REGDOCS filing documents.

The REGDOCS Recent Filings table links to filing detail pages at
``/Item/View/{nodeId}``.  Document download URLs (``/File/Download/{docId}``)
are only available on these detail pages, not in the listing table.

This module visits each filing's detail page using a shared Playwright
browser session and extracts the ``/File/Download/`` links to populate
each filing's document list.
"""

from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from cer_scraper.config.settings import ScraperSettings
from cer_scraper.scraper.models import ScrapedDocument, ScrapedFiling
from cer_scraper.scraper.rate_limiter import wait_between_requests

logger = logging.getLogger(__name__)

_DOWNLOAD_URL_RE = re.compile(r"/File/Download/([A-Za-z0-9]+)", re.IGNORECASE)


def _scrape_detail_page(html: str, base_url: str) -> list[ScrapedDocument]:
    """Parse document download links from a filing detail page."""
    soup = BeautifulSoup(html, "lxml")
    docs: list[ScrapedDocument] = []
    seen_urls: set[str] = set()

    from urllib.parse import urlparse

    parsed_base = urlparse(base_url)
    origin = f"{parsed_base.scheme}://{parsed_base.netloc}"

    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"])
        if not _DOWNLOAD_URL_RE.search(href):
            continue

        # Resolve to absolute URL.
        if href.startswith(("http://", "https://")):
            resolved = href
        elif href.startswith("/"):
            resolved = f"{origin}{href}"
        else:
            resolved = f"{base_url.rstrip('/')}/{href}"

        if resolved in seen_urls:
            continue
        seen_urls.add(resolved)

        link_text = anchor.get_text().strip()
        link_text = re.sub(r"\s+", " ", link_text)

        docs.append(
            ScrapedDocument(
                url=resolved,
                filename=link_text if link_text else None,
                content_type="application/pdf",
            )
        )

    return docs


def enrich_filings_with_documents(
    filings: list[ScrapedFiling],
    settings: ScraperSettings,
) -> int:
    """Visit detail pages for filings without documents and add download links.

    Uses a single Playwright browser session to visit each filing's URL,
    extract ``/File/Download/`` links, and attach them as ScrapedDocument
    objects.  Rate-limits between page visits.

    Only visits filings that have a URL but no documents.

    Args:
        filings: List of ScrapedFiling objects to enrich in-place.
        settings: Scraper settings (for delays, user agent).

    Returns:
        Number of filings successfully enriched with documents.
    """
    needs_enrichment = [f for f in filings if f.url and not f.has_documents]
    if not needs_enrichment:
        logger.debug("No filings need document enrichment")
        return 0

    logger.info(
        "Enriching %d filing(s) with document links from detail pages",
        len(needs_enrichment),
    )

    enriched_count = 0

    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(user_agent=settings.user_agent)
            page = context.new_page()

            for idx, filing in enumerate(needs_enrichment):
                if idx > 0:
                    wait_between_requests(
                        settings.delay_min_seconds,
                        settings.delay_max_seconds,
                    )

                try:
                    logger.debug(
                        "Fetching detail page for filing %s: %s",
                        filing.filing_id,
                        filing.url,
                    )
                    page.goto(filing.url, timeout=30_000)
                    page.wait_for_load_state("networkidle", timeout=30_000)
                    html = page.content()

                    docs = _scrape_detail_page(html, settings.base_url)
                    if docs:
                        filing.documents = docs
                        enriched_count += 1
                        logger.info(
                            "Filing %s: found %d document(s) on detail page",
                            filing.filing_id,
                            len(docs),
                        )
                    else:
                        logger.warning(
                            "Filing %s: no download links found on detail page",
                            filing.filing_id,
                        )

                except PlaywrightError as exc:
                    logger.warning(
                        "Failed to fetch detail page for filing %s: %s",
                        filing.filing_id,
                        exc,
                    )
                except Exception as exc:
                    logger.warning(
                        "Unexpected error fetching detail page for filing %s: %s",
                        filing.filing_id,
                        exc,
                    )

            browser.close()

    except Exception as exc:
        logger.warning("Detail page scraper failed: %s", exc)

    logger.info(
        "Detail page enrichment complete: %d/%d filings enriched",
        enriched_count,
        len(needs_enrichment),
    )
    return enriched_count
