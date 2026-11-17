"""대미지 계산 (9세대 공식, 레벨 50, 급소·도구·특성·날씨 미반영)."""
from __future__ import annotations

from .model import LEVEL, Mon, calc_stat, stage_mult
from .typechart import effectiveness


def rolls(power: int, atk: int, dfn: int, stab: bool, eff: float) -> list[int]:
    """난수 85~100 16개 대미지(HP 포인트)."""
    if eff == 0 or power == 0:
        return [0] * 16
    base = ((2 * LEVEL // 5 + 2) * power * atk // max(dfn, 1)) // 50 + 2
    out = []
    for r in range(85, 101):
        d = base * r // 100
        if stab:
            d = d * 3 // 2
        out.append(max(int(d * eff), 1))
    return out


def offense_stat(mon: Mon, cat: str, spread=None) -> int:
    stat = "atk" if cat == "P" else "spa"
    v = calc_stat(mon.species, stat, spread or mon.spread)
    v = int(v * stage_mult(mon.stages["atk" if cat == "P" else "spa"]))
    if cat == "P" and mon.status == "화상":
        v //= 2
    return v


def defense_stat(mon: Mon, cat: str, spread=None) -> int:
    stat = "def" if cat == "P" else "spd"
    return int(calc_stat(mon.species, stat, spread or mon.spread) * stage_mult(mon.stages[stat]))


def speed(mon: Mon, spread=None) -> int:
    v = int(calc_stat(mon.species, "spe", spread or mon.spread) * stage_mult(mon.stages["spe"]))
    return v // 2 if mon.status == "마비" else v


def damage_pct(atk: Mon, dfn: Mon, move: tuple, atk_spread=None, dfn_spread=None) -> list[float]:
    """공격자가 방어자에게 주는 대미지를 방어자 최대 HP 대비 %로 반환(16개 난수)."""
    mtype, cat, power, _acc, _prio = move
    a = offense_stat(atk, cat, atk_spread)
    d = defense_stat(dfn, cat, dfn_spread)
    hp = calc_stat(dfn.species, "hp", dfn_spread or dfn.spread)
    eff = effectiveness(mtype, dfn.types)
    return [x * 100 / hp for x in rolls(power, a, d, mtype in atk.types, eff)]
