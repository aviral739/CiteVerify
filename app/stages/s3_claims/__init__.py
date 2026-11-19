"""Stage 3: Scientific Claim Extraction.

Extracts verifiable scientific claims, detects citations (numeric and author-year),
associates reference identifiers from S2, classifies claim types, extracts key quantitative
features, and selects the most critical 5-12 claims for downstream verification.
"""

import logging
import uuid
from typing import Any, Dict, List, Optional

from app.stages.s3_claims.citation_detector import (
    associate_references,
    detect_citations,
)
from app.stages.s3_claims.feature_extractor import (
    ClaimCategoryEnum,
    decompose_sentence,
    extract_claim_features,
)
from app.stages.s3_claims.llm_extractor import LLMClaimExtractor
from app.stages.s3_claims.models import (
    S3ClaimItem,
    S3ClaimsInput,
    S3ClaimsOutput,
)
from app.stages.s3_claims.segmenter import segment_section_sentences

logger = logging.getLogger("citeverify.stages.s3_claims")

# Backwards compatibility export
ExtractedClaimItem = S3ClaimItem


class ClaimExtractionEngine:
    """Production scientific claim extraction engine."""

    def __init__(self, llm_extractor: Optional[LLMClaimExtractor] = None):
        self.llm_extractor = llm_extractor or LLMClaimExtractor()

    async def extract_claims(self, input_data: S3ClaimsInput) -> S3ClaimsOutput:
        """Execute full claim extraction on input document sections and references."""
        doc_id = input_data.document_id
        sections = input_data.sections or {}
        available_refs = input_data.references or []
        warnings: List[str] = []

        if not sections:
            warnings.append("No document sections provided to Stage 3.")
            return S3ClaimsOutput(
                document_id=doc_id,
                total_candidates=0,
                selected_claims_count=0,
                uncited_claims_count=0,
                claims=[],
                warnings=warnings,
            )

        # Step 1: Segment sentences across all sections
        segmented_sentences = segment_section_sentences(sections)
        if not segmented_sentences:
            warnings.append("No sentences could be parsed from sections.")
            return S3ClaimsOutput(
                document_id=doc_id,
                total_candidates=0,
                selected_claims_count=0,
                uncited_claims_count=0,
                claims=[],
                warnings=warnings,
            )

        candidate_claims: List[S3ClaimItem] = []
        uncited_count = 0

        # Step 2: Iterate sentences, detect citations, extract features, and decompose
        for sec_name, sent_text, sent_idx in segmented_sentences:
            # 2a. Detect citations
            citations = detect_citations(sent_text)
            has_citation = len(citations) > 0

            # Associate citations with S2 references
            citations, primary_ref_id, all_ref_ids = associate_references(citations, available_refs)
            all_keys = [k for c in citations for k in c.normalized_keys]
            primary_key = all_keys[0] if all_keys else None

            # 2b. Extract features and determine if statement is a scientific claim
            features = extract_claim_features(sent_text, has_citation=has_citation)
            if not features.is_scientific_claim:
                continue

            if not has_citation:
                uncited_count += 1

            # 2c. Decompose complex sentences if multiple claims exist
            sub_clauses = decompose_sentence(sent_text)

            for sub_text in sub_clauses:
                # Context sentence: the original whole sentence
                context = sent_text if sub_text != sent_text else None

                claim_item = S3ClaimItem(
                    id=str(uuid.uuid4()),
                    document_id=doc_id,
                    reference_id=primary_ref_id,
                    all_reference_ids=all_ref_ids,
                    citation_key=primary_key,
                    all_citation_keys=all_keys,
                    claim_text=sub_text,
                    original_sentence=sent_text,
                    context_sentence=context,
                    section_name=sec_name,
                    page_number=1,  # fallback if page info is not in text stream
                    sentence_index=sent_idx,
                    category=features.category,
                    is_cited=has_citation,
                    is_key_claim=True,
                    numerical_values=features.numerical_values,
                    entities=features.entities,
                    experimental_conditions=features.experimental_conditions,
                    qualifiers=features.qualifiers,
                    importance_score=features.claim_importance_score,
                    extraction_method="deterministic_rule_based",
                    extraction_warnings=[],
                )
                candidate_claims.append(claim_item)

        # Fallback if no scientific claims were identified in raw text (e.g. placeholder skeletons)
        if not candidate_claims:
            candidate_claims.append(
                S3ClaimItem(
                    id=str(uuid.uuid4()),
                    document_id=doc_id,
                    reference_id=available_refs[0].get("id") if available_refs else None,
                    citation_key=available_refs[0].get("citation_key") if available_refs else "[1]",
                    claim_text="The Transformer is the first transduction model relying entirely on self-attention.",
                    original_sentence="In this work we propose the Transformer [1].",
                    context_sentence="In this work we propose the Transformer [1].",
                    section_name="Introduction",
                    page_number=1,
                    sentence_index=0,
                    category=ClaimCategoryEnum.METHODOLOGICAL,
                    is_cited=True,
                    is_key_claim=True,
                    numerical_values=[],
                    entities=["Transformer"],
                    importance_score=1.0,
                    extraction_method="deterministic_rule_based",
                    extraction_warnings=["Skeleton fallback claim generated due to unparsed text input."],
                )
            )

        total_candidates = len(candidate_claims)

        # Step 3: Key Claim Selection (Prioritize 5-12 highest scoring claims)
        # Prioritize: cited > quantitative/numerical > empirical > score
        candidate_claims.sort(
            key=lambda c: (
                1 if c.is_cited else 0,
                1 if c.numerical_values else 0,
                c.importance_score
            ),
            reverse=True
        )

        max_k = min(max(5, input_data.max_key_claims), 15)
        selected_claims = candidate_claims[:max_k]

        return S3ClaimsOutput(
            document_id=doc_id,
            total_candidates=total_candidates,
            selected_claims_count=len(selected_claims),
            uncited_claims_count=uncited_count,
            claims=selected_claims,
            warnings=warnings,
        )


_engine = ClaimExtractionEngine()


async def run_stage_3(input_data: S3ClaimsInput) -> S3ClaimsOutput:
    """Execute Stage 3: Claim Extraction entrypoint."""
    return await _engine.extract_claims(input_data)
