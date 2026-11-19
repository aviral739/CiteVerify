"""Quote guard verification engine for academic claim provenance.

Verifies whether supporting quotations cited or extracted from claims exist verbatim
or near-verbatim in retrieved source passages.
Rejects generic, stop-word-heavy trivial sequences (such as "in case of", "as well as")
while preserving meaningful domain-specific textual evidence.
"""

import re
import unicodedata
from typing import Any, List, Optional, Set, Tuple
from pydantic import BaseModel, Field


# Comprehensive academic stopword set
STANDARD_STOPWORDS: Set[str] = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are",
    "as", "at", "be", "because", "been", "before", "being", "below", "between", "both", "but",
    "by", "can", "could", "did", "do", "does", "doing", "down", "during", "each", "few", "for",
    "from", "further", "had", "has", "have", "having", "he", "her", "here", "hers", "herself",
    "him", "himself", "his", "how", "i", "if", "in", "into", "is", "it", "its", "itself", "just",
    "me", "more", "most", "my", "myself", "no", "nor", "not", "now", "of", "off", "on", "once",
    "only", "or", "other", "our", "ours", "ourselves", "out", "over", "own", "same", "she",
    "should", "so", "some", "such", "than", "that", "the", "their", "theirs", "them", "themselves",
    "then", "there", "these", "they", "this", "those", "through", "to", "too", "under", "until",
    "up", "very", "was", "we", "were", "what", "when", "where", "which", "while", "who", "whom",
    "why", "with", "would", "you", "your", "yours", "yourself", "yourselves",
    # Academic/connective fillers that cause false quote positives
    "case", "terms", "respect", "order", "addition", "regard", "view", "well", "particular",
}


class QuoteGuardResult(BaseModel):
    """Result of quote guard inspection."""

    is_verified: bool = False
    matched_quote: Optional[str] = None
    matched_passage_id: Optional[str] = None
    rejection_reason: Optional[str] = None


def normalize_quote_text(text: str) -> str:
    """Normalize Unicode, whitespace, and punctuation for robust text matching."""
    if not text:
        return ""
    # 1. NFKC decomposes compatibility glyphs (ligatures, curly quotes, en-dashes)
    text = unicodedata.normalize("NFKC", text)
    # 2. Standardize quotation marks and hyphens
    text = re.sub(r"[\u2018\u2019\u201A\u201B`]", "'", text)
    text = re.sub(r"[\u201C\u201D\u201E\u201F«»]", '"', text)
    text = re.sub(r"[\u2013\u2014\u2212]", "-", text)
    # 3. Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def extract_content_words(text: str) -> List[str]:
    """Extract alphabetic words excluding common stopwords."""
    words = re.findall(r"\b[a-zA-Z]{2,}\b", text.lower())
    return [w for w in words if w not in STANDARD_STOPWORDS]


def is_distinctive_quotation(quote: str, min_chars: int = 20, min_content_words: int = 3) -> Tuple[bool, Optional[str]]:
    """Determine whether a candidate quotation is distinctive enough to serve as evidence."""
    norm = normalize_quote_text(quote)
    if len(norm) < min_chars:
        return False, f"Quote is too short ({len(norm)} chars < minimum {min_chars})"

    all_words = re.findall(r"\b[a-zA-Z0-9_-]+\b", norm)
    if len(all_words) < 4:
        return False, f"Quote has too few words ({len(all_words)} words < minimum 4)"

    content_words = extract_content_words(norm)
    if len(content_words) < min_content_words:
        return (
            False,
            f"Quote lacks distinctive terminology ({len(content_words)} content words < minimum {min_content_words})",
        )

    # Ratio of content words to total words must be at least 35%
    content_ratio = len(content_words) / max(len(all_words), 1)
    if content_ratio < 0.35:
        return (
            False,
            f"Quote is predominantly generic stopwords (content ratio {content_ratio:.2f} < 0.35)",
        )

    return True, None


