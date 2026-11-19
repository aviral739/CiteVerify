"""In-text citation marker detector and associator."""

import re
from typing import Dict, List, Optional, Tuple
from app.stages.s2_references.models import (
    CitationStyleEnum,
    ExtractedReferenceItem,
    InTextCitationMarker,
)

# Numeric citation patterns: e.g. [1], [1, 2], [1-3], [1–4]
NUMERIC_CITATION_PATTERN = re.compile(
    r"\[(\d{1,4}(?:\s*[,-–]\s*\d{1,4})*)\]"
)

# Author-year patterns:
# (Smith, 2020), (Smith et al., 2020), (Smith and Jones, 2021)
PAREN_AUTHOR_YEAR = re.compile(
    r"\(([A-Z][a-zA-Z\s\.,&]+?(?:et\s+al\.?)?),?\s+((?:19\d{2}|20[0-2]\d)[a-z]?)\)"
)

# Narrative author-year: Smith et al. (2020), Vaswani et al. (2017)
NARRATIVE_AUTHOR_YEAR = re.compile(
    r"\b([A-Z][a-zA-Z]+(?:\s+et\s+al\.?)?)\s+\(((?:19\d{2}|20[0-2]\d)[a-z]?)\)"
)

# Bracket author-year: Wan et al. [2013], Hinton et al. [2011], Kingma and Ba [2014]
BRACKET_AUTHOR_YEAR = re.compile(
    r"\b([A-Z][a-zA-Z\.\-]+(?:\s+(?:et\s+al\.?|and\s+[A-Z][a-zA-Z\.\-]+|&\s+[A-Z][a-zA-Z\.\-]+))?)\s*\[((?:19\d{2}|20[0-2]\d)[a-z]?)\]"
)


def expand_numeric_range(group_text: str) -> List[str]:
    """Expand numeric citation range string like '1-3, 5' into individual keys: ['1', '2', '3', '5']."""
    keys = []
    parts = [p.strip() for p in group_text.split(",") if p.strip()]
    for part in parts:
        range_match = re.match(r"^(\d{1,4})\s*[-–]\s*(\d{1,4})$", part)
        if range_match:
            start_num = int(range_match.group(1))
            end_num = int(range_match.group(2))
            if 0 < (end_num - start_num) <= 50:
                for n in range(start_num, end_num + 1):
                    keys.append(str(n))
            else:
                keys.append(part)
        elif part.isdigit():
            keys.append(part)
        else:
            keys.append(part)
    return keys


