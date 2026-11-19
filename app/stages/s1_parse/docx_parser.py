"""DOCX parsing engine using python-docx."""

import os
from typing import List, Tuple
import docx

from app.stages.s1_parse.models import DocumentMetadata, DocumentSection, PageContent
from app.stages.s1_parse.normalizer import normalize_academic_text
from app.stages.s1_parse.section_detector import classify_heading_text


def parse_docx_document(file_path: str) -> Tuple[str, List[PageContent], DocumentMetadata, List[str], List[DocumentSection]]:
    """Parse a DOCX document extracting paragraphs, headings, tables, and document metadata.

    Returns:
        full_text, pages, metadata, warnings, structured_sections
    """
    warnings: List[str] = []

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"DOCX file not found at path: {file_path}")

    file_size = os.path.getsize(file_path)

    try:
        doc = docx.Document(file_path)
    except Exception as exc:
        raise ValueError(f"Failed to open DOCX file (corrupted or invalid format): {exc}") from exc

    # Core properties
    core_props = doc.core_properties
    title = core_props.title or os.path.splitext(os.path.basename(file_path))[0]
    authors = core_props.author or None

    full_paragraphs: List[str] = []
    structured_sections: List[DocumentSection] = []

    current_heading = "Header"
    current_content: List[str] = []
    order = 0

    def commit_section():
        nonlocal order, current_heading, current_content
        text = "\n".join(current_content).strip()
        if not text and current_heading == "Header":
            return
        cat = classify_heading_text(current_heading)
        structured_sections.append(
            DocumentSection(
                heading=current_heading,
                normalized_heading=current_heading.strip(),
                section_type=cat,
                content=text,
                start_page=1,
                end_page=1,
                order=order,
            )
        )
        order += 1
        current_content = []

    # Process paragraphs and their styles
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue

        style_name = para.style.name.lower() if para.style else ""
        is_heading = "heading" in style_name or style_name.startswith("title")

        if is_heading:
            commit_section()
            current_heading = text
        else:
            current_content.append(text)

        full_paragraphs.append(text)

    # Process tables if practical
    for table in doc.tables:
        table_rows = []
        for row in table.rows:
            row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
            if row_text:
                table_rows.append(row_text)
        if table_rows:
            table_str = "\n".join(table_rows)
            current_content.append(table_str)
            full_paragraphs.append(table_str)

    commit_section()

    raw_combined = "\n\n".join(full_paragraphs)
    normalized_full = normalize_academic_text(raw_combined)

    # In DOCX without native page renderer, page count is estimated or 1
    page_count = 1
    pages = [
        PageContent(
            page_number=1,
            raw_text=raw_combined,
            normalized_text=normalized_full,
            is_empty=(len(normalized_full.strip()) == 0),
            char_count=len(normalized_full),
            word_count=len(normalized_full.split()),
        )
    ]

    metadata = DocumentMetadata(
        title=title,
        authors=authors,
        creator=core_props.author,
        creation_date=str(core_props.created) if core_props.created else None,
        modification_date=str(core_props.modified) if core_props.modified else None,
        file_type="docx",
        file_size_bytes=file_size,
        page_count=page_count,
    )

    if not normalized_full.strip():
        warnings.append("DOCX file contains no readable text.")

    return normalized_full, pages, metadata, warnings, structured_sections
