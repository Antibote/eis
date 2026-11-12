"""Эксперимент E4: устойчивость к качеству сканов.

Текстовые документы корпуса (PDF, DOCX, TXT; таблицы XLSX/CSV остаются электронными) превращаются в
изображения-«сканы» с заданными искажениями, распознаются Tesseract в обычном конвейере EIS, после чего
измеряются: сходство распознанного текста с исходным, извлечение требований (E1), анализ изменений
(M4, 25 сценариев) и обнаружение противоречий (C3).

Запуск: python experiments/eval_noise.py --variant test [--levels scan_clean,blur_2.5]
Результаты: experiments/results/E4_noise_<variant>.{json,md}
"""
from __future__ import annotations

import argparse
import copy
import difflib
import io
import json
import random
import shutil
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from common import ROOT, IdMap, PRF, git_commit, load_gold, load_manifest
from eval_contradictions import gold_item_map, score
from eval_extraction import eval_requirements
from methods import HybridMethod

sys.path.insert(0, str(ROOT / "dataset" / "generator"))
from build import BANNER, FONT, FONT_B, header  # noqa: E402
from model import DOCS  # noqa: E402
from render import render_all  # noqa: E402

from eis.graph.store import build_graph  # noqa: E402
from eis.services.contradictions import ContradictionDetector  # noqa: E402
from eis.services.ingest import ingest_dir  # noqa: E402

SCANNED_FORMATS = {"pdf", "docx", "txt", "png"}
LEVELS: dict[str, dict | None] = {
    "native": None,                                          # исходные форматы (1 скан D13 — как в E1–E3)
    "scan_clean": {},
    "scan_typical": {"noise": 0.004, "rot": 0.6, "blur": 0.6},   # как D13 в основном корпусе
    "blur_1.5": {"blur": 1.5},
    "blur_2.5": {"blur": 2.5},
    "noise_5pct": {"noise": 0.05},
    "rot_3deg": {"rot": 3.0},
    "lowres_100dpi": {"scale": 0.5},
    "jpeg_q10": {"jpeg": 10},
    "stamps": {"stamps": 3},
    "combined": {"blur": 1.2, "noise": 0.02, "rot": 2.0, "jpeg": 25, "stamps": 2},
}
W, MARGIN, SIZE, LEADING = 1654, 90, 30, 46     # A4 при 200 dpi, кегль ≈ 11 pt


def doc_lines(doc, blocks, as_text: bool = True) -> list:
    """Текст документа — тот же, что в TXT-версии (заголовок, предупреждение, блоки). Таблица: при as_text —
    строки с ячейками через пробел (эталон для сравнения текста), иначе — список ячеек (рисуется колонками)."""
    lines: list = header(doc) + [""]
    for kind, content, _ in blocks:
        if kind == "table":
            lines.append([list(r) for r in content] if not as_text else None)
            if as_text:
                lines.pop()
                lines += [" ".join(r) for r in content]
        else:
            lines.append(content)
    return lines


