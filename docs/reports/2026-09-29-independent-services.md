# 独立服务拆分：本地验收记录

## 实施结果

从 413131b 基线继续完成物理源码、运行进程与调用边界拆分。services 下包含 Gateway、Identity、Interview、Memory、Script、Media、Billing、Model Gateway、Tasks；workers 下包含 Interview、Media 两个直接执行入口。每个运行单元都有 Dockerfile，旧 HTTP Worker 和单体 API Dockerfile 已移除。

共享 backend runtime 用于保持 ORM/基础依赖版本一致；PostgreSQL 尚未按领域拆库。该结构支持单独启动、重启和后续横向扩展，但不等同于独立数据库或跨主机高可用。

## 本地检查

| 检查 | 结果 |
|---|---|
| 后端完整回归 | 690 passed / 21 skipped；跳过项未计为通过 |
| 架构、内部请求、CORS 与 Worker 最终定向回归 | 20 passed |
| 独立 PostgreSQL 迁移/并发上传补充 | 31 passed / 3 skipped |
| Web 单元与页面回归 | 24 文件 / 166 passed |
| Ruff | 所有业务服务、共享库及 Worker 通过 |
| Web lint | 0 error；2 条既有 Fast Refresh warning |
| 生产 Docker 镜像 | 全服务与 Web 构建通过；发布前仍核验最终镜像源码 |
| 空 PostgreSQL upgrade 与 alembic check | 升级至 20260929_0039，无新升级操作 |
| Nginx | HTTPS 缓存/鉴权头、Range、WSS、上传哈希、DNS 换址、65 秒静默响应及恢复通过 |

主回归的 21 跳过包含需专门数据库配置的项目；补充 PostgreSQL 运行覆盖迁移和并发事务，不能将两套结果相加视作全部未测项目清零。依赖废弃 API 的 warning 尚存在，没有将 warning 写成测试失败。

## Docker 业务与故障证据

使用 lifereel-servicesqa 独立 PostgreSQL/Redis/卷、合成账号与 Mock 模型，不连接付费模型、短信或支付。原有本地应用容器未停止。

1. Web 登录、网关分域路由、内部路径封锁通过。
2. 暂停 Tasks 发布后，新采访任务保留 queued；恢复发布后，采访 → 记忆 → 剧本 → 追问完成。
3. 相同 turn 幂等键不新增工作流、不重复消费。
4. Media Worker 生成合成视频，下载 SHA256 与记录一致，Range 206 内容正确。
5. Memory 停机时整体 ready 降级，但人物与钱包接口继续返回 200。
6. 停机期间任务失败，冻结释放、无消费；遵守冷却时间后通过 Tasks → Interview 重试，恢复完成且只消费一次。
7. 模型网关使用局域 HTTP 模拟模型：相同成功请求两次只实际调用一次；断线后再次请求被不确定状态阻止；成功/失败两份用量各投递到账本一次。

原始结果位于本地被忽略的 tmp/services-qa：api-final.log、architecture-release.log、postgres-tests.log、web-tests.log、nginx-results.json、e2e-results.json、model-gateway-results.json、alembic-check.log。失败的初轮日志保留用于追溯修正过程。

## 已修复的联调问题

- Compose 基础镜像依赖与小连接池配置不兼容。
- 前端内部路径未明确拦截、系统状态响应结构不兼容。
- 独立 FastAPI 入口未继承原有 CORS 配置，已补齐并逐服务验证。
- 生成媒体接口缺少 Range 与分段读取支持。
- 模型内部参数缺少严格验证；禁止通过内部视频请求覆盖 HTTP headers 等参数。
- 跨服务模型重放和不确定响应可能导致重复外部调用；增加持久调用收据与保守重试。
- media 目录的旧 Git ignore 规则会遗漏新服务源码；改为仅忽略根运行媒体目录。

## 边界与后续人工验收

真实实时语音、真实模型质量、支付及两类小程序真机未在本次常规发布回归调用。本轮没有声称覆盖长时间稳定性、异地恢复、多个物理节点或独立数据库。ASR 临时转运的异常退出保留对象需配置 service-transit 前缀一天过期，详情见独立服务部署说明。

此文档记录本地验收，不单凭提交 SHA 或本地通过宣布线上完成。正式发布需按 AGENTS.md 核验备份、活动任务、迁移、所有运行镜像与三方提交，生产结果以本次发布清单及最终反馈为准。
