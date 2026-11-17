"""포켓몬별 예상 세트: 기술 4개, 능력 포인트 배분·도구·특성의 사전확률.

사용률 통계가 없으므로 습득 기술 데이터와 종족값으로 자동 생성한다.
 - 기술: 자속 최고 위력기 + 포챔스 로스터 전체 상대 견제 범위를 넓히는 기술 + 역할에 맞는 변화기
 - 배분·도구·특성: 공격/특공·스피드·내구 종족값으로 정한 역할별 가중치
data/usage.json(선택)이 있으면 그 값을 우선 사용한다:
 {"species_id": {"moves": {"move_id": 비율}, "items": {"item_id": 비율}, "abilities": {...},
                 "spreads": [{"sp": [h,a,b,c,d,s], "plus": "atk", "minus": "spa", "w": 비율}]}}
"""
from __future__ import annotations

import json
import pathlib
from functools import lru_cache

from .dex import ITEMS, MOVES, PLAYABLE, SPECIES, learnset, mega_stones
from .model import PRESETS, Spread
from .typechart import effectiveness

_USAGE_PATH = pathlib.Path(__file__).parent / "data" / "usage.json"
USAGE: dict = json.loads(_USAGE_PATH.read_text(encoding="utf-8")) if _USAGE_PATH.exists() else {}

VAR_BP = {"lowkick": 80, "grassknot": 80, "heavyslam": 80, "heatcrash": 80, "gyroball": 70, "electroball": 70,
          "eruption": 150, "waterspout": 150, "reversal": 60, "flail": 60, "storedpower": 40, "powertrip": 40,
          "acrobatics": 100, "hex": 85, "knockoff": 97, "payback": 60, "avalanche": 60, "weatherball": 60,
          "terrainpulse": 55, "seismictoss": 70, "nightshade": 70, "tripleaxel": 100, "hardpress": 70,
          "lastrespects": 60, "ragefist": 75, "risingvoltage": 75, "beatup": 0, "fling": 0, "endeavor": 0,
          "superfang": 0, "finalgambit": 0, "counter": 0, "mirrorcoat": 0, "metalburst": 0, "comeuppance": 0,
          "spitup": 0, "round": 50, "snore": 0, "belch": 40, "lastresort": 0, "steelroller": 40,
          "futuresight": 70, "focuspunch": 70, "fakeout": 30, "dreameater": 0, "solarbeam": 60, "solarblade": 60,
          "skyattack": 60, "meteorbeam": 90, "electroshot": 90, "uproar": 60, "upperhand": 40, "burnup": 90,
          "doubleshock": 90, "poltergeist": 100, "mistyexplosion": 30, "explosion": 40, "selfdestruct": 30,
          "struggle": 0, "dig": 55, "fly": 60, "dive": 55, "bounce": 55, "phantomforce": 60, "hyperbeam": 75,
          "gigaimpact": 75, "foulplay": 55}
SETUP_P = {"swordsdance": 3, "dragondance": 3, "bulkup": 2, "shellsmash": 3, "coil": 2, "victorydance": 3,
           "tidyup": 2}
SETUP_S = {"nastyplot": 3, "quiverdance": 3, "calmmind": 2, "shellsmash": 3, "tailglow": 3, "geomancy": 3,
           "takeheart": 2}
RECOVERY = ("recover", "roost", "slackoff", "softboiled", "moonlight", "morningsun", "synthesis", "shoreup",
            "strengthsap", "milkdrink")
STATUS_UTIL = ("willowisp", "thunderwave", "toxic", "spore", "sleeppowder", "yawn", "stealthrock")
PRIORITY_GOOD = ("extremespeed", "suckerpunch", "bulletpunch", "aquajet", "iceshard", "machpunch",
                 "shadowsneak", "firstimpression", "jetpunch", "vacuumwave", "quickattack", "accelerock",
                 "grassyglide", "thunderclap")
