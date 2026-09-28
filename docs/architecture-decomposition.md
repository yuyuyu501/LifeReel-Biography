# 架构拆分基线

本项目采用三个阶段从模块化单体演进为可拆分的事件驱动服务体系。当前目标不是复制多份业务代码，而是先固定领域边界、接口契约、事件格式和运行角色，再按资源和流量逐步独立部署。

## 阶段一：领域边界与契约

Web 和微信/抖音小程序是两个客户端板块。微信与抖音保留各自的登录、录音、上传和支付适配层，共用前端契约和后端业务 API。

API 内部的领域边界如下：

| 边界 | 当前模块 | 后续独立服务 |
|---|---|---|
| identity | auth、identity、governance | 账号服务 |
| model_gateway | providers、orchestration | 模型管理与 AI 网关 |
| interview | interview | 采访服务 |
| memory | memory | 记忆服务 |
| script | script | 剧本服务 |
| media | evidence、restoration、production、publication | 图片与影像服务 |
| billing | billing | 钱包与计费服务 |
| worker | jobs | 异步任务执行平台 |
| storage | evidence.storage | OSS/S3 适配服务 |

`apps/api/src/lifereel_api/architecture` 保存服务目录和事件信封。`packages/contracts` 保存客户端可共享的数据契约。服务之间不应直接依赖其他服务的 ORM 私有实现。

## 阶段二：运行单元拆分

生产 Compose 将 Worker 分为两个运行角色：`worker-interview` 只领取采访任务，`worker-media` 只领取视频、图片和清理任务。两者共用任务账本和执行协议，但可以独立设置 CPU、内存、并发和超时。

API 网关由 Web Nginx 承担。上游通过 `API_UPSTREAM` 配置，默认仍为 `api:8000`，以后可切换到独立 Gateway 或 API 副本，不需要重新编译前端。

模型管理边界由 Provider Registry、任务模型配置、调用超时、流式策略和用量记录组成。模型管理不拥有记忆或剧本业务规则；记忆和剧本通过 AI 网关调用模型。

## 阶段三：事件驱动和独立数据边界

任务创建与业务事务同时写入 `outbox_events`。事件使用版本化 `EventEnvelope`，包含租户、聚合、幂等键、来源和业务负载。当前 Worker 仍从数据库任务账本领取任务，保证单机部署稳定；后续可增加 Outbox Publisher，将同一事件发布到 Redis Streams、NATS 或 Kafka，而不改动业务模块。

PostgreSQL 当前仍是一个实例，但服务边界按表和数据访问层隔离。拆成真正独立服务时，优先迁移钱包、媒体生产和记忆数据，再处理账号与采访的共享查询。Redis 负责队列和短期状态，OSS 负责私有媒体；它们不是业务微服务。

## 本地验证

```powershell
docker compose -f compose.production.yaml config --quiet
docker compose -f compose.production.yaml up -d --build
docker compose -f compose.production.yaml ps
```

验证重点是两个 Worker 都 healthy、采访任务只由 `worker-interview` 领取、媒体任务只由 `worker-media` 领取、数据库迁移到最新版本，以及 Web 通过 Nginx 上游访问 API。
