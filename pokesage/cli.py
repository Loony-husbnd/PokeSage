"""객관식/입력칸 폼 방식 CLI. 팀 설정 → 매 턴 상태 입력 → 시뮬레이션 추천 → 결과 입력(다음 턴 추정에 사용)."""
from __future__ import annotations

import datetime as dt
import json
import pathlib
from typing import Callable

from . import data
from .data import NATURES, STAT_KO, STATUS_KO, STATUSES, toid
from .engine import Engine, EngineError, Recommendation
from .state import BattleState, FoeMon, MyMon, MySet

Ask = Callable[[str], str]

SPREAD_PRESETS = {
    "물리 공격형 (공격32·스피드32·HP2)": {"hp": 2, "atk": 32, "spe": 32},
    "특수 공격형 (특공32·스피드32·HP2)": {"hp": 2, "spa": 32, "spe": 32},
    "물리 내구형 (HP32·공격32·방어2)": {"hp": 32, "atk": 32, "def": 2},
    "특수 내구형 (HP32·특공32·특방2)": {"hp": 32, "spa": 32, "spd": 2},
    "방어 내구형 (HP32·방어17·특방17)": {"hp": 32, "def": 17, "spd": 17},
}
WEATHER = [("없음", None), ("쾌청", "sunnyday"), ("비", "raindance"), ("모래바람", "sandstorm"), ("설경", "snowscape")]
TERRAIN = [("없음", None), ("일렉트릭필드", "electricterrain"), ("그래스필드", "grassyterrain"), ("미스트필드", "mistyterrain"), ("사이코필드", "psychicterrain")]
SIDE_CONDS = [("스텔스록", "stealthrock"), ("압정뿌리기 1겹", "spikes"), ("압정뿌리기 2겹", "spikes:2"), ("압정뿌리기 3겹", "spikes:3"),
              ("독압정", "toxicspikes"), ("끈적끈적네트", "stickyweb"), ("리플렉터", "reflect"), ("빛의장막", "lightscreen"),
              ("오로라베일", "auroraveil"), ("순풍", "tailwind")]


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

    def multi(self, title: str, options: list[str]) -> list[int]:
        self.out(f"\n[{title}] (쉼표로 여러 개, 비우면 없음)")
        for i, o in enumerate(options, 1):
            self.out(f"  {i}. {o}")
        while True:
            raw = self.ask("번호들> ").strip()
            if not raw:
                return []
            try:
                idx = [int(x) - 1 for x in raw.replace(" ", "").split(",")]
                if all(0 <= i < len(options) for i in idx):
                    return idx
            except ValueError:
                pass
            self.out("  목록의 번호를 쉼표로 구분해 입력해 주십시오.")

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

    def search(self, title: str, names: dict[str, str], pinned: list[str] | None = None) -> str:
        """names: id -> 표시 이름(한글). 이름 일부를 입력해 후보를 좁힌 뒤 번호로 고른다."""
        pinned = [p for p in (pinned or []) if p in names]
        while True:
            self.out(f"\n[{title}] 이름 일부를 입력하십시오 (한글/영문, 비우면 {'자주 쓰는 항목' if pinned else '전체'} 표시)")
            q = self.ask("검색> ").strip().lower()
            hits = [k for k in names if q and (q in names[k].lower() or q in k)] if q else (pinned or list(names))
            if not hits:
                self.out("  일치하는 항목이 없습니다.")
                continue
            if len(hits) > 15:
                self.out(f"  {len(hits)}개가 일치합니다. 더 구체적으로 입력해 주십시오.")
                continue
            return hits[self.choose(title, [f"{names[k]} ({k})" for k in hits])]


# ───────────────────────── 팀 설정 ─────────────────────────

def species_names() -> dict[str, str]:
    return {k: data.ko("species", k) for k in data.species()}


