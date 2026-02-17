# Smoke Test Runbook: Phases 01-05 (Live REGDOCS, Single Filing, Deep Phase 5 Validation)

**Document status:** Ready for implementation and execution  
**Last updated:** 2026-02-16  
**Test type:** Controlled live smoke test with focused Phase 5 coverage

## 1) Purpose

Extend the proven Phases 01-04 smoke flow into **Phase 05 (LLM analysis)** so we can validate front-to-back behavior for one real filing, end-to-end:

- **Phase 01:** Foundation/config/logging/database startup
- **Phase 02:** Scrape recent filings from REGDOCS
- **Phase 03:** Download PDF for selected filing/document
- **Phase 04:** Extract markdown text from downloaded PDF
- **Phase 05:** Analyze extracted text via Claude CLI and persist structured output

This remains a **safety-first smoke test**, not a performance or load test.

## 2) Keep Existing 01-04 Constraints Intact

Do not relax these constraints when adding Phase 5:

1. **Live REGDOCS only**
2. **One filing only** (upper-most filing from listing order)
3. **One document only** from that filing
4. **10-second request pacing** for web traffic
5. **One retry attempt** for smoke traffic control
6. **No duplicate filings** (dedupe by `filing_id`, keep first)
7. **Smoke-isolated paths only** for DB/data/logs
8. If constraints cannot be guaranteed, **abort**

Phase 5 adds one LLM analysis call for that single extracted filing.

## 3) Additional Prerequisites For Phase 5

All 01-04 prerequisites still apply, plus:

- [ ] Claude CLI available on PATH: `claude --version`
- [ ] Claude CLI authenticated and usable in this environment
- [ ] `config/analysis.yaml` present
- [ ] `config/prompts/filing_analysis.txt` present
- [ ] Operator confirms one analysis call is acceptable for this smoke run

Recommended quick CLI check before live smoke execution:

```bash
claude -p "Respond with exactly: OK" --max-turns 1 --no-session-persistence --tools ""
```

## 4) Required Smoke Settings (Phases 01-05)

Use the same smoke isolation as 01-04, plus explicit analysis settings.

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

## 5) Extension Blueprint (Smoke Harness)

Current harness: `tests/smoke/test_phases_01_04.py`  
Recommended extension target: `tests/smoke/test_phases_01_05.py` (keep 01-04 file unchanged as known-good baseline).

### Minimal code extension checklist

1. Copy `tests/smoke/test_phases_01_04.py` to `tests/smoke/test_phases_01_05.py`.
2. Add Phase 5 imports:
   - `AnalysisSettings` from `cer_scraper.config.settings`
   - `analyze_filings` from `cer_scraper.analyzer`
   - `AnalysisOutput` from `cer_scraper.analyzer.schemas` (for output schema verification)
3. Extend `_build_smoke_settings()` to return analysis settings.
4. Add a new smoke step (after extraction): `_step_g_analyze(session, analysis_settings)`.
5. Extend evidence model with Phase 5 fields (attempted/succeeded/failed/skipped, cost, token counts if present, prompt version, analysis path, schema checks).
6. Extend `_verify_and_collect()` to validate:
   - Filing `status_analyzed`
   - `Filing.analysis_json` presence/shape (for success profile)
   - On-disk `analysis.json` presence in filing folder (best-effort check)
7. Update CLI output summary and `smoke_evidence.json` persistence to include Phase 5 evidence.

## 6) Controlled Front-To-Back Procedure (01-05)

### Step A-F (unchanged)

Run all existing steps from the 01-04 runbook exactly as-is:

- Step A: Initialize isolated smoke runtime
- Step B: Scrape listing page
- Step C: Select upper-most filing (deduped)
- Step D: Enrich target + keep first document + persist
- Step E: Download single PDF
- Step F: Extract text to markdown

### Step G (new): Analyze filing text with Claude CLI

- Run `analyze_filings(session, analysis_settings)` once.
- Confirm analysis is restricted to extracted filings in smoke DB.
- Capture `AnalysisBatchResult`:
  - `filings_attempted`
  - `filings_succeeded`
  - `filings_failed`
  - `filings_skipped`
  - `total_cost_usd`
  - `errors`

### Step H (expanded verification)

Verify all final state fields for selected filing:

- `status_scraped == success`
- `status_downloaded == success`
- `status_extracted == success`
- `status_analyzed` matches expected profile outcome
- `analysis_json` DB column presence/absence according to profile
- Analysis artifact paths remain in `smoke_latest_one` namespace

## 7) Phase 5 Deep Test Matrix (Run These Profiles)

Run baseline first, then targeted negative/edge profiles. Keep one filing/one document scope each run.

