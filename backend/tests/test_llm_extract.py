"""Детерминированная проверка ответа LLM при извлечении требований (без запуска модели)."""
import json

from eis.extraction.llm_extract import parse_answer


class NoMentions:
    def find(self, text):
        return []


def run(items, text="Рабочее давление не более 1,6 МПа."):
    return parse_answer(json.dumps({"requirements": items}, ensure_ascii=False), text, "doc:1", "frag:1", NoMentions(), "cmp:P")


def test_accepts_value_present_in_fragment_and_ignores_extra_bounds():
    got, rej = run([{"subject": "", "parameter": "working_pressure", "kind": "demand", "operator": "<=", "value": 1.6,
                     "low": 0, "high": None, "unit": "МПа"}])
    assert not rej and len(got) == 1 and got[0].value == 1.6 and got[0].subject_id == "cmp:P"


def test_rejects_invented_number_and_unknown_parameter_and_wrong_unit():
    got, rej = run([{"parameter": "working_pressure", "kind": "demand", "operator": "<=", "value": 2.5, "unit": "МПа"},
                    {"parameter": "colour", "kind": "demand", "operator": "=", "value": 1.6, "unit": "МПа"},
                    {"parameter": "power", "kind": "nominal", "operator": "=", "value": 1.6, "unit": "Ватт"}])
    assert got == [] and len(rej) == 3
