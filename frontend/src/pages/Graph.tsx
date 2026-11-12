import dagre from "@dagrejs/dagre";
import { Background, Controls, MarkerType, MiniMap, ReactFlow, type Edge, type Node } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useEffect, useMemo, useState } from "react";
import EntityCard from "@/components/EntityCard";
import { Badge, Button, ErrorBox, PageHeader, Spinner } from "@/components/ui";
import { useApp } from "@/lib/context";
import { useApi } from "@/lib/hooks";
import { TYPE_RU, cn } from "@/lib/utils";

const NODE_STYLE: Record<string, { bg: string; border: string; text: string }> = {
  Product: { bg: "#0F2034", border: "#0F2034", text: "#fff" },
  Assembly: { bg: "#244A75", border: "#244A75", text: "#fff" },
  Component: { bg: "#FFFFFF", border: "#2F5A8A", text: "#1A1E24" },
  Material: { bg: "#F1F3F5", border: "#8A93A0", text: "#2E333B" },
  Constraint: { bg: "#FFF8EB", border: "#D9A441", text: "#5C3D05" },
  TechnicalRequirement: { bg: "#EEF2F7", border: "#9FB3CC", text: "#1C3A5E" },
  Test: { bg: "#ECF7F1", border: "#4B9B73", text: "#0B4D2E" },
  EngineeringDocument: { bg: "#F7F7F7", border: "#B5BBC3", text: "#4A5260" },
  Standard: { bg: "#F7F7F7", border: "#D0D4DA", text: "#7A8290" },
  ChangeRequest: { bg: "#F7F0FA", border: "#A57FBF", text: "#4A2A60" },
};
const EDGE_COLOR: Record<string, string> = {
  CONTAINS: "#8A93A0", DEPENDS_ON: "#C4320A", USES_MATERIAL: "#6B7280", DERIVED_FROM: "#7C3AED", VERIFIED_BY: "#067647",
  CONSTRAINS: "#9FB3CC", CHARACTERIZES: "#D9A441", DOCUMENTED_IN: "#D0D4DA", SUPERSEDES: "#A57FBF", AFFECTS: "#A57FBF",
};
const ALL_NODE_TYPES = Object.keys(NODE_STYLE);
const ALL_EDGE_TYPES = Object.keys(EDGE_COLOR);
const IMPACT_COLOR: Record<string, string> = { confirmed: "#B42318", direct: "#244A75", potential: "#B54708" };

function layout(nodes: any[], edges: any[]) {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: "LR", nodesep: 14, ranksep: 90, marginx: 20, marginy: 20 });
  g.setDefaultEdgeLabel(() => ({}));
  nodes.forEach((n) => g.setNode(n.id, { width: 190, height: 36 }));
  edges.forEach((e) => g.setEdge(e.source, e.target));
  dagre.layout(g);
  return (id: string) => { const p = g.node(id); return p ? { x: p.x - 95, y: p.y - 18 } : { x: 0, y: 0 }; };
}

