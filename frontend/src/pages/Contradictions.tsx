import { Check, Download, Sparkles, X } from "lucide-react";
import { useMemo, useState } from "react";
import { EvidenceQuote } from "@/components/Evidence";
import { Badge, Button, Card, Confidence, Empty, ErrorBox, PageHeader, SEVERITY_RU, SEVERITY_TONE, STATUS_RU, Select, Spinner } from "@/components/ui";
import { api, download } from "@/lib/api";
import { useApp } from "@/lib/context";
import { useApi } from "@/lib/hooks";

const TYPE_RU: Record<string, string> = {
  value_mismatch: "Расхождение значений", unit_hidden_mismatch: "Скрытое расхождение (единицы)",
  demand_exceeds_capability: "Требование превышает возможности", material_limit: "Предел материала",
  setpoint_exceeds_limit: "Уставка выше предела", material_mismatch: "Разные материалы", semantic: "Смысловое противоречие",
};
const DET_RU: Record<string, string> = { formal: "формальная проверка", graph: "проверка по графу", llm: "языковая модель" };
const REVIEW_RU: Record<string, string> = { confirmed_by_engineer: "подтверждено инженером", rejected: "отклонено", new: "не рассмотрено" };

export default function Contradictions() {
  const { project, user } = useApp();
  const { data, error, loading, reload } = useApi<any[]>(`/projects/${project}/contradictions`, [project]);
  const [sev, setSev] = useState(""); const [type, setType] = useState(""); const [rv, setRv] = useState("");
  const rows = useMemo(() => (data ?? []).filter((c) => (!sev || c.severity === sev) && (!type || c.type === type) &&
    (!rv || (c.review?.status ?? "new") === rv)), [data, sev, type, rv]);
  const [sem, setSem] = useState<string | null>(null);
  const runSemantic = async () => {
    setSem("Идёт сравнение пар фрагментов языковой моделью…");
    try { const r = await api<any>(`/projects/${project}/contradictions/semantic`, { method: "POST" });
      setSem(`Проверено пар: ${r.pairs}; возможных противоречий: ${r.found} (статус «потенциально», требуют проверки инженером)`); reload(); }
    catch (e: any) { setSem(String(e?.message ?? e)); }
  };
  const review = async (id: string, status: string) => { await api(`/projects/${project}/contradictions/${id}`, { method: "PATCH", json: { status } }); reload(); };
  return (
    <div>
      <PageHeader title="Обнаруженные противоречия" sub="Формальные проверки после приведения единиц и проверки по графу зависимостей. Каждое — с двумя источниками."
        right={<>
          <Button size="sm" onClick={runSemantic} title="Уровень 2: сравнение пар фрагментов локальной языковой моделью"><Sparkles className="h-3.5 w-3.5" />Семантическая проверка (LLM)</Button>
          <Button size="sm" onClick={() => download(`/projects/${project}/contradictions/export?fmt=docx`, "contradictions.docx")}><Download className="h-3.5 w-3.5" />DOCX</Button>
          <Button size="sm" onClick={() => download(`/projects/${project}/contradictions/export?fmt=pdf`, "contradictions.pdf")}><Download className="h-3.5 w-3.5" />PDF</Button>
        </>} />
      {sem && <div className="border-b border-line bg-canvas px-6 py-2 text-xs text-ink-soft">{sem}</div>}
      <div className="flex flex-wrap items-center gap-2 border-b border-line bg-surface px-6 py-2">
        <Select className="w-44" value={sev} onChange={(e) => setSev(e.target.value)}><option value="">Любая серьёзность</option>{Object.entries(SEVERITY_RU).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select>
        <Select className="w-64" value={type} onChange={(e) => setType(e.target.value)}><option value="">Все типы</option>{Object.entries(TYPE_RU).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select>
        <Select className="w-48" value={rv} onChange={(e) => setRv(e.target.value)}><option value="">Любой статус проверки</option>{Object.entries(REVIEW_RU).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select>
        <span className="ml-auto text-xs text-ink-faint">{rows.length} из {data?.length ?? 0}</span>
      </div>
      <div className="space-y-3 p-6">
        <ErrorBox error={error} />
        {loading && !data ? <Spinner /> : rows.length === 0 ? <Card><Empty title="Противоречий не найдено" /></Card> : rows.map((c) => (
          <Card key={c.id}>
            <div className="flex flex-wrap items-start gap-3 border-b border-line px-4 py-3">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-1.5">
                  <Badge tone={SEVERITY_TONE[c.severity]}>{SEVERITY_RU[c.severity]}</Badge>
                  <Badge tone="navy">{TYPE_RU[c.type] ?? c.type}</Badge>
                  <Badge>{STATUS_RU[c.status]}</Badge>
                  <span className="text-xs text-ink-faint">{DET_RU[c.detected_by]}</span>
                </div>
                <div className="mt-1.5 font-semibold">{c.title}</div>
                <div className="font-mono text-[12.5px] text-ink-soft">{c.description}</div>
              </div>
              <div className="flex flex-col items-end gap-2">
                <Confidence value={c.confidence} />
                {c.review ? <Badge tone={c.review.status === "rejected" ? "neutral" : "ok"}>{REVIEW_RU[c.review.status]} · {c.review.user}</Badge> :
                  user?.role !== "viewer" && <div className="flex gap-1">
                    <Button size="sm" onClick={() => review(c.id, "confirmed_by_engineer")}><Check className="h-3.5 w-3.5" />Подтвердить</Button>
                    <Button size="sm" variant="ghost" onClick={() => review(c.id, "rejected")}><X className="h-3.5 w-3.5" />Отклонить</Button>
                  </div>}
              </div>
            </div>
            <div className="grid gap-3 px-4 py-3 md:grid-cols-2">
              {c.evidence.slice(0, 2).map((e: any, i: number) => <div key={i}><div className="label mb-1">Источник {i + 1}</div><EvidenceQuote ev={e} /></div>)}
            </div>
            {c.evidence.length > 2 && <div className="px-4 pb-3"><div className="label mb-1">Связь по графу</div><EvidenceQuote ev={c.evidence[2]} /></div>}
            <div className="grid gap-3 border-t border-line px-4 py-3 text-sm md:grid-cols-2">
              <div><div className="label mb-0.5">Объяснение</div>{c.explanation}</div>
              <div><div className="label mb-0.5">Рекомендация</div>{c.recommendation}</div>
            </div>
            {c.entity_names.length > 0 && <div className="border-t border-line px-4 py-2 text-xs text-ink-faint">Затронуто: {c.entity_names.join(", ")}</div>}
          </Card>
        ))}
      </div>
    </div>
  );
}
