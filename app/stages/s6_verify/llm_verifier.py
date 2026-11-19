"""LLM-based Natural Language Inference (NLI) and scientific verification service.

Constructs grounded verification requests for Gemini passing claim, reference,
and retrieved multi-passage evidence. Parses structured responses, extracts
supporting quotations, and reports verification provenance and model status.
"""

import logging
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.core.llm import BaseLLMClient, get_llm_client
from app.models.schemas import VerdictEnum

logger = logging.getLogger("citeverify.s6.llm")


class LLMVerificationAssessment(BaseModel):
    """Structured response schema returned by Gemini semantic verification."""

    verdict: str = Field(
        ...,
        description="One of: supported, partially_supported, unsupported, contradictory, potentially_outdated, insufficient_evidence",
    )
    verdict_strength: float = Field(..., ge=0.0, le=1.0, description="Confidence in entailment assessment")
    reasoning: str = Field(..., description="Step-by-step scientific justification")
    supporting_quotes: List[str] = Field(default_factory=list, description="Verbatim phrases from evidence supporting claim")
    evidence_passage_ids: List[str] = Field(default_factory=list, description="IDs of passages that support or refute the claim")
    numerical_consistency: str = Field(
        default="not_applicable",
        description="One of: exact_match, mismatch, not_applicable, missing_in_source",
    )
    scope_consistency: str = Field(
        default="consistent",
        description="One of: consistent, overgeneralized, context_mismatch, hedged",
    )
    contradiction_detected: bool = Field(default=False, description="True if evidence directly refutes the claim")
    uncertainty: float = Field(default=0.0, ge=0.0, le=1.0, description="Estimated uncertainty in assessment")
    limitations: Optional[str] = Field(default=None, description="Disclosed limitations or missing data")
    contradiction_type: Optional[str] = Field(default=None, description="direct_refutation, opposite_effect, retracted_source, or null")
    warnings: List[str] = Field(default_factory=list)

    # Invocation provenance metadata
    invocation_status: str = Field(default="success", description="success, fallback, or error")
    model_name: str = Field(default="gemini-2.5-flash-lite", description="Actual model utilized")

    @property
    def explanation(self) -> str:
        """Compatibility property mapping reasoning to legacy explanation field."""
        return self.reasoning

    @property
    def quote_verified(self) -> bool:
        """Compatibility property checking if any non-empty supporting quotes exist."""
        return bool(self.supporting_quotes)


VERIFICATION_SYSTEM_PROMPT = """You are CiteVerify AI, a senior scientific verification auditor evaluating whether cited literature genuinely supports assertions made in an academic manuscript.

CRITICAL AUDIT PROTOCOLS:
1. Reason strictly from the provided cited evidence passages. Do NOT hallucinate external facts or invent quotations.
2. Choose exactly one of the 6 standardized verdicts:
   - "supported": The passage directly, unambiguously, and specifically entails the claim's core findings, conditions, and numbers.
   - "partially_supported": The passage supports part of the claim, or the claim overgeneralizes a specific finding, or minor conditions differ.
   - "unsupported": The passage discusses related topics but does NOT contain the asserted findings, mechanisms, or quantitative results.
   - "contradictory": The passage directly refutes the claim or establishes an opposite effect under comparable conditions.
   - "potentially_outdated": The passage is superseded or challenged by newer conflicting scientific findings provided in context.
   - "insufficient_evidence": The passage is incomplete, abstract-only without needed detail, or lacks substance to determine entailment.
3. Distinguish a paper's OWN findings from findings it merely cites as background or related work.
4. Numerical & Methodological Rigor: Scrutinize numbers, units, percentages, denominators, and experimental conditions.
5. Overgeneralization Detection: Flag claims generalizing from specific model sizes, domains, or species to broad universal conclusions.
6. Negative Evidence: Treat absence of evidence as "insufficient_evidence" or "unsupported", never as proof of "contradictory" unless an opposing result is shown.
7. Quotation Grounding: Every string in 'supporting_quotes' must be an exact verbatim substring from the provided evidence text. If no exact phrase is present, return an empty list.
8. Output strictly valid JSON conforming to the requested schema.
"""


