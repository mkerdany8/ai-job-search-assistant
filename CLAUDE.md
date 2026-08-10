# Assignment 2: Job Search Assistant

Course: AIP444. Python 3.9, venv at repo root `~/aip444/.venv`.
All LLM calls go through OpenRouter. Keys in `~/aip444/.env`, never hardcoded.

## What already exists (Phases 1 and 2, hand-written, do not rewrite)

`src/llm.py` — `get_client()` returns an OpenAI SDK client pointed at
OpenRouter. `EXTRACTION_MODEL` is the model slug.

`src/pdf.py` — `extract_text(path)` returns text from a PDF. Raises
`PdfExtractionError`.

`src/schema.py` — `JobPosting` Pydantic model with nested `SalaryRange` and
`ExperienceLevel`.

`src/extract.py` — `extract_posting(path)` returns a validated `JobPosting`.
Uses `client.chat.completions.parse()` with `response_format=JobPosting`,
i.e. real structured outputs. Retries transient errors, fails fast on 4xx.

`src/search.py` — `WEB_SEARCH_TOOL` is the tool schema to hand an LLM.
`web_search(query)` runs Tavily and returns text. Never raises on network
failure, returns an explanatory string instead.

`src/research.py` — `research_company()` runs a bounded tool-calling loop
(MAX_STEPS) then a final `parse()` call for structured output. Copy this
two-stage pattern: tools with `create()`, then structured output with
`parse()`. Do not mix tools and `response_format` in one call.

`src/store.py` — save/load extracted postings, slugify, source hashing.

`src/resume_schema.py` — `Resume`, `Gap`, `GapAnalysis` models.

`src/resume.py` — resume parsing and gap analysis.

`analyze_market.py` — Phase 1 CLI. `analyze_resume.py` — Phase 2 CLI.

## Existing data to load

- `data/analysis/market-analysis.json` — aggregated market patterns
- `data/analysis/gap-analysis.json` — strengths, gaps, unique value
- `data/resume/resume.json` — parsed resume
- `data/jobs/*.json` — the 8 extracted postings

## Conventions to follow

- Debug logging via `logging` to **stderr**, `--verbose` flag turns it on.
  stdout stays clean. Library loggers (openai, httpx, httpcore, urllib3,
  tavily) are set to WARNING.
- Every agentic loop needs a hard step limit.
- Every external call degrades gracefully. Never crash the run.
- Python 3.9: no `X | None` type syntax outside quotes.
- Pydantic models: all fields in `required`, optional ones typed
  `Optional[...]` with a description saying null is allowed.
