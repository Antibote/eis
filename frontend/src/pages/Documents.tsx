import { AlertTriangle, Upload, X } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { EvidenceQuote } from "@/components/Evidence";
import { Badge, Button, Card, Empty, ErrorBox, Input, PageHeader, Select, Spinner } from "@/components/ui";
import { api, download } from "@/lib/api";
import { useApp } from "@/lib/context";
import { useApi } from "@/lib/hooks";
import { DOCTYPE_RU, KIND_RU, PARAM_RU, TYPE_RU, cn, fmtReq } from "@/lib/utils";

const STATUS: Record<string, [string, "ok" | "crit" | "neutral"]> = { extracted: ["обработан", "ok"], failed: ["ошибка", "crit"], parsed: ["разобран", "neutral"] };

export default function Documents() {
  const { project, user } = useApp();
  const { data, error, loading, reload } = useApi<any[]>(`/projects/${project}/documents`, [project]);
  const [q, setQ] = useState("");
  const [type, setType] = useState("");
  const [sel, setSel] = useState<string | null>(null);
  const [upl, setUpl] = useState<{ busy: boolean; result?: any; error?: unknown }>({ busy: false });
  const file = useRef<HTMLInputElement>(null);
  const rows = useMemo(() => (data ?? []).filter((d) => (!type || d.doc_type === type) &&
    (!q || `${d.filename} ${d.title} ${d.code}`.toLowerCase().includes(q.toLowerCase()))), [data, q, type]);
  const onFiles = async (files: FileList | null) => {
    if (!files?.length) return;
    const fd = new FormData();
    Array.from(files).forEach((f) => fd.append("files", f));
    setUpl({ busy: true });
    try { setUpl({ busy: false, result: await api(`/projects/${project}/documents`, { method: "POST", body: fd }) }); reload(); }
    catch (e) { setUpl({ busy: false, error: e }); }
  };
  return (
    <div className="flex h-full flex-col">
      <PageHeader title="Библиотека документов" sub="Загрузка, статус обработки и извлечённые данные с привязкой к первоисточнику"
        right={user?.role !== "viewer" && <>
          <input ref={file} type="file" multiple className="hidden" accept=".pdf,.docx,.txt,.xlsx,.csv,.png,.jpg,.jpeg" onChange={(e) => onFiles(e.target.files)} />
          <Button variant="primary" loading={upl.busy} onClick={() => file.current?.click()}><Upload className="h-4 w-4" />Загрузить документы</Button>
        </>} />
      <div className="flex min-h-0 flex-1">
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex flex-wrap items-center gap-2 border-b border-line bg-surface px-6 py-2">
            <Input className="max-w-xs" placeholder="Поиск по названию, обозначению…" value={q} onChange={(e) => setQ(e.target.value)} />
            <Select className="max-w-[220px]" value={type} onChange={(e) => setType(e.target.value)}>
              <option value="">Все типы</option>
              {Object.entries(DOCTYPE_RU).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </Select>
            <span className="ml-auto text-xs text-ink-faint">PDF, DOCX, TXT, XLSX, CSV, PNG, JPEG · до 50 МБ · макросы запрещены</span>
          </div>
          {upl.result && (
            <div className="border-b border-line bg-navy-50 px-6 py-2 text-sm">
              Принято: {upl.result.accepted.length}.{" "}
              {upl.result.rejected.map((r: any) => <span key={r.filename} className="ml-2 text-crit">{r.filename}: {r.reason}</span>)}
            </div>
          )}
          <div className="px-6 pt-2"><ErrorBox error={error || upl.error} /></div>
          <div className="min-h-0 flex-1 overflow-auto px-6 py-3">
            {loading && !data ? <Spinner /> : rows.length === 0 ? <Card><Empty title="Документов нет">Загрузите файлы или откройте «Обзор», чтобы загрузить демонстрационный набор.</Empty></Card> : (
              <Card className="overflow-hidden">
                <table className="tbl">
                  <thead><tr><th>Документ</th><th>Тип</th><th>Статус</th><th className="text-right">Фрагм.</th><th className="text-right">Требов.</th><th /></tr></thead>
                  <tbody>{rows.map((d) => (
                    <tr key={d.id} className={cn("cursor-pointer", sel === d.id && "[&>td]:bg-navy-50")} onClick={() => setSel(d.id)}>
                      <td>
                        <div className="font-medium">{d.title ?? d.filename}</div>
                        <div className="font-mono text-[11px] text-ink-faint">{d.code ?? "—"} · {d.filename}</div>
                      </td>
                      <td className="text-ink-soft">{DOCTYPE_RU[d.doc_type] ?? "не определён"}{d.doc_type_confidence < 0.9 && d.doc_type && <span className="text-ink-faint"> (?)</span>}</td>
                      <td>
                        <Badge tone={STATUS[d.status]?.[1] ?? "neutral"}>{STATUS[d.status]?.[0] ?? d.status}</Badge>
                        {d.is_synthetic && <Badge className="ml-1">синт.</Badge>}
                        {d.metadata?.ocr_confidence != null && <Badge tone={d.metadata.ocr_confidence < 0.8 ? "high" : "neutral"} className="ml-1"
                          title={[d.metadata.ocr_confidence < 0.8 ? "Низкая уверенность OCR — сверьте числа с первоисточником." : "Документ распознан OCR.",
                                  d.metadata.preprocessing?.length ? "Предобработка: " + d.metadata.preprocessing.join(", ") : ""].join(" ")}>
                          OCR {Math.round(d.metadata.ocr_confidence * 100)}%</Badge>}
                        {d.injection_flags > 0 && <Badge tone="high" className="ml-1" title="Фрагменты с признаками инструкций для ИИ исключены из анализа"><AlertTriangle className="h-3 w-3" />инъекция</Badge>}
                        {d.error && <div className="mt-1 max-w-xs text-xs text-crit">{d.error}</div>}
                      </td>
                      <td className="text-right tabular">{d.fragments}</td>
                      <td className="text-right tabular">{d.requirements}</td>
                      <td className="text-right"><button className="text-xs text-navy-600 hover:underline" onClick={(e) => { e.stopPropagation(); download(`/projects/${project}/documents/${d.id}/file`, d.filename); }}>файл</button></td>
                    </tr>
                  ))}</tbody>
                </table>
              </Card>
            )}
          </div>
        </div>
        {sel && <DocPanel id={sel} onClose={() => setSel(null)} />}
      </div>
    </div>
  );
}

function DocPanel({ id, onClose }: { id: string; onClose: () => void }) {
  const { project } = useApp();
  const { data, loading, error } = useApi<any>(`/projects/${project}/documents/${encodeURIComponent(id)}`, [id]);
  const [tab, setTab] = useState<"req" | "frag" | "ent">("req");
  const reqFrags = useMemo(() => new Set((data?.requirements ?? []).flatMap((r: any) => r.evidence.map((e: any) => e.fragment_id))), [data]);
  return (
    <aside className="flex w-[520px] shrink-0 flex-col border-l border-line bg-surface">
      <div className="flex items-start justify-between gap-2 border-b border-line px-4 py-3">
        <div>
          <div className="font-semibold">{data?.document.title ?? "…"}</div>
          <div className="font-mono text-[11px] text-ink-faint">{data?.document.code} · {data?.document.filename} · sha256 {data?.document.sha256.slice(0, 12)}</div>
        </div>
        <button onClick={onClose} className="rounded p-1 hover:bg-canvas"><X className="h-4 w-4" /></button>
      </div>
      <div className="flex gap-1 border-b border-line px-3 pt-2">
        {([["req", `Требования (${data?.requirements.length ?? 0})`], ["frag", `Фрагменты (${data?.fragments.length ?? 0})`], ["ent", `Сущности (${data?.entities.length ?? 0})`]] as const).map(([k, l]) => (
          <button key={k} onClick={() => setTab(k)} className={cn("rounded-t px-3 py-1.5 text-sm", tab === k ? "border border-b-0 border-line bg-surface font-medium" : "text-ink-soft hover:text-ink")}>{l}</button>
        ))}
      </div>
      <div className="min-h-0 flex-1 overflow-auto p-4">
        {loading && <Spinner />}<ErrorBox error={error} />
        {data && tab === "req" && (data.requirements.length === 0 ? <Empty title="Требования не извлечены" /> : (
          <div className="space-y-3">{data.requirements.map((r: any) => (
            <div key={r.id} className="rounded border border-line p-2.5">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="font-medium">{PARAM_RU[r.parameter] ?? r.parameter}</span>
                <span className="font-mono text-sm">{fmtReq(r)}</span>
                <Badge tone="navy">{KIND_RU[r.kind]}</Badge>
                {r.section && <span className="text-xs text-ink-faint">п. {r.section}</span>}
                <span className="ml-auto text-xs text-ink-faint tabular">уверенность {Math.round(r.confidence * 100)}%</span>
              </div>
              <div className="mt-1 text-xs text-ink-faint">исходно: «{r.value_original}» · единица «{r.unit_original}»</div>
              <div className="mt-1.5"><EvidenceQuote ev={{ ...r.evidence[0], filename: data.document.filename, code: data.document.code }} /></div>
            </div>
          ))}</div>
        ))}
        {data && tab === "frag" && (
          <div className="space-y-1">{data.fragments.map((f: any) => (
            <div key={f.id} className={cn("rounded px-2 py-1 text-[12.5px]", f.kind === "heading" && "font-semibold", reqFrags.has(f.id) && "bg-navy-50", f.flags.includes("suspected_injection") && "bg-high/10")}>
              <span className="mr-2 font-mono text-[10.5px] text-ink-faint">{f.locator}</span>{f.text}
              {f.flags.includes("suspected_injection") && <Badge tone="high" className="ml-2">исключён: инструкция для ИИ</Badge>}
            </div>
          ))}</div>
        )}
        {data && tab === "ent" && (
          <table className="tbl"><tbody>{data.entities.map((e: any) => (
            <tr key={e.id}><td>{e.name}</td><td className="text-xs text-ink-faint">{TYPE_RU[e.type] ?? e.type}</td></tr>
          ))}</tbody></table>
        )}
      </div>
    </aside>
  );
}
