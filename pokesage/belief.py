"""상대 세트 추론: 능력 포인트 배분·도구 후보의 확률 분포를 관측으로 베이즈 갱신한다.

사전확률은 sets.py(사용률 파일이 있으면 그 값, 없으면 종족값 기반 규칙)에서 온다.
기술은 확인된 것을 우선 쓰고, 나머지는 예상 기술로 채운다. 특성은 공개되기 전까지 가장 유력한 것으로 본다.
"""
from __future__ import annotations

from typing import NamedTuple

from .dex import MOVES, SPECIES
from .model import Spread
from .sets import item_prior, likely_ability, likely_moves, spread_prior
from .sim import NONE, BMon, State, damage_rolls, speed

EPS = 1e-3  # 모순된 관측에도 후보를 완전히 지우지 않기 위한 하한


class Hyp(NamedTuple):
    spread: Spread
    item: str


def prior(species: str) -> dict[Hyp, float]:
    out = {}
    for sp, ws in spread_prior(species):
        for it, wi in item_prior(species):
            out[Hyp(sp, it)] = ws * wi
    tot = sum(out.values())
    return {h: w / tot for h, w in out.items()}


class Belief:
    """상대 포켓몬 한 마리에 대한 추론 상태."""

    def __init__(self, species: str):
        self.species = species          # 원래(메가 전) 형태
        p = prior(species)
        self.hyps = list(p)
        self.w = [p[h] for h in self.hyps]
        self.moves: list[str] = []      # 확인된 기술
        self.item_gone = False          # 도구를 잃었는가
        self.ability = likely_ability(species)
        self.ability_known = False
        self.mega: str | None = None    # 메가진화한 형태

    # ----- 조회 -----
    def moveset(self) -> tuple[str, ...]:
        mv = list(self.moves[:4])
        for m in likely_moves(self.species):
            if len(mv) >= 4:
                break
            if m not in mv:
                mv.append(m)
        return tuple(mv)

    def top(self, k: int) -> list[tuple[float, Hyp]]:
        """확률 상위 k개 후보(확률 재정규화)."""
        ranked = sorted(zip(self.w, self.hyps), key=lambda t: -t[0])[:k]
        tot = sum(w for w, _ in ranked) or 1.0
        return [(w / tot, h) for w, h in ranked]

    def prob(self, hyp: Hyp) -> float:
        return self.w[self.hyps.index(hyp)] if hyp in self.hyps else 0.0

    def marginal(self, field: str) -> dict:
        out: dict = {}
        for w, h in zip(self.w, self.hyps):
            k = getattr(h, field)
            out[k] = out.get(k, 0.0) + w
        return dict(sorted(out.items(), key=lambda t: -t[1]))

    def mon(self, hyp: Hyp, hp_frac=1.0, status=NONE, stages=None) -> BMon:
        item = "" if self.item_gone else hyp.item
        sid = self.mega or self.species
        m = BMon(sid, hyp.spread, self.moveset(), item, None, hp_frac, status, stages)
        if not self.mega:
            m.ability = self.ability
        else:
            m.mega_to = None
        return m

    # ----- 갱신 -----
    def _update(self, liks: list[float]) -> None:
        self.w = [w * max(l, EPS) for w, l in zip(self.w, liks)]
        tot = sum(self.w)
        self.w = [w / tot for w in self.w]

    def reveal_move(self, name: str) -> None:
        if name in MOVES and name not in self.moves:
            self.moves.append(name)

    def reveal_ability(self, ab: str) -> None:
        self.ability, self.ability_known = ab, True

    def reveal_item(self, item: str) -> None:
        if any(h.item == item for h in self.hyps):
            self._update([1.0 if h.item == item else 0.0 for h in self.hyps])
        else:  # 후보에 없던 도구: 배분 분포는 유지하고 도구만 바꾼다
            spreads = self.marginal("spread")
            self.hyps = [Hyp(sp, item) for sp in spreads]
            self.w = list(spreads.values())

    def lose_item(self) -> None:
        self.item_gone = True

    def reveal_mega(self, mega_species: str) -> None:
        stone = SPECIES[mega_species].get("item")
        if stone:
            self.reveal_item(stone)
        self.mega = mega_species
        self.ability = SPECIES[mega_species]["abilities"][0]
        self.ability_known = True

    def _liks(self, fn) -> list[float]:
        return [fn(h) for h in self.hyps]

    def observe_dealt(self, att: BMon, move: str, hp_frac: float, status: str, stages,
                      dmg_frac: float, tol: float = 0.01, ko: bool = False, state: State | None = None,
                      side: int | None = None) -> None:
        """내 기술이 상대에게 준 피해(상대 최대 HP 대비 비율)로 내구를 추론한다."""
        def lik(h):
            d = self.mon(h, hp_frac, status, stages)
            rolls = damage_rolls(att, d, move, s=state, aside=side)
            if ko:
                return sum(r >= d.hp - tol * d.max_hp for r in rolls) / 16
            return sum(abs(r / d.max_hp - dmg_frac) <= tol for r in rolls) / 16
        self._update(self._liks(lik))

    def observe_taken(self, move: str, hp_frac: float, status: str, stages, dfn: BMon,
                      dmg_frac: float, tol: float = 0.01, ko: bool = False, state: State | None = None,
                      side: int | None = None) -> None:
        """상대 기술이 내게 준 피해(내 최대 HP 대비 비율)로 화력·도구를 추론한다."""
        self.reveal_move(move)

        def lik(h):
            a = self.mon(h, hp_frac, status, stages)
            rolls = damage_rolls(a, dfn, move, s=state, aside=side)
            if ko:
                return sum(r >= dfn.hp - tol * dfn.max_hp for r in rolls) / 16
            return sum(abs(r / dfn.max_hp - dmg_frac) <= tol for r in rolls) / 16
        self._update(self._liks(lik))

    def observe_order(self, opp_first: bool, my_speed: int, status: str, stages, state: State | None = None,
                      side: int | None = None) -> None:
        """같은 우선도에서 누가 먼저 움직였는지로 스피드(투자·스카프)를 추론한다.
        트릭룸 중이면 느린 쪽이 먼저 움직인다."""
        tr = bool(state and state.field.get("trickroom"))

        def lik(h):
            sp = speed(self.mon(h, 1.0, status, stages), state, side)
            if sp == my_speed:
                return 0.5
            faster = sp > my_speed
            return float((faster != tr) == opp_first)
        self._update(self._liks(lik))


