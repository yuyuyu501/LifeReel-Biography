# 单库多 Schema：本地验收记录

## 实施范围

数据库保持一个，连接账号、端口与 OSS 配置不变。46 张业务表按服务分类：identity 12、interview 5、memory 4、script 4、media 11、billing 6、tasks 3、model_gateway 1。public 保留 Alembic 版本表和扩展；没有新增数据库或强制增加服务数据库账号。

模型声明完整 Schema 和外键引用，0040 迁移通过 ALTER TABLE SET SCHEMA 移动原表。索引命名约定保持旧名称；不复制行数据、不修改 OSS key、不搬动媒体文件。Alembic 检查涵盖全部业务 Schema，并忽略无关用户/扩展表。

## 本地检查结果

| 检查 | 结果 |
|---|---|
| 完整后端回归（包含 PostgreSQL 专项） | 717 passed / 3 skipped / 0 failed |
| Schema 专项（包含在完整回归中） | 4 passed |
| 生产 Compose 镜像构建 | 13 个镜像全部构建完成 |
| Docker 已有数据迁移 | 46 张表、191 条合成记录，全部数据摘要相同 |
| Docker 业务与故障联调 | 11 个检查通过 |
| 模型网关模拟 HTTP | 成功重放、不确定状态阻止重发、用量仅投递一次均通过 |
| Docker Alembic check | No new upgrade operations detected |
| Ruff | 共享库、服务、迁移、Worker、测试与本次联调脚本通过 |

完整回归的三个跳过是 SQLite 参数分支中仅适用于 PostgreSQL 的约束顺序/外层事务检查；同轮已启用并执行 PostgreSQL 对应分支。没有把跳过算作通过，也没有将专项计数重复累加。迁移专项存在依赖 warning，未将 warning 当作功能失败。

## 迁移保护验证

1. 空 PostgreSQL 从初始迁移升级到 0040，模型一致性检查通过。
2. 八个业务域均写入合成记录，逐表比较内容摘要、行数、表 OID、索引 OID 与约束定义属性；升级前后相同。
3. 目标 Schema 存在同名表时，迁移整体回滚，不留下部分移动状态。
4. 跨 Schema 外键仍拒绝悬空引用；删除章节后的 SET NULL 行为、钱包金额和媒体 key 保持正确。
5. 回退遇到不属于迁移的新增对象时拒绝级联删除，并完整回滚该回退操作。
6. 正常回退到 0039 后，表重新位于 public，旧布局读写及再次升级通过。
7. SQLite 测试虽将 Schema 映射到同一默认库，仍保留跨业务外键，避免因 SQLite 默认省略跨 Schema 外键而降低回归强度。

## 业务验证与修复

实际运行独立服务与 Worker，使用隔离数据库和模拟模型，验证登录、内部接口封锁、采访至记忆/剧本、钱包幂等、视频哈希与 Range 下载、停机降级、冻结释放和恢复后只消费一次。首次联调发现测试钱包初始化 SQL 仍使用旧的无 Schema 表名，已改为 billing.wallets 和 identity.persons，复验通过。

模型网关测试使用本地模拟 HTTP 服务，不调用付费 AI。没有在本轮调用真实语音、短信、支付或云视频，也没有把本轮回归记作长期压力或灾备测试。

## 发布要求

本记录证明本地验收，不能代替生产部署证据。发布需先提交推送，再同步服务器，停写后备份整库、环境与旧镜像；迁移前后比较全部业务表摘要，再启动新服务。回退到旧应用前必须将表迁回 public。生产的提交、备份、数据核验、迁移版本与镜像结果以本次运行报告为准。

原始证据位于被忽略的 tmp/schema-qa：schema-tests.log、api-full.log、qa-before.json、qa-after.json、e2e-results.json、model-gateway-results.json。表归属及 Navicat 查询方法见 [数据库分类说明](../database-schemas.md)。
