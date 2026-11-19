"""LLM-based Natural Language Inference (NLI) and scientific verification service."""

import logging
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.core.llm import BaseLLMClient, get_llm_client
from app.models.schemas import VerdictEnum

logger = logging.getLogger("citeverify.s6.llm")


class LLMVerificationAssessment(BaseModel):
    """Pydantic schema for structured LLM verification assessment."""
    verdict: str = Field(..., description="One of: supported, partially_supported, unsupported, contradictory, potentially_outdated, insufficient_evidence")
    verdict_strength: float = Field(..., ge=0.0, le=1.0, description="Confidence in entailment assessment")
    explanation: str = Field(..., description="Step-by-step scientific justification")
    quote_verified: bool = Field(default=False, description="True if evidence contains verbatim supporting phrasing")
    contradiction_type: Optional[str] = Field(default=None, description="direct_refutation, opposite_effect, retracted_source, or null")
    warnings: List[str] = Field(default_factory=list)


VERIFICATION_SYSTEM_PROMPT = """You are an expert scientific verification auditor evaluating whether a cited evidence passage logically entails, refutes, or fails to support an extracted scientific claim.

CRITICAL REASONING PROTOCOLS:
1. Reason strictly from the provided cited evidence text. Do NOT hallucinate external evidence.
2. Choose exactly one of the 6 standardized verdicts:
   - "supported": The passage directly and unambiguously entails the claim's core findings, conditions, and numbers.
   - "partially_supported": The passage supports part of the claim, or the claim overgeneralizes a specific finding, or minor conditions differ.
   - "unsupported": The passage discusses related topics but does NOT contain the asserted findings, mechanisms, or numbers.
   - "contradictory": The passage directly refutes the claim or establishes an opposite effect under comparable conditions.
   - "potentially_outdated": The passage is superseded by newer conflicting scientific findings provided in the context.
   - "insufficient_evidence": The passage is incomplete, abstract-only without needed detail, or lacks substance to determine entailment.
3. Abstract-only rule: If evidence is "abstract_only", abstain from assuming missing data implies contradiction. Disclose limitations explicitly.
4. Retraction rule: A retracted source alone does not automatically make findings logically contradictory unless evidence directly refutes the claim. If not refuted, use potentially_outdated or insufficient_evidence with a retraction notice.
5. Quote verification: Mark quote_verified=true ONLY if the core assertion exists verbatim or near-verbatim in the passage.
6. Return structured JSON conforming strictly to the requested schema.
"""


class LLMClaimVerifier:
    """Manages LLM NLI verification calls with structured schema and graceful retry/fallback."""

    def __init__(self, llm_client: Optional[BaseLLMClient] = None):
        self.llm = llm_client or get_llm_client()

    async def verify_pair(
        self,
        claim_text: str,
        evidence_text: str,
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
        if not evidence_text or not evidence_text.strip():
            return None

        # Build prompt
        prompt = f"""Evaluate the logical relationship between this Scientific Claim and the Cited Evidence Passage:

--- CLAIM TO VERIFY ---
Claim Text: {claim_text}
Numerical Values: {', '.join(claim_numbers or ['None'])}
Qualifiers: {', '.join(claim_qualifiers or ['None'])}
Experimental Conditions: {claim_conditions or 'None specified'}

--- CITED EVIDENCE PASSAGE ---
Completeness: {evidence_completeness}
Evidence Text:
\"\"\"{evidence_text}\"\"\"

--- DETERMINISTIC AUDIT FINDINGS ---
Numerical Consistency Status: {numeric_status or 'Not audited'}
Scope & Population Audit: {scope_status or 'Not audited'}
Retraction Status: {'RETRACTED SOURCE' if is_retracted else 'Normal'}
{f'Retraction Details: {retraction_notice}' if is_retracted and retraction_notice else ''}
{f'Newer Conflicting Evidence: {newer_conflicting_summary}' if has_newer_conflicting and newer_conflicting_summary else ''}

Evaluate logical entailment step-by-step and produce your structured assessment.
"""
        schema = LLMVerificationAssessment.model_json_schema()

        for attempt in range(max_retries):
            try:
                res = await self.llm.generate_structured(
                    prompt=prompt,
                    response_schema=schema,
                    system_instruction=VERIFICATION_SYSTEM_PROMPT,
                    temperature=0.1,
                )
                if isinstance(res, dict) and "verdict" in res and res.get("status") != "skeleton_placeholder":
                    # Normalize verdict string to valid enum if slight case deviation
                    raw_verdict = str(res["verdict"]).lower().strip()
                    valid_verdicts = {v.value for v in VerdictEnum}
                    if raw_verdict in valid_verdicts:
                        res["verdict"] = raw_verdict
                        return LLMVerificationAssessment.model_validate(res)
                    else:
                        logger.warning(f"LLM returned invalid verdict value: {raw_verdict}")
                else:
                    logger.debug(f"LLM returned placeholder or non-dictionary response: {res}")
                    return None
            except Exception as e:
                logger.warning(f"LLM verification attempt {attempt + 1} failed: {e}")
                if attempt == max_retries - 1:
                    logger.info("Falling back to deterministic rule-based verification.")
                    return None

        return None
