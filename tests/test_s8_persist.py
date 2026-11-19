"""Comprehensive automated test suite for Stage 8: Persistence Engine.

Tests:
1. Successful persistence of all S1–S7 outputs.
2. Correct document/reference/claim relationships.
3. Multiple references associated with a claim.
4. Evidence linked to the correct claim and reference.
5. All six canonical verdicts persisted correctly.
6. Numerical and scope metadata persisted.
7. S7 assessment persisted.
8. Idempotent retry behaviour.
9. Transaction rollback on injected failure.
10. No orphaned or duplicate records.
"""

import pytest
from unittest.mock import AsyncMock, patch
from sqlalchemy import select

from app.models.schemas import EvidenceAvailabilityEnum, VerdictEnum
from app.models.tables import (
    AuditLog,
    Claim,
    Document,
    Evidence,
    Event,
    Job,
    Reference,
    Result,
    Review,
)
from app.stages.s8_persist import (
    PersistenceEngine,
    S8PersistInput,
    S8PersistOutput,
    run_stage_8,
)
from tests.conftest import TestingSessionLocal


@pytest.fixture
def engine():
    return PersistenceEngine(session_factory=TestingSessionLocal)


@pytest.fixture
def sample_pipeline_data():
    """Generates a complete bundle of S1–S7 outputs for a realistic research paper."""
    doc_id = "doc-test-s8-001"
    references = [
        {
            "id": "ref-001",
            "citation_key": "[1]",
            "raw_citation": "Vaswani et al. (2017). Attention Is All You Need. NeurIPS.",
            "resolved_title": "Attention Is All You Need",
            "resolved_doi": "10.48550/arxiv.1706.03762",
            "resolved_year": 2017,
            "resolved_venue": "NeurIPS",
            "resolution_confidence": 0.99,
        },
        {
            "id": "ref-002",
            "citation_key": "[2]",
            "raw_citation": "Devlin et al. (2018). BERT: Pre-training of Deep Bidirectional Transformers.",
            "resolved_title": "BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding",
            "resolved_doi": "10.48550/arxiv.1810.04805",
            "resolved_year": 2018,
            "resolved_venue": "NAACL",
            "resolution_confidence": 0.98,
        },
    ]

    claims = [
        {
            "id": "claim-001",
            "claim_text": "The Transformer architecture replaces recurrent neural networks with multi-head self-attention.",
            "reference_id": "ref-001",
            "citation_key": "[1]",
            "context_sentence": "We introduce the Transformer, a novel neural network architecture based solely on attention mechanisms [1].",
            "section_name": "Introduction",
            "page_number": 1,
            "is_active": True,
        },
        {
            "id": "claim-002",
            "claim_text": "BERT achieves state-of-the-art results on eleven natural language processing tasks.",
            "reference_id": "ref-002",
            "citation_key": "[2]",
            "all_citation_keys": ["[1]", "[2]"],
            "context_sentence": "Bidirectional representation learning significantly improves downstream NLP benchmarks [2].",
            "section_name": "Results",
            "page_number": 4,
            "is_active": True,
        },
    ]

    evidences = [
        {
            "id": "ev-001",
            "reference_id": "ref-001",
            "citation_key": "[1]",
            "evidence_text": "The Transformer is the first transduction model relying entirely on self-attention to compute representations.",
            "section_title": "Abstract",
            "page_number": 1,
            "source_type": "full_text_available",
            "retrieval_score": 0.94,
        },
        {
            "id": "ev-002",
            "reference_id": "ref-002",
            "citation_key": "[2]",
            "evidence_text": "BERT is designed to pre-train deep bidirectional representations from unlabeled text.",
            "section_title": "Abstract",
            "page_number": 1,
            "source_type": "full_text_available",
            "retrieval_score": 0.91,
        },
    ]

    results = [
        {
            "claim_id": "claim-001",
            "evidence_id": "ev-001",
            "verdict": "supported",
            "verdict_strength": 0.96,
            "retrieval_match": 0.92,
            "evidence_completeness": "full_text_available",
            "explanation": "Exact alignment between self-attention definition in cited paper and manuscript claim.",
            "model_name": "gemini-1.5-pro",
        },
        {
            "claim_id": "claim-002",
            "evidence_id": "ev-002",
            "verdict": "partially_supported",
            "verdict_strength": 0.85,
            "retrieval_match": 0.88,
            "evidence_completeness": "full_text_available",
            "explanation": "Supported for GLUE benchmark, but general scope is bounded to specific NLP evaluation suites.",
            "model_name": "gemini-1.5-pro",
        },
    ]

    assessment_data = {
        "overall_health_score": 88.5,
        "summary": {"supported": 1, "partially_supported": 1},
        "assessment_notes": "High methodological rigor with reliable full-text open-access backing.",
    }

    return {
        "document_id": doc_id,
        "document_title": "Comparative Study of Attention Architectures",
        "document_doi": "10.1000/citeverify.test001",
        "document_authors": "Dr. Alice Research, Dr. Bob Scholar",
        "references": references,
        "claims": claims,
        "evidences": evidences,
        "results": results,
        "assessment_data": assessment_data,
        "job_id": "job-test-001",
    }


