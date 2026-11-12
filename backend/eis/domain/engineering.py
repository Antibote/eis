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

# Класс параметра определяет, в каком направлении изменение требует перепроверки зависимых узлов:
#   load   — внешнее воздействие на узлы (нагрузка, режим): опасно расширение диапазона / рост номинала;
#            смягчение не требует перепроверки (остаются только сохраняющиеся нарушения и производные);
#   budget — предел суммарной характеристики изделия (масса, шум, ресурс): ужесточение затрагивает вкладчиков,
#            смягчение — нет;
#   state  — предел на состояние самого узла (нагрев, вибрация): в обе стороны — узел должен выдержать
#            новое допустимое состояние, а контроль (уставки, испытания) — соответствовать новому пределу.
PARAM_CLASS: dict[str, str] = {
    "medium_temperature": "load", "ambient_temperature": "load", "working_pressure": "load", "test_pressure": "load",
    "power": "load", "torque": "load", "rotation_speed": "load", "flow_rate": "load", "head": "load",
    "mass": "budget", "noise_level": "budget", "service_life": "budget",
    "bearing_temperature": "state", "vibration_velocity": "state",
}

# Законы подобия центробежных насосов: при изменении частоты вращения n подача ∝ n, напор ∝ n², мощность ∝ n³.
AFFINITY: dict[str, dict[str, int]] = {"rotation_speed": {"flow_rate": 1, "head": 2, "power": 3}}


def change_is_harsher(param: str, old: tuple[float, float], new: tuple[float, float], operator: str) -> bool:
    """Требует ли изменение перепроверки зависимых узлов (см. PARAM_CLASS). Интервалы в единицах СИ."""
    cls = PARAM_CLASS.get(param, "load")
    if cls == "state":
        return True
    widened = new[0] < old[0] - 1e-12 or new[1] > old[1] + 1e-12
    narrowed = new[0] > old[0] + 1e-12 or new[1] < old[1] - 1e-12
    if cls == "budget":
        return narrowed
    if operator == "=":              # номинал нагрузки: опасен рост
        return new[1] > old[1] + 1e-12
    return widened

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
