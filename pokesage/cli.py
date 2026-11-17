"""객관식/입력칸 폼 방식의 대화형 CLI. 모든 질문은 번호 선택 또는 숫자 입력이다."""
from __future__ import annotations

import datetime as dt
import pathlib
from typing import Callable

from .advisor import Option, kibo_line
from .belief import Belief, OppMon, make_worlds
from .dex import ITEMS, MOVES, POKEMON
from .model import SPREADS, STATUS, STAT_KO, Mon
from .search import GREEDY, best_replacement, recommend
from .sim import BMon, damage_rolls, speed

# 탐색 강도: 이름 -> (깊이, 칸당 표본 수, 상대 세트 후보 수). 시간은 3대3 첫 턴 실측 기준.
LEVELS = {
    "빠름 (2턴 앞, 0.1초 안팎)": (2, 2, 3),
    "보통 (2턴 앞, 표본·세트 후보 증가, 1초 안팎)": (2, 6, 5),
    "정밀 (3턴 앞, 수 초)": (3, 4, 5),
    "최대 (4턴 앞, 수십 초)": (4, 1, 3),
}
# 상대 성향: 이름 -> 상대가 '뻔한 수'(최대 피해 기술)를 둘 것으로 보는 확률
STYLES = {
    f"정석형 (최대 피해 기술 위주, 권장 {GREEDY:g})": GREEDY,
    "심리전형 (교체·읽기 많음, 0.3)": 0.3,
    "최적 상대 가정 (균형 전략, 0)": 0.0,
}

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
        item = ITEMS[f.choose(f"{sp} 도구 (기타 = 계산에 영향 없는 도구)", list(ITEMS))]
        team.append(Mon(sp, spread, mv, item=item))
    return team


def edit_condition(f: Form, mon: Mon, who: str) -> None:
    mon.status = STATUS[f.choose(f"{who} 상태이상", list(STATUS), STATUS.index(mon.status))]
    if f.choose(f"{who} 랭크 변화", ["유지", "수정"]) == 1:
        keys = list(STAT_KO)
        for k in keys:
            mon.stages[k] = f.number(f"{who} {STAT_KO[k]} 랭크", -6, 6, mon.stages[k])


def to_bmon(mon: Mon) -> BMon:
    return BMon(mon.species, mon.spread_name, mon.moves, mon.item, mon.hp_pct / 100,
                mon.status, list(mon.stages.values()))


class OppRec:
    """상대 포켓몬 한 마리의 관측 상태와 세트 추론. 교체로 물러나도 유지된다."""

    def __init__(self, species: str):
        self.mon = Mon(species)
        self.belief = Belief(species)

    def view(self) -> OppMon:
        m = self.mon
        return OppMon(self.belief, m.hp_pct / 100, m.status, tuple(m.stages.values()))


def report_last_turn(f: Form, prev: dict, me: Mon, rec: OppRec, tol: float = 0.015) -> None:
    """지난 턴에 실제로 일어난 일을 입력받아 상대 세트 추론을 갱신한다."""
    if f.choose("지난 턴 결과 보고 (상대 세트 추론에 사용)", ["건너뛰기", "입력"]) == 0:
        return
    b, pm = rec.belief, prev["me"]
    mine = list(pm.moves) + ["교체 / 행동 못함"]
    i = f.choose(f"지난 턴 내 {pm.species}의 행동", mine)
    my_move = mine[i] if i < len(pm.moves) else None
    known = list(b.moveset())
    opts = known + ["목록에 없는 기술", "교체 / 행동 못함 / 모름"]
    j = f.choose(f"지난 턴 상대 {b.species}의 행동", opts, len(opts) - 1)
    opp_move = None
    if j < len(known):
        opp_move = known[j]
    elif j == len(known):
        pool = list(MOVES)
        opp_move = pool[f.choose("상대가 쓴 기술", pool)]
    if opp_move:
        b.reveal_move(opp_move)
    cond = (prev["opp_status"], prev["opp_stages"])
    if my_move and opp_move and MOVES[my_move][4] == MOVES[opp_move][4]:
        k = f.choose("누가 먼저 움직였습니까", ["모름", "내가 먼저", "상대가 먼저"])
        if k:
            b.observe_order(k == 2, speed(pm), *cond)
    q = "HP 변화가 기술 피해만으로 생겼습니까 (급소·반동·상태이상 피해·회복 없음, HP 정확 입력)"
    if f.choose(q, ["아니오 / 모름", "예"]) == 0:
        return
    dealt = prev["opp_hp"] - rec.mon.hp_pct
    if my_move and MOVES[my_move][1] != "Z" and dealt > 0:
        b.observe_dealt(pm, my_move, prev["opp_hp"] / 100, *cond, dealt / 100, tol)
    taken = prev["my_hp"] - me.hp_pct
    if opp_move and MOVES[opp_move][1] != "Z" and taken > 0 and me.species == pm.species:
        b.observe_taken(opp_move, prev["opp_hp"] / 100, *cond, pm, taken / 100, tol)


