"""전투 시뮬레이터: (상태, 양쪽 행동) -> 다음 상태.

싱글 배틀, 레벨 50. 반영: 우선도·스피드 순서, 명중, 급소, 난수, 상태이상, 랭크 변화,
변화기, 반동, 부가 효과, 풀죽음, 교체, 일부 도구(구애 3종·생명의구슬·기합의띠·먹다남은음식)와
특성(위협·멀티스케일). 미반영: 날씨/필드, 구애 도구의 기술 고정, 메가진화 등.

행동은 ("move", 기술 인덱스) 또는 ("switch", 팀 인덱스) 튜플이다.
"""
from __future__ import annotations

import random
from functools import lru_cache

from .dex import ABILITIES, MOVE_FX, MOVES, POKEMON
from .model import DEFAULT_SPREAD, LEVEL, SPREADS, STATS, calc_stat, stage_mult
from .typechart import effectiveness

SK = ("atk", "def", "spa", "spd", "spe")  # 랭크 배열 순서
CRIT_RATE = 1 / 24


def _hit(rng, side: int, acc: int) -> bool:
    """명중 판정. 탐색은 rng.hits[side]로 결과를 지정해 확률을 정확히 가중한다."""
    forced = getattr(rng, "hits", None)
    if forced and side in forced:
        return forced[side]
    return acc >= 100 or rng.random() * 100 < acc


def _proc(rng, side: int, chance: float) -> bool:
    """부가 효과 발동 판정. rng.procs[side]로 지정하거나, rng.quiet이면 확정 효과만 발동한다."""
    forced = getattr(rng, "procs", None)
    if forced and side in forced:
        return forced[side]
    if chance >= 100:
        return True
    return not getattr(rng, "quiet", False) and rng.random() * 100 < chance


@lru_cache(maxsize=None)
def _stats(species: str, spread_name: str) -> tuple[int, ...]:
    return tuple(calc_stat(species, s, SPREADS[spread_name]) for s in STATS)


class BMon:
    """전투 중인 포켓몬 한 마리(HP는 실수치)."""

    __slots__ = ("species", "types", "stats", "max_hp", "hp", "status", "stages", "moves",
                 "item", "ability", "tox", "slp", "spread_name")

    def __init__(self, species, spread_name=DEFAULT_SPREAD, moves=None, item="없음",
                 hp_frac=1.0, status="없음", stages=None):
        self.species = species
        self.types = POKEMON[species][0]
        self.spread_name = spread_name
        self.stats = _stats(species, spread_name)
        self.max_hp = self.stats[0]
        self.hp = 0 if hp_frac <= 0 else min(self.max_hp, max(1, round(self.max_hp * hp_frac)))
        self.status = status
        self.stages = list(stages) if stages else [0, 0, 0, 0, 0]
        self.moves = tuple(moves or POKEMON[species][2])
        self.item = item
        self.ability = ABILITIES.get(species, "")
        self.tox = 0
        self.slp = 2 if status == "잠듦" else 0

    def copy(self) -> "BMon":
        m = BMon.__new__(BMon)
        m.species, m.types, m.stats, m.max_hp = self.species, self.types, self.stats, self.max_hp
        m.hp, m.status, m.stages, m.moves = self.hp, self.status, self.stages[:], self.moves
        m.item, m.ability, m.tox, m.slp = self.item, self.ability, self.tox, self.slp
        m.spread_name = self.spread_name
        return m

    @property
    def frac(self) -> float:
        return self.hp / self.max_hp


class State:
    __slots__ = ("teams", "active", "unrevealed", "turn")

    def __init__(self, team0, team1, active=(0, 0), unrevealed=(0, 0), turn=1):
        self.teams = [list(team0), list(team1)]
        self.active = list(active)
        self.unrevealed = list(unrevealed)  # 아직 공개되지 않은 포켓몬 수
        self.turn = turn

    def copy(self) -> "State":
        s = State.__new__(State)
        s.teams = [[m.copy() for m in self.teams[0]], [m.copy() for m in self.teams[1]]]
        s.active, s.unrevealed, s.turn = self.active[:], self.unrevealed[:], self.turn
        return s

    def mon(self, side: int) -> BMon:
        return self.teams[side][self.active[side]]


# ---------- 계산 ----------

def speed(m: BMon) -> int:
    v = int(m.stats[5] * stage_mult(m.stages[4]))
    if m.item == "구애스카프":
        v = v * 3 // 2
    return v // 2 if m.status == "마비" else v


