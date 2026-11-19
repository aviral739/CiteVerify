"""Evidence retrieval orchestrator matching claims to cited passages."""

import logging
import uuid
from typing import Any, Dict, List, Optional

from app.models.schemas import EvidenceAvailabilityEnum
from app.stages.s5_evidence.bm25 import BM25Retriever
from app.stages.s5_evidence.chunker import chunk_document_text
from app.stages.s5_evidence.models import EvidencePassageItem, S5EvidenceOutput
from app.stages.s5_evidence.source_loader import SourceDocumentLoader, source_loader

logger = logging.getLogger("citeverify.stages.s5_evidence.retriever")


class EvidenceRetrievalEngine:
    """Retrieves relevant evidence passages for claims from cited reference works."""

    def __init__(self, loader: Optional[SourceDocumentLoader] = None):
        self.loader = loader or source_loader

    async def retrieve_evidence_for_claims(
        self,
        document_id: str,
        resolved_references: List[Dict[str, Any]],
        claims: List[Dict[str, Any]],
        top_k: int = 2,
    ) -> S5EvidenceOutput:
        """Execute evidence retrieval for all claims across resolved references."""
        # Index references by citation_key and stable ID
        ref_by_key: Dict[str, Dict[str, Any]] = {}
        ref_by_id: Dict[str, Dict[str, Any]] = {}

        for ref in resolved_references:
            ck = ref.get("citation_key")
            rid = ref.get("id") or ref.get("reference_id")
            if ck:
                ref_by_key[ck.strip()] = ref
                # Also index without brackets
                ref_by_key[ck.strip("[]")] = ref
            if rid:
                ref_by_id[str(rid).strip()] = ref

        evidence_items: List[EvidencePassageItem] = []
        full_text_count = 0
        abstract_count = 0
        unavailable_count = 0
        warnings: List[str] = []

        # Cache extracted passages for references to avoid repeated downloads & chunking
        # Key: reference_id or citation_key -> (List[DocumentPassage], source_type, source_url)
        ref_passages_cache: Dict[str, Any] = {}

        for claim in claims:
            claim_id = claim.get("id") or claim.get("claim_id") or str(uuid.uuid4())
            claim_text = claim.get("claim_text") or ""
            target_ck = claim.get("citation_key")
            target_rid = claim.get("reference_id")

            # Find matching reference metadata
            matched_ref = None
            if target_rid and str(target_rid).strip() in ref_by_id:
                matched_ref = ref_by_id[str(target_rid).strip()]
            elif target_ck and target_ck.strip() in ref_by_key:
                matched_ref = ref_by_key[target_ck.strip()]
            elif claim.get("all_citation_keys"):
                for ack in claim["all_citation_keys"]:
                    if ack in ref_by_key:
                        matched_ref = ref_by_key[ack]
                        break

            # Author + Year fallback matching across resolved references
            if not matched_ref:
                import re
                keys_to_search = ([target_ck] if target_ck else []) + (claim.get("all_citation_keys") or []) + [claim_text]
                for k_cand in keys_to_search:
                    if not k_cand:
                        continue
                    y_m = re.search(r'\b(19\d\d|20[0-2]\d)\b', k_cand)
                    auth_m = re.search(r'([A-Z][a-zA-Z\u00C0-\u024F\.\-]+)', k_cand)
                    if y_m and auth_m:
                        cand_yr = int(y_m.group(1))
                        cand_surname = auth_m.group(1).rstrip(",.").lower()
                        for r in resolved_references:
                            r_yr = r.get("year") or r.get("resolved_year")
                            r_authors = (r.get("authors") or r.get("resolved_authors") or "").lower()
                            r_raw = (r.get("raw_citation") or "").lower()
                            if r_yr == cand_yr and (cand_surname in r_authors or cand_surname in r_raw):
                                matched_ref = r
                                break
                    if matched_ref:
                        break

            if not matched_ref:
                # Reference metadata missing or uncited
                warnings.append(f"Claim '{claim_id}' had no matching resolved reference; marked as unavailable.")
                unavailable_count += 1
                evidence_items.append(
                    EvidencePassageItem(
                        evidence_id=str(uuid.uuid4()),
                        citation_key=target_ck or "[?]",
                        reference_id=target_rid,
                        claim_id=claim_id,
                        evidence_text="Reference could not be located in resolved bibliography.",
                        section_title=None,
                        page_number=None,
                        source_type=EvidenceAvailabilityEnum.UNAVAILABLE,
                        retrieval_score=0.0,
                    )
                )
                continue

            ref_key = matched_ref.get("citation_key") or target_ck or "[?]"
            ref_id = matched_ref.get("id") or matched_ref.get("reference_id")
            cache_id = str(ref_id) if ref_id else ref_key

            # Load source passages (using cache if already loaded for another claim)
            if cache_id in ref_passages_cache:
                passages, source_type, source_url = ref_passages_cache[cache_id]
            else:
                passages, source_type, source_url = await self._load_reference_passages(matched_ref)
                ref_passages_cache[cache_id] = (passages, source_type, source_url)

            if not passages:
                unavailable_count += 1
                warnings.append(f"Reference '{ref_key}' full text and abstract were unavailable.")
                evidence_items.append(
                    EvidencePassageItem(
                        evidence_id=str(uuid.uuid4()),
                        citation_key=ref_key,
                        reference_id=ref_id,
                        claim_id=claim_id,
                        evidence_text="Source document text and abstract are unavailable.",
                        section_title=None,
                        page_number=None,
                        source_type=EvidenceAvailabilityEnum.UNAVAILABLE,
                        retrieval_score=0.0,
                    )
                )
                continue

            if source_type == EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE:
                full_text_count += 1
            else:
                abstract_count += 1

            # Execute BM25 retrieval over the reference's passages
            corpus_texts = [p.text for p in passages]
            bm25 = BM25Retriever(corpus_texts)
            top_matches = bm25.search_top_k(claim_text, top_k=top_k)

            # Build evidence passages
            for rank, (p_idx, score) in enumerate(top_matches):
                chosen_passage = passages[p_idx]
                evidence_items.append(
                    EvidencePassageItem(
                        evidence_id=str(uuid.uuid4()),
                        citation_key=ref_key,
                        reference_id=ref_id,
                        claim_id=claim_id,
                        evidence_text=chosen_passage.text,
                        section_title=chosen_passage.section_title,
                        page_number=chosen_passage.page_number,
                        source_type=source_type,
                        retrieval_score=round(float(score), 4),
                        source_url=source_url,
                    )
                )

        return S5EvidenceOutput(
            document_id=document_id,
            evidence_items=evidence_items,
            total_retrieved=len(evidence_items),
            full_text_count=full_text_count,
            abstract_count=abstract_count,
            unavailable_count=unavailable_count,
            warnings=warnings,
        )

    async def _load_reference_passages(self, ref: Dict[str, Any]) -> Any:
        """Load text from normalized source text if available, otherwise OA PDF, otherwise abstract."""
        full_text = ref.get("full_text") or ref.get("source_text")
        oa_pdf_url = ref.get("oa_pdf_url")
        abstract = ref.get("abstract")

        # 1. Pre-fetched or normalized full text (e.g. Europe PMC XML text) without duplicate PDF download
        if full_text and full_text.strip():
            passages = chunk_document_text(full_text.strip())
            source_url = ref.get("url") or oa_pdf_url or (f"https://doi.org/{ref['doi']}" if ref.get("doi") else None)
            return passages, EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE, source_url

        # 2. Attempt full-text download if OA PDF URL is provided
        if oa_pdf_url:
            pdf_result = await self.loader.fetch_pdf_text(oa_pdf_url)
            if pdf_result:
                pdf_text, page_count = pdf_result
                if pdf_text.strip():
                    passages = chunk_document_text(pdf_text)
                    return passages, EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE, oa_pdf_url

        # 2. Fallback to abstract (never present abstract as full text)
        if abstract and abstract.strip():
            passages = chunk_document_text(abstract.strip())
            for p in passages:
                p.section_title = "Abstract"
                p.page_number = 1
            return passages, EvidenceAvailabilityEnum.ABSTRACT_ONLY, ref.get("url")

        # 3. Neither full text nor abstract is available
        return [], EvidenceAvailabilityEnum.UNAVAILABLE, None


evidence_retrieval_engine = EvidenceRetrievalEngine()
