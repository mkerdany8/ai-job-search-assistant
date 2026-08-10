"""Fit scoring: how well does this resume match this posting?

Skill overlap is computed in Python before the model sees anything, the same
grounding trick market.py uses for skill counts. The model scores each
dimension and explains itself; it never picks the final number or the band.
Those come from a fixed weighting and a fixed threshold table here, so the
same inputs always land in the same band.
"""

import json
import logging
import re
from typing import Literal, Optional

from pydantic import BaseModel, Field

from llm import get_client, REASONING_MODEL
from schema import JobPosting

log = logging.getLogger(__name__)

DIMENSIONS = ("required_skills", "preferred_skills", "experience", "education", "market_alignment")

WEIGHTS = {
    "required_skills": 0.45,
    "preferred_skills": 0.10,
    "experience": 0.20,
    "education": 0.10,
    "market_alignment": 0.15,
}

# Fixed thresholds. The point of keeping these out of the prompt is that the
# advice can never drift into telling the applicant not to bother.
BANDS = (
    (80, "strong", "Strong match", "Apply. You meet the bar for this role."),
    (50, "good", "Good match", "Apply. You match most of what they asked for."),
    (30, "stretch", "Stretch worth applying for",
     "Apply. Postings list wants, not hard gates, and the gaps here are the "
     "kind that get closed on the job."),
    (0, "growth", "Growth target",
     "Apply anyway if the role interests you, and treat it as a marker of "
     "what to build next. A long shot costs one application."),
)

# The encouraging call to action above is right for a real employer and wrong
# for a fraudulent one, so the legitimacy verdict overrides it here rather
# than in a prompt. The score and the dimension breakdown are honest measures
# of overlap with the stated requirements and stay exactly as computed. What
# changes is what the reader is told to do about them.
RED_LABEL = "Not an application target"

RED_MESSAGE = (
    "The legitimacy check on this posting came back red. This score measures "
    "overlap with the requirements as stated and nothing more. Do not apply, "
    "and do not send documents or personal details to this employer."
)

# Fraudulent postings keep their requirements vague so that nearly everyone
# qualifies. That inflates this score, which means a high number here is
# evidence for the fraud rather than a reason to engage. Saying so is the
# whole point: an unexplained 94% next to a red verdict reads as a conflict
# between two systems, and the reader may believe the wrong one.
RED_HIGH_SCORE_MESSAGE = (
    "The legitimacy check on this posting came back red, and this score is "
    "high because the posting asks for almost nothing. Vague, trivially "
    "satisfiable requirements are how fraudulent postings maximise the number "
    "of people who respond, so read this score as another fraud signal rather "
    "than as a reason to apply. Do not send documents or personal details to "
    "this employer."
)

# High enough that the score reads as an endorsement if left unexplained.
RED_HIGH_SCORE_THRESHOLD = 50

YELLOW_SUFFIX = (
    " The legitimacy check did not fully verify this employer, so confirm the "
    "posting on their own careers page before sending anything."
)


class SkillOverlap(BaseModel):
    """Exact, computed overlap between the resume and the posting."""

    matched_required: list[str] = Field(description="Required skills the resume lists directly")
    implied_required: list[str] = Field(description="Required skills that appear in resume prose but not in the skills list")
    missing_required: list[str] = Field(description="Required skills with no trace in the resume")
    matched_preferred: list[str]
    implied_preferred: list[str]
    missing_preferred: list[str]
    required_coverage_pct: int = Field(description="Percent of required skills matched, implied counting half")
    preferred_coverage_pct: int
    filtered_generic_required: list[str] = Field(
        description="Required entries excluded from scoring as generic engineering activities rather than named skills"
    )
    filtered_generic_preferred: list[str] = Field(
        description="Preferred entries excluded from scoring for the same reason"
    )


class DimensionScore(BaseModel):
    """One scored dimension with the evidence behind the score."""

    dimension: Literal["required_skills", "preferred_skills", "experience", "education", "market_alignment"]
    score: int = Field(description="0 to 100")
    evidence: str = Field(description="Why this score, citing specific resume and posting content")
    matched: list[str] = Field(description="What lines up on this dimension. Empty if nothing does.")
    missing: list[str] = Field(description="What does not line up. Empty if nothing is missing.")


