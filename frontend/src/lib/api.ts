import type {
  AuditLogResponse,
  ClaimPatchRequest,
  ClaimPatchResponse,
  DocumentCreate,
  DocumentReportResponse,
  DocumentResponse,
  ExportResponse,
  HealthResponse,
  ReviewCreateRequest,
  ReviewResponse,
} from '../types/index.ts';

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

/**
 * Generic fetch wrapper with JSON serialization, custom headers, and structured error handling.
 */
async function request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const url = `${API_BASE}${endpoint}`;
  const headers = new Headers(options.headers || {});

  if (options.body && !(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }

  let response: Response;
  try {
    response = await fetch(url, {
      ...options,
      headers,
    });
  } catch (err: any) {
    throw new ApiError(
      `Network connection failed: Unable to reach CiteVerify API at ${url}. ${err.message || ''}`.trim(),
      0
    );
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

/**
 * System Health Check endpoint
 * GET /health
 */
export async function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>('/health');
}

/**
 * Register a new research document
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

/**
 * Retrieve aggregated verification report for a document
 * GET /api/documents/{id}/report
 */
export async function getDocumentReport(id: string): Promise<DocumentReportResponse> {
  return request<DocumentReportResponse>(`/api/documents/${encodeURIComponent(id)}/report`);
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
