"""Core verification engine for S6 Claim Verification.

Coordinates deterministic numerical checking, scope auditing, source status auditing,
and LLM Natural Language Inference (NLI) with robust rule-based fallback.
"""

import logging
import re
from typing import List, Optional, Tuple
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


def _check_verbatim_quote(claim: str, evidence: str) -> bool:
    """Check if significant verbatim sequences from claim appear in evidence."""
    c_lower = claim.lower()
    e_lower = evidence.lower()

    # 1. Check for quoted substrings in claim
    quotes = re.findall(r'["\']([^"\']{6,})["\']', claim)
    for q in quotes:
        if q.lower().strip() in e_lower:
            return True

    # 2. Check for 3+ consecutive words
    words = re.findall(r"\b\w+\b", c_lower)
    if len(words) < 3:
        return claim.lower().strip() in e_lower if words else False

    for i in range(len(words) - 2):
        phrase = " ".join(words[i : i + 3])
        if phrase in e_lower:
            return True

    return False


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
        passage_quotes: List[bool] = []
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

            # Quote verification on this passage
            p_quote = _check_verbatim_quote(pair.claim_text, p.evidence_text)
            passage_quotes.append(p_quote)

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

        quote_verified = any(passage_quotes)
        max_overlap = max(passage_overlaps) if passage_overlaps else 0.0
        avg_overlap = sum(passage_overlaps) / len(passage_overlaps) if passage_overlaps else 0.0

        # Construct distinct, non-concatenated multi-passage text for LLM
        formatted_passages_for_llm = "\n\n".join(
            f"--- PASSAGE {i+1} [ID: {p.evidence_id}] (Section: {p.section_title or 'General'}, Page: {p.page_number if p.page_number is not None else 'N/A'}) ---\n\"{p.evidence_text}\""
            for i, p in enumerate(valid_passages)
        )

        # 3. LLM NLI Verification
        llm_assessment = await self.llm_verifier.verify_pair(
            claim_text=pair.claim_text,
            evidence_text=formatted_passages_for_llm,
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

        # 4. Synthesize Verdict (LLM or Rule-Based Fallback)
        if llm_assessment:
            raw_verdict = llm_assessment.verdict.lower().strip()
            verdict = VerdictEnum(raw_verdict)
            verdict_strength = llm_assessment.verdict_strength
            explanation = llm_assessment.explanation
            contradiction_type = llm_assessment.contradiction_type
            quote_verified = quote_verified or llm_assessment.quote_verified
            verification_method = "llm_nli"
            if llm_assessment.warnings:
                warnings.extend(llm_assessment.warnings)
        else:
            # Deterministic Rule-Based Fallback
            verification_method = "deterministic_rule_based"

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
                # F-04: Conservative abstract-only fallback
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
                    # Low lexical overlap alone must NOT establish unsupported for abstract
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

        # 5. Apply Mandatory Scientific Safety Overrides
        needs_human_review = False
        is_retracted_source = pair.is_retracted

        # A. Retraction Policy
        if pair.is_retracted:
            is_retracted_source = True
            needs_human_review = True
            contradiction_type = "retracted_source"
            retraction_note = pair.retraction_notice or "Source publication has been retracted by publisher."
            warnings.append(f"RETRACTED SOURCE WARNING: {retraction_note}")

            # Do NOT automatically classify as contradictory unless evidence actually establishes opposing finding
            if verdict not in (VerdictEnum.CONTRADICTORY, VerdictEnum.POTENTIALLY_OUTDATED):
                verdict = VerdictEnum.INSUFFICIENT_EVIDENCE
                verdict_strength = 0.2
                explanation = (
                    f"Verification abstained: {retraction_note} Retracted sources cannot reliably support "
                    "claims without explicit human review."
                )

        # B. Outdatedness Policy (Requires identifiable newer conflicting evidence)
        if pair.has_newer_conflicting_evidence:
            verdict = VerdictEnum.POTENTIALLY_OUTDATED
            verdict_strength = max(verdict_strength, 0.80)
            explanation = (
                f"Potentially outdated: superseded or challenged by newer evidence. "
                f"{pair.newer_conflicting_summary or ''} {explanation}".strip()
            )

        # C. Numerical Conflict Consistency
        if aggregate_num_status == "mismatch" and verdict == VerdictEnum.SUPPORTED:
            verdict = VerdictEnum.PARTIALLY_SUPPORTED
            verdict_strength = min(verdict_strength, 0.60)
            explanation = f"Qualitative topic matches, but quantitative values mismatch: {aggregate_num_details}. {explanation}"

        # D. Scope Overgeneralization Consistency
        if aggregate_scope_status == "overgeneralized" and verdict == VerdictEnum.SUPPORTED:
            verdict = VerdictEnum.PARTIALLY_SUPPORTED
            verdict_strength = min(verdict_strength, 0.70)
            explanation = f"Partially supported: claim overgeneralizes evidence scope. {aggregate_scope_details}. {explanation}"

        # E. Abstract-Only Limitations
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
            model_name="gemini-1.5-pro",
            verification_method=verification_method,
            warnings=warnings,
        )

    async def verify_all(self, pairs: List[ClaimEvidencePair]) -> List[VerificationResultItem]:
        """Verify a list of claim-evidence pairs."""
        results = []
        for pair in pairs:
            res = await self.verify_pair(pair)
            results.append(res)
        return results
