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

export type AuthUser = { id: string; tenant_id: string; email: string | null; phone: string | null; display_name: string; role: string; is_admin: boolean };
export type SmsPurpose = "register" | "reset_password" | "bind_phone" | "delete_account";
export type SmsVerification = { phone: string; challenge_id: string; code: string };
export type Account = { id: string; email: string | null; phone: string | null; display_name: string; is_active: boolean; is_admin: boolean; created_at: string; deleted_at: string | null };
export type AccountChanges = { display_name?: string; email?: string; password?: string; is_active?: boolean };

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
  registration: () => request<{ enabled: boolean; sms_enabled: boolean; password_reset_enabled?: boolean; phone_verification_enabled?: boolean }>("/v1/auth/registration"),
  sendSms: (phone: string, purpose: SmsPurpose) => request<{ challenge_id: string; expires_in: number; retry_after: number }>("/v1/auth/sms", { method: "POST", body: JSON.stringify({ phone, purpose }) }),
  register: (payload: SmsVerification & { password: string; display_name: string }) => request<AuthUser>("/v1/auth/register", {
    method: "POST", body: JSON.stringify(payload),
  }),
  resetPassword: (payload: SmsVerification & { password: string }) => request<void>("/v1/auth/password/reset", { method: "POST", body: JSON.stringify(payload) }),
  updateProfile: (display_name: string) => request<AuthUser>("/v1/auth/me", { method: "PATCH", body: JSON.stringify({ display_name }) }),
  changePassword: (current_password: string, password: string) => request<void>("/v1/auth/password", { method: "POST", body: JSON.stringify({ current_password, password }) }),
  changePhone: (payload: SmsVerification & { current_password: string }) => request<void>("/v1/auth/phone", { method: "PUT", body: JSON.stringify(payload) }),
  deleteAccount: (payload: { current_password: string; challenge_id?: string; code?: string }) => request<void>("/v1/auth/me", { method: "DELETE", body: JSON.stringify(payload) }),
  accounts: (q = "", state = "all", page = 1) => request<{ items: Account[]; total: number; page: number; page_size: number }>(`/v1/auth/accounts?${new URLSearchParams({ q, state, page: String(page) })}`),
  account: (id: string) => request<Account>(`/v1/auth/accounts/${id}`),
  createAccount: (payload: { display_name: string; email: string; password: string }) => request<Account>("/v1/auth/accounts", { method: "POST", body: JSON.stringify(payload) }),
  updateAccount: (id: string, payload: AccountChanges) => request<Account>(`/v1/auth/accounts/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  removeAccount: (id: string) => request<void>(`/v1/auth/accounts/${id}`, { method: "DELETE" }),
  login: (email: string, password: string) =>
    request<{ expires_in: number; user: AuthUser }>(
      "/v1/auth/login",
      { method: "POST", body: JSON.stringify({ email, password }) },
    ),
  me: () => request<AuthUser>("/v1/auth/me"),
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
      round_id?: string;
      action?: "interview" | "regenerate_script";
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
  listMemories: (subjectId?: string) =>
    request<MemoryClaim[]>(`/v1/memories${subjectId ? `?subject_id=${subjectId}` : ""}`),
  compileMemories: (payload: { interview_session_id?: string; subject_id?: string }) =>
    request<MemoryCompileResult>("/v1/memories/compile", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  listScripts: () => request<ScriptProject[]>("/v1/scripts"),
  scriptReferences: (projectId: string, sceneId: string) =>
    request<SourceAsset[]>(`/v1/scripts/${projectId}/scenes/${sceneId}/references`),
  updateScriptReferences: (projectId: string, sceneId: string, expectedVersion: number, assetIds: string[]) =>
    request<ScriptProject>(`/v1/scripts/${projectId}/scenes/${sceneId}/references`, {
      method: "PATCH", body: JSON.stringify({ expected_version: expectedVersion, asset_ids: assetIds }),
    }),
  updateScriptScene: (projectId: string, sceneId: string, payload: import("@lifereel/contracts").ScriptSceneUpdate) =>
    request<ScriptProject>(`/v1/scripts/${projectId}/scenes/${sceneId}`, {
      method: "PATCH", body: JSON.stringify(payload),
    }),
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
  uploadEvidence: async (payload: {
    subjectId: string;
    interviewSessionId?: string;
    kind: "audio" | "photo" | "video" | "document";
    consentScope?: "private" | "family" | "friends" | "public";
    file: File;
  }) => {
    const settings = await request<{ direct_upload: boolean }>("/v1/evidence/upload-settings");
    if (settings.direct_upload) {
      const permit = await request<{
        upload_id: string;
        url: string;
        fields: Record<string, string>;
        expires_at: string;
      }>("/v1/evidence/assets/direct-upload", {
        method: "POST",
        body: JSON.stringify({
          subject_id: payload.subjectId,
          interview_session_id: payload.interviewSessionId,
          kind: payload.kind,
          consent_scope: payload.consentScope ?? "private",
          original_filename: payload.file.name,
          mime_type: payload.file.type,
          byte_size: payload.file.size,
        }),
      });
      const directForm = new FormData();
      for (const [key, value] of Object.entries(permit.fields)) directForm.append(key, value);
      // OSS requires the file field last. Do not send application cookies or headers.
      directForm.append("file", payload.file);
      let uploaded: Response;
      try {
        uploaded = await fetch(permit.url, {
          method: "POST", credentials: "omit", body: directForm,
        });
      } catch {
        throw new ApiError("EVIDENCE_UPLOAD_FAILED", 0);
      }
      if (!uploaded.ok) throw new ApiError("EVIDENCE_UPLOAD_FAILED", uploaded.status);
      return request<SourceAsset>("/v1/evidence/assets/complete-direct-upload", {
        method: "POST", body: JSON.stringify({ upload_id: permit.upload_id }),
      });
    }
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
  photoRedrawStatus: (assetId: string) =>
    request<{ enabled: boolean; job: Job | null }>(`/v1/evidence/assets/${assetId}/redraw`),
  redrawPhoto: (assetId: string) =>
    request<Job>(`/v1/evidence/assets/${assetId}/redraw`, { method: "POST" }),
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
  restoreProductionOriginal: (runId: string) =>
    request<ProductionRun>(`/v1/production/runs/${runId}/continuation`, { method: "POST" }),
  replaceProductionReference: (runId: string, referenceAssetId: string) =>
    request<ProductionRun>(`/v1/production/runs/${runId}/reference`, {
      method: "POST", body: JSON.stringify({ reference_asset_id: referenceAssetId }),
    }),
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

export function productionSegmentUrl(runId: string, index: number) {
  return `${API_BASE_URL}/v1/production/runs/${runId}/segments/${index}/content`;
}

export function evidenceAssetUrl(assetId: string) {
  return `${API_BASE_URL}/v1/evidence/assets/${assetId}/content`;
}

export function publicContentUrl(token: string) {
  return `${API_BASE_URL}/v1/public/${token}/content`;
}
