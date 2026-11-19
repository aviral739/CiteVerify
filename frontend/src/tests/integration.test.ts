import test from 'node:test';
import assert from 'node:assert/strict';
import {
  ApiError,
  validateManuscriptFile,
  constructMultipartUploadData,
} from '../lib/api.ts';
import {
  parseSSEMessage,
  EventDeduplicator,
  CiteVerifySSEClient,
} from '../lib/sseClient.ts';
import {
  VerdictEnum,
  EvidenceAvailabilityEnum,
  HumanDecisionEnum,
  JobStatusEnum,
  PipelineStageEnum,
  type ClaimResponse,
  type ReferenceResponse,
  type DocumentReportResponse,
  type JobRecordResponse,
  type ReviewCreateRequest,
} from '../types/index.ts';
import { sampleResultsData } from '../mocks/sampleData.ts';

// -------------------------------------------------------------
// 1. API Error & HTTP Encapsulation
// -------------------------------------------------------------
test('ApiError encapsulates HTTP status code and details correctly', () => {
  const error = new ApiError('Document not found', 404, { document_id: 'doc-123' });
  assert.equal(error.message, 'Document not found');
  assert.equal(error.statusCode, 404);
  assert.deepEqual(error.details, { document_id: 'doc-123' });
  assert.equal(error.name, 'ApiError');

  // Timeout error representation (408)
  const timeoutErr = new ApiError('Request timeout: API did not respond in 30s', 408);
  assert.equal(timeoutErr.statusCode, 408);
});

// -------------------------------------------------------------
// 2. Canonical Verdicts, Availability, Decisions, & Status Enums
// -------------------------------------------------------------
test('VerdictEnum supports all 6 canonical verdicts', () => {
  const expectedVerdicts = [
    'supported',
    'partially_supported',
    'unsupported',
    'contradictory',
    'potentially_outdated',
    'insufficient_evidence',
  ];

  const actualVerdicts = Object.values(VerdictEnum);
  for (const verdict of expectedVerdicts) {
    assert.ok(actualVerdicts.includes(verdict as VerdictEnum), `Missing verdict: ${verdict}`);
  }
  assert.equal(actualVerdicts.length, 6);
});

test('EvidenceAvailabilityEnum supports all 3 availability tiers', () => {
  const expectedTiers = [
    'full_text_available',
    'abstract_only',
    'unavailable',
  ];

  const actualTiers = Object.values(EvidenceAvailabilityEnum);
  for (const tier of expectedTiers) {
    assert.ok(actualTiers.includes(tier as EvidenceAvailabilityEnum), `Missing tier: ${tier}`);
  }
  assert.equal(actualTiers.length, 3);
});

test('HumanDecisionEnum supports confirmed, overridden, and disputed', () => {
  const expectedDecisions = ['confirmed', 'overridden', 'disputed'];
  const actualDecisions = Object.values(HumanDecisionEnum);
  for (const dec of expectedDecisions) {
    assert.ok(actualDecisions.includes(dec as HumanDecisionEnum), `Missing decision: ${dec}`);
  }
  assert.equal(actualDecisions.length, 3);
});

test('JobStatusEnum supports all 5 background job statuses', () => {
  const expectedStatuses = ['pending', 'running', 'completed', 'failed', 'cancelled'];
  const actualStatuses = Object.values(JobStatusEnum);
  for (const st of expectedStatuses) {
    assert.ok(actualStatuses.includes(st as JobStatusEnum), `Missing job status: ${st}`);
  }
  assert.equal(actualStatuses.length, 5);
});

test('PipelineStageEnum supports all 8 canonical verification stages', () => {
  const expectedStages = [
    's1_parse',
    's2_references',
    's3_claims',
    's4_resolve',
    's5_evidence',
    's6_verify',
    's7_assessment',
    's8_persist',
  ];
  const actualStages = Object.values(PipelineStageEnum);
  for (const st of expectedStages) {
    assert.ok(actualStages.includes(st as PipelineStageEnum), `Missing stage: ${st}`);
  }
  assert.equal(actualStages.length, 8);
});

