import { Input } from "../components/ui/input";
import { Button } from "../components/ui/button";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type AuthUser, type SmsVerification } from "../api/client";
import { QueryState } from "../components/QueryState";
import { SmsCodeField } from "../components/SmsCodeField";
import { AccountDialog } from "../components/AccountDialog";
import { LogOut } from "lucide-react";

export function AccountPage() {
  const query = useQuery({ queryKey: ["auth-me"], queryFn: api.me });
  if (!query.data) return <QueryState queries={[query]} />;
  return <AccountSettings key={query.data.id} user={query.data} />;
}

function AccountSettings({ user }: { user: AuthUser }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [name, setName] = useState(user.display_name);
  const [currentPassword, setCurrentPassword] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [phone, setPhone] = useState("");
  const [phonePassword, setPhonePassword] = useState("");
  const [verification, setVerification] = useState<SmsVerification | null>(
    null,
  );
  const [busy, setBusy] = useState("");
  const [feedback, setFeedback] = useState({
    section: "",
    error: "",
    success: "",
  });
  const [deleting, setDeleting] = useState(false);
  const [deletePassword, setDeletePassword] = useState("");
  const [deleteCode, setDeleteCode] = useState<SmsVerification | null>(null);

  function relogin(message: string) {
    queryClient.clear();
    navigate("/login", { replace: true, state: { message } });
  }
  async function submit(
    event: FormEvent,
    section: string,
    action: () => Promise<void>,
  ) {
    event.preventDefault();
    setBusy(section);
    setFeedback({ section, error: "", success: "" });
    try {
      await action();
    } catch (cause) {
      setFeedback({
        section,
        error:
          cause instanceof Error ? cause.message : "操作失败，请稍后再试。",
        success: "",
      });
    } finally {
      setBusy("");
    }
  }
  function notice(section: string) {
    return (
      feedback.section === section && (
        <>
          {feedback.error && (
            <p className="field-error" role="alert">
              {feedback.error}
            </p>
          )}
          {feedback.success && (
            <p className="field-success" role="status">
              {feedback.success}
            </p>
          )}
        </>
      )
    );
  }
  return (
    <div className="page account-page">
      <header className="page-header">
        <div>
          <span className="eyebrow">个人资料</span>
          <h1>账号设置</h1>
        </div>
        {user.is_admin && (
          <Button asChild variant="outline" className="button secondary">
            <Link to="/admin/accounts">账号管理</Link>
          </Button>
        )}
      </header>
      <section className="account-section">
        <div>
          <h2>基本资料</h2>
          <p>{user.is_admin ? "平台管理员" : "家庭账号"}</p>
        </div>
        <form
          className="account-form"
          onSubmit={(event) =>
            submit(event, "profile", async () => {
              const updated = await api.updateProfile(name.trim());
              queryClient.setQueryData(["auth-me"], updated);
              setFeedback({
                section: "profile",
                error: "",
                success: "资料已保存。",
              });
            })
          }
        >
          <label>
            称呼
            <Input
              value={name}
              onChange={(event) => setName(event.target.value)}
              required
              maxLength={80}
            />
          </label>
          {user.email && (
            <label>
              邮箱
              <Input value={user.email} readOnly />
            </label>
          )}
          <label>
            手机号
            <Input value={user.phone || "尚未绑定"} readOnly />
          </label>
          {notice("profile")}
          <Button
            variant="default"
            className="button primary"
            disabled={!!busy}
          >
            {busy === "profile" ? "正在保存…" : "保存资料"}
          </Button>
        </form>
      </section>
      <section className="account-section">
        <div>
          <h2>修改密码</h2>
          <p>修改后需重新登录。</p>
        </div>
        <form
          className="account-form"
          onSubmit={(event) =>
            submit(event, "password", async () => {
              if (password !== confirm)
                throw new Error("两次输入的密码不一致。");
              await api.changePassword(currentPassword, password);
              relogin("密码已更新，请重新登录。");
            })
          }
        >
          <label>
            当前密码
            <Input
              type="password"
              autoComplete="current-password"
              value={currentPassword}
              onChange={(event) => setCurrentPassword(event.target.value)}
              required
              minLength={8}
              maxLength={200}
            />
          </label>
          <label>
            新密码
            <Input
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
              minLength={8}
              maxLength={200}
            />
          </label>
          <label>
            确认新密码
            <Input
              type="password"
              autoComplete="new-password"
              value={confirm}
              onChange={(event) => setConfirm(event.target.value)}
              required
              minLength={8}
              maxLength={200}
            />
          </label>
          {notice("password")}
          <Button
            variant="outline"
            className="button secondary"
            disabled={!!busy}
          >
            {busy === "password" ? "正在修改…" : "更新密码"}
          </Button>
        </form>
      </section>
      <section className="account-section">
        <div>
          <h2>{user.phone ? "更换手机号" : "绑定手机号"}</h2>
          <p>验证新手机号后生效，需重新登录。</p>
        </div>
        <form
          className="account-form"
          onSubmit={(event) =>
            submit(event, "phone", async () => {
              if (!verification?.challenge_id || verification.phone !== phone)
                throw new Error("请获取新手机号的验证码。");
              await api.changePhone({
                ...verification,
                current_password: phonePassword,
              });
              relogin("手机号已更新，请重新登录。");
            })
          }
        >
          <label>
            新手机号
            <Input
              type="tel"
              autoComplete="tel-national"
              value={phone}
              onChange={(event) => setPhone(event.target.value.trim())}
              required
              pattern="1[3-9][0-9]{9}"
              maxLength={11}
            />
          </label>
          <SmsCodeField
            key={phone}
            phone={phone}
            purpose="bind_phone"
            onChange={setVerification}
            disabled={!!busy}
          />
          <label>
            当前密码
            <Input
              type="password"
              autoComplete="current-password"
              value={phonePassword}
              onChange={(event) => setPhonePassword(event.target.value)}
              required
              minLength={8}
              maxLength={200}
            />
          </label>
          {notice("phone")}
          <Button
            variant="outline"
            className="button secondary"
            disabled={!!busy}
          >
            {busy === "phone" ? "正在更新…" : "确认绑定"}
          </Button>
        </form>
      </section>
      {!user.is_admin && (
        <section className="account-section account-danger">
          <div>
            <h2>注销账号</h2>
            <p>
              注销后无法登录，手机号不能重复注册。账单及档案记录保留；有充值余额、欠款或未完成任务时需先处理。
            </p>
          </div>
          <Button
            variant="destructive"
            className="button danger"
            onClick={() => {
              setDeleting(true);
              setDeletePassword("");
              setDeleteCode(null);
              setFeedback({ section: "", error: "", success: "" });
            }}
            disabled={!!busy}
          >
            注销账号
          </Button>
        </section>
      )}
      <section className="account-section">
        <div>
          <h2>登录状态</h2>
          {notice("logout")}
        </div>
        <Button
          variant="outline"
          type="button"
          className="button secondary"
          disabled={!!busy}
          onClick={async () => {
            setBusy("logout");
            try {
              await api.logout();
              relogin("已退出登录。");
            } catch (cause) {
              setFeedback({
                section: "logout",
                success: "",
                error:
                  cause instanceof Error
                    ? cause.message
                    : "退出失败，请稍后再试。",
              });
            } finally {
              setBusy("");
            }
          }}
        >
          <LogOut size={18} />
          退出登录
        </Button>
      </section>
      {deleting && (
        <AccountDialog
          title="确认注销账号"
          onClose={() => setDeleting(false)}
          busy={!!busy}
        >
          <form
            className="account-form"
            onSubmit={(event) =>
              submit(event, "delete", async () => {
                if (user.phone && !deleteCode?.challenge_id)
                  throw new Error("请先获取短信验证码。");
                await api.deleteAccount({
                  current_password: deletePassword,
                  ...(deleteCode
                    ? {
                        challenge_id: deleteCode.challenge_id,
                        code: deleteCode.code,
                      }
                    : {}),
                });
                relogin("账号已注销。");
              })
            }
          >
            <p>注销后无法恢复登录，请确认是否继续。</p>
            <label>
              当前密码
              <Input
                type="password"
                autoComplete="current-password"
                value={deletePassword}
                onChange={(event) => setDeletePassword(event.target.value)}
                required
                minLength={8}
                maxLength={200}
              />
            </label>
            {user.phone && (
              <>
                <p>验证手机：{user.phone}</p>
                <SmsCodeField
                  phone={user.phone}
                  purpose="delete_account"
                  onChange={setDeleteCode}
                  disabled={!!busy}
                />
              </>
            )}
            {notice("delete")}
            <div className="account-actions">
              <Button
                variant="outline"
                type="button"
                className="button secondary"
                disabled={!!busy}
                onClick={() => setDeleting(false)}
              >
                取消
              </Button>
              <Button
                variant="destructive"
                className="button danger"
                disabled={!!busy}
              >
                {busy ? "正在注销…" : "确认注销"}
              </Button>
            </div>
          </form>
        </AccountDialog>
      )}
    </div>
  );
}