class OppMon(NamedTuple):
    """관측된 상대 포켓몬의 현재 상태."""
    belief: Belief
    hp_frac: float
    status: str = NONE
    stages: tuple = (0, 0, 0, 0, 0, 0, 0)
    tox: int = 0
    slp: int = 0
    vol: dict | None = None


def make_worlds(my_team: list[BMon], my_active: int, opps: list[OppMon], opp_active: int,
                unrevealed: int, k: int = 4, field: dict | None = None, sides=None, turn: int = 1):
    """상대 선두의 세트 후보 상위 k개에 대해 (확률, State) 목록을 만든다. 나는 항상 side 0."""
    def build(o: OppMon, hyp: Hyp) -> BMon:
        m = o.belief.mon(hyp, o.hp_frac, o.status, o.stages)
        m.tox, m.slp = o.tox, o.slp
        if o.vol:
            m.vol = dict(o.vol)
        return m

    bench = {i: build(o, o.belief.top(1)[0][1]) for i, o in enumerate(opps) if i != opp_active}
    worlds = []
    for p, hyp in opps[opp_active].belief.top(k):
        team1 = [build(opps[opp_active], hyp) if i == opp_active else bench[i].copy()
                 for i in range(len(opps))]
        worlds.append((p, State([m.copy() for m in my_team], team1, (my_active, opp_active), (0, unrevealed),
                                turn, field, sides)))
    return worlds
