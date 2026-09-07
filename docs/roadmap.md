# 开发路线图

## Phase 0：Foundation（已完成）

- Monorepo、CI、Docker Compose
- FastAPI、PostgreSQL、Redis、MinIO
- 人物、关系、章节、采访会话与轮次
- React PWA 首页、人物和采访入口
- Mock Provider 与 Worker 框架

退出条件：新环境可按 README 启动，核心测试和构建通过。

当前实现已由早期 Mock 垂直切片扩展为完整产品闭环。规则和 Mock 能力用于无外部密钥的本地验收，Provider 接口用于部署时替换模型服务。

## Phase 1：采访与证据 MVP（已完成首版）

- 浏览器录音与分片上传
- SourceAsset、Transcript、TranscriptSegment
- Mock ASR 与 OpenAI-compatible 云 ASR 适配器
- 逐字稿校对、版本和时间戳
- 采访暂停、恢复、结束和批处理

## Phase 2：长期记忆与追问（已完成 AI 版）

- AI Claim、Entity、TimelineAnchor、Conflict 与人物小传
- 混合检索与来源回放
- 章节约束、语义缺口、AI 追问和失败重试
- 会话弧、周度编译、覆盖度与质量画像

## Phase 3：自传短视频剧本（已完成基础版）

- Evidence Pack
- 单章 / 多章项目
- Season、Episode、Scene、Shot
- 真实性等级、来源覆盖和时代一致性检查
- 一章一稿、来源引用与持续版本更新

## Phase 4：短剧生产（已完成本地 Mock 版）

- 图像、视频、TTS Provider
- 镜头级生成、幂等、Webhook、轮询和重试
- FFmpeg / Remotion 合成
- 字幕、片头、音乐和成本账本

## Phase 5：授权与发布（已完成基础闭环）

- 肖像、声音、未成年人和第三方授权
- family / friends / public 独立构建
- 发布、撤回、下架和审计
- 封闭 Beta 与付费限额

## 外部上线事项

代码层业务闭环已经完成。正式上线仍需由部署方提供：HTTPS 域名、备份策略、告警渠道、邮件/短信服务，以及选定的 ASR、LLM、图像、视频和语音 Provider 密钥。未配置外部 Provider 时只能使用 Mock 模式做开发验收；真实模式不会在 AI 失败时回退到 Mock 或固定脚本。
