"""Сборка синтетического датасета: документы всех форматов + эталонная разметка.

Запуск:  python dataset/generator/build.py [--variants dev test] [--seed 42]
Результат: dataset/out/<variant>/docs/*  и  dataset/out/<variant>/gold/*.json
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from model import (CHANGES, COMPONENTS, CONTRADICTIONS, DEPENDS_ON, DERIVED_FROM, DISTRACTORS, DOC, DOCS,  # noqa: E402
                   EXTRA_MATERIALS, INJECTIONS, MATERIALS, PARAMS, REQS, SCENARIOS, TESTS)
from render import BANNER, render_all  # noqa: E402

GEN_VERSION = "1.0"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
ROOT = Path(__file__).resolve().parents[1]

# Каноническая единица для каждой размерности (независимо от кода системы)
CANON = {"temperature": "°C", "pressure": "МПа", "flow": "м³/ч", "length": "м", "rotation": "об/мин",
         "power": "кВт", "velocity": "мм/с", "sound": "дБА", "time": "ч", "mass": "кг", "voltage": "В",
         "torque": "Н·м", "ip": ""}
TO_CANON = {"кгс/см²": 0.0980665}


def norm(v, unit):
    if v is None or isinstance(v, str):
        return v
    return round(v * TO_CANON.get(unit, 1.0), 6)


# ------------------------------------------------------------------ writers

def header(doc):
    return [doc.code, doc.title, BANNER]


def write_txt(path, doc, blocks):
    lines = header(doc) + [""]
    for kind, content, _ in blocks:
        if kind == "table":
            lines += ["\t".join(r) for r in content]
        else:
            lines.append(content)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_csv(path, doc, blocks):
    rows = [b[1] for b in blocks if b[0] == "table"][0]
    with path.open("w", encoding="utf-8", newline="") as f:
        f.write(f"# {doc.code}. {doc.title}. {BANNER}\n")
        csv.writer(f, delimiter=";").writerows(rows)


def write_xlsx(path, doc, blocks):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Лист1"
    for line in header(doc):
        ws.append([line])
    ws.append([])
    for kind, content, _ in blocks:
        if kind == "table":
            for r in content:
                ws.append(r)
    wb.save(path)


def write_docx(path, doc, blocks):
    import docx
    d = docx.Document()
    d.core_properties.title = doc.title
    d.core_properties.comments = BANNER
    d.add_heading(f"{doc.code}. {doc.title}", level=1)
    d.add_paragraph(BANNER)
    for kind, content, _ in blocks:
        if kind == "h":
            d.add_heading(content, level=2)
        elif kind == "p":
            d.add_paragraph(content)
        else:
            t = d.add_table(rows=0, cols=len(content[0]))
            t.style = "Table Grid"
            for r in content:
                cells = t.add_row().cells
                for c, v in zip(cells, r):
                    c.text = v
    d.save(path)


def write_pdf(path, doc, blocks):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table

    if "DejaVu" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("DejaVu", FONT))
        pdfmetrics.registerFont(TTFont("DejaVuB", FONT_B))
    body = ParagraphStyle("b", fontName="DejaVu", fontSize=11, leading=15, spaceAfter=6)
    head = ParagraphStyle("h", fontName="DejaVuB", fontSize=12, leading=16, spaceBefore=10, spaceAfter=6)
    title = ParagraphStyle("t", fontName="DejaVuB", fontSize=14, leading=18, spaceAfter=8)
    small = ParagraphStyle("s", fontName="DejaVu", fontSize=8, leading=10, spaceAfter=12)
    story = [Paragraph(doc.code, body), Paragraph(doc.title, title), Paragraph(BANNER, small)]
    for kind, content, _ in blocks:
        if kind == "h":
            story.append(Paragraph(content, head))
        elif kind == "p":
            story.append(Paragraph(content, body))
        else:
            story.append(Table(content, style=[("FONT", (0, 0), (-1, -1), "DejaVu", 9)]))
            story.append(Spacer(1, 6))
    SimpleDocTemplate(str(path), pagesize=A4, leftMargin=25 * mm, rightMargin=15 * mm,
                      title=doc.title, subject=BANNER).build(story)


def write_png(path, doc, blocks, seed):
    """Имитация скана: текст, лёгкий поворот, шум."""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    rng = random.Random(seed)
    W, H = 1654, 1100
    img = Image.new("L", (W, H), 248)
    dr = ImageDraw.Draw(img)
    f, fb, fs = ImageFont.truetype(FONT, 30), ImageFont.truetype(FONT_B, 34), ImageFont.truetype(FONT, 22)
    y = 60
    dr.text((80, y), doc.code, font=f, fill=20); y += 50
    dr.text((80, y), BANNER[:95], font=fs, fill=40); y += 32
    dr.text((80, y), BANNER[95:], font=fs, fill=40); y += 60
    for kind, content, _ in blocks:
        dr.text((80, y), content, font=fb if kind == "h" else f, fill=15)
        y += 70
    for _ in range(6000):  # шум
        x, yy = rng.randrange(W), rng.randrange(H)
        img.putpixel((x, yy), rng.randrange(120, 230))
    img = img.rotate(0.6, resample=Image.BICUBIC, fillcolor=248).filter(ImageFilter.GaussianBlur(0.6))
    img.save(path, dpi=(200, 200))


WRITERS = {"txt": write_txt, "csv": write_csv, "xlsx": write_xlsx, "docx": write_docx, "pdf": write_pdf}


# ------------------------------------------------------------------ gold

def gold(blocks_by_doc):
    reqs = []
    for r in REQS:
        d = asdict(r)
        dim = PARAMS[r.param].dimension
        d.update(dimension=dim, unit_canonical=CANON[dim], value_norm=norm(r.value, r.unit),
                 low_norm=norm(r.low, r.unit), high_norm=norm(r.high, r.unit))
        reqs.append(d)
    # ограничения материалов из ведомости материалов (D04)
    for m in MATERIALS:
        if any(c.material == m.id for c in COMPONENTS) or any(mm == m.id for _, mm in EXTRA_MATERIALS):
            reqs.append(dict(id=f"RM_{m.id}", doc="D04", subject=m.id, param="material_temperature", kind="capability",
                             op="range", value=None, low=m.t_low, high=m.t_high, unit="°C", explicit=True, section="1",
                             note="", dimension="temperature", unit_canonical="°C", value_norm=None,
                             low_norm=m.t_low, high_norm=m.t_high))

    rel = []

    def add(t, s, o, docs, note=""):
        rel.append({"type": t, "source": s, "target": o, "evidence_docs": docs, "note": note})

    for c in COMPONENTS:
        if c.parent:
            add("CONTAINS", c.parent, c.id, ["D02", "D03"])
        if c.material:
            add("USES_MATERIAL", c.id, c.material, ["D02", "D04"])
    for cid, mid in EXTRA_MATERIALS:
        add("USES_MATERIAL", cid, mid, ["D02", "D04", "D11"])
    add("USES_MATERIAL", "C07", "M8", ["D05"], "противоречит D02/D04 (K08)")
    for c, r, why in DEPENDS_ON:
        add("DEPENDS_ON", c, r, ["D03"], why)
    add("DEPENDS_ON", "C09", "R16", ["D03"], "monitoring")
    for a, b, why in DERIVED_FROM:
        add("DERIVED_FROM", a, b, ["D03", "D01"], why)
    for t in TESTS:
        for r in t.verifies:
            add("VERIFIED_BY", r, t.id, ["D08"])
    for ch in CHANGES:
        add("SUPERSEDES", f"{ch['document']} {ch['edition']}", f"{ch['document']} {ch['supersedes']}", ["D14"], ch["id"])
    # DOCUMENTED_IN: сущность упомянута в документе
    seen = set()
    forms = [(c.id, f) for c in COMPONENTS for f in (c.nom, c.gen)] + [(m.id, m.name) for m in MATERIALS]
    for did, blocks in blocks_by_doc.items():
        for kind, content, ids in blocks:
            text = " ".join(" ".join(r) for r in content) if kind == "table" else content
            surf = {eid for eid, f in forms if f.lower() in text.lower()}
            for e in [*ids, *sorted(surf)]:
                if (e, did) not in seen:
                    seen.add((e, did))
                    add("DOCUMENTED_IN", e, did, [did])
    rel = [r for i, r in enumerate(rel) if (r["type"], r["source"], r["target"]) not in
           {(x["type"], x["source"], x["target"]) for x in rel[:i]}]

    entities = {
        "components": [asdict(c) for c in COMPONENTS],
        "materials": [asdict(m) for m in MATERIALS],
        "documents": [asdict(d) | {"is_synthetic": True} for d in DOCS],
        "tests": [asdict(t) for t in TESTS],
        "changes": CHANGES,
    }
    return {"entities": entities, "requirements": reqs, "relations": rel, "contradictions": CONTRADICTIONS,
            "distractors": DISTRACTORS, "scenarios": SCENARIOS, "injections": INJECTIONS}


def validate(g):
    ids = ({c["id"] for c in g["entities"]["components"]} | {m["id"] for m in g["entities"]["materials"]} |
           {r["id"] for r in g["requirements"]} | {t["id"] for t in g["entities"]["tests"]} |
           {d["id"] for d in g["entities"]["documents"]})
    for s in g["scenarios"]:
        for k in ("affected_components", "violations", "documents", "tests"):
            bad = [x for x in s[k] if x not in ids]
            assert not bad, (s["id"], k, bad)
        assert set(s["violations"]) <= set(s["affected_components"]), s["id"]
        for ch in s["chains"]:
            assert all(x in ids for x in ch), (s["id"], ch)
    for k in g["contradictions"]:
        for p in k["pairs"]:
            for x in p:
                assert x.split(":")[0] in ids, (k["id"], x)


def build(variant: str, seed: int):
    out = ROOT / "out" / variant
    (out / "docs").mkdir(parents=True, exist_ok=True)
    (out / "gold").mkdir(parents=True, exist_ok=True)
    blocks = render_all(variant, seed)
    files = []
    for d in DOCS:
        p = out / "docs" / d.filename
        if d.fmt == "png":
            write_png(p, d, blocks[d.id], seed)
        else:
            WRITERS[d.fmt](p, d, blocks[d.id])
        files.append({"doc": d.id, "file": d.filename, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()})
    g = gold(blocks)
    validate(g)
    for k, v in g.items():
        (out / "gold" / f"{k}.json").write_text(json.dumps(v, ensure_ascii=False, indent=1), encoding="utf-8")
    # плоский текст блоков — для отладки и для проверки покрытия
    (out / "gold" / "rendered_blocks.json").write_text(json.dumps(blocks, ensure_ascii=False, indent=1), encoding="utf-8")
    stats = {
        "requirements": len(g["requirements"]),
        "components": len([c for c in COMPONENTS]),
        "documents": len(DOCS),
        "relations": len(g["relations"]),
        "relations_by_type": {t: sum(r["type"] == t for r in g["relations"]) for t in sorted({r["type"] for r in g["relations"]})},
        "contradictions": len(CONTRADICTIONS),
        "scenarios": len(SCENARIOS),
    }
    manifest = {"generator_version": GEN_VERSION, "variant_set": variant, "seed": seed, "synthetic": True,
                "files": files, "stats": stats,
                "dataset_hash": hashlib.sha256("".join(f["sha256"] for f in files).encode()).hexdigest()[:16]}
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--variants", nargs="+", default=["dev", "test"])
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    for v in a.variants:
        m = build(v, a.seed)
        print(v, m["dataset_hash"], json.dumps(m["stats"], ensure_ascii=False))
