"""Core verification engine for S6 Claim Verification.

Coordinates deterministic numerical checking, scope auditing, source status auditing,
strengthened quotation guard verification, and Gemini Natural Language Inference (NLI)
with robust rule-based fallback.
"""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

from app.models.schemas import EvidenceAvailabilityEnum, VerdictEnum
from app.stages.s6_verify.models import (
    ClaimEvidencePair,
    EvidencePassage,
    VerificationResultItem,
)
from app.stages.s6_verify.numeric_checker import check_numerical_consistency
from app.stages.s6_verify.scope_auditor import audit_scope
from app.stages.s6_verify.llm_verifier import LLMClaimVerifier
from app.stages.s6_verify.quote_guard import verify_quotation

logger = logging.getLogger("citeverify.s6.engine")


def _tokenize(text: str) -> set:
    """Normalize text and extract lowercase word tokens."""
    return set(re.findall(r"\b[a-zA-Z0-9_-]{3,}\b", text.lower()))


def _compute_token_overlap(claim: str, evidence: str) -> float:
    """Calculate token Jaccard containment of claim terms in evidence."""
    c_tokens = _tokenize(claim)
    if not c_tokens:
        return 0.0
    e_tokens = _tokenize(evidence)
    overlap = c_tokens.intersection(e_tokens)
    return len(overlap) / len(c_tokens)