# ---------------- 1. Successful Persistence of all S1–S7 Outputs ----------------
@pytest.mark.asyncio
async def test_successful_persistence_all_stages(engine, sample_pipeline_data):
    inp = S8PersistInput(**sample_pipeline_data)
    out = await engine.persist_pipeline_outputs(inp)

    assert out.persisted is True
    assert out.status == "completed"
    assert out.persisted_counts["references"] == 2
    assert out.persisted_counts["claims"] == 2
    assert out.persisted_counts["evidences"] == 2
    assert out.persisted_counts["results"] == 2

    # Verify rows in database
    async with TestingSessionLocal() as session:
        doc = (await session.execute(select(Document).where(Document.id == inp.document_id))).scalar_one_or_none()
        assert doc is not None
        assert doc.title == "Comparative Study of Attention Architectures"
        assert doc.status == "completed"

        refs = (await session.execute(select(Reference).where(Reference.document_id == inp.document_id))).scalars().all()
        assert len(refs) == 2

        claims = (await session.execute(select(Claim).where(Claim.document_id == inp.document_id))).scalars().all()
        assert len(claims) == 2

        evs = (await session.execute(select(Evidence))).scalars().all()
        assert len(evs) == 2

        res = (await session.execute(select(Result))).scalars().all()
        assert len(res) == 2

        evts = (await session.execute(select(Event).where(Event.document_id == inp.document_id))).scalars().all()
        assert len(evts) >= 1
        assert evts[0].stage == "s8_persist"

        audits = (await session.execute(select(AuditLog).where(AuditLog.document_id == inp.document_id))).scalars().all()
        assert len(audits) >= 1
        assert audits[0].action == "pipeline_persisted"


# ---------------- 2. Correct Document / Reference / Claim Relationships ----------------
@pytest.mark.asyncio
async def test_correct_document_reference_claim_relationships(engine, sample_pipeline_data):
    inp = S8PersistInput(**sample_pipeline_data)
    await engine.persist_pipeline_outputs(inp)

    async with TestingSessionLocal() as session:
        claims = (await session.execute(select(Claim).where(Claim.document_id == inp.document_id))).scalars().all()
        for claim in claims:
            assert claim.document_id == inp.document_id
            assert claim.reference_id is not None

            # Verify the linked reference exists and belongs to the same document
            ref = (await session.execute(select(Reference).where(Reference.id == claim.reference_id))).scalar_one_or_none()
            assert ref is not None
            assert ref.document_id == inp.document_id


# ---------------- 3. Multiple References Associated with a Claim ----------------
@pytest.mark.asyncio
async def test_multiple_references_associated_with_claim(engine, sample_pipeline_data):
    inp = S8PersistInput(**sample_pipeline_data)
    await engine.persist_pipeline_outputs(inp)

    async with TestingSessionLocal() as session:
        # Claim 2 cited [1] and [2]
        claims = (await session.execute(select(Claim).where(Claim.document_id == inp.document_id))).scalars().all()
        claim_2 = [c for c in claims if "BERT achieves" in c.claim_text][0]
        assert claim_2.reference_id is not None

        # Verify linked reference corresponds to [2]
        ref = (await session.execute(select(Reference).where(Reference.id == claim_2.reference_id))).scalar_one_or_none()
        assert ref.citation_key == "[2]"


