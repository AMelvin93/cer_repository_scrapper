"""CER REGDOCS Filing Monitor -- application entry point.

Startup sequence:
    1. Load pipeline configuration (needed for log_dir, db_path, retry settings)
    2. Setup logging (must happen before any code that logs)
    3. Load remaining configuration (scraper, email)
    4. Initialize database (engine, tables, session factory)
    5. Report readiness (database path, unprocessed filing count)

Pipeline stages will be wired in Phase 9.
"""

import logging
import sys

from cer_scraper.config import EmailSettings, PipelineSettings, ScraperSettings
from cer_scraper.db import (
    get_engine,
    get_session_factory,
    get_unprocessed_filings,
    init_db,
)
from cer_scraper.logging import setup_logging

logger = logging.getLogger(__name__)


def main() -> None:
    """Run the CER REGDOCS Filing Monitor pipeline."""
    # 1. Load pipeline config first -- needed for logging and database paths
    pipeline = PipelineSettings()

    # 2. Setup logging BEFORE anything else logs
    setup_logging(
        log_dir=pipeline.log_dir,
        max_bytes=pipeline.log_max_bytes,
        backup_count=pipeline.log_backup_count,
    )

    logger.info("CER REGDOCS Filing Monitor starting")

    # 3. Load remaining configuration
    scraper = ScraperSettings()
    email = EmailSettings()

    # Log non-sensitive config values (never log secrets like app_password)
    logger.info(
        "Config loaded -- scraper: base_url=%s, delay=%s, pages=%s",
        scraper.base_url,
        scraper.delay_seconds,
        scraper.pages_to_scrape,
    )
    logger.info(
        "Config loaded -- email: smtp_host=%s, smtp_port=%s, use_tls=%s",
        email.smtp_host,
        email.smtp_port,
        email.use_tls,
    )
    logger.info(
        "Config loaded -- pipeline: db_path=%s, log_dir=%s, max_retries=%s",
        pipeline.db_path,
        pipeline.log_dir,
        pipeline.max_retry_count,
    )

    # 4. Initialize database
    engine = get_engine(pipeline.db_path)
    init_db(engine)
    session_factory = get_session_factory(engine)

    logger.info("Database initialized at %s", pipeline.db_path)

    # 5. Report readiness
    with session_factory() as session:
        unprocessed = get_unprocessed_filings(
            session, max_retries=pipeline.max_retry_count
        )
        logger.info(
            "Application ready -- %s unprocessed filing(s) in queue",
            len(unprocessed),
        )

    # --- Pipeline stages will be wired here in Phase 9 ---
    # Phase 2: Scraper discovers new filings
    # Phase 3: Downloader fetches PDFs
    # Phase 4: Extractor pulls text from PDFs
    # Phase 5: Analyzer sends text to Claude for analysis
    # Phase 6: Formatter builds email content
    # Phase 8: Emailer delivers to recipient

    logger.info("Run complete")
    engine.dispose()


if __name__ == "__main__":
    sys.exit(main() or 0)