def verify_quotation(
    candidate_quote: Optional[str],
    evidence_passages: List[Any],
    claim_text: Optional[str] = None,
) -> QuoteGuardResult:
    """Validate that a candidate quotation exists verbatim or near-verbatim in evidence.

    Args:
        candidate_quote: Explicit quotation string to check (e.g. from LLM or manuscript).
        evidence_passages: List of EvidencePassage objects or dicts with 'evidence_text' & 'evidence_id'.
        claim_text: Optional claim text to extract explicit quoted spans from if candidate_quote is empty.

    Returns:
        QuoteGuardResult with verification status, matched quote, and passage ID.
    """
    candidates_to_test: List[str] = []

    if candidate_quote and candidate_quote.strip():
        candidates_to_test.append(candidate_quote.strip())

    # Also check if the claim itself contains explicit quotation marks: "..." or '...'
    if claim_text:
        quoted_spans = re.findall(r'["\u201C\u201D]([^"\u201C\u201D]{15,})["\u201C\u201D]', claim_text)
        for span in quoted_spans:
            if span not in candidates_to_test:
                candidates_to_test.append(span.strip())

        # If no explicit quotes, extract substantive distinctive contiguous phrases from claim
        # that appear verbatim in any of the evidence passages
        if not candidates_to_test:
            passage_texts = [
                normalize_quote_text(
                    getattr(p, "evidence_text", None)
                    or getattr(p, "text", None)
                    or (p.get("evidence_text") if isinstance(p, dict) else "")
                    or ""
                )
                for p in evidence_passages
            ]
            c_words = claim_text.split()
            found = False
            for w in range(len(c_words), 3, -1):
                for i in range(len(c_words) - w + 1):
                    phrase = " ".join(c_words[i : i + w]).strip(" ,;.!?:'\"()[]{}")
                    if len(phrase) >= 20:
                        norm_p = normalize_quote_text(phrase)
                        if any(norm_p in pt for pt in passage_texts):
                            is_dist, _ = is_distinctive_quotation(phrase)
                            if is_dist:
                                candidates_to_test.append(phrase)
                                found = True
                                break
                if found:
                    break

    if not candidates_to_test:
        return QuoteGuardResult(
            is_verified=False,
            rejection_reason="No explicit candidate quotation provided or extracted.",
        )

    last_rejection = "No candidate quote passed verification."

    for candidate in candidates_to_test:
        is_distinct, reject_reason = is_distinctive_quotation(candidate)
        if not is_distinct:
            last_rejection = reject_reason
            continue

        norm_candidate = normalize_quote_text(candidate)
        candidate_words = norm_candidate.split()
        # Create relaxed punctuation pattern for matching
        # e.g., words separated by any whitespace or standard punctuation
        escaped_words = [re.escape(w) for w in candidate_words]
        regex_pattern = r"\b" + r"[\s\.,;:'\"—\(\)\[\]\-/]+" .join(escaped_words) + r"\b"
        compiled_regex = re.compile(regex_pattern, re.IGNORECASE)

        for p in evidence_passages:
            p_text = (
                getattr(p, "evidence_text", None)
                or getattr(p, "text", None)
                or (p.get("evidence_text") if isinstance(p, dict) else "")
                or ""
            )
            p_id = (
                getattr(p, "evidence_id", None)
                or getattr(p, "id", None)
                or (p.get("evidence_id") if isinstance(p, dict) else "")
            )

            if not p_text:
                continue

            norm_p_text = normalize_quote_text(p_text)

            # 1. Exact normalized substring match
            if norm_candidate in norm_p_text:
                return QuoteGuardResult(
                    is_verified=True,
                    matched_quote=candidate,
                    matched_passage_id=p_id,
                )

            # 2. Relaxed punctuation regex match
            if compiled_regex.search(norm_p_text):
                return QuoteGuardResult(
                    is_verified=True,
                    matched_quote=candidate,
                    matched_passage_id=p_id,
                )

        last_rejection = f"Distinctive quotation '{candidate[:50]}...' could not be located in retrieved source passages."

    return QuoteGuardResult(
        is_verified=False,
        rejection_reason=last_rejection,
    )


class QuoteGuard:
    """Helper class providing quote guard validation methods."""

    @staticmethod
    def is_distinctive(quote: str, min_chars: int = 20, min_content_words: int = 3) -> Tuple[bool, Optional[str]]:
        return is_distinctive_quotation(quote, min_chars=min_chars, min_content_words=min_content_words)

    @staticmethod
    def normalize(text: str) -> str:
        return normalize_quote_text(text)

    @staticmethod
    def verify(quote: str, passage: Any) -> Tuple[bool, Optional[str]]:
        passages = [{"evidence_text": passage}] if isinstance(passage, str) else passage
        res = verify_quotation(candidate_quote=quote, evidence_passages=passages)
        return res.is_verified, res.matched_quote


# Compatibility aliases
normalize_text_for_matching = normalize_quote_text
is_distinctive_quote = is_distinctive_quotation

