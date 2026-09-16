import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import { Input } from "../components/ui/input";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronLeft,
  ChevronRight,
  Pencil,
  Plus,
  Search,
  Trash2,
} from "lucide-react";
import { type FormEvent, useState } from "react";
import { api, type Account } from "../api/client";
import { AccountDialog } from "../components/AccountDialog";
import { QueryState } from "../components/QueryState";

export function AccountsAdminPage() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [state, setState] = useState("all");
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<Account | "new" | null>(null);
  const [removing, setRemoving] = useState<Account | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const query = useQuery({
    queryKey: ["accounts", q, state, page],
    queryFn: () => api.accounts(q, state, page),
  });
  async function refresh() {
    await queryClient.invalidateQueries({ queryKey: ["accounts"] });
  }
  return (
    <div className="page accounts-page">
      <header className="page-header">
        <div>
          <span className="eyebrow">平台管理</span>
          <h1>账号管理</h1>
        </div>
        <Button
          variant="default"
          className="button primary"
          onClick={() => setEditing("new")}
        >
          <Plus size={18} />
          新增账号
        </Button>
      </header>
      <form
        className="accounts-toolbar"
        onSubmit={(event) => {
          event.preventDefault();
          setPage(1);
          setQ(search.trim());
        }}
      >
        <label>
          搜索账号
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="称呼、手机号或邮箱"
            maxLength={100}
          />
        </label>
        <label>
          账号状态
          <select
            value={state}
            onChange={(event) => {
              setState(event.target.value);
              setPage(1);
            }}
          >
            <option value="all">全部状态</option>
            <option value="active">正常</option>
            <option value="inactive">已停用</option>
          </select>
        </label>
        <Button
          variant="outline"
          size="icon"
          type="submit"
          className="icon-button"
          title="搜索"
          aria-label="搜索"
        >
          <Search size={20} />
        </Button>
      </form>
      <QueryState queries={[query]} />
      {query.data && (
        <>
          <div className="account-table-wrap">
            <table className="account-table">
              <thead>
                <tr>
                  <th>账号</th>
                  <th>手机号 / 邮箱</th>
                  <th>身份</th>
                  <th>状态</th>
                  <th>注册时间</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {query.data.items.map((user) => (
                  <tr key={user.id}>
                    <td>{user.display_name}</td>
                    <td>
                      {user.phone && <div>{user.phone}</div>}
                      {user.email && <div>{user.email}</div>}
                    </td>
                    <td>{user.is_admin ? "平台管理员" : "家庭账号"}</td>
                    <td>
                      <Badge
                        variant={user.is_active ? "secondary" : "destructive"}
                      >
                        {user.is_active ? "正常" : "已停用"}
                      </Badge>
                    </td>
                    <td>
                      {new Date(user.created_at).toLocaleDateString("zh-CN")}
                    </td>
                    <td>
                      <div className="account-actions">
                        <Button
                          variant="outline"
                          size="icon"
                          className="icon-button"
                          title="编辑账号"
                          aria-label={`编辑 ${user.display_name}`}
                          disabled={user.is_admin}
                          onClick={() => setEditing(user)}
                        >
                          <Pencil size={18} />
                        </Button>
                        <Button
                          variant="destructive"
                          size="icon"
                          className="icon-button danger"
                          title="删除账号"
                          aria-label={`删除 ${user.display_name}`}
                          disabled={user.is_admin}
                          onClick={() => {
                            setRemoving(user);
                            setError("");
                          }}
                        >
                          <Trash2 size={18} />
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!query.data.items.length && (
            <p className="account-empty">没有符合条件的账号。</p>
          )}
          <div className="account-pagination">
            <span>
              共 {query.data.total} 个账号 · 第 {page} 页
            </span>
            <div className="account-actions">
              <Button
                variant="outline"
                size="icon"
                className="icon-button"
                title="上一页"
                aria-label="上一页"
                disabled={page === 1 || query.isFetching}
                onClick={() => setPage((value) => value - 1)}
              >
                <ChevronLeft size={20} />
              </Button>
              <Button
                variant="outline"
                size="icon"
                className="icon-button"
                title="下一页"
                aria-label="下一页"
                disabled={
                  page * query.data.page_size >= query.data.total ||
                  query.isFetching
                }
                onClick={() => setPage((value) => value + 1)}
              >
                <ChevronRight size={20} />
              </Button>
            </div>
          </div>
        </>
      )}
      {editing && (
        <AccountEditor
          key={editing === "new" ? "new" : editing.id}
          user={editing}
          onClose={() => setEditing(null)}
          onSaved={refresh}
        />
      )}
      {removing && (
        <AccountDialog
          title="删除账号"
          onClose={() => setRemoving(null)}
          busy={busy}
        >
          <p>
            确认删除「{removing.display_name}
            」？该账号将无法登录，账单和档案记录保留。
          </p>
          {error && (
            <p className="field-error" role="alert">
              {error}
            </p>
          )}
          <div className="account-actions">
            <Button
              variant="outline"
              className="button secondary"
              disabled={busy}
              onClick={() => setRemoving(null)}
            >
              取消
            </Button>
            <Button
              variant="destructive"
              className="button danger"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                setError("");
                try {
                  await api.removeAccount(removing.id);
                  setRemoving(null);
                  if (query.data?.items.length === 1 && page > 1)
                    setPage((value) => value - 1);
                  await refresh();
                } catch (cause) {
                  setError(
                    cause instanceof Error
                      ? cause.message
                      : "删除失败，请稍后再试。",
                  );
                } finally {
                  setBusy(false);
                }
              }}
            >
              {busy ? "正在删除…" : "确认删除"}
            </Button>
          </div>
        </AccountDialog>
      )}
    </div>
  );
}

