# Phase 1: Foundation & Configuration - Research

**Researched:** 2026-02-05
**Domain:** Python project foundation -- SQLAlchemy ORM, YAML config, structured logging, SQLite state tracking
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

#### Configuration layout
- YAML format for config files
- Split into separate files per concern (scraper.yaml, email.yaml, etc.) inside a `config/` directory
- Secrets (Gmail app password, etc.) live exclusively in `.env` -- config files never contain or reference secrets
- Config files handle settings (URLs, delays, paths); `.env` handles credentials

#### State tracking schema
- Per-step status tracking: each pipeline stage (scraped, downloaded, extracted, analyzed, emailed) tracked independently per filing
- Failure recording includes status, error message, and retry count -- enables smart retry logic (e.g., skip after N failures)
- Run history with timestamps preserved -- enables auditing when things were processed and how long they took
- SQLite database at `data/state.db`

#### Logging behavior
- Logs go to both rotating files and console (stdout)
- Log files stored in top-level `logs/` directory

#### Filing data model
- SQLAlchemy ORM for data access (declarative models, query builder)
- Normalized schema: separate `filings`, `documents`, and `analyses` tables with foreign keys
- `filings` table: filing ID, date, applicant, type, proceeding number, and metadata from REGDOCS
- `documents` table: linked to filings, tracks individual PDF URLs and download status
- `analyses` table: linked to filings, stores analysis output separately from raw filing data
- Migration approach at Claude's discretion (Alembic vs create_all)

### Claude's Discretion

- Log format (structured JSON vs human-readable text)
- Log rotation policy (size-based vs time-based, retention count)
- Exact log level configuration per component
- Migration approach (Alembic vs create_all)

### Deferred Ideas (OUT OF SCOPE)

None -- discussion stayed within phase scope.
</user_constraints>

## Summary

Phase 1 builds the foundation layer that every downstream component depends on: SQLAlchemy ORM models backed by SQLite, YAML-based configuration with `.env` secrets, and structured logging with file rotation. The user has locked the core technology choices (SQLAlchemy, YAML split config, SQLite at `data/state.db`, rotating log files in `logs/`), leaving format and policy details at my discretion.

The standard approach is: **pydantic-settings** with YAML extra for type-safe configuration loading from multiple YAML files + `.env`, **SQLAlchemy 2.0** with `DeclarativeBase` and `Mapped[]` annotations for the ORM layer, **`Base.metadata.create_all()`** for initial schema creation (no Alembic at this stage), and Python's **stdlib logging** with `RotatingFileHandler` using **python-json-logger** for JSON file output alongside human-readable console output.

All libraries are well-established, production-stable, and verified against current PyPI releases. The primary risk in this phase is low -- these are standard patterns with extensive documentation.

**Primary recommendation:** Use pydantic-settings[yaml] for config, SQLAlchemy 2.0 Mapped[] models with create_all(), stdlib logging with dual handlers (JSON file + text console), and keep everything under a `src/cer_scraper/` package from day one.

## Discretion Decisions

These are the recommendations for areas marked as Claude's Discretion:

### Log Format: JSON for files, human-readable for console
- **File logs:** Structured JSON via python-json-logger. Machine-parseable, searchable with standard tools (`jq`, `grep`), includes all metadata as fields.
- **Console logs:** Human-readable text with `{timestamp} {level} {component} {message}` format. Optimized for developer experience during development.
- **Rationale:** A batch pipeline that runs unattended needs machine-readable logs for debugging after the fact. Console stays human-friendly for interactive development.

### Log Rotation: Size-based, 10MB, 5 backups
- **Policy:** `RotatingFileHandler` with `maxBytes=10_485_760` (10MB) and `backupCount=5`.
- **Total max disk:** 60MB (current file + 5 backups).
- **Rationale:** Size-based is simpler and more predictable than time-based for a periodic batch job. At 10-50 filings per run every 2 hours, 10MB per file provides plenty of history. Time-based rotation adds complexity (midnight rollover, missed runs) with no benefit here.

