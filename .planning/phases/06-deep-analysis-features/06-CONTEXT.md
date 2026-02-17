# Phase 6: Deep Analysis Features - Context

**Gathered:** 2026-02-16
**Status:** Ready for planning

<domain>
## Phase Boundary

Enrich the Phase 5 core analysis (entity extraction + document classification) with five deeper dimensions: regulatory implications, key dates/deadlines, sentiment assessment, representative quotes, and impact scoring. The output must be structured JSON consumable by email templates (Phase 8) and storage. This phase does NOT add new pipeline stages -- it extends the existing analysis prompt and response schema.

</domain>

<decisions>
## Implementation Decisions

### Regulatory implications
- Brief summary format: 2-3 sentences covering the main regulatory impact (not structured sub-sections)
- Affected parties: name specific companies/communities/stakeholders when mentioned in the filing, fall back to general categories (e.g., "pipeline operators", "Indigenous groups") otherwise
- No recommended next steps or action items -- just describe what the filing means
- Skip the implications section entirely for routine/low-significance filings (don't generate a placeholder)

### Deadline & date extraction
- Extract ALL dates found in the filing with their context (not just actionable ones)
- Each date flagged with temporal status relative to analysis date: past / upcoming / today
- Structured list format: each date as an object with {date, type, description, temporal_status}
- Always include the dates field in output -- return empty array if no dates found

### Sentiment & impact scoring
- Dual sentiment output: fixed category (routine, notable, urgent, adversarial, cooperative) PLUS free-form nuance description (e.g., "cautiously supportive")
- Impact score 1-5 based on reader urgency: 1 = informational only, 5 = requires immediate attention
- Every score gets a 1-2 sentence justification explaining the rating
- Same analysis depth for all filings regardless of impact score (no proportional shortening)

### Quote selection
- Purpose: quick scanning -- quotes that let the reader decide if they need to read the full filing
- Length: 1-2 sentences per quote (short and punchy for email scanning)
- Each quote tagged with source location (page number and/or section heading) when available
- Flexible count: 1-5 quotes proportional to filing length and number of notable passages

### Claude's Discretion
- Exact prompt engineering for each analysis dimension
- How to handle edge cases where filing text is too short for meaningful analysis
- Internal ordering of analysis sections in the JSON output
- Whether to combine the deep analysis prompt with the existing Phase 5 prompt or run separately

</decisions>

<specifics>
## Specific Ideas

- Implications should be scannable in email -- brief enough to read without expanding
- Dates structured as objects for potential calendar integration later
- "Headline" quotes that capture the filing's core substance in a glance

</specifics>

<deferred>
## Deferred Ideas

None -- discussion stayed within phase scope

</deferred>

---

*Phase: 06-deep-analysis-features*
*Context gathered: 2026-02-16*
