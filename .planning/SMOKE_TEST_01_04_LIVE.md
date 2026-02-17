# Smoke Test Runbook: Phases 01-04 (Live REGDOCS, Single Filing)

**Document status:** Ready for first execution  
**Last updated:** 2026-02-16  
**Test type:** Controlled live smoke test

For the front-to-back extension through Phase 5, see:
`.planning/SMOKE_TEST_01_05_LIVE.md`.

## 1) Purpose

Validate that completed phases currently work together in a real environment while minimizing traffic to REGDOCS:

- **Phase 01:** Foundation/config/logging/database startup
- **Phase 02:** Scrape recent filings from REGDOCS
- **Phase 03:** Download PDF(s) for target filing
- **Phase 04:** Extract markdown text from downloaded PDF

This is a **safety-first smoke test**, not a full regression suite.

## 2) Non-Negotiable Safety Constraints

The test MUST enforce all of the following:

1. **Live REGDOCS only** (no mock endpoint for this run).
2. **Only one filing** is processed.
3. **Only one document** from that filing is processed.
4. Filing selection is based on the **upper-most filing** returned from the recent filings page.
5. **No duplicates** are processed (deduplicate by `filing_id` and keep first).
6. Request pacing is fixed at **10 seconds** (`delay_min=10`, `delay_max=10`).
7. Retry budget is **one attempt only** for smoke-test traffic control.
8. Use isolated smoke-test storage paths (separate DB/data/logs).

If any constraint cannot be guaranteed, **abort the run**.

## 3) Test Environment Isolation

Use a dedicated smoke namespace so production-like state is untouched.

| Setting | Required value |
|---|---|
| `PIPELINE_DB_PATH` | `data/smoke_latest_one/state.db` |
| `PIPELINE_FILINGS_DIR` | `data/smoke_latest_one/filings` |
| `PIPELINE_LOG_DIR` | `logs/smoke_latest_one` |
| `SCRAPER_LOOKBACK_PERIOD` | `day` |
| `SCRAPER_PAGES_TO_SCRAPE` | `1` |
| `SCRAPER_DELAY_SECONDS` | `10` |
| `SCRAPER_DELAY_MIN_SECONDS` | `10` |
| `SCRAPER_DELAY_MAX_SECONDS` | `10` |
| `SCRAPER_DISCOVERY_RETRIES` | `1` |
| `SCRAPER_MAX_RETRIES` | `1` |

## 4) Pre-Run Checklist

Complete before any live calls:

- [ ] `uv sync` completed successfully
- [ ] Playwright Chromium installed (`uv run playwright install chromium`)
- [ ] Tesseract available (`tesseract --version`) for OCR fallback path readiness
- [ ] No other scraper/pipeline process running concurrently
- [ ] Smoke paths confirmed (DB/log/filings) and isolated
- [ ] Operator confirms this run is allowed against live REGDOCS now

## 5) Controlled Execution Procedure

### Step A - Initialize isolated runtime

- Load settings using the smoke environment overrides listed above.
- Initialize database and logging for smoke paths only.

### Step B - Scrape with conservative limits

- Run `scrape_recent_filings(...)` with the constrained settings.
- Collect all scraped filings in memory/DB for selection.

### Step C - Enforce single-filing target

- Select the **upper-most filing** (first filing returned by scrape order).
- Deduplicate by `filing_id` and keep first unique entry.
- Remove/ignore all non-selected filings for downstream steps.
- Verify exactly one filing remains for download/extraction pipeline steps.

### Step D - Enforce single-document target

- For selected filing, keep only the first document entry.
- Remove/ignore other document rows for this smoke run.
- Verify exactly one document is eligible for download.

### Step E - Download phase

- Run `download_filings(...)` for the constrained target.
- Confirm one PDF attempt only for the selected filing/document.

### Step F - Extraction phase

- Run `extract_filings(...)` for the constrained target.
- Confirm one markdown output (`.md`) is produced next to the downloaded PDF (if extraction succeeds).

### Step G - Idempotency safety check (optional but recommended)

- Re-run the same smoke flow once with identical inputs.
- Confirm no duplicate filing creation and no unnecessary reprocessing.

## 6) Evidence to Capture

Record all items below after execution:

1. **Run metadata**
   - Start/end timestamp
   - Operator
   - Environment override set used

2. **Scrape outcome**
   - Total found by scraper
   - Selected filing ID (upper-most)
   - Strategy used (`api` or `dom`)
   - Errors/warnings count

3. **Download outcome**
   - Filing attempted/succeeded/failed
   - Document attempted (must be 1)
   - Local PDF path
   - File size bytes

4. **Extraction outcome**
   - Document extraction status
   - Extraction method (`pymupdf4llm`, `pdfplumber`, or `tesseract`)
   - Markdown path
   - `char_count`, `page_count`

5. **State verification**
   - Filing status fields: `status_scraped`, `status_downloaded`, `status_extracted`
   - Duplicate check by `filing_id` (must be unique)

6. **Logs**
   - Smoke log location
   - Any warnings/errors related to rate limiting, robots, retries, extraction fallbacks

## 7) Pass/Fail Criteria

### Pass

All conditions below are true:

- Exactly one filing selected and processed downstream
- Exactly one document downloaded/extracted
- No duplicate filing entries in smoke DB for selected `filing_id`
- Request pacing and retry settings match constraints (10s delays, one attempt)
- Output artifacts created in smoke paths only
- Status transitions are internally consistent

### Fail

Any of the following occurs:

- More than one filing or more than one document processed
- Duplicate filing rows created for selected filing ID
- Constraints not applied (delay/retry/scope)
- Traffic pattern exceeds the agreed safety posture
- Outputs written outside smoke-isolated paths

## 8) Abort Conditions

Stop immediately if:

- REGDOCS appears unstable/unresponsive and retries would increase load.
- The test runner cannot guarantee one-filing/one-document enforcement.
- Unexpected loops, repeated network calls, or unbounded pagination are observed.
- robots.txt check returns disallow for target path/user-agent.

## 9) Post-Run Actions

- Archive the smoke log and summary evidence.
- Keep smoke DB and artifacts for inspection unless storage cleanup is explicitly approved.
- Document findings and open issues before expanding scope.

## 10) Planned Next Expansion (After First Pass)

When this run is stable, expand gradually:

1. One filing with all its documents
2. Two newest filings with strict pacing
3. Add automated assertions and repeatable CI-safe dry tests
4. Integrate into broader Phase 01-04 regression documentation