### Log Levels: INFO console, DEBUG file
- **Console handler:** INFO level (shows progress, warnings, errors).
- **File handler:** DEBUG level (captures everything for post-mortem debugging).
- **Per-component:** Not needed at this scale. Use `logging.getLogger(__name__)` in each module; the root logger configuration handles level filtering.
- **Rationale:** The pipeline processes 10-50 items per run. Per-component level tuning adds configuration complexity for negligible value. If needed later, it is trivial to add.

### Migration Approach: create_all() (not Alembic)
- **Use `Base.metadata.create_all(engine)`** to create tables on first run.
- **No Alembic** at this stage.
- **Rationale:** This is a fresh project with no existing production data. The schema is being defined for the first time. Alembic adds setup overhead (alembic init, env.py, versions directory, migration scripts) that provides no value until the schema needs to change after production data exists. `create_all()` is idempotent -- it only creates tables that do not already exist. If schema evolution is needed later, Alembic can be added retroactively without data loss.

## Standard Stack

The established libraries for this phase:

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| SQLAlchemy | >=2.0.46 | ORM with declarative models, SQLite engine | The Python ORM standard. 2.0 style with `Mapped[]` + `mapped_column()` provides full type-checking support. Production-stable. |
| pydantic-settings[yaml] | >=2.12.0 | Type-safe config from YAML files + .env | Built-in YAML and dotenv source support with priority ordering. Validates config at load time. |
| PyYAML | >=6.0.3 | YAML parsing (dependency of pydantic-settings[yaml]) | Installed automatically as dependency of pydantic-settings[yaml]. |
| python-dotenv | >=1.2.1 | Load `.env` file for secrets | Industry standard for .env loading. Dependency of pydantic-settings. |
| python-json-logger | >=4.0.0 | JSON formatter for Python stdlib logging | Plugs into stdlib logging as a Formatter. Lightweight, focused, well-maintained. |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pydantic | >=2.10 | Data validation (dependency of pydantic-settings) | Installed automatically. Used for config model validation. |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| pydantic-settings | dataclasses + PyYAML + python-dotenv manually | More code, no validation, no type-safe loading. pydantic-settings handles the entire config loading pipeline. |
| python-json-logger | structlog | structlog is more powerful but heavier. python-json-logger is a simple Formatter drop-in that does exactly what we need. |
| create_all() | Alembic | Alembic adds migration tracking but requires setup overhead. Not needed for a fresh schema with no production data. |
| PyYAML | ruamel.yaml | ruamel.yaml preserves comments on round-trip, but we only read config files, never write them. PyYAML is simpler and is the dependency pydantic-settings uses. |

**Installation:**
```bash
uv add sqlalchemy pydantic-settings[yaml] python-json-logger
```

This pulls in as transitive dependencies: pydantic, PyYAML, python-dotenv, typing-extensions.

## Architecture Patterns

### Recommended Project Structure
```
cer_repository_scrapper/
    src/
        cer_scraper/
            __init__.py
            config/
                __init__.py          # Config loading functions
                settings.py          # Pydantic settings models
            db/
                __init__.py
                engine.py            # Engine + session factory
                models.py            # SQLAlchemy ORM models (Filing, Document, Analysis)
            logging/
                __init__.py
                setup.py             # Logging configuration
    config/
        scraper.yaml                 # Scraping settings (URLs, delays)
        email.yaml                   # Email settings (SMTP host, port, recipient)
        pipeline.yaml                # Pipeline settings (paths, timeouts)
    data/
        state.db                     # SQLite database (created at runtime)
    logs/
        pipeline.log                 # Log files (created at runtime)
    tests/
        __init__.py
        test_config.py
        test_models.py
        test_logging.py
    .env                             # Secrets (gitignored)
    .env.example                     # Template showing required env vars
    pyproject.toml
    main.py                          # Entry point
```

### Pattern 1: Pydantic Settings with YAML + .env Source Priority

**What:** Use pydantic-settings to load config from multiple YAML files and .env with a clear priority order: env vars > .env > YAML files.

**When to use:** Every time the application starts, to build a validated, typed configuration object.

