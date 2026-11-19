"""Pipeline orchestrator defining the intended sequential verification flow.

Coordinates execution across the 8 stages:
S1: Document Parsing
S2: Reference Extraction
S3: Claim Extraction
S4: Reference Resolution
S5: Evidence Retrieval
S6: Claim Verification
S7: Assessment
S8: Persistence
"""

import logging
import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.core.db import AsyncSessionLocal
from app.core.event_bus import event_bus
from app.core.jobs import job_registry
from app.repositories.events import EventRepository
from app.repositories.jobs import JobRepository
from app.stages.s1_parse import run_stage_1, S1ParseInput
from app.stages.s2_references import run_stage_2, S2ReferencesInput
from app.stages.s3_claims import run_stage_3, S3ClaimsInput
from app.stages.s4_resolve import run_stage_4, S4ResolveInput
from app.stages.s5_evidence import run_stage_5, S5EvidenceInput
from app.stages.s6_verify import run_stage_6, S6VerifyInput
from app.stages.s7_assessment import run_stage_7, S7AssessmentInput
from app.stages.s8_persist import run_stage_8, S8PersistInput

logger = logging.getLogger("citeverify.pipeline")


class PipelineExecutionContract(BaseModel):
    document_id: str
    job_id: str
    status: str
    stages_executed: list[str] = []
    is_mock_run: bool = True
    summary: Optional[Dict[str, Any]] = None


