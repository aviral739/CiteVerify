import React, { useEffect, useState, useRef, useMemo } from 'react';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
import { Navbar, Footer } from '../components/layout/Navbar';
import { getDocument, getDocumentReport, getDocumentEventsUrl, getJob, ApiError } from '../lib/api';
import { CiteVerifySSEClient, SSEParsedMessage } from '../lib/sseClient';
import {
  DocumentResponse,
  DocumentReportResponse,
  ResultResponse,
  JobRecordResponse,
  JobStatusEnum,
  VerdictEnum,
} from '../types';

interface StageInfo {
  id: string;
  name: string;
  status: 'done' | 'active' | 'queued' | 'error';
  detail: string;
}

const INITIAL_STAGES: StageInfo[] = [
  { id: 's1_parse', name: 'Parse', status: 'queued', detail: 'PDF/DOCX structure' },
  { id: 's2_references', name: 'References', status: 'queued', detail: 'Extract citations' },
  { id: 's3_claims', name: 'Claims', status: 'queued', detail: 'Extract claims' },
  { id: 's4_resolve', name: 'Resolve', status: 'queued', detail: 'Match DOIs & venues' },
  { id: 's5_evidence', name: 'Evidence', status: 'queued', detail: 'Retrieve source text' },
  { id: 's6_verify', name: 'Verify', status: 'queued', detail: 'Compare claim & quote' },
  { id: 's7_assessment', name: 'Assessment', status: 'queued', detail: 'Formulate verdict' },
  { id: 's8_persist', name: 'Persist', status: 'queued', detail: 'Store report & audit' },
];

function normalizeStageId(raw: string): string {
  const lower = (raw || '').toLowerCase().trim();
  if (lower.startsWith('s1') || lower.includes('parse')) return 's1_parse';
  if (lower.startsWith('s2') || lower.includes('ref')) return 's2_references';
  if (lower.startsWith('s3') || lower.includes('claim')) return 's3_claims';
  if (lower.startsWith('s4') || lower.includes('resolve') || lower.includes('doi')) return 's4_resolve';
  if (lower.startsWith('s5') || lower.includes('evidence')) return 's5_evidence';
  if (lower.startsWith('s6') || lower.includes('verify')) return 's6_verify';
  if (lower.startsWith('s7') || lower.includes('assess')) return 's7_assessment';
  if (lower.startsWith('s8') || lower.includes('persist') || lower.includes('report')) return 's8_persist';
  return lower;
}

