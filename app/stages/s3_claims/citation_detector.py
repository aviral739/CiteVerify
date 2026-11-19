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

# 4. Bracketed Author-Year: Wan et al. [2013], Hinton et al. [2011], (LeCun et al. [2004])
_BRACKET_AUTHOR_YEAR_RE = re.compile(
    r'\b([A-Z][a-zA-Z\.\-]+(?:\s+(?:et\s+al\.?|and\s+[A-Z][a-zA-Z\.\-]+|&\s+[A-Z][a-zA-Z\.\-]+))?)\s*\[((?:19\d\d|20[0-2]\d)[a-z]?)\]'
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

    # 1. Bracketed Author-Year citations: Wan et al. [2013], Hinton et al. [2011]
    for m in _BRACKET_AUTHOR_YEAR_RE.finditer(sentence):
        span = m.span()
        raw = m.group(0)
        author = m.group(1).strip()
        year_str = m.group(2).strip()
        norm_keys = [raw, f"{author} {year_str}", f"{author} [{year_str}]", f"({author}, {year_str})"]
        matches.append(CitationMatch(
            raw_match=raw,
            normalized_keys=norm_keys,
            start_pos=span[0],
            end_pos=span[1],
        ))
        occupied_spans.add(span)

    # 2. Numeric Bracketed citations: [1], [1, 2], [1-3]
    for m in _NUMERIC_BRACKET_RE.finditer(sentence):
        span = m.span()
        if any(s[0] <= span[0] and span[1] <= s[1] for s in occupied_spans):
            continue
        raw = m.group(0)
        norm_keys = expand_numeric_range(raw)
        matches.append(CitationMatch(
            raw_match=raw,
            normalized_keys=norm_keys,
            start_pos=span[0],
            end_pos=span[1],
        ))
        occupied_spans.add(span)

    # 3. Parenthetical Author-Year citations: (Smith, 2023), (Smith et al., 2023)
    for m in _AUTHOR_YEAR_PAREN_RE.finditer(sentence):
        span = m.span()
        if any(s[0] <= span[0] < s[1] for s in occupied_spans):
            continue
        raw = m.group(0)
        inner = raw.strip('()')
        norm_keys = [f"({item.strip()})" for item in inner.split(';') if item.strip()]
        matches.append(CitationMatch(
            raw_match=raw,
            normalized_keys=norm_keys,
            start_pos=span[0],
            end_pos=span[1],
        ))
        occupied_spans.add(span)

    # 4. Narrative Author-Year citations: Smith et al. (2023)
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
    ref_lookup: Dict[str, str] = {}
    for ref in available_references:
        ref_id = ref.get("id") or ref.get("reference_id") or ""
        key = ref.get("citation_key") or ""
        if key:
            ref_lookup[key.strip().lower()] = ref_id
            ref_lookup[key.strip().lower().replace("[", "").replace("]", "")] = ref_id
        # Also map bracketed number if key has number
        digits = re.findall(r'\d+', key)
        for d in digits:
            if not (1900 <= int(d) <= 2099):
                ref_lookup[f"[{d}]"] = ref_id

    primary_ref_id: Optional[str] = None
    all_ref_ids: List[str] = []

    for cit in citations:
        for k in cit.normalized_keys:
            clean_k = k.strip().lower()
            if clean_k in ref_lookup:
                matched_id = ref_lookup[clean_k]
                if not cit.resolved_ref_id:
                    cit.resolved_ref_id = matched_id
                if not primary_ref_id:
                    primary_ref_id = matched_id
                if matched_id not in all_ref_ids:
                    all_ref_ids.append(matched_id)

        # If not matched by exact key, try Author + Year matching
        if not cit.resolved_ref_id:
            # Extract year from citation
            y_m = re.search(r'\b(19\d\d|20[0-2]\d)\b', cit.raw_match)
            if y_m:
                cit_year = int(y_m.group(1))
                # Extract author surname
                auth_m = re.search(r'([A-Z][a-zA-Z\u00C0-\u024F\.\-]+)', cit.raw_match)
                if auth_m:
                    cit_surname = auth_m.group(1).rstrip(",.").lower()
                    for ref in available_references:
                        ref_year = ref.get("year")
                        ref_authors = (ref.get("authors") or "").lower()
                        ref_raw = (ref.get("raw_citation") or "").lower()
                        if ref_year == cit_year and (cit_surname in ref_authors or cit_surname in ref_raw):
                            matched_id = ref.get("id") or ref.get("reference_id")
                            cit.resolved_ref_id = matched_id
                            if not primary_ref_id:
                                primary_ref_id = matched_id
                            if matched_id not in all_ref_ids:
                                all_ref_ids.append(matched_id)
                            break

    return citations, primary_ref_id, all_ref_ids
