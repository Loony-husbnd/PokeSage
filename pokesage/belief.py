"""상대 세트 추론: 노력치 유형·도구 후보에 대한 확률 분포를 관측으로 베이즈 갱신한다.

사전확률은 종족값 기반의 일반 규칙이다. 실제 사용률 통계가 있으면 `prior()`를 교체하면 된다.
"""
from __future__ import annotations

from typing import NamedTuple

from .dex import MOVES, POKEMON
from .sim import BMon, damage_rolls, speed

EPS = 1e-3  # 모순된 관측에도 후보를 완전히 지우지 않기 위한 하한


class Hyp(NamedTuple):
    spread: str
    item: str


_PHYS, _SPEC = "물리 공격형 (공격·스피드 252)", "특수 공격형 (특공·스피드 252)"
_PDEF, _SDEF, _NONE = "물리 내구형 (HP·방어 252)", "특수 내구형 (HP·특방 252)", "무투자"
_BPHYS, _BSPEC = "내구 물리형 (HP·공격 252)", "내구 특수형 (HP·특공 252)"


def prior(species: str) -> dict[Hyp, float]:
    """세트 후보와 사전확률."""
    b = POKEMON[species][1]
    atk, spa = b[1], b[3]
    if abs(atk - spa) <= 15:
        wp = ws = 0.5
    else:
        wp, ws = (0.94, 0.06) if atk > spa else (0.06, 0.94)
    spreads = {_PHYS: 0.38 * wp, _SPEC: 0.38 * ws, _BPHYS: 0.22 * wp, _BSPEC: 0.22 * ws,
               _PDEF: 0.12, _SDEF: 0.12, _NONE: 0.02}
    out: dict[Hyp, float] = {}
    for sp, w in spreads.items():
        if sp in (_PHYS, _SPEC):
            choice = "구애머리띠" if sp == _PHYS else "구애안경"
            items = {choice: 0.15, "구애스카프": 0.15, "생명의구슬": 0.2, "기합의띠": 0.2, "기타": 0.3}
        elif sp in (_BPHYS, _BSPEC):
            choice = "구애머리띠" if sp == _BPHYS else "구애안경"
            items = {choice: 0.2, "생명의구슬": 0.1, "먹다남은음식": 0.2, "기타": 0.5}
        elif sp == _NONE:
            items = {"기타": 1.0}
        else:
            items = {"먹다남은음식": 0.4, "기타": 0.6}
        for it, wi in items.items():
            out[Hyp(sp, it)] = w * wi
    total = sum(out.values())
    return {h: w / total for h, w in out.items()}


