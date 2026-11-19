"""Bibliography detection, segmentation, and metadata extraction."""

import re
import uuid
from typing import Dict, List, Optional, Tuple
from app.stages.s2_references.doi_utils import extract_arxiv_id, extract_doi, extract_url
from app.stages.s2_references.models import ExtractedReferenceItem

# Headings that signal bibliography
BIBLIOGRAPHY_HEADINGS = [
    r"^(?:\d+[\.\s]*)?references\b",
    r"^(?:\d+[\.\s]*)?bibliography\b",
    r"^(?:\d+[\.\s]*)?works\s+cited\b",
    r"^(?:\d+[\.\s]*)?literature\s+cited\b",
    r"^(?:\d+[\.\s]*)?references\s+and\s+notes\b",
]

# Patterns for bibliography entry segmentation
# 1. Numbered bracket entries: [1], [2], [10]
BRACKET_NUMBER_PATTERN = re.compile(r"^\s*(\[\d{1,4}\])\s*(.+)$", re.MULTILINE)

# 2. Dot-numbered entries: 1., 2., 10.
DOT_NUMBER_PATTERN = re.compile(r"^\s*(\d{1,4}\.)\s*(.+)$", re.MULTILINE)

# 3. Year pattern: (1998), (2020), 2021.
YEAR_PATTERN = re.compile(r"\b(19\d{2}|20[0-2]\d)\b")


def find_bibliography_text(raw_text: str, sections_dict: Optional[Dict[str, str]] = None) -> Tuple[str, bool]:
    """Locate the bibliography/references section from structured sections or raw text.

    Returns:
        (bib_text, found_flag)
    """
    # 1. First check structured sections dictionary if provided
    if sections_dict:
        for heading, content in sections_dict.items():
            h_clean = heading.strip().lower()
            h_clean = re.sub(r"^(?:(?:\d+(?:\.\d+)*|[ivx]+)\.?\s*)+", "", h_clean).strip()
            for pattern in BIBLIOGRAPHY_HEADINGS:
                if re.search(pattern, h_clean) and content.strip():
                    return content.strip(), True

    # 2. Fall back to scanning raw text for bibliography header
    lines = raw_text.split("\n")
    bib_start_idx = -1

    for idx, line in enumerate(lines):
        clean = line.strip().lower()
        clean = re.sub(r"^(?:(?:\d+(?:\.\d+)*|[ivx]+)\.?\s*)+", "", clean).strip()
        for pattern in BIBLIOGRAPHY_HEADINGS:
            if re.match(pattern, clean) and len(clean.split()) <= 4:
                bib_start_idx = idx
                break
        if bib_start_idx != -1:
            break

    if bib_start_idx != -1:
        bib_lines = lines[bib_start_idx + 1 :]
        # Check if another major section starts after references (e.g. Appendix, Acknowledgements)
        end_idx = len(bib_lines)
        for i, b_line in enumerate(bib_lines):
            b_clean = b_line.strip().lower()
            if re.match(r"^(?:\d+[\.\s]*)?(?:appendix|appendices|author\s+contributions)\b", b_clean) and len(b_clean.split()) <= 4:
                end_idx = i
                break
        bib_text = "\n".join(bib_lines[:end_idx]).strip()
        return bib_text, True

    return "", False