def describe(rec_, me_b: BMon, team: list[Mon], world) -> Option:
    """탐색 결과 한 줄을 사람이 읽을 요약으로 바꾼다. world는 가장 유력한 상대 세트의 상태."""
    kind, idx = rec_.action
    summary = f"선택 비중 {rec_.freq:.0%}, 기대 우세 {rec_.q:+.2f}"
    if kind == "switch":
        return Option("switch", team[idx].species, rec_.freq, summary)
    name = me_b.moves[idx]
    if MOVES[name][1] != "Z":
        foe = world.mon(1)
        rolls = damage_rolls(me_b, foe, name)
        lo, hi = (min(100, r * 100 // foe.max_hp) for r in (rolls[0], rolls[-1]))
        summary += f", 피해 {lo}~{hi}%"
        if rolls[0] >= foe.hp:
            summary += " (확정 1타)"
        elif rolls[-1] >= foe.hp:
            summary += " (난수 1타)"
        if MOVES[name][3] < 100:
            summary += f", 명중 {MOVES[name][3]}%"
    return Option("move", name, rec_.freq, summary)


def run(f: Form | None = None, save_dir: str | None = "kibo") -> list[str]:
    f = f or Form()
    f.out("PokeSage - 포챔스 턴별 최선수 추천 (싱글 배틀)")
    team = build_team(f)
    opp_size = f.number("상대 파티 크기", 1, 6, len(team))
    depth, samples, k = list(LEVELS.values())[f.choose("탐색 강도", list(LEVELS), 1)]
    greedy = list(STYLES.values())[f.choose("상대 성향", list(STYLES))]
    active = 0
    opps: dict[str, OppRec] = {}  # 지금까지 본 상대 포켓몬
    cur: str | None = None        # 상대 선두
    prev: dict | None = None      # 지난 턴 시작 시점의 스냅숏
    log: list[str] = []
    turn = 1
    while True:
        f.out(f"\n===== {turn}턴 =====")
        alive = [i for i, m in enumerate(team) if m.alive]
        if not alive:
            f.out("내 포켓몬이 모두 기절했습니다.")
            break
        if not team[active].alive:
            labels = [team[i].label() for i in alive]
            default = 0
            if cur is not None and opps[cur].mon.alive:
                seen = [r for r in opps.values() if r.mon.alive]
                worlds = make_worlds([to_bmon(m) for m in team], active, [r.view() for r in seen],
                                     seen.index(opps[cur]), max(0, opp_size - len(opps)), k)
                default = alive.index(best_replacement(worlds, greedy=greedy))
                labels[default] += f"  ← 추천 (상대 {cur} 기준)"
            active = alive[f.choose("내 선두 포켓몬 (기절한 포켓몬 교체)", labels, default)]
        else:
            labels = [f"{team[i].label()}{' (현재)' if i == active else ''}" for i in alive]
            active = alive[f.choose("내 선두 포켓몬", labels, alive.index(active))]
        me = team[active]
        me.hp_pct = f.hp(f"{me.species} 현재 HP", me.hp_pct)
        if not me.alive:
            f.out(f"{me.species} 기절 처리. 다음 포켓몬을 선택해 주십시오.")
            log.append(f"T{turn} | {me.species} 기절")
            prev = None
            continue
        edit_condition(f, me, "내")

        stayed = cur is not None
        if cur is None or f.choose("상대 선두 포켓몬", [f"유지 ({cur})", "다른 포켓몬 (교체됨)"]) == 1:
            stayed = False
            cur = pick_species(f, "상대 선두 포켓몬", cur)
            if cur not in opps:
                opps[cur] = OppRec(cur)
            opps[cur].mon.stages = {s: 0 for s in STAT_KO}
        rec = opps[cur]
        opp = rec.mon
        opp.hp_pct = f.hp(f"상대 {opp.species} 현재 HP", opp.hp_pct)
        if not opp.alive:
            f.out("상대 포켓몬이 기절했습니다. 새 상대를 선택해 주십시오.")
            log.append(f"T{turn} | 상대 {opp.species} 기절")
            cur = prev = None
            if len(opps) >= opp_size and not any(r.mon.alive for r in opps.values()):
                f.out("상대 포켓몬이 모두 기절했습니다.")
                break
            continue
        edit_condition(f, opp, "상대")
        if prev and stayed and prev["opp"] == cur:
            report_last_turn(f, prev, me, rec)

        # 상대 세트 후보별 세계를 만들어 탐색한다.
        seen = [r for r in opps.values() if r.mon.alive]
        worlds = make_worlds([to_bmon(m) for m in team], active, [r.view() for r in seen],
                             seen.index(rec), max(0, opp_size - len(opps)), k)
        me_b = worlds[0][1].mon(0)
        ranked = [describe(r, me_b, team, worlds[0][1]) for r in recommend(worlds, depth, samples, greedy=greedy)]
        best = ranked[0]
        guess = " · ".join(f"{h.spread.split(' (')[0]}/{h.item} {p:.0%}" for p, h in rec.belief.top(3))
        f.out(f"\n상대 {cur} 추정 세트: {guess}")
        f.out("--- 추천 ---")
        f.out(f"▶ {'교체' if best.kind == 'switch' else '기술'}: {best.name}  [{best.summary}]")
        for o in ranked[1:4]:
            f.out(f"   · {'교체' if o.kind == 'switch' else '기술'} {o.name}  [{o.summary}]")
        line = kibo_line(turn, me, opp, best)
        log.append(line)
        f.out("\n기보: " + line)
        prev = {"me": to_bmon(me), "my_hp": me.hp_pct, "opp": cur, "opp_hp": opp.hp_pct,
                "opp_status": opp.status, "opp_stages": list(opp.stages.values())}

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
