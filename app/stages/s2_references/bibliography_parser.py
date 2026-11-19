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

    # Check for [1] bracket numbered pattern (excluding 4-digit years like [2018])
    bracket_matches = list(re.finditer(r"(?:^|\n)\s*(\[\d{1,4}\])\s*", bib_text))
    valid_bracket_matches = [
        m for m in bracket_matches
        if not (1900 <= int(m.group(1).strip("[]")) <= 2099)
    ]
    if len(valid_bracket_matches) >= 2:
        for i, match in enumerate(valid_bracket_matches):
            key = match.group(1).strip()
            start_pos = match.end()
            end_pos = valid_bracket_matches[i + 1].start() if (i + 1 < len(valid_bracket_matches)) else len(bib_text)
            entry_body = bib_text[start_pos:end_pos].strip()
            # Collapse internal newlines
            entry_body = re.sub(r"\s+", " ", entry_body)
            full_entry = f"{key} {entry_body}"
            entries.append((key, full_entry))
        return entries

    # Check for "1. ", "2. " numbered pattern (excluding 4-digit years like 2018.)
    dot_matches = list(re.finditer(r"(?:^|\n)\s*(\d{1,4})\.\s+", bib_text))
    valid_dot_matches = [
        m for m in dot_matches
        if not (1900 <= int(m.group(1).strip()) <= 2099)
    ]
    if len(valid_dot_matches) >= 2:
        for i, match in enumerate(valid_dot_matches):
            num = match.group(1).strip()
            key = f"[{num}]"
            start_pos = match.end()
            end_pos = valid_dot_matches[i + 1].start() if (i + 1 < len(valid_dot_matches)) else len(bib_text)
            entry_body = bib_text[start_pos:end_pos].strip()
            entry_body = re.sub(r"\s+", " ", entry_body)
            full_entry = f"[{num}] {entry_body}"
            entries.append((key, full_entry))
        return entries

    # Author-year / unnumbered bibliography:
    # Check if split by double newlines produces good individual entries (average length <= 600 chars)
    raw_paras = re.split(r"\n{2,}", bib_text)
    if len(raw_paras) >= 3 and (len(bib_text) / len(raw_paras) <= 600):
        for i, para in enumerate(raw_paras):
            cleaned_entry = re.sub(r"\s+", " ", para).strip()
            if len(cleaned_entry) > 15:
                key = f"ref_{i + 1}"
                entries.append((key, cleaned_entry))
        return entries

    # Line-by-line author-year segmentation
    ay_entries: List[str] = []
    curr_lines: List[str] = []
    for idx, line in enumerate(lines):
        is_new_entry = False
        if curr_lines:
            prev_text = " ".join(curr_lines).strip()
            prev_has_year = bool(re.search(r"\b(19\d\d|20[0-2]\d)[a-z]?\b", prev_text))
            prev_terminal = prev_text.endswith((".", ")", '"', "'", "”")) or bool(re.search(r"\b(19\d\d|20[0-2]\d)[a-z]?\.?$", prev_text))
            is_year_start = bool(re.match(r"^(?:19\d\d|20[0-2]\d)[a-z]?\.\s*", line))
            author_start = bool(re.match(r"^[A-Z\u00C0-\u024F][a-zA-Z\u00C0-\u024F\.\-]+", line))
            is_lower_or_digit = line[0].islower() or line[0].isdigit()
            is_keyword = bool(re.match(r"^(?:in\s+|pages?\s+|arxiv\b|http|doi|vol\b|volume\b|no\.\s*|and\s+|et\s+al\b|proceedings\b|journal\b|conference\b)", line, re.IGNORECASE))
            not_continuation = not (is_lower_or_digit or is_keyword)

            has_future_year = bool(re.search(r"\b(19\d\d|20[0-2]\d)[a-z]?\b", " ".join(lines[idx:min(len(lines), idx + 5)])))

            if prev_has_year and prev_terminal and author_start and has_future_year and not is_year_start and not_continuation and len(prev_text) > 35:
                is_new_entry = True
        else:
            if re.match(r"^[A-Z\u00C0-\u024F]", line):
                is_new_entry = True

        if is_new_entry and curr_lines:
            ay_entries.append(" ".join(curr_lines).strip())
            curr_lines = [line]
        else:
            curr_lines.append(line)

    if curr_lines:
        ay_entries.append(" ".join(curr_lines).strip())

    if len(ay_entries) >= 2:
        for i, e in enumerate(ay_entries):
            key = f"ref_{i + 1}"
            entries.append((key, e))
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
    if not doi and arxiv_id:
        doi = f"10.48550/arxiv.{arxiv_id}"
    url = extract_url(raw_citation)

    # Clean citation text without leading key for metadata parsing
    clean_text = raw_citation
    if citation_key and raw_citation.startswith(citation_key):
        clean_text = raw_citation[len(citation_key) :].strip()

    # Extract year (e.g. (2017) or 2017.)
    year: Optional[int] = None
    y_match = re.search(r"\b(19\d{2}|20[0-2]\d)\b", clean_text)
    if y_match:
        try:
            year = int(y_match.group(1))
        except ValueError:
            year = None

    authors: Optional[str] = None
    title: Optional[str] = None
    venue: Optional[str] = None

    # Check for quoted title
    quote_match = re.search(r'["\u201c]([^"\u201d]+)["\u201d]', clean_text)
    if quote_match:
        title = quote_match.group(1).strip()
        before_quote = clean_text[: quote_match.start()].strip().rstrip(".,(")
        after_quote = clean_text[quote_match.end() :].strip().lstrip("., ")
        authors = before_quote or None
        venue = after_quote or None
    else:
        # Check for Author-Year style: Author (Year). Title. Venue
        paren_year_match = re.search(r"\((19\d{2}|20[0-2]\d)\)", clean_text)
        if (
            paren_year_match
            and paren_year_match.start() < 120
            and clean_text[: paren_year_match.start()].count(".") <= 2
        ):
            potential_authors = clean_text[: paren_year_match.start()].strip().rstrip(".,")
            if len(potential_authors) > 2 and not any(k in potential_authors.lower() for k in ["http", "doi", "www"]):
                authors = potential_authors
            remaining = clean_text[paren_year_match.end() :].strip().lstrip(".,: ")
            parts = [p.strip() for p in re.split(r"(?<!\b[A-Z])\.\s+", remaining) if p.strip()]
            if parts:
                title = parts[0]
                if len(parts) > 1:
                    venue = ". ".join(parts[1:]).strip() or None
        else:
            # Period-delimited academic style: Authors. Title. Venue, Year.
            # Avoid splitting on single-letter middle initials like "V." or "E." or "N."
            parts = [p.strip() for p in re.split(r"(?<!\b[A-Z])\.\s+", clean_text) if p.strip()]
            if len(parts) >= 3 and re.match(r"^(?:19\d\d|20[0-2]\d)[a-z]?$", parts[1]):
                authors = parts[0]
                title = parts[2]
                if len(parts) > 3:
                    venue = ". ".join(parts[3:]).strip() or None
            elif len(parts) >= 2:
                authors = parts[0]
                title = parts[1]
                if len(parts) > 2:
                    venue = ". ".join(parts[2:]).strip() or None
            elif len(parts) == 1:
                title = parts[0]

    # Clean up authors/title if too long
    if authors and len(authors) > 250:
        authors = authors[:250].strip()
    if title and len(title) > 300:
        title = title[:300].strip()

    # For author-year references with artificial keys (ref_X), generate an author-year citation key
    if (citation_key.startswith("ref_") or not citation_key) and authors and year:
        first_author = authors.split(",")[0].split(" and ")[0].split(" & ")[0].strip()
        tokens = first_author.split()
        surname = tokens[-1].rstrip(".,") if len(tokens) > 1 else first_author.rstrip(".,")
        is_multi = len(authors.split()) > 2 or "et al" in authors.lower() or "and" in authors.lower() or "&" in authors
        citation_key = f"{surname} et al. [{year}]" if is_multi else f"{surname} [{year}]"

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
