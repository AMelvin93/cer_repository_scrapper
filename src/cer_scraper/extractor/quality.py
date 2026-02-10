"""Quality validation for PDF text extraction results.

Provides garble detection and minimum-content checks to determine whether
extraction output is usable or whether the next fallback method should be
tried. Two validation levels:

- ``passes_quality_check``: Strict checks for pymupdf4llm and pdfplumber output.
- ``passes_ocr_quality_check``: Looser thresholds appropriate for Tesseract OCR.

Quality heuristics:
1. Minimum content: enough characters relative to page count.
2. Garble ratio: non-printable / replacement characters below threshold.
3. Excessive repetition: repeated 3-char sequences indicating font mapping issues.
"""

from __future__ import annotations

import logging
import re
from collections import Counter

from cer_scraper.config.settings import ExtractionSettings
from cer_scraper.extractor.types import ExtractionResult

logger = logging.getLogger(__name__)

# Matches Unicode replacement char, NULL, and non-printable control chars
_GARBLE_PATTERN = re.compile(r"[\ufffd\x00-\x08\x0b\x0c\x0e-\x1f]")


def passes_quality_check(
    result: ExtractionResult,
    page_count: int,
    settings: ExtractionSettings,
) -> bool:
    """Check whether extraction output meets quality standards.

    Three heuristics are applied in order:

    1. **Minimum content**: char_count must exceed
       ``max(100, page_count * min_chars_per_page)``. This catches the user's
       explicit requirement: a 50-page PDF producing fewer than 100 characters
       must trigger fallback.
    2. **Garble ratio**: the fraction of non-printable / replacement characters
       in the markdown must be below ``garble_ratio_threshold`` (default 0.05).
    3. **Excessive repetition**: any non-whitespace 3-character sequence
       appearing more than 200 times in the first 10,000 characters indicates
       a font-mapping error. The threshold is set high enough to avoid false
       positives on natural English text (common trigrams like "the" can
       appear 70+ times in 10K chars of regulatory documents).

    Args:
        result: Extraction result to validate.
        page_count: Number of pages in the source PDF.
        settings: Extraction settings with threshold configuration.

    Returns:
        True if all checks pass, False if any check fails.
    """
    # Empty or whitespace-only markdown always fails
    if not result.markdown or not result.markdown.strip():
        logger.warning("Quality check failed: empty or whitespace-only markdown")
        return False

    # Check 1: Minimum content
    min_chars = max(100, page_count * settings.min_chars_per_page)
    if result.char_count < min_chars:
        logger.warning(
            "Quality check failed (minimum content): %d chars < %d minimum "
            "(%d pages * %d chars/page, floor 100)",
            result.char_count,
            min_chars,
            page_count,
            settings.min_chars_per_page,
        )
        return False

    # Check 2: Garble ratio
    garble_chars = len(_GARBLE_PATTERN.findall(result.markdown))
    total_chars = len(result.markdown)
    if total_chars > 0:
        garble_ratio = garble_chars / total_chars
        if garble_ratio > settings.garble_ratio_threshold:
            logger.warning(
                "Quality check failed (garble ratio): %.3f > %.3f threshold "
                "(%d garbled chars in %d total)",
                garble_ratio,
                settings.garble_ratio_threshold,
                garble_chars,
                total_chars,
            )
            return False

    # Check 3: Excessive repetition (font mapping issue)
    # Font-mapping errors produce sequences like "???..." or "\x00\x00\x00..."
    # repeating hundreds of times. Natural English text has common trigrams
    # like "the" at ~70 per 10K chars, so the threshold must be well above
    # that. Only non-whitespace-containing trigrams are checked since space-
    # containing trigrams are ubiquitous in all text.
    sample = result.markdown[:10_000]
    if len(sample) >= 3:
        trigrams = [sample[i : i + 3] for i in range(len(sample) - 2)]
        trigram_counts = Counter(trigrams)
        for trigram, count in trigram_counts.most_common(10):
            if count > 200 and re.search(r"\S", trigram):
                logger.warning(
                    "Quality check failed (excessive repetition): "
                    "trigram %r appears %d times in first 10K chars",
                    trigram,
                    count,
                )
                return False

    return True


def passes_ocr_quality_check(
    result: ExtractionResult,
    page_count: int,
    settings: ExtractionSettings,
) -> bool:
    """Check whether OCR extraction output meets minimum quality standards.

    Uses looser thresholds than ``passes_quality_check`` because Tesseract
    OCR output is inherently noisier. The repetition check is skipped because
    OCR does not produce font-mapping repetition artifacts.

    Checks applied:
    1. **Minimum content**: char_count must exceed
       ``max(50, page_count * min_chars_per_page_ocr)``.
    2. **Garble ratio**: non-printable chars below
       ``ocr_garble_ratio_threshold`` (default 0.10).

    Args:
        result: OCR extraction result to validate.
        page_count: Number of pages in the source PDF.
        settings: Extraction settings with OCR threshold configuration.

    Returns:
        True if all checks pass, False if any check fails.
    """
    # Empty or whitespace-only markdown always fails
    if not result.markdown or not result.markdown.strip():
        logger.warning("OCR quality check failed: empty or whitespace-only markdown")
        return False

    # Check 1: Minimum content (looser threshold)
    min_chars = max(50, page_count * settings.min_chars_per_page_ocr)
    if result.char_count < min_chars:
        logger.warning(
            "OCR quality check failed (minimum content): %d chars < %d minimum "
            "(%d pages * %d chars/page, floor 50)",
            result.char_count,
            min_chars,
            page_count,
            settings.min_chars_per_page_ocr,
        )
        return False

    # Check 2: Garble ratio (looser threshold)
    garble_chars = len(_GARBLE_PATTERN.findall(result.markdown))
    total_chars = len(result.markdown)
    if total_chars > 0:
        garble_ratio = garble_chars / total_chars
        if garble_ratio > settings.ocr_garble_ratio_threshold:
            logger.warning(
                "OCR quality check failed (garble ratio): %.3f > %.3f threshold "
                "(%d garbled chars in %d total)",
                garble_ratio,
                settings.ocr_garble_ratio_threshold,
                garble_chars,
                total_chars,
            )
            return False

    # Repetition check intentionally skipped for OCR output
    return True
