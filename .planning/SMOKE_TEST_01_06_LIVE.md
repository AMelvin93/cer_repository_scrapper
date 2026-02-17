# Smoke Test Runbook: Phases 01-06 (Live REGDOCS, Single Filing, Step-06 Deep Analysis Validation)

**Document status:** Ready for implementation and execution  
**Last updated:** 2026-02-16  
**Test type:** Controlled live smoke test with focused Step-06 coverage

For the prior runbook through Step-05, see `.planning/SMOKE_TEST_01_05_LIVE.md`.

## 1) Purpose

Validate one real filing through the full pipeline and confirm that **Step-06 deep analysis fields** are generated and persisted correctly:

- **Phase 01:** Foundation/config/logging/database startup
- **Phase 02:** Scrape recent filings from REGDOCS
- **Phase 03:** Download one PDF for selected filing/document
- **Phase 04:** Extract markdown text from the downloaded PDF
- **Phase 05:** Analyze filing text with Claude CLI and persist structured JSON
- **Phase 06:** Validate deep-analysis dimensions in persisted `analysis_json`

This remains a **safety-first smoke test**, not a load test.

## 2) Non-Negotiable Constraints (Carry Forward from 01-05)

Do not relax these constraints:

1. **Live REGDOCS only**
2. **One filing only** (upper-most filing from listing order)
3. **One document only** from that filing
4. **10-second request pacing**
5. **One retry attempt** for smoke traffic control
6. **No duplicate filings** (dedupe by `filing_id`, keep first)
7. **Smoke-isolated paths only** for DB/data/logs
8. If constraints cannot be guaranteed, **abort**

## 3) Step-06 Preconditions

All 01-05 prerequisites still apply, plus:

- [ ] Step-06 schema is available via `AnalysisOutput` with fields:
  - `regulatory_implications`
  - `dates`
  - `sentiment`
  - `quotes`
  - `impact`
- [ ] Prompt template includes Step-06 deep-analysis instructions (`config/prompts/filing_analysis.txt`)
- [ ] Operator confirms one live analysis call is acceptable for this smoke run

## 4) Required Smoke Settings (01-06)

Use the same smoke isolation baseline as 01-05:

| Setting | Required value (baseline profile) |
|---|---|
| `PIPELINE_DB_PATH` | `data/smoke_latest_one/state.db` |
| `PIPELINE_FILINGS_DIR` | `data/smoke_latest_one/filings` |
| `PIPELINE_LOG_DIR` | `logs/smoke_latest_one` |
| `SCRAPER_LOOKBACK_PERIOD` | `week` |
| `SCRAPER_PAGES_TO_SCRAPE` | `1` |
| `SCRAPER_DELAY_SECONDS` | `10` |
| `SCRAPER_DELAY_MIN_SECONDS` | `10` |
| `SCRAPER_DELAY_MAX_SECONDS` | `10` |
| `SCRAPER_DISCOVERY_RETRIES` | `1` |
| `SCRAPER_MAX_RETRIES` | `1` |
| `ANALYSIS_MODEL` | `sonnet` (or team-approved model) |
| `ANALYSIS_TIMEOUT_SECONDS` | `300` |
| `ANALYSIS_MIN_TEXT_LENGTH` | `100` |
| `ANALYSIS_TEMPLATE_PATH` | `config/prompts/filing_analysis.txt` |

## 5) Smoke-Test Functionality Update Plan (Step-06 Focus)

Current smoke harness baseline: `tests/smoke/test_phases_01_05.py`  
Recommended Step-06 target: `tests/smoke/test_phases_01_06.py` (keep 01-05 file as known-good baseline).

### Functional update checklist

1. Keep Steps A-F unchanged (existing stable behavior).
2. Keep Step G (single analysis call) unchanged.
3. Extend verification/evidence with Step-06 assertions from parsed `AnalysisOutput`.
4. Fail on Step-06 contract violations (missing required deep fields in successful analysis).
5. Persist Step-06 evidence in `smoke_evidence.json` and print in CLI summary.

### Step-06 evidence fields to add

Minimum recommended additions:

- `phase6_regulatory_implications_is_null` (bool)
- `phase6_regulatory_implications_summary_present` (bool)
- `phase6_affected_parties_count` (int)
- `phase6_dates_count` (int)
- `phase6_dates_past_count` (int)
- `phase6_dates_upcoming_count` (int)
- `phase6_dates_today_count` (int)
- `phase6_dates_invalid_temporal_status_count` (int)
- `phase6_sentiment_present` (bool)
- `phase6_sentiment_category` (string)
- `phase6_sentiment_nuance_present` (bool)
- `phase6_quotes_count` (int)
- `phase6_quotes_with_source_count` (int)
- `phase6_impact_present` (bool)
- `phase6_impact_score` (int)
- `phase6_impact_justification_present` (bool)

### Step-06 verification rules (success profile)

When `status_analyzed=success` and `analysis_json` exists:

1. `analysis_json` validates against `AnalysisOutput`.
2. `regulatory_implications` is either:
   - `null` (accepted for routine filings), or
   - object with non-empty `summary`; `affected_parties` list may be empty.