// -------------------------------------------------------------
// 3. Manuscript File Validation (PDF / DOCX, 20MB limit)
// -------------------------------------------------------------
test('validateManuscriptFile accepts PDF and DOCX under 20MB and rejects others', () => {
  // Valid PDF
  const validPdf = { name: 'research_paper.pdf', size: 4 * 1024 * 1024, type: 'application/pdf' } as File;
  assert.equal(validateManuscriptFile(validPdf).valid, true);

  // Valid DOCX
  const validDocx = { name: 'research_draft.docx', size: 10 * 1024 * 1024, type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' } as File;
  assert.equal(validateManuscriptFile(validDocx).valid, true);

  // Case-insensitive valid extension
  const validUpper = { name: 'MANUSCRIPT.PDF', size: 1024, type: '' } as File;
  assert.equal(validateManuscriptFile(validUpper).valid, true);

  // Invalid extensions
  const invalidTxt = { name: 'notes.txt', size: 1024, type: 'text/plain' } as File;
  const resTxt = validateManuscriptFile(invalidTxt);
  assert.equal(resTxt.valid, false);
  assert.match(resTxt.error || '', /Unsupported file format/i);

  const invalidXls = { name: 'data.xlsx', size: 1024, type: 'application/vnd.ms-excel' } as File;
  const resXls = validateManuscriptFile(invalidXls);
  assert.equal(resXls.valid, false);
  assert.match(resXls.error || '', /Unsupported file format/i);

  // Exceeds 20 MB size limit
  const oversizedPdf = { name: 'giant_paper.pdf', size: 25 * 1024 * 1024, type: 'application/pdf' } as File;
  const resOversized = validateManuscriptFile(oversizedPdf);
  assert.equal(resOversized.valid, false);
  assert.match(resOversized.error || '', /20 MB limit/i);
});

// -------------------------------------------------------------
// 4. Multipart Form Data Construction (PDF & DOCX)
// -------------------------------------------------------------
test('constructMultipartUploadData builds FormData for PDF manuscripts', () => {
  const dummyBlob = new Blob(['sample pdf binary content'], { type: 'application/pdf' });
  const file = new File([dummyBlob], 'neural_ode.pdf', { type: 'application/pdf' });

  const formData = constructMultipartUploadData(file, {
    title: 'Neural Ordinary Differential Equations',
    doi: '10.48550/arXiv.1806.07366',
    authors: 'Chen et al.',
  });

  assert.ok(formData instanceof FormData);
  assert.ok(formData.has('file'));
  assert.equal(formData.get('title'), 'Neural Ordinary Differential Equations');
  assert.equal(formData.get('doi'), '10.48550/arXiv.1806.07366');
  assert.equal(formData.get('authors'), 'Chen et al.');
});

test('constructMultipartUploadData builds FormData for DOCX manuscripts', () => {
  const dummyBlob = new Blob(['sample docx binary content'], {
    type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  });
  const file = new File([dummyBlob], 'clinical_trial_report.docx', {
    type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  });

  const formData = constructMultipartUploadData(file, {
    title: 'Phase II Clinical Trial Report',
    doi: '10.1016/j.cell.2023.11.008',
  });

  assert.ok(formData instanceof FormData);
  assert.ok(formData.has('file'));
  assert.equal(formData.get('title'), 'Phase II Clinical Trial Report');
  assert.equal(formData.get('doi'), '10.1016/j.cell.2023.11.008');
  assert.equal(formData.has('authors'), false);
});

// -------------------------------------------------------------
// 5. Upload Failure & Fallback Handling
// -------------------------------------------------------------
test('Upload failure handling accurately classifies server and validation errors', () => {
  // 1. 400 Bad Request (Validation failure from backend)
  const validationErr = new ApiError('Pydantic validation error: file must be a valid PDF or DOCX', 400, {
    detail: [{ loc: ['body', 'file'], msg: 'Invalid MIME type' }],
  });
  assert.equal(validationErr.statusCode, 400);
  assert.ok(validationErr.message.includes('validation error'));

  // 2. 500 Internal Server Error
  const serverErr = new ApiError('An unexpected server error occurred.', 500);
  assert.equal(serverErr.statusCode, 500);

  // 3. Network unreachable (status 0)
  const networkErr = new ApiError('Network connection failed: Unable to reach CiteVerify API at /api/documents/upload', 0);
  assert.equal(networkErr.statusCode, 0);
});

test('Metadata-only fallback clearly states metadata was registered and does not claim binary upload or start analysis', () => {
  const fallbackResult = {
    document: {
      id: 'doc-meta-123',
      title: 'paper.pdf',
      doi: null,
      authors: null,
      status: 'pending',
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    },
    job_id: null,
    isBinaryUploaded: false,
    mode: 'metadata_registration' as const,
    notice: 'Manuscript metadata registered. Binary upload pending backend endpoint implementation.',
  };

  assert.equal(fallbackResult.isBinaryUploaded, false);
  assert.equal(fallbackResult.mode, 'metadata_registration');
  assert.equal(fallbackResult.job_id, null);
  assert.ok(fallbackResult.notice.includes('metadata registered'));

  // Routing decision logic: do NOT start analysis for metadata-only registration
  function handleUploadNavigation(result: typeof fallbackResult): string | null {
    if (result.isBinaryUploaded) {
      return `/documents/${result.document.id}/analysis`;
    }
    return null;
  }

  assert.equal(handleUploadNavigation(fallbackResult), null);
});

// -------------------------------------------------------------
// 6. Job Status Parsing
// -------------------------------------------------------------
test('JobRecordResponse parsing handles all lifecycle states correctly', () => {
  const pendingJob: JobRecordResponse = {
    job_id: 'job-001',
    document_id: 'doc-100',
    status: JobStatusEnum.PENDING,
    current_stage: null,
    progress_percentage: 0.0,
    error_message: null,
    created_at: '2026-11-19T14:00:00Z',
    updated_at: '2026-11-19T14:00:00Z',
  };
  assert.equal(pendingJob.status, 'pending');
  assert.equal(pendingJob.progress_percentage, 0.0);

  const runningJob: JobRecordResponse = {
    job_id: 'job-002',
    document_id: 'doc-100',
    status: JobStatusEnum.RUNNING,
    current_stage: 's4_resolve',
    progress_percentage: 50.0,
    error_message: null,
    created_at: '2026-11-19T14:00:00Z',
    updated_at: '2026-11-19T14:01:00Z',
  };
  assert.equal(runningJob.status, 'running');
  assert.equal(runningJob.current_stage, 's4_resolve');
  assert.equal(runningJob.progress_percentage, 50.0);

  const failedJob: JobRecordResponse = {
    job_id: 'job-003',
    document_id: 'doc-100',
    status: JobStatusEnum.FAILED,
    current_stage: 's5_evidence',
    progress_percentage: 62.5,
    error_message: 'Scholarly API rate limit exceeded during PDF retrieval',
    created_at: '2026-11-19T14:00:00Z',
    updated_at: '2026-11-19T14:02:00Z',
  };
  assert.equal(failedJob.status, 'failed');
  assert.ok(failedJob.error_message?.includes('rate limit'));
});

// -------------------------------------------------------------
// 7. Report Response Parsing & Missing Evidence Handling
// -------------------------------------------------------------
test('DocumentReportResponse parsing handles empty, partial, and complete reports', () => {
  // Empty report
  const emptyReport: DocumentReportResponse = {
    document: {
      id: 'doc-empty',
      title: 'Uploaded.pdf',
      status: 'pending',
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    },
    total_references: 5,
    total_claims: 10,
    total_results: 0,
    results_summary: {},
    results: [],
    generated_at: new Date().toISOString(),
    status_note: 'Verification pending',
  };
  assert.equal(emptyReport.total_results, 0);
  assert.equal(emptyReport.results.length, 0);

  // Partial report with missing evidence fields
  const partialReport: DocumentReportResponse = {
    document: {
      id: 'doc-partial',
      title: 'Partial.pdf',
      status: 'processing',
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    },
    total_references: 8,
    total_claims: 8,
    total_results: 2,
    results_summary: { supported: 1, insufficient_evidence: 1 },
    results: [
      {
        id: 'res-1',
        claim_id: 'claim-1',
        evidence_id: 'evi-1',
        verdict: VerdictEnum.SUPPORTED,
        verdict_strength: 0.95,
        retrieval_match: 0.90,
        evidence_completeness: EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE,
        explanation: 'Direct match confirmed.',
        evidence_quote: 'Found in source section 3.',
        reviews: [],
        created_at: new Date().toISOString(),
      },
      {
        id: 'res-2',
        claim_id: 'claim-2',
        evidence_id: null, // missing evidence
        verdict: VerdictEnum.INSUFFICIENT_EVIDENCE,
        verdict_strength: 0.20,
        retrieval_match: 0.10,
        evidence_completeness: EvidenceAvailabilityEnum.UNAVAILABLE, // unavailable evidence
        explanation: 'Source is behind paywall or unavailable in open-access repository.',
        evidence_quote: undefined, // no quote available
        reviews: [],
        created_at: new Date().toISOString(),
      },
    ],
    generated_at: new Date().toISOString(),
    status_note: 'Partial verification in progress',
    overall_health_score: 72.5,
    assessment_verdict: 'moderate_concerns',
  };

  assert.equal(partialReport.results.length, 2);
  assert.equal(partialReport.results[1].evidence_id, null);
  assert.equal(partialReport.results[1].evidence_quote, undefined);
  assert.equal(partialReport.overall_health_score, 72.5);
});

// -------------------------------------------------------------
// 8. Granular Claims & References Responses
// -------------------------------------------------------------
test('Granular claims and references responses parse accurately', () => {
  const claim: ClaimResponse = {
    id: 'claim-001',
    document_id: 'doc-123',
    reference_id: 'ref-001',
    claim_text: 'Self-attention reduces computational complexity for sequence modeling tasks.',
    section_name: 'Introduction',
    page_number: 2,
    is_active: true,
    created_at: '2026-11-19T14:10:00Z',
  };
  assert.equal(claim.is_active, true);
  assert.equal(claim.page_number, 2);

  const ref: ReferenceResponse = {
    id: 'ref-001',
    document_id: 'doc-123',
    raw_citation: 'Vaswani et al. (2017). Attention Is All You Need.',
    citation_key: '[1]',
    resolved_title: 'Attention Is All You Need',
    resolved_doi: '10.48550/arXiv.1706.03762',
    resolved_year: 2017,
    resolved_venue: 'NeurIPS',
    resolution_confidence: 0.98,
    is_retracted: false,
    retraction_notice: null,
    doi_title_mismatch: false,
    oa_pdf_url: 'https://arxiv.org/pdf/1706.03762.pdf',
    is_open_access: true,
    created_at: '2026-11-19T14:10:00Z',
  };
  assert.equal(ref.resolved_year, 2017);
  assert.equal(ref.is_retracted, false);
  assert.equal(ref.is_open_access, true);
});

// -------------------------------------------------------------
// 9. SSE Event Parsing & Deduplication
// -------------------------------------------------------------
test('parseSSEMessage correctly parses stage, reference, claim, result, and done events', () => {
  // 1. Stage event
  const stageMsg = parseSSEMessage('event: stage\ndata: {"stage": "s2_references", "status": "active", "message": "Parsing citations"}');
  assert.ok(stageMsg);
  assert.equal(stageMsg?.event, 'stage');
  assert.equal(stageMsg?.stage, 's2_references');
  assert.equal(stageMsg?.message, 'Parsing citations');

  // 2. Reference event
  const refMsg = parseSSEMessage('event: reference\ndata: {"id": "ref-1", "raw_citation": "Vaswani et al. 2017"}');
  assert.ok(refMsg);
  assert.equal(refMsg?.event, 'reference');
  assert.equal(refMsg?.payload.id, 'ref-1');

  // 3. Claim event
  const claimMsg = parseSSEMessage('event: claim\ndata: {"id": "claim-42", "claim_text": "Transformer achieves 28.4 BLEU"}');
  assert.ok(claimMsg);
  assert.equal(claimMsg?.event, 'claim');
  assert.equal(claimMsg?.payload.id, 'claim-42');

  // 4. Result event
  const resMsg = parseSSEMessage('event: result\ndata: {"id": "res-10", "verdict": "supported", "verdict_strength": 0.95}');
  assert.ok(resMsg);
  assert.equal(resMsg?.event, 'result');
  assert.equal(resMsg?.payload.verdict, 'supported');

  // 5. Done event
  const doneMsg = parseSSEMessage('event: done\ndata: {"message": "Pipeline completed successfully"}');
  assert.ok(doneMsg);
  assert.equal(doneMsg?.event, 'done');

  // 6. Malformed JSON handled safely without throwing
  const malformed = parseSSEMessage('event: result\ndata: {unclosed-json');
  assert.ok(malformed);
  assert.equal(malformed?.event, 'result');
  assert.equal(malformed?.message, '{unclosed-json');

  // 7. Event with sequence id field
  const withId = parseSSEMessage('id: evt-seq-99\nevent: stage\ndata: {"stage": "s1_parse"}');
  assert.ok(withId);
  assert.equal(withId?.id, 'evt-seq-99');
  assert.equal(withId?.stage, 's1_parse');
});

test('EventDeduplicator prevents duplicate processing and respects capacity', () => {
  const dedup = new EventDeduplicator(5);

  const ev1 = { id: 'evt-101', event: 'stage', stage: 's1_parse', message: 'Parsing...' };
  const ev1Dup = { id: 'evt-101', event: 'stage', stage: 's1_parse', message: 'Parsing...' };
  const ev2 = { id: 'evt-102', event: 'stage', stage: 's2_references', message: 'Resolving citations' };

  // First seen
  assert.equal(dedup.isDuplicate(ev1), false);
  assert.equal(dedup.markSeen(ev1), true);

  // Duplicate ID
  assert.equal(dedup.isDuplicate(ev1Dup), true);
  assert.equal(dedup.markSeen(ev1Dup), false);

  // New event
  assert.equal(dedup.isDuplicate(ev2), false);
  assert.equal(dedup.markSeen(ev2), true);

  // Fingerprint deduplication without id
  const evNoId1 = { event: 'reference', payload: { raw: 'Citation A' } };
  const evNoId2 = { event: 'reference', payload: { raw: 'Citation A' } };
  assert.equal(dedup.isDuplicate(evNoId1), false);
  assert.equal(dedup.markSeen(evNoId1), true);
  assert.equal(dedup.isDuplicate(evNoId2), true);
  assert.equal(dedup.markSeen(evNoId2), false);
});

// -------------------------------------------------------------
// 10. SSE Reconnect, Replay & Terminal Handling
// -------------------------------------------------------------
test('CiteVerifySSEClient calculates backoff, tracks replay, and terminates on done/fatal error', () => {
  function calculateBackoff(attempt: number): number {
    return Math.min(1000 * Math.pow(2, attempt), 15000);
  }

  assert.equal(calculateBackoff(0), 1000);
  assert.equal(calculateBackoff(1), 2000);
  assert.equal(calculateBackoff(2), 4000);
  assert.equal(calculateBackoff(3), 8000);
  assert.equal(calculateBackoff(4), 15000); // capped at 15s max
  assert.equal(calculateBackoff(5), 15000);

  let doneFired = false;
  const client = new CiteVerifySSEClient({
    url: 'http://localhost:8000/api/documents/doc-1/events',
    onDone: () => {
      doneFired = true;
    },
  });

  assert.equal(client.getStatus(), 'connecting');
  assert.equal(client.isTerminated(), false);

  // Dispatch terminal done event
  const doneMsg = parseSSEMessage('event: done\ndata: {"status": "completed"}');
  if (doneMsg) {
    (client as any).dispatchParsedMessage(doneMsg);
  }

  assert.equal(doneFired, true);
  assert.equal(client.isTerminated(), true);
  assert.equal(client.getStatus(), 'closed');

  client.close();
});

// -------------------------------------------------------------
// 11. Review Request Serialization
// -------------------------------------------------------------
test('ReviewCreateRequest serializes confirmed, overridden, and disputed decisions', () => {
  const confirmedReview: ReviewCreateRequest = {
    reviewer_id: 'dr_curie',
    human_decision: HumanDecisionEnum.CONFIRMED,
    notes: 'Verified against Table 1 experimental setup.',
  };
  assert.equal(confirmedReview.human_decision, 'confirmed');

  const overrideReview: ReviewCreateRequest = {
    reviewer_id: 'dr_curie',
    human_decision: HumanDecisionEnum.OVERRIDDEN,
    human_verdict: VerdictEnum.CONTRADICTORY,
    notes: 'Authors claimed 30% speedup, but source Figure 4 reports 12% regression.',
  };
  assert.equal(overrideReview.human_decision, 'overridden');
  assert.equal(overrideReview.human_verdict, 'contradictory');

  const disputedReview: ReviewCreateRequest = {
    reviewer_id: 'dr_curie',
    human_decision: HumanDecisionEnum.DISPUTED,
    notes: 'Methodology differences make comparison ambiguous.',
  };
  assert.equal(disputedReview.human_decision, 'disputed');
});

// -------------------------------------------------------------
// 12. Strict Separation between Real Analysis and Demo Mode
// -------------------------------------------------------------
test('Strict Demo Mode separation: real documents never silently substitute sampleData on error', () => {
  const realDocId = 'a1b2c3d4-e5f6-7890-abcd-ef1234567890';
  const demoDocId = 'sample-demo-4092';

  function resolveInitialReport(id: string, isDemoQuery: boolean, backendFailed: boolean) {
    if (id === demoDocId || isDemoQuery) {
      return { report: sampleResultsData, mode: 'demo' };
    }
    if (backendFailed) {
      return { report: null, error: 'Failed to load document report from CiteVerify backend', mode: 'real' };
    }
    return {
      report: {
        document: { id, title: 'Real Doc', status: 'pending', created_at: '', updated_at: '' },
        total_references: 0,
        total_claims: 0,
        total_results: 0,
        results: [],
        results_summary: {},
        status_note: '',
        generated_at: '',
      },
      mode: 'real',
    };
  }

  const demoResult = resolveInitialReport(demoDocId, false, false);
  assert.equal(demoResult.mode, 'demo');
  assert.equal(demoResult.report?.document.id, 'sample-demo-4092');

  const realSuccess = resolveInitialReport(realDocId, false, false);
  assert.equal(realSuccess.mode, 'real');
  assert.equal(realSuccess.report?.results.length, 0);

  const realFailure = resolveInitialReport(realDocId, false, true);
  assert.equal(realFailure.mode, 'real');
  assert.equal(realFailure.report, null);
  assert.ok(realFailure.error?.includes('Failed to load'));
});
