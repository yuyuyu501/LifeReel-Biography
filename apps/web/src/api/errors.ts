export const ERROR_MESSAGES: Record<string, string> = {
  NETWORK_ERROR: "网络连接失败，请检查网络后重试。",
  REQUEST_VALIDATION_FAILED: "提交的信息格式不正确，请检查后重试。",
  ROUTE_NOT_FOUND: "请求的功能不存在或已调整。",
  METHOD_NOT_ALLOWED: "当前操作方式不受支持。",
  REQUEST_FAILED: "请求失败，请稍后重试。",
  INTERNAL_SERVER_ERROR: "服务暂时出现异常，请稍后重试。",
  API_KEY_NOT_CONFIGURED: "服务访问密钥尚未配置，请联系管理员。",
  API_KEY_INVALID: "服务访问凭据无效，请联系管理员。",
  AUTH_INVALID_CREDENTIALS: "邮箱或密码不正确。",
  AUTH_MEMBERSHIP_MISSING: "该账号尚未加入家庭空间。",
  AUTH_SESSION_INVALID: "登录状态已失效，请重新登录。",
  AUTH_SESSION_INACTIVE: "该账号的家庭成员权限已失效，请重新登录。",
  AUTH_REQUIRED: "请先登录后再继续。",
  AUTH_READ_ONLY: "当前账号只有查看权限，不能执行此操作。",
  AUTH_USER_NOT_FOUND: "登录账号已不存在，请联系管理员。",
  PERSON_NOT_FOUND: "未找到该人物。",
  SUBJECT_NOT_FOUND: "未找到传记主人公。",
  CHAPTER_NOT_FOUND: "未找到该采访章节。",
  INTERVIEW_NOT_FOUND: "未找到该采访。",
  INTERVIEW_INACTIVE: "该采访已结束或暂停，无法继续操作。",
  INTERVIEW_ROUND_NOT_FOUND: "未找到该轮采访问题。",
  INTERVIEW_TURN_CONTENT_REQUIRED: "请先输入回答、录制语音或添加一份素材。",
  INTERVIEW_TURN_NOT_FOUND: "未找到这次整理任务。",
  INTERVIEW_TURN_STATE_INVALID: "这次内容正在处理或已经处理，请刷新后查看。",
  EVIDENCE_ASSET_NOT_FOUND: "未找到该素材。",
  EVIDENCE_ASSET_REQUIRED: "请先选择一份素材。",
  EVIDENCE_FILE_EMPTY: "不能上传空文件。",
  EVIDENCE_FILE_TOO_LARGE: "素材文件过大，请压缩后重试。",
  EVIDENCE_TYPE_UNSUPPORTED: "不支持这种素材格式。",
  EVIDENCE_RANGE_INVALID: "素材读取位置无效，请重新打开预览。",
  EVIDENCE_ANALYSIS_UNSUPPORTED: "这种素材暂时无法进行 AI 分析。",
  EVIDENCE_ANALYSIS_FAILED: "素材分析失败，请稍后重试。",
  VISION_CONFIGURATION_INCOMPLETE: "图片分析服务配置不完整，请联系管理员。",
  VISION_REQUEST_FAILED: "AI 暂时未完成图片或视频分析，请稍后重试。",
  VISION_RESPONSE_INVALID: "AI 返回的图片或视频分析结果无效，请稍后重试。",
  INTERVIEW_LLM_CONFIGURATION_INCOMPLETE: "采访 AI 配置不完整，请联系管理员。",
  INTERVIEW_LLM_REQUEST_FAILED: "采访 AI 暂时无法回答，请等待片刻后重试。",
  INTERVIEW_LLM_RESPONSE_INVALID: "采访 AI 返回的内容无效，请等待片刻后重试。",
  MEMORY_LLM_CONFIGURATION_INCOMPLETE: "记忆 AI 配置不完整，请联系管理员。",
  MEMORY_LLM_REQUEST_FAILED: "记忆 AI 暂时未完成整理，请稍后重试。",
  MEMORY_LLM_RESPONSE_INVALID: "记忆 AI 返回的整理结果无效，请稍后重试。",
  ASR_NOT_CONFIGURED: "语音转写服务尚未配置。",
  ASR_CONFIGURATION_INCOMPLETE: "语音转写服务配置不完整，请联系管理员。",
  ASR_REQUEST_FAILED: "语音转写失败，请稍后重试。",
  ASR_EMPTY_TRANSCRIPT: "语音转写没有识别出文字，请检查录音后重试。",
  TRANSCRIPT_NOT_FOUND: "该素材还没有逐字稿。",
  MEMORY_REVIEW_STATUS_INVALID: "记忆审核状态无效。",
  MEMORY_CLAIM_NOT_FOUND: "未找到该条记忆。",
  SCRIPT_PROJECT_NOT_FOUND: "未找到该剧本项目。",
  SCRIPT_MEMORIES_REQUIRED: "请先整理采访记忆，再生成剧本。",
  SCRIPT_LLM_CONFIGURATION_INCOMPLETE: "剧本生成模型配置不完整，请联系管理员。",
  SCRIPT_LLM_REQUEST_FAILED: "AI 剧本生成失败，请稍后重试。",
  SCRIPT_LLM_RESPONSE_INVALID: "AI 返回的剧本格式或来源引用无效，请重新生成。",
  GUARDIAN_CONSENT_REQUIRED: "未成年人需要监护人授权后才能制作。",
  PRODUCTION_CONSENT_REQUIRED: "缺少当前发布范围所需的制作授权。",
  PORTRAIT_CONSENT_REQUIRED: "缺少当前发布范围所需的肖像授权。",
  PUBLICATION_CONSENT_REQUIRED: "缺少当前发布范围所需的发布授权。",
  CONSENT_NOT_FOUND: "未找到该授权记录。",
  VIDEO_PROVIDER_INVALID: "所选视频生成服务不可用，请检查配置。",
  VIDEO_PROVIDER_FAILED: "视频生成失败，请稍后重试。",
  PRODUCTION_SCRIPT_EMPTY: "剧本还没有可制作的章节，请先继续整理剧本。",
  PRODUCTION_RUN_NOT_FOUND: "未找到该制作任务。",
  PRODUCTION_STATE_INVALID: "制作任务状态异常，请重新创建任务。",
  PRODUCTION_ASSET_NOT_FOUND: "未找到生成的视频文件。",
  PRODUCTION_NOT_COMPLETED: "视频制作完成后才能发布。",
  PUBLICATION_AUDIENCE_MISMATCH: "发布范围与制作时选择的范围不一致。",
  PUBLICATION_NOT_FOUND: "未找到该发布记录。",
  PUBLICATION_UNAVAILABLE: "该影传不存在、已撤回或暂不可访问。",
  PUBLICATION_ASSET_UNAVAILABLE: "已发布的影传文件暂不可用。",
  JOB_NOT_FOUND: "未找到该任务。",
  JOB_RETRY_NOT_ALLOWED: "只有失败或已取消的任务可以重试。",
  WORKER_ERROR: "后台任务执行失败，请稍后重试。",
};

