"""Рендеринг текстового содержимого документов из модели изделия.

Каждый документ — список блоков: ("h", текст) | ("p", текст) | ("table", [[...], ...]).
Для каждого требования есть несколько вариантов формулировки, разделённых на
набор "dev" (по нему разрабатываются правила извлечения) и "test" (используется в
экспериментах и при разработке не просматривается) — мера против подгонки экстрактора.
"""
from __future__ import annotations

import random

from model import (CHANGES, COMP, COMPONENTS, DEPENDS_ON, DOC, EXTRA_MATERIALS, INJECTIONS, MAT, MATERIALS,
                   PARAMS, REQS, TESTS, Req)

BANNER = ("СИНТЕТИЧЕСКИЙ ДОКУМЕНТ. Создан для демонстрации системы EIS. "
          "Не является документацией реального изделия.")

ADJ = {
    "max":   {"f": "максимальная", "n": "максимальное", "m": "максимальный"},
    "nom":   {"f": "номинальная", "n": "номинальное", "m": "номинальный"},
    "allow": {"f": "допустимая", "n": "допустимое", "m": "допустимый"},
    "limit": {"f": "предельная", "n": "предельное", "m": "предельный"},
}
MUST = {"f": "должна", "n": "должно", "m": "должен"}


def cap(s: str) -> str:
    return s[:1].upper() + s[1:]


class Ctx:
    def __init__(self, variant_set: str, seed: int):
        self.vs = variant_set
        self.rng = random.Random(seed)

    def pick(self, dev: list[str], test: list[str]) -> str:
        pool = dev if self.vs == "dev" else test if self.vs == "test" else dev + test
        return self.rng.choice(pool)

    # --- числа и единицы
    def num(self, v: float, signed: bool = False) -> str:
        s = f"{v:g}".replace(".", ",")
        if v < 0:
            s = self.pick(["−" + s[1:]], ["-" + s[1:], "минус " + s[1:]])
        elif signed and v > 0:
            s = "+" + s
        return s

    def unit(self, u: str) -> str:
        if u == "°C":
            return self.pick(["°C"], ["°С", "°C"])        # второй вариант — кириллическая «С»
        if u == "м³/ч":
            return self.pick(["м³/ч"], ["м3/ч", "м³/ч"])
        if u == "об/мин":
            return self.pick(["об/мин"], ["мин⁻¹", "об/мин"])
        return u

    def val(self, r: Req, v) -> str:
        if isinstance(v, str):
            return v
        u = self.unit(r.unit)
        sep = "" if u.startswith("°") and self.vs == "dev" else " "
        return f"{self.num(v, signed=r.unit == '°C' and r.op == 'range')}{sep}{u}"


# Формулировки, которые удобнее задать вручную (нестандартная лексика документа)
CUSTOM = {
    "R23": (["Расчётное давление корпуса насоса принято равным {v}."],
            ["Корпус насоса рассчитан на давление не более {v}."]),
    "R26": (["Диапазон измерения датчика давления: от {lo} до {hi}."],
            ["Датчик давления имеет диапазон измерения {lo}…{hi}."]),
    "R29": (["Диапазон измерения датчика температуры подшипника: от {lo} до {hi}."],
            ["Датчик температуры подшипника измеряет температуру в диапазоне от {lo} до {hi}."]),
    "R57": (["Вал насоса рассчитан на передаваемую мощность не более {v}."],
            ["Допустимая передаваемая мощность для вала насоса — не более {v}."]),
    "R27": (["Давление настройки клапана предохранительного — {v}."],
            ["Клапан предохранительный настраивается на давление {v}."]),
    "R55": (["Давление срабатывания клапана предохранительного — {v}."],
            ["Срабатывание клапана предохранительного: {v}."]),
    "R44": (["Аварийная уставка по температуре нагрева подшипникового узла — {v}."],
            ["Аварийная уставка: температура нагрева подшипникового узла {v}."]),
    "R45": (["Предупредительная уставка по температуре нагрева подшипникового узла — {v}."],
            ["Предупредительная уставка: температура нагрева подшипникового узла {v}."]),
    "R14": (["Степень защиты электродвигателя — не ниже {v} по ГОСТ 14254."],
            ["Электродвигатель должен иметь степень защиты не ниже {v} по ГОСТ 14254."]),
    "R31": (["Степень защиты — не ниже {v}."], ["Степень защиты оболочки: не ниже {v}."]),
}


