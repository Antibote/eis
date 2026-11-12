import { useState, type ReactNode } from "react";
import { api } from "@/lib/api";

/** Смена собственного пароля (пароль администратора по умолчанию нужно сменить перед показом). */
export function PasswordDialog({ trigger }: { trigger: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [oldP, setOldP] = useState(""); const [newP, setNewP] = useState(""); const [rep, setRep] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const submit = async () => {
    if (newP !== rep) { setMsg({ ok: false, text: "Повтор пароля не совпадает" }); return; }
    try {
      await api("/auth/password", { method: "POST", json: { old_password: oldP, new_password: newP } });
      setMsg({ ok: true, text: "Пароль изменён" }); setOldP(""); setNewP(""); setRep("");
    } catch (e: any) { setMsg({ ok: false, text: String(e?.message ?? e) }); }
  };
  const field = "h-8 w-full rounded border border-line bg-surface px-2 text-sm";
  return (
    <>
      <button className="rounded p-1 hover:bg-canvas" title="Сменить пароль" onClick={() => { setOpen(true); setMsg(null); }}>{trigger}</button>
      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={() => setOpen(false)}>
          <div className="w-80 rounded-md border border-line bg-surface p-4 shadow-lg" onClick={(e) => e.stopPropagation()}>
            <div className="mb-3 text-sm font-semibold text-ink">Смена пароля</div>
            <div className="space-y-2">
              <input className={field} type="password" autoComplete="current-password" placeholder="Текущий пароль" value={oldP} onChange={(e) => setOldP(e.target.value)} />
              <input className={field} type="password" autoComplete="new-password" placeholder="Новый пароль (не короче 10 символов)" value={newP} onChange={(e) => setNewP(e.target.value)} />
              <input className={field} type="password" autoComplete="new-password" placeholder="Повтор нового пароля" value={rep} onChange={(e) => setRep(e.target.value)} />
            </div>
            {msg && <div className={`mt-2 text-xs ${msg.ok ? "text-ok" : "text-crit"}`}>{msg.text}</div>}
            <div className="mt-3 flex justify-end gap-2">
              <button className="h-8 rounded px-3 text-sm text-ink-soft hover:bg-canvas" onClick={() => setOpen(false)}>Закрыть</button>
              <button className="h-8 rounded bg-navy-700 px-3 text-sm text-white hover:bg-navy-800" onClick={submit}>Сохранить</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
