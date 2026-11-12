"""Парсеры форматов → список Fragment с привязкой к месту в документе.

Каждый парсер возвращает ParsedDocument: фрагменты в порядке чтения, заголовок, число страниц.
Новые форматы (CAD, чертежи) добавляются регистрацией функции в PARSERS.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from pathlib import Path

from eis.domain.models import Fragment, stable_id

SECTION_RE = re.compile(r"^\s*((?:\d+\.)*\d+|[TТ]\d{2})\.?\s+(?=\S)")


class ParseError(Exception):
    pass


@dataclass
class ParsedDocument:
    fragments: list[Fragment] = field(default_factory=list)
    pages: int | None = None
    header_lines: list[str] = field(default_factory=list)   # первые строки (обозначение, название)
    warnings: list[str] = field(default_factory=list)


class _Builder:
    """Накапливает фрагменты, ведёт путь заголовков и номера пунктов."""

    def __init__(self, document_id: str):
        self.doc_id = document_id
        self.out = ParsedDocument()
        self.path: list[str] = []

    def add(self, kind: str, text: str, *, page=None, locator=None, bbox=None, cells=None, header=None,
            ocr=False, ocr_conf=None) -> Fragment | None:
        text = re.sub(r"[ \t ]+", " ", text).strip()
        if not text:
            return None
        m = SECTION_RE.match(text)
        section = m.group(1).replace("Т", "T") if m else None
        if kind == "heading":
            self.path = [text]
        f = Fragment(id=stable_id(self.doc_id, len(self.out.fragments), text[:40]), document_id=self.doc_id,
                     kind=kind, text=text, page=page, locator=locator, bbox=bbox, section=section,
                     heading_path=list(self.path) if kind != "heading" else [], cells=cells, header=header,
                     ocr=ocr, ocr_confidence=ocr_conf)
        self.out.fragments.append(f)
        if len(self.out.header_lines) < 4 and kind in ("line", "paragraph", "heading"):
            self.out.header_lines.append(text)
        return f


# ------------------------------------------------------------------ PDF

def parse_pdf(path: Path, doc_id: str) -> ParsedDocument:
    import pymupdf
    b = _Builder(doc_id)
    try:
        pdf = pymupdf.open(path)
    except Exception as e:  # noqa: BLE001
        raise ParseError(f"PDF не открывается: {e}") from e
    b.out.pages = pdf.page_count
    text_chars = 0
    for pno, page in enumerate(pdf, 1):
        d = page.get_text("dict")
        for blk in d["blocks"]:
            if blk.get("type") != 0:
                continue
            spans = [s for ln in blk["lines"] for s in ln["spans"]]
            text = " ".join("".join(s["text"] for s in ln["spans"]) for ln in blk["lines"])
            text_chars += len(text.strip())
            bold = spans and all("Bold" in s["font"] or s["flags"] & 16 for s in spans if s["text"].strip())
            big = spans and max(s["size"] for s in spans) >= 12
            kind = "heading" if bold and big and len(text) < 160 else "paragraph"
            b.add(kind, text, page=pno, locator=f"стр. {pno}", bbox=tuple(round(x, 1) for x in blk["bbox"]))
    if text_chars < 20:  # скан без текстового слоя → OCR страниц
        b.out.warnings.append("PDF без текстового слоя: выполнено OCR")
        for pno, page in enumerate(pdf, 1):
            pix = page.get_pixmap(dpi=200)
            _ocr_into(b, pix.tobytes("png"), page=pno)
    return b.out


# ------------------------------------------------------------------ DOCX

def parse_docx(path: Path, doc_id: str) -> ParsedDocument:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    try:
        d = docx.Document(str(path))
    except Exception as e:  # noqa: BLE001
        raise ParseError(f"DOCX не открывается: {e}") from e
    b = _Builder(doc_id)
    pi = ti = 0
    for el in d.element.body.iterchildren():
        tag = el.tag.split("}")[-1]
        if tag == "p":
            p = Paragraph(el, d)
            pi += 1
            style = (p.style.name or "").lower() if p.style is not None else ""
            kind = "heading" if style.startswith("heading") or style.startswith("заголовок") or style == "title" else "paragraph"
            b.add(kind, p.text, locator=f"абзац {pi}")
        elif tag == "tbl":
            ti += 1
            t = Table(el, d)
            rows = [[c.text.strip() for c in r.cells] for r in t.rows]
            _table_into(b, rows, locator_prefix=f"таблица {ti}")
    return b.out


def _table_into(b: _Builder, rows: list[list[str]], locator_prefix: str, page=None, first_row: int = 1):
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        return
    header = rows[0]
    for i, r in enumerate(rows[1:], first_row + 1):
        text = "; ".join(f"{h}: {c}" if h else c for h, c in zip(header, r) if c.strip())
        b.add("table_row", text, page=page, locator=f"{locator_prefix}, строка {i}", cells=r, header=header)


# ------------------------------------------------------------------ XLSX / CSV / TXT

def parse_xlsx(path: Path, doc_id: str) -> ParsedDocument:
    from openpyxl import load_workbook
    try:
        wb = load_workbook(path, read_only=True, data_only=True)
    except Exception as e:  # noqa: BLE001
        raise ParseError(f"XLSX не открывается: {e}") from e
    b = _Builder(doc_id)
    b.out.pages = len(wb.sheetnames)
    for si, ws in enumerate(wb.worksheets, 1):
        rows = [["" if v is None else str(v) for v in r] for r in ws.iter_rows(values_only=True)]
        _grid_into(b, rows, page=si, sheet=ws.title)
    return b.out


def _grid_into(b: _Builder, rows: list[list[str]], page=None, sheet=None):
    """Строки до первой «широкой» строки (≥3 непустых ячеек) — текст, далее — таблица."""
    start = next((i for i, r in enumerate(rows) if sum(bool(c.strip()) for c in r) >= 3), None)
    pre = rows if start is None else rows[:start]
    for i, r in enumerate(pre, 1):
        b.add("line", " ".join(c for c in r if c.strip()), page=page, locator=f"лист «{sheet}», строка {i}" if sheet else f"строка {i}")
    if start is not None:
        _table_into(b, rows[start:], locator_prefix=f"лист «{sheet}»" if sheet else "таблица", page=page,
                    first_row=start + 1)


def parse_csv(path: Path, doc_id: str) -> ParsedDocument:
    raw = _read_text(path)
    lines = raw.splitlines()
    b = _Builder(doc_id)
    comments = [ln.lstrip("# ").strip() for ln in lines if ln.startswith("#")]
    for i, c in enumerate(comments, 1):
        b.add("line", c, locator=f"комментарий {i}")
    body = "\n".join(ln for ln in lines if not ln.startswith("#"))
    try:
        dialect = csv.Sniffer().sniff(body[:2000], delimiters=";,\t")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(body), dialect))
    _table_into(b, rows, locator_prefix="таблица")
    return b.out


def parse_txt(path: Path, doc_id: str) -> ParsedDocument:
    b = _Builder(doc_id)
    for i, ln in enumerate(_read_text(path).splitlines(), 1):
        if "\t" in ln and ln.count("\t") >= 2:
            b.add("table_row", ln.replace("\t", "; "), locator=f"строка {i}", cells=ln.split("\t"))
        else:
            b.add("line", ln, locator=f"строка {i}")
    return b.out


def _read_text(path: Path) -> str:
    data = path.read_bytes()
    for enc in ("utf-8-sig", "cp1251"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ParseError("Не удалось определить кодировку текста")


# ------------------------------------------------------------------ изображения (OCR)

def ocr_available() -> bool:
    import shutil
    return shutil.which("tesseract") is not None


def _ocr_into(b: _Builder, image_bytes: bytes, page=None):
    if not ocr_available():
        raise ParseError("OCR недоступен: не установлен Tesseract (apt install tesseract-ocr tesseract-ocr-rus)")
    import pytesseract
    from PIL import Image
    img = Image.open(io.BytesIO(image_bytes))
    data = pytesseract.image_to_data(img, lang="rus+eng", output_type=pytesseract.Output.DICT)
    _layout_into(b, data, page)


def _layout_into(b: _Builder, data: dict, page=None):
    """Восстановление структуры по геометрии слов OCR: строки с крупными промежутками между словами —
    строки таблицы (ячейки); строки одного абзаца Tesseract склеиваются в абзац (кроме строк, начинающихся
    с номера пункта). Без этого перенос строки разрывает требование, а таблица теряет ячейки."""
    lines: dict[tuple, list[int]] = {}
    for i, w in enumerate(data["text"]):
        if w.strip():
            lines.setdefault((data["block_num"][i], data["par_num"][i], data["line_num"][i]), []).append(i)
    # Tesseract может отнести дальнюю колонку таблицы к другому блоку: строки, лежащие на одной высоте
    # и не перекрывающиеся по горизонтали, объединяются в одну строку страницы.
    groups: list[tuple[tuple, list[int]]] = []
    for key, idx in sorted(lines.items(), key=lambda kv: min(data["top"][i] for i in kv[1])):
        top = min(data["top"][i] for i in idx); bot = max(data["top"][i] + data["height"][i] for i in idx)
        x0 = min(data["left"][i] for i in idx); x1 = max(data["left"][i] + data["width"][i] for i in idx)
        for g in groups:
            gi = g[1]
            gt = min(data["top"][i] for i in gi); gb = max(data["top"][i] + data["height"][i] for i in gi)
            gx0 = min(data["left"][i] for i in gi); gx1 = max(data["left"][i] + data["width"][i] for i in gi)
            overlap = min(bot, gb) - max(top, gt)
            if overlap > 0.5 * min(bot - top, gb - gt) and (x0 >= gx1 or x1 <= gx0):
                gi.extend(idx)
                break
        else:
            groups.append((key, list(idx)))
    recs = []
    for key, idx in groups:
        idx.sort(key=lambda i: data["left"][i])
        hs = sorted(data["height"][i] for i in idx)
        h = hs[len(hs) // 2] or 20
        cells: list[list[str]] = [[data["text"][idx[0]]]]
        xs = [data["left"][idx[0]]]
        for a, c in zip(idx, idx[1:]):
            gap = data["left"][c] - (data["left"][a] + data["width"][a])
            if gap > max(0.9 * h, 20):           # межсловный пробел ≈ 0,3–0,4 высоты строки
                cells.append([])
                xs.append(data["left"][c])
            cells[-1].append(data["text"][c])
        confs = [float(data["conf"][i]) for i in idx if float(data["conf"][i]) >= 0]
        recs.append({"key": key, "cells": [" ".join(c) for c in cells], "xs": xs, "text": " ".join(data["text"][i] for i in idx),
                     "bbox": (min(data["left"][i] for i in idx), min(data["top"][i] for i in idx),
                              max(data["left"][i] + data["width"][i] for i in idx),
                              max(data["top"][i] + data["height"][i] for i in idx)),
                     "conf": sum(confs) / len(confs) / 100 if confs else None})
    buf: list[dict] = []

    def flush():
        if not buf:
            return
        text = ""
        for r in buf:
            text = text[:-1] + r["text"] if text.endswith("-") else (text + " " + r["text"]).strip()
        bb = (min(r["bbox"][0] for r in buf), min(r["bbox"][1] for r in buf), max(r["bbox"][2] for r in buf),
              max(r["bbox"][3] for r in buf))
        confs = [r["conf"] for r in buf if r["conf"] is not None]
        n0 = recs.index(buf[0]) + 1
        b.add("paragraph" if len(buf) > 1 else "line", text, page=page,
              locator=f"строки {n0}–{n0 + len(buf) - 1} (OCR)" if len(buf) > 1 else f"строка {n0} (OCR)", bbox=bb, ocr=True,
              ocr_conf=round(sum(confs) / len(confs), 3) if confs else None)
        buf.clear()

    header: dict | None = None             # заголовок текущей таблицы: первая строка группы строк-таблиц
    for n, r in enumerate(recs, 1):
        if len(r["cells"]) >= 2:
            flush()
            if header is None:
                header = r
                b.add("line", " ".join(r["cells"]), page=page, locator=f"строка {n} (OCR, заголовок таблицы)",
                      bbox=r["bbox"], ocr=True, ocr_conf=round(r["conf"], 3) if r["conf"] is not None else None)
                continue
            cols = _align_cells(r, header)
            b.add("table_row", "; ".join(f"{h}: {c}" for h, c in zip(header["cells"], cols) if c), page=page,
                  locator=f"строка {n} (OCR)", bbox=r["bbox"], cells=cols, header=header["cells"], ocr=True,
                  ocr_conf=round(r["conf"], 3) if r["conf"] is not None else None)
            continue
        header = None
        if buf and r["key"][:2] == buf[-1]["key"][:2] and not SECTION_RE.match(r["text"]):
            buf.append(r)
        else:
            flush()
            buf.append(r)
    flush()


def _align_cells(row: dict, header: dict) -> list[str]:
    """Раскладывает ячейки строки по колонкам заголовка: ячейка — в колонку с ближайшим левым краем не правее неё."""
    cols = [""] * len(header["cells"])
    for x, cell in zip(row["xs"], row["cells"]):
        j = max((i for i, hx in enumerate(header["xs"]) if hx <= x + 30), default=0)
        cols[j] = (cols[j] + " " + cell).strip()
    return cols


def parse_image(path: Path, doc_id: str) -> ParsedDocument:
    b = _Builder(doc_id)
    b.out.pages = 1
    _ocr_into(b, path.read_bytes(), page=1)
    return b.out


PARSERS = {"pdf": parse_pdf, "docx": parse_docx, "xlsx": parse_xlsx, "csv": parse_csv, "txt": parse_txt,
           "png": parse_image, "jpg": parse_image, "jpeg": parse_image}


def parse(path: Path, fmt: str, doc_id: str) -> ParsedDocument:
    fn = PARSERS.get(fmt)
    if fn is None:
        raise ParseError(f"Формат «{fmt}» не поддерживается")
    return fn(path, doc_id)