ABILITY_SCORE = {
    "intimidate": 6, "multiscale": 6, "shadowshield": 6, "hugepower": 9, "purepower": 9, "levitate": 5,
    "regenerator": 5, "magicguard": 5, "speedboost": 6, "adaptability": 6, "drought": 6, "drizzle": 6,
    "sandstream": 5, "snowwarning": 5, "electricsurge": 6, "psychicsurge": 6, "grassysurge": 5,
    "mistysurge": 5, "protean": 6, "libero": 6, "technician": 5, "toughclaws": 5, "sheerforce": 5,
    "moxie": 5, "guts": 4, "sturdy": 4, "roughskin": 4, "ironbarbs": 4, "magicbounce": 5, "prankster": 5,
    "unaware": 5, "thickfat": 4, "filter": 4, "solidrock": 4, "prismarmor": 4, "furcoat": 6, "icescales": 5,
    "fluffy": 5, "disguise": 6, "stancechange": 6, "goodasgold": 6, "armortail": 4, "queenlymajesty": 4,
    "dazzling": 4, "flashfire": 3, "waterabsorb": 3, "voltabsorb": 3, "lightningrod": 3, "stormdrain": 3,
    "sapsipper": 3, "eartheater": 3, "swiftswim": 3, "chlorophyll": 3, "sandrush": 3, "slushrush": 3,
    "contrary": 6, "moldbreaker": 4, "noguard": 4, "skilllink": 5, "sharpness": 5, "strongjaw": 5,
    "ironfist": 4, "megalauncher": 5, "pixilate": 6, "aerilate": 6, "refrigerate": 6, "galvanize": 6,
    "dragonize": 6, "parentalbond": 9, "naturalcure": 3, "poisonheal": 5, "marvelscale": 3, "competitive": 4,
    "defiant": 4, "justified": 2, "stamina": 4, "unburden": 4, "beastboost": 6, "supremeoverlord": 5,
    "shadowtag": 6, "punkrock": 5, "tintedlens": 4, "sniper": 3, "superluck": 3, "serenegrace": 4,
    "compoundeyes": 3, "hustle": 3, "solarpower": 3, "sandforce": 3, "analytic": 3, "download": 4,
    "trace": 3, "steelyspirit": 3, "steelworker": 4, "transistor": 5, "dragonsmaw": 5, "quickdraw": 3,
    "megasol": 6, "piercingdrill": 5, "spicyspray": 5, "auraguard": 5, "eelevate": 5, "firemane": 6,
    "unseenfist": 5, "purifyingsalt": 6, "wellbakedbody": 4, "galewings": 4, "thermalexchange": 3,
    "toxicdebris": 3, "seedsower": 3, "sandspit": 3, "guarddog": 4, "liquidvoice": 4, "fairyaura": 6,
}


def _bs(sid: str):
    return SPECIES[sid]["bs"]


def role(sid: str) -> str:
    """"P"(물리) | "S"(특수) | "M"(양쪽)."""
    b = _bs(sid)
    if abs(b[1] - b[3]) <= 10:
        return "M"
    return "P" if b[1] > b[3] else "S"


def move_power(sid: str, mid: str, abil: str = "") -> float:
    """기술의 대략적 화력 점수(위력×명중×자속×공격 능력치 비율×페널티)."""
    mv = MOVES[mid]
    if mv["cat"] == "Z":
        return 0.0
    bp = VAR_BP.get(mid, mv["bp"])
    mh = mv.get("multihit")
    if mh:
        bp *= (mh[1] if abil == "skilllink" else 3) if isinstance(mh, list) else mh
    if mv.get("ohko") or bp <= 0:
        return 0.0
    acc = 1.0 if mv["acc"] == 0 else mv["acc"] / 100
    b = _bs(sid)
    att = b[1] if mv["cat"] == "P" else b[3]
    if mid == "bodypress":
        att = b[2]
    sc = bp * acc * (att / max(b[1], b[3], 1)) ** 1.5
    if mv["type"] in SPECIES[sid]["types"]:
        sc *= 2 if abil == "adaptability" else 1.5
    if mv.get("recoil"):
        sc *= 0.92
    if mv.get("mindBlownRecoil"):
        sc *= 0.6
    if mv.get("self", {}).get("boosts"):
        sc *= 0.9 if any(v < 0 for v in mv["self"]["boosts"].values()) else 1.05
    if mv.get("self", {}).get("volatileStatus") in ("mustrecharge",):
        sc *= 0.6
    if mv.get("selfdestruct"):
        sc *= 0.4
    if mv.get("selfSwitch"):
        sc *= 1.1
    if mv["pri"] > 0:
        sc *= 1.15
    if mv.get("secondaries"):
        sc *= 1.05
    return sc


@lru_cache(maxsize=None)
def _targets() -> tuple:
    seen = {}
    for sid in PLAYABLE:
        t = tuple(SPECIES[sid]["types"])
        seen[t] = seen.get(t, 0) + 1
    return tuple(seen.items())


def _coverage(sid: str, moves: list[str], abil: str) -> float:
    total = 0.0
    for types, w in _targets():
        best = 0.0
        for mid in moves:
            mv = MOVES[mid]
            if mv["cat"] == "Z":
                continue
            e = effectiveness(mv["type"], types)
            best = max(best, move_power(sid, mid, abil) * e)
        total += w * best
    return total


def likely_ability(sid: str) -> str:
    u = USAGE.get(sid, {}).get("abilities")
    if u:
        return max(u, key=u.get)
    abs_ = SPECIES[sid]["abilities"]
    return max(abs_, key=lambda a: (ABILITY_SCORE.get(a, 1), -abs_.index(a))) if abs_ else ""


