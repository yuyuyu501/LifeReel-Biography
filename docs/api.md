# API 概览

业务接口默认前缀为 `/v1`。开发环境可使用默认租户；生产浏览器用户先调用登录接口并通过 HttpOnly Cookie 携带身份，租户与 owner/editor/viewer 角色由服务端成员关系确定。

## 错误协议

所有 API 错误使用稳定错误码，不返回供界面直接展示的英文错误文本：

```json
{
  "error": {
    "code": "AUTH_INVALID_CREDENTIALS"
  }
}
```

前端在 `src/api/errors.ts` 集中维护错误码对应的中文提示。参数校验、未知路由、权限、业务状态、第三方服务与服务器异常均遵循同一结构；未知错误码统一显示中文兜底提示。可变信息只能通过可选的 `error.context` 结构化返回，不作为用户界面文案。

生产环境还要求服务端 `X-API-Key`。Web 容器通过同源 Nginx 代理注入该密钥，密钥不会进入浏览器 JavaScript。携带内部 API Key 的 Worker 或可信网关可显式传入 `X-Tenant-ID`。`/v1/public/{token}` 与其内容流是按发布令牌开放的例外，撤回后立即返回不可访问。

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/health` | 进程健康检查 |
| GET | `/ready` | 数据库就绪检查 |
| GET | `/system-status` | 数据库、Redis、存储和 Provider 状态 |
| POST | `/v1/auth/login` | 登录并设置 HttpOnly 会话 Cookie |
| POST | `/v1/auth/logout` | 注销并清除会话 Cookie |
| GET | `/v1/auth/me` | 当前用户、租户和角色 |
| GET/POST | `/v1/persons` | 查询或创建人物 |
| GET | `/v1/chapters` | 查询 11 个生命章节 |
| GET/POST | `/v1/interviews` | 查询或创建采访 |
| GET | `/v1/interviews/{id}/workspace` | 读取采访记录、素材、当前章节剧本和工作流状态 |
| POST | `/v1/interviews/{id}/turns` | 幂等提交文字或素材并触发实时成稿 |
| POST | `/v1/interviews/{id}/rounds/{round_id}/answer` | 保存采访回答 |
| GET | `/v1/interviews/{id}/next-question` | 获取下一条自适应追问 |
| POST | `/v1/evidence/assets` | 上传私密录音、照片、视频或文档 |
| POST | `/v1/evidence/assets/{id}/transcribe` | 使用已配置 ASR 生成来源化逐字稿 |
| POST | `/v1/memories/compile` | 将已回答轮次幂等编译为记忆 |
| GET | `/v1/memories` | 查询带来源的长期记忆 |
| GET | `/v1/memories/subjects/{subject_id}/graph` | 查询人物关系、事件与来源组成的记忆图谱 |
| GET | `/v1/memories/subjects/{id}/overview` | 覆盖率、实体、时间线与冲突概览 |
| POST | `/v1/scripts/generate` | 从记忆生成短视频剧本草稿 |
| GET | `/v1/scripts` | 查询剧本及场景 |
| GET/POST | `/v1/consents` | 查询或记录授权 |
| POST | `/v1/production/runs` | 幂等创建媒体生产任务 |
| GET | `/v1/jobs` | 查询统一任务账本 |
| POST | `/v1/publications` | 创建受众发布版本 |
| POST | `/v1/publications/{id}/withdraw` | 撤回发布 |
| GET | `/v1/public/{token}` | 最小化公开发布信息 |
| GET | `/v1/public/{token}/content` | 在发布有效期内读取媒体内容 |
| GET | `/v1/providers` | Provider 能力和配置状态 |
| POST | `/v1/internal/interview-turns/{id}/execute` | Worker 执行采访 Turn（内部接口） |

完整、可交互的 OpenAPI 文档在 API 启动后访问 `http://localhost:8000/docs`。
