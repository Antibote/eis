"""Результаты анализа: противоречия и отчёт о последствиях изменения."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from eis.domain.models import Evidence, now


class Contradiction(BaseModel):
    id: str
    type: str            # value_mismatch | unit_hidden_mismatch | demand_exceeds_capability | material_limit |
                         # setpoint_exceeds_limit | material_mismatch | semantic
    status: str          # confirmed | potential | insufficient_data
    severity: str        # critical | high | medium | low
    title: str
    description: str
    explanation: str
    recommendation: str
    entities: list[str] = Field(default_factory=list)      # затронутые компоненты/материалы
    items: list[str] = Field(default_factory=list)         # id требований / связей, образующих противоречие
    evidence: list[Evidence] = Field(default_factory=list)
    confidence: float = 0.0
    detected_by: str = "formal"   # formal | graph | llm
    review_status: str = "new"    # new | confirmed_by_engineer | rejected
    created_at: datetime = Field(default_factory=now)


class PathStep(BaseModel):
    node: str
    via: str | None = None        # тип ребра, по которому пришли в узел
    reverse: bool = False


class CheckResult(BaseModel):
    verdict: str                  # violation | at_limit | ok | no_data
    detail: str
    against: list[str] = Field(default_factory=list)   # id требований-ограничений
    margin: float | None = None


class ImpactItem(BaseModel):
    entity_id: str
    name: str
    entity_type: str
    impact_class: str             # confirmed | potential | direct | documentary
    relation: str                 # subject | dependent | contained | material | derived | load_path
    confidence: float
    path: list[PathStep]
    check: CheckResult | None = None
    evidence: list[Evidence] = Field(default_factory=list)


class DocumentImpact(BaseModel):
    document_id: str
    filename: str
    code: str | None
    reasons: list[str]
    items: list[str]              # id требований/связей, из-за которых документ попал в список
    evidence: list[Evidence] = Field(default_factory=list)


class TestImpact(BaseModel):
    test_id: str
    name: str
    reason: str
    result: str | None = None
    result_still_valid: bool | None = None
    evidence: list[Evidence] = Field(default_factory=list)


class DerivedImpact(BaseModel):
    constraint_id: str
    description: str
    factor: float | None
    new_expected: float | None
    stated: list[str]
    evidence: list[Evidence] = Field(default_factory=list)


class ImpactReport(BaseModel):
    requirement_id: str
    requirement_text: str
    parameter: str
    subject_id: str
    old: str
    new: str
    items: list[ImpactItem]
    documents: list[DocumentImpact]
    tests: list[TestImpact]
    derived: list[DerivedImpact]
    conflicts_after_change: list[Contradiction]
    recommendations: list[str]
    settings: dict
    elapsed_ms: float
    created_at: datetime = Field(default_factory=now)
