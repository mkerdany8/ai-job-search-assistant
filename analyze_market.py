#!/usr/bin/env python3
"""Phase 1: extract job postings, research companies, build a market analysis.

Usage:
    python analyze_market.py [--postings DIR] [--force] [--verbose]
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from extract import extract_posting, ExtractionError  # noqa: E402
from market import build_market_analysis, save_analysis, write_report  # noqa: E402
from pdf import PdfExtractionError  # noqa: E402
from research import research_company  # noqa: E402
from store import already_extracted, load_all, output_path, save  # noqa: E402

log = logging.getLogger("phase1")


def setup_logging(verbose: bool) -> None:
    """Debug output goes to stderr so stdout stays clean."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="[%(levelname)s] %(message)s",
        stream=sys.stderr,
    )
    # Our diagnostics only. Library internals stay quiet.
    for noisy in ("openai", "httpx", "httpcore", "urllib3", "tavily"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def process_one(pdf: Path, force: bool) -> bool:
    """Extract and research a single posting. Returns True if it succeeded."""
    if not force and already_extracted(pdf):
        print(f"  skip     {pdf.name} (already extracted)")
        return True

    try:
        posting = extract_posting(pdf)
    except (ExtractionError, PdfExtractionError) as e:
        print(f"  FAILED   {pdf.name}: {e}", file=sys.stderr)
        return False

    research = research_company(posting.company_name, posting.job_title)

    out = save(posting, pdf)
    # Attach research alongside the extracted fields.
    import json
    data = json.loads(out.read_text())
    data["company_research"] = research.model_dump()
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    flag = "" if research.research_succeeded else "  (research unavailable)"
    print(f"  ok       {pdf.name} -> {out.name}{flag}")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="Phase 1: job market analysis")
    ap.add_argument("--postings", default="postings", help="directory of job posting PDFs")
    ap.add_argument("--force", action="store_true", help="re-extract even if output exists")
    ap.add_argument("--verbose", "-v", action="store_true", help="debug logging to stderr")
    args = ap.parse_args()

    setup_logging(args.verbose)

    pdf_dir = Path(args.postings)
    if not pdf_dir.is_dir():
        print(f"No such directory: {pdf_dir}", file=sys.stderr)
        return 1

    pdfs = sorted(pdf_dir.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs found in {pdf_dir}", file=sys.stderr)
        return 1

    print(f"Processing {len(pdfs)} posting(s) from {pdf_dir}/")
    failures = 0
    for pdf in pdfs:
        if not process_one(pdf, args.force):
            failures += 1

    postings = load_all()
    if not postings:
        print("No postings were extracted successfully, cannot analyze.", file=sys.stderr)
        return 1

    if failures:
        print(f"\n{failures} posting(s) failed, analyzing the remaining {len(postings)}.",
              file=sys.stderr)

    print(f"\nBuilding market analysis from {len(postings)} posting(s)...")
    try:
        analysis = build_market_analysis(postings)
    except Exception as e:
        print(f"Market analysis failed: {e}", file=sys.stderr)
        return 1

    json_path = save_analysis(analysis)
    md_path = write_report(analysis)

    print(f"\nWrote {json_path}")
    print(f"Wrote {md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
