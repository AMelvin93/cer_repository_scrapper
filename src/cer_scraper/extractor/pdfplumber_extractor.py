"""Fallback PDF text extraction using pdfplumber.

Table-focused extractor that handles complex and merged-cell tables better
than pymupdf4llm. This is the second tier in the extraction fallback chain,
activated when the primary pymupdf4llm extraction fails quality checks.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pandas as pd
import pdfplumber
from pdfplumber.utils import get_bbox_overlap, obj_to_bbox

from cer_scraper.config.settings import ExtractionSettings
from cer_scraper.extractor.types import ExtractionMethod, ExtractionResult

logger = logging.getLogger(__name__)

# Pattern to strip markdown syntax and whitespace for meaningful char count
_SYNTAX_PATTERN = re.compile(r"[#|*_\-\s\n]")


def _clamp_bbox(
    bbox: tuple[float, float, float, float],
    page_width: float,
    page_height: float,
) -> tuple[float, float, float, float]:
    """Clamp a bounding box to page boundaries.

    pdfplumber can sometimes detect table regions that extend slightly beyond
    page edges, causing ValueError during filtering. Clamping prevents this.

    Args:
        bbox: (x0, top, x1, bottom) bounding box.
        page_width: Width of the page.
        page_height: Height of the page.

    Returns:
        Clamped bounding box within page boundaries.
    """
    x0, top, x1, bottom = bbox
    return (
        max(0, x0),
        max(0, top),
        min(page_width, x1),
        min(page_height, bottom),
    )


def _table_to_markdown(table_data: list[list[str | None]]) -> str | None:
    """Convert pdfplumber table data to pipe-delimited markdown table.

    Args:
        table_data: List of rows, where the first row is the header.

    Returns:
        Markdown table string, or None if table is empty or malformed.
    """
    if not table_data or len(table_data) < 2:
        return None

    header = table_data[0]
    rows = table_data[1:]

    # Replace None cells with empty strings
    header = [str(cell) if cell is not None else "" for cell in header]
    cleaned_rows = [
        [str(cell) if cell is not None else "" for cell in row] for row in rows
    ]

    try:
        df = pd.DataFrame(cleaned_rows, columns=header)
        return df.to_markdown(index=False)
    except Exception:
        # Fallback: if DataFrame creation fails (mismatched columns, etc.)
        return None


def try_pdfplumber(pdf_path: Path, settings: ExtractionSettings) -> ExtractionResult:
    """Extract text from a PDF using pdfplumber with table detection.

    For each page, finds tables and extracts them as pipe-delimited markdown.
    Non-table text is extracted with layout preservation. Tables are filtered
    from the text region to avoid duplication.

    Args:
        pdf_path: Path to the PDF file.
        settings: Extraction configuration.

    Returns:
        ExtractionResult with markdown text on success, or with
        success=False and error message on failure.
    """
    try:
        all_pages_md: list[str] = []

        with pdfplumber.open(str(pdf_path)) as pdf:
            page_count = len(pdf.pages)

            for page_num, page in enumerate(pdf.pages):
                page_parts: list[str] = []

                tables = page.find_tables()

                if tables:
                    # Clamp table bounding boxes to page boundaries
                    # to avoid ValueError during filtering
                    clamped_bboxes = [
                        _clamp_bbox(
                            table.bbox, page.width, page.height
                        )
                        for table in tables
                    ]

                    # Filter out text within table regions
                    filtered_page = page
                    for clamped_bbox in clamped_bboxes:
                        filtered_page = filtered_page.filter(
                            lambda obj, bbox=clamped_bbox: get_bbox_overlap(
                                obj_to_bbox(obj), bbox
                            )
                            is None
                        )

                    # Extract non-table text with layout preservation
                    text = filtered_page.extract_text(layout=True)
                    if text and text.strip():
                        page_parts.append(text.strip())

                    # Extract each table as a markdown table
                    for table in tables:
                        table_data = table.extract()
                        md_table = _table_to_markdown(table_data)
                        if md_table:
                            page_parts.append(md_table)
                else:
                    # No tables on this page -- extract full text
                    text = page.extract_text(layout=True)
                    if text and text.strip():
                        page_parts.append(text.strip())

                if page_parts:
                    all_pages_md.append("\n\n".join(page_parts))

        md_text = "\n\n---\n\n".join(all_pages_md)

        # Count meaningful characters (strip markdown syntax and whitespace)
        clean_text = _SYNTAX_PATTERN.sub("", md_text)
        char_count = len(clean_text)

        logger.info(
            "pdfplumber extracted %d chars from %d pages: %s",
            char_count,
            page_count,
            pdf_path.name,
        )

        return ExtractionResult(
            success=True,
            markdown=md_text,
            method=ExtractionMethod.PDFPLUMBER,
            page_count=page_count,
            char_count=char_count,
        )

    except Exception as e:
        logger.warning("pdfplumber extraction failed for %s: %s", pdf_path.name, e)
        return ExtractionResult(success=False, error=str(e))
