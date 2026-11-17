"""Showdown 포챔스 모드에서 내보낸 데이터(data/champions/*.json)와 한글 이름표."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "champions"

STATS = ("hp", "atk", "def", "spa", "spd", "spe")
STAT_KO = {"hp": "HP", "atk": "공격", "def": "방어", "spa": "특공", "spd": "특방", "spe": "스피드"}
NATURES = {  # 이름: (올리는 스탯, 내리는 스탯)
    "Hardy": (None, None), "Docile": (None, None), "Serious": (None, None), "Bashful": (None, None), "Quirky": (None, None),
    "Lonely": ("atk", "def"), "Brave": ("atk", "spe"), "Adamant": ("atk", "spa"), "Naughty": ("atk", "spd"),
    "Bold": ("def", "atk"), "Relaxed": ("def", "spe"), "Impish": ("def", "spa"), "Lax": ("def", "spd"),
    "Timid": ("spe", "atk"), "Hasty": ("spe", "def"), "Jolly": ("spe", "spa"), "Naive": ("spe", "spd"),
    "Modest": ("spa", "atk"), "Mild": ("spa", "def"), "Quiet": ("spa", "spe"), "Rash": ("spa", "spd"),
    "Calm": ("spd", "atk"), "Gentle": ("spd", "def"), "Sassy": ("spd", "spe"), "Careful": ("spd", "spa"),
}
SP_PER_STAT, SP_TOTAL = 32, 66
STATUSES = ("none", "brn", "par", "psn", "tox", "slp", "frz")
STATUS_KO = {"none": "없음", "brn": "화상", "par": "마비", "psn": "독", "tox": "맹독", "slp": "잠듦", "frz": "얼음"}


def toid(s: str) -> str:
    return "".join(c for c in str(s).lower() if c.isalnum())


@lru_cache(maxsize=1)
def _load():
    d = {n: json.loads((DATA / f"{n}.json").read_text(encoding="utf-8")) for n in ("species", "moves", "items", "abilities", "meta")}
    ko = json.loads((ROOT / "data" / "ko_names.json").read_text(encoding="utf-8"))
    return d, ko


def species() -> dict: return _load()[0]["species"]
def moves() -> dict: return _load()[0]["moves"]
def items() -> dict: return _load()[0]["items"]
def abilities() -> dict: return _load()[0]["abilities"]
def meta() -> dict: return _load()[0]["meta"]


def ko(kind: str, key: str) -> str:
    """한글 이름 (없으면 영문 이름). kind: species|moves|abilities|items|types|natures"""
    table = _load()[1].get(kind, {})
    k = toid(key)
    if k in table:
        return table[k]
    src = {"species": species(), "moves": moves(), "items": items(), "abilities": abilities()}.get(kind, {})
    return src.get(k, {}).get("name", key)


def legal_items(mega_of: str | None = None) -> list[str]:
    """도구 id 목록. 메가스톤은 해당 종(mega_of)의 것만 포함한다."""
    sp = species().get(toid(mega_of)) if mega_of else None
    own = {m["item"] for m in sp["megas"]} if sp else set()
    return sorted(i for i, v in items().items() if not v.get("mega") or i in own)


def calc_stat(species_id: str, stat: str, sp_points: int, nature: str) -> int:
    """포챔스 능력치: Lv.50 기준 종족값 + SP + 20 (HP는 + 75), 성격 보정 ±10%."""
    base = species()[toid(species_id)]["baseStats"][stat]
    if stat == "hp":
        return base + sp_points + 75
    v = base + sp_points + 20
    plus, minus = NATURES[nature]
    if stat == plus:
        v = v * 110 // 100
    elif stat == minus:
        v = v * 90 // 100
    return v


def check_sp(evs: dict[str, int]) -> list[str]:
    problems = []
    for k, v in evs.items():
        if v < 0 or v > SP_PER_STAT:
            problems.append(f"{STAT_KO[k]} 스탯 포인트는 0~{SP_PER_STAT}이어야 합니다 ({v}).")
    if sum(evs.values()) > SP_TOTAL:
        problems.append(f"스탯 포인트 합계는 {SP_TOTAL} 이하여야 합니다 ({sum(evs.values())}).")
    return problems
