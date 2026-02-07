"""BeautifulSoup DOM parsing fallback for REGDOCS filing extraction.

When API endpoint discovery fails (no JSON endpoints found during Playwright
interception), the scraper falls back to parsing the fully-rendered HTML
using BeautifulSoup with the lxml backend.

Uses a multi-strategy approach to handle unknown/changing HTML structures:
    Strategy 1 -- Table-based layout (REGDOCS typically renders results in tables)
    Strategy 2 -- Link-based extraction (filing/document URL patterns)
    Strategy 3 -- Data attribute extraction (data-filing-id, data-id, etc.)

All strategies produce the same :class:`ScrapedFiling` output model used by
the API client, so downstream code never knows which path produced the data.
"""

from __future__ import annotations

import datetime
import logging
import re
from typing import Optional

from bs4 import BeautifulSoup, Tag

from cer_scraper.scraper.models import ScrapedDocument, ScrapedFiling

logger = logging.getLogger(__name__)

# Header keywords used to identify filing tables (case-insensitive).
_TABLE_HEADER_KEYWORDS = {"filing", "date", "applicant", "type", "proceeding", "title", "name"}

# URL patterns for filing pages.
_FILING_URL_RE = re.compile(r"/Item/Filing/([A-Za-z0-9]+)", re.IGNORECASE)

# URL patterns for document view pages.
_DOCUMENT_URL_RE = re.compile(r"/Item/View/([A-Za-z0-9]+)", re.IGNORECASE)

# File extensions that indicate downloadable documents.
_DOC_EXTENSIONS = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".rtf", ".txt", ".zip")

# MIME type mapping for file extensions.
_EXTENSION_MIME_MAP: dict[str, str] = {
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".csv": "text/csv",
    ".rtf": "application/rtf",
    ".txt": "text/plain",
    ".zip": "application/zip",
}

# Date formats to try when parsing date strings.
_DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%SZ",
    "%m/%d/%Y",
    "%d/%m/%Y",
    "%B %d, %Y",        # January 15, 2026
    "%b %d, %Y",        # Jan 15, 2026
    "%B %d %Y",         # January 15 2026
    "%b %d %Y",         # Jan 15 2026
    "%Y/%m/%d",
    "%d-%b-%Y",         # 15-Jan-2026
)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _clean_text(text: str) -> str:
    """Strip whitespace, collapse multiple spaces, remove non-breaking spaces."""
    cleaned = text.replace("\xa0", " ").replace("\u200b", "")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _extract_date(text: str) -> Optional[datetime.date]:
    """Try multiple date formats and return the first match, or None."""
    if not text:
        return None

    cleaned = _clean_text(text)
    if not cleaned:
        return None

    for fmt in _DATE_FORMATS:
        try:
            return datetime.datetime.strptime(cleaned, fmt).date()
        except (ValueError, IndexError):
            continue

    # Last resort: look for YYYY-MM-DD substring anywhere in the text.
    iso_match = re.search(r"(\d{4}-\d{2}-\d{2})", cleaned)
    if iso_match:
        try:
            return datetime.date.fromisoformat(iso_match.group(1))
        except ValueError:
            pass

    logger.debug("Could not parse date from text: %r", cleaned[:80])
    return None


def _infer_content_type(url: str) -> Optional[str]:
    """Map file extensions in the URL to MIME types."""
    url_lower = url.lower().split("?")[0]  # Strip query params before checking.
    for ext, mime in _EXTENSION_MIME_MAP.items():
        if url_lower.endswith(ext):
            return mime
    return None


def _extract_filing_id_from_url(url: str) -> Optional[str]:
    """Extract a filing ID from a REGDOCS filing URL."""
    match = _FILING_URL_RE.search(url)
    return match.group(1) if match else None


def _extract_document_id_from_url(url: str) -> Optional[str]:
    """Extract a document ID from a REGDOCS document view URL."""
    match = _DOCUMENT_URL_RE.search(url)
    return match.group(1) if match else None


