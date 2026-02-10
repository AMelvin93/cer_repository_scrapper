"""Markdown output writer with YAML frontmatter for extracted PDF text.

Handles the filesystem side of extraction: writing markdown files alongside
their source PDFs with structured YAML frontmatter containing extraction
metadata. Provides idempotency via ``should_extract`` -- if a markdown file
already exists and has content, the document is skipped on re-run.

Public API:
    should_extract(md_path)  -> bool
    write_markdown_file(...)  -> None
"""

from __future__ import annotations

import datetime
import logging
from pathlib import Path

import frontmatter

logger = logging.getLogger(__name__)


def should_extract(md_path: Path) -> bool:
    """Check whether a markdown extraction file needs to be created.

    Returns False (skip) if *md_path* already exists and has content.
    Returns True (proceed) if the file is missing or empty.

    This provides idempotency: re-running extraction does not overwrite
    previously extracted markdown files.

    Args:
        md_path: Target path for the markdown output file.

    Returns:
        True if extraction should proceed, False to skip.
    """
    if md_path.exists() and md_path.stat().st_size > 0:
        return False
    return True


def write_markdown_file(
    md_path: Path,
    markdown_content: str,
    method: str,
    page_count: int,
    char_count: int,
    pdf_filename: str,
) -> None:
    """Write extracted markdown to disk with YAML frontmatter metadata.

    Creates a markdown file alongside the source PDF containing the
    extracted text plus structured YAML frontmatter with:

    - ``source_pdf``: Original PDF filename
    - ``extraction_method``: Which extractor produced this text
    - ``extraction_date``: UTC ISO-8601 timestamp
    - ``page_count``: Number of pages in the source PDF
    - ``char_count``: Meaningful character count (excludes syntax/whitespace)

    Args:
        md_path: Destination path for the markdown file.
        markdown_content: Extracted text in markdown format.
        method: Extraction method name (e.g. "pymupdf4llm").
        page_count: Number of pages in the source PDF.
        char_count: Meaningful character count.
        pdf_filename: Source PDF filename (not full path).
    """
    # Build frontmatter post with metadata
    post = frontmatter.Post(markdown_content)
    post.metadata["source_pdf"] = pdf_filename
    post.metadata["extraction_method"] = method
    # Use fully qualified datetime.datetime to avoid Pydantic v2 shadowing bug
    post.metadata["extraction_date"] = (
        datetime.datetime.now(datetime.UTC).isoformat()
    )
    post.metadata["page_count"] = page_count
    post.metadata["char_count"] = char_count

    # Ensure parent directory exists
    md_path.parent.mkdir(parents=True, exist_ok=True)

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(frontmatter.dumps(post))

    logger.info(
        "Wrote extraction to %s (%d chars, %d pages)",
        md_path.name,
        char_count,
        page_count,
    )