# ---------------- 4. Evidence Linked to Correct Claim and Reference ----------------
@pytest.mark.asyncio
async def test_evidence_linked_to_correct_claim_and_reference(engine, sample_pipeline_data):
    inp = S8PersistInput(**sample_pipeline_data)
    await engine.persist_pipeline_outputs(inp)

    async with TestingSessionLocal() as session:
        results = (await session.execute(select(Result))).scalars().all()
        for res in results:
            assert res.claim_id is not None
            assert res.evidence_id is not None

            # Verify evidence and claim relationships
            ev = (await session.execute(select(Evidence).where(Evidence.id == res.evidence_id))).scalar_one_or_none()
            claim = (await session.execute(select(Claim).where(Claim.id == res.claim_id))).scalar_one_or_none()
            assert ev is not None
            assert claim is not None
            # The evidence reference must match the claim reference
            assert ev.reference_id == claim.reference_id


# ---------------- 5. All Six Canonical Verdicts Persisted Correctly ----------------
@pytest.mark.asyncio
async def test_all_six_canonical_verdicts_persisted(engine):
    doc_id = "doc-six-verdicts"
    verdicts = [
        VerdictEnum.SUPPORTED,
        VerdictEnum.PARTIALLY_SUPPORTED,
        VerdictEnum.UNSUPPORTED,
        VerdictEnum.CONTRADICTORY,
        VerdictEnum.POTENTIALLY_OUTDATED,
        VerdictEnum.INSUFFICIENT_EVIDENCE,
    ]

    refs = [{"id": f"ref-v-{i}", "raw_citation": f"Source {i}", "citation_key": f"[{i}]"} for i in range(len(verdicts))]
    claims = [{"id": f"claim-v-{i}", "claim_text": f"Claim statement {i}", "reference_id": f"ref-v-{i}"} for i in range(len(verdicts))]
    evs = [{"id": f"ev-v-{i}", "reference_id": f"ref-v-{i}", "evidence_text": f"Evidence passage {i}"} for i in range(len(verdicts))]
    results = [
        {
            "claim_id": f"claim-v-{i}",
            "evidence_id": f"ev-v-{i}",
            "verdict": v.value,
            "verdict_strength": 0.85,
            "evidence_completeness": "full_text_available",
        }
        for i, v in enumerate(verdicts)
    ]

    inp = S8PersistInput(
        document_id=doc_id,
        references=refs,
        claims=claims,
        evidences=evs,
        results=results,
    )
    out = await engine.persist_pipeline_outputs(inp)
    assert out.persisted is True
    assert out.persisted_counts["results"] == 6

    async with TestingSessionLocal() as session:
        stored_results = (await session.execute(select(Result))).scalars().all()
        stored_verdicts = {r.verdict for r in stored_results}
        for v in verdicts:
            assert v.value in stored_verdicts


# ---------------- 6. Numerical and Scope Metadata Persisted ----------------
@pytest.mark.asyncio
async def test_numerical_and_scope_metadata_persisted(engine):
    doc_id = "doc-numerical-scope"
    ref = [{"id": "r-num", "raw_citation": "Clinical Trial J. (2022)"}]
    claim = [{"id": "c-num", "claim_text": "Drug X reduces blood pressure by 25.4 mmHg in humans.", "reference_id": "r-num"}]
    ev = [{"id": "e-num", "reference_id": "r-num", "evidence_text": "Drug X showed 12.1 mmHg reduction in mice.", "source_type": "full_text_available"}]
    res = [{
        "claim_id": "c-num",
        "evidence_id": "e-num",
        "verdict": "contradictory",
        "verdict_strength": 0.92,
        "retrieval_match": 0.78,
        "evidence_completeness": "full_text_available",
        "explanation": "Numerical mismatch: 25.4 mmHg vs 12.1 mmHg; scope overgeneralization: humans vs murine in-vivo.",
    }]

    inp = S8PersistInput(document_id=doc_id, references=ref, claims=claim, evidences=ev, results=res)
    await engine.persist_pipeline_outputs(inp)

    async with TestingSessionLocal() as session:
        result_row = (await session.execute(select(Result))).scalar_one_or_none()
        assert result_row is not None
        assert result_row.verdict == "contradictory"
        assert result_row.verdict_strength == 0.92
        assert result_row.retrieval_match == 0.78
        assert "Numerical mismatch" in result_row.explanation
        assert "scope overgeneralization" in result_row.explanation


