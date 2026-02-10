"""Shared types for the extraction pipeline.

Defines ExtractionResult and ExtractionMethod used across all extractor
modules, quality checks, and the orchestration service.
"""

from dataclasses import dataclass, field
from enum import Enum


class ExtractionMethod(Enum):
    """Method used to extract text from a PDF."""

    PYMUPDF4LLM = "pymupdf4llm"
    PDFPLUMBER = "pdfplumber"
    TESSERACT = "tesseract"
    FAILED = "failed"


@dataclass
class ExtractionResult:
    """Result of a single PDF text extraction attempt.

    Attributes:
        success: Whether extraction produced usable text.
        markdown: Extracted text in markdown format.
        method: Which extraction method produced this result.
        page_count: Number of pages in the source PDF.
        char_count: Meaningful character count (excluding whitespace/syntax).
        error: Error description if extraction failed.
    """

    success: bool
    markdown: str = ""
    method: ExtractionMethod = field(default=ExtractionMethod.FAILED)
    page_count: int = 0
    char_count: int = 0
    error: str | None = None
