import { BookOpenText, LockKeyhole } from "lucide-react";
import { type FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";

export function LoginPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const [registering, setRegistering] = useState(false);
  const [name, setName] = useState("");
  const registration = useQuery({ queryKey: ["registration"], queryFn: api.registration });

  async function submit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setError("");
    try {
      if (registering) await api.register(email, password, name);
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
      <div className="login-context" aria-hidden="true"><div className="login-context-mark"><BookOpenText size={28} /></div><span>私人生命档案</span><h2>让讲述有来处，<br />让记忆有归档。</h2><p>采访原声、事实核对与发布授权，在同一条清晰的制作轨道上完成。</p><div className="archive-lines"><i /><i /><i /><i /></div></div>
      <form className="login-card" onSubmit={submit}>
        <div className="login-mark"><LockKeyhole size={24} /></div>
        <span className="eyebrow">家庭私密空间</span>
        <h1>{registering ? "创建家庭账户" : "登录后继续整理"}</h1>
        <p>人物、声音、照片和影传仅保存在所属家庭空间。</p>
        {registering && <label>称呼<input value={name} onChange={event => setName(event.target.value)} required maxLength={80} /></label>}
        <label>邮箱<input type="email" value={email} onChange={(event) => setEmail(event.target.value)} required /></label>
        <label>密码<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} required minLength={8} /></label>
        {error && <div className="notice error" role="alert">{error}</div>}
        <button className="button primary" disabled={pending}>{registering ? "注册并进入" : "进入档案工作台"}</button>
        {registration.data?.enabled && <button type="button" className="button secondary" disabled={pending} onClick={() => { setRegistering(!registering); setError(""); }}>{registering ? "已有账号，去登录" : "创建账号"}</button>}
        <small>开发演示账号见 README；生产环境请使用部署时设置的管理员账号。</small>
      </form>
    </div>
  );
}
