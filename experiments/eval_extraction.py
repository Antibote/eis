"""Эксперимент E1: точность извлечения требований и связей против эталона.

Запуск: python experiments/eval_extraction.py --variant test
"""
from __future__ import annotations

import argparse
import json
import math
import time
from collections import defaultdict

from common import ROOT, IdMap, PRF, build_kb, git_commit, load_gold, load_manifest, prf

OPS_EQUIV = {"<=": "<=", ">=": ">=", "=": "=", "range": "range"}


def req_key(subject, param, op, value, low, high, doc):
    def r(x):
        return None if x is None else (x if isinstance(x, str) else round(float(x), 3))
    return (doc, subject, param, OPS_EQUIV.get(op, op), r(value), r(low), r(high))


def gold_req_key(g, idm: IdMap):
    op = g["op"]
    return req_key(idm(g["subject"]), g["param"], op, g["value_norm"], g["low_norm"], g["high_norm"], idm(g["doc"]))


def eval_requirements(gold, kb, idm):
    gold_keys = {gold_req_key(g, idm): g for g in gold["requirements"]}
    pred_keys = {req_key(r.subject_id, r.parameter, r.operator, r.value, r.low, r.high, r.document_id): r
                 for r in kb.requirements.values()}
    overall = prf(set(pred_keys), set(gold_keys))
    by_kind = defaultdict(PRF)
    for k, g in gold_keys.items():
        by_kind[g["kind"]].add_sets({k} & set(pred_keys), {k})
    for k, r in pred_keys.items():
        if k not in gold_keys:
            by_kind[r.kind].fp += 1
    # частичное совпадение: (документ, субъект, параметр) — показывает, где ошибка в значении/операторе
    loose = prf({k[:3] for k in pred_keys}, {k[:3] for k in gold_keys})
    errors = {"missed": [g["id"] + " " + g["doc"] + " " + g["param"] for k, g in gold_keys.items() if k not in pred_keys],
              "spurious": [f"{kb.documents[r.document_id].filename[:3]} {r.parameter} {r.subject_id} {r.operator} "
                           f"{r.value}/{r.low}/{r.high} «{r.text[:70]}»" for k, r in pred_keys.items() if k not in gold_keys]}
    return overall, dict(by_kind), loose, errors


def eval_relations(gold, kb, idm):
    pred = defaultdict(set)
    for r in kb.relations.values():
        pred[r.type.value].add((r.source, r.target))
    goldset = defaultdict(set)
    for g in gold["relations"]:
        t, s, o = g["type"], g["source"], g["target"]
        if t == "DEPENDS_ON":
            def node(x):
                return idm.constraint_of(x) if x in idm.gold_reqs else idm(x)
            goldset[t].add((node(s), node(o)))
        elif t == "DERIVED_FROM":
            goldset[t].add((idm.constraint_of(s), idm.constraint_of(o)))
        elif t == "VERIFIED_BY":
            goldset[t].add((("REQ", o.split(":")[0]), idm(o)) if False else (s, idm(o)))
        elif t == "SUPERSEDES":
            goldset[t].add((f"docver:{s}", f"docver:{o}"))
        elif t == "DOCUMENTED_IN":
            if s.startswith("R"):
                continue   # документирование требований оценивается через E1-требования
            goldset[t].add((idm(s), idm(o)))
        else:
            goldset[t].add((idm(s), idm(o)))
    # VERIFIED_BY: сопоставляем требование системы с эталонным через ключ
    req_by_gold = {}
    for g in gold["requirements"]:
        k = gold_req_key(g, idm)
        for r in kb.requirements.values():
            if req_key(r.subject_id, r.parameter, r.operator, r.value, r.low, r.high, r.document_id) == k:
                req_by_gold[g["id"]] = r.id
    goldset["VERIFIED_BY"] = {(req_by_gold.get(s, f"missing:{s}"), t) for s, t in goldset["VERIFIED_BY"]}
    # DOCUMENTED_IN для системы: только сущности тех типов, что размечены в эталоне
    kinds = {"Product", "Assembly", "Component", "Material", "Test", "ChangeRequest"}
    pred["DOCUMENTED_IN"] = {(s, t) for s, t in pred["DOCUMENTED_IN"] if kb.entities.get(s) and kb.entities[s].type.value in kinds}
    out = {}
    for t in sorted(goldset):
        out[t] = prf(pred.get(t, set()), goldset[t])
    return out, {t: sorted(map(str, goldset[t] - pred.get(t, set())))[:15] for t in goldset}, \
        {t: sorted(map(str, pred.get(t, set()) - goldset[t]))[:15] for t in goldset}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="test")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    gold = load_gold(a.variant)
    t0 = time.perf_counter()
    kb = build_kb(a.variant)
    t_ingest = time.perf_counter() - t0
    idm = IdMap(gold, kb)
    overall, by_kind, loose, errors = eval_requirements(gold, kb, idm)
    rels, missed_rel, spurious_rel = eval_relations(gold, kb, idm)
    failed = [d.filename + ": " + (d.error or "") for d in kb.documents.values() if d.status == "failed"]
    res = {
        "experiment": "E1_extraction", "variant": a.variant, "dataset_hash": load_manifest(a.variant)["dataset_hash"],
        "commit": git_commit(), "ingest_seconds": round(t_ingest, 2), "failed_documents": failed,
        "requirements": overall.row(), "requirements_loose_doc_subject_param": loose.row(),
        "requirements_by_kind": {k: v.row() for k, v in by_kind.items()},
        "relations": {k: v.row() for k, v in rels.items()},
        "errors": errors, "relations_missed": missed_rel, "relations_spurious": spurious_rel,
    }
    out = ROOT / "experiments" / "results" / f"E1_extraction_{a.variant}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[{a.variant}] ingest {t_ingest:.1f}s  failed: {failed}")
    print("requirements:", overall.row())
    print("  loose (doc,subject,param):", loose.row())
    for k, v in by_kind.items():
        print(f"  {k:10s}", v.row())
    for k, v in rels.items():
        print(f"rel {k:14s}", v.row())
    if a.verbose:
        print(json.dumps({"errors": errors, "missed": missed_rel, "spurious": spurious_rel}, ensure_ascii=False, indent=1))
    _ = math


if __name__ == "__main__":
    main()
