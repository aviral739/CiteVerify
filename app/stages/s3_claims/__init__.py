"""Stage 3: Claim Extraction.

Future Responsibility:
Identify scientific claims in the manuscript that directly reference cited works.
Extract the target sentence, immediate context, section, and attached citation markers.

TODO:
- Identify sentences containing citation markers.
- Determine if the sentence makes an assertional or empirical claim.
- Extract surrounding contextual sentences.
"""

from typing import List, Optional
from pydantic import BaseModel


class ExtractedClaimItem(BaseModel):
    citation_key: str
    claim_text: str
    context_sentence: Optional[str] = None
    section_name: Optional[str] = None


class S3ClaimsInput(BaseModel):
    document_id: str
    sections: dict


class S3ClaimsOutput(BaseModel):
    document_id: str
    claims: List[ExtractedClaimItem]


async def run_stage_3(input_data: S3ClaimsInput) -> S3ClaimsOutput:
    """Execute Stage 3: Claim Extraction skeleton entrypoint."""
    # SKELETON PLACEHOLDER
    return S3ClaimsOutput(
        document_id=input_data.document_id,
        claims=[
            ExtractedClaimItem(
                citation_key="[1]",
                claim_text="The Transformer is the first transduction model relying entirely on self-attention.",
                context_sentence="In this work we propose the Transformer [1].",
                section_name="Introduction",
            )
        ],
    )

