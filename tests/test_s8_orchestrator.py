"""Tests for S8 Orchestrator Integration (Phase 1).

Verifies:
1. All seven S1-S7 outputs reach S8 with complete typed structures.
2. Exact document_id and job_id are preserved throughout orchestration.
3. S8 is invoked strictly after S7 completes.
4. Progress does not reach 100% before successful S8 completion.
5. S8 failure prevents marking the job completed and preserves failure details.
6. Upstream stage failures halt the pipeline prior to S8.
7. Strict S8PersistInput contract enforcement and legacy adapter support.
"""

from unittest.mock import AsyncMock, patch
import pytest
from pydantic import ValidationError

from app.core.jobs import JobStatus, job_registry
from app.pipeline.orchestrator import orchestrator
from app.stages.s1_parse.models import S1ParseOutput
from app.stages.s2_references.models import S2ReferencesOutput
from app.stages.s3_claims.models import S3ClaimsOutput
from app.stages.s4_resolve.models import S4ResolveOutput
from app.stages.s5_evidence.models import S5EvidenceOutput
from app.stages.s6_verify.models import S6VerifyOutput
from app.stages.s7_assessment.models import S7AssessmentOutput
from app.stages.s8_persist.models import (
    LegacyS8PersistInput,
    S8PersistInput,
    S8PersistOutput,
    adapt_legacy_input,
)


@pytest.mark.asyncio
async def test_all_seven_stage_outputs_reach_s8():
    """Verify that S8 receives all seven upstream stage outputs without discarding any."""
    doc_id = "doc-full-payload-test-001"
    job_id = "job-full-payload-test-001"
    job_registry.register(job_id=job_id, document_id=doc_id)

    captured_input: S8PersistInput = None

    async def mock_run_stage_8(input_data: S8PersistInput) -> S8PersistOutput:
        nonlocal captured_input
        captured_input = input_data
        return S8PersistOutput(
            document_id=input_data.document_id,
            job_id=input_data.job_id,
            persisted=True,
            status="completed",
        )

    with patch("app.pipeline.orchestrator.run_stage_8", side_effect=mock_run_stage_8):
        contract = await orchestrator.execute(document_id=doc_id, job_id=job_id)

    assert contract.status == "completed"
    assert captured_input is not None
    assert captured_input.document_id == doc_id
    assert captured_input.job_id == job_id

    # Verify all seven typed stage outputs are present
    assert isinstance(captured_input.s1_parse, S1ParseOutput)
    assert isinstance(captured_input.s2_references, S2ReferencesOutput)
    assert isinstance(captured_input.s3_claims, S3ClaimsOutput)
    assert isinstance(captured_input.s4_resolve, S4ResolveOutput)
    assert isinstance(captured_input.s5_evidence, S5EvidenceOutput)
    assert isinstance(captured_input.s6_verify, S6VerifyOutput)
    assert isinstance(captured_input.s7_assessment, S7AssessmentOutput)


@pytest.mark.asyncio
async def test_original_identifiers_preserved():
    """Verify exact document_id and job_id are preserved in S8 and contract."""
    custom_doc_id = "custom-uuid-doc-987654"
    custom_job_id = "custom-uuid-job-123456"
    job_registry.register(job_id=custom_job_id, document_id=custom_doc_id)

    contract = await orchestrator.execute(document_id=custom_doc_id, job_id=custom_job_id)

    assert contract.document_id == custom_doc_id
    assert contract.job_id == custom_job_id

    job_record = job_registry.get(custom_job_id)
    assert job_record.document_id == custom_doc_id
    assert job_record.job_id == custom_job_id


@pytest.mark.asyncio
async def test_s8_invoked_only_after_s7_completes():
    """Verify S8 is only called after S7 completes and S7 output is available."""
    doc_id = "doc-order-test"
    job_id = "job-order-test"
    job_registry.register(job_id=job_id, document_id=doc_id)

    stage_order = []

    async def tracked_s8(input_data):
        # Assert S7 assessment has already computed health score and summary
        assert input_data.s7_assessment is not None
        assert input_data.s7_assessment.overall_health_score >= 0.0
        stage_order.append("s8_persist")
        return S8PersistOutput(document_id=input_data.document_id, persisted=True, status="completed")

    with patch("app.pipeline.orchestrator.run_stage_8", side_effect=tracked_s8):
        contract = await orchestrator.execute(document_id=doc_id, job_id=job_id)

    assert contract.status == "completed"
    assert "s8_persist" in stage_order
    # In contract executed stages, s7_assessment immediately precedes s8_persist
    s7_idx = contract.stages_executed.index("s7_assessment")
    s8_idx = contract.stages_executed.index("s8_persist")
    assert s8_idx == s7_idx + 1


