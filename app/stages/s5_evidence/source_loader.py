"""Source text loader for Open-Access PDFs and abstracts."""

import asyncio
import io
import logging
from typing import Optional, Tuple
import httpx
import pymupdf

from app.core.http import get_http_client
from app.stages.s1_parse.normalizer import normalize_academic_text

logger = logging.getLogger("citeverify.stages.s5_evidence.source_loader")


class SourceDocumentLoader:
    """Retrieves and parses source documents (full-text PDFs or abstracts)."""

    def __init__(self, timeout_seconds: float = 12.0):
        self.timeout = timeout_seconds

    async def fetch_pdf_text(self, pdf_url: str) -> Optional[Tuple[str, int]]:
        """Download open-access PDF into memory and extract text using PyMuPDF.

        Returns:
            Tuple[full_text, page_count] or None if unavailable/unreachable.
        """
        if not pdf_url or not pdf_url.startswith("http"):
            return None

        client = await get_http_client()
        try:
            response = await client.get(
                pdf_url,
                timeout=self.timeout,
                follow_redirects=True,
                headers={"User-Agent": "CiteVerify-EvidenceRetriever/0.1.0"},
            )
            if response.status_code != 200 or len(response.content) < 100:
                logger.warning(f"Failed to fetch PDF from {pdf_url}: HTTP {response.status_code}")
                return None

            # Parse in background thread to keep event loop responsive
            def _parse_bytes(data: bytes) -> Optional[Tuple[str, int]]:
                try:
                    doc = pymupdf.open(stream=data, filetype="pdf")
                    page_texts = []
                    for page_idx in range(len(doc)):
                        p_text = doc[page_idx].get_text("text") or ""
                        if p_text.strip():
                            page_texts.append(p_text.strip())
                    page_count = len(doc)
                    doc.close()
                    full_text = "\n\n".join(page_texts)
                    return normalize_academic_text(full_text), page_count
                except Exception as exc:
                    logger.warning(f"Error parsing downloaded PDF bytes: {exc}")
                    return None

            return await asyncio.to_thread(_parse_bytes, response.content)

        except (httpx.RequestError, httpx.TimeoutException) as exc:
            logger.warning(f"Network error fetching PDF from {pdf_url}: {exc}")
            return None


source_loader = SourceDocumentLoader()
