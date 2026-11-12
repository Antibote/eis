"""Распознавание и нормализация чисел и единиц измерения.

Каноническая единица задаётся для каждой физической размерности; все сравнения
выполняются только после приведения к ней. Таблица коэффициентов явная и тестируемая.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

CANONICAL = {
    "temperature": "°C", "pressure": "МПа", "flow": "м³/ч", "length": "м", "rotation": "об/мин", "power": "кВт",
    "velocity": "мм/с", "sound": "дБА", "time": "ч", "mass": "кг", "voltage": "В", "torque": "Н·м", "ip": "",
}

# написание → (размерность, множитель к канонической, смещение)
_UNITS: list[tuple[str, str, float, float]] = [
    # температура (°C, °С с кириллической С, ℃, К)
    (r"°\s?[CС]|℃|град(?:\.|усов)?\s?[CС]?", "temperature", 1.0, 0.0),
    (r"K(?![a-zа-я])|К(?![a-zа-я])", "temperature", 1.0, -273.15),
    # давление
    (r"МПа|MPa", "pressure", 1.0, 0.0),
    (r"кПа|kPa", "pressure", 1e-3, 0.0),
    (r"бар|bar", "pressure", 0.1, 0.0),
    (r"кгс/см[²2]|кгс/кв\.?\s?см|ат(?![a-zа-я])", "pressure", 0.0980665, 0.0),
    (r"Па(?![a-zа-я])", "pressure", 1e-6, 0.0),
    # расход
    (r"м[³3]/ч|куб\.?\s?м/ч", "flow", 1.0, 0.0),
    (r"л/с", "flow", 3.6, 0.0),
    (r"м[³3]/с", "flow", 3600.0, 0.0),
    # частота вращения
    (r"об\.?/мин|мин[⁻-]¹|мин-1|rpm", "rotation", 1.0, 0.0),
    # мощность
    (r"кВт|kW", "power", 1.0, 0.0),
    (r"МВт", "power", 1000.0, 0.0),
    (r"Вт(?![a-zа-я])|W(?![a-z])", "power", 1e-3, 0.0),
    # скорость (вибрация)
    (r"мм/с", "velocity", 1.0, 0.0),
    (r"м/с", "velocity", 1000.0, 0.0),
    # звук
    (r"дБ\s?\(?А\)?|дБА|dBA", "sound", 1.0, 0.0),
    # время
    (r"ч(?:ас(?:ов|а)?)?(?![a-zа-я])", "time", 1.0, 0.0),
    (r"мин(?![a-zа-я⁻-])", "time", 1 / 60, 0.0),
    # масса
    (r"кг(?![a-zа-я])|kg", "mass", 1.0, 0.0),
    (r"т(?![a-zа-я])", "mass", 1000.0, 0.0),
    # напряжение
    (r"кВ(?![a-zа-ят])", "voltage", 1000.0, 0.0),
    (r"В(?![a-zа-ят])|V(?![a-z])", "voltage", 1.0, 0.0),
    # момент
    (r"Н[·⋅*\.]?\s?м|Нм|N·m", "torque", 1.0, 0.0),
    (r"кН[·⋅*\.]?\s?м", "torque", 1000.0, 0.0),
    # длина (для отсева: «12 мм» не является давлением)
    (r"мм(?![a-zа-я/])", "length", 1e-3, 0.0),
    (r"м(?![a-zа-я/³3])", "length", 1.0, 0.0),
]
_UNIT_RE = [(re.compile(p), dim, k, off) for p, dim, k, off in _UNITS]

NUM = r"(?:[−\-–]|минус\s)?\s?\+?\d+(?:[.,]\d+)?"
NUM_RE = re.compile(NUM)


def parse_number(s: str) -> float:
    s = s.strip().replace(" ", "")
    neg = s.startswith(("−", "-", "–", "минус"))
    s = re.sub(r"^(?:[−\-–]|минус)", "", s).lstrip("+").replace(",", ".")
    v = float(s)
    return -v if neg else v


@dataclass
class UnitMatch:
    text: str
    dimension: str
    factor: float
    offset: float
    start: int
    end: int


def match_unit(text: str, pos: int = 0) -> UnitMatch | None:
    """Единица, начинающаяся в позиции pos (допускаются пробелы перед ней)."""
    m_ws = re.compile(r"\s*").match(text, pos)
    p = m_ws.end()
    best = None
    for rx, dim, k, off in _UNIT_RE:
        m = rx.match(text, p)
        if m and (best is None or len(m.group(0)) > len(best.text)):
            best = UnitMatch(m.group(0), dim, k, off, m.start(), m.end())
    return best


def unit_in(text: str) -> UnitMatch | None:
    """Первая единица где-либо в строке (для заголовков таблиц: «Температура применения, °C»)."""
    for i in range(len(text)):
        if i == 0 or not text[i - 1].isalpha():
            u = match_unit(text, i)
            if u and u.start == i:
                return u
    return None


def to_canonical(value: float, u: UnitMatch) -> float:
    return round(value * u.factor + u.offset, 6)
