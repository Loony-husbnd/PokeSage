"""시뮬레이터·세트 추론·탐색·아레나 테스트."""
import random

from pokesage import arena
from pokesage.belief import Belief, Hyp, OppMon, make_worlds, prior
from pokesage.calc import damage_pct
from pokesage.dex import MOVES, POKEMON
from pokesage.model import Mon
from pokesage.search import recommend, solve
from pokesage.sim import BMon, State, damage, damage_rolls, legal, speed, step, switch_in, winner

PHYS = "물리 공격형 (공격·스피드 252)"
BULK = "물리 내구형 (HP·방어 252)"


def _state(a: list[BMon], b: list[BMon]) -> State:
    return State(a, b)


def _move(m: BMon, name: str) -> tuple:
    return ("move", m.moves.index(name))


# ---------- 시뮬레이터 ----------

def test_sim_damage_matches_calc():
    """도구·특성이 없으면 새 시뮬레이터와 기존 계산기의 난수 16개가 같아야 한다."""
    for att, dfn, mv in [("한카리아스", "메타그로스", "지진"), ("팬텀", "가디안", "섀도볼"),
                         ("고릴타", "갸라도스", "우드해머"), ("개굴닌자", "마기라스", "하이드로펌프")]:
        a, d = BMon(att), BMon(dfn)
        d.ability = ""
        hp = d.max_hp
        old = [round(x * hp / 100) for x in damage_pct(Mon(att), Mon(dfn), MOVES[mv])]
        assert damage_rolls(a, d, mv) == old, (att, dfn, mv)


def test_step_does_not_mutate_and_hits():
    a, b = BMon("한카리아스", PHYS), BMon("메타그로스", BULK)
    s = _state([a], [b])
    t = step(s, _move(a, "지진"), ("move", 0), random.Random(1))
    assert s.mon(1).hp == b.max_hp            # 원본 유지
    assert t.mon(1).hp < b.max_hp             # 지진 명중
    assert t.turn == s.turn + 1


def test_priority_moves_first():
    """망나뇽의 신속(우선도 +2)은 더 빠른 상대보다 먼저 맞힌다."""
    dnite = BMon("망나뇽", PHYS, hp_frac=0.01)
    fast = BMon("개굴닌자", PHYS)
    assert speed(fast) > speed(dnite)
    s = _state([dnite], [fast])
    ev = []
    step(s, _move(dnite, "신속"), ("move", 0), random.Random(0), ev)
    used = [e for e in ev if e[0] == "used"]
    assert used[0][1] == 0 and used[0][3] == "신속"


def test_sucker_punch_fails_against_status_move():
    kingambit = BMon("대도각참", PHYS)
    garch = BMon("한카리아스", PHYS)       # 기본 기술에 칼춤 포함
    s = _state([kingambit], [garch])
    t = step(s, _move(kingambit, "기습"), _move(garch, "칼춤"), random.Random(0))
    assert t.mon(1).hp == garch.max_hp
    assert t.mon(1).stages[0] == 2


def test_focus_sash_survives_ohko():
    garch = BMon("한카리아스", PHYS)
    gengar = BMon("팬텀", "무투자", item="기합의띠")
    assert min(damage_rolls(garch, gengar, "지진")) >= gengar.max_hp
    s = _state([garch], [gengar])
    t = step(s, _move(garch, "지진"), ("move", 0), random.Random(0))
    assert t.mon(1).hp == 1 and t.mon(1).item == "없음"


def test_immunity_and_intimidate_on_switch():
    garch, dnite = BMon("한카리아스", PHYS), BMon("망나뇽", PHYS)
    gyara = BMon("갸라도스", PHYS)
    assert damage(garch, gyara, "지진") == 0
    s = _state([garch], [dnite, gyara])
    switch_in(s, 1, 1)
    assert s.mon(0).stages[0] == -1       # 위협


