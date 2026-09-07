import { BookOpenText, LockKeyhole } from "lucide-react";
import { type FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";

export function LoginPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setError("");
    try {
      const result = await api.login(email, password);
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
      <div className="login-context" aria-hidden="true"><div className="login-context-mark"><BookOpenText size={28} /></div><span>私人生命档案</span><h2>让讲述有来处，<br />让记忆有归档。</h2><p>采访原声、事实核对与发布授权，在同一条清晰的制作轨道上完成。</p><div className="archive-lines"><i /><i /><i /><i /></div></div>
      <form className="login-card" onSubmit={submit}>
        <div className="login-mark"><LockKeyhole size={24} /></div>
        <span className="eyebrow">家庭私密空间</span>
        <h1>登录后继续整理</h1>
        <p>人物、声音、照片和影传仅保存在所属家庭空间。</p>
        <label>邮箱<input type="email" value={email} onChange={(event) => setEmail(event.target.value)} required /></label>
        <label>密码<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} required minLength={8} /></label>
        {error && <div className="notice error" role="alert">{error}</div>}
        <button className="button primary" disabled={pending}>进入档案工作台</button>
        <small>开发演示账号见 README；生产环境请使用部署时设置的管理员账号。</small>
      </form>
    </div>
  );
}
