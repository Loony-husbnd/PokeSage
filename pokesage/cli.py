"""객관식/입력칸 폼 방식의 대화형 CLI. 모든 질문은 번호 선택 또는 숫자 입력이다."""
from __future__ import annotations

import datetime as dt
import pathlib
from typing import Callable

from .advisor import kibo_line, recommend
from .dex import MOVES, POKEMON
from .model import SPREADS, STATUS, STAT_KO, Mon

Ask = Callable[[str], str]


class Form:
    def __init__(self, ask: Ask = input, out: Callable[[str], None] = print):
        self.ask, self.out = ask, out

    def choose(self, title: str, options: list[str], default: int = 0) -> int:
        self.out(f"\n[{title}]")
        for i, o in enumerate(options, 1):
            self.out(f"  {i}. {o}" + ("  (기본)" if i - 1 == default else ""))
        while True:
            raw = self.ask("번호> ").strip()
            if raw == "":
                return default
            if raw.isdigit() and 1 <= int(raw) <= len(options):
                return int(raw) - 1
            self.out("  목록의 번호를 입력해 주십시오.")

    def number(self, title: str, lo: int, hi: int, default: int) -> int:
        while True:
            raw = self.ask(f"{title} ({lo}~{hi}, 기본 {default})> ").strip()
            if raw == "":
                return default
            if raw.lstrip("-").isdigit() and lo <= int(raw) <= hi:
                return int(raw)
            self.out("  범위 내 숫자를 입력해 주십시오.")

    def hp(self, title: str, default: int) -> int:
        opts = [f"유지 ({default}%)", "100%", "75%", "50%", "25%", "10%", "0% (기절)", "직접 입력"]
        i = self.choose(title, opts)
        if i == 0:
            return default
        if i == len(opts) - 1:
            return self.number(title, 0, 100, default)
        return int(opts[i].split("%")[0])


def pick_species(f: Form, title: str, default: str | None = None) -> str:
    names = list(POKEMON)
    d = names.index(default) if default in names else 0
    return names[f.choose(title, names, d)]


def build_team(f: Form) -> list[Mon]:
    n = f.number("내 파티 크기", 1, 6, 3)
    team = []
    for k in range(1, n + 1):
        sp = pick_species(f, f"내 포켓몬 {k}")
        spread = list(SPREADS)[f.choose(f"{sp} 노력치 유형", list(SPREADS))]
        mv = list(POKEMON[sp][2])
        if f.choose(f"{sp} 기술", [f"기본: {', '.join(mv)}", "직접 선택"]) == 1:
            pool = list(MOVES)
            for i, m in enumerate(pool, 1):
                f.out(f"  {i}. {m}")
            while True:
                raw = f.ask("기술 번호 1~4개를 쉼표로> ")
                try:
                    idx = [int(x) for x in raw.split(",")]
                    if 1 <= len(idx) <= 4 and all(1 <= i <= len(pool) for i in idx):
                        mv = [pool[i - 1] for i in idx]
                        break
                except ValueError:
                    pass
                f.out("  다시 입력해 주십시오.")
        team.append(Mon(sp, spread, mv))
    return team


def edit_condition(f: Form, mon: Mon, who: str) -> None:
    mon.status = STATUS[f.choose(f"{who} 상태이상", list(STATUS), STATUS.index(mon.status))]
    if f.choose(f"{who} 랭크 변화", ["유지", "수정"]) == 1:
        keys = list(STAT_KO)
        for k in keys:
            mon.stages[k] = f.number(f"{who} {STAT_KO[k]} 랭크", -6, 6, mon.stages[k])


def run(f: Form | None = None, save_dir: str | None = "kibo") -> list[str]:
    f = f or Form()
    f.out("PokeSage - 포챔스 턴별 최선수 추천 (싱글 배틀)")
    team = build_team(f)
    active = 0
    opp: Mon | None = None
    log: list[str] = []
    turn = 1
    while True:
        f.out(f"\n===== {turn}턴 =====")
        alive = [i for i, m in enumerate(team) if m.alive]
        if not alive:
            f.out("내 포켓몬이 모두 기절했습니다.")
            break
        if not team[active].alive:
            active = alive[f.choose("내 선두 포켓몬 (기절한 포켓몬 교체)", [team[i].label() for i in alive])]
        else:
            labels = [f"{team[i].label()}{' (현재)' if i == active else ''}" for i in alive]
            active = alive[f.choose("내 선두 포켓몬", labels, alive.index(active))]
        me = team[active]
        me.hp_pct = f.hp(f"{me.species} 현재 HP", me.hp_pct)
        if not me.alive:
            f.out(f"{me.species} 기절 처리. 다음 포켓몬을 선택해 주십시오.")
            log.append(f"T{turn} | {me.species} 기절")
            continue
        edit_condition(f, me, "내")

        if opp is None or f.choose("상대 선두 포켓몬", [f"유지 ({opp.species})", "다른 포켓몬 (교체됨)"]) == 1:
            opp = Mon(pick_species(f, "상대 선두 포켓몬", opp.species if opp else None))
        opp.hp_pct = f.hp(f"상대 {opp.species} 현재 HP", opp.hp_pct)
        if not opp.alive:
            f.out("상대 포켓몬이 기절했습니다. 새 상대를 선택해 주십시오.")
            log.append(f"T{turn} | 상대 {opp.species} 기절")
            opp = None
            continue
        edit_condition(f, opp, "상대")

        bench = [m for i, m in enumerate(team) if i != active]
        ranked = recommend(me, bench, opp)
        best = ranked[0]
        f.out("\n--- 추천 ---")
        f.out(f"▶ {'교체' if best.kind == 'switch' else '기술'}: {best.name}  [{best.summary}]")
        for o in ranked[1:4]:
            f.out(f"   · {'교체' if o.kind == 'switch' else '기술'} {o.name}  [{o.summary}]")
        line = kibo_line(turn, me, opp, best)
        log.append(line)
        f.out("\n기보: " + line)

        if f.choose("다음", ["다음 턴 진행", "종료"]) == 1:
            break
        turn += 1

    if save_dir and log:
        p = pathlib.Path(save_dir)
        p.mkdir(parents=True, exist_ok=True)
        path = p / f"{dt.datetime.now():%Y%m%d_%H%M%S}.md"
        path.write_text("# 기보\n\n" + "\n".join(f"- {l}" for l in log) + "\n", encoding="utf-8")
        f.out(f"기보 저장: {path}")
    return log
