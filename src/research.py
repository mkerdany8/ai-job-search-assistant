"""Company research using an LLM with a web search tool."""

import json
import logging
from typing import Optional

from pydantic import BaseModel, Field

from llm import get_client, EXTRACTION_MODEL
from search import WEB_SEARCH_TOOL, web_search, SearchUnavailable

log = logging.getLogger(__name__)

MAX_STEPS = 5  # hard guardrail on the tool-calling loop


class CompanyResearch(BaseModel):
    """What we learned about the hiring company from the web."""

    company_size: Optional[str] = Field(description="Employee count or size band, null if not found")
    industry: Optional[str] = Field(description="Primary industry, null if not found")
    recent_news: list[str] = Field(description="Recent developments such as layoffs, funding, or expansion. Empty if none found.")
    culture_signals: list[str] = Field(description="Observations about work culture from reviews or public sources. Empty if none found.")
    notes_for_applicant: list[str] = Field(description="Anything else useful to someone applying here")
    research_succeeded: bool = Field(description="False if searches failed or returned nothing useful")


SYSTEM_PROMPT = """You research companies for a job applicant in Canada.

You have a web_search tool. Use it to learn about the company: its size,
industry, recent news, and what people say about working there. Prefer
Canadian and English-language sources.

Make focused searches, at most {max_steps}. Write specific queries. Searching
the bare company name is rarely useful; add words like "layoffs 2026",
"employee reviews", "engineering team", or "headquarters".

When you have enough, stop searching and report what you found. Only state
things the search results actually support. If searches turn up nothing
useful, say so honestly and set research_succeeded to false rather than
guessing."""


def research_company(company_name: str, job_title: str) -> CompanyResearch:
    """Run a bounded tool-calling loop to research one company.

    Always returns a CompanyResearch. On failure it returns an empty result
    with research_succeeded=False so the caller can carry on.
    """
    log.debug("Researching company: %s", company_name)

    empty = CompanyResearch(
        company_size=None,
        industry=None,
        recent_news=[],
        culture_signals=[],
        notes_for_applicant=[],
        research_succeeded=False,
    )

    client = get_client()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT.format(max_steps=MAX_STEPS)},
        {
            "role": "user",
            "content": f"Research {company_name}, who are hiring for a {job_title} role.",
        },
    ]

    try:
        for step in range(1, MAX_STEPS + 1):
            log.debug("Research step %d/%d", step, MAX_STEPS)
            completion = client.chat.completions.create(
                model=EXTRACTION_MODEL,
                messages=messages,
                tools=[WEB_SEARCH_TOOL],
            )
            msg = completion.choices[0].message

            if not msg.tool_calls:
                log.debug("Model stopped searching after %d step(s)", step - 1)
                break

            messages.append(msg.model_dump(exclude_none=True))
            for call in msg.tool_calls:
                try:
                    args = json.loads(call.function.arguments)
                    result = web_search(args["query"])
                except SearchUnavailable:
                    raise
                except Exception as e:
                    log.debug("Tool call failed: %s", e)
                    result = f"Tool call failed: {e}"
                messages.append(
                    {"role": "tool", "tool_call_id": call.id, "content": result}
                )
        else:
            log.debug("Hit MAX_STEPS=%d, forcing summary", MAX_STEPS)

        # Final pass: turn the gathered context into structured output.
        messages.append(
            {
                "role": "user",
                "content": "Now summarise your findings in the required structure.",
            }
        )
        final = client.chat.completions.parse(
            model=EXTRACTION_MODEL,
            messages=messages,
            response_format=CompanyResearch,
        )
        result = final.choices[0].message.parsed
        if result is None:
            log.debug("Research summary returned nothing")
            return empty

        log.debug(
            "Research complete: %d news items, %d culture signals, succeeded=%s",
            len(result.recent_news),
            len(result.culture_signals),
            result.research_succeeded,
        )
        return result

    except SearchUnavailable as e:
        log.debug("Search unavailable, skipping research: %s", e)
        return empty
    except Exception as e:
        log.debug("Research failed for %s: %s", company_name, e)
        return empty