def segment_bibliography_entries(bib_text: str) -> List[Tuple[str, str]]:
    """Segment bibliography text into individual reference items.

    Returns list of (citation_key, raw_entry_text).
    """
    if not bib_text.strip():
        return []

    lines = [l.strip() for l in bib_text.split("\n") if l.strip()]
    if not lines:
        return []

    entries: List[Tuple[str, str]] = []

    # Check for [1] bracket numbered pattern
    bracket_matches = list(re.finditer(r"(?:^|\n)\s*(\[\d{1,4}\])\s*", bib_text))
    if len(bracket_matches) >= 2:
        for i, match in enumerate(bracket_matches):
            key = match.group(1).strip()
            start_pos = match.end()
            end_pos = bracket_matches[i + 1].start() if (i + 1 < len(bracket_matches)) else len(bib_text)
            entry_body = bib_text[start_pos:end_pos].strip()
            # Collapse internal newlines
            entry_body = re.sub(r"\s+", " ", entry_body)
            full_entry = f"{key} {entry_body}"
            entries.append((key, full_entry))
        return entries

    # Check for "1. ", "2. " numbered pattern
    dot_matches = list(re.finditer(r"(?:^|\n)\s*(\d{1,4})\.\s+", bib_text))
    if len(dot_matches) >= 2:
        for i, match in enumerate(dot_matches):
            num = match.group(1).strip()
            key = f"[{num}]"
            start_pos = match.end()
            end_pos = dot_matches[i + 1].start() if (i + 1 < len(dot_matches)) else len(bib_text)
            entry_body = bib_text[start_pos:end_pos].strip()
            entry_body = re.sub(r"\s+", " ", entry_body)
            full_entry = f"[{num}] {entry_body}"
            entries.append((key, full_entry))
        return entries

    # Author-year / unnumbered bibliography: split by double newlines or blank lines
    raw_paras = re.split(r"\n{2,}", bib_text)
    if len(raw_paras) >= 2:
        for i, para in enumerate(raw_paras):
            cleaned_entry = re.sub(r"\s+", " ", para).strip()
            if len(cleaned_entry) > 15:
                # Derive citation key if possible
                key = f"ref_{i + 1}"
                entries.append((key, cleaned_entry))
        return entries

    # Fallback: treat each line with substantial length as an entry
    for i, line in enumerate(lines):
        if len(line) > 25:
            key = f"[{i + 1}]"
            entries.append((key, line))

    return entries


def parse_reference_metadata(citation_key: str, raw_citation: str) -> ExtractedReferenceItem:
    """Extract granular bibliographic fields from a reference string.

    Never fabricates missing data (leaves null/None).
    """
    ref_id = str(uuid.uuid4())
    doi = extract_doi(raw_citation)
    arxiv_id = extract_arxiv_id(raw_citation)
    url = extract_url(raw_citation)

    # Clean citation text without leading key for metadata parsing
    clean_text = raw_citation
    if citation_key and raw_citation.startswith(citation_key):
        clean_text = raw_citation[len(citation_key) :].strip()

    # Extract year (e.g. (2017) or 2017.)
    year: Optional[int] = None
    year_match = re.search(r"\(?(19\d{2}|20[0-2]\d)\)?", clean_text)
    if year_match:
        try:
            year = int(year_match.group(1))
        except ValueError:
            year = None

    # Authors heuristic: text before year or first period/comma cluster
    authors: Optional[str] = None
    title: Optional[str] = None
    venue: Optional[str] = None

    if year_match and year_match.start() > 3:
        potential_authors = clean_text[: year_match.start()].strip().rstrip(".,")
        if len(potential_authors) > 2 and not any(k in potential_authors.lower() for k in ["http", "doi", "www"]):
            authors = potential_authors

        remaining = clean_text[year_match.end() :].strip().lstrip(".,): ")
        # Title is often between quotes or up to the next period
        quote_match = re.search(r'["\u201c]([^"\u201d]+)["\u201d]', remaining)
        if quote_match:
            title = quote_match.group(1).strip()
            post_title = remaining[quote_match.end() :].strip().lstrip("., ")
            if post_title:
                venue = post_title.split(".")[0].strip() or None
        else:
            parts = [p.strip() for p in remaining.split(".") if p.strip()]
            if parts:
                title = parts[0].strip()
                if len(parts) > 1:
                    venue = parts[1].strip()
    else:
        # Fallback segmentation by period
        parts = [p.strip() for p in clean_text.split(".") if p.strip()]
        if len(parts) >= 2:
            authors = parts[0]
            title = parts[1]
            if len(parts) >= 3:
                venue = parts[2]
        elif len(parts) == 1:
            title = parts[0]

    # Clean up authors/title if too short or obviously wrong
    if authors and len(authors) > 200:
        authors = authors[:200]
    if title and len(title) > 300:
        title = title[:300]

    return ExtractedReferenceItem(
        reference_id=ref_id,
        citation_key=citation_key,
        raw_citation=raw_citation,
        title=title,
        authors=authors,
        year=year,
        journal_or_venue=venue,
        doi=doi,
        arxiv_id=arxiv_id,
        url=url,
    )
