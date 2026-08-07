"""Aggregate extracted postings into a market analysis."""

import json
import logging
from collections import Counter
from pathlib import Path

from pydantic import BaseModel, Field

from llm import get_client, EXTRACTION_MODEL
from store import load_all

log = logging.getLogger(__name__)

ANALYSIS_DIR = Path("data/analysis")
REPORTS_DIR = Path("reports")


class SkillDemand(BaseModel):
    skill: str
    posting_count: int = Field(description="How many postings mention this skill")
    notes: str = Field(description="Short note on how it appears, for example 'usually paired with cloud work'")


class MarketAnalysis(BaseModel):
    """Aggregated patterns across all analyzed postings."""

    postings_analyzed: int
    roles_covered: list[str] = Field(description="Distinct job titles in the set")
    top_required_skills: list[SkillDemand] = Field(description="Most demanded hard skills, most common first")
    top_preferred_skills: list[SkillDemand] = Field(description="Most common nice-to-have skills")
    experience_pattern: str = Field(description="Typical seniority and years asked for across the set")
    education_pattern: str = Field(description="What education these postings typically require")
    salary_observations: str = Field(description="What the salary data shows, including how many postings listed one")
    common_responsibilities: list[str] = Field(description="Responsibilities that recur across postings")
    company_and_culture_patterns: list[str] = Field(description="Patterns from company research across employers")
    trends: list[str] = Field(description="Notable observations a job seeker should act on")


def _skill_counts(postings: list[dict]) -> tuple[Counter, Counter]:
    """Count raw skill frequencies to ground the LLM in real numbers."""
    req, pref = Counter(), Counter()
    for p in postings:
        req.update(s.lower().strip() for s in p.get("required_skills", []))
        pref.update(s.lower().strip() for s in p.get("preferred_skills", []))
    return req, pref


def build_market_analysis(postings: list[dict]) -> MarketAnalysis:
    """Have the LLM find patterns across all extracted postings."""
    if not postings:
        raise ValueError("no postings to analyze, run extraction first")

    req, pref = _skill_counts(postings)
    log.debug("Aggregating %d postings", len(postings))
    log.debug("Distinct required skills: %d, preferred: %d", len(req), len(pref))

    payload = {
        "postings": postings,
        "computed_required_skill_counts": dict(req.most_common()),
        "computed_preferred_skill_counts": dict(pref.most_common()),
    }

    system = """You analyze job market data for a job seeker.

You are given structured data extracted from real job postings, plus exact
skill frequency counts computed from that data.

Use the computed counts for posting_count values. Do not estimate them.

Some postings list both a category and its instances, for example "relational
databases" alongside "PostgreSQL". Merge these sensibly when reporting demand
rather than double counting, and mention the merge in the notes field.

Be specific and quantitative. "Python appears in 6 of 8 postings" is useful.
"Python is popular" is not. Only claim what the data supports."""

    client = get_client()
    completion = client.chat.completions.parse(
        model=EXTRACTION_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        response_format=MarketAnalysis,
    )
    analysis = completion.choices[0].message.parsed
    if analysis is None:
        raise ValueError("market analysis returned no parsed content")

    log.debug("Market analysis: %d top skills identified", len(analysis.top_required_skills))
    if completion.usage:
        log.debug("Tokens: %d prompt, %d completion",
                  completion.usage.prompt_tokens, completion.usage.completion_tokens)
    return analysis


def write_report(analysis: MarketAnalysis) -> Path:
    """Have the LLM turn the structured analysis into a Markdown report."""
    system = """Write a job market analysis report in Markdown for a new
graduate job seeker in Toronto.

Structure it with clear headings. Be concrete and cite the numbers from the
data. Keep it readable, not padded. No preamble, start with the title."""

    client = get_client()
    completion = client.chat.completions.create(
        model=EXTRACTION_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": analysis.model_dump_json(indent=2)},
        ],
    )
    md = completion.choices[0].message.content or ""

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORTS_DIR / "market-analysis.md"
    out.write_text(md)
    log.debug("Wrote %s (%d chars)", out, len(md))
    return out


def save_analysis(analysis: MarketAnalysis) -> Path:
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    out = ANALYSIS_DIR / "market-analysis.json"
    out.write_text(analysis.model_dump_json(indent=2))
    log.debug("Wrote %s", out)
    return out
