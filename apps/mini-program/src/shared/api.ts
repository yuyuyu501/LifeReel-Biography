import Taro from "@tarojs/taro";
import type {
  Chapter,
  InterviewSession,
  InterviewRound,
  InterviewTurnWorkflow,
  InterviewWorkspace,
  Job,
  MemoryClaim,
  MemoryConflict,
  MemoryEntity,
  MemoryGraph,
  MemoryOverview,
  Person,
  PersonCreate,
  PersonUpdate,
  ProductionRun,
  ProductionSettings,
  ScriptProject,
  SourceAsset,
  TimelineAnchor,
} from "@lifereel/contracts";
import { getStored, removeStored, store } from "./platform";

type AuthUser = {
  id: string;
  tenant_id: string;
  email: string | null;
  phone: string | null;
  display_name: string;
  role: string;
  is_admin: boolean;
};

type MiniAuth = {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  user: AuthUser;
};

const ACCESS_TOKEN = "lifereel_mini_access_token";
const REFRESH_TOKEN = "lifereel_mini_refresh_token";
const apiBaseUrl =
  process.env.TARO_APP_API_BASE_URL || "https://bianjiaigc.com";
type RequestOptions = Omit<Taro.request.Option, "url">;

async function request<T>(
  path: string,
  options: RequestOptions = {},
  allowRefresh = true,
): Promise<T> {
  const accessToken = getStored<string>(ACCESS_TOKEN);
  const response = await Taro.request<T>({
    url: `${apiBaseUrl}${path}`,
    ...options,
    header: {
      ...(options.header || {}),
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
    },
  });
  if (
    response.statusCode === 401 &&
    allowRefresh &&
    getStored<string>(REFRESH_TOKEN)
  ) {
    try {
      const auth = await request<MiniAuth>(
        "/v1/auth/mini-program/refresh",
        {
          method: "POST",
          data: { refresh_token: getStored<string>(REFRESH_TOKEN) },
        },
        false,
      );
      miniApi.saveAuth(auth);
      return request<T>(path, options, false);
    } catch {
      miniApi.clearAuth();
    }
  }
  if (response.statusCode < 200 || response.statusCode >= 300) {
    const error = response.data as {
      error?: { code?: string; message?: string };
    };
    throw new Error(
      error.error?.message ||
        error.error?.code ||
        `请求失败（${response.statusCode}）`,
    );
  }
  return response.data;
}

