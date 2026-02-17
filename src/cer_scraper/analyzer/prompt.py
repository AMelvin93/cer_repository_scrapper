"""Prompt template management for CER filing analysis.

Loads the prompt template from disk, computes a version hash for
traceability, builds a human-readable JSON schema description matching
the AnalysisOutput Pydantic model, and fills template placeholders with
filing data and document text.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def load_prompt_template(template_path: Path) -> tuple[str, str]:
    """Load prompt template from disk and compute its version hash.

    Args:
        template_path: Absolute or relative path to the template file.

    Returns:
        Tuple of (template_content, version_hash) where version_hash is
        the first 12 hex characters of the SHA-256 digest.

    Raises:
        FileNotFoundError: If the template file does not exist.
    """
    if not template_path.exists():
        msg = f"Prompt template not found: {template_path}"
        raise FileNotFoundError(msg)

    content = template_path.read_text(encoding="utf-8")
    version_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]
    logger.info(
        "Loaded prompt template: %s (version %s, %d chars)",
        template_path.name,
        version_hash,
        len(content),
    )
    return content, version_hash


def get_json_schema_description() -> str:
    """Return a human-readable JSON schema description for Claude.

    The description matches the AnalysisOutput Pydantic model fields
    exactly, including CER-specific taxonomy, entity types, and role
    options.  Formatted as a readable JSON example with inline comments
    rather than formal JSON Schema spec -- optimised for LLM consumption.

    Returns:
        Multi-line string describing the expected JSON output structure.
    """
    return """\
{
  "summary": "2-3 sentence plain-language overview of the filing.",

  "entities": [
    {
      "name": "Entity name as it appears in the text",
      "type": "company | facility | location | regulatory_reference",
      "role": "applicant | intervener | regulator | contractor | operator | landowner | consultant | other | null"
    }
  ],

  "relationships": [
    {
      "subject": "The entity performing the action",
      "predicate": "The action or relationship type",
      "object": "The entity or thing being acted upon",
      "context": "Optional additional context (or null)"
    }
  ],

  "classification": {
    "primary_type": "One of: Application, Order, Decision, Compliance Filing, Correspondence, Notice, Conditions Compliance, Financial Submission, Safety Report, Environmental Assessment",
    "tags": ["lowercase-hyphenated-topic-tags"],
    "confidence": 85,
    "justification": "1-2 sentence explanation of why this classification was chosen."
  },

  "key_facts": [
    "Short bullet-point string for each important fact (3-8 items)"
  ],

  "regulatory_implications": {
    "summary": "2-3 sentences describing the regulatory impact. What does this filing mean for affected parties?",
    "affected_parties": ["Specific company/community names when mentioned, or general categories like 'pipeline operators'"]
  },

  "dates": [
    {
      "date": "2026-03-15",
      "type": "deadline | hearing | comment_period | effective | filing | other",
      "description": "What this date refers to",
      "temporal_status": "past | upcoming | today"
    }
  ],

  "sentiment": {
    "category": "routine | notable | urgent | adversarial | cooperative",
    "nuance": "Free-form description of tone, e.g. 'cautiously supportive with procedural concerns'"
  },

  "quotes": [
    {
      "text": "1-2 sentence quote that captures a key point from the filing",
      "source_location": "Document name, page number, or section heading (or null)"
    }
  ],

  "impact": {
    "score": 3,
    "justification": "1-2 sentence explanation of why this score was assigned"
  }
}"""


def build_prompt(
    template: str,
    filing_id: str,
    filing_date: str | None,
    applicant: str | None,
    filing_type: str | None,
    document_text: str,
    num_documents: int,
    num_missing: int,
    json_schema_description: str,
    analysis_date: str,
) -> str:
    """Fill template placeholders with filing data and document text.

    Args:
        template: Raw template string with ``{variable}`` placeholders.
        filing_id: CER filing identifier (e.g. ``"C12345"``).
        filing_date: Filing date string, or None/empty for "Unknown".
        applicant: Applicant name, or None/empty for "Unknown".
        filing_type: Filing type label, or None/empty for "Unknown".
        document_text: Concatenated extracted text from all documents.
        num_documents: Total number of documents in the filing.
        num_missing: Number of documents unavailable for analysis.
        json_schema_description: Output from :func:`get_json_schema_description`.
        analysis_date: Today's date in ISO 8601 format (e.g. ``"2026-02-16"``).
                       Used by the LLM to determine temporal_status of
                       extracted dates (past/upcoming/today).

    Returns:
        The fully populated prompt string ready for Claude CLI.
    """
    return template.format(
        filing_id=filing_id,
        filing_date=filing_date or "Unknown",
        applicant=applicant or "Unknown",
        filing_type=filing_type or "Unknown",
        document_text=document_text,
        num_documents=num_documents,
        num_missing=num_missing,
        json_schema_description=json_schema_description,
        analysis_date=analysis_date,
    )
