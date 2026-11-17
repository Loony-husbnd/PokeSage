"""동시수 게임 탐색.

매 턴을 (내 행동 x 상대 행동) 보수 행렬로 보고 깊이 제한 탐색으로 채운 뒤 균형 전략을 구한다.
상대 세트가 불확실하므로 루트에서는 세트 후보(world)별 행렬을 만들어 베이즈 게임으로 푼다:
나는 상대 세트를 모르고 하나의 전략을 쓰고, 상대는 자기 세트에 맞춰 최선으로 대응한다.
값은 항상 side 0(나) 관점이며 범위는 [-1, 1]이다.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from .dex import MOVE_FX, MOVES
from .sim import State, damage, legal, pending, stalled, step, switch_in, winner


GREEDY = 0.8  # 상대가 '뻔한 수'(최대 피해 기술)를 둘 것으로 보는 기본 확률(아레나 측정으로 결정)


class SearchRng(random.Random):
    """탐색용 난수원. sim이 아래 속성을 읽는다.

    mean: 대미지 난수·급소를 평균값으로 고정 / hits, procs: {side: bool} 명중·부가 효과 결과 지정
    quiet: 지정되지 않은 확률형 부가 효과는 발동하지 않는 것으로 처리
    """
    mean = True
    quiet = True
    hits = None
    procs = None


@dataclass
class Rec:
    action: tuple   # ("move", i) | ("switch", j)
    freq: float     # 균형 전략에서의 선택 비중
    q: float        # 상대 균형 전략에 대한 기대값


# ---------- 평가 함수 ----------

def _side_score(team, unrevealed: int) -> float:
    t = float(unrevealed)
    for m in team:
        if m.hp > 0:
            v = 0.4 + 0.6 * m.hp / m.max_hp
            if m.status in ("마비", "잠듦", "얼음"):
                v -= 0.12
            elif m.status != "없음":
                v -= 0.08
            t += v
    return t


def evaluate(s: State) -> float:
    a = _side_score(s.teams[0], s.unrevealed[0])
    b = _side_score(s.teams[1], s.unrevealed[1])
    n = max(len(s.teams[0]) + s.unrevealed[0], len(s.teams[1]) + s.unrevealed[1])
    v = (a - b) / n
    for side, sign in ((0, 1), (1, -1)):
        m = s.mon(side)
        if m.hp > 0:
            st = m.stages
            v += sign * 0.03 * (st[0] + st[2] + st[4] + 0.5 * (st[1] + st[3])) / n
    return max(-0.95, min(0.95, v))


# ---------- 행렬 게임 풀이 (가상 플레이) ----------

def solve(Ms: list[list[list[float]]], ps: list[float], iters: int = 2000):
    """베이즈 영합 게임 풀이. Ms[w][a][b]: world w에서의 내 보수, ps[w]: world 확률.

    반환: (내 혼합 전략 x, 행동별 기대값 q, 게임 값)
    """
    m, W = len(Ms[0]), len(Ms)
    xc = [0] * m
    ycs = [[0] * len(M[0]) for M in Ms]
    cum_a = [0.0] * m
    cum_b = [[0.0] * len(M[0]) for M in Ms]
    a, bs = 0, [0] * W
    for _ in range(iters):
        xc[a] += 1
        for w in range(W):
            ycs[w][bs[w]] += 1
            M, b, p = Ms[w], bs[w], ps[w]
            for i in range(m):
                cum_a[i] += p * M[i][b]
            row, cb = M[a], cum_b[w]
            for j in range(len(cb)):
                cb[j] += row[j]
        a = max(range(m), key=cum_a.__getitem__)
        bs = [min(range(len(cb)), key=cb.__getitem__) for cb in cum_b]
    x = [c / iters for c in xc]
    q = [0.0] * m
    for w in range(W):
        y = [c / iters for c in ycs[w]]
        for i in range(m):
            q[i] += ps[w] * sum(Ms[w][i][j] * y[j] for j in range(len(y)))
    lower = sum(ps[w] * min(sum(x[i] * Ms[w][i][j] for i in range(m)) for j in range(len(Ms[w][0])))
                for w in range(W))
    return x, q, (lower + max(q)) / 2


def _value_of(M: list[list[float]]) -> float:
    """단일 행렬 게임의 값. 안장점이 있으면 정확값, 없으면 짧은 가상 플레이 근사."""
    lo = max(min(r) for r in M)
    hi = min(max(r[j] for r in M) for j in range(len(M[0])))
    if hi - lo < 1e-9:
        return lo
    return solve([M], [1.0], 40)[2]


# ---------- 탐색 ----------

def _outcomes(s: State, side: int, act: tuple, full: bool) -> list[tuple]:
    """행동의 (확률, 명중 여부, 부가 효과 발동 여부) 목록. full이면 부가 효과까지 나눈다."""
    if act[0] != "move":
        return [(1.0, None, None)]
    name = s.mon(side).moves[act[1]]
    _t, cat, _pw, acc, _pr = MOVES[name]
    fx = MOVE_FX.get(name, {})
    acc = 1.0 if cat == "Z" and "status" not in fx else acc / 100
    c = 0.0
    if full and cat != "Z":
        if "flinch" in fx:
            c = fx["flinch"] / 100
        elif ("status" in fx or "foe" in fx) and fx.get("chance", 100) < 100:
            c = fx["chance"] / 100
    outs = [(1 - acc, False, None)] if acc < 1 else []
    if c:
        outs += [(acc * c, True, True), (acc * (1 - c), True, False)]
    else:
        outs.append((acc, True, None))
    return outs


def _expect(s: State, a: tuple, b: tuple, r: SearchRng, depth: int, cfg, root_seed=None) -> float:
    """(a, b)를 둔 뒤의 기대값. 명중은 추첨하지 않고 확률로 가중한다.

    root_seed가 주어지면 루트 수로 취급한다: 부가 효과도 확률로 가중하고, 실제 대미지 난수·급소를
    추첨하되 모든 칸이 같은 난수열을 쓰도록 매번 같은 시드로 되돌린다.
    """
    root = root_seed is not None
    tot = 0.0
    for p0, h0, c0 in _outcomes(s, 0, a, root):
        for p1, h1, c1 in _outcomes(s, 1, b, root):
            if root:
                r.seed(root_seed)
                r.mean = False
            r.hits = {sd: h for sd, h in ((0, h0), (1, h1)) if h is not None}
            r.procs = {sd: c for sd, c in ((0, c0), (1, c1)) if c is not None}
            t = step(s, a, b, r)
            r.mean = True
            tot += p0 * p1 * value(t, depth, r, cfg)
    return tot


def _greedy_col(s: State, B: list[tuple]) -> int:
    """상대(side 1)의 '뻔한 수'(기대 피해 최대 기술)의 열 번호."""
    me, foe = s.mon(1), s.mon(0)
    best, best_d = 0, -1.0
    for j, (kind, i) in enumerate(B):
        if kind == "move":
            mv = MOVES[me.moves[i]]
            if mv[1] != "Z":
                d = min(damage(me, foe, me.moves[i], 92), foe.hp) * mv[3]
                if d > best_d:
                    best, best_d = j, d
    return best


def _blend(M: list[list[float]], g: int, lam: float) -> list[list[float]]:
    """상대가 확률 lam으로 뻔한 수(g열)를 두고, 나머지 확률로만 자유롭게 대응한다고 본 행렬."""
    if not lam:
        return M
    return [[lam * row[g] + (1 - lam) * v for v in row] for row in M]


def value(s: State, depth: int, rng, cfg: float = 0.0) -> float:
    w = winner(s)
    if w is not None:
        return 1.0 if w == 0 else -1.0
    if stalled(s):
        return evaluate(s)
    for side in (0, 1):
        if pending(s, side):
            vals = []
            for _, j in legal(s, side):
                t = s.copy()
                switch_in(t, side, j)
                vals.append(value(t, depth, rng, cfg))
            return max(vals) if side == 0 else min(vals)
    if depth <= 0:
        return evaluate(s)
    A, B = legal(s, 0), legal(s, 1)
    M = [[_expect(s, a, b, rng, depth - 1, cfg) for b in B] for a in A]
    return _value_of(_blend(M, _greedy_col(s, B), cfg) if cfg else M)


def recommend(worlds: list[tuple[float, State]], depth: int = 2, samples: int = 4,
              seed: int | None = 0, greedy: float = GREEDY) -> list[Rec]:
    """행동 추천. worlds는 belief.make_worlds()의 결과. 선택 비중이 높은 순으로 반환한다.

    루트 수는 실제 대미지 난수·급소를 samples번 추첨하고(모든 칸이 같은 난수열을 공유),
    명중과 부가 효과는 확률로 정확히 가중한다. 그 아래 수는 평균 대미지로 계산한다.
    greedy: 상대가 '뻔한 수'를 둘 확률(0이면 순수 균형 전략, 1이면 뻔한 수에 대한 최선 응수).
    """
    base = random.Random(seed).getrandbits(32)
    r = SearchRng()
    A = legal(worlds[0][1], 0)
    Ms, ps = [], []
    for p, s in worlds:
        B = legal(s, 1) or [("move", 0)]
        M = [[sum(_expect(s, a, b, r, depth - 1, greedy, base + i) for i in range(samples)) / samples
              for b in B] for a in A]
        Ms.append(_blend(M, _greedy_col(s, B), greedy))
        ps.append(p)
    x, q, _ = solve(Ms, ps)
    recs = [Rec(a, x[i], q[i]) for i, a in enumerate(A)]
    return sorted(recs, key=lambda r: (round(r.freq, 2), r.q), reverse=True)


def best_replacement(worlds: list[tuple[float, State]], depth: int = 1, seed: int | None = 0,
                     greedy: float = GREEDY) -> int:
    """내 선두가 기절했을 때 내보낼 포켓몬의 팀 인덱스."""
    rng = SearchRng(seed)
    best, best_v = None, -9.0
    for _, j in legal(worlds[0][1], 0):
        v = 0.0
        for p, s in worlds:
            t = s.copy()
            switch_in(t, 0, j)
            v += p * value(t, depth, rng, greedy)
        if v > best_v:
            best, best_v = j, v
    return best