def build_mon(f: Form) -> MySet:
    sid = f.search("내 포켓몬", species_names())
    sp = data.species()[sid]
    abil = list(dict.fromkeys(sp["abilities"].values()))
    ability = abil[f.choose(f"{data.ko('species', sid)} 특성", [data.ko("abilities", a) for a in abil])]
    own_stones = [m["item"] for m in sp["megas"]]
    common = ["leftovers", "sitrusberry", "lifeorb", "focussash", "choicescarf", "lumberry"] + own_stones
    item = f.search("도구", {k: data.ko("items", k) for k in data.legal_items(sid)}, pinned=common)
    pool = {k: data.ko("moves", k) for k in sp["moves"]}
    moves: list[str] = []
    while len(moves) < 4:
        mv = f.search(f"기술 {len(moves) + 1}/4", {k: v for k, v in pool.items() if k not in moves})
        moves.append(mv)
    presets = list(SPREAD_PRESETS) + ["직접 입력"]
    pi = f.choose("스탯 포인트 (합계 66, 스탯당 최대 32)", presets)
    if pi < len(SPREAD_PRESETS):
        evs = dict(SPREAD_PRESETS[presets[pi]])
    else:
        while True:
            evs = {k: f.number(f"{STAT_KO[k]} 포인트", 0, 32, 0) for k in data.STATS}
            probs = data.check_sp(evs)
            if not probs:
                break
            f.out("  " + " / ".join(probs))
    plus_names = [f"{data.ko('natures', n)} ({'무보정' if NATURES[n][0] is None else '↑' + STAT_KO[NATURES[n][0]] + ' ↓' + STAT_KO[NATURES[n][1]]})" for n in NATURES]
    nature = list(NATURES)[f.choose("성격", plus_names, list(NATURES).index("Adamant"))]
    return MySet(sp["name"], next(v for v in sp["abilities"].values() if toid(v) == toid(ability)), item, moves, nature, evs)


def team_to_json(team: list[MySet]) -> list[dict]:
    return [m.to_json() for m in team]


def team_from_json(rows: list[dict]) -> list[MySet]:
    return [MySet(r["species"], r["ability"], r["item"], r["moves"], r.get("nature", "Hardy"), r.get("evs", {})) for r in rows]


def build_team(f: Form, eng: Engine, team_dir: str = "teams") -> list[MySet]:
    p = pathlib.Path(team_dir)
    team: list[MySet] = []
    while True:
        while len(team) < 6:
            f.out(f"\n=== 내 포켓몬 {len(team) + 1}/6 ===")
            team.append(build_mon(f))
        probs = eng.validate(team_to_json(team))
        if not probs:
            break
        f.out("\n팀이 현재 규정(Reg M-C)에 맞지 않습니다:")
        for q in probs:
            f.out("  - " + q)
        bad = f.choose("어떻게 할까요?", ["문제 있는 포켓몬을 다시 입력 (번호 지정)", "전체 다시 입력"])
        if bad == 1:
            team = []
        else:
            i = f.choose("다시 입력할 포켓몬", [data.ko("species", m.species) for m in team])
            team[i] = build_mon(f)
    if f.choose("팀 저장", ["저장하지 않음", "저장"]) == 1:
        name = f.ask("팀 이름> ").strip() or dt.datetime.now().strftime("team_%Y%m%d_%H%M%S")
        p.mkdir(exist_ok=True)
        (p / f"{name}.json").write_text(json.dumps(team_to_json(team), ensure_ascii=False, indent=1), encoding="utf-8")
    return team


def load_or_build_team(f: Form, eng: Engine, team_dir: str = "teams") -> list[MySet]:
    p = pathlib.Path(team_dir)
    saved = sorted(p.glob("*.json")) if p.exists() else []
    if saved:
        i = f.choose("내 팀", ["새로 만들기"] + [f"불러오기: {s.stem}" for s in saved])
        if i > 0:
            team = team_from_json(json.loads(saved[i - 1].read_text(encoding="utf-8")))
            probs = eng.validate(team_to_json(team))
            if probs:
                f.out("저장된 팀이 현재 규정에 맞지 않습니다 (규정이 바뀌었을 수 있습니다):")
                for q in probs:
                    f.out("  - " + q)
            else:
                return team
    return build_team(f, eng, team_dir)


