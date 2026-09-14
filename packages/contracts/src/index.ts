export type UUID = string;

export interface Person {
  id: UUID;
  tenant_id: UUID;
  display_name: string;
  preferred_name: string | null;
  birth_year: number | null;
  birthplace: string | null;
  relation_to_owner: string | null;
  is_subject: boolean;
  biography_note: string | null;
  is_minor: boolean;
  guardian_name: string | null;
  created_at: string;
  updated_at: string;
}

export interface PersonCreate {
  display_name: string;
  preferred_name?: string | null;
  birth_year?: number | null;
  birthplace?: string | null;
  relation_to_owner?: string | null;
  is_subject?: boolean;
  biography_note?: string | null;
  is_minor?: boolean;
  guardian_name?: string | null;
}

export type PersonUpdate = Partial<PersonCreate>;

export interface Chapter {
  id: UUID;
  order_index: number;
  title: string;
  description: string | null;
  opening_questions: string[];
  is_system: boolean;
}

export interface InterviewRound {
  id: UUID;
  round_index: number;
  question_text: string;
  question_intent: string | null;
  question_source: string | null;
  answer_text: string | null;
  source_asset_id: UUID | null;
  transcript_status: string;
  created_at: string;
  answered_at: string | null;
}

export interface SourceAsset {
  id: UUID;
  subject_id: UUID;
  interview_session_id: UUID | null;
  kind: "audio" | "photo" | "video" | "document" | string;
  original_filename: string;
  mime_type: string;
  byte_size: number;
  sha256: string;
  status: string;
  consent_scope: string;
  captured_at: string;
  created_at: string;
}

export interface TranscriptVersion {
  id: UUID;
  version_number: number;
  text: string;
  source: string;
  edit_reason: string | null;
  created_at: string;
}

export interface TranscriptSegment {
  id: UUID;
  order_index: number;
  start_ms: number | null;
  end_ms: number | null;
  speaker_label: string | null;
  text: string;
}

export interface Transcript {
  id: UUID;
  source_asset_id: UUID;
  language: string;
  status: string;
  current_version: number;
  versions: TranscriptVersion[];
}

export interface EvidenceObservation {
  id: UUID;
  subject_id: UUID;
  source_asset_id: UUID;
  source_transcript_version_id: UUID | null;
  version_number: number;
  analysis_kind: string;
  text: string;
  locator: Record<string, unknown>;
  confidence: number;
  review_status: string;
  provider: string;
  model_name: string | null;
  created_at: string;
}

export interface Job {
  id: UUID;
  kind: string;
  status: string;
  idempotency_key: string | null;
  payload: Record<string, unknown>;
  result: Record<string, unknown> | null;
  error_code: string | null;
  error_message: string | null;
  attempt_count: number;
  created_at: string;
  updated_at: string;
}

export interface InterviewSession {
  id: UUID;
  subject_id: UUID;
  chapter_id: UUID | null;
  topic_hint: string | null;
  status: "active" | "paused" | "completed" | string;
  round_count: number;
  started_at: string;
  updated_at: string;
  completed_at: string | null;
  rounds: InterviewRound[];
}

export interface NextQuestion {
  question_text: string;
  question_intent: string;
  question_source: string;
}

