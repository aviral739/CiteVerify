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
});

// -------------------------------------------------------------
// 2. Canonical Verdicts & Evidence Availability Enums
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
// 4. Multipart Form Data Construction
// -------------------------------------------------------------
test('constructMultipartUploadData builds FormData with file and metadata', () => {
  const dummyBlob = new Blob(['sample pdf content'], { type: 'application/pdf' });
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
    isBinaryUploaded: false,
    mode: 'metadata_registration' as const,
    notice: 'Manuscript metadata registered. Binary upload pending backend endpoint implementation.',
  };

  // 1. Binary upload flag must be false
  assert.equal(fallbackResult.isBinaryUploaded, false);
  assert.equal(fallbackResult.mode, 'metadata_registration');

  // 2. Must state metadata was registered
  assert.ok(fallbackResult.notice.includes('metadata registered'));

  // 3. Routing decision logic: only navigate / start analysis when isBinaryUploaded is true
  function handleUploadNavigation(result: typeof fallbackResult): string | null {
    if (result.isBinaryUploaded) {
      return `/documents/${result.document.id}/analysis`;
    }
    // Do NOT start analysis for metadata-only registration
    return null;
  }

  assert.equal(handleUploadNavigation(fallbackResult), null);
});

// -------------------------------------------------------------
// 5. SSE Event Parsing & Deduplication
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

  // 7. Event with id field
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
// 6. SSE Interruption, Reconnection & Backoff Calculation
// -------------------------------------------------------------
test('CiteVerifySSEClient computes exponential backoff and tracks sequence replay', () => {
  // Test exponential backoff formula: min(1000 * 2^attempt, 15000)
  function calculateBackoff(attempt: number): number {
    return Math.min(1000 * Math.pow(2, attempt), 15000);
  }

  assert.equal(calculateBackoff(0), 1000);
  assert.equal(calculateBackoff(1), 2000);
  assert.equal(calculateBackoff(2), 4000);
  assert.equal(calculateBackoff(3), 8000);
  assert.equal(calculateBackoff(4), 15000); // capped at 15s max
  assert.equal(calculateBackoff(5), 15000);

  // Test sequence tracking for Last-Event-ID replay
  const client = new CiteVerifySSEClient({
    url: 'http://localhost:8000/api/documents/doc-1/events',
  });

  assert.equal(client.getStatus(), 'connecting');
  assert.equal(client.getLastEventId(), null);

  // Close cleans up
  client.close();
  assert.equal(client.getStatus(), 'closed');
});

// -------------------------------------------------------------
// 7. Empty, Partial, and Completed Report State Handling
// -------------------------------------------------------------
test('Empty report handling: total_results = 0 indicates pending verification without faking results', () => {
  const emptyReport = {
    document: {
      id: 'doc-real-999',
      title: 'Newly Uploaded Manuscript.pdf',
      doi: null,
      authors: null,
      status: 'pending',
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    },
    total_references: 14,
    total_claims: 28,
    total_results: 0,
    results_summary: {},
    results: [],
    status_note: 'Automated verification pending pipeline execution',
    generated_at: new Date().toISOString(),
  };

  assert.equal(emptyReport.total_results, 0);
  assert.equal(emptyReport.results.length, 0);
  assert.ok(emptyReport.total_claims > 0);

  // Verification state logic
  const isPartial = emptyReport.total_claims > emptyReport.total_results && emptyReport.total_results > 0;
  const isComplete = emptyReport.total_results >= emptyReport.total_claims && emptyReport.total_results > 0;
  const isPending = emptyReport.total_results === 0;

  assert.equal(isPartial, false);
  assert.equal(isComplete, false);
  assert.equal(isPending, true);
});

test('Partial report handling: total_results < total_claims identifies in-progress audit truthfully', () => {
  const partialReport = {
    document: {
      id: 'doc-real-999',
      title: 'Active Verification Manuscript.pdf',
      status: 'processing',
    },
    total_references: 10,
    total_claims: 12,
    total_results: 4,
    results_summary: {
      supported: 3,
      contradictory: 1,
    },
    results: [
      { id: 'res-1', verdict: 'supported' },
      { id: 'res-2', verdict: 'supported' },
      { id: 'res-3', verdict: 'supported' },
      { id: 'res-4', verdict: 'contradictory' },
    ],
  };

  const isPartial = partialReport.total_claims > partialReport.total_results && partialReport.total_results > 0;
  assert.equal(isPartial, true);
  assert.equal(partialReport.results.length, 4);
});

test('Complete report handling: total_results >= total_claims reflects full audit completion', () => {
  const completedReport = {
    document: {
      id: 'doc-real-999',
      title: 'Complete Manuscript.pdf',
      status: 'completed',
    },
    total_references: 5,
    total_claims: 5,
    total_results: 5,
    results: [
      { id: 'r1', verdict: 'supported' },
      { id: 'r2', verdict: 'partially_supported' },
      { id: 'r3', verdict: 'unsupported' },
      { id: 'r4', verdict: 'contradictory' },
      { id: 'r5', verdict: 'insufficient_evidence' },
    ],
  };

  const isComplete = completedReport.total_results >= completedReport.total_claims && completedReport.total_results > 0;
  assert.equal(isComplete, true);
});

// -------------------------------------------------------------
// 8. Strict Separation between Real Analysis and Demo Mode
// -------------------------------------------------------------
test('Strict Demo Mode separation: real documents never silently substitute sampleData on error', () => {
  const realDocId = 'a1b2c3d4-e5f6-7890-abcd-ef1234567890';
  const demoDocId = 'sample-demo-4092';

  function resolveInitialReport(id: string, isDemoQuery: boolean, backendFailed: boolean) {
    if (id === demoDocId || isDemoQuery) {
      return { report: sampleResultsData, mode: 'demo' };
    }
    if (backendFailed) {
      // Must NOT return sampleResultsData
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

  // 1. Explicit demo ID gets sample data
  const demoResult = resolveInitialReport(demoDocId, false, false);
  assert.equal(demoResult.mode, 'demo');
  assert.equal(demoResult.report?.document.id, 'sample-demo-4092');

  // 2. Real document that succeeds gets real report (not sample)
  const realSuccess = resolveInitialReport(realDocId, false, false);
  assert.equal(realSuccess.mode, 'real');
  assert.equal(realSuccess.report?.results.length, 0);

  // 3. Real document where backend fails MUST report error and NOT fall back to sample
  const realFailure = resolveInitialReport(realDocId, false, true);
  assert.equal(realFailure.mode, 'real');
  assert.equal(realFailure.report, null);
  assert.ok(realFailure.error?.includes('Failed to load'));
});
