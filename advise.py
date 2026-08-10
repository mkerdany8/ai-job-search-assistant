#!/usr/bin/env python3
"""Phase 3: turn one job posting PDF into an application report.

Usage:
    python advise.py POSTING.pdf [--out PATH] [--verbose]

Runs a fixed pipeline: extract the posting, load the Phase 1 and Phase 2
analyses, research the company, assess legitimacy, score fit, generate
advice, render HTML. The two agentic steps (company research, legitimacy)
are bounded loops inside their own modules.
"""

import argparse
import datetime as dt
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from advice import build_advice  # noqa: E402
from extract import extract_posting, ExtractionError  # noqa: E402
from fit import score_fit  # noqa: E402
from legitimacy import assess_legitimacy  # noqa: E402
from pdf import extract_text, PdfExtractionError  # noqa: E402
from report import render_report, write_report  # noqa: E402
from research import research_company  # noqa: E402
from store import slugify  # noqa: E402

MARKET_JSON = Path("data/analysis/market-analysis.json")
GAPS_JSON = Path("data/analysis/gap-analysis.json")
RESUME_JSON = Path("data/resume/resume.json")
APPLICATIONS_DIR = Path("data/applications")
DEFAULT_OUT = Path("reports/application-report.html")

log = logging.getLogger("phase3")


def setup_logging(verbose: bool) -> None:
    """Debug output goes to stderr so stdout stays clean."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="[%(levelname)s] %(message)s",
        stream=sys.stderr,
    )
    for noisy in ("openai", "httpx", "httpcore", "urllib3", "tavily"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def load_inputs() -> "tuple | None":
    """Load the Phase 1 and Phase 2 outputs this report is built on."""
    missing = [p for p in (MARKET_JSON, GAPS_JSON, RESUME_JSON) if not p.exists()]
    if missing:
        print("Missing required data from earlier phases:", file=sys.stderr)
        for p in missing:
            print(f"  {p}", file=sys.stderr)
        print("\nRun these first:", file=sys.stderr)
        print("  python analyze_market.py", file=sys.stderr)
        print("  python analyze_resume.py", file=sys.stderr)
        return None

    try:
        market = json.loads(MARKET_JSON.read_text())
        gaps = json.loads(GAPS_JSON.read_text())
        resume = json.loads(RESUME_JSON.read_text())
    except json.JSONDecodeError as e:
        print(f"Could not read stored analysis: {e}", file=sys.stderr)
        return None

    log.debug(
        "Loaded market analysis (%d postings), gap analysis (%d gaps), resume (%d hard skills)",
        market.get("postings_analyzed", 0), len(gaps.get("gaps", [])), len(resume.get("hard_skills", [])),
    )
    return market, gaps, resume


def save_application(payload: dict, slug: str) -> Path:
    """Persist the structured result so the report can be traced back."""
    APPLICATIONS_DIR.mkdir(parents=True, exist_ok=True)
    out = APPLICATIONS_DIR / f"{slug}.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    log.debug("Wrote %s", out)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Phase 3: application advisor")
    ap.add_argument("posting", help="path to the job posting PDF")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help=f"output HTML path (default {DEFAULT_OUT})")
    ap.add_argument("--verbose", "-v", action="store_true", help="debug logging to stderr")
    args = ap.parse_args()

    setup_logging(args.verbose)

    pdf = Path(args.posting)
    if not pdf.exists():
        print(f"No such file: {pdf}", file=sys.stderr)
        return 1

    loaded = load_inputs()
    if loaded is None:
        return 1
    market, gaps, resume = loaded

    # 1. Extract the posting. This one is fatal: without it there is no report.
    print(f"Extracting {pdf.name}...")
    try:
        posting = extract_posting(pdf)
    except (ExtractionError, PdfExtractionError) as e:
        print(f"Could not extract the posting: {e}", file=sys.stderr)
        return 1
    print(f"  {posting.job_title} at {posting.company_name}")

    # Raw text again for the legitimacy check: the extracted schema has no
    # website field, so contact domains only exist in the original text.
    try:
        raw_text = extract_text(pdf)
    except PdfExtractionError as e:
        log.debug("Could not re-read PDF text for domain seeding: %s", e)
        raw_text = ""

    # 2. Company research (agentic, bounded).
    print("Researching the company...")
    research = research_company(posting.company_name, posting.job_title)
    if not research.research_succeeded:
        print("  research unavailable, continuing without it")
    research_data = research.model_dump()

    # 3. Legitimacy (agentic, bounded).
    print("Checking legitimacy...")
    verdict_obj = assess_legitimacy(posting, raw_text, research_data)
    if verdict_obj.assessment_succeeded:
        negatives = sum(1 for s in verdict_obj.signals if s.direction == "negative")
        print(f"  {verdict_obj.verdict.upper()} — {len(verdict_obj.signals)} signal(s), {negatives} negative")
    else:
        print("  could not complete, reported as unverified")

    # A failed check tells us nothing, so it must not be treated as a red one.
    verdict = verdict_obj.verdict if verdict_obj.assessment_succeeded else "unknown"

    # 4. Fit scoring. The verdict governs the call to action, not the score.
    print("Scoring fit...")
    fit = score_fit(posting, resume, market, gaps, research_data, verdict)
    print(f"  {fit.overall_score}% — {fit.band_label}")

    # 5. Advice. A red verdict switches this to role analysis.
    print("Generating advice...")
    advice = build_advice(posting, resume, fit.model_dump(), market, gaps, research_data, verdict)
    if not advice.advice_succeeded:
        print("  advice generation failed, those sections will say so")

    # 6. Report.
    html_text = render_report(
        posting=posting.model_dump(),
        legitimacy=verdict_obj.model_dump(),
        fit=fit.model_dump(),
        advice=advice.model_dump(),
        source_file=pdf.name,
    )
    out_path = write_report(html_text, Path(args.out))

    slug = slugify(f"{posting.job_title} {posting.company_name}")
    saved = save_application(
        {
            "generated_on": dt.date.today().isoformat(),
            "source_file": pdf.name,
            "posting": posting.model_dump(),
            "company_research": research_data,
            "legitimacy": verdict_obj.model_dump(),
            "fit": fit.model_dump(),
            "advice": advice.model_dump(),
        },
        slug,
    )

    print(f"\nWrote {out_path}")
    print(f"Wrote {saved}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
