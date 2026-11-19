"""Text normalization utilities for academic manuscripts.

Carefully normalizes whitespace and line breaks while preserving:
- Scientific notation (e.g., 1.5e-4, 3.2 x 10^8)
- Decimal numbers and percentages (e.g., 99.4%, 0.001)
- Citation callouts (e.g., [1], [1, 2], [1-3], (Smith, 2020))
- Units and mathematical operators (e.g., kg/m^3, p < 0.05, +/-)
- Meaningful punctuation
"""

import re
import unicodedata


def normalize_academic_text(text: str) -> str:
    """Normalize text extracted from academic documents without destroying domain syntax."""
    if not text:
        return ""

    # 1. Unicode normalization (NFKC decomposes compatibility chars while preserving readable text)
    # However, preserve standard quotes and hyphens specifically
    text = unicodedata.normalize("NFKC", text)

    # 2. Standardize carriage returns and line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # 3. Replace non-breaking spaces and unusual whitespace with standard space
    text = re.sub(r"[\u00A0\u1680\u2000-\u200A\u202F\u205F\u3000]", " ", text)

    # 4. Standardize dashes and hyphens used in words and citations (e.g. en-dash to hyphen for ranges)
    # Keep standard hyphen-minus '-' for ranges like [1-4] or words like well-known
    text = text.replace("–", "-").replace("—", " - ")

    # 5. Fix hyphenated line breaks in words (e.g., "experi-\nment" -> "experiment")
    # Only de-hyphenate if hyphen is between lowercase letters: [a-z]-\n[a-z]
    text = re.sub(r"([a-zA-Z])-\n([a-zA-Z])", r"\1\2", text)

    # 5b. Ensure recognized academic headings have double newlines around them
    heading_pattern = re.compile(
        r"^(?:(?:\d+(?:\.\d+)*|[IVX]+)\.?\s*)?(?:abstract|introduction|related\s+work|background|methodology|methods|model\s+architecture|experiments|results|discussion|conclusions?|references|acknowledgements?)\b",
        re.IGNORECASE,
    )
    raw_lines = text.split("\n")
    spaced_lines = []
    for l in raw_lines:
        s = l.strip()
        is_heading = (
            s
            and len(s) < 80
            and (
                heading_pattern.match(s)
                or re.match(r"^(?:(?:\d+(?:\.\d+)*|[IVX]+)\.?\s+[A-Za-z]|#{1,4}\s+|\[\d+\])", s)
            )
        )
        if is_heading:
            spaced_lines.append("")
            spaced_lines.append(s)
            spaced_lines.append("")
        else:
            spaced_lines.append(l)
    text = "\n".join(spaced_lines)

    # 6. Join broken lines within paragraphs while preserving paragraph breaks (double newlines)
    # Split into paragraphs by 2 or more newlines
    paragraphs = re.split(r"\n{2,}", text)
    cleaned_paragraphs = []

    for para in paragraphs:
        # Inside a paragraph, convert single newlines into spaces unless the line looks like a heading, list item, or formula
        raw_lines = [line.strip() for line in para.split("\n") if line.strip()]
        if not raw_lines:
            continue

        # Preserve lines if any line in this paragraph looks like a section heading or reference item
        has_structural_line = any(
            heading_pattern.match(l)
            or re.match(r"^(?:(?:\d+(?:\.\d+)*|[IVX]+)\.?\s+[A-Za-z]|#{1,4}\s+|\[\d+\])", l)
            for l in raw_lines
        )
        if has_structural_line:
            cleaned_paragraphs.append("\n".join(re.sub(r"[ \t]+", " ", l) for l in raw_lines))
        else:
            cleaned_para = " ".join(raw_lines)
            cleaned_para = re.sub(r"[ \t]+", " ", cleaned_para)
            cleaned_paragraphs.append(cleaned_para)

    return "\n\n".join(cleaned_paragraphs).strip()


def clean_line_whitespace(text: str) -> str:
    """Clean individual lines preserving explicit structure."""
    if not text:
        return ""
    lines = text.split("\n")
    cleaned = [re.sub(r"[ \t]+", " ", line).strip() for line in lines]
    return "\n".join(cleaned)