class LLMClaimVerifier:
    """Manages LLM NLI verification calls with structured schema and graceful retry/fallback."""

    def __init__(self, llm_client: Optional[BaseLLMClient] = None):
        self.llm = llm_client or get_llm_client()
        self.last_failure_reason: Optional[str] = None

    async def verify_pair(
        self,
        claim_text: str,
        evidence_text: str,
        citation_key: Optional[str] = None,
        section_name: Optional[str] = None,
        reference_id: Optional[str] = None,
        reference_title: Optional[str] = None,
        reference_doi: Optional[str] = None,
        reference_authors: Optional[str] = None,
        reference_year: Optional[int] = None,
        claim_numbers: Optional[List[str]] = None,
        claim_qualifiers: Optional[List[str]] = None,
        claim_conditions: Optional[str] = None,
        evidence_completeness: str = "full_text_available",
        is_retracted: bool = False,
        retraction_notice: Optional[str] = None,
        has_newer_conflicting: bool = False,
        newer_conflicting_summary: Optional[str] = None,
        numeric_status: Optional[str] = None,
        scope_status: Optional[str] = None,
        max_retries: int = 2,
    ) -> Optional[LLMVerificationAssessment]:
        """Perform structured LLM NLI reasoning on a claim-evidence pair."""
        self.last_failure_reason = None
        if not evidence_text or not evidence_text.strip():
            logger.debug(f"Evidence text empty for claim '{claim_text[:50]}...'; skipping LLM call.")
            self.last_failure_reason = "insufficient_evidence"
            return None

        # Build comprehensive grounded prompt
        prompt = f"""--- MANUSCRIPT CLAIM ---
Claim: {claim_text}
Citation Marker: {citation_key or 'Not specified'}
Section: {section_name or 'General'}
Numerical Values: {', '.join(claim_numbers or ['None'])}
Qualifiers: {', '.join(claim_qualifiers or ['None'])}
Experimental Conditions: {claim_conditions or 'None specified'}

--- CITED REFERENCE METADATA ---
Title: {reference_title or 'Unknown Title'}
DOI: {reference_doi or 'None'}
Authors: {reference_authors or 'Unknown Authors'}
Year: {reference_year or 'Unknown'}
Access Level: {evidence_completeness}
Retraction Status: {'RETRACTED SOURCE' if is_retracted else 'Normal'}
{f'Retraction Details: {retraction_notice}' if is_retracted and retraction_notice else ''}
{f'Newer Conflicting Evidence: {newer_conflicting_summary}' if has_newer_conflicting and newer_conflicting_summary else ''}

--- RETRIEVED EVIDENCE PASSAGES ---
{evidence_text}

--- DETERMINISTIC AUDIT FINDINGS ---
Preliminary Numerical Check: {numeric_status or 'Not audited'}
Preliminary Scope Check: {scope_status or 'Not audited'}

Analyze the relationship between the manuscript claim and the cited evidence passages step-by-step.
Produce your structured verification assessment.
"""
        schema = {
            "type": "object",
            "properties": {
                "verdict": {
                    "type": "string",
                    "enum": [
                        "supported",
                        "partially_supported",
                        "unsupported",
                        "contradictory",
                        "potentially_outdated",
                        "insufficient_evidence",
                    ],
                },
                "verdict_strength": {"type": "number"},
                "reasoning": {"type": "string"},
                "supporting_quotes": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "evidence_passage_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "numerical_consistency": {
                    "type": "string",
                    "enum": ["exact_match", "mismatch", "not_applicable", "missing_in_source"],
                },
                "scope_consistency": {
                    "type": "string",
                    "enum": ["consistent", "overgeneralized", "context_mismatch", "hedged"],
                },
                "contradiction_detected": {"type": "boolean"},
                "uncertainty": {"type": "number"},
                "limitations": {"type": "string"},
                "contradiction_type": {
                    "type": "string",
                    "enum": ["direct_refutation", "opposite_effect", "retracted_source", "none"],
                },
            },
            "required": [
                "verdict",
                "verdict_strength",
                "reasoning",
                "supporting_quotes",
                "evidence_passage_ids",
                "numerical_consistency",
                "scope_consistency",
                "contradiction_detected",
                "uncertainty",
            ],
        }

        try:
            res = await self.llm.generate_structured(
                prompt=prompt,
                response_schema=schema,
                system_instruction=VERIFICATION_SYSTEM_PROMPT,
                temperature=0.1,
            )

            status = res.get("_status") if isinstance(res, dict) else None

            if status == "success" and "verdict" in res:
                raw_verdict = str(res["verdict"]).lower().strip()
                valid_verdicts = {v.value for v in VerdictEnum}
                if raw_verdict in valid_verdicts:
                    res["verdict"] = raw_verdict
                    # Map 'none' to None for contradiction_type
                    if res.get("contradiction_type") == "none":
                        res["contradiction_type"] = None
                    assessment = LLMVerificationAssessment.model_validate(res)
                    assessment.invocation_status = "success"
                    assessment.model_name = res.get("_model", getattr(self.llm, "model", "gemini-3.5-flash-lite"))
                    self.last_failure_reason = None
                    logger.info(
                        f"Gemini verification succeeded for citation '{citation_key}': "
                        f"verdict='{assessment.verdict}' (strength={assessment.verdict_strength})"
                    )
                    return assessment
                else:
                    logger.warning(f"Gemini returned invalid verdict string: '{raw_verdict}'")
                    self.last_failure_reason = "schema_validation_failed"
                    return None
            else:
                failure_reason = (
                    res.get("fallback_reason")
                    or res.get("_status")
                    or "provider_error"
                ) if isinstance(res, dict) else "provider_error"
                # Normalize status strings
                if failure_reason in ("missing_config", "missing_api_key"):
                    self.last_failure_reason = "missing_api_key"
                elif failure_reason in ("provider_failure", "provider_error"):
                    self.last_failure_reason = "provider_error"
                elif failure_reason in (
                    "quota_exceeded", "rate_limited", "timeout", "invalid_model",
                    "invalid_response", "schema_validation_failed", "insufficient_evidence",
                ):
                    self.last_failure_reason = failure_reason
                else:
                    self.last_failure_reason = "provider_error"

                logger.warning(
                    f"Gemini verification unavailable (status={status}, reason={self.last_failure_reason}: {res.get('error') if isinstance(res, dict) else res}); "
                    "activating deterministic rule-based fallback."
                )
                return None

        except Exception as exc:
            logger.warning(f"Exception during LLM verification call: {exc}; falling back to deterministic rules.")
            self.last_failure_reason = "provider_error"
            return None


# Compatibility aliases
GeminiClaimVerifier = LLMClaimVerifier

