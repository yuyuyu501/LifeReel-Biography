import type {
  RechargeOrder,
  WalletSummary, WalletEntry, WalletPage, ProviderUsage,
  Chapter,
  InterviewSession,
  InterviewTurnWorkflow,
  InterviewWorkspace,
  Job,
  MemoryClaim,
  MemoryCompileResult,
  MemoryConflict,
  MemoryEntity,
  MemoryGraph,
  MemoryOverview,
  NextQuestion,
  Person,
  PersonCreate,
  PersonUpdate,
  ProductionRun,
  ProductionSettings,
  Publication,
  ConsentGrant,
  EvidenceObservation,
  ScriptProject,
  SourceAsset,
  Transcript,
  TimelineAnchor,
} from "@lifereel/contracts";
import { ApiError, apiErrorFromResponse } from "./errors";

export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const isFormData = init?.body instanceof FormData;
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      credentials: "include",
      headers: {
        ...(isFormData ? {} : { "Content-Type": "application/json" }),
        ...init?.headers,
      },
    });
  } catch {
    throw new ApiError("NETWORK_ERROR", 0);
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw apiErrorFromResponse(response.status, payload);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const api = {
  rechargeOrders: (page = 1) => request<WalletPage<RechargeOrder>>(`/v1/wallet/recharge/orders?page=${page}`),
  rechargeOrder: (id: string) => request<RechargeOrder>(`/v1/wallet/recharge/${id}`),
  createRecharge: (payload: { request_id: string; amount_cents: number }) => request<RechargeOrder>("/v1/wallet/recharge", { method: "POST", body: JSON.stringify(payload) }),
  reportRecharge: (id: string, payer_reference: string) => request<RechargeOrder>(`/v1/wallet/recharge/${id}/report`, { method: "POST", body: JSON.stringify({ payer_reference }) }),
  cancelRecharge: (id: string) => request<RechargeOrder>(`/v1/wallet/recharge/${id}/cancel`, { method: "POST" }),
  wallet: () => request<WalletSummary>("/v1/wallet"),
  walletLedger: (page = 1, event = "") => request<WalletPage<WalletEntry>>(`/v1/wallet/ledger?page=${page}${event ? `&event=${event}` : ""}`),
  providerUsage: (page = 1) => request<WalletPage<ProviderUsage>>(`/v1/wallet/usage?page=${page}`),
  registration: () => request<{ enabled: boolean }>("/v1/auth/registration"),
  register: (email: string, password: string, display_name: string) => request("/v1/auth/register", {
    method: "POST", body: JSON.stringify({ email, password, display_name }),
  }),
  login: (email: string, password: string) =>
    request<{ expires_in: number; user: { display_name: string; role: string } }>(
      "/v1/auth/login",
      { method: "POST", body: JSON.stringify({ email, password }) },
    ),
  me: () => request<{ display_name: string; role: string }>("/v1/auth/me"),
  logout: () => request<void>("/v1/auth/logout", { method: "POST" }),
  health: () => request<{ status: string }>("/health"),
  listPersons: () => request<Person[]>("/v1/persons"),
  createPerson: (payload: PersonCreate) =>
    request<Person>("/v1/persons", { method: "POST", body: JSON.stringify(payload) }),
  updatePerson: (personId: string, payload: PersonUpdate) =>
    request<Person>(`/v1/persons/${personId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  listChapters: () => request<Chapter[]>("/v1/chapters"),
  listInterviews: () => request<InterviewSession[]>("/v1/interviews"),
  startInterview: (payload: { subject_id: string; chapter_id?: string; topic_hint?: string }) =>
    request<InterviewSession>("/v1/interviews", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  getInterview: (id: string) => request<InterviewSession>(`/v1/interviews/${id}`),
  getInterviewWorkspace: (id: string) =>
    request<InterviewWorkspace>(`/v1/interviews/${id}/workspace`),
  createInterviewTurn: (
    sessionId: string,
    payload: {
      round_id: string;
      answer_text?: string;
      asset_ids: string[];
      idempotency_key: string;
    },
  ) => request<InterviewTurnWorkflow>(`/v1/interviews/${sessionId}/turns`, {
    method: "POST",
    body: JSON.stringify(payload),
  }),
  answerRound: (
    sessionId: string,
    roundId: string,
    answer_text: string,
    source_asset_id?: string,
  ) =>
    request(`/v1/interviews/${sessionId}/rounds/${roundId}/answer`, {
      method: "POST",
      body: JSON.stringify({ answer_text, source_asset_id }),
    }),
  nextQuestion: (sessionId: string) =>
    request<NextQuestion>(`/v1/interviews/${sessionId}/next-question`),
  createRound: (sessionId: string, payload: NextQuestion) =>
    request(`/v1/interviews/${sessionId}/rounds`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  completeInterview: (sessionId: string) =>
    request<InterviewSession>(`/v1/interviews/${sessionId}/complete`, { method: "POST" }),
  pauseInterview: (sessionId: string) =>
    request<InterviewSession>(`/v1/interviews/${sessionId}/pause`, { method: "POST" }),
  resumeInterview: (sessionId: string) =>
    request<InterviewSession>(`/v1/interviews/${sessionId}/resume`, { method: "POST" }),
  listMemories: (subjectId?: string) =>
    request<MemoryClaim[]>(`/v1/memories${subjectId ? `?subject_id=${subjectId}` : ""}`),
  compileMemories: (payload: { interview_session_id?: string; subject_id?: string }) =>
    request<MemoryCompileResult>("/v1/memories/compile", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  listScripts: () => request<ScriptProject[]>("/v1/scripts"),
  generateScript: (payload: {
    subject_id: string;
    idempotency_key?: string;
    title?: string;
    mode: "single_chapter" | "multi_chapter";
    audience: "private" | "family" | "friends" | "public";
    chapter_id?: string;
  }) =>
    request<ScriptProject>("/v1/scripts/generate", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  uploadEvidence: (payload: {
    subjectId: string;
    interviewSessionId?: string;
    kind: "audio" | "photo" | "video" | "document";
    consentScope?: "private" | "family" | "friends" | "public";
    file: File;
  }) => {
    const form = new FormData();
    form.set("subject_id", payload.subjectId);
    if (payload.interviewSessionId) form.set("interview_session_id", payload.interviewSessionId);
    form.set("kind", payload.kind);
    form.set("consent_scope", payload.consentScope ?? "private");
    form.set("file", payload.file);
    return request<SourceAsset>("/v1/evidence/assets", { method: "POST", body: form });
  },
  createTranscript: (assetId: string, text: string, source = "manual") =>
    request<Transcript>(`/v1/evidence/assets/${assetId}/transcript`, {
      method: "POST",
      body: JSON.stringify({ text, source, language: "zh-CN" }),
    }),
  listEvidence: (subjectId?: string) =>
    request<SourceAsset[]>(`/v1/evidence/assets${subjectId ? `?subject_id=${subjectId}` : ""}`),
  getTranscript: (transcriptId: string) =>
    request<Transcript>(`/v1/evidence/transcripts/${transcriptId}`),
  getAssetTranscript: (assetId: string) =>
    request<Transcript>(`/v1/evidence/assets/${assetId}/transcript`),
  transcribeEvidence: (assetId: string) =>
    request<Transcript>(`/v1/evidence/assets/${assetId}/transcribe`, { method: "POST" }),
  analyzeEvidence: (assetId: string) =>
    request<EvidenceObservation>(`/v1/evidence/assets/${assetId}/analyze`, { method: "POST" }),
  listEvidenceObservations: (assetId: string) =>
    request<EvidenceObservation[]>(`/v1/evidence/assets/${assetId}/observations`),
  reviseTranscript: (transcriptId: string, text: string, edit_reason: string) =>
    request<Transcript>(`/v1/evidence/transcripts/${transcriptId}/revisions`, {
      method: "POST",
      body: JSON.stringify({ text, edit_reason }),
    }),
  memoryOverview: (subjectId: string) =>
    request<MemoryOverview>(`/v1/memories/subjects/${subjectId}/overview`),
  listMemoryEntities: (subjectId: string) =>
    request<MemoryEntity[]>(`/v1/memories/subjects/${subjectId}/entities`),
  listMemoryTimeline: (subjectId: string) =>
    request<TimelineAnchor[]>(`/v1/memories/subjects/${subjectId}/timeline`),
  listMemoryConflicts: (subjectId: string) =>
    request<MemoryConflict[]>(`/v1/memories/subjects/${subjectId}/conflicts`),
  getMemoryGraph: (subjectId: string) =>
    request<MemoryGraph>(`/v1/memories/subjects/${subjectId}/graph`),
  reviewMemory: (claimId: string, status: "verified" | "disputed" | "private") =>
    request<MemoryClaim>(`/v1/memories/${claimId}/review`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    }),
  listConsents: (subjectId?: string) =>
    request<ConsentGrant[]>(`/v1/consents${subjectId ? `?subject_id=${subjectId}` : ""}`),
  createConsent: (payload: {
    subject_id: string;
    consent_type: "interview" | "portrait" | "voice" | "production" | "publication" | "guardian";
    scope: "private" | "family" | "friends" | "public";
    granted_by: string;
    evidence_note?: string;
  }) =>
    request<ConsentGrant>("/v1/consents", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  revokeConsent: (consentId: string) =>
    request<ConsentGrant>(`/v1/consents/${consentId}/revoke`, { method: "POST" }),
  listProductionRuns: () => request<ProductionRun[]>("/v1/production/runs"),
  productionSettings: () => request<ProductionSettings>("/v1/production/settings"),
  startProduction: (payload: {
    quoted_amount_cents?: number;
    project_id: string;
    scene_id?: string;
    audience: "private" | "family" | "friends" | "public";
    provider?: string;
  }) =>
    request<ProductionRun>("/v1/production/runs", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  listPublications: () => request<Publication[]>("/v1/publications"),
  publicPublication: (token: string) =>
    request<Pick<Publication, "id" | "production_run_id" | "audience" | "status" | "published_at">>(
      `/v1/public/${token}`,
    ),
  publish: (production_run_id: string, audience: "private" | "family" | "friends" | "public") =>
    request<Publication>("/v1/publications", {
      method: "POST",
      body: JSON.stringify({ production_run_id, audience }),
    }),
  withdrawPublication: (publicationId: string) =>
    request<Publication>(`/v1/publications/${publicationId}/withdraw`, { method: "POST" }),
  listJobs: () => request<Job[]>("/v1/jobs"),
  retryJob: (jobId: string) =>
    request<Job>(`/v1/jobs/${jobId}/retry`, { method: "POST" }),
};

export function generatedAssetUrl(assetId: string) {
  return `${API_BASE_URL}/v1/production/assets/${assetId}/content`;
}

export function evidenceAssetUrl(assetId: string) {
  return `${API_BASE_URL}/v1/evidence/assets/${assetId}/content`;
}

export function publicContentUrl(token: string) {
  return `${API_BASE_URL}/v1/public/${token}/content`;
}