**Example:**
```python
# src/cer_scraper/config/settings.py
# Source: https://docs.pydantic.dev/latest/concepts/pydantic_settings/

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class ScraperSettings(BaseSettings):
    """Settings loaded from config/scraper.yaml"""
    base_url: str = "https://apps.cer-rec.gc.ca/REGDOCS"
    recent_filings_path: str = "/Search/RecentFilings"
    delay_seconds: float = 2.0
    pages_to_scrape: int = 1

    model_config = SettingsConfigDict(
        yaml_file="config/scraper.yaml",
        env_prefix="SCRAPER_",
    )

class EmailSettings(BaseSettings):
    """Settings loaded from config/email.yaml + .env for secrets"""
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    sender_address: str = ""      # From .env: EMAIL_SENDER_ADDRESS
    app_password: str = ""        # From .env: EMAIL_APP_PASSWORD
    recipient_address: str = ""   # From .env: EMAIL_RECIPIENT_ADDRESS

    model_config = SettingsConfigDict(
        yaml_file="config/email.yaml",
        env_file=".env",
        env_prefix="EMAIL_",
    )

class PipelineSettings(BaseSettings):
    """Settings loaded from config/pipeline.yaml"""
    data_dir: str = "data"
    db_path: str = "data/state.db"
    log_dir: str = "logs"
    log_max_bytes: int = 10_485_760  # 10MB
    log_backup_count: int = 5
    analysis_timeout_seconds: int = 300

    model_config = SettingsConfigDict(
        yaml_file="config/pipeline.yaml",
        env_prefix="PIPELINE_",
    )
```

### Pattern 2: SQLAlchemy 2.0 Declarative Models with Mapped[]

**What:** Define ORM models using the modern SQLAlchemy 2.0 syntax with `DeclarativeBase`, `Mapped[]` type annotations, and `mapped_column()`.

**When to use:** For all database table definitions.

**Example:**
```python
# src/cer_scraper/db/models.py
# Source: https://docs.sqlalchemy.org/en/20/orm/quickstart.html

import datetime
from typing import Optional
from sqlalchemy import ForeignKey, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Filing(Base):
    __tablename__ = "filings"

    id: Mapped[int] = mapped_column(primary_key=True)
    filing_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    date: Mapped[Optional[datetime.date]]
    applicant: Mapped[Optional[str]] = mapped_column(String(500))
    filing_type: Mapped[Optional[str]] = mapped_column(String(200))
    proceeding_number: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    title: Mapped[Optional[str]] = mapped_column(String(1000))
    url: Mapped[Optional[str]] = mapped_column(String(2000))

    # Per-step status tracking
    status_scraped: Mapped[str] = mapped_column(String(20), default="pending")
    status_downloaded: Mapped[str] = mapped_column(String(20), default="pending")
    status_extracted: Mapped[str] = mapped_column(String(20), default="pending")
    status_analyzed: Mapped[str] = mapped_column(String(20), default="pending")
    status_emailed: Mapped[str] = mapped_column(String(20), default="pending")

    # Failure tracking
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(default=0)

    # Timestamps
    created_at: Mapped[datetime.datetime] = mapped_column(
        server_default=func.now()
    )
    updated_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        onupdate=func.now()
    )

    # Relationships
    documents: Mapped[list["Document"]] = relationship(
        back_populates="filing", cascade="all, delete-orphan"
    )
    analyses: Mapped[list["Analysis"]] = relationship(
        back_populates="filing", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Filing(filing_id={self.filing_id!r}, applicant={self.applicant!r})>"


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    filing_id: Mapped[int] = mapped_column(ForeignKey("filings.id"))
    document_url: Mapped[str] = mapped_column(String(2000))
    filename: Mapped[Optional[str]] = mapped_column(String(500))
    local_path: Mapped[Optional[str]] = mapped_column(String(1000))
    download_status: Mapped[str] = mapped_column(String(20), default="pending")
    file_size_bytes: Mapped[Optional[int]]
    content_type: Mapped[Optional[str]] = mapped_column(String(100))

    created_at: Mapped[datetime.datetime] = mapped_column(
        server_default=func.now()
    )

    filing: Mapped["Filing"] = relationship(back_populates="documents")

    def __repr__(self) -> str:
        return f"<Document(filename={self.filename!r}, status={self.download_status!r})>"


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[int] = mapped_column(primary_key=True)
    filing_id: Mapped[int] = mapped_column(ForeignKey("filings.id"))
    analysis_type: Mapped[str] = mapped_column(String(50))  # e.g., "full", "summary", "entity"
    output: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    duration_seconds: Mapped[Optional[float]]

    created_at: Mapped[datetime.datetime] = mapped_column(
        server_default=func.now()
    )

    filing: Mapped["Filing"] = relationship(back_populates="analyses")

    def __repr__(self) -> str:
        return f"<Analysis(type={self.analysis_type!r}, status={self.status!r})>"


class RunHistory(Base):
    """Tracks each pipeline run for auditing."""
    __tablename__ = "run_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime.datetime] = mapped_column(
        server_default=func.now()
    )
    completed_at: Mapped[Optional[datetime.datetime]]
    total_filings_found: Mapped[int] = mapped_column(default=0)
    new_filings: Mapped[int] = mapped_column(default=0)
    processed_ok: Mapped[int] = mapped_column(default=0)
    processed_failed: Mapped[int] = mapped_column(default=0)
    duration_seconds: Mapped[Optional[float]]

    def __repr__(self) -> str:
        return f"<RunHistory(id={self.id}, started={self.started_at})>"
```

