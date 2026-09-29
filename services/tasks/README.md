# tasks

任务查询/重试和 Outbox 发布。重试分发给所属领域；不在本服务执行采访或媒体生成。

- 入口：app.py；业务源码：src/lifereel_api。
- 镜像：本目录 Dockerfile，引用统一 backend-runtime。
- 本地/生产均由根 compose.production.yaml 编排，内部端口 8000。
- 健康接口：/health、/ready；内部能力使用签名 HTTP，只允许白名单调用方。
- 仍共享 PostgreSQL、ORM 和统一版本基础库；不代表独立数据库。
- 发布/回滚见 ../../docs/independent-services-release.md。
