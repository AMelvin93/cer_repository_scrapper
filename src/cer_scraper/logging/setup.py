"""Dual-handler logging setup: JSON rotating file + human-readable console.

This module configures Python's stdlib logging with two handlers:
    1. RotatingFileHandler -- JSON format, DEBUG level, 10MB rotation, 5 backups
    2. StreamHandler -- Text format, INFO level, for developer console

Call setup_logging() once at application startup, before any other code runs.
Module code throughout the project should use logging.getLogger(__name__).
"""

import logging
import logging.handlers
from pathlib import Path

from pythonjsonlogger.json import JsonFormatter


def setup_logging(
    log_dir: str = "logs",
    log_level_file: int = logging.DEBUG,
    log_level_console: int = logging.INFO,
    max_bytes: int = 10_485_760,  # 10MB
    backup_count: int = 5,
) -> None:
    """Configure dual-handler logging: JSON file + text console.

    Creates the log directory if it does not exist. Clears any existing
    handlers on the root logger to prevent duplicate output if called
    multiple times.

    Args:
        log_dir: Directory for log files.
        log_level_file: Logging level for the file handler (default DEBUG).
        log_level_console: Logging level for the console handler (default INFO).
        max_bytes: Maximum size per log file before rotation (default 10MB).
        backup_count: Number of rotated backup files to keep (default 5).
    """
    # Ensure log directory exists
    Path(log_dir).mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)  # Capture everything; handlers filter

    # Clear any existing handlers to prevent duplicates if called multiple times
    root_logger.handlers.clear()

    # --- File handler: JSON format, rotating ---
    file_handler = logging.handlers.RotatingFileHandler(
        filename=str(Path(log_dir) / "pipeline.log"),
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(log_level_file)

    json_formatter = JsonFormatter(
        fmt="%(asctime)s %(name)s %(levelname)s %(message)s",
        rename_fields={
            "asctime": "timestamp",
            "levelname": "level",
            "name": "component",
        },
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    file_handler.setFormatter(json_formatter)

    # --- Console handler: human-readable text ---
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level_console)

    text_formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_handler.setFormatter(text_formatter)

    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