export const miniApi = {
  login: (platform: "wechat" | "douyin", code: string, displayName?: string) =>
    request<MiniAuth>("/v1/auth/mini-program/login", {
      method: "POST",
      data: {
        platform,
        code,
        ...(displayName ? { display_name: displayName } : {}),
      },
    }),
  refresh: () => {
    const refreshToken = getStored<string>(REFRESH_TOKEN);
    if (!refreshToken) throw new Error("登录状态已失效，请重新登录");
    return request<MiniAuth>("/v1/auth/mini-program/refresh", {
      method: "POST",
      data: { refresh_token: refreshToken },
    });
  },
  me: () => request<AuthUser>("/v1/auth/me"),
  persons: () => request<Person[]>("/v1/persons"),
  person: (id: string) => request<Person>(`/v1/persons/${id}`),
  createPerson: (payload: PersonCreate) =>
    request<Person>("/v1/persons", { method: "POST", data: payload }),
  updatePerson: (id: string, payload: PersonUpdate) =>
    request<Person>(`/v1/persons/${id}`, { method: "PATCH", data: payload }),
  chapters: () => request<Chapter[]>("/v1/chapters"),
  interviews: () => request<InterviewSession[]>("/v1/interviews"),
  startInterview: (payload: {
    subject_id: string;
    chapter_id?: string;
    topic_hint?: string;
  }) =>
    request<InterviewSession>("/v1/interviews", {
      method: "POST",
      data: payload,
    }),
  interview: (id: string) => request<InterviewSession>(`/v1/interviews/${id}`),
  nextQuestion: (id: string) =>
    request<{
      question_text: string;
      question_intent: string;
      question_source: string;
    }>(`/v1/interviews/${id}/next-question`),
  createRound: (
    sessionId: string,
    payload: {
      question_text: string;
      question_intent?: string;
      question_source?: string;
    },
  ) =>
    request<InterviewRound>(`/v1/interviews/${sessionId}/rounds`, {
      method: "POST",
      data: payload,
    }),
  answerRound: (
    sessionId: string,
    roundId: string,
    payload: { answer_text: string; source_asset_id?: string },
  ) =>
    request<InterviewRound>(
      `/v1/interviews/${sessionId}/rounds/${roundId}/answer`,
      { method: "POST", data: payload },
    ),
  workspace: (sessionId: string) =>
    request<InterviewWorkspace>(`/v1/interviews/${sessionId}/workspace`),
  createTurn: (
    sessionId: string,
    payload: {
      action?: "interview" | "regenerate_script";
      round_id?: string;
      answer_text?: string;
      asset_ids?: string[];
      idempotency_key: string;
    },
  ) =>
    request<InterviewTurnWorkflow>(`/v1/interviews/${sessionId}/turns`, {
      method: "POST",
      data: payload,
    }),
  memories: (subjectId: string) =>
    request<MemoryClaim[]>(`/v1/memories?subject_id=${subjectId}`),
  memoryOverview: (subjectId: string) =>
    request<MemoryOverview>(`/v1/memories/subjects/${subjectId}/overview`),
  entities: (subjectId: string) =>
    request<MemoryEntity[]>(`/v1/memories/subjects/${subjectId}/entities`),
  timeline: (subjectId: string) =>
    request<TimelineAnchor[]>(`/v1/memories/subjects/${subjectId}/timeline`),
  conflicts: (subjectId: string) =>
    request<MemoryConflict[]>(`/v1/memories/subjects/${subjectId}/conflicts`),
  graph: (subjectId: string) =>
    request<MemoryGraph>(`/v1/memories/subjects/${subjectId}/graph`),
  scripts: () => request<ScriptProject[]>("/v1/scripts"),
  script: (projectId: string) =>
    request<ScriptProject>(`/v1/scripts/${projectId}`),
  generateScript: (payload: {
    subject_id: string;
    title?: string;
    mode?: "single_chapter" | "multi_chapter";
    audience?: string;
    chapter_id?: string;
  }) =>
    request<ScriptProject>("/v1/scripts/generate", {
      method: "POST",
      data: payload,
    }),
  productionSettings: () =>
    request<ProductionSettings>("/v1/production/settings"),
  productionRuns: () => request<ProductionRun[]>("/v1/production/runs"),
  startProduction: (payload: {
    project_id: string;
    scene_id?: string;
    audience?: string;
    provider?: string;
  }) =>
    request<ProductionRun>("/v1/production/runs", {
      method: "POST",
      data: payload,
    }),
  jobs: () => request<Job[]>("/v1/jobs"),
  job: (jobId: string) => request<Job>(`/v1/jobs/${jobId}`),
  retryJob: (jobId: string) =>
    request<Job>(`/v1/jobs/${jobId}/retry`, { method: "POST" }),
  assets: (subjectId: string) =>
    request<SourceAsset[]>(`/v1/evidence/assets?subject_id=${subjectId}`),
  uploadAsset: (
    filePath: string,
    subjectId: string,
    kind: "audio" | "photo" | "video" | "document",
    sessionId?: string,
  ) =>
    new Promise<SourceAsset>((resolve, reject) => {
      Taro.uploadFile({
        url: `${apiBaseUrl}/v1/evidence/assets`,
        filePath,
        name: "file",
        formData: {
          subject_id: subjectId,
          kind,
          consent_scope: "private",
          ...(sessionId ? { interview_session_id: sessionId } : {}),
        },
        header: getStored<string>(ACCESS_TOKEN)
          ? { Authorization: `Bearer ${getStored<string>(ACCESS_TOKEN)}` }
          : {},
        success: (response) => {
          try {
            if (response.statusCode < 200 || response.statusCode >= 300)
              throw new Error(`上传失败（${response.statusCode}）`);
            resolve(JSON.parse(response.data) as SourceAsset);
          } catch (error) {
            reject(error);
          }
        },
        fail: reject,
      });
    }),
  saveAuth(auth: MiniAuth) {
    store(ACCESS_TOKEN, auth.access_token);
    store(REFRESH_TOKEN, auth.refresh_token);
    store("lifereel_mini_user", auth.user);
  },
  clearAuth() {
    removeStored(ACCESS_TOKEN);
    removeStored(REFRESH_TOKEN);
    removeStored("lifereel_mini_user");
  },
};
