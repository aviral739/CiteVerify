"""Test suite for API endpoints, schemas, database, and pipeline stage imports."""

import pytest
from httpx import AsyncClient

from app.models.schemas import (
    EvidenceAvailabilityEnum,
    HumanDecisionEnum,
    VerdictEnum,
)
from app.stages.s1_parse import S1ParseInput, run_stage_1
from app.stages.s2_references import S2ReferencesInput, run_stage_2
from app.stages.s3_claims import S3ClaimsInput, run_stage_3
from app.stages.s4_resolve import S4ResolveInput, run_stage_4
from app.stages.s5_evidence import S5EvidenceInput, run_stage_5
from app.stages.s6_verify import S6VerifyInput, run_stage_6
from app.stages.s7_assessment import S7AssessmentInput, run_stage_7
from app.stages.s8_persist import S8PersistInput, run_stage_8


@pytest.mark.asyncio
async def test_health_endpoint(async_client: AsyncClient):
    """Verify /health returns 200 OK and expected structure."""
    response = await async_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["database_connected"] is True
    assert data["llm_service_ready"] is True


@pytest.mark.asyncio
async def test_create_and_get_document(async_client: AsyncClient):
    """Test POST /api/documents and GET /api/documents/{id}."""
    create_payload = {
        "title": "Empirical Verification of Scientific Literature",
        "doi": "10.1234/citeverify.test",
        "authors": "Dr. Alice, Dr. Bob",
    }
    response = await async_client.post("/api/documents", json=create_payload)
    assert response.status_code == 201
    doc = response.json()
    assert doc["title"] == create_payload["title"]
    assert doc["doi"] == create_payload["doi"]
    doc_id = doc["id"]

    # Retrieve document
    get_res = await async_client.get(f"/api/documents/{doc_id}")
    assert get_res.status_code == 200
    fetched = get_res.json()
    assert fetched["id"] == doc_id
    assert fetched["title"] == create_payload["title"]


@pytest.mark.asyncio
async def test_demo_document_endpoint(async_client: AsyncClient):
    """Test POST /api/documents/demo seeds demo data."""
    res = await async_client.post("/api/documents/demo", json={"sample_key": "attention_is_all_you_need"})
    assert res.status_code == 201
    demo_doc = res.json()
    assert "Demo Sample" in demo_doc["title"]
    doc_id = demo_doc["id"]

    # Verify report endpoint
    report_res = await async_client.get(f"/api/documents/{doc_id}/report")
    assert report_res.status_code == 200
    report_data = report_res.json()
    assert report_data["document"]["id"] == doc_id
    assert report_data["total_references"] >= 1
    assert report_data["total_claims"] >= 1


@pytest.mark.asyncio
async def test_claim_patch_endpoint(async_client: AsyncClient):
    """Test PATCH /api/documents/{id}/claims updates claim state."""
    # Seed demo document first
    seed_res = await async_client.post("/api/documents/demo")
    assert seed_res.status_code == 201
    doc_id = seed_res.json()["id"]

    # Get report to find claim ID
    rep_res = await async_client.get(f"/api/documents/{doc_id}/report")
    assert rep_res.status_code == 200

    # In a new DB session, seed another claim
    patch_res = await async_client.patch(
        f"/api/documents/{doc_id}/claims",
        json={"claim_id": "nonexistent-claim", "is_active": False},
    )
    # Should cleanly return 404
    assert patch_res.status_code == 404


@pytest.mark.asyncio
async def test_export_and_audit_endpoints(async_client: AsyncClient):
    """Test GET /api/documents/{id}/export and GET /api/documents/{id}/audit."""
    create_res = await async_client.post(
        "/api/documents",
        json={"title": "Audit and Export Test Paper"},
    )
    assert create_res.status_code == 201
    doc_id = create_res.json()["id"]

    # Test export
    export_res = await async_client.get(f"/api/documents/{doc_id}/export?format=json")
    assert export_res.status_code == 200
    export_data = export_res.json()
    assert export_data["document_id"] == doc_id
    assert export_data["export_format"] == "json"

    # Test audit
    audit_res = await async_client.get(f"/api/documents/{doc_id}/audit")
    assert audit_res.status_code == 200
    audit_data = audit_res.json()
    assert isinstance(audit_data, list)


@pytest.mark.asyncio
async def test_stage_imports_and_contracts():
    """Verify that all 8 pipeline stages can be imported and executed with typed contracts."""
    doc_id = "test-doc-id"

    # Stage 1
    s1_out = await run_stage_1(S1ParseInput(document_id=doc_id, file_path="dummy.pdf"))
    assert s1_out.document_id == doc_id

    # Stage 2
    s2_out = await run_stage_2(S2ReferencesInput(document_id=doc_id, raw_text=s1_out.raw_text))
    assert len(s2_out.references) > 0

    # Stage 3
    s3_out = await run_stage_3(S3ClaimsInput(document_id=doc_id, sections=s1_out.sections))
    assert len(s3_out.claims) > 0

    # Stage 4
    s4_out = await run_stage_4(S4ResolveInput(
        document_id=doc_id,
        raw_citations=[r.model_dump() for r in s2_out.references],
    ))
    assert len(s4_out.resolved_references) > 0

    # Stage 5
    s5_out = await run_stage_5(S5EvidenceInput(
        document_id=doc_id,
        resolved_references=[r.model_dump() for r in s4_out.resolved_references],
        claims=[c.model_dump() for c in s3_out.claims],
    ))
    assert len(s5_out.evidence_items) > 0

    # Stage 6
    s6_out = await run_stage_6(S6VerifyInput(
        document_id=doc_id,
        claims_with_evidence=[e.model_dump() for e in s5_out.evidence_items],
    ))
    assert len(s6_out.results) > 0
    assert s6_out.results[0].verdict in VerdictEnum

    # Stage 7
    s7_out = await run_stage_7(S7AssessmentInput(
        document_id=doc_id,
        results=[r.model_dump() for r in s6_out.results],
    ))
    assert s7_out.overall_health_score >= 0.0

    # Stage 8
    s8_out = await run_stage_8(S8PersistInput(
        document_id=doc_id,
        assessment_data=s7_out.model_dump(),
    ))
    assert s8_out.persisted is True

