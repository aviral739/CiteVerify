"""PDF parsing engine using PyMuPDF (fitz)."""

import os
from typing import List, Tuple
import pymupdf

from app.stages.s1_parse.models import DocumentMetadata, PageContent
from app.stages.s1_parse.normalizer import normalize_academic_text


def parse_pdf_document(file_path: str) -> Tuple[str, List[PageContent], DocumentMetadata, List[str], bool]:
    """Parse a PDF document and extract page-level text, metadata, and quality warnings.

    Returns:
        full_text, pages, metadata, warnings, is_scanned
    """
    warnings: List[str] = []
    pages: List[PageContent] = []
    is_scanned = False

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"PDF file not found at path: {file_path}")

    file_size = os.path.getsize(file_path)

    try:
        doc = pymupdf.open(file_path)
    except Exception as exc:
        raise ValueError(f"Failed to open PDF file (corrupted or invalid format): {exc}") from exc

    try:
        if doc.is_encrypted:
            # Attempt to authenticate with empty password
            if not doc.authenticate(""):
                warnings.append("Document is password protected and could not be decrypted.")
                return (
                    "",
                    [],
                    DocumentMetadata(
                        file_type="pdf",
                        file_size_bytes=file_size,
                        page_count=0,
                    ),
                    warnings,
                    False,
                )

        page_count = len(doc)
        doc_meta = doc.metadata or {}

        title = doc_meta.get("title") or os.path.splitext(os.path.basename(file_path))[0]
        authors = doc_meta.get("author") or None

        total_extracted_chars = 0
        pages_with_images_only = 0

        for page_idx in range(page_count):
            page_num = page_idx + 1
            page = doc[page_idx]

            # Extract raw text
            page_raw_text = page.get_text("text") or ""
            normalized_page = normalize_academic_text(page_raw_text)

            char_count = len(normalized_page.strip())
            word_count = len(normalized_page.split())
            is_empty = (char_count == 0)

            # Check if page has images but no or very little text (potential scanned page)
            image_list = page.get_images()
            is_image_page = (char_count < 50 and len(image_list) > 0)
            if is_image_page:
                pages_with_images_only += 1

            pages.append(
                PageContent(
                    page_number=page_num,
                    raw_text=page_raw_text,
                    normalized_text=normalized_page,
                    is_empty=is_empty,
                    is_scanned_or_image_only=is_image_page,
                    char_count=char_count,
                    word_count=word_count,
                )
            )
            total_extracted_chars += char_count

        # Quality warnings
        if page_count == 0:
            warnings.append("PDF document contains 0 pages.")
        elif total_extracted_chars == 0:
            warnings.append("No readable text could be extracted. The document may be image-only, scanned, or empty.")
            is_scanned = True
        elif pages_with_images_only >= (page_count * 0.7):
            warnings.append("High proportion of pages are image-only/scanned without OCR text.")
            is_scanned = True

        full_text = "\n\n".join(p.normalized_text for p in pages if p.normalized_text)

        metadata = DocumentMetadata(
            title=title,
            authors=authors,
            creator=doc_meta.get("creator"),
            producer=doc_meta.get("producer"),
            creation_date=doc_meta.get("creationDate"),
            modification_date=doc_meta.get("modDate"),
            file_type="pdf",
            file_size_bytes=file_size,
            page_count=page_count,
        )

        return full_text, pages, metadata, warnings, is_scanned

    finally:
        doc.close()
