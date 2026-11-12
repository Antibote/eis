"""Предложения написаны вручную (не генератором) — проверка обобщения правил."""
from eis.extraction.mentions import MentionIndex
from eis.extraction.requirements import extract_requirements

KINDS = {"p": "Product", "seal": "Component", "motor": "Assembly", "bu": "Assembly"}


def idx():
    m = MentionIndex()
    m.add_with_head_alias("seal", "торцевое уплотнение")
    m.add("motor", "электродвигатель")
    m.add("bu", "подшипниковый узел")
    return m


def ex(text, subj="p"):
    return extract_requirements(text, idx().find(text), KINDS, subj)


def test_max_demand_default_subject():
    (r,) = ex("Температура перекачиваемой среды не должна превышать 95 °C.")
    assert (r.parameter, r.operator, r.value, r.kind, r.subject_id) == ("medium_temperature", "<=", 95, "demand", "p")


def test_masculine_operator():
    (r,) = ex("Назначенный ресурс не должен быть менее 30000 ч.")
    assert (r.parameter, r.operator, r.value) == ("service_life", ">=", 30000)


def test_capability_with_subject_after_dlya():
    (r,) = ex("Предельное рабочее давление для торцевого уплотнения составляет 25 бар.")
    assert (r.kind, r.subject_id, r.value) == ("capability", "seal", 2.5)


def test_range_with_minus_word():
    (r,) = ex("Температура окружающего воздуха — от минус 45 до плюс 40 °C.".replace("плюс ", "+"))
    assert (r.operator, r.low, r.high) == ("range", -45, 40)


def test_wrong_dimension_rejected():
    assert ex("Толщина стенки 12 мм обеспечивает прочность при расчётном давлении.") == []


def test_ip_code():
    (r,) = ex("Степень защиты электродвигателя — не ниже IP 55.")
    assert (r.value, r.operator, r.subject_id) == ("IP55", ">=", "motor")


def test_inflected_mention():
    found = idx().find("Температура нагрева подшипникового узла и уплотнения торцевого")
    assert [m.entity_id for m in found] == ["bu", "seal"]
