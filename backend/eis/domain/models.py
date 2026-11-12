"""Доменные модели EIS. Не зависят от БД, API и конкретных библиотек.

Ключевой принцип: любая сущность и любая связь несёт список Evidence — ссылок на
первоисточник (документ, страница/лист/абзац, смещения, цитата) или на правило вывода.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, Field


def now() -> datetime:
    return datetime.now(timezone.utc)


def stable_id(*parts: object) -> str:
    """Детерминированный идентификатор — для воспроизводимости экспериментов."""
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:12]


class EntityType(StrEnum):
    PRODUCT = "Product"
    ASSEMBLY = "Assembly"
    COMPONENT = "Component"
    MATERIAL = "Material"
    REQUIREMENT = "TechnicalRequirement"
    DOCUMENT = "EngineeringDocument"
    TEST = "Test"
    STANDARD = "Standard"
    CHANGE = "ChangeRequest"
    CONSTRAINT = "Constraint"        # характеристика субъекта (субъект, параметр), на которую ссылаются требования


class RelationType(StrEnum):
    CONTAINS = "CONTAINS"
    DEPENDS_ON = "DEPENDS_ON"
    SATISFIES = "SATISFIES"
    CONTRADICTS = "CONTRADICTS"
    DOCUMENTED_IN = "DOCUMENTED_IN"
    VERIFIED_BY = "VERIFIED_BY"
    USES_MATERIAL = "USES_MATERIAL"
    AFFECTS = "AFFECTS"
    SUPERSEDES = "SUPERSEDES"
    DERIVED_FROM = "DERIVED_FROM"
    CONSTRAINS = "CONSTRAINS"        # требование → Constraint (субъект, параметр)
    CHARACTERIZES = "CHARACTERIZES"  # Constraint → субъект (компонент/материал/изделие)


class EvidenceMethod(StrEnum):
    RULE = "rule"            # правило извлечения по тексту
    TABLE = "table"          # строка таблицы
    LLM = "llm"              # извлечено/выведено языковой моделью
    GRAPH_RULE = "graph_rule"  # выведено правилом на графе
    MANUAL = "manual"


class Evidence(BaseModel):
    document_id: str | None = None
    fragment_id: str | None = None
    page: int | None = None              # страница PDF / номер листа XLSX / None
    locator: str | None = None           # «абзац 12», «таблица 1, строка 5», «строка 7»
    bbox: tuple[float, float, float, float] | None = None
    char_start: int | None = None        # смещения цитаты внутри текста фрагмента
    char_end: int | None = None
    quote: str = ""
    method: EvidenceMethod = EvidenceMethod.RULE
    rule: str | None = None              # имя правила
    confidence: float = 1.0
    created_at: datetime = Field(default_factory=now)


class Fragment(BaseModel):
    """Логический фрагмент документа: абзац, заголовок, строка таблицы, строка текста."""
    id: str
    document_id: str
    kind: str                            # heading | paragraph | table_row | line
    text: str
    page: int | None = None
    locator: str | None = None
    bbox: tuple[float, float, float, float] | None = None
    section: str | None = None           # номер пункта, если распознан («3.2.1»)
    heading_path: list[str] = Field(default_factory=list)
    cells: list[str] | None = None       # для строк таблиц
    header: list[str] | None = None      # заголовок таблицы
    ocr: bool = False
    ocr_confidence: float | None = None
    flags: list[str] = Field(default_factory=list)   # например, "suspected_injection"


class Document(BaseModel):
    id: str
    project_id: str = "default"
    filename: str
    fmt: str
    sha256: str
    title: str | None = None
    code: str | None = None              # обозначение документа («НА-200.00.000 ТЗ»)
    doc_type: str | None = None
    doc_type_confidence: float = 0.0
    subject_id: str | None = None        # субъект по умолчанию (изделие/компонент)
    is_synthetic: bool = False
    status: str = "uploaded"             # uploaded | parsed | extracted | failed
    error: str | None = None
    pages: int | None = None
    processed_at: datetime | None = None
    metadata: dict = Field(default_factory=dict)


class Entity(BaseModel):
    id: str
    type: EntityType
    name: str
    designation: str | None = None
    aliases: list[str] = Field(default_factory=list)
    attrs: dict = Field(default_factory=dict)
    evidence: list[Evidence] = Field(default_factory=list)
    confidence: float = 1.0


class Requirement(BaseModel):
    """Типизированное техническое требование / ограничение."""
    id: str
    subject_id: str | None              # к какому компоненту/материалу/изделию относится
    parameter: str                       # нормализованный ключ параметра
    dimension: str
    kind: str                            # demand | capability | setpoint | nominal
    operator: str                        # <= | >= | = | range
    value: float | str | None = None     # в канонических единицах
    low: float | None = None
    high: float | None = None
    unit: str                            # каноническая единица
    unit_original: str = ""
    value_original: str = ""
    section: str | None = None
    text: str = ""
    document_id: str
    evidence: list[Evidence] = Field(default_factory=list)
    confidence: float = 1.0
    status: str = "active"               # active | superseded

    def interval(self) -> tuple[float, float] | None:
        """Допустимый интервал значений параметра (−∞/+∞ для односторонних)."""
        inf = float("inf")
        if isinstance(self.value, str):
            return None
        if self.operator == "<=":
            return (-inf, self.value)
        if self.operator == ">=":
            return (self.value, inf)
        if self.operator == "=":
            return (self.value, self.value)
        if self.operator == "range":
            return (self.low, self.high)
        return None


class Relation(BaseModel):
    id: str
    type: RelationType
    source: str
    target: str
    weight: float = 1.0
    attrs: dict = Field(default_factory=dict)
    evidence: list[Evidence] = Field(min_length=1)   # связь без основания недопустима


class KnowledgeBase(BaseModel):
    """Результат обработки корпуса документов одного проекта."""
    project_id: str = "default"
    documents: dict[str, Document] = Field(default_factory=dict)
    fragments: dict[str, Fragment] = Field(default_factory=dict)
    entities: dict[str, Entity] = Field(default_factory=dict)
    requirements: dict[str, Requirement] = Field(default_factory=dict)
    relations: dict[str, Relation] = Field(default_factory=dict)

    def add_relation(self, rel: Relation) -> Relation:
        """Объединяет evidence при повторном обнаружении той же связи."""
        key = stable_id(rel.type, rel.source, rel.target)
        rel.id = key
        if key in self.relations:
            ex = self.relations[key]
            ex.evidence.extend(rel.evidence)
            ex.attrs.update({k: v for k, v in rel.attrs.items() if k not in ex.attrs})
            return ex
        self.relations[key] = rel
        return rel

    def add_entity(self, ent: Entity) -> Entity:
        if ent.id in self.entities:
            ex = self.entities[ent.id]
            ex.evidence.extend(ent.evidence)
            for a in ent.aliases:
                if a not in ex.aliases:
                    ex.aliases.append(a)
            for k, v in ent.attrs.items():
                ex.attrs.setdefault(k, v)
            return ex
        self.entities[ent.id] = ent
        return ent

    def fragments_of(self, document_id: str) -> list[Fragment]:
        return [f for f in self.fragments.values() if f.document_id == document_id]