# ───────────────────────── 배틀 ─────────────────────────

def edit_condition(f: Form, mon, who: str) -> None:
    mon.status = STATUSES[f.choose(f"{who} 상태이상", [STATUS_KO[s] for s in STATUSES], STATUSES.index(mon.status))]
    if f.choose(f"{who} 랭크 변화", ["유지", "수정"]) == 1:
        for k in ("atk", "def", "spa", "spd", "spe"):
            mon.boosts[k] = f.number(f"{who} {STAT_KO[k]} 랭크", -6, 6, mon.boosts.get(k, 0))


def edit_field(f: Form, st: BattleState) -> None:
    if f.choose("필드·사이드 상태", ["유지", "수정"]) == 0:
        return
    fld: dict = {}
    w = f.choose("날씨", [n for n, _ in WEATHER])
    if WEATHER[w][1]: fld["weather"] = WEATHER[w][1]
    t = f.choose("필드", [n for n, _ in TERRAIN])
    if TERRAIN[t][1]: fld["terrain"] = TERRAIN[t][1]
    if f.choose("트릭룸", ["없음", "있음"]) == 1: fld["pseudo"] = ["trickroom"]
    fld["me"] = [SIDE_CONDS[i][1] for i in f.multi("내 쪽 상태", [n for n, _ in SIDE_CONDS])]
    fld["foe"] = [SIDE_CONDS[i][1] for i in f.multi("상대 쪽 상태", [n for n, _ in SIDE_CONDS])]
    st.field = fld


def foe_by_species(st: BattleState, sid: str) -> FoeMon:
    base = toid(data.species()[sid]["baseSpecies"]) if sid in data.species() else sid
    for m in st.foe:
        if toid(data.species()[toid(m.species)]["baseSpecies"]) == base:
            return m
    m = FoeMon(data.species()[sid]["name"])
    st.foe.append(m)
    return m


def show(f: Form, st: BattleState, rec: Recommendation, worlds_req: int) -> None:
    f.out("\n─── 추천 (시뮬레이션 승률) ───")
    for i, r in enumerate(rec.results[:6]):
        lo, hi = r.interval
        f.out(f"{'▶' if i == 0 else ' '} {i + 1}. {st.label(r.choice):<22} 승률 {r.value * 100:5.1f}%  (95% {lo * 100:.0f}~{hi * 100:.0f}%, {r.n}판)")
    f.out(f"  세계 {rec.worlds}개, 관측과 일치 {rec.accepted}개" + (f", 불일치 {rec.relaxed}개(그대로 사용)" if rec.relaxed else ""))
    if len(rec.results) > 1:
        a, c = rec.results[0], rec.results[1]
        if a.interval[0] < c.interval[1]:
            f.out("  ※ 1·2순위의 승률 구간이 겹칩니다. 사실상 비슷한 수이며, 판 수(--worlds)를 늘리면 순위가 안정됩니다.")
    f.out("  ※ 승률은 '추정한 상대(세계)'와 휴리스틱 상대 정책을 가정한 값이라 절대 수치보다 행동 간 상대 비교로 보십시오.")
    top = st.label(rec.best.choice)
    if any(top == data.ko("moves", m) for m in ("protect", "detect", "substitute")):
        f.out("  ※ 방어·대리 같은 '한 턴을 쉬는' 행동은 시뮬레이션이 유리하게 평가하는 경향이 있습니다. 공격 행동과 차이가 작다면 공격을 우선 검토하십시오.")