const EVIDENCE_KIND_LABELS: Record<string, string> = {
  photo: "图片",
  document: "文档",
  audio: "音频",
  video: "视频",
};

function localizedErrorMessage(code: string, context?: Record<string, unknown>): string {
  if (code === "EVIDENCE_FILE_TOO_LARGE") {
    const kind = typeof context?.kind === "string" ? context.kind : "";
    const limitBytes = typeof context?.limit_bytes === "number" ? context.limit_bytes : 0;
    const label = EVIDENCE_KIND_LABELS[kind];
    if (label && limitBytes > 0) {
      const unit = limitBytes >= 1024 ** 3 ? "GB" : "MB";
      const divisor = unit === "GB" ? 1024 ** 3 : 1024 ** 2;
      return `${label}不能超过 ${limitBytes / divisor} ${unit}。`;
    }
  }
  return ERROR_MESSAGES[code] ?? "操作失败，请稍后重试。";
}

const STATUS_FALLBACK_CODES: Record<number, string> = {
  400: "REQUEST_FAILED",
  401: "AUTH_REQUIRED",
  403: "AUTH_READ_ONLY",
  404: "ROUTE_NOT_FOUND",
  405: "METHOD_NOT_ALLOWED",
  413: "EVIDENCE_FILE_TOO_LARGE",
  422: "REQUEST_VALIDATION_FAILED",
  500: "INTERNAL_SERVER_ERROR",
  502: "REQUEST_FAILED",
  503: "REQUEST_FAILED",
};

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly context?: Record<string, unknown>;

  constructor(code: string, status: number, context?: Record<string, unknown>) {
    super(localizedErrorMessage(code, context));
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.context = context;
  }
}

export function apiErrorFromResponse(
  status: number,
  payload: unknown,
): ApiError {
  const error =
    payload && typeof payload === "object" && "error" in payload
      ? (payload.error as Record<string, unknown> | null)
      : null;
  const code = typeof error?.code === "string"
    ? error.code
    : STATUS_FALLBACK_CODES[status] ?? "REQUEST_FAILED";
  const context = error?.context && typeof error.context === "object"
    ? error.context as Record<string, unknown>
    : undefined;
  return new ApiError(code, status, context);
}

export function isApiError(error: unknown, code?: string): error is ApiError {
  return error instanceof ApiError && (!code || error.code === code);
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return "操作失败，请稍后重试。";
}

export function isAuthenticationError(error: unknown): boolean {
  return error instanceof ApiError && [
    "AUTH_REQUIRED",
    "AUTH_SESSION_INVALID",
    "AUTH_SESSION_INACTIVE",
    "AUTH_USER_NOT_FOUND",
    "AUTH_MEMBERSHIP_MISSING",
  ].includes(error.code);
}
