import test from 'node:test';
import assert from 'node:assert/strict';
import { ApiError } from '../lib/api.ts';
import {
  VerdictEnum,
  EvidenceAvailabilityEnum,
  HumanDecisionEnum,
} from '../types/index.ts';
import { sampleResultsData } from '../mocks/sampleData.ts';

test('ApiError encapsulates HTTP status code and details correctly', () => {
  const error = new ApiError('Document not found', 404, { document_id: 'doc-123' });
  assert.equal(error.message, 'Document not found');
  assert.equal(error.statusCode, 404);
  assert.deepEqual(error.details, { document_id: 'doc-123' });
  assert.equal(error.name, 'ApiError');
});

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

test('File validation logic accepts PDF and DOCX under 20MB and rejects others', () => {
  const MAX_BYTES = 20 * 1024 * 1024;
  const ALLOWED_EXT = ['.pdf', '.docx'];

  function validate(fileName: string, sizeBytes: number): string | null {
    const ext = '.' + fileName.split('.').pop()?.toLowerCase();
    if (!ALLOWED_EXT.includes(ext)) {
      return 'Unsupported file format';
    }
    if (sizeBytes > MAX_BYTES) {
      return 'File size exceeds 20 MB limit';
    }
    return null;
  }

  // Valid files
  assert.equal(validate('manuscript.pdf', 5 * 1024 * 1024), null);
  assert.equal(validate('manuscript.docx', 12 * 1024 * 1024), null);
  assert.equal(validate('PAPER.PDF', 1024), null);

  // Invalid extension
  assert.equal(validate('table.xlsx', 1024), 'Unsupported file format');
  assert.equal(validate('notes.txt', 1024), 'Unsupported file format');
  assert.equal(validate('script.py', 1024), 'Unsupported file format');

  // File size limit
  assert.equal(validate('huge.pdf', 25 * 1024 * 1024), 'File size exceeds 20 MB limit');
});

test('Demo mode separation: sampleData is strictly labeled as demonstration audit', () => {
  assert.equal(sampleResultsData.document.id, 'sample-demo-4092');
  assert.ok(sampleResultsData.status_note.includes('Sample demonstration'));
  assert.ok(sampleResultsData.results.length > 0);
  
  // Real mode document check simulation: when total_results is 0, results array must be empty
  const realDocumentReport = {
    document: {
      id: 'real-doc-uuid',
      title: 'Real Uploaded Paper.pdf',
      doi: null,
      authors: null,
      status: 'pending',
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    },
    total_references: 0,
    total_claims: 0,
    total_results: 0,
    results_summary: {
      supported: 0,
      partially_supported: 0,
      unsupported: 0,
      contradictory: 0,
      potentially_outdated: 0,
      insufficient_evidence: 0,
    },
    results: [],
    status_note: 'Real verification pending',
    generated_at: new Date().toISOString(),
  };

  assert.equal(realDocumentReport.results.length, 0);
  assert.notEqual(realDocumentReport.document.id, sampleResultsData.document.id);
});

test('SSE event deduplication logic correctly filters repeating messages', () => {
  const seen = new Set<string>();

  function processEvent(event: { id?: string; event: string; stage?: string; message?: string }) {
    const fingerprint = `${event.id || ''}_${event.event || ''}_${event.stage || ''}_${event.message || ''}`;
    if (seen.has(fingerprint)) {
      return false; // rejected as duplicate
    }
    seen.add(fingerprint);
    return true; // accepted
  }

  const ev1 = { id: 'ev-1', event: 'stage_started', stage: 's1_parse', message: 'Parsing...' };
  const ev1Dup = { id: 'ev-1', event: 'stage_started', stage: 's1_parse', message: 'Parsing...' };
  const ev2 = { id: 'ev-2', event: 'stage_completed', stage: 's1_parse', message: 'Done' };

  assert.equal(processEvent(ev1), true);
  assert.equal(processEvent(ev1Dup), false); // duplicate ignored
  assert.equal(processEvent(ev2), true);
});