### Pattern 3: Engine and Session Factory

**What:** Create the SQLAlchemy engine and session factory once, reuse across the application.

**When to use:** At application startup, before any database operations.

**Example:**
```python
# src/cer_scraper/db/engine.py
# Source: https://docs.sqlalchemy.org/en/20/dialects/sqlite.html

from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from .models import Base


def get_engine(db_path: str = "data/state.db"):
    """Create SQLAlchemy engine for SQLite database."""
    # Ensure parent directory exists
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(
        f"sqlite:///{db_path}",
        echo=False,  # Set True for SQL debugging
    )
    return engine


def init_db(engine) -> None:
    """Create all tables if they don't exist."""
    Base.metadata.create_all(engine)


def get_session_factory(engine) -> sessionmaker[Session]:
    """Create a session factory bound to the engine."""
    return sessionmaker(bind=engine)
```

### Pattern 4: Dual-Handler Logging Setup

**What:** Configure logging with JSON output to rotating files and human-readable output to console.

**When to use:** Once at application startup, before any other code runs.

**Example:**
```python
# src/cer_scraper/logging/setup.py
# Source: https://docs.python.org/3/howto/logging-cookbook.html

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
    """Configure dual-handler logging: JSON file + text console."""
    # Ensure log directory exists
    Path(log_dir).mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)  # Capture everything; handlers filter

    # --- File handler: JSON format, rotating ---
    file_handler = logging.handlers.RotatingFileHandler(
        filename=Path(log_dir) / "pipeline.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(log_level_file)
    json_formatter = JsonFormatter(
        fmt="%(asctime)s %(name)s %(levelname)s %(message)s",
        rename_fields={"asctime": "timestamp", "levelname": "level", "name": "component"},
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
```

### Anti-Patterns to Avoid

- **Mixing secrets into YAML files:** Never put passwords, API keys, or tokens in YAML config files. They go in `.env` only. The YAML files should be committed to version control; `.env` must be gitignored.
- **Using the old SQLAlchemy `Column()` syntax:** Always use `Mapped[]` + `mapped_column()` for type safety and IDE support. The legacy `Column(Integer, ...)` pattern lacks type annotations.
- **Creating engines per request/call:** Create the engine once at startup. SQLAlchemy engines manage their own connection pool.
- **Using `logging.basicConfig()` in library code:** Only call logging setup in `main.py`. Module code should use `logging.getLogger(__name__)` and never configure handlers.
- **Hardcoding file paths:** All paths (db, logs, config) should come from configuration, not be scattered as string literals.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| YAML config + .env loading with validation | Custom loader with yaml.safe_load + os.environ + type casting | pydantic-settings[yaml] | Handles source priority, type validation, nested models, default values, env var prefix mapping. Custom code would reinvent all of this poorly. |
| JSON log formatting | Custom logging.Formatter subclass that builds JSON strings | python-json-logger `JsonFormatter` | Handles edge cases (exception serialization, extra fields, timestamp formatting, nested objects). A hand-rolled JSON formatter will miss these. |
| Database schema creation | Raw `sqlite3.execute("CREATE TABLE ...")` | SQLAlchemy `create_all()` | Models define the schema once; `create_all()` generates correct DDL. Raw SQL means maintaining schema in two places. |
| Session lifecycle management | Manual `connection.execute()` with try/finally | SQLAlchemy `sessionmaker` + context manager | Proper transaction handling, connection pooling, and cleanup. Manual management leaks connections. |
| .env file parsing | Custom regex or split-based parser | python-dotenv (via pydantic-settings) | Handles quoting, multiline values, comments, export prefix. Custom parsing will break on edge cases. |