def req_text(ctx: Ctx, r: Req) -> str:
    p = PARAMS[r.param]
    pn = p.nom if ctx.vs == "dev" or not p.alt_nom else ctx.rng.choice([p.nom, *p.alt_nom])
    g = p.gender
    subj = COMP[r.subject]
    S = (" " + subj.gen) if r.explicit else ""
    v = ctx.val(r, r.value) if r.value is not None else ""
    lo = ctx.num(r.low, signed=r.unit == "°C") if r.low is not None else ""
    hi = ctx.val(r, r.high) if r.high is not None else ""

    if r.id in CUSTOM:
        dev, test = CUSTOM[r.id]
        return ctx.pick(dev, test).format(v=v, lo=lo, hi=hi)

    if r.kind == "capability":
        Sg = subj.gen
        if r.op == "<=":
            t = ctx.pick([f"{cap(ADJ['allow'][g])} {pn} для {Sg} — не более {v}."],
                         [f"{cap(ADJ['limit'][g])} {pn} для {Sg} составляет {v}."])
        else:  # range
            t = ctx.pick([f"{cap(ADJ['allow'][g])} {pn} для {Sg} — от {lo} до {hi}."],
                         [f"Диапазон {p.gen}, допустимый для {Sg}: от {lo} до {hi}."])
        return t
    if r.kind == "nominal":
        return ctx.pick([f"{cap(ADJ['nom'][g])} {pn}{S} — {v}."],
                        [f"{cap(pn)}{S} (номинальное значение): {v}.", f"{cap(pn)}{S} {MUST[g]} составлять {v}."])
    # demand
    if r.op == "<=":
        return ctx.pick([f"{cap(pn)}{S} — не более {v}.", f"{cap(ADJ['max'][g])} {pn}{S} составляет {v}."],
                        [f"{cap(pn)}{S} не {MUST[g]} превышать {v}.", f"{cap(pn)}{S}: не выше {v}."])
    if r.op == ">=":
        return ctx.pick([f"{cap(pn)}{S} — не менее {v}."], [f"{cap(pn)}{S} не {MUST[g]} быть менее {v}."])
    if r.op == "=":
        return ctx.pick([f"{cap(pn)}{S} — {v}."], [f"{cap(pn)}{S} {MUST[g]} составлять {v}."])
    if r.op == "range":
        return ctx.pick([f"{cap(pn)}{S} — от {lo} до {hi}."], [f"{cap(pn)}{S} в диапазоне от {lo} до {hi}."])
    raise ValueError(r)


def _sec_key(r: Req):
    return [int(x) if x.isdigit() else x for x in r.section.replace("T", "").split(".")]


def reqs_of(doc_id: str) -> list[Req]:
    return sorted([r for r in REQS if r.doc == doc_id], key=_sec_key)


def numbered(ctx: Ctx, doc_id: str, prefix_section: bool = True) -> list[tuple]:
    out = []
    for r in reqs_of(doc_id):
        t = req_text(ctx, r)
        out.append(("p", f"{r.section} {t}" if prefix_section and r.section else t, [r.id]))
    return out


def names(ids) -> str:
    return ", ".join(COMP[i].nom for i in ids)


# ------------------------------------------------------------------ документы

def doc_D01(ctx):
    rs = {r.section: r for r in reqs_of("D01")}
    b = [("h", "1 Наименование и область применения", []),
         ("p", "Насосный агрегат НА-200 предназначен для перекачивания воды и нейтральных жидкостей "
               "в системах теплоснабжения промышленных объектов.", ["P"]),
         ("h", "2 Состав изделия", []),
         ("p", f"В состав насосного агрегата НА-200 входят: {names(['A1', 'A2', 'A3', 'A4'])}.",
          ["P", "A1", "A2", "A3", "A4"]),
         ("h", "3 Технические требования", []),
         ("h", "3.1 Основные параметры", [])]
    groups = [("3.1", None), ("3.2", "3.2 Требования к рабочей среде и давлению"),
              ("3.3", "3.3 Требования к вибрации, шуму и нагреву"), ("3.4", "3.4 Условия эксплуатации и электропитание"),
              ("3.5", "3.5 Надёжность и масса")]
    for pref, head in groups:
        if head:
            b.append(("h", head, []))
        for sec in sorted(s for s in rs if s.startswith(pref + ".")):
            r = rs[sec]
            b.append(("p", f"{sec} {req_text(ctx, r)}", [r.id]))
    b += [("h", "4 Нормативные ссылки", []),
          ("p", "Испытания проводятся по ГОСТ 6134-2007. Степень защиты — по ГОСТ 14254-2015.", [])]
    return b


