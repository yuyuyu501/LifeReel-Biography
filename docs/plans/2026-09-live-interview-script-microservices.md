# 实时采访成稿与微服务演进计划

- 日期：2026-09-07
- 状态：阶段 A 已完成；阶段 B/C 待独立部署条件成熟后实施
- 负责人：LifeReel 团队

> 更新：本文中的章节审核与锁定设计已由 ADR 0006 取代。当前章节允许随采访持续优化，制作阶段只校验内容存在和必要授权。

## 1. 背景

现有流程将采访、素材、长期记忆和剧本生成拆成连续页面，用户只有在采访结束后才能看到剧本。这不符合口述史访谈的真实节奏，也让用户难以判断当前章节还缺少什么。

本次改造把采访房间升级为“采访桌 + 同步成稿”工作台：左侧保留可长期续聊的采访记录，右侧持续呈现当前章节剧本；文字、录音或素材一旦提交，系统立即整理来源、更新本章草稿，并根据缺失信息生成下一次追问。

## 2. 目标

1. 一个人、一个章节仍只有一条长期采访会话。
2. 文字回答、录音、图片、音频、视频和文档均可在聊天输入区提交。
3. 每次提交产生可查询、可重试、可幂等的工作流状态。
4. 采访 AI 输出结构化的 `ScriptUpdateBrief`，剧本 AI 只消费该契约和可追溯记忆，不直接读取任意聊天字符串。
5. 当前章节剧本随采访增量更新，界面可看到处理中、已更新和失败状态。
6. 每次新增事实都重新整理该章唯一当前稿，不产生平行草稿。
7. 代码按可独立部署的服务边界整理，同时避免一次性引入多数据库和分布式事务。

## 3. 非目标

- 本阶段不拆分为数据库独占的多个仓库。
- 本阶段不引入 Kafka、服务网格或跨服务分布式事务。
- 本阶段使用轮询刷新工作流；SSE/WebSocket 放到后续阶段。
- 本阶段不自动生成最终视频，只把实时剧本作为后续影像服务的输入。

## 4. 新用户流程

1. 用户打开某人物的某一章节采访。
2. 左侧显示该章节永久保存的全部问答；右侧显示该章节当前草稿。
3. 用户输入文字、录音，或上传一份素材。
4. 系统保存原始回答或素材，并创建 `interview.turn.process` 工作流。
5. 素材服务完成 ASR、图片理解或文档抽取，产生证据观察。
6. 记忆服务把本次新增来源整理成可追溯记忆主张。
7. 采访编排器评估时间、地点、人物、事件、影响、感受和意义等缺口，输出下一问题与结构化剧本更新摘要。
8. 剧本服务用该章全部有效记忆重写唯一的当前章节稿件，并保留来源引用。
9. 工作流完成后，左侧出现下一问题，右侧刷新本章剧本与缺失信息。

## 5. 交互设计

### 桌面端

- 顶部保留采访状态、暂停、继续和结束操作。
- 主区为左右两栏，中间使用窄状态轴表达“已收到 → 正在整理 → 剧本已更新”。
- 左栏为聊天记录和输入器，上传入口支持图片、音频、视频和文档。
- 右栏只展示当前章节，包括旁白、画面建议、时长和来源数量。
- 剧本不存在时显示等待首次素材的空状态，不要求用户离开页面手动生成。

### 移动端

- 使用“采访 / 剧本”分段切换，不压缩为并排双栏。
- 输入器只固定在采访页签内。
- 工作流运行时页签显示更新状态，完成后可切换查看本章结果。

## 6. 服务边界

```text
Web Client
    |
    v
Core API / Gateway
    |-- Interview Orchestrator  ---- Redis job ----> Workflow Worker
    |          |                                      |
    |          |                                      +--> Evidence Service
    |          |                                      +--> Memory Service
    |          |                                      +--> Script Service
    |          |
    |          +--> Workspace read model
    |
    +--> Auth / Identity / Governance

PostgreSQL（过渡期共享实例，按表严格归属）
MinIO（私有原始素材）
```

当前部署保持 `web`、`api`、`worker`、PostgreSQL、Redis 和 MinIO。代码内部新增独立的编排模块和明确的消息契约；当吞吐或团队边界需要时，可把编排、素材与剧本入口分别部署，而无需改变 Web 契约。

## 7. 核心契约

### Turn 提交

`POST /v1/interviews/{session_id}/turns`

```json
{
  "round_id": "uuid",
  "answer_text": "可选文字",
  "asset_ids": ["uuid"],
  "idempotency_key": "客户端生成的稳定键"
}
```

返回当前工作流。提交至少包含文字或一份素材。已有录音可先通过素材接口上传并转写，再把素材 ID 与校对文本一并提交。

### 工作台读取

`GET /v1/interviews/{session_id}/workspace`

返回会话、当前章节剧本、关联素材、最新工作流、缺失主题及剧本摘要。前端在运行状态下轮询该接口。

### 内部执行

`POST /v1/internal/interview-turns/{workflow_id}/execute`

仅由 Worker 使用 API 访问密钥和租户头调用。重复执行已完成工作流时直接返回既有结果。

### ScriptUpdateBrief

```json
{
  "chapter_id": "uuid",
  "chapter_title": "童年岁月",
  "chapter_profile": {
    "keywords": ["童年", "玩伴", "家人", "游戏", "物件"],
    "required_topics": ["童年生活环境", "常见玩伴", "难忘小事", "童年感受"],
    "excluded_topics": ["成年工作", "婚姻生活", "晚年愿望"],
    "interview_goal": "唤起可感知、可复述的童年生活片段",
    "script_goal": "写成一章有生活质感的童年回忆"
  },
  "new_facts": [
    {
      "text": "小时候住在海边",
      "source_type": "interview_round",
      "source_id": "uuid",
      "claim_id": "uuid"
    }
  ],
  "tone": "克制、第一人称、自然口语",
  "missing_topics": ["具体年份", "地点细节", "关键人物"],
  "update_mode": "replace_current_chapter"
}
```

