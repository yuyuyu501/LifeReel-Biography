# 总体架构

## 1. 目标形态

当前采用独立进程服务：Web 与小程序为两个前端板块；Gateway 只做路由；Identity、Interview、Memory、Script、Media、Billing、Model Gateway、Tasks 分别启动；两个 Worker 在自己的进程执行任务。每个服务和 Worker 有独立目录、入口与 Dockerfile。

服务间 HTTP 使用 HMAC 签名、调用方白名单与租户校验。事务 Outbox 投递到 Inbox 后才能领取任务；账本命令和剧本结果有幂等收据。成功的模型响应可重放缓存，网络不确定状态禁止自动重复收费请求。

仍保留单个 PostgreSQL、共享 ORM 和同一版本 backend wheel。人物小传更新、初始化及部分跨域查询仍有兼容性共享；尚不是每服务独立数据库或独立依赖发布。主机与数据库仍是共同故障域。实时语音连接由 Interview 持有，记忆与剧本更新调用独立服务。

```mermaid
flowchart TB
    WEB[React PWA\n老人端 / 家属端 / 工作台]
    API[Nginx Gateway]
    ORCHESTRATOR[Interview Orchestrator]
    SERVICES[Evidence / Memory / Script Services]
    WORKER[Interview Worker + Media Worker]
    PG[(PostgreSQL + pgvector)]
    REDIS[(Redis)]
    S3[(S3 / MinIO 私有对象存储)]
    PROVIDERS[ASR / LLM / Image / Video / Voice Providers]

    WEB --> API
    API --> ORCHESTRATOR
    API --> SERVICES
    ORCHESTRATOR --> PG
    SERVICES --> PG
    API --> S3
    API --> REDIS
    PG -->|Outbox / Inbox 与租约| WORKER
    WORKER --> SERVICES
    SERVICES --> S3
    SERVICES --> PROVIDERS
```

## 2. 领域边界

| 模块 | 职责 |
|---|---|
| Auth / Identity | 账号、会话、租户成员、人物和关系 |
| Interview | 章节、采访会话、轮次、问题规划 |
| Interview Orchestrator | Turn 幂等、处理状态、信息缺口与跨服务编排 |
| Evidence | 媒体、逐字稿、片段、版本与哈希 |
| Memory | 主张、实体、关系图谱、时间线、矛盾和覆盖度 |
| Script | 人物剧本、章节、镜头和持续版本更新 |
| Governance | 肖像、声音、制作、发布和监护授权及审计 |
| Production | Provider 任务、费用、FFmpeg 合成与生成资产 |
| Publication | 家庭/朋友/公开独立构建与撤回 |

## 3. 数据原则

1. 原始证据只追加版本，不被 AI 输出覆盖。
2. `Claim` 是可引用、可冲突、可撤回的事实单元。
3. 所有查询必须带租户边界。
4. 生成资产必须记录输入版本、Provider、模型、费用和输出哈希。
5. 对外内容按目标受众独立构建并校验授权，不在同一份完整内容上做运行时隐藏。

## 4. Provider 设计

业务层使用统一接口：

- `capabilities()`
- `estimate(request)`
- `submit(request, idempotency_key)`
- `get_status(provider_job_id)`
- `cancel(provider_job_id)`
- `fetch_outputs(provider_job_id)`

当前代码包含五类确定性 Mock Provider、OpenAI-compatible LLM/ASR，以及已接入生产 Worker 的通用异步媒体适配器。可通过 `GET /v1/providers` 查看能力和配置状态。外部视频输出可通过下载 URL 或 Base64 返回，系统下载后写入私有存储并记录哈希。

## 5. 当前可运行的数据链路

```mermaid
flowchart LR
    PERSON[人物 Person] --> SESSION[采访 InterviewSession]
    SESSION --> ROUND[问答 InterviewRound]
    ROUND --> TURN[持久化 Turn 工作流]
    TURN -->|素材分析 / ASR| OBSERVATION[证据 Observation]
    TURN -->|保留 source_round_id 与原话| CLAIM[记忆 MemoryClaim]
    OBSERVATION -->|保留 source_observation_id| CLAIM
    CLAIM -->|保留 source_claim_ids| SCRIPT[剧本 ScriptProject]
    SCRIPT --> SCENE[场景 ScriptScene]
    SCENE --> CONSENT[制作 / 肖像 / 发布授权]
    CONSENT --> JOB[幂等视频生产 Job]
    JOB --> ASSET[私有生成资产]
    ASSET --> PUBLICATION[分受众发布 / 撤回]
```

每次文字、语音或素材提交都会创建 `interview.turn.process` 工作流。Worker 依次完成素材分析、记忆编译、AI 语义缺口判断、结构化 `ScriptUpdateBrief`、当前章节剧本与镜头更新，再写入 AI 生成的下一条追问。Mock 模式保留确定性实现用于测试；OpenAI-compatible 真实模式禁止规则降级，采访、记忆、视觉或剧本模型失败时记录领域错误码并由用户重新提交任务。无论使用何种 Provider，都不得覆盖原始证据或移除来源引用；当前章节会随新增采访持续重写为唯一最新稿。

## 6. 身份与流量边界

- 浏览器经 Web Nginx 同源访问 API；Nginx 注入内部 `X-API-Key`。
- 用户身份由签名的 HttpOnly 会话 Cookie 提供，租户与角色每次请求从数据库成员关系确认。
- Worker 直接执行所属领域任务，内部 HTTP 只调用其他服务能力；旧 HTTP Worker 已移除，公开网关禁止执行接口。
- 发布令牌只开放最小发布元数据和对应成片，不开放人物、记忆、逐字稿或素材列表。
