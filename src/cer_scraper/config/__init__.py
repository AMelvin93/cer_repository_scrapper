"""Configuration package -- typed, validated settings from YAML + .env."""

from .settings import EmailSettings, PipelineSettings, ScraperSettings

__all__ = [
    "EmailSettings",
    "PipelineSettings",
    "ScraperSettings",
    "load_all_settings",
]


def load_all_settings() -> tuple[ScraperSettings, EmailSettings, PipelineSettings]:
    """Load and return all configuration objects.

    Returns a tuple of (ScraperSettings, EmailSettings, PipelineSettings),
    each populated from its own YAML file with environment variable overrides.
    """
    return ScraperSettings(), EmailSettings(), PipelineSettings()
