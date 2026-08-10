"""Legitimacy assessment: is this posting a real job at a real company?

A bounded tool-calling loop with two tools, web_search and whois_lookup,
followed by a structured verdict. Same two-stage shape as research.py:
create() with tools for the loop, parse() for the structured output.
"""

import json
import logging
import re
from typing import Literal, Optional

from pydantic import BaseModel, Field

from llm import get_client, REASONING_MODEL
from schema import JobPosting
from search import WEB_SEARCH_TOOL, web_search, SearchUnavailable
from whois_lookup import WHOIS_TOOL, whois_lookup

log = logging.getLogger(__name__)

MAX_STEPS = 6  # hard guardrail on the tool-calling loop

# Domains that appear on every job board print-out and say nothing about the
# employer, so they are not worth a lookup.
_BORING_DOMAINS = {
    "linkedin.com", "indeed.com", "glassdoor.com", "ziprecruiter.com",
    "monster.com", "workopolis.com", "jobbank.gc.ca", "google.com",
    "facebook.com", "twitter.com", "x.com", "instagram.com", "youtube.com",
    "apple.com", "microsoft.com", "adobe.com", "w3.org", "schema.org",
    "gmail.com", "outlook.com", "hotmail.com", "yahoo.com", "icloud.com",
    "greenhouse.io", "lever.co", "workday.com", "myworkdayjobs.com",
    "smartrecruiters.com", "icims.com", "taleo.net", "bamboohr.com",
}

_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# Postings often print a bare hostname with no scheme. Matching those needs a
# TLD allowlist, otherwise "Node.js" and "index.html" come back as domains.
_BARE_DOMAIN_RE = re.compile(
    r"(?<![A-Za-z0-9@.-])"
    r"(?:www\.[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+"
    r"|[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*"
    r"\.(?:com|ca|net|org|io|co|ai|dev|jobs|careers|inc|group|tech|cloud|app))"
    r"(?![A-Za-z0-9-])",
    re.IGNORECASE,
)


class LegitimacySignal(BaseModel):
    """One specific observation, with the evidence behind it."""

    signal: str = Field(description="What was observed, in one short phrase")
    evidence: str = Field(
        description="The concrete evidence: a registration date, a search result, a "
        "phrase from the posting. Never a general impression."
    )
    direction: Literal["positive", "neutral", "negative"] = Field(
        description="Whether this points towards the posting being legitimate, is neutral, or is a warning sign"
    )
    weight: Literal["strong", "moderate", "weak"] = Field(
        description="How much this signal should count"
    )


class LegitimacyVerdict(BaseModel):
    """The structured verdict on one posting."""

    verdict: Literal["green", "yellow", "red"] = Field(
        description="green: verified legitimate. yellow: mostly fine but unverified in places. red: active warning signs."
    )
    headline: str = Field(description="One sentence stating the verdict and the main reason")
    signals: list[LegitimacySignal] = Field(description="Every signal found, positive and negative")
    domains_checked: list[str] = Field(description="Domains actually looked up. Empty if none were checked.")
    recommendation: str = Field(
        description="What the applicant should do: apply normally, apply with specific precautions, or verify specific things first"
    )
    assessment_succeeded: bool = Field(
        description="False if the tools failed and this verdict is not based on real evidence"
    )


SYSTEM_PROMPT = """You assess whether a job posting is legitimate, on behalf
of a job seeker in Canada who is about to send their resume and personal
details to whoever posted it.

You have two tools:
- web_search: find the company's real web presence, news, and reputation.
- whois_lookup: look up when a domain was registered and by whom.

Domain registration date is your single most important signal. An employer
domain registered decades ago and expiring years from now is very strong
evidence of a real company. A domain registered weeks ago for a company
claiming to be large and established is a serious warning sign.

Check the company's own domain. Also check any domain that appears in the
posting's contact details if it differs from the company's real one. A
posting that claims to be from a major bank but asks you to apply to a
lookalike domain registered last month is the exact fraud this check exists
to catch.

domains_found_in_posting_text is often empty. Job board pages printed to PDF
usually keep their links outside the text layer, so an empty list means no
domain could be extracted, NOT that the posting concealed its contact
details. Never report an empty list as a warning sign. When it is empty, use
web_search to find the company's official domain and look that one up.

Read these correctly:
- Redacted or privacy-protected registrant details are the DEFAULT at most
  registrars. This is normal and is NOT a warning sign. Do not report it as
  a negative signal.
- A failed lookup means no information. It is not evidence of anything.
- A young domain alone does not make a posting fraudulent. Real startups
  have young domains. It is young domain PLUS no independent web presence
  PLUS a mismatched or free-email contact address that means fraud.

Posting-text signals worth noting when present: requests for money, banking
details, or ID documents up front; promises of unusually high pay for little
experience; pressure to respond immediately; interviews conducted only over
text chat apps; a free email address as the only contact for a large company;
vague descriptions with no named team or product.

Make at most {max_steps} tool calls. Be efficient: for a well-known employer,
one search and one domain lookup is usually enough.

Assign the verdict on this basis:
- green: the company is independently verifiable AND the domain evidence is
  consistent with an established organisation. Absence of warning signs on a
  well-known employer is a green, not a yellow.
- yellow: mostly consistent, but something could not be verified, or the
  company is small or new with a thin public footprint.
- red: concrete warning signs. Name them. Never assign red on the basis of an
  unverifiable detail alone.

Every signal needs specific evidence attached. "Company seems real" is not a
signal. "rbc.com registered 1994-11-15, expires 2027-11-14" is a signal. Do
not invent evidence you did not obtain from a tool or read in the posting."""


