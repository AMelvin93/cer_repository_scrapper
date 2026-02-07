"""Pydantic settings models for CER REGDOCS scraper configuration.

Three settings classes load from separate YAML config files with environment
variable override support. Source priority (highest to lowest):

    1. Environment variables (with prefix, e.g., SCRAPER_DELAY_SECONDS)
    2. .env file (for secrets, e.g., EMAIL_APP_PASSWORD)
    3. YAML config file (e.g., config/scraper.yaml)
    4. Default values defined here

Config paths are resolved relative to PROJECT_ROOT so the application works
regardless of the current working directory (e.g., Windows Task Scheduler).
"""

from pathlib import Path

from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

# Resolve project root: settings.py -> config/ -> cer_scraper/ -> src/ -> repo root
PROJECT_ROOT = Path(__file__).resolve().parents[3]

_CONFIG_DIR = PROJECT_ROOT / "config"
_ENV_FILE = PROJECT_ROOT / ".env"


class ScraperSettings(BaseSettings):
    """Scraping behaviour: target URL, request pacing, user agent."""

    base_url: str = "https://apps.cer-rec.gc.ca/REGDOCS"
    recent_filings_path: str = "/Search/RecentFilings"
    delay_seconds: float = 2.0
    pages_to_scrape: int = 1
    user_agent: str = "CER-Filing-Monitor/1.0"

    # Phase 2: rate limiting
    delay_min_seconds: float = 1.0
    delay_max_seconds: float = 3.0

    # Phase 2: scraping scope
    lookback_period: str = "week"  # "day", "week", "month" -> maps to p=1, p=2, p=3

    # Phase 2: resilience
    max_retries: int = 3
    backoff_base: float = 2.0
    backoff_max: float = 30.0
    discovery_retries: int = 3

    # Phase 2: filtering
    filing_type_include: list[str] = []  # Empty = all types
    filing_type_exclude: list[str] = []
    applicant_filter: list[str] = []  # Empty = all applicants
    proceeding_filter: list[str] = []  # Empty = all proceedings

    model_config = SettingsConfigDict(
        yaml_file=str(_CONFIG_DIR / "scraper.yaml"),
        env_prefix="SCRAPER_",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            YamlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )


class EmailSettings(BaseSettings):
    """Email delivery: SMTP connection and credentials.

    Non-secret settings (host, port, TLS) come from config/email.yaml.
    Secrets (sender_address, app_password, recipient_address) come from .env
    or environment variables only -- they must NEVER appear in YAML files.
    """

    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    use_tls: bool = True
    sender_address: str = ""
    app_password: str = ""
    recipient_address: str = ""

    model_config = SettingsConfigDict(
        yaml_file=str(_CONFIG_DIR / "email.yaml"),
        env_file=str(_ENV_FILE),
        env_prefix="EMAIL_",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            YamlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )


class PipelineSettings(BaseSettings):
    """Pipeline operations: paths, logging, timeouts, retries."""

    data_dir: str = "data"
    db_path: str = "data/state.db"
    log_dir: str = "logs"
    log_max_bytes: int = 10_485_760  # 10MB
    log_backup_count: int = 5
    analysis_timeout_seconds: int = 300
    max_retry_count: int = 3

    model_config = SettingsConfigDict(
        yaml_file=str(_CONFIG_DIR / "pipeline.yaml"),
        env_prefix="PIPELINE_",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            YamlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )
