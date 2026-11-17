"""대화형 CLI 종단 테스트: 자동 응답으로 팀 구성 → 미리보기 → 선출 → 몇 턴 진행 → 저장."""
import json

from pokesage.cli import Form, run
from pokesage.dex import SPECIES_INDEX


def feed(*answers):
    it = iter(answers)
    return lambda _prompt: next(it)


class Bot:
    """이름 질문에는 준비된 이름을, 나머지 질문에는 기본값(Enter)을 답한다. N턴 뒤 종료한다."""

    def __init__(self, names, turns=3):
        self.names, self.turns, self.out = list(names), turns, []

    def ask(self, prompt: str) -> str:
        if prompt.endswith("이름> "):
            return self.names.pop(0) if self.names else ""
        title = next((l.strip() for l in reversed(self.out) if l.strip().startswith("[")), "")
        seen_turns = sum(1 for l in self.out if l.strip().startswith("===== "))
        if title == "[다음]" and (seen_turns >= self.turns or "프로그램 종료" in "".join(self.out[-3:])):
            return "2"
        return ""


def test_name_exact_match_confirms_immediately():
    out = []
    f = Form(feed("한카리아스"), out.append)
    assert f.name("species", "테스트", SPECIES_INDEX) == "garchomp"
    assert any("확정" in l for l in out) and not any(l.strip().startswith("[") for l in out)


def test_name_fuzzy_and_chosung():
    out = []
    f = Form(feed("ㅎㅋㄹㅇㅅ", ""), out.append)
    assert f.name("species", "테스트", SPECIES_INDEX) == "garchomp"
    f = Form(feed("한까리아스", "1"), out.append)
    assert f.name("species", "테스트", SPECIES_INDEX) == "garchomp"


def test_full_battle_flow(tmp_path):
    team = ["한카리아스", "가디안", "메타그로스", "갸라도스", "리자몽", "킬가르도"]
    opp = ["망나뇽", "팬텀", "마기라스", "개굴닌자", "아머까오", "몰드류"]
    bot = Bot(team + opp, turns=3)
    log = run(Form(bot.ask, bot.out.append), save_dir=str(tmp_path / "kibo"), team_dir=str(tmp_path / "teams"))
    text = "\n".join(bot.out)
    assert "선출 추천" in text and "--- 추천 ---" in text
    assert log and log[0].startswith("T1 |")
    saved = json.loads((tmp_path / "teams" / "my_team.json").read_text(encoding="utf-8"))
    assert len(saved["team"]) == 6
    assert list((tmp_path / "kibo").glob("*.md"))
    # 저장한 팀을 다시 불러와 대전
    bot2 = Bot(opp, turns=1)
    log2 = run(Form(bot2.ask, bot2.out.append), save_dir=None, team_dir=str(tmp_path / "teams"))
    assert "불러오기: my_team" in "\n".join(bot2.out) and log2
