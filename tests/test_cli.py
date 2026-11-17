from pokesage import cli, data

TEAM = [
    ("garchomp", "focussash", ["earthquake", "dragonclaw", "stoneedge", "protect"]),
    ("gyarados", "leftovers", ["waterfall", "earthquake", "icefang", "dragondance"]),
    ("dragonite", "sitrusberry", ["extremespeed", "dragonclaw", "earthquake", "protect"]),
    ("tyranitar", "lifeorb", ["stoneedge", "crunch", "earthquake", "protect"]),
    ("excadrill", "choicescarf", ["earthquake", "ironhead", "swordsdance", "protect"]),
    ("gardevoir", "lumberry", ["moonblast", "psychic", "shadowball", "protect"]),
]
PREVIEW = ["dragonite", "tyranitar", "excadrill", "gardevoir", "kingambit", "gyarados"]


class Scripted(cli.Form):
    """제목에 따라 정해진 답을 돌려주는 폼 (실제 입력 흐름 전체를 시험한다)."""
    def __init__(self):
        super().__init__(ask=lambda _p: "", out=self.lines.append if hasattr(self, "lines") else (lambda s: None))
        self.lines, self.mon, self.turns, self.titles = [], -1, 0, []
        self.out = self.lines.append

    def search(self, title, names, pinned=None):
        self.titles.append(title)
        if title.startswith("내 포켓몬"): self.mon += 1; return TEAM[self.mon][0]
        if title.startswith("도구"): return TEAM[self.mon][1]
        if title.startswith("기술"): return TEAM[self.mon][2][int(title.split()[1][0]) - 1]
        if title.startswith("상대 팀 미리보기"): return PREVIEW[int(title.split()[-1].split("/")[0]) - 1]
        if title == "상대 기술": return "extremespeed"
        raise AssertionError(title)

    def choose(self, title, options, default=0):
        self.titles.append(title)
        if title.startswith("상대 선두"): return next(i for i, o in enumerate(options) if "망나뇽" in o)
        if title == "다음":
            self.turns += 1
            return 0 if self.turns < 2 else 1
        if title == "먼저 움직인 쪽": return 2
        if title == "상대가 한 행동": return 0
        if title == "팀 저장": return 0
        return default

    def multi(self, title, options):
        return [0, 1, 2] if title.startswith("이번 배틀 선출") else []

    def hp(self, title, default):
        return 60 if "상대" in title else 80


def test_full_flow(eng, tmp_path):
    f = Scripted()
    log = cli.run(f, eng, worlds=30, save_dir=str(tmp_path / "kibo"), team_dir=str(tmp_path / "teams"))
    assert len(log) == 2
    assert log[0].startswith("T1 |") and "추천" in log[0] and "실제" in log[0]
    assert "승률" in "\n".join(f.lines)                      # 추천 표
    assert "관측과 일치" in "\n".join(f.lines)
    assert list((tmp_path / "kibo").glob("*.md"))
    # 2턴째에는 지난 턴 관측(상대 선공, 내 HP 80·상대 HP 60)이 히스토리로 들어간다
    assert "상대 망나뇽" in log[1]


def test_team_validation_blocks_illegal_item(eng):
    f = Scripted()
    team = [cli.MySet(data.species()[s]["name"], list(data.species()[s]["abilities"].values())[0], i, m, "Adamant", {"hp": 2, "atk": 32, "spe": 32})
            for s, i, m in TEAM]
    assert eng.validate(cli.team_to_json(team)) == []
    team[1].item = "assaultvest"
    assert eng.validate(cli.team_to_json(team))
