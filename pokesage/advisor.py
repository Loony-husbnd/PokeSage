"""턴별 추천 엔진 (싱글 배틀, 휴리스틱).

상대의 노력치·기술을 모르므로 범위로 다룬다.
 - 내가 주는 대미지: 최소 = 상대 내구 최대 가정 / 최대 = 상대 무투자 가정
 - 상대 스피드: 무투자(성격 하락)~252 성격 상승
 - 상대가 주는 대미지: 상대 자속(STAB) 위력 90 기술 기준, 공격 252 성격 상승 가정
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .calc import damage_pct, speed
from .dex import MOVES
from .model import MAX_BULK, MAX_OFFENSE, MAX_SPEED, MIN_SPREAD, Mon, calc_stat

OPP_THREAT_POWER = 90


@dataclass
class Option:
    kind: str  # "move" | "switch"
    name: str
    score: float
    summary: str
    detail: str = ""


def _speed_relation(me: Mon, opp: Mon) -> bool | None:
    """True=확실히 선공, False=확실히 후공, None=불확실."""
    mine = speed(me)
    lo, hi = speed(opp, MIN_SPREAD), speed(opp, MAX_SPEED)
    if mine > hi:
        return True
    if mine < lo:
        return False
    return None


def _spe_text(rel: bool | None) -> str:
    return {True: "선공 확정", False: "후공 확정", None: "스피드 불확실"}[rel]


def _opp_threat(opp: Mon, me: Mon) -> float:
    """상대 자속 기술이 내게 줄 수 있는 최대 대미지(내 최대 HP 대비 %)."""
    best = 0.0
    for t in opp.types:
        for cat in ("P", "S"):
            mv = (t, cat, OPP_THREAT_POWER, 100, 0)
            best = max(best, max(damage_pct(opp, me, mv, atk_spread=MAX_OFFENSE)))
    return best


def _move_range(me: Mon, opp: Mon, move: tuple) -> tuple[float, float]:
    lo = min(damage_pct(me, opp, move, dfn_spread=MAX_BULK))
    hi = max(damage_pct(me, opp, move, dfn_spread=MIN_SPREAD))
    return lo, hi


def _hits_text(opp_hp: float, lo: float, hi: float) -> tuple[str, str]:
    """(타수 문구, 확정도 문구)"""
    if hi <= 0:
        return "무효", ""
    if lo >= opp_hp:
        return "확정 1타", "sure"
    if hi >= opp_hp:
        return "난수 1타", "poss"
    n_best = math.ceil(opp_hp / hi)
    n_worst = math.ceil(opp_hp / lo) if lo > 0 else 99
    n = f"{n_best}타" if n_best == n_worst else f"{n_best}~{n_worst}타"
    return n, ""


def evaluate_moves(me: Mon, opp: Mon) -> list[Option]:
    rel = _speed_relation(me, opp)
    threat = _opp_threat(opp, me)
    opp_can_ko = threat >= me.hp_pct
    out = []
    for name in me.moves:
        move = MOVES[name]
        mtype, cat, power, acc, prio = move
        lo, hi = _move_range(me, opp, move)
        first = True if prio > 0 else rel
        hits, sure = _hits_text(opp.hp_pct, lo, hi)
        p_move = 1.0
        if opp_can_ko and first is False:
            p_move = 0.5
        elif opp_can_ko and first is None:
            p_move = 0.75
        mid = min((lo + hi) / 2, opp.hp_pct) * acc / 100
        ko_bonus = {"sure": 40, "poss": 20}.get(sure, 0) * acc / 100
        score = (mid + ko_bonus) * p_move
        if not (sure == "sure" and first is True and acc == 100):
            score -= min(threat, me.hp_pct) * 0.3
        order = "우선도 선공" if prio > 0 else _spe_text(rel)
        summary = f"{min(lo, 100):.0f}~{min(hi, 100):.0f}%, {hits}, {order}"
        if acc < 100:
            summary += f", 명중 {acc}%"
        if hi <= 0:
            score = -999
        out.append(Option("move", name, score, summary))
    return out


def evaluate_switches(bench: list[Mon], opp: Mon) -> list[Option]:
    out = []
    for b in bench:
        if not b.alive:
            continue
        threat = _opp_threat(opp, b)
        best = 0.0
        for name in b.moves:
            lo, hi = _move_range(b, opp, MOVES[name])
            best = max(best, min((lo + hi) / 2, opp.hp_pct))
        ko_risk = threat >= b.hp_pct
        score = best * 0.5 - min(threat * 0.7, b.hp_pct) * 0.5 - 10 - (40 if ko_risk else 0)
        risk = "교체 후 KO 위험" if ko_risk else f"받는 피해 최대 {threat:.0f}%"
        out.append(Option("switch", b.species, score, f"{risk}, 다음 턴 평균 {best:.0f}% 가능"))
    return out


def recommend(me: Mon, bench: list[Mon], opp: Mon) -> list[Option]:
    opts = evaluate_moves(me, opp) + evaluate_switches(bench, opp)
    return sorted(opts, key=lambda o: o.score, reverse=True)


def kibo_line(turn: int, me: Mon, opp: Mon, best: Option) -> str:
    verb = "교체" if best.kind == "switch" else "기술"
    return f"T{turn} | 나 {me.label()} vs 상대 {opp.label()} | 추천 {verb}: {best.name} ({best.summary})"
