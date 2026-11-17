"""포챔스 싱글 배틀 시뮬레이터: (상태, 양쪽 행동) -> 다음 상태.

레벨 50, 능력 포인트(SP) 체계, 메가진화(팀당 1회, 기술을 고르면 자동으로 메가진화),
포챔스 상태이상 규칙(마비로 못 움직일 확률 1/8, 잠듦 1~2턴, 얼음 최대 3턴)을 따른다.
기술·특성·도구는 data/*.json의 데이터와 아래의 효과 표로 처리한다. 효과 표에 없는 특성·도구는
효과가 없는 것으로 취급한다(UNSUPPORTED_* 참고).

행동: ("move", 기술 인덱스) | ("switch", 팀 인덱스). 발버둥은 ("move", -1).
"""
from __future__ import annotations

import random
from functools import lru_cache

from .dex import ITEMS, MOVES, SPECIES, mega_of
from .model import DEFAULT_PRESET, PRESETS, Spread, calc_stats, stage_mult
from .typechart import effectiveness

SK = ("atk", "def", "spa", "spd", "spe", "accuracy", "evasion")  # 랭크 배열 순서
CRIT_STAGE = (1 / 24, 1 / 8, 1 / 2, 1.0)
NONE = "없음"

STRUGGLE = {"name": "Struggle", "ko": "발버둥", "type": "???", "cat": "P", "bp": 50, "acc": 0, "pri": 0,
            "target": "normal", "flags": ["contact"]}

# ---------- 효과 분류표 ----------
TYPE_ITEMS = {
    "charcoal": "fire", "mysticwater": "water", "magnet": "electric", "miracleseed": "grass",
    "nevermeltice": "ice", "blackbelt": "fighting", "poisonbarb": "poison", "softsand": "ground",
    "sharpbeak": "flying", "twistedspoon": "psychic", "silverpowder": "bug", "hardstone": "rock",
    "spelltag": "ghost", "dragonfang": "dragon", "blackglasses": "dark", "metalcoat": "steel",
    "silkscarf": "normal", "fairyfeather": "fairy",
}
RESIST_BERRIES = {
    "occaberry": "fire", "passhoberry": "water", "wacanberry": "electric", "rindoberry": "grass",
    "yacheberry": "ice", "chopleberry": "fighting", "kebiaberry": "poison", "shucaberry": "ground",
    "cobaberry": "flying", "payapaberry": "psychic", "tangaberry": "bug", "chartiberry": "rock",
    "kasibberry": "ghost", "habanberry": "dragon", "colburberry": "dark", "babiriberry": "steel",
    "roseliberry": "fairy", "chilanberry": "normal",
}
CURE_BERRIES = {"cheriberry": ("마비",), "chestoberry": ("잠듦",), "pechaberry": ("독", "맹독"),
                "rawstberry": ("화상",), "aspearberry": ("얼음",),
                "lumberry": ("마비", "잠듦", "독", "맹독", "화상", "얼음")}
WEATHER_ROCKS = {"heatrock": "sun", "damprock": "rain", "smoothrock": "sand", "icyrock": "snow"}
TERRAIN_SEEDS = {"electricseed": ("electric", 1), "grassyseed": ("grassy", 1),
                 "psychicseed": ("psychic", 3), "mistyseed": ("misty", 3)}
ATE = {"aerilate": "flying", "pixilate": "fairy", "refrigerate": "ice", "galvanize": "electric",
       "dragonize": "dragon"}
ABSORB = {  # 특성: (흡수 타입, 효과)
    "voltabsorb": ("electric", "heal"), "waterabsorb": ("water", "heal"), "dryskin": ("water", "heal"),
    "eartheater": ("ground", "heal"), "flashfire": ("fire", "flashfire"),
    "lightningrod": ("electric", "spa"), "stormdrain": ("water", "spa"), "motordrive": ("electric", "spe"),
    "sapsipper": ("grass", "atk"), "wellbakedbody": ("fire", "def2"), "levitate": ("ground", None),
    "eelevate": ("ground", None),
}
PINCH = {"overgrow": "grass", "blaze": "fire", "torrent": "water", "swarm": "bug"}
WEATHER_SPEED = {"swiftswim": "rain", "chlorophyll": "sun", "sandrush": "sand", "slushrush": "snow"}
WEATHER_SET = {"drought": "sun", "drizzle": "rain", "sandstream": "sand", "snowwarning": "snow",
               "sunnyday": "sun", "raindance": "rain", "sandstorm": "sand", "snowscape": "snow"}
TERRAIN_SET = {"electricsurge": "electric", "grassysurge": "grassy", "psychicsurge": "psychic",
               "mistysurge": "misty", "electricterrain": "electric", "grassyterrain": "grassy",
               "psychicterrain": "psychic", "mistyterrain": "misty"}
ANNOUNCED = {"intimidate", "drought", "drizzle", "sandstream", "snowwarning", "electricsurge", "grassysurge",
             "psychicsurge", "mistysurge", "download", "trace", "screencleaner", "pressure", "unnerve",
             "moldbreaker", "teravolt", "turboblaze", "frisk", "anticipation", "forewarn", "airlock",
             "cloudnine", "megasol"}
MOLD = {"moldbreaker", "teravolt", "turboblaze"}
NO_DROP = {"clearbody", "whitesmoke", "fullmetalbody", "mirrorarmor"}
STATUS_IMMUNE = {"limber": ("마비",), "insomnia": ("잠듦",), "vitalspirit": ("잠듦",), "sweetveil": ("잠듦",),
                 "immunity": ("독", "맹독"), "pastelveil": ("독", "맹독"), "waterveil": ("화상",),
                 "waterbubble": ("화상",), "thermalexchange": ("화상",), "magmaarmor": ("얼음",),
                 "purifyingsalt": ("마비", "잠듦", "독", "맹독", "화상", "얼음"),
                 "comatose": ("마비", "잠듦", "독", "맹독", "화상", "얼음")}
INTIM_IMMUNE = {"innerfocus", "owntempo", "oblivious", "scrappy", "guarddog"} | NO_DROP
CONTACT_STATUS = {"static": "마비", "flamebody": "화상", "poisonpoint": "독"}
TWO_TURN_SEMI = {"dig", "fly", "dive", "bounce", "phantomforce", "shadowforce"}
TWO_TURN_CHARGE = {"solarbeam", "solarblade", "skyattack", "meteorbeam", "electroshot", "razorwind",
                   "skullbash", "freezeshock", "iceburn", "geomancy"}
PROTECT_SIDE = {"kingsshield", "spikyshield", "banefulbunker", "silktrap", "burningbulwark", "obstruct"}
FOE_TARGETS = {"normal", "any", "allAdjacentFoes", "allAdjacent", "randomNormal", "adjacentFoe", "scripted"}
SCREEN_BREAK = {"brickbreak", "psychicfangs", "ragingbull"}
STATUS_SHORT = {"brn": "화상", "par": "마비", "psn": "독", "tox": "맹독", "slp": "잠듦", "frz": "얼음"}

ABILITY_EFFECTS = set(ABSORB) | set(PINCH) | set(WEATHER_SPEED) | set(MOLD) | set(NO_DROP) \
    | set(STATUS_IMMUNE) | set(INTIM_IMMUNE) | set(CONTACT_STATUS) | set(ATE) | {
        k for k in WEATHER_SET if k in ("drought", "drizzle", "sandstream", "snowwarning")} | {
        "electricsurge", "grassysurge", "psychicsurge", "mistysurge", "intimidate", "multiscale",
        "shadowshield", "hugepower", "purepower", "adaptability", "technician", "toughclaws", "sheerforce",
        "guts", "ironfist", "strongjaw", "megalauncher", "sharpness", "punkrock", "reckless", "sandforce",
        "solarpower", "thickfat", "heatproof", "filter", "solidrock", "prismarmor", "furcoat", "icescales",
        "fluffy", "auraguard", "firemane", "megasol", "piercingdrill", "unseenfist", "spicyspray",
        "regenerator", "naturalcure", "magicguard", "sturdy", "unaware", "speedboost", "moxie", "contrary",
        "simple", "prankster", "galewings", "skilllink", "parentalbond", "noguard", "compoundeyes", "hustle",
        "sniper", "superluck", "merciless", "battlearmor", "shellarmor", "tintedlens", "infiltrator",
        "roughskin", "ironbarbs", "effectspore", "poisontouch", "gooey", "tanglinghair", "aftermath",
        "stamina", "weakarmor", "justified", "rattled", "angerpoint", "berserk", "defiant", "competitive",
        "protean", "libero", "quickfeet", "unburden", "surgesurfer", "sandveil", "snowcloak", "steadfast",
        "shielddust", "serenegrace", "soundproof", "bulletproof", "overcoat", "damp", "goodasgold",
        "magicbounce", "queenlymajesty", "dazzling", "armortail", "suctioncups", "shadowtag", "stakeout",
        "analytic", "stall", "quickdraw", "longreach", "liquidvoice", "steelworker", "transistor",
        "dragonsmaw", "steelyspirit", "fairyaura", "poisonheal", "dryskin", "raindish", "icebody",
        "shedskin", "hydration", "leafguard", "liquidooze", "disguise", "stancechange", "download", "trace",
        "screencleaner", "toxicdebris", "seedsower", "sandspit", "supremeoverlord", "lightmetal",
        "heavymetal", "grasspelt", "marvelscale", "emergencyexit", "wimpout", "cursedbody", "rockhead",
        "keeneye", "hypercutter", "bigpecks", "aromaveil", "eelevate", "electromorphosis", "cloudnine",
        "airlock", "corrosion", "synchronize", "klutz", "comatose", "earlybird", "triage",
    }
ITEM_EFFECTS = set(TYPE_ITEMS) | set(RESIST_BERRIES) | set(CURE_BERRIES) | set(WEATHER_ROCKS) \
    | set(TERRAIN_SEEDS) | {
        "choicescarf", "lifeorb", "focussash", "leftovers", "sitrusberry", "oranberry", "expertbelt",
        "muscleband", "wiseglasses", "focusband", "rockyhelmet", "shellbell", "kingsrock", "scopelens",
        "widelens", "zoomlens", "brightpowder", "quickclaw", "whiteherb", "mentalherb", "airballoon",
        "ejectbutton", "redcard", "lightclay", "terrainextender", "ironball", "lightball", "leek",
        "normalgem", "bigroot", "shedshell", "other",
    }


def _flags(mv: dict) -> list:
    return mv.get("flags", ())


def move_data(mid: str) -> dict:
    return STRUGGLE if mid == "struggle" else MOVES[mid]


@lru_cache(maxsize=None)
def _stats(species: str, spread_key: tuple) -> tuple[int, ...]:
    return calc_stats(SPECIES[species]["bs"], Spread(*spread_key))


def default_ability(species: str) -> str:
    abs_ = SPECIES[species]["abilities"]
    return abs_[0] if abs_ else ""


