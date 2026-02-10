# Phase 4: PDF Text Extraction - Research

**Researched:** 2026-02-09
**Domain:** PDF text extraction, OCR, markdown conversion
**Confidence:** HIGH

## Summary

This phase extracts text from downloaded CER filing PDFs and produces markdown files for LLM analysis. The key discovery is that **pymupdf4llm** (v0.2.9) is a purpose-built library that already handles the entire extraction pipeline: it converts PDFs to GitHub-compatible markdown with header detection, table formatting, and built-in OCR via Tesseract. Its OCR subsystem automatically detects scanned pages on a per-page basis and applies either full-page OCR or targeted span-level repair for garbled characters -- directly addressing the user's mixed-document and fallback requirements.

The user's CONTEXT.md specifies a three-tier fallback: PyMuPDF -> pdfplumber -> Tesseract. pymupdf4llm already uses PyMuPDF internally and has built-in OCR. pdfplumber remains valuable as a dedicated fallback for complex table-heavy documents where pymupdf4llm's table detection produces garbled or malformed tables (a known limitation with merged cells and gridless tables). The architecture should be: **pymupdf4llm as primary** (handles text + tables + automatic OCR for scanned pages), **pdfplumber as table-focused fallback** (when garble detection triggers on table-heavy documents), and **direct pytesseract as last resort** (when both structured extractors fail entirely).

**Primary recommendation:** Use `pymupdf4llm.to_markdown()` with `use_ocr=True` as the primary extraction method. It handles machine-generated text, tables, and scanned pages in a single call. Fall back to pdfplumber only when the output quality check detects garbled tables. Use direct Tesseract OCR via PyMuPDF's pixmap rendering only as a last-resort fallback.

<user_constraints>

## User Constraints (from CONTEXT.md)

### Locked Decisions
- **Output format:** Convert entire PDF to markdown (.md file per PDF). Best effort structure detection: headings, lists, tables where detectable; fall back to plain paragraphs. Single .md file per PDF with page breaks marked by separators. Tables always rendered as pipe-delimited markdown tables.
- **Storage layout:** .md files stored alongside PDFs in same filing directory. Extraction metadata in BOTH database (new Document columns) AND YAML frontmatter in .md file. Full extracted text in database TEXT column. Skip extraction if .md already exists with content.
- **Fallback strategy:** Per-document fallback (not per-page). If all three methods fail: mark `extraction_failed`, log warning, continue pipeline.
- **Mixed document handling:** Detect text-layer vs scanned pages before extraction. Process text pages with PyMuPDF/pdfplumber, scanned pages with Tesseract OCR. Merge into single .md.
- **Encrypted PDFs:** Skip entirely, mark `extraction_failed` with reason `encrypted`.
- **Language:** Tesseract English only. French sections extract best-effort.

### Claude's Discretion
- Garble detection heuristic (what triggers PyMuPDF -> pdfplumber fallback)
- OCR quality validation thresholds (what constitutes acceptable vs. failed Tesseract output)
- Maximum PDF size/page count guard for extraction (if needed to prevent hour-long OCR runs)

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope.

</user_constraints>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pymupdf4llm | 0.2.9 | Primary PDF-to-markdown extraction | Purpose-built for LLM consumption; handles text, tables, headers, and has built-in OCR. Used by PyMuPDF maintainers. |
| PyMuPDF (pymupdf) | 1.25.x+ | PDF rendering, page analysis, pixmap generation | Installed as pymupdf4llm dependency. Fastest Python PDF library. Provides encryption detection, image extraction, page rendering. |
| pdfplumber | 0.11.9 | Table-focused fallback extraction | Superior table detection for complex/merged-cell tables. Built on pdfminer.six. Industry standard for tabular PDF data. |
| python-frontmatter | 1.1.0 | YAML frontmatter in markdown files | De facto standard for reading/writing YAML frontmatter in .md files. |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pymupdf-layout | latest | Enhanced layout analysis for pymupdf4llm | Install via `pymupdf4llm[layout]` extra. Required for automatic OCR heuristics. |
| tabulate | latest | Pandas DataFrame to markdown tables | Required by pandas `.to_markdown()` for pdfplumber fallback path. |
| pandas | latest | Table data manipulation | Convert pdfplumber table arrays to markdown via `.to_markdown(index=False)`. |

