import { Send, ShieldCheck } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { EvidenceQuote } from "@/components/Evidence";
import { Badge, Button, Card, ErrorBox, Input, PageHeader, Select } from "@/components/ui";
import { api } from "@/lib/api";
import { useApp } from "@/lib/context";
import { useApi } from "@/lib/hooks";
import { cn } from "@/lib/utils";

const SUGGEST = [
  "Какие документы связаны с торцевым уплотнением?",
  "Какие требования относятся к подшипниковому узлу?",
  "Что произойдёт, если увеличить температуру перекачиваемой среды с 80 °C до 100 °C?",
  "Какие документы необходимо пересмотреть, если рабочее давление увеличится с 1,6 МПа до 2,5 МПа?",
  "Есть ли противоречия между техническим заданием и руководством по эксплуатации?",
  "Какие испытания связаны с требованием к виброскорости?",
  "Почему кольцо уплотнительное считается затронутым?",
];
const INTENT_RU: Record<string, string> = { impact: "анализ изменения", why: "обоснование", contradictions: "противоречия", tests: "испытания", revise: "пересмотр документов", documents: "документы", requirements: "требования", search: "поиск" };

type Msg = { role: "user" | "assistant"; text: string; ans?: any };

function Rich({ text, onCite }: { text: string; onCite: (n: number) => void }) {
  const parts = text.split(/(\[\d+\])/g);
  return <>{parts.map((p, i) => {
    const m = p.match(/^\[(\d+)\]$/);
    return m ? <button key={i} onClick={() => onCite(+m[1])} className="mx-px rounded bg-navy-50 px-1 font-mono text-[11px] text-navy-600 hover:bg-navy-100">{p}</button> : <span key={i}>{p}</span>;
  })}</>;
}

export default function Assistant() {
  const { project } = useApp();
  const { data: subjects } = useApi<any[]>(`/projects/${project}/subjects`, [project]);
  const [ctx, setCtx] = useState("");
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const [cite, setCite] = useState<{ ans: any; n: number } | null>(null);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs]);
  const ask = async (question: string) => {
    if (!question.trim()) return;
    setMsgs((m) => [...m, { role: "user", text: question }]); setQ(""); setBusy(true); setErr(null);
    try {
      const ans = await api(`/projects/${project}/assistant`, { method: "POST", json: { question, context_entity: ctx || null } });
      setMsgs((m) => [...m, { role: "assistant", text: ans.llm_text ?? ans.text, ans }]);
      if (ans.citations.length) setCite({ ans, n: 1 });
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  return (
    <div className="flex h-full flex-col">
      <PageHeader title="Инженерный помощник" sub="Ответы формируются из графа знаний и найденных фрагментов; каждое утверждение — со ссылкой на источник"
        right={<label className="flex items-center gap-2 text-sm"><span className="text-ink-faint">Контекст</span>
          <Select className="w-64" value={ctx} onChange={(e) => setCtx(e.target.value)}><option value="">не задан</option>{(subjects ?? []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</Select></label>} />
      <div className="flex min-h-0 flex-1">
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="min-h-0 flex-1 space-y-4 overflow-auto p-6">
            {msgs.length === 0 && (
              <Card className="p-4">
                <div className="label mb-2">Примеры вопросов</div>
                <div className="grid gap-1.5 md:grid-cols-2">{SUGGEST.map((s) => <button key={s} onClick={() => ask(s)} className="rounded border border-line px-3 py-2 text-left text-sm hover:border-navy-500/40 hover:bg-navy-50">{s}</button>)}</div>
              </Card>
            )}
            {msgs.map((m, i) => (
              <div key={i} className={cn("max-w-3xl", m.role === "user" ? "ml-auto" : "")}>
                {m.role === "user" ? <div className="rounded-md bg-navy-700 px-3.5 py-2 text-sm text-white">{m.text}</div> : (
                  <Card className="px-4 py-3">
                    <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
                      <Badge tone="navy">{INTENT_RU[m.ans.intent] ?? m.ans.intent}</Badge>
                      <Badge>{m.ans.llm_used ? `LLM: ${m.ans.llm_provider}` : "без LLM: ответ из графа и документов"}</Badge>
                      {m.ans.guard && <Badge tone="ok"><ShieldCheck className="h-3 w-3" />проверка ссылок: отклонено {m.ans.guard.rejected.length}</Badge>}
                    </div>
                    <div className="whitespace-pre-wrap text-sm leading-6"><Rich text={m.text} onCite={(n) => setCite({ ans: m.ans, n })} /></div>
                    {m.ans.warnings.length > 0 && <div className="mt-2 text-xs text-med">{m.ans.warnings.join(" ")}</div>}
                  </Card>
                )}
              </div>
            ))}
            {busy && <div className="text-sm text-ink-faint">Анализ…</div>}
            <ErrorBox error={err} />
            <div ref={end} />
          </div>
          <form className="flex gap-2 border-t border-line bg-surface px-6 py-3" onSubmit={(e) => { e.preventDefault(); ask(q); }}>
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Вопрос о документации, требованиях, изменениях…" />
            <Button variant="primary" loading={busy} type="submit"><Send className="h-4 w-4" />Спросить</Button>
          </form>
        </div>
        <aside className="hidden w-[420px] shrink-0 flex-col border-l border-line bg-surface lg:flex">
          <div className="border-b border-line px-4 py-2.5 text-sm font-semibold">Источники ответа</div>
          <div className="min-h-0 flex-1 space-y-2 overflow-auto p-4">
            {!cite ? <div className="text-sm text-ink-faint">Нажмите на ссылку [n] в ответе.</div> :
              cite.ans.citations.map((c: any) => (
                <div key={c.n} className={cn("rounded", c.n === cite.n && "ring-2 ring-navy-500/40")}><EvidenceQuote ev={c} n={c.n} /></div>
              ))}
          </div>
        </aside>
      </div>
    </div>
  );
}