export const AnalysisPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  const isDemoQuery = searchParams.get('mode') === 'demo';
  const isDemoDocId = id === 'sample-demo-4092';
  const jobIdParam = searchParams.get('job_id');

  const [doc, setDoc] = useState<DocumentResponse | null>(null);
  const [job, setJob] = useState<JobRecordResponse | null>(null);
  const [report, setReport] = useState<DocumentReportResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // SSE Stream State & Counters
  const [streamStatus, setStreamStatus] = useState<'connecting' | 'connected' | 'reconnecting' | 'idle' | 'closed'>('connecting');
  const [liveEvents, setLiveEvents] = useState<SSEParsedMessage[]>([]);
  const [liveResults, setLiveResults] = useState<ResultResponse[]>([]);
  const [streamedRefCount, setStreamedRefCount] = useState<number>(0);
  const [streamedClaimCount, setStreamedClaimCount] = useState<number>(0);

  // Stages State
  const [stages, setStages] = useState<StageInfo[]>(INITIAL_STAGES);

  const isDemo = isDemoDocId || isDemoQuery || doc?.status === 'demo_ready';

  useEffect(() => {
    if (!id) return;

    let isMounted = true;
    setIsLoading(true);
    setErrorMessage(null);

    // 1. Fetch real document metadata from backend
    getDocument(id)
      .then((documentData) => {
        if (!isMounted) return;
        setDoc(documentData);

        // Fetch report to see if any claims or results already exist
        return getDocumentReport(id).then((reportData) => {
          if (!isMounted) return;
          setReport(reportData);
          if (reportData.results && reportData.results.length > 0) {
            setLiveResults(reportData.results);
          }
        });
      })
      .catch((err: any) => {
        if (!isMounted) return;
        console.warn("Could not retrieve document from backend API:", err);

        if (isDemoDocId || isDemoQuery) {
          // Allowed fallback only for explicit demonstration modes
          setDoc({
            id: id || 'sample-demo-4092',
            title: "sample_paper.pdf",
            doi: "10.1016/j.cell.2023.11.008",
            authors: "Vaswani et al.",
            status: "demo_ready",
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          });
        } else {
          let msg = "Failed to load document metadata from CiteVerify backend.";
          if (err instanceof ApiError) {
            msg = `Error (${err.statusCode}): ${err.message}`;
          }
          setErrorMessage(msg);
        }
      })
      .finally(() => {
        if (isMounted) setIsLoading(false);
      });

    // 2. Connect to robust SSE pipeline stream
    let sseClient: CiteVerifySSEClient | null = null;

    if (!isDemoDocId) {
      try {
        const streamUrl = getDocumentEventsUrl(id);
        sseClient = new CiteVerifySSEClient({
          url: streamUrl,
          onOpen: () => {
            if (!isMounted) return;
            setStreamStatus('connected');
          },
          onStatusChange: (status) => {
            if (!isMounted) return;
            setStreamStatus(status);
          },
          onMessage: (parsed) => {
            if (!isMounted) return;
            setLiveEvents((prev) => [parsed, ...prev.slice(0, 24)]);
          },
          onStage: (rawStageId, stageStatus, detail) => {
            if (!isMounted) return;
            const normId = normalizeStageId(rawStageId);

            setStages((prevStages) =>
              prevStages.map((st) => {
                if (st.id === normId || st.name.toLowerCase() === rawStageId.toLowerCase()) {
                  return {
                    ...st,
                    status: stageStatus,
                    detail: detail || (stageStatus === 'done' ? 'Completed' : stageStatus === 'error' ? 'Error encountered' : 'In progress'),
                  };
                }
                return st;
              })
            );
          },
          onReference: (refData) => {
            if (!isMounted) return;
            setStreamedRefCount((c) => {
              const updated = c + 1;
              setStages((prev) =>
                prev.map((s) => (s.id === 's2_references' ? { ...s, status: 'active', detail: `${updated} citations resolved` } : s))
              );
              return updated;
            });
          },
          onClaim: (claimData) => {
            if (!isMounted) return;
            setStreamedClaimCount((c) => {
              const updated = c + 1;
              setStages((prev) =>
                prev.map((s) => (s.id === 's3_claims' ? { ...s, status: 'active', detail: `${updated} claims extracted` } : s))
              );
              return updated;
            });
          },
          onResult: (resultData) => {
            if (!isMounted) return;
            if (resultData && resultData.id) {
              setLiveResults((prev) => {
                if (prev.some((r) => r.id === resultData.id)) return prev;
                return [resultData, ...prev];
              });
            }
          },
          onDone: () => {
            if (!isMounted) return;
            setStreamStatus('closed');
            setStages((prev) =>
              prev.map((s) => ({ ...s, status: s.status === 'error' ? 'error' : 'done' }))
            );
            // Refresh aggregated report once pipeline signals done
            getDocumentReport(id)
              .then((fresh) => {
                if (isMounted) {
                  setReport(fresh);
                  if (fresh.document) {
                    setDoc(fresh.document);
                  }
                  if (fresh.results && fresh.results.length > 0) {
                    setLiveResults(fresh.results);
                  }
                }
              })
              .catch(() => {});
            getDocument(id)
              .then((d) => {
                if (isMounted) setDoc(d);
              })
              .catch(() => {});
          },
          onError: (errData) => {
            if (!isMounted) return;
            console.warn("Pipeline SSE reported error event:", errData);
          },
        });

        sseClient.connect();
      } catch (e) {
        console.warn("Failed to initialize SSE client:", e);
        setStreamStatus('closed');
      }
    } else {
      // Demo mode simulated progression
      setStreamStatus('idle');
      setStages([
        { id: 's1_parse', name: 'Parse', status: 'done', detail: '18 pgs parsed' },
        { id: 's2_references', name: 'References', status: 'done', detail: '23 resolved' },
        { id: 's3_claims', name: 'Claims', status: 'done', detail: '41 extracted' },
        { id: 's4_resolve', name: 'Resolve', status: 'done', detail: '23 DOIs queried' },
        { id: 's5_evidence', name: 'Evidence', status: 'active', detail: '6 of 14 retrieved' },
        { id: 's6_verify', name: 'Verify', status: 'queued', detail: 'Queued' },
        { id: 's7_assessment', name: 'Assessment', status: 'queued', detail: 'Queued' },
        { id: 's8_persist', name: 'Persist', status: 'queued', detail: 'Queued' },
      ]);
    }

    return () => {
      isMounted = false;
      if (sseClient) {
        sseClient.close();
      }
    };
  }, [id, isDemoDocId, isDemoQuery]);

  // Fallback job & document status polling synchronization
  useEffect(() => {
    if (!id || isDemoDocId) return;

    let isPolling = true;

    const pollStatus = async () => {
      if (!isPolling) return;

      // 1. Poll job status if jobId exists
      const targetJobId = jobIdParam || job?.job_id;
      if (targetJobId) {
        try {
          const freshJob = await getJob(targetJobId);
          if (!isPolling) return;
          setJob(freshJob);

          if (freshJob.current_stage) {
            const normStage = normalizeStageId(freshJob.current_stage);
            setStages((prevStages) => {
              const targetIdx = prevStages.findIndex((s) => s.id === normStage);
              if (targetIdx === -1) return prevStages;
              return prevStages.map((s, idx) => {
                if (idx < targetIdx) {
                  return { ...s, status: 'done', detail: 'Completed' };
                } else if (idx === targetIdx) {
                  const sStatus =
                    freshJob.status === JobStatusEnum.FAILED || freshJob.status === 'failed'
                      ? 'error'
                      : freshJob.status === JobStatusEnum.COMPLETED || freshJob.status === 'completed'
                      ? 'done'
                      : 'active';
                  return {
                    ...s,
                    status: sStatus,
                    detail: freshJob.status === 'completed' ? 'Completed' : 'In progress',
                  };
                } else {
                  return { ...s, status: s.status === 'done' ? 'done' : 'queued' };
                }
              });
            });
          }

          if (freshJob.status === JobStatusEnum.COMPLETED || freshJob.status === 'completed') {
            try {
              const freshDoc = await getDocument(id);
              if (isPolling) setDoc(freshDoc);
            } catch {
              // Ignore glitch, will fallback to freshReport.document
            }
            const freshReport = await getDocumentReport(id);
            if (!isPolling) return;
            setReport(freshReport);
            if (freshReport.document && isPolling) {
              setDoc(freshReport.document);
            }
            if (freshReport.results && freshReport.results.length > 0) {
              setLiveResults(freshReport.results);
            }
            setStages((prev) => prev.map((s) => ({ ...s, status: s.status === 'error' ? 'error' : 'done' })));
            return;
          } else if (freshJob.status === JobStatusEnum.FAILED || freshJob.status === 'failed') {
            if (!isPolling) return;
            setErrorMessage(freshJob.error_message || 'Background verification job failed.');
            return;
          }
        } catch {
          // If job endpoint 404s, fall through to document report poll
        }
      }

      // 2. Poll document status & report
      try {
        const freshDoc = await getDocument(id);
        if (!isPolling) return;
        setDoc(freshDoc);

        const freshReport = await getDocumentReport(id);
        if (!isPolling) return;
        setReport(freshReport);
        if (freshReport.results && freshReport.results.length > 0) {
          setLiveResults(freshReport.results);
        }

        if (freshDoc.status === 'completed' || freshDoc.status === 'audit_complete' || freshDoc.status === 'verified') {
          setStages((prev) => prev.map((s) => ({ ...s, status: s.status === 'error' ? 'error' : 'done' })));
        }
      } catch {
        // Ignore network polling glitches
      }
    };

    const intervalId = setInterval(pollStatus, 2500);
    return () => {
      isPolling = false;
      clearInterval(intervalId);
    };
  }, [id, isDemoDocId, jobIdParam, job?.job_id]);

  const handleLeave = () => {
    navigate('/');
  };

  const handleViewResults = () => {
    const targetUrl = `/documents/${id || 'sample-demo-4092'}/results${isDemo ? '?mode=demo' : ''}`;
    navigate(targetUrl);
  };

  // ---------------------------------------------------------------------------
  // Sequential Pipeline Stage Animation
  // ---------------------------------------------------------------------------
  const [visualCompletedCount, setVisualCompletedCount] = useState<number>(0);
  const [visualActiveIndex, setVisualActiveIndex] = useState<number>(0);

  // Accessibility: respect user preference for reduced motion
  const [prefersReducedMotion, setPrefersReducedMotion] = useState<boolean>(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return false;
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  });

  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return;
    const mediaQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
    const handleChange = (e: MediaQueryListEvent) => {
      setPrefersReducedMotion(e.matches);
    };
    mediaQuery.addEventListener('change', handleChange);
    return () => mediaQuery.removeEventListener('change', handleChange);
  }, []);

  // Compute backend truth target: how many stages the backend has actually finished
  const isJobFinished =
    job?.status === JobStatusEnum.COMPLETED ||
    job?.status === 'completed' ||
    doc?.status === 'completed' ||
    doc?.status === 'audit_complete' ||
    doc?.status === 'verified' ||
    streamStatus === 'closed' ||
    (stages.length === 8 && stages.every((s) => s.status === 'done'));

  const isJobFailed =
    job?.status === JobStatusEnum.FAILED ||
    job?.status === 'failed' ||
    stages.some((s) => s.status === 'error');

  const backendTargetCompleted = useMemo(() => {
    if (isJobFinished) return 8;
    if (isJobFailed) {
      const errIdx = stages.findIndex((s) => s.status === 'error');
      return errIdx !== -1 ? errIdx : 0;
    }
    const realDone = stages.filter((s) => s.status === 'done').length;
    return realDone;
  }, [isJobFinished, isJobFailed, stages]);

  const backendTargetActiveIdx = useMemo(() => {
    if (isJobFinished) return -1;
    if (isJobFailed) return -1;
    const actIdx = stages.findIndex((s) => s.status === 'active');
    if (actIdx !== -1) return actIdx;
    return backendTargetCompleted < 8 ? backendTargetCompleted : -1;
  }, [isJobFinished, isJobFailed, stages, backendTargetCompleted]);

  // Sequential progression effect: advances visual stages one-by-one with 500ms delay
  useEffect(() => {
    if (prefersReducedMotion) {
      setVisualCompletedCount(backendTargetCompleted);
      setVisualActiveIndex(backendTargetActiveIdx);
      return;
    }

    // If already caught up with backend progress
    if (visualCompletedCount >= backendTargetCompleted) {
      if (visualCompletedCount >= 8) {
        setVisualActiveIndex(-1);
      } else {
        setVisualActiveIndex(backendTargetActiveIdx);
      }
      return;
    }

    // The stage currently being completed shows active/in-progress
    setVisualActiveIndex(visualCompletedCount);

    const timer = setTimeout(() => {
      setVisualCompletedCount((prev) => {
        if (prev < backendTargetCompleted) {
          return prev + 1;
        }
        return prev;
      });
    }, 500);

    return () => clearTimeout(timer);
  }, [visualCompletedCount, backendTargetCompleted, backendTargetActiveIdx, prefersReducedMotion]);

  const currentProgressPercent = (visualCompletedCount / stages.length) * 100;

  return (
    <div className="bg-surface font-body-md text-on-surface antialiased flex flex-col min-h-screen">
      <Navbar
        documentTitle={doc?.title || "Document Analysis"}
        isAnalyzing={true}
      />

      <main className="w-full pt-28 pb-16 bg-surface flex-1">
        <div className="flex flex-col w-full">
          <div className="w-full flex justify-center py-space-lg px-gutter-sm sm:px-gutter">
            <div className="w-full max-w-[840px] flex flex-col gap-space-lg">

              {/* Demo Mode Notice Banner */}
              {isDemo && (
                <div className="w-full bg-amber-500/10 border border-amber-500/30 rounded-xl p-space-md flex items-start gap-space-sm shadow-xs">
                  <span className="material-symbols-outlined text-amber-800 text-[22px] shrink-0 mt-0.5">science</span>
                  <div className="flex flex-col text-sm text-amber-950">
                    <span className="font-semibold">DEMONSTRATION AUDIT MODE</span>
                    <span className="text-[13px] text-amber-900/90 mt-0.5">
                      You are previewing a demonstration paper with planted citation errors. This mode demonstrates pipeline transitions and is clearly separated from real verification audits.
                    </span>
                  </div>
                </div>
              )}

              {/* Error Banner */}
              {errorMessage && (
                <div className="w-full bg-error-container text-on-error-container rounded-xl p-space-md flex items-start justify-between gap-space-sm border border-error/30 shadow-xs">
                  <div className="flex items-start gap-space-sm">
                    <span className="material-symbols-outlined text-error text-[22px] shrink-0 mt-0.5">error</span>
                    <div className="flex flex-col">
                      <span className="font-semibold text-error">Unable to load document</span>
                      <span className="text-sm mt-0.5">{errorMessage}</span>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => navigate('/')}
                    className="px-3 py-1 bg-surface text-on-surface rounded text-xs font-semibold hover:bg-surface-container transition-colors shrink-0"
                  >
                    Return Home
                  </button>
                </div>
              )}

              {/* Persistent Connection & Session Info Banner */}
              <div className="w-full bg-surface-container-high rounded-lg p-space-md flex items-center justify-between shadow-sm">
                <div className="flex items-center gap-space-sm min-w-0">
                  <div className="w-7 h-7 rounded-full bg-surface-container flex items-center justify-center shrink-0">
                    <span className="material-symbols-outlined text-secondary text-[18px]">
                      {streamStatus === 'connected' ? 'cloud_done' : streamStatus === 'reconnecting' ? 'cloud_sync' : 'cloud_queue'}
                    </span>
                  </div>
                  <span className="font-body-md text-body-md text-on-surface truncate">
                    {streamStatus === 'connected'
                      ? 'Live connection active. Analysis executes on CiteVerify backend.'
                      : streamStatus === 'reconnecting'
                      ? 'Reconnecting to live SSE pipeline stream (polling fallback active)...'
                      : streamStatus === 'idle'
                      ? 'Stream idle. Polling backend for stage progress...'
                      : visualCompletedCount === stages.length
                      ? 'Verification pipeline completed. All 8 stages finished.'
                      : 'You can safely leave this page. Analysis status is saved.'}
                  </span>
                </div>
                <div className="flex items-center gap-space-xs shrink-0 pl-space-md">
                  <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium ${
                    streamStatus === 'connected'
                      ? 'bg-secondary-container/40 text-secondary'
                      : streamStatus === 'reconnecting'
                      ? 'bg-amber-500/20 text-amber-800'
                      : visualCompletedCount === stages.length
                      ? 'bg-primary-container text-on-primary'
                      : 'bg-surface-container text-on-surface-variant'
                  }`}>
                    <span className={`w-1.5 h-1.5 rounded-full ${
                      streamStatus === 'connected'
                        ? 'bg-secondary animate-pulse'
                        : streamStatus === 'reconnecting'
                        ? 'bg-amber-600 animate-ping'
                        : visualCompletedCount === stages.length
                        ? 'bg-primary'
                        : 'bg-outline'
                    }`}></span>
                    {streamStatus === 'connected' ? 'Stream Live' : streamStatus === 'reconnecting' ? 'Reconnecting' : visualCompletedCount === stages.length ? 'Completed' : 'Standby'}
                  </span>
                </div>
              </div>

              {/* Document Header Context & Action Panel */}
              <div className="w-full bg-surface-container-lowest rounded-xl p-space-lg shadow-sm flex flex-col sm:flex-row sm:items-center justify-between gap-space-md border border-outline-variant/30">
                <div className="flex items-start gap-space-md min-w-0">
                  <div className="w-12 h-12 rounded-lg bg-surface-container-high flex items-center justify-center shrink-0">
                    <span className="material-symbols-outlined text-primary text-[28px]">article</span>
                  </div>
                  <div className="flex flex-col min-w-0">
                    <div className="flex items-center gap-space-sm flex-wrap">
                      <span className="font-headline-sm text-headline-sm text-on-surface font-semibold truncate max-w-md">
                        {isLoading ? "Loading manuscript..." : (doc?.title || "Untitled Manuscript")}
                      </span>
                      <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-surface-container text-primary font-label-md text-label-md font-medium">
                        <span className="w-2 h-2 rounded-full bg-secondary-container animate-pulse"></span>
                        Status: {doc?.status || 'registered'}
                      </span>
                    </div>
                    <div className="flex items-center gap-space-sm mt-1 text-on-surface-variant font-body-sm text-body-sm flex-wrap">
                      <span>Doc ID: <span className="font-code-sm text-code-sm text-on-surface">{id}</span></span>
                      {(jobIdParam || job?.job_id) && (
                        <>
                          <span>•</span>
                          <span>Job ID: <span className="font-code-sm text-code-sm text-primary">{job?.job_id || jobIdParam}</span></span>
                          <span>•</span>
                          <span>Job: <span className="font-medium text-on-surface capitalize">{job?.status || 'queued'}</span></span>
                        </>
                      )}
                      {doc?.doi && (
                        <>
                          <span>•</span>
                          <span>DOI: <span className="font-code-sm text-code-sm text-on-surface">{doc.doi}</span></span>
                        </>
                      )}
                      {doc?.authors && (
                        <>
                          <span>•</span>
                          <span>{doc.authors}</span>
                        </>
                      )}
                    </div>
                  </div>
                </div>

                {/* Honest Controls: No fake pause/resume */}
                <div className="flex items-center gap-space-sm shrink-0">
                  <button
                    type="button"
                    disabled
                    title="Pause and resume operations are not supported by the backend pipeline"
                    className="px-space-md py-2 rounded-lg bg-surface-container/60 text-on-surface-variant font-label-md text-label-md transition-colors flex items-center gap-1.5 cursor-not-allowed opacity-60"
                  >
                    <span className="material-symbols-outlined text-[18px]">pause_circle</span>
                    <span>Pause (Unsupported)</span>
                  </button>
                  <button
                    type="button"
                    onClick={handleLeave}
                    className="px-space-md py-2 rounded-lg bg-surface-container hover:bg-surface-container-high text-on-surface font-label-md text-label-md transition-colors flex items-center gap-1.5 cursor-pointer"
                  >
                    <span className="material-symbols-outlined text-[18px]">arrow_back</span>
                    <span>Back</span>
                  </button>
                </div>
              </div>

              {/* Horizontal Stepper (8 Stages) */}
              <div className="w-full bg-surface-container-lowest rounded-xl p-space-lg shadow-sm border border-outline-variant/30">
                <div className="flex items-center justify-between mb-space-md">
                  <div className="flex items-center gap-space-xs">
                    <span className="material-symbols-outlined text-primary text-[20px]">account_tree</span>
                    <span className="font-label-md text-label-md text-on-surface font-semibold uppercase tracking-wider">
                      Verification Pipeline
                    </span>
                  </div>
                  <span className="font-body-sm text-body-sm text-on-surface-variant">
                    {visualCompletedCount} of {stages.length} stages completed
                    {visualActiveIndex >= 0 ? ` · Stage ${visualActiveIndex + 1} active` : ''}
                  </span>
                </div>

                {/* Track Line & Stage Nodes */}
                <div className="w-full overflow-x-auto pb-space-xs">
                  <div className="min-w-[720px] flex items-start justify-between relative px-2">
                    <div className="absolute top-4 left-6 right-6 h-0.5 bg-surface-container -z-0">
                      <div
                        className="h-full bg-primary-container transition-all duration-500 ease-out"
                        style={{ width: `${currentProgressPercent}%` }}
                      ></div>
                    </div>

                    {stages.map((stage, idx) => {
                      const isDone = idx < visualCompletedCount;
                      const isActive = idx === visualActiveIndex;
                      const isError = stage.status === 'error' && idx === visualCompletedCount;

                      return (
                        <div key={stage.id} className="relative z-10 flex flex-col items-center text-center w-24">
                          {isDone ? (
                            <div className="w-8 h-8 rounded-full bg-primary-container text-on-primary flex items-center justify-center shadow-sm transition-all duration-300">
                              <span className="material-symbols-outlined text-[18px]">check</span>
                            </div>
                          ) : isActive ? (
                            <div className="w-8 h-8 rounded-full bg-surface-container-lowest text-primary flex items-center justify-center shadow-md ring-4 ring-primary-container/20 transition-all duration-300">
                              <span className="material-symbols-outlined text-[20px] animate-spin text-primary">progress_activity</span>
                            </div>
                          ) : isError ? (
                            <div className="w-8 h-8 rounded-full bg-error-container text-error flex items-center justify-center shadow-sm transition-all duration-300">
                              <span className="material-symbols-outlined text-[18px]">error</span>
                            </div>
                          ) : (
                            <div className="w-8 h-8 rounded-full bg-surface-container text-on-surface-variant flex items-center justify-center transition-all duration-300">
                              <span className="material-symbols-outlined text-[18px]">radio_button_unchecked</span>
                            </div>
                          )}

                          <span className={`font-label-md text-label-md mt-2 transition-colors duration-200 ${
                            isActive ? 'text-primary font-bold' : isDone ? 'text-on-surface font-semibold' : 'text-on-surface-variant'
                          }`}>
                            {stage.name}
                          </span>
                          <span className="font-body-sm text-[12px] text-on-surface-variant leading-tight">
                            {isDone
                              ? (stage.detail && stage.detail !== 'Queued' ? stage.detail : 'Completed')
                              : isActive
                              ? (stage.detail && stage.detail !== 'Queued' ? stage.detail : 'In progress')
                              : stage.detail}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>

              {/* Live Events Stream Feed (Real SSE Output) */}
              {!isDemo && liveEvents.length > 0 && (
                <div className="w-full bg-surface-container-lowest rounded-xl p-space-md shadow-sm border border-outline-variant/30 flex flex-col gap-space-xs">
                  <div className="flex items-center justify-between">
                    <span className="font-label-md text-label-md text-on-surface font-semibold flex items-center gap-2">
                      <span className="material-symbols-outlined text-[18px] text-secondary">terminal</span>
                      Live Pipeline Stream
                    </span>
                    <span className="font-code-sm text-xs text-on-surface-variant">Last-Event: {liveEvents[0].event}</span>
                  </div>
                  <div className="max-h-36 overflow-y-auto space-y-1.5 p-2 bg-surface-container-low rounded-lg font-code-sm text-xs text-on-surface-variant">
                    {liveEvents.map((ev, i) => (
                      <div key={i} className="flex items-start gap-2">
                        <span className="text-primary font-bold shrink-0">[{ev.stage || ev.event}]</span>
                        <span className="text-on-surface">{ev.message || JSON.stringify(ev.payload || '')}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Real Mode vs Demo Mode Results Feed */}
              {!isDemo ? (
                /* REAL DOCUMENT FEED */
                <div className="w-full flex flex-col gap-space-md">
                  <div className="flex items-center justify-between flex-wrap gap-space-xs">
                    <div className="flex items-center gap-space-sm">
                      <h2 className="font-headline-sm text-headline-sm text-on-surface">Verification Status</h2>
                      <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded bg-surface-container text-secondary font-label-sm text-label-sm">
                        <span className="w-1.5 h-1.5 rounded-full bg-secondary animate-pulse"></span>
                        LIVE STREAM
                      </span>
                    </div>
                    <span className="font-body-sm text-body-sm text-on-surface-variant">
                      Backend Document Status: <span className="font-medium text-on-surface">{doc?.status || 'pending'}</span>
                    </span>
                  </div>

                  {/* Honest Representation of Real Verification State */}
                  {liveResults.length > 0 ? (
                    <div className="flex flex-col gap-space-sm">
                      {liveResults.map((res) => (
                        <div key={res.id} className="w-full bg-surface-container-lowest rounded-xl p-space-md shadow-sm flex flex-col gap-space-xs border border-outline-variant/20">
                          <div className="flex items-start justify-between gap-space-sm">
                            <div className="flex-1 min-w-0">
                              <p className="font-headline-sm text-on-surface text-[1.125rem] leading-snug">
                                {res.claim?.claim_text || `Claim ID: ${res.claim_id}`}
                              </p>
                              {res.claim?.section_name && (
                                <span className="font-body-sm text-on-surface-variant text-xs mt-1 block">
                                  Section: {res.claim.section_name}
                                </span>
                              )}
                            </div>
                            <span className="shrink-0 inline-flex items-center gap-1 px-2.5 py-1 rounded bg-surface-container-high text-primary font-label-md text-sm font-semibold">
                              {res.verdict}
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="w-full bg-surface-container-lowest rounded-xl p-8 text-center flex flex-col items-center justify-center gap-3 border border-outline-variant/30">
                      <div className="w-12 h-12 rounded-full bg-surface-container-high flex items-center justify-center text-primary">
                        <span className="material-symbols-outlined text-[24px]">hourglass_empty</span>
                      </div>
                      <div className="flex flex-col gap-1 max-w-md">
                        <p className="font-label-md text-base text-on-surface font-semibold">
                          Automated Verification Pending
                        </p>
                        <p className="font-body-sm text-sm text-on-surface-variant leading-relaxed">
                          This manuscript is registered in CiteVerify (status: <code className="font-code-sm text-on-surface">{doc?.status || 'pending'}</code>).
                          {streamedRefCount > 0 ? ` Extracted ${streamedRefCount} references.` : ''}
                          {streamedClaimCount > 0 ? ` Extracted ${streamedClaimCount} assertions.` : ''}
                          {report?.status_note ? ` ${report.status_note}` : ' Automated verification results will appear as pipeline workers execute.'}
                        </p>
                      </div>
                      <div className="flex items-center gap-2 pt-2">
                        <button
                          type="button"
                          onClick={() => window.location.reload()}
                          className="px-4 py-2 rounded-lg bg-surface-container-high hover:bg-surface-container text-on-surface font-label-md text-xs font-semibold transition-colors flex items-center gap-1.5 cursor-pointer"
                        >
                          <span className="material-symbols-outlined text-[16px]">refresh</span>
                          Refresh Status
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                /* DEMO MODE ILLUSTRATIVE FEED */
                <div className="w-full flex flex-col gap-space-md">
                  <div className="flex items-center justify-between flex-wrap gap-space-xs">
                    <div className="flex items-center gap-space-sm">
                      <h2 className="font-headline-sm text-headline-sm text-on-surface">Demonstration Stream</h2>
                      <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded bg-amber-500/15 text-amber-900 font-label-sm text-label-sm font-semibold">
                        DEMO SAMPLES
                      </span>
                    </div>
                    <span className="font-body-sm text-body-sm text-on-surface-variant">
                      Showing simulated claims for feature demonstration
                    </span>
                  </div>

                  <div className="flex flex-col gap-space-sm">
                    {/* Demo Row 1: Partly supported */}
                    <div className="w-full bg-surface-container-lowest rounded-xl p-space-md shadow-sm flex flex-col gap-space-xs border border-outline-variant/20 hover:bg-surface-container-low transition-colors">
                      <div className="flex items-start justify-between gap-space-sm">
                        <div className="flex-1 min-w-0">
                          <p className="font-headline-sm text-headline-sm text-on-surface text-[1.125rem] leading-snug">
                            “A study found that a learning app improved test scores by 30%.”
                          </p>
                          <div className="flex items-center gap-space-sm mt-1.5 font-body-sm text-body-sm text-on-surface-variant">
                            <span className="font-medium text-on-surface">Page 4, ¶ 2</span>
                            <span>•</span>
                            <span>Ref: <span className="font-code-sm text-code-sm">10.1037/edu0000412</span></span>
                          </div>
                        </div>
                        <span className="shrink-0 inline-flex items-center gap-1 px-2.5 py-1 rounded bg-tertiary-fixed text-tertiary font-label-md text-label-md font-semibold">
                          <span className="material-symbols-outlined text-[16px]">pie_chart</span>
                          Partly supported
                        </span>
                      </div>
                      <div className="flex items-center gap-space-sm pt-2 text-body-sm text-body-sm">
                        <span className="px-2 py-0.5 rounded bg-surface-container text-on-surface-variant font-label-sm text-label-sm">Abstract only</span>
                        <span className="text-tertiary font-medium flex items-center gap-1">
                          <span className="material-symbols-outlined text-[16px]">info</span> Quantitative mismatch: source reports 18.4% improvement
                        </span>
                      </div>
                    </div>

                    {/* Demo Row 2: Supported */}
                    <div className="w-full bg-surface-container-lowest rounded-xl p-space-md shadow-sm flex flex-col gap-space-xs border border-outline-variant/20 hover:bg-surface-container-low transition-colors">
                      <div className="flex items-start justify-between gap-space-sm">
                        <div className="flex-1 min-w-0">
                          <p className="font-headline-sm text-headline-sm text-on-surface text-[1.125rem] leading-snug">
                            “Metformin administration delays cellular senescence biomarkers in control mice…”
                          </p>
                          <div className="flex items-center gap-space-sm mt-1.5 font-body-sm text-body-sm text-on-surface-variant">
                            <span className="font-medium text-on-surface">Page 2, ¶ 5</span>
                            <span>•</span>
                            <span>Ref: <span className="font-code-sm text-code-sm">10.1038/s41586-021-03912-w</span></span>
                          </div>
                        </div>
                        <span className="shrink-0 inline-flex items-center gap-1 px-2.5 py-1 rounded bg-secondary-container/40 text-secondary font-label-md text-label-md font-semibold">
                          <span className="material-symbols-outlined text-[16px]">verified</span>
                          Supported
                        </span>
                      </div>
                      <div className="flex items-center gap-space-sm pt-2 text-body-sm text-body-sm">
                        <span className="px-2 py-0.5 rounded bg-surface-container text-on-surface-variant font-label-sm text-label-sm">Full text</span>
                        <span className="text-secondary font-medium flex items-center gap-1">
                          <span className="material-symbols-outlined text-[16px]">done_all</span> Exact match confirmed against Fig 3B dataset
                        </span>
                      </div>
                    </div>

                    {/* Demo Row 3: Contradictory */}
                    <div className="w-full bg-surface-container-lowest rounded-xl p-space-md shadow-sm flex flex-col gap-space-xs border border-outline-variant/20 hover:bg-surface-container-low transition-colors">
                      <div className="flex items-start justify-between gap-space-sm">
                        <div className="flex-1 min-w-0">
                          <p className="font-headline-sm text-headline-sm text-on-surface text-[1.125rem] leading-snug">
                            “Ambient pressure superconductivity demonstrated at 294 K in modified lead-…”
                          </p>
                          <div className="flex items-center gap-space-sm mt-1.5 font-body-sm text-body-sm text-on-surface-variant">
                            <span className="font-medium text-on-surface">Page 11, ¶ 3</span>
                            <span>•</span>
                            <span>Ref: <span className="font-code-sm text-code-sm">10.48550/arXiv.2307.12008</span></span>
                          </div>
                        </div>
                        <span className="shrink-0 inline-flex items-center gap-1 px-2.5 py-1 rounded bg-error-container text-error font-label-md text-label-md font-semibold">
                          <span className="material-symbols-outlined text-[16px]">compare_arrows</span>
                          Contradictory
                        </span>
                      </div>
                      <div className="flex items-center gap-space-sm pt-2 text-body-sm text-body-sm">
                        <span className="px-2 py-0.5 rounded bg-surface-container text-on-surface-variant font-label-sm text-label-sm">Preprint</span>
                        <span className="text-error font-medium flex items-center gap-1">
                          <span className="material-symbols-outlined text-[16px]">report</span> Flagged: Retracted Paper (Notice #RW2023-88)
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* Bottom Actions & Navigation Panel */}
              <div className="w-full bg-surface-container-low rounded-xl p-space-lg shadow-sm flex flex-col sm:flex-row items-center justify-between gap-space-md border border-outline-variant/20">
                <div className="flex flex-col gap-1 w-full sm:w-auto">
                  <div className="flex items-center gap-space-xs">
                    <span className="material-symbols-outlined text-secondary text-[20px]">verified</span>
                    <span className="font-label-md text-label-md text-on-surface font-semibold">
                      Verification Report Ready
                    </span>
                  </div>
                  <p className="font-body-sm text-body-sm text-on-surface-variant">
                    {isDemo
                      ? "Explore full demonstration audit findings with claim-by-claim reviews and filters."
                      : "Access the aggregate audit report, human-in-the-loop review actions, and JSON export."}
                  </p>
                </div>

                <div className="flex items-center gap-space-sm w-full sm:w-auto justify-end">
                  <button
                    type="button"
                    onClick={handleViewResults}
                    className="px-space-lg py-2.5 rounded bg-primary-container text-on-primary hover:bg-primary transition-colors font-label-md text-label-md font-medium shadow-sm flex items-center gap-1.5 cursor-pointer"
                  >
                    <span>{isDemo ? "Explore Demo Results" : "View Audit Report"}</span>
                    <span className="material-symbols-outlined text-[18px]">arrow_forward</span>
                  </button>
                </div>
              </div>

            </div>
          </div>
        </div>
      </main>

      <Footer />
    </div>
  );
};