class FitScoring(BaseModel):
    """What the model produces. The overall number is computed from this."""

    dimensions: list[DimensionScore] = Field(description="One entry per dimension you can assess")
    summary: str = Field(description="Two or three sentences on how this candidate lines up with this role")
    why_apply: list[str] = Field(description="Concrete reasons this application is worth sending")
    transferable_strengths: list[str] = Field(description="Resume items that cover a requirement indirectly")
    honest_stretches: list[str] = Field(description="Where the candidate genuinely falls short, stated plainly and without discouraging them")


class FitAssessment(BaseModel):
    """The finished assessment: model judgement plus locally computed scoring."""

    overall_score: int
    band: Literal["strong", "good", "stretch", "growth"] = Field(
        description="Requirement-overlap band. Independent of legitimacy: it says nothing about whether to apply."
    )
    band_label: str
    band_message: str
    advisory: Literal["apply", "verify_first", "do_not_engage"] = Field(
        description="What to do about this posting, derived from the legitimacy verdict rather than the score"
    )
    dimensions: list[DimensionScore]
    skill_overlap: SkillOverlap
    summary: str
    why_apply: list[str]
    transferable_strengths: list[str]
    honest_stretches: list[str]
    scoring_succeeded: bool


SYSTEM_PROMPT = """You score how well one candidate fits one job posting, for
the candidate's own use.

You are given the posting, the candidate's resume, a market analysis built
from real postings in this field, a gap analysis of this candidate, and an
exact skill overlap computed from the resume and posting text.

Use the computed overlap as ground truth for which skills match. Do not
re-derive it or contradict it.

The overlap's filtered_generic_required and filtered_generic_preferred lists
hold entries the posting stated as requirements that name no specific
technology, such as "coding" or "unit testing". They are excluded from
coverage on purpose, because counting them would penalise the candidate for
not listing words that describe the job rather than a skill. You may refer to
them in your evidence where it is useful, but never treat them as matched or
missing skills.

Score each dimension 0 to 100:
- required_skills: coverage of the stated requirements. Start from the
  computed coverage and adjust only for things it cannot see, such as one
  listed requirement being far more central to the role than the others.
- preferred_skills: coverage of the nice-to-haves. If the posting lists none,
  omit this dimension entirely rather than inventing a score.
- experience: the candidate's experience against what the posting asks for.
  Projects, coursework, and internships count as real experience for entry
  level roles. Be realistic for senior roles that ask for many years.
- education: the credential against what the posting asks for.
- market_alignment: how well this candidate's profile matches what the wider
  market analysis says employers in this field actually want.

Omit any dimension you genuinely cannot assess. Do not guess a score to fill
a slot.

Every score needs evidence naming specific resume and posting content.

You are also given legitimacy_verdict, the result of a separate check on
whether this posting is a real job at a real company.

When legitimacy_verdict is "red", the posting is fraudulent or shows serious
warning signs. Score the requirement overlap exactly as honestly as you would
otherwise, because it is a real measurement, but change what you write around
it:
- why_apply must be an empty list. There is no reason to apply to a fraud.
- The summary must not encourage applying, must not describe the role as an
  opportunity, and must not address the employer as a real prospective one.
- If the score is high, say why in the summary: these postings state vague,
  trivially satisfiable requirements precisely so that everyone appears
  qualified, so a high overlap score on a red posting is a further sign of
  fraud rather than a sign of fit.
- Never suggest contacting them, applying, or sending anything.

When the verdict is "yellow", write normally but do not oversell the
employer, and treat the company as unverified.

On tone for green and yellow postings. This scoring exists to help someone
decide where to spend their applications, not to talk them out of applying. Job postings list wishes, not
gates, and candidates who meet most of a posting still get hired. So:
- Never advise against applying on the basis of a weak fit. That is not your
  call, and the final recommendation is generated elsewhere. This is about
  fit only, and does not override the red-verdict rules above.
- Do not pad the scores either. An honest low score with a clear explanation
  of what is missing is useful. A dishonest high one is not.
- State shortfalls plainly in honest_stretches, as facts about the gap rather
  than judgements about the candidate.
- why_apply must be grounded in what the candidate actually has. If the fit
  is weak, the honest reasons are things like relevant adjacent skills, or
  the value of getting on this employer's radar, not invented qualifications."""


