# LLM 分任务等待与不确定结果（R01）

共享 OpenAI-compatible 聊天接口不再固定等待 60 秒。文字与视觉请求默认使用
connect/read/write/pool = **10 / 180 / 30 / 10 秒**；实际分镜曾在 108.55 秒完成，
180 秒为初始读取等待值，不代表模型一定能在此时间内完成。

真实 Web 回归另观察到章节评估约 126 秒收到上游 HTTP 524；本地 read=180 无法延长
供应商网关截止。已有一次 graph 耗时约 66 秒成功，只证明旧 60 秒限制已移除。

## 可选 SSE 流式接收

本地开发默认 `LLM_STREAM=false`；生产 Compose 默认开启 `LLM_STREAM=true`，也可在生产
`.env` 中显式覆盖。可设置 `INTERVIEW_LLM_STREAM=true` 仅对采访/章节评估开启，
也支持 `MEMORY_LLM_STREAM`、`SCRIPT_LLM_STREAM`、`VISION_LLM_STREAM`、
`VIDEO_PLAN_LLM_STREAM`。未设置的任务继承全局开关，显式 false 可覆盖全局 true。
这是后端接收供应商 SSE，不改变浏览器 API 的响应格式。

只使用标准 OpenAI `stream=true` 与 `stream_options={"include_usage":true}`；不发送
供应商私有推理参数。支持 SSE 注释、跨网络块/UTF-8 边界的 data 事件、delta.content
拼接和最后单独的 usage 事件。必须收到 finish_reason 和 `[DONE]` 才认定流完成。
流无最终 usage 时保留未知用量，不按零费用处理；已收到的 usage 原样审计，即使随后断流。
400 不支持 stream/stream_options、流中错误、缺失 DONE、无效 UTF-8/事件、超时均不自动
改用非流式或重发。仅原有明确 response_format 不支持的拒绝允许一次格式回退。

`LLM_STREAM_MAX_SECONDS=600`（有限正数，上限 3600）限制接收期间的累计时长，
并设 2000000 字节的解码后响应大小上限。每个网络块检查预算，注释/无换行内容也计入。
如果网络完全静默，退出由 read timeout 保证，最坏可在累计预算之后再等待一个 read
窗口；该预算不是强行取消云端任务的精确 deadline。HTTP connect/write/pool 仍各自有界。
Streaming 只有在首个事件及时到达且网关不缓冲时，才可能避开无响应体截止；
首 token 等待过长、网关硬总时限或不支持标准 SSE 时仍会失败。

HTTP 504/524 的安全元数据透传到 ApiError/采访工作流，页面明确显示“AI 服务商等待超时”，
提醒先核对状态和用量；不展示响应文本。旧失败记录没有元数据时维持原有通用提示。

## 配置

| HTTP 阶段 | 全局环境变量 | 默认秒数 |
| --- | --- | --- |
| 建立连接 | `LLM_CONNECT_TIMEOUT_SECONDS` | 10 |
| 等待下一批响应数据 | `LLM_READ_TIMEOUT_SECONDS` | 180 |
| 写入请求数据 | `LLM_WRITE_TIMEOUT_SECONDS` | 30 |
| 等待 HTTP 连接池 | `LLM_POOL_TIMEOUT_SECONDS` | 10 |

每个值须为有限正数，最多 3600 秒；0、负数、NaN、Infinity 不允许。
按任务覆盖采用 `{TASK}_LLM_{PHASE}_TIMEOUT_SECONDS`；未设置的阶段继承全局值。
不要把可选覆盖设为空字符串。模型选择与等待选择彼此独立，即便所有用途使用同一模型，
也不会混用等待配置。

| TASK 前缀 | usage context | 用途 |
| --- | --- | --- |
| `INTERVIEW` | `interview`、`question` | 采访、追问、章节评估 |
| `MEMORY` | `memory` | 记忆提取、图谱、小传；MemoryClient 也显式选择该任务 |
| `SCRIPT` | `script` | 剧本生成 |
| `VISION` | `evidence`、`vision` | 图片分析；analyze_images 始终选择该任务 |
| `VIDEO_PLAN` | `video`、`video_plan` | 视频分镜；沿用 script 模型配置 |

例如，`VIDEO_PLAN_LLM_READ_TIMEOUT_SECONDS=240` 只覆盖分镜读取等待；
`VISION_LLM_WRITE_TIMEOUT_SECONDS=60` 为包含图片的请求增加上传等待。
没有 usage context 或显式任务的通用客户端按 interview 处理；不要根据模型名猜任务。
ASR `/audio/transcriptions` 不属于本次 LLM 配置，保留现有 180 秒设置。

生产 Compose 的 API 从 `.env` 读取这些变量；开发 Compose 显式透传所有全局和任务值。
修改配置后需重建/重新创建 API（Settings 有缓存），单纯修改宿主机文件不会更新容器。
`.env.example` 仅有占位配置，不包含真实供应商密钥。

## Worker、租约与整轮时长

Worker 发出 execute 请求时，另一个线程每 20 秒续租；API 默认租约 120 秒。
因此 180 秒的单次 LLM 等待不会单独造成租约过期。续租请求自身等待 10 秒。
LLM 并发槽还可能等待 `RESOURCE_WAIT_SECONDS`（默认 120 秒），限流间隔默认 0.25 秒；
这些等待不属于 HTTP pool timeout，也不计入 provider 的网络请求时长。

采访一轮可能串行处理多个 claim，再生成图谱、小传、章节评估、剧本和追问，
还可能执行有限的格式纠正。`memory/recovery.py` 的 `MAX_RUNS=3` 和
`check_call_budget()` 限制恢复次数/已知费用，不限制整轮墙钟时长。
不能用一次 180 秒乘以固定的三个阶段来推算整轮上限；多个慢请求可累计超过旧 900 秒。

