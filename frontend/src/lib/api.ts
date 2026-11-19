import type {
  AuditLogResponse,
  ClaimPatchRequest,
  ClaimPatchResponse,
  ClaimResponse,
  DocumentCreate,
  DocumentReportResponse,
  DocumentResponse,
  DocumentUploadResponse,
  ExportResponse,
  HealthResponse,
  JobRecordResponse,
  ReferenceResponse,
  ReviewCreateRequest,
  ReviewResponse,
} from '../types/index.ts';

export const MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024; // 20 MB
export const ALLOWED_EXTENSIONS = ['.pdf', '.docx'] as const;
export const DEFAULT_REQUEST_TIMEOUT_MS = 30000; // 30 seconds

/**
 * Custom API Error class with HTTP status code and parsed details from the backend.
 */
export class ApiError extends Error {
  statusCode: number;
  details?: any;

  constructor(message: string, statusCode: number, details?: any) {
    super(message);
    this.name = 'ApiError';
    this.statusCode = statusCode;
    this.details = details;
  }
}

const API_BASE = (typeof import.meta !== 'undefined' && (import.meta as any).env?.VITE_API_BASE_URL) || '';
const CONFIGURED_UPLOAD_ENDPOINT =
  (typeof import.meta !== 'undefined' && (import.meta as any).env?.VITE_UPLOAD_ENDPOINT) || '';

/**
 * Validates file extension and size before initiating network transmission.
 */
export function validateManuscriptFile(file: File): { valid: boolean; error?: string } {
  if (!file) {
    return { valid: false, error: 'No file provided.' };
  }
  const extension = '.' + file.name.split('.').pop()?.toLowerCase();
  if (!ALLOWED_EXTENSIONS.includes(extension as any)) {
    return {
      valid: false,
      error: `Unsupported file format (${extension || 'unknown'}). Only PDF and DOCX files are supported.`,
    };
  }
  if (file.size > MAX_FILE_SIZE_BYTES) {
    const sizeMB = (file.size / (1024 * 1024)).toFixed(1);
    return {
      valid: false,
      error: `File size (${sizeMB} MB) exceeds the 20 MB limit. Please select a smaller manuscript.`,
    };
  }
  return { valid: true };
}

/**
 * Constructs a standard FormData object for multipart/form-data upload.
 */
export function constructMultipartUploadData(
  file: File,
  options?: { title?: string; doi?: string; authors?: string }
): FormData {
  const formData = new FormData();
  formData.append('file', file, file.name);
  if (options?.title) {
    formData.append('title', options.title);
  }
  if (options?.doi) {
    formData.append('doi', options.doi);
  }
  if (options?.authors) {
    formData.append('authors', options.authors);
  }
  return formData;
}

/**
 * Generic fetch wrapper with JSON serialization, custom headers, timeout, and structured error handling.
 */
async function request<T>(
  endpoint: string,
  options: RequestInit = {},
  timeoutMs: number = DEFAULT_REQUEST_TIMEOUT_MS
): Promise<T> {
  const url = `${API_BASE}${endpoint}`;
  const headers = new Headers(options.headers || {});

  if (options.body && !(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }

  // Timeout controller setup
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  // If caller provided a signal, chain it
  if (options.signal) {
    options.signal.addEventListener('abort', () => controller.abort());
  }

  let response: Response;
  try {
    response = await fetch(url, {
      ...options,
      headers,
      signal: controller.signal,
    });
  } catch (err: any) {
    clearTimeout(timeoutId);
    if (err.name === 'AbortError') {
      throw new ApiError(`Request timeout: CiteVerify API at ${url} did not respond within ${timeoutMs / 1000}s.`, 408);
    }
    throw new ApiError(
      `Network connection failed: Unable to reach CiteVerify API at ${url}. ${err.message || ''}`.trim(),
      0
    );
  } finally {
    clearTimeout(timeoutId);
  }

  let data: any = null;
  const contentType = response.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    try {
      data = await response.json();
    } catch {
      data = null;
    }
  } else {
    data = await response.text();
  }

  if (!response.ok) {
    let message = `Request failed with status ${response.status}`;
    let details: any = undefined;

    if (data && typeof data === 'object') {
      if (data.message) {
        message = data.message;
      } else if (data.detail) {
        if (typeof data.detail === 'string') {
          message = data.detail;
        } else if (Array.isArray(data.detail)) {
          // FastAPI / Pydantic validation error format
          message = data.detail.map((d: any) => `${d.loc?.join('.') || 'field'}: ${d.msg}`).join(', ');
        }
      }
      details = data.details || data;
    } else if (typeof data === 'string' && data.length > 0) {
      message = data;
    }

    throw new ApiError(message, response.status, details);
  }

  return data as T;
}