def render_scan(lines: list, params: dict, seed: int) -> Image.Image:
    """Строки текста переносятся по ширине; таблица (список строк-ячеек) рисуется выровненными колонками."""
    f, fb = ImageFont.truetype(FONT, SIZE), ImageFont.truetype(FONT_B, SIZE)
    wrapped: list = []
    for ln in lines:
        if isinstance(ln, list):
            ncol = max(len(r) for r in ln)
            avail = W - 2 * MARGIN - 40 * (ncol - 1)
            size = SIZE
            while True:                     # широкая таблица набирается мельче (как в документах), без наложения
                ft = ImageFont.truetype(FONT, size)
                widths = [max(ft.getlength(r[c]) if c < len(r) else 0 for r in ln) for c in range(ncol)]
                if sum(widths) <= avail or size <= 18:
                    break
                size -= 1
            xs, x = [], MARGIN
            for wd in widths:
                xs.append(x)
                x += wd + 40
            for r in ln:
                wrapped.append([(xs[c], cell, ft) for c, cell in enumerate(r)])
            continue
        words, cur = ln.split(" "), ""
        for w in words:
            t = (cur + " " + w).strip()
            if f.getlength(t) > W - 2 * MARGIN and cur:
                wrapped.append(cur)
                cur = w
            else:
                cur = t
        wrapped.append(cur)
    H = 2 * MARGIN + LEADING * len(wrapped)
    img = Image.new("L", (W, H), 248)
    dr = ImageDraw.Draw(img)
    for i, ln in enumerate(wrapped):
        if isinstance(ln, list):
            for x, cell, ft in ln:
                dr.text((x, MARGIN + i * LEADING), cell, font=ft, fill=18)
        else:
            dr.text((MARGIN, MARGIN + i * LEADING), ln, font=fb if i == 0 else f, fill=18)
    rng = random.Random(seed)
    for _ in range(params.get("stamps", 0)):                 # штамп «КОПИЯ ВЕРНА» поверх текста
        cx, cy = rng.randrange(300, W - 300), rng.randrange(150, max(151, H - 150))
        ov = Image.new("L", (W, H), 0)
        od = ImageDraw.Draw(ov)
        od.ellipse((cx - 210, cy - 95, cx + 210, cy + 95), outline=255, width=7)
        od.text((cx - 150, cy - 22), "КОПИЯ ВЕРНА", font=ImageFont.truetype(FONT_B, 40), fill=255)
        od.line((cx - 260, cy + 120, cx + 240, cy + 60), fill=255, width=5)   # подпись от руки
        img = Image.composite(Image.new("L", (W, H), 110), img, ov.point(lambda v: int(v * 0.75)))
    if params.get("noise"):
        n = int(W * H * params["noise"])
        px = img.load()
        for _ in range(n):
            px[rng.randrange(W), rng.randrange(H)] = rng.choice((0, 255)) if rng.random() < 0.5 else rng.randrange(60, 230)
    if params.get("rot"):
        img = img.rotate(params["rot"], resample=Image.BICUBIC, expand=True, fillcolor=248)
    if params.get("blur"):
        img = img.filter(ImageFilter.GaussianBlur(params["blur"]))
    if params.get("scale"):
        s = params["scale"]
        img = img.resize((int(img.width * s), int(img.height * s)), Image.BILINEAR)
    if params.get("jpeg"):
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=params["jpeg"])
        img = Image.open(io.BytesIO(buf.getvalue())).convert("L")
    return img


def build_corpus(level: str, params: dict | None, variant: str, out: Path, seed: int = 42) -> dict[str, str]:
    """→ {id документа: имя файла в построенном корпусе}."""
    src = ROOT / "dataset" / "out" / variant / "docs"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    names = {}
    blocks = render_all(variant, seed) if params is not None else None
    for d in DOCS:
        if params is None or d.fmt not in SCANNED_FORMATS:
            shutil.copy(src / d.filename, out / d.filename)
            names[d.id] = d.filename
            continue
        dpi = int(200 * params.get("scale", 1.0))
        name = Path(d.filename).stem + ".png"
        render_scan(doc_lines(d, blocks[d.id], as_text=False), params, seed + int(d.id[1:])).save(out / name, dpi=(dpi, dpi))
        names[d.id] = name
    return names


def text_similarity(kb, names, variant) -> float | None:
    """Сходство распознанного текста с исходным (difflib, по сканированным документам, взвешено по длине)."""
    blocks = render_all(variant, 42)
    num = den = 0.0
    by_file = {d.filename: d.id for d in kb.documents.values()}
    for d in DOCS:
        if not names[d.id].endswith(".png"):
            continue
        did = by_file.get(names[d.id])
        if did is None:
            continue
        ocr = " ".join(" ".join(f.cells) if f.cells else f.text      # порядок вставки = порядок в документе
                       for f in kb.fragments.values() if f.document_id == did)
        ref = " ".join(" ".join(doc_lines(d, blocks[d.id])).split())
        ocr = " ".join(ocr.split())
        r = difflib.SequenceMatcher(None, ref, ocr, autojunk=False).ratio()
        num += r * len(ref)
        den += len(ref)
    return round(num / den, 4) if den else None


