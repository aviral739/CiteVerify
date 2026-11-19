"""Reference hygiene checks and validation."""

from typing import List
from app.stages.s2_references.models import (
    ExtractedReferenceItem,
    HygieneCheckReport,
    InTextCitationMarker,
)


def run_reference_hygiene_checks(
    references: List[ExtractedReferenceItem],
    citations: List[InTextCitationMarker],
    missing_bib: bool = False,
) -> HygieneCheckReport:
    """Execute quality checks on extracted references and citations."""
    report = HygieneCheckReport(missing_bibliography_section=missing_bib)

    if missing_bib:
        report.warnings.append("No bibliography/references section was detected in the document.")
        return report

    seen_dois = {}
    seen_titles = {}

    for ref in references:
        # 1. Missing DOI warning (Warning only, not an error)
        if not ref.doi:
            report.missing_dois.append(ref.citation_key)

        # 2. Duplicate DOI check
        if ref.doi:
            norm_doi = ref.doi.lower().strip()
            if norm_doi in seen_dois:
                dup_str = f"Duplicate DOI '{norm_doi}' found in {seen_dois[norm_doi]} and {ref.citation_key}"
                report.duplicate_dois.append(dup_str)
            else:
                seen_dois[norm_doi] = ref.citation_key

        # 3. Duplicate title / entry check
        if ref.title and len(ref.title) > 10:
            norm_title = "".join(ch for ch in ref.title.lower() if ch.isalnum())
            if norm_title in seen_titles:
                dup_ref_str = f"Potential duplicate reference between {seen_titles[norm_title]} and {ref.citation_key} ('{ref.title}')"
                report.potential_duplicate_references.append(dup_ref_str)
            else:
                seen_titles[norm_title] = ref.citation_key

        # 4. Malformed reference entry check (e.g. suspiciously short or unparseable)
        if len(ref.raw_citation.strip()) < 15 or (not ref.title and not ref.authors and not ref.year):
            report.malformed_entries.append(f"{ref.citation_key}: {ref.raw_citation}")

        # 5. Bibliography entry never cited in text
        if not ref.is_cited_in_text:
            report.uncited_bibliography_entries.append(ref.citation_key)

    # 6. Unmatched in-text citations
    for cit in citations:
        if not cit.is_associated:
            report.unmatched_in_text_citations.append(cit.raw_citation)
            if cit.style.value == "author_year":
                report.unresolved_author_year_matches.append(cit.raw_citation)

    # Aggregate summaries
    if report.duplicate_dois:
        report.warnings.append(f"Detected {len(report.duplicate_dois)} duplicate DOI(s).")
    if report.potential_duplicate_references:
        report.warnings.append(f"Detected {len(report.potential_duplicate_references)} potential duplicate reference(s).")
    if report.uncited_bibliography_entries:
        report.warnings.append(f"{len(report.uncited_bibliography_entries)} reference(s) appear in bibliography but are not cited in manuscript text.")
    if report.unmatched_in_text_citations:
        report.warnings.append(f"{len(report.unmatched_in_text_citations)} in-text citation(s) could not be linked to bibliography entries.")

    return report