3. `dates` is always present as an array (empty allowed).
4. Every date item has:
   - `date` non-empty string
   - `type` in `deadline|hearing|comment_period|effective|filing|other`
   - `description` non-empty string
   - `temporal_status` in `past|upcoming|today`
5. `sentiment` is present with:
   - `category` in `routine|notable|urgent|adversarial|cooperative`
   - non-empty `nuance`
6. `quotes` is an array; expected range in baseline success is `1..5` when analysis succeeds.
7. `impact` is present with:
   - `score` integer in `1..5`
   - non-empty `justification`

## 6) End-to-End Procedure (01-06)

### Step A-F (unchanged)

Run the existing 01-05 controlled flow exactly as-is:

- Step A: Initialize isolated smoke runtime
- Step B: Scrape listing page
- Step C: Select upper-most filing (deduped)
- Step D: Enrich target + keep first document + persist
- Step E: Download single PDF
- Step F: Extract text to markdown

### Step G (unchanged)

- Execute one analysis call for the selected extracted filing.
- Capture attempted/succeeded/failed/skipped counts, cost, and errors.

### Step H (new Step-06 verification focus)

- Parse persisted `analysis_json` through `AnalysisOutput`.
- Execute all Step-06 verification rules from Section 5.
- Persist Step-06 evidence fields in `smoke_evidence.json`.
- Include Step-06 result details in terminal summary and logs.

## 7) End-to-End Test Case (Required)

### E2E-06-A Baseline Success

**Goal:** Validate full 01-06 pipeline with one live filing and Step-06 deep fields present/valid.

**Run command:**

```bash
uv run python -m tests.smoke.test_phases_01_06
```

**Expected outcomes:**

1. One filing selected, one document processed.
2. Final filing statuses are internally consistent through analyzed step:
   - `status_scraped=success`
   - `status_downloaded=success`
   - `status_extracted=success`
   - `status_analyzed=success`
3. `analysis_json` exists in DB and validates against `AnalysisOutput`.
4. Step-06 fields satisfy Section 5 verification rules.
5. Evidence and logs are written only under `smoke_latest_one` paths.

## 8) Step-06 Profile Matrix (After Baseline)

Run baseline first, then targeted profiles:

| Profile | Override(s) | Expected Step-06 behavior | Expected DB state |
|---|---|---|---|
| **S6-A Baseline success** | baseline settings | Deep fields present and valid (`sentiment`, `impact`, `dates`, `quotes`; implications null/object by context) | `status_analyzed=success`, `analysis_json` populated |
| **S6-B Routine filing behavior** | none (depends on selected filing content) | `regulatory_implications` may be `null`; other Step-06 fields still valid | `status_analyzed=success` |
| **S6-C Insufficient text skip** | `ANALYSIS_MIN_TEXT_LENGTH=1000000` | Analysis step skipped; no Step-06 payload expected | `status_analyzed=success`, may have empty `analysis_json` |
| **S6-D Timeout failure** | `ANALYSIS_TIMEOUT_SECONDS=1` | Analysis failure path triggered; Step-06 checks not executed | `status_analyzed=failed`, error captured |
| **S6-E Idempotency** | Re-run after S6-A without reinitializing DB | No additional pending analyses | second run `filings_attempted=0` |

## 9) Verification Commands

### Run Step-06 smoke test

```bash
uv run python -m tests.smoke.test_phases_01_06
```

### Inspect final filing state

```bash
sqlite3 data/smoke_latest_one/state.db \
"SELECT filing_id,status_scraped,status_downloaded,status_extracted,status_analyzed,retry_count,LENGTH(analysis_json) FROM filings;"
```

### Inspect Step-06 output quickly

```bash
sqlite3 data/smoke_latest_one/state.db \
"SELECT substr(analysis_json,1,600) FROM filings LIMIT 1;"
```

## 10) Pass/Fail Criteria (01-06)

### Pass

All conditions below are true:

- 01-05 constraints remain enforced (scope, pacing, retries, isolation)
- Baseline E2E-06-A completes with one analyzed filing
- `analysis_json` validates via `AnalysisOutput`
- Step-06 verification rules all pass for successful analysis
- Evidence/log artifacts are complete and inspectable

### Fail

Any of the following occurs:

- Scope constraints are violated (more than one filing or one document)
- `status_analyzed` contradicts observed analyzer results
- Step-06 fields violate contract/rules in a successful analysis result
- Unexpected retries or uncontrolled repeat analysis calls
- Artifacts written outside smoke-isolated namespace

## 11) Abort Conditions

Abort immediately if:

- Claude CLI is unavailable or unauthenticated
- Runner cannot guarantee one-filing/one-document scope
- REGDOCS instability requires traffic above smoke constraints
- Loop/retry behavior exceeds the agreed safety posture

## 12) Post-Run Actions

- Save `logs/smoke_latest_one/pipeline.log` and `logs/smoke_latest_one/smoke_evidence.json`.
- Record Step-06 profile outcomes (S6-A to S6-E).
- Open defects for any Step-06 schema/prompt contract violations before broader rollout.
