"""Восстановление структуры текста по геометрии слов OCR (без запуска Tesseract)."""
from eis.parsing.parsers import _Builder, _layout_into

H, CHAR, SPACE, COLUMN = 28, 14, 10, 320     # высота строки, ширина символа, пробел, шаг колонок таблицы


def words(rows):
    """rows: [(block, par, line, «слова; | — граница колонки»)] → словарь формата pytesseract.image_to_data."""
    d = {k: [] for k in ("text", "block_num", "par_num", "line_num", "left", "top", "width", "height", "conf")}
    for n, (blk, par, ln, text) in enumerate(rows):
        x, col = 90, 0
        for tok in text.split(" "):
            if tok == "|":                     # следующая ячейка — с левого края следующей колонки
                col += 1
                x = 90 + col * COLUMN
                continue
            d["text"].append(tok); d["block_num"].append(blk); d["par_num"].append(par); d["line_num"].append(ln)
            d["left"].append(x); d["top"].append(100 + 46 * n); d["width"].append(len(tok) * CHAR)
            d["height"].append(H); d["conf"].append(90)
            x += len(tok) * CHAR + SPACE
    return d


def test_wrapped_paragraph_is_merged_and_section_starts_new_fragment():
    b = _Builder("doc:x")
    _layout_into(b, words([(1, 1, 1, "1.2 Рабочее давление не"), (1, 1, 2, "более 1,6 МПа."),
                           (1, 1, 3, "1.3 Подача 200 м³/ч.")]))
    assert [f.text for f in b.out.fragments] == ["1.2 Рабочее давление не более 1,6 МПа.", "1.3 Подача 200 м³/ч."]
    assert b.out.fragments[0].kind == "paragraph" and b.out.fragments[0].section == "1.2"


def test_wide_gaps_become_table_cells_aligned_to_header():
    b = _Builder("doc:x")
    _layout_into(b, words([(2, 1, 1, "Материал | Температура | НТД"),
                           (2, 1, 2, "Резина | -30…100 | ГОСТ")]))
    head, row = b.out.fragments
    assert head.kind == "line" and row.kind == "table_row"
    assert row.header == ["Материал", "Температура", "НТД"] and row.cells == ["Резина", "-30…100", "ГОСТ"]