def _empty_verdict(reason: str) -> LegitimacyVerdict:
    """Used when the assessment could not run. Deliberately not a red."""
    return LegitimacyVerdict(
        verdict="yellow",
        headline="The legitimacy check could not be completed.",
        signals=[],
        domains_checked=[],
        recommendation=(
            f"This check did not run ({reason}), so it says nothing about this "
            "employer either way. Verify the company yourself before sending "
            "personal documents: find their official site directly, and confirm "
            "the posting appears on their own careers page."
        ),
        assessment_succeeded=False,
    )


def seed_domains(text: str, limit: int = 8) -> list[str]:
    """Pull candidate domains out of the raw posting text.

    The extracted JobPosting has no website field, so the contact details in
    the original text are the only place a lookalike domain would show up.
    Sorted for reproducibility.
    """
    from whois_lookup import normalize_domain

    found = set()
    for url in _URL_RE.findall(text):
        found.add(normalize_domain(url))
    for email in _EMAIL_RE.findall(text):
        found.add(normalize_domain(email))
    for bare in _BARE_DOMAIN_RE.findall(text):
        found.add(normalize_domain(bare))

    useful = sorted(d for d in found if d and "." in d and d not in _BORING_DOMAINS)
    if len(useful) > limit:
        log.debug("Found %d candidate domains, keeping first %d", len(useful), limit)
    return useful[:limit]


def assess_legitimacy(
    posting: JobPosting,
    raw_text: str,
    research: Optional[dict] = None,
) -> LegitimacyVerdict:
    """Run the bounded legitimacy loop and return a structured verdict.

    Always returns a verdict. On failure it returns an inconclusive one with
    assessment_succeeded=False so the report can say so plainly.
    """
    domains = seed_domains(raw_text)
    log.debug("Legitimacy check for %s, seed domains: %s", posting.company_name, domains or "none")

    client = get_client()
    payload = {
        "posting": posting.model_dump(),
        "domains_found_in_posting_text": domains,
        "company_research": research or "not available",
        # Trimmed: the model needs the posting's own wording to spot pressure
        # tactics and payment requests, but not 40k characters of nav chrome.
        "posting_text_excerpt": raw_text[:6000],
    }
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT.format(max_steps=MAX_STEPS)},
        {
            "role": "user",
            "content": (
                f"Assess this posting for {posting.job_title} at "
                f"{posting.company_name}.\n\n"
                + json.dumps(payload, ensure_ascii=False, default=str)
            ),
        },
    ]

    tools = [WEB_SEARCH_TOOL, WHOIS_TOOL]
    checked: list[str] = []

    try:
        for step in range(1, MAX_STEPS + 1):
            log.debug("Legitimacy step %d/%d", step, MAX_STEPS)
            completion = client.chat.completions.create(
                model=REASONING_MODEL,
                messages=messages,
                tools=tools,
                temperature=0,
            )
            msg = completion.choices[0].message

            if not msg.tool_calls:
                log.debug("Model stopped investigating after %d step(s)", step - 1)
                break

            messages.append(msg.model_dump(exclude_none=True))
            for call in msg.tool_calls:
                name = call.function.name
                try:
                    args = json.loads(call.function.arguments)
                    if name == "whois_lookup":
                        domain = args["domain"]
                        checked.append(domain)
                        result = whois_lookup(domain)
                    elif name == "web_search":
                        result = web_search(args["query"])
                    else:
                        result = f"Unknown tool {name!r}."
                        log.debug("Model called unknown tool %r", name)
                except SearchUnavailable as e:
                    # Search being off should not kill the check: whois still works.
                    log.debug("Search unavailable: %s", e)
                    result = "Web search is unavailable. Rely on domain lookups and the posting text."
                except Exception as e:
                    log.debug("Tool call %s failed: %s", name, e)
                    result = f"Tool call failed: {e}"
                messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
        else:
            log.debug("Hit MAX_STEPS=%d, forcing verdict", MAX_STEPS)

        # Second stage: structured verdict, no tools in this call.
        messages.append(
            {
                "role": "user",
                "content": "Now give your verdict in the required structure.",
            }
        )
        final = client.chat.completions.parse(
            model=REASONING_MODEL,
            messages=messages,
            response_format=LegitimacyVerdict,
            temperature=0,
        )
        verdict = final.choices[0].message.parsed
        if verdict is None:
            log.debug("Verdict returned no parsed content")
            return _empty_verdict("the model returned no verdict")

        # Trust our own record of what was looked up over the model's memory.
        if checked:
            verdict.domains_checked = sorted(set(checked))

        negatives = sum(1 for s in verdict.signals if s.direction == "negative")
        log.debug(
            "Verdict: %s, %d signals (%d negative), domains checked: %s",
            verdict.verdict, len(verdict.signals), negatives,
            ", ".join(verdict.domains_checked) or "none",
        )
        return verdict

    except Exception as e:
        log.debug("Legitimacy assessment failed: %s", e)
        return _empty_verdict(str(e))
