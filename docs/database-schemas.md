# 单库服务 Schema 与媒体存储

保留现有 lifereel 数据库、用户名、密码、端口和备份流程；49 张业务表按服务分类到九个 Schema。
public 保留 alembic_version 和数据库扩展。Schema 分类本身不构成权限隔离，本轮不增加多套数据库账号。

| Schema | 管理的数据表 |
|---|---|
| identity | account_audits, account_phones, audit_events, auth_rate_limits, consent_grants, mini_sessions, persons, platform_identities, sms_challenges, tenant_memberships, tenants, user_accounts |
| interview | chapters, interview_rounds, interview_sessions, interview_turn_workflows, interview_voice_calls |
| memory | memory_claims, memory_conflicts, memory_entities, timeline_anchors |
| script | script_generation_receipts, script_projects, script_scenes, script_shots |
| book | books, book_chapters, book_revisions |
| media | chapter_reference_packages, evidence_observations, evidence_uploads, generated_assets, production_runs, publications, restoration_photos, source_assets, transcript_segments, transcript_versions, transcripts |
| billing | billing_charges, billing_commands, provider_usage, recharge_orders, wallet_ledger, wallets |
| tasks | job_deliveries, jobs, outbox_events |
| model_gateway | model_invocations |

## 媒体文件

media 表包含素材标识、storage_key、MIME、大小、哈希、来源、归属、转录/观察文本和处理状态等元数据。生产配置 STORAGE_BACKEND=s3 时，文件由私有 OSS 保存；访问地址按需签名生成。生成和转码可能使用临时本地文件，测试可使用 local 存储。数据库不保存图片、音频、视频文件本体。

## 查询与维护

在 Navicat 中连接原数据库后刷新 Schema 列表，例如查询 media.source_assets、billing.wallets。SQL 应使用完整限定名；不通过设置全局 search_path 来隐式跨业务查表。ORM 已显式声明 Schema 与外键目标。

0040 使用 ALTER TABLE SET SCHEMA 原地移动表，保留行数据、索引和外键，不重建媒体对象、不改变 OSS key。跨 Schema 外键继续存在。Alembic 版本表仍为 public.alembic_version，统一执行升级和一致性检查。整库 pg_dump 包含全部业务 Schema；不要只备份 public。

## 发布和回退

迁移前停止所有业务写入并备份整库、环境、旧镜像。先执行新版本迁移，再启动新服务。若回退到 0039 的旧应用，必须先停止新服务，用新迁移工具执行 alembic downgrade 20260929_0039，把表移回 public，核对数据后再启动旧镜像；不能只切换旧镜像。回退使用 DROP SCHEMA RESTRICT，遇到用户新增对象会拒绝，不执行 CASCADE。

SQLite 单元测试通过 schema_translate_map 将命名空间映射到默认库；真实分类、外键与迁移必须由隔离 PostgreSQL 回归覆盖。

0043 新增独立 book Schema 及书籍、章节、历史版本三张表，不改动已有业务表数据。正文是文本，保存在数据库中；本次不向 OSS 写入书稿文件。回退 0043 时若已有书籍数据会拒绝删除，必须保留备份并单独处理，不能直接丢弃用户书稿。
