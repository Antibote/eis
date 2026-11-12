import { ArrowRight, Download, Network, Play } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { EvidenceQuote } from "@/components/Evidence";
import { Badge, Button, CLASS_RU, CLASS_TONE, Card, CardHeader, Confidence, Empty, ErrorBox, Input, PageHeader, Select } from "@/components/ui";
import { api, download } from "@/lib/api";
import { useApp } from "@/lib/context";
import { useApi } from "@/lib/hooks";
import { KIND_RU, PARAM_RU, cn, fmtReq } from "@/lib/utils";

const VERDICT: Record<string, [string, "crit" | "med" | "ok" | "neutral"]> = {
  violation: ["нарушение", "crit"], at_limit: ["на пределе", "med"], ok: ["соответствует", "ok"], no_data: ["нет данных", "neutral"],
};
const EXAMPLES = [
  "Максимальная рабочая температура перекачиваемой среды увеличивается с 80 °C до 100 °C.",
  "Рабочее давление на выходе насоса увеличивается с 1,6 МПа до 2,5 МПа.",
  "Номинальная мощность электродвигателя увеличивается с 55 кВт до 75 кВт.",
  "Нижняя граница температуры окружающего воздуха снижается с −40 °C до −50 °C.",
  "Допустимая виброскорость агрегата ужесточается с 4,5 мм/с до 2,8 мм/с.",
];

export default function Impact() {
  const { project, setLastImpact, user } = useApp();
  const nav = useNavigate();
  const [params] = useSearchParams();
  const { data: subjects } = useApi<any[]>(`/projects/${project}/subjects`, [project]);
  const [subject, setSubject] = useState("");
  const { data: reqs } = useApi<any[]>(subject ? `/projects/${project}/requirements?subject=${encodeURIComponent(subject)}` : null, [subject]);
  const [reqId, setReqId] = useState("");
  const [val, setVal] = useState(""); const [lo, setLo] = useState(""); const [hi, setHi] = useState("");
  const [text, setText] = useState("");
  const [mode, setMode] = useState<"form" | "text">("form");
  const [rep, setRep] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);

  useEffect(() => { if (subjects?.length && !subject) setSubject(subjects[0].id); }, [subjects, subject]);
  const changeable = useMemo(() => (reqs ?? []).filter((r) => ["demand", "nominal"].includes(r.kind) && typeof r.value !== "string"), [reqs]);
  const req = changeable.find((r) => r.id === reqId);
  useEffect(() => { if (changeable.length && !changeable.some((r) => r.id === reqId)) setReqId(changeable[0].id); }, [changeable, reqId]);
  useEffect(() => { if (req) { setVal(req.value != null ? String(req.value) : ""); setLo(req.low != null ? String(req.low) : ""); setHi(req.high != null ? String(req.high) : ""); } }, [req]);
  useEffect(() => { const id = params.get("report"); if (id) api(`/projects/${project}/impact/${id}`).then(setRep).catch(setErr); }, [params, project]);

  const num = (s: string) => (s.trim() === "" ? null : Number(s.replace(",", ".")));
  const run = async () => {
    setBusy(true); setErr(null);
    try {
      const body = mode === "text" ? { text } : req?.operator === "range" ? { requirement_id: reqId, new_low: num(lo), new_high: num(hi) } : { requirement_id: reqId, new_value: num(val) };
      const r = await api(`/projects/${project}/impact`, { method: "POST", json: body });
      setRep(r); setLastImpact(r);
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    rep?.items.filter((i: any) => i.entity_type !== "Material").forEach((i: any) => { c[i.impact_class] = (c[i.impact_class] ?? 0) + 1; });
    return c;
  }, [rep]);
  const canRun = user?.role !== "viewer";

  return (
    <div>
      <PageHeader title="Анализ последствий изменения" sub="Выбор требования, задание нового значения, обход графа зависимостей и формальная перепроверка ограничений" />
      <div className="grid gap-4 p-6 xl:grid-cols-[360px_1fr]">
        <Card className="h-fit">
          <div className="flex border-b border-line text-sm">
            {(["form", "text"] as const).map((m) => (
              <button key={m} onClick={() => setMode(m)} className={cn("flex-1 py-2", mode === m ? "border-b-2 border-navy-700 font-medium" : "text-ink-soft")}>
                {m === "form" ? "Выбор требования" : "Текст извещения"}
              </button>
            ))}
          </div>
          <div className="space-y-3 p-4">
            {mode === "form" ? <>
              <label className="block"><span className="label">Изделие / компонент</span>
                <Select className="mt-1" value={subject} onChange={(e) => { setSubject(e.target.value); setReqId(""); }}>
                  {(subjects ?? []).map((s) => <option key={s.id} value={s.id}>{s.name}{s.designation ? ` (${s.designation})` : ""}</option>)}
                </Select></label>
              <label className="block"><span className="label">Требование</span>
                <Select className="mt-1" value={reqId} onChange={(e) => setReqId(e.target.value)}>
                  {changeable.map((r) => <option key={r.id} value={r.id}>{PARAM_RU[r.parameter] ?? r.parameter}: {fmtReq(r)} — {r.document_code} {r.section ? `п. ${r.section}` : ""}</option>)}
                </Select></label>
              {req && <div className="quote">«{req.text}»</div>}
              {req && (req.operator === "range" ? (
                <div className="grid grid-cols-2 gap-2">
                  <label><span className="label">Нижняя граница, {req.unit}</span><Input className="mt-1 font-mono" value={lo} onChange={(e) => setLo(e.target.value)} /></label>
                  <label><span className="label">Верхняя граница, {req.unit}</span><Input className="mt-1 font-mono" value={hi} onChange={(e) => setHi(e.target.value)} /></label>
                </div>
              ) : (
                <label className="block"><span className="label">Новое значение ({req.operator === "<=" ? "≤" : req.operator === ">=" ? "≥" : "="}), {req.unit}</span>
                  <Input className="mt-1 font-mono" value={val} onChange={(e) => setVal(e.target.value)} /></label>
              ))}
            </> : <>
              <label className="block"><span className="label">Формулировка изменения</span>
                <textarea className="mt-1 h-24 w-full rounded border border-line p-2 text-sm focus:border-navy-500 focus:outline-none" value={text} onChange={(e) => setText(e.target.value)} placeholder="Например: рабочее давление увеличивается с 1,6 МПа до 2,5 МПа" /></label>
              <div className="space-y-1">{EXAMPLES.map((x) => <button key={x} onClick={() => setText(x)} className="block w-full rounded px-2 py-1 text-left text-xs text-navy-600 hover:bg-navy-50">{x}</button>)}</div>
            </>}
            <ErrorBox error={err} />
            <Button variant="primary" size="lg" className="w-full" loading={busy} disabled={!canRun || (mode === "form" ? !reqId : !text.trim())} onClick={run}>
              <Play className="h-4 w-4" />Запустить анализ</Button>
            {!canRun && <div className="text-xs text-ink-faint">Роль «viewer» не может запускать анализ.</div>}
          </div>
        </Card>
        {!rep ? <Card><Empty title="Результат появится здесь">Система найдёт исходное требование, пройдёт по зависимостям с учётом физической природы параметра, перепроверит ограничения компонентов и материалов новым значением и сформирует перечень документов и испытаний.</Empty></Card> : <Result rep={rep} counts={counts} onGraph={() => { setLastImpact(rep); nav("/graph"); }} project={project} />}
      </div>
    </div>
  );
}

