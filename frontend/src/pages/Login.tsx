import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button, ErrorBox, Input } from "@/components/ui";
import { api, setToken } from "@/lib/api";
import { useApp } from "@/lib/context";

export default function Login() {
  const [u, setU] = useState("admin");
  const [p, setP] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const { setUser } = useApp();
  const nav = useNavigate();
  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setBusy(true); setErr(null);
    try {
      const r = await api("/auth/login", { method: "POST", json: { username: u, password: p } });
      setToken(r.token); setUser({ username: r.username, role: r.role }); nav("/");
    } catch (x) { setErr(x); } finally { setBusy(false); }
  };
  return (
    <div className="flex h-full items-center justify-center bg-graphite-900 p-4">
      <form onSubmit={submit} className="w-full max-w-sm rounded-md border border-white/10 bg-surface p-6 shadow-xl">
        <div className="font-mono text-[11px] tracking-[0.2em] text-ink-faint">EIS</div>
        <h1 className="mt-1 text-base font-semibold">Анализ инженерной документации</h1>
        <p className="mt-1 text-sm text-ink-soft">Оценка последствий конструкторских изменений</p>
        <div className="mt-5 space-y-3">
          <label className="block"><span className="label">Пользователь</span><Input className="mt-1" value={u} onChange={(e) => setU(e.target.value)} autoComplete="username" /></label>
          <label className="block"><span className="label">Пароль</span><Input className="mt-1" type="password" value={p} onChange={(e) => setP(e.target.value)} autoComplete="current-password" /></label>
          <ErrorBox error={err} />
          <Button variant="primary" size="lg" className="w-full" loading={busy} type="submit">Войти</Button>
        </div>
        <p className="mt-4 text-xs text-ink-faint">Данные обрабатываются локально. Внешние языковые модели по умолчанию отключены.</p>
      </form>
    </div>
  );
}
