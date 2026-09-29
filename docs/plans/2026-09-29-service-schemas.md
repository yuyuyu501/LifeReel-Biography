# 单个数据库、按服务分类 Schema

## 已确认范围

继续使用一个 PostgreSQL 数据库与现有数据库连接。采用 identity、interview、memory、script、media、billing、tasks、model_gateway 八个 Schema；不新增数据库、服务器或强制引入多套账号。Schema 是表的命名空间分类，本轮不宣称实现数据库权限隔离。

media 表记录 OSS object key、大小、哈希、归属、处理状态及相关业务数据；文件二进制仍由 OSS 存储，生成/转码可使用临时文件。迁移不改 storage_key、不复制或删除 OSS 对象。

## 执行顺序

1. 明确现有表归属，ORM 表及外键使用完整 Schema 名，保持原表名、列、索引和约束。
2. 新增 0040 迁移，用 ALTER TABLE SET SCHEMA 原地移动既有表，提供反向迁移；Alembic 版本表留在 public。适配 SQLite 测试映射和 PostgreSQL 多 Schema 一致性检查。
3. 在隔离 PostgreSQL 测试空库升级、带数据迁移、外键与删除语义、升级/回退、重复升级及 alembic check；执行后端回归和 Docker 业务联调，全部使用模拟模型。
4. 更新文档与运维 SQL。测试通过后提交推送 Git，再同步服务器；停写后备份数据库与环境并保留旧镜像，运行迁移和新服务。回滚必须先把表移回 public，再启动旧版本。
5. 核对线上表分布、数据摘要、迁移版本、容器镜像、HTTPS 健康和三方 Git 提交；保留发布证据。

## 验收标准

- 业务表仅位于所属 Schema，public 保留迁移版本表及扩展对象。
- 数据行、主外键、媒体对象键和账本金额不因迁移改变。
- 不依赖修改全局 search_path 来隐藏未适配的业务查询。
- 单一备份覆盖全部业务 Schema；数据库用户名、密码、端口和数据库名不变。
- 不调用付费 AI、短信、支付或视频服务作为发布回归。
