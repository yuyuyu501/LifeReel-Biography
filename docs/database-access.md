# PostgreSQL 管理连接

生产数据库为 PostgreSQL 16，数据库名和用户名均为 `lifereel`。
密码只保存在服务器私有 `.env`，不能写入仓库或发布报告。

## 配置

- `POSTGRES_PASSWORD`：数据库原始密码。已有数据库改密还须执行 `ALTER ROLE`；仅更改环境变量不会改变已初始化数据库的密码。
- `DATABASE_URL`：应用与 Alembic 共用的连接串，密码部分须经过 URL 编码；例如 `@` 编码为 `%40`，反斜杠编码为 `%5C`。Navicat 填原始密码，不填编码后的密码。
- `POSTGRES_BIND_HOST`：宿主机监听地址，默认 `127.0.0.1`；公网直连需在私有环境中显式设为 `0.0.0.0`。
- `POSTGRES_PORT`：宿主机映射端口，默认 `5432`；容器内部端口始终为 `5432`。

## 发布与验证

先确认无运行中任务，备份数据库、环境配置与运行镜像；本地检查通过并推送 Git 后，服务器再快进更新。
同步修改数据库角色密码、`POSTGRES_PASSWORD` 和编码后的 `DATABASE_URL`，再重建 PostgreSQL 与 API 容器。
保留原持久化卷，不使用 `down -v`，不重新初始化数据库。

公网放行应限制为管理电脑当前公网 IP，同时核验云安全组和 Docker 转发链；单独配置 UFW 不保证限制 Docker 发布端口。
`deploy/postgres-access-guard.sh` 和 `deploy/lifereel-postgres-access.service` 提供 Docker 转发链的白名单规则。
安装为 `/usr/local/sbin/lifereel-postgres-access` 和 `/etc/systemd/system/lifereel-postgres-access.service` 后，
在仅 root 可读的 `/etc/lifereel/postgres-access.conf` 中设置 `POSTGRES_ADMIN_CIDR`、`POSTGRES_EXTERNAL_INTERFACE` 和 `POSTGRES_PORT`，
然后执行 `systemctl enable --now lifereel-postgres-access.service`。规则在发布数据库端口前安装；Docker 重启后由服务重新应用。
更换管理网络时同步更新 CIDR 和云安全组，并重启此服务。
使用 Navicat 的 PostgreSQL 连接填写服务器地址、映射端口、`lifereel` 用户名、原始密码和 `lifereel` 初始数据库。
连接后验证数据库身份和事务回滚写入，并检查 API `/ready`、迁移版本及所有生产服务健康。

验证命令：`apps/api/.venv/Scripts/python.exe -m pytest deploy/tests/test_database_configuration.py -q`。
