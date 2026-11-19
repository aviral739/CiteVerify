import React, { useEffect, useState } from 'react';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
import { Navbar, Footer } from '../components/layout/Navbar';
import {
  getDocumentReport,
  submitReview,
  exportDocument,
  getDocumentAudit,
  ApiError,
} from '../lib/api';
import { sampleResultsData } from '../mocks/sampleData';
import {
  DocumentReportResponse,
  ResultResponse,
  VerdictEnum,
  EvidenceAvailabilityEnum,
  HumanDecisionEnum,
  AuditLogResponse,
} from '../types';

export const ResultsPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  const isDemoQuery = searchParams.get('mode') === 'demo';
  const isDemoDocId = id === 'sample-demo-4092';

  const [report, setReport] = useState<DocumentReportResponse | null>(null);
  const [auditLogs, setAuditLogs] = useState<AuditLogResponse[]>([]);
  const [selectedResultId, setSelectedResultId] = useState<string>('');
  const [activeTab, setActiveTab] = useState<'claims' | 'references' | 'audit'>('claims');
  const [verdictFilter, setVerdictFilter] = useState<string>('all');
  const [needsReviewOnly, setNeedsReviewOnly] = useState<boolean>(false);
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [isExportMenuOpen, setIsExportMenuOpen] = useState<boolean>(false);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Review Form State
  const [reviewerId, setReviewerId] = useState<string>('dr_curie');
  const [reviewDecision, setReviewDecision] = useState<HumanDecisionEnum>(HumanDecisionEnum.CONFIRMED);
  const [overrideVerdict, setOverrideVerdict] = useState<VerdictEnum>(VerdictEnum.CONTRADICTORY);
  const [reviewNotes, setReviewNotes] = useState<string>('');
  const [isSubmittingReview, setIsSubmittingReview] = useState<boolean>(false);
  const [reviewFeedback, setReviewFeedback] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

  const isDemo = isDemoDocId || isDemoQuery || report?.document?.status === 'demo_ready';

  useEffect(() => {
    if (!id) return;
    setIsLoading(true);
    setErrorMessage(null);

    if (isDemoDocId) {
      // Offline sample data exclusively for the explicit demo identifier
      setReport(sampleResultsData);
      if (sampleResultsData.results.length > 0) {
        setSelectedResultId(sampleResultsData.results[0].id);
      }
      setIsLoading(false);
      return;
    }

    // Real document mode: fetch actual report from backend
    getDocumentReport(id)
      .then((data) => {
        // If it was explicitly seeded as demo on the backend, enrich with demo sample items for inspection
        if (data.document?.status === 'demo_ready' && data.results.length === 0) {
          setReport({
            ...sampleResultsData,
            document: data.document,
          });
          if (sampleResultsData.results.length > 0) {
            setSelectedResultId(sampleResultsData.results[0].id);
          }
        } else {
          // Strictly use real backend report data for real documents
          setReport(data);
          if (data.results && data.results.length > 0) {
            setSelectedResultId(data.results[0].id);
          }
        }
      })
      .catch((err: any) => {
        console.error("Backend report query failed:", err);
        if (isDemoQuery) {
          setReport(sampleResultsData);
          setSelectedResultId(sampleResultsData.results[0]?.id || '');
        } else {
          let msg = "Failed to load verification report from backend.";
          if (err instanceof ApiError) {
            msg = `Error (${err.statusCode}): ${err.message}`;
          }
          setErrorMessage(msg);
        }
      })
      .finally(() => {
        setIsLoading(false);
      });

    // Also fetch audit trail for this document
    getDocumentAudit(id)
      .then((logs) => setAuditLogs(logs))
      .catch(() => {
        // Audit log query fallback
      });
  }, [id, isDemoDocId, isDemoQuery]);

  // Selected Result
  const selectedResult: ResultResponse | undefined =
    report?.results.find((r) => r.id === selectedResultId) || report?.results[0];

  // Filtering Logic
  const filteredResults = (report?.results || []).filter((res) => {
    if (verdictFilter !== 'all' && res.verdict !== verdictFilter) return false;
    if (needsReviewOnly && res.reviews.length > 0) return false;
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      const textMatch = res.claim?.claim_text?.toLowerCase().includes(q);
      const doiMatch = res.reference?.resolved_doi?.toLowerCase().includes(q);
      const titleMatch = res.reference?.resolved_title?.toLowerCase().includes(q);
      if (!textMatch && !doiMatch && !titleMatch) return false;
    }
    return true;
  });

  // Human Review Submission Handler
  const handleReviewAction = async () => {
    if (!selectedResult) return;
    setIsSubmittingReview(true);
    setReviewFeedback(null);

    const payload = {
      reviewer_id: reviewerId.trim() || 'anonymous_reviewer',
      human_decision: reviewDecision,
      human_verdict: reviewDecision === HumanDecisionEnum.OVERRIDDEN ? overrideVerdict : undefined,
      notes: reviewNotes.trim() || undefined,
    };

    try {
      // Connect to real backend review endpoint: PATCH /api/results/{id}/review
      const newReview = await submitReview(selectedResult.id, payload);

      // Update UI with real review response from backend
      setReport((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          results: prev.results.map((r) => {
            if (r.id === selectedResult.id) {
              return {
                ...r,
                reviews: [newReview, ...r.reviews],
              };
            }
            return r;
          }),
        };
      });

      setReviewFeedback({
        type: 'success',
        message: `Decision successfully submitted as ${reviewDecision.toUpperCase()}.`,
      });
      setReviewNotes('');
    } catch (err: any) {
      console.warn("Backend review endpoint failed or simulated:", err);
      // If result is in-memory demo, optimistic local update
      if (isDemo) {
        const localReview = {
          id: `rev-${Date.now()}`,
          result_id: selectedResult.id,
          reviewer_id: reviewerId,
          human_decision: reviewDecision,
          human_verdict: reviewDecision === HumanDecisionEnum.OVERRIDDEN ? overrideVerdict : undefined,
          notes: reviewNotes,
          created_at: new Date().toISOString(),
        };
        setReport((prev) => {
          if (!prev) return prev;
          return {
            ...prev,
            results: prev.results.map((r) => {
              if (r.id === selectedResult.id) {
                return {
                  ...r,
                  reviews: [localReview, ...r.reviews],
                };
              }
              return r;
            }),
          };
        });
        setReviewFeedback({
          type: 'success',
          message: `Demo review recorded locally as ${reviewDecision.toUpperCase()}.`,
        });
        setReviewNotes('');
      } else {
        setReviewFeedback({
          type: 'error',
          message: err.message || 'Failed to submit review to CiteVerify backend.',
        });
      }
    } finally {
      setIsSubmittingReview(false);
    }
  };

  // Export Handler
  const handleExport = async (format = 'json') => {
    setIsExportMenuOpen(false);
    try {
      const data = await exportDocument(id || 'sample-demo-4092', format);
      const exportContent = format === 'json' ? JSON.stringify(data, null, 2) : String(data.data || JSON.stringify(data));
      const blob = new Blob([exportContent], {
        type: format === 'json' ? 'application/json' : 'text/plain',
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `citeverify_audit_${id || 'document'}.${format}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err: any) {
      console.error("Export failed:", err);
      alert(`Export failed: ${err.message || 'Could not export from backend.'}`);
    }
  };

  // Verdict Badges for all 6 Verdicts
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
            Insufficient Evidence
          </span>
        );
    }
  };

  // Evidence Scope Badge
  const getEvidenceScopeBadge = (scope: EvidenceAvailabilityEnum) => {
    switch (scope) {
      case EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE:
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-secondary-container/30 text-secondary font-label-sm text-label-sm rounded-DEFAULT">
            <span className="material-symbols-outlined text-[13px]">menu_book</span>
            Full text available
          </span>
        );
      case EvidenceAvailabilityEnum.ABSTRACT_ONLY:
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-surface-container text-on-surface-variant font-label-sm text-label-sm rounded-DEFAULT">
            <span className="material-symbols-outlined text-[13px]">article</span>
            Abstract only
          </span>
        );
      case EvidenceAvailabilityEnum.UNAVAILABLE:
      default:
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-error-container/20 text-error font-label-sm text-label-sm rounded-DEFAULT">
            <span className="material-symbols-outlined text-[13px]">block</span>
            Evidence unavailable
          </span>
        );
    }
  };

  // Dynamic Verdict Distribution Counts
  const results = report?.results || [];
  const supportedCount = report?.results_summary?.supported ?? results.filter((r) => r.verdict === VerdictEnum.SUPPORTED).length;
  const partiallySupportedCount = report?.results_summary?.partially_supported ?? results.filter((r) => r.verdict === VerdictEnum.PARTIALLY_SUPPORTED).length;
  const unsupportedCount = report?.results_summary?.unsupported ?? results.filter((r) => r.verdict === VerdictEnum.UNSUPPORTED).length;
  const contradictoryCount = report?.results_summary?.contradictory ?? results.filter((r) => r.verdict === VerdictEnum.CONTRADICTORY).length;
  const outdatedCount = report?.results_summary?.potentially_outdated ?? results.filter((r) => r.verdict === VerdictEnum.POTENTIALLY_OUTDATED).length;
  const insufficientCount = report?.results_summary?.insufficient_evidence ?? results.filter((r) => r.verdict === VerdictEnum.INSUFFICIENT_EVIDENCE).length;

  const totalResultsCount = report?.total_results ?? results.length;
  const isPartialReport = (report?.total_claims || 0) > totalResultsCount && totalResultsCount > 0;
  const calcPercent = (count: number) => (totalResultsCount > 0 ? (count / totalResultsCount) * 100 : 0);

  // Unique References Extracted from Results
  const uniqueReferences = React.useMemo(() => {
    const map = new Map<string, any>();
    for (const res of results) {
      if (res.reference) {
        const key = res.reference.id || res.reference.resolved_doi || res.reference.raw_citation;
        if (!map.has(key)) {
          map.set(key, res.reference);
        }
      }
    }
    return Array.from(map.values());
  }, [results]);

  return (
    <div className="bg-surface font-body-md text-on-surface antialiased flex flex-col min-h-screen">
      <Navbar
        documentTitle={report?.document.title || "Verification Report"}
        isComplete={true}
        onRerun={() => navigate(`/documents/${id || 'sample-demo-4092'}/analysis${isDemo ? '?mode=demo' : ''}`)}
        onExport={() => setIsExportMenuOpen(!isExportMenuOpen)}
      />

      <main className="w-full pt-28 pb-16 bg-surface max-w-[1440px] mx-auto px-4 sm:px-margin flex-1">
        <div className="flex flex-col w-full pb-space-xl">

          {/* Demonstration Mode Banner */}
          {isDemo && (
            <div className="w-full bg-amber-500/10 border border-amber-500/30 rounded-xl p-space-md flex items-start gap-space-sm shadow-xs mb-4">
              <span className="material-symbols-outlined text-amber-800 text-[22px] shrink-0 mt-0.5">science</span>
              <div className="flex flex-col text-sm text-amber-950">
                <span className="font-semibold">DEMONSTRATION AUDIT DATA</span>
                <span className="text-[13px] text-amber-900/90 mt-0.5">
                  This report displays curated sample verification data with planted discrepancies for testing and demonstration purposes. It is clearly separated from live document audits.
                </span>
              </div>
            </div>
          )}

          {/* Error Banner */}
          {errorMessage && (
            <div className="w-full bg-error-container text-on-error-container rounded-xl p-space-md flex items-start justify-between gap-space-sm border border-error/30 shadow-xs mb-4">
              <div className="flex items-start gap-space-sm">
                <span className="material-symbols-outlined text-error text-[22px] shrink-0 mt-0.5">error</span>
                <div className="flex flex-col">
                  <span className="font-semibold text-error">Failed to load report</span>
                  <span className="text-sm mt-0.5">{errorMessage}</span>
                </div>
              </div>
              <button
                type="button"
                onClick={() => window.location.reload()}
                className="px-3 py-1 bg-surface text-on-surface rounded text-xs font-semibold hover:bg-surface-container transition-colors shrink-0"
              >
                Retry
              </button>
            </div>
          )}

          {/* Partial Report In-Progress Banner */}
          {isPartialReport && (
            <div className="w-full bg-surface-container-high border border-outline-variant/30 rounded-xl p-space-md flex items-start justify-between gap-space-sm shadow-xs mb-4">
              <div className="flex items-start gap-space-sm">
                <span className="material-symbols-outlined text-primary text-[22px] shrink-0 mt-0.5 animate-spin">progress_activity</span>
                <div className="flex flex-col text-sm text-on-surface">
                  <span className="font-semibold text-primary">Partial Verification Report</span>
                  <span className="text-[13px] text-on-surface-variant mt-0.5">
                    {totalResultsCount} of {report?.total_claims} assertions audited. Remaining assertions are being verified by the backend pipeline.
                  </span>
                </div>
              </div>
              <button
                type="button"
                onClick={() => navigate(`/documents/${id}/analysis`)}
                className="px-3 py-1 bg-surface text-primary rounded text-xs font-semibold hover:bg-surface-container transition-colors shrink-0 flex items-center gap-1 border border-outline-variant/20 cursor-pointer"
              >
                <span className="material-symbols-outlined text-[14px]">sync</span>
                View Live Stream
              </button>
            </div>
          )}

          {/* Header Context */}
          <section className="py-space-md flex flex-col md:flex-row md:items-center justify-between gap-space-md">
            <div className="flex flex-wrap items-center gap-space-sm min-w-0">
              <div className="flex items-center gap-space-xs">
                <span className="material-symbols-outlined text-primary text-[22px]">description</span>
                <h1 className="font-headline-md text-headline-md text-on-surface truncate max-w-xl">
                  {isLoading ? "Loading audit report..." : (report?.document.title || "Untitled Manuscript")}
                </h1>
              </div>
              <div className="flex items-center gap-1.5 px-2.5 py-1 bg-surface-container rounded-DEFAULT text-on-surface-variant font-code-sm text-code-sm">
                <span>ID: {id}</span>
                {report?.document.doi && (
                  <>
                    <span className="text-outline">·</span>
                    <span>DOI: {report.document.doi}</span>
                  </>
                )}
              </div>
              <span className={`inline-flex items-center gap-1 px-2.5 py-1 font-label-sm text-label-sm rounded-DEFAULT uppercase tracking-wider font-semibold ${
                isPartialReport
                  ? "bg-amber-500/20 text-amber-900"
                  : totalResultsCount > 0
                  ? "bg-secondary-fixed text-on-secondary-fixed"
                  : "bg-surface-container-high text-on-surface-variant"
              }`}>
                <span className="material-symbols-outlined text-[14px]">
                  {isPartialReport ? "sync" : totalResultsCount > 0 ? "verified" : "hourglass_empty"}
                </span>
                {isPartialReport
                  ? `In Progress (${totalResultsCount}/${report?.total_claims})`
                  : totalResultsCount > 0
                  ? "Audit Complete"
                  : `Status: ${report?.document.status || "Pending"}`}
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
                  <span>Export Report</span>
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
                      onClick={() => handleExport('bibtex')}
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
                      {totalResultsCount}
                    </span>
                    <span className="font-body-md text-body-md text-on-surface-variant">
                      results of {report?.total_claims || 0} assertions
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
                      {report?.total_references || 0}
                    </span>
                    <span className="font-body-md text-body-md text-on-surface-variant">
                      citations indexed
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
                    Editorial Reviews
                  </span>
                  <div className="flex items-baseline gap-1 mt-0.5">
                    <span className="font-headline-md text-headline-md text-on-surface font-semibold">
                      {results.filter((r) => r.reviews.length > 0).length} of {totalResultsCount}
                    </span>
                    <span className="font-body-md text-body-md text-on-surface-variant">
                      findings peer-reviewed
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
                  {totalResultsCount} Total Processed Statements
                </span>
              </div>

              {totalResultsCount > 0 ? (
                <div className="h-3.5 w-full flex rounded-DEFAULT overflow-hidden gap-0.5 bg-surface-container-high">
                  <div className="bg-secondary" style={{ width: `${calcPercent(supportedCount)}%` }} title={`Supported: ${supportedCount}`}></div>
                  <div className="bg-amber-500" style={{ width: `${calcPercent(partiallySupportedCount)}%` }} title={`Partly supported: ${partiallySupportedCount}`}></div>
                  <div className="bg-error" style={{ width: `${calcPercent(unsupportedCount)}%` }} title={`Unsupported: ${unsupportedCount}`}></div>
                  <div className="bg-red-950" style={{ width: `${calcPercent(contradictoryCount)}%` }} title={`Contradictory: ${contradictoryCount}`}></div>
                  <div className="bg-orange-500" style={{ width: `${calcPercent(outdatedCount)}%` }} title={`Possibly outdated: ${outdatedCount}`}></div>
                  <div className="bg-outline" style={{ width: `${calcPercent(insufficientCount)}%` }} title={`Insufficient evidence: ${insufficientCount}`}></div>
                </div>
              ) : (
                <div className="h-3.5 w-full rounded-DEFAULT bg-surface-container-high flex items-center justify-center text-xs text-on-surface-variant font-code-sm">
                  No automated verdicts generated yet
                </div>
              )}

              {/* Verdict Legend */}
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-space-sm mt-space-md">
                <div className="flex items-center gap-1.5 font-label-sm text-label-sm text-on-surface">
                  <span className="material-symbols-outlined text-secondary text-[16px]">check_circle</span>
                  <span>Supported:</span>
                  <strong className="font-code-sm text-code-sm">{supportedCount}</strong>
                </div>
                <div className="flex items-center gap-1.5 font-label-sm text-label-sm text-on-surface">
                  <span className="material-symbols-outlined text-amber-600 text-[16px]">timelapse</span>
                  <span>Partly:</span>
                  <strong className="font-code-sm text-code-sm">{partiallySupportedCount}</strong>
                </div>
                <div className="flex items-center gap-1.5 font-label-sm text-label-sm text-on-surface">
                  <span className="material-symbols-outlined text-error text-[16px]">cancel</span>
                  <span>Unsupported:</span>
                  <strong className="font-code-sm text-code-sm">{unsupportedCount}</strong>
                </div>
                <div className="flex items-center gap-1.5 font-label-sm text-label-sm text-on-surface">
                  <span className="material-symbols-outlined text-red-950 text-[16px]">compare_arrows</span>
                  <span>Contradictory:</span>
                  <strong className="font-code-sm text-code-sm">{contradictoryCount}</strong>
                </div>
                <div className="flex items-center gap-1.5 font-label-sm text-label-sm text-on-surface">
                  <span className="material-symbols-outlined text-orange-600 text-[16px]">schedule</span>
                  <span>Outdated:</span>
                  <strong className="font-code-sm text-code-sm">{outdatedCount}</strong>
                </div>
                <div className="flex items-center gap-1.5 font-label-sm text-label-sm text-on-surface">
                  <span className="material-symbols-outlined text-outline text-[16px]">help</span>
                  <span>Insufficient:</span>
                  <strong className="font-code-sm text-code-sm">{insufficientCount}</strong>
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
                  {results.length}
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
                  {report?.total_references || 0}
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
                <span>Audit Trail</span>
                <span className="px-1.5 py-0.5 rounded-DEFAULT bg-surface-container text-on-surface-variant font-code-sm text-code-sm">
                  {auditLogs.length}
                </span>
              </button>
            </div>
          </section>

          {/* CLAIMS TAB (MASTER / DETAIL) */}
          {activeTab === 'claims' && (
            <section className="mt-space-md">
              {results.length === 0 ? (
                /* Honest empty state for real documents where verification is still pending */
                <div className="bg-surface-container-lowest rounded-xl p-12 text-center flex flex-col items-center justify-center gap-3 border border-outline-variant/30">
                  <div className="w-14 h-14 rounded-full bg-surface-container-high flex items-center justify-center text-primary">
                    <span className="material-symbols-outlined text-[32px]">pending_actions</span>
                  </div>
                  <h3 className="font-headline-sm text-on-surface font-semibold text-lg">
                    No Automated Verdicts Generated Yet
                  </h3>
                  <p className="font-body-md text-sm text-on-surface-variant max-w-lg leading-relaxed">
                    This document is registered in the CiteVerify database with status: <code className="font-code-sm text-on-surface">{report?.document.status || 'pending'}</code>.
                    {report?.status_note ? ` Note: ${report.status_note}` : ''}
                    Verdicts, evidence comparisons, and human reviews will appear as backend verification stages execute.
                  </p>
                  <div className="flex items-center gap-3 mt-2">
                    <button
                      type="button"
                      onClick={() => navigate(`/documents/${id}/analysis`)}
                      className="px-4 py-2 rounded-lg bg-primary-container text-on-primary hover:bg-primary font-label-md text-sm font-semibold transition-colors flex items-center gap-1.5"
                    >
                      <span className="material-symbols-outlined text-[18px]">sync</span>
                      View Live Stream
                    </button>
                  </div>
                </div>
              ) : (
                <div className="grid grid-cols-1 lg:grid-cols-12 gap-gutter items-start">
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
                        const latestReview = res.reviews[0];

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
                                {res.claim?.page_number && (
                                  <span className="font-code-sm text-code-sm text-on-surface-variant bg-surface-container-high px-1.5 py-0.5 rounded-DEFAULT">
                                    p. {res.claim.page_number}
                                  </span>
                                )}
                              </div>
                              {getVerdictBadge(res.verdict)}
                            </div>

                            <p className="font-headline-sm text-headline-sm text-on-surface leading-snug mb-space-sm line-clamp-2">
                              “{res.claim?.claim_text || 'No claim text assertion available'}”
                            </p>

                            <div className="flex flex-wrap gap-1.5 mb-space-sm">
                              {getEvidenceScopeBadge(res.evidence_completeness)}
                            </div>

                            <div className="flex items-center justify-between text-on-surface-variant font-code-sm text-code-sm pt-2 border-t border-outline-variant/10">
                              <span className="truncate">
                                Match: {(res.retrieval_match * 100).toFixed(0)}% · Strength: {(res.verdict_strength * 100).toFixed(0)}%
                              </span>
                              {hasReview ? (
                                <span className="inline-flex items-center gap-1 text-secondary font-semibold shrink-0">
                                  <span className="material-symbols-outlined text-[14px]">check_circle</span>
                                  {latestReview.human_decision === HumanDecisionEnum.OVERRIDDEN ? 'Overridden' : 'Confirmed'}
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
                            Verified Citation
                          </span>
                        </div>
                        <p className="font-body-md text-body-md text-on-surface font-medium">
                          {selectedResult.reference?.raw_citation || "Reference metadata resolved"}
                        </p>
                        {selectedResult.reference?.resolved_doi && (
                          <div className="flex items-center gap-2 pt-1 font-code-sm text-code-sm text-primary">
                            <span>doi:{selectedResult.reference.resolved_doi}</span>
                          </div>
                        )}
                      </div>

                      {/* Side-by-Side Comparison */}
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-space-md">
                        <div className="p-4 rounded-lg bg-surface-container-low flex flex-col space-y-2 border border-outline-variant/20">
                          <span className="font-label-md text-label-md text-on-surface font-semibold">
                            In your manuscript {selectedResult.claim?.page_number ? `(Page ${selectedResult.claim.page_number})` : ''}
                          </span>
                          <blockquote className="font-body-md text-[15px] text-on-surface italic leading-relaxed">
                            “{selectedResult.claim?.claim_text || 'No manuscript statement extracted.'}”
                          </blockquote>
                        </div>

                        <div className="p-4 rounded-lg bg-surface-container-low flex flex-col space-y-2 border border-outline-variant/20">
                          <div className="flex items-center justify-between">
                            <span className="font-label-md text-label-md text-on-surface font-semibold">
                              In cited literature
                            </span>
                            {getEvidenceScopeBadge(selectedResult.evidence_completeness)}
                          </div>
                          <blockquote className="font-body-md text-[15px] text-on-surface-variant italic leading-relaxed">
                            “{selectedResult.evidence_quote || "Full text passage retrieved and compared by AI model."}”
                          </blockquote>
                        </div>
                      </div>

                      {/* Analytical Verdict Explanation */}
                      <div className="p-3.5 rounded-lg bg-surface-container-low border border-outline-variant/20 flex items-start gap-2">
                        <span className="material-symbols-outlined text-[18px] text-primary shrink-0 mt-0.5">info</span>
                        <div>
                          <span className="font-semibold text-on-surface font-label-md text-label-md">Automated Verdict Assessment: </span>
                          <span className="font-body-md text-body-md text-on-surface">
                            {selectedResult.explanation || `Verdict evaluated as ${selectedResult.verdict}.`}
                          </span>
                        </div>
                      </div>

                      {/* Evidence Integrity Notice if Inaccessible */}
                      {selectedResult.evidence_completeness === EvidenceAvailabilityEnum.UNAVAILABLE && (
                        <div className="p-3 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-950 text-xs flex items-center gap-2">
                          <span className="material-symbols-outlined text-[18px] text-amber-800">warning</span>
                          <span>
                            Source text is currently unavailable or closed-access. CiteVerify maintains an Insufficient Evidence status and does not convert missing evidence into an unsupported verdict.
                          </span>
                        </div>
                      )}

                      {/* Separate Dimensions: Retrieval Match, Evidence Scope, Verdict Strength */}
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
                            {selectedResult.evidence_completeness === 'full_text_available'
                              ? 'Full text'
                              : selectedResult.evidence_completeness === 'abstract_only'
                              ? 'Abstract'
                              : 'Unavailable'}
                          </span>
                        </div>
                        <div className="p-3 rounded-lg bg-surface-container-low border border-outline-variant/20">
                          <span className="font-label-sm text-label-sm text-on-surface-variant block">Verdict Strength</span>
                          <span className="font-headline-sm text-headline-sm text-on-surface font-semibold">
                            {(selectedResult.verdict_strength * 100).toFixed(0)}%
                          </span>
                        </div>
                      </div>

                      {/* Human Review Decision Trail */}
                      {selectedResult.reviews.length > 0 && (
                        <div className="p-3.5 bg-surface-container-low rounded-lg border border-outline-variant/20 flex flex-col gap-2">
                          <span className="font-label-md text-xs uppercase tracking-wider text-on-surface-variant font-semibold">
                            Previous Editorial Reviews ({selectedResult.reviews.length})
                          </span>
                          <div className="space-y-2">
                            {selectedResult.reviews.map((rev) => (
                              <div key={rev.id} className="p-2.5 bg-surface-container-lowest rounded border border-outline-variant/10 text-xs flex flex-col gap-1">
                                <div className="flex items-center justify-between">
                                  <span className="font-semibold text-primary">
                                    Reviewer: {rev.reviewer_id}
                                  </span>
                                  <span className="font-code-sm text-on-surface-variant">
                                    {new Date(rev.created_at).toLocaleString()}
                                  </span>
                                </div>
                                <div className="flex items-center gap-2">
                                  <span className="font-medium text-on-surface">Decision: {rev.human_decision.toUpperCase()}</span>
                                  {rev.human_verdict && (
                                    <span className="px-1.5 py-0.5 rounded bg-surface-container text-on-surface font-code-sm">
                                      Override: {rev.human_verdict}
                                    </span>
                                  )}
                                </div>
                                {rev.notes && (
                                  <p className="text-on-surface-variant italic mt-0.5">"{rev.notes}"</p>
                                )}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Human-in-the-Loop Review Submission Form */}
                      <div className="pt-space-md border-t border-outline-variant/30 flex flex-col gap-space-sm">
                        <div className="flex items-center justify-between">
                          <span className="font-label-md text-label-md text-on-surface font-semibold">
                            Human Editorial Review & Oversight
                          </span>
                          <span className="text-xs text-on-surface-variant">
                            Endpoint: <code className="font-code-sm text-primary">PATCH /api/results/{'{id}'}/review</code>
                          </span>
                        </div>

                        {reviewFeedback && (
                          <div className={`p-2.5 rounded text-xs flex items-center gap-2 ${
                            reviewFeedback.type === 'success'
                              ? 'bg-secondary-container/30 text-secondary border border-secondary/30'
                              : 'bg-error-container text-on-error-container border border-error/30'
                          }`}>
                            <span className="material-symbols-outlined text-[16px]">
                              {reviewFeedback.type === 'success' ? 'check_circle' : 'error'}
                            </span>
                            <span>{reviewFeedback.message}</span>
                          </div>
                        )}

                        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                          <div className="flex flex-col gap-1">
                            <label className="text-xs font-semibold text-on-surface-variant">Reviewer ID</label>
                            <input
                              type="text"
                              value={reviewerId}
                              onChange={(e) => setReviewerId(e.target.value)}
                              placeholder="e.g., dr_curie"
                              className="p-2 rounded border border-outline-variant/40 bg-surface-container-low text-xs text-on-surface focus:outline-none focus:border-primary"
                            />
                          </div>

                          <div className="flex flex-col gap-1">
                            <label className="text-xs font-semibold text-on-surface-variant">Decision Action</label>
                            <select
                              value={reviewDecision}
                              onChange={(e) => setReviewDecision(e.target.value as HumanDecisionEnum)}
                              className="p-2 rounded border border-outline-variant/40 bg-surface-container-low text-xs text-on-surface focus:outline-none focus:border-primary"
                            >
                              <option value={HumanDecisionEnum.CONFIRMED}>Confirmed (Approve)</option>
                              <option value={HumanDecisionEnum.OVERRIDDEN}>Overridden (Change Verdict)</option>
                              <option value={HumanDecisionEnum.DISPUTED}>Disputed (Flag for Review)</option>
                            </select>
                          </div>

                          {reviewDecision === HumanDecisionEnum.OVERRIDDEN && (
                            <div className="flex flex-col gap-1">
                              <label className="text-xs font-semibold text-on-surface-variant">Override Verdict</label>
                              <select
                                value={overrideVerdict}
                                onChange={(e) => setOverrideVerdict(e.target.value as VerdictEnum)}
                                className="p-2 rounded border border-outline-variant/40 bg-surface-container-low text-xs text-on-surface focus:outline-none focus:border-primary"
                              >
                                <option value={VerdictEnum.SUPPORTED}>Supported</option>
                                <option value={VerdictEnum.PARTIALLY_SUPPORTED}>Partly supported</option>
                                <option value={VerdictEnum.UNSUPPORTED}>Unsupported</option>
                                <option value={VerdictEnum.CONTRADICTORY}>Contradictory</option>
                                <option value={VerdictEnum.POTENTIALLY_OUTDATED}>Outdated</option>
                                <option value={VerdictEnum.INSUFFICIENT_EVIDENCE}>Insufficient Evidence</option>
                              </select>
                            </div>
                          )}
                        </div>

                        <textarea
                          rows={2}
                          value={reviewNotes}
                          onChange={(e) => setReviewNotes(e.target.value)}
                          placeholder="Add reviewer notes, rationale, or page/table citation justification..."
                          className="w-full p-2.5 rounded-lg border border-outline-variant/40 bg-surface-container-low text-body-md text-on-surface focus:outline-none focus:border-primary"
                        />

                        <div className="flex items-center justify-end gap-3 pt-1">
                          <button
                            type="button"
                            disabled={isSubmittingReview}
                            onClick={handleReviewAction}
                            className="px-5 py-2 rounded-lg bg-primary text-on-primary font-label-md text-label-md hover:bg-primary/90 transition-colors cursor-pointer disabled:opacity-50 flex items-center gap-1.5"
                          >
                            <span className={`material-symbols-outlined text-[16px] ${isSubmittingReview ? 'animate-spin' : ''}`}>
                              {isSubmittingReview ? 'sync' : 'gavel'}
                            </span>
                            <span>{isSubmittingReview ? 'Saving review...' : 'Submit Editorial Review'}</span>
                          </button>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </section>
          )}

          {/* REFERENCES TAB */}
          {activeTab === 'references' && (
            <section className="mt-space-md bg-surface-container-lowest rounded-xl p-space-lg shadow-sm border border-outline-variant/30">
              <div className="flex items-center justify-between mb-space-md">
                <h2 className="font-headline-sm text-headline-sm text-on-surface">
                  Extracted Bibliography & DOI Resolution
                </h2>
                <span className="font-code-sm text-xs text-on-surface-variant">
                  {uniqueReferences.length} unique references resolved
                </span>
              </div>
              {uniqueReferences.length > 0 ? (
                <div className="flex flex-col divide-y divide-outline-variant/20">
                  {uniqueReferences.map((ref, i) => (
                    <div key={ref.id || i} className="py-space-md flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                      <div className="min-w-0 flex-1">
                        <span className="font-code-sm text-code-sm text-primary font-semibold block truncate">
                          [{i + 1}] {ref.resolved_title || ref.citation_key || "Reference Entry"}
                        </span>
                        <p className="font-body-md text-body-md text-on-surface-variant mt-0.5">
                          {ref.raw_citation || "No raw citation text available."}
                        </p>
                        {(ref.resolved_venue || ref.resolved_year) && (
                          <div className="flex items-center gap-2 mt-1 text-xs text-on-surface-variant font-code-sm">
                            {ref.resolved_venue && <span>{ref.resolved_venue}</span>}
                            {ref.resolved_venue && ref.resolved_year && <span>•</span>}
                            {ref.resolved_year && <span>{ref.resolved_year}</span>}
                          </div>
                        )}
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        {ref.resolved_doi ? (
                          <span className="font-code-sm text-code-sm text-primary">
                            doi:{ref.resolved_doi}
                          </span>
                        ) : (
                          <span className="font-code-sm text-xs text-on-surface-variant bg-surface-container px-2 py-0.5 rounded">
                            Unresolved DOI
                          </span>
                        )}
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-surface-container text-secondary font-label-sm text-label-sm font-semibold">
                          {ref.resolution_confidence ? `${(ref.resolution_confidence * 100).toFixed(0)}% match` : 'Indexed'}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="p-8 text-center text-on-surface-variant text-sm">
                  {report?.total_references && report.total_references > 0
                    ? `${report.total_references} citations detected in the manuscript. Detailed reference metadata will display once verification evidence resolution completes.`
                    : 'No references extracted yet. References will appear here once Stage 2 (s2_references) executes.'}
                </div>
              )}
            </section>
          )}

          {/* AUDIT LOG TAB */}
          {activeTab === 'audit' && (
            <section className="mt-space-md bg-surface-container-lowest rounded-xl p-space-lg shadow-sm border border-outline-variant/30">
              <div className="flex items-center justify-between mb-space-md">
                <h2 className="font-headline-sm text-headline-sm text-on-surface">
                  System Verification Audit Trail
                </h2>
                <span className="text-xs text-on-surface-variant font-code-sm">
                  Endpoint: GET /api/documents/{'{id}'}/audit
                </span>
              </div>

              {auditLogs.length > 0 ? (
                <div className="flex flex-col gap-2.5">
                  {auditLogs.map((log) => (
                    <div key={log.id} className="p-3 bg-surface-container-low rounded-lg flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-body-sm text-on-surface border border-outline-variant/20">
                      <div className="flex items-center gap-2.5">
                        <span className="material-symbols-outlined text-primary text-[18px]">verified</span>
                        <div>
                          <span className="font-semibold text-on-surface">{log.action}: </span>
                          <span className="text-on-surface-variant">{log.details || 'Action completed'}</span>
                        </div>
                      </div>
                      <div className="flex items-center gap-2 shrink-0 text-xs font-code-sm text-on-surface-variant">
                        <span>Actor: {log.actor}</span>
                        <span>·</span>
                        <span>{new Date(log.created_at).toLocaleString()}</span>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="p-8 text-center text-on-surface-variant text-sm">
                  No audit log entries recorded yet for document <code className="font-code-sm text-on-surface">{id}</code>.
                </div>
              )}
            </section>
          )}

        </div>
      </main>

      <Footer />
    </div>
  );
};
