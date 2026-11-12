"""Эксперимент E5: масштабируемость.

1) Загрузка: корпус копируется ×N (файлы с другими именами) и обрабатывается конвейером EIS целиком —
   время, документов/с. Содержимое копий одинаково, поэтому сущности сливаются; измеряется именно
   стоимость разбора, OCR, извлечения и связывания.
2) Аналитика: база знаний клонируется как N независимых изделий (все идентификаторы с суффиксом копии) —
   время построения графа, поиска противоречий по всей базе, анализа изменения (25 сценариев, копия 0),
   поиска (BM25 + векторный, матрица эмбеддингов ×N), пиковая память процесса.

Запуск: python experiments/eval_scale.py [--ingest 1,5,10,20] [--kb 1,10,50,100]
"""
from __future__ import annotations

import argparse
import json
import re
import resource
import shutil
import statistics
import time
from pathlib import Path

import numpy as np

from common import ROOT, git_commit, load_gold, load_manifest

from eis.domain.models import KnowledgeBase
from eis.graph.store import build_graph
from rank_bm25 import BM25Okapi

from eis.rag.retriever import default_embedder, lemmatize
from eis.services.change_request import parse_change
from eis.services.contradictions import ContradictionDetector
from eis.services.impact import ImpactAnalyzer
from eis.services.ingest import ingest_dir

SRC = ROOT / "dataset" / "out" / "test" / "docs"


def rss_mb() -> float:
    """Текущая резидентная память процесса, МБ."""
    for ln in open("/proc/self/status"):
        if ln.startswith("VmRSS:"):
            return round(int(ln.split()[1]) / 1024, 1)
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)


def ingest_scale(n: int, work: Path) -> dict:
    d = work / f"ingest_x{n}"
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    files = sorted(p for p in SRC.iterdir() if p.is_file())
    for k in range(n):
        for p in files:
            shutil.copy(p, d / f"c{k:03d}_{p.name}")
    size = sum(p.stat().st_size for p in d.iterdir()) / 2**20
    t = time.perf_counter()
    kb = ingest_dir(d)
    dt = time.perf_counter() - t
    shutil.rmtree(d)
    return {"copies": n, "documents": len(kb.documents), "size_mb": round(size, 1), "seconds": round(dt, 2),
            "docs_per_second": round(len(kb.documents) / dt, 2), "failed": sum(x.status == "failed" for x in kb.documents.values())}


def clone_kb(kb: KnowledgeBase, n: int) -> KnowledgeBase:
    """N независимых копий базы знаний: копия 0 — исходные идентификаторы, копии 1..N−1 — с суффиксом «#k»."""
    raw = kb.model_dump_json()
    ids = set(kb.entities) | set(kb.requirements) | set(kb.relations) | set(kb.documents) | set(kb.fragments)
    pat = re.compile(r'"((?:[^"\\]|\\.)*)"')
    big = json.loads(raw)
    for k in range(1, n):
        s = pat.sub(lambda m: f'"{m.group(1)}#{k}"' if m.group(1) in ids else m.group(0), raw)
        part = json.loads(s)
        for key in ("documents", "fragments", "entities", "requirements", "relations"):
            big[key].update(part[key])
    return KnowledgeBase.model_validate(big)


