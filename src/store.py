"""Reading and writing extracted posting data."""

import hashlib
import json
import logging
import re
from pathlib import Path

from schema import JobPosting

log = logging.getLogger(__name__)

JOBS_DIR = Path("data/jobs")


def slugify(text: str) -> str:
    """Turn a title or company name into a filename-safe slug."""
    s = text.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return re.sub(r"-+", "-", s).strip("-")


def source_hash(pdf_path: Path) -> str:
    """Short hash of the PDF bytes, used to detect changed source files."""
    return hashlib.sha256(pdf_path.read_bytes()).hexdigest()[:12]


def output_path(pdf_path: Path) -> Path:
    """Where the JSON for a given PDF lives.

    Named from the PDF filename so we can check for existing output before
    spending money on an LLM call.
    """
    return JOBS_DIR / f"{slugify(pdf_path.stem)}.json"


def already_extracted(pdf_path: Path) -> bool:
    """True if this PDF has been extracted and the source has not changed."""
    out = output_path(pdf_path)
    if not out.exists():
        return False
    try:
        data = json.loads(out.read_text())
    except json.JSONDecodeError:
        log.debug("%s is corrupt, will re-extract", out.name)
        return False
    return data.get("_source_hash") == source_hash(pdf_path)


def save(posting: JobPosting, pdf_path: Path) -> Path:
    """Write a posting to data/jobs/, tagged with its source file and hash."""
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    out = output_path(pdf_path)
    data = posting.model_dump()
    data["_source_file"] = pdf_path.name
    data["_source_hash"] = source_hash(pdf_path)
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    log.debug("Saved %s", out)
    return out


def load_all() -> list[dict]:
    """Load every extracted posting JSON."""
    if not JOBS_DIR.exists():
        return []
    out = []
    for f in sorted(JOBS_DIR.glob("*.json")):
        try:
            out.append(json.loads(f.read_text()))
        except json.JSONDecodeError:
            log.debug("Skipping corrupt file %s", f.name)
    return out
