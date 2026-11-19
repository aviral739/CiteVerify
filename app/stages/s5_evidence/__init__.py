"""Stage 5: Evidence Retrieval.

Obtains source text (open-access full text or abstract) of cited references,
chunks documents with section and page awareness, and retrieves top-k relevant
passages using BM25 lexical ranking.
"""

import logging
from typing import List

from app.models.schemas import EvidenceAvailabilityEnum
from app.stages.s5_evidence.bm25 import BM25Retriever
from app.stages.s5_evidence.chunker import DocumentPassage, chunk_document_text
from app.stages.s5_evidence.models import (
    EvidencePassageItem,
    RetrievedEvidenceItem,
    S5EvidenceInput,
    S5EvidenceOutput,
)
from app.stages.s5_evidence.retriever import EvidenceRetrievalEngine, evidence_retrieval_engine
from app.stages.s5_evidence.source_loader import SourceDocumentLoader, source_loader

logger = logging.getLogger("citeverify.stages.s5_evidence")

__all__ = [
    "S5EvidenceInput",
    "S5EvidenceOutput",
    "EvidencePassageItem",
    "RetrievedEvidenceItem",
    "EvidenceAvailabilityEnum",
    "EvidenceRetrievalEngine",
    "evidence_retrieval_engine",
    "BM25Retriever",
    "chunk_document_text",
    "DocumentPassage",
    "SourceDocumentLoader",
    "source_loader",
    "run_stage_5",
]


async def run_stage_5(input_data: S5EvidenceInput) -> S5EvidenceOutput:
    """Execute Stage 5: Evidence Retrieval pipeline entrypoint."""
    doc_id = input_data.document_id
    resolved_refs = input_data.resolved_references or []
    claims = input_data.claims or []
    logger.info(f"Executing Stage 5 evidence retrieval for doc {doc_id} ({len(claims)} claims, {len(resolved_refs)} references)")

    if not claims:
        return S5EvidenceOutput(
            document_id=doc_id,
            evidence_items=[],
            total_retrieved=0,
            full_text_count=0,
            abstract_count=0,
            unavailable_count=0,
            warnings=["No claims provided to Stage 5."],
        )

    output = await evidence_retrieval_engine.retrieve_evidence_for_claims(
        document_id=doc_id,
        resolved_references=resolved_refs,
        claims=claims,
        top_k=2,
    )
    return output
