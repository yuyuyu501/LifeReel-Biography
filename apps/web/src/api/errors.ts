export const ERROR_MESSAGES: Record<string, string> = {
  RESOURCE_BUSY: "当前处理任务较多，请稍后重试。已保存的内容不会丢失。",
  WALLET_NOT_FOUND: "未找到所属家庭的钱包。",
  WALLET_INSUFFICIENT_BALANCE: "钱包可用余额不足，已暂停新的调用或任务。请前往钱包查看余额。",
  BILLING_STATE_INVALID: "扣费状态异常，请刷新后重试或联系管理员。",
  BILLING_MODEL_UNPRICED: "当前模型尚未配置用量价格，请联系管理员。",
  BILLING_USAGE_PENDING: "上次 AI 调用的用量正在核对，已暂停新的调用，请联系管理员核对后再试。",
  BILLING_BUSY: "当前章节正在生成，请稍后重试。",
  BILLING_QUOTE_CHANGED: "价格已更新，请刷新页面后重新确认。",
  PAYMENT_NOT_ENABLED: "充值暂未开通，请勿向任何收款码付款。",
  RECHARGE_NOT_FOUND: "没有找到这笔充值订单。",
  RECHARGE_STATE_INVALID: "订单状态已更新，请刷新充值记录。",
  RECHARGE_LIMIT_REACHED: "充值操作过于频繁，请稍后再试。",
  RECHARGE_REQUEST_CONFLICT: "充值金额与原请求不一致，请重新选择金额。",
  RECHARGE_AMOUNT_MISMATCH: "核实金额与订单不一致，暂未入账。",
  RECHARGE_RECEIPT_USED: "这笔微信交易已用于其它订单，不能重复入账。",
  REGISTRATION_DISABLED: "注册暂未开放，请联系管理员。",
  REGISTRATION_EMAIL_UNAVAILABLE: "该邮箱无法注册，请登录或换用其他邮箱。",
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
  EVIDENCE_UPLOAD_UNAVAILABLE: "素材直传服务暂不可用，请联系管理员。",
  EVIDENCE_UPLOAD_NOT_FOUND: "素材尚未上传完成或上传记录不存在，请重新上传。",
  EVIDENCE_UPLOAD_EXPIRED: "上传凭证已过期，请重新选择文件上传。",
  EVIDENCE_UPLOAD_INVALID: "素材内容校验未通过，请检查文件后重新上传。",
  EVIDENCE_UPLOAD_BUSY: "待完成的上传较多，请稍后重试。",
  EVIDENCE_UPLOAD_FAILED: "素材上传或校验失败，请检查网络后重试；持续失败请联系管理员检查存储跨域配置。",
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
  MEMORY_RETRY_LIMIT_REACHED: "本轮整理已达到重试上限，请联系管理员排查。已保存的回答和剧本仍可查看。",
  MEMORY_RETRY_COOLDOWN: "请稍等片刻再重新整理，避免重复消耗。",
  ASR_NOT_CONFIGURED: "语音转写服务尚未配置。",
  ASR_CONFIGURATION_INCOMPLETE: "语音转写服务配置不完整，请联系管理员。",
  ASR_REQUEST_FAILED: "语音转写失败，请稍后重试。",
  ASR_EMPTY_TRANSCRIPT: "语音转写没有识别出文字，请检查录音后重试。",
  TRANSCRIPT_NOT_FOUND: "该素材还没有逐字稿。",
  MEMORY_REVIEW_STATUS_INVALID: "记忆审核状态无效。",
  MEMORY_CLAIM_NOT_FOUND: "未找到该条记忆。",
  SCRIPT_PROJECT_NOT_FOUND: "未找到该剧本项目。",
  SCRIPT_EDIT_CONFLICT: "剧本已在其他位置更新，请刷新后重新编辑。当前输入仍已保留。",
  SCRIPT_EDIT_BUSY: "本章正在由 AI 整理，请等待完成后再保存修改。",
  SCRIPT_CONTENT_INVALID: "请检查剧本内容，分镜时长之和须等于章节总时长。",
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
  VIDEO_PROVIDER_CONFIGURATION_INCOMPLETE: "视频生成服务配置不完整，请联系管理员。",
  VIDEO_PROVIDER_REQUEST_FAILED: "视频生成服务暂时无法连接，请稍后重试。",
  VIDEO_PROVIDER_TIMEOUT: "视频生成等待超时，请稍后重试。",
  VIDEO_PROVIDER_OUTPUT_INVALID: "视频生成结果无效，请重新生成。",
  VIDEO_PROVIDER_FAILED: "视频生成失败，请稍后重试。",
  VIDEO_REFERENCE_REJECTED: "续接素材未通过视频平台的内容审核，请先处理下方的续接问题。",
  VIDEO_CONTINUATION_UNAVAILABLE: "无法验证原始续接素材，可能已过期或生成账号发生变化。请稍后重试或联系支持。",
  VIDEO_CONTENT_REJECTED: "视频内容未通过平台审核，请先修改相关剧本内容。",
  VIDEO_REFERENCE_INVALID: "请选择该家人名下另一张不超过 10MB 的 JPEG、PNG 或 WebP 图片，不可重复使用已被拒的图片。",
  VIDEO_PLAN_FAILED: "分镜 AI 暂时不可用，请稍后重试。",
  VIDEO_PLAN_INVALID: "分镜结果未通过校验，暂未生成视频。",
  VIDEO_PLAN_CONFIGURATION_INCOMPLETE: "请先配置分镜 AI 服务。",
  VIDEO_ASSEMBLY_UNAVAILABLE: "视频拼接工具不可用，请检查服务配置。",
  VIDEO_ASSEMBLY_FAILED: "视频拼接失败，已生成片段会保留，请重试。",
  VIDEO_DURATION_UNSUPPORTED: "每章需为 4 至 300 秒，一次制作最多 24 段。",
  VIDEO_DURATION_MISMATCH: "视频时长与分镜计划不符，请检查生成结果。",
  VIDEO_SUBMISSION_UNCERTAIN: "提交结果不确定，已停止自动重发，请先核对云端任务。",
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
