export enum VerdictEnum {
  SUPPORTED = "supported",
  PARTIALLY_SUPPORTED = "partially_supported",
  UNSUPPORTED = "unsupported",
  CONTRADICTORY = "contradictory",
  POTENTIALLY_OUTDATED = "potentially_outdated",
  INSUFFICIENT_EVIDENCE = "insufficient_evidence",
}

export enum EvidenceAvailabilityEnum {
  FULL_TEXT_AVAILABLE = "full_text_available",
  ABSTRACT_ONLY = "abstract_only",
  UNAVAILABLE = "unavailable",
}

export enum HumanDecisionEnum {
  CONFIRMED = "confirmed",
  OVERRIDDEN = "overridden",
  DISPUTED = "disputed",
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

export interface SSEPipelineEvent {
  event: string;
  document_id?: string;
  stage?: string;
  message?: string;
  payload?: any;
}

