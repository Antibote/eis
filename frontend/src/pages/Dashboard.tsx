import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Badge, Button, Card, CardHeader, Empty, ErrorBox, PageHeader, SEVERITY_RU, SEVERITY_TONE, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { useApp } from "@/lib/context";
import { useApi } from "@/lib/hooks";
import { useState } from "react";

const ACTION_RU: Record<string, string> = {
  load_demo: "загрузка демонстрационного набора", upload: "загрузка документов", impact_analysis: "анализ изменения",
  review_contradiction: "решение по противоречию", export_report: "экспорт отчёта", assistant: "запрос к помощнику",
  download: "открытие первоисточника", delete_document: "удаление документа",
};

function Kpi({ label, value, sub, to }: { label: string; value: number | string; sub?: string; to?: string }) {
  const body = (
    <Card className="px-4 py-3 transition-colors hover:border-navy-500/40">
      <div className="label">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular tracking-tight">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-ink-faint">{sub}</div>}
    </Card>
  );
  return to ? <Link to={to}>{body}</Link> : body;
}

export default function Dashboard() {
  const { project, user } = useApp();
  const { data, error, loading, reload } = useApi<any>(`/projects/${project}/dashboard`, [project]);
  const [busy, setBusy] = useState(false);
  const loadDemo = async () => { setBusy(true); try { await api(`/projects/${project}/demo`, { method: "POST" }); await reload(); } finally { setBusy(false); } };
  if (loading && !data) return <Spinner />;
  if (error) return <div className="p-6"><ErrorBox error={error} /></div>;
  if (!data) return null;
  const rel = Object.entries(data.relations_by_type as Record<string, number>).filter(([k]) => !["CHARACTERIZES"].includes(k))
    .map(([type, n]) => ({ type, n })).sort((a, b) => b.n - a.n);
  return (
    <div>
      <PageHeader title="Обзор проекта" sub="Состояние базы знаний, построенной из загруженной документации"
        right={data.synthetic && <Badge tone="dark">синтетические данные для демонстрации</Badge>} />
      {data.documents === 0 ? (
        <Card className="m-6"><Empty title="В проекте нет документов">
          Загрузите документацию на странице «Документы» или используйте демонстрационный набор — 14 синтетических документов насосного агрегата НА-200.
          {project === "demo" && user?.role !== "viewer" && <div className="mt-4"><Button variant="primary" loading={busy} onClick={loadDemo}>Загрузить демонстрационный набор</Button></div>}
        </Empty></Card>
      ) : (
        <div className="space-y-4 p-6">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
            <Kpi label="Документы" value={data.documents} sub={data.documents_failed ? `не обработано: ${data.documents_failed}` : "все обработаны"} to="/documents" />
            <Kpi label="Требования" value={data.requirements} sub={`ограничений: ${data.requirements_by_kind.capability ?? 0}`} to="/documents" />
            <Kpi label="Компоненты" value={data.components} sub={`материалов: ${data.materials}`} to="/graph" />
            <Kpi label="Испытания" value={data.tests} />
            <Kpi label="Связи графа" value={data.relations} to="/graph" />
            <Kpi label="Противоречия" value={data.contradictions} sub={`подтверждено: ${data.contradictions_by_status.confirmed ?? 0}`} to="/contradictions" />
          </div>
          <div className="grid gap-4 lg:grid-cols-3">
            <Card className="lg:col-span-2">
              <CardHeader title="Связи графа знаний по типам" sub="Каждая связь имеет основание: документ, фрагмент или правило" />
              <div className="h-64 px-2 py-3">
                <ResponsiveContainer>
                  <BarChart data={rel} layout="vertical" margin={{ left: 40, right: 16 }}>
                    <CartesianGrid horizontal={false} stroke="#E6E9ED" />
                    <XAxis type="number" tick={{ fontSize: 11, fill: "#7A8290" }} axisLine={false} tickLine={false} />
                    <YAxis type="category" dataKey="type" width={110} interval={0} tick={{ fontSize: 11, fill: "#4A5260", fontFamily: "IBM Plex Mono" }} axisLine={false} tickLine={false} />
                    <Tooltip cursor={{ fill: "#EEF2F7" }} contentStyle={{ fontSize: 12, borderRadius: 4, borderColor: "#DCE0E5" }} formatter={(v) => [v, "связей"]} />
                    <Bar dataKey="n" fill="#244A75" radius={[0, 2, 2, 0]} barSize={14} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Card>
            <Card>
              <CardHeader title="Противоречия по серьёзности" right={<Link className="text-xs text-navy-600 hover:underline" to="/contradictions">открыть</Link>} />
              <div className="space-y-2 p-4">
                {["critical", "high", "medium", "low"].map((s) => {
                  const n = data.contradictions_by_severity[s] ?? 0;
                  const pct = data.contradictions ? (n / data.contradictions) * 100 : 0;
                  return (
                    <div key={s} className="flex items-center gap-3">
                      <Badge tone={SEVERITY_TONE[s]} className="w-24 justify-center">{SEVERITY_RU[s]}</Badge>
                      <div className="h-2 flex-1 overflow-hidden rounded-full bg-canvas"><div className="h-full bg-navy-600" style={{ width: `${pct}%` }} /></div>
                      <span className="w-6 text-right tabular text-sm">{n}</span>
                    </div>
                  );
                })}
              </div>
            </Card>
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader title="Последние результаты анализа изменений" right={<Link className="text-xs text-navy-600 hover:underline" to="/impact">новый анализ</Link>} />
              {data.recent_reports.length === 0 ? <Empty title="Анализов ещё не было" /> : (
                <table className="tbl"><tbody>{data.recent_reports.map((r: any) => (
                  <tr key={r.id}><td>{r.summary}</td><td className="whitespace-nowrap text-right text-xs text-ink-faint">{new Date(r.created_at).toLocaleString("ru")}</td></tr>
                ))}</tbody></table>
              )}
            </Card>
            <Card>
              <CardHeader title="Журнал операций" />
              <table className="tbl"><tbody>{data.recent_events.map((e: any, i: number) => (
                <tr key={i}><td className="w-36 whitespace-nowrap text-xs text-ink-faint">{new Date(e.ts).toLocaleString("ru")}</td><td>{ACTION_RU[e.action] ?? e.action}</td><td className="text-xs text-ink-faint">{e.user}</td></tr>
              ))}</tbody></table>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}