# Words that carry no identifying weight in a skill name, so "REST APIs" and
# "experience with REST API development" reduce to the same thing.
_STOPWORDS = {
    "and", "or", "the", "of", "in", "with", "for", "a", "an", "to", "on", "using",
    "based", "experience", "knowledge", "skills", "skill", "proficiency", "strong",
    "familiarity", "understanding", "development", "developing", "tools", "tool",
    "technologies", "technology", "frameworks", "framework", "systems", "system",
    "working", "such", "as", "e.g", "etc", "including", "plus", "related",
}

# How many trailing characters two tokens may differ by and still count as the
# same word. 3 lets rest/restful and postgres/postgresql through while keeping
# java/javascript apart, which is the pair that actually matters here.
_STEM_SLACK = 3


def _norm(text: str) -> str:
    """Lowercase and strip punctuation, keeping the characters that carry
    meaning in tech names: C++, C#, .NET, Node.js."""
    s = text.lower().strip()
    s = re.sub(r"[^a-z0-9+#.\s]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _tokens(text: str) -> list:
    """Meaningful tokens of a skill name or phrase.

    Trailing dots are stripped because _norm keeps '.' on purpose, for .NET
    and Node.js, which otherwise leaves sentence-final periods stuck to prose
    tokens: 'api.' would never match 'api'. Leading dots survive, so .NET
    still reads the same on both sides of a comparison.
    """
    out = []
    for token in _norm(text).split():
        token = token.rstrip(".")
        if token and token not in _STOPWORDS:
            out.append(token)
    return out


def _singular(token: str) -> str:
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _token_match(a: str, b: str) -> bool:
    """Same word, allowing plurals and a short suffix difference."""
    a, b = _singular(a), _singular(b)
    if a == b:
        return True
    # Prefix stemming, but only across a small gap. Without the cap this
    # happily matches 'java' to 'javascript', which is a wrong answer that
    # inflates the score.
    if len(a) >= 4 and len(b) >= 4:
        short, long_ = (a, b) if len(a) < len(b) else (b, a)
        if long_.startswith(short) and len(long_) - len(short) <= _STEM_SLACK:
            return True
    return False


# Extraction returns what the posting asked for, faithfully, which is what
# data/jobs/ should hold. But postings describe the job as well as list its
# tools, so "solid engineering fundamentals, including coding, debugging and
# unit testing" arrives as separate requirements. Counting those dilutes the
# denominator here: every generic entry is one more thing to miss, and how
# many of them a posting yields varies run to run for the same PDF. So the
# judgement call lives here, in scoring, and nowhere else.
#
# The test is the one applied to the field descriptions: does the entry name a
# specific technology, or a practice with a recognised name? If it only
# describes what any software job involves doing, it does not belong in the
# denominator.
_GENERIC_ACTIVITIES = (
    "coding", "programming", "debugging", "testing", "unit testing",
    "integration testing", "automated testing", "quality assurance",
    "troubleshooting", "problem solving", "analytical skills", "communication",
    "collaboration", "teamwork", "documentation", "code review", "maintenance",
    "software delivery", "software delivery practices", "software engineering",
    "software engineering fundamentals", "engineering fundamentals",
    "software development lifecycle", "system development lifecycle", "sdlc",
    "infrastructure", "applications integration", "application integration",
    "system and technology integration", "technology integration",
)

# Named practices that survive, even though they contain a generic word.
# Without these, "Test Driven Development" is filtered by "testing" and
# "Infrastructure as Code" by "infrastructure".
_NAMED_PRACTICES = (
    "ci cd", "continuous integration", "continuous delivery",
    "continuous deployment", "rest api", "restful api", "graphql", "grpc",
    "agile", "scrum", "kanban", "devops", "tdd", "test driven development",
    "bdd", "behaviour driven development", "behavior driven development",
    "infrastructure as code", "iac", "version control", "source control",
    "object oriented programming", "object oriented design", "pair programming",
)


def _covers(skill_tokens: list, candidate_tokens) -> bool:
    """True if every token of the skill has a counterpart in the candidate."""
    if not skill_tokens:
        return False
    return all(any(_token_match(s, c) for c in candidate_tokens) for s in skill_tokens)


def _term_covers_skill(skill_tokens: list, term_tokens: list) -> bool:
    """Does this one resume term cover this posting skill?

    Forward: every token of the skill appears in the term, so "Linux" is
    covered by "Linux administration".

    Reverse: every token of the term appears in the skill, so "CI/CD" covers
    "CI/CD pipelines". This only applies to terms of two or more tokens.
    Allowing it for single tokens would let "Java" swallow "Java Spring Boot",
    which is a different requirement the candidate has not claimed.
    """
    if _covers(skill_tokens, term_tokens):
        return True
    if len(term_tokens) >= 2 and _covers(term_tokens, skill_tokens):
        return True
    return False


def _resume_terms(resume: dict) -> tuple:
    """Tokenised skill terms, plus a prose token set for implied matches."""
    terms = []
    seen = set()
    for field in ("hard_skills", "domain_keywords", "certifications"):
        for item in resume.get(field) or []:
            toks = _tokens(str(item))
            key = " ".join(toks)
            if toks and key not in seen:
                seen.add(key)
                terms.append(toks)
    for project in resume.get("projects") or []:
        for tech in project.get("technologies") or []:
            toks = _tokens(str(tech))
            key = " ".join(toks)
            if toks and key not in seen:
                seen.add(key)
                terms.append(toks)

    prose_parts = []
    for job in resume.get("work_experience") or []:
        prose_parts.append(job.get("role") or "")
        prose_parts.extend(job.get("highlights") or [])
    for project in resume.get("projects") or []:
        prose_parts.append(project.get("name") or "")
        prose_parts.append(project.get("description") or "")
    for edu in resume.get("education") or []:
        prose_parts.append(edu.get("credential") or "")
        prose_parts.extend(edu.get("coursework") or [])
    prose_parts.extend(str(s) for s in resume.get("soft_skills") or [])

    prose_tokens = set(_tokens(" ".join(p for p in prose_parts if p)))
    return terms, prose_tokens


# Tokenised once at import, since every skill on every posting is tested
# against both lists.
_GENERIC_ACTIVITY_TOKENS = [_tokens(s) for s in _GENERIC_ACTIVITIES]
_NAMED_PRACTICE_TOKENS = [_tokens(s) for s in _NAMED_PRACTICES]


def _is_generic(skill: str) -> bool:
    """True if this entry describes the work rather than naming a skill."""
    toks = _tokens(skill)
    if not toks:
        return False
    # A recognised name wins, even when it contains a generic word.
    if any(_covers(exc, toks) for exc in _NAMED_PRACTICE_TOKENS):
        return False
    return any(_covers(gen, toks) for gen in _GENERIC_ACTIVITY_TOKENS)


def _filter_generic(skills: list, label: str) -> tuple:
    """Split a posting's skill list into named skills and generic prose.

    If every entry is generic, the whole list is kept. A posting written
    entirely in prose still has requirements, and scoring it against an empty
    denominator would report 0% coverage, which is a worse answer than a
    diluted one.
    """
    named, dropped = [], []
    for skill in skills or []:
        (dropped if _is_generic(skill) else named).append(skill)

    if dropped:
        log.debug("Filtered %d generic %s entr(ies): %s", len(dropped), label, dropped)
    if skills and not named:
        log.debug(
            "All %d %s entries were generic, scoring against the full list instead",
            len(skills), label,
        )
        return list(skills), []
    return named, dropped


def _classify(skills: list, terms: list, prose_tokens: set) -> tuple:
    """Split posting skills into matched, implied, and missing.

    matched: the skill is named in the resume's own skill lists.
    implied: the resume evidences it in prose but never lists it. This is the
             most actionable category, since it is fixed by editing wording.
    """
    matched, implied, missing = [], [], []
    for skill in skills:
        toks = _tokens(str(skill))
        if not toks:
            continue
        if any(_term_covers_skill(toks, term) for term in terms):
            matched.append(skill)
        elif _covers(toks, prose_tokens):
            implied.append(skill)
        else:
            missing.append(skill)
    return matched, implied, missing


def _coverage(matched: list, implied: list, missing: list) -> int:
    """Implied matches count half: the skill is evidenced but not advertised."""
    total = len(matched) + len(implied) + len(missing)
    if total == 0:
        return 0
    return round(100 * (len(matched) + 0.5 * len(implied)) / total)


def compute_overlap(posting: JobPosting, resume: dict) -> SkillOverlap:
    """Exact skill overlap, computed locally. No model involved.

    Generic entries are dropped from both sides of the fraction before
    anything is counted, so they neither inflate the denominator nor earn
    credit in the numerator.
    """
    terms, prose = _resume_terms(resume)

    required, dropped_required = _filter_generic(posting.required_skills, "required")
    preferred, dropped_preferred = _filter_generic(posting.preferred_skills, "preferred")

    mr, ir, xr = _classify(required, terms, prose)
    mp, ip, xp = _classify(preferred, terms, prose)

    overlap = SkillOverlap(
        matched_required=mr, implied_required=ir, missing_required=xr,
        matched_preferred=mp, implied_preferred=ip, missing_preferred=xp,
        required_coverage_pct=_coverage(mr, ir, xr),
        preferred_coverage_pct=_coverage(mp, ip, xp),
        filtered_generic_required=dropped_required,
        filtered_generic_preferred=dropped_preferred,
    )
    log.debug(
        "Skill overlap: required %d matched / %d implied / %d missing (%d%%), "
        "preferred %d/%d/%d (%d%%), %d generic entr(ies) excluded from scoring",
        len(mr), len(ir), len(xr), overlap.required_coverage_pct,
        len(mp), len(ip), len(xp), overlap.preferred_coverage_pct,
        len(dropped_required) + len(dropped_preferred),
    )
    return overlap


def band_for(score: int, verdict: str = "green") -> tuple:
    """Map a score and a legitimacy verdict to (band, label, message, advisory).

    Fixed table, no model involvement. The band always reflects requirement
    overlap honestly; the verdict decides what the reader is told to do with
    it. Keeping this in Python rather than in a prompt means a red posting can
    never be handed an encouraging call to action, however the model phrases
    things on a given run.
    """
    band, label, message = BANDS[-1][1:]
    for threshold, b, lab, msg in BANDS:
        if score >= threshold:
            band, label, message = b, lab, msg
            break

    if verdict == "red":
        high = score >= RED_HIGH_SCORE_THRESHOLD
        return band, RED_LABEL, (RED_HIGH_SCORE_MESSAGE if high else RED_MESSAGE), "do_not_engage"
    if verdict == "green":
        return band, label, message, "apply"
    # Yellow, or a check that could not complete. Neither is evidence against
    # the employer, but neither confirms them either, so an unqualified
    # "Apply." is more than we know.
    return band, label, message + YELLOW_SUFFIX, "verify_first"


def _combine(dimensions: list, overlap: SkillOverlap) -> int:
    """Weighted average over the dimensions we actually have.

    Weights are renormalised over present dimensions, so omitting a dimension
    that does not apply does not silently drag the score down.
    """
    seen = {}
    for d in dimensions:
        if d.dimension in WEIGHTS and d.dimension not in seen:
            seen[d.dimension] = max(0, min(100, d.score))

    # required_skills anchors the score, so fall back to the computed value
    # rather than dropping it if the model left it out.
    if "required_skills" not in seen:
        log.debug("Model omitted required_skills, using computed coverage")
        seen["required_skills"] = overlap.required_coverage_pct

    total_weight = sum(WEIGHTS[k] for k in seen)
    score = sum(WEIGHTS[k] * v for k, v in seen.items()) / total_weight
    log.debug("Dimension scores: %s -> overall %d", seen, round(score))
    return round(score)


def _fallback(
    posting: JobPosting, overlap: SkillOverlap, reason: str, verdict: str = "green"
) -> FitAssessment:
    """Scoring from the computed overlap alone, when the model call fails."""
    log.debug("Falling back to computed-only scoring: %s", reason)
    score = overlap.required_coverage_pct
    band, label, message, advisory = band_for(score, verdict)
    return FitAssessment(
        overall_score=score,
        band=band,
        band_label=label,
        band_message=message,
        advisory=advisory,
        dimensions=[
            DimensionScore(
                dimension="required_skills",
                score=score,
                evidence=(
                    f"Computed from skill overlap only: {len(overlap.matched_required)} "
                    f"of {len(overlap.matched_required) + len(overlap.implied_required) + len(overlap.missing_required)} "
                    "required skills matched directly."
                ),
                matched=overlap.matched_required,
                missing=overlap.missing_required,
            )
        ],
        skill_overlap=overlap,
        summary=(
            f"Detailed scoring was unavailable ({reason}), so this is the raw "
            f"skill overlap against the {posting.job_title} posting only."
        ),
        why_apply=(
            []
            if verdict == "red"
            else [f"{len(overlap.matched_required)} of the required skills are already on the resume."]
        ),
        transferable_strengths=[],
        honest_stretches=list(overlap.missing_required),
        scoring_succeeded=False,
    )


def score_fit(
    posting: JobPosting,
    resume: dict,
    market: dict,
    gaps: dict,
    research: Optional[dict] = None,
    verdict: str = "green",
) -> FitAssessment:
    """Score this resume against this posting. Always returns an assessment."""
    overlap = compute_overlap(posting, resume)

    payload = {
        "posting": posting.model_dump(),
        "resume": resume,
        "computed_skill_overlap": overlap.model_dump(),
        "market_analysis": market,
        "gap_analysis": gaps,
        "company_research": research or "not available",
        "legitimacy_verdict": verdict,
    }

    try:
        client = get_client()
        completion = client.chat.completions.parse(
            model=REASONING_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
            ],
            response_format=FitScoring,
            temperature=0,
        )
        scoring = completion.choices[0].message.parsed
        if scoring is None:
            return _fallback(posting, overlap, "the model returned no scoring", verdict)
        if completion.usage:
            log.debug("Tokens: %d prompt, %d completion",
                      completion.usage.prompt_tokens, completion.usage.completion_tokens)
    except Exception as e:
        return _fallback(posting, overlap, str(e), verdict)

    # Clamp anything out of range before it reaches the arithmetic.
    dimensions = [
        d.model_copy(update={"score": max(0, min(100, d.score))})
        for d in scoring.dimensions
        if d.dimension in WEIGHTS
    ]
    score = _combine(dimensions, overlap)
    band, label, message, advisory = band_for(score, verdict)

    # Reasons to apply have no place on a posting we are telling the reader not
    # to apply to. Cleared here as well as forbidden in the prompt, so a model
    # that writes them anyway cannot get them onto the page.
    why_apply = [] if verdict == "red" else scoring.why_apply
    if verdict == "red" and scoring.why_apply:
        log.debug("Red verdict: dropped %d why_apply item(s)", len(scoring.why_apply))

    log.debug("Fit: %d%% -> %s (%s), advisory=%s", score, band, label, advisory)
    return FitAssessment(
        overall_score=score,
        band=band,
        band_label=label,
        band_message=message,
        advisory=advisory,
        dimensions=dimensions,
        skill_overlap=overlap,
        summary=scoring.summary,
        why_apply=why_apply,
        transferable_strengths=scoring.transferable_strengths,
        honest_stretches=scoring.honest_stretches,
        scoring_succeeded=True,
    )
