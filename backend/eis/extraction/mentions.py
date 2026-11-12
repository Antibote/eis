"""Поиск упоминаний сущностей в русском тексте с учётом словоизменения.

Имя сущности и текст приводятся к леммам (pymorphy3); совпадение — непрерывная
последовательность токенов, мультимножество лемм которой равно лемме имени
(порядок слов не важен: «фланец напорный» = «напорного фланца»).
Берутся самые длинные непересекающиеся совпадения.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache

import pymorphy3

TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9][A-Za-zА-Яа-яЁё0-9\-]*")
_morph = pymorphy3.MorphAnalyzer()


@lru_cache(maxsize=100_000)
def lemma(word: str) -> str:
    w = word.lower().replace("ё", "е")
    if any(ch.isdigit() for ch in w) or re.fullmatch(r"[a-z\-]+", w):
        return w
    return _morph.parse(w)[0].normal_form.replace("ё", "е")


@lru_cache(maxsize=10_000)
def pos(word: str) -> str | None:
    return _morph.parse(word.lower())[0].tag.POS


def tokens(text: str) -> list[tuple[str, int, int]]:
    return [(m.group(0), m.start(), m.end()) for m in TOKEN_RE.finditer(text)]


def lemmas_of(name: str) -> tuple[str, ...]:
    return tuple(lemma(t) for t, _, _ in tokens(name))


@dataclass
class Mention:
    entity_id: str
    start: int
    end: int
    text: str
    alias: bool


class MentionIndex:
    def __init__(self):
        self._names: dict[int, list[tuple[Counter, str, bool]]] = {}

    def add(self, entity_id: str, name: str, alias: bool = False):
        lm = lemmas_of(name)
        if lm:
            self._names.setdefault(len(lm), []).append((Counter(lm), entity_id, alias))

    def add_with_head_alias(self, entity_id: str, name: str):
        """Имя + синоним «главное существительное», если имя = 1 существительное + прилагательные."""
        self.add(entity_id, name)
        toks = [t for t, _, _ in tokens(name)]
        if len(toks) >= 2:
            p = [pos(t) for t in toks]
            nouns = [t for t, x in zip(toks, p) if x == "NOUN"]
            if len(nouns) == 1 and all(x in ("NOUN", "ADJF", "PRTF") for x in p):
                self.add(entity_id, nouns[0], alias=True)

    def find(self, text: str) -> list[Mention]:
        toks = tokens(text)
        lms = [lemma(t) for t, _, _ in toks]
        found: list[Mention] = []
        used = [False] * len(toks)
        for n in sorted(self._names, reverse=True):
            for i in range(len(toks) - n + 1):
                if any(used[i:i + n]):
                    continue
                c = Counter(lms[i:i + n])
                for names_c, eid, alias in self._names[n]:
                    if c == names_c:
                        s, e = toks[i][1], toks[i + n - 1][2]
                        found.append(Mention(eid, s, e, text[s:e], alias))
                        for k in range(i, i + n):
                            used[k] = True
                        break
        return sorted(found, key=lambda m: m.start)
