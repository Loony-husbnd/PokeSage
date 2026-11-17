"""배틀 상태 모델과 능력치 계산."""
from __future__ import annotations

from dataclasses import dataclass, field

from .dex import MOVES, POKEMON

LEVEL = 50
STATS = ("hp", "atk", "def", "spa", "spd", "spe")
STAT_KO = {"atk": "공격", "def": "방어", "spa": "특공", "spd": "특방", "spe": "스피드"}
STATUS = ("없음", "화상", "마비", "독", "맹독", "잠듦", "얼음")

# 노력치 프리셋: (stat -> EV, stat -> 성격 보정)
SPREADS = {
    "물리 공격형 (공격·스피드 252)": ({"hp": 4, "atk": 252, "spe": 252}, {"atk": 1.1}),
    "특수 공격형 (특공·스피드 252)": ({"hp": 4, "spa": 252, "spe": 252}, {"spa": 1.1}),
    "물리 내구형 (HP·방어 252)": ({"hp": 252, "def": 252, "spd": 4}, {"def": 1.1}),
    "특수 내구형 (HP·특방 252)": ({"hp": 252, "spd": 252, "def": 4}, {"spd": 1.1}),
    "무투자": ({}, {}),
}
DEFAULT_SPREAD = next(iter(SPREADS))

# 불확실한 상대 능력치의 하한/상한
MIN_SPREAD = ({}, {"def": 0.9, "spd": 0.9, "spe": 0.9})
MAX_BULK = ({"hp": 252, "def": 252, "spd": 252}, {"def": 1.1, "spd": 1.1})
MAX_SPEED = ({"spe": 252}, {"spe": 1.1})
MAX_OFFENSE = ({"atk": 252, "spa": 252}, {"atk": 1.1, "spa": 1.1})


def calc_stat(species: str, stat: str, spread: tuple[dict, dict]) -> int:
    evs, nature = spread
    idx = STATS.index(stat)
    base = POKEMON[species][1][idx]
    core = (2 * base + 31 + evs.get(stat, 0) // 4) * LEVEL // 100
    if stat == "hp":
        return core + LEVEL + 10
    return int((core + 5) * nature.get(stat, 1.0))


def stage_mult(stage: int) -> float:
    return (2 + stage) / 2 if stage >= 0 else 2 / (2 - stage)


@dataclass
class Mon:
    species: str
    spread_name: str = DEFAULT_SPREAD
    moves: list[str] = field(default_factory=list)
    hp_pct: int = 100
    status: str = "없음"
    stages: dict[str, int] = field(default_factory=lambda: {k: 0 for k in STAT_KO})

    def __post_init__(self):
        if not self.moves:
            self.moves = list(POKEMON[self.species][2])
        for m in self.moves:
            if m not in MOVES:
                raise ValueError(f"알 수 없는 기술: {m}")

    @property
    def types(self) -> tuple[str, ...]:
        return POKEMON[self.species][0]

    @property
    def spread(self) -> tuple[dict, dict]:
        return SPREADS[self.spread_name]

    @property
    def alive(self) -> bool:
        return self.hp_pct > 0

    def label(self) -> str:
        return f"{self.species} {self.hp_pct}%"