class BMon:
    """전투 중인 포켓몬 한 마리(HP는 실수치)."""

    __slots__ = ("species", "types", "stats", "max_hp", "hp", "status", "stages", "moves", "item",
                 "ability", "spread", "tox", "slp", "frz", "vol", "perm", "mega_to")

    def __init__(self, species, spread: Spread | str | None = None, moves=None, item="", ability=None,
                 hp_frac=1.0, status=NONE, stages=None):
        if isinstance(spread, str):
            spread = PRESETS[spread]
        self.spread = spread or PRESETS[DEFAULT_PRESET]
        self.species = species
        e = SPECIES[species]
        self.types = tuple(e["types"])
        self.stats = _stats(species, self.spread.key())
        self.max_hp = self.stats[0]
        self.hp = 0 if hp_frac <= 0 else min(self.max_hp, max(1, round(self.max_hp * hp_frac)))
        self.status = status or NONE
        st = list(stages) if stages else []
        self.stages = (st + [0] * 7)[:7]
        if moves is None:
            from .sets import likely_moves
            moves = likely_moves(species)
        self.moves = tuple(moves)
        self.item = item or ""
        self.ability = ability if ability is not None else default_ability(species)
        self.tox = 0
        self.slp = 2 if self.status == "잠듦" else 0
        self.frz = 3 if self.status == "얼음" else 0
        self.vol: dict = {}
        self.perm: dict = {}
        self.mega_to = mega_of(species, self.item) if self.item else None

    def copy(self) -> "BMon":
        m = BMon.__new__(BMon)
        m.species, m.types, m.stats, m.max_hp = self.species, self.types, self.stats, self.max_hp
        m.hp, m.status, m.stages, m.moves = self.hp, self.status, self.stages[:], self.moves
        m.item, m.ability, m.spread = self.item, self.ability, self.spread
        m.tox, m.slp, m.frz, m.mega_to = self.tox, self.slp, self.frz, self.mega_to
        m.vol = dict(self.vol) if self.vol else {}
        m.perm = dict(self.perm) if self.perm else {}
        return m

    @property
    def frac(self) -> float:
        return self.hp / self.max_hp

    @property
    def spread_name(self) -> str:
        return self.spread.label

    def mega_evolve(self) -> str:
        to = self.mega_to
        e = SPECIES[to]
        self.species, self.types = to, tuple(e["types"])
        self.stats = _stats(to, self.spread.key())
        self.max_hp = self.stats[0]  # 메가진화는 HP 종족값이 같다
        self.ability = e["abilities"][0] if e["abilities"] else self.ability
        self.mega_to = None
        return to

    def __repr__(self):
        return f"<{self.species} {self.hp}/{self.max_hp} {self.status}>"


class State:
    __slots__ = ("teams", "active", "unrevealed", "turn", "field", "sides")

    def __init__(self, team0, team1, active=(0, 0), unrevealed=(0, 0), turn=1, field=None, sides=None):
        self.teams = [list(team0), list(team1)]
        self.active = list(active)
        self.unrevealed = list(unrevealed)  # 아직 공개되지 않은 포켓몬 수
        self.turn = turn
        self.field = dict(field) if field else {}
        self.sides = [dict(sides[0]), dict(sides[1])] if sides else [{}, {}]

    def copy(self) -> "State":
        s = State.__new__(State)
        s.teams = [[m.copy() for m in self.teams[0]], [m.copy() for m in self.teams[1]]]
        s.active, s.unrevealed, s.turn = self.active[:], self.unrevealed[:], self.turn
        s.field = dict(self.field)
        s.sides = [dict(self.sides[0]), dict(self.sides[1])]
        return s

    def mon(self, side: int) -> BMon:
        return self.teams[side][self.active[side]]

    def side_of(self, m: BMon) -> int:
        return 0 if any(x is m for x in self.teams[0]) else 1

    @property
    def weather(self) -> str:
        return self.field.get("weather", "")

    @property
    def terrain(self) -> str:
        return self.field.get("terrain", "")


# ---------- 난수 ----------

def _hit(rng, side: int, acc: float) -> bool:
    """명중 판정. 탐색은 rng.hits[side]로 결과를 지정해 확률을 정확히 가중한다."""
    forced = getattr(rng, "hits", None)
    if forced and side in forced:
        return forced[side]
    return acc >= 100 or rng.random() * 100 < acc


def _proc(rng, side: int, chance: float) -> bool:
    """부가 효과 발동 판정. rng.procs[side]로 지정하거나, rng.quiet이면 확정 효과만 발동한다."""
    forced = getattr(rng, "procs", None)
    if forced and side in forced:
        return forced[side]
    if chance >= 100:
        return True
    return not getattr(rng, "quiet", False) and rng.random() * 100 < chance


def _mean(rng) -> bool:
    return getattr(rng, "mean", False)


# ---------- 조회 ----------

def ability(m: BMon, s: State | None = None) -> str:
    return "" if m.vol.get("gastro") else m.ability


def item(m: BMon) -> str:
    return "" if m.ability == "klutz" else m.item


def grounded(m: BMon, s: State | None = None) -> bool:
    if item(m) == "ironball":
        return True
    if "flying" in m.types or m.ability in ("levitate", "eelevate"):
        return False
    return item(m) != "airballoon" and not m.vol.get("magnetrise")


def eff_weather(s: State | None, m: BMon | None = None) -> str:
    if m is not None and m.ability == "megasol":
        return "sun"
    if s is None:
        return ""
    for side in (0, 1):
        a = s.mon(side).ability
        if a in ("cloudnine", "airlock") and s.mon(side).hp > 0:
            return ""
    return s.weather


def speed(m: BMon, s: State | None = None, side: int | None = None) -> int:
    v = m.stats[5] * stage_mult(m.stages[4])
    it, ab = item(m), m.ability
    if it == "choicescarf":
        v *= 1.5
    if it == "ironball":
        v *= 0.5
    if s is not None:
        w = eff_weather(s)
        if WEATHER_SPEED.get(ab) == w and w:
            v *= 2
        if ab == "surgesurfer" and s.terrain == "electric":
            v *= 2
        if side is None:
            side = s.side_of(m)
        if s.sides[side].get("tailwind"):
            v *= 2
    if ab == "unburden" and m.vol.get("unburden"):
        v *= 2
    if ab == "quickfeet" and m.status != NONE:
        v *= 1.5
    elif m.status == "마비":
        v *= 0.5
    return int(v)


def is_status_move(mid: str) -> bool:
    return move_data(mid)["cat"] == "Z"


def move_type(m: BMon, mid: str, s: State | None = None) -> str:
    mv = move_data(mid)
    t = mv["type"]
    if mid == "weatherball":
        t = {"sun": "fire", "rain": "water", "sand": "rock", "snow": "ice"}.get(eff_weather(s, m), "normal")
    elif mid == "terrainpulse" and s is not None and grounded(m):
        t = {"electric": "electric", "grassy": "grass", "psychic": "psychic", "misty": "fairy"}.get(s.terrain, t)
    elif mid == "aurawheel" and m.species == "morpekohangry":
        t = "dark"
    elif mid == "ragingbull" and m.species.startswith("taurospaldea"):
        t = m.types[-1]
    if t == "normal" and m.ability in ATE and mv["cat"] != "Z":
        t = ATE[m.ability]
    if m.ability == "liquidvoice" and "sound" in _flags(mv):
        t = "water"
    return t


def type_eff(att: BMon, dfn: BMon, mid: str, mtype: str) -> float:
    def_types = dfn.types
    e = 1.0
    for dt in def_types:
        x = effectiveness(mtype, (dt,))
        if x == 0 and dt == "ghost" and mtype in ("normal", "fighting") and att.ability in ("scrappy", "mindseye"):
            x = 1.0
        if mid == "freezedry" and dt == "water":
            x = 2.0
        e *= x
    if mid == "flyingpress":
        e *= effectiveness("flying", def_types)
    if mtype == "ground" and e == 0 and item(dfn) == "ironball":
        e = 1.0
    return e


def _weight(m: BMon) -> float:
    w = SPECIES[m.species].get("weight", 50)
    if m.ability == "heavymetal":
        w *= 2
    elif m.ability == "lightmetal":
        w /= 2
    return w


