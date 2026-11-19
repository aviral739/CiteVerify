"""Stage 5: Evidence Retrieval.

Future Responsibility:
Obtain source text (full text or abstract) of the cited reference and locate relevant paragraphs.
Retrieve evidence snippets matching the semantic context of the claiming paper.

Supported source types:
- 'full_text_available': Open-access full text retrieved from arXiv, PubMed Central, or publisher.
- 'abstract_only': Paywalled or unavailable full text; abstract retrieved via metadata API.
- 'unavailable': Metadata or paper unreachable.

TODO:
- Fetch open access PDF via Unpaywall / arXiv / PubMed Central.
- Parse cited PDF or fallback to abstract text.
- Run vector or BM25 retrieval to isolate top-k relevant candidate evidence snippets.
"""

from typing import List, Optional
from pydantic import BaseModel
from app.models.schemas import EvidenceAvailabilityEnum


class RetrievedEvidenceItem(BaseModel):
    citation_key: str
    evidence_text: str
    section_title: Optional[str] = None
    page_number: Optional[int] = None
    source_type: EvidenceAvailabilityEnum
    retrieval_score: float = 0.0


class S5EvidenceInput(BaseModel):
    document_id: str
    resolved_references: List[dict]
    claims: List[dict]


class S5EvidenceOutput(BaseModel):
    document_id: str
    evidence_items: List[RetrievedEvidenceItem]


async def run_stage_5(input_data: S5EvidenceInput) -> S5EvidenceOutput:
    """Execute Stage 5: Evidence Retrieval skeleton entrypoint."""
    # SKELETON PLACEHOLDER
    return S5EvidenceOutput(
        document_id=input_data.document_id,
        evidence_items=[
            RetrievedEvidenceItem(
                citation_key="[1]",
                evidence_text="We propose the Transformer, a model architecture eschewing recurrence and instead relying entirely on an attention mechanism to draw global dependencies between input and output.",
                section_title="Abstract",
                page_number=1,
                source_type=EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE,
                retrieval_score=0.92,
            )
        ],
    )

