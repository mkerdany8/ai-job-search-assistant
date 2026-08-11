"""Parse a resume and compare it against the market analysis."""

import json
import logging
from pathlib import Path

from llm import get_client, EXTRACTION_MODEL
from pdf import extract_text
from resume_schema import GapAnalysis, Resume
from search import WEB_SEARCH_TOOL, web_search, SearchUnavailable

log = logging.getLogger(__name__)

RESUME_DIR = Path("data/resume")
ANALYSIS_DIR = Path("data/analysis")
REPORTS_DIR = Path("reports")

MAX_STEPS = 6

PARSE_SYSTEM = """You extract structured data from a resume.

Rules:
- Extract only what the resume says. Never invent experience or skills.
- Split skills into individual items. "C, C++, Java" becomes three entries.
- hard_skills means technologies: languages, frameworks, tools, platforms.
- soft_skills means human skills like communication or leadership.
- domain_keywords means methodologies and practices such as Agile, CI/CD,
  REST API design, or object-oriented design. These often appear in the
  summary or embedded in bullet points, so read for them specifically.
- Include in-progress certifications, marked as such.
- The text comes from a PDF, so spacing may be irregular. Read through it."""

GAP_SYSTEM = """You advise a new graduate on their job search in Toronto.

You are given their structured resume and a market analysis built from real
job postings they would apply to.

Identify:
- strengths: what they have that the market frequently asks for. Cite the
  posting counts from the market data.
- gaps: what the market asks for that their resume does not show well.
- unique_value: what they bring that postings do not commonly ask for.

Triage every gap honestly:
- quick win: they have it but did not list it, or used different wording
- short-term: days to weeks, a tutorial or small project or free cert
- medium-term: weeks to months, a framework or portfolio project
- long-term: years of experience or a degree

Every action must be specific. Name the resource and the rough time cost.
"Learn AWS" is useless. "AWS Cloud Practitioner, free tier plus about 20
hours" is useful.

Use the web_search tool when you need current specifics: what a
certification costs, how long a course takes, whether a tool is still
current. Do not guess at these details.

Be honest about weak areas. False encouragement does not help them."""


def parse_resume(path: Path) -> Resume:
    """Extract structured data from a resume PDF."""
    text = extract_text(path)
    log.debug("Parsing resume: %s (%d chars)", path.name, len(text))

    client = get_client()
    completion = client.chat.completions.parse(
        model=EXTRACTION_MODEL,
        messages=[
            {"role": "system", "content": PARSE_SYSTEM},
            {"role": "user", "content": text},
        ],
        response_format=Resume,
    )
    resume = completion.choices[0].message.parsed
    if resume is None:
        raise ValueError("resume parsing returned no content")

    log.debug(
        "Extracted %d hard skills, %d soft skills, %d roles, %d projects, %d certs",
        len(resume.hard_skills), len(resume.soft_skills),
        len(resume.work_experience), len(resume.projects), len(resume.certifications),
    )
    if completion.usage:
        log.debug("Tokens: %d prompt, %d completion",
                  completion.usage.prompt_tokens, completion.usage.completion_tokens)
    return resume


def analyze_gaps(resume: Resume, market: dict) -> GapAnalysis:
    """Compare the resume to the market analysis, with search for specifics."""
    log.debug("Running gap analysis")

    client = get_client()
    messages = [
        {"role": "system", "content": GAP_SYSTEM},
        {
            "role": "user",
            "content": json.dumps(
                {"resume": resume.model_dump(), "market_analysis": market},
                ensure_ascii=False,
            ),
        },
    ]

    for step in range(1, MAX_STEPS + 1):
        log.debug("Gap analysis step %d/%d", step, MAX_STEPS)
        # The model skips research when it feels confident, which produces
        # invented costs and durations. Force a tool call on the first step,
        # then let it decide whether it needs more.
        completion = client.chat.completions.create(
            model=EXTRACTION_MODEL,
            messages=messages,
            tools=[WEB_SEARCH_TOOL],
            tool_choice="required" if step == 1 else "auto",
        )
        msg = completion.choices[0].message
        if not msg.tool_calls:
            log.debug("Model finished researching after %d step(s)", step - 1)
            break
        messages.append(msg.model_dump(exclude_none=True))
        for call in msg.tool_calls:
            try:
                args = json.loads(call.function.arguments)
                result = web_search(args["query"])
            except SearchUnavailable as e:
                log.debug("Search unavailable: %s", e)
                result = "Search is unavailable. Rely on the data you already have."
            except Exception as e:
                log.debug("Tool call failed: %s", e)
                result = f"Tool call failed: {e}"
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
    else:
        log.debug("Hit MAX_STEPS=%d, forcing summary", MAX_STEPS)

    messages.append({"role": "user", "content": "Now produce the gap analysis in the required structure."})
    final = client.chat.completions.parse(
        model=EXTRACTION_MODEL, messages=messages, response_format=GapAnalysis
    )
    analysis = final.choices[0].message.parsed
    if analysis is None:
        raise ValueError("gap analysis returned no content")

    from collections import Counter
    levels = Counter(g.level for g in analysis.gaps)
    log.debug("Gap analysis: %d strengths, %d gaps %s, %d unique",
              len(analysis.strengths), len(analysis.gaps), dict(levels), len(analysis.unique_value))
    return analysis


def save_resume(resume: Resume) -> Path:
    RESUME_DIR.mkdir(parents=True, exist_ok=True)
    out = RESUME_DIR / "resume.json"
    out.write_text(resume.model_dump_json(indent=2))
    log.debug("Wrote %s", out)
    return out


def save_gap_analysis(analysis: GapAnalysis) -> Path:
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    out = ANALYSIS_DIR / "gap-analysis.json"
    out.write_text(analysis.model_dump_json(indent=2))
    log.debug("Wrote %s", out)
    return out


def write_gap_report(analysis: GapAnalysis) -> Path:
    """Turn the structured gap analysis into a Markdown report."""
    system = """Write a gap analysis report in Markdown for a new graduate
job seeker.

Structure: strengths, then gaps grouped by triage level from quick win to
long-term, then unique value, then a short closing summary.

Keep every specific action and time estimate from the data. Do not soften
the gaps or pad the writing. No preamble, start with the title."""

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
    out = REPORTS_DIR / "gap-analysis.md"
    out.write_text(md)
    log.debug("Wrote %s (%d chars)", out, len(md))
    return out