def _resolve_url(href: str, base_url: str) -> str:
    """Resolve a relative URL against the base URL."""
    if href.startswith(("http://", "https://")):
        return href
    base = base_url.rstrip("/")
    if href.startswith("/"):
        # Absolute path -- prepend scheme + host from base_url.
        # For REGDOCS, base_url is like https://apps.cer-rec.gc.ca/REGDOCS
        # and we want https://apps.cer-rec.gc.ca + href
        from urllib.parse import urlparse

        parsed = urlparse(base_url)
        return f"{parsed.scheme}://{parsed.netloc}{href}"
    return f"{base}/{href}"


def _find_document_links(container: Tag, base_url: str) -> list[ScrapedDocument]:
    """Find all document links within a DOM container element."""
    docs: list[ScrapedDocument] = []
    seen_urls: set[str] = set()

    for anchor in container.find_all("a", href=True):
        href = str(anchor["href"])
        resolved = _resolve_url(href, base_url)

        # Match REGDOCS document view URLs.
        if _DOCUMENT_URL_RE.search(href):
            if resolved not in seen_urls:
                seen_urls.add(resolved)
                link_text = _clean_text(anchor.get_text())
                docs.append(
                    ScrapedDocument(
                        url=resolved,
                        filename=link_text if link_text else None,
                        content_type=_infer_content_type(href),
                    )
                )
            continue

        # Match direct file download URLs (by extension).
        href_lower = href.lower().split("?")[0]
        if any(href_lower.endswith(ext) for ext in _DOC_EXTENSIONS):
            if resolved not in seen_urls:
                seen_urls.add(resolved)
                link_text = _clean_text(anchor.get_text())
                docs.append(
                    ScrapedDocument(
                        url=resolved,
                        filename=link_text if link_text else href.rsplit("/", 1)[-1],
                        content_type=_infer_content_type(href),
                    )
                )

    return docs


# ---------------------------------------------------------------------------
# Strategy 1: Table-based layout
# ---------------------------------------------------------------------------

def _strategy_table(soup: BeautifulSoup, base_url: str) -> list[ScrapedFiling]:
    """Extract filings from HTML table structures."""
    filings: list[ScrapedFiling] = []

    for table in soup.find_all("table"):
        # Look for header row with filing-related keywords.
        header_row = table.find("tr")
        if header_row is None:
            continue

        headers = [_clean_text(th.get_text()).lower() for th in header_row.find_all(["th", "td"])]
        if not headers:
            continue

        # Check if enough header keywords match.
        keyword_matches = sum(1 for h in headers if any(kw in h for kw in _TABLE_HEADER_KEYWORDS))
        if keyword_matches < 2:
            continue

        logger.debug("Found filing table with headers: %s", headers)

        # Build a column index map.
        col_map: dict[str, int] = {}
        for idx, header_text in enumerate(headers):
            for kw in _TABLE_HEADER_KEYWORDS:
                if kw in header_text and kw not in col_map:
                    col_map[kw] = idx

        # Parse data rows.
        data_rows = table.find_all("tr")[1:]  # Skip header row.
        for row in data_rows:
            cells = row.find_all(["td", "th"])
            if not cells or len(cells) < 2:
                continue

            # Try to extract filing_id from links in the row.
            filing_id = None
            filing_url = None
            for anchor in row.find_all("a", href=True):
                href = str(anchor["href"])
                extracted_id = _extract_filing_id_from_url(href)
                if extracted_id:
                    filing_id = extracted_id
                    filing_url = _resolve_url(href, base_url)
                    break

            if not filing_id:
                continue

            # Extract metadata from cells based on column map.
            def _cell_text(keyword: str) -> Optional[str]:
                col_idx = col_map.get(keyword)
                if col_idx is not None and col_idx < len(cells):
                    text = _clean_text(cells[col_idx].get_text())
                    return text if text else None
                return None

            date_text = _cell_text("date")
            applicant = _cell_text("applicant") or _cell_text("name")
            filing_type = _cell_text("type")
            proceeding = _cell_text("proceeding")
            title = _cell_text("title") or _cell_text("filing")

            # Find document links within this row.
            documents = _find_document_links(row, base_url)

            if not filing_url:
                filing_url = f"{base_url}/Item/Filing/{filing_id}"

            try:
                filing = ScrapedFiling(
                    filing_id=filing_id,
                    date=_extract_date(date_text) if date_text else None,
                    applicant=applicant,
                    filing_type=filing_type,
                    proceeding_number=proceeding,
                    title=title,
                    url=filing_url,
                    documents=documents,
                )
                filings.append(filing)
                logger.debug("Table strategy: extracted filing %s", filing_id)
            except Exception as exc:
                logger.warning("Table strategy: failed to create filing from row: %s", exc)

    return filings