export default function Graph() {
  const { project, lastImpact, setLastImpact } = useApp();
  const [nodeTypes, setNodeTypes] = useState<Set<string>>(new Set(["Product", "Assembly", "Component", "Material", "Constraint"]));
  const [edgeTypes, setEdgeTypes] = useState<Set<string>>(new Set(["CONTAINS", "DEPENDS_ON", "USES_MATERIAL", "DERIVED_FROM", "VERIFIED_BY", "CONSTRAINS", "CHARACTERIZES"]));
  const [focus, setFocus] = useState<string | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  const q = `/projects/${project}/graph?node_types=${[...nodeTypes].join(",")}&edge_types=${[...edgeTypes].join(",")}${focus ? `&focus=${encodeURIComponent(focus)}&depth=2` : ""}`;
  const { data, loading, error } = useApi<any>(q, [q]);

  const impact = useMemo(() => {
    const m = new Map<string, string>(); const pathEdges = new Set<string>(); const onPath = new Set<string>();
    if (lastImpact) {
      lastImpact.items.forEach((it: any) => {
        m.set(it.entity_id, it.impact_class);
        const ids = it.path.map((s: any) => s.node);
        ids.forEach((x: string) => onPath.add(x));
        for (let i = 1; i < ids.length; i++) { pathEdges.add(`${ids[i - 1]}|${ids[i]}`); pathEdges.add(`${ids[i]}|${ids[i - 1]}`); }
      });
      m.set(lastImpact.requirement_id, "source");
    }
    return { m, pathEdges, onPath };
  }, [lastImpact]);

  const { nodes, edges } = useMemo(() => {
    if (!data) return { nodes: [] as Node[], edges: [] as Edge[] };
    // в режиме анализа показываем только затронутую подсеть: элементы, узлы их цепочек и изделие
    const ns = lastImpact && !focus ? data.nodes.filter((n: any) => impact.m.has(n.id) || impact.onPath.has(n.id) || n.type === "Product") : data.nodes;
    const visible = new Set(ns.map((n: any) => n.id));
    const es = data.edges.filter((e: any) => visible.has(e.source) && visible.has(e.target));
    const pos = layout(ns, es);
    const nodes: Node[] = ns.map((n: any) => {
      const st = NODE_STYLE[n.type] ?? NODE_STYLE.Standard;
      const imp = impact.m.get(n.id);
      const ring = imp === "source" ? "#0F2034" : imp ? IMPACT_COLOR[imp] : null;
      return {
        id: n.id, position: pos(n.id),
        data: { label: n.name.length > 42 ? n.name.slice(0, 40) + "…" : n.name },
        style: {
          width: 190, fontSize: 11, lineHeight: "14px", padding: "6px 8px", borderRadius: 4, background: st.bg, color: st.text,
          border: `1px solid ${st.border}`, boxShadow: ring ? `0 0 0 3px ${ring}` : undefined,
          opacity: lastImpact && !imp && !impact.onPath.has(n.id) && n.type !== "Product" ? 0.35 : 1,
        },
      };
    });
    const edges: Edge[] = es.map((e: any) => {
      const hot = impact.pathEdges.has(`${e.source}|${e.target}`);
      return {
        id: e.id, source: e.source, target: e.target, type: "smoothstep",
        style: { stroke: hot ? "#B42318" : EDGE_COLOR[e.type] ?? "#999", strokeWidth: hot ? 2.2 : 1, opacity: lastImpact && !hot ? 0.3 : 0.9 },
        markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: hot ? "#B42318" : EDGE_COLOR[e.type] },
        label: e.type === "DEPENDS_ON" || hot ? e.type : undefined,
        labelStyle: { fontSize: 9, fontFamily: "IBM Plex Mono", fill: "#4A5260" },
        labelBgStyle: { fill: "#F4F5F7" },
      };
    });
    return { nodes, edges };
  }, [data, impact, lastImpact, focus]);

  useEffect(() => { setSel(null); }, [project]);
  const toggle = (set: Set<string>, setter: (s: Set<string>) => void, k: string) => { const s = new Set(set); s.has(k) ? s.delete(k) : s.add(k); setter(s); };

  return (
    <div className="flex h-full flex-col">
      <PageHeader title="Граф знаний" sub={data ? `${data.stats.nodes} узлов, ${data.stats.edges} связей в базе знаний; показано ${nodes.length} узлов и ${edges.length} связей` : "…"}
        right={<>
          {focus && <Button size="sm" onClick={() => setFocus(null)}>Показать весь граф</Button>}
          {lastImpact && <Button size="sm" onClick={() => setLastImpact(null)}>Снять выделение анализа</Button>}
        </>} />
      <div className="flex flex-wrap gap-x-6 gap-y-2 border-b border-line bg-surface px-6 py-2 text-xs">
        <div className="flex flex-wrap items-center gap-1"><span className="label mr-1">Узлы</span>
          {ALL_NODE_TYPES.map((t) => (
            <button key={t} onClick={() => toggle(nodeTypes, setNodeTypes, t)}
              className={cn("flex items-center gap-1 rounded border px-1.5 py-0.5", nodeTypes.has(t) ? "border-navy-500/40 bg-navy-50 text-ink" : "border-line text-ink-faint")}>
              <span className="h-2.5 w-2.5 rounded-sm border" style={{ background: NODE_STYLE[t].bg, borderColor: NODE_STYLE[t].border }} />{TYPE_RU[t] ?? t}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-1"><span className="label mr-1">Связи</span>
          {ALL_EDGE_TYPES.map((t) => (
            <button key={t} onClick={() => toggle(edgeTypes, setEdgeTypes, t)}
              className={cn("flex items-center gap-1 rounded border px-1.5 py-0.5 font-mono text-[10.5px]", edgeTypes.has(t) ? "border-navy-500/40 bg-navy-50 text-ink" : "border-line text-ink-faint")}>
              <span className="h-0.5 w-3" style={{ background: EDGE_COLOR[t] }} />{t}
            </button>
          ))}
        </div>
        {lastImpact && (
          <div className="flex items-center gap-2">
            <span className="label">Анализ</span>
            <Badge tone="crit">подтверждённое</Badge><Badge tone="navy">прямое</Badge><Badge tone="med">потенциальное</Badge>
          </div>
        )}
      </div>
      <ErrorBox error={error} />
      <div className="flex min-h-0 flex-1">
        <div className="relative min-w-0 flex-1">
          {loading && !data && <Spinner />}
          <ReactFlow nodes={nodes} edges={edges} fitView minZoom={0.1} maxZoom={2} onNodeClick={(_, n) => setSel(n.id)}
            onNodeDoubleClick={(_, n) => setFocus(n.id)} proOptions={{ hideAttribution: true }} nodesConnectable={false}>
            <Background gap={20} size={1} color="#E3E6EA" />
            <Controls showInteractive={false} />
            <MiniMap pannable zoomable nodeColor={(n) => (n.style?.background as string) ?? "#ccc"} maskColor="rgba(244,245,247,0.7)" />
          </ReactFlow>
          <div className="pointer-events-none absolute bottom-3 left-14 text-[11px] text-ink-faint">клик — карточка сущности · двойной клик — окрестность узла</div>
        </div>
        {sel && <EntityCard id={sel} onClose={() => setSel(null)} onFocus={(id) => { setFocus(id); setSel(id); }} />}
      </div>
    </div>
  );
}
