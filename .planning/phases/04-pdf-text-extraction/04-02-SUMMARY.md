---
phase: 04-pdf-text-extraction
plan: 02
subsystem: extraction
tags: [pymupdf4llm, pdfplumber, pytesseract, tesseract-ocr, quality-check, markdown]

# Dependency graph
requires:
  - phase: 04-pdf-text-extraction
    provides: "ExtractionSettings, Document model with extraction columns, extractor package"
provides:
  - "try_pymupdf4llm: primary PDF-to-markdown extraction via pymupdf4llm"
  - "try_pdfplumber: table-focused fallback extraction with bbox clamping"
  - "try_tesseract_direct: last-resort OCR via PyMuPDF pixmap + pytesseract"
  - "passes_quality_check / passes_ocr_quality_check: garble detection with 3 heuristics"
  - "extract_document: per-document tiered fallback orchestrator"
  - "ExtractionResult / ExtractionMethod shared types"
affects: [04-pdf-text-extraction]

# Tech tracking
tech-stack:
  added: [pytesseract]
  patterns:
    - "Three-tier extraction fallback: pymupdf4llm -> pdfplumber -> Tesseract"
    - "Quality gate between tiers: min content, garble ratio, repetition detection"
    - "Shared types module to avoid circular imports between extractor modules"

key-files:
  created:
    - src/cer_scraper/extractor/types.py
    - src/cer_scraper/extractor/pymupdf_extractor.py
    - src/cer_scraper/extractor/pdfplumber_extractor.py
    - src/cer_scraper/extractor/quality.py
    - src/cer_scraper/extractor/service.py
  modified:
    - pyproject.toml
    - uv.lock

key-decisions:
  - "ExtractionResult and ExtractionMethod defined in types.py to avoid circular imports between service.py and extractor modules"
  - "pymupdf4llm.to_markdown called with available params only (no use_ocr/ocr_language -- not in v0.2.9 API)"
  - "Repetition threshold raised from plan's 50 to 200 -- common English trigrams like 'the' appear 70+ times per 10K chars in regulatory text"
  - "Only non-whitespace-containing trigrams checked in repetition heuristic"
  - "pymupdf.layout import skipped -- module not available in installed pymupdf version"

patterns-established:
  - "Extraction pipeline: pre-checks (encryption, page count) -> tier 1 -> quality -> tier 2 -> quality -> tier 3 -> quality -> failed"
  - "Quality checker: configurable thresholds via ExtractionSettings, separate strict/OCR validation functions"
  - "pdfplumber bbox clamping: clamp table bboxes to page boundaries before filtering"

# Metrics
duration: 4.3min
completed: 2026-02-10
---

# Phase 4 Plan 02: Extraction Engines & Service Summary

**Three-tier PDF extraction pipeline (pymupdf4llm -> pdfplumber -> Tesseract) with quality gate heuristics (min chars, garble ratio, repetition detection) and per-document fallback orchestration**

## Performance

- **Duration:** 4.3 min
- **Started:** 2026-02-10T04:33:06Z
- **Completed:** 2026-02-10T04:37:27Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments
- Created pymupdf4llm primary extractor with markdown conversion, page separators, and configurable table strategy
- Created pdfplumber table-focused fallback with bbox clamping, table-text filtering, and pipe-delimited markdown tables via pandas
- Implemented quality checker with 3 heuristics: minimum content (50 chars/page, floor 100), garble ratio (5%), and repetition detection (200+ trigram threshold)
- Implemented OCR quality checker with looser thresholds (20 chars/page, 10% garble, no repetition check)
- Created extraction service orchestrating the full tiered fallback pipeline with encryption/page-count guards
- Added pytesseract dependency for Tesseract OCR last-resort extraction

## Task Commits

Each task was committed atomically:

1. **Task 1: Create extraction engines and quality checker** - `4e376c0` (feat)
2. **Task 2: Create per-document extraction service with tiered fallback** - `44ab952` (feat)

## Files Created/Modified
- `src/cer_scraper/extractor/types.py` - ExtractionResult dataclass and ExtractionMethod enum (shared types)
- `src/cer_scraper/extractor/pymupdf_extractor.py` - try_pymupdf4llm() primary extraction via pymupdf4llm.to_markdown
- `src/cer_scraper/extractor/pdfplumber_extractor.py` - try_pdfplumber() fallback with table detection, bbox clamping, markdown table output
- `src/cer_scraper/extractor/quality.py` - passes_quality_check() and passes_ocr_quality_check() with configurable thresholds
- `src/cer_scraper/extractor/service.py` - extract_document() tiered fallback orchestrator, try_tesseract_direct() OCR function
- `pyproject.toml` - Added pytesseract dependency
- `uv.lock` - Updated lockfile with pytesseract + packaging transitive deps