| Profile | Override(s) | Expected Phase 5 behavior | Expected DB status |
|---|---|---|---|
| **P5-A Baseline success** | none beyond baseline settings | 1 attempted, 1 succeeded, 0 failed, 0 skipped | `status_analyzed=success`, `analysis_json` populated |
| **P5-B Insufficient text skip** | `ANALYSIS_MIN_TEXT_LENGTH=1000000` | 1 attempted, 0 succeeded, 0 failed, 1 skipped | `status_analyzed=success`, `analysis_json` may remain empty |
| **P5-C Timeout failure** | `ANALYSIS_TIMEOUT_SECONDS=1` | likely timeout path; 1 failed | `status_analyzed=failed`, retry count increments |
| **P5-D Template path failure** | `ANALYSIS_TEMPLATE_PATH=config/prompts/does_not_exist.txt` | analysis step throws, orchestrator isolates failure | `status_analyzed=failed`, error message set |
| **P5-E Idempotency** | Re-run Phase 5 immediately after P5-A without reinitializing DB | second run should find nothing pending | second run: `filings_attempted=0` |

Notes:
- P5-C can be model/latency dependent; rerun if needed to trigger timeout deterministically.
- P5-B is expected to skip analysis call due short-text guard.

## 8) Phase 5 Assertions (Must Check)

For **P5-A baseline success**, verify all of the following:

1. `AnalysisBatchResult` indicates one successful filing.
2. Filing row has:
   - `status_analyzed = success`
   - non-empty `analysis_json`
3. `analysis.json` file exists beside downloaded document (best effort but expected in healthy run).
4. `analysis_json` validates against `AnalysisOutput` schema:
   - top-level keys: `summary`, `entities`, `relationships`, `classification`, `key_facts`
   - `classification.confidence` is integer in range 0-100
5. Classification `primary_type` is one of CER taxonomy values:
   - `Application`, `Order`, `Decision`, `Compliance Filing`, `Correspondence`, `Notice`, `Conditions Compliance`, `Financial Submission`, `Safety Report`, `Environmental Assessment`
6. Logs include analyzer lifecycle events:
   - Claude invocation
   - analysis success/failure
   - persistence outcome

For **failure/skip profiles (P5-B to P5-D)**, verify:

- Failure does not create duplicate filings.
- Failure/skip on one filing does not imply uncontrolled retries.
- `retry_count` increments only on failure paths with error updates.
- Error text is captured in `error_message` and in smoke evidence.

## 9) Evidence Collection (Extended For Phase 5)

Add these fields to smoke evidence output:

- `analysis_attempted`, `analysis_succeeded`, `analysis_failed`, `analysis_skipped`
- `analysis_total_cost_usd`
- `analysis_errors[]`
- `analysis_json_db_present` (bool)
- `analysis_json_path`
- `analysis_schema_valid` (bool)
- `analysis_classification_primary`
- `analysis_classification_confidence`
- `analysis_entities_count`
- `analysis_relationships_count`
- `analysis_key_facts_count`

## 10) Useful Verification Commands

### Run extended smoke test

```bash
uv run python -m tests.smoke.test_phases_01_05
```

### Inspect filing statuses and analysis JSON length

```bash
sqlite3 data/smoke_latest_one/state.db \
"SELECT filing_id,status_scraped,status_downloaded,status_extracted,status_analyzed,retry_count,LENGTH(analysis_json) FROM filings;"
```

### Inspect document extraction state

```bash
sqlite3 data/smoke_latest_one/state.db \
"SELECT filename,download_status,extraction_status,char_count,page_count FROM documents;"
```

### Validate stored analysis JSON against schema

```bash
uv run python - <<'PY'
import sqlite3
from cer_scraper.analyzer.schemas import AnalysisOutput

conn = sqlite3.connect("data/smoke_latest_one/state.db")
row = conn.execute("SELECT analysis_json FROM filings LIMIT 1").fetchone()
if not row or not row[0]:
    raise SystemExit("No analysis_json found in filings table")

AnalysisOutput.model_validate_json(row[0])
print("Schema validation: PASS")
PY
```

## 11) Pass/Fail Criteria (01-05)

### Pass

All conditions below are true:

- 01-04 constraints remain enforced (one filing, one document, safe pacing, isolated paths)
- Phase 5 outcome matches intended profile expectations
- No duplicate filing rows created
- `status_*` transitions are internally consistent through analyzed step
- Evidence artifacts and logs are complete and inspectable

### Fail

Any of the following occurs:

- 01-04 scope constraints are broken while adding Phase 5
- `status_analyzed` inconsistent with observed analyzer result
- Expected success profile lacks valid `analysis_json`
- Unexpected retries or uncontrolled repeat analysis calls
- Output/evidence written outside smoke-isolated namespace

## 12) Abort Conditions

Abort immediately if:

- Claude CLI is unavailable or unauthenticated in the current environment
- REGDOCS stability issues require increased traffic beyond smoke constraints
- The runner cannot guarantee one-filing/one-document scope
- Any loop/retry behavior exceeds agreed safety posture

## 13) Post-Run Actions

- Save `logs/smoke_latest_one/pipeline.log` and `logs/smoke_latest_one/smoke_evidence.json`.
- Keep smoke DB and artifacts for inspection unless cleanup is explicitly approved.
- Record profile results (P5-A through P5-E) and open defects before broadening scope.

