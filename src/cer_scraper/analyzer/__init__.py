"""CER REGDOCS filing analysis via Claude Code CLI.

This package provides LLM-powered analysis of extracted filing text,
producing structured JSON with entity extraction, document classification,
plain-language summaries, and key facts.

Modules:
    types -- Shared types (AnalysisResult dataclass).
    schemas -- Pydantic models for analysis output validation.
    service -- Core analysis service (Plan 02).
    prompt -- Prompt template loading and variable substitution (Plan 02).
    orchestrator -- Filing-level analysis orchestration (Plan 03).
"""
