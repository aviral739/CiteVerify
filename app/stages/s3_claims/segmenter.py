"""Sentence segmentation utilities for scientific academic literature."""

import re
from typing import List, Tuple

# Common academic, scientific, and Latin abbreviations that should not trigger sentence splits
ACADEMIC_ABBREVIATIONS = {
    "e.g.", "i.e.", "et al.", "etc.", "vs.", "cf.", "al.", "approx.",
    "fig.", "figs.", "ref.", "refs.", "sec.", "secs.", "eq.", "eqs.",
    "no.", "vol.", "pp.", "p.", "ed.", "eds.", "ch.", "app.",
    "dr.", "prof.", "mr.", "ms.", "mrs.", "jr.", "sr.",
    "dept.", "univ.", "int.", "conf.", "proc.", "trans.",
    "ca.", "viz.", "ibid.", "id.", "op. cit.", "loc. cit.",
}

# Regex for sentence boundaries: period, question mark, or exclamation point followed by whitespace and capital letter
_SENTENCE_BOUNDARY_RE = re.compile(r'([.?!])\s+(?=[A-Z0-9"\'\(\[])')

# Regex for detecting decimal numbers or abbreviations before a dot
_DECIMAL_OR_INITIAL_RE = re.compile(r'\b[A-Za-z0-9]\.\s*$|\b\d+\.\s*$')


def segment_sentences(text: str) -> List[str]:
    """Segment scientific text into coherent sentences without breaking abbreviations or decimals."""
    if not text or not text.strip():
        return []

    # Normalize whitespace while preserving paragraphs
    normalized = re.sub(r'[\r\n]+', ' ', text).strip()
    normalized = re.sub(r'[ \t]+', ' ', normalized)

    # Initial split candidate tokens
    raw_splits = _SENTENCE_BOUNDARY_RE.split(normalized)
    if len(raw_splits) <= 1:
        return [normalized] if normalized else []

    sentences: List[str] = []
    current_chunk = ""

    i = 0
    while i < len(raw_splits):
        part = raw_splits[i]
        # raw_splits alternates: text, punct, text, punct...
        if i + 1 < len(raw_splits):
            punct = raw_splits[i + 1]
            candidate = (current_chunk + part + punct).strip()

            # Check if candidate ends with an abbreviation
            words = candidate.split()
            last_token = words[-1].lower() if words else ""

            # Check if last token is an abbreviation (e.g., 'et al.' or 'fig.')
            is_abbrev = False
            for abbrev in ACADEMIC_ABBREVIATIONS:
                if last_token.endswith(abbrev) or candidate.lower().endswith(" " + abbrev):
                    is_abbrev = True
                    break

            # Check if it's a single letter initial (e.g., 'J. Smith')
            if _DECIMAL_OR_INITIAL_RE.search(part + punct):
                is_abbrev = True

            if is_abbrev:
                # Do not split here; merge with next sentence part
                current_chunk = candidate + " "
            else:
                sentences.append(candidate)
                current_chunk = ""
            i += 2
        else:
            final_part = (current_chunk + part).strip()
            if final_part:
                sentences.append(final_part)
            i += 1

    return [s for s in sentences if s.strip()]


def segment_section_sentences(sections: dict) -> List[Tuple[str, str, int]]:
    """Segment dictionary of sections into (section_name, sentence_text, sentence_index) tuples."""
    results: List[Tuple[str, str, int]] = []
    sent_idx = 0
    for sec_name, sec_text in sections.items():
        if not isinstance(sec_text, str):
            continue
        sents = segment_sentences(sec_text)
        for s in sents:
            results.append((sec_name, s, sent_idx))
            sent_idx += 1
    return results
