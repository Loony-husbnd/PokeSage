"""자동 대전 아레나: 에이전트끼리 시뮬레이터로 대전시켜 승률을 측정한다.

    python -m pokesage.arena --a search --b heuristic --games 100 --depth 2

각 에이전트는 자기 팀만 정확히 알고, 상대는 관측(피해·행동 순서·도구 발동)으로 추론한다.
같은 팀 구성을 진영만 바꿔 두 번씩 대전하여 팀 운의 영향을 줄인다.
"""
from __future__ import annotations

import argparse
import math
import random
import time

from . import advisor
from .belief import Belief, Hyp, OppMon, make_worlds, prior
from .dex import MOVES, POKEMON
from .model import Mon, STAT_KO
from .search import GREEDY, best_replacement, recommend
from .sim import BMon, State, damage_rolls, legal, pending, speed, step, switch_in, winner

MAX_TURNS = 150


# ---------- 에이전트 ----------

class RandomAgent:
    name = "random"

    def act(self, worlds, rng):
        return rng.choice(legal(worlds[0][1], 0))

    def replace(self, worlds, rng):
        return rng.choice(legal(worlds[0][1], 0))[1]


class MaxDamageAgent(RandomAgent):
    """가장 유력한 상대 세트 기준으로 기대 피해가 최대인 기술을 고른다(교체 안 함)."""
    name = "maxdmg"

    def act(self, worlds, rng):
        s = worlds[0][1]
        me, foe = s.mon(0), s.mon(1)

        def score(i):
            name = me.moves[i]
            return min(sum(damage_rolls(me, foe, name)) / 16, foe.hp) * MOVES[name][3]
        return ("move", max(range(len(me.moves)), key=score))

    def replace(self, worlds, rng):
        return legal(worlds[0][1], 0)[0][1]


class HeuristicAgent(MaxDamageAgent):
    """탐색 도입 이전의 1수 휴리스틱(advisor.recommend)."""
    name = "heuristic"

    @staticmethod
    def _mon(b: BMon) -> Mon:
        return Mon(b.species, b.spread_name, list(b.moves), max(1, round(b.frac * 100)) if b.hp > 0 else 0,
                   b.status, stages=dict(zip(STAT_KO, b.stages)))

    def act(self, worlds, rng):
        s = worlds[0][1]
        me = s.mon(0)
        bench = [(j, self._mon(m)) for j, m in enumerate(s.teams[0]) if j != s.active[0] and m.hp > 0]
        best = advisor.recommend(self._mon(me), [m for _, m in bench], self._mon(s.mon(1)))[0]
        if best.kind == "move":
            return ("move", me.moves.index(best.name))
        return ("switch", next(j for j, m in bench if m.species == best.name))


class SearchAgent:
    def __init__(self, depth=2, samples=2, worlds=3, greedy=GREEDY):
        self.depth, self.samples, self.k, self.greedy = depth, samples, worlds, greedy
        self.name = f"search(d{depth},g{greedy:g})"

    def act(self, worlds, rng):
        return recommend(worlds[:self.k], self.depth, self.samples, rng.random(), self.greedy)[0].action

    def replace(self, worlds, rng):
        return best_replacement(worlds[:self.k], 1, rng.random(), self.greedy)


def make_agent(name: str, depth: int = 2, samples: int = 2, worlds: int = 3):
    if name == "search":
        return SearchAgent(depth, samples, worlds)
    return {"random": RandomAgent, "maxdmg": MaxDamageAgent, "heuristic": HeuristicAgent}[name]()


# ---------- 대전 ----------

def random_team(rng, n: int = 3) -> list[BMon]:
    team = []
    for sp in rng.sample(list(POKEMON), n):
        p = prior(sp)
        hyp = rng.choices(list(p), list(p.values()))[0]
        team.append(BMon(sp, hyp.spread, None, hyp.item))
    return team


