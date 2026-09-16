import { Input } from "../components/ui/input";
import { Button } from "../components/ui/button";
import { LockKeyhole } from "lucide-react";
import { type FormEvent, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type SmsVerification } from "../api/client";
import { SmsCodeField } from "../components/SmsCodeField";

export function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const registering = location.pathname === "/register";
  const resetting = location.pathname === "/forgot-password";
  const [verification, setVerification] = useState<SmsVerification | null>(
    null,
  );
  const [confirmPassword, setConfirmPassword] = useState("");
  const [name, setName] = useState("");
  const registration = useQuery({
    queryKey: ["registration"],
    queryFn: api.registration,
  });
  const smsReady = resetting
    ? registration.data?.password_reset_enabled
    : registration.data?.sms_enabled;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setError("");
    try {
      if (registering || resetting) {
        if (password !== confirmPassword)
          throw new Error("两次输入的密码不一致。");
        if (!verification?.challenge_id || verification.phone !== email)
          throw new Error("请先获取当前手机号的短信验证码。");
        if (resetting) {
          await api.resetPassword({ ...verification, password });
          navigate("/login", {
            replace: true,
            state: { message: "密码已重置，请使用新密码登录。" },
          });
          return;
        }
        await api.register({ ...verification, password, display_name: name });
      }
      const result = await api.login(email, password);
      queryClient.clear();
      queryClient.setQueryData(["auth-me"], result.user);
      navigate("/");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "登录失败");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="login-page">
      <Link className="auth-brand" to="/login">
        <span className="brand-mark">岁</span>
        <strong>岁忆影传</strong>
      </Link>
      <form className="login-card" onSubmit={submit}>
        <span className="auth-kicker">
          <LockKeyhole size={15} aria-hidden="true" />
          家庭私密空间
        </span>
        <h1>
          {registering
            ? "创建家庭账户"
            : resetting
              ? "找回密码"
              : "登录后继续整理"}
        </h1>
        <p>人物、声音、照片和影传仅保存在所属家庭空间。</p>
        {registering && (
          <label>
            称呼
            <Input
              value={name}
              onChange={(event) => setName(event.target.value)}
              required
              maxLength={80}
            />
          </label>
        )}
        {!registering && !resetting && location.state?.message && (
          <p className="field-success" role="status">
            {location.state.message}
          </p>
        )}
        <label>
          {registering || resetting ? "手机号" : "手机号或邮箱"}
          <Input
            type={registering || resetting ? "tel" : "text"}
            autoComplete="username"
            value={email}
            onChange={(event) => setEmail(event.target.value.trim())}
            required
            maxLength={registering || resetting ? 11 : 255}
            pattern={registering || resetting ? "1[3-9][0-9]{9}" : undefined}
          />
        </label>
        {(registering || resetting) && (
          <SmsCodeField
            key={`${location.pathname}:${email}`}
            phone={email}
            purpose={registering ? "register" : "reset_password"}
            onChange={setVerification}
            disabled={pending || !smsReady}
          />
        )}
        <label>
          {resetting ? "新密码" : "密码"}
          <Input
            type="password"
            autoComplete={
              registering || resetting ? "new-password" : "current-password"
            }
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
            minLength={8}
            maxLength={200}
          />
        </label>
        {(registering || resetting) && (
          <>
            <small>密码至少 8 位。</small>
            <label>
              确认密码
              <Input
                type="password"
                autoComplete="new-password"
                value={confirmPassword}
                onChange={(event) => setConfirmPassword(event.target.value)}
                required
                minLength={8}
                maxLength={200}
              />
            </label>
          </>
        )}
        {error && (
          <div className="notice error" role="alert">
            {error}
          </div>
        )}
        {registering && registration.data && !registration.data.enabled && (
          <p className="field-error" role="alert">
            注册暂未开放，请联系管理员。
          </p>
        )}
        {(registering || resetting) && registration.data && !smsReady && (
          <p className="field-error" role="alert">
            短信验证暂未开通，请稍后再试。
          </p>
        )}
        <Button
          variant="default"
          className="button primary"
          disabled={
            pending ||
            ((registering || resetting) && !smsReady) ||
            (registering && !registration.data?.enabled)
          }
        >
          {pending
            ? "正在提交…"
            : registering
              ? "注册并进入"
              : resetting
                ? "重置密码"
                : "进入档案工作台"}
        </Button>
        <div className="auth-links">
          {registering || resetting ? (
            <Link to="/login">返回登录</Link>
          ) : (
            <>
              {registration.data?.enabled && (
                <Link to="/register">创建账号</Link>
              )}
              <Link to="/forgot-password">忘记密码</Link>
            </>
          )}
        </div>
      </form>
    </div>
  );
}