**Key insight:** The config loading and validation problem is deceptively complex. Handling multiple sources (YAML files, .env, env vars) with priority ordering, type coercion, validation, and defaults is exactly what pydantic-settings was built for. Building this manually with PyYAML + python-dotenv + dataclasses would take 100+ lines and still miss edge cases.

## Common Pitfalls

### Pitfall 1: SQLite func.now() Returns String, Not Datetime
**What goes wrong:** `server_default=func.now()` in SQLite stores timestamps as TEXT strings, not native datetime objects. SQLAlchemy handles the conversion on read, but raw SQL queries return strings.
**Why it happens:** SQLite has no native DATETIME type. It stores everything as TEXT, REAL, or INTEGER.
**How to avoid:** Always access timestamps through SQLAlchemy ORM (which handles conversion). If raw SQL is needed, use `datetime()` SQL function for comparisons. Test that timestamp comparisons work correctly in queries.
**Warning signs:** Queries like `WHERE created_at > '2026-01-01'` working inconsistently.

### Pitfall 2: pydantic-settings Source Priority Confusion
**What goes wrong:** Environment variables unexpectedly override YAML config values, or YAML values do not load because .env takes precedence.
**Why it happens:** pydantic-settings has a default priority order. Without explicitly customizing `settings_customise_sources`, the behavior may not match expectations.
**How to avoid:** Explicitly define source priority in `settings_customise_sources`. Document the priority order. Test with conflicting values to verify behavior.
**Warning signs:** Config values differ between local development and production despite identical YAML files.

### Pitfall 3: SQLAlchemy Session Not Committed
**What goes wrong:** Data appears to be saved (no errors) but is not persisted to the database.
**Why it happens:** SQLAlchemy sessions require explicit `session.commit()`. Without it, changes are lost when the session closes.
**How to avoid:** Use the context manager pattern: `with Session(engine) as session: ... session.commit()`. Or use `session.begin()` which auto-commits on block exit.
**Warning signs:** Data visible within the session but gone after restart.

### Pitfall 4: Logging Configuration Applied Too Late
**What goes wrong:** Early startup messages (config loading, DB initialization) are not captured in log files.
**Why it happens:** Logging setup runs after the code that produces the first log messages.
**How to avoid:** Call `setup_logging()` as the very first thing in `main()`, before loading config or initializing the database. Use a two-phase startup: minimal logging first, full configuration second.
**Warning signs:** Missing log entries for startup phase.

### Pitfall 5: SQLite File Path Not Created
**What goes wrong:** `create_engine("sqlite:///data/state.db")` fails because the `data/` directory does not exist.
**Why it happens:** SQLite creates the database file but not parent directories.
**How to avoid:** Always call `Path(db_path).parent.mkdir(parents=True, exist_ok=True)` before creating the engine. Same for the `logs/` directory.
**Warning signs:** `OperationalError: unable to open database file`.

### Pitfall 6: YAML Config Files Not Found (Relative Paths)
**What goes wrong:** `yaml_file="config/scraper.yaml"` fails when the script is run from a different working directory (e.g., Windows Task Scheduler).
**Why it happens:** Relative paths resolve from the current working directory, which varies by invocation context.
**How to avoid:** Resolve config paths relative to the project root. Use `Path(__file__).resolve().parents[N]` to find the project root, or pass the project root as a CLI argument / environment variable.
**Warning signs:** Works in development, fails when scheduled.