class ClaimVerificationEngine:
    """Production verification engine evaluating claim entailment and provenance."""

    def __init__(self, llm_verifier: Optional[LLMClaimVerifier] = None):
        self.llm_verifier = llm_verifier or LLMClaimVerifier()

    async def verify_pair(self, pair: ClaimEvidencePair) -> VerificationResultItem:
        """Verify a single ClaimEvidencePair and return a structured VerificationResultItem."""
        warnings: List[str] = []

        # Check publication age (warning only, no arbitrary outdatedness verdict)
        current_year = datetime.now().year
        if pair.reference_year:
            age = current_year - pair.reference_year
            if age > 10:
                warnings.append(
                    f"Cited reference is {age} years old ({pair.reference_year}). "
                    "Recommend checking recent literature for newer developments."
                )

        # 1. Filter and validate available evidence passages
        if not pair.evidence_passages:
            is_ret = pair.is_retracted
            return VerificationResultItem(
                claim_id=pair.claim_id,
                reference_id=pair.reference_id,
                citation_key=pair.citation_key,
                all_reference_ids=pair.all_reference_ids or ([pair.reference_id] if pair.reference_id else []),
                verdict=VerdictEnum.INSUFFICIENT_EVIDENCE,
                verdict_strength=0.0,
                retrieval_match=0.0,
                evidence_completeness=EvidenceAvailabilityEnum.UNAVAILABLE,
                explanation="No evidence passage was retrieved for this cited reference; cannot evaluate entailment.",
                is_retracted_source=is_ret,
                retraction_warning=pair.retraction_notice if is_ret else None,
                contradiction_type="retracted_source" if is_ret else None,
                needs_human_review=is_ret,
                verification_method="abstention",
                fallback_reason="abstention",
                warnings=warnings,
            )

        # Filter out unavailable or empty passages, ensuring references are not accidentally mixed
        valid_passages: List[EvidencePassage] = []
        for p in pair.evidence_passages:
            # Check reference consistency: do not mix passages from unrelated references
            if pair.reference_id and p.reference_id and p.reference_id != pair.reference_id and p.reference_id not in pair.all_reference_ids:
                continue
            if p.source_type != EvidenceAvailabilityEnum.UNAVAILABLE and p.evidence_text and p.evidence_text.strip():
                valid_passages.append(p)

        if not valid_passages:
            # All provided passages were unavailable or empty
            primary = pair.evidence_passages[0]
            is_ret = pair.is_retracted
            return VerificationResultItem(
                claim_id=pair.claim_id,
                evidence_id=primary.evidence_id,
                reference_id=pair.reference_id or primary.reference_id,
                citation_key=pair.citation_key or primary.citation_key,
                all_reference_ids=pair.all_reference_ids or ([pair.reference_id] if pair.reference_id else []),
                verdict=VerdictEnum.INSUFFICIENT_EVIDENCE,
                verdict_strength=0.0,
                retrieval_match=0.0,
                evidence_completeness=EvidenceAvailabilityEnum.UNAVAILABLE,
                explanation="Cited source text is unavailable or empty; logical verification abstained.",
                is_retracted_source=is_ret,
                retraction_warning=pair.retraction_notice if is_ret else None,
                contradiction_type="retracted_source" if is_ret else None,
                needs_human_review=is_ret,
                verification_method="abstention",
                fallback_reason="abstention",
                warnings=warnings,
            )

        # Determine evidence completeness across passages
        has_full_text = any(p.source_type == EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE for p in valid_passages)
        is_abstract_only = not has_full_text and any(p.source_type == EvidenceAvailabilityEnum.ABSTRACT_ONLY for p in valid_passages)
        overall_completeness = EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE if has_full_text else (
            EvidenceAvailabilityEnum.ABSTRACT_ONLY if is_abstract_only else EvidenceAvailabilityEnum.UNAVAILABLE
        )

        if is_abstract_only:
            warnings.append("Verification based on abstract only; full text was not accessible.")

        # Highest retrieval score passage is primary for provenance
        primary_passage = max(valid_passages, key=lambda p: p.retrieval_score or 0.0)
        retrieval_match = max(0.0, min(1.0, primary_passage.retrieval_score or _compute_token_overlap(pair.claim_text, primary_passage.evidence_text)))

        # 2. Multi-Passage Deterministic Evaluation
        passage_provenance_notes: List[str] = []
        passage_scope_statuses: List[str] = []
        passage_overlaps: List[float] = []
        contradicting_passages: List[str] = []

        # Joint numerical tracking across passages
        verified_claim_numbers = set()
        num_mismatch_details = []

        for cn in pair.numerical_values:
            for p in valid_passages:
                cn_res = check_numerical_consistency([cn], p.evidence_text, p.source_type.value)
                if cn_res.status in ("exact_match", "range_containment", "compatible_inequality"):
                    verified_claim_numbers.add(cn)
                    break
                elif cn_res.status == "mismatch":
                    num_mismatch_details.append(cn_res.details)

        for p in valid_passages:
            sec_info = p.section_title or "Text"
            pg_info = f"p.{p.page_number}" if p.page_number is not None else ""
            pass_label = f"Passage [{p.evidence_id}] ({sec_info}{' ' + pg_info if pg_info else ''})".strip()

            p_num = check_numerical_consistency(pair.numerical_values, p.evidence_text, p.source_type.value)
            if p_num.status == "mismatch":
                contradicting_passages.append(f"{pass_label}: numerical conflict ({p_num.details})")

            # Scope check on this passage
            p_scope = audit_scope(pair.claim_text, p.evidence_text, pair.qualifiers, pair.experimental_conditions)
            passage_scope_statuses.append(p_scope.status)
            if p_scope.status == "context_mismatch":
                contradicting_passages.append(f"{pass_label}: context mismatch ({p_scope.details})")

            # Lexical overlap on this passage
            p_overlap = _compute_token_overlap(pair.claim_text, p.evidence_text)
            passage_overlaps.append(p_overlap)

            passage_provenance_notes.append(
                f"{pass_label}: overlap={p_overlap:.2f}, num={p_num.status}, scope={p_scope.status}"
            )

        # Aggregate numerical check across passages
        if pair.numerical_values:
            if num_mismatch_details:
                aggregate_num_status = "mismatch"
                aggregate_num_details = "; ".join(num_mismatch_details)
            elif len(verified_claim_numbers) == len(pair.numerical_values):
                aggregate_num_status = "exact_match"
                aggregate_num_details = f"All {len(pair.numerical_values)} numerical values jointly corroborated across passages."
            elif len(verified_claim_numbers) > 0:
                aggregate_num_status = "exact_match"
                aggregate_num_details = f"{len(verified_claim_numbers)}/{len(pair.numerical_values)} numerical values corroborated across passages."
            else:
                aggregate_num_status = "missing_in_source"
                aggregate_num_details = f"Numerical values ({', '.join(pair.numerical_values)}) not located in evaluated passages."
        else:
            aggregate_num_status = "not_applicable"
            aggregate_num_details = "No numerical claims present."

        # Aggregate scope across passages:
        if "context_mismatch" in passage_scope_statuses:
            aggregate_scope_status = "context_mismatch"
            aggregate_scope_details = "Context mismatch identified in at least one cited evidence passage."
        elif all(s == "overgeneralized" for s in passage_scope_statuses):
            aggregate_scope_status = "overgeneralized"
            aggregate_scope_details = "Claim overgeneralizes findings; all cited passages are restricted to preclinical/correlational scope."
        elif any(s == "consistent" for s in passage_scope_statuses):
            aggregate_scope_status = "consistent"
            aggregate_scope_details = "Scope and experimental conditions corroborated across evaluated passages."
        elif any(s == "hedged" for s in passage_scope_statuses):
            aggregate_scope_status = "hedged"
            aggregate_scope_details = "Claim preserves scientific qualifiers and hedging present in evidence."
        else:
            aggregate_scope_status = passage_scope_statuses[0] if passage_scope_statuses else "consistent"
            aggregate_scope_details = "Scope evaluated across passages."

        max_overlap = max(passage_overlaps) if passage_overlaps else 0.0
        avg_overlap = sum(passage_overlaps) / len(passage_overlaps) if passage_overlaps else 0.0

        # Construct distinct, non-concatenated multi-passage text for LLM
        formatted_passages_for_llm = "\n\n".join(
            f"--- PASSAGE {i+1} [ID: {p.evidence_id}] (Section: {p.section_title or 'General'}, Page: {p.page_number if p.page_number is not None else 'N/A'}) ---\n\"{p.evidence_text}\""
            for i, p in enumerate(valid_passages)
        )

        # 3. LLM NLI Verification (Gemini)
        llm_assessment = await self.llm_verifier.verify_pair(
            claim_text=pair.claim_text,
            evidence_text=formatted_passages_for_llm,
            citation_key=pair.citation_key,
            section_name=pair.section_name,
            reference_id=pair.reference_id,
            reference_title=pair.reference_title,
            reference_doi=pair.reference_doi,
            reference_authors=pair.reference_authors,
            reference_year=pair.reference_year,
            claim_numbers=pair.numerical_values,
            claim_qualifiers=pair.qualifiers,
            claim_conditions=pair.experimental_conditions,
            evidence_completeness=overall_completeness.value,
            is_retracted=pair.is_retracted,
            retraction_notice=pair.retraction_notice,
            has_newer_conflicting=pair.has_newer_conflicting_evidence,
            newer_conflicting_summary=pair.newer_conflicting_summary,
            numeric_status=aggregate_num_status,
            scope_status=aggregate_scope_status,
        )

        # 4. Synthesize Verdict & Verify Quotes
        ai_verdict: Optional[VerdictEnum] = None
        override_reason: Optional[str] = None
        supporting_quotes: List[str] = []
        fallback_reason: Optional[str] = None

        if llm_assessment:
            raw_verdict = llm_assessment.verdict.lower().strip()
            ai_verdict = VerdictEnum(raw_verdict)
            verdict = ai_verdict
            verdict_strength = llm_assessment.verdict_strength
            explanation = llm_assessment.reasoning
            contradiction_type = llm_assessment.contradiction_type
            verification_method = "gemini_assisted"
            fallback_reason = None
            model_name = llm_assessment.model_name
            supporting_quotes = llm_assessment.supporting_quotes or []

            # Check proposed quotes with strengthened quote guard
            candidate_quote = supporting_quotes[0] if supporting_quotes else None
            q_res = verify_quotation(candidate_quote, valid_passages, pair.claim_text)
            quote_verified = q_res.is_verified

            if llm_assessment.warnings:
                warnings.extend(llm_assessment.warnings)
        else:
            # Deterministic Rule-Based Fallback
            verification_method = "deterministic_fallback"
            fallback_reason = getattr(self.llm_verifier, "last_failure_reason", None) or "provider_error"
            model_name = getattr(self.llm_verifier.llm, "model", "gemini-3.5-flash-lite")

            # Validate quotes against manuscript text
            q_res = verify_quotation(None, valid_passages, pair.claim_text)
            quote_verified = q_res.is_verified

            if contradicting_passages or aggregate_num_status == "mismatch":
                verdict = VerdictEnum.CONTRADICTORY
                verdict_strength = 0.85
                contradiction_type = "direct_refutation"
                explanation = f"Contradiction identified in cited evidence: {'; '.join(contradicting_passages or [aggregate_num_details])}"
            elif aggregate_scope_status == "context_mismatch":
                verdict = VerdictEnum.CONTRADICTORY
                verdict_strength = 0.80
                contradiction_type = "opposite_effect"
                explanation = f"Context mismatch between claim and evidence: {aggregate_scope_details}"
            elif is_abstract_only:
                # Conservative abstract-only fallback
                if aggregate_scope_status == "overgeneralized":
                    verdict = VerdictEnum.PARTIALLY_SUPPORTED
                    verdict_strength = 0.65
                    contradiction_type = None
                    explanation = f"Abstract partially supports claim assertions, but claim overgeneralizes scope: {aggregate_scope_details}"
                elif aggregate_num_status == "missing_in_source" and pair.numerical_values:
                    verdict = VerdictEnum.INSUFFICIENT_EVIDENCE
                    verdict_strength = 0.30
                    contradiction_type = None
                    explanation = f"Abstract lacks specific quantitative figures ({', '.join(pair.numerical_values)}); full text required."
                elif max_overlap < 0.25:
                    verdict = VerdictEnum.INSUFFICIENT_EVIDENCE
                    verdict_strength = 0.25
                    contradiction_type = None
                    explanation = "Abstract-only evidence does not contain sufficient detail or lexical overlap to verify the claim; full text required."
                elif max_overlap >= 0.60 and (aggregate_num_status in ("exact_match", "not_applicable")):
                    verdict = VerdictEnum.SUPPORTED
                    verdict_strength = 0.75
                    contradiction_type = None
                    explanation = "Abstract passage directly corroborates the asserted finding."
                else:
                    verdict = VerdictEnum.PARTIALLY_SUPPORTED
                    verdict_strength = 0.60
                    contradiction_type = None
                    explanation = f"Abstract partially supports claim assertions: {aggregate_scope_details}"
            else:
                # Full-text rule-based fallback
                if aggregate_scope_status == "overgeneralized":
                    verdict = VerdictEnum.PARTIALLY_SUPPORTED
                    verdict_strength = 0.75
                    contradiction_type = None
                    explanation = f"Findings are partially supported, but claim overgeneralizes scope: {aggregate_scope_details}"
                elif max_overlap >= 0.55 or (len(valid_passages) > 1 and avg_overlap >= 0.40):
                    verdict = VerdictEnum.SUPPORTED
                    verdict_strength = 0.80
                    contradiction_type = None
                    explanation = "Key concepts, entities, and relationships are corroborated across cited evidence passages."
                elif max_overlap >= 0.25:
                    verdict = VerdictEnum.PARTIALLY_SUPPORTED
                    verdict_strength = 0.60
                    contradiction_type = None
                    explanation = "Cited passages discuss related concepts but provide only partial corroboration."
                else:
                    verdict = VerdictEnum.UNSUPPORTED
                    verdict_strength = 0.65
                    contradiction_type = None
                    explanation = "Retrieved full-text evidence passages do not corroborate the stated findings or claims."

        # 5. Apply Mandatory Scientific Safety Overrides (Auditable Order of Operations)
        needs_human_review = False
        is_retracted_source = pair.is_retracted

        # Rule 1 — Retraction Policy
        if pair.is_retracted:
            is_retracted_source = True
            needs_human_review = True
            contradiction_type = "retracted_source"
            retraction_note = pair.retraction_notice or "Source publication has been retracted by publisher."
            warnings.append(f"RETRACTED SOURCE WARNING: {retraction_note}")

            if verdict not in (VerdictEnum.CONTRADICTORY, VerdictEnum.POTENTIALLY_OUTDATED):
                if ai_verdict and ai_verdict != VerdictEnum.INSUFFICIENT_EVIDENCE:
                    override_reason = f"Retracted source override: AI assigned '{ai_verdict.value}', but retracted sources require explicit human review."
                verdict = VerdictEnum.INSUFFICIENT_EVIDENCE
                verdict_strength = 0.20
                explanation = (
                    f"Verification abstained: {retraction_note} Retracted sources cannot reliably support "
                    "claims without explicit human review."
                )

        # Rule 2 — DOI/Title Identity Mismatch
        if pair.doi_title_mismatch:
            needs_human_review = True
            mismatch_note = "Resolved DOI title diverges from cited bibliography entry."
            warnings.append(f"DOI_TITLE_MISMATCH: {mismatch_note}")
            if verdict == VerdictEnum.SUPPORTED:
                if ai_verdict:
                    override_reason = "DOI/Title identity mismatch: cited DOI belongs to a different paper."
                verdict = VerdictEnum.UNSUPPORTED
                verdict_strength = 0.65
                explanation = f"Verification downgraded: {mismatch_note} Evidence cannot be attributed to cited reference."

        # Rule 3 — Numerical Conflict Consistency
        if aggregate_num_status == "mismatch" and verdict == VerdictEnum.SUPPORTED:
            if ai_verdict:
                override_reason = f"Numerical mismatch override: AI assigned supported, but quantitative figures conflict ({aggregate_num_details})."
            verdict = VerdictEnum.PARTIALLY_SUPPORTED
            verdict_strength = min(verdict_strength, 0.60)
            explanation = f"Qualitative topic matches, but quantitative values mismatch: {aggregate_num_details}. {explanation}"

        # Rule 4 — Scope Overgeneralization Consistency
        if aggregate_scope_status == "overgeneralized" and verdict == VerdictEnum.SUPPORTED:
            if ai_verdict:
                override_reason = f"Scope overgeneralization override: claim overgeneralizes evidence scope ({aggregate_scope_details})."
            verdict = VerdictEnum.PARTIALLY_SUPPORTED
            verdict_strength = min(verdict_strength, 0.70)
            explanation = f"Partially supported: claim overgeneralizes evidence scope. {aggregate_scope_details}. {explanation}"

        # Rule 5 — Outdatedness Policy
        if pair.has_newer_conflicting_evidence:
            verdict = VerdictEnum.POTENTIALLY_OUTDATED
            verdict_strength = max(verdict_strength, 0.80)
            explanation = (
                f"Potentially outdated: superseded or challenged by newer evidence. "
                f"{pair.newer_conflicting_summary or ''} {explanation}".strip()
            )

        # Rule 6 — Abstract-Only Limitations
        if is_abstract_only:
            if aggregate_num_status == "missing_in_source" and verdict == VerdictEnum.UNSUPPORTED:
                verdict = VerdictEnum.INSUFFICIENT_EVIDENCE
                explanation = f"Abstract lacks specific quantitative/methodological details; full text required. {explanation}"

        # Include passage provenance notes in explanation for full audit traceability
        if passage_provenance_notes:
            explanation = f"{explanation} | Evaluated Passages: [{'; '.join(passage_provenance_notes)}]"

        return VerificationResultItem(
            claim_id=pair.claim_id,
            evidence_id=primary_passage.evidence_id,
            reference_id=pair.reference_id or primary_passage.reference_id,
            citation_key=pair.citation_key or primary_passage.citation_key,
            all_reference_ids=pair.all_reference_ids or ([pair.reference_id] if pair.reference_id else []),
            verdict=verdict,
            verdict_strength=verdict_strength,
            retrieval_match=retrieval_match,
            evidence_completeness=overall_completeness,
            explanation=explanation,
            quote_verified=quote_verified,
            numerical_consistency=aggregate_num_status,
            numerical_details=aggregate_num_details,
            scope_audit=aggregate_scope_status,
            scope_details=aggregate_scope_details,
            is_retracted_source=is_retracted_source,
            retraction_warning=pair.retraction_notice if is_retracted_source else None,
            contradiction_type=contradiction_type,
            needs_human_review=needs_human_review,
            ai_verdict=ai_verdict.value if ai_verdict else None,
            override_reason=override_reason,
            supporting_quotes=supporting_quotes,
            model_name=model_name,
            verification_method=verification_method,
            fallback_reason=fallback_reason,
            warnings=warnings,
        )

    async def verify_all(self, pairs: List[ClaimEvidencePair]) -> List[VerificationResultItem]:
        """Verify a list of claim-evidence pairs."""
        results = []
        for pair in pairs:
            res = await self.verify_pair(pair)
            results.append(res)
        return results
