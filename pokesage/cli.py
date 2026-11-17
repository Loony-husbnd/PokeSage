"""대화형 CLI(코랩·터미널 공용). 모든 입력은 번호 선택, 숫자, 이름 입력으로 이루어진다.

이름 입력: 한국어·영어 이름이 정확히 일치하면 바로 확정하고, 아니면 후보(접두어·초성·오타 유사)를 보여준다.
매 턴에는 "무슨 일이 있었는지"만 입력한다. 결과(HP 등)는 시뮬레이터가 예측한 값이 기본값으로 나오며,
Enter로 확정하거나 실제 값을 입력한다. 입력한 결과로 상대 세트 추론을 갱신한다.
"""
from __future__ import annotations

import datetime as dt
import itertools
import json
import math
import pathlib
from typing import Callable

from .belief import Belief, OppMon, make_worlds
from .dex import (ITEM_INDEX, ITEMS, MOVE_INDEX, SPECIES, SPECIES_INDEX, Index, base_of, josa, ko, learnset)
from .model import PRESETS, SP_MAX, SP_TOTAL, STAT_KO, STATS, Spread
from .search import GREEDY, SearchRng, best_replacement, recommend
from .sets import item_prior, likely_ability, likely_moves
from .sim import NONE, SK, BMon, State, damage_range, damage_rolls, is_status_move, legal, move_data, on_start, \
    speed, step, switch_in

Ask = Callable[[str], str]

# 탐색 강도: 이름 -> (깊이, 칸당 표본 수, 상대 세트 후보 수). 시간은 3대3 실측 기준.
LEVELS = {
    "빠름 (2턴 앞, 0.5초 안팎)": (2, 2, 3),
    "보통 (2턴 앞, 표본·세트 후보 증가, 1~2초)": (2, 4, 5),
    "정밀 (3턴 앞, 15~30초)": (3, 2, 3),
}
STYLES = {
    f"정석형 (최대 피해 기술 위주, 권장 {GREEDY:g})": GREEDY,
    "심리전형 (교체·읽기 많음, 0.3)": 0.3,
    "최적 상대 가정 (균형 전략, 0)": 0.0,
}
STATUS_LIST = (NONE, "화상", "마비", "독", "맹독", "잠듦", "얼음")
WEATHER_KO = {"sun": "쾌청", "rain": "비", "sand": "모래바람", "snow": "설경"}
TERRAIN_KO = {"electric": "일렉트릭필드", "grassy": "그래스필드", "psychic": "사이코필드", "misty": "미스트필드"}
SIDE_KO = {"sr": "스텔스록", "spikes": "압정뿌리기", "tspikes": "독압정", "web": "끈적끈적네트",
           "reflect": "리플렉터", "lightscreen": "빛의장막", "auroraveil": "오로라베일", "tailwind": "순풍",
           "safeguard": "신비의부적"}


# ---------- 입력 폼 ----------

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

    def text(self, title: str, default: str = "") -> str:
        raw = self.ask(f"{title}{f' (기본 {default})' if default else ''}> ").strip()
        return raw or default

    def name(self, kind: str, title: str, index: Index, allowed: set | None = None,
             default: str | None = None, allow_empty: bool = False) -> str | None:
        """이름 입력. 정확히 일치하면 바로 확정, 아니면 후보 목록에서 고른다."""
        while True:
            hint = f" (Enter: {ko(kind, default)})" if default else " (Enter: 건너뛰기)" if allow_empty else ""
            raw = self.ask(f"{title}{hint} 이름> ").strip()
            if raw == "":
                if default:
                    return default
                if allow_empty:
                    return None
                continue
            hit = index.exact(raw)
            if hit and (allowed is None or hit in allowed):
                self.out(f"  → {ko(kind, hit)} 확정")
                return hit
            if hit:
                self.out(f"  {ko(kind, hit)}: 여기서는 고를 수 없습니다(배울 수 없는 기술 등).")
            cands = [c for c in index.search(raw, 16) if allowed is None or c in allowed][:8]
            if not cands:
                self.out("  일치하는 이름이 없습니다. 다시 입력해 주십시오(초성·영어 이름도 가능).")
                continue
            i = self.choose(f"'{raw}' 후보", [ko(kind, c) for c in cands] + ["다시 입력"])
            if i < len(cands):
                return cands[i]