def test_burn_residual_and_winner():
    gengar = BMon("팬텀", PHYS)
    target = BMon("메타그로스", BULK, hp_frac=0.05)
    s = _state([gengar], [target])
    t = step(s, _move(gengar, "도깨비불"), ("move", 0), random.Random(3))
    if t.mon(1).status == "화상":
        assert t.mon(1).hp < target.hp or t.mon(1).hp == 0
    t.mon(1).hp = 0
    assert winner(t) == 0


# ---------- 세트 추론 ----------

def test_prior_is_distribution():
    for sp in POKEMON:
        p = prior(sp)
        assert abs(sum(p.values()) - 1) < 1e-9


def test_belief_learns_choice_band_from_damage():
    """구애머리띠 한카리아스의 실제 피해를 관측하면 머리띠 후보 확률이 오른다."""
    truth = BMon("한카리아스", PHYS, item="구애머리띠")
    me = BMon("메타그로스", BULK)
    b = Belief("한카리아스")
    before = b.marginal("item").get("구애머리띠", 0)
    for _ in range(2):
        dmg = damage(truth, me, "지진", 93)
        b.observe_taken("지진", 1.0, "없음", None, me, dmg / me.max_hp)
    assert b.marginal("item")["구애머리띠"] > max(0.5, before * 3)
    assert "지진" in b.moves


def test_belief_learns_scarf_from_order():
    me = BMon("개굴닌자", PHYS)          # 최속 개굴닌자보다 먼저 움직였다면 스카프
    b = Belief("한카리아스")
    b.observe_order(True, speed(me), "없음", None)
    assert b.marginal("item")["구애스카프"] > 0.9


def test_make_worlds_probabilities():
    opp = OppMon(Belief("망나뇽"), 1.0)
    worlds = make_worlds([BMon("한카리아스", PHYS)], 0, [opp], 0, unrevealed=2, k=3)
    assert len(worlds) == 3
    assert abs(sum(p for p, _ in worlds) - 1) < 1e-9
    assert worlds[0][1].unrevealed == [0, 2]


# ---------- 탐색 ----------

def test_solve_matching_pennies():
    x, q, v = solve([[[1, -1], [-1, 1]]], [1.0], iters=4000)
    assert abs(x[0] - 0.5) < 0.05 and abs(v) < 0.05


def test_search_takes_sure_ko():
    garch = BMon("한카리아스", PHYS)
    opp = OppMon(Belief("망나뇽"), 0.3)
    worlds = make_worlds([garch], 0, [opp], 0, unrevealed=0, k=3)
    best = recommend(worlds, depth=2, samples=1)[0]
    assert best.action == _move(garch, "드래곤크루")


def test_search_avoids_immune_move():
    excad = BMon("몰드류", PHYS)
    opp = OppMon(Belief("갸라도스"), 1.0)
    worlds = make_worlds([excad], 0, [opp], 0, unrevealed=0, k=2)
    recs = recommend(worlds, depth=1, samples=1)
    assert recs[0].action != _move(excad, "지진")


def test_legal_actions_after_faint():
    a, b = BMon("한카리아스", PHYS, hp_frac=0), BMon("가디안", BULK)
    s = _state([a, b], [BMon("망나뇽")])
    assert legal(s, 0) == [("switch", 1)]


# ---------- 아레나 ----------

def test_arena_smoke():
    r = arena.run_match(arena.make_agent("search", depth=1, samples=1, worlds=2),
                        arena.make_agent("random"), games=2, seed=0, verbose=False)
    assert r["games"] == 2 and 0 <= r["win_rate"] <= 1
    assert 0 <= r["belief_post"] <= 1


def test_arena_game_is_deterministic_for_seed():
    def once():
        rng = random.Random(5)
        t0, t1 = arena.random_team(rng), arena.random_team(rng)
        return arena.Game(t0, t1).play([arena.make_agent("maxdmg"), arena.make_agent("heuristic")], rng)
    assert once() == once()
