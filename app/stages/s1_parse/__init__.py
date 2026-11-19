"""Stage 1: Document Parsing.

Future Responsibility:
Extract structural text, sections, headers, and paragraphs from uploaded PDFs or raw text files.
Supported future tools: PyPDF / pdfminer / GROBID.

TODO:
- Implement PDF file ingestion and caching.
- Extract structured sections (Abstract, Introduction, Related Work, Methods, Results, Discussion).
- Handle multi-column layouts and mathematical formulas without losing citation markers.
"""

from typing import Any, Dict
from pydantic import BaseModel


class S1ParseInput(BaseModel):
    document_id: str
    file_path: str


class S1ParseOutput(BaseModel):
    document_id: str
    title: str
    sections: Dict[str, str]
    raw_text: str
    page_count: int


async def run_stage_1(input_data: S1ParseInput) -> S1ParseOutput:
    """Execute Stage 1: Document Parsing skeleton entrypoint."""
    # SKELETON PLACEHOLDER
    return S1ParseOutput(
        document_id=input_data.document_id,
        title="Unparsed Document",
        sections={"body": "Document parsing stage skeleton. Implementation pending."},
        raw_text="Document parsing stage skeleton. Implementation pending.",
        page_count=1,
    )