function AccountEditor({
  user,
  onClose,
  onSaved,
}: {
  user: Account | "new";
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const existing = user === "new" ? null : user;
  const [name, setName] = useState(existing?.display_name || "");
  const [email, setEmail] = useState(existing?.email || "");
  const [password, setPassword] = useState("");
  const [active, setActive] = useState(existing?.is_active ?? true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (existing)
        await api.updateAccount(existing.id, {
          display_name: name.trim(),
          ...(email ? { email } : {}),
          is_active: active,
          ...(password ? { password } : {}),
        });
      else
        await api.createAccount({ display_name: name.trim(), email, password });
      await onSaved();
      onClose();
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "保存失败，请稍后再试。",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <AccountDialog
      title={existing ? "编辑账号" : "新增账号"}
      onClose={onClose}
      busy={busy}
    >
      <form className="account-form" onSubmit={submit}>
        <label>
          称呼
          <Input
            value={name}
            onChange={(event) => setName(event.target.value)}
            required
            maxLength={80}
          />
        </label>
        <label>
          邮箱
          <Input
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value.trim())}
            required={!existing || !!existing.email}
            maxLength={255}
          />
        </label>
        {existing?.phone && (
          <label>
            已验证手机号
            <Input readOnly value={existing.phone} />
          </label>
        )}
        <label>
          {existing ? "重置密码（留空不修改）" : "初始密码"}
          <Input
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required={!existing}
            minLength={8}
            maxLength={200}
          />
        </label>
        {existing && (
          <label className="account-checkbox">
            <input
              type="checkbox"
              checked={active}
              onChange={(event) => setActive(event.target.checked)}
            />
            允许登录
          </label>
        )}
        {error && (
          <p className="field-error" role="alert">
            {error}
          </p>
        )}
        <div className="account-actions">
          <Button
            variant="outline"
            type="button"
            className="button secondary"
            disabled={busy}
            onClick={onClose}
          >
            取消
          </Button>
          <Button variant="default" className="button primary" disabled={busy}>
            {busy ? "正在保存…" : "保存账号"}
          </Button>
        </div>
      </form>
    </AccountDialog>
  );
}
