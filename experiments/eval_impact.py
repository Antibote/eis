"""Эксперимент E2: определение последствий изменений (5 сценариев × методы M1–M4 + абляции M4).

Запуск: python experiments/eval_impact.py --variant test [--embedder tfidf]
Результаты: experiments/results/E2_impact_<variant>.json и .md
"""
from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict

from common import ROOT, IdMap, PRF, build_kb, git_commit, load_gold, load_manifest
from methods import GraphMethod, HybridMethod, KeywordMethod, RagMethod

from eis.graph.store import build_graph
from eis.rag.retriever import HybridRetriever, default_embedder
from eis.services.impact import ImpactSettings


def chain_recall(chains, reached, idm, req_id_of):
    ok = 0
    for ch in chains:
        nodes = [req_id_of.get(x, idm(x)) if x.startswith("R") else idm(x) for x in ch]
        ok += all(n in reached for n in nodes)
    return ok / len(chains) if chains else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="test")
    ap.add_argument("--embedder", default=None, help="tfidf | имя модели sentence-transformers")
    ap.add_argument("--k", type=int, default=10)
    a = ap.parse_args()
    gold = load_gold(a.variant)
    kb = build_kb(a.variant)
    g = build_graph(kb)
    idm = IdMap(gold, kb)
    # эталонные требования → требования системы (для цепочек)
    from eval_extraction import gold_req_key, req_key
    req_id_of = {}
    for gr in gold["requirements"]:
        k = gold_req_key(gr, idm)
        for r in kb.requirements.values():
            if req_key(r.subject_id, r.parameter, r.operator, r.value, r.low, r.high, r.document_id) == k:
                req_id_of[gr["id"]] = r.id
    t0 = time.perf_counter()
    emb = default_embedder(a.embedder)
    retr = HybridRetriever(kb, emb)
    t_index = time.perf_counter() - t0

    methods = [
        KeywordMethod(kb, g, retr, k=a.k),
        RagMethod(kb, g, retr, k=a.k),
        GraphMethod(kb, g, depth=2),
        GraphMethod(kb, g, depth=3),
        HybridMethod(kb, g),
        HybridMethod(kb, g, include_classes={"confirmed", "direct"}, name="M4_hybrid_direct_only"),
        HybridMethod(kb, g, ImpactSettings(use_physics=False), name="M4_ablation_no_physics"),
        HybridMethod(kb, g, ImpactSettings(use_doc_filter=False), name="M4_ablation_no_doc_filter"),
        HybridMethod(kb, g, ImpactSettings(use_load_path=False), name="M4_ablation_no_load_path"),
        HybridMethod(kb, g, ImpactSettings(use_checks=False), name="M4_ablation_no_checks"),
    ]
    methods[2].name, methods[3].name = "M3_graph_d2", "M3_graph_d3"
    results = {}
    for m in methods:
        agg = defaultdict(PRF)
        per = []
        chains, times, claims, supported = [], [], 0, 0
        for sc in gold["scenarios"]:
            t = time.perf_counter()
            out = m.run(sc["text"])
            times.append((time.perf_counter() - t) * 1000)
            gc = {idm(x) for x in sc["affected_components"]}
            gd = {idm(x) for x in sc["documents"]}
            gt = {idm(x) for x in sc["tests"]}
            row = {"scenario": sc["id"],
                   "components": PRF().add_sets(out.components, gc).row(),
                   "documents": PRF().add_sets(out.documents, gd).row(),
                   "tests": PRF().add_sets(out.tests, gt).row(),
                   "chain_recall": round(chain_recall(sc["chains"], out.reached, idm, req_id_of), 4),
                   "fp_components": sorted(kb.entities[x].name for x in out.components - gc),
                   "fn_components": sorted(kb.entities[x].name if x in kb.entities else x for x in gc - out.components),
                   "fp_documents": sorted(kb.documents[x].filename for x in out.documents - gd if x in kb.documents),
                   "fn_documents": sorted(x for x in gd - out.documents)}
            agg["components"].add_sets(out.components, gc)
            agg["documents"].add_sets(out.documents, gd)
            agg["tests"].add_sets(out.tests, gt)
            if out.violations is not None:
                gv = {idm(x) for x in sc["violations"]}
                row["violations"] = PRF().add_sets(out.violations, gv).row()
                agg["violations"].add_sets(out.violations, gv)
            chains.append(row["chain_recall"])
            claims += out.claims
            supported += out.supported_claims
            per.append(row)
        macro_c = sum(r["components"]["f1"] for r in per) / len(per)
        results[m.name] = {
            "micro": {k: v.row() for k, v in agg.items()},
            "macro_f1_components": round(macro_c, 4),
            "chain_recall_mean": round(sum(chains) / len(chains), 4),
            "supported_claims_share": round(supported / claims, 4) if claims else None,
            "time_ms_mean": round(sum(times) / len(times), 2),
            "per_scenario": per,
        }
    man = load_manifest(a.variant)
    res = {"experiment": "E2_impact", "variant": a.variant, "dataset_hash": man["dataset_hash"], "commit": git_commit(),
           "embedder": emb.name, "k": a.k, "index_seconds": round(t_index, 2),
           "failed_documents": [d.filename for d in kb.documents.values() if d.status == "failed"], "methods": results}
    out = ROOT / "experiments" / "results" / f"E2_impact_{a.variant}.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = [f"# E2 — последствия изменений ({a.variant}, датасет {man['dataset_hash']}, эмбеддинги {emb.name})", "",
             "| Метод | Компоненты P | R | F1 | Документы P | R | F1 | Испытания F1 | Нарушения F1 | Цепочки | мс |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, r in results.items():
        c, d, t = r["micro"]["components"], r["micro"]["documents"], r["micro"]["tests"]
        v = r["micro"].get("violations")
        lines.append(f"| {name} | {c['precision']:.2f} | {c['recall']:.2f} | {c['f1']:.2f} | {d['precision']:.2f} | "
                     f"{d['recall']:.2f} | {d['f1']:.2f} | {t['f1']:.2f} | {v['f1'] if v else '—'} | "
                     f"{r['chain_recall_mean']:.2f} | {r['time_ms_mean']:.1f} |")
    (out.with_suffix(".md")).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