@lru_cache(maxsize=None)
def likely_moves(sid: str, n: int = 4) -> tuple[str, ...]:
    """가장 그럴듯한 기술 n개."""
    u = USAGE.get(sid, {}).get("moves")
    if u:
        return tuple(sorted(u, key=u.get, reverse=True)[:n])
    pool = [m for m in learnset(sid) if m in MOVES]
    if not pool:
        return tuple()
    abil = likely_ability(sid)
    attacks = sorted((m for m in pool if MOVES[m]["cat"] != "Z" and move_power(sid, m, abil) > 0),
                     key=lambda m: -move_power(sid, m, abil))
    chosen: list[str] = []
    # 자속 기술: 타입별 최고 1개(최대 2개)
    for t in SPECIES[sid]["types"]:
        best = next((m for m in attacks if MOVES[m]["type"] == t), None)
        if best and best not in chosen:
            chosen.append(best)
    # 역할에 맞는 변화기 1개
    b = _bs(sid)
    r = role(sid)
    bulky = b[0] + b[2] + b[4] >= 290 and max(b[1], b[3]) < 105
    setup = SETUP_P if r == "P" else SETUP_S if r == "S" else {**SETUP_P, **SETUP_S}
    status_pick = None
    sets = [m for m in pool if m in setup]
    if sets and not bulky:
        status_pick = max(sets, key=setup.get)
    elif bulky:
        rec = [m for m in RECOVERY if m in pool]
        util = [m for m in STATUS_UTIL if m in pool]
        status_pick = rec[0] if rec else (util[0] if util else None)
    if status_pick:
        chosen.append(status_pick)
    # 견제 범위
    while len(chosen) < n and attacks:
        base = _coverage(sid, chosen, abil)
        best, gain = None, 0.0
        for m in attacks[:30]:
            if m in chosen or any(MOVES[c]["type"] == MOVES[m]["type"] and MOVES[c]["cat"] != "Z" for c in chosen):
                continue
            g = _coverage(sid, chosen + [m], abil) - base
            if g > gain:
                best, gain = m, g
        if best is None:
            break
        chosen.append(best)
    for m in attacks:
        if len(chosen) >= n:
            break
        if m not in chosen:
            chosen.append(m)
    if len(chosen) < n and bulky:
        for m in RECOVERY + STATUS_UTIL:
            if m in pool and m not in chosen and len(chosen) < n:
                chosen.append(m)
    return tuple(chosen[:n])


# ---------- 세트 사전확률 ----------

@lru_cache(maxsize=None)
def spread_prior(sid: str) -> tuple[tuple[Spread, float], ...]:
    u = USAGE.get(sid, {}).get("spreads")
    if u:
        tot = sum(x["w"] for x in u)
        return tuple((Spread(x["sp"], x.get("plus"), x.get("minus")), x["w"] / tot) for x in u)
    b = _bs(sid)
    r = role(sid)
    fast = b[5] >= 85
    bulky = b[0] + b[2] + b[4] >= 290
    P = PRESETS
    w: dict[str, float] = {}
    if r in ("P", "M"):
        w["물리 어태커 (공격·스피드 32, 고집)"] = 0.3
        w["물리 스피드형 (공격·스피드 32, 명랑)"] = 0.3 if fast else 0.12
        w["내구 물리형 (HP·공격 32, 고집)"] = 0.25 if (bulky or not fast) else 0.12
    if r in ("S", "M"):
        k = 0.5 if r == "M" else 1.0
        w["특수 어태커 (특공·스피드 32, 조심)"] = 0.3 * k
        w["특수 스피드형 (특공·스피드 32, 겁쟁이)"] = (0.3 if fast else 0.12) * k
        w["내구 특수형 (HP·특공 32, 조심)"] = (0.25 if (bulky or not fast) else 0.12) * k
    w["물리 내구형 (HP·방어 32, 장난꾸러기)"] = 0.12 if bulky else 0.04
    w["특수 내구형 (HP·특방 32, 신중)"] = 0.12 if bulky else 0.04
    tot = sum(w.values())
    return tuple((P[k], v / tot) for k, v in w.items())


@lru_cache(maxsize=None)
def item_prior(sid: str) -> tuple[tuple[str, float], ...]:
    u = USAGE.get(sid, {}).get("items")
    if u:
        tot = sum(u.values())
        return tuple((k, v / tot) for k, v in u.items())
    b = _bs(sid)
    bulky = b[0] + b[2] + b[4] >= 290
    frail = b[0] + b[2] + b[4] < 230
    w: dict[str, float] = {}
    stones = mega_stones(sid)
    for st in stones:
        w[st] = 0.45 / len(stones)
    w["choicescarf"] = 0.10 if b[5] >= 60 else 0.04
    w["lifeorb"] = 0.08 if not bulky else 0.04
    w["focussash"] = 0.12 if frail else 0.04
    w["leftovers"] = 0.12 if bulky else 0.05
    w["sitrusberry"] = 0.08
    w["lumberry"] = 0.04
    t = SPECIES[sid]["types"][0]
    from .sim import TYPE_ITEMS
    boost = next((k for k, v in TYPE_ITEMS.items() if v == t and k in ITEMS), None)
    if boost:
        w[boost] = 0.05
    w["other"] = 0.12
    tot = sum(w.values())
    return tuple(sorted(((k, v / tot) for k, v in w.items()), key=lambda kv: -kv[1]))