def extract_in_text_citations(text: str) -> List[InTextCitationMarker]:
    """Scan manuscript text and extract all in-text citation markers."""
    citations: List[InTextCitationMarker] = []
    occupied_spans = set()

    # 1. Bracket author-year: Wan et al. [2013]
    for match in BRACKET_AUTHOR_YEAR.finditer(text):
        span = match.span()
        raw = match.group(0)
        author = match.group(1).strip()
        year_str = match.group(2).strip()
        year = int(re.sub(r"[a-z]", "", year_str)) if re.sub(r"[a-z]", "", year_str).isdigit() else None
        if any(w in author.lower() for w in ["fig", "table", "eq", "section"]):
            continue
        citation = InTextCitationMarker(
            raw_citation=raw,
            style=CitationStyleEnum.AUTHOR_YEAR,
            keys=[raw, f"{author} {year_str}", f"{author} [{year_str}]"],
            author=author,
            year=year,
        )
        citations.append(citation)
        occupied_spans.add(span)

    # 2. Parenthetical author-year: (Smith et al., 2020)
    for match in PAREN_AUTHOR_YEAR.finditer(text):
        span = match.span()
        if any(s[0] <= span[0] < s[1] for s in occupied_spans):
            continue
        raw = match.group(0)
        author = match.group(1).strip()
        year_str = match.group(2).strip()
        year = int(re.sub(r"[a-z]", "", year_str)) if re.sub(r"[a-z]", "", year_str).isdigit() else None

        # Filter out common false positives like (Figure 1, 2020) or (Table 2)
        if any(w in author.lower() for w in ["fig", "table", "eq", "section", "page", "ch."]):
            continue

        citation = InTextCitationMarker(
            raw_citation=raw,
            style=CitationStyleEnum.AUTHOR_YEAR,
            keys=[f"{author} {year_str}"],
            author=author,
            year=year,
        )
        citations.append(citation)
        occupied_spans.add(span)

    # 3. Narrative author-year: Smith et al. (2020)
    for match in NARRATIVE_AUTHOR_YEAR.finditer(text):
        span = match.span()
        if any(s[0] <= span[0] < s[1] for s in occupied_spans):
            continue
        raw = match.group(0)
        author = match.group(1).strip()
        year_str = match.group(2).strip()
        year = int(re.sub(r"[a-z]", "", year_str)) if re.sub(r"[a-z]", "", year_str).isdigit() else None

        if any(w in author.lower() for w in ["fig", "table", "eq", "section"]):
            continue

        citation = InTextCitationMarker(
            raw_citation=raw,
            style=CitationStyleEnum.AUTHOR_YEAR,
            keys=[f"{author} {year_str}"],
            author=author,
            year=year,
        )
        citations.append(citation)
        occupied_spans.add(span)

    # 4. Numeric bracket citations [1], [1, 2], [1-4] (ignoring occupied spans)
    for match in NUMERIC_CITATION_PATTERN.finditer(text):
        span = match.span()
        if any(s[0] <= span[0] < s[1] for s in occupied_spans):
            continue
        raw = match.group(0)
        inner = match.group(1)
        expanded_nums = expand_numeric_range(inner)
        citation = InTextCitationMarker(
            raw_citation=raw,
            style=CitationStyleEnum.NUMERIC,
            keys=[f"[{num}]" for num in expanded_nums],
            sentence=None,
        )
        citations.append(citation)

    return citations


def associate_citations_with_references(
    citations: List[InTextCitationMarker],
    references: List[ExtractedReferenceItem],
) -> Tuple[List[InTextCitationMarker], List[ExtractedReferenceItem]]:
    """Associate in-text citation markers with corresponding bibliography entries.

    Never guesses when ambiguous.
    """
    # Build lookup by bracket key, e.g. '[1]'
    key_to_ref: Dict[str, ExtractedReferenceItem] = {}
    for ref in references:
        key_to_ref[ref.citation_key.strip()] = ref
        # Also map without brackets if numeric
        bare = ref.citation_key.strip("[]")
        if bare:
            key_to_ref[bare] = ref

    for citation in citations:
        if citation.style == CitationStyleEnum.NUMERIC:
            # Check if primary key matches
            for k in citation.keys:
                if k in key_to_ref:
                    matched_ref = key_to_ref[k]
                    citation.resolved_reference_id = matched_ref.reference_id
                    citation.is_associated = True
                    matched_ref.in_text_mention_count += 1
                    matched_ref.is_cited_in_text = True
                    break

        elif citation.style == CitationStyleEnum.AUTHOR_YEAR:
            if not citation.author or not citation.year:
                continue

            # Clean primary author name (e.g. "Vaswani et al." -> "Vaswani")
            primary_author = citation.author.split()[0].replace(",", "").lower()

            matching_refs = []
            for ref in references:
                ref_text_lower = ref.raw_citation.lower()
                authors_lower = (ref.authors or "").lower()

                # Author matches and year matches
                if (primary_author in authors_lower or primary_author in ref_text_lower) and (
                    ref.year == citation.year
                ):
                    matching_refs.append(ref)

            # Only associate if uniquely resolved
            if len(matching_refs) == 1:
                matched_ref = matching_refs[0]
                citation.resolved_reference_id = matched_ref.reference_id
                citation.is_associated = True
                matched_ref.in_text_mention_count += 1
                matched_ref.is_cited_in_text = True
            elif len(matching_refs) > 1:
                # Ambiguous match, do not guess
                citation.is_associated = False

    return citations, references
