import { AlertTriangle, BotMessageSquare, FileText, GitBranch, LayoutDashboard, LogOut, Network, ScrollText } from "lucide-react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { setToken } from "@/lib/api";
import { useApp } from "@/lib/context";
import { useApi } from "@/lib/hooks";
import { cn } from "@/lib/utils";

const NAV = [
  { to: "/", label: "Обзор", icon: LayoutDashboard },
  { to: "/documents", label: "Документы", icon: FileText },
  { to: "/graph", label: "Граф знаний", icon: Network },
  { to: "/impact", label: "Анализ изменений", icon: GitBranch },
  { to: "/contradictions", label: "Противоречия", icon: AlertTriangle },
  { to: "/assistant", label: "Помощник", icon: BotMessageSquare },
  { to: "/reports", label: "Отчёты", icon: ScrollText },
];

export default function Layout() {
  const { user, setUser, project, setProject } = useApp();
  const nav = useNavigate();
  const { data: projects } = useApi<any[]>("/projects");
  const { data: health } = useApi<any>("/health");
  return (
    <div className="flex h-full">
      <aside className="flex w-56 shrink-0 flex-col bg-graphite-900 text-[#C9CED6]">
        <div className="border-b border-white/10 px-4 py-4">
          <div className="font-mono text-[11px] tracking-[0.2em] text-[#8A93A0]">EIS</div>
          <div className="mt-0.5 text-[13px] font-semibold leading-tight text-white">Engineering Intelligence System</div>
        </div>
        <nav className="flex-1 space-y-0.5 px-2 py-3">
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} end={to === "/"}
              className={({ isActive }) => cn("flex items-center gap-2.5 rounded px-2.5 py-1.5 text-[13px] transition-colors",
                isActive ? "bg-white/10 text-white" : "hover:bg-white/5 hover:text-white")}>
              <Icon className="h-4 w-4 opacity-80" />{label}
            </NavLink>
          ))}
        </nav>
        <div className="space-y-1.5 border-t border-white/10 px-4 py-3 text-[11.5px]">
          <div className="flex justify-between"><span>OCR</span><span className={health?.ocr ? "text-[#7FD1A3]" : "text-[#E8A27C]"}>{health ? (health.ocr ? "доступен" : "нет") : "…"}</span></div>
          <div className="flex justify-between"><span>LLM</span><span className={health?.llm_available ? "text-[#7FD1A3]" : "text-[#8A93A0]"}>{health ? (health.llm_available ? health.llm : "не подключена") : "…"}</span></div>
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-11 shrink-0 items-center justify-between gap-4 border-b border-line bg-surface px-6">
          <div className="flex items-center gap-2 text-sm">
            <span className="text-ink-faint">Проект</span>
            <select className="h-7 rounded border border-line bg-surface px-2 text-sm" value={project} onChange={(e) => setProject(e.target.value)}>
              {(projects ?? [{ id: project, name: project }]).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </div>
          <div className="flex items-center gap-3 text-sm text-ink-soft">
            <span>{user?.username} <span className="text-ink-faint">· {user?.role}</span></span>
            <button className="rounded p-1 hover:bg-canvas" title="Выйти" onClick={() => { setToken(null); setUser(null); nav("/login"); }}>
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        </header>
        <main className="min-h-0 flex-1 overflow-auto"><Outlet /></main>
      </div>
    </div>
  );
}
