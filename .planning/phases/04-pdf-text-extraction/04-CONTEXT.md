# Phase 4: PDF Text Extraction - Context

**Gathered:** 2026-02-09
**Status:** Ready for planning

<domain>
## Phase Boundary

Extract text from downloaded CER filing PDFs using a tiered fallback strategy (PyMuPDF -> pdfplumber -> Tesseract OCR) and produce clean markdown files suitable for LLM analysis in Phases 5-6. Tools are locked by the roadmap; this phase covers extraction logic, quality validation, and output storage.

</domain>

<decisions>
## Implementation Decisions

### Output format
- Convert entire PDF to markdown (not just tables) — `.md` file per PDF
- Best effort structure detection: headings, lists, tables where detectable; fall back to plain paragraphs when structure detection fails
- Single `.md` file per PDF document with page breaks marked by separators (e.g., `---` or `<!-- page N -->`)
- Tables always rendered as pipe-delimited markdown tables, even for wide/complex regulatory tables

### Storage layout
- `.md` files stored alongside PDFs in the same filing directory (e.g., `data/filings/2026-02-05_Filing-12345/documents/doc_001.md` next to `doc_001.pdf`)
- Extraction metadata stored in BOTH database (new columns on Document model) AND YAML frontmatter in the `.md` file
- Full extracted text also stored in a database TEXT column (enables SQL queries on content)
- Skip extraction if `.md` file already exists and has content (no re-extract on re-run)

### Fallback strategy
- Per-document fallback: if quality triggers fire, re-extract the entire document with the next method (not per-page)
- If all three methods fail (PyMuPDF, pdfplumber, Tesseract): mark document as `extraction_failed` in DB, log a warning, and continue pipeline — filing proceeds to email without text analysis

### Mixed document handling
- Detect which pages have text layers vs. scanned images before extraction
- Process text-layer pages with PyMuPDF/pdfplumber; process scanned pages with Tesseract OCR
- Merge results into a single `.md` file maintaining page order

### Encrypted PDFs
- Skip password-protected/encrypted PDFs entirely
- Mark as `extraction_failed` with reason `encrypted`, log a warning

### Language
- Tesseract configured for English only
- French sections may have lower OCR quality but still extract what they can

### Claude's Discretion
- Garble detection heuristic (what triggers PyMuPDF -> pdfplumber fallback)
- OCR quality validation thresholds (what constitutes acceptable vs. failed Tesseract output)
- Maximum PDF size/page count guard for extraction (if needed to prevent hour-long OCR runs)

</decisions>

<specifics>
## Specific Ideas

- User wants the entire document converted to markdown, not just plain text — this gives the LLM structured input to work with
- Markdown tables should be used consistently even for complex regulatory tables (the LLM can handle them)
- Metadata should be self-contained in the .md frontmatter AND queryable in the database — redundancy is acceptable for flexibility

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 04-pdf-text-extraction*
*Context gathered: 2026-02-09*
