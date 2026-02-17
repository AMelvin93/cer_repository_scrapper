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


class RegulatoryImplications(BaseModel):
    """Regulatory impact assessment for a CER filing.

    Describes the real-world regulatory significance of a filing:
    what it means for affected parties and what actions may follow.
    Optional (None) for routine filings with no notable implications.

    Attributes:
        summary: 2-3 sentences describing the regulatory impact.
        affected_parties: Specific names or general categories of parties
                          affected by this filing (e.g. "TC Energy",
                          "pipeline operators", "landowners near km 45").
    """

    summary: str
    affected_parties: list[str] = Field(default_factory=list)


class ExtractedDate(BaseModel):
    """A date or temporal reference extracted from filing text.

    Uses str for the date field rather than datetime.date because CER
    filings often contain descriptive temporal references (e.g. "Q1 2026",
    "within 30 days of this order") that are not ISO 8601 parseable.

    Attributes:
        date: ISO 8601 preferred, but accepts descriptive text like
              "Q1 2026" or "within 30 days".
        type: Category of the date -- one of "deadline", "hearing",
              "comment_period", "effective", "filing", "other".
        description: What this date refers to.
        temporal_status: Whether the date is "past", "upcoming", or "today"
                         relative to the analysis date.
    """

    date: str
    type: str  # "deadline", "hearing", "comment_period", "effective", "filing", "other"
    description: str
    temporal_status: str  # "past", "upcoming", "today"


class SentimentAssessment(BaseModel):
    """Tone and urgency assessment of a CER filing.

    Captures both a categorical classification and a free-form nuance
    description to give readers a quick sense of the filing's tone.

    Attributes:
        category: One of "routine", "notable", "urgent", "adversarial",
                  "cooperative".
        nuance: Free-form description of tone, e.g. "cautiously supportive
                with procedural concerns".
    """

    category: str  # "routine", "notable", "urgent", "adversarial", "cooperative"
    nuance: str


class RepresentativeQuote(BaseModel):
    """A notable quote extracted from filing text.

    Selected quotes that capture key points, positions, or decisions
    from the filing. Useful for email digests and quick scanning.

    Attributes:
        text: The quote text (1-2 sentences).
        source_location: Page number, section heading, or document name
                         where the quote appears. None if not identifiable.
    """

    text: str
    source_location: str | None = None


class ImpactScore(BaseModel):
    """Significance rating for a CER filing.

    A 1-5 score indicating how much attention this filing warrants,
    with justification. Used for prioritizing email notifications.

    Scale:
        1 = Informational only (routine correspondence)
        2 = Low impact (standard compliance filings)
        3 = Moderate impact (notable decisions, conditions)
        4 = High impact (major orders, enforcement actions)
        5 = Immediate attention (emergency orders, safety alerts)

    Attributes:
        score: Integer 1-5 indicating significance level.
        justification: 1-2 sentence explanation of why this score was assigned.
    """

    score: int = Field(ge=1, le=5)
    justification: str


class AnalysisOutput(BaseModel):
    """Complete analysis output for a CER REGDOCS filing.

    This is the top-level schema that Claude's analysis JSON must validate
    against. It contains a plain-language summary, extracted entities with
    roles, structured relationships, document classification, key facts,
    and Phase 6 deep analysis fields.

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

    Phase 5 fields (always present):
        summary: 2-3 sentence plain-language overview of the filing.
        entities: Named entities extracted from the text, with types and roles.
        relationships: Subject-predicate-object triples connecting entities.
        classification: Document type classification with confidence score.
        key_facts: Bullet-point list of the most important details.

    Phase 6 fields (defaults for backward compatibility with Phase 5 data):
        regulatory_implications: Regulatory impact assessment. None for routine
                                 filings with no notable implications.
        dates: Extracted dates and temporal references from the filing text.
               Empty list if no dates found.
        sentiment: Tone and urgency assessment. None default for backward
                   compat; new analyses always populate this.
        quotes: Notable quotes capturing key points from the filing.
                Empty list if no notable quotes.
        impact: Significance score (1-5) with justification. None default
                for backward compat; new analyses always populate this.
    """

    summary: str
    entities: list[EntityRef]
    relationships: list[Relationship]
    classification: Classification
    key_facts: list[str]

    # Phase 6 fields (all have defaults for backward compatibility with Phase 5 data)
    regulatory_implications: RegulatoryImplications | None = None
    dates: list[ExtractedDate] = Field(default_factory=list)
    sentiment: SentimentAssessment | None = None
    quotes: list[RepresentativeQuote] = Field(default_factory=list)
    impact: ImpactScore | None = None
