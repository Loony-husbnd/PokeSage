"""배틀 상태 모델. 워커에 보내는 JSON 구조와 같은 모양으로 직렬화한다."""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

from . import data
from .data import STATUSES, toid


@dataclass
class MySet:
    species: str
    ability: str
    item: str
    moves: list[str]
    nature: str = "Hardy"
    evs: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        s = data.species()[toid(self.species)]
        return {"species": s["name"], "ability": self.ability, "item": self.item, "moves": list(self.moves),
                "nature": self.nature, "evs": dict(self.evs)}


@dataclass
class MyMon:
    set: MySet
    hp: int = 100
    status: str = "none"
    boosts: dict = field(default_factory=dict)
    active: bool = False
    megaed: bool = False
    fainted: bool = False
    last_move: str | None = None       # 구애 도구를 들었을 때 마지막에 쓴 기술

    def to_json(self) -> dict:
        st = self.set.to_json()
        if self.megaed:                      # 이미 메가진화했다면 메가 폼과 그 특성으로 보낸다
            mg = next((m for m in data.species()[toid(self.set.species)]["megas"] if m["item"] == self.set.item), None)
            if mg:
                st["species"], st["ability"] = mg["forme"], next(iter(mg["abilities"].values()))
        return {"set": st, "hp": self.hp, "status": self.status, "boosts": dict(self.boosts),
                "active": self.active, "megaed": self.megaed, "fainted": self.fainted or self.hp <= 0, "lastMove": self.last_move}

    @property
    def name(self) -> str:
        return data.ko("species", self.set.species)


@dataclass
class FoeMon:
    species: str
    hp: int = 100
    status: str = "none"
    boosts: dict = field(default_factory=dict)
    active: bool = False
    megaed: bool = False
    mega_form: str | None = None
    moves: list[str] = field(default_factory=list)     # 사용해서 드러난 기술
    ability: str | None = None
    item: str | None = None
    item_gone: bool = False

    def to_json(self) -> dict:
        rev = {"moves": list(self.moves), "itemGone": self.item_gone}
        if self.ability: rev["ability"] = self.ability
        if self.item is not None: rev["item"] = self.item
        return {"species": data.species()[toid(self.species)]["name"], "hp": self.hp, "status": self.status, "boosts": dict(self.boosts),
                "active": self.active, "megaed": self.megaed, "megaForm": self.mega_form, "revealed": rev,
                "fainted": self.hp <= 0}

    @property
    def name(self) -> str:
        return data.ko("species", self.species)


@dataclass
class BattleState:
    me: list[MyMon]                       # 이번 배틀에 선출한 3마리
    foe: list[FoeMon] = field(default_factory=list)       # 지금까지 나온 상대 포켓몬
    foe_preview: list[str] = field(default_factory=list)  # 팀 프리뷰로 본 상대 6마리
    field: dict = field(default_factory=dict)             # {weather, terrain, pseudo, me, foe}
    turn: int = 1

    def my_active(self) -> MyMon: return next(m for m in self.me if m.active and m.hp > 0)
    def foe_active(self) -> FoeMon: return next(m for m in self.foe if m.active and m.hp > 0)

    def ordered_me(self) -> list[MyMon]:
        """워커의 normalizeMons 와 같은 순서: 살아 있는 포켓몬, 선두가 맨 앞."""
        alive = [m for m in self.me if m.hp > 0 and not m.fainted]
        lead = next((i for i, m in enumerate(alive) if m.active), 0)
        if lead:
            alive.insert(0, alive.pop(lead))
        return alive

    def to_json(self) -> dict:
        foe_alive = [m for m in self.foe]
        return {"me": {"mons": [m.to_json() for m in self.me]},
                "foe": {"mons": [m.to_json() for m in foe_alive if m.hp > 0], "preview": list(self.foe_preview), "pick": 3},
                "field": self.field, "turn": self.turn}

    def snapshot(self) -> dict:
        return copy.deepcopy(self.to_json())

    def label(self, choice: str) -> str:
        """워커의 선택 문자열('move 2 mega', 'switch 3')을 한글로."""
        order = self.ordered_me()
        parts = choice.split()
        if parts[0] == "move":
            mv = order[0].set.moves[int(parts[1]) - 1]
            return ("메가진화 + " if len(parts) > 2 else "") + data.ko("moves", mv)
        if parts[0] == "switch":
            return f"{order[int(parts[1]) - 1].name}(으)로 교체"
        return choice


def validate_status(s: str) -> str:
    if s not in STATUSES:
        raise ValueError(s)
    return s
