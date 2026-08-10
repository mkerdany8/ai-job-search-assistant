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


# Used when the legitimacy check comes back red. The spec still wants all five
# sections, because what a role of this kind involves is worth knowing even
# when this particular posting is fraudulent. What it does not want is a
# packet of materials addressed to criminals, so this prompt produces analysis
# of the role type instead of an application to this employer.
ANALYSIS_SYSTEM_PROMPT = """You analyse a job posting that has FAILED a
legitimacy check. It is fraudulent or shows serious warning signs. The reader
is not going to apply to it and must not contact whoever posted it.

Your job is not to help them apply. It is to salvage what is useful: what a
genuine version of this role would involve, and how their resume stands
against it. Write about the role type, never to or about this employer as a
real prospective one.

Hard rules. These are not stylistic preferences:
- Never address this employer, name them as a destination for an application,
  or write anything intended to be sent to them.
- Never instruct the reader to apply, submit, contact, email, call, follow up,
  or share any document or personal detail with them.
- cover_letter_opening and cover_letter_closing must be empty strings. Do not
  write an opening or closing line for a letter to these people.
- questions_to_ask_them must be an empty list. There is nobody legitimate to
  ask.
- company_hooks must be an empty list. Do not repeat this employer's claims
  about itself; the research about them is unverified or false.

What to write instead:
- positioning_angle: how a candidate with this resume would position
  themselves for a genuine role of this type. One argument, about the role
  type, not about this employer.
- resume_summary_rewrite: a rewritten summary aimed at genuine postings of
  this kind. Useful work either way, so make it good.
- resume_edits and keywords_to_add: exactly as useful as they would be
  normally, since they improve the resume for real applications. Same honesty
  rules: only real content, reframed.
- cover_letter_points: what a cover letter for a genuine role of this type
  would need to argue, written as guidance about the role type. Not addressed
  to anyone.
- address_the_gaps: what this comparison reveals about the resume, and what
  would close those gaps before applying to a real posting of this kind.
- interview_questions: what a genuine interview for this kind of role would
  test, and how this candidate would answer from their own background. Frame
  as preparation for real interviews.
- advice_succeeded: true if you produced this analysis.

Only reference experience that appears in the resume. Never invent anything.
Write the actual sentences, not descriptions of sentences."""


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


def _strip_outreach(advice: ApplicationAdvice) -> ApplicationAdvice:
    """Remove anything that only makes sense as contact with the employer.

    The prompt already forbids these fields on a red verdict. Clearing them
    here too means a model that writes a cover letter anyway cannot get it
    onto the page.
    """
    dropped = [
        name for name, value in (
            ("cover_letter_opening", advice.cover_letter_opening),
            ("cover_letter_closing", advice.cover_letter_closing),
            ("questions_to_ask_them", advice.questions_to_ask_them),
            ("company_hooks", advice.company_hooks),
        ) if value
    ]
    if dropped:
        log.debug("Red verdict: cleared %s", ", ".join(dropped))
    return advice.model_copy(update={
        "cover_letter_opening": "",
        "cover_letter_closing": "",
        "questions_to_ask_them": [],
        "company_hooks": [],
    })


def build_advice(
    posting: JobPosting,
    resume: dict,
    fit: dict,
    market: dict,
    gaps: dict,
    research: Optional[dict] = None,
    verdict: str = "green",
) -> ApplicationAdvice:
    """Generate the advice sections. Always returns an object.

    A red legitimacy verdict switches to analysis of the role type instead of
    materials addressed to this employer.
    """
    is_red = verdict == "red"
    log.debug(
        "Building %s for %s at %s",
        "role analysis (red verdict)" if is_red else "application advice",
        posting.job_title, posting.company_name,
    )

    payload = {
        "posting": posting.model_dump(),
        "resume": resume,
        "fit_assessment": fit,
        "market_analysis": market,
        "gap_analysis": gaps,
        # On a red verdict the research describes an entity that may not exist,
        # or repeats the fraudster's own claims, so it is withheld entirely.
        "company_research": "withheld: this posting failed its legitimacy check"
        if is_red else (research or "not available"),
        "legitimacy_verdict": verdict,
    }

    try:
        client = get_client()
        completion = client.chat.completions.parse(
            model=REASONING_MODEL,
            messages=[
                {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT if is_red else SYSTEM_PROMPT},
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

    if is_red:
        advice = _strip_outreach(advice)

    log.debug(
        "Advice: %d resume edits, %d keywords, %d letter points, %d interview questions",
        len(advice.resume_edits), len(advice.keywords_to_add),
        len(advice.cover_letter_points), len(advice.interview_questions),
    )
    return advice