## Code Examples

### Complete Config YAML File Structure

```yaml
# config/scraper.yaml
base_url: "https://apps.cer-rec.gc.ca/REGDOCS"
recent_filings_path: "/Search/RecentFilings"
delay_seconds: 2.0
pages_to_scrape: 1
user_agent: "CER-Filing-Monitor/1.0"
```

```yaml
# config/email.yaml
smtp_host: "smtp.gmail.com"
smtp_port: 587
use_tls: true
```

```yaml
# config/pipeline.yaml
data_dir: "data"
db_path: "data/state.db"
log_dir: "logs"
log_max_bytes: 10485760
log_backup_count: 5
analysis_timeout_seconds: 300
max_retry_count: 3
```

### .env.example Template

```bash
# .env.example -- Copy to .env and fill in real values
# NEVER commit .env to version control

# Email credentials (Gmail with app password)
EMAIL_SENDER_ADDRESS=your.email@gmail.com
EMAIL_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
EMAIL_RECIPIENT_ADDRESS=recipient@example.com
```

### .gitignore Additions

```gitignore
# Secrets
.env

# Runtime data
data/
logs/

# Python
__pycache__/
*.pyc
.venv/
```

### Querying Unprocessed Filings

```python
# Source: https://docs.sqlalchemy.org/en/20/orm/quickstart.html
from sqlalchemy import select
from sqlalchemy.orm import Session
from cer_scraper.db.models import Filing

def get_unprocessed_filings(session: Session) -> list[Filing]:
    """Return filings that have not been fully processed."""
    stmt = select(Filing).where(
        (Filing.status_emailed != "success") &
        (Filing.retry_count < 3)  # Skip after 3 failures
    )
    return list(session.scalars(stmt).all())

def mark_step_complete(
    session: Session,
    filing_id: str,
    step: str,
    status: str = "success",
    error: str | None = None,
) -> None:
    """Update a specific pipeline step status for a filing."""
    stmt = select(Filing).where(Filing.filing_id == filing_id)
    filing = session.scalars(stmt).one()

    setattr(filing, f"status_{step}", status)
    if error:
        filing.error_message = error
        filing.retry_count += 1

    session.commit()
```

### Using Logging in Module Code

```python
# In any module, e.g., src/cer_scraper/db/engine.py
import logging

logger = logging.getLogger(__name__)

def init_db(engine):
    """Create all tables if they don't exist."""
    logger.info("Initializing database tables")
    Base.metadata.create_all(engine)
    logger.debug("Database initialization complete")
```

### Application Entry Point Pattern

