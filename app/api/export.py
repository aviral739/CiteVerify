"""Document export endpoints for JSON, CSV, BibTeX, and Markdown."""

import csv
import io
from typing import Any, Dict
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.exceptions import DocumentNotFoundError
from app.models.schemas import ExportResponse
from app.repositories.reports import DocumentReportRepository

router = APIRouter(prefix="/api/documents", tags=["export"])


@router.get("/{id}/export", response_model=ExportResponse)
async def export_document_data(
    id: str,
    format: str = Query("json", description="Export format: json, csv, bibtex, markdown"),
    db: AsyncSession = Depends(get_db),
):
    """Export document verification data in requested format."""
    report_repo = DocumentReportRepository(db)
    report = await report_repo.build_document_report(id)
    if not report:
        raise DocumentNotFoundError(id)

    doc = report.document
    format_clean = format.lower().strip()

    if format_clean == "csv":
        out = io.StringIO()
        writer = csv.writer(out, quoting=csv.QUOTE_MINIMAL)
        # Header
        writer.writerow([
            "document_id",
            "document_title",
            "claim_id",
            "section_name",
            "citation_key",
            "claim_text",
            "verdict",
            "verdict_strength",
            "retrieval_match",
            "evidence_completeness",
            "reference_title",
            "resolved_doi",
            "evidence_quote",
            "needs_review",
            "human_decision",
            "human_verdict",
            "human_notes",
        ])

        if report.results:
            for r in report.results:
                c = r.claim
                ref = r.reference
                review = r.reviews[0] if r.reviews else None
                needs_review = r.verdict.value in ("insufficient_evidence", "unsupported", "contradictory")
                writer.writerow([
                    doc.id,
                    doc.title,
                    r.claim_id,
                    c.section_name if c else "",
                    ref.citation_key if ref and ref.citation_key else "",
                    c.claim_text if c else "",
                    r.verdict.value,
                    f"{r.verdict_strength:.2f}",
                    f"{r.retrieval_match:.2f}",
                    r.evidence_completeness.value,
                    ref.resolved_title if ref and ref.resolved_title else (ref.raw_citation if ref else ""),
                    ref.resolved_doi if ref and ref.resolved_doi else "",
                    r.evidence_quote or "",
                    "YES" if needs_review else "NO",
                    review.human_decision.value if review else "",
                    review.human_verdict.value if review and review.human_verdict else "",
                    review.notes if review and review.notes else "",
                ])
        else:
            from app.repositories.claims import ClaimRepository
            claim_repo = ClaimRepository(db)
            doc_claims = await claim_repo.get_by_document(id)
            for c in doc_claims:
                writer.writerow([
                    doc.id,
                    doc.title,
                    c.id,
                    c.section_name or "",
                    "",
                    c.claim_text,
                    "pending",
                    "0.00",
                    "0.00",
                    "unavailable",
                    "",
                    "",
                    "",
                    "YES",
                    "",
                    "",
                    "",
                ])

        csv_text = out.getvalue()
        return ExportResponse(
            document_id=id,
            export_format="csv",
            content=csv_text,
            data={
                "content": csv_text,
                "document_id": doc.id,
                "title": doc.title,
                "total_rows": len(report.results),
            },
        )

    elif format_clean == "markdown":
        md_lines = [
            f"# Verification Report: {doc.title}",
            f"**Document ID:** `{doc.id}`  ",
            f"**Status:** {report.status_note}  ",
            f"**Total References:** {report.total_references} | **Total Claims:** {report.total_claims} | **Results:** {report.total_results}\n",
            "## Verification Results\n",
        ]
        for idx, r in enumerate(report.results, start=1):
            c = r.claim
            ref = r.reference
            md_lines.append(f"### Claim {idx}: {r.verdict.value.upper()}")
            md_lines.append(f"> \"{c.claim_text if c else 'N/A'}\"\n")
            if ref:
                md_lines.append(f"- **Citation:** {ref.citation_key or '[?]'} {ref.resolved_title or ref.raw_citation}")
                if ref.resolved_doi:
                    md_lines.append(f"- **DOI:** https://doi.org/{ref.resolved_doi}")
            md_lines.append(f"- **Verdict Strength:** {r.verdict_strength * 100:.1f}%")
            md_lines.append(f"- **Retrieval Match:** {r.retrieval_match * 100:.1f}%")
            if r.evidence_quote:
                md_lines.append(f"- **Evidence Quote:** \"{r.evidence_quote}\"")
            md_lines.append("")

        md_text = "\n".join(md_lines)
        return ExportResponse(
            document_id=id,
            export_format="markdown",
            content=md_text,
            data={"content": md_text, "document_id": doc.id, "title": doc.title},
        )

    # Default to json
    report_dict = report.model_dump(mode="json")
    return ExportResponse(
        document_id=id,
        export_format="json",
        content=None,
        data=report_dict,
    )

