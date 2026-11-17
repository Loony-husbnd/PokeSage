"""자동 대전 아레나: 에이전트끼리 시뮬레이터로 대전시켜 승률을 측정한다.

    python -m pokesage.arena --a search --b maxdmg --games 100 --depth 2

팀은 포챔스 로스터 전체에서 무작위로 뽑고, 기술·배분·도구·특성은 sets.py의 예상 세트에서 뽑는다
(BSS 규칙: 도구 중복 금지, 메가스톤은 팀당 1개). 각 에이전트는 자기 팀만 정확히 알고, 상대 세트는
관측(피해·행동 순서·도구 발동·메가진화)으로 추론한다. 같은 팀 구성을 진영만 바꿔 두 번씩 대전한다.
"""
from __future__ import annotations

import argparse
import math
import random
import time

from .belief import Belief, Hyp, OppMon, make_worlds, prior
from .dex import ITEMS, PLAYABLE, base_of
from .search import GREEDY, best_replacement, recommend
from .sets import item_prior, likely_ability, likely_moves, spread_prior
from .sim import BMon, State, accuracy, damage, is_status_move, legal, pending, speed, step, switch_in, winner

MAX_TURNS = 100


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
        opts = [a for a in legal(s, 0) if a[0] == "move"]
        if not opts:
            return legal(s, 0)[0]

        def score(a):
            i = a[1]
            if i < 0 or is_status_move(me.moves[i]):
                return 0.0
            mid = me.moves[i]
            return min(damage(me, foe, mid, 92, s=s, aside=0), foe.hp) * min(100.0, accuracy(me, foe, mid, s))
        return max(opts, key=score)

    def replace(self, worlds, rng):
        return best_replacement(worlds[:1], 0, rng.random(), 1.0)


class SearchAgent:
    def __init__(self, depth=2, samples=2, worlds=3, greedy=GREEDY):
        self.depth, self.samples, self.k, self.greedy = depth, samples, worlds, greedy
        self.name = f"search(d{depth},g{greedy:g})"

    def act(self, worlds, rng):
        return recommend(worlds[:self.k], self.depth, self.samples, rng.random(), self.greedy)[0].action

    def replace(self, worlds, rng):
        return best_replacement(worlds[:self.k], 1, rng.random(), self.greedy)


def make_agent(name: str, depth: int = 2, samples: int = 2, worlds: int = 3, greedy: float = GREEDY):
    if name == "search":
        return SearchAgent(depth, samples, worlds, greedy)
    return {"random": RandomAgent, "maxdmg": MaxDamageAgent}[name]()


# ---------- 팀 생성 ----------

def _pick(rng, pairs):
    keys = [k for k, _ in pairs]
    return rng.choices(keys, [w for _, w in pairs])[0]


def random_team(rng, n: int = 3, pool=None) -> list[BMon]:
    """무작위 팀(도구 중복 금지, 메가스톤 1개 이하)."""
    pool = [s for s in (pool or PLAYABLE) if len(likely_moves(s)) >= 2]
    team, used_items, mega = [], set(), False
    for sp in rng.sample(pool, n):
        sp_spread = _pick(rng, spread_prior(sp))
        for _ in range(20):
            it = _pick(rng, item_prior(sp))
            is_stone = bool(ITEMS.get(it, {}).get("megaStone"))
            if (it in used_items and it != "other") or (is_stone and mega):
                continue
            break
        else:
            it = "other"
            is_stone = False
        used_items.add(it)
        mega |= is_stone
        team.append(BMon(sp, sp_spread, likely_moves(sp), it, likely_ability(sp)))
    return team


# ---------- 대전 ----------