### External System Dependencies
| Tool | Version | Purpose | Installation |
|------|---------|---------|-------------|
| Tesseract OCR | 5.3.x | OCR engine for scanned pages | Windows: UB-Mannheim installer from https://digi.bib.uni-mannheim.de/tesseract/ -- must be on PATH or configured via `pytesseract.pytesseract.tesseract_cmd` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| pymupdf4llm | Raw PyMuPDF + custom markdown | pymupdf4llm already does the markdown conversion with header/table detection -- no reason to hand-roll |
| pdfplumber | camelot-py | camelot requires ghostscript and has more complex setup; pdfplumber is lighter and sufficient |
| pdf2image + pytesseract | PyMuPDF pixmap + Tesseract | PyMuPDF can render pages to images natively via `page.get_pixmap(dpi=300)` -- no need for poppler/pdf2image dependency |
| python-frontmatter | Raw PyYAML | python-frontmatter provides `.dump()` and `.load()` that handle the `---` separators automatically |

### Installation
```bash
uv add pymupdf4llm[layout] pdfplumber python-frontmatter pandas tabulate
```

**Note:** Tesseract OCR must be installed separately as a system dependency. On Windows, download and run the UB-Mannheim installer. The installer adds Tesseract to PATH by default; if not, configure the path in settings.

## Architecture Patterns

### Recommended Project Structure
```
src/cer_scraper/
├── extractor/
│   ├── __init__.py
│   ├── service.py           # Main extraction orchestrator (per-document)
│   ├── pymupdf_extractor.py # pymupdf4llm-based primary extraction
│   ├── pdfplumber_extractor.py  # pdfplumber-based table fallback
│   ├── quality.py           # Garble detection and quality validation
│   └── markdown.py          # Markdown output formatting + frontmatter
├── db/
│   ├── models.py            # (extend Document model with extraction columns)
│   └── state.py             # (add get_filings_for_extraction query)
└── config/
    └── settings.py          # (add ExtractionSettings section)
```

### Pattern 1: Tiered Extraction with Quality Gate

**What:** Try pymupdf4llm first. If quality check fails, try pdfplumber. If that fails, try direct Tesseract. If all fail, mark as `extraction_failed`.

**When to use:** Every document extraction.

**Example:**
```python
# Source: Architecture decision based on CONTEXT.md fallback strategy
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

class ExtractionMethod(Enum):
    PYMUPDF4LLM = "pymupdf4llm"
    PDFPLUMBER = "pdfplumber"
    TESSERACT = "tesseract"
    FAILED = "failed"

@dataclass
class ExtractionResult:
    success: bool
    markdown: str = ""
    method: ExtractionMethod = ExtractionMethod.FAILED
    page_count: int = 0
    char_count: int = 0
    error: str | None = None

def extract_document(pdf_path: Path, settings) -> ExtractionResult:
    """Extract text from a single PDF using tiered fallback."""
    # 1. Check for encryption
    doc = pymupdf.open(str(pdf_path))
    if doc.needs_pass:
        doc.close()
        return ExtractionResult(
            success=False,
            method=ExtractionMethod.FAILED,
            error="encrypted",
        )
    page_count = len(doc)
    doc.close()

    # 2. Guard: skip very large documents
    if page_count > settings.max_pages_for_extraction:
        return ExtractionResult(
            success=False,
            method=ExtractionMethod.FAILED,
            error=f"too_many_pages ({page_count})",
        )

    # 3. Try pymupdf4llm (handles text + tables + OCR automatically)
    result = try_pymupdf4llm(pdf_path, settings)
    if result.success and passes_quality_check(result, page_count):
        return result

    # 4. Fallback: pdfplumber (better for complex tables)
    result = try_pdfplumber(pdf_path, settings)
    if result.success and passes_quality_check(result, page_count):
        return result

    # 5. Last resort: direct Tesseract via PyMuPDF pixmap
    result = try_tesseract_direct(pdf_path, settings)
    if result.success and passes_quality_check(result, page_count):
        return result

    # 6. All methods failed
    return ExtractionResult(
        success=False,
        method=ExtractionMethod.FAILED,
        error="all_methods_failed",
    )
```

