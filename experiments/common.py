"""Общие средства экспериментов: загрузка эталона, сопоставление идентификаторов эталона и системы, метрики.

Сопоставление выполняется по наблюдаемым признакам (обозначение компонента, имя материала,
имя файла), а не по внутренним идентификаторам генератора — система их не знает.
"""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from eis.domain.models import KnowledgeBase  # noqa: E402
from eis.extraction.pipeline import mat_key  # noqa: E402
from eis.services.ingest import ingest_dir  # noqa: E402


def dataset_dir(variant: str) -> Path:
    return ROOT / "dataset" / "out" / variant


def load_gold(variant: str) -> dict:
    g = dataset_dir(variant) / "gold"
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in g.glob("*.json") if p.stem != "rendered_blocks"}


def load_manifest(variant: str) -> dict:
    return json.loads((dataset_dir(variant) / "manifest.json").read_text(encoding="utf-8"))


def build_kb(variant: str) -> KnowledgeBase:
    return ingest_dir(dataset_dir(variant) / "docs")


def git_commit() -> str:
    try:
        return subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:  # noqa: BLE001
        return "uncommitted"


class IdMap:
    """gold id → system id."""

    def __init__(self, gold: dict, kb: KnowledgeBase):
        ents = gold["entities"]
        self.m: dict[str, str] = {}
        for c in ents["components"]:
            self.m[c["id"]] = f"cmp:{c['designation']}"
        for mt in ents["materials"]:
            self.m[mt["id"]] = mat_key(mt["name"])
        by_file = {d.filename: d.id for d in kb.documents.values()}
        for d in ents["documents"]:
            self.m[d["id"]] = by_file.get(d["filename"], f"missing:{d['filename']}")
        for t in ents["tests"]:
            self.m[t["id"]] = f"test:{t['id']}"
        for ch in ents["changes"]:
            self.m[ch["id"]] = f"chg:{ch['id']}"
        self.gold_reqs = {r["id"]: r for r in gold["requirements"]}

    def __call__(self, gid: str) -> str:
        return self.m.get(gid, gid)

    def constraint_of(self, gold_req_id: str) -> str:
        r = self.gold_reqs[gold_req_id]
        return f"con:{self(r['subject'])}:{r['param']}"


@dataclass
class PRF:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def p(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 0.0

    @property
    def r(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 0.0

    @property
    def f1(self) -> float:
        return 2 * self.p * self.r / (self.p + self.r) if self.p + self.r else 0.0

    def add_sets(self, pred: set, gold: set):
        self.tp += len(pred & gold)
        self.fp += len(pred - gold)
        self.fn += len(gold - pred)
        return self

    def row(self) -> dict:
        return {"tp": self.tp, "fp": self.fp, "fn": self.fn, "precision": round(self.p, 4), "recall": round(self.r, 4),
                "f1": round(self.f1, 4)}


def prf(pred: set, gold: set) -> PRF:
    return PRF().add_sets(pred, gold)