export interface InterviewTurnWorkflow {
  id: UUID;
  session_id: UUID;
  round_id: UUID;
  chapter_id: UUID | null;
  job_id: UUID | null;
  idempotency_key: string;
  status: "queued" | "running" | "completed" | "failed" | string;
  asset_ids: UUID[];
  source_claim_ids: UUID[];
  script_scene_ids: UUID[];
  script_project_id: UUID | null;
  next_question: string | null;
  next_question_intent: string | null;
  missing_topics: string[];
  script_brief: Record<string, unknown>;
  error_code: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface InterviewWorkspace {
  session: InterviewSession;
  assets: SourceAsset[];
  script: ScriptProject | null;
  latest_workflow: InterviewTurnWorkflow | null;
}

export interface MemoryClaim {
  id: UUID;
  subject_id: UUID;
  interview_session_id: UUID | null;
  source_round_id: UUID | null;
  source_observation_id: UUID | null;
  chapter_id: UUID | null;
  claim_text: string;
  source_quote: string;
  claim_type: string;
  confidence: number;
  review_status: string;
  extraction_provider: string;
  extraction_model: string | null;
  created_at: string;
  updated_at: string;
}

export interface MemoryCompileResult {
  created_count: number;
  existing_count: number;
  claims: MemoryClaim[];
}

export interface MemoryOverview {
  claim_count: number;
  reviewed_count: number;
  entity_count: number;
  timeline_count: number;
  open_conflict_count: number;
  covered_chapter_ids: UUID[];
  coverage_ratio: number;
}

export interface MemoryEntity {
  id: UUID;
  subject_id: UUID;
  entity_type: string;
  name: string;
  relationship: string;
  source_claim_ids: UUID[];
}

export interface TimelineAnchor {
  id: UUID;
  subject_id: UUID;
  claim_id: UUID;
  year: number | null;
  time_text: string;
  event_text: string;
  precision: string;
}

export interface MemoryConflict {
  id: UUID;
  subject_id: UUID;
  claim_ids: UUID[];
  conflict_key: string;
  description: string;
  status: string;
}

export interface MemoryGraphNode {
  id: string;
  kind: "subject" | "person" | "place" | "organization" | "event" | string;
  label: string;
  description: string | null;
  time_text: string | null;
  source_claim_ids: UUID[];
}

export interface MemoryGraphEdge {
  id: string;
  source_id: string;
  target_id: string;
  relationship: string;
  source_claim_ids: UUID[];
}

export interface MemoryGraph {
  subject_id: UUID;
  nodes: MemoryGraphNode[];
  edges: MemoryGraphEdge[];
}

export interface ScriptScene {
  id: UUID;
  chapter_id: UUID | null;
  order_index: number;
  heading: string;
  narration: string;
  visual_prompt: string;
  duration_seconds: number;
  source_claim_ids: UUID[];
}

export interface ScriptShot {
  id: UUID;
  scene_id: UUID;
  order_index: number;
  shot_type: string;
  visual_prompt: string;
  duration_seconds: number;
  source_claim_ids: UUID[];
}

export interface ScriptProject {
  id: UUID;
  subject_id: UUID;
  title: string;
  mode: "single_chapter" | "multi_chapter" | string;
  status: string;
  audience: string;
  source_claim_ids: UUID[];
  version_number: number;
  generation_provider: string;
  generation_model: string | null;
  created_at: string;
  updated_at: string;
  scenes: ScriptScene[];
  shots: ScriptShot[];
}

export interface ConsentGrant {
  id: UUID;
  subject_id: UUID;
  consent_type: "interview" | "portrait" | "voice" | "production" | "publication" | string;
  scope: string;
  status: string;
  granted_by: string;
  evidence_note: string | null;
  expires_at: string | null;
  created_at: string;
}

export interface GeneratedAsset {
  id: UUID;
  scene_id: UUID | null;
  kind: string;
  provider: string;
  mime_type: string;
  sha256: string;
  generation_parameters: Record<string, unknown>;
}

export interface ProductionRun {
  id: UUID;
  project_id: UUID;
  job_id?: UUID | null;
  status: string;
  provider: string;
  audience: string;
  estimated_cost: number;
  actual_cost: number;
  output_manifest: (Record<string, unknown> & {
    scene_id?: UUID | null;
    script_version?: number;
    script_snapshot?: ScriptScene[];
    stage?: "planning" | "generating" | "assembling" | "completed";
    completed_segments?: number;
    segments?: Array<{ status: string; duration_seconds: number; narration: string }>;
    target_duration_seconds?: number;
    billing_quote?: { amount_cents: number; target_seconds: number; version: string; title: string };
    billing?: { status: "pending" | "settled"; reserved_cents: number; charged_cents?: number };
  }) | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  assets: GeneratedAsset[];
  recovery?: { code: string; segment_index: number; rejected_asset_ids: UUID[] } | null;
}

export interface ProductionSettings {
  mode?: "segmented" | "single_clip";
  max_segment_seconds?: number;
  provider: string;
  model: string | null;
  resolution: string | null;
  ratio: string | null;
  duration_seconds: number | null;
  generate_audio: boolean | null;
}

export interface Publication {
  id: UUID;
  production_run_id: UUID;
  subject_id: UUID;
  audience: string;
  status: string;
  access_token: string;
  published_at: string;
  withdrawn_at: string | null;
  created_at: string;
}
export interface WalletSummary {
  recharge?: { mode: "disabled" | "manual_wechat"; min_cents: number; max_cents: number };
  paid_cents: number;
  bonus_cents: number;
  frozen_cents: number;
  available_cents: number;
  debt_cents?: number;
  token_remainder_nano?: number;
  prices: { version: string; video_cents_per_second: number; script_chapter_cents: number;
    video_billing_mode?: "tokens" | "per_second"; video_reserve_cents?: number;
    video_cny_per_million?: string; video_markup?: string;
    welcome_bonus_cents: number; payment_enabled: boolean; script_billing_mode: string };
}
export interface WalletEntry {
  id: string; charge_id: string | null; event: "bonus" | "reserve" | "consume" | "release" | "recharge";
  title: string; amount_cents: number; available_after_cents: number;
  paid_delta: number; bonus_delta: number; frozen_delta: number; created_at: string;
}
export interface ProviderUsage {
  id: string; model: string; operation: string; status: string; created_at: string;
  usage: Record<string, unknown>; duration_ms: number; provider_request_id: string | null;
  metering?: Record<string, unknown>;
}
export interface WalletPage<T> { total: number; page: number; page_size: number; items: T[] }
export interface RechargeOrder {
  id: string;
  amount_cents: number;
  status: "pending" | "submitted" | "credited" | "rejected" | "cancelled";
  payer_reference: string | null;
  review_note: string | null;
  created_at: string;
  reviewed_at: string | null;
}
