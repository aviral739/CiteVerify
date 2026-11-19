"""DOI, arXiv, and URL extraction and normalization utilities."""

import re
from typing import Optional

# Standard DOI pattern matching 10.XXXX/...
# Handles doi:10.xxx, https://doi.org/10.xxx, http://dx.doi.org/10.xxx, etc.
DOI_PATTERN = re.compile(
    r"(?:https?://(?:dx\.)?doi\.org/|doi:\s*|DOI:\s*)?(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)",
    re.IGNORECASE,
)

# arXiv identifier pattern: arXiv:YYMM.NNNNN or arXiv:arch-ive/YYMMNNN
ARXIV_PATTERN = re.compile(
    r"(?:arxiv:\s*|https?://arxiv\.org/(?:abs|pdf)/)(\d{4}\.\d{4,5}(?:v\d+)?|[a-z\-]+(?:\.[A-Z]{2})?/\d{7})",
    re.IGNORECASE,
)

# URL pattern
URL_PATTERN = re.compile(
    r"https?://[^\s\"'<>]+",
    re.IGNORECASE,
)


def extract_doi(text: str) -> Optional[str]:
    """Extract and normalize canonical DOI from a text string."""
    if not text:
        return None

    match = DOI_PATTERN.search(text)
    if not match:
        return None

    raw_doi = match.group(1).strip()
    # Strip any trailing punctuation that might have been picked up from sentence endings
    cleaned_doi = re.sub(r"[.,;>)\s]+$", "", raw_doi)
    return normalize_doi(cleaned_doi)


def normalize_doi(doi: str) -> Optional[str]:
    """Normalize DOI to standard lowercase format starting with 10.xxxx/."""
    if not doi:
        return None

    clean = doi.strip()
    # Strip common prefixes
    clean = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", clean, flags=re.IGNORECASE)
    clean = re.sub(r"^doi:\s*", "", clean, flags=re.IGNORECASE)
    clean = clean.strip().rstrip(".").rstrip("/")

    if clean.startswith("10.") and "/" in clean:
        return clean.lower()
    return None


def extract_arxiv_id(text: str) -> Optional[str]:
    """Extract canonical arXiv identifier from a text string."""
    if not text:
        return None

    match = ARXIV_PATTERN.search(text)
    if not match:
        return None

    raw_id = match.group(1).strip()
    # Strip trailing punctuation
    return re.sub(r"[.,;>)\s]+$", "", raw_id)


def extract_url(text: str) -> Optional[str]:
    """Extract standard web URL from a text string."""
    if not text:
        return None

    match = URL_PATTERN.search(text)
    if not match:
        return None

    url = match.group(0).strip()
    return re.sub(r"[.,;>)\s]+$", "", url)
