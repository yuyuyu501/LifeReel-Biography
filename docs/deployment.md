# 部署说明

## 更新顺序与源码一致性

1. 只在本地工作区修改源代码；先检查 Git 状态，保留已有改动。
2. 本地完成相关单元测试、完整构建和桌面/手机界面验证。AI 回归默认使用模拟响应，避免发布检查产生真实费用。
3. 测试通过后提交并推送 GitHub，记录本次提交 SHA。
4. 服务器确认工作区干净，再 `git fetch origin main` 并 `git merge --ff-only <本次提交 SHA>`。发现未提交改动时先核对并备份，不直接覆盖。
5. 从该提交构建和部署，检查运行任务、服务健康及静态资源版本，最后核对本地、GitHub、服务器的提交 SHA 一致。

发布完成必须同时核验源码、运行中的容器和数据库迁移。仅三方 Git 提交一致不代表线上更新已生效；有后端变更时，必须重新构建对应镜像、执行迁移并更新相关服务，核对容器中的代码与已推送提交一致。仅重启旧镜像不能完成代码发布。发布结果应记录提交 SHA、服务启动时间、健康状态、迁移版本和备份位置。

服务器不单独修改业务源码；需要修复时回到本地重复以上流程。`.env`、密钥、数据库、OSS 文件和其他运行数据不参与 Git 同步。

若服务器无法直连 GitHub，可从已推送的同一提交生成 Git bundle，通过 SSH 上传后由服务器 `git fetch <bundle>`，再快进到相同 SHA。该方式保留原始 Git 历史，不另写或覆盖一份服务器源码。发布前保留上一版镜像用于回滚；依赖未变化时可复用现有镜像依赖层，但业务源码必须来自已验证的提交。

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

### 阿里云 OSS（S3 兼容接口）

本地验证 OSS 时，在根目录 `.env` 中设置以下配置；不要把真实密钥写入 `.env.example` 或提交到 Git：

```dotenv
STORAGE_BACKEND=s3
S3_ENDPOINT_URL=https://oss-cn-shenzhen.aliyuncs.com
S3_REGION_NAME=oss-cn-shenzhen
S3_ADDRESSING_STYLE=virtual
S3_ACCESS_KEY=你的AccessKeyId
S3_SECRET_KEY=你的AccessKeySecret
S3_BUCKET=bianji123
```

Compose 会把这些值传给 API。OSS Bucket 必须属于该 AccessKey，且授予应用读写对象权限；推荐只授予指定 Bucket 的最小权限。个人 AccessKey Secret 不应在聊天、代码或日志中继续传播，若已公开，应立即在阿里云控制台轮换。

项目在 Bucket 中使用独立根目录 `LifeReel-Biography/`，不会使用 Bucket 根目录或其它项目目录。

### 浏览器直传 OSS

在上述 OSS 配置基础上增加 `OSS_DIRECT_UPLOAD_ENABLED=true`，执行迁移并重建 Web/API：

```bash
docker compose up -d --build api web
docker compose exec api python -m lifereel_api.modules.evidence.oss_admin configure-cors --origin http://localhost:5173 --origin http://127.0.0.1:5173
docker compose exec api python -m lifereel_api.modules.evidence.oss_admin configure-lifecycle
```

生产环境的 `--origin` 应使用真实 HTTPS 域名，不要包含路径或通配符。配置命令保留 Bucket 既有规则；如果之前已有 `AllowedOrigins=*`，需要先核对其他应用用途，再手动收紧。CORS 不是权限控制：Bucket 和对象必须保持私有。运行时应用只需指定 Bucket 范围的读、写、删除权限；CORS 和生命周期管理权限只在上述初始化命令执行时需要。

上传链路：

1. 浏览器查询 `GET /v1/evidence/upload-settings`。关闭直传时保留原中转接口；开启后发生错误不会悄悄改走中转。
2. `POST /v1/evidence/assets/direct-upload` 校验家庭、人物、采访、MIME 和类型限额，为随机临时对象签发一小时 OSS POST Policy。许可限制确切路径、文件大小、Content-Type，并禁止覆盖。浏览器只获得 AccessKey ID 和限权签名，不获得 AccessKey Secret。
3. 浏览器用 FormData 直接 POST 到 OSS，文件字段最后发送，不携带应用 Cookie 或 API Key。
4. `POST /v1/evidence/assets/complete-direct-upload` 只接收上传 ID。后端锁定上传记录并再次鉴权，检查实际大小、类型头，以 1 MiB 块读取 OSS 内容计算真实 SHA-256。通过后在 OSS 内部复制到正式路径，再提交素材记录。重复确认返回同一素材；同一人物按真实哈希去重，不跨人物共享记录。
5. 成功后删除临时对象。放弃、失败或清理失败的对象由 `LifeReel-Biography/uploads/staging/` 专用一天过期规则回收，正式素材不在此目录。该前缀必须专用于本功能，不得放入其他业务数据。过期上传数据库记录暂保留用于追溯。

