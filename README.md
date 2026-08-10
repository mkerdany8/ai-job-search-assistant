# Assignment 2: Job Search Assistant

AIP444 — Mostafa Elkerdany

A three-phase job search assistant. Phase 1 extracts job postings and builds a
market analysis, Phase 2 parses a resume and triages the gaps, Phase 3 turns a
single new posting into an HTML application report.

## Setup

Python 3.9, using the venv at the repo root:

```
source ~/aip444/.venv/bin/activate
```

Python packages: `openai`, `pydantic`, `pypdf`, `python-dotenv`,
`tavily-python`, `requests`.

API keys live in `~/aip444/.env` and are read from the environment. Never
hardcoded, never committed.

```
OPENROUTER_API_KEY=...
TAVILY_API_KEY=...
```

All LLM calls go through OpenRouter. `EXTRACTION_MODEL` handles schema
filling; `REASONING_MODEL` handles the judgement calls (legitimacy verdict,
fit scoring, application advice).

### Domain lookups (Phase 3)

The legitimacy agent looks up domain registration records. There are two
backends and it falls through them in order:

1. **RDAP over HTTPS** — the primary path. RDAP is the structured-JSON
   successor to the WHOIS protocol. This uses `requests` against
   `https://rdap.org`, so there is **no extra Python package to install**, but
   it does need outbound HTTPS.

   Two things worth knowing. `rdap.org` sits behind Cloudflare, which serves a
   403 challenge page to the default `python-requests` user agent, so the code
   sends its own User-Agent. And CIRA's RDAP service (`.ca`) is often slow
   enough to hit the 10-second timeout, which is one reason the fallback
   exists.

2. **The system `whois` binary** — the fallback, used when RDAP returns 404 or
   is unavailable. **This is a system dependency, not a Python one.** It is
   preinstalled on macOS (`/usr/bin/whois`) and most Linux distributions. On
   Debian/Ubuntu, install it with `apt install whois`.

   One quirk this code works around: when a `.com` domain does not exist, the
   macOS `whois` client returns the IANA registry record for the TLD itself
   rather than an error. That record contains its own `created:` date
   (1985-01-01 for `.com`), so a naive parser reports a nonexistent domain as
   registered forty years ago — exactly backwards. The parser only reads the
   block that names the queried domain.

**If `whois` is not installed and RDAP is unreachable, nothing crashes.**
Lookups return an explanatory string, the agent is told that a failed lookup
is not evidence in either direction, and the legitimacy check proceeds on web
search alone.

## Usage

```
# Phase 1: extract postings, research companies, build the market analysis
python analyze_market.py [--postings DIR] [--force] [--verbose]

# Phase 2: parse the resume, compare it to the market
python analyze_resume.py [--resume PATH] [--force] [--verbose]

# Phase 3: application report for one posting
python advise.py POSTING.pdf [--out PATH] [--verbose]
```

Phase 3 requires the outputs of Phases 1 and 2 (`data/analysis/*.json` and
`data/resume/resume.json`) and will tell you which are missing.

`--verbose` sends debug logging to stderr. stdout stays clean.

### Re-extraction

`store.already_extracted()` compares a hash of the source PDF, not of the
prompt or the schema. Changing an extraction prompt or a field description
therefore does not invalidate anything already in `data/jobs/`, and
`python analyze_market.py --force` is required to pick the change up.

Phase 3 does not cache. `advise.py` calls `extract_posting()` on every run, so
it reflects prompt and schema changes immediately.

## Outputs

| Path | Written by |
| --- | --- |
| `data/jobs/*.json` | Phase 1 |
| `data/analysis/market-analysis.json` | Phase 1 |
| `data/analysis/gap-analysis.json` | Phase 2 |
| `data/resume/resume.json` | Phase 2 |
| `reports/market-analysis.md`, `reports/gap-analysis.md` | Phases 1, 2 |
| `reports/application-report.html` | Phase 3 |
| `data/applications/<slug>.json` | Phase 3 |

The Phase 3 HTML report is a single self-contained file with the CSS inline
and no external references, so it can be opened or shared on its own.

## Phase 3 structure

A deterministic pipeline with two bounded agentic loops inside it:

```
advise.py
 1  extract_posting()      reuses src/extract.py
 2  load market / gaps / resume JSON
 3  research_company()     agentic, MAX_STEPS = 5   (src/research.py)
 4  assess_legitimacy()    agentic, MAX_STEPS = 6   (src/legitimacy.py)
 5  score_fit()            single call             (src/fit.py)
 6  build_advice()         single call             (src/advice.py)
 7  render_report()        no LLM                  (src/report.py)
```

The stage order never varies, so the outer pipeline is plain Python. The two
steps that genuinely cannot know in advance how much evidence they need are
the ones that get loops, and both have hard step limits.

Both loops use the two-stage pattern from `src/research.py`: `create()` with
tools to gather evidence, then one `parse()` call for structured output.
Tools and `response_format` are never mixed in a single call.

Fit scoring keeps the arithmetic out of the model. Skill overlap is computed
in Python, the model scores each dimension with evidence, and the weighted
total and its band come from a fixed table in `src/fit.py`. The model never
picks the band.

Before coverage is computed, `src/fit.py` drops entries that describe the job
rather than naming a skill — "coding", "debugging", "unit testing" — while
keeping named practices such as CI/CD, REST APIs and Test Driven Development.
Extraction stays faithful to what each posting asked for, so `data/jobs/`
remains a true record and the market analysis is unaffected; the judgement
lives in scoring alone. Everything filtered is logged at debug level and
listed in the report under the skill chips.

The HTML is rendered in Python rather than generated by the model, so the
markup is always valid, the five sections are always in the required order,
and everything originating from a posting or a model is escaped on the way in.
