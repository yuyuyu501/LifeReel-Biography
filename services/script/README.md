# script

章节剧本、剧情、分镜、书稿影视化规划、版本和生成收据。剧本结果与结算事件同事务提交。

整本书改编按以下结构保存和传递中间产物：

```text
SourceSnapshot -> AdaptationBrief -> StoryBible -> SequencePlan -> SceneDraft -> ShotDraft
```

`ScriptProject` 保存改编简报、故事圣经和场次计划；场景和镜头保存稳定的
`sequence_key`、人物/地点引用及连续性元数据。规划条目和最终剧本都必须引用当前
书稿修订，来源不在输入范围内时生成失败，不会静默扩展来源。

- 入口：app.py；业务源码：src/lifereel_api。
- 镜像：本目录 Dockerfile，引用统一 backend-runtime。
- 本地/生产均由根 compose.production.yaml 编排，内部端口 8000。
- 健康接口：/health、/ready；内部能力使用签名 HTTP，只允许白名单调用方。
- 仍共享 PostgreSQL、ORM 和统一版本基础库；不代表独立数据库。
- 发布/回滚见 ../../docs/independent-services-release.md。