# ---------------------------------------------------------------------------
# Strategy 2: Link-based extraction
# ---------------------------------------------------------------------------

def _strategy_links(soup: BeautifulSoup, base_url: str) -> list[ScrapedFiling]:
    """Extract filings by finding links matching REGDOCS URL patterns."""
    filings: list[ScrapedFiling] = []
    seen_ids: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"])
        filing_id = _extract_filing_id_from_url(href)
        if not filing_id or filing_id in seen_ids:
            continue

        seen_ids.add(filing_id)
        filing_url = _resolve_url(href, base_url)
        link_text = _clean_text(anchor.get_text())

        # Look at surrounding DOM context for metadata.
        parent = anchor.parent
        grandparent = parent.parent if parent else None

        # Search container for additional metadata.
        container = grandparent or parent or anchor
        container_text = _clean_text(container.get_text()) if container else ""

        # Try to extract date from surrounding text.
        filing_date = None
        if container_text:
            # Look for date patterns in container text.
            date_match = re.search(
                r"(\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4}|\w+ \d{1,2},?\s+\d{4})",
                container_text,
            )
            if date_match:
                filing_date = _extract_date(date_match.group(1))

        # Find document links in the same container.
        documents = _find_document_links(container, base_url) if isinstance(container, Tag) else []

        title = link_text if link_text and link_text != filing_id else None

        try:
            filing = ScrapedFiling(
                filing_id=filing_id,
                date=filing_date,
                applicant=None,
                filing_type=None,
                proceeding_number=None,
                title=title,
                url=filing_url,
                documents=documents,
            )
            filings.append(filing)
            logger.debug("Link strategy: extracted filing %s", filing_id)
        except Exception as exc:
            logger.warning("Link strategy: failed to create filing from link: %s", exc)

    return filings


# ---------------------------------------------------------------------------
# Strategy 3: Data attribute extraction
# ---------------------------------------------------------------------------

