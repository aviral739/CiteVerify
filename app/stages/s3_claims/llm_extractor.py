"""LLM enhancement service for S3 claim extraction and structured JSON validation."""

import logging
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.core.llm import BaseLLMClient, get_llm_client
from app.stages.s3_claims.feature_extractor import ClaimCategoryEnum

logger = logging.getLogger("citeverify.s3.llm")


class LLMDecomposedClaim(BaseModel):
    claim_text: str
    category: str = "empirical"
    citation_keys: List[str] = Field(default_factory=list)
    numerical_values: List[str] = Field(default_factory=list)
    entities: List[str] = Field(default_factory=list)
    experimental_conditions: Optional[str] = None


class LLMClaimExtractionResponse(BaseModel):
    claims: List[LLMDecomposedClaim] = Field(default_factory=list)
    summary: Optional[str] = None


CLAIM_EXTRACTION_SYSTEM_PROMPT = """You are an expert scientific claim extraction system for scholarly literature verification.
Your task is to identify verifiable empirical, statistical, comparative, or quantitative claims from academic sentences.
Extract exact numerical values, entities, and conditions.
Never fabricate citations or data not present in the input text."""


class LLMClaimExtractor:
    """Handles structured LLM-enhanced extraction with bounded retries and safe fallback."""

    def __init__(self, llm_client: Optional[BaseLLMClient] = None):
        self.llm = llm_client or get_llm_client()

    async def refine_claims(
        self,
        sentences: List[Dict[str, Any]],
        max_retries: int = 2
    ) -> Optional[List[Dict[str, Any]]]:
        """Send chunk of candidate sentences to LLM for precise decomposition and feature extraction."""
        if not sentences:
            return None

        # Build prompt
        formatted_sents = "\n".join(
            f"[{i}] Section: {s.get('section', 'General')} | Text: \"{s.get('text', '')}\""
            for i, s in enumerate(sentences[:10])  # keep bounded chunk size
        )

        user_prompt = f"""Extract and decompose key scientific claims from these academic sentences:

{formatted_sents}

For each claim:
- Specify exact claim text.
- Classify into: empirical, statistical, comparative, causal, methodological, literature, quantitative, other.
- Extract citation markers (e.g. [1], (Smith, 2020)).
- List numerical values and experimental conditions.
"""
        schema = LLMClaimExtractionResponse.model_json_schema()

        for attempt in range(max_retries):
            try:
                res = await self.llm.generate_structured(
                    prompt=user_prompt,
                    response_schema=schema,
                    system_instruction=CLAIM_EXTRACTION_SYSTEM_PROMPT,
                    temperature=0.1,
                )
                if isinstance(res, dict) and "claims" in res and isinstance(res["claims"], list):
                    # Validate structured response
                    validated = LLMClaimExtractionResponse.model_validate(res)
                    return [c.model_dump() for c in validated.claims]
                else:
                    logger.debug(f"LLM returned mock or unstructured response: {res}")
                    return None
            except Exception as e:
                logger.warning(f"LLM claim extraction attempt {attempt + 1} failed: {e}")
                if attempt == max_retries - 1:
                    logger.info("Falling back to deterministic claim extraction.")
                    return None

        return None
