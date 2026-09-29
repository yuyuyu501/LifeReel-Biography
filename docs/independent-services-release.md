# 独立服务发布与恢复

## 配置与镜像

使用唯一的 `compose.production.yaml`。`LIFEREEL_RELEASE` 为提交 SHA；`LIFEREEL_ENV_FILE` 默认 `.env`。每个服务有独立 Dockerfile，共享依赖镜像为 `deploy/Dockerfile.backend`，通过 Compose `additional_contexts: service:migrate` 构建。需使用支持该功能的 Docker Compose V2 / BuildKit。

`services/` 保存领域源码，`workers/` 保存执行入口，`apps/api/` 保存基础库、迁移、ORM 注册及兼容测试入口。后端 wheel 仍包含共享领域模型，采用统一版本发布；数据库尚未按服务拆分。

## 发布顺序

1. 本地隔离测试通过后 commit/push，在服务器确认干净工作区并 fetch 同一提交。服务器访问 GitHub 失败时可上传已推送提交的 Git bundle，核验 SHA 后快进。
2. 检查活动 Job、语音通话和待投递事件，等待任务结束。备份数据库、`.env`、旧 Compose 配置，保留旧运行镜像。
3. 在维护窗口停止待替换的旧 API/Worker，保留数据库、Redis 和存储卷。执行 migrate，成功后启动所有新服务。迁移与旧业务写入不得并行。
4. 若服务器不能下载镜像，上传本地同提交构建的 `docker save` 镜像包，校验 SHA256 后 `docker load`。禁止直接修改服务器源码或用重启旧镜像代替更新。
5. 校验本地/GitHub/服务器提交、运行镜像 ID及容器代码、迁移版本、各服务和 Worker 健康。检查 `/ready`，不能仅凭 `/health` 判断整个系统就绪。

## 运行与故障语义

- `/health` 检查 Web → Gateway 存活；`/ready` 聚合业务服务数据库就绪；`/system-status` 保留 checks 字段并增加 services。
- 任务与 Outbox 同事务创建，Tasks 发布到 Inbox 后 Worker 才领取。投递重试不增加同一任务；Worker 在自身进程续租和执行。
- 账本按命令 ID 去重，剧本持久结果与结算命令共同提交。跨服务失败显式报错，不回落旧单体执行。
- 模型响应成功缓存可重放；收到不确定状态时先核对模型与账本记录，不强制重新发起收费调用。此机制不承诺所有外部供应商严格一次执行。
- PostgreSQL 及宿主机仍是共享故障域；本次不引入第二台服务器、独立数据库或异地高可用。
- ASR 临时转运对象使用私有 `service-transit/` 前缀并在请求结束删除。进程强制退出后可留下临时对象，OSS 应针对该前缀配置一天自动过期；不可对原始证据前缀应用该规则。

## 回滚

停止新业务服务，用保留的旧 Compose 与镜像恢复旧服务。0037–0039 为新增表，旧代码可以忽略；旧 API 的启动命令必须直接启动 uvicorn，跳过旧镜像中的 Alembic 自动升级（旧迁移目录不认识 0039）。不要为应用回滚直接删表。若需要恢复数据库，先停止所有写入，核验备份恢复点及之后新增数据的影响。备份和旧镜像保留至人工验收完成。

## 隔离测试

联调用同一生产 Compose、独立 project/env/卷。`deploy/tests/service_e2e.py` 只接受 localhost、tmp 下配置与 Mock 模型；使用 project `lifereel-servicesqa`。合成模型用于验证实际模型网关 HTTP、幂等和断线语义，不能把它当成真实模型质量验收。真实语音通话和支付仍由用户验收。
