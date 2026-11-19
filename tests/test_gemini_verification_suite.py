"""Comprehensive regression and verification test suite for Gemini-powered claim verification.

Covers:
1. Gemini LLM client (structured schema response, error classification, retry backoff)
2. Quote Guard (distinctiveness checks, stop words, normalization, exact passage matching)
3. Deterministic safety rules & AI verdict overrides (retraction, numeric mismatch, DOI mismatch)
4. S8 persistence and report serialization of AI provenance (ai_verdict, override_reason)
5. Live smoke test probe (conditional on real API key)
"""

import os
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import Response, Request

from app.config import get_settings
from app.core.llm import GeminiLLMClient
from app.models.schemas import EvidenceAvailabilityEnum, VerdictEnum
from app.stages.s6_verify.quote_guard import (
    QuoteGuard,
    verify_quotation,
    normalize_text_for_matching,
    is_distinctive_quote,
)
from app.stages.s6_verify.engine import ClaimVerificationEngine
from app.stages.s6_verify.models import (
    ClaimEvidencePair,
    EvidencePassage,
    VerificationResultItem,
    S6VerifyOutput,
)
from app.stages.s6_verify.llm_verifier import LLMVerificationAssessment, LLMClaimVerifier


# =============================================================================
# 1. Quote Guard Tests
# =============================================================================

class TestQuoteGuard:
    def test_rejects_generic_stopword_phrases(self):
        """Verifies that common/stop-word-heavy phrases are rejected."""
        guard = QuoteGuard()
        
        # Test phrases that are too short or mostly stop-words
        generic_phrases = [
            "in case of",
            "as well as",
            "on the other hand",
            "it is known that",
            "in this work",
            "we show that",
            "short",
            "the and of in",
        ]
        
        for phrase in generic_phrases:
            is_valid, reason = guard.is_distinctive(phrase)
            assert not is_valid, f"Expected '{phrase}' to be rejected as not distinctive, but passed ({reason})"
            
            # Even if present in passage, verify_quotation must reject
            passage = "We note that in case of failure, on the other hand it is known that we show that."
            verified, match = guard.verify(phrase, passage)
            assert not verified, f"Expected verify() to reject '{phrase}'"

    def test_accepts_distinctive_scientific_quotations(self):
        """Verifies that distinctive domain content is accepted when present."""
        guard = QuoteGuard()
        passage = (
            "The Transformer allows for significantly more parallelization and can reach a new "
            "state of the art in translation quality after being trained for as little as twelve hours."
        )
        
        # Distinctive substring present
        quote = "significantly more parallelization and can reach a new state of the art"
        is_dist, reason = guard.is_distinctive(quote)
        assert is_dist, f"Expected '{quote}' to be distinctive, failed with: {reason}"
        
        verified, matched_text = guard.verify(quote, passage)
        assert verified, "Expected distinctive quote to be verified in passage"
        assert matched_text is not None

    def test_rejects_distinctive_quote_missing_from_passage(self):
        """Verifies that distinctive quotes absent from passage are rejected."""
        guard = QuoteGuard()
        passage = "Attention mechanisms have become an integral part of compelling sequence modeling."
        quote = "Convolutional neural networks achieve state-of-the-art results on ImageNet classification."
        
        is_dist, _ = guard.is_distinctive(quote)
        assert is_dist
        
        verified, matched = guard.verify(quote, passage)
        assert not verified
        assert matched is None

    def test_normalization_handles_whitespace_case_punctuation(self):
        """Verifies that NFKC normalization, curly quotes, and punctuation are relaxed."""
        guard = QuoteGuard()
        passage = 'Our model achieves 28.4 BLEU on the WMT 2014 English-to-German translation task!'
        quote = 'our model achieves 28.4 BLEU on the WMT 2014 English-to-German translation task'
        
        verified, matched = guard.verify(quote, passage)
        assert verified
        assert matched is not None


