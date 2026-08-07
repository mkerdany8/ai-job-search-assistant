"""Extract structured data from a job posting PDF using an LLM."""

import datetime as dt
import logging
from pathlib import Path

from openai import APIError, APIConnectionError, APIStatusError, RateLimitError
from pydantic import ValidationError

from llm import get_client, EXTRACTION_MODEL
from pdf import extract_text
from schema import JobPosting

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You extract structured data from job postings.

Rules:
- Extract only what the posting actually says. Never invent or infer a value.
- If a field is not mentioned, use null (or an empty list for list fields).
- Split skills into individual items. "React and Node.js" becomes two entries.
- Required skills are things the posting states as requirements. Preferred
  skills are labelled as nice-to-have, bonus, an asset, or preferred.
- Skills means technologies, languages, tools, and platforms. Do not put soft
  skills like "communication" in the skills lists.
- The text comes from a browser print of a job board page, so it may contain
  navigation menus, ads, and unrelated job listings. Extract only the main
  posting.
"""

USER_TEMPLATE = """Today's date is {today}.
This PDF was captured on {captured}.

Calculate posting_age_days from any date information in the posting. If the
posting shows a relative date such as "3 days ago", calculate it relative to
the capture date, not today. If the posting shows an absolute date, use that.
If no date information appears at all, set posting_age_days to null.

Job posting text:
---
{text}
---"""


class ExtractionError(Exception):
    """Raised when extraction fails after retries."""


def _capture_date(path: Path) -> dt.date:
    """Approximate when the PDF was captured, using file modification time."""
    return dt.date.fromtimestamp(path.stat().st_mtime)


def extract_posting(path: Path, retries: int = 2) -> JobPosting:
    """Extract structured data from one job posting PDF.

    Raises ExtractionError if the PDF is unusable or the model cannot produce
    schema-valid output within the retry budget.
    """
    text = extract_text(path)
    captured = _capture_date(path)
    today = dt.date.today()

    log.debug("Extracting posting: %s", path.name)
    log.debug("Captured %s, today %s, %d chars of text", captured, today, len(text))

    client = get_client()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": USER_TEMPLATE.format(
                today=today.isoformat(), captured=captured.isoformat(), text=text
            ),
        },
    ]

    last_error = None
    for attempt in range(1, retries + 2):
        try:
            log.debug("LLM call: %s (attempt %d)", EXTRACTION_MODEL, attempt)
            completion = client.chat.completions.parse(
                model=EXTRACTION_MODEL,
                messages=messages,
                response_format=JobPosting,
            )
            posting = completion.choices[0].message.parsed
            if posting is None:
                raise ExtractionError("model returned no parsed content")

            log.debug("Structured output validation: passed")
            log.debug(
                "Extracted %d required skills, %d preferred skills",
                len(posting.required_skills),
                len(posting.preferred_skills),
            )
            log.debug(
                "Salary: %s",
                "not listed" if posting.salary.min_amount is None else f"{posting.salary.min_amount}-{posting.salary.max_amount}",
            )
            log.debug("posting_age_days: %s", posting.posting_age_days)
            if completion.usage:
                log.debug(
                    "Tokens: %d prompt, %d completion",
                    completion.usage.prompt_tokens,
                    completion.usage.completion_tokens,
                )
            return posting

        except (ValidationError, ExtractionError) as e:
            last_error = e
            log.debug("Validation failed on attempt %d: %s", attempt, e)
        except (APIConnectionError, RateLimitError) as e:
            # Transient: worth retrying.
            last_error = e
            log.debug("Transient API error on attempt %d: %s", attempt, e)
        except APIStatusError as e:
            # 4xx other than rate limiting is a permanent problem such as a bad
            # model slug or a rejected schema. Retrying cannot help, so fail fast.
            if 400 <= e.status_code < 500 and e.status_code != 429:
                raise ExtractionError(f"permanent API error for {path.name}: {e}") from e
            last_error = e
            log.debug("Server API error on attempt %d: %s", attempt, e)
        except APIError as e:
            last_error = e
            log.debug("API error on attempt %d: %s", attempt, e)

    raise ExtractionError(f"failed to extract {path.name} after {retries + 1} attempts: {last_error}")
