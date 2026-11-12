"""Определение типа документа и его обозначения (по ГОСТ 2.102 / 2.602 коды документов)."""
from __future__ import annotations

import re

DOC_CODE_RE = re.compile(r"(?P<des>[А-ЯA-Z]{1,6}-?\d+(?:\.\d{2,3}){2,})\s+(?P<code>[А-Я]{2,3})\b")

TYPE_BY_CODE = {
    "ТЗ": "TechnicalSpecification", "СП": "Specification", "ПЗ": "ExplanatoryNote", "ВМ": "MaterialRequirements",
    "ТУ": "ComponentSpecification", "ТТ": "ComponentSpecification", "РР": "Calculation", "ПМ": "TestProgram",
    "ПИ": "TestReport", "РЭ": "OperationManual", "ПС": "Passport", "ФО": "Passport", "КУ": "Setpoints",
    "ЖИ": "ChangeLog", "ИИ": "ChangeLog",
}
TYPE_BY_TITLE = [
    (r"техническое\s+задание", "TechnicalSpecification"), (r"спецификаци", "Specification"),
    (r"пояснительн", "ExplanatoryNote"), (r"материал", "MaterialRequirements"),
    (r"технические\s+(?:условия|требования)", "ComponentSpecification"), (r"расч[её]т", "Calculation"),
    (r"программа\s+и\s+методика", "TestProgram"), (r"протокол", "TestReport"),
    (r"руководство\s+по\s+эксплуатации", "OperationManual"), (r"паспорт|формуляр", "Passport"),
    (r"уставк", "Setpoints"), (r"извещени|журнал\s+изменени", "ChangeLog"),
]


def classify(header_lines: list[str], filename: str) -> tuple[str | None, str | None, str | None, float, str | None]:
    """→ (обозначение изделия/компонента, код документа, тип, уверенность, заголовок)."""
    text = "\n".join(header_lines)
    cands = []
    for ln in header_lines:
        for part in re.split(r"\.\s+", ln):
            part = DOC_CODE_RE.sub("", part).strip(" .")
            if len(part) > 8 and "СИНТЕТИЧЕСКИЙ" not in part.upper() and "демонстрации" not in part:
                cands.append(part)
    title = cands[0] if cands else None
    m = DOC_CODE_RE.search(text)
    if m and m.group("code") in TYPE_BY_CODE:
        return m.group("des"), f"{m.group('des')} {m.group('code')}", TYPE_BY_CODE[m.group("code")], 0.95, title
    low = (text + " " + filename).lower()
    for rx, t in TYPE_BY_TITLE:
        if re.search(rx, low):
            return (m.group("des") if m else None), None, t, 0.6, title
    return None, None, None, 0.0, title
