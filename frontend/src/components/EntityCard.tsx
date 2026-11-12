import { X } from "lucide-react";
import { EvidenceQuote } from "@/components/Evidence";
import { Badge, ErrorBox, Spinner } from "@/components/ui";
import { useApp } from "@/lib/context";
import { useApi } from "@/lib/hooks";
import { KIND_RU, PARAM_RU, TYPE_RU, fmtReq } from "@/lib/utils";

export default function EntityCard({ id, onClose, onFocus }: { id: string; onClose: () => void; onFocus?: (id: string) => void }) {
  const { project } = useApp();
  const { data, loading, error } = useApi<any>(`/projects/${project}/entities/${encodeURIComponent(id)}`, [id]);
  const e = data?.entity;
  const rels = data ? [...data.outgoing.map((r: any) => ({ ...r, dir: "→" })), ...data.incoming.map((r: any) => ({ ...r, dir: "←" }))]
    .filter((r: any) => r.type !== "DOCUMENTED_IN") : [];
  const docs = data ? data.outgoing.filter((r: any) => r.type === "DOCUMENTED_IN") : [];
  return (
    <aside className="flex w-[440px] shrink-0 flex-col border-l border-line bg-surface">
      <div className="flex items-start justify-between gap-2 border-b border-line px-4 py-3">
        <div className="min-w-0">
          <div className="label">{e ? TYPE_RU[e.type] ?? e.type : ""}</div>
          <div className="font-semibold">{e?.name ?? "…"}</div>
          {e?.designation && <div className="font-mono text-[11px] text-ink-faint">{e.designation}</div>}
        </div>
        <button onClick={onClose} className="rounded p-1 hover:bg-canvas"><X className="h-4 w-4" /></button>
      </div>
      <div className="min-h-0 flex-1 space-y-4 overflow-auto p-4">
        {loading && <Spinner />}<ErrorBox error={error} />
        {data?.requirements.length > 0 && (
          <section>
            <div className="label mb-1.5">Требования и ограничения</div>
            <div className="space-y-1.5">{data.requirements.map((r: any) => (
              <div key={r.id} className="flex items-center gap-2 text-sm">
                <span>{PARAM_RU[r.parameter] ?? r.parameter}</span><span className="font-mono">{fmtReq(r)}</span><Badge tone="navy">{KIND_RU[r.kind]}</Badge>
              </div>
            ))}</div>
          </section>
        )}
        {rels.length > 0 && (
          <section>
            <div className="label mb-1.5">Связи</div>
            <div className="space-y-2">{rels.map((r: any) => (
              <details key={r.id + r.dir} className="rounded border border-line">
                <summary className="flex cursor-pointer items-center gap-2 px-2.5 py-1.5 text-sm">
                  <span className="font-mono text-[11px] text-navy-600">{r.dir} {r.type}</span>
                  <button className="truncate text-left hover:underline" onClick={(ev) => { ev.preventDefault(); onFocus?.(r.other); }}>{r.other_name}</button>
                </summary>
                <div className="space-y-1.5 px-2.5 pb-2.5">{r.evidence.map((ev: any, i: number) => <EvidenceQuote key={i} ev={ev} />)}</div>
              </details>
            ))}</div>
          </section>
        )}
        {docs.length > 0 && (
          <section>
            <div className="label mb-1.5">Документы-источники</div>
            <div className="space-y-1.5">{docs.map((r: any) => <EvidenceQuote key={r.id} ev={r.evidence[0]} />)}</div>
          </section>
        )}
      </div>
    </aside>
  );
}