def base_power(att: BMon, dfn: BMon, mid: str, s: State | None, aside: int | None = None) -> int:
    """기술의 실제 위력(위력 변동 기술 반영)."""
    mv = move_data(mid)
    bp = mv["bp"]
    if mid in ("lowkick", "grassknot"):
        w = _weight(dfn)
        bp = 20 if w < 10 else 40 if w < 25 else 60 if w < 50 else 80 if w < 100 else 100 if w < 200 else 120
    elif mid in ("heavyslam", "heatcrash"):
        r = _weight(att) / max(_weight(dfn), 0.1)
        bp = 120 if r >= 5 else 100 if r >= 4 else 80 if r >= 3 else 60 if r >= 2 else 40
    elif mid in ("reversal", "flail"):
        p = 48 * att.hp // att.max_hp
        bp = 200 if p <= 1 else 150 if p <= 4 else 100 if p <= 9 else 80 if p <= 16 else 40 if p <= 32 else 20
    elif mid in ("eruption", "waterspout"):
        bp = max(1, 150 * att.hp // att.max_hp)
    elif mid == "hardpress":
        bp = max(1, 100 * dfn.hp // dfn.max_hp)
    elif mid == "gyroball":
        bp = min(150, 25 * speed(dfn, s) // max(1, speed(att, s)) + 1)
    elif mid == "electroball":
        r = speed(att, s) / max(1, speed(dfn, s))
        bp = 150 if r >= 4 else 120 if r >= 3 else 80 if r >= 2 else 60 if r >= 1 else 40
    elif mid in ("storedpower", "powertrip"):
        bp = 20 + 20 * sum(x for x in att.stages if x > 0)
    elif mid == "acrobatics" and not att.item:
        bp *= 2
    elif mid == "hex" and dfn.status != NONE:
        bp *= 2
    elif mid in ("venoshock", "barbbarrage") and dfn.status in ("독", "맹독"):
        bp *= 2
    elif mid == "infernalparade" and dfn.status != NONE:
        bp *= 2
    elif mid == "facade" and att.status in ("화상", "마비", "독", "맹독"):
        bp *= 2
    elif mid == "knockoff" and dfn.item and not (SPECIES[dfn.species].get("mega")) \
            and not ITEMS.get(dfn.item, {}).get("megaStone"):
        bp = bp * 3 // 2
    elif mid == "payback" and dfn.vol.get("moved"):
        bp *= 2
    elif mid == "avalanche" and att.vol.get("hitby"):
        bp *= 2
    elif mid == "assurance" and dfn.vol.get("damaged"):
        bp *= 2
    elif mid == "lastrespects" and s is not None:
        side = s.side_of(att) if aside is None else aside
        bp = 50 + 50 * sum(1 for m in s.teams[side] if m.hp <= 0)
    elif mid == "ragefist":
        bp = min(350, 50 + 50 * att.perm.get("hits", 0))
    elif mid == "weatherball" and eff_weather(s, att):
        bp = 100
    elif mid == "terrainpulse" and s is not None and s.terrain and grounded(att):
        bp = 100
    elif mid in ("solarbeam", "solarblade") and eff_weather(s, att) in ("rain", "sand", "snow"):
        bp //= 2
    elif mid == "expandingforce" and s is not None and s.terrain == "psychic" and grounded(att):
        bp = bp * 3 // 2
    elif mid == "risingvoltage" and s is not None and s.terrain == "electric" and grounded(dfn):
        bp *= 2
    elif mid == "mistyexplosion" and s is not None and s.terrain == "misty" and grounded(att):
        bp = bp * 3 // 2
    elif mid == "round":
        bp = 60
    return bp


# ---------- 대미지 ----------

def _atk_def(att: BMon, dfn: BMon, mid: str, mv: dict, crit: bool, s, mtype: str):
    cat = mv["cat"]
    if mid == "shellsidearm":
        cat = "P" if att.stats[1] / max(dfn.stats[2], 1) > att.stats[3] / max(dfn.stats[4], 1) else "S"
    if mid == "bodypress":
        ai = 2
    elif cat == "P":
        ai = 1
    else:
        ai = 3
    src = dfn if mid == "foulplay" else att
    di = 2 if (cat == "P" or mid in ("psyshock", "psystrike", "secretsword")) else 4
    ast = src.stages[ai - 1]
    dst = dfn.stages[di - 1]
    mold = att.ability in MOLD
    if dfn.ability == "unaware" and not mold:
        ast = 0
    if att.ability == "unaware" or mid in ("sacredsword", "darkestlariat"):
        dst = 0
    if crit:
        ast, dst = max(ast, 0), min(dst, 0)
    a = src.stats[ai] * stage_mult(ast)
    d = dfn.stats[di] * stage_mult(dst)
    ab, it = att.ability, item(att)
    if ai == 1:
        if ab in ("hugepower", "purepower"):
            a *= 2
        if ab == "hustle":
            a *= 1.5
        if ab == "guts" and att.status != NONE:
            a *= 1.5
    if ai == 3 and ab == "solarpower" and eff_weather(s, att) == "sun":
        a *= 1.5
    if ab == "firemane" and mtype == "fire":
        a *= 1.5
    if ab == "flashfire" and att.vol.get("flashfire") and mtype == "fire":
        a *= 1.5
    if ab in PINCH and PINCH[ab] == mtype and att.hp * 3 <= att.max_hp:
        a *= 1.5
    if (ab == "steelworker" and mtype == "steel") or (ab == "transistor" and mtype == "electric") \
            or (ab == "dragonsmaw" and mtype == "dragon") or (ab == "steelyspirit" and mtype == "steel"):
        a *= 1.5
    if ab == "waterbubble" and mtype == "water":
        a *= 2
    if it == "lightball" and att.species.startswith("pikachu"):
        a *= 2
    dab = "" if mold else dfn.ability
    if dab == "thickfat" and mtype in ("fire", "ice"):
        a *= 0.5
    if dab == "heatproof" and mtype == "fire":
        a *= 0.5
    if dab == "waterbubble" and mtype == "fire":
        a *= 0.5
    if dab == "purifyingsalt" and mtype == "ghost":
        a *= 0.5
    w = eff_weather(s)
    if di == 4 and w == "sand" and "rock" in dfn.types:
        d *= 1.5
    if di == 2 and w == "snow" and "ice" in dfn.types:
        d *= 1.5
    if di == 2 and dab == "furcoat":
        d *= 2
    if di == 2 and dab == "marvelscale" and dfn.status != NONE:
        d *= 1.5
    if di == 2 and dab == "grasspelt" and s is not None and s.terrain == "grassy":
        d *= 1.5
    return max(1, int(a)), max(1, int(d)), cat


def damage(att: BMon, dfn: BMon, mid: str, roll: int = 100, crit: bool = False, s: State | None = None,
           aside: int | None = None, hit: int = 1) -> int:
    """기술 1타의 대미지(HP 실수치). roll은 85~100. s를 주면 날씨·필드·벽을 반영한다."""
    mv = move_data(mid)
    if mv["cat"] == "Z":
        return 0
    if mid in ("seismictoss", "nightshade"):
        mtype = "fighting" if mid == "seismictoss" else "ghost"
        return 0 if type_eff(att, dfn, mid, mtype) == 0 else 50
    if mid in ("superfang", "ruination", "naturesmadness"):
        return max(1, dfn.hp // 2)
    if mid == "endeavor":
        return max(0, dfn.hp - att.hp)
    if mid == "finalgambit":
        return att.hp
    if mv.get("ohko"):
        return dfn.hp
    mtype = move_type(att, mid, s)
    eff = type_eff(att, dfn, mid, mtype) if mtype != "???" else 1.0
    if eff == 0:
        return 0
    if mid in ("counter", "mirrorcoat", "metalburst", "comeuppance"):
        taken = att.vol.get("taken")
        if not taken:
            return 0
        if mid == "counter" and taken[0] != "P" or mid == "mirrorcoat" and taken[0] != "S":
            return 0
        return int(taken[1] * (2 if mid in ("counter", "mirrorcoat") else 1.5))
    bp = base_power(att, dfn, mid, s, aside)
    if mid == "tripleaxel":
        bp = 20 * hit
    ab = att.ability
    flags = _flags(mv)
    mod = 1.0
    if ab == "technician" and bp <= 60:
        mod *= 1.5
    if ab == "toughclaws" and "contact" in flags and ab != "longreach":
        mod *= 1.3
    if ab == "ironfist" and "punch" in flags:
        mod *= 1.2
    if ab == "strongjaw" and "bite" in flags:
        mod *= 1.5
    if ab == "megalauncher" and "pulse" in flags:
        mod *= 1.5
    if ab == "sharpness" and "slicing" in flags:
        mod *= 1.5
    if ab == "punkrock" and "sound" in flags:
        mod *= 1.3
    if ab == "reckless" and (mv.get("recoil") or mv.get("hasCrashDamage")):
        mod *= 1.2
    if ab == "sheerforce" and mv.get("secondaries"):
        mod *= 1.3
    if ab in ATE and mv["type"] == "normal":
        mod *= 1.2
    if ab == "sandforce" and eff_weather(s) == "sand" and mtype in ("rock", "ground", "steel"):
        mod *= 1.3
    if ab == "analytic" and att.vol.get("movinglast"):
        mod *= 1.3
    if ab == "stakeout" and dfn.vol.get("switchedin"):
        mod *= 2
    if ab == "supremeoverlord" and s is not None:
        side = s.side_of(att) if aside is None else aside
        mod *= 1 + 0.1 * min(5, sum(1 for m in s.teams[side] if m.hp <= 0))
    if ab == "fairyaura" or dfn.ability == "fairyaura":
        if mtype == "fairy":
            mod *= 4 / 3
    if att.vol.get("charge") and mtype == "electric":
        mod *= 2
    it = item(att)
    if TYPE_ITEMS.get(it) == mtype:
        mod *= 1.2
    if it == "muscleband" and mv["cat"] == "P":
        mod *= 1.1
    if it == "wiseglasses" and mv["cat"] == "S":
        mod *= 1.1
    if it == "normalgem" and mtype == "normal":
        mod *= 1.3
    if s is not None:
        t = s.terrain
        if t and grounded(att):
            if (t == "electric" and mtype == "electric") or (t == "grassy" and mtype == "grass") \
                    or (t == "psychic" and mtype == "psychic"):
                mod *= 1.3
        if t == "misty" and mtype == "dragon" and grounded(dfn):
            mod *= 0.5
        if t == "grassy" and mid in ("earthquake", "bulldoze") and grounded(dfn):
            mod *= 0.5
    bp = max(1, int(bp * mod))
    a, d, cat = _atk_def(att, dfn, mid, mv, crit, s, mtype)
    base = (22 * bp * a // d) // 50 + 2
    w = eff_weather(s, att)
    if w == "sun" and dfn.ability != "megasol":
        base = int(base * (1.5 if mtype == "fire" else 0.5 if mtype == "water" else 1))
    elif w == "rain":
        base = int(base * (1.5 if mtype == "water" else 0.5 if mtype == "fire" else 1))
    if crit:
        base = base * 3 // 2
    dmg = base * roll // 100
    if mtype in att.types or (att.ability in ("protean", "libero") and mtype != "???"):
        dmg = int(dmg * (2 if ab == "adaptability" else 1.5))
    dmg = int(dmg * eff)
    if cat == "P" and att.status == "화상" and ab != "guts" and mid != "facade":
        dmg //= 2
    # 최종 보정
    fm = 1.0
    if s is not None and not crit and ab != "infiltrator":
        dside = s.sides[1 - aside] if aside is not None else s.sides[s.side_of(dfn)]
        if dside.get("auroraveil") or (cat == "P" and dside.get("reflect")) or (cat == "S" and dside.get("lightscreen")):
            fm *= 0.5
    mold = ab in MOLD
    dab = "" if mold else dfn.ability
    if dab in ("multiscale", "shadowshield") and dfn.hp == dfn.max_hp:
        fm *= 0.5
    if dab in ("filter", "solidrock", "prismarmor") and eff > 1:
        fm *= 0.75
    if dab == "fluffy":
        if "contact" in flags and ab != "longreach":
            fm *= 0.5
        if mtype == "fire":
            fm *= 2
    if dab == "auraguard" and "contact" in flags and ab != "longreach":
        fm *= 0.5
    if dab == "icescales" and cat == "S":
        fm *= 0.5
    if dab == "punkrock" and "sound" in flags:
        fm *= 0.5
    if dab == "dryskin" and mtype == "fire":
        fm *= 1.25
    if ab == "tintedlens" and eff < 1:
        fm *= 2
    if ab == "sniper" and crit:
        fm *= 1.5
    if it == "expertbelt" and eff > 1:
        fm *= 1.2
    if it == "lifeorb":
        fm *= 1.3
    if RESIST_BERRIES.get(item(dfn)) == mtype and (eff > 1 or mtype == "normal") and dfn.ability != "klutz":
        fm *= 0.5
    if att.vol.get("bypassprotect"):
        fm *= 0.25
    if ab == "parentalbond" and hit == 2:
        fm *= 0.25
    dmg = int(dmg * fm)
    return max(dmg, 1)


def damage_rolls(att: BMon, dfn: BMon, mid: str, crit: bool = False, s: State | None = None,
                 aside: int | None = None) -> list[int]:
    return [damage(att, dfn, mid, r, crit, s, aside) for r in range(85, 101)]


def damage_range(att: BMon, dfn: BMon, mid: str, s: State | None = None, aside: int | None = None
                 ) -> tuple[int, int]:
    """연속기는 평균 타수(트리플악셀은 3타, 스킬링크는 최대 타수)를 합친 (최소, 최대) 대미지."""
    hits = n_hits(att, mid, type("R", (), {"mean": True})())
    lo = hi = 0
    for h in range(1, hits + 1):
        lo += damage(att, dfn, mid, 85, False, s, aside, hit=h)
        hi += damage(att, dfn, mid, 100, False, s, aside, hit=h)
    return lo, hi


def n_hits(att: BMon, mid: str, rng) -> int:
    mv = move_data(mid)
    mh = mv.get("multihit")
    if att.ability == "parentalbond" and not mh and mv["cat"] != "Z":
        return 2
    if mid == "tripleaxel":
        return 3
    if not mh:
        return 1
    if isinstance(mh, list):
        if att.ability == "skilllink":
            return mh[1]
        if _mean(rng):
            return 3 if mh == [2, 5] else round(sum(mh) / 2)
        if mh == [2, 5]:
            return rng.choice((2, 2, 2, 3, 3, 3, 4, 5)) if item(att) != "loadeddice" else rng.choice((4, 5))
        return rng.randint(mh[0], mh[1])
    return mh


def accuracy(att: BMon, dfn: BMon, mid: str, s: State | None) -> float:
    """명중률(%). 100 이상이면 반드시 맞는다."""
    mv = move_data(mid)
    acc = mv["acc"]
    if acc == 0 or att.ability == "noguard" or dfn.ability == "noguard":
        return 101
    w = eff_weather(s, att)
    if mid in ("thunder", "hurricane"):
        if w == "rain":
            return 101
        if w == "sun":
            acc = 50
    if mid == "blizzard" and w == "snow":
        return 101
    if mid == "toxic" and "poison" in att.types:
        return 101
    if mv.get("ohko"):
        acc = 20 if (mid == "sheercold" and "ice" not in att.types) else 30
        return acc
    st = att.stages[5] - (0 if mv.get("ignoreEvasion") or att.ability == "keeneye" else dfn.stages[6])
    st = max(-6, min(6, st))
    acc *= (3 + st) / 3 if st >= 0 else 3 / (3 - st)
    if att.ability == "compoundeyes":
        acc *= 1.3
    if att.ability == "hustle" and mv["cat"] == "P":
        acc *= 0.8
    if item(att) == "widelens":
        acc *= 1.1
    if item(att) == "zoomlens" and dfn.vol.get("moved"):
        acc *= 1.2
    if item(dfn) == "brightpowder":
        acc *= 0.9
    if (dfn.ability == "sandveil" and w == "sand") or (dfn.ability == "snowcloak" and w == "snow"):
        acc *= 0.8
    return acc


def crit_chance(att: BMon, dfn: BMon, mid: str) -> float:
    mv = move_data(mid)
    if dfn.ability in ("battlearmor", "shellarmor") and att.ability not in MOLD:
        return 0.0
    if mv.get("willCrit") or (att.ability == "merciless" and dfn.status in ("독", "맹독")):
        return 1.0
    st = mv.get("critRatio", 1) - 1 + att.vol.get("focusenergy", 0)
    if att.ability == "superluck":
        st += 1
    if item(att) == "scopelens" or (item(att) == "leek" and "farfetchd" in att.species):
        st += 1 + (item(att) == "leek")
    return CRIT_STAGE[min(3, max(0, st))]


# ---------- 상태 질의 ----------

def _forced(m: BMon) -> int | None:
    for k in ("charging", "semi", "locked", "recharge"):
        if k in m.vol:
            v = m.vol[k]
            return v[0] if isinstance(v, tuple) else v
    return None


def trapped(s: State, side: int) -> bool:
    me, foe = s.mon(side), s.mon(1 - side)
    if item(me) == "shedshell" or "ghost" in me.types:
        return False
    if foe.hp > 0 and foe.ability == "shadowtag" and me.ability != "shadowtag":
        return True
    return bool(me.vol.get("trapped") or me.vol.get("ingrain"))


def legal(s: State, side: int) -> list[tuple]:
    team, a = s.teams[side], s.active[side]
    me = team[a]
    sw = [("switch", j) for j, m in enumerate(team) if j != a and m.hp > 0]
    if me.hp <= 0:
        return sw
    f = _forced(me)
    if f is not None:
        return [("move", f)]
    if trapped(s, side):
        sw = []
    idx = list(range(len(me.moves)))
    lock = me.vol.get("choice")
    if lock is not None and lock < len(me.moves) and item(me) in ("choicescarf",):
        idx = [lock]
    enc = me.vol.get("encore")
    if enc:
        idx = [enc[0]]
    if me.vol.get("taunt"):
        idx = [i for i in idx if not is_status_move(me.moves[i])]
    if me.status != "잠듦":
        idx = [i for i in idx if me.moves[i] not in ("sleeptalk", "snore")]
    if me.vol.get("turns", 0) > 0:
        idx = [i for i in idx if me.moves[i] not in ("fakeout", "firstimpression")]
    if not idx:
        return [("move", -1)] + sw
    return [("move", i) for i in idx] + sw


def _alive(s: State, side: int) -> bool:
    return any(m.hp > 0 for m in s.teams[side])


def winner(s: State) -> int | None:
    """승자 side. 미정이면 None. (동시 전멸은 side 1 승으로 처리)"""
    for side in (0, 1):
        if not _alive(s, side) and s.unrevealed[side] == 0:
            return 1 - side
    return None


def pending(s: State, side: int) -> bool:
    """기절로 인한 교체 선택이 필요한가."""
    return s.mon(side).hp <= 0 and _alive(s, side)


def stalled(s: State) -> bool:
    """공개된 포켓몬이 전멸했지만 미공개 포켓몬이 남아 더 진행할 수 없는 상태."""
    return any(not _alive(s, side) and s.unrevealed[side] > 0 for side in (0, 1))


# ---------- 상태 변경 도우미 ----------

def boost(s: State, m: BMon, delta: dict, by_foe: bool = False, ev=None, side=None) -> bool:
    """랭크 변화. 하나라도 적용되면 True."""
    if m.hp <= 0:
        return False
    if by_foe and m.ability in NO_DROP and any(v < 0 for v in delta.values()):
        delta = {k: v for k, v in delta.items() if v > 0}
    if by_foe and m.vol.get("sub"):
        return False
    changed = False
    lowered = False
    for k, v in delta.items():
        if k not in SK:
            continue
        if m.ability == "contrary":
            v = -v
        if m.ability == "simple":
            v *= 2
        if by_foe and v < 0 and ((m.ability == "hypercutter" and k == "atk") or (
                m.ability == "bigpecks" and k == "def") or (m.ability == "keeneye" and k == "accuracy")):
            continue
        i = SK.index(k)
        new = max(-6, min(6, m.stages[i] + v))
        if new != m.stages[i]:
            changed = True
            lowered |= new < m.stages[i]
        m.stages[i] = new
    if lowered and by_foe:
        if m.ability == "defiant":
            boost(s, m, {"atk": 2})
        elif m.ability == "competitive":
            boost(s, m, {"spa": 2})
        if item(m) == "whiteherb":
            m.stages = [max(0, x) for x in m.stages]
            _consume(s, m, ev, side)
    return changed


def _consume(s, m: BMon, ev=None, side=None) -> None:
    if not m.item:
        return
    if ev is not None:
        ev.append(("item", s.side_of(m) if side is None else side, m.species, m.item))
        ev.append(("itemlost", s.side_of(m) if side is None else side, m.species))
    if ITEMS.get(m.item, {}).get("isBerry"):
        m.perm["ateberry"] = True
    m.item = ""
    if m.ability == "unburden":
        m.vol["unburden"] = True


def can_status(s: State | None, m: BMon, st: str, src: BMon | None = None) -> bool:
    if m.status != NONE or m.hp <= 0:
        return False
    t = m.types
    if (st == "화상" and "fire" in t) or (st == "마비" and "electric" in t) or (st == "얼음" and "ice" in t):
        return False
    if st in ("독", "맹독") and ("poison" in t or "steel" in t) and not (src is not None and src.ability == "corrosion"):
        return False
    if st in STATUS_IMMUNE.get(m.ability, ()):
        return False
    if s is not None:
        side = s.side_of(m)
        if s.sides[side].get("safeguard") and src is not None and src is not m:
            return False
        if grounded(m) and (s.terrain == "misty" or (s.terrain == "electric" and st == "잠듦")):
            return False
        if m.ability == "leafguard" and eff_weather(s) == "sun":
            return False
    if st == "잠듦" and m.vol.get("uproar"):
        return False
    return True


def inflict(s: State | None, m: BMon, st: str, rng, src: BMon | None = None, turns: int | None = None) -> bool:
    if not can_status(s, m, st, src):
        return False
    m.status, m.tox = st, 0
    if st == "잠듦":
        m.slp = turns if turns is not None else (2 if _mean(rng) else rng.choice((2, 3, 3)))
    elif st == "얼음":
        m.frz = 3
    if src is not None and src is not m and m.ability == "synchronize" and st in ("화상", "마비", "독", "맹독"):
        inflict(s, src, "독" if st == "맹독" else st, rng)
    it = item(m)
    if it in CURE_BERRIES and st in CURE_BERRIES[it]:
        m.status = NONE
        _consume(s, m) if s is not None else None
    return True


def heal(m: BMon, amount: int) -> int:
    if m.hp <= 0:
        return 0
    old = m.hp
    m.hp = min(m.max_hp, m.hp + max(1, amount))
    return m.hp - old


def chip(s: State, m: BMon, frac: float) -> None:
    """간접 대미지(매직가드면 무효)."""
    if m.hp <= 0 or m.ability == "magicguard":
        return
    m.hp = max(0, m.hp - max(1, int(m.max_hp * frac)))
    _check_berry(s, m)


def _check_berry(s: State, m: BMon, ev=None) -> None:
    if m.hp <= 0:
        return
    it = item(m)
    if it == "sitrusberry" and m.hp * 2 <= m.max_hp:
        heal(m, m.max_hp // 4)
        _consume(s, m, ev)
    elif it == "oranberry" and m.hp * 2 <= m.max_hp:
        heal(m, 10)
        _consume(s, m, ev)
    if m.ability == "berserk" and m.hp * 2 <= m.max_hp and not m.perm.get("berserked"):
        m.perm["berserked"] = True
        boost(s, m, {"spa": 1})


def set_weather(s: State, w: str, setter: BMon) -> None:
    if s.weather == w:
        return
    s.field["weather"] = w
    s.field["wturns"] = 8 if WEATHER_ROCKS.get(item(setter)) == w else 5


def set_terrain(s: State, t: str, setter: BMon) -> None:
    if s.terrain == t:
        return
    s.field["terrain"] = t
    s.field["tturns"] = 8 if item(setter) == "terrainextender" else 5
    for side in (0, 1):
        m = s.mon(side)
        seed = TERRAIN_SEEDS.get(item(m))
        if seed and seed[0] == t and m.hp > 0:
            boost(s, m, {SK[seed[1]]: 1})
            _consume(s, m)


def on_start(s: State, side: int, ev=None) -> None:
    """등장(또는 메가진화) 시 발동하는 특성."""
    m, foe = s.mon(side), s.mon(1 - side)
    ab = ability(m)
    if ev is not None and ab in ANNOUNCED:
        ev.append(("ability", side, m.species, ab))
    if ab == "intimidate" and foe.hp > 0:
        if foe.ability in INTIM_IMMUNE or foe.vol.get("sub"):
            if foe.ability == "guarddog":
                boost(s, foe, {"atk": 1})
        else:
            boost(s, foe, {"atk": -1}, by_foe=True, ev=ev, side=1 - side)
            if foe.ability == "rattled":
                boost(s, foe, {"spe": 1})
    elif ab in ("drought", "drizzle", "sandstream", "snowwarning"):
        set_weather(s, WEATHER_SET[ab], m)
    elif ab in ("electricsurge", "grassysurge", "psychicsurge", "mistysurge"):
        set_terrain(s, TERRAIN_SET[ab], m)
    elif ab == "download" and foe.hp > 0:
        boost(s, m, {"atk": 1} if foe.stats[2] * stage_mult(foe.stages[1]) < foe.stats[4] * stage_mult(
            foe.stages[3]) else {"spa": 1})
    elif ab == "trace" and foe.ability not in ("trace", "multitype", "stancechange", "disguise", "imposter"):
        m.ability = foe.ability
        if m.ability != "trace":
            on_start(s, side, ev)
    elif ab == "screencleaner":
        for sd in s.sides:
            for k in ("reflect", "lightscreen", "auroraveil"):
                sd.pop(k, None)
    seed = TERRAIN_SEEDS.get(item(m))
    if seed and seed[0] == s.terrain:
        boost(s, m, {SK[seed[1]]: 1})
        _consume(s, m, ev, side)


def switch_out(s: State, side: int) -> None:
    out = s.mon(side)
    if out.hp > 0:
        if out.ability == "regenerator":
            heal(out, out.max_hp // 3)
        if out.ability == "naturalcure":
            out.status = NONE
    if out.species == "aegislashblade":
        out.species = "aegislash"
        out.stats = _stats("aegislash", out.spread.key())
    out.stages = [0] * 7
    out.tox = 0
    out.vol = {}


def switch_in(s: State, side: int, j: int, ev=None, keep: dict | None = None) -> None:
    """side의 선두를 j번으로 바꾼다(s를 직접 수정)."""
    switch_out(s, side)
    s.active[side] = j
    m = s.mon(side)
    m.vol = {"switchedin": True, "turns": 0}
    if keep:
        m.stages = keep.get("stages", m.stages)
        if keep.get("sub"):
            m.vol["sub"] = keep["sub"]
    sd = s.sides[side]
    if sd.pop("healingwish", None):
        m.hp, m.status = m.max_hp, NONE
    if m.ability != "magicguard":
        if sd.get("sr"):
            m.hp = max(0, m.hp - int(m.max_hp * effectiveness("rock", m.types) / 8))
        if sd.get("spikes") and grounded(m):
            m.hp = max(0, m.hp - m.max_hp // (8, 6, 4)[min(3, sd["spikes"]) - 1])
    if grounded(m):
        if sd.get("tspikes"):
            if "poison" in m.types:
                sd.pop("tspikes")
            else:
                inflict(s, m, "맹독" if sd["tspikes"] >= 2 else "독", random)
        if sd.get("web"):
            boost(s, m, {"spe": -1}, by_foe=True)
    if m.hp <= 0:
        return
    _check_berry(s, m, ev)
    on_start(s, side, ev)


def best_bench(s: State, side: int, rng=None, forced: bool = False) -> int | None:
    """중간 교체(유턴·탈출버튼 등) 때 내보낼 포켓몬. 강제 교체면 무작위."""
    cands = [j for j, m in enumerate(s.teams[side]) if j != s.active[side] and m.hp > 0]
    if not cands:
        return None
    if forced:
        return (rng or random).choice(cands) if not _mean(rng) else cands[0]
    foe = s.mon(1 - side)

    def score(j):
        m = s.teams[side][j]
        if foe.hp <= 0:
            return m.frac
        out = max((damage(m, foe, mv, 92) for mv in m.moves if not is_status_move(mv)), default=0) / foe.max_hp
        inc = max((damage(foe, m, mv, 92) for mv in foe.moves if not is_status_move(mv)), default=0) / m.max_hp
        return out - inc + 0.3 * m.frac
    return max(cands, key=score)


# ---------- 기술 실행 ----------

def _protect_blocks(foe: BMon, mid: str, mv: dict) -> bool:
    return foe.vol.get("protect") and mv["target"] in FOE_TARGETS and not mv.get("breaksProtect") \
        and not (mid == "feint")


def _immune(s, att: BMon, dfn: BMon, mid: str, mv: dict, mtype: str, ev, dside) -> bool:
    """특성·타입에 의한 무효. True면 기술이 막힌다."""
    if att.ability in MOLD:
        dab = ""
    else:
        dab = dfn.ability
    flags = _flags(mv)
    if mv["cat"] == "Z" and mv["target"] not in FOE_TARGETS:
        return False
    if dab == "goodasgold" and mv["cat"] == "Z":
        return True
    if dab == "soundproof" and "sound" in flags:
        return True
    if dab == "bulletproof" and "bullet" in flags:
        return True
    if "powder" in flags and ("grass" in dfn.types or dab == "overcoat"):
        return True
    if mv["cat"] == "Z" and att.vol.get("prankster") and "dark" in dfn.types:
        return True
    if mv["pri"] > 0 or att.vol.get("prankster") or att.vol.get("galewings"):
        if dab in ("queenlymajesty", "dazzling", "armortail"):
            return True
        if s is not None and s.terrain == "psychic" and grounded(dfn) and mv["cat"] != "Z":
            return True
    if dab in ABSORB and ABSORB[dab][0] == mtype and dab not in ("levitate", "eelevate"):
        eff = ABSORB[dab][1]
        if eff == "heal":
            heal(dfn, dfn.max_hp // 4)
        elif eff == "flashfire":
            dfn.vol["flashfire"] = True
        elif eff == "spa":
            boost(s, dfn, {"spa": 1})
        elif eff == "spe":
            boost(s, dfn, {"spe": 1})
        elif eff == "atk":
            boost(s, dfn, {"atk": 1})
        elif eff == "def2":
            boost(s, dfn, {"def": 2})
        if ev is not None:
            ev.append(("ability", dside, dfn.species, dab))
        return True
    if mtype == "ground" and mv["cat"] != "Z" and not grounded(dfn) and mid != "thousandarrows":
        return True
    return False


def _contact_effects(s: State, att: BMon, dfn: BMon, aside: int, rng, ev) -> None:
    if att.ability == "longreach" or item(att) == "protectivepads":
        return
    dab = dfn.ability
    if dab in ("roughskin", "ironbarbs"):
        chip(s, att, 1 / 8)
    if item(dfn) == "rockyhelmet":
        chip(s, att, 1 / 6)
    if dab in CONTACT_STATUS and _proc(rng, 1 - aside, 30):
        inflict(s, att, CONTACT_STATUS[dab], rng, dfn)
    if dab == "effectspore" and "grass" not in att.types and _proc(rng, 1 - aside, 30):
        inflict(s, att, rng.choice(("독", "마비", "잠듦")) if not _mean(rng) else "독", rng, dfn)
    if dab in ("gooey", "tanglinghair"):
        boost(s, att, {"spe": -1}, by_foe=True)
    if att.ability == "poisontouch" and _proc(rng, aside, 30):
        inflict(s, dfn, "독", rng, att)
    if dab == "aftermath" and dfn.hp <= 0:
        chip(s, att, 1 / 4)


def _deal(s: State, att: BMon, dfn: BMon, mid: str, mv: dict, dmg: int, aside: int, rng, ev,
          crit: bool) -> int:
    """대미지를 실제로 적용한다(대타출동·탈·기합의띠·옹골참·열매)."""
    dside = 1 - aside
    if dfn.vol.get("sub") and "sound" not in _flags(mv) and att.ability != "infiltrator":
        sub = dfn.vol["sub"]
        done = min(sub, dmg)
        if sub - dmg <= 0:
            dfn.vol.pop("sub")
        else:
            dfn.vol["sub"] = sub - dmg
        return -done  # 음수: 대타출동이 맞음
    if dfn.ability == "disguise" and not dfn.perm.get("busted") and att.ability not in MOLD \
            and dfn.species.startswith("mimikyu"):
        dfn.perm["busted"] = True
        dfn.hp = max(0, dfn.hp - dfn.max_hp // 8)
        return 0
    full = dfn.hp == dfn.max_hp
    special = False
    if dmg >= dfn.hp:
        if full and (item(dfn) == "focussash" or (dfn.ability == "sturdy" and att.ability not in MOLD)):
            dmg, special = dfn.hp - 1, True
            if item(dfn) == "focussash":
                _consume(s, dfn, ev, dside)
        elif dfn.vol.get("endure"):
            dmg, special = dfn.hp - 1, True
        elif item(dfn) == "focusband" and _proc(rng, dside, 10):
            dmg, special = dfn.hp - 1, True
    dmg = min(dmg, dfn.hp)
    dfn.hp -= dmg
    if dmg > 0:
        dfn.vol["damaged"] = True
        dfn.vol["taken"] = (mv["cat"], dmg)
        dfn.perm["hits"] = dfn.perm.get("hits", 0) + 1
        if dfn.hp > 0:
            _check_berry(s, dfn, ev)
        if RESIST_BERRIES.get(item(dfn)) == move_type(att, mid, s) and dfn.hp >= 0:
            _consume(s, dfn, ev, dside)
        if item(dfn) == "airballoon":
            _consume(s, dfn, ev, dside)
        if dfn.status == "얼음" and (move_type(att, mid, s) == "fire" or mv.get("thawsTarget")):
            dfn.status = NONE
        dfn.vol["hitby"] = True
    if special:
        dfn.vol["survived"] = True
    return dmg


def _after_hit_defender(s: State, att: BMon, dfn: BMon, mid: str, mv: dict, aside: int, rng, ev,
                        crit: bool, total: int) -> None:
    dab = dfn.ability
    mtype = move_type(att, mid, s)
    if dfn.hp > 0 and total > 0:
        if dab == "stamina":
            boost(s, dfn, {"def": 1})
        if dab == "weakarmor" and mv["cat"] == "P":
            boost(s, dfn, {"def": -1, "spe": 2})
        if dab == "justified" and mtype == "dark":
            boost(s, dfn, {"atk": 1})
        if dab == "thermalexchange" and mtype == "fire":
            boost(s, dfn, {"atk": 1})
        if dab == "rattled" and mtype in ("dark", "bug", "ghost"):
            boost(s, dfn, {"spe": 1})
        if dab == "angerpoint" and crit:
            boost(s, dfn, {"atk": 12})
        if dab == "electromorphosis":
            dfn.vol["charge"] = True
    if total > 0:
        if dab == "spicyspray":
            inflict(s, att, "화상", rng, dfn)
        if dab == "toxicdebris" and mv["cat"] == "P":
            sd = s.sides[aside]
            sd["tspikes"] = min(2, sd.get("tspikes", 0) + 1)
        if dab == "seedsower":
            set_terrain(s, "grassy", dfn)
        if dab == "sandspit":
            set_weather(s, "sand", dfn)
        if dab == "cursedbody" and _proc(rng, 1 - aside, 30):
            pass


def use_move(s: State, side: int, idx: int, rng, ev=None, acts=None, moved=None) -> None:
    me, foe = s.mon(side), s.mon(1 - side)
    if me.hp <= 0:
        return
    if me.vol.pop("flinch", False):
        if me.ability == "steadfast":
            boost(s, me, {"spe": 1})
        return
    if me.vol.pop("recharge", None) is not None:
        return
    mid = "struggle" if idx < 0 or idx >= len(me.moves) else me.moves[idx]
    # 상태이상·혼란
    if me.status == "잠듦":
        me.slp -= 2 if me.ability == "earlybird" else 1
        if me.slp <= 0:
            me.status = NONE
        elif mid not in ("sleeptalk", "snore"):
            _clear_charge(me)
            return
    elif me.status == "얼음":
        me.frz -= 1
        if me.frz <= 0 or (not _mean(rng) and rng.random() < 0.25):
            me.status = NONE
        else:
            return
    if me.status == "마비" and not _mean(rng) and rng.random() < 1 / 8:
        _clear_charge(me)
        return
    if me.vol.get("conf"):
        me.vol["conf"] -= 1
        if me.vol["conf"] <= 0:
            me.vol.pop("conf")
        elif not _mean(rng) and rng.random() < 1 / 3:
            a = me.stats[1] * stage_mult(me.stages[0])
            d = me.stats[2] * stage_mult(me.stages[1])
            me.hp = max(0, me.hp - ((22 * 40 * int(a) // max(1, int(d))) // 50 + 2))
            return
    if me.status == "잠듦" and mid == "sleeptalk":
        opts = [m for m in me.moves if m not in ("sleeptalk", "snore", "focuspunch")
                and m not in TWO_TURN_SEMI | TWO_TURN_CHARGE]
        if not opts:
            return
        mid = opts[0] if _mean(rng) else rng.choice(opts)
        idx = me.moves.index(mid) if mid in me.moves else idx
    mv = move_data(mid)
    if ev is not None:
        ev.append(("used", side, me.species, mid))
    me.vol["lastmove"] = idx
    if item(me) == "choicescarf" and "choice" not in me.vol and idx >= 0:
        me.vol["choice"] = idx
    # 2턴 기술
    if mid in TWO_TURN_SEMI | TWO_TURN_CHARGE and not (me.vol.get("charging") or me.vol.get("semi")):
        w = eff_weather(s, me)
        if not ((mid in ("solarbeam", "solarblade") and w == "sun") or (mid == "electroshot" and w == "rain")):
            if mid in ("meteorbeam", "electroshot"):
                boost(s, me, {"spa": 1})
            if mid == "skullbash":
                boost(s, me, {"def": 1})
            if item(me) == "powerherb":
                _consume(s, me, ev, side)
            else:
                me.vol["semi" if mid in TWO_TURN_SEMI else "charging"] = idx
                return
    me.vol.pop("charging", None)
    me.vol.pop("semi", None)
    # 위력 조건이 있는 기술
    if mid in ("fakeout", "firstimpression") and me.vol.get("turns", 0) > 0:
        return
    if mid in ("suckerpunch", "thunderclap", "upperhand"):
        fa = acts[1 - side] if acts else ("switch", 0)
        fm = foe.moves[fa[1]] if fa[0] == "move" and 0 <= fa[1] < len(foe.moves) else None
        ok = fm is not None and not (moved and moved[1 - side]) and not is_status_move(fm)
        if mid == "upperhand":
            ok = ok and move_data(fm)["pri"] > 0
        if not ok:
            return
    if mid == "focuspunch" and me.vol.get("damaged"):
        return
    if mid == "poltergeist" and not foe.item:
        return
    if mid == "belch" and not me.perm.get("ateberry"):
        return
    if mid in ("doubleshock", "burnup"):
        t = "electric" if mid == "doubleshock" else "fire"
        if t not in me.types:
            return
    if mid == "steelroller" and not s.terrain:
        return
    if mid == "snore" and me.status != "잠듦":
        return
    # 특성: 변환자재, 배틀스위치, 질풍날개·심술꾸러기 표시
    if me.ability in ("protean", "libero") and not me.vol.get("protean") and mid != "struggle":
        me.types = (move_type(me, mid, s),)
        me.vol["protean"] = True
    if me.ability == "stancechange" and me.species.startswith("aegislash"):
        to = "aegislash" if mid == "kingsshield" else ("aegislashblade" if mv["cat"] != "Z" else None)
        if to and to != me.species and to in SPECIES:
            me.species = to
            me.stats = _stats(to, me.spread.key())
    me.vol["prankster"] = me.ability == "prankster" and mv["cat"] == "Z"
    me.vol["galewings"] = me.ability == "galewings" and mv["type"] == "flying" and me.hp == me.max_hp
    if mv["cat"] == "Z":
        _status_move(s, side, mid, mv, rng, ev)
        return
    _attack(s, side, mid, mv, rng, ev, moved)


def _clear_charge(m: BMon) -> None:
    for k in ("charging", "semi", "locked"):
        m.vol.pop(k, None)


def _attack(s: State, side: int, mid: str, mv: dict, rng, ev, moved) -> None:
    me, foe = s.mon(side), s.mon(1 - side)
    if foe.hp <= 0:
        return
    mtype = move_type(me, mid, s)
    # 방어
    me.vol.pop("bypassprotect", None)
    if _protect_blocks(foe, mid, mv):
        if "contact" in _flags(mv) and me.ability in ("unseenfist", "piercingdrill"):
            me.vol["bypassprotect"] = True
        else:
            p = foe.vol.get("protect")
            if "contact" in _flags(mv) and me.ability != "longreach":
                if p == "spikyshield":
                    chip(s, me, 1 / 8)
                elif p == "kingsshield":
                    boost(s, me, {"atk": -1}, by_foe=True)
                elif p == "banefulbunker":
                    inflict(s, me, "독", rng, foe)
                elif p == "silktrap":
                    boost(s, me, {"spe": -1}, by_foe=True)
                elif p == "burningbulwark":
                    inflict(s, me, "화상", rng, foe)
            if mv.get("hasCrashDamage"):
                chip(s, me, 0.5)
            return
    if foe.vol.get("semi") is not None and me.ability != "noguard" and foe.ability != "noguard":
        semi = foe.moves[foe.vol["semi"]] if foe.vol["semi"] < len(foe.moves) else ""
        hits_semi = (semi == "dig" and mid in ("earthquake", "magnitude")) or (
            semi in ("fly", "bounce") and mid in ("thunder", "hurricane", "skyuppercut")) or (
            semi == "dive" and mid in ("surf", "whirlpool"))
        if not hits_semi:
            return
    if _immune(s, me, foe, mid, mv, mtype, ev, 1 - side):
        if mv.get("hasCrashDamage"):
            chip(s, me, 0.5)
        return
    eff = type_eff(me, foe, mid, mtype) if mtype != "???" else 1.0
    if eff == 0 and not mv.get("ohko") and mid not in ("seismictoss", "nightshade"):
        return
    if mv.get("ohko"):
        if (foe.ability == "sturdy" and me.ability not in MOLD) or (mid == "sheercold" and "ice" in foe.types):
            return
    if not _hit(rng, side, accuracy(me, foe, mid, s)):
        if mv.get("hasCrashDamage"):
            chip(s, me, 0.5)
        return
    if mid in SCREEN_BREAK:
        for k in ("reflect", "lightscreen", "auroraveil"):
            s.sides[1 - side].pop(k, None)
    snap = (me.copy(), foe.copy(), s.copy()) if ev is not None else None
    hits = n_hits(me, mid, rng)
    total = 0
    crit_any = False
    sub_hit = False
    for h in range(1, hits + 1):
        if foe.hp <= 0 or me.hp <= 0:
            break
        if mid == "tripleaxel" and h > 1 and not _mean(rng) and not _hit(rng, side, accuracy(me, foe, mid, s)):
            break
        cc = crit_chance(me, foe, mid)
        crit = cc >= 1 or (not _mean(rng) and rng.random() < cc)
        roll = 92 if _mean(rng) else rng.randint(85, 100)
        dmg = damage(me, foe, mid, roll, crit, s, side, hit=h)
        if dmg <= 0:
            break
        done = _deal(s, me, foe, mid, mv, dmg, side, rng, ev, crit)
        if done < 0:
            sub_hit = True
            total += -done
        else:
            total += done
            crit_any |= crit
            if "contact" in _flags(mv):
                _contact_effects(s, me, foe, side, rng, ev)
    if ev is not None and total > 0 and not sub_hit:
        unusual = crit_any or hits > 1 or bool(foe.vol.get("survived")) or snap[1].vol.get("sub") is not None
        ev.append(("hit", side, mid, snap[0], snap[1], total, unusual, snap[2]))
    if total <= 0:
        return
    if not sub_hit:
        _after_hit_defender(s, me, foe, mid, mv, side, rng, ev, crit_any, total)
    # 공격자 측 후처리
    if mv.get("recoil") and me.ability not in ("rockhead", "magicguard"):
        r = mv["recoil"]
        me.hp = max(0, me.hp - max(1, round(total * r[0] / r[1])))
    if mid == "struggle":
        me.hp = max(0, me.hp - max(1, me.max_hp // 4))
    if mv.get("mindBlownRecoil"):
        chip(s, me, 0.5)
    if mv.get("drain"):
        d = mv["drain"]
        amt = max(1, round(total * d[0] / d[1] * (1.3 if item(me) == "bigroot" else 1)))
        if foe.ability == "liquidooze":
            chip(s, me, amt / me.max_hp)
        else:
            heal(me, amt)
    if item(me) == "shellbell" and total > 0:
        heal(me, total // 8)
    sheer = me.ability == "sheerforce" and mv.get("secondaries")
    if item(me) == "lifeorb" and not sheer and me.ability != "magicguard":
        me.hp = max(0, me.hp - max(1, me.max_hp // 10))
        if ev is not None:
            ev.append(("item", side, me.species, "lifeorb"))
    if me.hp > 0:
        _check_berry(s, me, ev)
    if mv.get("self", {}).get("boosts") and not sheer:
        boost(s, me, mv["self"]["boosts"])
    if mv.get("selfBoost", {}).get("boosts"):
        boost(s, me, mv["selfBoost"]["boosts"])
    if mv.get("self", {}).get("volatileStatus") == "mustrecharge":
        me.vol["recharge"] = me.vol.get("lastmove", 0)
    if mv.get("self", {}).get("volatileStatus") == "lockedmove":
        if "locked" not in me.vol:  # 2~3턴 연속 사용 후 혼란
            me.vol["locked"] = (me.vol.get("lastmove", 0), 1 if _mean(rng) else rng.choice((1, 2)))
        else:
            i, rem = me.vol["locked"]
            if rem <= 1:
                me.vol.pop("locked")
                if me.ability != "owntempo":
                    me.vol["conf"] = 2 if _mean(rng) else rng.randint(2, 5)
            else:
                me.vol["locked"] = (i, rem - 1)
    if mid in ("doubleshock", "burnup"):
        t = "electric" if mid == "doubleshock" else "fire"
        me.types = tuple(x for x in me.types if x != t) or ("???",)
    # 부가 효과
    if foe.hp > 0 and not sub_hit and not sheer and foe.ability != "shielddust" and item(foe) != "covertcloak":
        for sec in mv.get("secondaries", ()):
            ch = sec.get("chance", 100) * (2 if me.ability == "serenegrace" else 1)
            if not _proc(rng, side, ch):
                continue
            if sec.get("status"):
                inflict(s, foe, STATUS_SHORT.get(sec["status"], sec["status"]), rng, me)
            vs = sec.get("volatileStatus")
            if vs == "flinch" and not (moved and moved[1 - side]) and foe.ability != "innerfocus":
                foe.vol["flinch"] = True
            elif vs == "confusion" and foe.ability != "owntempo" and "conf" not in foe.vol:
                foe.vol["conf"] = 3 if _mean(rng) else rng.randint(2, 5)
            if sec.get("boosts"):
                boost(s, foe, sec["boosts"], by_foe=True, ev=ev, side=1 - side)
            if sec.get("self", {}).get("boosts"):
                boost(s, me, sec["self"]["boosts"])
        if item(me) == "kingsrock" and not (moved and moved[1 - side]) and _proc(rng, side, 10) \
                and foe.ability != "innerfocus":
            foe.vol["flinch"] = True
    elif sheer is False and foe.hp <= 0:
        for sec in mv.get("secondaries", ()):
            if sec.get("self", {}).get("boosts") and _proc(rng, side, sec.get("chance", 100)):
                boost(s, me, sec["self"]["boosts"])
    # 기술 고유 효과
    if mid == "knockoff" and foe.item and not ITEMS.get(foe.item, {}).get("megaStone") and foe.hp >= 0:
        if ev is not None:
            ev.append(("itemlost", 1 - side, foe.species))
        foe.item = ""
        if foe.ability == "unburden":
            foe.vol["unburden"] = True
    if mid in ("thief", "covet") and not me.item and foe.item and not ITEMS.get(foe.item, {}).get("megaStone"):
        me.item, foe.item = foe.item, ""
    if mid in ("rapidspin", "mortalspin"):
        for k in ("sr", "spikes", "tspikes", "web"):
            s.sides[side].pop(k, None)
        me.vol.pop("seeded", None)
        if mid == "rapidspin":
            boost(s, me, {"spe": 1})
        elif foe.hp > 0:
            inflict(s, foe, "독", rng, me)
    if mid in ("icespinner", "steelroller"):
        s.field.pop("terrain", None)
    if mid == "clearsmog" and foe.hp > 0:
        foe.stages = [0] * 7
    if mid == "ceaselessedge":
        s.sides[1 - side]["spikes"] = min(3, s.sides[1 - side].get("spikes", 0) + 1)
    if mid == "stoneaxe":
        s.sides[1 - side]["sr"] = True
    if mv.get("selfdestruct") or mid == "finalgambit":
        me.hp = 0
    if foe.hp <= 0:
        if me.ability == "moxie":
            boost(s, me, {"atk": 1})
        elif me.ability == "eelevate":
            best = max(range(1, 6), key=lambda i: me.stats[i])
            boost(s, me, {SK[best - 1]: 1})
        if foe.vol.get("destinybond"):
            me.hp = 0
    # 교체 효과
    if foe.hp > 0 and me.hp > 0:
        if item(foe) == "redcard" and not sub_hit:
            _consume(s, foe, ev, 1 - side)
            if me.ability != "suctioncups" and me.ability != "guarddog":
                j = best_bench(s, side, rng, forced=True)
                if j is not None:
                    switch_in(s, side, j, ev)
                    return
        if item(foe) == "ejectbutton" and not sub_hit:
            j = best_bench(s, 1 - side, rng)
            if j is not None:
                _consume(s, foe, ev, 1 - side)
                switch_in(s, 1 - side, j, ev)
        elif foe.ability in ("emergencyexit", "wimpout") and foe.hp * 2 <= foe.max_hp < 2 * (foe.hp + total):
            j = best_bench(s, 1 - side, rng)
            if j is not None:
                switch_in(s, 1 - side, j, ev)
    if mv.get("forceSwitch") and foe.hp > 0 and s.mon(1 - side) is foe and foe.ability not in (
            "suctioncups", "guarddog") and not foe.vol.get("ingrain"):
        j = best_bench(s, 1 - side, rng, forced=True)
        if j is not None:
            switch_in(s, 1 - side, j, ev)
    if mv.get("selfSwitch") and me.hp > 0 and s.mon(side) is me:
        j = best_bench(s, side, rng)
        if j is not None:
            switch_in(s, side, j, ev)


def _status_move(s: State, side: int, mid: str, mv: dict, rng, ev) -> None:
    me, foe = s.mon(side), s.mon(1 - side)
    tgt_foe = mv["target"] in FOE_TARGETS
    if tgt_foe:
        if foe.hp <= 0:
            return
        if _protect_blocks(foe, mid, mv):
            return
        if foe.ability == "magicbounce" and me.ability not in MOLD:
            me, foe = foe, me  # 반사: 역할을 바꿔 다시 적용
            side = 1 - side
        if _immune(s, me, foe, mid, mv, mv["type"], ev, 1 - side):
            return
        if foe.vol.get("sub") and "sound" not in _flags(mv) and me.ability != "infiltrator" and mid not in (
                "roar", "whirlwind"):
            return
        if not _hit(rng, side, accuracy(me, foe, mid, s)):
            return
    if mid == "rest":
        if me.hp == me.max_hp or me.status == "잠듦" or me.ability in ("insomnia", "vitalspirit", "comatose"):
            return
        me.status, me.slp, me.hp, me.tox = "잠듦", 3, me.max_hp, 0  # 2턴 잠든 뒤 3턴째 행동
        return
    st = mv.get("status")
    if st:
        target = foe if tgt_foe else me
        stk = STATUS_SHORT.get(st, st)
        if mid == "thunderwave" and effectiveness("electric", target.types) == 0:
            return
        inflict(s, target, stk, rng, me)
    if mv.get("boosts"):
        if tgt_foe:
            if mid == "strengthsap":
                amt = int(foe.stats[1] * stage_mult(foe.stages[0]))
                heal(me, amt)
            boost(s, foe, mv["boosts"], by_foe=True, ev=ev, side=1 - side)
        else:
            boost(s, me, mv["boosts"])
    vs = mv.get("volatileStatus")
    if vs:
        _volatile(s, side, me, foe, mid, vs, rng)
    if mv.get("heal"):
        h = mv["heal"]
        frac = h[0] / h[1]
        if mid in ("moonlight", "morningsun", "synthesis"):
            w = eff_weather(s, me)
            frac = 2 / 3 if w == "sun" else 0.25 if w in ("rain", "sand", "snow") else 0.5
        if mid == "shoreup" and eff_weather(s) == "sand":
            frac = 2 / 3
        heal(me, int(me.max_hp * frac))
    if mid == "roost":
        me.vol["roost"] = True
    sc = mv.get("sideCondition")
    if sc:
        tside = s.sides[1 - side] if tgt_foe or sc in ("stealthrock", "spikes", "toxicspikes", "stickyweb") \
            else s.sides[side]
        key = {"stealthrock": "sr", "stickyweb": "web"}.get(sc, sc)
        if sc == "spikes":
            tside["spikes"] = min(3, tside.get("spikes", 0) + 1)
        elif sc == "toxicspikes":
            tside["tspikes"] = min(2, tside.get("tspikes", 0) + 1)
        elif sc in ("reflect", "lightscreen", "auroraveil"):
            if sc == "auroraveil" and eff_weather(s) != "snow":
                return
            tside[key] = 8 if item(me) == "lightclay" else 5
        elif sc == "tailwind":
            tside[key] = 4
        elif sc == "safeguard":
            tside[key] = 5
        elif key in ("sr", "web"):
            tside[key] = True
    if mv.get("weather"):
        w = WEATHER_SET.get(mid) or {"SunnyDay": "sun", "RainDance": "rain", "Sandstorm": "sand",
                                     "snowscape": "snow"}.get(mv["weather"], "")
        if w:
            set_weather(s, w, me)
    if mv.get("terrain") and mid in TERRAIN_SET:
        set_terrain(s, TERRAIN_SET[mid], me)
    if mv.get("pseudoWeather") == "trickroom":
        if s.field.get("trickroom"):
            s.field.pop("trickroom")
        else:
            s.field["trickroom"] = 5
    if mv.get("stallingMove"):
        n = me.vol.get("protectn", 0)
        if _mean(rng):
            ok = n == 0
        else:
            ok = rng.random() < 1 / (3 ** n)
        if ok:
            me.vol["protect" if mid != "endure" else "endure"] = mid if mid != "endure" else True
            me.vol["protectn_next"] = n + 1
        return
    if mv.get("forceSwitch") and foe.hp > 0 and foe.ability not in ("suctioncups", "guarddog"):
        j = best_bench(s, 1 - side, rng, forced=True)
        if j is not None:
            switch_in(s, 1 - side, j, ev)
        return
    _special_status(s, side, me, foe, mid, rng, ev)
    if mv.get("selfSwitch") and me.hp > 0 and s.mon(side) is me:
        keep = None
        if mid == "batonpass":
            keep = {"stages": me.stages[:], "sub": me.vol.get("sub")}
        if mid == "shedtail":
            if me.hp * 2 <= me.max_hp:
                return
            me.hp -= me.max_hp // 2
            keep = {"sub": me.max_hp // 4}
        j = best_bench(s, side, rng)
        if j is not None:
            switch_in(s, side, j, ev, keep)


def _volatile(s, side, me, foe, mid, vs, rng) -> None:
    if vs == "confusion":
        if foe.ability != "owntempo" and "conf" not in foe.vol:
            foe.vol["conf"] = 3 if _mean(rng) else rng.randint(2, 5)
    elif vs == "taunt":
        if foe.ability not in ("oblivious", "aromaveil"):
            foe.vol["taunt"] = 3
    elif vs == "encore":
        last = foe.vol.get("lastmove")
        if last is not None and last >= 0:
            foe.vol["encore"] = (last, 3)
    elif vs == "leechseed":
        if "grass" not in foe.types:
            foe.vol["seeded"] = True
    elif vs == "substitute":
        if me.hp > me.max_hp // 4 and not me.vol.get("sub"):
            me.hp -= me.max_hp // 4
            me.vol["sub"] = me.max_hp // 4
    elif vs == "yawn":
        if foe.status == NONE and "yawn" not in foe.vol and can_status(s, foe, "잠듦", me):
            foe.vol["yawn"] = 2
    elif vs == "focusenergy":
        me.vol["focusenergy"] = 2
    elif vs == "magnetrise":
        me.vol["magnetrise"] = 5
    elif vs == "aquaring":
        me.vol["aquaring"] = True
    elif vs == "ingrain":
        me.vol["ingrain"] = True
    elif vs == "destinybond":
        me.vol["destinybond"] = True
    elif vs == "charge":
        me.vol["charge"] = True
        boost(s, me, {"spd": 1})
    elif vs == "stockpile":
        boost(s, me, {"def": 1, "spd": 1})
    elif vs == "endure":
        pass
    elif vs == "attract" or vs == "torment" or vs == "disable" or vs == "imprison":
        pass
    elif vs == "gastroacid":
        foe.vol["gastro"] = True


def _special_status(s: State, side: int, me: BMon, foe: BMon, mid: str, rng, ev) -> None:
    if mid == "haze":
        me.stages = [0] * 7
        foe.stages = [0] * 7
    elif mid == "defog":
        for sd in s.sides:
            for k in ("sr", "spikes", "tspikes", "web"):
                sd.pop(k, None)
        for k in ("reflect", "lightscreen", "auroraveil", "safeguard"):
            s.sides[1 - side].pop(k, None)
        boost(s, foe, {"evasion": -1}, by_foe=True)
    elif mid == "tidyup":
        for sd in s.sides:
            for k in ("sr", "spikes", "tspikes", "web"):
                sd.pop(k, None)
    elif mid == "painsplit" and foe.hp > 0:
        avg = (me.hp + foe.hp) // 2
        me.hp, foe.hp = min(me.max_hp, avg), min(foe.max_hp, avg)
    elif mid == "bellydrum":
        if me.hp * 2 > me.max_hp:
            me.hp -= me.max_hp // 2
            boost(s, me, {"atk": 12})
    elif mid == "memento":
        boost(s, foe, {"atk": -2, "spa": -2}, by_foe=True)
        me.hp = 0
    elif mid == "curse":
        if "ghost" in me.types:
            me.hp = max(0, me.hp - me.max_hp // 2)
            foe.vol["cursed"] = True
        else:
            boost(s, me, {"atk": 1, "def": 1, "spe": -1})
    elif mid in ("trick", "switcheroo") and foe.hp > 0:
        if not ITEMS.get(foe.item, {}).get("megaStone") and not ITEMS.get(me.item, {}).get("megaStone") \
                and foe.ability != "stickyhold":
            me.item, foe.item = foe.item, me.item
            me.vol.pop("choice", None)
            foe.vol.pop("choice", None)
    elif mid == "corrosivegas" and foe.item and not ITEMS.get(foe.item, {}).get("megaStone"):
        foe.item = ""
    elif mid == "wish":
        s.sides[side]["wish"] = (2, me.max_hp // 2)
    elif mid == "healingwish":
        if any(m.hp > 0 for j, m in enumerate(s.teams[side]) if j != s.active[side]):
            me.hp = 0
            s.sides[side]["healingwish"] = True
    elif mid == "psychup":
        me.stages = foe.stages[:]
    elif mid == "skillswap":
        me.ability, foe.ability = foe.ability, me.ability
    elif mid in ("worryseed", "simplebeam", "entrainment"):
        foe.ability = {"worryseed": "insomnia", "simplebeam": "simple"}.get(mid, me.ability)
    elif mid == "roleplay":
        me.ability = foe.ability
    elif mid == "soak":
        foe.types = ("water",)
    elif mid == "acupressure":
        k = rng.choice(SK[:5]) if not _mean(rng) else "def"
        boost(s, me, {k: 2})
    elif mid in ("meanlook", "block"):
        foe.vol["trapped"] = True
    elif mid == "lifedew":
        heal(me, me.max_hp // 4)
    elif mid == "healbell":
        for m in s.teams[side]:
            if m.hp > 0:
                m.status = NONE
    elif mid in ("clangoroussoul", "noretreat"):
        if mid == "clangoroussoul":
            if me.hp * 3 <= me.max_hp:
                return
            me.hp -= me.max_hp // 3
        else:
            if me.vol.get("noretreat"):
                return
            me.vol["noretreat"] = me.vol["trapped"] = True
        boost(s, me, {"atk": 1, "def": 1, "spa": 1, "spd": 1, "spe": 1})
    elif mid == "topsyturvy" and foe.hp > 0:
        foe.stages = [-x for x in foe.stages]
    elif mid == "reflecttype":
        me.types = foe.types
    elif mid == "magicpowder" and foe.hp > 0:
        foe.types = ("psychic",)
    elif mid == "speedswap" and foe.hp > 0:
        a, b = me.stats, foe.stats
        me.stats, foe.stats = a[:5] + b[5:], b[:5] + a[5:]
    elif mid == "growth" and eff_weather(s, me) == "sun":
        boost(s, me, {"atk": 1, "spa": 1})
    elif mid == "sleeptalk":
        pass
    elif mid == "partingshot":
        pass


# ---------- 턴 진행 ----------

def _priority(s: State, side: int, act: tuple) -> float:
    if act[0] != "move":
        return 7
    m = s.mon(side)
    mid = "struggle" if act[1] < 0 or act[1] >= len(m.moves) else m.moves[act[1]]
    mv = move_data(mid)
    p = mv["pri"]
    if m.ability == "prankster" and mv["cat"] == "Z":
        p += 1
    if m.ability == "galewings" and move_type(m, mid, s) == "flying" and m.hp == m.max_hp:
        p += 1
    if m.ability == "triage" and (mv.get("drain") or mv.get("heal")):
        p += 3
    return p


def _turn_order(s: State, acts, rng) -> list[int]:
    keys = {}
    tr = bool(s.field.get("trickroom"))
    for sd in (0, 1):
        m = s.mon(sd)
        sp = speed(m, s, sd)
        if tr:
            sp = -sp
        bonus = 0
        if acts[sd][0] == "move":
            if (item(m) == "quickclaw" and _proc(rng, sd, 20)) or (m.ability == "quickdraw" and _proc(rng, sd, 30)):
                bonus = 1
            if m.ability == "stall":
                bonus = -1
        keys[sd] = (_priority(s, sd, acts[sd]), bonus, sp, rng.random())
    return sorted((0, 1), key=lambda sd: keys[sd], reverse=True)


def _end_of_turn(s: State, ev, rng) -> None:
    w = s.weather
    for side in (0, 1):
        m = s.mon(side)
        if m.hp <= 0:
            continue
        ab = m.ability
        if w == "sand" and eff_weather(s) == "sand" and not set(m.types) & {"rock", "ground", "steel"} \
                and ab not in ("sandveil", "sandrush", "sandforce", "overcoat") and item(m) != "safetygoggles":
            chip(s, m, 1 / 16)
    if w:
        s.field["wturns"] = s.field.get("wturns", 5) - 1
        if s.field["wturns"] <= 0:
            s.field.pop("weather", None)
            s.field.pop("wturns", None)
    for side in (0, 1):
        m = s.mon(side)
        sd = s.sides[side]
        if "wish" in sd:
            t, amt = sd["wish"]
            if t <= 1:
                heal(m, amt)
                sd.pop("wish")
            else:
                sd["wish"] = (t - 1, amt)
        if m.hp <= 0:
            continue
        ab, it = m.ability, item(m)
        we = eff_weather(s, m)
        if s.terrain == "grassy" and grounded(m):
            heal(m, m.max_hp // 16)
        if ab == "raindish" and we == "rain" or ab == "icebody" and we == "snow":
            heal(m, m.max_hp // 16)
        if ab == "dryskin":
            if we == "rain":
                heal(m, m.max_hp // 8)
            elif we == "sun":
                chip(s, m, 1 / 8)
        if ab == "solarpower" and we == "sun":
            chip(s, m, 1 / 8)
        if ab == "hydration" and we == "rain":
            m.status = NONE
        if ab == "shedskin" and m.status != NONE and _proc(rng, side, 33):
            m.status = NONE
        if it == "leftovers" and m.hp < m.max_hp:
            heal(m, m.max_hp // 16)
            if ev is not None:
                ev.append(("item", side, m.species, "leftovers"))
        if m.vol.get("aquaring") or m.vol.get("ingrain"):
            heal(m, m.max_hp // 16)
        if m.vol.get("seeded") and m.ability != "magicguard":
            amt = max(1, m.max_hp // 8)
            m.hp = max(0, m.hp - amt)
            foe = s.mon(1 - side)
            if foe.hp > 0:
                if m.ability == "liquidooze":
                    chip(s, foe, amt / foe.max_hp)
                else:
                    heal(foe, amt)
        if m.hp > 0 and m.ability != "magicguard":
            if ab == "poisonheal" and m.status in ("독", "맹독"):
                heal(m, m.max_hp // 8)
            elif m.status == "화상":
                m.hp -= max(1, m.max_hp // 16)
            elif m.status == "독":
                m.hp -= max(1, m.max_hp // 8)
            elif m.status == "맹독":
                m.tox += 1
                m.hp -= max(1, m.max_hp * m.tox // 16)
            if m.vol.get("cursed"):
                m.hp -= max(1, m.max_hp // 4)
            m.hp = max(0, m.hp)
        if m.hp > 0:
            _check_berry(s, m, ev)
        if "yawn" in m.vol:
            m.vol["yawn"] -= 1
            if m.vol["yawn"] <= 0:
                m.vol.pop("yawn")
                inflict(s, m, "잠듦", rng)
        for k in ("taunt", "magnetrise"):
            if k in m.vol:
                m.vol[k] -= 1
                if m.vol[k] <= 0:
                    m.vol.pop(k)
        if "encore" in m.vol:
            i, t = m.vol["encore"]
            m.vol["encore"] = (i, t - 1)
            if t - 1 <= 0:
                m.vol.pop("encore")
        if ab == "speedboost" and m.vol.get("turns", 0) >= 0 and m.hp > 0 and not m.vol.get("switchedin"):
            boost(s, m, {"spe": 1})
        for k in ("reflect", "lightscreen", "auroraveil", "tailwind", "safeguard"):
            if k in sd:
                sd[k] -= 1
                if sd[k] <= 0:
                    sd.pop(k)
    if s.terrain:
        s.field["tturns"] = s.field.get("tturns", 5) - 1
        if s.field["tturns"] <= 0:
            s.field.pop("terrain", None)
            s.field.pop("tturns", None)
    if s.field.get("trickroom"):
        s.field["trickroom"] -= 1
        if s.field["trickroom"] <= 0:
            s.field.pop("trickroom")
    for side in (0, 1):
        m = s.mon(side)
        v = m.vol
        for k in ("protect", "endure", "flinch", "damaged", "taken", "hitby", "moved", "movinglast",
                  "switchedin", "roost", "bypassprotect", "prankster", "galewings", "survived"):
            v.pop(k, None)
        if "protectn_next" in v:
            v["protectn"] = v.pop("protectn_next")
        elif "protectn" in v:
            v.pop("protectn")
        v["turns"] = v.get("turns", 0) + 1


def step(s: State, a0: tuple, a1: tuple, rng=random, events: list | None = None,
         first: int | None = None) -> State:
    """한 턴을 진행한 새 상태를 반환한다(원본은 유지). events에 관측 가능한 사건을 기록한다.
    first를 주면 둘 다 기술을 쓸 때 그 쪽이 먼저 행동한다(실제 관측된 순서 재현용)."""
    s = s.copy()
    acts = [a0, a1]
    # 메가진화(기술을 고른 경우 자동, 팀당 1회)
    for side in sorted((0, 1), key=lambda sd: speed(s.mon(sd), s, sd), reverse=True):
        m = s.mon(side)
        if acts[side][0] == "move" and m.mega_to and not s.sides[side].get("mega") and m.hp > 0:
            frm = m.species
            to = m.mega_evolve()
            s.sides[side]["mega"] = True
            if events is not None:
                events.append(("mega", side, frm, to))
            on_start(s, side, events)
    # 교체
    for side in sorted((0, 1), key=lambda sd: speed(s.mon(sd), s, sd), reverse=True):
        if acts[side][0] == "switch":
            switch_in(s, side, acts[side][1], events)
            if events is not None:
                events.append(("switch", side, s.mon(side).species))
    movers = [sd for sd in (0, 1) if acts[sd][0] == "move"]
    order = [sd for sd in _turn_order(s, acts, rng) if sd in movers]
    if first is not None and len(order) == 2:
        order = [first, 1 - first]
    if len(movers) == 2:
        if events is not None and _priority(s, 0, acts[0]) == _priority(s, 1, acts[1]):
            events.append(("first", order[0], s.mon(0).copy(), s.mon(1).copy(), s.copy()))
        s.mon(order[1]).vol["movinglast"] = True
    # 방어 연속 사용 카운터: 이번 턴에 방어를 쓰지 않으면 초기화
    moved = [False, False]
    for side in order:
        m = s.mon(side)
        if m.hp <= 0 or acts[side][0] != "move":
            moved[side] = True
            continue
        use_move(s, side, acts[side][1], rng, events, acts, moved)
        moved[side] = True
        s.mon(side).vol["moved"] = True
        if s.mon(1 - side).hp <= 0 and s.mon(side).hp <= 0:
            break
    for side in (0, 1):
        m = s.mon(side)
        if "protect" not in m.vol and "endure" not in m.vol:
            m.vol.pop("protectn_next", None)
            m.vol.pop("protectn", None)
    _end_of_turn(s, events, rng)
    s.turn += 1
    return s


def unsupported(kind: str, ids) -> list[str]:
    """시뮬레이터가 효과를 처리하지 않는 특성·도구 목록."""
    table = ABILITY_EFFECTS if kind == "ability" else ITEM_EFFECTS
    return sorted(i for i in ids if i not in table and not (kind == "item" and ITEMS.get(i, {}).get("megaStone")))
