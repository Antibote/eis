"""Словарь инженерных параметров и маркеров вида требования.

Словарь составлен по предметной области (насосное оборудование, ГОСТ 6134, ГОСТ 14254,
ГОСТ ИСО 10816) и не зависит от генератора синтетических документов.
Порядок важен: более специфичные шаблоны идут раньше общих.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# (regex по тексту в нижнем регистре, ключ параметра, размерность, подсказка вида или None)
PARAMETERS: list[tuple[str, str, str, str | None]] = [
    (r"температур\w*\s+(?:нагрева\s+)?подшипник\w*", "bearing_temperature", "temperature", None),
    (r"температур\w*\s+нагрева", "bearing_temperature", "temperature", None),
    (r"температур\w*\s+перекачиваем\w+\s+(?:сред\w*|жидкост\w*)", "medium_temperature", "temperature", None),
    (r"температур\w*\s+(?:рабоч\w+\s+)?сред\w*(?!\s+окруж)", "medium_temperature", "temperature", None),
    (r"температур\w*\s+окружающ\w+\s+(?:воздух\w*|сред\w*)", "ambient_temperature", "temperature", None),
    # «рабочая температура» насосного агрегата — температура перекачиваемой среды
    (r"рабоч\w+\s+температур\w*", "medium_temperature", "temperature", None),
    (r"температур\w*\s+примен\w*", "material_temperature", "temperature", "capability"),
    (r"испытательн\w+\s+давлени\w*|давлени\w*\s+(?:гидравлическ\w+\s+)?испытани\w*", "test_pressure", "pressure", None),
    (r"давлени\w*\s+(?:настройки|срабатывани\w*)|срабатывани\w*\s+клапан\w*|настраива\w+\s+на\s+давлени\w*",
     "working_pressure", "pressure", "setpoint"),
    (r"расч[её]тн\w+\s+давлени\w*|рассчитан\w*\s+на\s+давлени\w*", "working_pressure", "pressure", "capability"),
    (r"рабоч\w+\s+давлени\w*|давлени\w*\s+на\s+выходе|давлени\w*\s+нагнетани\w*", "working_pressure", "pressure", None),
    (r"подач\w*|производительност\w*|расход\w*", "flow_rate", "flow", None),
    (r"напор\w*", "head", "length", None),
    (r"частот\w*\s+вращени\w*|скорост\w*\s+вращени\w*", "rotation_speed", "rotation", None),
    (r"крутящ\w+\s+момент\w*", "torque", "torque", None),
    (r"передаваем\w+\s+мощност\w*", "power", "power", "capability"),
    (r"(?:номинальн\w+\s+|потребляем\w+\s+)?мощност\w*", "power", "power", None),
    (r"(?:среднеквадратичн\w+\s+значени\w+\s+)?виброскорост\w*", "vibration_velocity", "velocity", None),
    (r"уров\w+\s+(?:звук\w*|шума)|шум\w*", "noise_level", "sound", None),
    (r"(?:назначенн\w+\s+)?ресурс\w*|срок\w*\s+службы", "service_life", "time", None),
    (r"масс\w*", "mass", "mass", None),
    (r"степен\w*\s+защиты", "ingress_protection", "ip", None),
    (r"(?:номинальн\w+\s+)?напряжени\w*(?:\s+питани\w+)?", "voltage", "voltage", None),
    (r"диапазон\w*\s+измерени\w*|измеря\w+\s+(?:температур\w*|давлени\w*)", "measurement_range", "*", "capability"),
]
PARAM_RE = [(re.compile(r"(?<![а-яa-z])" + p), key, dim, hint) for p, key, dim, hint in PARAMETERS]

KIND_CUES = [
    ("setpoint", re.compile(r"уставк\w*|настройк\w*|срабатывани\w*")),
    ("capability", re.compile(r"допустим\w*|предельн\w*|рассчитан\w*|работоспособ\w*|выдерживает|диапазон\w*,?\s+допустим")),
    ("nominal", re.compile(r"номинальн\w*")),
]

OPERATOR_CUES = [
    ("range", re.compile(r"(?:от|в\s+диапазоне\s+от|в\s+пределах\s+от)\s+(?P<lo>" r"(?:[−\-–]|минус\s)?\s?\+?\d+(?:[.,]\d+)?)"
                         r"\s*(?P<lou>[^\d\s]{0,6})?\s*до\s+(?P<hi>(?:[−\-–]|минус\s)?\s?\+?\d+(?:[.,]\d+)?)")),
    ("range", re.compile(r"(?P<lo>(?:[−\-–]|минус\s)?\+?\d+(?:[.,]\d+)?)\s*(?:…|\.\.\.|÷)\s*(?P<hi>(?:[−\-–])?\+?\d+(?:[.,]\d+)?)")),
    ("<=", re.compile(r"не\s+более|не\s+выше|не\s+долж(?:ен|н\w+)\s+превышать|не\s+превыша\w+|максимальн\w*|предельн\w*|"
                      r"≤|<=|(?<![а-я])до(?=\s+[−\-+]?\d)")),
    (">=", re.compile(r"не\s+менее|не\s+ниже|не\s+долж(?:ен|н\w+)\s+быть\s+(?:менее|ниже)|минимальн\w*|≥|>=")),
]

INJECTION_RE = re.compile(
    r"игнориру\w+\s+(?:все\s+)?(?:предыдущ|прежн|вышеуказан)\w*\s+(?:инструкц|указани)|"
    r"ignore\s+(?:all\s+)?(?:previous|prior)\s+instructions|"
    r"(?:для|к)\s+(?:систем\w*\s+)?(?:искусственного\s+интеллекта|ии|ai|llm|нейросет\w*)[:,]|"
    r"system\s+prompt|системн\w+\s+(?:промпт|инструкц)|"
    r"ты\s+(?:теперь|должен)\s+(?:—|-)?\s*(?:отвеча|сообща)",
    re.IGNORECASE)


@dataclass
class ParamHit:
    key: str
    dimension: str
    hint: str | None
    start: int
    end: int


def find_params(text_lc: str) -> list[ParamHit]:
    """Все непересекающиеся упоминания параметров (более ранние шаблоны приоритетнее)."""
    hits: list[ParamHit] = []
    taken: list[tuple[int, int]] = []
    for rx, key, dim, hint in PARAM_RE:
        for m in rx.finditer(text_lc):
            s, e = m.span()
            if any(s < te and e > ts for ts, te in taken):
                continue
            taken.append((s, e))
            hits.append(ParamHit(key, dim, hint, s, e))
    return sorted(hits, key=lambda h: h.start)


def kind_of(text_lc: str, hint: str | None) -> str:
    if hint:
        return hint
    for kind, rx in KIND_CUES:
        if rx.search(text_lc):
            return kind
    return "demand"
