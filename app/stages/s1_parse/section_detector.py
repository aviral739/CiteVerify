"""Academic section detection and segmentation."""

import re
from typing import Dict, List, Tuple
from app.stages.s1_parse.models import DocumentSection

# Common section type aliases and canonical keywords
SECTION_PATTERNS = [
    ("abstract", r"^(?:\d+[\.\s]*)?abstract\b"),
    ("introduction", r"^(?:\d+[\.\s]*)?introduction\b"),
    ("related_work", r"^(?:\d+[\.\s]*)?(?:related\s+work|literature\s+review|background|prior\s+work)\b"),
    ("methodology", r"^(?:\d+[\.\s]*)?(?:methodology|methods|materials\s+and\s+methods|proposed\s+method|approach|model|system\s+design)\b"),
    ("results", r"^(?:\d+[\.\s]*)?(?:results|experiments|experimental\s+results|evaluation|findings)\b"),
    ("discussion", r"^(?:\d+[\.\s]*)?(?:discussion|analysis|comparative\s+analysis)\b"),
    ("conclusion", r"^(?:\d+[\.\s]*)?(?:conclusion|conclusions|concluding\s+remarks|summary)\b"),
    ("references", r"^(?:\d+[\.\s]*)?(?:references|bibliography|works\s+cited|literature\s+cited|references\s+and\s+notes)\b"),
    ("acknowledgements", r"^(?:\d+[\.\s]*)?(?:acknowledgements?|funding|competing\s+interests)\b"),
    ("appendix", r"^(?:\d+[\.\s]*)?(?:appendix|appendices|supplementary\s+material)\b"),
]

# Regex for line headings: e.g. "1. Introduction", "## Methodology", "ABSTRACT", "II. RELATED WORK"
HEADING_REGEX = re.compile(
    r"^(?:#{1,4}\s+|(?:\d+(?:\.\d+)*|[I|V|X]+\.?)\s+)?([A-Z][A-Za-z0-9\s,\-–:]{2,60})$"
)


def classify_heading_text(heading: str) -> str:
    """Classify a section heading into a canonical section category."""
    clean = heading.strip().lower()
    # Strip numbering prefix like "1. ", "1.1 ", "ii. "
    clean_no_num = re.sub(r"^(?:(?:\d+(?:\.\d+)*|[ivx]+)\.?\s*)+", "", clean).strip()

    for category, pattern in SECTION_PATTERNS:
        if re.search(pattern, clean_no_num) or re.search(pattern, clean):
            return category

    return "other"


def is_likely_heading(line: str) -> bool:
    """Heuristic to detect if a standalone line is likely a section heading."""
    line = line.strip()
    if not line or len(line) > 80:
        return False
    # If ends with terminal sentence punctuation (. ! ?), rarely a heading (except numbering like "1.")
    if line.endswith(".") and not re.match(r"^\d+\.$", line):
        # Allow if it's e.g. "1. Introduction." but usually headings do not have periods at end
        if len(line.split()) > 4:
            return False

    # Check against known category patterns
    if classify_heading_text(line) != "other":
        return True

    # Check numbered heading pattern (1 or 2 digit section numbers, never 4-digit years)
    if re.match(r"^(?:(?:\d{1,2}(?:\.\d{1,2})*|[IVX]+)\.?\s+)[A-Z][A-Za-z\s]{2,40}$", line):
        return True

    # Check markdown heading pattern
    if re.match(r"^#{1,3}\s+[A-Za-z0-9\s]{2,50}$", line):
        return True

    # Check ALL CAPS short heading
    if line.isupper() and 3 <= len(line) <= 40 and not any(char.isdigit() for char in line):
        return True

    return False


def segment_document_sections(text: str) -> Tuple[Dict[str, str], List[DocumentSection]]:
    """Segment a manuscript text into sections using detected headings.

    Returns:
        - sections_dict: Dict[str, str] mapping section name to content (compatible with S1/S3 contract)
        - structured_sections: List[DocumentSection] with rich metadata
    """
    lines = text.split("\n")
    sections_dict: Dict[str, str] = {}
    structured_sections: List[DocumentSection] = []

    current_heading = "Header"
    current_lines: List[str] = []
    order = 0

    def commit_section(heading: str, content_lines: List[str]):
        nonlocal order
        content = "\n".join(content_lines).strip()
        if not content and heading == "Header":
            return
        cat = classify_heading_text(heading)
        # Unique dictionary key
        dict_key = heading.lower().strip()
        if dict_key in sections_dict:
            dict_key = f"{dict_key}_{order}"
        sections_dict[dict_key] = content

        structured_sections.append(
            DocumentSection(
                heading=heading,
                normalized_heading=heading.strip(),
                section_type=cat,
                content=content,
                order=order,
            )
        )
        order += 1

    in_references = False

    for line in lines:
        stripped = line.strip()
        if is_likely_heading(stripped):
            cat = classify_heading_text(stripped)
            # Once inside references, only recognize valid post-references sections
            if in_references:
                is_post_ref = (
                    cat in ("appendix", "acknowledgements")
                    or bool(re.match(r"^(?:(?:[A-Z0-9]+[\.\s]*)?(?:appendix|appendices|supplementary|author\s+contributions))\b", stripped, re.IGNORECASE))
                )
                if not is_post_ref:
                    current_lines.append(line)
                    continue
                else:
                    in_references = False

            if cat == "references":
                in_references = True

            # Commit previous section
            commit_section(current_heading, current_lines)
            current_heading = stripped
            current_lines = []
        else:
            current_lines.append(line)

    # Commit final section
    commit_section(current_heading, current_lines)

    # Fallback: if no sections detected at all, return full text in 'body'
    if not sections_dict:
        sections_dict["body"] = text
        structured_sections.append(
            DocumentSection(
                heading="body",
                normalized_heading="body",
                section_type="other",
                content=text,
                order=0,
            )
        )

    return sections_dict, structured_sections