### Pattern 2: pymupdf4llm Primary Extraction

**What:** Use pymupdf4llm.to_markdown() with layout mode and OCR enabled.

**When to use:** First extraction attempt for every document.

**Example:**
```python
# Source: https://pymupdf.readthedocs.io/en/latest/pymupdf4llm/api.html
import pymupdf4llm

def try_pymupdf4llm(pdf_path: Path, settings) -> ExtractionResult:
    """Primary extraction using pymupdf4llm with built-in OCR."""
    try:
        # Import layout module to activate layout-aware extraction
        import pymupdf.layout  # noqa: F401 -- side-effect import

        md_text = pymupdf4llm.to_markdown(
            str(pdf_path),
            pages=None,              # All pages
            use_ocr=True,            # Auto-detect and OCR scanned pages
            ocr_language="eng",      # English only per user decision
            table_strategy="lines_strict",  # Best default for styled tables
            page_chunks=False,       # Single string output
            show_progress=False,
            embed_images=False,      # No image embedding
            write_images=False,      # No image file creation
            force_text=True,         # Extract text from image-overlapping areas
        )

        # Count characters (excluding whitespace/markdown syntax)
        import re
        clean_text = re.sub(r'[#|*_\-\s\n]', '', md_text)
        char_count = len(clean_text)

        return ExtractionResult(
            success=True,
            markdown=md_text,
            method=ExtractionMethod.PYMUPDF4LLM,
            char_count=char_count,
        )

    except Exception as e:
        logger.warning("pymupdf4llm extraction failed for %s: %s", pdf_path, e)
        return ExtractionResult(success=False, error=str(e))
```

### Pattern 3: pdfplumber Table-Focused Fallback

**What:** Use pdfplumber to extract text and tables separately, combine into markdown.

**When to use:** When pymupdf4llm quality check fails (garbled tables detected).

**Example:**
```python
# Source: https://github.com/jsvine/pdfplumber/discussions/1026
import pdfplumber
import pandas as pd
from pdfplumber.utils import get_bbox_overlap, obj_to_bbox

def try_pdfplumber(pdf_path: Path, settings) -> ExtractionResult:
    """Fallback extraction using pdfplumber for better table handling."""
    try:
        all_pages_md = []

        with pdfplumber.open(str(pdf_path)) as pdf:
            for page_num, page in enumerate(pdf.pages):
                page_parts = []

                # Find tables on this page
                tables = page.find_tables()

                if tables:
                    # Filter text outside table regions
                    filtered_page = page
                    for table in tables:
                        filtered_page = filtered_page.filter(
                            lambda obj: get_bbox_overlap(
                                obj_to_bbox(obj), table.bbox
                            ) is None
                        )

                    # Extract non-table text
                    text = filtered_page.extract_text(layout=True)
                    if text and text.strip():
                        page_parts.append(text.strip())

                    # Extract tables as markdown
                    for table in tables:
                        table_data = table.extract()
                        if table_data and len(table_data) > 1:
                            df = pd.DataFrame(table_data[1:], columns=table_data[0])
                            page_parts.append(df.to_markdown(index=False))
                else:
                    text = page.extract_text(layout=True)
                    if text and text.strip():
                        page_parts.append(text.strip())

                if page_parts:
                    all_pages_md.append("\n\n".join(page_parts))

        md_text = "\n\n---\n\n".join(all_pages_md)

        import re
        clean_text = re.sub(r'[#|*_\-\s\n]', '', md_text)

        return ExtractionResult(
            success=True,
            markdown=md_text,
            method=ExtractionMethod.PDFPLUMBER,
            char_count=len(clean_text),
        )

    except Exception as e:
        logger.warning("pdfplumber extraction failed for %s: %s", pdf_path, e)
        return ExtractionResult(success=False, error=str(e))
```

### Pattern 4: Direct Tesseract OCR via PyMuPDF Pixmap

**What:** Render each page to a high-DPI image using PyMuPDF, then OCR with Tesseract.

