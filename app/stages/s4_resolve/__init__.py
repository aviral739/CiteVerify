"""Stage 4: Reference Resolution.

Future Responsibility:
Resolve raw bibliographic strings against authoritative academic metadata APIs:
- CrossRef API
- OpenAlex API
- Semantic Scholar API

Retrieve canonical DOIs, titles, authors, venues, publication years, and open-access PDF links.

TODO:
- Query CrossRef with title / author fuzzy matching.
- Normalize and validate DOIs.
- Fall back to OpenAlex / Semantic Scholar on missing records.
- Cache resolution results to avoid redundant external network roundtrips.
"""

from typing import List, Optional
from pydantic import BaseModel


class ResolvedReferenceItem(BaseModel):
    citation_key: str
    doi: Optional[str] = None
    title: str
    year: Optional[int] = None
    venue: Optional[str] = None
    oa_pdf_url: Optional[str] = None
    confidence: float = 0.0


class S4ResolveInput(BaseModel):
    document_id: str
    raw_citations: List[dict]


class S4ResolveOutput(BaseModel):
    document_id: str
    resolved_references: List[ResolvedReferenceItem]


async def run_stage_4(input_data: S4ResolveInput) -> S4ResolveOutput:
    """Execute Stage 4: Reference Resolution skeleton entrypoint."""
    # SKELETON PLACEHOLDER
    return S4ResolveOutput(
        document_id=input_data.document_id,
        resolved_references=[
            ResolvedReferenceItem(
                citation_key="[1]",
                doi="10.48550/arXiv.1706.03762",
                title="Attention Is All You Need",
                year=2017,
                venue="NeurIPS",
                oa_pdf_url="https://arxiv.org/pdf/1706.03762.pdf",
                confidence=0.98,
            )
        ],
    )