# ---------- 팀 ----------

def mon_to_dict(m: BMon) -> dict:
    return {"species": m.species, "spread": m.spread.to_dict(), "moves": list(m.moves), "item": m.item,
            "ability": m.ability}


def mon_from_dict(d: dict) -> BMon:
    return BMon(d["species"], Spread.from_dict(d["spread"]), d["moves"], d.get("item", ""), d.get("ability"))


def describe_mon(m: BMon) -> str:
    mv = ", ".join(ko("move", x) for x in m.moves)
    return (f"{ko('species', m.species)} @{ko('item', m.item)} [{ko('ability', m.ability)}] "
            f"{m.spread.describe()} | {mv}")


def input_spread(f: Form, sid: str) -> Spread:
    presets = list(PRESETS)
    i = f.choose(f"{ko('species', sid)} 능력 포인트", presets + ["직접 입력"])
    if i < len(presets):
        return PRESETS[presets[i]]
    while True:
        raw = f.ask(f"HP 공격 방어 특공 특방 스피드 순서로 6개 (각 0~{SP_MAX}, 합계 {SP_TOTAL} 이하)> ")
        try:
            sp = [int(x) for x in raw.replace(",", " ").split()]
            if len(sp) != 6:
                raise ValueError("숫자 6개가 필요합니다")
            Spread(sp)
            break
        except ValueError as e:
            f.out(f"  다시 입력해 주십시오: {e}")
    stats = ["무보정"] + [STAT_KO[s] for s in STATS[1:]]
    plus = f.choose("성격: 올라가는 능력치", stats)
    minus = f.choose("성격: 내려가는 능력치", stats) if plus else 0
    return Spread(sp, STATS[plus] if plus else None, STATS[minus] if minus else None)


def input_moves(f: Form, sid: str) -> list[str]:
    sug = list(likely_moves(sid))
    i = f.choose(f"{ko('species', sid)} 기술", [f"예상 기술 사용: {', '.join(ko('move', m) for m in sug)}",
                                              "직접 입력"])
    if i == 0:
        return sug
    allowed = set(learnset(sid))
    out: list[str] = []
    while len(out) < 4:
        mid = f.name("move", f"기술 {len(out) + 1}/4", MOVE_INDEX, allowed - set(out), allow_empty=bool(out))
        if mid is None:
            break
        out.append(mid)
    return out


def input_mon(f: Form, k: int, used_items: set) -> BMon:
    sid = f.name("species", f"내 포켓몬 {k}", SPECIES_INDEX)
    abil = SPECIES[sid]["abilities"]
    if len(abil) > 1:
        d = abil.index(likely_ability(sid)) if likely_ability(sid) in abil else 0
        ab = abil[f.choose(f"{ko('species', sid)} 특성", [ko("ability", a) for a in abil], d)]
    else:
        ab = abil[0] if abil else ""
    sug = next((it for it, _ in item_prior(sid) if it not in used_items and it in ITEMS), "")
    i = f.choose(f"{ko('species', sid)} 도구", [f"추천: {ko('item', sug)}", "직접 입력", "없음"])
    item = sug if i == 0 else "" if i == 2 else f.name("item", "도구", ITEM_INDEX)
    if item and item in used_items:
        f.out("  경고: 같은 도구를 두 마리 이상이 지닐 수 없습니다(도구 클로즈).")
    spread = input_spread(f, sid)
    moves = input_moves(f, sid)
    m = BMon(sid, spread, moves, item, ab)
    f.out("  ✔ " + describe_mon(m))
    return m


