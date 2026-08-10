"""Render the application report as a single self-contained HTML file.

No LLM involved. The model produces structured advice; this turns it into
HTML. Doing it here rather than asking for HTML back means the markup is
always valid, the five sections are always in the required order, the CSS is
not regenerated on every run, and everything that came from a job posting or
a model is escaped before it reaches the page. A posting is untrusted input,
and this report is the last place it should be able to inject markup.
"""

import datetime as dt
import html
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

REPORTS_DIR = Path("reports")

VERDICT_STYLE = {
    "green": ("#0f7b46", "#e8f6ee", "Legitimate"),
    "yellow": ("#9a6a00", "#fdf4e0", "Some caution"),
    "red": ("#b32d20", "#fdeceb", "Warning signs"),
}
UNAVAILABLE_STYLE = ("#5b6570", "#f1f3f5", "Not verified")

BAND_COLOR = {
    "strong": "#0f7b46",
    "good": "#2c7a7b",
    "stretch": "#9a6a00",
    "growth": "#5b6570",
}

DIMENSION_LABEL = {
    "required_skills": "Required skills",
    "preferred_skills": "Preferred skills",
    "experience": "Experience",
    "education": "Education",
    "market_alignment": "Market alignment",
}

CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body {
  margin: 0; padding: 0 1.25rem 4rem;
  font: 16px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  color: #1c2024; background: #fbfbfc;
}
.wrap { max-width: 52rem; margin: 0 auto; }
header.masthead { padding: 2.5rem 0 1.5rem; border-bottom: 2px solid #e6e8eb; margin-bottom: 2rem; }
header.masthead h1 { margin: 0 0 .35rem; font-size: 1.9rem; line-height: 1.25; }
header.masthead .company { font-size: 1.15rem; color: #3d4550; margin: 0 0 .75rem; }
.meta { font-size: .85rem; color: #6b7480; }
.meta span + span::before { content: "  ·  "; }
section { margin: 0 0 2.75rem; }
h2 {
  font-size: 1.3rem; margin: 0 0 1rem; padding-bottom: .5rem;
  border-bottom: 1px solid #e6e8eb;
}
h2 .num { color: #9aa3ad; font-weight: 600; margin-right: .5rem; }
h3 { font-size: 1.02rem; margin: 1.5rem 0 .6rem; }
p { margin: 0 0 .85rem; }
ul { margin: 0 0 .95rem; padding-left: 1.3rem; }
li { margin-bottom: .4rem; }
.card { background: #fff; border: 1px solid #e6e8eb; border-radius: 8px; padding: 1.1rem 1.25rem; margin-bottom: 1rem; }
.banner { border-radius: 8px; padding: 1.1rem 1.25rem; margin-bottom: 1.25rem; border-left: 5px solid; }
.banner .verdict-label { font-weight: 700; letter-spacing: .04em; text-transform: uppercase; font-size: .78rem; }
.banner .headline { font-size: 1.05rem; margin: .35rem 0 0; font-weight: 600; }
.signal { border-left: 3px solid #dcdfe3; padding: .1rem 0 .1rem .85rem; margin-bottom: .9rem; }
.signal.positive { border-left-color: #0f7b46; }
.signal.negative { border-left-color: #b32d20; }
.signal.neutral  { border-left-color: #9aa3ad; }
.signal .name { font-weight: 600; }
.signal .weight { font-size: .72rem; text-transform: uppercase; letter-spacing: .05em; color: #6b7480; margin-left: .4rem; }
.signal .evidence { color: #3d4550; font-size: .93rem; margin: .15rem 0 0; }
.score-row { display: flex; align-items: baseline; gap: .75rem; flex-wrap: wrap; margin-bottom: .6rem; }
.score-num { font-size: 2.6rem; font-weight: 700; line-height: 1; }
.score-band { font-size: 1.05rem; font-weight: 600; }
.meter { height: 10px; background: #e9ecef; border-radius: 5px; overflow: hidden; margin: .4rem 0 .9rem; }
.meter > div { height: 100%; border-radius: 5px; }
.dim { margin-bottom: 1.1rem; }
.dim-head { display: flex; justify-content: space-between; align-items: baseline; gap: 1rem; }
.dim-name { font-weight: 600; }
.dim-score { font-variant-numeric: tabular-nums; color: #3d4550; font-weight: 600; }
.dim-meter { height: 6px; background: #e9ecef; border-radius: 3px; overflow: hidden; margin: .35rem 0 .45rem; }
.dim-meter > div { height: 100%; background: #6b7480; border-radius: 3px; }
.dim .evidence { font-size: .93rem; color: #3d4550; margin: 0 0 .35rem; }
.chips { margin: .3rem 0 .2rem; }
.chip {
  display: inline-block; font-size: .8rem; padding: .16rem .55rem; border-radius: 20px;
  margin: 0 .3rem .35rem 0; background: #eef0f2; color: #3d4550; border: 1px solid #e0e3e7;
}
.chip.yes { background: #e8f6ee; color: #0b5c34; border-color: #cfe9dc; }
.chip.part { background: #fdf4e0; color: #7a5400; border-color: #f0e3c2; }
.chip.no { background: #fdeceb; color: #8f241a; border-color: #f4d5d2; }
.label { font-size: .78rem; text-transform: uppercase; letter-spacing: .05em; color: #6b7480; margin: .8rem 0 .25rem; font-weight: 600; }
.quote {
  background: #fff; border: 1px solid #e6e8eb; border-left: 4px solid #b9c0c8;
  border-radius: 6px; padding: .85rem 1rem; margin: 0 0 1rem; font-style: italic; color: #2b3138;
}
.edit { border-top: 1px solid #eceef0; padding: .9rem 0 0; margin-bottom: .9rem; }
.edit:first-of-type { border-top: 0; padding-top: 0; }
.edit .section-name { font-weight: 600; margin-bottom: .35rem; }
.edit .was { color: #6b7480; text-decoration: line-through; font-size: .93rem; margin: 0 0 .3rem; }
.edit .now { margin: 0 0 .3rem; }
.edit .why { font-size: .88rem; color: #6b7480; margin: 0; }
.qa { border-top: 1px solid #eceef0; padding-top: .9rem; margin-bottom: 1.1rem; }
.qa:first-of-type { border-top: 0; padding-top: 0; }
.qa .q { font-weight: 600; margin-bottom: .35rem; }
.qa .row { font-size: .93rem; margin: 0 0 .3rem; }
.qa .row b { color: #3d4550; font-weight: 600; }
.note { font-size: .9rem; color: #6b7480; background: #f1f3f5; border-radius: 6px; padding: .75rem .9rem; }
footer { margin-top: 3rem; padding-top: 1.25rem; border-top: 1px solid #e6e8eb; font-size: .82rem; color: #8a929c; }
@media print {
  body { background: #fff; padding: 0; }
  .card, .banner, .quote { break-inside: avoid; }
  section { break-inside: auto; }
}
"""


def esc(value) -> str:
    """Escape anything on its way into the page."""
    return html.escape("" if value is None else str(value))


def _ul(items, css_class: str = "") -> str:
    items = [i for i in (items or []) if str(i).strip()]
    if not items:
        return ""
    cls = f' class="{css_class}"' if css_class else ""
    lis = "".join(f"<li>{esc(i)}</li>" for i in items)
    return f"<ul{cls}>{lis}</ul>"


def _p(text) -> str:
    return f"<p>{esc(text)}</p>" if text and str(text).strip() else ""


def _chips(items, kind: str) -> str:
    items = [i for i in (items or []) if str(i).strip()]
    if not items:
        return ""
    return '<div class="chips">' + "".join(
        f'<span class="chip {kind}">{esc(i)}</span>' for i in items
    ) + "</div>"


def _label(text: str) -> str:
    return f'<div class="label">{esc(text)}</div>'


def _unavailable(message: str) -> str:
    return f'<div class="note">{esc(message)}</div>'


def _section_legitimacy(verdict: dict) -> str:
    """Section 1. Always first: no point reading the rest if this is a scam."""
    succeeded = verdict.get("assessment_succeeded", False)
    key = verdict.get("verdict", "yellow")
    color, background, label = (
        VERDICT_STYLE.get(key, UNAVAILABLE_STYLE) if succeeded else UNAVAILABLE_STYLE
    )

    out = [
        '<section id="legitimacy"><h2><span class="num">1</span>Legitimacy assessment</h2>',
        f'<div class="banner" style="border-left-color:{color};background:{background}">'
        f'<div class="verdict-label" style="color:{color}">{esc(label)}</div>'
        f'<p class="headline">{esc(verdict.get("headline", ""))}</p></div>',
    ]

    signals = verdict.get("signals") or []
    if signals:
        out.append(_label("Signals"))
        for s in signals:
            direction = s.get("direction", "neutral")
            if direction not in ("positive", "negative", "neutral"):
                direction = "neutral"
            out.append(
                f'<div class="signal {direction}">'
                f'<span class="name">{esc(s.get("signal", ""))}</span>'
                f'<span class="weight">{esc(s.get("weight", ""))}</span>'
                f'<p class="evidence">{esc(s.get("evidence", ""))}</p></div>'
            )

    domains = verdict.get("domains_checked") or []
    if domains:
        out.append(_label("Domains checked"))
        out.append(_chips(domains, ""))

    if verdict.get("recommendation"):
        out.append(_label("Recommendation"))
        out.append(f'<div class="card">{_p(verdict["recommendation"])}</div>')

    if not succeeded:
        out.append(_unavailable(
            "This assessment did not complete, so it is not evidence about this "
            "employer in either direction."
        ))

    out.append("</section>")
    return "".join(out)


def _section_fit(fit: dict, verdict: str = "green") -> str:
    """Section 2.

    On a red verdict the score and the dimension breakdown stay exactly as
    computed, because they honestly measure overlap with the stated
    requirements. Only the colour and the call to action change.
    """
    score = int(fit.get("overall_score", 0))
    band = fit.get("band", "growth")
    color = VERDICT_STYLE["red"][0] if verdict == "red" else BAND_COLOR.get(band, "#5b6570")

    out = [
        '<section id="fit"><h2><span class="num">2</span>Fit assessment</h2>',
        '<div class="card">',
        '<div class="score-row">'
        f'<span class="score-num" style="color:{color}">{score}%</span>'
        f'<span class="score-band" style="color:{color}">{esc(fit.get("band_label", ""))}</span>'
        "</div>",
        f'<div class="meter"><div style="width:{max(0, min(100, score))}%;background:{color}"></div></div>',
        _p(fit.get("band_message", "")),
        "</div>",
        _p(fit.get("summary", "")),
    ]

    if verdict == "red":
        # Without this the number reads as an endorsement sitting directly
        # under a fraud warning, and the reader has to reconcile the two.
        out.insert(1, (
            '<div class="banner" style="border-left-color:{c};background:{b}">'
            '<div class="verdict-label" style="color:{c}">Scored for reference only</div>'
            '<p class="headline">This posting failed its legitimacy check. The '
            "score below measures overlap with the requirements as written and "
            "is not a recommendation to apply.</p></div>"
        ).format(c=VERDICT_STYLE["red"][0], b=VERDICT_STYLE["red"][1]))

    overlap = fit.get("skill_overlap") or {}
    if overlap:
        out.append(_label("Required skills"))
        out.append(
            _chips(overlap.get("matched_required"), "yes")
            + _chips(overlap.get("implied_required"), "part")
            + _chips(overlap.get("missing_required"), "no")
        )
        if overlap.get("matched_preferred") or overlap.get("implied_preferred") or overlap.get("missing_preferred"):
            out.append(_label("Preferred skills"))
            out.append(
                _chips(overlap.get("matched_preferred"), "yes")
                + _chips(overlap.get("implied_preferred"), "part")
                + _chips(overlap.get("missing_preferred"), "no")
            )
        out.append(
            '<p class="meta">Green: on the resume. Amber: evidenced in your '
            "experience but not listed as a skill. Red: no trace found.</p>"
        )
        excluded = (overlap.get("filtered_generic_required") or []) + (
            overlap.get("filtered_generic_preferred") or []
        )
        if excluded:
            out.append(
                '<p class="meta">Not scored, as these describe the job rather '
                f'than naming a skill: {esc(", ".join(str(e) for e in excluded))}.</p>'
            )

    dimensions = fit.get("dimensions") or []
    if dimensions:
        out.append(_label("Score breakdown"))
        out.append('<div class="card">')
        for d in dimensions:
            name = DIMENSION_LABEL.get(d.get("dimension", ""), d.get("dimension", ""))
            dscore = max(0, min(100, int(d.get("score", 0))))
            out.append(
                '<div class="dim">'
                f'<div class="dim-head"><span class="dim-name">{esc(name)}</span>'
                f'<span class="dim-score">{dscore}%</span></div>'
                f'<div class="dim-meter"><div style="width:{dscore}%"></div></div>'
                f'<p class="evidence">{esc(d.get("evidence", ""))}</p>'
                "</div>"
            )
        out.append("</div>")

    if fit.get("why_apply"):
        out.append(_label("Why this is worth applying to"))
        out.append(_ul(fit["why_apply"]))
    if fit.get("transferable_strengths"):
        out.append(_label("Transferable strengths"))
        out.append(_ul(fit["transferable_strengths"]))
    if fit.get("honest_stretches"):
        out.append(_label("Where you are stretching"))
        out.append(_ul(fit["honest_stretches"]))

    if not fit.get("scoring_succeeded", True):
        out.append(_unavailable(
            "Detailed scoring was unavailable, so this score reflects computed "
            "skill overlap only."
        ))

    out.append("</section>")
    return "".join(out)


def _section_resume(advice: dict, verdict: str = "green") -> str:
    """Section 3."""
    title = "Resume notes for this type of role" if verdict == "red" else "Resume adaptation"
    out = [f'<section id="resume"><h2><span class="num">3</span>{title}</h2>']

    if not advice.get("advice_succeeded", False):
        out.append(_unavailable(advice.get("positioning_angle") or "Advice generation failed."))
        out.append("</section>")
        return "".join(out)

    if verdict == "red":
        out.append(_unavailable(
            "This posting failed its legitimacy check, so the three sections "
            "below analyse what a genuine role of this kind would involve. "
            "They are not application materials, and nothing here should be "
            "sent to this employer."
        ))

    if advice.get("positioning_angle"):
        out.append(_label("Positioning angle" if verdict != "red" else "How to position for this kind of role"))
        out.append(f'<div class="card">{_p(advice["positioning_angle"])}</div>')

    if advice.get("resume_summary_rewrite"):
        out.append(_label("Rewritten summary"))
        out.append(f'<div class="quote">{esc(advice["resume_summary_rewrite"])}</div>')

    edits = advice.get("resume_edits") or []
    if edits:
        out.append(_label("Edits"))
        out.append('<div class="card">')
        for e in edits:
            out.append('<div class="edit">')
            out.append(f'<div class="section-name">{esc(e.get("section", ""))}</div>')
            if e.get("current"):
                out.append(f'<p class="was">{esc(e["current"])}</p>')
            out.append(f'<p class="now">{esc(e.get("suggested", ""))}</p>')
            if e.get("rationale"):
                out.append(f'<p class="why">{esc(e["rationale"])}</p>')
            out.append("</div>")
        out.append("</div>")

    if advice.get("keywords_to_add"):
        out.append(_label("Keywords to work in"))
        out.append(_chips(advice["keywords_to_add"], ""))

    out.append("</section>")
    return "".join(out)


def _section_cover_letter(advice: dict, verdict: str = "green") -> str:
    """Section 4.

    On a red verdict the opening, closing, company hooks and any other
    outreach content have already been cleared upstream, so this renders as
    guidance about the role type rather than a letter.
    """
    red = verdict == "red"
    title = "What a letter for this kind of role must argue" if red else "Cover letter guidance"
    out = [f'<section id="cover-letter"><h2><span class="num">4</span>{title}</h2>']

    if not advice.get("advice_succeeded", False):
        out.append(_unavailable("Cover letter guidance was unavailable for this run."))
        out.append("</section>")
        return "".join(out)

    if advice.get("cover_letter_opening"):
        out.append(_label("Opening"))
        out.append(f'<div class="quote">{esc(advice["cover_letter_opening"])}</div>')
    if advice.get("cover_letter_points"):
        out.append(_label("Arguments to make" if red else "Body"))
        out.append(_ul(advice["cover_letter_points"]))
    if advice.get("cover_letter_closing"):
        out.append(_label("Closing"))
        out.append(f'<div class="quote">{esc(advice["cover_letter_closing"])}</div>')
    if advice.get("company_hooks"):
        out.append(_label("Company specifics worth referencing"))
        out.append(_ul(advice["company_hooks"]))
    if advice.get("address_the_gaps"):
        out.append(_label("What the gaps mean" if red else "Handling the gaps honestly"))
        out.append(_ul(advice["address_the_gaps"]))

    out.append("</section>")
    return "".join(out)


def _section_interview(advice: dict, verdict: str = "green") -> str:
    """Section 5."""
    red = verdict == "red"
    title = "What this kind of role tests" if red else "Interview prep"
    out = [f'<section id="interview"><h2><span class="num">5</span>{title}</h2>']

    if not advice.get("advice_succeeded", False):
        out.append(_unavailable("Interview prep was unavailable for this run."))
        out.append("</section>")
        return "".join(out)

    questions = advice.get("interview_questions") or []
    if questions:
        out.append('<div class="card">')
        for q in questions:
            out.append('<div class="qa">')
            out.append(f'<p class="q">{esc(q.get("question", ""))}</p>')
            if q.get("why_asked"):
                out.append(f'<p class="row"><b>What they are testing:</b> {esc(q["why_asked"])}</p>')
            if q.get("answer_strategy"):
                out.append(f'<p class="row"><b>How to answer:</b> {esc(q["answer_strategy"])}</p>')
            if q.get("from_your_background"):
                out.append(f'<p class="row"><b>Use:</b> {esc(q["from_your_background"])}</p>')
            out.append("</div>")
        out.append("</div>")

    if advice.get("questions_to_ask_them"):
        out.append(_label("Questions to ask them"))
        out.append(_ul(advice["questions_to_ask_them"]))

    out.append("</section>")
    return "".join(out)


def render_report(
    posting: dict,
    legitimacy: dict,
    fit: dict,
    advice: dict,
    source_file: Optional[str] = None,
    generated_on: Optional[str] = None,
) -> str:
    """Build the whole page. Sections are emitted in the required order."""
    title = f"{posting.get('job_title', 'Role')} at {posting.get('company_name', 'Company')}"
    generated = generated_on or dt.date.today().isoformat()

    # A failed check is not a red verdict: it means we learned nothing, so it
    # must not trigger the fraud framing.
    verdict = legitimacy.get("verdict", "yellow") if legitimacy.get("assessment_succeeded") else "unknown"

    meta = [f"<span>{esc(posting.get('location', 'Location not listed'))}</span>"]
    if posting.get("remote_status") and posting["remote_status"] != "not listed":
        meta.append(f"<span>{esc(posting['remote_status'])}</span>")
    if posting.get("posting_age_days") is not None:
        meta.append(f"<span>posted {esc(posting['posting_age_days'])} days ago</span>")
    if source_file:
        meta.append(f"<span>{esc(source_file)}</span>")
    meta.append(f"<span>generated {esc(generated)}</span>")

    body = (
        "<div class=\"wrap\">"
        '<header class="masthead">'
        f"<h1>{esc(posting.get('job_title', 'Role'))}</h1>"
        f'<p class="company">{esc(posting.get("company_name", ""))}</p>'
        f'<div class="meta">{"".join(meta)}</div>'
        "</header>"
        + _section_legitimacy(legitimacy)
        + _section_fit(fit, verdict)
        + _section_resume(advice, verdict)
        + _section_cover_letter(advice, verdict)
        + _section_interview(advice, verdict)
        + '<footer>Generated by the AIP444 application advisor. Legitimacy '
          "signals and company research come from automated web and domain "
          "lookups and can be wrong or out of date; verify anything you are "
          "going to act on.</footer>"
        "</div>"
    )

    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{esc(title)}</title>\n"
        f"<style>{CSS}</style>\n"
        "</head>\n<body>\n"
        f"{body}\n"
        "</body>\n</html>\n"
    )


def write_report(html_text: str, out_path: Optional[Path] = None) -> Path:
    """Write the report, creating the directory if needed."""
    out = out_path or (REPORTS_DIR / "application-report.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html_text, encoding="utf-8")
    log.debug("Wrote %s (%d chars)", out, len(html_text))
    return out
