"""SQLAlchemy 2.0 ORM models for CER REGDOCS filing state tracking.

Models:
    Filing -- Core filing record with per-step pipeline status tracking.
    Document -- Individual documents (PDFs) linked to a filing.
    Analysis -- AI analysis output linked to a filing.
    RunHistory -- Audit log of each pipeline execution run.
"""

import datetime
from typing import Optional

from sqlalchemy import ForeignKey, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    pass


class Filing(Base):
    """A CER REGDOCS filing with per-step pipeline status tracking."""

    __tablename__ = "filings"

    id: Mapped[int] = mapped_column(primary_key=True)
    filing_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    date: Mapped[Optional[datetime.date]] = mapped_column(default=None)
    applicant: Mapped[Optional[str]] = mapped_column(String(500), default=None)
    filing_type: Mapped[Optional[str]] = mapped_column(String(200), default=None)
    proceeding_number: Mapped[Optional[str]] = mapped_column(
        String(100), index=True, default=None
    )
    title: Mapped[Optional[str]] = mapped_column(String(1000), default=None)
    url: Mapped[Optional[str]] = mapped_column(String(2000), default=None)

    # Per-step status tracking -- each pipeline stage tracked independently
    status_scraped: Mapped[str] = mapped_column(String(20), default="pending")
    status_downloaded: Mapped[str] = mapped_column(String(20), default="pending")
    status_extracted: Mapped[str] = mapped_column(String(20), default="pending")
    status_analyzed: Mapped[str] = mapped_column(String(20), default="pending")
    status_emailed: Mapped[str] = mapped_column(String(20), default="pending")

    # Failure tracking -- enables smart retry logic (skip after N failures)
    error_message: Mapped[Optional[str]] = mapped_column(Text, default=None)
    retry_count: Mapped[int] = mapped_column(default=0)

    # Timestamps
    created_at: Mapped[datetime.datetime] = mapped_column(
        server_default=func.now()
    )
    updated_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        onupdate=func.now(), default=None
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
    """An individual document (PDF) linked to a filing."""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    filing_id: Mapped[int] = mapped_column(ForeignKey("filings.id"))
    document_url: Mapped[str] = mapped_column(String(2000))
    filename: Mapped[Optional[str]] = mapped_column(String(500), default=None)
    local_path: Mapped[Optional[str]] = mapped_column(String(1000), default=None)
    download_status: Mapped[str] = mapped_column(String(20), default="pending")
    file_size_bytes: Mapped[Optional[int]] = mapped_column(default=None)
    content_type: Mapped[Optional[str]] = mapped_column(String(100), default=None)

    created_at: Mapped[datetime.datetime] = mapped_column(
        server_default=func.now()
    )

    filing: Mapped["Filing"] = relationship(back_populates="documents")

    def __repr__(self) -> str:
        return f"<Document(filename={self.filename!r}, status={self.download_status!r})>"


class Analysis(Base):
    """AI analysis output linked to a filing."""

    __tablename__ = "analyses"

    id: Mapped[int] = mapped_column(primary_key=True)
    filing_id: Mapped[int] = mapped_column(ForeignKey("filings.id"))
    analysis_type: Mapped[str] = mapped_column(String(50))
    output: Mapped[Optional[str]] = mapped_column(Text, default=None)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    error_message: Mapped[Optional[str]] = mapped_column(Text, default=None)
    duration_seconds: Mapped[Optional[float]] = mapped_column(default=None)

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
    completed_at: Mapped[Optional[datetime.datetime]] = mapped_column(default=None)
    total_filings_found: Mapped[int] = mapped_column(default=0)
    new_filings: Mapped[int] = mapped_column(default=0)
    processed_ok: Mapped[int] = mapped_column(default=0)
    processed_failed: Mapped[int] = mapped_column(default=0)
    duration_seconds: Mapped[Optional[float]] = mapped_column(default=None)

    def __repr__(self) -> str:
        return f"<RunHistory(id={self.id}, started={self.started_at})>"
