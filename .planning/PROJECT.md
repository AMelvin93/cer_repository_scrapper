# CER REGDOCS Scraper & Analyzer

## What This Is

An automated tool that scrapes the Canada Energy Regulator's REGDOCS website for recent regulatory filings, downloads associated PDFs, runs deep-dive NLP analysis on each filing using Claude Code CLI, and sends per-filing email reports via Gmail. It runs periodically (every ~2 hours) and only processes new/incremental filings.

## Core Value

Every CER filing gets captured, analyzed in depth, and delivered to the user's inbox — no filings slip through the cracks.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Scrape all recent filings from REGDOCS (Last Day/Week/Month pages)
- [ ] Handle JavaScript-rendered content (Playwright or reverse-engineered API)
- [ ] Navigate from filing list to individual filing pages and extract PDF links
- [ ] Download all PDFs for each filing to organized local folders
- [ ] Track which filings have been processed (avoid re-processing)
- [ ] Run deep-dive analysis per filing via Claude Code CLI (`claude -p`)
- [ ] Analysis includes: entity extraction, filing type classification, regulatory implications, key deadlines, sentiment, cross-referencing context
- [ ] Send individual Gmail email per filing with the full analysis
- [ ] Run on a periodic schedule (~every 2 hours)
- [ ] Only process incremental/new filings each run

### Out of Scope

- Web dashboard or UI — email-only delivery for v1
- Database storage — local folders only for v1
- Filtering or priority tiers — all filings get full treatment
- Multi-user support — single user (the owner)
- Cloud deployment — runtime environment TBD, design locally first
- API-based LLM calls — using Claude Code CLI instead to save on token costs

## Context

- **REGDOCS site**: `https://apps.cer-rec.gc.ca/REGDOCS/Search/RecentFilings?p=1` — JavaScript-rendered, content loads dynamically via AJAX. No publicly documented API. Individual filings at `/REGDOCS/Item/View/{ID}` and `/REGDOCS/Item/Filing/{ID}`.
- **Filing volume**: Estimated 10-50 filings per day across all categories.
- **PDF structure**: Each filing page contains one or more PDF documents. PDFs are regulatory documents (applications, decisions, orders, correspondence, etc.).
- **Existing codebase**: Bare Python scaffold — `main.py` (hello world), `pyproject.toml` (Python 3.11+, no deps yet). Using `uv` package manager.
- **Analysis approach**: Shell out to `claude -p` CLI with PDF path and analysis prompt. Captures stdout as the analysis result. Leverages existing Claude Code subscription rather than API billing.

## Constraints

- **Tech stack**: Python 3.11+, `uv` package manager — already established in `pyproject.toml`
- **Scraping**: REGDOCS is JS-rendered — must use Playwright or discover internal API endpoints
- **LLM**: Claude Code CLI (`claude -p`) — no API key management, uses existing subscription
- **Email**: Gmail with app password for sending
- **Storage**: Local filesystem — organized folder structure for PDFs and analysis outputs
- **Rate limiting**: Must respect CER website — no aggressive scraping, reasonable delays between requests

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Claude Code CLI over API | User wants to leverage existing subscription, avoid per-token API costs | — Pending |
| Playwright over Selenium | Modern, async-native, better for JS-rendered content in Python | — Pending |
| Local folders over database | Simpler v1, user preference for straightforward storage | — Pending |
| Per-filing emails over digest | User wants immediate per-filing visibility despite high volume | — Pending |
| Gmail for email delivery | User preference, simple setup with app passwords | — Pending |

---
*Last updated: 2026-02-05 after initialization*