function Result({ rep, counts, onGraph, project }: { rep: any; counts: Record<string, number>; onGraph: () => void; project: string }) {
  return (
    <div className="space-y-4">
      <Card>
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
          <div>
            <div className="label">{PARAM_RU[rep.parameter] ?? rep.parameter}</div>
            <div className="flex items-center gap-2 font-mono text-base"><span>{rep.old}</span><ArrowRight className="h-4 w-4 text-ink-faint" /><span className="font-semibold">{rep.new}</span></div>
          </div>
          {(["confirmed", "direct", "potential"] as const).map((c) => (
            <div key={c}><div className="label">{CLASS_RU[c]}</div><div className="text-xl font-semibold tabular">{counts[c] ?? 0}</div></div>
          ))}
          <div><div className="label">Документы</div><div className="text-xl font-semibold tabular">{rep.documents.length}</div></div>
          <div><div className="label">Повторить испытаний</div><div className="text-xl font-semibold tabular">{rep.tests.filter((t: any) => t.repeat_required !== false).length}</div></div>
          <div className="ml-auto flex gap-2">
            <Button size="sm" onClick={onGraph}><Network className="h-3.5 w-3.5" />На графе</Button>
            <Button size="sm" onClick={() => download(`/projects/${project}/impact/${rep.id}/export?fmt=docx`, "impact_report.docx")}><Download className="h-3.5 w-3.5" />DOCX</Button>
            <Button size="sm" onClick={() => download(`/projects/${project}/impact/${rep.id}/export?fmt=pdf`, "impact_report.pdf")}><Download className="h-3.5 w-3.5" />PDF</Button>
          </div>
        </div>
        <div className="border-t border-line px-4 py-2 text-xs text-ink-faint">Исходное требование: «{rep.requirement_text}» · расчёт {rep.elapsed_ms} мс · глубина {rep.settings.max_depth} · учёт физики параметра: {rep.settings.use_physics ? "да" : "нет"} · изменение: {rep.change_direction === "milder" ? "смягчение" : "ужесточение"}
          {rep.change_direction === "milder" && rep.not_rechecked?.length > 0 && <div className="mt-1">Смягчение требования: перепроверка не требуется — {rep.not_rechecked.join(", ")} (формальная проверка нарушений не выявила)</div>}</div>
      </Card>

      <Card>
        <CardHeader title="Затронутые элементы" sub="Транзитивная связь не считается доказательством влияния: «подтверждённое» — только при формальном нарушении ограничения" />
        <table className="tbl">
          <thead><tr><th>Элемент</th><th>Класс</th><th>Достоверность</th><th>Проверка новым значением</th><th>Цепочка</th></tr></thead>
          <tbody>{rep.items.map((it: any) => (
            <tr key={it.entity_id}>
              <td className="font-medium">{it.name}<div className="text-[11px] font-normal text-ink-faint">{it.entity_type === "Material" ? "материал" : ({ subject: "субъект требования", dependent: "явная зависимость", derived: "производная величина", contained: "входит в состав", load_path: "путь нагрузки", material: "материал детали", contributor: "вклад в характеристику", own_limit: "собственное ограничение по параметру", realizes: "задаёт номинал" } as any)[it.relation]}</div></td>
              <td><Badge tone={CLASS_TONE[it.impact_class]}>{CLASS_RU[it.impact_class]}</Badge></td>
              <td><Confidence value={it.confidence} /></td>
              <td className="max-w-md">
                {it.check && <Badge tone={VERDICT[it.check.verdict][1]}>{VERDICT[it.check.verdict][0]}</Badge>}
                {it.check && it.check.verdict !== "no_data" && <div className="mt-1 text-xs text-ink-soft">{it.check.detail.split("; ")[0]}</div>}
                {it.evidence[0] && <details className="mt-1"><summary className="cursor-pointer text-xs text-navy-600">основание</summary><div className="mt-1"><EvidenceQuote ev={it.evidence[0]} /></div></details>}
              </td>
              <td className="text-xs text-ink-soft">{it.path_names.slice(1).join(" → ")}</td>
            </tr>
          ))}</tbody>
        </table>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title="Документы, требующие пересмотра" sub="Только документы с утверждениями об изменяемом или связанных параметрах" />
          <div className="divide-y divide-line">{rep.documents.map((d: any) => (
            <details key={d.document_id} className="px-4 py-2">
              <summary className="cursor-pointer"><span className="font-mono text-sm">{d.code ?? d.filename}</span><span className="ml-2 text-xs text-ink-faint">{d.reasons.length} основ.</span></summary>
              <ul className="mt-1 list-disc pl-5 text-xs text-ink-soft">{d.reasons.map((r: string) => <li key={r}>{r}</li>)}</ul>
              <div className="mt-2 space-y-1.5">{d.evidence.slice(0, 2).map((e: any, i: number) => <EvidenceQuote key={i} ev={e} />)}</div>
            </details>
          ))}</div>
        </Card>
        <div className="space-y-4">
          <Card>
            <CardHeader title="Испытания" />
            <div className="divide-y divide-line">{rep.tests.length === 0 ? <Empty title="Связанных испытаний нет" /> : rep.tests.map((t: any) => (
              <div key={t.test_id} className="px-4 py-2">
                <div className="flex items-center gap-2"><span className="font-medium">{t.name}</span>
                  {t.result_still_valid === false && <Badge tone="crit">результат не подтверждает новое значение</Badge>}
                  {t.result_still_valid === true && <Badge tone="ok">повторение не требуется</Badge>}
                  {t.result_still_valid !== true && t.result_still_valid !== false && <Badge tone="high">повторить</Badge>}</div>
                <div className="text-xs text-ink-soft">{t.reason}{t.result && <> · результат: {t.result}</>}</div>
              </div>
            ))}</div>
          </Card>
          {rep.derived.length > 0 && <Card>
            <CardHeader title="Производные величины" />
            <div className="divide-y divide-line">{rep.derived.map((d: any) => (
              <div key={d.constraint_id} className="px-4 py-2 text-sm">{d.description}: новое значение <span className="font-mono font-semibold">{d.new_expected}</span>
                <div className="text-xs text-ink-faint">в документах: {d.stated.join("; ") || "—"}</div></div>
            ))}</div>
          </Card>}
          {rep.conflicts_after_change.length > 0 && <Card>
            <CardHeader title="Расхождения после изменения" />
            <div className="divide-y divide-line">{rep.conflicts_after_change.map((c: any) => <div key={c.id} className="px-4 py-2 text-sm">{c.description}</div>)}</div>
          </Card>}
        </div>
      </div>
      <Card>
        <CardHeader title="Рекомендации" sub="Сформированы по результатам формальных проверок; требуют решения инженера" />
        <ol className="list-decimal space-y-1 py-3 pl-9 pr-4 text-sm">{rep.recommendations.map((r: string, i: number) => <li key={i}>{r}</li>)}</ol>
      </Card>
      <div className="text-xs text-ink-faint">Виды: {Object.entries(KIND_RU).map(([k, v]) => `${k} — ${v}`).join(", ")}</div>
    </div>
  );
}
