"""Automated tests for Human Review workflow, result overrides, and audit trails.

Verifies:
1. Confirmed human review.
2. Overridden human review with new human verdict.
3. Disputed human review.
4. Human verdict stored separately from original automated AI verdict.
5. Review creates an immutable audit record in the database.
6. Subsequent report retrieval reflects human review details accurately.
7. Validation and 404 handling on nonexistent result ID.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.schemas import HumanDecisionEnum, VerdictEnum
from app.models.tables import AuditLog, Claim, Result, Review
from app.stages.s8_persist import (
    DocumentReportRepository,
    PersistenceEngine,
    S8PersistInput,
)
from tests.conftest import TestingSessionLocal


@pytest.fixture
def engine():
    return PersistenceEngine(session_factory=TestingSessionLocal)


@pytest.fixture
async def seeded_document(engine):
    """Seeds a complete document with 1 reference, 1 claim, and 1 automated result."""
    doc_id = "doc-human-review-test"
    ref = [{"id": "ref-hr-1", "raw_citation": "Author et al. (2023). Test Paper.", "citation_key": "[1]"}]
    claim = [{"id": "claim-hr-1", "claim_text": "Model achieves 95% accuracy.", "reference_id": "ref-hr-1"}]
    ev = [{"id": "ev-hr-1", "reference_id": "ref-hr-1", "evidence_text": "Accuracy reached 95% across validation split."}]
    res = [{
        "id": "result-hr-1",
        "claim_id": "claim-hr-1",
        "evidence_id": "ev-hr-1",
        "verdict": "supported",
        "verdict_strength": 0.95,
        "retrieval_match": 0.93,
        "evidence_completeness": "full_text_available",
        "explanation": "Automated verification: claim supported by validation results.",
    }]

    inp = S8PersistInput(
        document_id=doc_id,
        document_title="Human Review Test Manuscript",
        references=ref,
        claims=claim,
        evidences=ev,
        results=res,
    )
    await engine.persist_pipeline_outputs(inp)

    # Return the persisted result ID
    async with TestingSessionLocal() as session:
        result_row = (await session.execute(select(Result))).scalar_one()
        return {"document_id": doc_id, "result_id": result_row.id}


# ---------------- 1. Confirmed Review ----------------
@pytest.mark.asyncio
async def test_human_review_confirmed(async_client: AsyncClient, seeded_document):
    result_id = seeded_document["result_id"]
    payload = {
        "reviewer_id": "auditor_alice",
        "human_decision": "confirmed",
        "notes": "Verified against experimental metrics.",
    }
    response = await async_client.patch(f"/api/results/{result_id}/review", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["result_id"] == result_id
    assert data["reviewer_id"] == "auditor_alice"
    assert data["human_decision"] == "confirmed"
    assert data["human_verdict"] is None
    assert data["notes"] == "Verified against experimental metrics."

    # Verify database persistence
    async with TestingSessionLocal() as session:
        rev = (await session.execute(select(Review).where(Review.result_id == result_id))).scalar_one_or_none()
        assert rev is not None
        assert rev.human_decision == "confirmed"


# ---------------- 2. Overridden Review ----------------
@pytest.mark.asyncio
async def test_human_review_overridden(async_client: AsyncClient, seeded_document):
    result_id = seeded_document["result_id"]
    payload = {
        "reviewer_id": "senior_reviewer_bob",
        "human_decision": "overridden",
        "human_verdict": "contradictory",
        "notes": "Table 4 indicates 75% accuracy on test split, contradicting 95% validation claim.",
    }
    response = await async_client.patch(f"/api/results/{result_id}/review", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["human_decision"] == "overridden"
    assert data["human_verdict"] == "contradictory"
    assert "contradicting 95%" in data["notes"]


# ---------------- 3. Disputed Review ----------------
@pytest.mark.asyncio
async def test_human_review_disputed(async_client: AsyncClient, seeded_document):
    result_id = seeded_document["result_id"]
    payload = {
        "reviewer_id": "domain_expert_charlie",
        "human_decision": "disputed",
        "notes": "Extraction ambiguity: cited paper discusses a different dataset variant.",
    }
    response = await async_client.patch(f"/api/results/{result_id}/review", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["human_decision"] == "disputed"


# ---------------- 4. Human Verdict Stored Separately from AI Verdict ----------------
@pytest.mark.asyncio
async def test_human_verdict_stored_separately_from_ai_verdict(async_client: AsyncClient, seeded_document):
    result_id = seeded_document["result_id"]

    # Original AI verdict was "supported"
    async with TestingSessionLocal() as session:
        initial_res = (await session.execute(select(Result).where(Result.id == result_id))).scalar_one()
        assert initial_res.verdict == "supported"

    # Human reviewer overrides to "contradictory"
    payload = {
        "reviewer_id": "auditor_dan",
        "human_decision": "overridden",
        "human_verdict": "contradictory",
        "notes": "Override based on manual cross-check.",
    }
    res_override = await async_client.patch(f"/api/results/{result_id}/review", json=payload)
    assert res_override.status_code == 200

    # Verify that the original Result.verdict in database remains "supported"
    # and the human override is stored exclusively in the Review table
    async with TestingSessionLocal() as session:
        res_after = (await session.execute(select(Result).where(Result.id == result_id))).scalar_one()
        assert res_after.verdict == "supported"  # Preserved!

        rev = (await session.execute(select(Review).where(Review.result_id == result_id))).scalar_one()
        assert rev.human_decision == "overridden"
        assert rev.human_verdict == "contradictory"  # Stored separately!


# ---------------- 5. Review Creates Audit Record ----------------
@pytest.mark.asyncio
async def test_review_creates_audit_record(async_client: AsyncClient, seeded_document):
    result_id = seeded_document["result_id"]
    payload = {
        "reviewer_id": "compliance_officer_eve",
        "human_decision": "confirmed",
        "notes": "Audit compliance check passed.",
    }
    await async_client.patch(f"/api/results/{result_id}/review", json=payload)

    async with TestingSessionLocal() as session:
        audit = (
            await session.execute(
                select(AuditLog).where(AuditLog.action == "human_review_submitted")
            )
        ).scalar_one_or_none()
        assert audit is not None
        assert audit.actor == "compliance_officer_eve"
        assert result_id in audit.details


# ---------------- 6. Subsequent Report Reflects Review ----------------
@pytest.mark.asyncio
async def test_subsequent_report_reflects_review(async_client: AsyncClient, seeded_document):
    doc_id = seeded_document["document_id"]
    result_id = seeded_document["result_id"]

    # Submit review
    payload = {
        "reviewer_id": "lead_scientist",
        "human_decision": "confirmed",
        "notes": "Confirmed by lead scientist.",
    }
    await async_client.patch(f"/api/results/{result_id}/review", json=payload)

    # Re-fetch report using DocumentReportRepository
    async with TestingSessionLocal() as session:
        repo = DocumentReportRepository(session)
        report = await repo.build_document_report(doc_id)
        assert report is not None
        res_item = [r for r in report.results if r.id == result_id][0]
        assert len(res_item.reviews) == 1
        assert res_item.reviews[0].reviewer_id == "lead_scientist"
        assert res_item.reviews[0].human_decision == HumanDecisionEnum.CONFIRMED


# ---------------- 7. Nonexistent Result Returns 404 ----------------
@pytest.mark.asyncio
async def test_review_nonexistent_result_returns_404(async_client: AsyncClient):
    response = await async_client.patch(
        "/api/results/unknown-result-uuid/review",
        json={"human_decision": "confirmed", "reviewer_id": "ghost"},
    )
    assert response.status_code == 404
    data = response.json()
    assert "not found" in data["message"].lower()
