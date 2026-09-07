# 功能完成矩阵

| 领域 | 已实现 | 外部配置 |
|---|---|---|
| 身份与家庭 | 本地账号、PBKDF2 密码、签名会话、租户成员、owner/editor/viewer | 正式管理员初始账号 |
| 采访 | 11 章节、暂停/结束、AI 语义缺口与章节内追问、失败重试 | 真实环境必须配置 LLM Provider |
| 证据 | 浏览器录音、文件上传、SHA-256 去重、本地/S3 私有存储 | MinIO/S3 凭据 |
| 逐字稿 | 原文、版本修订、片段模型、来源状态 | 可选 ASR Provider |
| 长期记忆 | AI Claim、实体关系、时间线、语义冲突、人物小传、覆盖率 | 真实环境必须配置 LLM Provider |
| 剧本 | AI 单章/多章、Scene、Shot、来源引用、持续版本更新 | 真实环境必须配置 LLM Provider |
| 生产 | 幂等 Job、Redis Worker、成本字段、Provider 注册表、本地 MP4 | 真实图像/视频/语音 API |
| 授权 | 采访、肖像、声音、制作、发布、监护人授权与撤回 | 可选电子签名服务 |
| 发布 | private/family/friends/public、访问令牌、撤回、最小公开响应 | HTTPS 与内容分发配置 |
| 运维 | Dockerfile、Compose、迁移、健康/系统状态、CI、PWA | Docker Engine、备份、监控告警 |