def build_team(f: Form, team_dir: str | None) -> list[BMon]:
    tdir = pathlib.Path(team_dir) if team_dir else None
    saved = sorted(tdir.glob("*.json")) if tdir and tdir.exists() else []
    if saved:
        i = f.choose("내 팀", [f"불러오기: {p.stem}" for p in saved] + ["새로 만들기"])
        if i < len(saved):
            data = json.loads(saved[i].read_text(encoding="utf-8"))
            team = [mon_from_dict(d) for d in data["team"]]
            for m in team:
                f.out("  " + describe_mon(m))
            return team
    n = f.number("내 파티 크기", 1, 6, 6)
    team, used = [], set()
    for k in range(1, n + 1):
        m = input_mon(f, k, used)
        if m.item:
            used.add(m.item)
        team.append(m)
    if tdir is not None and f.choose("팀 저장", ["저장", "저장 안 함"]) == 0:
        name = f.text("팀 이름", "my_team")
        tdir.mkdir(parents=True, exist_ok=True)
        path = tdir / f"{name}.json"
        path.write_text(json.dumps({"team": [mon_to_dict(m) for m in team]}, ensure_ascii=False, indent=1),
                        encoding="utf-8")
        f.out(f"  저장: {path}")
    return team


# ---------- 선출 ----------

def matchup(a: BMon, b: BMon) -> float:
    """a가 b를 상대로 1대1에서 얼마나 유리한가(-2~2)."""
    def best(x, y):
        return max((sum(damage_rolls(x, y, m)) / 16 / y.max_hp for m in x.moves if not is_status_move(m)),
                   default=0.0)
    da, db = best(a, b), best(b, a)
    ta = math.ceil(1 / da) if da > 0 else 9
    tb = math.ceil(1 / db) if db > 0 else 9
    margin = (tb - ta) + (0.5 if speed(a) > speed(b) else -0.5)
    return max(-2.0, min(2.0, margin))


def pick_three(team: list[BMon], opps: list[str]) -> tuple[list[int], int]:
    """선출 3마리(팀 인덱스)와 추천 선두. 상대 각 포켓몬에 유리한 대면을 최대한 갖추는 조합."""
    foes = []
    for o in opps:
        b = Belief(o)
        foes.append(b.mon(b.top(1)[0][1]))
    M = [[matchup(m, o) for o in foes] for m in team]
    best, best_v = None, -1e9
    for combo in itertools.combinations(range(len(team)), min(3, len(team))):
        v = sum(max(M[i][j] for i in combo) for j in range(len(foes))) \
            + 0.2 * sum(sum(M[i]) for i in combo) / max(1, len(foes))
        if v > best_v:
            best, best_v = list(combo), v
    lead = max(best, key=lambda i: sum(M[i]))
    return best, lead


# ---------- 전투 ----------

