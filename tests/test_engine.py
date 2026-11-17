"""시뮬레이터·세트 추론·탐색·아레나 테스트 (포챔스 데이터 기준)."""
import random

import pytest

from pokesage import arena
from pokesage.belief import Belief, OppMon, make_worlds, prior
from pokesage.dex import ITEMS, MOVES, PLAYABLE, SPECIES
from pokesage.model import PRESETS, Spread, calc_stats, from_evs
from pokesage.search import recommend, solve
from pokesage.sets import likely_moves
from pokesage.sim import (BMon, State, damage, damage_rolls, legal, speed, step, switch_in, unsupported,
                          winner)

PHYS = PRESETS["물리 어태커 (공격·스피드 32, 고집)"]
JOLLY = PRESETS["물리 스피드형 (공격·스피드 32, 명랑)"]
SPEC = PRESETS["특수 어태커 (특공·스피드 32, 조심)"]
BULK = PRESETS["물리 내구형 (HP·방어 32, 장난꾸러기)"]
NOSP = PRESETS["무투자 (성격 무보정)"]


def mon(sp, spread=PHYS, moves=None, item="", ability=None, **kw):
    return BMon(sp, spread, moves or likely_moves(sp), item, ability, **kw)


def mv(m: BMon, name: str) -> tuple:
    return ("move", m.moves.index(name))


class Mean(random.Random):
    mean = True


# ---------- 데이터 ----------

def test_roster_and_names():
    assert len(PLAYABLE) >= 230
    assert SPECIES["garchomp"]["ko"] == "한카리아스"
    assert MOVES["earthquake"]["ko"] == "지진"
    assert ITEMS["choicescarf"]["ko"] == "구애스카프"
    assert {"garchompmega", "garchompmegaz"} <= set(SPECIES["garchomp"]["megas"])
    assert all(len(likely_moves(s)) == 4 for s in PLAYABLE if s != "ditto")


def test_champions_stats():
    bs = SPECIES["garchomp"]["bs"]
    assert calc_stats(bs, NOSP) == (183, 150, 115, 100, 105, 122)
    assert calc_stats(bs, PHYS)[1] == 200          # (130+32+20)*1.1
    assert calc_stats(bs, PHYS)[3] == 90           # 특공 하락 보정
    assert from_evs({"atk": 252, "spe": 252, "hp": 4}).sp == (1, 32, 0, 0, 0, 32)
    with pytest.raises(ValueError):
        Spread((32, 32, 32, 0, 0, 0))              # 합계 66 초과


# ---------- 시뮬레이터 ----------