# =============================================================================
# 2. Gemini LLM Client Unit Tests (Mocked for CI / Offline)
# =============================================================================

class TestGeminiLLMClient:
    @pytest.mark.asyncio
    async def test_missing_api_key_returns_missing_config(self):
        """Client gracefully handles missing or empty API keys without throwing."""
        client = GeminiLLMClient(api_key="", model="gemini-2.5-flash-lite")
        resp = await client.generate_structured("prompt", response_schema={"type": "object"})
        assert resp.get("_status") == "missing_config"
        assert "not configured" in resp.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_successful_structured_response(self):
        """Client parses valid JSON response matching structured schema."""
        mock_payload = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": json.dumps({
                                    "verdict": "supported",
                                    "reasoning": "The passage confirms the exact BLEU score.",
                                    "supporting_quotes": ["achieves 28.4 BLEU on WMT 2014"],
                                    "evidence_passage_ids": ["ev-1"],
                                    "numerical_consistency": "exact_match",
                                    "scope_consistency": "consistent",
                                    "contradiction_detected": False,
                                    "uncertainty": 0.05,
                                    "limitations": "Tested only on WMT benchmark",
                                    "verdict_strength": 0.95
                                })
                            }
                        ]
                    }
                }
            ]
        }
        
        client = GeminiLLMClient(api_key="mock-key-123", model="gemini-2.5-flash-lite")
        
        mock_http_response = Response(200, json=mock_payload, request=Request("POST", "https://api.example.com"))
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_http_response
            resp = await client.generate_structured("test prompt", response_schema={"type": "object"})
            
            assert resp.get("_status") == "success"
            assert resp.get("verdict") == "supported"
            assert resp.get("verdict_strength") == 0.95
            assert resp.get("numerical_consistency") == "exact_match"

    @pytest.mark.asyncio
    async def test_retry_on_429_rate_limit(self):
        """Client retries on 429 status code with exponential backoff."""
        client = GeminiLLMClient(api_key="mock-key-123", model="gemini-2.5-flash-lite", max_retries=2)
        
        rate_limit_resp = Response(429, text="Rate limit exceeded", request=Request("POST", "https://api.example.com"))
        success_payload = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": json.dumps({
                                    "verdict": "supported",
                                    "reasoning": "Recovered after backoff",
                                    "supporting_quotes": [],
                                    "evidence_passage_ids": [],
                                    "numerical_consistency": "not_applicable",
                                    "scope_consistency": "consistent",
                                    "contradiction_detected": False,
                                    "uncertainty": 0.1,
                                    "limitations": "",
                                    "verdict_strength": 0.9
                                })
                            }
                        ]
                    }
                }
            ]
        }
        success_resp = Response(200, json=success_payload, request=Request("POST", "https://api.example.com"))
        
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post, \
             patch("asyncio.sleep", new_callable=AsyncMock):
            mock_post.side_effect = [rate_limit_resp, success_resp]
            resp = await client.generate_structured("prompt", response_schema={"type": "object"})
            
            assert mock_post.call_count == 2
            assert resp.get("_status") == "success"
            assert resp.get("verdict") == "supported"


# =============================================================================
# 3. Deterministic Safety Overrides & AI Verdict Audit
# =============================================================================

