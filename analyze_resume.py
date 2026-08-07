#!/usr/bin/env python3
"""Phase 2: parse a resume, compare it to the market analysis, triage the gaps.

Usage:
    python analyze_resume.py [--resume PATH] [--force] [--verbose]
"""

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from pdf import PdfExtractionError  # noqa: E402
from resume import (  # noqa: E402
    analyze_gaps, parse_resume, save_gap_analysis, save_resume, write_gap_report,
)
from resume_schema import Resume  # noqa: E402

MARKET_JSON = Path("data/analysis/market-analysis.json")
RESUME_JSON = Path("data/resume/resume.json")
RESUME_DIR = Path("data/resume")

log = logging.getLogger("phase2")


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="[%(levelname)s] %(message)s",
        stream=sys.stderr,
    )
    for noisy in ("openai", "httpx", "httpcore", "urllib3", "tavily"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def find_resume() -> "Path | None":
    """Find the resume file in data/resume/, ignoring our own output."""
    candidates = [
        p for p in RESUME_DIR.glob("*")
        if p.suffix.lower() == ".pdf" and p.name != "resume.json"
    ]
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        print(f"Multiple PDFs in {RESUME_DIR}/, pass --resume to choose one:", file=sys.stderr)
        for c in candidates:
            print(f"  {c}", file=sys.stderr)
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Phase 2: resume gap analysis")
    ap.add_argument("--resume", help="path to resume PDF (defaults to the one in data/resume/)")
    ap.add_argument("--force", action="store_true", help="re-parse the resume even if resume.json exists")
    ap.add_argument("--verbose", "-v", action="store_true", help="debug logging to stderr")
    args = ap.parse_args()

    setup_logging(args.verbose)

    if not MARKET_JSON.exists():
        print(f"{MARKET_JSON} not found. Run Phase 1 first:", file=sys.stderr)
        print("  python analyze_market.py", file=sys.stderr)
        return 1
    market = json.loads(MARKET_JSON.read_text())
    log.debug("Loaded market analysis covering %d postings", market.get("postings_analyzed", 0))

    # Reuse the parsed resume unless asked not to, same skip idea as Phase 1.
    if RESUME_JSON.exists() and not args.force:
        print(f"Using existing {RESUME_JSON} (--force to re-parse)")
        resume = Resume.model_validate_json(RESUME_JSON.read_text())
    else:
        path = Path(args.resume) if args.resume else find_resume()
        if path is None:
            print(f"No resume PDF found in {RESUME_DIR}/. Put one there or pass --resume.",
                  file=sys.stderr)
            return 1
        print(f"Parsing {path.name}...")
        try:
            resume = parse_resume(path)
        except (PdfExtractionError, ValueError) as e:
            print(f"Could not parse resume: {e}", file=sys.stderr)
            return 1
        out = save_resume(resume)
        print(f"Wrote {out}")

    print("Analyzing gaps against the market...")
    try:
        analysis = analyze_gaps(resume, market)
    except Exception as e:
        print(f"Gap analysis failed: {e}", file=sys.stderr)
        return 1

    json_path = save_gap_analysis(analysis)
    md_path = write_gap_report(analysis)

    print(f"\nWrote {json_path}")
    print(f"Wrote {md_path}")

    from collections import Counter
    levels = Counter(g.level for g in analysis.gaps)
    print(f"\n{len(analysis.strengths)} strengths, {len(analysis.gaps)} gaps:")
    for level in ("quick win", "short-term", "medium-term", "long-term"):
        if levels[level]:
            print(f"  {levels[level]} {level}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
