/**
 * Canonical Types & Contracts for CiteVerify Frontend & S8 API Integration
 */

// -----------------------------------------------------------------------------
// Enums & String Unions (Strip-types compatible as-const dictionaries)
// -----------------------------------------------------------------------------

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

export const JobStatusEnum = {
  PENDING: "pending",
  RUNNING: "running",
  COMPLETED: "completed",
  FAILED: "failed",
  CANCELLED: "cancelled",
} as const;
export type JobStatusEnum = (typeof JobStatusEnum)[keyof typeof JobStatusEnum];

export const PipelineStageEnum = {
  S1_PARSE: "s1_parse",
  S2_REFERENCES: "s2_references",
  S3_CLAIMS: "s3_claims",
  S4_RESOLVE: "s4_resolve",
  S5_EVIDENCE: "s5_evidence",
  S6_VERIFY: "s6_verify",
  S7_ASSESSMENT: "s7_assessment",
  S8_PERSIST: "s8_persist",
} as const;
export type PipelineStageEnum = (typeof PipelineStageEnum)[keyof typeof PipelineStageEnum];

export const ReviewPriorityEnum = {
  CRITICAL: "critical",
  HIGH: "high",
  MEDIUM: "medium",
  LOW: "low",
} as const;
export type ReviewPriorityEnum = (typeof ReviewPriorityEnum)[keyof typeof ReviewPriorityEnum];

export const AssessmentVerdictEnum = {
  ROBUST_SUPPORT: "robust_support",
  MODERATE_CONCERNS: "moderate_concerns",
  HIGH_CONCERNS: "high_concerns",
  CRITICAL_CONCERNS: "critical_concerns",
  INSUFFICIENT_EVIDENCE: "insufficient_evidence",
  UNASSESSED_EMPTY: "unassessed_empty",
} as const;
export type AssessmentVerdictEnum = (typeof AssessmentVerdictEnum)[keyof typeof AssessmentVerdictEnum];

// -----------------------------------------------------------------------------
// Document Schemas
// -----------------------------------------------------------------------------

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
  file_path?: string | null;
  file_hash?: string | null;
  created_at: string;
  updated_at: string;
}

export interface DocumentUploadResponse {
  document_id: string;
  job_id?: string | null;
  title: string;
  status: string;
  file_size?: number | null;
  created_at: string;
}

export interface DemoDocumentRequest {
  sample_key?: string;
}

// -----------------------------------------------------------------------------
// Background Job Schemas
// -----------------------------------------------------------------------------

export interface JobRecordResponse {
  job_id: string;
  document_id: string;
  status: JobStatusEnum | string;
  current_stage?: string | null;
  progress_percentage: number;
  error_message?: string | null;
  created_at: string;
  updated_at: string;
}

// -----------------------------------------------------------------------------
// Reference & Citation Schemas
// -----------------------------------------------------------------------------

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

  // Provisional S4 Reference Resolution fields
  is_retracted?: boolean | null;
  retraction_notice?: string | null;
  doi_title_mismatch?: boolean | null;
  oa_pdf_url?: string | null;
  is_open_access?: boolean | null;
}

// -----------------------------------------------------------------------------
// Claim Schemas
// -----------------------------------------------------------------------------

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

// -----------------------------------------------------------------------------
// Evidence & Result Schemas
// -----------------------------------------------------------------------------

export interface EvidenceResponse {
  id: string;
  reference_id: string;
  evidence_text: string;
  section_title?: string | null;
  page_number?: number | null;
  source_type: EvidenceAvailabilityEnum | string;
  retrieval_score: number;
  created_at: string;
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

  // Provisional S6 verification dimensions
  numerical_consistency?: 'exact_match' | 'mismatch' | 'missing_in_source' | 'not_applicable' | string | null;
  numerical_details?: string | null;
  scope_audit?: 'consistent' | 'overgeneralized' | 'hedged' | 'context_mismatch' | string | null;
  scope_details?: string | null;
  is_retracted_source?: boolean | null;
  retraction_warning?: string | null;
}

// -----------------------------------------------------------------------------
// Assessment & Report Schemas
// -----------------------------------------------------------------------------

export interface DiscrepancyStats {
  numerical_mismatch_count?: number;
  scope_discrepancy_count?: number;
  retracted_source_count?: number;
  outdated_citation_count?: number;
  human_review_required_count?: number;
}

export interface HumanReviewItem {
  claim_id: string;
  reference_id?: string | null;
  all_reference_ids?: string[];
  citation_key?: string | null;
  evidence_id?: string | null;
  verdict: string;
  priority: ReviewPriorityEnum | string;
  flag_reasons: string[];
  claim_text: string;
  explanation?: string | null;
  numerical_details?: string | null;
  scope_details?: string | null;
  retraction_warning?: string | null;
  evidence_completeness: string;
}

export interface AssessmentFactorItem {
  category: string;
  title: string;
  description: string;
  impact_level: string;
  claim_ids?: string[];
  reference_ids?: string[];
  evidence_ids?: string[];
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

  // Provisional S7 Assessment summary fields
  overall_health_score?: number | null;
  assessment_verdict?: AssessmentVerdictEnum | string | null;
  discrepancies?: DiscrepancyStats | null;
  high_priority_reviews?: HumanReviewItem[] | null;
  factors?: AssessmentFactorItem[] | null;
  executive_summary?: string | null;
  methodology_notes?: string | null;
  limitations_disclaimer?: string | null;
}

// -----------------------------------------------------------------------------
// Audit & Export Schemas
// -----------------------------------------------------------------------------

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

// -----------------------------------------------------------------------------
// SSE Stream Pipeline Event Schemas
// -----------------------------------------------------------------------------

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
