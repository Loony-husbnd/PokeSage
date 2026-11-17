from pokesage.advisor import recommend
from pokesage.calc import damage_pct
from pokesage.cli import Form, run
from pokesage.dex import MOVES
from pokesage.model import Mon, calc_stat
from pokesage.typechart import effectiveness


def test_type_chart():
    assert effectiveness("ground", ("flying",)) == 0
    assert effectiveness("ice", ("dragon", "ground")) == 4
    assert effectiveness("fairy", ("dragon", "dark")) == 4


def test_stats_lv50():
    # 한카리아스 H108 무투자 Lv50 = 183, 공격 252 성격+ = 200
    assert calc_stat("한카리아스", "hp", ({}, {})) == 183
    assert calc_stat("한카리아스", "atk", ({"atk": 252}, {"atk": 1.1})) == 200


def test_immune_zero():
    me, opp = Mon("한카리아스"), Mon("갸라도스")
    assert max(damage_pct(me, opp, MOVES["지진"])) == 0


def test_super_effective_recommended():
    me, opp = Mon("한카리아스"), Mon("망나뇽")
    ranked = recommend(me, [], opp)
    assert ranked[0].name == "드래곤크루"


def test_immune_move_not_best():
    me, opp = Mon("몰드류"), Mon("갸라도스")
    assert recommend(me, [], opp)[0].name != "지진"


def test_burn_halves_physical():
    a = Mon("한카리아스")
    b = Mon("한카리아스")
    base = max(damage_pct(a, b, MOVES["스톤에지"]))
    a.status = "화상"
    assert max(damage_pct(a, b, MOVES["스톤에지"])) < base * 0.6


def test_cli_end_to_end(tmp_path):
    # 파티 2마리 -> 1턴 -> 종료
    answers = iter([
        "2",                    # 파티 크기
        "1", "", "", "",        # 한카리아스, 기본 노력치, 기본 기술, 도구 없음
        "12", "3", "", "",      # 가디안, 내구형, 기본 기술, 도구 없음
        "", "1", "",            # 상대 파티 크기 기본, 탐색 강도 빠름, 상대 성향 기본
        "", "", "", "",         # 선두 기본, HP 유지, 상태이상 기본, 랭크 유지
        "7", "", "", "",        # 상대 포켓몬 선택(갸라도스), HP 유지, 상태, 랭크
        "2",                    # 종료
    ])
    out = []
    log = run(Form(lambda _p: next(answers), out.append), save_dir=str(tmp_path))
    assert log and log[0].startswith("T1 |")
    assert list(tmp_path.glob("*.md"))
