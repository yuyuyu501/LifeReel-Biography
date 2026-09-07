# 贡献指南

## 分支与提交

- 功能分支：`feat/<scope>-<summary>`
- 修复分支：`fix/<scope>-<summary>`
- 提交信息建议遵循 Conventional Commits。

## 合并前检查

1. 不包含密钥、个人媒体或真实敏感数据。
2. 数据库变更附 Alembic migration。
3. API 变更更新 Schema、测试和共享契约。
4. 新 Provider 具备契约测试、错误归一化和费用解析。
5. `pytest`、前端测试、lint 和 build 全部通过。

## 数据与 AI 约束

- 任何事实性主张都必须保留来源引用。
- Prompt 必须版本化，结构化输出必须有 Schema。
- 不允许用“优化体验”为理由静默改写原始证据。
- 涉及肖像、声音、未成年人和第三方隐私的功能必须先完成授权设计。