**When to use:** Last resort when both pymupdf4llm and pdfplumber fail (typically fully scanned documents where pymupdf4llm OCR also failed).

**Example:**
```python
# Source: https://pymupdf.readthedocs.io/en/latest/recipes-ocr.html
import pymupdf
import pytesseract
from PIL import Image
import io

def try_tesseract_direct(pdf_path: Path, settings) -> ExtractionResult:
    """Last-resort OCR using PyMuPDF pixmap + pytesseract."""
    try:
        doc = pymupdf.open(str(pdf_path))
        all_pages_text = []

        for page_num in range(len(doc)):
            page = doc[page_num]
            # Render at 300 DPI for OCR quality
            pix = page.get_pixmap(dpi=300)
            img_data = pix.tobytes("png")
            img = Image.open(io.BytesIO(img_data))

            text = pytesseract.image_to_string(img, lang="eng")
            if text and text.strip():
                all_pages_text.append(text.strip())

        doc.close()

        md_text = "\n\n---\n\n".join(all_pages_text)
        import re
        clean_text = re.sub(r'[#|*_\-\s\n]', '', md_text)

        return ExtractionResult(
            success=True,
            markdown=md_text,
            method=ExtractionMethod.TESSERACT,
            char_count=len(clean_text),
        )

    except Exception as e:
        logger.warning("Tesseract extraction failed for %s: %s", pdf_path, e)
        return ExtractionResult(success=False, error=str(e))
```

### Pattern 5: Markdown Output with YAML Frontmatter

**What:** Write extraction results as markdown with metadata frontmatter.

**When to use:** After successful extraction, when persisting the .md file.

**Example:**
```python
# Source: https://python-frontmatter.readthedocs.io/
import frontmatter
import datetime

def write_markdown_file(
    md_path: Path,
    markdown_content: str,
    method: str,
    page_count: int,
    char_count: int,
    pdf_filename: str,
) -> None:
    """Write extracted markdown with YAML frontmatter metadata."""
    post = frontmatter.Post(markdown_content)
    post.metadata = {
        "source_pdf": pdf_filename,
        "extraction_method": method,
        "extraction_date": datetime.datetime.now(datetime.UTC).isoformat(),
        "page_count": page_count,
        "char_count": char_count,
    }
    md_path.parent.mkdir(parents=True, exist_ok=True)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(frontmatter.dumps(post))
```

### Pattern 6: Skip-If-Exists Idempotency

**What:** Check if .md file already exists before extraction.

**When to use:** At the start of every document extraction to support re-runs.

**Example:**
```python
def should_extract(md_path: Path) -> bool:
    """Check if extraction is needed (skip if .md exists with content)."""
    if md_path.exists() and md_path.stat().st_size > 0:
        return False
    return True
```