def _strategy_data_attributes(soup: BeautifulSoup, base_url: str) -> list[ScrapedFiling]:
    """Extract filings from elements with data attributes."""
    filings: list[ScrapedFiling] = []
    seen_ids: set[str] = set()

    # Look for elements with filing-related data attributes.
    selectors = [
        "[data-filing-id]",
        "[data-id]",
        "[data-nodeid]",
        "[data-filing]",
    ]

    for selector in selectors:
        elements = soup.select(selector)
        if not elements:
            continue

        logger.debug("Data attribute strategy: found %d elements with %s", len(elements), selector)

        for element in elements:
            # Extract the filing ID from the data attribute.
            filing_id = (
                element.get("data-filing-id")
                or element.get("data-id")
                or element.get("data-nodeid")
                or element.get("data-filing")
            )

            if not filing_id:
                continue

            filing_id = str(filing_id).strip()
            if not filing_id or filing_id in seen_ids:
                continue

            seen_ids.add(filing_id)

            # Extract text content for metadata.
            element_text = _clean_text(element.get_text())

            # Try to find metadata in nested elements or text.
            date_text = element.get("data-date") or element.get("data-filing-date")
            applicant = element.get("data-applicant") or element.get("data-company")
            filing_type = element.get("data-type") or element.get("data-filing-type")
            proceeding = element.get("data-proceeding")
            title_attr = element.get("data-title") or element.get("title")

            # Try to extract date from element text if not in attributes.
            filing_date = None
            if date_text:
                filing_date = _extract_date(str(date_text))
            elif element_text:
                date_match = re.search(r"(\d{4}-\d{2}-\d{2})", element_text)
                if date_match:
                    filing_date = _extract_date(date_match.group(1))

            # Find document links within this element.
            documents = _find_document_links(element, base_url) if isinstance(element, Tag) else []

            filing_url = f"{base_url}/Item/Filing/{filing_id}"

            try:
                filing = ScrapedFiling(
                    filing_id=filing_id,
                    date=filing_date,
                    applicant=str(applicant) if applicant else None,
                    filing_type=str(filing_type) if filing_type else None,
                    proceeding_number=str(proceeding) if proceeding else None,
                    title=str(title_attr) if title_attr else (element_text[:200] if element_text else None),
                    url=filing_url,
                    documents=documents,
                )
                filings.append(filing)
                logger.debug("Data attribute strategy: extracted filing %s", filing_id)
            except Exception as exc:
                logger.warning("Data attribute strategy: failed to create filing: %s", exc)

    return filings


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_filings_from_html(html: str, base_url: str) -> list[ScrapedFiling]:
    """Parse filing metadata from rendered REGDOCS HTML.

    Uses a multi-strategy approach since the exact HTML structure is unknown
    and may change over time:

    1. Table-based layout (tables with filing-keyword headers)
    2. Link-based extraction (anchor tags matching REGDOCS URL patterns)
    3. Data attribute extraction (elements with data-filing-id, etc.)

    Results are deduplicated by filing_id. Strategies are applied in order
    and all results are merged (later strategies may find filings missed by
    earlier ones).

    Args:
        html: The fully-rendered HTML page content.
        base_url: The REGDOCS base URL for resolving relative links.

    Returns:
        List of :class:`ScrapedFiling` models extracted from the HTML.
    """
    logger.info("DOM parser starting (HTML length: %d chars)", len(html))

    soup = BeautifulSoup(html, "lxml")

    all_filings: list[ScrapedFiling] = []
    seen_ids: set[str] = set()
    strategy_used: list[str] = []

    # Strategy 1: Table-based layout.
    table_filings = _strategy_table(soup, base_url)
    if table_filings:
        strategy_used.append("table")
        for f in table_filings:
            if f.filing_id not in seen_ids:
                seen_ids.add(f.filing_id)
                all_filings.append(f)
        logger.info("Table strategy: found %d filing(s)", len(table_filings))
    else:
        logger.debug("Table strategy: no filing tables found")

    # Strategy 2: Link-based extraction.
    link_filings = _strategy_links(soup, base_url)
    if link_filings:
        strategy_used.append("link")
        new_from_links = 0
        for f in link_filings:
            if f.filing_id not in seen_ids:
                seen_ids.add(f.filing_id)
                all_filings.append(f)
                new_from_links += 1
        logger.info(
            "Link strategy: found %d filing(s) (%d new after dedup)",
            len(link_filings),
            new_from_links,
        )
    else:
        logger.debug("Link strategy: no filing links found")

    # Strategy 3: Data attribute extraction.
    data_filings = _strategy_data_attributes(soup, base_url)
    if data_filings:
        strategy_used.append("data-attribute")
        new_from_data = 0
        for f in data_filings:
            if f.filing_id not in seen_ids:
                seen_ids.add(f.filing_id)
                all_filings.append(f)
                new_from_data += 1
        logger.info(
            "Data attribute strategy: found %d filing(s) (%d new after dedup)",
            len(data_filings),
            new_from_data,
        )
    else:
        logger.debug("Data attribute strategy: no elements with filing data attributes found")

    # Final summary.
    if all_filings:
        logger.info(
            "DOM parser complete: %d unique filing(s) via strategies: %s",
            len(all_filings),
            ", ".join(strategy_used),
        )
    else:
        logger.warning(
            "DOM parser found zero filings from all strategies. "
            "REGDOCS site structure may have changed. "
            "Check logs at DEBUG level for selector details."
        )

    return all_filings
