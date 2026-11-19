export const VerdictEnum = {
  SUPPORTED: "supported",
  PARTIALLY_SUPPORTED: "partially_supported",
  UNSUPPORTED: "unsupported",
  CONTRADICTORY: "contradictory",
  POTENTIALLY_OUTDATED: "potentially_outdated",
  INSUFFICIENT_EVIDENCE: "insufficient_evidence",
} as const;
export type VerdictEnum = (typeof VerdictEnum)[keyof typeof VerdictEnum];

export const EvidenceAvailabilityEnum = {
  FULL_TEXT_AVAILABLE: "full_text_available",
  ABSTRACT_ONLY: "abstract_only",
  UNAVAILABLE: "unavailable",
} as const;
export type EvidenceAvailabilityEnum = (typeof EvidenceAvailabilityEnum)[keyof typeof EvidenceAvailabilityEnum];

export const HumanDecisionEnum = {
  CONFIRMED: "confirmed",
  OVERRIDDEN: "overridden",
  DISPUTED: "disputed",
} as const;
export type HumanDecisionEnum = (typeof HumanDecisionEnum)[keyof typeof HumanDecisionEnum];

export interface DocumentCreate {
  title: string;
  doi?: string | null;
  authors?: string | null;
}

export interface DocumentResponse {
  id: string;
  title: string;
  doi?: string | null;
  authors?: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface DemoDocumentRequest {
  sample_key?: string;
}

export interface ReferenceResponse {
  id: string;
  document_id: string;
  raw_citation: string;
  citation_key?: string | null;
  resolved_title?: string | null;
  resolved_doi?: string | null;
  resolved_year?: number | null;
  resolved_venue?: string | null;
  resolution_confidence: number;
  created_at: string;
}

export interface ClaimResponse {
  id: string;
  document_id: string;
  reference_id?: string | null;
  claim_text: string;
  context_sentence?: string | null;
  section_name?: string | null;
  page_number?: number | null;
  is_active: boolean;
  created_at: string;
}

export interface ClaimPatchRequest {
  claim_id: string;
  is_active?: boolean;
  claim_text?: string;
}

export interface ClaimPatchResponse {
  success: boolean;
  message: string;
  updated_claim?: ClaimResponse | null;
}

export interface ReviewCreateRequest {
  reviewer_id?: string;
  human_decision: HumanDecisionEnum;
  human_verdict?: VerdictEnum | null;
  notes?: string | null;
}

export interface ReviewResponse {
  id: string;
  result_id: string;
  reviewer_id: string;
  human_decision: HumanDecisionEnum;
  human_verdict?: VerdictEnum | null;
  notes?: string | null;
  created_at: string;
}

export interface ResultResponse {
  id: string;
  claim_id: string;
  evidence_id?: string | null;
  verdict: VerdictEnum;
  verdict_strength: number;
  retrieval_match: number;
  evidence_completeness: EvidenceAvailabilityEnum;
  explanation?: string | null;
  model_name?: string | null;
  created_at: string;
  reviews: ReviewResponse[];
  
  // Enriched UI properties
  claim?: ClaimResponse;
  reference?: ReferenceResponse;
  evidence_quote?: string;
}

export interface DocumentReportResponse {
  document: DocumentResponse;
  total_references: number;
  total_claims: number;
  total_results: number;
  results_summary: Record<string, number>;
  results: ResultResponse[];
  generated_at: string;
  status_note: string;
}

export interface AuditLogResponse {
  id: string;
  document_id?: string | null;
  action: string;
  actor: string;
  details?: string | null;
  created_at: string;
}

export interface ExportResponse {
  document_id: string;
  export_format: string;
  data: Record<string, any>;
}

export interface HealthResponse {
  status: string;
  version: string;
  service: string;
  database_connected: boolean;
  llm_service_ready: boolean;
}

export interface SSEPipelineEvent {
  event: string;
  id?: string;
  job_id?: string;
  document_id?: string;
  stage?: string;
  event_type?: string;
  message?: string;
  payload?: any;
  created_at?: string;
}
