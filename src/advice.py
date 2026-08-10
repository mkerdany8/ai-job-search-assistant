"""Application advice: resume adaptation, cover letter guidance, interview prep.

One structured call rather than three. The three sections have to agree with
each other, and the same angle that justifies the cover letter should be the
one the resume rewrite leans on and the one the interview answers return to.
Generating them separately makes that agreement a coincidence.
"""

import json
import logging
from typing import Optional

from pydantic import BaseModel, Field

from llm import get_client, REASONING_MODEL
from schema import JobPosting

log = logging.getLogger(__name__)


class ResumeEdit(BaseModel):
    """One concrete change to make to the resume for this application."""

    section: str = Field(description="Which part of the resume, for example 'Skills' or the name of a project")
    current: Optional[str] = Field(description="What the resume says now, quoted. Null if this is a new addition.")
    suggested: str = Field(description="The exact replacement or addition text")
    rationale: str = Field(description="Which posting requirement this serves")


class InterviewQuestion(BaseModel):
    """A question to expect, and how to answer it from this candidate's history."""

    question: str
    why_asked: str = Field(description="What the interviewer is actually testing")
    answer_strategy: str = Field(description="How to structure the answer")
    from_your_background: str = Field(
        description="The specific project, role, or course from this resume to use. Never generic."
    )


class ApplicationAdvice(BaseModel):
    """Everything the report needs for sections three, four, and five."""

    positioning_angle: str = Field(
        description="The single argument this whole application makes for this candidate"
    )
    resume_summary_rewrite: str = Field(
        description="A rewritten resume summary or profile paragraph, targeted at this posting"
    )
    resume_edits: list[ResumeEdit] = Field(description="Specific edits, most important first")
    keywords_to_add: list[str] = Field(
        description="Exact terms from the posting that should appear in the resume and honestly can"
    )
    cover_letter_opening: str = Field(description="A written opening line, not a description of one")
    cover_letter_points: list[str] = Field(
        description="What each body paragraph should argue, with the evidence to use"
    )
    cover_letter_closing: str = Field(description="A written closing line")
    company_hooks: list[str] = Field(
        description="Specifics about this employer worth referencing, from the research. Empty if research found nothing."
    )
    address_the_gaps: list[str] = Field(
        description="How to handle the missing requirements honestly, in the letter or the interview"
    )
    interview_questions: list[InterviewQuestion] = Field(description="Questions to prepare for")
    questions_to_ask_them: list[str] = Field(description="Questions to ask the interviewer, specific to this employer")
    advice_succeeded: bool = Field(description="False if this advice is not based on the real inputs")


SYSTEM_PROMPT = """You coach one candidate through one specific job
application. You are given the posting, their resume, a fit assessment
including exactly which required skills they match and miss, a market
analysis, a gap analysis, and research on the employer.

Everything you write must be usable as-is. Write the actual sentences, not
descriptions of sentences. "Open by connecting your capstone to their
platform work" is not usable. The opening line itself is.

Rules:
- Only reference experience that appears in the resume. Never invent a
  project, a job, a technology, or a number. If you want a metric that is not
  there, say the candidate should supply it and mark the spot.
- Resume edits must be honest reframings of real content. Adding a keyword
  the candidate cannot back up in an interview is bad advice.
- keywords_to_add: only terms the resume can honestly support, including ones
  the candidate already demonstrates but words differently. Nothing else.
- Use the fit assessment's missing requirements to drive address_the_gaps.
  The honest move is to name the gap, show the nearest adjacent experience,
  and show evidence of learning quickly. Never suggest hiding or implying
  something untrue.
- company_hooks come from the research only. If the research found nothing,
  return an empty list rather than generic flattery.
- Interview questions must be answerable from this resume. Name the specific
  project or role to draw on for each one. Include at least one question
  about a missing requirement, since it will come up.
- questions_to_ask_them must be specific to this employer and role. Nothing
  that could be asked of any company.
- The tone throughout treats this application as worth sending."""


def _empty_advice(reason: str) -> ApplicationAdvice:
    """Placeholder so the report can render with this section marked unavailable."""
    return ApplicationAdvice(
        positioning_angle=f"Application advice could not be generated ({reason}).",
        resume_summary_rewrite="",
        resume_edits=[],
        keywords_to_add=[],
        cover_letter_opening="",
        cover_letter_points=[],
        cover_letter_closing="",
        company_hooks=[],
        address_the_gaps=[],
        interview_questions=[],
        questions_to_ask_them=[],
        advice_succeeded=False,
    )


def build_advice(
    posting: JobPosting,
    resume: dict,
    fit: dict,
    market: dict,
    gaps: dict,
    research: Optional[dict] = None,
) -> ApplicationAdvice:
    """Generate the advice sections. Always returns an object."""
    log.debug("Building application advice for %s at %s", posting.job_title, posting.company_name)

    payload = {
        "posting": posting.model_dump(),
        "resume": resume,
        "fit_assessment": fit,
        "market_analysis": market,
        "gap_analysis": gaps,
        "company_research": research or "not available",
    }

    try:
        client = get_client()
        completion = client.chat.completions.parse(
            model=REASONING_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
            ],
            response_format=ApplicationAdvice,
            temperature=0,
        )
        advice = completion.choices[0].message.parsed
        if advice is None:
            return _empty_advice("the model returned no content")
        if completion.usage:
            log.debug("Tokens: %d prompt, %d completion",
                      completion.usage.prompt_tokens, completion.usage.completion_tokens)
    except Exception as e:
        log.debug("Advice generation failed: %s", e)
        return _empty_advice(str(e))

    log.debug(
        "Advice: %d resume edits, %d keywords, %d letter points, %d interview questions",
        len(advice.resume_edits), len(advice.keywords_to_add),
        len(advice.cover_letter_points), len(advice.interview_questions),
    )
    return advice
