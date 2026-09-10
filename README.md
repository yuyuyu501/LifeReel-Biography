# 岁忆影传 · LifeReel Biography

岁忆影传是一套面向个人与家庭的 AI 口述史与自传短剧平台。系统通过语音采访持续积累可信的生命记忆，在保留原始证据、来源和授权边界的前提下，持续生成并优化单章或多章短视频剧本，再通过可替换的视频 API 生产短剧。

## 当前状态

仓库已经打通完整的可运行产品闭环：家庭账号与人物档案 → 真实浏览器录音/素材上传 → 逐字稿版本 → 长期记忆与自适应追问 → 单章/多章自传短视频剧本 → 授权确认 → 异步媒体生产 → 分受众发布与撤回。

系统默认提供 Mock Provider 与本地 FFmpeg，便于没有付费模型密钥时完成开发验收。API Docker 镜像内置 FFmpeg。OpenAI-compatible LLM/ASR、本地 faster-whisper 和通用异步图像、视频、语音 API 已提供适配层；真实模式下，追问、信息缺口、记忆、关系图谱、时间线、冲突、人物小传、章节正文和镜头都必须由对应 AI 完成，任何模型失败都会返回明确错误码并进入可重试状态，不会静默改用固定脚本。

## 架构原则

- **证据优先**：原始音频、逐字稿、照片和文档不可被生成文本覆盖。
- **回答即可收敛**：人工修订是加速器，不是系统继续工作的硬依赖。
- **计划实时重算**：采访计划是地图，不是给老人看的任务清单。
- **授权边界独立**：剧本随采访持续优化；肖像、制作、声音和发布仍由人物授权控制。
- **供应商无关**：ASR、采访 LLM、记忆 LLM、剧本 LLM、视觉、视频和语音均通过 Provider 接口接入，各用途模型独立配置。
- **隐私默认关闭**：未明确批准的内容默认为私密。

## 仓库结构

```text
apps/
  api/          FastAPI 模块化后端
  web/          React + TypeScript PWA
  worker/       异步任务 Worker
packages/
  contracts/    跨前后端共享的数据契约
docs/
  adr/          架构决策记录
  architecture.md
  roadmap.md
```

## 本地开发

### 1. 准备配置并启动基础设施

复制 `.env.example` 为 `.env`，至少替换认证密钥、初始管理员密码和 MinIO 密码。生产 Compose 会拒绝缺失这些值的配置。

```powershell
Copy-Item .env.example .env
docker compose up -d
```

服务地址：

- PostgreSQL: `localhost:5432`
- Redis: `localhost:6379`
- MinIO API: `http://localhost:9000`
- MinIO Console: `http://localhost:9001`

### 2. 启动 API

```powershell
cd apps/api
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item ../../.env.example .env
alembic upgrade head
uvicorn lifereel_api.main:app --reload
```

API 文档：`http://localhost:8000/docs`

### 3. 启动 Web

```powershell
pnpm install
pnpm --filter @lifereel/web dev
```

Web：`http://localhost:5173`

开发模式自动创建演示账号 `demo@lifereel.local`，密码 `LifeReelDemo2026!`。生产模式只创建 `.env` 中 `BOOTSTRAP_OWNER_EMAIL` / `BOOTSTRAP_OWNER_PASSWORD` 指定的首位管理员。

### 4. 启动 Worker（可选）

```powershell
cd apps/worker
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
lifereel-worker
```

### 5. 验证

```powershell
cd apps/api
pytest
cd ../..
pnpm --filter @lifereel/web test
pnpm --filter @lifereel/web build
```

已验证的基础能力：

- `GET /health`、`GET /ready`
- 人物创建、11 个生命章节、采访开始/回答/追问/结束
- 从采访回答幂等编译记忆，每条记忆保留 `source_round_id` 与原话
- 从记忆生成单章节或多章节剧本草稿，每个场景保留 `source_claim_ids`
- Scene → Shot 镜头拆解与剧本持续版本更新
- 采访聊天内录音与私密文件上传、SHA-256 去重、逐字稿版本修订
- 素材分类限额：图片 20 MB、文档 50 MB、音频 500 MB、视频 2 GB
- 人物/地点实体、时间线、冲突提示和章节覆盖率
- 按人物隔离的只读记忆档案、可追溯关系图谱与四类回忆文件浏览
- 肖像、制作、声音与发布授权记录
- 幂等生产任务、任务账本、Mock FFmpeg 竖屏 MP4 和受众发布撤回
- 统一 Provider 协议、OpenAI-compatible LLM/ASR 与通用异步媒体 API 接入点
- PBKDF2 密码、HttpOnly 会话 Cookie、租户成员角色和未成年人监护授权闸门
- 发布访问页 `/watch/{token}`、公开媒体流与撤回后即时失效
- 数据库、Redis、私有存储和 Provider 系统状态检查
- 有内容的剧本在制作与肖像授权齐全后可以进入视频生产
- API 测试、Ruff、TypeScript、ESLint、Vitest 和 Vite 生产构建

如果 Docker Desktop 尚未启动，可以不启动基础设施，临时使用 API 默认的 SQLite 开发库；正式联调 PostgreSQL、Redis 和 MinIO 前请启动 Docker Desktop。

## 安全注意事项

- 禁止提交真实 `.env`、API Key、访问令牌和任何未经授权的录音/照片/视频。
- 示例媒体只能使用合成素材或具有明确公开授权的素材。
- 声音克隆、肖像生成和公开发布必须分别获得明确授权。
- 浏览器身份使用 `HttpOnly` 会话 Cookie；生产 Nginx 只在服务端注入内部 `X-API-Key`，不会将密钥暴露给前端代码。
- `X-Tenant-ID` 仅供持有内部 API Key 的可信 Worker/网关调用；普通用户的租户和角色由登录会话决定。

## 文档

- [完整技术设计说明书](docs/project-specification.md)
- [总体架构](docs/architecture.md)
- [开发路线图](docs/roadmap.md)
- [API 概览](docs/api.md)
- [部署说明](docs/deployment.md)
- [功能完成矩阵](docs/feature-matrix.md)
- [贡献指南](CONTRIBUTING.md)
- [架构决策记录](docs/adr/)

## License

本项目源代码采用 [Apache License 2.0](LICENSE) 许可。

第三方依赖和素材仍适用其各自的许可证；用户上传的录音、照片、文档、视频及由此产生的内容不因本项目的代码许可证而改变其权利归属。