class Battle:
    def __init__(self, f: Form, team: list[BMon], opp_ids: list[str], level=(2, 2, 3), greedy=GREEDY,
                 my_lead: int = 0, opp_lead: str | None = None):
        self.f = f
        self.depth, self.samples, self.k = level
        self.greedy = greedy
        self.opp_ids = opp_ids                     # 상대 팀(미리보기), 원래 형태 id
        self.beliefs = {o: Belief(o) for o in opp_ids}
        self.seen: list[str] = []                 # 등장한 상대 순서(s.teams[1]의 순서와 같다)
        self.log: list[str] = []
        self.opp_size = min(3, len(opp_ids))
        self.s = State([m.copy() for m in team], [], (my_lead, 0), (0, self.opp_size))
        self.bring_in_opp(opp_lead or opp_ids[0])
        self.s.active[1] = 0
        for side in (0, 1):
            on_start(self.s, side)

    # ----- 상태 구성 -----
    def opp_mon(self, sid: str) -> BMon:
        return self.s.teams[1][self.seen.index(sid)]

    def bring_in_opp(self, sid: str, s: State | None = None) -> int:
        s = s or self.s
        if sid not in self.seen:
            b = self.beliefs[sid]
            self.seen.append(sid)
        if len(s.teams[1]) < len(self.seen):
            b = self.beliefs[sid]
            s.teams[1].append(b.mon(b.top(1)[0][1]))
        s.unrevealed[1] = max(0, self.opp_size - len(self.seen))
        return self.seen.index(sid)

    def opp_alive(self) -> list[str]:
        return [o for o in self.opp_ids if not (o in self.seen and self.opp_mon(o).hp <= 0)]

    def worlds(self):
        s = self.s
        opps = [OppMon(self.beliefs[sid], m.frac, m.status, tuple(m.stages), m.tox, m.slp, m.vol)
                for sid, m in zip(self.seen, s.teams[1])]
        return make_worlds(s.teams[0], s.active[0], opps, s.active[1], s.unrevealed[1], self.k,
                           s.field, s.sides, s.turn)

    def sync_opp(self) -> None:
        """추론이 바뀌면 상대 포켓몬 객체를 가장 유력한 세트로 다시 만든다(관측 상태는 유지)."""
        for i, sid in enumerate(self.seen):
            old = self.s.teams[1][i]
            b = self.beliefs[sid]
            new = b.mon(b.top(1)[0][1], old.frac, old.status, old.stages)
            new.hp = 0 if old.hp <= 0 else max(1, round(new.max_hp * old.frac))
            new.vol, new.perm = dict(old.vol), dict(old.perm)
            new.tox, new.slp, new.frz = old.tox, old.slp, old.frz
            new.moves = tuple(dict.fromkeys(list(b.moves[:4]) + list(new.moves)))[:4]
            if self.s.sides[1].get("mega") and b.mega is None:
                new.mega_to = None
            self.s.teams[1][i] = new

    # ----- 표시 -----
    def board(self) -> str:
        s = self.s

        def line(m: BMon, mine: bool) -> str:
            hp = f"{m.hp}/{m.max_hp}" if mine else f"{round(m.frac * 100)}%"
            extra = [] if m.status == NONE else [m.status]
            st = [f"{(STAT_KO[SK[i]] if i < 5 else ('명중', '회피')[i - 5])}{v:+d}"
                  for i, v in enumerate(m.stages) if v]
            return f"{ko('species', m.species)} {hp} {' '.join(extra + st)}".strip()
        out = [f"나: {line(s.mon(0), True)}   |   상대: {line(s.mon(1), False)}"]
        fld = []
        if s.weather:
            fld.append(f"{WEATHER_KO[s.weather]}({s.field.get('wturns', '?')})")
        if s.terrain:
            fld.append(f"{TERRAIN_KO[s.terrain]}({s.field.get('tturns', '?')})")
        if s.field.get("trickroom"):
            fld.append(f"트릭룸({s.field['trickroom']})")
        for side, who in ((0, "내 쪽"), (1, "상대 쪽")):
            conds = [SIDE_KO[k] + (str(v) if k in ("spikes", "tspikes") else "")
                     for k, v in s.sides[side].items() if k in SIDE_KO]
            if conds:
                fld.append(f"{who}: {', '.join(conds)}")
        if fld:
            out.append("필드: " + " / ".join(fld))
        bench = [f"{ko('species', m.species)} {m.hp}/{m.max_hp}" for j, m in enumerate(s.teams[0])
                 if j != s.active[0]]
        out.append("내 대기: " + (", ".join(bench) or "없음"))
        return "\n".join(out)

    def action_label(self, side: int, a: tuple, s: State | None = None) -> str:
        s = s or self.s
        m = s.mon(side)
        if a[0] == "switch":
            return f"교체 → {ko('species', s.teams[side][a[1]].species)}"
        mid = "struggle" if a[1] < 0 else m.moves[a[1]]
        mega = " (메가진화)" if side == 0 and m.mega_to and not s.sides[0].get("mega") else ""
        return f"{move_data(mid)['ko']}{mega}"

    # ----- 추천 -----
    def recommend(self):
        W = self.worlds()
        recs = recommend(W, self.depth, self.samples, greedy=self.greedy)
        s0 = W[0][1]
        me, foe = s0.mon(0), s0.mon(1)
        b = self.beliefs[self.seen[self.s.active[1]]]
        guess = " · ".join(f"{h.spread.describe()} @{ko('item', h.item)} {p:.0%}" for p, h in b.top(2))
        self.f.out(f"\n상대 {ko('species', foe.species)} 추정: [{ko('ability', b.ability)}] {guess}")
        self.f.out("  예상 기술(? = 미확인): " +
                   ", ".join(ko("move", m) + ("" if m in b.moves else "?") for m in b.moveset()))
        self.f.out("--- 추천 ---")
        for n, r in enumerate(recs[:4]):
            info = f"선택 비중 {r.freq:.0%}, 기대 우세 {r.q:+.2f}"
            if r.action[0] == "move" and r.action[1] >= 0 and not is_status_move(me.moves[r.action[1]]):
                dlo, dhi = damage_range(me, foe, me.moves[r.action[1]], s0, 0)
                lo, hi = (min(100, x * 100 // foe.max_hp) for x in (dlo, dhi))
                info += f", 피해 {lo}~{hi}%"
                if dlo >= foe.hp:
                    info += " 확정 1타"
                elif dhi >= foe.hp:
                    info += " 난수 1타"
            self.f.out(f"{'▶' if n == 0 else ' ·'} {self.action_label(0, r.action)}  [{info}]")
        return recs

    # ----- 입력 -----
    def ask_my_action(self, recs) -> tuple:
        opts = legal(self.s, 0)
        default = opts.index(recs[0].action) if recs and recs[0].action in opts else 0
        i = self.f.choose("이번 턴 내 행동", [self.action_label(0, a) for a in opts], default)
        return opts[i]

    def ask_opp_action(self) -> tuple | None:
        s = self.s
        op = s.mon(1)
        known = list(op.moves)
        cur = self.seen[s.active[1]]
        switch_to = [o for o in self.opp_alive() if o != cur]
        if len(self.seen) >= self.opp_size:
            switch_to = [o for o in switch_to if o in self.seen]
        labels = [ko("move", m) for m in known] + ["다른 기술 (이름 입력)"] + \
                 [f"교체 → {ko('species', o)}" for o in switch_to] + ["모름 / 행동하지 못함"]
        i = self.f.choose(f"이번 턴 상대 {ko('species', op.species)}의 행동", labels, len(labels) - 1)
        if i < len(known):
            return ("move", i)
        if i == len(known):
            mid = self.f.name("move", "상대가 쓴 기술", MOVE_INDEX)
            self.beliefs[cur].reveal_move(mid)
            if mid not in op.moves:  # 확인되지 않은 예상 기술 하나를 대체
                keep = [m for m in op.moves if m in self.beliefs[cur].moves]
                rest = [m for m in op.moves if m not in keep]
                op.moves = tuple((keep + [mid] + rest)[:4])
            return ("move", list(op.moves).index(mid))
        j = i - len(known) - 1
        if j < len(switch_to):
            return ("switch", self.bring_in_opp(switch_to[j]))
        return None

    def _opp_mega(self, opp_act) -> None:
        s, f = self.s, self.f
        op = s.mon(1)
        sid = self.seen[s.active[1]]
        b = self.beliefs[sid]
        megas = SPECIES[sid].get("megas", [])
        if opp_act[0] != "move" or not megas or s.sides[1].get("mega") or b.mega:
            return
        opts = ["아니오"] + [f"예 → {ko('species', m)}" for m in megas]
        k = f.choose(f"상대 {josa(ko('species', op.species))} 메가진화했습니까", opts)
        stones = {SPECIES[m].get("item") for m in megas}
        if k:
            stone = SPECIES[megas[k - 1]].get("item", "")
            b.reveal_item(stone)
            op.item, op.mega_to = stone, megas[k - 1]
            b.reveal_mega(megas[k - 1])
            b.mega = None  # 실제 변신은 시뮬레이션의 메가진화 단계에서 일어난다
            self._pending_mega = megas[k - 1]
        else:
            b._update([0.0 if h.item in stones else 1.0 for h in b.hyps])
            op.mega_to = None
            if op.item in stones:
                op.item = b.top(1)[0][1].item

    # ----- 턴 처리 -----
    def turn(self) -> bool:
        s, f = self.s, self.f
        f.out(f"\n===== {s.turn}턴 =====")
        f.out(self.board())
        recs = self.recommend()
        my_act = self.ask_my_action(recs)
        opp_act = self.ask_opp_action()
        opp_known = opp_act is not None
        if opp_act is None:
            opp_act = ("move", 0)
            s.mon(1).vol["_unknown"] = True
        self._pending_mega = None
        self._opp_mega(opp_act)
        first = None
        if my_act[0] == "move" and opp_known and opp_act[0] == "move":
            k = f.choose("누가 먼저 행동했습니까", ["모름", "내가 먼저", "상대가 먼저"])
            first = {1: 0, 2: 1}.get(k)
        flags = {"crit_me": False, "crit_opp": False, "miss_me": False, "miss_opp": False}
        keys = ("crit_me", "crit_opp", "miss_me", "miss_opp")
        while True:
            k = f.choose("특이사항 (해당하는 것을 하나씩 고르고, 끝나면 1번)",
                         ["없음 / 완료", "내 공격이 급소", "상대 공격이 급소", "내 공격이 빗나감", "상대 공격이 빗나감"])
            if k == 0:
                break
            flags[keys[k - 1]] = True
        # 예측 시뮬레이션: 평균 대미지, 확률형 부가 효과 없음, 명중은 입력대로
        rng = SearchRng(0)
        rng.mean, rng.quiet = True, True
        rng.hits = {0: not flags["miss_me"], 1: not flags["miss_opp"] and opp_known}
        rng.procs = {0: False, 1: False}
        ev: list = []
        pred = step(s, my_act, opp_act, rng, ev, first)
        s.mon(1).vol.pop("_unknown", None)
        pred.mon(1).vol.pop("_unknown", None)
        if self._pending_mega and self.beliefs[self.seen[s.active[1]]].mega is None:
            self.beliefs[self.seen[s.active[1]]].mega = self._pending_mega
        # 기술 후 교체(유턴·탈출버튼 등)로 상대 선두가 바뀐 경우
        if pred.active[1] != s.active[1] and opp_act[0] == "move":
            cands = [o for o in self.opp_alive() if o != self.seen[s.active[1]]]
            j = f.choose("상대가 교체해 들여보낸 포켓몬", [ko("species", o) for o in cands])
            pred.active[1] = self.bring_in_opp(cands[j], pred)
        me_new, op_new = pred.mon(0), pred.mon(1)
        pred_me, pred_op = me_new.hp, op_new.frac
        # 결과 입력
        hp = f.text(f"내 {ko('species', me_new.species)} 남은 HP (실수치 또는 %, 최대 {me_new.max_hp}, 기본=예측)",
                    str(me_new.hp))
        me_new.hp = self._parse_hp(hp, me_new.max_hp, me_new.hp)
        pct = f.number(f"상대 {ko('species', op_new.species)} 남은 HP% (기본=예측)", 0, 100,
                       round(op_new.frac * 100))
        if pct != round(op_new.frac * 100):
            op_new.hp = 0 if pct == 0 else max(1, round(op_new.max_hp * pct / 100))
        for m, who in ((me_new, "내"), (op_new, "상대")):
            if m.hp > 0:
                d = STATUS_LIST.index(m.status) if m.status in STATUS_LIST else 0
                st = STATUS_LIST[f.choose(f"{who} {ko('species', m.species)} 상태이상 (기본=예측)",
                                          list(STATUS_LIST), d)]
                if st != m.status:
                    m.status, m.tox = st, 0
                    m.slp = 2 if st == "잠듦" else 0
                    m.frz = 3 if st == "얼음" else 0
        if f.choose("랭크 변화가 예측과 다릅니까", ["예측대로", "직접 수정"]) == 1:
            for m, who in ((me_new, "내"), (op_new, "상대")):
                for i in range(5):
                    m.stages[i] = f.number(f"{who} {STAT_KO[SK[i]]} 랭크", -6, 6, m.stages[i])
        b = self.beliefs[self.seen[pred.active[1]]]
        if f.choose("상대 도구가 드러났습니까 (발동·소모 등)", ["아니오", "예"]) == 1:
            it = f.name("item", "상대 도구", ITEM_INDEX)
            b.reveal_item(it)
            if f.choose("그 도구를 소모했습니까 (기합의띠·열매 등)", ["아니오", "예"]) == 1:
                b.lose_item()
                op_new.item = ""
            else:
                op_new.item = it
        self._learn(s, pred, ev, opp_act, opp_known, first, flags, pred_me, pred_op)
        self.log.append(f"T{s.turn} | 나 {self.action_label(0, my_act)} / 상대 "
                        f"{self.action_label(1, opp_act) if opp_known else '?'} | "
                        f"내 {ko('species', me_new.species)} {me_new.hp}/{me_new.max_hp}, "
                        f"상대 {ko('species', op_new.species)} {round(op_new.frac * 100)}%")
        self.s = pred
        self.sync_opp()
        return self._faints()

    @staticmethod
    def _parse_hp(raw: str, max_hp: int, default: int) -> int:
        raw = raw.strip()
        try:
            if raw.endswith("%"):
                return max(0, min(max_hp, round(max_hp * float(raw[:-1]) / 100)))
            return max(0, min(max_hp, int(raw)))
        except ValueError:
            return default

    def _learn(self, s, new, ev, opp_act, opp_known, first, flags, pred_me, pred_op) -> None:
        """관측(행동 순서, 실제 피해)으로 상대 세트 추론을 갱신한다.
        실제 피해 = 예측 피해 + (예측 남은 HP - 실제 남은 HP)."""
        sid = self.seen[s.active[1]]
        b = self.beliefs[sid]
        if first is not None:
            st = s.copy()
            b.observe_order(first == 1, speed(s.mon(0), st, 0), s.mon(1).status, s.mon(1).stages, st, 1)
        hits = [e for e in ev if e[0] == "hit"]
        by_side = {0: [e for e in hits if e[1] == 0], 1: [e for e in hits if e[1] == 1]}
        same_opp = new.active[1] == s.active[1]
        same_me = new.active[0] == s.active[0]
        if len(by_side[0]) == 1 and not flags["crit_me"] and same_opp:
            _, _, move, att, dfn, dmg, unusual, st = by_side[0][0]
            if not unusual and base_of(dfn.species) == sid:
                obs = dmg / dfn.max_hp + (pred_op - new.mon(1).frac)
                if obs > 0:
                    b.observe_dealt(att, move, dfn.frac, dfn.status, dfn.stages, obs, tol=0.02,
                                    ko=new.mon(1).hp <= 0, state=st, side=0)
        if len(by_side[1]) == 1 and opp_known and not flags["crit_opp"] and same_me:
            _, _, move, att, dfn, dmg, unusual, st = by_side[1][0]
            if not unusual:
                obs = (dmg + pred_me - new.mon(0).hp) / dfn.max_hp
                if obs > 0:
                    b.observe_taken(move, att.frac, att.status, att.stages, dfn, obs, tol=0.006,
                                    ko=new.mon(0).hp <= 0, state=st, side=1)

    def _faints(self) -> bool:
        """기절 처리. 대전이 끝나면 False."""
        s, f = self.s, self.f
        if all(m.hp <= 0 for m in s.teams[0]):
            f.out("\n내 포켓몬이 모두 쓰러졌습니다.")
            return False
        if s.mon(1).hp <= 0:
            self.log.append(f"   상대 {ko('species', s.mon(1).species)} 기절")
            if sum(1 for m in s.teams[1] if m.hp <= 0) >= self.opp_size:
                f.out("\n상대 포켓몬을 모두 쓰러뜨렸습니다.")
                return False
            cands = self.opp_alive()
            if len(self.seen) >= self.opp_size:
                cands = [o for o in cands if o in self.seen]
            j = f.choose("상대가 다음으로 내보낸 포켓몬", [ko("species", o) for o in cands])
            switch_in(s, 1, self.bring_in_opp(cands[j]))
        if s.mon(0).hp <= 0:
            self.log.append(f"   내 {ko('species', s.mon(0).species)} 기절")
            opts = [j for j, m in enumerate(s.teams[0]) if m.hp > 0]
            rec = best_replacement(self.worlds(), 1, 0, self.greedy)
            labels = [ko("species", s.teams[0][j].species) + ("  ← 추천" if j == rec else "") for j in opts]
            j = opts[f.choose("다음에 내보낼 내 포켓몬", labels, opts.index(rec) if rec in opts else 0)]
            switch_in(s, 0, j)
        return True


def input_opp_team(f: Form) -> list[str]:
    f.out("\n=== 새 대전: 상대 파티(미리보기 6마리)를 입력합니다. 다 입력했으면 빈 칸에서 Enter ===")
    opp: list[str] = []
    while len(opp) < 6:
        sid = f.name("species", f"상대 {len(opp) + 1}번째", SPECIES_INDEX, allow_empty=bool(opp))
        if sid is None:
            break
        if base_of(sid) in opp:
            f.out("  이미 입력한 포켓몬입니다.")
            continue
        opp.append(base_of(sid))
    return opp


def run(f: Form | None = None, save_dir: str | None = "kibo", team_dir: str | None = "teams") -> list[str]:
    """대화형 실행. 코랩에서는 save_dir·team_dir를 구글 드라이브 경로로 주면 기보·팀이 보존된다."""
    f = f or Form()
    f.out("PokeSage - 포챔스 싱글 배틀 턴별 최선수 추천")
    team = build_team(f, team_dir)
    level = list(LEVELS.values())[f.choose("탐색 강도", list(LEVELS), 1)]
    greedy = list(STYLES.values())[f.choose("상대 성향", list(STYLES))]
    log: list[str] = []
    while True:
        opp = input_opp_team(f)
        bring, lead = pick_three(team, opp)
        f.out("\n선출 추천: " + ", ".join(ko("species", team[i].species) for i in bring) +
              f" (선두 {ko('species', team[lead].species)})")
        if len(team) > 3 and f.choose("선출", ["추천대로", "직접 선택"]) == 1:
            bring = []
            while len(bring) < 3:
                rest = [j for j in range(len(team)) if j not in bring]
                i = f.choose(f"데리고 갈 포켓몬 {len(bring) + 1}/3", [ko("species", team[j].species) for j in rest])
                bring.append(rest[i])
            lead = bring[0]
        chosen = [team[i] for i in bring]
        li = f.choose("내 선두", [ko("species", m.species) for m in chosen], bring.index(lead))
        oi = f.choose("상대 선두", [ko("species", o) for o in opp])
        battle = Battle(f, chosen, opp, level, greedy, li, opp[oi])
        while battle.turn():
            if f.choose("다음", ["다음 턴 진행", "대전 종료"]) == 1:
                break
        log = battle.log
        if save_dir and log:
            p = pathlib.Path(save_dir)
            p.mkdir(parents=True, exist_ok=True)
            path = p / f"{dt.datetime.now():%Y%m%d_%H%M%S}.md"
            head = (f"# 기보\n\n- 내 선출: {', '.join(ko('species', m.species) for m in chosen)}\n"
                    f"- 상대 파티: {', '.join(ko('species', o) for o in opp)}\n\n")
            path.write_text(head + "\n".join(f"- {l}" for l in log) + "\n", encoding="utf-8")
            f.out(f"기보 저장: {path}")
        if f.choose("다음", ["새 대전", "프로그램 종료"]) == 1:
            return log