def update_after_turn(f: Form, st: BattleState, h: dict) -> tuple[MyMon, FoeMon]:
    """지난 턴 결과(HP·교체·기절)를 입력받아 상태를 갱신하고, 지난 턴 관측(h['after'])을 채운다."""
    after: dict = {}
    alive = [i for i, m in enumerate(st.me) if m.hp > 0 and not m.fainted]
    cur = next((k for k, i in enumerate(alive) if st.me[i].active), 0)
    k = f.choose("내 선두 (교체했다면 변경)", [f"{st.me[i].name} {st.me[i].hp}%" for i in alive], cur)
    for m in st.me: m.active = False
    me_a = st.me[alive[k]]; me_a.active = True
    me_a.hp = f.hp(f"{me_a.name} 현재 HP", me_a.hp)
    if toid(me_a.set.species) == h["_me"]:
        after["meHp"] = me_a.hp
    if me_a.hp <= 0:
        me_a.fainted = True; me_a.active = False
        rest = [m for m in st.me if m.hp > 0 and not m.fainted]
        if rest:
            me_a = rest[f.choose("내 다음 선두", [m.name for m in rest])]; me_a.active = True
    prev = next((m for m in st.foe if m.active), None)
    di = next((i for i, p in enumerate(st.foe_preview) if prev and toid(p) == toid(prev.species)), 0)
    for m in st.foe: m.active = False
    foe_a = foe_by_species(st, toid(st.foe_preview[f.choose("상대 선두", [data.ko("species", toid(p)) for p in st.foe_preview], di)])); foe_a.active = True
    foe_a.hp = f.hp(f"상대 {foe_a.name} 현재 HP", foe_a.hp)
    if toid(foe_a.species) == h["_foe"]:
        after["foeHp"] = foe_a.hp
    if foe_a.hp <= 0:
        foe_a.active = False
        left = [p for p in st.foe_preview if not any(toid(p) == toid(m.species) and m.hp <= 0 for m in st.foe)]
        if left:
            foe_a = foe_by_species(st, toid(left[f.choose("상대 다음 포켓몬", [data.ko("species", toid(p)) for p in left])])); foe_a.active = True
            foe_a.hp = f.hp(f"상대 {foe_a.name} 현재 HP", foe_a.hp)
    h["after"] = after
    return me_a, foe_a


def ask_foe_action(f: Form, foe_a: FoeMon) -> tuple[str | None, bool]:
    sp = data.species()[toid(foe_a.species)]
    opts = [data.ko("moves", m) for m in foe_a.moves] + ["다른 기술 (검색)", "교체함", "행동 못함/모름"]
    k = f.choose("상대가 한 행동", opts, len(opts) - 1)
    if k < len(foe_a.moves):
        return foe_a.moves[k], False
    if k == len(foe_a.moves):
        mv = f.search("상대 기술", {m: data.ko("moves", m) for m in sp["moves"]})
        if mv not in foe_a.moves: foe_a.moves.append(mv)
        return mv, False
    return None, k == len(foe_a.moves) + 1


def ask_reveal(f: Form, foe_a: FoeMon) -> None:
    sp = data.species()[toid(foe_a.species)]
    rv = f.choose("상대에 대해 새로 드러난 정보", ["없음", "특성 공개", "도구 공개", "도구 소모됨", "메가진화"])
    if rv == 1:
        ab = list(dict.fromkeys(sp["abilities"].values())); foe_a.ability = ab[f.choose("상대 특성", [data.ko("abilities", a) for a in ab])]
    elif rv == 2:
        foe_a.item = f.search("상대 도구", {k: data.ko("items", k) for k in data.legal_items(foe_a.species)}, pinned=["leftovers", "sitrusberry", "lifeorb", "focussash", "choicescarf"])
    elif rv == 3:
        foe_a.item_gone = True
    elif rv == 4 and sp["megas"]:
        mg = sp["megas"][f.choose("메가 폼", [data.ko("species", m["id"]) for m in sp["megas"]])]
        foe_a.megaed, foe_a.mega_form, foe_a.item = True, mg["forme"], mg["item"]


