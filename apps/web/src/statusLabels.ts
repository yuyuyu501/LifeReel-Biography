const labels = {
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
} satisfies Record<string, string>;

export function statusLabel(value: string | null | undefined, fallback = "未知状态") {
  if (!value) return fallback;
  return labels[value as keyof typeof labels] ?? fallback;
}

export function providerLabel(value: string) {
  if (value === "mock" || value.startsWith("mock-")) return "本地模拟生成";
  if (value === "openai-compatible") return "兼容接口服务";
  if (value.startsWith("generic-media")) return "媒体生成服务";
  return "已配置生成服务";
}
