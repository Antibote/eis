from eis.services.change_request import parse_change
from eis.services.contradictions import covers, detect_contradictions
from eis.services.impact import ImpactAnalyzer, ImpactSettings

INF = float("inf")


def test_covers_one_sided():
    assert covers((-INF, 80), (-30, 100), "<=")[0]          # нижняя граница не задана требованием
    assert not covers((-INF, 100), (-INF, 90), "<=")[0]
    assert not covers((-50, 40), (-40, 120), "range")[0]


def test_every_relation_has_evidence(dev_kb):
    assert all(r.evidence and r.evidence[0].document_id for r in dev_kb.relations.values())


def test_injection_fragment_not_used(dev_kb):
    flagged = [f for f in dev_kb.fragments.values() if "suspected_injection" in f.flags]
    assert flagged
    used = {e.fragment_id for r in dev_kb.relations.values() for e in r.evidence}
    assert not used & {f.id for f in flagged}


def test_contradictions_have_two_sources(dev_kb, dev_graph):
    cs = detect_contradictions(dev_kb, dev_graph)
    assert len(cs) >= 9
    for c in cs:
        assert len(c.evidence) >= 2 and all(e.quote for e in c.evidence)


def test_no_contradiction_for_different_parameters(dev_kb, dev_graph):
    cs = detect_contradictions(dev_kb, dev_graph)
    for c in cs:
        params = {dev_kb.requirements[i].parameter for i in c.items if i in dev_kb.requirements}
        assert not {"ambient_temperature", "medium_temperature"} <= params


def test_change_temperature(dev_kb, dev_graph):
    pc = parse_change("Максимальная температура перекачиваемой среды увеличивается с 80 °C до 100 °C.", dev_kb, dev_graph)
    rep = ImpactAnalyzer(dev_kb, dev_graph).analyze(pc.requirement.id, new_value=pc.new_value)
    confirmed = {i.name for i in rep.items if i.impact_class == "confirmed"}
    assert confirmed == {"Торцевое уплотнение"}
    seal = next(i for i in rep.items if i.name == "Торцевое уплотнение")
    assert "90" in seal.check.detail and seal.evidence


def test_torque_rule(dev_kb, dev_graph):
    pc = parse_change("Номинальная мощность электродвигателя увеличивается с 55 кВт до 75 кВт.", dev_kb, dev_graph)
    rep = ImpactAnalyzer(dev_kb, dev_graph).analyze(pc.requirement.id, new_value=pc.new_value)
    coupling = next(i for i in rep.items if i.name == "Муфта соединительная")
    assert coupling.impact_class == "confirmed" and "243" in coupling.check.detail


def test_physics_ablation_increases_reach(dev_kb, dev_graph):
    pc = parse_change("Допустимая виброскорость агрегата ужесточается с 4,5 мм/с до 2,8 мм/с.", dev_kb, dev_graph)
    a = ImpactAnalyzer(dev_kb, dev_graph).analyze(pc.requirement.id, new_value=pc.new_value)
    b = ImpactAnalyzer(dev_kb, dev_graph, ImpactSettings(use_physics=False)).analyze(pc.requirement.id, new_value=pc.new_value)
    assert len(b.items) > len(a.items)


def test_reproducible(dev_kb, dev_graph):
    pc = parse_change("Рабочее давление увеличивается с 1,6 МПа до 2,5 МПа.", dev_kb, dev_graph)
    r1 = ImpactAnalyzer(dev_kb, dev_graph).analyze(pc.requirement.id, new_value=pc.new_value)
    r2 = ImpactAnalyzer(dev_kb, dev_graph).analyze(pc.requirement.id, new_value=pc.new_value)
    assert [i.entity_id for i in r1.items] == [i.entity_id for i in r2.items]