def kb_scale(base: KnowledgeBase, n: int, changes, emb, base_matrix) -> dict:
    t = time.perf_counter()
    kb = clone_kb(base, n)
    t_clone = time.perf_counter() - t
    t = time.perf_counter()
    g = build_graph(kb)
    t_graph = time.perf_counter() - t
    t = time.perf_counter()
    ctr = ContradictionDetector(kb, g).run()
    t_ctr = time.perf_counter() - t
    a = ImpactAnalyzer(kb, g)
    times = []
    for rid, nv, lo, hi in changes:
        t = time.perf_counter()
        a.analyze(rid, new_value=nv, new_low=lo, new_high=hi)
        times.append((time.perf_counter() - t) * 1000)
    # поиск: BM25 по всем фрагментам; векторная часть — матрица эмбеддингов исходного корпуса, размноженная ×N
    t = time.perf_counter()
    bm25 = BM25Okapi([lemmatize(f.text) or ["∅"] for f in kb.fragments.values()])
    t_bm25 = time.perf_counter() - t
    mat = np.tile(base_matrix, (n, 1))
    q = emb.encode_query("рабочее давление корпуса насоса")
    ql = lemmatize("рабочее давление корпуса насоса")
    qt = []
    for _ in range(20):
        t = time.perf_counter()
        bm = bm25.get_scores(ql)
        np.argpartition(-bm, 10)[:10]
        sims = mat @ q
        np.argpartition(-sims, 10)[:10]
        qt.append((time.perf_counter() - t) * 1000)
    return {"copies": n, "components": sum(e.type.value in ("Component", "Assembly") for e in kb.entities.values()),
            "requirements": len(kb.requirements), "relations": len(kb.relations), "fragments": len(kb.fragments),
            "clone_seconds": round(t_clone, 2), "graph_seconds": round(t_graph, 3), "contradictions_seconds": round(t_ctr, 3),
            "contradictions_found": len(ctr), "impact_ms_median": round(statistics.median(times), 2),
            "impact_ms_max": round(max(times), 2), "bm25_index_seconds": round(t_bm25, 2),
            "search_ms_median": round(statistics.median(qt), 2), "rss_mb": rss_mb()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ingest", default="1,5,10,20")
    ap.add_argument("--kb", default="1,10,50,100")
    ap.add_argument("--workdir", default=str(ROOT / "experiments" / ".scale_corpus"))
    a = ap.parse_args()
    work = Path(a.workdir)
    work.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    ing = []
    for n in [int(x) for x in a.ingest.split(",") if x]:
        r = ingest_scale(n, work)
        ing.append(r)
        print(f"загрузка ×{n}: {r['documents']} док., {r['seconds']} с, {r['docs_per_second']} док/с "
              f"(всего {time.perf_counter() - t0:.0f} с)", flush=True)
    base = ingest_dir(SRC)
    g0 = build_graph(base)
    gold = load_gold("test")
    changes = []
    for sc in gold["scenarios"]:
        pc = parse_change(sc["text"], base, g0)
        changes.append((pc.requirement.id, pc.new_value, pc.new_low, pc.new_high))
    emb = default_embedder(None)
    t = time.perf_counter()
    texts = [f.text for f in base.fragments.values()]
    base_matrix = np.asarray(emb.encode_passages(texts), dtype=np.float32)
    t_emb = time.perf_counter() - t
    emb_rate = len(texts) / t_emb
    print(f"эмбеддинги: {len(texts)} фрагментов за {t_emb:.1f} с ({emb_rate:.0f} фрагм/с, {emb.name})", flush=True)
    import gc
    gc.collect()
    rss0 = rss_mb()
    print(f"память после загрузки модели и базы ×1: {rss0} МБ", flush=True)
    kbs = []
    for n in [int(x) for x in a.kb.split(",") if x]:
        r = kb_scale(base, n, changes, emb, base_matrix)
        r["embedding_seconds_estimate"] = round(r["fragments"] / emb_rate, 1)
        r["rss_increment_mb"] = round(r["rss_mb"] - rss0, 1)
        gc.collect()
        kbs.append(r)
        print(f"база ×{n}: {r['components']} комп., {r['relations']} связей; граф {r['graph_seconds']} с, "
              f"противоречия {r['contradictions_seconds']} с, анализ {r['impact_ms_median']} мс, поиск {r['search_ms_median']} мс, "
              f"противоречий {r['contradictions_found']}, прирост памяти {r['rss_increment_mb']} МБ (всего {time.perf_counter() - t0:.0f} с)", flush=True)
    shutil.rmtree(work, ignore_errors=True)
    man = load_manifest("test")
    res = {"experiment": "E5_scale", "dataset_hash": man["dataset_hash"], "commit": git_commit(), "embedder": emb.name,
           "embedding_fragments_per_second": round(emb_rate, 1), "rss_base_mb": rss0, "ingest": ing, "kb": kbs,
           "cpu": open("/proc/cpuinfo").read().split("model name")[1].split("\n")[0].strip(" :\t")}
    out = ROOT / "experiments" / "results" / "E5_scale.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = [f"# E5 — масштабируемость (датасет {man['dataset_hash']}, {res['cpu']})", "",
             "| Копий | Документов | Объём, МБ | Загрузка, с | Док/с |", "|---|---|---|---|---|"]
    lines += [f"| ×{r['copies']} | {r['documents']} | {r['size_mb']} | {r['seconds']} | {r['docs_per_second']} |" for r in ing]
    lines += ["", "| Копий | Компонентов | Требований | Связей | Граф, с | Противоречия, с | Анализ изменения, мс (медиана / макс) | Поиск, мс | Эмбеддинги (оценка), с | Прирост памяти, МБ |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    lines += [f"| ×{r['copies']} | {r['components']} | {r['requirements']} | {r['relations']} | {r['graph_seconds']} | "
              f"{r['contradictions_seconds']} | {r['impact_ms_median']} / {r['impact_ms_max']} | {r['search_ms_median']} | "
              f"{r['embedding_seconds_estimate']} | {r['rss_increment_mb']} |" for r in kbs]
    out.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