// -----------------------------------------------------------------------------
// System Health
// -----------------------------------------------------------------------------

/**
 * System Health Check endpoint
 * GET /health
 */
export async function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>('/health');
}

// -----------------------------------------------------------------------------
// Document Upload & Ingestion
// -----------------------------------------------------------------------------

export interface UploadFileOptions {
  uploadEndpoint?: string;
  doi?: string;
  authors?: string;
  title?: string;
  forceMetadataOnly?: boolean;
}

export interface UploadResult {
  document: DocumentResponse;
  job_id?: string | null;
  isBinaryUploaded: boolean;
  mode: 'multipart_binary' | 'metadata_registration';
  notice?: string;
}

/**
 * Upload manuscript file with pre-validation and graceful adaptation.
 * If a multipart upload endpoint is available/configured, transmits binary stream via FormData.
 * If the backend does not yet support multipart upload, registers document metadata and notes status.
 */
export async function uploadDocumentFile(
  file: File,
  options?: UploadFileOptions
): Promise<UploadResult> {
  const validation = validateManuscriptFile(file);
  if (!validation.valid) {
    throw new ApiError(validation.error || 'Invalid manuscript file.', 400);
  }

  const endpoint = options?.uploadEndpoint || CONFIGURED_UPLOAD_ENDPOINT || '/api/documents/upload';

  // 1. If explicit multipart endpoint is configured, try multipart upload
  if (endpoint && !options?.forceMetadataOnly) {
    const formData = constructMultipartUploadData(file, options);
    try {
      const resp = await request<DocumentUploadResponse | DocumentResponse>(endpoint, {
        method: 'POST',
        body: formData,
      });

      const doc: DocumentResponse = 'document_id' in resp
        ? {
            id: resp.document_id,
            title: resp.title || file.name,
            status: resp.status || 'processing',
            created_at: resp.created_at || new Date().toISOString(),
            updated_at: new Date().toISOString(),
          }
        : (resp as DocumentResponse);

      const jobId = 'job_id' in resp ? resp.job_id : null;

      return {
        document: doc,
        job_id: jobId,
        isBinaryUploaded: true,
        mode: 'multipart_binary',
      };
    } catch (err: any) {
      // If endpoint is 404/405/501 (not implemented on backend), fall back to metadata registration
      if (err instanceof ApiError && (err.statusCode === 404 || err.statusCode === 405 || err.statusCode === 501)) {
        console.warn(`Multipart endpoint ${endpoint} returned ${err.statusCode}. Falling back to document registration.`);
      } else {
        throw err;
      }
    }
  }

  // 2. Register metadata via confirmed POST /api/documents
  const doc = await createDocument({
    title: options?.title || file.name,
    doi: options?.doi,
    authors: options?.authors,
  });

  return {
    document: doc,
    job_id: null,
    isBinaryUploaded: false,
    mode: 'metadata_registration',
    notice: 'Manuscript metadata registered. Binary upload pending backend endpoint implementation.',
  };
}

/**
 * Standard typed S8 multipart upload method: POST /api/documents/upload
 */
export async function uploadDocument(
  file: File,
  options?: UploadFileOptions
): Promise<UploadResult> {
  const targetEndpoint = options?.uploadEndpoint || CONFIGURED_UPLOAD_ENDPOINT || '/api/documents/upload';
  return uploadDocumentFile(file, {
    ...options,
    uploadEndpoint: targetEndpoint,
  });
}

/**
 * Register a new research document metadata record
 * POST /api/documents
 */