11 个系统章节各有独立的结构化画像。采访 AI 使用关键词、必问主题和越界主题生成下一问；剧本 AI 使用同一画像，只消费当前章节的记忆主张，并始终返回一个连续的 `chapter` 对象，不返回多份草稿或场景列表。

## 8. 数据模型

新增 `interview_turn_workflows`：

- `id`, `tenant_id`, `session_id`, `round_id`, `chapter_id`, `job_id`
- `idempotency_key`
- `status`: `queued | running | completed | failed`
- `asset_ids`, `source_claim_ids`, `script_scene_ids`
- `script_project_id`
- `next_question`, `next_question_intent`
- `missing_topics`, `script_brief`
- `error_code`
- `created_at`, `updated_at`, `completed_at`

唯一约束为租户加幂等键。所有关联对象读取时同时校验租户、人物和采访会话。

`script_scenes` 在当前语义中代表“章节稿件”。数据库通过 `(project_id, chapter_id)` 唯一约束保证一本人物剧本中每章只有一份当前稿件；`script_shots` 仍允许一章包含多个镜头建议。迁移 `20260907_0017` 会先合并历史重复章节的正文、画面建议、镜头与来源，再建立约束。

## 9. 一致性、幂等与错误处理

- Turn 先保存用户输入和工作流，再提交队列；同一幂等键返回原工作流。
- Worker 对 `completed` 工作流不重复执行。
- 记忆编译依赖来源唯一性，重复执行不会重复创建主张。
- 剧本按章节替换唯一当前稿件；后续采访会继续优化同一章。
- Provider 异常只向客户端暴露错误码，不返回英文异常文本。
- 工作流失败保留原始聊天与素材，可通过任务重试恢复。

## 10. 安全与隐私

- 素材默认 `private`，继续存放于私有 MinIO。
- 工作流和读取接口必须执行租户隔离、人物归属和会话归属校验。
- AI 输入只包含当前租户、人物、章节所需的最小上下文；采访记忆和冲突也按当前章节过滤。
- 剧本场景继续保存 `source_claim_ids`，禁止无来源事实进入草稿。
- API 密钥只通过环境变量注入，不写入文档、日志或前端。

## 11. 分阶段实施

### 阶段 A：可运行的实时闭环

- 新增工作流模型、迁移、DTO 和错误码。
- 新增 Turn、Workspace 和内部执行接口。
- 新增章节级增量剧本方法和锁定保护。
- 新增 11 章结构化提示画像与每章唯一稿件约束。
- Worker 支持 `interview.turn.process`。
- Mock 环境可内联执行，测试无需 Redis。
- 采访房间升级为桌面双栏和移动页签，加入四类素材上传。

### 阶段 B：独立部署入口

- 为 Interview Orchestrator、Evidence Service、Script Service 提供独立 FastAPI entrypoint。
- Core API 通过内部 HTTP 或队列调用，不再跨模块直接调用服务函数。
- 引入 transactional outbox，消除数据库提交与 Redis 入队之间的窗口。

### 阶段 C：数据独立化

- 按服务迁移表所有权和数据库账号。
- 用事件维护 Core API 的工作台读取模型。
- 增加死信队列、重放工具、链路追踪和容量隔离。

## 12. 本次涉及文件

- `apps/api/src/lifereel_api/modules/interview/*`
- `apps/api/src/lifereel_api/modules/script/service.py`
- `apps/api/src/lifereel_api/modules/jobs/*`
- `apps/api/src/lifereel_api/core/errors.py`
- `apps/api/alembic/versions/20260907_0016_live_interview_workflows.py`
- `apps/api/alembic/versions/20260907_0017_one_script_per_chapter.py`
- `apps/worker/src/lifereel_worker/main.py`
- `packages/contracts/src/index.ts`
- `apps/web/src/api/client.ts`
- `apps/web/src/api/errors.ts`
- `apps/web/src/pages/InterviewRoomPage.tsx`
- `apps/web/src/styles.css`
- API 与 Web 对应测试

## 13. 验收清单

- [x] 文字回答可在一次请求后保存、整理记忆、更新本章剧本并生成下一问题。
- [x] 图片、音频、视频和文档可从聊天输入区上传并显示。
- [x] 素材与人物、会话、租户严格隔离。
- [x] 工作流重复提交和重复执行保持幂等。
- [x] 同一章节始终只有一份随采访持续更新的当前稿。
- [x] 同一章节多轮对话后仍只有一份稿件，新事实会融入该稿件。
- [x] 采访 AI 的记忆、冲突、关键词与追问目标均限定在所选章节。
- [x] 工作流状态与失败错误码可在前端中文显示。
- [x] 桌面双栏无重叠，移动端采访/剧本可切换。
- [x] 旧的采访记录、素材页、剧本书籍页继续工作。
- [x] API、Web、Worker 测试和构建通过。
- [x] 在生产数据库副本验证迁移后再应用到当前环境。

## 14. 回滚方案

- 前端可回退到旧 InterviewRoom，而新接口不影响原回答接口。
- `0017` 在建约束前合并历史重复章节；执行生产迁移前保留数据库备份。
- Worker 不识别新任务时只会将任务标记失败，不会删除用户输入。
- 剧本更新失败时保留更新前章节，并允许重试工作流。
