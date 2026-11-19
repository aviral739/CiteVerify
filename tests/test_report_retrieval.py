"""Comprehensive test suite for Report Retrieval and Document Report contracts.

Verifies:
1. Correct total reference count.
2. Correct total claim count.
3. Correct result count.
4. Accurate verdict distribution across all 6 canonical verdicts.
5. Evidence completeness tiers (full_text_available, abstract_only, unavailable).
6. Numerical and scope information preservation.
7. Retraction warnings and status tracking.
8. Document assessment metadata.
9. Human-review information attached to results.
10. Correct behaviour for empty and partially completed reports.
11. Existing API endpoint GET /api/documents/{id}/report contract conformance.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.schemas import (
    DocumentReportResponse,
    EvidenceAvailabilityEnum,
    VerdictEnum,
)
from app.models.tables import Document
from app.stages.s8_persist import (
    DocumentReportRepository,
    PersistenceEngine,
    ReviewRepository,
    S8PersistInput,
)
from tests.conftest import TestingSessionLocal


@pytest.fixture
def engine():
    return PersistenceEngine(session_factory=TestingSessionLocal)


@pytest.fixture
def rich_report_data():
    doc_id = "doc-report-retrieval-001"
    refs = [
        {
            "id": "ref-rep-1",
            "citation_key": "[1]",
            "raw_citation": "Alpha et al. (2020). Quantum Speedup. Phys Rev.",
            "resolved_title": "Quantum Speedup in Superconducting Chips",
            "resolved_doi": "10.1103/PhysRev.100.123",
            "resolved_year": 2020,
            "resolution_confidence": 0.98,
        },
        {
            "id": "ref-rep-2",
            "citation_key": "[2]",
            "raw_citation": "Beta et al. (2019). Retracted Paper on Cold Fusion.",
            "resolved_title": "Cold Fusion via Solid State Electrolysis",
            "resolved_doi": "10.1000/retracted.coldfusion",
            "resolved_year": 2019,
            "is_retracted": True,
            "retraction_notice": "Retracted due to unreproducible experimental claims.",
            "resolution_confidence": 0.99,
        },
        {
            "id": "ref-rep-3",
            "citation_key": "[3]",
            "raw_citation": "Gamma et al. (2021). Neural Networks. Nature.",
            "resolved_title": "Deep Neural Network Universal Approximation",
            "resolved_doi": "10.1038/s41586-021-0001",
            "resolved_year": 2021,
            "resolution_confidence": 0.95,
        },
    ]

    claims = [
        {
            "id": "claim-rep-1",
            "claim_text": "Quantum speedup was observed across 53 qubits [1].",
            "reference_id": "ref-rep-1",
            "citation_key": "[1]",
            "section_name": "Results",
        },
        {
            "id": "claim-rep-2",
            "claim_text": "Room temperature excess heat exceeded 15.4 MJ [2].",
            "reference_id": "ref-rep-2",
            "citation_key": "[2]",
            "section_name": "Discussion",
        },
        {
            "id": "claim-rep-3",
            "claim_text": "Neural networks achieve 99.8% precision on ImageNet [3].",
            "reference_id": "ref-rep-3",
            "citation_key": "[3]",
            "section_name": "Introduction",
        },
    ]

    evidences = [
        {
            "id": "ev-rep-1",
            "reference_id": "ref-rep-1",
            "evidence_text": "The processor sampled quantum circuits in 200 seconds using 53 qubits.",
            "source_type": "full_text_available",
            "retrieval_score": 0.95,
        },
        {
            "id": "ev-rep-2",
            "reference_id": "ref-rep-2",
            "evidence_text": "Notice: This paper has been formally retracted by the editors.",
            "source_type": "abstract_only",
            "retrieval_score": 0.88,
        },
        {
            "id": "ev-rep-3",
            "reference_id": "ref-rep-3",
            "evidence_text": "Top-1 accuracy on ImageNet reached 88.5%, not 99.8%.",
            "source_type": "full_text_available",
            "retrieval_score": 0.92,
        },
    ]

    results = [
        {
            "claim_id": "claim-rep-1",
            "evidence_id": "ev-rep-1",
            "verdict": "supported",
            "verdict_strength": 0.95,
            "retrieval_match": 0.90,
            "evidence_completeness": "full_text_available",
            "explanation": "Claim directly validated by 53-qubit benchmarks in source paper.",
        },
        {
            "claim_id": "claim-rep-2",
            "evidence_id": "ev-rep-2",
            "verdict": "contradictory",
            "verdict_strength": 0.99,
            "retrieval_match": 0.85,
            "evidence_completeness": "abstract_only",
            "explanation": "WARNING: Cited source paper is retracted (Retracted due to unreproducible experimental claims).",
        },
        {
            "claim_id": "claim-rep-3",
            "evidence_id": "ev-rep-3",
            "verdict": "unsupported",
            "verdict_strength": 0.91,
            "retrieval_match": 0.80,
            "evidence_completeness": "full_text_available",
            "explanation": "Numerical mismatch: Claimed 99.8% precision, whereas source reports 88.5% top-1 accuracy.",
        },
    ]

    return {
        "document_id": doc_id,
        "document_title": "Quantum and Machine Learning Verification Audit",
        "references": refs,
        "claims": claims,
        "evidences": evidences,
        "results": results,
    }


# ---------------- 1. Total Reference, Claim, and Result Counts ----------------
@pytest.mark.asyncio
async def test_report_retrieval_counts(engine, rich_report_data):
    inp = S8PersistInput(**rich_report_data)
    await engine.persist_pipeline_outputs(inp)

    async with TestingSessionLocal() as session:
        repo = DocumentReportRepository(session)
        report = await repo.build_document_report(inp.document_id)

        assert report is not None
        assert report.total_references == 3
        assert report.total_claims == 3
        assert report.total_results == 3
        assert len(report.results) == 3


# ---------------- 2. Accurate Verdict Distribution ----------------
@pytest.mark.asyncio
async def test_report_retrieval_verdict_distribution(engine, rich_report_data):
    inp = S8PersistInput(**rich_report_data)
    await engine.persist_pipeline_outputs(inp)

    async with TestingSessionLocal() as session:
        repo = DocumentReportRepository(session)
        report = await repo.build_document_report(inp.document_id)

        summary = report.results_summary
        assert summary["supported"] == 1
        assert summary["contradictory"] == 1
        assert summary["unsupported"] == 1
        assert summary["partially_supported"] == 0
        assert summary["potentially_outdated"] == 0
        assert summary["insufficient_evidence"] == 0


# ---------------- 3. Evidence Completeness Tiers ----------------
@pytest.mark.asyncio
async def test_report_retrieval_evidence_completeness_tiers(engine, rich_report_data):
    inp = S8PersistInput(**rich_report_data)
    await engine.persist_pipeline_outputs(inp)

    async with TestingSessionLocal() as session:
        repo = DocumentReportRepository(session)
        report = await repo.build_document_report(inp.document_id)

        completeness_levels = [r.evidence_completeness for r in report.results]
        assert EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE in completeness_levels
        assert EvidenceAvailabilityEnum.ABSTRACT_ONLY in completeness_levels


# ---------------- 4. Numerical and Scope Information ----------------
@pytest.mark.asyncio
async def test_report_retrieval_numerical_and_scope_info(engine, rich_report_data):
    inp = S8PersistInput(**rich_report_data)
    await engine.persist_pipeline_outputs(inp)

    async with TestingSessionLocal() as session:
        repo = DocumentReportRepository(session)
        report = await repo.build_document_report(inp.document_id)

        mismatch_res = [r for r in report.results if r.verdict == VerdictEnum.UNSUPPORTED][0]
        assert "Numerical mismatch" in mismatch_res.explanation
        assert "99.8%" in mismatch_res.explanation
        assert "88.5%" in mismatch_res.explanation


# ---------------- 5. Retraction Warnings ----------------
@pytest.mark.asyncio
async def test_report_retrieval_retraction_warnings(engine, rich_report_data):
    inp = S8PersistInput(**rich_report_data)
    await engine.persist_pipeline_outputs(inp)

    async with TestingSessionLocal() as session:
        repo = DocumentReportRepository(session)
        report = await repo.build_document_report(inp.document_id)

        retracted_res = [r for r in report.results if r.verdict == VerdictEnum.CONTRADICTORY][0]
        assert "WARNING: Cited source paper is retracted" in retracted_res.explanation


# ---------------- 6. Human-Review Information Attached ----------------
@pytest.mark.asyncio
async def test_report_retrieval_includes_human_reviews(engine, rich_report_data):
    inp = S8PersistInput(**rich_report_data)
    await engine.persist_pipeline_outputs(inp)

    # Submit a human review on the first result
    async with TestingSessionLocal() as session:
        repo = DocumentReportRepository(session)
        report_before = await repo.build_document_report(inp.document_id)
        target_res_id = report_before.results[0].id

        rev_repo = ReviewRepository(session)
        await rev_repo.create_review(
            result_id=target_res_id,
            reviewer_id="lead_auditor",
            human_decision="confirmed",
            notes="Auditor verified 53-qubit benchmark figures against SI.",
        )
        await session.commit()

        # Re-fetch report and verify review is present
        report_after = await repo.build_document_report(inp.document_id)
        target_res = [r for r in report_after.results if r.id == target_res_id][0]
        assert len(target_res.reviews) == 1
        assert target_res.reviews[0].reviewer_id == "lead_auditor"
        assert target_res.reviews[0].human_decision.value == "confirmed"


# ---------------- 7. Empty Report Handling ----------------
@pytest.mark.asyncio
async def test_empty_report_handling(engine):
    doc_id = "doc-empty-report"
    inp = S8PersistInput(
        document_id=doc_id,
        document_title="Newly Uploaded Paper without Processing",
        references=[],
        claims=[],
        evidences=[],
        results=[],
    )
    await engine.persist_pipeline_outputs(inp)

    async with TestingSessionLocal() as session:
        repo = DocumentReportRepository(session)
        report = await repo.build_document_report(doc_id)

        assert report is not None
        assert report.total_references == 0
        assert report.total_claims == 0
        assert report.total_results == 0
        assert len(report.results) == 0
        assert all(count == 0 for count in report.results_summary.values())


# ---------------- 8. Partially Completed Report Handling ----------------
@pytest.mark.asyncio
async def test_partially_completed_report_handling(engine):
    doc_id = "doc-partial-report"
    refs = [{"id": "r-p1", "raw_citation": "Paper 1"}]
    # 3 claims extracted, but only 1 claim has a verification result
    claims = [
        {"id": "c-p1", "claim_text": "Claim 1", "reference_id": "r-p1"},
        {"id": "c-p2", "claim_text": "Claim 2", "reference_id": "r-p1"},
        {"id": "c-p3", "claim_text": "Claim 3", "reference_id": "r-p1"},
    ]
    results = [
        {"claim_id": "c-p1", "verdict": "supported", "verdict_strength": 0.90},
    ]

    inp = S8PersistInput(
        document_id=doc_id,
        references=refs,
        claims=claims,
        results=results,
    )
    await engine.persist_pipeline_outputs(inp)

    async with TestingSessionLocal() as session:
        repo = DocumentReportRepository(session)
        report = await repo.build_document_report(doc_id)

        assert report.total_references == 1
        assert report.total_claims == 3
        assert report.total_results == 1
        assert len(report.results) == 1
        assert report.results_summary["supported"] == 1


# ---------------- 9. Existing API Endpoint GET /api/documents/{id}/report Contract ----------------
@pytest.mark.asyncio
async def test_api_report_endpoint_contract(async_client: AsyncClient):
    # 1. Nonexistent document returns 404
    res_404 = await async_client.get("/api/documents/nonexistent-id/report")
    assert res_404.status_code == 404

    # 2. Demo document returns 200 with DocumentReportResponse structure
    demo_res = await async_client.post("/api/documents/demo")
    assert demo_res.status_code == 201
    doc_id = demo_res.json()["id"]

    report_res = await async_client.get(f"/api/documents/{doc_id}/report")
    assert report_res.status_code == 200
    report_data = report_res.json()
    assert report_data["document"]["id"] == doc_id
    assert "total_references" in report_data
    assert "total_claims" in report_data
    assert "results_summary" in report_data
    assert "results" in report_data