## Decisions Made
- **Shared types module:** Defined ExtractionResult and ExtractionMethod in `types.py` rather than `service.py` to avoid circular imports (extractors import types, service imports extractors)
- **pymupdf4llm API adaptation:** The plan assumed `use_ocr` and `ocr_language` parameters and a `pymupdf.layout` side-effect import. None of these exist in pymupdf4llm v0.2.9. Used only available parameters (`page_separators=True`, `force_text=True`, `table_strategy` from settings)
- **Repetition threshold:** Raised from plan's 50 to 200 after testing showed common English trigrams ("the", "he ") appear 70-120 times per 10K chars in realistic CER regulatory text. Threshold of 50 would cause false positives on valid extraction output
- **Non-whitespace trigrams only:** Repetition check skips space-containing trigrams since they are ubiquitous in all natural text

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] pymupdf.layout import unavailable**
- **Found during:** Task 1 (pymupdf extractor implementation)
- **Issue:** Plan specified `import pymupdf.layout  # noqa: F401` before pymupdf4llm import. Module `pymupdf.layout` does not exist in pymupdf 1.26.7 (it's a separate `pymupdf_layout` package)
- **Fix:** Removed the non-existent import. pymupdf4llm works correctly without it
- **Files modified:** src/cer_scraper/extractor/pymupdf_extractor.py
- **Verification:** pymupdf4llm.to_markdown() call succeeds and produces markdown output
- **Committed in:** 4e376c0

**2. [Rule 3 - Blocking] pymupdf4llm API mismatch (use_ocr, ocr_language params)**
- **Found during:** Task 1 (pymupdf extractor implementation)
- **Issue:** Plan specified `use_ocr=True` and `ocr_language=settings.ocr_language` params. pymupdf4llm v0.2.9 does not support these parameters
- **Fix:** Used only available parameters. pymupdf4llm has built-in per-page OCR detection via its `page_is_ocr()` internal function, so explicit OCR params are unnecessary
- **Files modified:** src/cer_scraper/extractor/pymupdf_extractor.py
- **Verification:** Function signature inspection confirms available params, import test passes
- **Committed in:** 4e376c0

**3. [Rule 1 - Bug] Repetition threshold too low for natural text**
- **Found during:** Task 1 (quality checker testing)
- **Issue:** Plan specified threshold of 50 trigram repetitions. Testing with realistic CER regulatory text showed common English trigrams ("he ": 120, "the": 70) far exceed this in 10K chars
- **Fix:** Raised threshold to 200 and restricted check to non-whitespace-containing trigrams only
- **Files modified:** src/cer_scraper/extractor/quality.py
- **Verification:** Quality checker passes on realistic regulatory text while still catching extreme repetition (300+ of same pattern)
- **Committed in:** 4e376c0

**4. [Rule 3 - Blocking] Circular import prevention**
- **Found during:** Task 1 (module design)
- **Issue:** Plan suggested defining ExtractionResult/ExtractionMethod in service.py. But extractors and quality.py need these types at import time, and service.py imports from extractors -- creating a circular dependency
- **Fix:** Created types.py in the extractor package for shared types. Service.py re-exports them for backward compatibility
- **Files modified:** src/cer_scraper/extractor/types.py, src/cer_scraper/extractor/service.py
- **Verification:** All modules import successfully with no circular import errors
- **Committed in:** 4e376c0

**5. [Rule 3 - Blocking] pytesseract not installed**
- **Found during:** Task 1 (dependency check)
- **Issue:** pytesseract was not in pyproject.toml dependencies despite being needed for Tesseract OCR
- **Fix:** Ran `uv add pytesseract` to install it
- **Files modified:** pyproject.toml, uv.lock
- **Verification:** `import pytesseract` succeeds
- **Committed in:** 4e376c0

---

**Total deviations:** 5 auto-fixed (1 bug, 4 blocking)
**Impact on plan:** All auto-fixes necessary for correctness and functionality. No scope creep. The core architecture (three-tier fallback with quality gates) is implemented exactly as planned.

## Issues Encountered
None beyond the deviations documented above.

## User Setup Required

**Tesseract OCR must be installed as a system dependency for Tier 3 OCR to function.**
- Windows: Download UB-Mannheim installer from https://digi.bib.uni-mannheim.de/tesseract/
- Ensure `tesseract` is on PATH, or set `EXTRACTION_TESSERACT_CMD` to the full path
- Tiers 1 and 2 (pymupdf4llm and pdfplumber) work without Tesseract

## Next Phase Readiness
- All three extraction methods are implemented and importable
- extract_document() is ready for the batch orchestrator (Plan 03)
- Quality checks are configurable via ExtractionSettings
- Tesseract is gracefully handled: if not installed, try_tesseract_direct raises an exception which is caught and logged, allowing the pipeline to report all_methods_failed cleanly

## Self-Check: PASSED

---
*Phase: 04-pdf-text-extraction*
*Completed: 2026-02-10*
