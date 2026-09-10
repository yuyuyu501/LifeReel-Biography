import {
  BookHeart,
  BookOpenText,
  Film,
  LockKeyhole,
  LogOut,
  Mic2,
  UsersRound,
  Wallet,
} from "lucide-react";
import type { PropsWithChildren } from "react";
import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useQueryClient } from "@tanstack/react-query";

const workflowItems = [
  { to: "/people", label: "家人", icon: UsersRound },
  { to: "/interviews", label: "采访", icon: Mic2 },
  { to: "/scripts", label: "剧本", icon: BookOpenText },
  { to: "/studio", label: "影像", icon: Film },
];
const profileItems = [
  { to: "/memories", label: "记忆", icon: BookHeart },
  { to: "/wallet", label: "钱包", icon: Wallet },
];
const navigationGroups = [
  {
    id: "workflow-navigation",
    label: "生命档案流程",
    items: workflowItems,
    workflow: true,
  },
  {
    id: "profile-navigation",
    label: "个人资料",
    items: profileItems,
    workflow: false,
  },
];

export function AppShell({ children }: PropsWithChildren) {
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const currentSection = [...workflowItems, ...profileItems].find(
    (item) =>
      location.pathname === item.to ||
      location.pathname.startsWith(`${item.to}/`),
  );
  async function logout() {
    try {
      await api.logout();
    } finally {
      queryClient.clear();
      navigate("/login", { replace: true });
    }
  }
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        跳到主要内容
      </a>
      <aside className="sidebar">
        <NavLink to="/" className="brand" aria-label="岁忆影传首页">
          <span className="brand-mark">岁</span>
          <span>
            <strong>岁忆影传</strong>
            <small>LifeReel Biography</small>
          </span>
        </NavLink>
        {navigationGroups.map((group) => (
          <div
            key={group.id}
            className={`sidebar-group${group.workflow ? "" : " sidebar-profile"}`}
          >
            <span id={group.id} className="sidebar-label">
              {group.label}
            </span>
            <nav aria-labelledby={group.id}>
              {group.items.map(({ to, label, icon: Icon }, index) => (
                <NavLink key={to} to={to} className="nav-item">
                  <Icon size={20} strokeWidth={1.8} aria-hidden="true" />
                  <span>{label}</span>
                  {group.workflow && (
                    <small aria-hidden="true">
                      {String(index + 1).padStart(2, "0")}
                    </small>
                  )}
                </NavLink>
              ))}
            </nav>
          </div>
        ))}
        <div className="sidebar-footer">
          <div className="privacy-note">
            <LockKeyhole size={17} />
            <div>
              <strong>家庭私密空间</strong>
              <small>内容默认不公开，发布前需确认授权。</small>
            </div>
          </div>
          <button className="logout-button" onClick={logout}>
            <LogOut size={16} /> 退出登录
          </button>
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
            <strong>
              {currentSection?.label ??
                (location.pathname === "/" ? "首页" : "生命档案")}
            </strong>
          </div>
          <nav className="workspace-links" aria-label="个人资料快捷入口">
            {profileItems.map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                className="workspace-security"
                to={to}
                aria-label={label}
                title={label}
              >
                <Icon size={17} aria-hidden="true" />
                <span>{label}</span>
              </NavLink>
            ))}
          </nav>
        </header>
        <main className="main-content" id="main-content">
          {children}
        </main>
      </div>
    </div>
  );
}
