"""Инженерные знания, используемые формальными правилами (экспертная база, не подгоняется под сценарии).

1. PROPAGATION — как изменение параметра распространяется по типам связей графа
   (учёт физической природы параметра; см. абляцию «без учёта физики» в экспериментах).
2. RELATED — какие параметры содержательно связаны (для отбора документов на пересмотр).
3. DERIVED_RULES — расчётные зависимости (крутящий момент из мощности и частоты вращения).
4. MATERIAL_LIMITED — параметры, для которых проверяется температура применения материалов.
"""
from __future__ import annotations

TEMPERATURE_PARAMS = {"medium_temperature", "ambient_temperature", "bearing_temperature"}

# распространяется ли влияние вниз по составу (CONTAINS) и на материалы (USES_MATERIAL)
PROPAGATION: dict[str, dict[str, bool]] = {
    # тепловое воздействие передаётся на входящие детали и их материалы
    "medium_temperature": {"contains_down": True, "materials": True},
    "ambient_temperature": {"contains_down": True, "materials": True},
    "bearing_temperature": {"contains_down": True, "materials": True},
    # граница давления перечисляется в документации явно — по составу не распространяется
    "working_pressure": {"contains_down": False, "materials": False},
    "test_pressure": {"contains_down": False, "materials": False},
    # механическая нагрузка (мощность/момент) передаётся через детали сборочной единицы
    "power": {"contains_down": True, "materials": False},
    "torque": {"contains_down": True, "materials": False},
    "rotation_speed": {"contains_down": True, "materials": False},
    # вибрация: источники перечисляются явно
    "vibration_velocity": {"contains_down": False, "materials": False},
}
DEFAULT_PROPAGATION = {"contains_down": False, "materials": False}

RELATED: dict[str, set[str]] = {
    "medium_temperature": TEMPERATURE_PARAMS | {"material_temperature"},
    "ambient_temperature": TEMPERATURE_PARAMS | {"material_temperature"},
    "bearing_temperature": TEMPERATURE_PARAMS | {"material_temperature"},
    "working_pressure": {"working_pressure", "test_pressure"},
    "test_pressure": {"working_pressure", "test_pressure"},
    "power": {"power", "torque"},
    "torque": {"power", "torque"},
    "vibration_velocity": {"vibration_velocity"},
}


def related(param: str) -> set[str]:
    return RELATED.get(param, {param})


# Расчётные зависимости: при изменении параметра source вычисляется target.
# M [Н·м] = 9550 · P [кВт] / n [об/мин]
DERIVED_RULES = {
    "power": [{"target": "torque", "needs": "rotation_speed", "fn": lambda p, n: 9550.0 * p / n,
               "formula": "M = 9550·P/n"}],
}

MATERIAL_LIMITED = TEMPERATURE_PARAMS

# Минимальный относительный запас, ниже которого результат проверки считается «на пределе»
MARGIN_WARN = 0.05

# Русские названия параметров (для подписей узлов, отчётов, ответов помощника)
PARAM_RU = {
    "medium_temperature": "температура перекачиваемой среды", "ambient_temperature": "температура окружающего воздуха",
    "bearing_temperature": "температура нагрева подшипникового узла", "working_pressure": "рабочее давление",
    "test_pressure": "испытательное давление", "flow_rate": "подача", "head": "напор", "rotation_speed": "частота вращения",
    "power": "мощность", "vibration_velocity": "виброскорость", "noise_level": "уровень звука", "service_life": "ресурс",
    "mass": "масса", "ingress_protection": "степень защиты", "voltage": "напряжение", "torque": "крутящий момент",
    "material_temperature": "температура применения материала",
}