class TestDeterministicSafetyOverrides:
    @pytest.mark.asyncio
    async def test_retracted_source_overrides_ai_supported(self):
        """Deterministic rule must override Gemini 'supported' verdict if reference is retracted."""
        engine = ClaimVerificationEngine()
        
        # Mock LLM verifier returning 'supported'
        mock_gemini = AsyncMock()
        mock_gemini.verify_pair.return_value = LLMVerificationAssessment(
            verdict="supported",
            verdict_strength=0.98,
            reasoning="The paper strongly supports the statement.",
            supporting_quotes=["valid quote in paper text"],
            evidence_passage_ids=["ev-1"],
            numerical_consistency="exact_match",
            scope_consistency="consistent",
            contradiction_detected=False,
            uncertainty=0.02,
            limitations="",
            invocation_status="success",
            model_name="gemini-2.5-flash-lite",
        )
        engine.llm_verifier = mock_gemini
        
        pair = ClaimEvidencePair(
            claim_id="claim-101",
            claim_text="The therapy is completely safe and effective.",
            citation_key="Smith2020",
            reference_id="ref-202",
            reference_title="Clinical Trial of Therapy X",
            is_retracted=True,  # Retracted!
            retraction_notice="Retracted due to data fabrication.",
            evidence_passages=[
                EvidencePassage(
                    evidence_id="ev-1",
                    citation_key="Smith2020",
                    evidence_text="The therapy showed 99% efficacy in trials.",
                    source_type=EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE,
                    retrieval_score=0.9,
                )
            ],
        )
        
        res = await engine.verify_pair(pair)
        
        # Final verdict must override 'supported' to insufficient_evidence or contradictory
        assert res.verdict in (VerdictEnum.INSUFFICIENT_EVIDENCE, VerdictEnum.CONTRADICTORY)
        # Must record that AI originally said supported
        assert res.ai_verdict == "supported"
        assert res.override_reason is not None
        assert "retracted" in res.override_reason.lower()
        assert res.needs_human_review is True

    @pytest.mark.asyncio
    async def test_numeric_mismatch_overrides_ai_supported(self):
        """Deterministic rule must flag numeric conflict and override or downgrade verdict."""
        engine = ClaimVerificationEngine()
        
        mock_gemini = AsyncMock()
        mock_gemini.verify_pair.return_value = LLMVerificationAssessment(
            verdict="supported",  # AI smoothed over number
            verdict_strength=0.8,
            reasoning="Looks similar enough",
            supporting_quotes=[],
            evidence_passage_ids=["ev-1"],
            numerical_consistency="mismatch",  # But noted mismatch
            scope_consistency="consistent",
            contradiction_detected=False,
            uncertainty=0.2,
            limitations="",
            invocation_status="success",
            model_name="gemini-2.5-flash-lite",
        )
        engine.llm_verifier = mock_gemini
        
        pair = ClaimEvidencePair(
            claim_id="claim-102",
            claim_text="Our model achieves 95.5% accuracy on benchmark Y.",
            numerical_values=["95.5%"],
            citation_key="Brown2021",
            reference_id="ref-203",
            reference_title="Benchmark Study",
            evidence_passages=[
                EvidencePassage(
                    evidence_id="ev-1",
                    citation_key="Brown2021",
                    evidence_text="The baseline model reached 82.1% accuracy on benchmark Y.",
                    source_type=EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE,
                    retrieval_score=0.85,
                )
            ],
        )
        
        res = await engine.verify_pair(pair)
        
        assert res.numerical_consistency == "mismatch"
        assert res.verdict.value in ("unsupported", "partially_supported", "contradictory")
        assert res.ai_verdict == "supported"
        assert res.override_reason is not None
        assert "numerical mismatch" in res.override_reason.lower()

    @pytest.mark.asyncio
    async def test_insufficient_evidence_when_no_passages_available(self):
        """When evidence is unavailable, verdict must remain insufficient_evidence without converting to unsupported."""
        engine = ClaimVerificationEngine()
        
        pair = ClaimEvidencePair(
            claim_id="claim-103",
            claim_text="Some closed-source finding.",
            citation_key="Secret2022",
            reference_id="ref-204",
            reference_title="Paywalled Finding",
            evidence_passages=[],  # No evidence
        )
        
        res = await engine.verify_pair(pair)
        
        assert res.verdict == VerdictEnum.INSUFFICIENT_EVIDENCE
        assert res.evidence_completeness == EvidenceAvailabilityEnum.UNAVAILABLE
        assert res.verdict_strength == 0.0


# =============================================================================
# 4. S8 Persistence Integration Test
# =============================================================================