@pytest.mark.asyncio
async def test_progress_does_not_reach_100_before_s8_completion():
    """Verify progress is 95% while S8 is executing, and reaches 100% only after S8 returns."""
    doc_id = "doc-progress-test"
    job_id = "job-progress-test"
    job_registry.register(job_id=job_id, document_id=doc_id)

    progress_during_s8 = None
    status_during_s8 = None

    async def probe_s8(input_data):
        nonlocal progress_during_s8, status_during_s8
        # Probe in-memory job registry mid-execution
        current_job = job_registry.get(job_id)
        progress_during_s8 = current_job.progress_percentage
        status_during_s8 = current_job.status
        return S8PersistOutput(document_id=input_data.document_id, persisted=True, status="completed")

    with patch("app.pipeline.orchestrator.run_stage_8", side_effect=probe_s8):
        contract = await orchestrator.execute(document_id=doc_id, job_id=job_id)

    assert contract.status == "completed"
    # Mid-execution checks: progress was 95.0% and status was RUNNING
    assert progress_during_s8 == 95.0
    assert status_during_s8 == JobStatus.RUNNING

    # Post-execution check: progress reaches 100.0% only after S8 succeeded
    final_job = job_registry.get(job_id)
    assert final_job.progress_percentage == 100.0
    assert final_job.status == JobStatus.COMPLETED


@pytest.mark.asyncio
async def test_s8_failure_prevents_job_completion():
    """Verify that if S8 persistence fails, the job is marked failed and progress is not 100%."""
    doc_id = "doc-fail-s8-test"
    job_id = "job-fail-s8-test"
    job_registry.register(job_id=job_id, document_id=doc_id)

    async def failing_s8(input_data):
        return S8PersistOutput(
            document_id=input_data.document_id,
            job_id=input_data.job_id,
            persisted=False,
            status="failed",
            warnings=["Database connection refused during commit."],
        )

    with patch("app.pipeline.orchestrator.run_stage_8", side_effect=failing_s8):
        contract = await orchestrator.execute(document_id=doc_id, job_id=job_id)

    assert contract.status == "failed"
    assert "s8_persist" not in contract.stages_executed
    assert contract.summary["failed_stage"] == "s8_persist"

    job_record = job_registry.get(job_id)
    assert job_record.status == JobStatus.FAILED
    assert job_record.progress_percentage == 95.0  # Must NOT be 100.0%
    assert "Stage 8 persistence failed" in job_record.error_message


@pytest.mark.asyncio
async def test_upstream_failure_halts_pipeline_prior_to_s8():
    """Verify that if an upstream stage fails, S8 is never invoked and job fails with stage name."""
    doc_id = "doc-upstream-fail"
    job_id = "job-upstream-fail"
    job_registry.register(job_id=job_id, document_id=doc_id)

    s8_invoked = False

    async def s8_spy(input_data):
        nonlocal s8_invoked
        s8_invoked = True
        return S8PersistOutput(document_id=input_data.document_id, persisted=True, status="completed")

    async def failing_s4(input_data):
        raise ConnectionResetError("Scholarly API gateway timeout")

    with patch("app.pipeline.orchestrator.run_stage_4", side_effect=failing_s4), \
         patch("app.pipeline.orchestrator.run_stage_8", side_effect=s8_spy):
        contract = await orchestrator.execute(document_id=doc_id, job_id=job_id)

    assert contract.status == "failed"
    assert s8_invoked is False
    assert contract.summary["failed_stage"] == "s4_resolve"
    assert "s4_resolve" not in contract.stages_executed

    job_record = job_registry.get(job_id)
    assert job_record.status == JobStatus.FAILED
    assert job_record.progress_percentage == 50.0


def test_s8_persist_input_strict_contract_enforcement():
    """Verify S8PersistInput strictly requires all seven stage outputs when called in production mode."""
    # Omitting s1_parse must raise ValidationError
    with pytest.raises(ValidationError) as exc_info:
        S8PersistInput(document_id="doc-invalid")
    errors = str(exc_info.value)
    assert "s1_parse" in errors
    assert "s2_references" in errors
    assert "s3_claims" in errors


def test_s8_persist_input_legacy_adapter():
    """Verify legacy adapter safely handles assessment_data-only inputs without raising ValidationError."""
    legacy = LegacyS8PersistInput(
        document_id="doc-legacy-123",
        assessment_data={"overall_health_score": 85.0, "summary": {"supported": 4}},
    )
    adapted = adapt_legacy_input(legacy)
    assert isinstance(adapted, S8PersistInput)
    assert adapted.document_id == "doc-legacy-123"
    assert adapted.s7_assessment.overall_health_score == 85.0
    assert adapted.s7_assessment.summary == {"supported": 4}

    # Verify S8PersistInput adapts dictionary with assessment_data via validator
    adapted_from_dict = S8PersistInput.model_validate({
        "document_id": "doc-legacy-dict",
        "assessment_data": {"overall_health_score": 90.0},
    })
    assert isinstance(adapted_from_dict, S8PersistInput)
    assert adapted_from_dict.s7_assessment.overall_health_score == 90.0
