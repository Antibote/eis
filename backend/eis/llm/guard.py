"""Проверка ответа LLM на опору на источники (citation guard).

Ответ делится на предложения. Предложение принимается, если:
  • содержит ссылку [n] на существующий фрагмент контекста;
  • все числа в предложении (кроме номеров ссылок и пунктов) встречаются в процитированных фрагментах.
Иначе предложение помечается как неподтверждённое и удаляется из итогового ответа.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

CITE_RE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
NUM_RE = re.compile(r"(?<![\w.])[−-]?\d+(?:[.,]\d+)?")
SENT_RE = re.compile(r"(?<=[.!?])\s+")


@dataclass
class GuardResult:
    text: str
    accepted: list[str] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)   # (предложение, причина)
    cited: set[int] = field(default_factory=set)

    @property
    def unsupported_share(self) -> float:
        n = len(self.accepted) + len(self.rejected)
        return len(self.rejected) / n if n else 0.0


def _nums(s: str) -> set[str]:
    return {x.replace(",", ".").replace("−", "-").lstrip("+") for x in NUM_RE.findall(s)}


def guard(answer: str, context: dict[int, str]) -> GuardResult:
    res = GuardResult(text="")
    for sent in (s.strip() for s in SENT_RE.split(answer.strip())):
        if not sent:
            continue
        refs = {int(x) for m in CITE_RE.finditer(sent) for x in m.group(1).split(",")}
        if not refs:
            if len(sent) < 60 and not NUM_RE.search(sent):     # служебные фразы («Ниже перечислены…»)
                res.accepted.append(sent)
            else:
                res.rejected.append((sent, "нет ссылки на источник"))
            continue
        bad = refs - set(context)
        if bad:
            res.rejected.append((sent, f"ссылка на несуществующий фрагмент {sorted(bad)}"))
            continue
        body = CITE_RE.sub("", sent)
        src = " ".join(context[r] for r in refs)
        missing = _nums(body) - _nums(src)
        if missing:
            res.rejected.append((sent, f"числа {sorted(missing)} отсутствуют в цитируемых фрагментах"))
            continue
        res.accepted.append(sent)
        res.cited |= refs
    res.text = " ".join(res.accepted)
    return res
