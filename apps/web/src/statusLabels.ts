const labels = {
  WALLET_INSUFFICIENT_BALANCE: "钱包可用余额不足，请前往钱包查看。",
  BILLING_STATE_INVALID: "扣费状态异常，请联系管理员。",
  BILLING_BUSY: "当前章节正在生成，请稍后重试。",
  active: "进行中",
  paused: "已暂停",
  completed: "已完成",
  queued: "等待处理",
  running: "处理中",
  failed: "处理失败",
  cancelled: "已取消",
  open: "待处理",
  resolved: "已解决",
  published: "已发布",
  withdrawn: "已撤回",
  granted: "已授权",
  revoked: "已撤销",
  draft: "草稿",
  unreviewed: "待核对",
  verified: "已核对",
  disputed: "存在争议",
  private: "仅自己可见",
  family: "家人可见",
  friends: "亲友可见",
  public: "公开",
  person: "人物",
  place: "地点",
  organization: "组织",
  year: "年份",
  relative: "相对时间",
  interview: "采访授权",
  portrait: "肖像授权",
  voice: "声音授权",
  production: "制作授权",
  publication: "发布授权",
  guardian: "监护人授权",
  audio: "音频",
  photo: "照片",
  video: "视频",
  document: "文档",
  ready: "可用",
  "production.render": "影传视频生成",
  VIDEO_PROVIDER_CONFIGURATION_INCOMPLETE: "视频服务配置不完整",
  VIDEO_PROVIDER_REQUEST_FAILED: "视频服务暂时无法连接",
  VIDEO_PROVIDER_TIMEOUT: "视频生成等待超时",
  VIDEO_PROVIDER_OUTPUT_INVALID: "视频生成结果无效",
  VIDEO_PROVIDER_FAILED: "视频生成失败",
  VIDEO_PLAN_FAILED: "分镜 AI 暂时不可用，请稍后重试",
  VIDEO_PLAN_INVALID: "分镜未完整保留剧本，请重试",
  VIDEO_PLAN_CONFIGURATION_INCOMPLETE: "分镜 AI 尚未配置",
  VIDEO_ASSEMBLY_UNAVAILABLE: "视频拼接工具不可用",
  VIDEO_ASSEMBLY_FAILED: "视频拼接失败，已生成片段会保留",
  VIDEO_DURATION_UNSUPPORTED: "章节时长超出支持范围",
  VIDEO_DURATION_MISMATCH: "视频时长与分镜计划不符",
  VIDEO_SUBMISSION_UNCERTAIN: "提交结果不确定，已停止自动重发，请先核对云端任务",
} satisfies Record<string, string>;

export function statusLabel(value: string | null | undefined, fallback = "未知状态") {
  if (!value) return fallback;
  return labels[value as keyof typeof labels] ?? fallback;
}

export function providerLabel(value: string) {
  if (value === "mock" || value.startsWith("mock-")) return "本地模拟生成";
  if (["volcengine-seedance", "volcengine-seedance-1.5"].includes(value)) {
    return "火山方舟 Seedance";
  }
  if (value === "openai-compatible") return "兼容接口服务";
  if (value.startsWith("generic-media")) return "媒体生成服务";
  return "已配置生成服务";
}
