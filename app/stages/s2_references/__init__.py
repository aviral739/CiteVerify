"""Stage 2: Reference Extraction.

Future Responsibility:
Locate the bibliography/references section and parse individual reference strings into structured items.
Identify citation keys (e.g. '[1]', '[Vaswani+17]', '(Smith et al., 2020)').

TODO:
- Extract raw reference strings from bibliography.
- Segment individual references.
- Link in-text citation callouts with bibliography entries.
"""

from typing import List, Optional
from pydantic import BaseModel


class RawReferenceItem(BaseModel):
    citation_key: str
    raw_citation: str


class S2ReferencesInput(BaseModel):
    document_id: str
    raw_text: str


class S2ReferencesOutput(BaseModel):
    document_id: str
    references: List[RawReferenceItem]


async def run_stage_2(input_data: S2ReferencesInput) -> S2ReferencesOutput:
    """Execute Stage 2: Reference Extraction skeleton entrypoint."""
    # SKELETON PLACEHOLDER
    return S2ReferencesOutput(
        document_id=input_data.document_id,
        references=[
            RawReferenceItem(
                citation_key="[1]",
                raw_citation="Vaswani, A., et al. (2017). Attention is all you need. NeurIPS.",
            )
        ],
    )

