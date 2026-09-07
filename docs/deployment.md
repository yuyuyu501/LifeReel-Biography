# 部署说明

## 单机 Docker Compose

1. 启动 Docker Desktop 或 Linux Docker Engine。
2. 在仓库根目录创建 `.env`，至少设置以下值。所有密码和密钥都应使用独立的强随机值：

```env
API_ACCESS_KEY=replace-with-a-long-random-secret
AUTH_TOKEN_SECRET=replace-with-a-different-long-random-secret
AUTH_COOKIE_SECURE=false
BOOTSTRAP_OWNER_EMAIL=owner@example.com
BOOTSTRAP_OWNER_PASSWORD=replace-with-a-strong-initial-password
BOOTSTRAP_OWNER_NAME=家庭管理员
MINIO_ROOT_PASSWORD=replace-with-a-long-random-secret
```

3. 启动：

```bash
docker compose up -d --build
```

API 容器启动时会依次执行 Alembic 迁移和幂等基础数据初始化，创建默认租户、首位 owner 账号及 11 个生命章节。

4. 检查：

```bash
docker compose ps
curl http://localhost:8000/health
curl -H "X-API-Key: replace-with-a-long-random-secret" http://localhost:8000/v1/chapters
```

Web 默认在 `http://localhost:5173`，API 在 `http://localhost:8000`。用户通过 Web 登录，身份保存在 `Secure`、`HttpOnly`、`SameSite=Lax` Cookie 中。发布成功后的家庭访问地址为 `http://localhost:5173/watch/{token}`。

本机使用 `http://localhost:5173` 验收时保留 `AUTH_COOKIE_SECURE=false`。对外上线必须先启用 HTTPS，再改为 `AUTH_COOKIE_SECURE=true`，否则会话 Cookie 可能经明文连接发送。还应使用外部密钥管理、定期备份、日志/告警和受控对象存储。`X-API-Key` 仅供 Nginx 和 Worker 内部调用，不应交给浏览器用户。

## 数据与备份

- PostgreSQL：人物、采访、记忆、剧本、授权、任务、发布与审计。
- `private-data`：本地存储模式下的原始证据与生成资产，不能公开挂载。
- Redis：异步任务队列，可重建但应开启持久化。
- MinIO：Compose 默认启用的 S3 兼容私有对象存储，Bucket 禁止匿名读取。若目标 S3 已配置 SSE/KMS，可设置 `S3_SERVER_SIDE_ENCRYPTION=AES256` 或服务端支持的算法；默认 MinIO 未配置 KMS，因此该项留空。

建议每日备份 PostgreSQL 和私有资产卷，并定期做恢复演练。撤回发布只停止访问，不自动删除原始证据；数据删除应走单独的合规流程。

素材上传默认按类型限制为图片 20 MB、文档 50 MB、音频 500 MB、视频 2 GB。可通过 `MAX_EVIDENCE_*_BYTES` 调整 API 限额；`NGINX_CLIENT_MAX_BODY_SIZE` 必须略高于其中最大值，以容纳 multipart 请求开销。

## Provider 配置

默认 `mock` Provider 可生成本地竖屏 MP4 验收样片。现有适配层支持 OpenAI-compatible LLM/ASR，以及具有提交、查询、取消和结果下载能力的通用异步媒体 API。可通过 `GET /v1/providers` 查看能力与配置状态，通过 `GET /system-status` 查看运行依赖。

接入真实 ASR、LLM、图像、视频和语音服务时，应记录模型、输入版本、幂等键、费用、输出哈希、Webhook 和错误信息，并在上线前验证供应商的数据保留、训练使用和跨境传输条款。

采访、记忆、剧本、视觉和 ASR 应使用独立模型配置。以下示例不会包含真实密钥：

```dotenv
LLM_PROVIDER=openai-compatible
ASR_PROVIDER=faster-whisper
OPENAI_COMPATIBLE_BASE_URL=https://provider.example/v1
OPENAI_COMPATIBLE_API_KEY=replace-me
INTERVIEW_LLM_MODEL=gpt-5.6-luna
MEMORY_LLM_MODEL=gpt-5.6-luna
SCRIPT_LLM_MODEL=gpt-5.6-luna
VISION_LLM_MODEL=gpt-5.6-luna
ASR_MODEL=small
WHISPER_MODEL_PATH=
WHISPER_DEVICE=cpu
WHISPER_COMPUTE_TYPE=int8
```

供应商兼容 `/chat/completions` 不代表兼容 `/audio/transcriptions`。当前推荐使用本地 `faster-whisper` 处理隐私敏感录音；`small` 模型适合 CPU 首次部署，GPU 环境可按硬件调整模型、设备和计算精度。模型会在第一次转写时下载并缓存。启用真实录音采访前必须分别验证聊天、图片输入和 Whisper。原始素材只在用户明确执行转写或分析时发送给外部 Provider；使用本地 Whisper 时音频不会发送给聊天供应商。剧本模型接收经过筛选的 Evidence Pack，而不是整个私有素材库。

## 上线检查

- 执行 `alembic upgrade head` 并确认数据库位于最新迁移。
- 登录首位管理员，立即验证角色与租户范围。
- 验证 MinIO/S3 Bucket 无匿名权限，并完成一次备份恢复演练。
- 完成采访、剧本持续更新、授权、生产、发布、公开观看和撤回的端到端演练。
- 为 `/health`、`/ready`、`/system-status`、Worker 队列积压和 Provider 失败率配置监控。
- 明确录音、肖像、声音克隆、未成年人信息和公开发布的隐私政策与删除流程。