# ---------------- 7. S7 Assessment Persisted ----------------
@pytest.mark.asyncio
async def test_s7_assessment_persisted(engine, sample_pipeline_data):
    inp = S8PersistInput(**sample_pipeline_data)
    await engine.persist_pipeline_outputs(inp)

    async with TestingSessionLocal() as session:
        audit = (await session.execute(select(AuditLog).where(AuditLog.document_id == inp.document_id))).scalars().all()
        assert len(audit) > 0
        details = audit[0].details
        assert details is not None
        assert "88.5" in details  # overall_health_score


# ---------------- 8. Idempotent Retry Behaviour ----------------
@pytest.mark.asyncio
async def test_idempotent_retry_behaviour(engine, sample_pipeline_data):
    inp = S8PersistInput(**sample_pipeline_data)

    # First run
    out1 = await engine.persist_pipeline_outputs(inp)
    assert out1.persisted is True

    # Retry run with exact same data
    out2 = await engine.persist_pipeline_outputs(inp)
    assert out2.persisted is True

    # Verify no duplicate records created
    async with TestingSessionLocal() as session:
        docs = (await session.execute(select(Document).where(Document.id == inp.document_id))).scalars().all()
        assert len(docs) == 1

        refs = (await session.execute(select(Reference).where(Reference.document_id == inp.document_id))).scalars().all()
        assert len(refs) == 2

        claims = (await session.execute(select(Claim).where(Claim.document_id == inp.document_id))).scalars().all()
        assert len(claims) == 2

        res = (await session.execute(select(Result))).scalars().all()
        assert len(res) == 2


# ---------------- 9. Transaction Rollback on Injected Failure ----------------
@pytest.mark.asyncio
async def test_transaction_rollback_on_injected_failure(engine, sample_pipeline_data):
    inp = S8PersistInput(**sample_pipeline_data)

    # Inject failure during results persistence
    with patch("app.repositories.ResultRepository.create", side_effect=RuntimeError("Simulated DB Crash")):
        with pytest.raises(RuntimeError, match="Simulated DB Crash"):
            await engine.persist_pipeline_outputs(inp)

    # Verify full transaction rollback: zero claims, references, or results persisted
    async with TestingSessionLocal() as session:
        refs = (await session.execute(select(Reference).where(Reference.document_id == inp.document_id))).scalars().all()
        assert len(refs) == 0

        claims = (await session.execute(select(Claim).where(Claim.document_id == inp.document_id))).scalars().all()
        assert len(claims) == 0

        res = (await session.execute(select(Result))).scalars().all()
        assert len(res) == 0


# ---------------- 10. No Orphaned or Duplicate Records ----------------
@pytest.mark.asyncio
async def test_no_orphaned_or_duplicate_records(engine, sample_pipeline_data):
    inp = S8PersistInput(**sample_pipeline_data)
    await engine.persist_pipeline_outputs(inp)

    async with TestingSessionLocal() as session:
        # Every claim must have a valid document
        claims = (await session.execute(select(Claim))).scalars().all()
        for c in claims:
            doc = (await session.execute(select(Document).where(Document.id == c.document_id))).scalar_one_or_none()
            assert doc is not None

        # Every result must map to a valid claim
        results = (await session.execute(select(Result))).scalars().all()
        for r in results:
            claim = (await session.execute(select(Claim).where(Claim.id == r.claim_id))).scalar_one_or_none()
            assert claim is not None
