"""Формирование отчётов DOCX/PDF: анализ последствий изменения и реестр противоречий.
Каждый вывод в отчёте сопровождается источником (документ, место, цитата)."""
from __future__ import annotations

import io
from datetime import datetime

from eis.domain.models import KnowledgeBase
from eis.domain.results import Contradiction, ImpactReport
from eis.services.contradictions import PARAM_RU

CLS_RU = {"confirmed": "Подтверждённое влияние", "direct": "Прямая зависимость", "potential": "Потенциальное влияние",
          "documentary": "Документальная связь"}
STATUS_RU = {"confirmed": "подтверждено", "potential": "потенциальное", "insufficient_data": "недостаточно данных"}
NOTE = ("Отчёт сформирован автоматически системой EIS. Выводы требуют проверки инженером. "
        "Исходные данные демонстрационного набора являются синтетическими.")


def _src(kb: KnowledgeBase, ev) -> str:
    d = kb.documents.get(ev.document_id)
    return f"{(d.code or d.filename) if d else ev.document_id}, {ev.locator or ''}: «{ev.quote[:160]}»"


def impact_sections(rep: ImpactReport, kb: KnowledgeBase) -> list[tuple[str, list]]:
    subj = kb.entities.get(rep.subject_id)
    head = [f"Изменяемое требование: {PARAM_RU.get(rep.parameter, rep.parameter)} — «{subj.name if subj else rep.subject_id}»",
            f"Было: {rep.old}; стало: {rep.new}", f"Формулировка: «{rep.requirement_text}»"]
    rows = [["Элемент", "Класс", "Достоверность", "Проверка", "Основание"]]
    for it in rep.items:
        rows.append([it.name, CLS_RU[it.impact_class], f"{it.confidence:.2f}",
                     it.check.detail[:200] if it.check else "—", _src(kb, it.evidence[0]) if it.evidence else "—"])
    docs = [["Документ", "Причины"]] + [[d.code or d.filename, "; ".join(d.reasons)[:400]] for d in rep.documents]
    tests = [["Испытание", "Причина", "Результат"]] + [[t.name, t.reason, t.result or "—"] for t in rep.tests]
    derived = [f"{d.description}: новое расчётное значение {d.new_expected:g}; в документах: {', '.join(d.stated)}"
               for d in rep.derived if d.new_expected is not None]
    conflicts = [c.description for c in rep.conflicts_after_change]
    return [("Исходные данные", head), ("Затронутые элементы", [rows]), ("Документы, требующие пересмотра", [docs]),
            ("Испытания", [tests]), ("Производные величины", derived), ("Расхождения после изменения", conflicts),
            ("Рекомендации", rep.recommendations)]


def contradiction_sections(items: list[Contradiction], kb: KnowledgeBase) -> list[tuple[str, list]]:
    out = []
    for i, c in enumerate(items, 1):
        body = [f"Тип: {c.type}; статус: {STATUS_RU[c.status]}; серьёзность: {c.severity}; достоверность: {c.confidence:.2f}",
                c.description, f"Объяснение: {c.explanation}", f"Рекомендация: {c.recommendation}"]
        body += [f"Источник {k}: {_src(kb, e)}" for k, e in enumerate(c.evidence, 1)]
        out.append((f"{i}. {c.title}", body))
    return out


def to_docx(title: str, sections: list[tuple[str, list]]) -> bytes:
    import docx
    from docx.shared import Pt
    d = docx.Document()
    d.styles["Normal"].font.size = Pt(10)
    d.add_heading(title, level=1)
    d.add_paragraph(f"Дата формирования: {datetime.now():%d.%m.%Y %H:%M}")
    d.add_paragraph(NOTE).italic = True
    for head, body in sections:
        d.add_heading(head, level=2)
        for el in body:
            if isinstance(el, list):
                t = d.add_table(rows=0, cols=len(el[0]))
                t.style = "Table Grid"
                for r in el:
                    for c, v in zip(t.add_row().cells, r):
                        c.text = str(v)
            else:
                d.add_paragraph(str(el), style="List Bullet" if head == "Рекомендации" else None)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def to_pdf(title: str, sections: list[tuple[str, list]]) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    for name, path in (("DejaVu", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
                       ("DejaVuB", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")):
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, path))
    st = ParagraphStyle("b", fontName="DejaVu", fontSize=9, leading=12)
    sm = ParagraphStyle("s", fontName="DejaVu", fontSize=7.5, leading=9.5)
    h1 = ParagraphStyle("h1", fontName="DejaVuB", fontSize=14, leading=18, spaceAfter=6)
    h2 = ParagraphStyle("h2", fontName="DejaVuB", fontSize=11, leading=14, spaceBefore=8, spaceAfter=4)
    esc = lambda s: str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")  # noqa: E731
    story = [Paragraph(esc(title), h1), Paragraph(f"Дата формирования: {datetime.now():%d.%m.%Y %H:%M}", st),
             Paragraph(esc(NOTE), sm), Spacer(1, 6)]
    page_w = landscape(A4)[0] - 30 * mm
    for head, body in sections:
        story.append(Paragraph(esc(head), h2))
        for el in body:
            if isinstance(el, list):
                data = [[Paragraph(esc(v), sm) for v in r] for r in el]
                t = Table(data, colWidths=[page_w / len(el[0])] * len(el[0]), repeatRows=1)
                t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                                       ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8ecf2")),
                                       ("VALIGN", (0, 0), (-1, -1), "TOP")]))
                story.append(t)
            else:
                story.append(Paragraph("• " + esc(el), st))
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=15 * mm, rightMargin=15 * mm, topMargin=12 * mm,
                      bottomMargin=12 * mm, title=title).build(story)
    return buf.getvalue()