export async function createDocument(data: DocumentCreate): Promise<DocumentResponse> {
  return request<DocumentResponse>('/api/documents', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

/**
 * Seed a demonstration document with pre-populated references and claims
 * POST /api/documents/demo
 */
export async function seedDemoDocument(sampleKey = 'attention_is_all_you_need'): Promise<DocumentResponse> {
  return request<DocumentResponse>('/api/documents/demo', {
    method: 'POST',
    body: JSON.stringify({ sample_key: sampleKey }),
  });
}

/**
 * Retrieve document metadata by document ID
 * GET /api/documents/{id}
 */
export async function getDocument(id: string): Promise<DocumentResponse> {
  return request<DocumentResponse>(`/api/documents/${encodeURIComponent(id)}`);
}

// -----------------------------------------------------------------------------
// Background Jobs & Orchestration
// -----------------------------------------------------------------------------

/**
 * Query background verification job status
 * GET /api/jobs/{id}
 * Note: Provisional endpoint for S8 background orchestration tracking.
 */
export async function getJob(id: string): Promise<JobRecordResponse> {
  return request<JobRecordResponse>(`/api/jobs/${encodeURIComponent(id)}`);
}

// -----------------------------------------------------------------------------
// Verification Reports, Claims & References
// -----------------------------------------------------------------------------

/**
 * Retrieve aggregated verification report for a document
 * GET /api/documents/{id}/report
 */
export async function getDocumentReport(id: string): Promise<DocumentReportResponse> {
  return request<DocumentReportResponse>(`/api/documents/${encodeURIComponent(id)}/report`);
}

/**
 * Retrieve granular claims for a document
 * GET /api/documents/{id}/claims
 * Note: Provisional endpoint for granular claims inspection.
 */
export async function getDocumentClaims(
  id: string,
  options?: { active_only?: boolean; section?: string }
): Promise<ClaimResponse[]> {
  const params = new URLSearchParams();
  if (options?.active_only !== undefined) {
    params.set('active_only', String(options.active_only));
  }
  if (options?.section) {
    params.set('section', options.section);
  }
  const queryString = params.toString() ? `?${params.toString()}` : '';
  return request<ClaimResponse[]>(`/api/documents/${encodeURIComponent(id)}/claims${queryString}`);
}

/**
 * Retrieve resolved bibliography references for a document
 * GET /api/documents/{id}/references
 * Note: Provisional endpoint for bibliography metadata.
 */
export async function getDocumentReferences(id: string): Promise<ReferenceResponse[]> {
  return request<ReferenceResponse[]>(`/api/documents/${encodeURIComponent(id)}/references`);
}

/**
 * Update or toggle active state of an extracted claim in document
 * PATCH /api/documents/{id}/claims
 */
export async function patchDocumentClaim(
  documentId: string,
  data: ClaimPatchRequest
): Promise<ClaimPatchResponse> {
  return request<ClaimPatchResponse>(`/api/documents/${encodeURIComponent(documentId)}/claims`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

// -----------------------------------------------------------------------------
// Human-in-the-Loop Reviews
// -----------------------------------------------------------------------------

/**
 * Submit human-in-the-loop review or override on an automated verification verdict
 * PATCH /api/results/{id}/review
 */
export async function submitReview(
  resultId: string,
  data: ReviewCreateRequest
): Promise<ReviewResponse> {
  return request<ReviewResponse>(`/api/results/${encodeURIComponent(resultId)}/review`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

// -----------------------------------------------------------------------------
// Audit Trail & Export
// -----------------------------------------------------------------------------

/**
 * Retrieve chronological audit trail for a document
 * GET /api/documents/{id}/audit
 */
export async function getDocumentAudit(id: string): Promise<AuditLogResponse[]> {
  return request<AuditLogResponse[]>(`/api/documents/${encodeURIComponent(id)}/audit`);
}

/**
 * Export structured verification data in requested format (json, csv, bibtex, markdown)
 * GET /api/documents/{id}/export?format={format}
 */
export async function exportDocument(
  id: string,
  format = 'json'
): Promise<ExportResponse> {
  return request<ExportResponse>(
    `/api/documents/${encodeURIComponent(id)}/export?format=${encodeURIComponent(format)}`
  );
}

/**
 * Helper to construct the Server-Sent Events (SSE) streaming URL
 */
export function getDocumentEventsUrl(id: string): string {
  return `${API_BASE}/api/documents/${encodeURIComponent(id)}/events`;
}