class VerificationOrchestrator:
    """Orchestrates the 8-stage verification workflow.

    Defines the contract and execution sequence without fabricating fake verification output.
    """

    STAGES = [
        ("s1_parse", run_stage_1),
        ("s2_references", run_stage_2),
        ("s3_claims", run_stage_3),
        ("s4_resolve", run_stage_4),
        ("s5_evidence", run_stage_5),
        ("s6_verify", run_stage_6),
        ("s7_assessment", run_stage_7),
        ("s8_persist", run_stage_8),
    ]

    async def _emit_stage_progress(self, document_id: str, job_id: str, stage: str, progress: float, message: str) -> None:
        job_registry.update_stage(job_id, stage, progress)
        evt_id = str(uuid.uuid4())
        await event_bus.publish(document_id, {
            "id": evt_id,
            "event": "stage",
            "stage": stage,
            "document_id": document_id,
            "job_id": job_id,
            "message": message,
            "progress": progress,
        })
        try:
            async with AsyncSessionLocal() as session:
                job_repo = JobRepository(session)
                existing = await job_repo.get_by_id(job_id)
                if existing:
                    await job_repo.update_progress(job_id, stage=stage, progress=progress, status="running")
                event_repo = EventRepository(session)
                await event_repo.append_event(
                    document_id=document_id,
                    job_id=job_id,
                    stage=stage,
                    event_type="stage",
                    message=message,
                    payload={"progress": progress, "stage": stage},
                    event_id=evt_id,
                )
                await session.commit()
        except Exception as exc:
            logger.debug(f"Stage progress event persistence skipped for {job_id}: {exc}")

    async def _emit_completion(self, document_id: str, job_id: str) -> None:
        job_registry.mark_completed(job_id)
        evt_id = str(uuid.uuid4())
        await event_bus.publish(document_id, {
            "id": evt_id,
            "event": "done",
            "document_id": document_id,
            "job_id": job_id,
            "message": "Verification pipeline completed successfully.",
            "progress": 100.0,
        })
        try:
            async with AsyncSessionLocal() as session:
                job_repo = JobRepository(session)
                existing = await job_repo.get_by_id(job_id)
                if existing:
                    await job_repo.mark_completed(job_id)
                event_repo = EventRepository(session)
                await event_repo.append_event(
                    document_id=document_id,
                    job_id=job_id,
                    stage="s8_persist",
                    event_type="done",
                    message="Verification pipeline completed successfully.",
                    payload={"progress": 100.0, "status": "completed"},
                    event_id=evt_id,
                )
                await session.commit()
        except Exception as exc:
            logger.debug(f"Completion event persistence skipped for {job_id}: {exc}")

    async def _emit_failure(self, document_id: str, job_id: str, stage: str, exc: Exception) -> None:
        job_registry.mark_failed(job_id, str(exc))
        evt_id = str(uuid.uuid4())
        await event_bus.publish(document_id, {
            "id": evt_id,
            "event": "error",
            "stage": stage,
            "document_id": document_id,
            "job_id": job_id,
            "message": str(exc),
            "fatal": True,
        })
        try:
            async with AsyncSessionLocal() as session:
                job_repo = JobRepository(session)
                existing = await job_repo.get_by_id(job_id)
                if existing:
                    await job_repo.mark_failed(job_id, error_message=str(exc))
                event_repo = EventRepository(session)
                await event_repo.append_event(
                    document_id=document_id,
                    job_id=job_id,
                    stage=stage,
                    event_type="error",
                    message=f"Pipeline error at stage {stage}: {exc}",
                    payload={"error": str(exc), "stage": stage, "fatal": True},
                    event_id=evt_id,
                )
                await session.commit()
        except Exception as err:
            logger.debug(f"Failure event persistence skipped for {job_id}: {err}")

    async def execute(self, document_id: str, job_id: str, file_path: str = "") -> PipelineExecutionContract:
        """Sequential skeleton execution of pipeline stages.

        Updates job registry status at each stage transition.
        """
        logger.info(f"Starting pipeline orchestration for document {document_id}, job {job_id}")
        executed_stages = []
        current_stage = "initialization"

        try:
            # Stage 1: Parse
            current_stage = "s1_parse"
            await self._emit_stage_progress(document_id, job_id, "s1_parse", 12.5, "Parsing document sections")
            s1_out = await run_stage_1(S1ParseInput(document_id=document_id, file_path=file_path))
            executed_stages.append("s1_parse")

            # Stage 2: Extract References
            current_stage = "s2_references"
            await self._emit_stage_progress(document_id, job_id, "s2_references", 25.0, "Extracting bibliography references")
            s2_out = await run_stage_2(S2ReferencesInput(
                document_id=document_id,
                raw_text=s1_out.raw_text,
                sections=s1_out.sections,
            ))
            executed_stages.append("s2_references")

            # Stage 3: Extract Claims
            current_stage = "s3_claims"
            await self._emit_stage_progress(document_id, job_id, "s3_claims", 37.5, "Extracting verifiable claims")
            s3_out = await run_stage_3(S3ClaimsInput(
                document_id=document_id,
                sections=s1_out.sections,
                references=[r.model_dump() for r in s2_out.references]
            ))
            executed_stages.append("s3_claims")

            # Stage 4: Resolve References
            current_stage = "s4_resolve"
            await self._emit_stage_progress(document_id, job_id, "s4_resolve", 50.0, "Resolving references against academic metadata")
            s4_out = await run_stage_4(S4ResolveInput(
                document_id=document_id,
                raw_citations=[r.model_dump() for r in s2_out.references]
            ))
            executed_stages.append("s4_resolve")

            # Stage 5: Evidence Retrieval
            current_stage = "s5_evidence"
            await self._emit_stage_progress(document_id, job_id, "s5_evidence", 62.5, "Retrieving cited source evidence passages")
            s5_out = await run_stage_5(S5EvidenceInput(
                document_id=document_id,
                resolved_references=[r.model_dump() if hasattr(r, "model_dump") else r for r in s4_out.resolved_references],
                claims=[c.model_dump() for c in s3_out.claims]
            ))
            executed_stages.append("s5_evidence")

            # Stage 6: Claim Verification
            current_stage = "s6_verify"
            await self._emit_stage_progress(document_id, job_id, "s6_verify", 75.0, "Verifying claims against cited evidence")

            # Map S4 resolved references by citation_key or id using stable identifiers
            resolved_ref_map = {}
            for ref in s4_out.resolved_references:
                ref_dict = ref.model_dump() if hasattr(ref, "model_dump") else dict(ref)
                if ref_dict.get("citation_key"):
                    resolved_ref_map[ref_dict["citation_key"].strip()] = ref_dict
                if ref_dict.get("id"):
                    resolved_ref_map[ref_dict["id"].strip()] = ref_dict

            # Enrich claims with S4 metadata (DOI, year, retraction status) without title-based guessing
            enriched_claims = []
            for c in s3_out.claims:
                c_dict = c.model_dump() if hasattr(c, "model_dump") else dict(c)
                matched_ref = None
                if c_dict.get("reference_id") and c_dict["reference_id"] in resolved_ref_map:
                    matched_ref = resolved_ref_map[c_dict["reference_id"]]
                elif c_dict.get("citation_key") and c_dict["citation_key"] in resolved_ref_map:
                    matched_ref = resolved_ref_map[c_dict["citation_key"]]
                elif c_dict.get("all_citation_keys"):
                    for ck in c_dict["all_citation_keys"]:
                        if ck in resolved_ref_map:
                            matched_ref = resolved_ref_map[ck]
                            break

                if matched_ref:
                    if matched_ref.get("doi"):
                        c_dict["reference_doi"] = matched_ref["doi"]
                    if matched_ref.get("year"):
                        c_dict["reference_year"] = matched_ref["year"]
                    if matched_ref.get("title"):
                        c_dict["reference_title"] = matched_ref["title"]
                    if "is_retracted" in matched_ref:
                        c_dict["is_retracted"] = matched_ref["is_retracted"]
                    if matched_ref.get("retraction_notice"):
                        c_dict["retraction_notice"] = matched_ref["retraction_notice"]
                    if matched_ref.get("doi_title_mismatch"):
                        c_dict["doi_title_mismatch"] = matched_ref["doi_title_mismatch"]
                    if matched_ref.get("pmcid"):
                        c_dict["reference_pmcid"] = matched_ref["pmcid"]
                enriched_claims.append(c_dict)

            s6_out = await run_stage_6(S6VerifyInput(
                document_id=document_id,
                claims=enriched_claims,
                evidences=[e.model_dump() for e in s5_out.evidence_items],
                resolved_references=[r.model_dump() if hasattr(r, "model_dump") else r for r in s4_out.resolved_references]
            ))
            executed_stages.append("s6_verify")

            # Stage 7: Assessment
            current_stage = "s7_assessment"
            await self._emit_stage_progress(document_id, job_id, "s7_assessment", 87.5, "Synthesizing document verification assessment")
            s7_out = await run_stage_7(S7AssessmentInput(
                document_id=document_id,
                results=[r.model_dump() for r in s6_out.results],
                claims=enriched_claims,
                resolved_references=[r.model_dump() if hasattr(r, "model_dump") else r for r in s4_out.resolved_references],
            ))
            executed_stages.append("s7_assessment")

            # Stage 8: Persistence
            current_stage = "s8_persist"
            await self._emit_stage_progress(document_id, job_id, "s8_persist", 95.0, "Persisting verification results to database")
            s8_out = await run_stage_8(S8PersistInput(
                document_id=document_id,
                job_id=job_id,
                s1_parse=s1_out,
                s2_references=s2_out,
                s3_claims=s3_out,
                s4_resolve=s4_out,
                s5_evidence=s5_out,
                s6_verify=s6_out,
                s7_assessment=s7_out,
            ))

            if not s8_out.persisted or s8_out.status != "completed":
                raise RuntimeError(
                    f"Stage 8 persistence failed for document '{document_id}': status='{s8_out.status}'"
                )

            executed_stages.append("s8_persist")

            # Mark 100% completed only AFTER S8 finishes successfully
            await self._emit_completion(document_id, job_id)

            return PipelineExecutionContract(
                document_id=document_id,
                job_id=job_id,
                status="completed",
                stages_executed=executed_stages,
                is_mock_run=True,
                summary=s7_out.summary,
            )

        except Exception as exc:
            logger.error(f"Pipeline orchestration error at stage '{current_stage}': {exc}", exc_info=True)
            await self._emit_failure(document_id, job_id, current_stage, exc)
            return PipelineExecutionContract(
                document_id=document_id,
                job_id=job_id,
                status="failed",
                stages_executed=executed_stages,
                is_mock_run=True,
                summary={"error": str(exc), "failed_stage": current_stage},
            )


orchestrator = VerificationOrchestrator()