class Game:
    """실제 상태와 양쪽의 관측·추론 상태를 함께 관리한다."""

    def __init__(self, team0, team1):
        self.s = State([m.copy() for m in team0], [m.copy() for m in team1])
        self.true_hyp = [{m.species: Hyp(m.spread, m.item) for m in t} for t in (team0, team1)]
        self.beliefs: list[dict[str, Belief]] = [{}, {}]
        self.seen: list[list[int]] = [[], []]
        self._mark_seen()
        for side in (0, 1):
            from .sim import on_start
            on_start(self.s, side)

    def _mark_seen(self):
        for side in (0, 1):
            j = self.s.active[1 - side]
            if j not in self.seen[side]:
                self.seen[side].append(j)
                sp = base_of(self.s.teams[1 - side][j].species)
                self.beliefs[side][sp] = Belief(sp)

    def worlds(self, side: int, k: int = 4):
        s = self.s
        opp_team = s.teams[1 - side]
        opps = [OppMon(self.beliefs[side][base_of(opp_team[j].species)], opp_team[j].frac, opp_team[j].status,
                       tuple(opp_team[j].stages), opp_team[j].tox, opp_team[j].slp, opp_team[j].vol)
                for j in self.seen[side]]
        sides = [s.sides[side], s.sides[1 - side]]
        return make_worlds(s.teams[side], s.active[side], opps, self.seen[side].index(s.active[1 - side]),
                           len(opp_team) - len(self.seen[side]), k, s.field, sides, s.turn)

    def _observe(self, events):
        for e in events:
            kind = e[0]
            for obs in (0, 1):
                B = self.beliefs[obs]
                if kind == "used" and e[1] != obs:
                    B[base_of(e[2])].reveal_move(e[3])
                elif kind == "mega" and e[1] != obs:
                    B[base_of(e[2])].reveal_mega(e[3])
                elif kind == "ability" and e[1] != obs and base_of(e[2]) in B:
                    B[base_of(e[2])].reveal_ability(e[3])
                elif kind == "hit" and not e[6]:
                    _, side, move, att, dfn, dmg, _, st = e
                    ko = dmg >= dfn.hp
                    if side == obs and base_of(dfn.species) in B:
                        B[base_of(dfn.species)].observe_dealt(att, move, dfn.frac, dfn.status, dfn.stages,
                                                              dmg / dfn.max_hp, ko=ko, state=st, side=side)
                    elif side != obs and base_of(att.species) in B:
                        B[base_of(att.species)].observe_taken(move, att.frac, att.status, att.stages, dfn,
                                                              dmg / dfn.max_hp, ko=ko, state=st, side=side)
                elif kind == "first":
                    first, m0, m1, st = e[1], e[2], e[3], e[4]
                    mine, opp = (m0, m1) if obs == 0 else (m1, m0)
                    if base_of(opp.species) in B:
                        B[base_of(opp.species)].observe_order(first != obs, speed(mine, st, obs),
                                                              opp.status, opp.stages, st, 1 - obs)
                elif kind == "item" and e[1] != obs and base_of(e[2]) in B:
                    B[base_of(e[2])].reveal_item(e[3])
                elif kind == "itemlost" and e[1] != obs and base_of(e[2]) in B:
                    B[base_of(e[2])].lose_item()

    def play(self, agents, rng) -> int:
        """승자 side를 반환한다(턴 제한 시 남은 HP 비율 합으로 판정)."""
        while winner(self.s) is None and self.s.turn <= MAX_TURNS:
            for side in (0, 1):
                if pending(self.s, side):
                    ev: list = []
                    switch_in(self.s, side, agents[side].replace(self.worlds(side), rng), ev)
                    self._mark_seen()
                    self._observe(ev)
            if winner(self.s) is not None:
                break
            if any(pending(self.s, sd) for sd in (0, 1)):
                continue
            acts = [agents[side].act(self.worlds(side), rng) for side in (0, 1)]
            ev = []
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
        true = {base_of(k): v for k, v in self.true_hyp[1 - side].items()}
        for sp, b in B.items():
            h = true[sp]
            pri += prior(sp).get(h, 0.0)
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
    names = ["search", "maxdmg", "random"]
    ap.add_argument("--a", choices=names, default="search")
    ap.add_argument("--b", choices=names, default="maxdmg")
    ap.add_argument("--games", type=int, default=50)
    ap.add_argument("--team-size", type=int, default=3)
    ap.add_argument("--depth", type=int, default=2, help="search 에이전트의 탐색 깊이")
    ap.add_argument("--samples", type=int, default=2, help="행렬 칸당 표본 수")
    ap.add_argument("--worlds", type=int, default=3, help="고려할 상대 세트 후보 수")
    ap.add_argument("--greedy", type=float, default=GREEDY,
                    help="search가 보는 '상대가 최대 피해 기술을 고를' 확률(0~1)")
    ap.add_argument("--b-depth", type=int, default=None, help="b가 search일 때의 깊이(기본: --depth)")
    ap.add_argument("--b-greedy", type=float, default=None, help="b가 search일 때의 greedy(기본: --greedy)")
    ap.add_argument("--seed", type=int, default=0)
    o = ap.parse_args(argv)
    a = make_agent(o.a, o.depth, o.samples, o.worlds, o.greedy)
    b = make_agent(o.b, o.b_depth or o.depth, o.samples, o.worlds,
                   o.greedy if o.b_greedy is None else o.b_greedy)
    r = run_match(a, b, o.games, o.team_size, o.seed)
    lo, hi = r["ci95"]
    print(f"\n{r['a']} vs {r['b']}: {r['games']}판, 승률 {r['win_rate']:.1%} (95% 신뢰구간 {lo:.1%}~{hi:.1%})")
    print(f"평균 {r['avg_turns']:.1f}턴, 소요 {r['seconds']:.0f}초")
    print(f"세트 추론({r['a']}): 실제 세트 확률 {r['belief_prior']:.1%} → {r['belief_post']:.1%}")
    return r


if __name__ == "__main__":
    main()
