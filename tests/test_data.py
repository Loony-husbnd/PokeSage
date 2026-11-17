from pokesage import data


def test_champions_item_availability():
    it = data.items()
    assert "assaultvest" not in it            # 포챔스에 없는 도구
    assert "choiceband" not in it
    for ok in ("choicescarf", "focussash", "leftovers", "lifeorb", "sitrusberry"):
        assert ok in it


def test_learnset_filters_illegal_moves():
    sp = data.species()
    assert "earthquake" not in sp["kingambit"]["moves"]
    assert "earthquake" in sp["garchomp"]["moves"]


def test_restricted_and_mythical_excluded():
    assert "mewtwo" not in data.species()
    assert "garchomp" in data.species()


def test_mega_data():
    megas = data.species()["garchomp"]["megas"]
    assert any(m["item"] == "garchompite" for m in megas)
    # 메가스톤은 해당 종에게만 보인다
    assert "garchompite" in data.legal_items("garchomp")
    assert "charizarditex" not in data.legal_items("garchomp")


def test_stat_formula_is_stat_points():
    # Garchomp 공격 종족값 130, SP 32, 성격 보정 ↑ => (130+32+20)*1.1 = 200
    assert data.calc_stat("garchomp", "atk", 32, "Adamant") == 200
    assert data.calc_stat("garchomp", "hp", 2, "Jolly") == 108 + 2 + 75


def test_sp_limits():
    assert data.check_sp({"hp": 2, "atk": 32, "spe": 32}) == []
    assert data.check_sp({"hp": 32, "atk": 32, "def": 32})            # 합계 96 > 66
    assert data.check_sp({"atk": 33})                                  # 스탯당 최대 32


def test_korean_names():
    assert data.ko("species", "garchomp") == "한카리아스"
    assert data.ko("moves", "earthquake") == "지진"
