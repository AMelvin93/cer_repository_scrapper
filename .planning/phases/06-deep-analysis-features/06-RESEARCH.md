# Phase 6: Deep Analysis Features - Research

**Researched:** 2026-02-16
**Domain:** LLM prompt engineering, structured JSON schema extension, regulatory filing analysis
**Confidence:** HIGH

## Summary

Phase 6 extends the existing Phase 5 analysis pipeline with five new dimensions: regulatory implications, date/deadline extraction, sentiment assessment, representative quotes, and impact scoring. The work is entirely within the existing `analyzer` module -- no new pipeline stages, no new dependencies, no new subprocess patterns. The core changes are: (1) extend `AnalysisOutput` Pydantic schema with new fields, (2) expand the prompt template with instructions for the five dimensions, (3) update `get_json_schema_description()` to include the new output shape, and (4) update the `build_prompt` signature to pass `analysis_date` for temporal status computation.

The fundamental architecture question -- combine into one prompt or split into separate calls -- is answered by the phase boundary itself: "This phase does NOT add new pipeline stages." A single, enriched prompt is the right approach. The existing prompt already produces good structured JSON; the new dimensions add roughly 40-60% more output but remain well within Claude's output window. Cost increases proportionally (more output tokens) but the filing text (input tokens, which dominate cost) is unchanged.