class Belief:
    """상대 포켓몬 한 마리에 대한 추론 상태."""

    def __init__(self, species: str):
        self.species = species
        p = prior(species)
        self.hyps = list(p)
        self.w = [p[h] for h in self.hyps]
        self.moves: list[str] = []  # 확인된 기술
        self.item_gone = False      # 도구를 잃었는가

    # ----- 조회 -----
    def moveset(self) -> tuple[str, ...]:
        mv = list(self.moves)
        for m in POKEMON[self.species][2]:
            if len(mv) >= 4:
                break
            if m not in mv:
                mv.append(m)
        return tuple(mv[:4]) if len(self.moves) <= 4 else tuple(self.moves)

    def top(self, k: int) -> list[tuple[float, Hyp]]:
        """확률 상위 k개 후보(확률 재정규화)."""
        ranked = sorted(zip(self.w, self.hyps), key=lambda t: -t[0])[:k]
        tot = sum(w for w, _ in ranked) or 1.0
        return [(w / tot, h) for w, h in ranked]

    def prob(self, hyp: Hyp) -> float:
        return self.w[self.hyps.index(hyp)] if hyp in self.hyps else 0.0

    def marginal(self, field: str) -> dict[str, float]:
        out: dict[str, float] = {}
        for w, h in zip(self.w, self.hyps):
            k = getattr(h, field)
            out[k] = out.get(k, 0.0) + w
        return dict(sorted(out.items(), key=lambda t: -t[1]))

    def mon(self, hyp: Hyp, hp_frac=1.0, status="없음", stages=None) -> BMon:
        item = "없음" if self.item_gone else hyp.item
        return BMon(self.species, hyp.spread, self.moveset(), item, hp_frac, status, stages)

    # ----- 갱신 -----
    def _update(self, liks: list[float]) -> None:
        self.w = [w * max(l, EPS) for w, l in zip(self.w, liks)]
        tot = sum(self.w)
        self.w = [w / tot for w in self.w]

    def reveal_move(self, name: str) -> None:
        if name in MOVES and name not in self.moves:
            self.moves.append(name)

    def reveal_item(self, item: str) -> None:
        if any(h.item == item for h in self.hyps):
            self._update([1.0 if h.item == item else 0.0 for h in self.hyps])

    def lose_item(self) -> None:
        self.item_gone = True

    def observe_dealt(self, att: BMon, move: str, hp_frac: float, status: str, stages,
                      dmg_frac: float, tol: float = 0.01, ko: bool = False) -> None:
        """내 기술이 상대에게 준 피해(상대 최대 HP 대비 비율)로 내구를 추론한다."""
        liks = []
        for h in self.hyps:
            d = self.mon(h, hp_frac, status, stages)
            rolls = damage_rolls(att, d, move)
            if ko:
                n = sum(r >= d.hp - tol * d.max_hp for r in rolls)
            else:
                n = sum(abs(r / d.max_hp - dmg_frac) <= tol for r in rolls)
            liks.append(n / 16)
        self._update(liks)

    def observe_taken(self, move: str, hp_frac: float, status: str, stages, dfn: BMon,
                      dmg_frac: float, tol: float = 0.01, ko: bool = False) -> None:
        """상대 기술이 내게 준 피해(내 최대 HP 대비 비율)로 화력·도구를 추론한다."""
        self.reveal_move(move)
        liks = []
        for h in self.hyps:
            a = self.mon(h, hp_frac, status, stages)
            rolls = damage_rolls(a, dfn, move)
            if ko:
                n = sum(r >= dfn.hp - tol * dfn.max_hp for r in rolls)
            else:
                n = sum(abs(r / dfn.max_hp - dmg_frac) <= tol for r in rolls)
            liks.append(n / 16)
        self._update(liks)

    def observe_order(self, opp_first: bool, my_speed: int, status: str, stages) -> None:
        """같은 우선도에서 누가 먼저 움직였는지로 스피드(투자·스카프)를 추론한다."""
        liks = []
        for h in self.hyps:
            sp = speed(self.mon(h, 1.0, status, stages))
            liks.append(0.5 if sp == my_speed else float((sp > my_speed) == opp_first))
        self._update(liks)


class OppMon(NamedTuple):
    """관측된 상대 포켓몬의 현재 상태."""
    belief: Belief
    hp_frac: float
    status: str = "없음"
    stages: tuple = (0, 0, 0, 0, 0)
    tox: int = 0
    slp: int = 0


def make_worlds(my_team: list[BMon], my_active: int, opps: list[OppMon], opp_active: int,
                unrevealed: int, k: int = 4):
    """상대 선두의 세트 후보 상위 k개에 대해 (확률, State) 목록을 만든다. 나는 항상 side 0."""
    from .sim import State

    def build(o: OppMon, hyp: Hyp) -> BMon:
        m = o.belief.mon(hyp, o.hp_frac, o.status, o.stages)
        m.tox, m.slp = o.tox, o.slp
        return m

    bench = {i: build(o, o.belief.top(1)[0][1]) for i, o in enumerate(opps) if i != opp_active}
    worlds = []
    for p, hyp in opps[opp_active].belief.top(k):
        team1 = [build(opps[opp_active], hyp) if i == opp_active else bench[i].copy()
                 for i in range(len(opps))]
        worlds.append((p, State([m.copy() for m in my_team], team1,
                                (my_active, opp_active), (0, unrevealed))))
    return worlds
