"""Per-document PDF text extraction service with tiered fallback.

Orchestrates the three-tier extraction pipeline for a single PDF:

1. **pymupdf4llm** -- primary extractor for machine-generated PDFs.
2. **pdfplumber** -- table-focused fallback when pymupdf4llm quality fails.
3. **Tesseract OCR** -- last resort for scanned/image-only PDFs.

Each tier is followed by a quality check. If the check fails, the next tier
is attempted. If all tiers fail, the document is marked as extraction_failed.

Edge cases handled:
- Encrypted PDFs: detected and returned as extraction_failed with "encrypted".
- Oversized PDFs: page_count > max_pages_for_extraction skipped.
- OCR guard: page_count > max_pages_for_ocr skips Tesseract.
"""

from __future__ import annotations

import io
import logging
import re
from pathlib import Path

import pymupdf

from cer_scraper.config.settings import ExtractionSettings
from cer_scraper.extractor.pdfplumber_extractor import try_pdfplumber
from cer_scraper.extractor.pymupdf_extractor import try_pymupdf4llm
from cer_scraper.extractor.quality import passes_ocr_quality_check, passes_quality_check
from cer_scraper.extractor.types import ExtractionMethod, ExtractionResult

logger = logging.getLogger(__name__)

# Re-export shared types so consumers can import from service
__all__ = [
    "ExtractionMethod",
    "ExtractionResult",
    "extract_document",
]

# Pattern to strip markdown syntax and whitespace for meaningful char count
_SYNTAX_PATTERN = re.compile(r"[#|*_\-\s\n]")


def extract_document(
    pdf_path: Path,
    settings: ExtractionSettings,
) -> ExtractionResult:
    """Extract text from a single PDF using tiered fallback.

    Attempts extraction in three tiers, each followed by a quality check.
    Returns the first result that passes quality validation.

    Args:
        pdf_path: Path to the PDF file on disk.
        settings: Extraction configuration (thresholds, OCR settings).

    Returns:
        ExtractionResult with extracted markdown on success, or with
        success=False and an error description on failure.
    """
    # --- Pre-checks: encryption and page count ---

    try:
        doc = pymupdf.open(str(pdf_path))
    except Exception as e:
        logger.error("Cannot open PDF %s: %s", pdf_path.name, e)
        return ExtractionResult(success=False, error=f"cannot_open: {e}")

    if doc.needs_pass:
        doc.close()
        logger.warning("Encrypted PDF skipped: %s", pdf_path.name)
        return ExtractionResult(
            success=False,
            method=ExtractionMethod.FAILED,
            error="encrypted",
        )

    page_count = len(doc)
    doc.close()

    if page_count > settings.max_pages_for_extraction:
        logger.warning(
            "Oversized PDF skipped (%d pages > %d max): %s",
            page_count,
            settings.max_pages_for_extraction,
            pdf_path.name,
        )
        return ExtractionResult(
            success=False,
            method=ExtractionMethod.FAILED,
            page_count=page_count,
            error=f"too_many_pages ({page_count})",
        )

    # --- Tier 1: pymupdf4llm (primary) ---

    logger.info("Tier 1 (pymupdf4llm): attempting extraction for %s", pdf_path.name)
    result = try_pymupdf4llm(pdf_path, settings)
    result.page_count = page_count

    if result.success and passes_quality_check(result, page_count, settings):
        logger.info(
            "Extraction succeeded via pymupdf4llm: %s (%d chars, %d pages)",
            pdf_path.name,
            result.char_count,
            page_count,
        )
        return result

    if result.success:
        logger.warning(
            "pymupdf4llm quality check failed for %s, falling back to pdfplumber",
            pdf_path.name,
        )
    else:
        logger.warning(
            "pymupdf4llm extraction failed for %s: %s, falling back to pdfplumber",
            pdf_path.name,
            result.error,
        )

    # --- Tier 2: pdfplumber (table-focused fallback) ---

    logger.info("Tier 2 (pdfplumber): attempting extraction for %s", pdf_path.name)
    result = try_pdfplumber(pdf_path, settings)
    result.page_count = page_count

    if result.success and passes_quality_check(result, page_count, settings):
        logger.info(
            "Extraction succeeded via pdfplumber: %s (%d chars, %d pages)",
            pdf_path.name,
            result.char_count,
            page_count,
        )
        return result

    if result.success:
        logger.warning(
            "pdfplumber quality check failed for %s, falling back to Tesseract",
            pdf_path.name,
        )
    else:
        logger.warning(
            "pdfplumber extraction failed for %s: %s, falling back to Tesseract",
            pdf_path.name,
            result.error,
        )

    # --- Tier 3: Tesseract OCR (last resort) ---

    if page_count > settings.max_pages_for_ocr:
        logger.warning(
            "Skipping OCR for %d-page document (max %d): %s",
            page_count,
            settings.max_pages_for_ocr,
            pdf_path.name,
        )
    else:
        logger.info(
            "Tier 3 (Tesseract): attempting OCR extraction for %s", pdf_path.name
        )
        result = try_tesseract_direct(pdf_path, settings)
        result.page_count = page_count

        if result.success and passes_ocr_quality_check(result, page_count, settings):
            logger.info(
                "Extraction succeeded via Tesseract OCR: %s (%d chars, %d pages)",
                pdf_path.name,
                result.char_count,
                page_count,
            )
            return result

        if result.success:
            logger.warning(
                "Tesseract OCR quality check failed for %s", pdf_path.name
            )
        else:
            logger.warning(
                "Tesseract OCR failed for %s: %s", pdf_path.name, result.error
            )

    # --- All methods failed ---

    logger.error(
        "All extraction methods failed for %s (%d pages)", pdf_path.name, page_count
    )
    return ExtractionResult(
        success=False,
        method=ExtractionMethod.FAILED,
        page_count=page_count,
        error="all_methods_failed",
    )