def evaluate(level, params, variant, gold0, workdir: Path) -> dict:
    t0 = time.perf_counter()
    names = build_corpus(level, params, variant, workdir / level)
    gold = copy.deepcopy(gold0)
    for d in gold["entities"]["documents"]:
        d["filename"] = names[d["id"]]
    kb = ingest_dir(workdir / level)
    t_ingest = time.perf_counter() - t0
    g = build_graph(kb)
    idm = IdMap(gold, kb)
    req, _, _, errors = eval_requirements(gold, kb, idm)
    # анализ изменений, 25 сценариев
    m = HybridMethod(kb, g)
    agg = {k: PRF() for k in ("components", "documents", "violations", "tests")}
    failed = []
    for sc in gold["scenarios"]:
        try:
            out = m.run(sc["text"])
        except Exception as e:  # noqa: BLE001 — отказ = пустой ответ
            failed.append(f"{sc['id']}: {type(e).__name__}")
            out = None
        pred = (out.components, out.documents, out.violations, out.tests) if out else (set(), set(), set(), set())
        for k, p, gl in zip(("components", "documents", "violations", "tests"), pred,
                            (sc["affected_components"], sc["documents"], sc["violations"], sc["tests"])):
            agg[k].add_sets(p, {idm(x) for x in gl})
    # противоречия
    gmap = gold_item_map(gold, kb, idm)
    dsets = [set(gmap[x] for x in d["pair"]) for d in gold["distractors"] if all(gmap.get(x) for x in d["pair"])]
    c3 = score([set(c.items) for c in ContradictionDetector(kb, g).run()], gold, gmap, dsets)
    return {
        "level": level, "params": params, "seconds": round(time.perf_counter() - t0, 1), "ingest_seconds": round(t_ingest, 1),
        "failed_documents": [d.filename for d in kb.documents.values() if d.status == "failed"],
        "text_similarity": text_similarity(kb, names, variant) if params is not None else None,
        "requirements": req.row(), "missed_requirements": errors["missed"],
        "impact": {k: v.row() for k, v in agg.items()}, "impact_failures": failed,
        "contradictions": {k: c3[k] for k in ("found", "precision", "recall", "f1", "detected", "missed", "distractor_hits")},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="test")
    ap.add_argument("--levels", default=",".join(LEVELS))
    ap.add_argument("--workdir", default=str(ROOT / "experiments" / ".noise_corpus"))
    a = ap.parse_args()
    gold0 = load_gold(a.variant)
    workdir = Path(a.workdir)
    levels = a.levels.split(",")
    rows, t_start = [], time.perf_counter()
    for i, lv in enumerate(levels, 1):
        r = evaluate(lv, LEVELS[lv], a.variant, gold0, workdir)
        rows.append(r)
        print(f"[{i}/{len(levels)}] {lv}: текст {r['text_similarity']}, требования R {r['requirements']['recall']:.2f}, "
              f"компоненты F1 {r['impact']['components']['f1']:.2f}, противоречия R {r['contradictions']['recall']:.2f} "
              f"({r['seconds']} с; всего {time.perf_counter() - t_start:.0f} с)", flush=True)
    man = load_manifest(a.variant)
    res = {"experiment": "E4_noise", "variant": a.variant, "dataset_hash": man["dataset_hash"], "commit": git_commit(),
           "scanned_formats": sorted(SCANNED_FORMATS), "levels": rows}
    out = ROOT / "experiments" / "results" / f"E4_noise_{a.variant}.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = [f"# E4 — качество сканов ({a.variant}, датасет {man['dataset_hash']})", "",
             "Сканируются PDF/DOCX/TXT (11 документов); XLSX/CSV остаются электронными.", "",
             "| Уровень | Сходство текста | Требования P / R | Компоненты F1 | Документы F1 | Нарушения F1 | Противоречия R (из 10) | Отказы |",
             "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        q, im, c = r["requirements"], r["impact"], r["contradictions"]
        lines.append(f"| {r['level']} | {r['text_similarity'] if r['text_similarity'] is not None else '—'} | "
                     f"{q['precision']:.2f} / {q['recall']:.2f} | {im['components']['f1']:.2f} | {im['documents']['f1']:.2f} | "
                     f"{im['violations']['f1']:.2f} | {c['recall']:.2f} | {len(r['failed_documents']) + len(r['impact_failures'])} |")
    out.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
