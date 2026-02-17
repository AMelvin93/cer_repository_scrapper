"""Pydantic v2 models for validating LLM analysis output.

These schemas define the contract between the Claude CLI response and
downstream consumers (database storage, email reports, future APIs).
All analysis JSON must validate against AnalysisOutput before being
accepted and persisted.
"""

from pydantic import BaseModel, Field


class EntityRef(BaseModel):
    """A named entity extracted from filing text.

    Attributes:
        name: Entity name as it appears in the text.
        type: Entity category -- one of "company", "facility", "location",
              or "regulatory_reference".
        role: Entity role in the filing context (e.g. "applicant",
              "intervener", "regulator", "contractor"). None if not
              determinable from the text.
    """

    name: str
    type: str  # "company", "facility", "location", "regulatory_reference"
    role: str | None = None  # "applicant", "intervener", "regulator", "contractor", etc.


class Relationship(BaseModel):
    """A structured relationship between entities.

    Represents a subject-predicate-object triple extracted from filing text,
    e.g. "TC Energy (subject) applied for (predicate) export permit (object)".

    Attributes:
        subject: The entity performing the action.
        predicate: The action or relationship type.
        object: The entity or thing being acted upon.
        context: Optional additional context for the relationship.
    """

    subject: str
    predicate: str
    object: str
    context: str | None = None


class Classification(BaseModel):
    """Document classification with CER-specific taxonomy.

    Attributes:
        primary_type: The primary document type from the CER taxonomy.
        tags: Secondary topic tags (e.g. ["export", "natural-gas"]).
        confidence: Classification confidence as an integer 0-100.
        justification: Brief explanation (1-2 sentences) of why this
                       classification was chosen.
    """

    primary_type: str
    tags: list[str] = Field(default_factory=list)
    confidence: int = Field(ge=0, le=100)
    justification: str


class AnalysisOutput(BaseModel):
    """Complete analysis output for a CER REGDOCS filing.

    This is the top-level schema that Claude's analysis JSON must validate
    against. It contains a plain-language summary, extracted entities with
    roles, structured relationships, document classification, and key facts.

    CER-specific document taxonomy for classification.primary_type:
        - Application
        - Order
        - Decision
        - Compliance Filing
        - Correspondence
        - Notice
        - Conditions Compliance
        - Financial Submission
        - Safety Report
        - Environmental Assessment

    Attributes:
        summary: 2-3 sentence plain-language overview of the filing.
        entities: Named entities extracted from the text, with types and roles.
        relationships: Subject-predicate-object triples connecting entities.
        classification: Document type classification with confidence score.
        key_facts: Bullet-point list of the most important details.
    """

    summary: str
    entities: list[EntityRef]
    relationships: list[Relationship]
    classification: Classification
    key_facts: list[str]
