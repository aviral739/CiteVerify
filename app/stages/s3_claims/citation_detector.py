"""Citation pattern detection, normalization, and reference association."""

import re
from typing import Dict, List, Optional, Set, Tuple
from pydantic import BaseModel


class CitationMatch(BaseModel):
    raw_match: str               # e.g., "[1]", "[1, 2]", "(Smith et al., 2023)"
    normalized_keys: List[str]   # e.g., ["[1]"], ["[1]", "[2]"], ["(Smith et al., 2023)"]
    start_pos: int
    end_pos: int
    resolved_ref_id: Optional[str] = None


# Regex Patterns for Citation Detection

# 1. Bracketed Numeric: [1], [1, 2], [1-3], [1–4], [1,2,3]
_NUMERIC_BRACKET_RE = re.compile(r'\[(?:\s*\d+\s*(?:[–\-—]\s*\d+\s*)?,?)+\]')

# 2. Parenthetical Author-Year: (Smith, 2023), (Smith et al., 2023), (Smith and Jones, 2022; Lee, 2021)
_AUTHOR_YEAR_PAREN_RE = re.compile(
    r'\(([A-Z][a-zA-Z\.\-]+(?:\s+(?:et\s+al\.?|and\s+[A-Z][a-zA-Z\.\-]+|&\s+[A-Z][a-zA-Z\.\-]+))?,\s*\b(19\d\d|20\d\d)[a-z]?)(?:;\s*([A-Z][a-zA-Z\.\-]+(?:\s+(?:et\s+al\.?|and\s+[A-Z][a-zA-Z\.\-]+|&\s+[A-Z][a-zA-Z\.\-]+))?,\s*\b(19\d\d|20\d\d)[a-z]?))*\)'
)

# 3. Narrative Author-Year: Smith et al. (2023), Vaswani et al. [1]
_NARRATIVE_AUTHOR_YEAR_RE = re.compile(
    r'\b([A-Z][a-zA-Z\.\-]+(?:\s+et\s+al\.?)?)\s*\((19\d\d|20\d\d)[a-z]?\)'
)


def expand_numeric_range(token: str) -> List[str]:
    """Expand numeric citation range like '1-4' or '1–3' into ['[1]', '[2]', '[3]', '[4]']."""
    clean = token.strip().replace('[', '').replace(']', '')
    keys = []
    for part in re.split(r'[,;]\s*', clean):
        part = part.strip()
        if not part:
            continue
        range_match = re.match(r'^(\d+)\s*[–\-—]\s*(\d+)$', part)
        if range_match:
            start, end = int(range_match.group(1)), int(range_match.group(2))
            if start <= end and (end - start) < 50:  # reasonable range bounds
                for n in range(start, end + 1):
                    keys.append(f"[{n}]")
            else:
                keys.append(f"[{part}]")
        elif part.isdigit():
            keys.append(f"[{part}]")
        else:
            keys.append(f"[{part}]")
    return keys


def detect_citations(sentence: str) -> List[CitationMatch]:
    """Detect numeric, parenthetical, and narrative citations within a sentence."""
    matches: List[CitationMatch] = []
    occupied_spans: Set[Tuple[int, int]] = set()

    # 1. Numeric Bracketed citations
    for m in _NUMERIC_BRACKET_RE.finditer(sentence):
        span = m.span()
        raw = m.group(0)
        norm_keys = expand_numeric_range(raw)
        matches.append(CitationMatch(
            raw_match=raw,
            normalized_keys=norm_keys,
            start_pos=span[0],
            end_pos=span[1],
        ))
        occupied_spans.add(span)

    # 2. Parenthetical Author-Year citations
    for m in _AUTHOR_YEAR_PAREN_RE.finditer(sentence):
        span = m.span()
        if any(s[0] <= span[0] < s[1] for s in occupied_spans):
            continue
        raw = m.group(0)
        # Split multiple citations in semicolon (e.g. "(Smith, 2020; Lee, 2021)")
        inner = raw.strip('()')
        norm_keys = [f"({item.strip()})" for item in inner.split(';') if item.strip()]
        matches.append(CitationMatch(
            raw_match=raw,
            normalized_keys=norm_keys,
            start_pos=span[0],
            end_pos=span[1],
        ))
        occupied_spans.add(span)

    # 3. Narrative Author-Year citations
    for m in _NARRATIVE_AUTHOR_YEAR_RE.finditer(sentence):
        span = m.span()
        if any(s[0] <= span[0] < s[1] for s in occupied_spans):
            continue
        raw = m.group(0)
        matches.append(CitationMatch(
            raw_match=raw,
            normalized_keys=[raw],
            start_pos=span[0],
            end_pos=span[1],
        ))
        occupied_spans.add(span)

    # Sort matches by position in text
    matches.sort(key=lambda x: x.start_pos)
    return matches


def associate_references(
    citations: List[CitationMatch],
    available_references: Optional[List[dict]] = None
) -> Tuple[List[CitationMatch], Optional[str], List[str]]:
    """Associate detected citation markers with reference IDs from S2 reference extraction.

    Returns:
        (updated_citations, primary_reference_id, all_reference_ids)
    """
    if not available_references:
        return citations, None, []

    # Build reference lookup maps
    # map by citation_key (e.g. "[1]", "(Smith, 2020)") and by author/number
    ref_lookup: Dict[str, str] = {}
    for ref in available_references:
        ref_id = ref.get("id") or ref.get("reference_id") or ""
        key = ref.get("citation_key") or ""
        raw = ref.get("raw_citation") or ""

        if key:
            ref_lookup[key.strip().lower()] = ref_id
        # Also map bracketed number if key has number
        digits = re.findall(r'\d+', key)
        for d in digits:
            ref_lookup[f"[{d}]"] = ref_id

    primary_ref_id: Optional[str] = None
    all_ref_ids: List[str] = []

    for cit in citations:
        for k in cit.normalized_keys:
            clean_k = k.strip().lower()
            if clean_k in ref_lookup:
                matched_id = ref_lookup[clean_k]
                cit.resolved_ref_id = matched_id
                if not primary_ref_id:
                    primary_ref_id = matched_id
                if matched_id not in all_ref_ids:
                    all_ref_ids.append(matched_id)

    return citations, primary_ref_id, all_ref_ids