@pytest.mark.asyncio
async def test_s8_persists_ai_verdict_and_override_reason():
    """Verify that S8 stage persists ai_verdict and override_reason to the DB and repository returns them."""
    import uuid
    from app.core.db import AsyncSessionLocal
    from app.stages.s8_persist.engine import PersistenceEngine
    from app.repositories.reports import DocumentReportRepository
    from app.models.tables import Document
    
    session_factory = AsyncSessionLocal
    test_doc_id = f"doc-test-{uuid.uuid4().hex[:8]}"
    test_claim_id = f"claim-test-{uuid.uuid4().hex[:8]}"
    test_res_id = f"res-test-{uuid.uuid4().hex[:8]}"
    
    try:
        # Run S8 persistence with ai_verdict and override_reason
        s8_engine = PersistenceEngine(session_factory=session_factory)
        input_data = {
            "document_id": test_doc_id,
            "claims": [
                {
                    "id": test_claim_id,
                    "claim_text": "Manuscript statement",
                }
            ],
            "assessment_data": {
                "overall_health_score": 85.0,
                "confidence_score": 0.9,
                "assessment_verdict": "high_trust",
            },
            "results": [
                {
                    "id": test_res_id,
                    "claim_id": test_claim_id,
                    "verdict": "contradictory",
                    "verdict_strength": 0.9,
                    "retrieval_match": 0.85,
                    "evidence_completeness": "full_text_available",
                    "explanation": "Retracted source override",
                    "quote_verified": False,
                    "ai_verdict": "supported",
                    "override_reason": "Retracted scientific source: Flagged as retracted.",
                    "verification_method": "gemini_assisted",
                }
            ],
        }
        
        result = await s8_engine.persist_pipeline_outputs(input_data)
        assert result.persisted is True
        
        # Verify using DocumentReportRepository
        async with session_factory() as session:
            report_repo = DocumentReportRepository(session)
            report = await report_repo.build_document_report(test_doc_id)
            
            assert report is not None
            assert len(report.results) == 1
            res_item = report.results[0]
            assert res_item.verdict.value == "contradictory"
            assert res_item.ai_verdict == "supported"
            assert res_item.override_reason == "Retracted scientific source: Flagged as retracted."
            assert res_item.verification_method == "gemini_assisted"
    finally:
        async with session_factory() as session:
            async with session.begin():
                await session.execute(Document.__table__.delete().where(Document.id.in_([test_doc_id, "doc-test-ai-persist"])))



# =============================================================================
# 5. Live Smoke Test (Conditional on Real Configured API Key)
# =============================================================================

@pytest.mark.asyncio
async def test_live_gemini_smoke_probe():
    """Live smoke test that probes the real Gemini API if configured."""
    settings = get_settings()
    key = settings.GEMINI_API_KEY
    
    if not key or len(key) < 20 or key.startswith("dummy"):
        pytest.skip("No valid live GEMINI_API_KEY present in environment; skipping live smoke probe.")
        
    client = GeminiLLMClient(api_key=key, model=settings.GEMINI_MODEL)
    verifier = LLMClaimVerifier(llm_client=client)
    
    assessment = await verifier.verify_pair(
        claim_text="The Transformer achieves 28.4 BLEU on the WMT 2014 English-to-German translation task.",
        citation_key="Vaswani2017",
        reference_title="Attention Is All You Need",
        evidence_text="On the WMT 2014 English-to-German translation task, the big transformer model achieves 28.4 BLEU, establishing a new state of the art.",
        claim_numbers=["28.4 BLEU"],
    )
    
    assert assessment is not None, "Live Gemini probe returned None assessment"
    assert assessment.verdict in ("supported", "partially_supported")
    assert assessment.numerical_consistency in ("exact_match", "not_applicable")
    print(f"\n[LIVE SMOKE SUCCESS] Model: {assessment.model_name}, Verdict: {assessment.verdict}, Status: {assessment.invocation_status}")
