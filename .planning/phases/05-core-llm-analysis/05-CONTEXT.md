# Phase 5: Core LLM Analysis - Context

**Gathered:** 2026-02-16
**Status:** Ready for planning

<domain>
## Phase Boundary

Invoke Claude Code CLI (`claude -p`) on extracted filing text and return structured JSON analysis with entity extraction and document classification. This phase covers the CLI integration, prompt template system, entity extraction, classification, and a plain-language summary with key facts. Deep analysis features (regulatory implications, deadlines, sentiment, impact scoring) belong to Phase 6. Long document chunking belongs to Phase 7.

</domain>

<decisions>
## Implementation Decisions

### Entity extraction scope
- Extract: companies/organizations, facilities, locations, and regulatory references (permit numbers, order numbers, proceeding IDs, legislation citations)
- No people entities -- companies are sufficient for user's needs
- Companies tagged with roles: applicant, intervener, regulator, contractor, etc.
- Structured relationships between entities (e.g., "Company A applied to export gas from Facility B in Location C") as a separate section in the output

### Document classification
- CER-specific taxonomy: Application, Order, Decision, Compliance Filing, Correspondence, Notice, Conditions Compliance, Financial Submission, Safety Report, Environmental Assessment
- Primary type + secondary tags (e.g., primary: "Application", tags: ["export", "natural-gas"])
- Confidence expressed as numeric 0-100%
- Brief justification included (1-2 sentences explaining why the classification was chosen)

### Analysis output structure
- Top-level JSON fields: summary (2-3 sentence plain-language overview), entities (role-tagged, with relationships), classification (primary + tags + confidence + justification), key_facts (bullet-point list of most important details)
- Storage: both JSON file (analysis.json in filing's documents folder) AND database column on the Filing record
- Prompt template: plain text with {variables} (Python .format() placeholders) -- no Jinja2 dependency
- Full analysis metadata: model used, prompt version hash, processing time, input/output token counts, timestamp

### Multi-document handling
- One analysis per filing (not per document) -- concatenate all document texts
- Documents clearly delimited with headers in prompt: "--- Document 1: filename.pdf (N pages) ---"
- Proceed with available documents if some failed extraction -- note missing docs in metadata
- No hard length limit -- attempt analysis regardless of size; if Claude CLI times out or errors, mark as needing Phase 7 long-document handling

### Claude's Discretion
- Exact prompt wording and structure (within the constraints above)
- CLI invocation details (subprocess management, stdin vs file piping)
- JSON schema naming conventions and nesting depth
- How to handle edge cases (empty filing text, single-page filings, non-English content)
- Prompt version hashing approach

</decisions>

<specifics>
## Specific Ideas

- The smoke test extracted text from an NRG Business Marketing LLC export application -- this is a good reference filing for testing the analysis prompt
- Existing extracted markdown at `data/smoke_latest_one/filings/2026-02-16_Filing-C38251/documents/doc_001.md` can serve as test input
- Blocker note from STATE.md: "Claude CLI subprocess invocation details underdocumented -- needs prototyping early in Phase 5"

</specifics>

<deferred>
## Deferred Ideas

None -- discussion stayed within phase scope

</deferred>

---

*Phase: 05-core-llm-analysis*
*Context gathered: 2026-02-16*
