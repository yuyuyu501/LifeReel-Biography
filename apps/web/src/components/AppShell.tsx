import { BookHeart, BookOpenText, Film, Home, LockKeyhole, LogOut, Mic2, UsersRound } from "lucide-react";
import type { PropsWithChildren } from "react";
import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useQueryClient } from "@tanstack/react-query";

const items = [
  { to: "/", label: "首页", icon: Home },
  { to: "/people", label: "家人", icon: UsersRound },
  { to: "/interviews", label: "采访", icon: Mic2 },
  { to: "/memories", label: "记忆", icon: BookHeart, secondary: true },
  { to: "/scripts", label: "剧本", icon: BookOpenText },
  { to: "/studio", label: "影像", icon: Film },
];

export function AppShell({ children }: PropsWithChildren) {
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const currentSection = items.find((item) => item.to === "/" ? location.pathname === "/" : location.pathname.startsWith(item.to));
  async function logout() {
    try {
      await api.logout();
    } finally {
      queryClient.removeQueries({ queryKey: ["auth-me"] });
      navigate("/login", { replace: true });
    }
  }
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">跳到主要内容</a>
      <aside className="sidebar">
        <NavLink to="/" className="brand" aria-label="岁忆影传首页">
          <span className="brand-mark">岁</span>
          <span>
            <strong>岁忆影传</strong>
            <small>LifeReel Biography</small>
          </span>
        </NavLink>
        <span className="sidebar-label">生命档案流程</span>
        <nav aria-label="主导航">
          {items.map(({ to, label, icon: Icon, secondary }, index) => (
            <NavLink key={to} to={to} end={to === "/"} className={`nav-item ${secondary ? "nav-secondary" : ""}`}>
              <Icon size={20} strokeWidth={1.8} />
              <span>{label}</span>
              <small>{String(index + 1).padStart(2, "0")}</small>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-footer">
          <div className="privacy-note">
            <LockKeyhole size={17} />
            <div>
              <strong>家庭私密空间</strong>
              <small>内容默认不公开，制作与发布前必须确认授权。</small>
            </div>
          </div>
          <button className="logout-button" onClick={logout}><LogOut size={16} /> 退出登录</button>
        </div>
      </aside>
      <div className="main-frame">
        <header className="workspace-bar">
          <Link to="/" className="mobile-brand" aria-label="岁忆影传首页">
            <span className="brand-mark">岁</span>
            <strong>岁忆影传</strong>
          </Link>
          <div>
            <span className="workspace-label">当前工作区</span>
            <strong>{currentSection?.label ?? "生命档案"}</strong>
          </div>
          <Link className="workspace-security" to="/memories" aria-label="记忆档案" title="记忆档案"><BookHeart size={17} /><span>记忆档案</span></Link>
        </header>
        <main className="main-content" id="main-content">{children}</main>
      </div>
    </div>
  );
}