### Anti-Patterns to Avoid
- **Per-page fallback:** CONTEXT.md explicitly says per-document fallback. Do NOT switch methods mid-document (except for pymupdf4llm's built-in per-page OCR which is internal to the first tier).
- **Storing only text, not markdown:** The user explicitly wants markdown with structure (headings, tables, lists) for LLM input. Do not strip formatting.
- **Using pdf2image + poppler:** PyMuPDF renders pages to images natively via `page.get_pixmap()`. No need for the pdf2image/poppler dependency chain.
- **Importing pymupdf.layout after pymupdf4llm:** The layout module MUST be imported BEFORE pymupdf4llm to activate enhanced analysis. Use `import pymupdf.layout` as the first import.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| PDF to markdown | Custom text extraction + markdown formatting | `pymupdf4llm.to_markdown()` | Handles headers, tables, bold/italic, code blocks, multi-column layout. Well-tested on thousands of PDFs. |
| Table detection | Custom rectangle/line analysis | pymupdf4llm's built-in table finder or pdfplumber's `find_tables()` | Table boundary detection is deceptively complex (merged cells, invisible borders, text-aligned columns). |
| Scanned page detection | Custom image-coverage heuristic | pymupdf4llm's `should_ocr_page()` internal heuristic | Uses multi-factor analysis: text area, readability, image coverage, vector graphics. Better than a simple threshold. |
| PDF page to image | pdf2image + poppler | `page.get_pixmap(dpi=300)` from PyMuPDF | PyMuPDF renders pages natively without external dependencies. |
| YAML frontmatter | Manual `---\n` string concatenation | `python-frontmatter` library | Handles edge cases (YAML escaping, multi-line values, encoding). |
| Garbled character detection | Custom regex for bad characters | pymupdf4llm's built-in U+FFFD replacement character detection | The library already checks for Unicode replacement characters and triggers repair. |

## Common Pitfalls

### Pitfall 1: pymupdf.layout Import Order
**What goes wrong:** pymupdf4llm produces basic markdown without layout analysis or OCR heuristics.
**Why it happens:** `pymupdf.layout` must be imported BEFORE `pymupdf4llm` to activate layout mode. If imported after (or not at all), pymupdf4llm falls back to legacy mode without OCR support.
**How to avoid:** Always import in this order:
```python
import pymupdf.layout  # noqa: F401 -- activates layout mode
import pymupdf4llm
```
**Warning signs:** OCR never triggers even for obviously scanned pages; output lacks header detection.

### Pitfall 2: Tesseract Not on PATH (Windows)
**What goes wrong:** OCR silently fails or raises FileNotFoundError.
**Why it happens:** Tesseract is a system binary, not a Python package. On Windows, the UB-Mannheim installer may or may not add it to PATH.
**How to avoid:** Add a settings field `tesseract_cmd` that defaults to `"tesseract"` (assumes PATH) but can be overridden to the full path like `C:\Program Files\Tesseract-OCR\tesseract.exe`. Check at startup that Tesseract is available.
**Warning signs:** `FileNotFoundError: [WinError 2] The system cannot find the file specified`.

### Pitfall 3: Enormous PDFs Causing OOM or Hour-Long OCR
**What goes wrong:** A 500-page scanned PDF takes hours to OCR or exhausts memory.
**Why it happens:** OCR at 300 DPI generates ~25MB per page image. 500 pages = ~12GB of image data processed sequentially.
**How to avoid:** Set a configurable `max_pages_for_extraction` guard (recommend 300 pages). For OCR specifically, set a lower `max_pages_for_ocr` (recommend 100 pages). Log a warning and mark as `extraction_failed` with reason `too_many_pages` for documents exceeding the limit.
**Warning signs:** Extraction takes >10 minutes for a single document.

### Pitfall 4: SQLite TEXT Column Size for Large Documents
**What goes wrong:** Storing full extracted text in SQLite for a 200-page document works fine -- SQLite TEXT columns handle up to 1GB. But queries on large TEXT columns are slow.
**Why it happens:** SQLite handles large text, but `LIKE` queries or full-text operations on multi-MB text fields are inefficient.
**How to avoid:** Store the full text in the database as specified by the user (enables SQL queries), but keep in mind this is for lookup/basic filtering, not full-text search. If search becomes needed later, consider SQLite FTS5 (Phase 7+ concern, not this phase).
**Warning signs:** N/A for this phase.

### Pitfall 5: pdfplumber Table Bounding Box Exceeds Page
**What goes wrong:** `pdfplumber.filter()` raises errors when table bbox extends beyond page boundaries.
**Why it happens:** Some PDFs have tables whose detected boundaries extend slightly past page edges.
**How to avoid:** Clamp table bbox coordinates to page boundaries before filtering:
```python
page_bbox = page.bbox  # (x0, y0, x1, y1)
clamped = (
    max(table.bbox[0], page_bbox[0]),
    max(table.bbox[1], page_bbox[1]),
    min(table.bbox[2], page_bbox[2]),
    min(table.bbox[3], page_bbox[3]),
)
```
**Warning signs:** `ValueError` or `IndexError` during pdfplumber table extraction.

### Pitfall 6: pymupdf4llm Duplicate Table Output
**What goes wrong:** Tables appear twice in the markdown -- once as raw text in reading order, and once as a formatted markdown table at the bottom of the page.
**Why it happens:** Known issue in pymupdf4llm where table text is included both inline and as a formatted table block.
**How to avoid:** Post-process the output: if a formatted table appears at the end of a page section, check for duplicate text above it. Alternatively, use `page_chunks=True` to get structured output where tables are separate from text, then manually combine. Monitor pymupdf4llm releases for fixes.
**Warning signs:** Tables appear twice with slightly different formatting in the output.

## Code Examples

### Complete Extraction Orchestrator (Filing-Level)
```python
# Pattern: mirrors Phase 3's filing-level download orchestrator
def extract_filing_documents(
    session: Session,
    filing: Filing,
    settings: ExtractionSettings,
) -> bool:
    """Extract text from all documents in a filing.

    Returns True if at least one document was successfully extracted.
    """
    success_count = 0
    fail_count = 0

    for doc in filing.documents:
        if doc.download_status != "success":
            continue  # Skip documents that weren't downloaded

        pdf_path = Path(doc.local_path)
        md_path = pdf_path.with_suffix(".md")

        # Idempotency: skip if already extracted
        if not should_extract(md_path):
            logger.info("Skipping already-extracted %s", md_path.name)
            success_count += 1
            continue

        result = extract_document(pdf_path, settings)

        if result.success:
            write_markdown_file(
                md_path=md_path,
                markdown_content=result.markdown,
                method=result.method.value,
                page_count=result.page_count,
                char_count=result.char_count,
                pdf_filename=pdf_path.name,
            )
            # Update Document record
            doc.extraction_method = result.method.value
            doc.extraction_status = "success"
            doc.extracted_text = result.markdown
            doc.char_count = result.char_count
            session.commit()
            success_count += 1
        else:
            doc.extraction_status = "failed"
            doc.extraction_error = result.error
            session.commit()
            fail_count += 1
            logger.warning(
                "Extraction failed for %s: %s", pdf_path.name, result.error
            )

    # Filing-level status: success if ANY document extracted
    has_extractions = success_count > 0
    return has_extractions
```

### Quality Check / Garble Detection (Claude's Discretion)
```python
def passes_quality_check(result: ExtractionResult, page_count: int) -> bool:
    """Validate extraction quality. Returns False if output appears garbled.

    Heuristics (Claude's discretion):
    1. Minimum characters per page: at least 50 chars per page on average
       (a 50-page PDF with <100 chars total = 2 chars/page = clearly failed)
    2. Garble ratio: if >30% of characters are non-ASCII-printable (excluding
       common Unicode like accented French characters), likely garbled
    3. Repetition ratio: if the same short sequence repeats >50 times,
       likely a font mapping issue
    """
    if not result.markdown or not result.markdown.strip():
        return False

    # Heuristic 1: Minimum content threshold
    # User requirement: 50-page PDF with <100 chars triggers warning
    min_chars = max(100, page_count * 50)
    if result.char_count < min_chars:
        logger.warning(
            "Quality check failed: %d chars for %d pages (min %d)",
            result.char_count, page_count, min_chars,
        )
        return False

    # Heuristic 2: Garble ratio (non-printable / replacement characters)
    import re
    # Count Unicode replacement chars (U+FFFD) and control characters
    garble_chars = len(re.findall(r'[\ufffd\x00-\x08\x0b\x0c\x0e-\x1f]', result.markdown))
    total_chars = len(result.markdown)
    if total_chars > 0 and garble_chars / total_chars > 0.05:
        logger.warning(
            "Quality check failed: garble ratio %.2f (threshold 0.05)",
            garble_chars / total_chars,
        )
        return False

    # Heuristic 3: Excessive repetition (font mapping failure)
    # Look for any 3-char sequence repeated >50 times
    text_sample = result.markdown[:10000]  # Check first 10K chars
    for i in range(0, min(len(text_sample) - 3, 500), 1):
        pattern = re.escape(text_sample[i:i+3])
        if len(re.findall(pattern, text_sample)) > 50:
            logger.warning("Quality check failed: excessive repetition detected")
            return False

    return True
```

### OCR Quality Validation (Claude's Discretion)
```python
def passes_ocr_quality_check(result: ExtractionResult, page_count: int) -> bool:
    """Validate OCR output quality. Looser thresholds than text extraction.

    OCR thresholds (Claude's discretion):
    - Minimum 20 chars per page (OCR on sparse documents may legitimately
      produce less text than machine-generated PDFs)
    - Garble ratio threshold: 10% (OCR naturally produces more errors)
    - Skip repetition check (OCR doesn't produce font-mapping repetition)
    """
    if not result.markdown or not result.markdown.strip():
        return False

    min_chars = max(50, page_count * 20)
    if result.char_count < min_chars:
        return False

    import re
    garble_chars = len(re.findall(r'[\ufffd\x00-\x08\x0b\x0c\x0e-\x1f]', result.markdown))
    total_chars = len(result.markdown)
    if total_chars > 0 and garble_chars / total_chars > 0.10:
        return False

    return True
```

### Document Model Extension
```python
# New columns to add to Document model
class Document(Base):
    # ... existing columns ...

    # Phase 4: extraction tracking
    extraction_status: Mapped[Optional[str]] = mapped_column(
        String(20), default=None
    )  # "success", "failed", None (not attempted)
    extraction_method: Mapped[Optional[str]] = mapped_column(
        String(20), default=None
    )  # "pymupdf4llm", "pdfplumber", "tesseract"
    extraction_error: Mapped[Optional[str]] = mapped_column(
        String(500), default=None
    )  # "encrypted", "too_many_pages", "all_methods_failed"
    extracted_text: Mapped[Optional[str]] = mapped_column(
        Text, default=None
    )  # Full markdown text for SQL queries
    char_count: Mapped[Optional[int]] = mapped_column(default=None)
    page_count: Mapped[Optional[int]] = mapped_column(default=None)
```

### Extraction Settings Extension
```python
# Add to PipelineSettings or create ExtractionSettings
class ExtractionSettings(BaseSettings):
    """PDF text extraction configuration."""

    # Page/size guards (Claude's discretion)
    max_pages_for_extraction: int = 300
    max_pages_for_ocr: int = 100

    # Quality thresholds
    min_chars_per_page: int = 50
    garble_ratio_threshold: float = 0.05
    ocr_garble_ratio_threshold: float = 0.10

    # Tesseract configuration
    tesseract_cmd: str = "tesseract"  # Override if not on PATH
    ocr_language: str = "eng"
    ocr_dpi: int = 300

    # pymupdf4llm options
    table_strategy: str = "lines_strict"

    model_config = SettingsConfigDict(
        yaml_file=str(_CONFIG_DIR / "extraction.yaml"),
        env_prefix="EXTRACTION_",
    )
```

### State Store: Get Filings for Extraction
```python
def get_filings_for_extraction(
    session: Session, max_retries: int = 3
) -> list[Filing]:
    """Return filings that need text extraction.

    A filing needs extraction if:
        - status_downloaded == "success"
        - status_extracted != "success"
        - retry_count < max_retries
    """
    stmt = (
        select(Filing)
        .where(
            Filing.status_downloaded == "success",
            Filing.status_extracted != "success",
            Filing.retry_count < max_retries,
        )
        .options(selectinload(Filing.documents))
    )
    return list(session.scalars(stmt).all())
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| PyMuPDF + manual markdown | pymupdf4llm `to_markdown()` | 2024 (v0.0.1+) | Single function call replaces hundreds of lines of custom extraction code |
| pdf2image + poppler + pytesseract | pymupdf4llm with `use_ocr=True` + built-in Tesseract | 2024 (v0.2.0) | Eliminates poppler system dependency; automatic per-page OCR detection |
| OpenCV required for OCR heuristics | NumPy-based image analysis | Jan 2026 (v0.2.9) | Removes opencv-python dependency for OCR decision-making |
| Manual garble detection regex | pymupdf4llm's U+FFFD detection + repair_blocks | 2024 (v0.2.0) | Library handles targeted span-level OCR repair for garbled characters |

**Deprecated/outdated:**
- **pdf2image + poppler:** Not needed. PyMuPDF renders pages to images natively.
- **opencv-python for pymupdf4llm:** Removed in v0.2.9. NumPy handles image quality analysis now.
- **Legacy PyMuPDF text extraction (page.get_text()):** Still works but pymupdf4llm adds table/header/structure detection on top.

## Open Questions

1. **pymupdf4llm duplicate table output**
   - What we know: There is a known issue where tables may appear twice in output (raw text + formatted table). The `page_chunks=True` mode separates them.
   - What's unclear: Whether v0.2.9 has fixed this, and whether `page_chunks=True` with manual reassembly is worth the complexity.
   - Recommendation: Start with `page_chunks=False`. If duplicate tables are observed during testing, add a post-processing dedup step or switch to `page_chunks=True`.

2. **pymupdf4llm layout mode onnxruntime size**
   - What we know: The `pymupdf-layout` extra pulls in `onnxruntime` which is a large dependency (~200MB).
   - What's unclear: Whether layout mode provides sufficient benefit over legacy mode for CER regulatory PDFs specifically.
   - Recommendation: Install with layout mode. The improved table/header detection and automatic OCR heuristics justify the dependency size for this use case.

3. **Tesseract installation automation on Windows**
   - What we know: Tesseract must be installed separately via the UB-Mannheim installer.
   - What's unclear: Whether the project should include automated setup scripts or just document it.
   - Recommendation: Document in README. Check for Tesseract at startup and log a clear error message if not found. Add `tesseract_cmd` to settings for path override.

## Sources

### Primary (HIGH confidence)
- [pymupdf4llm API documentation](https://pymupdf.readthedocs.io/en/latest/pymupdf4llm/api.html) - Full API reference for `to_markdown()`, all parameters verified
- [pymupdf4llm CHANGES.md](https://github.com/pymupdf/pymupdf4llm/blob/main/CHANGES.md) - Version history, v0.2.9 confirmed current, OpenCV dependency removed
- [PyMuPDF OCR recipes](https://pymupdf.readthedocs.io/en/latest/recipes-ocr.html) - Tesseract integration, pixmap OCR, GlyphlessFont detection
- [pymupdf4llm OCR subsystem (DeepWiki)](https://deepwiki.com/pymupdf/pymupdf4llm/7-examples-and-use-cases) - should_ocr_page internals, thresholds, repair_blocks
- [pdfplumber GitHub](https://github.com/jsvine/pdfplumber) - API overview, table extraction, version 0.11.9
- [pdfplumber text+table extraction discussion](https://github.com/jsvine/pdfplumber/discussions/1026) - Maintainer-recommended pattern for combining text and tables
- [PyMuPDF scanned page detection](https://github.com/pymupdf/PyMuPDF/discussions/1653) - Image coverage heuristic, GlyphlessFont detection
- [PyMuPDF find_tables vs pdfplumber](https://github.com/pymupdf/PyMuPDF/issues/3156) - When pymupdf table detection is worse, lines_strict recommendation

### Secondary (MEDIUM confidence)
- [python-frontmatter PyPI](https://pypi.org/project/python-frontmatter/) - v1.1.0 confirmed, API verified via docs
- [Tesseract UB-Mannheim downloads](https://digi.bib.uni-mannheim.de/tesseract/) - Windows installer v5.3.x confirmed available
- [PDF extraction comparison (Medium)](https://onlyoneaman.medium.com/i-tested-7-python-pdf-extractors-so-you-dont-have-to-2025-edition-c88013922257) - Real-world comparison of extraction libraries

### Tertiary (LOW confidence)
- [pdfplumber text+table tutorial (DEV)](https://dev.to/rishabdugar/pdf-extraction-retrieving-text-and-tables-together-using-python-14c2) - Code pattern for combining text and tables, community example

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - pymupdf4llm API verified via official docs, pdfplumber verified via GitHub, versions confirmed
- Architecture: HIGH - Tiered fallback matches user decisions, patterns verified against library APIs
- Pitfalls: MEDIUM - Import order and Tesseract PATH issues verified; duplicate table issue based on GitHub issues; OOM thresholds are estimates
- Quality thresholds: MEDIUM - Garble detection heuristics are reasonable but not validated against CER PDFs specifically; will need tuning

**Research date:** 2026-02-09
**Valid until:** 2026-03-09 (30 days - libraries are stable, pymupdf4llm releases monthly)
