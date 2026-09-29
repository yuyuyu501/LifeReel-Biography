# LifeReel API

共享后端基础库、ORM 注册、Alembic 迁移与兼容测试入口。领域源码已移至 `services/*/src`，运行入口为各服务的 `app.py`；生产不再启动这里的单体兼容 app。所有服务暂共用一个版本的 backend wheel 与 PostgreSQL，具体边界见根目录架构文档。功能包括：

- 本地账号、HttpOnly 会话、租户成员与角色权限
- 人物档案、未成年人和监护授权
- 11 个自传章节、规则/LLM 自适应追问
- 私密证据、OpenAI-compatible ASR、逐字稿版本
- 来源化长期记忆、实体、时间线、冲突与覆盖率
- 单章/多章短视频剧本、场景、镜头与持续更新
- PostgreSQL 任务/事件账本、独立 Worker、Mock FFmpeg 与模型网关
- 分受众发布、令牌观看、撤回与审计
- PostgreSQL/Alembic 与 SQLite 测试模式

运行方式见仓库根目录 README。
