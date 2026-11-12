"""Эксперимент E3: обнаружение противоречий.

Методы:
  C1_similarity — без структурирования: пары фрагментов из разных документов с косинусным сходством ≥ τ,
                  содержащие разные числа (типичный «наивный RAG»-подход);
  C2_formal     — уровень 1: сравнение требований одной характеристики (без графа);
  C3_hybrid     — уровни 1+3: формальные правила + проверки по графу (зависимости, материалы, состав).
  (уровень 2 — LLM — запускается отдельно при наличии модели; здесь не измеряется)

Метрики: полнота по внесённым противоречиям (K01–K10), точность по найденным элементам,
срабатывания на ловушках (distractors).
"""
from __future__ import annotations

import argparse
import json
import re
from itertools import combinations

import numpy as np
from common import ROOT, IdMap, PRF, build_kb, git_commit, load_gold, load_manifest

from eis.graph.store import build_graph
from eis.rag.retriever import HybridRetriever, default_embedder
from eis.services.contradictions import ContradictionDetector

NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")


def gold_item_map(gold, kb, idm):
    from eval_extraction import gold_req_key, req_key
    m = {}
    for gr in gold["requirements"]:
        k = gold_req_key(gr, idm)
        for r in kb.requirements.values():
            if req_key(r.subject_id, r.parameter, r.operator, r.value, r.low, r.high, r.document_id) == k:
                m[gr["id"]] = r.id
    for rel in kb.relations.values():
        if rel.type.value == "USES_MATERIAL":
            for c in gold["entities"]["components"]:
                for mt in gold["entities"]["materials"]:
                    if rel.source == idm(c["id"]) and rel.target == idm(mt["id"]):
                        m[f"{c['id']}:{mt['id']}"] = rel.id
    return m


def item_fragments(kb, item_id):
    if item_id in kb.requirements:
        return {e.fragment_id for e in kb.requirements[item_id].evidence}
    if item_id in kb.relations:
        return {e.fragment_id for e in kb.relations[item_id].evidence}
    return set()


def score(found_items: list[set[str]], gold, gmap, distractor_sets):
    """found_items — список множеств id (требования/связи/фрагменты) для каждого найденного противоречия."""
    detected_k, matched = set(), 0
    for items in found_items:
        hit = False
        for k in gold["contradictions"]:
            for pair in k["pairs"]:
                ids = [gmap.get(x) for x in pair]
                if all(ids) and set(ids) <= items:
                    detected_k.add(k["id"])
                    hit = True
        matched += hit
    dist = sum(any(ds <= items for items in found_items) for ds in distractor_sets)
    n = len(gold["contradictions"])
    p = matched / len(found_items) if found_items else 0.0
    r = len(detected_k) / n
    return {"found": len(found_items), "matched_found": matched, "precision": round(p, 4),
            "recall": round(r, 4), "f1": round(2 * p * r / (p + r), 4) if p + r else 0.0,
            "detected": sorted(detected_k), "missed": sorted({k["id"] for k in gold["contradictions"]} - detected_k),
            "distractor_hits": dist}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="test")
    ap.add_argument("--tau", type=float, default=0.88)
    a = ap.parse_args()
    gold = load_gold(a.variant)
    kb = build_kb(a.variant)
    g = build_graph(kb)
    idm = IdMap(gold, kb)
    gmap = gold_item_map(gold, kb, idm)
    distractor_sets = []
    for d in gold["distractors"]:
        ids = [gmap.get(x) for x in d["pair"]]
        if all(ids):
            distractor_sets.append(set(ids))
    res = {}
    # C3 и C2
    full = ContradictionDetector(kb, g).run()
    res["C3_hybrid"] = score([set(c.items) for c in full], gold, gmap, distractor_sets)
    det = ContradictionDetector(kb, g)
    det._dependents = lambda subj, param: {subj}          # без графовых зависимостей
    det.value_mismatches(); det.capability_violations(); det.setpoints()
    res["C2_formal"] = score([set(c.items) for c in det.out.values()], gold, gmap, distractor_sets)
    # C1: сходство фрагментов; порог подбирается по лучшему F1 (в пользу базового метода), кривая сохраняется
    emb = default_embedder()
    retr = HybridRetriever(kb, emb)
    frags = [f for f in retr.frags if NUM_RE.search(f.text)]
    idx = {f.id: i for i, f in enumerate(retr.frags)}
    pairs = []
    for f1, f2 in combinations(frags, 2):
        if f1.document_id == f2.document_id:
            continue
        n1 = set(NUM_RE.findall(re.sub(r"^\S+\s", "", f1.text)))
        n2 = set(NUM_RE.findall(re.sub(r"^\S+\s", "", f2.text)))
        if n1 != n2:
            pairs.append((float(retr.mat[idx[f1.id]] @ retr.mat[idx[f2.id]]), {f1.id, f2.id}))
    sid_frags = {sid: item_fragments(kb, sid) for sid in gmap.values()}
    curve = {}
    for tau in [round(x, 3) for x in np.arange(0.80, 0.991, 0.01)]:
        expanded = []
        for sim, pf in pairs:
            if sim >= tau:
                expanded.append(pf | {sid for sid, fr in sid_frags.items() if fr & pf})
        curve[tau] = score(expanded, gold, gmap, distractor_sets)
    best = max(curve, key=lambda t: (curve[t]["f1"], t))
    res["C1_similarity"] = dict(curve[best], tau=best,
                                curve={t: {k: v[k] for k in ("found", "precision", "recall", "f1")} for t, v in curve.items()})
    man = load_manifest(a.variant)
    out = {"experiment": "E3_contradictions", "variant": a.variant, "dataset_hash": man["dataset_hash"],
           "commit": git_commit(), "embedder": emb.name,
           "failed_documents": [d.filename for d in kb.documents.values() if d.status == "failed"], "methods": res,
           "hybrid_findings": [{"type": c.type, "status": c.status, "severity": c.severity, "description": c.description,
                                "detected_by": c.detected_by, "confidence": c.confidence} for c in full]}
    p = ROOT / "experiments" / "results" / f"E3_contradictions_{a.variant}.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = [f"# E3 — противоречия ({a.variant}, датасет {man['dataset_hash']})", "",
             "| Метод | Найдено | P | R (из 10) | F1 | Ловушки | Пропущены |", "|---|---|---|---|---|---|---|"]
    for name in ("C1_similarity", "C2_formal", "C3_hybrid"):
        r = res[name]
        label = f"{name} (τ={r['tau']})" if "tau" in r else name
        lines.append(f"| {label} | {r['found']} | {r['precision']:.2f} | {r['recall']:.2f} | {r['f1']:.2f} | "
                     f"{r['distractor_hits']} | {', '.join(r['missed'])} |")
    p.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    _ = PRF, np


if __name__ == "__main__":
    main()
