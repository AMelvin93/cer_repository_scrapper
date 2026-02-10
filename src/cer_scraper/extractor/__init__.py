"""PDF text extraction package for CER REGDOCS filings.

Provides multi-method text extraction from downloaded PDFs using:
    - pymupdf4llm (primary: fast native text with markdown formatting)
    - pdfplumber (fallback: alternative native text extraction)
    - Tesseract OCR (last resort: for scanned/image-only documents)

Orchestration and extraction logic will be added in Plans 02 and 03.
"""
