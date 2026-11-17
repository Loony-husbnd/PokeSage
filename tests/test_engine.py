import subprocess
from pathlib import Path

from pokesage import data
from pokesage.state import BattleState, FoeMon, MyMon, MySet

GARCHOMP = MySet("Garchomp", "Rough Skin", "focussash", ["earthquake", "dragonclaw", "stoneedge", "protect"], "Jolly", {"hp": 2, "atk": 32, "spe": 32})
GYARADOS = MySet("Gyarados", "Intimidate", "leftovers", ["waterfall", "earthquake", "icefang", "dragondance"], "Adamant", {"hp": 32, "atk": 32, "def": 2})
PREVIEW = ["Tyranitar", "Dragonite", "Excadrill", "Gardevoir", "Kingambit", "Gyarados"]


def state(foe_hp=70):
    return BattleState(me=[MyMon(GARCHOMP, 100, active=True), MyMon(GYARADOS, 80)],
                       foe=[FoeMon("Dragonite", foe_hp, active=True, moves=["extremespeed"])], foe_preview=PREVIEW)


def test_validator_rejects_non_champions_items(eng):
    bad = {**GYARADOS.to_json(), "item": "assaultvest"}
    assert any("Assault Vest" in p for p in eng.validate([bad]))
    assert eng.validate([GARCHOMP.to_json()]) == []


def test_validator_rejects_unlearnable_move_and_sp(eng):
    bad = {**GARCHOMP.to_json(), "moves": ["earthquake", "triattack"]}
    assert any("can't learn" in p for p in eng.validate([bad]))
    over = {**GARCHOMP.to_json(), "evs": {"hp": 32, "atk": 32, "def": 32}}
    assert any("Stat Points" in p for p in eng.validate([over]))


def test_recommend_prefers_super_effective(eng):
    rec = eng.recommend(state().to_json(), worlds=40, seed=3)
    st = state()
    assert rec.results[0].n >= 30
    # 드래곤 타입 기술이 용/비행 상대에게 가장 좋아야 한다
    assert "드래곤크루" in st.label(rec.best.choice) or "지진" not in st.label(rec.best.choice)
    assert [r.value for r in rec.results] == sorted([r.value for r in rec.results], reverse=True)


def test_recommend_deterministic_for_seed(eng):
    a = eng.recommend(state().to_json(), worlds=20, seed=5)
    b = eng.recommend(state().to_json(), worlds=20, seed=5)
    assert [(r.choice, round(r.value, 6)) for r in a.results] == [(r.choice, round(r.value, 6)) for r in b.results]


def test_observation_filter_rejects_inconsistent_worlds(eng):
    """지난 턴 관측과 맞지 않는 세계는 걸러지고, 맞는 관측은 대부분 통과한다."""
    st = state(foe_hp=100)
    before = st.snapshot()
    base = {"before": before, "myChoice": "move 2", "foeMove": "extremespeed", "first": "foe"}
    # 신속이 먼저 나가고 드래곤크루가 상대 풀피를 55%로 만들었다: 어떤 세계에서도 불가능 (거의 확정 1타)
    bad = eng.recommend(st.to_json(), [{**base, "after": {"foeHp": 55}}], worlds=20, seed=1, tolerance=2)
    assert bad.relaxed > 0 and bad.accepted < 20
    # 드래곤크루로 쓰러졌다(0%)는 관측은 일치하는 세계를 찾아낸다
    good = eng.recommend(st.to_json(), [{**base, "after": {"foeHp": 0}}], worlds=20, seed=1, tolerance=2)
    assert good.accepted == 20 and good.relaxed == 0
    # 순서 관측도 쓰인다: 신속(+2)이 아니라 내가 먼저 움직였다는 관측은 불가능
    wrong_order = eng.recommend(st.to_json(), [{**base, "first": "me"}], worlds=20, seed=1)
    assert wrong_order.relaxed > 0


def test_stats_match_showdown(eng):
    """Python 능력치 공식이 Showdown 시뮬레이터의 실제 값과 같은지 교차 검증."""
    root = Path(__file__).resolve().parent.parent
    code = """
const {dex, Battle, SIM_FORMAT} = require(process.argv[1] + '/engine/common');
const set = {name:'g', species:'Garchomp', ability:'Rough Skin', item:'', moves:['earthquake'], nature:'Adamant', evs:{hp:2,atk:32,def:0,spa:0,spd:0,spe:7}, ivs:{hp:31,atk:31,def:31,spa:31,spd:31,spe:31}, level:50};
const b = new Battle({formatid: SIM_FORMAT, seed:[1,2,3,4], p1:{name:'a', team:[set]}, p2:{name:'b', team:[set]}});
b.choose('p1','default'); b.choose('p2','default');
const p = b.p1.pokemon[0];
console.log(JSON.stringify({hp:p.maxhp, atk:p.storedStats.atk, spe:p.storedStats.spe, def:p.storedStats.def}));
"""
    import json, os
    out = subprocess.run(["node", "-e", code, str(root)], capture_output=True, text=True, env={**os.environ, "POKESAGE_SHOWDOWN": str(eng.showdown)})
    sd = json.loads(out.stdout.strip().splitlines()[-1])
    assert sd["hp"] == data.calc_stat("garchomp", "hp", 2, "Adamant")
    assert sd["atk"] == data.calc_stat("garchomp", "atk", 32, "Adamant")
    assert sd["spe"] == data.calc_stat("garchomp", "spe", 7, "Adamant")
    assert sd["def"] == data.calc_stat("garchomp", "def", 0, "Adamant")
