"""Primary PDF text extraction using pymupdf4llm.

Converts PDFs to GitHub-compatible markdown with automatic header detection,
table formatting, and layout-aware text extraction. This is the first tier
in the extraction fallback chain.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pymupdf
import pymupdf4llm

from cer_scraper.config.settings import ExtractionSettings
from cer_scraper.extractor.types import ExtractionMethod, ExtractionResult

logger = logging.getLogger(__name__)

# Pattern to strip markdown syntax and whitespace for meaningful char count
_SYNTAX_PATTERN = re.compile(r"[#|*_\-\s\n]")


def try_pymupdf4llm(pdf_path: Path, settings: ExtractionSettings) -> ExtractionResult:
    """Extract text from a PDF using pymupdf4llm markdown conversion.

    Uses pymupdf4llm.to_markdown() which handles machine-generated text,
    tables, and headers in a single call. The ``force_text=True`` parameter
    extracts text even from areas overlapping images.

    Args:
        pdf_path: Path to the PDF file.
        settings: Extraction configuration (table_strategy, etc.).

    Returns:
        ExtractionResult with markdown text and character count on success,
        or with success=False and error message on failure.
    """
    try:
        md_text = pymupdf4llm.to_markdown(
            str(pdf_path),
            pages=None,
            table_strategy=settings.table_strategy,
            page_chunks=False,
            page_separators=True,
            show_progress=False,
            embed_images=False,
            write_images=False,
            force_text=True,
        )

        # Count meaningful characters (strip markdown syntax and whitespace)
        clean_text = _SYNTAX_PATTERN.sub("", md_text)
        char_count = len(clean_text)

        # Get page count from the PDF
        doc = pymupdf.open(str(pdf_path))
        page_count = len(doc)
        doc.close()

        logger.info(
            "pymupdf4llm extracted %d chars from %d pages: %s",
            char_count,
            page_count,
            pdf_path.name,
        )

        return ExtractionResult(
            success=True,
            markdown=md_text,
            method=ExtractionMethod.PYMUPDF4LLM,
            page_count=page_count,
            char_count=char_count,
        )

    except Exception as e:
        logger.warning("pymupdf4llm extraction failed for %s: %s", pdf_path.name, e)
        return ExtractionResult(success=False, error=str(e))
