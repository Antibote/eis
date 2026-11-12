import pytest

from eis.extraction.units import match_unit, parse_number, to_canonical


@pytest.mark.parametrize("s,v", [("1,6", 1.6), ("−40", -40), ("-45", -45), ("минус 50", -50), ("+80", 80)])
def test_parse_number(s, v):
    assert parse_number(s) == v


@pytest.mark.parametrize("text,dim,val,canon", [
    ("°C", "temperature", 80, 80), ("°С", "temperature", 80, 80),        # латинская и кириллическая «С»
    ("К", "temperature", 373.15, 100), ("кгс/см²", "pressure", 20, 1.96133), ("бар", "pressure", 16, 1.6),
    ("кПа", "pressure", 1600, 1.6), ("м3/ч", "flow", 200, 200), ("л/с", "flow", 10, 36),
    ("мин⁻¹", "rotation", 2950, 2950), ("Н·м", "torque", 200, 200), ("кВт", "power", 55, 55),
])
def test_units(text, dim, val, canon):
    u = match_unit(text)
    assert u and u.dimension == dim
    assert to_canonical(val, u) == pytest.approx(canon, rel=1e-4)


def test_mm_is_not_pressure():
    assert match_unit("мм").dimension == "length"
