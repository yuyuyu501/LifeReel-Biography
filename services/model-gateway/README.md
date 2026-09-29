# model-gateway

模型协议、LLM/ASR/图片/视频外部请求。成功 LLM 结果可重放，不确定结果拒绝自动重复请求。

- 入口：app.py；业务源码：src/lifereel_api。
- 镜像：本目录 Dockerfile，引用统一 backend-runtime。
- 本地/生产均由根 compose.production.yaml 编排，内部端口 8000。
- 健康接口：/health、/ready；内部能力使用签名 HTTP，只允许白名单调用方。
- 仍共享 PostgreSQL、ORM 和统一版本基础库；不代表独立数据库。
- 发布/回滚见 ../../docs/independent-services-release.md。
