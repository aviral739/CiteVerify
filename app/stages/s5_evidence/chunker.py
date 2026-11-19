"""Passage chunking and section-aware segmenter for scientific text."""

import re
from typing import List, Optional
from pydantic import BaseModel


class DocumentPassage(BaseModel):
    """An excerpted passage with section and page metadata."""

    text: str
    section_title: Optional[str] = None
    page_number: Optional[int] = None
    passage_index: int = 0


def chunk_document_text(
    full_text: str,
    sections: Optional[dict] = None,
    pages: Optional[List[dict]] = None,
    target_words: int = 120,
    overlap_words: int = 25,
) -> List[DocumentPassage]:
    """Chunk manuscript text into overlapping passages while preserving section and page boundaries."""
    passages: List[DocumentPassage] = []
    passage_idx = 0

    # Strategy 1: If structured sections dictionary provided, chunk per section
    if sections:
        for sec_heading, sec_content in sections.items():
            clean_content = sec_content.strip()
            if not clean_content:
                continue

            # Split into paragraphs or sentences
            paras = [p.strip() for p in re.split(r"\n{2,}", clean_content) if p.strip()]
            for para in paras:
                words = para.split()
                if len(words) <= target_words:
                    passages.append(
                        DocumentPassage(
                            text=para,
                            section_title=sec_heading,
                            page_number=1,
                            passage_index=passage_idx,
                        )
                    )
                    passage_idx += 1
                else:
                    # Slide window
                    start = 0
                    while start < len(words):
                        chunk_words = words[start : start + target_words]
                        passages.append(
                            DocumentPassage(
                                text=" ".join(chunk_words),
                                section_title=sec_heading,
                                page_number=1,
                                passage_index=passage_idx,
                            )
                        )
                        passage_idx += 1
                        start += target_words - overlap_words
        if passages:
            return passages

    # Strategy 2: If page-level text is provided, chunk per page
    if pages:
        for page_obj in pages:
            page_num = page_obj.get("page_number", 1)
            p_text = page_obj.get("normalized_text") or page_obj.get("raw_text") or ""
            paras = [p.strip() for p in re.split(r"\n{2,}", p_text) if p.strip()]
            for para in paras:
                words = para.split()
                if len(words) <= target_words:
                    passages.append(
                        DocumentPassage(
                            text=para,
                            section_title="Body",
                            page_number=page_num,
                            passage_index=passage_idx,
                        )
                    )
                    passage_idx += 1
                else:
                    start = 0
                    while start < len(words):
                        chunk_words = words[start : start + target_words]
                        passages.append(
                            DocumentPassage(
                                text=" ".join(chunk_words),
                                section_title="Body",
                                page_number=page_num,
                                passage_index=passage_idx,
                            )
                        )
                        passage_idx += 1
                        start += target_words - overlap_words
        if passages:
            return passages

    # Strategy 3: Chunk full_text by paragraphs and sliding words
    paras = [p.strip() for p in re.split(r"\n{2,}", full_text) if p.strip()]
    for para in paras:
        words = para.split()
        if len(words) <= target_words:
            passages.append(
                DocumentPassage(
                    text=para,
                    section_title="Document",
                    page_number=1,
                    passage_index=passage_idx,
                )
            )
            passage_idx += 1
        else:
            start = 0
            while start < len(words):
                chunk_words = words[start : start + target_words]
                passages.append(
                    DocumentPassage(
                        text=" ".join(chunk_words),
                        section_title="Document",
                        page_number=1,
                        passage_index=passage_idx,
                    )
                )
                passage_idx += 1
                start += target_words - overlap_words

    return passages