```python
# main.py
from pathlib import Path
from cer_scraper.logging.setup import setup_logging
from cer_scraper.config.settings import PipelineSettings
from cer_scraper.db.engine import get_engine, init_db, get_session_factory

def main():
    # 1. Setup logging FIRST (before any other imports that might log)
    setup_logging()

    import logging
    logger = logging.getLogger(__name__)
    logger.info("CER REGDOCS Scraper starting")

    # 2. Load configuration
    pipeline_config = PipelineSettings()
    logger.info("Configuration loaded", extra={"db_path": pipeline_config.db_path})

    # 3. Initialize database
    engine = get_engine(pipeline_config.db_path)
    init_db(engine)
    SessionFactory = get_session_factory(engine)
    logger.info("Database initialized")

    # 4. Ready for pipeline operations (implemented in later phases)
    with SessionFactory() as session:
        logger.info("Application ready")

if __name__ == "__main__":
    main()
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `Column(Integer, ...)` | `Mapped[int] = mapped_column(...)` | SQLAlchemy 2.0 (Jan 2023) | Full type safety, IDE autocomplete, static analysis support |
| `declarative_base()` function | `class Base(DeclarativeBase)` | SQLAlchemy 2.0 (Jan 2023) | Cleaner class hierarchy, better type inference |
| `session.query(Model)` | `select(Model)` with `session.scalars()` | SQLAlchemy 2.0 (Jan 2023) | Unified Core/ORM query interface, better composability |
| `configparser` / raw `os.environ` | pydantic-settings with sources | pydantic-settings 2.0+ (2023) | Type validation, multiple sources, nested config |
| `logging.Formatter` with custom `format()` | python-json-logger `JsonFormatter` | Stable since 2020+ | Drop-in JSON formatting without custom code |

**Deprecated/outdated:**
- `declarative_base()` function: Replaced by `DeclarativeBase` class. Still works but is legacy.
- `session.query()`: Replaced by `select()` + `session.scalars()`. Still works but is "1.x style."
- PyYAML `yaml.load()` without Loader: Security risk. Always use `yaml.safe_load()` or explicit `Loader=yaml.SafeLoader`.

## Open Questions

1. **pydantic-settings with multiple separate YAML files (one per concern)**
   - What we know: pydantic-settings supports `yaml_file` as a list for multiple files, but the documented pattern loads them into a single Settings model. The user wants split config (scraper.yaml, email.yaml, pipeline.yaml).
   - What's unclear: Whether having separate pydantic-settings models each pointing to their own YAML file works cleanly, or whether there are edge cases with source priority across models.
   - Recommendation: Use separate pydantic BaseSettings subclasses, each with its own `yaml_file`. This is the cleanest separation. Test during implementation.

2. **SQLAlchemy func.now() behavior on SQLite**
   - What we know: SQLite stores timestamps as TEXT. SQLAlchemy handles conversion on ORM reads.
   - What's unclear: Whether `onupdate=func.now()` works correctly with SQLite (some reports suggest it only fires for ORM updates, not raw SQL).
   - Recommendation: Verify with a simple test during implementation. If `onupdate` is unreliable, set `updated_at` explicitly in Python code before commit.

## Sources

### Primary (HIGH confidence)
- [SQLAlchemy 2.0 ORM Quick Start](https://docs.sqlalchemy.org/en/20/orm/quickstart.html) -- DeclarativeBase, Mapped[], relationships, session usage
- [SQLAlchemy 2.0 Declarative Tables](https://docs.sqlalchemy.org/en/20/orm/declarative_tables.html) -- Column types, nullable, defaults, server_default
- [SQLAlchemy SQLite Dialect](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html) -- Engine URI format, Windows paths, connection pool
- [Python Logging Cookbook](https://docs.python.org/3/howto/logging-cookbook.html) -- RotatingFileHandler, dual handlers, dictConfig
- [Pydantic Settings Documentation](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) -- YAML source, .env source, source priority
- [PyPI: SQLAlchemy 2.0.46](https://pypi.org/project/SQLAlchemy/) -- Released 2026-01-21
- [PyPI: pydantic-settings 2.12.0](https://pypi.org/project/pydantic-settings/) -- Released 2025-11-10, yaml extra available
- [PyPI: PyYAML 6.0.3](https://pypi.org/project/PyYAML/) -- Released 2025-09-25
- [PyPI: python-dotenv 1.2.1](https://pypi.org/project/python-dotenv/) -- Released 2025-10-26
- [PyPI: python-json-logger 4.0.0](https://pypi.org/project/python-json-logger/) -- Released 2025-10-06

### Secondary (MEDIUM confidence)
- [DeepWiki: pydantic-settings Configuration Files](https://deepwiki.com/pydantic/pydantic-settings/3.2-configuration-files) -- Multi-YAML examples, section support
- [Better Stack: Python Logging Best Practices](https://betterstack.com/community/guides/logging/python/python-logging-best-practices/) -- RotatingFileHandler sizing, JSON formatting patterns

### Tertiary (LOW confidence)
- Multiple YAML files with separate pydantic-settings models -- pattern synthesized from documentation examples, not explicitly documented as a pattern. Needs validation during implementation.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all libraries verified on PyPI with current versions, official docs consulted
- Architecture: HIGH -- patterns from official SQLAlchemy and Python logging documentation
- Pitfalls: HIGH -- SQLite timestamp behavior and config path issues are well-documented
- Discretion decisions: HIGH -- logging format/rotation choices follow established best practices for batch pipelines

**Research date:** 2026-02-05
**Valid until:** 2026-03-07 (30 days -- all libraries are stable, slow-moving)