def try_tesseract_direct(
    pdf_path: Path,
    settings: ExtractionSettings,
) -> ExtractionResult:
    """Last-resort OCR extraction using PyMuPDF pixmap rendering + pytesseract.

    Renders each PDF page to a high-DPI PNG image using PyMuPDF, then runs
    Tesseract OCR on each image. Pages are joined with markdown page separators.

    Args:
        pdf_path: Path to the PDF file.
        settings: Extraction configuration (ocr_dpi, ocr_language, tesseract_cmd).

    Returns:
        ExtractionResult with OCR text on success, or with success=False
        and error message on failure.
    """
    try:
        import pytesseract
        from PIL import Image

        # Configure tesseract executable path if non-default
        if settings.tesseract_cmd != "tesseract":
            pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd

        doc = pymupdf.open(str(pdf_path))
        all_pages_text: list[str] = []

        for page_num in range(len(doc)):
            page = doc[page_num]
            # Render at configured DPI (default 300) for OCR quality
            pix = page.get_pixmap(dpi=settings.ocr_dpi)
            img_data = pix.tobytes("png")
            img = Image.open(io.BytesIO(img_data))

            text = pytesseract.image_to_string(img, lang=settings.ocr_language)
            if text and text.strip():
                all_pages_text.append(text.strip())

        doc.close()

        md_text = "\n\n---\n\n".join(all_pages_text)

        # Count meaningful characters (strip markdown syntax and whitespace)
        clean_text = _SYNTAX_PATTERN.sub("", md_text)
        char_count = len(clean_text)

        logger.info(
            "Tesseract OCR extracted %d chars from %s", char_count, pdf_path.name
        )

        return ExtractionResult(
            success=True,
            markdown=md_text,
            method=ExtractionMethod.TESSERACT,
            char_count=char_count,
        )

    except Exception as e:
        logger.warning("Tesseract extraction failed for %s: %s", pdf_path.name, e)
        return ExtractionResult(success=False, error=str(e))
