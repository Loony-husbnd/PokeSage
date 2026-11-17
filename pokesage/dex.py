"""포챔스 데이터(pokesage/data/*.json) 로더와 이름 검색.

데이터는 tools/build_data.py가 Showdown 포챔스 모드와 PokeAPI 한국어 이름으로 만든다.
 SPECIES[id]   = {name, ko, num, types, bs[6], abilities[], weight, base?, mega?, item?, megas?}
 MOVES[id]     = {name, ko, type, cat(P/S/Z), bp, acc(0=필중), pri, target, flags?, secondaries?, ...}
 ITEMS[id]     = {name, ko, megaStone?}
 ABILITIES[id] = {name, ko}
 LEARNSETS[id] = [기술 id, ...]
"""
from __future__ import annotations

import difflib
import json
import pathlib
import re

_DIR = pathlib.Path(__file__).parent / "data"


def _load(name: str) -> dict:
    return json.loads((_DIR / f"{name}.json").read_text(encoding="utf-8"))


SPECIES: dict = _load("species")
MOVES: dict = _load("moves")
ITEMS: dict = _load("items")
ABILITIES: dict = _load("abilities")
LEARNSETS: dict = _load("learnsets")

# 대전에 데리고 갈 수 있는 포켓몬(메가진화·전투 중 폼 제외)
PLAYABLE = sorted((k for k, v in SPECIES.items() if not v.get("mega") and not v.get("battleOnly")),
                  key=lambda k: (SPECIES[k]["num"], k))


def toid(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def ko(kind: str, i: str) -> str:
    if kind == "item" and i in ("", "other"):
        return "기타 도구" if i == "other" else "없음"
    table = {"species": SPECIES, "move": MOVES, "item": ITEMS, "ability": ABILITIES}[kind]
    return table[i]["ko"] if i in table else i


def josa(word: str, pair: str = "이가") -> str:
    """받침에 따라 조사를 붙인다. pair: "이가", "은는", "을를", "과와"."""
    if not word:
        return word
    c = ord(word[-1]) - 0xAC00
    has = 0 <= c < 11172 and c % 28 != 0
    if not (0 <= c < 11172):
        has = word[-1] in "LMNRlmnr136780"
    return word + (pair[0] if has else pair[1])


# ---------- 이름 검색 ----------

_CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"


def _norm(s: str) -> str:
    return re.sub(r"[\s\-_.,·:'’()\[\]]", "", s.lower())


def _chosung(s: str) -> str:
    out = []
    for ch in s:
        c = ord(ch) - 0xAC00
        out.append(_CHO[c // 588] if 0 <= c < 11172 else ch)
    return "".join(out)


class Index:
    """한국어·영어 이름과 id로 찾는 검색 색인."""

    def __init__(self, table: dict, ids=None):
        self.table = table
        self.ids = list(ids if ids is not None else table)
        self.keys: dict[str, str] = {}
        for i in self.ids:
            e = table[i]
            for name in (e["ko"], e["name"], i):
                self.keys.setdefault(_norm(name), i)

    def exact(self, text: str) -> str | None:
        return self.keys.get(_norm(text))

    def search(self, text: str, limit: int = 8) -> list[str]:
        q = _norm(text)
        if not q:
            return []
        if q in self.keys:
            return [self.keys[q]]
        scored: dict[str, float] = {}
        cho_q = all(c in _CHO for c in q)
        for i in self.ids:
            e = self.table[i]
            names = [_norm(e["ko"]), _norm(e["name"])]
            best = 0.0
            for n in names:
                if n.startswith(q):
                    best = max(best, 3 + len(q) / len(n))
                elif q in n:
                    best = max(best, 2 + len(q) / len(n))
                else:
                    best = max(best, difflib.SequenceMatcher(None, q, n).ratio())
            if cho_q:
                c = _chosung(e["ko"]).replace(" ", "")
                if c.startswith(q):
                    best = max(best, 3 + len(q) / len(c))
                elif q in c:
                    best = max(best, 2 + len(q) / len(c))
            if best >= 0.5:
                scored[i] = best
        return sorted(scored, key=lambda i: -scored[i])[:limit]


SPECIES_INDEX = Index(SPECIES, PLAYABLE)
for _k, _v in SPECIES.items():  # "메가한카리아스"로 입력해도 원래 포켓몬으로 찾는다
    if _v.get("mega") and _v.get("base") in SPECIES:
        for _n in (_v["ko"], _v["name"], _k):
            SPECIES_INDEX.keys.setdefault(_norm(_n), _v["base"])
ALL_SPECIES_INDEX = Index(SPECIES)
MOVE_INDEX = Index(MOVES)
ITEM_INDEX = Index(ITEMS)
ABILITY_INDEX = Index(ABILITIES)


# ---------- 종 정보 ----------

def base_of(sid: str) -> str:
    """메가진화·전투 중 폼이라면 원래 형태의 id."""
    e = SPECIES[sid]
    return e["base"] if (e.get("mega") or e.get("battleOnly")) and e.get("base") in SPECIES else sid


def learnset(sid: str) -> list[str]:
    return LEARNSETS.get(base_of(sid), [])


def mega_of(sid: str, item: str) -> str | None:
    """sid가 item을 지닐 때 메가진화하는 형태의 id."""
    for m in SPECIES[sid].get("megas", []):
        if SPECIES[m].get("item") == item:
            return m
    return None


def mega_stones(sid: str) -> list[str]:
    return [SPECIES[m]["item"] for m in SPECIES[sid].get("megas", []) if SPECIES[m].get("item") in ITEMS]
