"""Smoke test: Phases 01-06 live REGDOCS single-filing run.

Extends the 01-05 smoke test with Phase 06 (Deep Analysis Validation).
Validates that foundation, scraping, downloading, extraction, analysis,
and deep-analysis fields work together against the live REGDOCS site with
strict safety constraints:
- Only one filing processed (upper-most from recent filings)
- Only one document from that filing
- 10-second request pacing
- One retry attempt only
- All outputs isolated to smoke-test paths
- One LLM analysis call for the single extracted filing
- Deep analysis fields (regulatory_implications, dates, sentiment, quotes, impact) validated

Usage:
    uv run python -m tests.smoke.test_phases_01_06

See .planning/SMOKE_TEST_01_06_LIVE.md for full runbook.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

# ---------------------------------------------------------------------------
# Resolve project root (must happen before cer_scraper imports)
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from cer_scraper.analyzer import AnalysisBatchResult, analyze_filings
from cer_scraper.analyzer.schemas import AnalysisOutput
from cer_scraper.config.settings import (
    AnalysisSettings,
    ExtractionSettings,
    PipelineSettings,
    ScraperSettings,
)
from cer_scraper.db import (
    get_engine,
    get_session_factory,
    init_db,
)
from cer_scraper.db.models import Document, Filing
from cer_scraper.db.state import create_filing
from cer_scraper.downloader import DownloadBatchResult, download_filings
from cer_scraper.extractor import ExtractionBatchResult, extract_filings
from cer_scraper.logging import setup_logging
from cer_scraper.scraper.detail_scraper import enrich_filings_with_documents
from cer_scraper.scraper.discovery import DiscoveryResult, discover_api_endpoints
from cer_scraper.scraper.dom_parser import parse_filings_from_html
from cer_scraper.scraper.models import ScrapedFiling
from cer_scraper.scraper.robots import check_robots_allowed

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Smoke-test settings (matches runbook section 4)
# ---------------------------------------------------------------------------

SMOKE_DB_PATH = "data/smoke_latest_one/state.db"
SMOKE_FILINGS_DIR = "data/smoke_latest_one/filings"
SMOKE_LOG_DIR = "logs/smoke_latest_one"

# CER taxonomy values for validation
CER_TAXONOMY = {
    "Application",
    "Order",
    "Decision",
    "Compliance Filing",
    "Correspondence",
    "Notice",
    "Conditions Compliance",
    "Financial Submission",
    "Safety Report",
    "Environmental Assessment",
}

# Phase 6 valid enum values
VALID_DATE_TYPES = {"deadline", "hearing", "comment_period", "effective", "filing", "other"}
VALID_TEMPORAL_STATUSES = {"past", "upcoming", "today"}
VALID_SENTIMENT_CATEGORIES = {"routine", "notable", "urgent", "adversarial", "cooperative"}


def _build_smoke_settings() -> (
    tuple[ScraperSettings, PipelineSettings, ExtractionSettings, AnalysisSettings]
):
    """Create settings objects with smoke-test overrides."""
    scraper = ScraperSettings(
        lookback_period="week",
        pages_to_scrape=1,
        delay_seconds=10.0,
        delay_min_seconds=10.0,
        delay_max_seconds=10.0,
        discovery_retries=1,
        max_retries=1,
    )
    pipeline = PipelineSettings(
        db_path=SMOKE_DB_PATH,
        filings_dir=SMOKE_FILINGS_DIR,
        log_dir=SMOKE_LOG_DIR,
        max_retry_count=1,
    )
    extraction = ExtractionSettings()
    analysis = AnalysisSettings(
        model="sonnet",
        timeout_seconds=300,
        min_text_length=100,
        template_path="config/prompts/filing_analysis.txt",
    )
    return scraper, pipeline, extraction, analysis


# ---------------------------------------------------------------------------
# Evidence capture (extended for Phase 6)
# ---------------------------------------------------------------------------


@dataclass
class SmokeEvidence:
    """Structured evidence collected during the smoke run."""

    # Run metadata
    start_time: str = ""
    end_time: str = ""
    environment: dict = field(default_factory=dict)

    # Scrape outcome
    scrape_total_found: int = 0
    scrape_strategy: str = ""
    scrape_errors: list[str] = field(default_factory=list)
    selected_filing_id: str = ""

    # Download outcome
    download_attempted: int = 0
    download_succeeded: int = 0
    download_failed: int = 0
    download_doc_count: int = 0
    download_pdf_path: str = ""
    download_file_size: int = 0
    download_errors: list[str] = field(default_factory=list)

    # Extraction outcome
    extract_status: str = ""
    extract_method: str = ""
    extract_md_path: str = ""
    extract_char_count: int = 0
    extract_page_count: int = 0
    extract_errors: list[str] = field(default_factory=list)

    # Phase 5: Analysis outcome
    analysis_attempted: int = 0
    analysis_succeeded: int = 0
    analysis_failed: int = 0
    analysis_skipped: int = 0
    analysis_total_cost_usd: float = 0.0
    analysis_errors: list[str] = field(default_factory=list)
    analysis_json_db_present: bool = False
    analysis_json_path: str = ""
    analysis_schema_valid: bool = False
    analysis_classification_primary: str = ""
    analysis_classification_confidence: int = 0
    analysis_entities_count: int = 0
    analysis_relationships_count: int = 0
    analysis_key_facts_count: int = 0

    # Phase 6: Deep analysis evidence
    phase6_regulatory_implications_is_null: bool = True
    phase6_regulatory_implications_summary_present: bool = False
    phase6_affected_parties_count: int = 0
    phase6_dates_count: int = 0
    phase6_dates_past_count: int = 0
    phase6_dates_upcoming_count: int = 0
    phase6_dates_today_count: int = 0
    phase6_dates_invalid_temporal_status_count: int = 0
    phase6_sentiment_present: bool = False
    phase6_sentiment_category: str = ""
    phase6_sentiment_nuance_present: bool = False
    phase6_quotes_count: int = 0
    phase6_quotes_with_source_count: int = 0
    phase6_impact_present: bool = False
    phase6_impact_score: int = 0
    phase6_impact_justification_present: bool = False

    # State verification
    filing_status_scraped: str = ""
    filing_status_downloaded: str = ""
    filing_status_extracted: str = ""
    filing_status_analyzed: str = ""
    duplicate_check_passed: bool = False

    # Overall
    passed: bool = False
    failure_reasons: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Pre-run checks
# ---------------------------------------------------------------------------


def _pre_run_checks() -> list[str]:
    """Run pre-flight checks and return list of failure messages (empty = OK)."""
    failures = []

    # Check Playwright Chromium
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            browser.close()
    except Exception as exc:
        failures.append(f"Playwright Chromium not available: {exc}")

    # Check Tesseract (optional but recommended)
    try:
        subprocess.run(
            ["tesseract", "--version"],
            capture_output=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        logger.warning("Tesseract not found -- OCR fallback will not be available")

    # Check Claude CLI availability
    try:
        result = subprocess.run(
            ["claude", "--version"],
            capture_output=True,
            timeout=10,
            text=True,
        )
        if result.returncode != 0:
            failures.append(
                f"Claude CLI returned non-zero exit code: {result.returncode}"
            )
    except FileNotFoundError:
        failures.append("Claude CLI not found on PATH")
    except subprocess.TimeoutExpired:
        failures.append("Claude CLI --version timed out")

    # Check analysis config files exist
    template_path = PROJECT_ROOT / "config" / "prompts" / "filing_analysis.txt"
    if not template_path.exists():
        failures.append(f"Prompt template not found: {template_path}")

    return failures


# ---------------------------------------------------------------------------
# Core smoke steps (A-F unchanged from 01-04)
# ---------------------------------------------------------------------------


def _step_a_initialize(
    pipeline: PipelineSettings,
) -> tuple:
    """Step A: Initialize isolated runtime (DB, logging, paths)."""
    # Clean previous smoke data for a fresh run
    smoke_data = PROJECT_ROOT / "data" / "smoke_latest_one"
    smoke_logs = PROJECT_ROOT / "logs" / "smoke_latest_one"
    if smoke_data.exists():
        shutil.rmtree(smoke_data)
    if smoke_logs.exists():
        shutil.rmtree(smoke_logs)

    # Set up logging to smoke path
    setup_logging(log_dir=str(PROJECT_ROOT / pipeline.log_dir))

    # Initialize database
    db_path = str(PROJECT_ROOT / pipeline.db_path)
    engine = get_engine(db_path)
    init_db(engine)
    session_factory = get_session_factory(engine)

    logger.info("Step A: Smoke environment initialized")
    logger.info("  DB: %s", db_path)
    logger.info("  Filings: %s", PROJECT_ROOT / pipeline.filings_dir)
    logger.info("  Logs: %s", PROJECT_ROOT / pipeline.log_dir)

    return engine, session_factory


def _step_b_scrape_listing(
    settings: ScraperSettings,
) -> tuple[list[ScrapedFiling], str]:
    """Step B: Scrape listing page only (no detail page visits)."""
    logger.info("Step B: Scraping recent filings listing page")

    # robots.txt check
    allowed = check_robots_allowed(
        settings.base_url,
        settings.recent_filings_path,
        settings.user_agent,
    )
    if not allowed:
        raise RuntimeError("robots.txt disallows scraping -- aborting")

    # API discovery (captures rendered HTML for DOM fallback)
    discovery = discover_api_endpoints(settings)
    rendered_html = discovery.rendered_html if discovery else ""

    if not rendered_html:
        raise RuntimeError("Failed to get rendered HTML from REGDOCS")

    # Parse filings from HTML (returns filings without documents)
    filings = parse_filings_from_html(rendered_html, settings.base_url)
    strategy = "dom"

    logger.info("Step B: Found %d filing(s) via %s strategy", len(filings), strategy)
    return filings, strategy


def _step_c_select_target(
    filings: list[ScrapedFiling],
) -> ScrapedFiling:
    """Step C: Select upper-most filing (first in scrape order)."""
    # Deduplicate by filing_id, keep first
    seen: set[str] = set()
    unique: list[ScrapedFiling] = []
    for f in filings:
        if f.filing_id not in seen:
            seen.add(f.filing_id)
            unique.append(f)

    if len(unique) < len(filings):
        logger.warning(
            "Step C: Deduplicated %d -> %d filings",
            len(filings),
            len(unique),
        )

    target = unique[0]
    logger.info(
        "Step C: Selected filing %s as target (from %d candidates)",
        target.filing_id,
        len(unique),
    )
    return target


def _step_d_enrich_and_persist(
    session,
    target: ScrapedFiling,
    settings: ScraperSettings,
) -> Filing | None:
    """Step D: Enrich target filing with document URLs and persist to DB."""
    logger.info(
        "Step D: Fetching detail page for filing %s to find document URLs",
        target.filing_id,
    )
    enriched = enrich_filings_with_documents([target], settings)
    if enriched == 0 or not target.has_documents:
        logger.error(
            "Step D: No documents found on detail page for filing %s",
            target.filing_id,
        )
        return None

    logger.info(
        "Step D: Found %d document(s) for filing %s",
        len(target.documents),
        target.filing_id,
    )

    # Keep only the first document
    if len(target.documents) > 1:
        logger.info(
            "Step D: Keeping only first document (removing %d extra)",
            len(target.documents) - 1,
        )
        target.documents = [target.documents[0]]

    # Persist to DB
    db_filing = create_filing(
        session,
        filing_id=target.filing_id,
        date=target.date,
        applicant=target.applicant or "Unknown",
        filing_type=target.filing_type or "Unknown",
        proceeding_number=target.proceeding_number,
        title=target.title,
        url=target.url,
    )

    doc = target.documents[0]
    db_doc = Document(
        filing_id=db_filing.id,
        document_url=doc.url,
        filename=doc.filename,
        content_type=doc.content_type,
    )
    session.add(db_doc)
    session.commit()

    logger.info(
        "Step D: Persisted filing %s with 1 document to smoke DB (doc_url=%s)",
        target.filing_id,
        doc.url,
    )

    # Verify exactly 1 filing and 1 document in DB
    filing_count = session.scalar(select(func.count()).select_from(Filing))
    doc_count = session.scalar(select(func.count()).select_from(Document))
    logger.info(
        "Step D: DB contains %d filing(s), %d document(s)",
        filing_count,
        doc_count,
    )

    return db_filing


def _step_e_download(
    session,
    pipeline: PipelineSettings,
    scraper: ScraperSettings,
) -> DownloadBatchResult:
    """Step E: Download phase for constrained target."""
    logger.info("Step E: Downloading single filing/document")
    result = download_filings(session, pipeline, scraper)
    logger.info(
        "Step E complete: attempted=%d, succeeded=%d, failed=%d, pdfs=%d, bytes=%d",
        result.filings_attempted,
        result.filings_succeeded,
        result.filings_failed,
        result.total_pdfs_downloaded,
        result.total_bytes,
    )
    return result


def _step_f_extract(
    session,
    extraction: ExtractionSettings,
) -> ExtractionBatchResult:
    """Step F: Extraction phase for constrained target."""
    logger.info("Step F: Extracting text from downloaded PDF")
    result = extract_filings(session, extraction)
    logger.info(
        "Step F complete: attempted=%d, succeeded=%d, failed=%d, "
        "docs_extracted=%d, docs_failed=%d",
        result.filings_attempted,
        result.filings_succeeded,
        result.filings_failed,
        result.total_docs_extracted,
        result.total_docs_failed,
    )
    return result


# ---------------------------------------------------------------------------
# Phase 5: Analysis step
# ---------------------------------------------------------------------------


def _step_g_analyze(
    session,
    analysis_settings: AnalysisSettings,
) -> AnalysisBatchResult:
    """Step G: Analyze filing text via Claude CLI."""
    logger.info("Step G: Analyzing filing text with Claude CLI")
    result = analyze_filings(session, analysis_settings)
    logger.info(
        "Step G complete: attempted=%d, succeeded=%d, failed=%d, "
        "skipped=%d, cost=$%.4f",
        result.filings_attempted,
        result.filings_succeeded,
        result.filings_failed,
        result.filings_skipped,
        result.total_cost_usd,
    )
    return result


# ---------------------------------------------------------------------------
# Phase 6: Deep analysis verification (Step H)
# ---------------------------------------------------------------------------


def _step_h_verify_deep_analysis(
    parsed: AnalysisOutput, evidence: SmokeEvidence
) -> None:
    """Step H: Verify Phase 6 deep analysis fields against contract rules."""

    # --- regulatory_implications ---
    if parsed.regulatory_implications is not None:
        evidence.phase6_regulatory_implications_is_null = False
        ri = parsed.regulatory_implications
        evidence.phase6_regulatory_implications_summary_present = bool(
            ri.summary and ri.summary.strip()
        )
        evidence.phase6_affected_parties_count = len(ri.affected_parties)

        # Rule 2: if present, summary must be non-empty
        if not ri.summary or not ri.summary.strip():
            evidence.failure_reasons.append(
                "Phase 6: regulatory_implications present but summary is empty"
            )
    else:
        # null is acceptable for routine filings
        evidence.phase6_regulatory_implications_is_null = True

    # --- dates ---
    dates = parsed.dates
    evidence.phase6_dates_count = len(dates)

    for i, d in enumerate(dates):
        # Rule 4: each date item must have non-empty date, valid type,
        #          non-empty description, valid temporal_status
        if not d.date or not d.date.strip():
            evidence.failure_reasons.append(
                f"Phase 6: dates[{i}].date is empty"
            )
        if d.type not in VALID_DATE_TYPES:
            evidence.failure_reasons.append(
                f"Phase 6: dates[{i}].type '{d.type}' not in {VALID_DATE_TYPES}"
            )
        if not d.description or not d.description.strip():
            evidence.failure_reasons.append(
                f"Phase 6: dates[{i}].description is empty"
            )
        if d.temporal_status not in VALID_TEMPORAL_STATUSES:
            evidence.phase6_dates_invalid_temporal_status_count += 1
            evidence.failure_reasons.append(
                f"Phase 6: dates[{i}].temporal_status '{d.temporal_status}' "
                f"not in {VALID_TEMPORAL_STATUSES}"
            )

        # Count temporal status categories
        if d.temporal_status == "past":
            evidence.phase6_dates_past_count += 1
        elif d.temporal_status == "upcoming":
            evidence.phase6_dates_upcoming_count += 1
        elif d.temporal_status == "today":
            evidence.phase6_dates_today_count += 1

    # --- sentiment ---
    if parsed.sentiment is not None:
        evidence.phase6_sentiment_present = True
        evidence.phase6_sentiment_category = parsed.sentiment.category
        evidence.phase6_sentiment_nuance_present = bool(
            parsed.sentiment.nuance and parsed.sentiment.nuance.strip()
        )

        # Rule 5: category must be valid, nuance must be non-empty
        if parsed.sentiment.category not in VALID_SENTIMENT_CATEGORIES:
            evidence.failure_reasons.append(
                f"Phase 6: sentiment.category '{parsed.sentiment.category}' "
                f"not in {VALID_SENTIMENT_CATEGORIES}"
            )
        if not parsed.sentiment.nuance or not parsed.sentiment.nuance.strip():
            evidence.failure_reasons.append(
                "Phase 6: sentiment.nuance is empty"
            )
    else:
        evidence.failure_reasons.append(
            "Phase 6: sentiment is null (required for successful analysis)"
        )

    # --- quotes ---
    quotes = parsed.quotes
    evidence.phase6_quotes_count = len(quotes)
    evidence.phase6_quotes_with_source_count = sum(
        1 for q in quotes if q.source_location and q.source_location.strip()
    )

    # Rule 6: expected range 1..5 in baseline success (warn, not fail)
    if len(quotes) < 1:
        logger.warning(
            "Phase 6: quotes count is %d (expected 1..5 for baseline success)",
            len(quotes),
        )
    elif len(quotes) > 5:
        logger.warning(
            "Phase 6: quotes count is %d (above expected range 1..5)",
            len(quotes),
        )

    # --- impact ---
    if parsed.impact is not None:
        evidence.phase6_impact_present = True
        evidence.phase6_impact_score = parsed.impact.score
        evidence.phase6_impact_justification_present = bool(
            parsed.impact.justification and parsed.impact.justification.strip()
        )

        # Rule 7: score 1-5, non-empty justification
        if not (1 <= parsed.impact.score <= 5):
            evidence.failure_reasons.append(
                f"Phase 6: impact.score {parsed.impact.score} not in range 1-5"
            )
        if not parsed.impact.justification or not parsed.impact.justification.strip():
            evidence.failure_reasons.append(
                "Phase 6: impact.justification is empty"
            )
    else:
        evidence.failure_reasons.append(
            "Phase 6: impact is null (required for successful analysis)"
        )


# ---------------------------------------------------------------------------
# Verification and evidence (extended for Phase 6)
# ---------------------------------------------------------------------------


def _verify_and_collect(session, evidence: SmokeEvidence) -> None:
    """Verify final state and populate evidence fields."""
    # Reload filing with documents
    stmt = (
        select(Filing)
        .options(selectinload(Filing.documents))
        .order_by(Filing.id.asc())
    )
    filings = list(session.scalars(stmt).all())

    if not filings:
        evidence.failure_reasons.append("No filings found in smoke DB after run")
        return

    if len(filings) > 1:
        evidence.failure_reasons.append(
            f"Expected 1 filing, found {len(filings)}"
        )

    filing = filings[0]
    evidence.selected_filing_id = filing.filing_id
    evidence.filing_status_scraped = filing.status_scraped
    evidence.filing_status_downloaded = filing.status_downloaded
    evidence.filing_status_extracted = filing.status_extracted
    evidence.filing_status_analyzed = filing.status_analyzed

    # Duplicate check: count filings with same filing_id
    dup_count = session.scalar(
        select(func.count())
        .select_from(Filing)
        .where(Filing.filing_id == filing.filing_id)
    )
    evidence.duplicate_check_passed = dup_count == 1
    if not evidence.duplicate_check_passed:
        evidence.failure_reasons.append(
            f"Duplicate filing rows for filing_id={filing.filing_id}: {dup_count}"
        )

    # Document checks
    docs = filing.documents
    if len(docs) != 1:
        evidence.failure_reasons.append(
            f"Expected 1 document, found {len(docs)}"
        )

    if docs:
        doc = docs[0]
        if doc.local_path:
            evidence.download_pdf_path = doc.local_path
            pdf = Path(doc.local_path)
            if pdf.exists():
                evidence.download_file_size = pdf.stat().st_size
            else:
                evidence.failure_reasons.append(
                    f"PDF file not found at {doc.local_path}"
                )
        if doc.extraction_status == "success":
            evidence.extract_status = doc.extraction_status
            evidence.extract_method = doc.extraction_method or ""
            evidence.extract_char_count = doc.char_count or 0
            evidence.extract_page_count = doc.page_count or 0
            # Check for markdown file alongside PDF
            if doc.local_path:
                md_path = Path(doc.local_path).with_suffix(".md")
                if md_path.exists():
                    evidence.extract_md_path = str(md_path)
                else:
                    evidence.failure_reasons.append(
                        f"Markdown file not found at {md_path}"
                    )

    # Verify outputs are in smoke paths only
    if evidence.download_pdf_path:
        if "smoke_latest_one" not in evidence.download_pdf_path:
            evidence.failure_reasons.append(
                "PDF written outside smoke-isolated path"
            )
    if evidence.extract_md_path:
        if "smoke_latest_one" not in evidence.extract_md_path:
            evidence.failure_reasons.append(
                "Markdown written outside smoke-isolated path"
            )

    # Status consistency checks (Phases 1-4)
    if filing.status_scraped != "success":
        evidence.failure_reasons.append(
            f"Unexpected scrape status: {filing.status_scraped}"
        )
    if filing.status_downloaded not in ("success", "failed"):
        evidence.failure_reasons.append(
            f"Unexpected download status: {filing.status_downloaded}"
        )

    # -----------------------------------------------------------------------
    # Phase 5: Analysis verification
    # -----------------------------------------------------------------------

    # Check analysis_json in database
    evidence.analysis_json_db_present = bool(filing.analysis_json)

    if filing.status_analyzed == "success" and filing.analysis_json:
        # Validate against AnalysisOutput schema
        try:
            parsed = AnalysisOutput.model_validate_json(filing.analysis_json)
            evidence.analysis_schema_valid = True

            # Extract classification details
            evidence.analysis_classification_primary = (
                parsed.classification.primary_type
            )
            evidence.analysis_classification_confidence = (
                parsed.classification.confidence
            )
            evidence.analysis_entities_count = len(parsed.entities)
            evidence.analysis_relationships_count = len(parsed.relationships)
            evidence.analysis_key_facts_count = len(parsed.key_facts)

            # Validate confidence range
            if not (0 <= parsed.classification.confidence <= 100):
                evidence.failure_reasons.append(
                    f"Classification confidence out of range: "
                    f"{parsed.classification.confidence}"
                )

            # Validate primary_type against CER taxonomy
            if parsed.classification.primary_type not in CER_TAXONOMY:
                evidence.failure_reasons.append(
                    f"Unknown primary_type: {parsed.classification.primary_type}"
                )

            # -----------------------------------------------------------
            # Phase 6: Deep analysis verification (Step H)
            # -----------------------------------------------------------
            _step_h_verify_deep_analysis(parsed, evidence)

        except Exception as exc:
            evidence.analysis_schema_valid = False
            evidence.failure_reasons.append(
                f"analysis_json failed schema validation: {exc}"
            )

        # Check on-disk analysis.json
        if docs and docs[0].local_path:
            analysis_json_path = (
                Path(docs[0].local_path).parent / "analysis.json"
            )
            if analysis_json_path.exists():
                evidence.analysis_json_path = str(analysis_json_path)
                # Verify it's in smoke namespace
                if "smoke_latest_one" not in str(analysis_json_path):
                    evidence.failure_reasons.append(
                        "analysis.json written outside smoke-isolated path"
                    )
            else:
                # Best-effort check -- not a hard failure
                logger.warning(
                    "analysis.json not found on disk at %s", analysis_json_path
                )

    elif filing.status_analyzed == "success":
        # Success status but no analysis_json -- could be a skip
        pass

    elif filing.status_analyzed == "failed":
        # Failed analysis -- check error_message is populated
        if not filing.error_message:
            evidence.failure_reasons.append(
                "status_analyzed=failed but no error_message set"
            )

    # Determine overall pass/fail
    evidence.passed = len(evidence.failure_reasons) == 0


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run_smoke_test() -> SmokeEvidence:
    """Execute the full smoke test (Phases 01-06) and return evidence."""
    evidence = SmokeEvidence()
    evidence.start_time = datetime.now(timezone.utc).isoformat()
    evidence.environment = {
        "db_path": SMOKE_DB_PATH,
        "filings_dir": SMOKE_FILINGS_DIR,
        "log_dir": SMOKE_LOG_DIR,
        "delay_seconds": 10,
        "lookback": "week",
        "pages": 1,
        "max_retries": 1,
        "analysis_model": "sonnet",
        "analysis_timeout": 300,
        "analysis_min_text_length": 100,
    }

    # Build settings
    scraper, pipeline, extraction, analysis = _build_smoke_settings()

    # Pre-run checks
    print("=" * 60)
    print("SMOKE TEST: Phases 01-06 (Live REGDOCS, Single Filing)")
    print("  Includes Phase 6: Deep Analysis Validation")
    print("=" * 60)
    print()
    print("[Pre-Run] Checking prerequisites...")
    preflight_failures = _pre_run_checks()
    if preflight_failures:
        for f in preflight_failures:
            print(f"  FAIL: {f}")
        evidence.failure_reasons.extend(preflight_failures)
        evidence.end_time = datetime.now(timezone.utc).isoformat()
        return evidence
    print("  All prerequisites OK")
    print()

    engine = None
    ext_result = None
    try:
        # Step A: Initialize
        print("[Step A] Initializing isolated smoke environment...")
        engine, session_factory = _step_a_initialize(pipeline)
        print("  Done")
        print()

        # Step B: Scrape listing page (no detail pages yet)
        print("[Step B] Scraping REGDOCS listing page...")
        print("  (Playwright discovery + DOM parse -- ~10-30s)")
        try:
            all_filings, strategy = _step_b_scrape_listing(scraper)
        except RuntimeError as exc:
            msg = f"Scrape failed: {exc}"
            print(f"  ABORT: {msg}")
            evidence.failure_reasons.append(msg)
            evidence.end_time = datetime.now(timezone.utc).isoformat()
            return evidence

        evidence.scrape_total_found = len(all_filings)
        evidence.scrape_strategy = strategy

        if not all_filings:
            msg = "Listing page returned zero filings"
            print(f"  ABORT: {msg}")
            evidence.failure_reasons.append(msg)
            evidence.end_time = datetime.now(timezone.utc).isoformat()
            return evidence

        print(f"  Found {len(all_filings)} filing(s) via {strategy}")
        print()

        # Step C: Select single target filing
        print("[Step C] Selecting upper-most filing...")
        target = _step_c_select_target(all_filings)
        evidence.selected_filing_id = target.filing_id
        print(f"  Target: {target.filing_id} - {(target.title or '')[:60]}")
        print()

        with session_factory() as session:
            # Step D: Enrich target with documents and persist
            print("[Step D] Fetching detail page for document URLs...")
            print("  (Single Playwright page visit -- ~10s)")
            db_filing = _step_d_enrich_and_persist(
                session, target, scraper
            )
            if db_filing is None:
                evidence.failure_reasons.append(
                    "No documents found for target filing"
                )
                evidence.end_time = datetime.now(timezone.utc).isoformat()
                return evidence
            print(f"  1 document persisted to smoke DB")
            print()

            # Step E: Download
            print("[Step E] Downloading PDF (10s pacing)...")
            dl_result = _step_e_download(session, pipeline, scraper)
            evidence.download_attempted = dl_result.filings_attempted
            evidence.download_succeeded = dl_result.filings_succeeded
            evidence.download_failed = dl_result.filings_failed
            evidence.download_doc_count = dl_result.total_pdfs_downloaded
            evidence.download_errors = list(dl_result.errors)

            if dl_result.filings_succeeded == 0:
                msg = f"Download failed: {dl_result.errors}"
                print(f"  FAIL: {msg}")
                evidence.failure_reasons.append(msg)
            else:
                print(
                    f"  Downloaded {dl_result.total_pdfs_downloaded} PDF(s), "
                    f"{dl_result.total_bytes} bytes"
                )
            print()

            # Step F: Extract (only if download succeeded)
            if dl_result.filings_succeeded > 0:
                print("[Step F] Extracting text from PDF...")
                ext_result = _step_f_extract(session, extraction)
                evidence.extract_errors = list(ext_result.errors)

                if ext_result.filings_succeeded == 0:
                    msg = f"Extraction failed: {ext_result.errors}"
                    print(f"  FAIL: {msg}")
                    evidence.failure_reasons.append(msg)
                else:
                    print(
                        f"  Extracted {ext_result.total_docs_extracted} document(s)"
                    )
            else:
                print("[Step F] Skipped -- download did not succeed")
            print()

            # Step G: Analyze (only if extraction succeeded)
            if (
                dl_result.filings_succeeded > 0
                and ext_result is not None
                and ext_result.filings_succeeded > 0
            ):
                print("[Step G] Analyzing filing text with Claude CLI...")
                print("  (Single LLM call -- may take 30-120s)")
                analysis_result = _step_g_analyze(session, analysis)
                evidence.analysis_attempted = analysis_result.filings_attempted
                evidence.analysis_succeeded = analysis_result.filings_succeeded
                evidence.analysis_failed = analysis_result.filings_failed
                evidence.analysis_skipped = analysis_result.filings_skipped
                evidence.analysis_total_cost_usd = (
                    analysis_result.total_cost_usd
                )
                evidence.analysis_errors = list(analysis_result.errors)

                if analysis_result.filings_succeeded > 0:
                    print(
                        f"  Analysis succeeded: "
                        f"{analysis_result.filings_succeeded} filing(s), "
                        f"cost=${analysis_result.total_cost_usd:.4f}"
                    )
                elif analysis_result.filings_skipped > 0:
                    print(
                        f"  Analysis skipped: "
                        f"{analysis_result.filings_skipped} filing(s)"
                    )
                elif analysis_result.filings_failed > 0:
                    msg = f"Analysis failed: {analysis_result.errors}"
                    print(f"  FAIL: {msg}")
                    evidence.failure_reasons.append(msg)
                else:
                    print("  No filings pending analysis")
            else:
                print("[Step G] Skipped -- extraction did not succeed")
            print()

            # Verification (includes Phase 6 Step H)
            print("[Verify] Checking final state (Phases 1-6)...")
            print("  (Includes Step H: Deep Analysis Field Validation)")
            _verify_and_collect(session, evidence)

    except Exception as exc:
        logger.exception("Smoke test aborted with unexpected error")
        evidence.failure_reasons.append(f"Unexpected error: {exc}")
    finally:
        evidence.end_time = datetime.now(timezone.utc).isoformat()
        if engine is not None:
            engine.dispose()

    return evidence


def main():
    evidence = run_smoke_test()

    # Print summary
    print()
    print("=" * 60)
    if evidence.passed:
        print("RESULT: PASS")
    else:
        print("RESULT: FAIL")
        for reason in evidence.failure_reasons:
            print(f"  - {reason}")
    print("=" * 60)
    print()

    # Print evidence summary
    print("Evidence Summary:")
    print(f"  Start:              {evidence.start_time}")
    print(f"  End:                {evidence.end_time}")
    print(f"  Filing ID:          {evidence.selected_filing_id}")
    print(f"  Strategy:           {evidence.scrape_strategy}")
    print(f"  Scrape found:       {evidence.scrape_total_found}")
    print(f"  Download:           {evidence.download_succeeded}/{evidence.download_attempted} succeeded")
    print(f"  PDF path:           {evidence.download_pdf_path}")
    print(f"  PDF size:           {evidence.download_file_size} bytes")
    print(f"  Extract method:     {evidence.extract_method}")
    print(f"  Markdown path:      {evidence.extract_md_path}")
    print(f"  Char count:         {evidence.extract_char_count}")
    print(f"  Page count:         {evidence.extract_page_count}")
    print()
    print("  Phase 5 (Analysis):")
    print(f"    Attempted:        {evidence.analysis_attempted}")
    print(f"    Succeeded:        {evidence.analysis_succeeded}")
    print(f"    Failed:           {evidence.analysis_failed}")
    print(f"    Skipped:          {evidence.analysis_skipped}")
    print(f"    Cost:             ${evidence.analysis_total_cost_usd:.4f}")
    print(f"    DB JSON present:  {evidence.analysis_json_db_present}")
    print(f"    Schema valid:     {evidence.analysis_schema_valid}")
    print(f"    Classification:   {evidence.analysis_classification_primary}")
    print(f"    Confidence:       {evidence.analysis_classification_confidence}")
    print(f"    Entities:         {evidence.analysis_entities_count}")
    print(f"    Relationships:    {evidence.analysis_relationships_count}")
    print(f"    Key facts:        {evidence.analysis_key_facts_count}")
    print(f"    JSON on disk:     {evidence.analysis_json_path}")
    print()
    print("  Phase 6 (Deep Analysis):")
    print(f"    Reg implications null:           {evidence.phase6_regulatory_implications_is_null}")
    print(f"    Reg implications summary:        {evidence.phase6_regulatory_implications_summary_present}")
    print(f"    Affected parties count:          {evidence.phase6_affected_parties_count}")
    print(f"    Dates count:                     {evidence.phase6_dates_count}")
    print(f"    Dates past:                      {evidence.phase6_dates_past_count}")
    print(f"    Dates upcoming:                  {evidence.phase6_dates_upcoming_count}")
    print(f"    Dates today:                     {evidence.phase6_dates_today_count}")
    print(f"    Dates invalid temporal status:   {evidence.phase6_dates_invalid_temporal_status_count}")
    print(f"    Sentiment present:               {evidence.phase6_sentiment_present}")
    print(f"    Sentiment category:              {evidence.phase6_sentiment_category}")
    print(f"    Sentiment nuance present:        {evidence.phase6_sentiment_nuance_present}")
    print(f"    Quotes count:                    {evidence.phase6_quotes_count}")
    print(f"    Quotes with source:              {evidence.phase6_quotes_with_source_count}")
    print(f"    Impact present:                  {evidence.phase6_impact_present}")
    print(f"    Impact score:                    {evidence.phase6_impact_score}")
    print(f"    Impact justification present:    {evidence.phase6_impact_justification_present}")
    print()
    print(f"  Status:             scraped={evidence.filing_status_scraped}, "
          f"downloaded={evidence.filing_status_downloaded}, "
          f"extracted={evidence.filing_status_extracted}, "
          f"analyzed={evidence.filing_status_analyzed}")
    print(f"  Duplicates OK:      {evidence.duplicate_check_passed}")
    print()

    # Save evidence to file
    log_dir = PROJECT_ROOT / SMOKE_LOG_DIR
    log_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = log_dir / "smoke_evidence.json"
    with open(evidence_path, "w") as f:
        json.dump(asdict(evidence), f, indent=2)
    print(f"Full evidence saved to: {evidence_path}")
    print(f"Smoke log:              {log_dir / 'pipeline.log'}")

    return 0 if evidence.passed else 1


if __name__ == "__main__":
    sys.exit(main())
