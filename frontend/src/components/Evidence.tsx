import { ExternalLink } from "lucide-react";
import { download } from "@/lib/api";
import { useApp } from "@/lib/context";

export type Ev = { document_id: string; filename?: string | null; code?: string | null; page?: number | null; locator?: string | null; quote: string; method?: string; rule?: string; confidence?: number; ocr_confidence?: number | null };

export function EvidenceQuote({ ev, n }: { ev: Ev; n?: number }) {
  const { project } = useApp();
  return (
    <div className="quote">
      <div className="mb-0.5 flex flex-wrap items-center gap-x-2 text-[11px] text-ink-faint">
        {n !== undefined && <span className="font-mono text-navy-600">[{n}]</span>}
        <span className="font-medium text-ink-soft">{ev.code ?? ev.filename}</span>
        {ev.locator && <span>{ev.locator}</span>}
        {ev.method && <span className="font-mono">{ev.method}{ev.rule ? `:${ev.rule}` : ""}</span>}
        {ev.ocr_confidence != null && <span className={ev.ocr_confidence < 0.8 ? "rounded bg-amber-100 px-1 text-amber-800" : ""}
          title={ev.ocr_confidence < 0.8 ? "Низкая уверенность распознавания: сверьте числа с первоисточником" : "Фрагмент распознан OCR"}>
          OCR {Math.round(ev.ocr_confidence * 100)}%{ev.ocr_confidence < 0.8 ? " — сверить" : ""}</span>}
        <button className="ml-auto inline-flex items-center gap-0.5 text-navy-600 hover:underline"
          onClick={() => download(`/projects/${project}/documents/${ev.document_id}/file`, ev.filename ?? "document")}>
          первоисточник <ExternalLink className="h-3 w-3" />
        </button>
      </div>
      «{ev.quote}»
    </div>
  );
}