**Primary recommendation:** Extend the existing prompt template and Pydantic schema in-place. One Claude CLI call per filing, one enriched JSON output. No changes to service.py, orchestrator, or subprocess invocation logic.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Regulatory implications:**
- Brief summary format: 2-3 sentences covering the main regulatory impact (not structured sub-sections)
- Affected parties: name specific companies/communities/stakeholders when mentioned in the filing, fall back to general categories (e.g., "pipeline operators", "Indigenous groups") otherwise
- No recommended next steps or action items -- just describe what the filing means
- Skip the implications section entirely for routine/low-significance filings (don't generate a placeholder)

**Deadline & date extraction:**
- Extract ALL dates found in the filing with their context (not just actionable ones)
- Each date flagged with temporal status relative to analysis date: past / upcoming / today
- Structured list format: each date as an object with {date, type, description, temporal_status}
- Always include the dates field in output -- return empty array if no dates found

**Sentiment & impact scoring:**
- Dual sentiment output: fixed category (routine, notable, urgent, adversarial, cooperative) PLUS free-form nuance description (e.g., "cautiously supportive")
- Impact score 1-5 based on reader urgency: 1 = informational only, 5 = requires immediate attention
- Every score gets a 1-2 sentence justification explaining the rating
- Same analysis depth for all filings regardless of impact score (no proportional shortening)

**Quote selection:**
- Purpose: quick scanning -- quotes that let the reader decide if they need to read the full filing
- Length: 1-2 sentences per quote (short and punchy for email scanning)
- Each quote tagged with source location (page number and/or section heading) when available
- Flexible count: 1-5 quotes proportional to filing length and number of notable passages

### Claude's Discretion
- Exact prompt engineering for each analysis dimension
- How to handle edge cases where filing text is too short for meaningful analysis
- Internal ordering of analysis sections in the JSON output
- Whether to combine the deep analysis prompt with the existing Phase 5 prompt or run separately

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope
</user_constraints>

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `pydantic` | 2.x (existing) | Schema validation for extended AnalysisOutput | Already used in Phase 5 schemas.py |
| Python `.format()` | stdlib | Prompt template variable substitution | Locked decision from Phase 5 |
| `datetime` | stdlib | Generate analysis_date for temporal status | Standard library, already imported |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `json` (stdlib) | Python 3.11+ | Serialize extended analysis output | Already used throughout analyzer module |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Single enriched prompt | Two separate Claude CLI calls | Two calls doubles cost and latency. Filing text (input tokens) would be sent twice. Single call is cheaper and simpler. |
| Pydantic `Optional` fields for implications | Always-required fields | User wants implications skipped for routine filings, so `Optional[str]` with `None` is correct. |

**Installation:**
No new packages needed. All changes are to existing files using existing dependencies.

## Architecture Patterns

### Files Modified

```
src/cer_scraper/
    analyzer/
        schemas.py           # ADD: 5 new Pydantic models + extend AnalysisOutput
        prompt.py            # MODIFY: get_json_schema_description(), build_prompt() signature
        service.py           # MODIFY: pass analysis_date to build_prompt()
config/
    prompts/
        filing_analysis.txt  # REPLACE: enriched prompt template with all 5 dimensions
tests/
    (new or extended)        # Test schema validation, prompt building
```

### Pattern 1: Single Enriched Prompt (Recommended)

**What:** Combine all analysis dimensions (existing Phase 5 + new Phase 6) into one prompt template. Claude produces one JSON object with all fields in a single CLI call.

**When to use:** Always. This is the right approach for Phase 6.

**Why single prompt wins over separate calls:**
- The filing text dominates input tokens (often 10K-100K+ chars). Sending it twice for two separate analyses roughly doubles API cost.
- A single call produces a coherent analysis where sentiment informs quote selection, implications reference entities, and impact score reflects the full picture.
- No orchestration complexity for combining results from two calls.
- The additional output fields add ~500-1000 output tokens, negligible compared to the input.

**Impact on existing code:**
- `service.py`: Only change is passing `analysis_date` as a new template variable. The `_invoke_claude_cli`, `strip_code_fences`, and error handling paths are unchanged.
- `__init__.py` (orchestrator): No changes. It already calls `analyze_filing_text()` and persists the result. The extended JSON simply has more fields.
- `types.py` (AnalysisResult): No changes. It carries `analysis_json: dict | None` which holds whatever the schema validates.

### Pattern 2: Optional Fields for Conditional Sections

**What:** Use `Optional[T] = None` for fields the LLM may omit based on filing significance.

**When to use:** For `regulatory_implications` (skipped for routine filings).

**Example:**
```python
class AnalysisOutput(BaseModel):
    # ... existing fields ...

    # Phase 6: Optional -- None for routine/low-significance filings
    regulatory_implications: RegulatoryImplications | None = None

    # Phase 6: Required -- always present (empty array if no dates)
    dates: list[ExtractedDate] = Field(default_factory=list)

    # Phase 6: Required -- always present
    sentiment: SentimentAssessment
    quotes: list[RepresentativeQuote] = Field(default_factory=list)
    impact: ImpactScore
```

**Key design decisions:**
- `regulatory_implications`: Optional (None) -- user says "skip entirely for routine filings"
- `dates`: Required list, defaults to empty -- user says "always include, return empty array if none"
- `sentiment`: Required -- every filing gets a sentiment assessment
- `quotes`: Required list, defaults to empty -- flexible 1-5 count, but could be 0 for extremely short filings
- `impact`: Required -- every filing gets an impact score

### Pattern 3: Analysis Date as Template Variable

**What:** Pass the current date into the prompt so Claude can compute temporal status (past/upcoming/today) for extracted dates.

**When to use:** Always. The LLM needs to know "today" to flag dates correctly.

**Example:**
```python
# In service.py, within analyze_filing_text():
import datetime

analysis_date = datetime.date.today().isoformat()  # "2026-02-16"

prompt = build_prompt(
    template=template,
    # ... existing args ...
    analysis_date=analysis_date,
    json_schema_description=json_schema_description,
)
```

The prompt template includes:
```
Today's date (for temporal status): {analysis_date}
```

### Pattern 4: Backward-Compatible Schema Extension

**What:** Add new fields to `AnalysisOutput` with defaults so that existing analysis JSON (from Phase 5) still validates if re-parsed.

**When to use:** For schema evolution without breaking existing data.

**Example:**
```python
class AnalysisOutput(BaseModel):
    # Phase 5 fields (unchanged, no defaults)
    summary: str
    entities: list[EntityRef]
    relationships: list[Relationship]
    classification: Classification
    key_facts: list[str]

    # Phase 6 fields (all have defaults for backward compat)
    regulatory_implications: RegulatoryImplications | None = None
    dates: list[ExtractedDate] = Field(default_factory=list)
    sentiment: SentimentAssessment | None = None
    quotes: list[RepresentativeQuote] = Field(default_factory=list)
    impact: ImpactScore | None = None
```

**Note:** For NEW analyses (Phase 6+), the prompt explicitly requests all fields. But existing Phase 5 analysis.json files in the database will still validate against the extended schema because the new fields have defaults.

### Pattern 5: Prompt Template with Double Braces

**What:** The prompt template uses Python `.format()`. Any literal braces in the template (for JSON examples) must be doubled (`{{`, `}}`).

**When to use:** Always, when writing the prompt template. This is a known pitfall from Phase 5.

**Example in template:**
```
Return a JSON object like:
{{
  "sentiment": {{
    "category": "routine",
    "nuance": "standard administrative filing"
  }}
}}
```

### Anti-Patterns to Avoid

- **Separate CLI calls for Phase 5 vs Phase 6 analysis:** Doubles cost, doubles latency, loses coherence between dimensions. Always use single enriched prompt.
- **Making all Phase 6 fields required (no defaults):** Breaks backward compatibility with existing Phase 5 analysis data. Always add defaults.
- **Hardcoding analysis_date:** The date must be dynamic (today's date at analysis time), not a static value in the template.
- **Asking for page numbers without document delimiters:** The existing prompt uses `--- Document N: filename.pdf (M pages) ---` delimiters. Quotes can reference these, but the LLM cannot know actual PDF page numbers from extracted text alone. Page numbers come from the delimiter headers.
- **Asking for too-specific temporal status format:** Keep temporal_status as a simple enum string ("past", "upcoming", "today"), not a complex calculated field. The LLM determines it from context.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Date parsing/validation | Custom regex for date formats | Let the LLM extract dates as ISO strings; validate with Pydantic | CER filings use varied date formats (Jan 15, 2026; 2026-01-15; January 15th, etc.) |
| Sentiment classification | Custom keyword-based sentiment | LLM classification with fixed categories | Regulatory sentiment is nuanced; keyword matching misses context |
| Quote deduplication | Post-processing to deduplicate similar quotes | Prompt instructions telling Claude to pick diverse quotes | The LLM sees the full text and can select non-overlapping quotes naturally |
| Impact score calibration | Custom scoring algorithm | LLM scoring with clear rubric in prompt | The rubric (1=informational, 5=immediate attention) is subjective by design |

**Key insight:** All five new dimensions are pure LLM tasks -- they require reading comprehension, judgment, and contextual understanding. There is no hand-rolled alternative that would work better than a well-crafted prompt with structured output validation.

## Common Pitfalls

### Pitfall 1: Prompt Template Braces Causing KeyError

**What goes wrong:** Python `.format()` interprets `{` and `}` as variable placeholders. Any literal braces in the JSON schema description or examples cause `KeyError`.
**Why it happens:** The Phase 6 prompt template has more JSON structure examples than Phase 5.
**How to avoid:** Double ALL literal braces in the template: `{{` and `}}`. The existing `get_json_schema_description()` returns a separate string that is inserted via `{json_schema_description}` -- this is safe because the braces in that string are already resolved before `.format()` runs.
**Warning signs:** `KeyError: 'category'` or similar when calling `template.format(...)`.

### Pitfall 2: LLM Returns null for regulatory_implications When It Should Return an Object

**What goes wrong:** The user wants implications skipped for routine filings (return null/omit). But the LLM might also return null for non-routine filings when it is uncertain.
**Why it happens:** Ambiguous prompt instructions about when to skip.
**How to avoid:** The prompt must be explicit: "If this is a routine administrative filing with no meaningful regulatory implications (e.g., procedural notices, standard compliance acknowledgments), set regulatory_implications to null. For ALL other filings, provide the implications object."
**Warning signs:** Too many filings returning null implications. Monitor the ratio during testing.

### Pitfall 3: Date Extraction Returns Inconsistent Formats

**What goes wrong:** The LLM extracts dates in various formats ("2026-01-15", "January 15, 2026", "Q1 2026", "within 30 days").
**Why it happens:** CER filings contain dates in many formats, and relative dates ("within 30 days of this order") are common.
**How to avoid:** Instruct the LLM to normalize to ISO 8601 (`YYYY-MM-DD`) where possible, and use descriptive text for relative/vague dates. The Pydantic schema should accept `str` for the date field (not `datetime.date`) to handle partial dates like "2026-Q1" or "within 30 days".
**Warning signs:** Pydantic validation failures on date fields.

### Pitfall 4: Impact Score Justification Too Long or Generic

**What goes wrong:** The LLM writes multi-paragraph justifications instead of 1-2 sentences, or uses generic boilerplate like "This filing is moderately important."
**Why it happens:** Without explicit length constraints, LLMs tend toward verbosity. Without examples, they default to generic language.
**How to avoid:** The prompt should include 2-3 examples of good justifications at different score levels, and explicitly state "1-2 sentences maximum."
**Warning signs:** Justifications longer than ~200 characters; all justifications using similar phrasing.

### Pitfall 5: Quotes Missing Source Location

**What goes wrong:** The LLM provides quotes but cannot identify page numbers or section headings.
**Why it happens:** Extracted text from pymupdf4llm may not preserve page boundaries clearly. Section headings may not be obvious in the extracted markdown.
**How to avoid:** Make `source_location` optional (`str | None`). The document delimiters include filename and page count, but not per-page markers. Instruct the LLM: "Include the source document name and section heading if identifiable. Set to null if the location cannot be determined."
**Warning signs:** All quotes returning null for source_location. Consider whether document text extraction preserves enough structure.

### Pitfall 6: Prompt Version Hash Changes Breaking Traceability

**What goes wrong:** Modifying the prompt template changes the SHA-256 hash, making it impossible to compare Phase 5 analyses with Phase 6 analyses by prompt version.
**Why it happens:** The hash covers the entire template content.
**How to avoid:** This is expected and correct behavior. The hash SHOULD change when the prompt changes -- that is its purpose. Document the mapping: old hash = Phase 5 prompt, new hash = Phase 6 prompt. No code changes needed.
**Warning signs:** None -- this is working as designed.

### Pitfall 7: Backward Compatibility with Existing analysis_json

**What goes wrong:** Re-parsing existing Phase 5 analysis_json from the database against the extended AnalysisOutput schema fails because Phase 5 output lacks Phase 6 fields.
**Why it happens:** If Phase 6 fields are added as required (no defaults), existing data breaks.
**How to avoid:** ALL Phase 6 fields must have defaults in the Pydantic model: `None` for optional objects, `Field(default_factory=list)` for lists, `None` for `sentiment` and `impact`. This ensures old data parses cleanly. New data from Phase 6+ will always have all fields populated.
**Warning signs:** `ValidationError` when loading old analysis data from database.

## Code Examples

### Extended Pydantic Schema (schemas.py)

```python
# Source: Designed from CONTEXT.md locked decisions

from pydantic import BaseModel, Field


# --- Existing Phase 5 models (unchanged) ---

class EntityRef(BaseModel):
    name: str
    type: str
    role: str | None = None

class Relationship(BaseModel):
    subject: str
    predicate: str
    object: str
    context: str | None = None

class Classification(BaseModel):
    primary_type: str
    tags: list[str] = Field(default_factory=list)
    confidence: int = Field(ge=0, le=100)
    justification: str


# --- Phase 6 new models ---

class RegulatoryImplications(BaseModel):
    """Regulatory impact summary for a filing.

    Brief (2-3 sentences) describing what the filing means for
    affected parties. Only populated for non-routine filings.
    """
    summary: str
    affected_parties: list[str] = Field(default_factory=list)

class ExtractedDate(BaseModel):
    """A date extracted from filing text with temporal context.

    The date field is a string (not datetime) to handle partial
    dates like 'Q1 2026' or relative dates like 'within 30 days'.
    """
    date: str  # ISO 8601 preferred, but accepts descriptive text
    type: str  # "deadline", "hearing", "comment_period", "effective", "filing", "other"
    description: str  # What the date refers to
    temporal_status: str  # "past", "upcoming", "today"

class SentimentAssessment(BaseModel):
    """Dual sentiment output: fixed category + free-form nuance."""
    category: str  # "routine", "notable", "urgent", "adversarial", "cooperative"
    nuance: str  # Free-form description, e.g. "cautiously supportive"

class RepresentativeQuote(BaseModel):
    """A key quote selected for email scanning."""
    text: str  # The quote text (1-2 sentences)
    source_location: str | None = None  # Page/section if identifiable

class ImpactScore(BaseModel):
    """Filing impact rating with justification."""
    score: int = Field(ge=1, le=5)  # 1=informational, 5=immediate attention
    justification: str  # 1-2 sentence explanation


# --- Extended top-level output ---

class AnalysisOutput(BaseModel):
    """Complete analysis output for a CER REGDOCS filing.

    Phase 5 fields (always present):
        summary, entities, relationships, classification, key_facts

    Phase 6 fields (added with defaults for backward compat):
        regulatory_implications, dates, sentiment, quotes, impact
    """

    # Phase 5 (unchanged)
    summary: str
    entities: list[EntityRef]
    relationships: list[Relationship]
    classification: Classification
    key_facts: list[str]

    # Phase 6 (all have defaults for backward compat)
    regulatory_implications: RegulatoryImplications | None = None
    dates: list[ExtractedDate] = Field(default_factory=list)
    sentiment: SentimentAssessment | None = None
    quotes: list[RepresentativeQuote] = Field(default_factory=list)
    impact: ImpactScore | None = None
```

### Extended JSON Schema Description (prompt.py)

```python
def get_json_schema_description() -> str:
    """Return human-readable JSON schema description including Phase 6 fields."""
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
    "summary": "2-3 sentences describing the regulatory impact. What does this filing mean?",
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
```

### Updated build_prompt Signature (prompt.py)

```python
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
    analysis_date: str,  # NEW: today's date for temporal status
) -> str:
    """Fill template placeholders with filing data and document text."""
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
```

### Updated service.py Call Site

```python
# In analyze_filing_text(), after building the JSON schema description:
import datetime

analysis_date = datetime.date.today().isoformat()

prompt = build_prompt(
    template=template,
    filing_id=filing_id,
    filing_date=filing_date,
    applicant=applicant,
    filing_type=filing_type,
    document_text=document_text,
    num_documents=num_documents,
    num_missing=num_missing,
    json_schema_description=json_schema_description,
    analysis_date=analysis_date,
)
```

### Prompt Template Structure (filing_analysis.txt)

```text
You are an expert regulatory analyst specializing in Canadian Energy Regulator (CER) filings. Your task is to analyze a regulatory filing and produce a comprehensive structured JSON analysis.

Analyze the filing below and return ONLY a valid JSON object -- no markdown, no code fences, no commentary, no text before or after the JSON. Your entire response must be parseable by json.loads().

The JSON object must have this exact structure:

{json_schema_description}

[... classification taxonomy, entity types/roles instructions (unchanged from Phase 5) ...]

Instructions for each field:

CORE ANALYSIS (from Phase 5):
- "summary": [unchanged]
- "entities": [unchanged]
- "relationships": [unchanged]
- "classification": [unchanged]
- "key_facts": [unchanged]

DEEP ANALYSIS (Phase 6):

- "regulatory_implications": Describe the regulatory impact in 2-3 concise sentences.
  Name specific companies, communities, or stakeholders mentioned in the filing as
  affected parties. If no specific names are mentioned, use general categories (e.g.,
  "pipeline operators", "Indigenous groups", "landowners").
  Do NOT include recommended actions or next steps -- only describe what the filing means.
  If this is a routine administrative filing with no meaningful regulatory implications
  (e.g., procedural notices, standard compliance acknowledgments, routine correspondence),
  set regulatory_implications to null.

- "dates": Extract ALL dates mentioned in the filing.
  Today's date is {analysis_date}. For each date, flag its temporal_status:
    - "past" if the date is before today
    - "upcoming" if the date is today or after
    - "today" if the date matches today exactly
  Use ISO 8601 format (YYYY-MM-DD) when possible. For vague or relative dates
  (e.g., "within 30 days", "Q1 2026"), use descriptive text.
  Always include the dates array -- return an empty array [] if no dates found.

- "sentiment": Assess the overall tone of the filing.
  category: Choose exactly one of: "routine", "notable", "urgent", "adversarial", "cooperative"
  nuance: Provide a brief free-form description (e.g., "cautiously supportive with
  procedural concerns", "standard administrative language").

- "quotes": Select 1-5 representative quotes that let a reader quickly grasp the
  filing's core substance without reading the full document.
  Each quote should be 1-2 sentences, short and punchy for email scanning.
  Include source_location (document name, page number, or section heading) when
  identifiable from the text. Set source_location to null if not determinable.
  Choose fewer quotes for short filings, more for long/complex ones.

- "impact": Rate the filing's urgency for the reader on a 1-5 scale:
  1 = Informational only, no action needed
  2 = Minor update, worth noting
  3 = Moderate significance, review recommended
  4 = High significance, timely review important
  5 = Critical, requires immediate attention
  Provide a 1-2 sentence justification explaining the score.

[... edge cases, filing metadata, document text sections ...]

Filing metadata:
- Filing ID: {filing_id}
- Date: {filing_date}
- Applicant: {applicant}
- Filing Type: {filing_type}
- Documents: {num_documents} total, {num_missing} unavailable for analysis
- Analysis Date: {analysis_date}

Document text:

{document_text}

Return ONLY the JSON object.
```

### Test Example: Schema Validation

```python
def test_extended_schema_validates_full_output():
    """Phase 6 output with all fields validates."""
    data = {
        "summary": "TC Energy filed an application...",
        "entities": [{"name": "TC Energy", "type": "company", "role": "applicant"}],
        "relationships": [{"subject": "TC Energy", "predicate": "applied for", "object": "export licence"}],
        "classification": {"primary_type": "Application", "tags": ["export"], "confidence": 90, "justification": "Filed as application."},
        "key_facts": ["Export licence application filed."],
        "regulatory_implications": {
            "summary": "This application could affect...",
            "affected_parties": ["TC Energy", "pipeline operators in Alberta"]
        },
        "dates": [
            {"date": "2026-03-15", "type": "deadline", "description": "Comment period closes", "temporal_status": "upcoming"}
        ],
        "sentiment": {"category": "routine", "nuance": "standard administrative language"},
        "quotes": [{"text": "The Board hereby gives notice...", "source_location": "Document 1, Section 3"}],
        "impact": {"score": 2, "justification": "Standard application with no unusual elements."}
    }
    output = AnalysisOutput.model_validate(data)
    assert output.impact.score == 2
    assert output.regulatory_implications.affected_parties == ["TC Energy", "pipeline operators in Alberta"]


def test_extended_schema_validates_phase5_output():
    """Existing Phase 5 output (without Phase 6 fields) still validates."""
    data = {
        "summary": "TC Energy filed...",
        "entities": [{"name": "TC Energy", "type": "company", "role": "applicant"}],
        "relationships": [],
        "classification": {"primary_type": "Application", "tags": [], "confidence": 85, "justification": "Application filing."},
        "key_facts": ["Application filed."],
    }
    output = AnalysisOutput.model_validate(data)
    assert output.regulatory_implications is None
    assert output.dates == []
    assert output.sentiment is None
    assert output.quotes == []
    assert output.impact is None


def test_null_implications_for_routine():
    """Routine filings should have null regulatory_implications."""
    data = {
        "summary": "...",
        "entities": [],
        "relationships": [],
        "classification": {"primary_type": "Correspondence", "tags": [], "confidence": 80, "justification": "..."},
        "key_facts": [],
        "regulatory_implications": None,
        "dates": [],
        "sentiment": {"category": "routine", "nuance": "standard correspondence"},
        "quotes": [],
        "impact": {"score": 1, "justification": "Informational only."}
    }
    output = AnalysisOutput.model_validate(data)
    assert output.regulatory_implications is None
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Phase 5 prompt (5 fields) | Phase 6 enriched prompt (10 fields) | This phase | More comprehensive analysis output per filing |
| No analysis_date in prompt | Pass today's date for temporal status | This phase | Enables date extraction with past/upcoming/today flags |
| All schema fields required | Optional fields with defaults | This phase | Backward-compatible schema extension |

## Open Questions

1. **How well does Claude handle "set to null" for optional fields?**
   - What we know: Pydantic accepts null for Optional fields. Claude generally follows null instructions well.
   - What's unclear: Whether Claude consistently returns null (not an empty object) for regulatory_implications on routine filings.
   - Recommendation: Test with a few filings during implementation. If Claude returns empty objects instead of null, add post-processing to normalize. HIGH confidence overall.

2. **Output token budget for enriched response**
   - What we know: Phase 5 analysis produces ~500-1000 tokens of output. Phase 6 adds ~500-1000 more (implications + dates + sentiment + quotes + impact).
   - What's unclear: Whether total output (~1500-2000 tokens) stays within Claude's default output limits.
   - Recommendation: Claude's output limit is 8192+ tokens for Sonnet. 2000 tokens is well within limits. No concern here. HIGH confidence.

3. **Quote source_location accuracy**
   - What we know: Extracted text uses pymupdf4llm markdown which may preserve some heading structure but not explicit page numbers.
   - What's unclear: How often Claude can identify meaningful source locations from the extracted text.
   - Recommendation: Make source_location Optional. Accept that many quotes will have null locations. Consider enhancing document delimiters in the orchestrator's `assemble_filing_text` to include page range information if available from Document.page_count. MEDIUM confidence on location accuracy.

4. **Temporal status for vague dates**
   - What we know: Some filings contain relative dates ("within 30 days of this order") or partial dates ("Q1 2026").
   - What's unclear: How Claude handles temporal_status for dates that cannot be precisely compared to today.
   - Recommendation: Accept "upcoming" as default for future-oriented vague dates, "past" for past-oriented ones. The LLM's judgment is sufficient for this purpose. MEDIUM confidence.

## Sources

### Primary (HIGH confidence)
- Existing codebase: `src/cer_scraper/analyzer/` (schemas.py, prompt.py, service.py, types.py, __init__.py) -- the entire Phase 5 implementation is the foundation
- `config/prompts/filing_analysis.txt` -- current prompt template structure
- `.planning/phases/05-core-llm-analysis/05-RESEARCH.md` -- Phase 5 research findings (all still valid)
- `.planning/STATE.md` -- accumulated decisions from all prior phases

### Secondary (MEDIUM confidence)
- Pydantic v2 documentation (from training data) -- Optional field handling, model_validate behavior with missing fields
- Claude prompt engineering patterns (from training data) -- structured JSON output, null handling, rubric-based scoring

### Tertiary (LOW confidence)
- None. All research for Phase 6 is based on extending known, working infrastructure.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - No new dependencies. Pure extension of existing Phase 5 code.
- Architecture: HIGH - Single enriched prompt is the obvious choice given phase boundary constraints.
- Schema design: HIGH - Pydantic Optional fields with defaults is well-understood and tested.
- Prompt engineering: MEDIUM - The specific prompt wording will need iteration during testing. The structure and approach are sound.
- Pitfalls: HIGH - All pitfalls are extensions of known Phase 5 pitfalls (braces, backward compat, optional handling).

**Research date:** 2026-02-16
**Valid until:** 2026-03-16 (stable -- no external dependencies changing)