def doc_D02(ctx):
    rows = [["Поз.", "Обозначение", "Наименование", "Кол.", "Материал", "Примечание"]]
    for i, c in enumerate(COMPONENTS, 1):
        mats = [MAT[c.material].name] if c.material else []
        mats += [MAT[m].name for cid, m in EXTRA_MATERIALS if cid == c.id]
        qty = 4 if c.id == "C16" else 2 if c.id == "C08" else 1
        rows.append([str(i), c.designation, cap(c.nom), str(qty), "; ".join(mats), ""])
    return [("table", rows, [c.id for c in COMPONENTS])]


def doc_D03(ctx):
    dep = {}
    for c, r, why in DEPENDS_ON:
        dep.setdefault(why, []).append(c)
    b = [("h", "1 Описание сборочных единиц", [])]
    for a in [c for c in COMPONENTS if c.kind == "Assembly"]:
        kids = [c.id for c in COMPONENTS if c.parent == a.id]
        if kids:
            t = ctx.pick([f"{cap(a.nom)} состоит из: {names(kids)}."],
                         [f"В состав сборочной единицы «{a.nom}» входят: {names(kids)}."])
            b.append(("p", t, [a.id, *kids]))
    b.append(("h", "2 Характеристики компонентов", []))
    b += numbered(ctx, "D03")
    b.append(("h", "3 Функциональные зависимости", []))
    phr = {
        "medium_contact": (["С перекачиваемой средой контактируют: {}."], ["В контакте с перекачиваемой средой находятся: {}."]),
        "pressure_boundary": (["Границу рабочего давления образуют: {}."], ["Под рабочим давлением находятся: {}."]),
        "ambient_exposure": (["Воздействию температуры окружающего воздуха подвержены: {}."],
                             ["Температура окружающего воздуха воздействует на следующие элементы: {}."]),
        "power_transmission": (["Мощность электродвигателя передают: {}."], ["Крутящий момент от электродвигателя передают: {}."]),
        "vibration_source": (["Источниками вибрации агрегата являются: {}."], ["На виброскорость агрегата влияют: {}."]),
        "mass_contribution": (["Основной вклад в массу агрегата вносят: {}."], ["Массу агрегата в основном определяют: {}."]),
    }
    for why, comps in dep.items():
        if why in phr:
            b.append(("p", ctx.pick(*phr[why]).format(names(comps)), comps))
    b.append(("p", ctx.pick(["Температура нагрева подшипникового узла зависит от температуры перекачиваемой среды."],
                            ["Нагрев подшипникового узла определяется температурой перекачиваемой среды."]), ["A6"]))
    b.append(("p", "Датчик температуры подшипника контролирует температуру нагрева подшипникового узла.", ["C09", "A6"]))
    b.append(("p", "Испытательное давление принимается равным 1,5 рабочего давления; давление настройки клапана "
                   "предохранительного — 1,1 рабочего давления.", ["C14"]))
    return b


def mat_range(ctx, m) -> str:
    return f"от {ctx.num(m.t_low, True)} до {ctx.num(m.t_high, True)}"


def doc_D04(ctx):
    rows = [["Компонент", "Материал", "Температура применения, °C", "НТД"]]
    ids = []
    for c in COMPONENTS:
        mids = ([c.material] if c.material else []) + [m for cid, m in EXTRA_MATERIALS if cid == c.id]
        for mid in mids:
            m = MAT[mid]
            rows.append([cap(c.nom), m.name, mat_range(ctx, m), m.note])
            ids += [c.id, mid]
    return [("h", "1 Ведомость материалов", []), ("table", rows, ids),
            ("h", "2 Требования к материалам", []),
            ("p", "Материалы, контактирующие с перекачиваемой средой, должны сохранять работоспособность во всём "
                  "диапазоне температур, установленном техническим заданием.", [])]


def doc_D05(ctx):
    return [("h", "1 Технические требования", []), *numbered(ctx, "D05"),
            ("p", "1.5 Уплотнительные кольца торцевого уплотнения изготавливаются из резины FKM.", ["C07", "M8"]),
            ("p", "1.6 Пара трения: карбид кремния SiC / карбид кремния SiC.", ["M6"]),
            ("h", "2 Правила приёмки", []),
            ("p", "Каждое уплотнение подвергается испытанию на герметичность.", [])]


def doc_D06(ctx):
    return [("h", "Технические требования к электродвигателю НА-200.02.000", []), *numbered(ctx, "D06"),
            ("p", "6 Режим работы — S1 (продолжительный).", [])]