Worker 等待 execute 响应的配置为：

| 变量 | 默认秒数 | 允许范围 |
| --- | --- | --- |
| `WORKER_INTERVIEW_TIMEOUT_SECONDS` | 3600 | 60–14400，有限数 |
| `WORKER_VIDEO_TIMEOUT_SECONDS` | 7200 | 60–14400，有限数 |

两份 Compose 都透传 worker 配置。调高任务 read timeout 时，应同时核对预期串行调用数、
素材处理、格式纠正次数、并发等待和 worker 的等待窗口，不能只调 API。
Worker execute 是单个非流式响应，这个读取窗口限制 worker 等待结果的时间；
HTTP 分阶段等待不是精确的端到端总 deadline，也不会在到期时取消 API 中的执行。
前端/反向代理若先断开，仍应查询后台任务状态。

结果不确定（网络超时、HTTP 错误、无效返回）或返回 queued/running 时，worker
停止本次续租但**不调用 release 将租约缩短到 5 秒**，保留最近一次续租的到期时间。
有限等待后 worker 继续工作，不无限挂起；租约自然到期后可能再次投递，但 execute 的
job execution lock 与 workflow lock 阻止活跃任务重复执行，终态数据库记录阻止完成后重跑。
进程中断后的恢复还检查未结算 token hold，并复用 memory checkpoint；
不能把租约超时、HTTP 超时或锁释放当作供应商未消费的证明。
非 token 计费模式无法仅靠供应商回执冻结机制防止进程崩溃后的外部重复消费，
execution fencing 也不能取消已发出的云端请求；不承诺跨进程崩溃的 exactly-once。

## 响应与诊断

connect/read/write/pool timeout 均不自动重试。MemoryClient 保留原有有限 schema
纠正、ConnectError/429 策略，但不再自动重试 ConnectTimeout。
`chat_json` 只有在 HTTP 400 明确指明不支持 `response_format` / `json_object` 时，
才移除 response_format 再调用一次；普通 400（模型、参数、内容审核等）不回退，
fallback 自身失败也不继续尝试。格式纠正与兼容回退是额外真实调用，分别记录用量。

非 JSON HTTP 响应、非法 choices/message/content、JSON 内容不是对象等均明确报错。
错误响应先保留 HTTP 状态，HTML 502 不会被误记成单纯 JSON 解析失败。
沿用前端现有业务错误码；内部 `LLM_RESPONSE_*` / `LLM_OUTPUT_*` 标识响应问题。
日志只记录任务、错误类型/稳定原因码、HTTP 状态、经过格式校验的请求编号及超时阶段；
不输出 body、prompt、请求 URL、授权头或密钥。JSONDecodeError 不携带原始输出 doc。
请求编号优先读取 `x-request-id`、`request-id`、`x-ms-request-id`、`x-tt-logid`，
无头部编号时使用响应 `id`。计费去重优先保留 completion id，防止改变既有回执语义。

已取得实际 usage 时，即使响应不合法仍保留并结算实际费用；没有可信回执的超时和 5xx
保留 pending，不按零消费自动释放。受支持的明确 HTTP 拒绝可按既有策略释放冻结。
后续付费调用受 `BILLING_USAGE_PENDING` 阻断，必须用供应商回执或明确无消费证据对账。
诊断编号用于追踪，不是“未计费”的凭证。

usage 字典原样保存到审计记录，不过滤、强制转换或改写计数；音频 token、cache creation
等未定价类别和负值/非法类型仍由原有计价器拒绝并保留 pending。usage 不写入诊断日志。

## 文档与剧本输入预算

这三个预算统一由缓存的主 Settings 读取，处理函数不再逐次读取 `.env`。
`DOCUMENT_EXTRACT_MAX_CHARS` 默认 16000，最大 200000；
`DOCUMENT_EXTRACT_MAX_PAGES` 默认 200，最大 1000；
`SCRIPT_INPUT_MAX_CHARS` 默认 48000，最大 200000。均须为正整数。
预算与上传文件大小限制分别生效，不会为满足模型限制而静默截断原始资料。

## 本地验证边界

`tests/test_llm_timeouts.py` 用 mock transport/替换 httpx.post 检查配置、108.55 秒模拟完成、
全部超时阶段、HTTP 状态/编号、隐私过滤、JSON fallback 和 MemoryClient 继承链。
模拟耗时只证明不会再被本地固定 60 秒设置挡住，不代表真实供应商性能或成功率。
token metering、memory recovery、worker capacity、capacity dispatch、视频分镜修复
使用隔离数据库和 mock 验证；不调用付费 LLM、视频、SMS 或支付服务。

2026-09-21 R01 最终定向回归：176 项后端测试通过（包括 23 项 SSE/诊断专项），
前端错误提示和 InterviewRoomPage 28 项通过，TypeScript 编译、定向 Ruff/ESLint、
两份 Compose 配置校验通过。测试证据为 Git 忽略目录的 `tmp/r01-final-regression.xml`。

主验收流程反馈：非流式章节评估两次约 126 秒 HTTP 524，手动恢复复用了 memory
checkpoints；开启 SSE 后章节评估 41.53 秒、剧本 129.66 秒、追问 36.03 秒完成，
Web 已同步；视频分镜 35.66 秒通过。上述为主验收流程的真实付费验证结果，
本任务的故障与回归测试全部使用 mock；不据此宣称后续视频制作或新人物整轮已完成。
当前供应商部署须显式设置 `LLM_STREAM=true` 才会启用此次验证的流式路径。
默认 false 保留其他 OpenAI-compatible 供应商的兼容性，不能只部署新代码而漏掉该配置。