def damage(att: BMon, dfn: BMon, name: str, roll: int = 100, crit: bool = False) -> int:
    """기술 1회의 대미지(HP 실수치). roll은 85~100."""
    mtype, cat, power, _acc, _prio = MOVES[name]
    if cat == "Z" or power == 0:
        return 0
    eff = effectiveness(mtype, dfn.types)
    if eff == 0:
        return 0
    ai, di = (1, 2) if cat == "P" else (3, 4)
    ast, dst = att.stages[ai - 1], dfn.stages[di - 1]
    if crit:
        ast, dst = max(ast, 0), min(dst, 0)
    a = int(att.stats[ai] * stage_mult(ast))
    d = int(dfn.stats[di] * stage_mult(dst))
    if (cat == "P" and att.item == "구애머리띠") or (cat == "S" and att.item == "구애안경"):
        a = a * 3 // 2
    if cat == "P" and att.status == "화상":
        a //= 2
    if dfn.item != "없음" and MOVE_FX.get(name, {}).get("knock"):
        power = power * 3 // 2
    base = ((2 * LEVEL // 5 + 2) * power * a // max(d, 1)) // 50 + 2
    if crit:
        base = base * 3 // 2
    dmg = base * roll // 100
    if mtype in att.types:
        dmg = dmg * 3 // 2
    dmg = int(dmg * eff)
    if att.item == "생명의구슬":
        dmg = dmg * 13 // 10
    if dfn.ability == "멀티스케일" and dfn.hp == dfn.max_hp:
        dmg //= 2
    return max(dmg, 1)


def damage_rolls(att: BMon, dfn: BMon, name: str, crit: bool = False) -> list[int]:
    return [damage(att, dfn, name, r, crit) for r in range(85, 101)]


# ---------- 상태 질의 ----------

def legal(s: State, side: int) -> list[tuple]:
    team, a = s.teams[side], s.active[side]
    sw = [("switch", j) for j, m in enumerate(team) if j != a and m.hp > 0]
    if team[a].hp <= 0:
        return sw
    return [("move", i) for i in range(len(team[a].moves))] + sw


def _alive(s: State, side: int) -> bool:
    return any(m.hp > 0 for m in s.teams[side])


def winner(s: State) -> int | None:
    """승자 side. 미정이면 None. (동시 전멸은 side 1 승으로 처리)"""
    for side in (0, 1):
        if not _alive(s, side) and s.unrevealed[side] == 0:
            return 1 - side
    return None


def pending(s: State, side: int) -> bool:
    """기절로 인한 교체 선택이 필요한가."""
    return s.mon(side).hp <= 0 and _alive(s, side)


def stalled(s: State) -> bool:
    """공개된 포켓몬이 전멸했지만 미공개 포켓몬이 남아 더 진행할 수 없는 상태."""
    return any(not _alive(s, side) and s.unrevealed[side] > 0 for side in (0, 1))


# ---------- 상태 변경 ----------

def _boost(m: BMon, delta: dict) -> None:
    for k, v in delta.items():
        i = SK.index(k)
        m.stages[i] = max(-6, min(6, m.stages[i] + v))


def _inflict(m: BMon, st: str, rng) -> None:
    if m.status != "없음" or m.hp <= 0:
        return
    t = m.types
    if (st == "화상" and "fire" in t) or (st == "마비" and "electric" in t) or (st == "얼음" and "ice" in t):
        return
    if st in ("독", "맹독") and ("poison" in t or "steel" in t):
        return
    m.status, m.tox = st, 0
    if st == "잠듦":
        m.slp = rng.randint(1, 3)


def switch_in(s: State, side: int, j: int) -> None:
    """side의 선두를 j번으로 바꾼다(s를 직접 수정)."""
    out = s.mon(side)
    out.stages = [0, 0, 0, 0, 0]
    out.tox = 0
    s.active[side] = j
    foe = s.mon(1 - side)
    if s.teams[side][j].ability == "위협" and foe.hp > 0:
        _boost(foe, {"atk": -1})


def _use_move(s, side, name, rng, ev, foe_moved, foe_act, flinched) -> None:
    me, foe = s.mon(side), s.mon(1 - side)
    if me.hp <= 0 or flinched[side]:
        return
    if me.status == "잠듦":
        if me.slp <= 0:
            me.status = "없음"
        else:
            me.slp -= 1
            return
    if me.status == "얼음":
        if rng.random() < 0.2:
            me.status = "없음"
        else:
            return
    if me.status == "마비" and rng.random() < 0.25:
        return
    if ev is not None:
        ev.append(("used", side, me.species, name))
    mtype, cat, _power, acc, _prio = MOVES[name]
    fx = MOVE_FX.get(name, {})

    if cat == "Z":
        if "self" in fx:
            _boost(me, fx["self"])
        if "heal" in fx:
            me.hp = min(me.max_hp, me.hp + int(me.max_hp * fx["heal"]))
        if "status" in fx and foe.hp > 0:
            if fx.get("type_immune") and effectiveness(mtype, foe.types) == 0:
                return
            if _hit(rng, side, acc):
                _inflict(foe, fx["status"], rng)
        return

    if foe.hp <= 0:
        return
    if fx.get("sucker"):
        foe_attacking = foe_act[0] == "move" and MOVES[foe.moves[foe_act[1]]][1] != "Z"
        if foe_moved or not foe_attacking:
            return
    if not _hit(rng, side, acc):
        return
    if getattr(rng, "mean", False):  # 탐색용: 난수·급소를 평균값으로 고정해 잡음을 줄인다
        crit, roll = False, 92
    else:
        crit, roll = rng.random() < CRIT_RATE, rng.randint(85, 100)
    dmg = damage(me, foe, name, roll, crit)
    if dmg == 0:
        return
    snap = (me.copy(), foe.copy()) if ev is not None else None
    sash = False
    if dmg >= foe.hp and foe.hp == foe.max_hp and foe.item == "기합의띠":
        dmg, sash, foe.item = foe.hp - 1, True, "없음"
    dmg = min(dmg, foe.hp)
    foe.hp -= dmg
    if ev is not None:
        ev.append(("hit", side, name, snap[0], snap[1], dmg, crit or sash))
        if sash:
            ev.append(("item", 1 - side, foe.species, "기합의띠"))
            ev.append(("itemlost", 1 - side, foe.species))
    if fx.get("knock") and foe.item != "없음":
        foe.item = "없음"
        if ev is not None:
            ev.append(("itemlost", 1 - side, foe.species))
    if "recoil" in fx:
        me.hp = max(0, me.hp - max(1, round(dmg * fx["recoil"])))
    if me.item == "생명의구슬":
        me.hp = max(0, me.hp - max(1, me.max_hp // 10))
        if ev is not None:
            ev.append(("item", side, me.species, "생명의구슬"))
    if "self" in fx:
        _boost(me, fx["self"])
    if foe.hp > 0:
        if "flinch" in fx:
            if _proc(rng, side, fx["flinch"]) and not foe_moved:
                flinched[1 - side] = True
        elif ("status" in fx or "foe" in fx) and _proc(rng, side, fx.get("chance", 100)):
            if "status" in fx:
                _inflict(foe, fx["status"], rng)
            if "foe" in fx:
                _boost(foe, fx["foe"])


def _end_of_turn(s: State, ev) -> None:
    for side in (0, 1):
        m = s.mon(side)
        if m.hp <= 0:
            continue
        if m.status == "화상":
            m.hp -= max(1, m.max_hp // 16)
        elif m.status == "독":
            m.hp -= max(1, m.max_hp // 8)
        elif m.status == "맹독":
            m.tox += 1
            m.hp -= max(1, m.max_hp * m.tox // 16)
        m.hp = max(0, m.hp)
        if m.hp > 0 and m.item == "먹다남은음식" and m.hp < m.max_hp:
            m.hp = min(m.max_hp, m.hp + max(1, m.max_hp // 16))
            if ev is not None:
                ev.append(("item", side, m.species, "먹다남은음식"))


def step(s: State, a0: tuple, a1: tuple, rng=random, events: list | None = None) -> State:
    """한 턴을 진행한 새 상태를 반환한다(원본은 유지). events에 관측 가능한 사건을 기록한다."""
    s = s.copy()
    acts = (a0, a1)
    order = sorted((0, 1), key=lambda sd: (speed(s.mon(sd)), rng.random()), reverse=True)
    for side in order:
        if acts[side][0] == "switch":
            switch_in(s, side, acts[side][1])
    movers = [sd for sd in (0, 1) if acts[sd][0] == "move"]
    if len(movers) == 2:
        prio = [MOVES[s.mon(sd).moves[acts[sd][1]]][4] for sd in (0, 1)]
        movers.sort(key=lambda sd: (prio[sd], speed(s.mon(sd)), rng.random()), reverse=True)
        if events is not None and prio[0] == prio[1]:
            events.append(("first", movers[0], s.mon(0).copy(), s.mon(1).copy()))
    flinched = [False, False]
    moved = [False, False]
    for side in movers:
        name = s.mon(side).moves[acts[side][1]]
        _use_move(s, side, name, rng, events, moved[1 - side], acts[1 - side], flinched)
        moved[side] = True
    _end_of_turn(s, events)
    s.turn += 1
    return s
