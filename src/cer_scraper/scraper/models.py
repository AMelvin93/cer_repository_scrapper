"""Pydantic models for scraped REGDOCS data.

ScrapedDocument represents a single downloadable document (PDF, Word, etc.).
ScrapedFiling represents a regulatory filing that may contain multiple documents.

Note: The ``date`` field uses ``datetime.date`` (fully qualified) rather than
a bare ``from datetime import date`` import.  Pydantic v2 resolves field type
annotations within the class namespace, so a field named ``date`` shadows the
bare ``date`` type and causes validation to accept only ``None``.  Using the
fully-qualified ``datetime.date`` avoids the name collision entirely.
"""

import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class ScrapedDocument(BaseModel):
    """A single document attached to a REGDOCS filing."""

    url: str
    filename: Optional[str] = None
    content_type: Optional[str] = None  # e.g., "application/pdf", "application/msword"


class ScrapedFiling(BaseModel):
    """A regulatory filing discovered from the REGDOCS recent-filings page."""

    filing_id: str
    date: Optional[datetime.date] = None
    applicant: Optional[str] = None
    filing_type: Optional[str] = None
    proceeding_number: Optional[str] = None
    title: Optional[str] = None
    url: Optional[str] = None
    documents: list[ScrapedDocument] = Field(default_factory=list)

    @field_validator("filing_id")
    @classmethod
    def filing_id_must_not_be_empty(cls, v: str) -> str:
        """Validate that filing_id is a non-empty string."""
        if not v.strip():
            raise ValueError("filing_id must be a non-empty string")
        return v

    @property
    def has_documents(self) -> bool:
        """Return True if this filing has at least one attached document."""
        return len(self.documents) > 0
