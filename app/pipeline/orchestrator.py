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
from typing import Any, Dict, Optional
from pydantic import BaseModel

from app.core.jobs import job_registry
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

    async def execute(self, document_id: str, job_id: str, file_path: str = "") -> PipelineExecutionContract:
        """Sequential skeleton execution of pipeline stages.

        Updates job registry status at each stage transition.
        """
        logger.info(f"Starting pipeline orchestration for document {document_id}, job {job_id}")
        executed_stages = []

        try:
            # Stage 1: Parse
            job_registry.update_stage(job_id, "s1_parse", 12.5)
            s1_out = await run_stage_1(S1ParseInput(document_id=document_id, file_path=file_path))
            executed_stages.append("s1_parse")

            # Stage 2: Extract References
            job_registry.update_stage(job_id, "s2_references", 25.0)
            s2_out = await run_stage_2(S2ReferencesInput(
                document_id=document_id,
                raw_text=s1_out.raw_text,
                sections=s1_out.sections,
            ))
            executed_stages.append("s2_references")

            # Stage 3: Extract Claims
            job_registry.update_stage(job_id, "s3_claims", 37.5)
            s3_out = await run_stage_3(S3ClaimsInput(
                document_id=document_id,
                sections=s1_out.sections,
                references=[r.model_dump() for r in s2_out.references]
            ))
            executed_stages.append("s3_claims")

            # Stage 4: Resolve References
            job_registry.update_stage(job_id, "s4_resolve", 50.0)
            s4_out = await run_stage_4(S4ResolveInput(
                document_id=document_id,
                raw_citations=[r.model_dump() for r in s2_out.references]
            ))
            executed_stages.append("s4_resolve")

            # Stage 5: Evidence Retrieval
            job_registry.update_stage(job_id, "s5_evidence", 62.5)
            s5_out = await run_stage_5(S5EvidenceInput(
                document_id=document_id,
                resolved_references=[r.model_dump() if hasattr(r, "model_dump") else r for r in s4_out.resolved_references],
                claims=[c.model_dump() for c in s3_out.claims]
            ))
            executed_stages.append("s5_evidence")

            # Stage 6: Claim Verification
            job_registry.update_stage(job_id, "s6_verify", 75.0)

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
            job_registry.update_stage(job_id, "s7_assessment", 87.5)
            s7_out = await run_stage_7(S7AssessmentInput(
                document_id=document_id,
                results=[r.model_dump() for r in s6_out.results],
                claims=enriched_claims,
                resolved_references=[r.model_dump() if hasattr(r, "model_dump") else r for r in s4_out.resolved_references],
            ))
            executed_stages.append("s7_assessment")

            # Stage 8: Persistence
            job_registry.update_stage(job_id, "s8_persist", 100.0)
            s8_out = await run_stage_8(S8PersistInput(
                document_id=document_id,
                assessment_data=s7_out.model_dump()
            ))
            executed_stages.append("s8_persist")

            job_registry.mark_completed(job_id)

            return PipelineExecutionContract(
                document_id=document_id,
                job_id=job_id,
                status="completed",
                stages_executed=executed_stages,
                is_mock_run=True,
                summary=s7_out.summary,
            )

        except Exception as exc:
            logger.error(f"Pipeline orchestration error: {exc}", exc_info=True)
            job_registry.mark_failed(job_id, str(exc))
            return PipelineExecutionContract(
                document_id=document_id,
                job_id=job_id,
                status="failed",
                stages_executed=executed_stages,
                is_mock_run=True,
                summary={"error": str(exc)},
            )


orchestrator = VerificationOrchestrator()
