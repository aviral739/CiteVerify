"""End-to-end integration test verifying the orchestration workflow contract."""

import pytest
from httpx import AsyncClient

from app.core.jobs import job_registry
from app.pipeline.orchestrator import orchestrator


@pytest.mark.asyncio
async def test_pipeline_orchestrator_contract():
    """Verify the 8-stage orchestrator runs through all stages and updates job state."""
    doc_id = "e2e-doc-123"
    job_id = "job-test-456"

    # Register job
    job_registry.register(job_id=job_id, document_id=doc_id)

    # Execute orchestrator
    result = await orchestrator.execute(document_id=doc_id, job_id=job_id, file_path="storage/uploads/test.pdf")

    assert result.document_id == doc_id
    assert result.job_id == job_id
    assert result.status == "completed"
    assert result.is_mock_run is True

    # Check all 8 stages were traversed
    expected_stages = [
        "s1_parse",
        "s2_references",
        "s3_claims",
        "s4_resolve",
        "s5_evidence",
        "s6_verify",
        "s7_assessment",
        "s8_persist",
    ]
    assert result.stages_executed == expected_stages

    # Verify job registry was updated
    job_record = job_registry.get(job_id)
    assert job_record is not None
    assert job_record.status == "completed"
    assert job_record.progress_percentage == 100.0


@pytest.mark.asyncio
async def test_swagger_documentation_available(async_client: AsyncClient):
    """Verify FastAPI automatically exposes Swagger docs and OpenAPI JSON."""
    docs_response = await async_client.get("/docs")
    assert docs_response.status_code == 200

    openapi_response = await async_client.get("/openapi.json")
    assert openapi_response.status_code == 200
    spec = openapi_response.json()
    assert spec["info"]["title"] == "CiteVerify"

    # Verify all expected endpoint paths exist in spec
    paths = spec["paths"]
    assert "/api/documents" in paths
    assert "/api/documents/demo" in paths
    assert "/api/documents/{id}" in paths
    assert "/api/documents/{id}/events" in paths
    assert "/api/documents/{id}/report" in paths
    assert "/api/documents/{id}/claims" in paths
    assert "/api/results/{id}/review" in paths
    assert "/api/documents/{id}/audit" in paths
    assert "/api/documents/{id}/export" in paths
    assert "/health" in paths