def doc_D07(ctx):
    return [("h", "1 Исходные данные", []),
            ("p", "Материал корпуса — сталь 25Л. Допускаемое напряжение принято по ГОСТ 34233.1-2017.", ["C01", "M1"]),
            ("h", "2 Результаты расчёта", []), *numbered(ctx, "D07"),
            ("p", "2.2 Толщина стенки корпуса 12 мм обеспечивает запас прочности не менее 1,5 при расчётном давлении.", ["C01"]),
            ("h", "3 Вывод", []), ("p", "Прочность корпуса насоса обеспечена.", ["C01"])]


def doc_D08(ctx):
    d01 = {r.id: r.section for r in reqs_of("D01")}
    crit = {r.section: r for r in reqs_of("D08")}
    b = [("h", "1 Объект испытаний", []), ("p", "Насосный агрегат НА-200.", ["P"]), ("h", "2 Программа испытаний", [])]
    for t in TESTS:
        refs = ", ".join(d01[x] for x in t.verifies)
        b.append(("h", f"{t.id} {t.name}", [t.id]))
        b.append(("p", ctx.pick([f"Проверяемые требования: ТЗ п. {refs}."], [f"Испытание подтверждает выполнение требований ТЗ п. {refs}."]),
                  [t.id, *t.verifies]))
        if t.id in crit:
            r = crit[t.id]
            t_ = req_text(ctx, r)
            b.append(("p", "Критерий приёмки: " + t_[0].lower() + t_[1:], [r.id]))
    return b


def doc_D09(ctx):
    rows = [["Испытание", "Наименование", "Результат", "Заключение"]]
    for t in TESTS:
        rows.append([t.id, t.name, t.measured, "соответствует"])
    return [("table", rows, [t.id for t in TESTS])]


def doc_D10(ctx):
    rs = {r.section: r for r in reqs_of("D10")}
    b = [("h", "1 Описание и работа", [])]
    for s in ("1.1", "1.2", "1.3", "1.4", "1.5"):
        b.append(("p", f"{s} {req_text(ctx, rs[s])}", [rs[s].id]))
    b += [("h", "2 Подготовка к работе", []),
          ("p", "Перед пуском заполнить насос перекачиваемой жидкостью и проверить центровку муфты соединительной.", ["A3"]),
          ("p", INJECTIONS[0]["text"], []),
          ("h", "3 Использование по назначению", []),
          ("p", "Не допускается работа насоса без перекачиваемой среды.", ["A1"]),
          ("h", "4 Техническое обслуживание", [])]
    for s in ("4.1", "4.2"):
        b.append(("p", f"{s} {req_text(ctx, rs[s])}", [rs[s].id]))
    b.append(("p", "4.3 Замену смазки подшипникового узла производить через 4000 ч работы.", ["A6"]))
    return b


def doc_D11(ctx):
    return [("h", "Паспорт подшипникового узла НА-200.06.000", []),
            ("p", "1 Подшипниковый узел включает подшипник радиальный 6312 и датчик температуры подшипника.", ["A6", "C08", "C09"]),
            *numbered(ctx, "D11"),
            ("p", "4 Смазка: Литол-24, заправка 0,3 кг.", ["M10"])]


def doc_D12(ctx):
    return [("h", "1 Муфта соединительная", []), *[x for x in numbered(ctx, "D12") if x[1].startswith("1.")],
            ("h", "2 Опоры", []), *[x for x in numbered(ctx, "D12") if x[1].startswith("2.")]]


def doc_D13(ctx):
    rs = {r.section: r for r in reqs_of("D13")}
    return [("h", "КАРТА УСТАВОК ДАТЧИКОВ НА-200", [])] + [("p", f"{s}. {req_text(ctx, rs[s])}", [rs[s].id]) for s in sorted(rs)]


def doc_D14(ctx):
    rows = [["Извещение", "Дата", "Документ", "Редакция", "Заменяет", "Содержание изменения"]]
    for c in CHANGES:
        rows.append([c["id"], c["date"], c["document"], c["edition"], c["supersedes"], c["text"]])
    return [("table", rows, [c["id"] for c in CHANGES])]


RENDERERS = {f"D{i:02d}": globals()[f"doc_D{i:02d}"] for i in range(1, 15)}


def render_all(variant_set: str, seed: int) -> dict[str, list[tuple]]:
    ctx = Ctx(variant_set, seed)
    return {d: fn(ctx) for d, fn in RENDERERS.items()}