每个家庭最多保留 10 个未过期且未完成的上传许可；这不是完整的上线防刷方案，仍需配合注册保护、容量配额和全局限流。现有图片 20 MiB、文档 50 MiB、音频 500 MiB、视频 2 GiB 限额保持不变。当前是单次表单直传，不支持断点续传；慢速上传超过一小时需重新上传。

上传文件不再经过 Web/API 转发给 OSS，但完成校验仍会从 OSS 下载一遍文件，分析/转写也会读取素材；预览和发布播放暂时仍经 API 中转。深圳同地域服务器部署时应规划服务端内网读写，后续再将预览改为鉴权签名下载；不能把本次改动理解为媒体流量已完全绕过服务器。超大文件确认受网速及当前 Nginx 900 秒超时影响，上线前需验证实际最大文件和并发负载，必要时把完整校验迁移至异步任务。

将存储从 MinIO 切换为 OSS 不会迁移旧文件；正式切换前应迁移原始素材和生成资产并校验哈希。迁移完成前旧数据的预览可能不可用。

可选的真实云端连通测试（会创建独立合成人物和少量测试对象，并在结束时删除，仅用于上传验证，不调用 AI）：

```bash
docker compose exec api python tests/oss_live_check.py
```

该测试覆盖四类文件、POST Policy 大小约束、禁止覆盖、匿名拒绝、内容哈希、Range 读取及重复确认。测试文件包含合成格式头，不代替真实音视频解码测试。若发生中断，先核对测试人物 ID，再用 `--cleanup-person <UUID>` 清理本次测试数据，不清空 Bucket。

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

## 照片文字标注

设置 `PHOTO_REDRAW_PROVIDER=siliconflow` 与 `SILICONFLOW_API_KEY` 后，在“记忆档案 / 回忆文件”
选择原始照片并点击“添加标注”。默认关闭；`mock` 仅允许开发和隔离测试环境使用。
当前固定使用 `Qwen/Qwen-Image-Edit-2509`、20 步和 `ai-label-v2` 提示词，
要求保留原图，仅在右下角添加“本图片由ai生成”。密钥只存环境，不返回浏览器、不记录到任务中。

上传不会自动触发付费调用。用户点击添加标注后创建数据库任务，由现有视频
任务通道串行调度；HTTP 返回后可以离开页面，回来仍能查询结果。重复点击同一原图和
提示词版本复用任务，原图不会被覆盖。失败最多允许三次实际执行，服务商拒绝的请求
不提供原样重试；超时或进程中断后的未知结果不自动重发，手动重试可能再次产生供应商费用。
当前图片编辑费用由运营方承担，不扣用户钱包，未纳入视频计费。

只接受已授权且不超过 10 MiB 的 PNG/JPEG/WebP 原图；调用前校验来源、哈希、文件类型和
人物归属。结果写入私有存储，保留来源、输出哈希、模型、提示词版本及服务商追踪 ID。
衍生图不作为采访事实证据；文字标注不构成视频平台的真人肖像授权，视频提交仍需正常审核。
开启 `VIDEO_REFERENCE_STYLE=color_redraw` 后，生成本章影像会先准备剧本“形象”栏中的
图片，复用同版本图片编辑任务，再将标注图与所选音频提交给视频平台。编辑失败不会回退原图。
`color_redraw` 是兼容已有配置的历史名称；实际行为以 `reference_prompt_version` 为准。
新提示词不会复用旧转描图；前端发现提示词版本变化时新建影像任务，保留历史任务与素材。
形象栏支持图片与 MP3/WAV 音频；音频需要搭配图片，单段 2–15 秒，总长不超过 15 秒。
本章素材选择需要迁移 `20260917_0028`。发布需重建 API 与 Web，并校验运行配置。

## 上线检查

- 执行 `alembic upgrade head` 并确认数据库位于最新迁移。
- 登录首位管理员，立即验证角色与租户范围。
- 验证 MinIO/S3 Bucket 无匿名权限，并完成一次备份恢复演练。
- 完成采访、剧本持续更新、授权、生产、发布、公开观看和撤回的端到端演练。
- 为 `/health`、`/ready`、`/system-status`、Worker 队列积压和 Provider 失败率配置监控。
- 明确录音、肖像、声音克隆、未成年人信息和公开发布的隐私政策与删除流程。
