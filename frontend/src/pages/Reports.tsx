import { Download } from "lucide-react";
import { Link } from "react-router-dom";
import { Button, Card, CardHeader, Empty, ErrorBox, PageHeader, Spinner } from "@/components/ui";
import { download } from "@/lib/api";
import { useApp } from "@/lib/context";
import { useApi } from "@/lib/hooks";

export default function Reports() {
  const { project } = useApp();
  const { data, error, loading } = useApi<any[]>(`/projects/${project}/impact`, [project]);
  return (
    <div>
      <PageHeader title="Отчёты" sub="Отчёты об оценке последствий изменений и реестр противоречий в форматах DOCX и PDF" />
      <div className="space-y-4 p-6">
        <Card>
          <CardHeader title="Реестр противоречий" sub="Все обнаруженные противоречия с объяснениями и двумя источниками" right={<div className="flex gap-2">
            <Button size="sm" onClick={() => download(`/projects/${project}/contradictions/export?fmt=docx`, "contradictions.docx")}><Download className="h-3.5 w-3.5" />DOCX</Button>
            <Button size="sm" onClick={() => download(`/projects/${project}/contradictions/export?fmt=pdf`, "contradictions.pdf")}><Download className="h-3.5 w-3.5" />PDF</Button></div>} />
        </Card>
        <Card>
          <CardHeader title="Анализы последствий изменений" />
          <ErrorBox error={error} />
          {loading && !data ? <Spinner /> : !data?.length ? <Empty title="Отчётов пока нет">Запустите анализ на странице «Анализ изменений».</Empty> : (
            <table className="tbl">
              <thead><tr><th>Изменение</th><th>Автор</th><th>Дата</th><th /></tr></thead>
              <tbody>{data.map((r) => (
                <tr key={r.id}>
                  <td><Link className="text-navy-600 hover:underline" to={`/impact?report=${r.id}`}>{r.summary}</Link></td>
                  <td className="text-ink-soft">{r.user}</td>
                  <td className="whitespace-nowrap text-ink-soft">{new Date(r.created_at).toLocaleString("ru")}</td>
                  <td className="whitespace-nowrap text-right">
                    <Button size="sm" variant="ghost" onClick={() => download(`/projects/${project}/impact/${r.id}/export?fmt=docx`, "impact_report.docx")}>DOCX</Button>
                    <Button size="sm" variant="ghost" onClick={() => download(`/projects/${project}/impact/${r.id}/export?fmt=pdf`, "impact_report.pdf")}>PDF</Button>
                  </td>
                </tr>
              ))}</tbody>
            </table>
          )}
        </Card>
      </div>
    </div>
  );
}
