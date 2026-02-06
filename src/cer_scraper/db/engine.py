"""Database engine, session factory, and initialization.

This module provides the core database infrastructure:
    get_engine -- Create a SQLAlchemy engine for the SQLite database.
    init_db -- Create all tables idempotently using Base.metadata.create_all().
    get_session_factory -- Create a session factory bound to the engine.

Usage:
    engine = get_engine("data/state.db")
    init_db(engine)
    SessionFactory = get_session_factory(engine)
    with SessionFactory() as session:
        ...
"""

import logging
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base

logger = logging.getLogger(__name__)


def get_engine(db_path: str = "data/state.db") -> Engine:
    """Create SQLAlchemy engine for SQLite database.

    Ensures the parent directory exists before creating the engine
    to avoid 'unable to open database file' errors.

    Args:
        db_path: Path to the SQLite database file.

    Returns:
        A SQLAlchemy Engine instance.
    """
    # Resolve to absolute path to avoid issues with working directory changes
    resolved_path = Path(db_path).resolve()

    # Ensure parent directory exists (SQLite creates the file but not directories)
    resolved_path.parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(
        f"sqlite:///{resolved_path}",
        echo=False,  # Set True for SQL debugging
    )
    return engine


def init_db(engine: Engine) -> None:
    """Create all tables if they don't exist.

    This is idempotent -- it only creates tables that do not already exist.
    Safe to call on every application startup.

    Args:
        engine: SQLAlchemy Engine to create tables on.
    """
    Base.metadata.create_all(engine)
    logger.info("Database tables initialized")


def get_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create a session factory bound to the engine.

    Args:
        engine: SQLAlchemy Engine to bind sessions to.

    Returns:
        A sessionmaker instance that produces Session objects.
    """
    return sessionmaker(bind=engine)
