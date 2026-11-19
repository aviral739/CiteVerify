"""Stage 2: Reference Extraction.

Locates the bibliography section and parses individual reference strings into structured items.
Detects numeric and author-year in-text citation markers, associates them with references,
and performs hygiene inspections.
"""

import asyncio
import logging
from typing import List

from app.stages.s2_references.bibliography_parser import (
    find_bibliography_text,
    parse_reference_metadata,
    segment_bibliography_entries,
)
from app.stages.s2_references.citation_detector import (
    associate_citations_with_references,
    extract_in_text_citations,
)
from app.stages.s2_references.hygiene_checker import run_reference_hygiene_checks
from app.stages.s2_references.models import (
    ExtractedReferenceItem,
    HygieneCheckReport,
    InTextCitationMarker,
    RawReferenceItem,
    S2ReferencesInput,
    S2ReferencesOutput,
)

logger = logging.getLogger("citeverify.stages.s2_references")

__all__ = [
    "S2ReferencesInput",
    "S2ReferencesOutput",
    "RawReferenceItem",
    "ExtractedReferenceItem",
    "InTextCitationMarker",
    "HygieneCheckReport",
    "run_stage_2",
]


def _sync_extract_references(document_id: str, raw_text: str, sections_dict: dict = None) -> S2ReferencesOutput:
    """Synchronous pipeline logic for Stage 2."""
    # 1. Locate bibliography text
    bib_text, found_bib = find_bibliography_text(raw_text, sections_dict)

    # 2. Segment bibliography into individual entries
    segmented = segment_bibliography_entries(bib_text) if found_bib else []

    # 3. Parse metadata for each entry
    structured_refs: List[ExtractedReferenceItem] = []
    for key, raw_entry in segmented:
        ref_item = parse_reference_metadata(key, raw_entry)
        structured_refs.append(ref_item)

    # 4. Extract in-text citation markers from main body
    # (Exclude bibliography text if isolated to prevent self-citation loops)
    body_text = raw_text
    if found_bib and bib_text:
        body_text = raw_text.replace(bib_text, "")

    citations = extract_in_text_citations(body_text)

    # 5. Associate in-text citations with bibliography entries
    citations, structured_refs = associate_citations_with_references(citations, structured_refs)

    # 6. Run reference hygiene inspections
    hygiene_report = run_reference_hygiene_checks(structured_refs, citations, missing_bib=(not found_bib))

    # 7. Build backward-compatible RawReferenceItem list for downstream S3/S4
    compat_references: List[RawReferenceItem] = []
    for ref in structured_refs:
        compat_references.append(
            RawReferenceItem(
                citation_key=ref.citation_key,
                raw_citation=ref.raw_citation,
                reference_id=ref.reference_id,
                title=ref.title,
                year=ref.year,
                doi=ref.doi,
            )
        )

    # If document has no references found, provide clean empty lists without failing
    return S2ReferencesOutput(
        document_id=document_id,
        references=compat_references,
        structured_references=structured_refs,
        in_text_citations=citations,
        hygiene_report=hygiene_report,
        total_references=len(structured_refs),
        total_in_text_citations=len(citations),
    )


async def run_stage_2(input_data: S2ReferencesInput) -> S2ReferencesOutput:
    """Execute Stage 2: Reference Extraction asynchronously."""
    logger.info(f"Executing Stage 2 reference extraction for document {input_data.document_id}")

    # Fallback for skeleton placeholder input
    if "Document parsing stage skeleton" in input_data.raw_text:
        return S2ReferencesOutput(
            document_id=input_data.document_id,
            references=[
                RawReferenceItem(
                    citation_key="[1]",
                    raw_citation="Vaswani, A., et al. (2017). Attention is all you need. NeurIPS.",
                )
            ],
            total_references=1,
            total_in_text_citations=0,
        )

    output = await asyncio.to_thread(
        _sync_extract_references,
        input_data.document_id,
        input_data.raw_text,
        input_data.sections or {},
    )
    return output