def run(f: Form | None = None, eng: Engine | None = None, worlds: int = 300, save_dir: str | None = "kibo", team_dir: str = "teams") -> list[str]:
    f = f or Form()
    own = eng is None
    eng = eng or Engine()
    log: list[str] = []
    try:
        f.out("PokeSage - 포챔스 턴별 최선수 추천 (싱글, Reg M-C, Showdown 시뮬레이션)")
        team = load_or_build_team(f, eng, team_dir)
        picks = f.multi("이번 배틀 선출 3마리", [data.ko("species", m.species) for m in team])
        while len(picks) != 3:
            f.out("  정확히 3마리를 선택해 주십시오.")
            picks = f.multi("이번 배틀 선출 3마리", [data.ko("species", m.species) for m in team])
        names = species_names()
        preview: list[str] = []
        while len(preview) < 6:
            preview.append(f.search(f"상대 팀 미리보기 {len(preview) + 1}/6", {k: v for k, v in names.items() if k not in preview}))
        st = BattleState(me=[MyMon(team[i]) for i in picks], foe_preview=[data.species()[p]["name"] for p in preview])
        st.me[f.choose("내 선두", [m.name for m in st.me])].active = True
        history: list[dict] = []
        while True:
            f.out(f"\n===== {st.turn}턴 =====")
            if history:
                me_a, foe_a = update_after_turn(f, st, history[-1])
                if not any(m.hp > 0 and not m.fainted for m in st.me):
                    f.out("내 포켓몬이 모두 기절했습니다."); break
            else:
                foe_a = foe_by_species(st, toid(st.foe_preview[f.choose("상대 선두", [data.ko("species", toid(p)) for p in st.foe_preview])]))
                foe_a.active = True; me_a = st.my_active()
            edit_condition(f, me_a, "내"); edit_condition(f, foe_a, "상대"); edit_field(f, st)
            if me_a.set.item.startswith("choice"):
                lm = f.choose("내 선두가 마지막에 쓴 기술 (구애 고정)", ["없음/교체 직후"] + [data.ko("moves", m) for m in me_a.set.moves])
                me_a.last_move = me_a.set.moves[lm - 1] if lm else None

            f.out("\n시뮬레이션 중...")
            public = [{k: v for k, v in h.items() if not k.startswith("_")} for h in history]
            try:
                rec = eng.recommend(st.to_json(), public, worlds=worlds, seed=st.turn)
            except EngineError as e:
                f.out(f"추천 실패: {e}"); break
            show(f, st, rec, worlds)
            before = st.snapshot()          # 이번 턴 시작 시점의 상태 (결과 입력 전)
            best = rec.best
            line = f"T{st.turn} | 나 {me_a.name} {me_a.hp}% vs 상대 {foe_a.name} {foe_a.hp}% | 추천 {st.label(best.choice)} (승률 {best.value * 100:.0f}%)"

            ci = f.choose("내가 실제로 한 행동", [st.label(r.choice) for r in rec.results], 0)
            taken = rec.results[ci].choice
            foe_move, foe_switched = ask_foe_action(f, foe_a)
            first = [None, "me", "foe"][f.choose("먼저 움직인 쪽", ["모름", "나", "상대"], 0)]
            if foe_move:
                ask_reveal(f, foe_a)
            if "mega" in taken:
                me_a.megaed = True
            history.append({"before": before, "myChoice": taken, "foeMove": foe_move, "first": first, "_me": toid(me_a.set.species), "_foe": toid(foe_a.species)})
            log.append(line + f" | 실제: {st.label(taken)} / 상대 {data.ko('moves', foe_move) if foe_move else ('교체' if foe_switched else '모름')}")
            f.out("\n기보: " + log[-1])
            if f.choose("다음", ["다음 턴 진행", "종료"]) == 1:
                break
            st.turn += 1
    finally:
        if own:
            eng.close()
    if save_dir and log:
        p = pathlib.Path(save_dir); p.mkdir(parents=True, exist_ok=True)
        path = p / f"{dt.datetime.now():%Y%m%d_%H%M%S}.md"
        path.write_text("# 기보\n\n" + "\n".join(f"- {l}" for l in log) + "\n", encoding="utf-8")
        f.out(f"기보 저장: {path}")
    return log
