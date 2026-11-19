import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Navbar, Footer } from '../components/layout/Navbar';
import { getDocument } from '../lib/api';
import { DocumentResponse, SSEPipelineEvent } from '../types';

interface StageInfo {
  id: string;
  name: string;
  status: 'done' | 'active' | 'queued';
  detail: string;
}

export const AnalysisPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const [doc, setDoc] = useState<DocumentResponse | null>(null);
  const [isPaused, setIsPaused] = useState(false);
  const [currentProgress, setCurrentProgress] = useState(62.5);
  const [completedClaimsCount, setCompletedClaimsCount] = useState(6);
  const [totalClaimsCount, setTotalClaimsCount] = useState(14);
  const [activeStageIndex, setActiveStageIndex] = useState(4); // 0-indexed: 4 is Stage 5 (Verify)

  // 8 Pipeline Stages
  const [stages, setStages] = useState<StageInfo[]>([
    { id: 's1_parse', name: 'Parse', status: 'done', detail: '18 pgs parsed' },
    { id: 's2_references', name: 'References', status: 'done', detail: '23 resolved' },
    { id: 's3_claims', name: 'Claims', status: 'done', detail: '41 extracted' },
    { id: 's4_resolve', name: 'Resolve', status: 'done', detail: '23 DOIs queried' },
    { id: 's5_evidence', name: 'Evidence', status: 'active', detail: '6 of 14 retrieved' },
    { id: 's6_verify', name: 'Verify', status: 'queued', detail: 'Queued' },
    { id: 's7_assessment', name: 'Assessment', status: 'queued', detail: 'Queued' },
    { id: 's8_persist', name: 'Persist', status: 'queued', detail: 'Queued' },
  ]);

  useEffect(() => {
    if (!id) return;

    // Fetch document details from real backend
    getDocument(id)
      .then((data) => setDoc(data))
      .catch((err) => {
        console.warn("Could not fetch document from API, using demo context:", err);
        setDoc({
          id: id,
          title: "sample_paper.pdf",
          doi: "10.1016/j.cell.2023.11.008",
          authors: "Vaswani et al.",
          status: "analyzing",
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        });
      });

    // Native SSE EventSource connection
    let eventSource: EventSource | null = null;
    try {
      eventSource = new EventSource(`/api/documents/${id}/events`);
      eventSource.onmessage = (event) => {
        try {
          const parsed: SSEPipelineEvent = JSON.parse(event.data);
          console.log("SSE event received:", parsed);
        } catch (e) {
          console.error("SSE parse error", e);
        }
      };
      eventSource.onerror = (err) => {
        console.warn("SSE connection error or closed:", err);
      };
    } catch (e) {
      console.warn("EventSource failed to initialize:", e);
    }

    return () => {
      if (eventSource) {
        eventSource.close();
      }
    };
  }, [id]);

  const handleCancel = () => {
    navigate('/');
  };

  const handleViewResults = () => {
    navigate(`/documents/${id || 'sample-demo-4092'}/results`);
  };

  return (
    <div className="bg-surface font-body-md text-on-surface antialiased flex flex-col min-h-screen">
      <Navbar
        documentTitle={doc?.title || "sample_paper.pdf"}
        isAnalyzing={true}
      />

      <main className="w-full pt-28 pb-16 bg-surface flex-1">
        <div className="flex flex-col w-full">
          <div className="w-full flex justify-center py-space-lg px-gutter-sm sm:px-gutter">
            <div className="w-full max-w-[820px] flex flex-col gap-space-lg">
              
              {/* Persistent Info Banner */}
              <div className="w-full bg-surface-container-high rounded-lg p-space-md flex items-center justify-between shadow-sm">
                <div className="flex items-center gap-space-sm min-w-0">
                  <div className="w-7 h-7 rounded-full bg-surface-container flex items-center justify-center shrink-0">
                    <span className="material-symbols-outlined text-secondary text-[18px]">cloud_sync</span>
                  </div>
                  <span className="font-body-md text-body-md text-on-surface truncate">
                    You can safely leave this page. Analysis executes remotely and your session progress is saved.
                  </span>
                </div>
                <div className="flex items-center gap-space-xs shrink-0 pl-space-md">
                  <span className="font-label-sm text-label-sm text-on-surface-variant uppercase tracking-wider">
                    Session Active
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
                      <span className="font-headline-sm text-headline-sm text-on-surface font-semibold truncate">
                        {doc?.title || "sample_paper.pdf"}
                      </span>
                      <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-surface-container text-primary font-label-md text-label-md font-medium">
                        <span className="w-2 h-2 rounded-full bg-secondary-container animate-pulse"></span>
                        Analysis in progress
                      </span>
                    </div>
                    <div className="flex items-center gap-space-sm mt-1 text-on-surface-variant font-body-sm text-body-sm">
                      <span>2.4 MB</span>
                      <span>•</span>
                      <span>18 pages</span>
                      <span>•</span>
                      <span>
                        Identified: <span className="font-code-sm text-code-sm text-on-surface">{doc?.doi || "10.1016/j.cell.2023.11.008"}</span>
                      </span>
                    </div>
                  </div>
                </div>

                <div className="flex items-center gap-space-sm shrink-0">
                  <button
                    type="button"
                    onClick={() => setIsPaused(!isPaused)}
                    className="px-space-md py-2 rounded-lg bg-surface-container hover:bg-surface-container-high text-on-surface font-label-md text-label-md transition-colors flex items-center gap-1.5 cursor-pointer"
                  >
                    <span className="material-symbols-outlined text-[18px]">
                      {isPaused ? 'play_circle' : 'pause_circle'}
                    </span>
                    <span>{isPaused ? 'Resume' : 'Pause'}</span>
                  </button>
                  <button
                    type="button"
                    onClick={handleCancel}
                    className="px-space-md py-2 rounded-lg bg-error-container/40 hover:bg-error-container text-on-error-container font-label-md text-label-md transition-colors flex items-center gap-1.5 cursor-pointer"
                  >
                    <span className="material-symbols-outlined text-[18px]">cancel</span>
                    <span>Cancel analysis</span>
                  </button>
                </div>
              </div>

              {/* Horizontal Stepper (8 Stages strictly) */}
              <div className="w-full bg-surface-container-lowest rounded-xl p-space-lg shadow-sm border border-outline-variant/30">
                <div className="flex items-center justify-between mb-space-md">
                  <div className="flex items-center gap-space-xs">
                    <span className="material-symbols-outlined text-primary text-[20px]">account_tree</span>
                    <span className="font-label-md text-label-md text-on-surface font-semibold uppercase tracking-wider">
                      Verification Pipeline
                    </span>
                  </div>
                  <span className="font-body-sm text-body-sm text-on-surface-variant">
                    Step {activeStageIndex + 1} of 8 active
                  </span>
                </div>

                {/* Track Line & Stage Nodes */}
                <div className="w-full overflow-x-auto pb-space-xs">
                  <div className="min-w-[720px] flex items-start justify-between relative px-2">
                    <div className="absolute top-4 left-6 right-6 h-0.5 bg-surface-container -z-0">
                      <div
                        className="h-full bg-primary-container transition-all duration-500"
                        style={{ width: `${currentProgress}%` }}
                      ></div>
                    </div>

                    {stages.map((stage, idx) => (
                      <div key={stage.id} className="relative z-10 flex flex-col items-center text-center w-24">
                        {stage.status === 'done' ? (
                          <div className="w-8 h-8 rounded-full bg-primary-container text-on-primary flex items-center justify-center shadow-sm">
                            <span className="material-symbols-outlined text-[18px]">check</span>
                          </div>
                        ) : stage.status === 'active' ? (
                          <div className="w-8 h-8 rounded-full bg-surface-container-lowest text-primary flex items-center justify-center shadow-md ring-4 ring-primary-container/20">
                            <span className="material-symbols-outlined text-[20px] animate-spin text-primary">progress_activity</span>
                          </div>
                        ) : (
                          <div className="w-8 h-8 rounded-full bg-surface-container text-on-surface-variant flex items-center justify-center">
                            <span className="material-symbols-outlined text-[18px]">radio_button_unchecked</span>
                          </div>
                        )}

                        <span className={`font-label-md text-label-md mt-2 ${stage.status === 'active' ? 'text-primary font-bold' : 'text-on-surface font-semibold'}`}>
                          {stage.name}
                        </span>
                        <span className="font-body-sm text-[12px] text-on-surface-variant leading-tight">
                          {stage.detail}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              {/* Reference Health Triage Strip */}
              <div className="w-full bg-surface-container-lowest rounded-xl p-space-md shadow-sm flex flex-col gap-space-sm border border-outline-variant/30">
                <div className="flex items-center justify-between flex-wrap gap-space-xs">
                  <span className="font-label-md text-label-md text-on-surface font-semibold">
                    Reference Health Triage
                  </span>
                  <span className="font-body-sm text-body-sm text-on-surface-variant">
                    Crossref, PubMed & Retraction Watch databases
                  </span>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-space-sm">
                  {/* Verified */}
                  <div className="bg-surface-container-low rounded-lg p-space-sm flex items-center gap-space-sm border border-outline-variant/20">
                    <div className="w-8 h-8 rounded bg-secondary-container/30 flex items-center justify-center shrink-0">
                      <span className="material-symbols-outlined text-secondary text-[20px]">check_circle</span>
                    </div>
                    <div className="flex flex-col min-w-0">
                      <span className="font-label-md text-label-md text-on-surface font-bold">19</span>
                      <span className="font-body-sm text-body-sm text-on-surface-variant truncate">Verified</span>
                    </div>
                  </div>
                  {/* DOI mismatch */}
                  <div className="bg-surface-container-low rounded-lg p-space-sm flex items-center gap-space-sm border border-outline-variant/20">
                    <div className="w-8 h-8 rounded bg-tertiary-fixed flex items-center justify-center shrink-0">
                      <span className="material-symbols-outlined text-tertiary text-[20px]">warning</span>
                    </div>
                    <div className="flex flex-col min-w-0">
                      <span className="font-label-md text-label-md text-on-surface font-bold">2</span>
                      <span className="font-body-sm text-body-sm text-on-surface-variant truncate">DOI mismatch</span>
                    </div>
                  </div>
                  {/* Retracted */}
                  <div className="bg-surface-container-low rounded-lg p-space-sm flex items-center gap-space-sm border border-outline-variant/20">
                    <div className="w-8 h-8 rounded bg-error-container flex items-center justify-center shrink-0">
                      <span className="material-symbols-outlined text-error text-[20px]">error</span>
                    </div>
                    <div className="flex flex-col min-w-0">
                      <span className="font-label-md text-label-md text-on-surface font-bold">1</span>
                      <span className="font-body-sm text-body-sm text-error truncate font-medium">Retracted</span>
                    </div>
                  </div>
                  {/* Not found */}
                  <div className="bg-surface-container-low rounded-lg p-space-sm flex items-center gap-space-sm border border-outline-variant/20">
                    <div className="w-8 h-8 rounded bg-surface-container-high flex items-center justify-center shrink-0">
                      <span className="material-symbols-outlined text-outline text-[20px]">help_center</span>
                    </div>
                    <div className="flex flex-col min-w-0">
                      <span className="font-label-md text-label-md text-on-surface font-bold">1</span>
                      <span className="font-body-sm text-body-sm text-on-surface-variant truncate">Not found</span>
                    </div>
                  </div>
                </div>
              </div>

              {/* Results So Far Live Stream Section */}
              <div className="w-full flex flex-col gap-space-md">
                <div className="flex items-center justify-between flex-wrap gap-space-xs">
                  <div className="flex items-center gap-space-sm">
                    <h2 className="font-headline-sm text-headline-sm text-on-surface">Results so far</h2>
                    <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded bg-surface-container text-secondary font-label-sm text-label-sm">
                      <span className="w-1.5 h-1.5 rounded-full bg-secondary animate-pulse"></span>
                      LIVE STREAM
                    </span>
                  </div>
                  <span className="font-body-sm text-body-sm text-on-surface-variant">
                    Streaming completed claim checks ({completedClaimsCount} completed, {totalClaimsCount - completedClaimsCount} in queue)
                  </span>
                </div>

                {/* Claims Feed Stack */}
                <div className="flex flex-col gap-space-sm">
                  {/* Row 1: Partly supported */}
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

                  {/* Row 2: Supported */}
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

                  {/* Row 3: Contradictory (Retracted paper) */}
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

                  {/* Row 4: Active Claim Currently Comparing */}
                  <div className="w-full bg-surface-container-low rounded-xl p-space-md shadow-sm flex flex-col gap-space-sm ring-1 ring-primary/20 border border-primary/20">
                    <div className="flex items-start justify-between gap-space-sm">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="w-2 h-2 rounded-full bg-primary animate-ping"></span>
                          <span className="font-label-sm text-label-sm text-primary font-bold uppercase tracking-wider">
                            Evaluating Sentence
                          </span>
                        </div>
                        <p className="font-headline-sm text-headline-sm text-on-surface text-[1.125rem] leading-snug">
                          “Early dietary zinc intervention cut infant diarrhea duration by 48 hours…”
                        </p>
                        <div className="flex items-center gap-space-sm mt-1.5 font-body-sm text-body-sm text-on-surface-variant">
                          <span className="font-medium text-on-surface">Page 14, ¶ 2</span>
                          <span>•</span>
                          <span>Target Ref: <span className="font-code-sm text-code-sm">10.1016/S0140-6736(00)02082-8</span></span>
                        </div>
                      </div>
                      <span className="shrink-0 inline-flex items-center gap-1.5 px-3 py-1 rounded bg-surface-container-highest text-primary font-label-md text-label-md font-medium">
                        <span className="material-symbols-outlined text-[18px] animate-spin">sync</span>
                        Matching
                      </span>
                    </div>
                    {/* Pulsing loader bar */}
                    <div className="w-full bg-surface-container-highest rounded-full h-1.5 overflow-hidden">
                      <div className="h-full bg-primary-container rounded-full animate-pulse w-3/4"></div>
                    </div>
                    <div className="flex items-center gap-space-xs font-body-sm text-body-sm text-on-surface-variant">
                      <span className="material-symbols-outlined text-[16px] text-primary">download</span>
                      <span>Retrieving source quote from PubMed Central OA repository...</span>
                    </div>
                  </div>
                </div>
              </div>

              {/* Bottom Actions & Completion Panel */}
              <div className="w-full bg-surface-container-low rounded-xl p-space-lg shadow-sm flex flex-col sm:flex-row items-center justify-between gap-space-md border border-outline-variant/20">
                <div className="flex flex-col gap-1 w-full sm:w-auto">
                  <div className="flex items-center gap-space-xs">
                    <span className="material-symbols-outlined text-secondary text-[20px]">notifications_active</span>
                    <span className="font-label-md text-label-md text-on-surface font-semibold">
                      Notify upon completion
                    </span>
                  </div>
                  <p className="font-body-sm text-body-sm text-on-surface-variant">
                    Large audits take several minutes. We will email the audit digest once all 14 claims conclude.
                  </p>
                  <div className="flex items-center gap-space-xs mt-2">
                    <input
                      type="email"
                      placeholder="researcher@university.edu"
                      className="px-space-md py-1.5 rounded bg-surface-container-lowest text-on-surface font-body-sm text-body-sm placeholder:text-outline focus:outline-none focus:ring-1 focus:ring-primary w-64 shadow-sm border border-outline-variant/30"
                    />
                    <button
                      type="button"
                      className="px-space-md py-1.5 rounded bg-surface-container-highest hover:bg-surface-container text-on-surface font-label-md text-label-md transition-colors cursor-pointer"
                    >
                      Save
                    </button>
                  </div>
                </div>

                <div className="flex items-center gap-space-sm w-full sm:w-auto justify-end">
                  <button
                    type="button"
                    onClick={handleViewResults}
                    className="px-space-lg py-2.5 rounded bg-primary-container text-on-primary hover:bg-primary transition-colors font-label-md text-label-md font-medium shadow-sm flex items-center gap-1.5 cursor-pointer"
                  >
                    <span>View partial results</span>
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

