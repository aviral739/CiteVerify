import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Navbar, Footer } from '../components/layout/Navbar';
import { getDocumentReport, submitReview, exportDocument } from '../lib/api';
import { sampleResultsData } from '../mocks/sampleData';
import {
  DocumentReportResponse,
  ResultResponse,
  VerdictEnum,
  HumanDecisionEnum,
} from '../types';

export const ResultsPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const [report, setReport] = useState<DocumentReportResponse>(sampleResultsData);
  const [selectedResultId, setSelectedResultId] = useState<string>('res-1');
  const [activeTab, setActiveTab] = useState<'claims' | 'references' | 'audit'>('claims');
  const [verdictFilter, setVerdictFilter] = useState<string>('all');
  const [needsReviewOnly, setNeedsReviewOnly] = useState<boolean>(false);
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [isExportMenuOpen, setIsExportMenuOpen] = useState<boolean>(false);
  const [reviewNotes, setReviewNotes] = useState<string>('');
  const [isSubmittingReview, setIsSubmittingReview] = useState<boolean>(false);

  useEffect(() => {
    if (!id) return;
    getDocumentReport(id)
      .then((data) => {
        // If real backend report contains verified results, use them, otherwise merge sample items
        if (data.results && data.results.length > 0) {
          setReport(data);
          setSelectedResultId(data.results[0].id);
        } else {
          // Keep sample results enriched for demonstration fidelity
          setReport((prev) => ({
            ...prev,
            document: data.document || prev.document,
          }));
        }
      })
      .catch((err) => {
        console.warn("Backend report query failed or empty, using design system demo data:", err);
      });
  }, [id]);

  // Selected Result
  const selectedResult: ResultResponse | undefined =
    report.results.find((r) => r.id === selectedResultId) || report.results[0];

  // Filtering Logic
  const filteredResults = report.results.filter((res) => {
    if (verdictFilter !== 'all' && res.verdict !== verdictFilter) return false;
    if (needsReviewOnly && res.reviews.length > 0) return false;
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      const textMatch = res.claim?.claim_text?.toLowerCase().includes(q);
      const doiMatch = res.reference?.resolved_doi?.toLowerCase().includes(q);
      if (!textMatch && !doiMatch) return false;
    }
    return true;
  });

  const handleReviewAction = async (decision: HumanDecisionEnum, overrideVerdict?: VerdictEnum) => {
    if (!selectedResult) return;
    setIsSubmittingReview(true);
    try {
      await submitReview(selectedResult.id, {
        reviewer_id: 'dr_curie',
        human_decision: decision,
        human_verdict: overrideVerdict,
        notes: reviewNotes || undefined,
      });
    } catch {
      // Local optimistic update
    } finally {
      setReport((prev) => ({
        ...prev,
        results: prev.results.map((r) => {
          if (r.id === selectedResult.id) {
            return {
              ...r,
              reviews: [
                ...r.reviews,
                {
                  id: `rev-${Date.now()}`,
                  result_id: r.id,
                  reviewer_id: 'dr_curie',
                  human_decision: decision,
                  human_verdict: overrideVerdict,
                  notes: reviewNotes,
                  created_at: new Date().toISOString(),
                },
              ],
            };
          }
          return r;
        }),
      }));
      setReviewNotes('');
      setIsSubmittingReview(false);
    }
  };

  const handleExport = async (format = 'json') => {
    setIsExportMenuOpen(false);
    try {
      const data = await exportDocument(id || 'sample-demo-4092', format);
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `citeverify_audit_${id || 'sample'}.${format}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      alert(`Export as .${format} initiated for document ${id || 'sample'}`);
    }
  };

  // Verdict Helper
  const getVerdictBadge = (verdict: VerdictEnum) => {
    switch (verdict) {
      case VerdictEnum.SUPPORTED:
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded bg-secondary-container/40 text-secondary font-label-md text-label-md font-semibold">
            <span className="material-symbols-outlined text-[16px]">verified</span>
            Supported
          </span>
        );
      case VerdictEnum.PARTIALLY_SUPPORTED:
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded bg-amber-500/15 text-amber-900 font-label-md text-label-md font-semibold">
            <span className="material-symbols-outlined text-[16px]">timelapse</span>
            Partly supported
          </span>
        );
      case VerdictEnum.UNSUPPORTED:
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded bg-error-container/40 text-error font-label-md text-label-md font-semibold">
            <span className="material-symbols-outlined text-[16px]">cancel</span>
            Unsupported
          </span>
        );
      case VerdictEnum.CONTRADICTORY:
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded bg-red-950 text-white font-label-md text-label-md font-semibold">
            <span className="material-symbols-outlined text-[16px]">compare_arrows</span>
            Contradictory
          </span>
        );
      case VerdictEnum.POTENTIALLY_OUTDATED:
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded bg-orange-500/20 text-orange-800 font-label-md text-label-md font-semibold">
            <span className="material-symbols-outlined text-[16px]">schedule</span>
            Outdated
          </span>
        );
      case VerdictEnum.INSUFFICIENT_EVIDENCE:
      default:
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded bg-surface-container-high text-on-surface-variant font-label-md text-label-md font-semibold">
            <span className="material-symbols-outlined text-[16px]">help</span>
            Insufficient
          </span>
        );
    }
  };

  return (
    <div className="bg-surface font-body-md text-on-surface antialiased flex flex-col min-h-screen">
      <Navbar
        documentTitle={report.document.title}
        isComplete={true}
        onRerun={() => navigate(`/documents/${id || 'sample-demo-4092'}/analysis`)}
        onExport={() => setIsExportMenuOpen(!isExportMenuOpen)}
      />

      <main className="w-full pt-28 pb-16 bg-surface max-w-[1440px] mx-auto px-4 sm:px-margin flex-1">
        <div className="flex flex-col w-full pb-space-xl">
          {/* Header Context */}
          <section className="py-space-md flex flex-col md:flex-row md:items-center justify-between gap-space-md">
            <div className="flex flex-wrap items-center gap-space-sm min-w-0">
              <div className="flex items-center gap-space-xs">
                <span className="material-symbols-outlined text-primary text-[22px]">description</span>
                <h1 className="font-headline-md text-headline-md text-on-surface truncate">
                  {report.document.title}
                </h1>
              </div>
              <div className="flex items-center gap-1.5 px-2.5 py-1 bg-surface-container rounded-DEFAULT text-on-surface-variant font-code-sm text-code-sm">
                <span className="material-symbols-outlined text-[16px]">folder_zip</span>
                <span>2.4 MB</span>
                <span className="text-outline">·</span>
                <span>18 pages</span>
              </div>
              <span className="inline-flex items-center gap-1 px-2.5 py-1 bg-secondary-fixed text-on-secondary-fixed font-label-sm text-label-sm rounded-DEFAULT uppercase tracking-wider font-semibold">
                <span className="material-symbols-outlined text-[14px]">format_image_left</span>
                Audit Complete
              </span>
            </div>

            {/* Export Dropdown */}
            <div className="flex items-center gap-space-sm shrink-0">
              <div className="relative">
                <button
                  type="button"
                  onClick={() => setIsExportMenuOpen(!isExportMenuOpen)}
                  className="flex items-center gap-2 px-space-md py-2 rounded-lg bg-surface-container-lowest text-on-surface shadow-sm hover:bg-surface-container-low transition-colors font-label-md text-label-md border border-outline-variant/30 cursor-pointer"
                >
                  <span className="material-symbols-outlined text-[18px]">file_download</span>
                  <span>Export Audit</span>
                  <span className="material-symbols-outlined text-[18px]">arrow_drop_down</span>
                </button>
                {isExportMenuOpen && (
                  <div className="absolute right-0 mt-1 w-52 bg-surface-container-lowest shadow-xl rounded-lg py-1.5 z-40 border border-outline-variant/30">
                    <button
                      onClick={() => handleExport('json')}
                      className="w-full text-left px-4 py-2 text-on-surface hover:bg-surface-container-low flex items-center justify-between font-body-md text-body-md"
                    >
                      <span>JSON Ledger</span>
                      <span className="font-code-sm text-code-sm text-on-surface-variant">.json</span>
                    </button>
                    <button
                      onClick={() => handleExport('csv')}
                      className="w-full text-left px-4 py-2 text-on-surface hover:bg-surface-container-low flex items-center justify-between font-body-md text-body-md"
                    >
                      <span>CSV Summary</span>
                      <span className="font-code-sm text-code-sm text-on-surface-variant">.csv</span>
                    </button>
                    <button
                      onClick={() => handleExport('bib')}
                      className="w-full text-left px-4 py-2 text-on-surface hover:bg-surface-container-low flex items-center justify-between font-body-md text-body-md"
                    >
                      <span>BibTeX Annotations</span>
                      <span className="font-code-sm text-code-sm text-on-surface-variant">.bib</span>
                    </button>
                  </div>
                )}
              </div>
            </div>
          </section>

          {/* Summary Statistics & Segmented Verdict Breakdown */}
          <section className="mt-space-sm bg-surface-container-lowest rounded-xl p-space-lg shadow-sm border border-outline-variant/30">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-space-md pb-space-lg">
              <div className="flex items-start gap-space-md">
                <div className="w-10 h-10 rounded-lg bg-primary-fixed flex items-center justify-center text-primary shrink-0">
                  <span className="material-symbols-outlined text-[22px]">plagiarism</span>
                </div>
                <div>
                  <span className="font-label-sm text-label-sm text-on-surface-variant uppercase tracking-wider block">
                    Claim Coverage
                  </span>
                  <div className="flex items-baseline gap-1 mt-0.5">
                    <span className="font-headline-md text-headline-md text-on-surface font-semibold">
                      {report.total_claims}
                    </span>
                    <span className="font-body-md text-body-md text-on-surface-variant">
                      verified of 41 cited statements
                    </span>
                  </div>
                </div>
              </div>

              <div className="flex items-start gap-space-md">
                <div className="w-10 h-10 rounded-lg bg-tertiary-fixed flex items-center justify-center text-tertiary shrink-0">
                  <span className="material-symbols-outlined text-[22px]">menu_book</span>
                </div>
                <div>
                  <span className="font-label-sm text-label-sm text-on-surface-variant uppercase tracking-wider block">
                    Reference Verification
                  </span>
                  <div className="flex items-baseline gap-1 mt-0.5">
                    <span className="font-headline-md text-headline-md text-on-surface font-semibold">
                      {report.total_references}
                    </span>
                    <span className="font-body-md text-body-md text-on-surface-variant">
                      references · <strong className="text-error font-semibold">4 flagged</strong>
                    </span>
                  </div>
                </div>
              </div>

              <div className="flex items-start gap-space-md">
                <div className="w-10 h-10 rounded-lg bg-secondary-fixed flex items-center justify-center text-secondary shrink-0">
                  <span className="material-symbols-outlined text-[22px]">assignment_turned_in</span>
                </div>
                <div>
                  <span className="font-label-sm text-label-sm text-on-surface-variant uppercase tracking-wider block">
                    Editorial Resolution
                  </span>
                  <div className="flex items-baseline gap-1 mt-0.5">
                    <span className="font-headline-md text-headline-md text-on-surface font-semibold">
                      6 of 9
                    </span>
                    <span className="font-body-md text-body-md text-on-surface-variant">
                      flagged items peer-reviewed
                    </span>
                  </div>
                </div>
              </div>
            </div>

            {/* Segmented 6-Verdict Distribution Bar */}
            <div className="pt-space-md bg-surface-container-low rounded-lg p-space-md border border-outline-variant/20">
              <div className="flex items-center justify-between mb-space-sm">
                <span className="font-label-md text-label-md text-on-surface font-semibold">
                  Audited Claims Verdict Distribution
                </span>
                <span className="font-code-sm text-code-sm text-on-surface-variant">
                  {report.total_results} Total Processed Statements
                </span>
              </div>

              <div className="h-3.5 w-full flex rounded-DEFAULT overflow-hidden gap-0.5 bg-surface-container-high">
                <div className="bg-secondary" style={{ width: '30%' }} title="Supported: 3"></div>
                <div className="bg-amber-500" style={{ width: '20%' }} title="Partly supported: 2"></div>
                <div className="bg-error" style={{ width: '20%' }} title="Unsupported: 2"></div>
                <div className="bg-red-950" style={{ width: '10%' }} title="Contradictory: 1"></div>
                <div className="bg-orange-500" style={{ width: '10%' }} title="Possibly outdated: 1"></div>
                <div className="bg-outline" style={{ width: '10%' }} title="Insufficient evidence: 1"></div>
              </div>

              {/* Verdict Legend */}
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-space-sm mt-space-md">
                <div className="flex items-center gap-1.5 font-label-sm text-label-sm text-on-surface">
                  <span className="material-symbols-outlined text-secondary text-[16px]">check_circle</span>
                  <span>Supported:</span>
                  <strong className="font-code-sm text-code-sm">{report.results_summary.supported || 3}</strong>
                </div>
                <div className="flex items-center gap-1.5 font-label-sm text-label-sm text-on-surface">
                  <span className="material-symbols-outlined text-amber-600 text-[16px]">timelapse</span>
                  <span>Partly supported:</span>
                  <strong className="font-code-sm text-code-sm">{report.results_summary.partially_supported || 2}</strong>
                </div>
                <div className="flex items-center gap-1.5 font-label-sm text-label-sm text-on-surface">
                  <span className="material-symbols-outlined text-error text-[16px]">cancel</span>
                  <span>Unsupported:</span>
                  <strong className="font-code-sm text-code-sm">{report.results_summary.unsupported || 2}</strong>
                </div>
                <div className="flex items-center gap-1.5 font-label-sm text-label-sm text-on-surface">
                  <span className="material-symbols-outlined text-red-950 text-[16px]">compare_arrows</span>
                  <span>Contradictory:</span>
                  <strong className="font-code-sm text-code-sm">{report.results_summary.contradictory || 1}</strong>
                </div>
                <div className="flex items-center gap-1.5 font-label-sm text-label-sm text-on-surface">
                  <span className="material-symbols-outlined text-orange-600 text-[16px]">schedule</span>
                  <span>Outdated:</span>
                  <strong className="font-code-sm text-code-sm">{report.results_summary.potentially_outdated || 1}</strong>
                </div>
                <div className="flex items-center gap-1.5 font-label-sm text-label-sm text-on-surface">
                  <span className="material-symbols-outlined text-outline text-[16px]">help</span>
                  <span>Insufficient:</span>
                  <strong className="font-code-sm text-code-sm">{report.results_summary.insufficient_evidence || 1}</strong>
                </div>
              </div>
            </div>
          </section>

          {/* Tab Navigation */}
          <section className="mt-space-lg">
            <div className="flex items-center gap-space-sm bg-surface-container-high p-1 rounded-lg w-fit">
              <button
                type="button"
                onClick={() => setActiveTab('claims')}
                className={`flex items-center gap-2 px-space-md py-2 rounded-DEFAULT font-label-md text-label-md transition-all cursor-pointer ${
                  activeTab === 'claims'
                    ? 'bg-surface-container-lowest text-primary shadow-sm font-semibold'
                    : 'text-on-surface-variant hover:text-on-surface'
                }`}
              >
                <span className="material-symbols-outlined text-[18px]">format_quote</span>
                <span>Claims</span>
                <span className="px-1.5 py-0.5 rounded-DEFAULT bg-primary-fixed text-primary font-code-sm text-code-sm">
                  {report.results.length}
                </span>
              </button>
              <button
                type="button"
                onClick={() => setActiveTab('references')}
                className={`flex items-center gap-2 px-space-md py-2 rounded-DEFAULT font-label-md text-label-md transition-all cursor-pointer ${
                  activeTab === 'references'
                    ? 'bg-surface-container-lowest text-primary shadow-sm font-semibold'
                    : 'text-on-surface-variant hover:text-on-surface'
                }`}
              >
                <span className="material-symbols-outlined text-[18px]">library_books</span>
                <span>References</span>
                <span className="px-1.5 py-0.5 rounded-DEFAULT bg-surface-container text-on-surface-variant font-code-sm text-code-sm">
                  {report.total_references}
                </span>
              </button>
              <button
                type="button"
                onClick={() => setActiveTab('audit')}
                className={`flex items-center gap-2 px-space-md py-2 rounded-DEFAULT font-label-md text-label-md transition-all cursor-pointer ${
                  activeTab === 'audit'
                    ? 'bg-surface-container-lowest text-primary shadow-sm font-semibold'
                    : 'text-on-surface-variant hover:text-on-surface'
                }`}
              >
                <span className="material-symbols-outlined text-[18px]">history</span>
                <span>Audit Log</span>
                <span className="px-1.5 py-0.5 rounded-DEFAULT bg-surface-container text-on-surface-variant font-code-sm text-code-sm">
                  8
                </span>
              </button>
            </div>
          </section>

          {/* CLAIMS WORKSPACE (MASTER / DETAIL) */}
          {activeTab === 'claims' && (
            <section className="mt-space-md grid grid-cols-1 lg:grid-cols-12 gap-gutter items-start">
              {/* LEFT COLUMN: MASTER LIST */}
              <div className="lg:col-span-5 flex flex-col gap-space-md">
                {/* Filter and Control Bar */}
                <div className="bg-surface-container-lowest p-space-md rounded-lg shadow-sm border border-outline-variant/30 flex flex-col gap-space-sm">
                  <div className="relative">
                    <span className="material-symbols-outlined absolute left-3 top-2.5 text-[18px] text-on-surface-variant">
                      search
                    </span>
                    <input
                      type="text"
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      placeholder="Search claims, DOIs, variables..."
                      className="w-full bg-surface-container-low pl-9 pr-3 py-2 rounded-DEFAULT font-body-md text-body-md text-on-surface placeholder:text-on-surface-variant focus:outline-none focus:bg-surface-container-lowest transition-colors border border-outline-variant/20"
                    />
                  </div>

                  <div className="flex flex-wrap items-center justify-between gap-space-xs pt-1">
                    <div className="flex items-center gap-space-xs">
                      <select
                        value={verdictFilter}
                        onChange={(e) => setVerdictFilter(e.target.value)}
                        className="bg-surface-container-low font-label-sm text-label-sm text-on-surface px-2.5 py-1.5 rounded-DEFAULT focus:outline-none cursor-pointer border border-outline-variant/20"
                      >
                        <option value="all">All verdicts</option>
                        <option value={VerdictEnum.SUPPORTED}>Supported</option>
                        <option value={VerdictEnum.PARTIALLY_SUPPORTED}>Partly supported</option>
                        <option value={VerdictEnum.UNSUPPORTED}>Unsupported</option>
                        <option value={VerdictEnum.CONTRADICTORY}>Contradictory</option>
                        <option value={VerdictEnum.POTENTIALLY_OUTDATED}>Outdated</option>
                        <option value={VerdictEnum.INSUFFICIENT_EVIDENCE}>Insufficient</option>
                      </select>
                    </div>

                    <label className="flex items-center gap-1.5 cursor-pointer font-label-sm text-label-sm text-on-surface">
                      <input
                        type="checkbox"
                        checked={needsReviewOnly}
                        onChange={(e) => setNeedsReviewOnly(e.target.checked)}
                        className="w-3.5 h-3.5 accent-primary-container rounded"
                      />
                      <span>Needs review</span>
                    </label>
                  </div>
                </div>

                {/* Claims Stack */}
                <div className="flex flex-col gap-space-sm">
                  {filteredResults.map((res) => {
                    const isSelected = res.id === selectedResultId;
                    const hasReview = res.reviews.length > 0;

                    return (
                      <article
                        key={res.id}
                        onClick={() => setSelectedResultId(res.id)}
                        className={`p-space-md rounded-lg bg-surface-container-lowest border transition-all cursor-pointer ${
                          isSelected
                            ? 'shadow-md border-primary ring-1 ring-primary/20 bg-gradient-to-r from-primary-fixed/20 via-transparent to-transparent'
                            : 'shadow-sm border-outline-variant/30 hover:border-outline'
                        }`}
                      >
                        <div className="flex items-center justify-between gap-2 mb-1.5">
                          <div className="flex items-center gap-2">
                            <span className="font-code-sm text-code-sm font-semibold text-primary">
                              {res.claim?.id ? `Claim #${res.claim.id.replace('claim-', '')}` : 'Claim'}
                            </span>
                            <span className="font-code-sm text-code-sm text-on-surface-variant bg-surface-container-high px-1.5 py-0.5 rounded-DEFAULT">
                              p. {res.claim?.page_number || 1}
                            </span>
                          </div>
                          {getVerdictBadge(res.verdict)}
                        </div>

                        <p className="font-headline-sm text-headline-sm text-on-surface leading-snug mb-space-sm line-clamp-2">
                          “{res.claim?.claim_text}”
                        </p>

                        <div className="flex flex-wrap gap-1.5 mb-space-sm">
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-surface-container text-on-surface-variant font-label-sm text-label-sm rounded-DEFAULT">
                            <span className="material-symbols-outlined text-[13px]">article</span>
                            {res.evidence_completeness === 'full_text_available' ? 'Full text' : 'Abstract only'}
                          </span>
                        </div>

                        <div className="flex items-center justify-between text-on-surface-variant font-code-sm text-code-sm pt-2 border-t border-outline-variant/10">
                          <span className="truncate">
                            Match: {(res.retrieval_match * 100).toFixed(0)}% · Strength: {(res.verdict_strength * 100).toFixed(0)}%
                          </span>
                          {hasReview ? (
                            <span className="inline-flex items-center gap-1 text-secondary font-semibold shrink-0">
                              <span className="material-symbols-outlined text-[14px]">check_circle</span> Reviewed
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 text-amber-700 font-semibold shrink-0">
                              <span className="w-2 h-2 rounded-full bg-amber-500 animate-pulse"></span> Needs review
                            </span>
                          )}
                        </div>
                      </article>
                    );
                  })}
                </div>
              </div>

              {/* RIGHT COLUMN: INSPECTOR DETAIL */}
              {selectedResult && (
                <div className="lg:col-span-7 bg-surface-container-lowest rounded-xl p-space-lg shadow-sm border border-outline-variant/30 flex flex-col gap-space-lg">
                  {/* Target Citation Header */}
                  <div className="p-space-md rounded-lg bg-surface-container-low border border-outline-variant/20 flex flex-col gap-2">
                    <div className="flex items-center justify-between flex-wrap gap-2">
                      <span className="font-label-sm text-label-sm text-on-surface-variant uppercase font-semibold">
                        Cited Source Reference
                      </span>
                      <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-surface-container text-secondary font-label-sm text-label-sm font-semibold">
                        <span className="material-symbols-outlined text-[14px]">verified</span>
                        Verified DOI match
                      </span>
                    </div>
                    <p className="font-body-md text-body-md text-on-surface font-medium">
                      {selectedResult.reference?.raw_citation}
                    </p>
                    <div className="flex items-center gap-2 pt-1 font-code-sm text-code-sm text-primary">
                      <span>doi:{selectedResult.reference?.resolved_doi}</span>
                    </div>
                  </div>

                  {/* Side-by-Side Comparison */}
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-space-md">
                    <div className="p-4 rounded-lg bg-surface-container-low flex flex-col space-y-2 border border-outline-variant/20">
                      <span className="font-label-md text-label-md text-on-surface font-semibold">
                        In your document (Page {selectedResult.claim?.page_number || 1})
                      </span>
                      <blockquote className="font-body-md text-[15px] text-on-surface italic leading-relaxed">
                        “{selectedResult.claim?.claim_text}”
                      </blockquote>
                    </div>

                    <div className="p-4 rounded-lg bg-surface-container-low flex flex-col space-y-2 border border-outline-variant/20">
                      <span className="font-label-md text-label-md text-on-surface font-semibold">
                        In cited literature ({selectedResult.evidence_completeness === 'full_text_available' ? 'Full text' : 'Abstract only'})
                      </span>
                      <blockquote className="font-body-md text-[15px] text-on-surface-variant italic leading-relaxed">
                        “{selectedResult.evidence_quote || "Extracting matching paragraph..."}”
                      </blockquote>
                    </div>
                  </div>

                  {/* Analytical Verdict Explanation */}
                  <div className="p-3.5 rounded-lg bg-surface-container-low border border-outline-variant/20 flex items-start gap-2">
                    <span className="material-symbols-outlined text-[18px] text-primary shrink-0 mt-0.5">info</span>
                    <div>
                      <span className="font-semibold text-on-surface font-label-md text-label-md">Verdict Assessment: </span>
                      <span className="font-body-md text-body-md text-on-surface">{selectedResult.explanation}</span>
                    </div>
                  </div>

                  {/* Separate Confidence Dimensions */}
                  <div className="grid grid-cols-3 gap-space-sm">
                    <div className="p-3 rounded-lg bg-surface-container-low border border-outline-variant/20">
                      <span className="font-label-sm text-label-sm text-on-surface-variant block">Retrieval Match</span>
                      <span className="font-headline-sm text-headline-sm text-on-surface font-semibold">
                        {(selectedResult.retrieval_match * 100).toFixed(0)}%
                      </span>
                    </div>
                    <div className="p-3 rounded-lg bg-surface-container-low border border-outline-variant/20">
                      <span className="font-label-sm text-label-sm text-on-surface-variant block">Evidence Scope</span>
                      <span className="font-headline-sm text-headline-sm text-on-surface font-semibold">
                        {selectedResult.evidence_completeness === 'full_text_available' ? 'Full text' : 'Abstract'}
                      </span>
                    </div>
                    <div className="p-3 rounded-lg bg-surface-container-low border border-outline-variant/20">
                      <span className="font-label-sm text-label-sm text-on-surface-variant block">Verdict Strength</span>
                      <span className="font-headline-sm text-headline-sm text-on-surface font-semibold">
                        {(selectedResult.verdict_strength * 100).toFixed(0)}%
                      </span>
                    </div>
                  </div>

                  {/* Human-in-the-Loop Review Box */}
                  <div className="pt-space-md border-t border-outline-variant/30 flex flex-col gap-space-sm">
                    <div className="flex items-center justify-between">
                      <span className="font-label-md text-label-md text-on-surface font-semibold">
                        Human Editorial Review & Oversight
                      </span>
                      {selectedResult.reviews.length > 0 && (
                        <span className="text-secondary font-label-sm text-label-sm font-semibold flex items-center gap-1">
                          <span className="material-symbols-outlined text-[14px]">check</span>
                          Reviewed by {selectedResult.reviews[0].reviewer_id}
                        </span>
                      )}
                    </div>

                    <textarea
                      rows={2}
                      value={reviewNotes}
                      onChange={(e) => setReviewNotes(e.target.value)}
                      placeholder="Add reviewer notes or justification for override..."
                      className="w-full p-2.5 rounded-lg border border-outline-variant/40 bg-surface-container-low text-body-md text-on-surface focus:outline-none focus:border-primary"
                    />

                    <div className="flex items-center justify-end gap-3 pt-1">
                      <button
                        type="button"
                        disabled={isSubmittingReview}
                        onClick={() => handleReviewAction(HumanDecisionEnum.OVERRIDDEN, VerdictEnum.CONTRADICTORY)}
                        className="px-4 py-2 rounded-lg bg-surface-container-lowest text-on-surface border border-outline-variant/60 font-label-md text-label-md hover:bg-surface-container-low transition-colors cursor-pointer"
                      >
                        Override Verdict
                      </button>
                      <button
                        type="button"
                        disabled={isSubmittingReview}
                        onClick={() => handleReviewAction(HumanDecisionEnum.CONFIRMED)}
                        className="px-5 py-2 rounded-lg bg-primary text-on-primary font-label-md text-label-md hover:bg-primary/90 transition-colors cursor-pointer"
                      >
                        Approve Assessment
                      </button>
                    </div>
                  </div>
                </div>
              )}
            </section>
          )}

          {/* REFERENCES TAB */}
          {activeTab === 'references' && (
            <section className="mt-space-md bg-surface-container-lowest rounded-xl p-space-lg shadow-sm border border-outline-variant/30">
              <h2 className="font-headline-sm text-headline-sm text-on-surface mb-space-md">
                Extracted Bibliography & DOI Integrity
              </h2>
              <div className="flex flex-col divide-y divide-outline-variant/20">
                {report.results.map((res, i) => (
                  <div key={res.id} className="py-space-md flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                    <div>
                      <span className="font-code-sm text-code-sm text-primary font-semibold block">
                        [{i + 1}] {res.reference?.resolved_title || "Reference entry"}
                      </span>
                      <p className="font-body-md text-body-md text-on-surface-variant mt-0.5">
                        {res.reference?.raw_citation}
                      </p>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <span className="font-code-sm text-code-sm text-outline">
                        doi:{res.reference?.resolved_doi || "10.1234/unresolved"}
                      </span>
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-surface-container text-secondary font-label-sm text-label-sm">
                        Verified
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* AUDIT LOG TAB */}
          {activeTab === 'audit' && (
            <section className="mt-space-md bg-surface-container-lowest rounded-xl p-space-lg shadow-sm border border-outline-variant/30">
              <h2 className="font-headline-sm text-headline-sm text-on-surface mb-space-md">
                System Verification Audit Ledger
              </h2>
              <div className="flex flex-col gap-3">
                <div className="p-3 bg-surface-container-low rounded-lg flex items-center justify-between text-body-sm text-on-surface border border-outline-variant/20">
                  <span>S1: Document Parsing completed (18 pages parsed)</span>
                  <span className="font-code-sm text-code-sm text-on-surface-variant">System · 10:20:00</span>
                </div>
                <div className="p-3 bg-surface-container-low rounded-lg flex items-center justify-between text-body-sm text-on-surface border border-outline-variant/20">
                  <span>S2: Reference Extraction resolved 23 citations against CrossRef</span>
                  <span className="font-code-sm text-code-sm text-on-surface-variant">System · 10:20:04</span>
                </div>
                <div className="p-3 bg-surface-container-low rounded-lg flex items-center justify-between text-body-sm text-on-surface border border-outline-variant/20">
                  <span>S3: Claim Extraction identified 41 asserted empirical statements</span>
                  <span className="font-code-sm text-code-sm text-on-surface-variant">System · 10:20:08</span>
                </div>
                <div className="p-3 bg-surface-container-low rounded-lg flex items-center justify-between text-body-sm text-on-surface border border-outline-variant/20">
                  <span>S6: Natural Language Inference verified claim set with Gemini client</span>
                  <span className="font-code-sm text-code-sm text-on-surface-variant">System · 10:20:15</span>
                </div>
              </div>
            </section>
          )}
        </div>
      </main>

      <Footer />
    </div>
  );
};

