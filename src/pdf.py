"""PDF text extraction."""

import logging
from pathlib import Path

from pypdf import PdfReader

log = logging.getLogger(__name__)


class PdfExtractionError(Exception):
    """Raised when a PDF cannot be read or contains no usable text."""


def extract_text(path: Path, min_chars: int = 200) -> str:
    """Read a PDF and return its text.

    Raises PdfExtractionError if the file is unreadable or has too little
    text to be a real posting (for example a scanned image with no text layer).
    """
    if not path.exists():
        raise PdfExtractionError(f"file not found: {path}")

    try:
        reader = PdfReader(str(path))
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception as e:
        raise PdfExtractionError(f"could not parse {path.name}: {e}") from e

    text = "\n".join(pages).strip()
    log.debug("Extracted %d chars from %d pages in %s", len(text), len(pages), path.name)

    if len(text) < min_chars:
        raise PdfExtractionError(
            f"{path.name} yielded only {len(text)} chars, likely a scanned PDF with no text layer"
        )

    return text


# pypdf logs structural warnings for browser-printed PDFs. The text extracts
# fine, so quiet these to keep our own stderr debug output readable.
logging.getLogger("pypdf").setLevel(logging.ERROR)