class Game:
    """실제 상태와 양쪽의 관측·추론 상태를 함께 관리한다."""

    def __init__(self, team0, team1):
        self.s = State([m.copy() for m in team0], [m.copy() for m in team1])
        self.true_hyp = [{m.species: Hyp(m.spread_name, m.item) for m in t} for t in (team0, team1)]
        self.beliefs = [{}, {}]  # beliefs[side][상대 종] = Belief
        self.seen = [[], []]     # seen[side] = side가 본 상대 팀 인덱스(공개 순)
        self._mark_seen()

    def _mark_seen(self):
        for side in (0, 1):
            j = self.s.active[1 - side]
            if j not in self.seen[side]:
                self.seen[side].append(j)
                sp = self.s.teams[1 - side][j].species
                self.beliefs[side][sp] = Belief(sp)

    def worlds(self, side: int, k: int = 4):
        s = self.s
        opp_team = s.teams[1 - side]
        opps = [OppMon(self.beliefs[side][opp_team[j].species], opp_team[j].frac, opp_team[j].status,
                       tuple(opp_team[j].stages), opp_team[j].tox, opp_team[j].slp)
                for j in self.seen[side]]
        return make_worlds(s.teams[side], s.active[side], opps,
                           self.seen[side].index(s.active[1 - side]),
                           len(opp_team) - len(self.seen[side]), k)

    def _observe(self, events):
        for e in events:
            kind = e[0]
            for obs in (0, 1):
                B = self.beliefs[obs]
                if kind == "used" and e[1] != obs:
                    B[e[2]].reveal_move(e[3])
                elif kind == "hit" and not e[6]:
                    _, side, move, att, dfn, dmg, _ = e
                    ko = dmg >= dfn.hp
                    if side == obs:
                        B[dfn.species].observe_dealt(att, move, dfn.frac, dfn.status, dfn.stages,
                                                     dmg / dfn.max_hp, ko=ko)
                    else:
                        B[att.species].observe_taken(move, att.frac, att.status, att.stages, dfn,
                                                     dmg / dfn.max_hp, ko=ko)
                elif kind == "first":
                    mine, opp = e[2 + obs], e[3 - obs]
                    B[opp.species].observe_order(e[1] != obs, speed(mine), opp.status, opp.stages)
                elif kind == "item" and e[1] != obs:
                    B[e[2]].reveal_item(e[3])
                elif kind == "itemlost" and e[1] != obs:
                    B[e[2]].lose_item()

    def play(self, agents, rng) -> int:
        """승자 side를 반환한다(턴 제한 시 남은 HP 합으로 판정)."""
        while winner(self.s) is None and self.s.turn <= MAX_TURNS:
            for side in (0, 1):
                if pending(self.s, side):
                    switch_in(self.s, side, agents[side].replace(self.worlds(side), rng))
                    self._mark_seen()
            acts = [agents[side].act(self.worlds(side), rng) for side in (0, 1)]
            ev: list = []
            self.s = step(self.s, acts[0], acts[1], rng, ev)
            self._mark_seen()
            self._observe(ev)
        w = winner(self.s)
        if w is None:
            hp = [sum(m.frac for m in t) for t in self.s.teams]
            w = 0 if hp[0] >= hp[1] else 1
        return w

    def belief_quality(self, side: int) -> tuple[float, float]:
        """side가 본 상대 포켓몬들의 (실제 세트 사전확률 평균, 사후확률 평균)."""
        pri = post = 0.0
        B = self.beliefs[side]
        for sp, b in B.items():
            h = self.true_hyp[1 - side][sp]
            pri += prior(sp)[h]
            post += b.prob(h)
        return pri / len(B), post / len(B)


def run_match(a, b, games: int = 50, team_size: int = 3, seed: int = 0, verbose: bool = True) -> dict:
    """a와 b를 games판 대전시킨다(짝수로 올림: 같은 팀으로 진영을 바꿔 2판씩)."""
    rng = random.Random(seed)
    wins = n = turns = 0
    pri = post = 0.0
    t0 = time.time()
    for g in range((games + 1) // 2):
        t_a, t_b = random_team(rng, team_size), random_team(rng, team_size)
        for swap in (False, True):
            game = Game(t_b, t_a) if swap else Game(t_a, t_b)
            w = game.play([b, a] if swap else [a, b], rng)
            a_side = 1 if swap else 0
            wins += w == a_side
            n += 1
            turns += game.s.turn
            q = game.belief_quality(a_side)
            pri, post = pri + q[0], post + q[1]
        if verbose and (g + 1) % 5 == 0:
            print(f"  {n}판: {a.name} 승률 {wins / n:.1%}", flush=True)
    p = wins / n
    z = 1.96
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return {"a": a.name, "b": b.name, "games": n, "win_rate": p, "ci95": (c - h, c + h),
            "avg_turns": turns / n, "belief_prior": pri / n, "belief_post": post / n,
            "seconds": time.time() - t0}


def main(argv=None):
    ap = argparse.ArgumentParser(description="PokeSage 자동 대전 아레나")
    names = ["search", "heuristic", "maxdmg", "random"]
    ap.add_argument("--a", choices=names, default="search")
    ap.add_argument("--b", choices=names, default="heuristic")
    ap.add_argument("--games", type=int, default=50)
    ap.add_argument("--team-size", type=int, default=3)
    ap.add_argument("--depth", type=int, default=2, help="search 에이전트의 탐색 깊이")
    ap.add_argument("--samples", type=int, default=2, help="행렬 칸당 표본 수")
    ap.add_argument("--worlds", type=int, default=3, help="고려할 상대 세트 후보 수")
    ap.add_argument("--b-depth", type=int, default=None, help="b가 search일 때의 깊이(기본: --depth)")
    ap.add_argument("--seed", type=int, default=0)
    o = ap.parse_args(argv)
    a = make_agent(o.a, o.depth, o.samples, o.worlds)
    b = make_agent(o.b, o.b_depth or o.depth, o.samples, o.worlds)
    r = run_match(a, b, o.games, o.team_size, o.seed)
    lo, hi = r["ci95"]
    print(f"\n{r['a']} vs {r['b']}: {r['games']}판, 승률 {r['win_rate']:.1%} (95% 신뢰구간 {lo:.1%}~{hi:.1%})")
    print(f"평균 {r['avg_turns']:.1f}턴, 소요 {r['seconds']:.0f}초")
    print(f"세트 추론({r['a']}): 실제 세트 확률 {r['belief_prior']:.1%} → {r['belief_post']:.1%}")
    return r


if __name__ == "__main__":
    main()