def test_damage_formula_by_hand():
    """한카리아스(공격 200) 지진 → 무투자 메타그로스(방어 150): 손으로 계산한 값과 일치."""
    a = mon("garchomp", PHYS, ["earthquake"])
    d = mon("metagross", NOSP, ["bulletpunch"], ability="")
    base = (22 * 100 * 200 // calc_stats(SPECIES["metagross"]["bs"], NOSP)[2]) // 50 + 2
    expect = int(int(base * 100 // 100 * 1.5) * 2)
    assert damage(a, d, "earthquake", 100) == expect


def test_step_does_not_mutate_and_hits():
    a, b = mon("garchomp", moves=["earthquake"]), mon("metagross", BULK, ["bulletpunch"])
    s = State([a], [b])
    t = step(s, ("move", 0), ("move", 0), random.Random(1))
    assert s.mon(1).hp == b.max_hp and t.mon(1).hp < b.max_hp and t.turn == 2


def test_mega_evolution_once_per_team():
    a = mon("garchomp", moves=["earthquake"], item="garchompite")
    b = mon("charizard", moves=["flamethrower"], item="charizarditey")
    s = State([a, b], [mon("metagross", BULK)])
    t = step(s, ("move", 0), ("move", 0), Mean())
    assert t.mon(0).species == "garchompmega" and t.sides[0]["mega"]
    switch_in(t, 0, 1)
    t2 = step(t, ("move", 0), ("move", 0), Mean())
    assert t2.mon(0).species == "charizard"         # 두 번째 메가진화 불가


def test_intimidate_and_stealth_rock():
    s = State([mon("garchomp"), mon("charizard")], [mon("gyarados", ability="intimidate"), mon("metagross")])
    s.sides[0]["sr"] = True
    switch_in(s, 1, 0)
    assert s.mon(0).stages[0] == -1
    switch_in(s, 0, 1)
    zard = s.mon(0)
    assert zard.hp == zard.max_hp - zard.max_hp // 2   # 바위 4배: 1/2


def test_choice_scarf_lock_and_speed():
    a = mon("garchomp", JOLLY, ["earthquake", "outrage"], item="choicescarf")
    assert speed(a) == int(a.stats[5] * 1.5)
    s = State([a, mon("gardevoir", SPEC)], [mon("metagross", BULK)])
    t = step(s, ("move", 0), ("move", 0), Mean())
    assert [x for x in legal(t, 0) if x[0] == "move"] == [("move", 0)]


def test_protect_consecutive_fails_in_mean_mode():
    a = mon("garchomp", moves=["protect", "earthquake"])
    s = State([a], [mon("metagross", PHYS, ["bulletpunch"])])
    t = step(s, ("move", 0), ("move", 0), Mean())
    assert t.mon(0).hp == a.max_hp
    t2 = step(t, ("move", 0), ("move", 0), Mean())
    assert t2.mon(0).hp < a.max_hp


def test_sucker_punch_fails_against_status_move():
    k = mon("kingambit", moves=["suckerpunch"])
    g = mon("garchomp", moves=["swordsdance"])
    t = step(State([k], [g]), ("move", 0), ("move", 0), Mean())
    assert t.mon(1).hp == g.max_hp and t.mon(1).stages[0] == 2


def test_focus_sash_and_sitrus():
    g = mon("garchomp", moves=["earthquake"])
    gen = mon("gengar", NOSP, ["shadowball"], item="focussash")
    gen.ability = ""
    assert min(damage_rolls(g, gen, "earthquake")) >= gen.max_hp
    t = step(State([g], [gen]), ("move", 0), ("move", 0), Mean())
    assert t.mon(1).hp == 1 and t.mon(1).item == ""
    m = mon("metagross", BULK, ["bulletpunch"], item="sitrusberry")
    t = step(State([mon("garchomp", moves=["earthquake"])], [m]), ("move", 0), ("move", 0), Mean())
    assert t.mon(1).item == "" or t.mon(1).hp * 2 > t.mon(1).max_hp


def test_weather_and_absorb_abilities():
    zard = mon("charizard", SPEC, ["flamethrower"])
    target = mon("metagross", BULK, ["bulletpunch"])
    s = State([zard], [target])
    base = damage(zard, target, "flamethrower", 100, s=s, aside=0)
    s.field["weather"], s.field["wturns"] = "sun", 5
    assert damage(zard, target, "flamethrower", 100, s=s, aside=0) > base * 1.4
    ff = mon("heatran" if "heatran" in SPECIES else "arcanine", BULK, None, ability="flashfire")
    t = step(State([zard], [ff]), ("move", 0), ("move", 0), Mean())
    assert t.mon(1).hp == ff.max_hp or t.mon(1).vol.get("flashfire")


def test_levitate_and_knock_off():
    g = mon("garchomp", moves=["earthquake"])
    rot = mon("rotomwash", BULK, None, ability="levitate", item="leftovers")
    assert step(State([g], [rot]), ("move", 0), ("move", 0), Mean()).mon(1).hp >= rot.hp
    k = mon("kingambit", moves=["knockoff"])
    m1 = mon("metagross", BULK, ["bulletpunch"], item="leftovers")
    m2 = mon("metagross", BULK, ["bulletpunch"])
    assert damage(k, m1, "knockoff", 100) > damage(k, m2, "knockoff", 100) * 1.4
    t = step(State([k], [m1]), ("move", 0), ("move", 0), Mean())
    assert t.mon(1).item == ""


def test_uturn_switches_and_trick_room_order():
    from pokesage.dex import LEARNSETS
    att = next(s for s in PLAYABLE if "uturn" in LEARNSETS.get(s, []))
    a = mon(att, moves=["uturn"])
    s = State([a, mon("garchomp")], [mon("metagross", BULK)])
    t = step(s, ("move", 0), ("move", 0), Mean())
    assert t.active[0] == 1
    slow = mon("metagross", BULK, ["bulletpunch", "ironhead"])
    fast = mon("garchomp", JOLLY, ["earthquake"])
    s = State([slow], [fast])
    s.field["trickroom"] = 3
    ev = []
    step(s, ("move", 1), ("move", 0), Mean(), ev)
    used = [e for e in ev if e[0] == "used"]
    assert used[0][1] == 0                           # 트릭룸: 느린 쪽이 먼저


def test_multihit_rest_substitute():
    a = mon("garchomp", moves=["substitute", "rest", "earthquake"])
    s = State([a], [mon("metagross", BULK, ["willowisp"])])   # 느린 상대: 대타출동이 먼저
    t = step(s, ("move", 0), ("move", 0), Mean())
    assert t.mon(0).vol.get("sub") and t.mon(0).status == "없음"     # 대타출동이 상태이상을 막음
    t.mon(0).hp = 50
    t.mon(0).vol.pop("sub")
    t2 = step(t, ("move", 1), ("move", 0), Mean())
    assert t2.mon(0).status == "잠듦" and t2.mon(0).hp == t2.mon(0).max_hp


def test_winner_and_legal_after_faint():
    a, b = mon("garchomp", hp_frac=0), mon("gardevoir", SPEC)
    s = State([a, b], [mon("dragonite")])
    assert legal(s, 0) == [("switch", 1)]
    s.teams[1][0].hp = 0
    assert winner(s) == 0


def test_unsupported_lists_are_small():
    abil = {a for s in PLAYABLE for a in SPECIES[s]["abilities"]}
    assert len(unsupported("ability", abil)) / len(abil) < 0.35
    assert len(unsupported("item", ITEMS)) / len(ITEMS) < 0.2


# ---------- 세트 추론 ----------

def test_prior_is_distribution():
    for sp in PLAYABLE[:80]:
        assert abs(sum(prior(sp).values()) - 1) < 1e-9


def test_belief_learns_from_damage_and_order():
    truth = mon("garchomp", PHYS, ["earthquake"], item="lifeorb")
    me = mon("metagross", BULK, ["bulletpunch"])
    b = Belief("garchomp")
    for _ in range(2):
        dmg = damage(truth, me, "earthquake", 93)
        b.observe_taken("earthquake", 1.0, "없음", None, me, dmg / me.max_hp)
    assert b.marginal("item").get("lifeorb", 0) > 0.3 and "earthquake" in b.moves
    b2 = Belief("garchomp")
    fast = mon("greninja" if "greninja" in SPECIES else "dragapult", PRESETS["특수 스피드형 (특공·스피드 32, 겁쟁이)"])
    b2.observe_order(True, speed(fast), "없음", None)
    assert b2.marginal("item").get("choicescarf", 0) > 0.6


def test_belief_mega_reveal():
    b = Belief("garchomp")
    b.reveal_mega("garchompmega")
    m = b.mon(b.top(1)[0][1])
    assert m.species == "garchompmega" and m.item == "garchompite"


def test_make_worlds_probabilities():
    worlds = make_worlds([mon("garchomp")], 0, [OppMon(Belief("dragonite"), 1.0)], 0, 2, 3)
    assert len(worlds) == 3 and abs(sum(p for p, _ in worlds) - 1) < 1e-9 and worlds[0][1].unrevealed == [0, 2]


# ---------- 탐색 ----------

def test_solve_matching_pennies():
    x, q, v = solve([[[1, -1], [-1, 1]]], [1.0], iters=4000)
    assert abs(x[0] - 0.5) < 0.05 and abs(v) < 0.05


def test_search_takes_sure_ko():
    g = mon("garchomp", moves=["outrage", "earthquake", "swordsdance", "ironhead"])
    worlds = make_worlds([g], 0, [OppMon(Belief("dragonite"), 0.25)], 0, 0, 2)
    assert recommend(worlds, depth=2, samples=1)[0].action in (("move", 0), ("move", 3))


def test_search_avoids_immune_move():
    ex = mon("excadrill", moves=["earthquake", "ironhead", "rockslide", "swordsdance"])
    worlds = make_worlds([ex], 0, [OppMon(Belief("corviknight"), 1.0)], 0, 0, 2)
    assert recommend(worlds, depth=1, samples=1)[0].action != ("move", 0)


# ---------- 아레나 ----------

def test_random_team_rules():
    rng = random.Random(3)
    for _ in range(30):
        t = arena.random_team(rng, 6)
        items = [m.item for m in t if m.item != "other"]
        assert len(items) == len(set(items))
        assert sum(1 for m in t if ITEMS.get(m.item, {}).get("megaStone")) <= 1


def test_arena_smoke_and_determinism():
    r = arena.run_match(arena.make_agent("search", depth=1, samples=1, worlds=2),
                        arena.make_agent("random"), games=2, seed=0, verbose=False)
    assert r["games"] == 2 and 0 <= r["belief_post"] <= 1

    def once():
        rng = random.Random(5)
        t0, t1 = arena.random_team(rng), arena.random_team(rng)
        return arena.Game(t0, t1).play([arena.make_agent("maxdmg"), arena.make_agent("random")], rng)
    assert once() == once()
