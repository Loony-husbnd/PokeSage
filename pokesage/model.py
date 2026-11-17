"""포챔스 능력치 계산(레벨 50).

포챔스는 개체값이 모두 최대이고, 노력치 대신 능력 포인트(SP)를 쓴다.
 - 한 능력치 최대 32, 합계 최대 66. 1포인트마다 실수치 +1.
 - HP = 종족값 + SP + 75, 그 외 = floor((종족값 + SP + 20) × 성격 보정 1.1/0.9)
 - 본가 노력치 환산: SP = (노력치 + 4) // 8 (252 → 32)
"""
from __future__ import annotations

STATS = ("hp", "atk", "def", "spa", "spd", "spe")
STAT_KO = {"hp": "HP", "atk": "공격", "def": "방어", "spa": "특공", "spd": "특방", "spe": "스피드"}
SP_MAX, SP_TOTAL = 32, 66


class Spread:
    """능력 포인트 배분과 성격(상승·하락 능력치)."""

    __slots__ = ("sp", "plus", "minus", "label")

    def __init__(self, sp=(0, 0, 0, 0, 0, 0), plus: str | None = None, minus: str | None = None,
                 label: str = ""):
        sp = tuple(int(x) for x in sp)
        if len(sp) != 6 or any(x < 0 or x > SP_MAX for x in sp) or sum(sp) > SP_TOTAL:
            raise ValueError(f"능력 포인트는 능력치당 0~{SP_MAX}, 합계 {SP_TOTAL} 이하여야 합니다: {sp}")
        if plus == minus:
            plus = minus = None
        self.sp, self.plus, self.minus = sp, plus, minus
        self.label = label or self.describe()

    def key(self) -> tuple:
        return (self.sp, self.plus, self.minus)

    def __eq__(self, o):
        return isinstance(o, Spread) and self.key() == o.key()

    def __hash__(self):
        return hash(self.key())

    def __repr__(self):
        return f"Spread({self.describe()})"

    def describe(self) -> str:
        parts = [f"{STAT_KO[s]}{v}" for s, v in zip(STATS, self.sp) if v]
        nat = f" / {STAT_KO[self.plus]}↑{STAT_KO[self.minus]}↓" if self.plus else " / 무보정 성격"
        return (" ".join(parts) or "무투자") + nat

    def to_dict(self) -> dict:
        return {"sp": list(self.sp), "plus": self.plus, "minus": self.minus}

    @classmethod
    def from_dict(cls, d: dict) -> "Spread":
        return cls(d["sp"], d.get("plus"), d.get("minus"))


def from_evs(evs: dict, plus=None, minus=None) -> Spread:
    """본가 노력치 → 능력 포인트."""
    return Spread([min(SP_MAX, (evs.get(s, 0) + 4) // 8) if evs.get(s, 0) else 0 for s in STATS], plus, minus)


def calc_stats(bs, spread: Spread) -> tuple[int, ...]:
    out = []
    for i, s in enumerate(STATS):
        v = bs[i] + spread.sp[i]
        if s == "hp":
            out.append(v + 75)
            continue
        v += 20
        if spread.plus == s:
            v = v * 110 // 100
        elif spread.minus == s:
            v = v * 90 // 100
        out.append(v)
    return tuple(out)


def stage_mult(stage: int) -> float:
    return (2 + stage) / 2 if stage >= 0 else 2 / (2 - stage)


# ---------- 대표 배분 ----------

def _sp(h=0, a=0, b=0, c=0, d=0, s=0) -> tuple:
    return (h, a, b, c, d, s)


PRESETS = {
    "물리 어태커 (공격·스피드 32, 고집)": Spread(_sp(h=2, a=32, s=32), "atk", "spa"),
    "물리 스피드형 (공격·스피드 32, 명랑)": Spread(_sp(h=2, a=32, s=32), "spe", "spa"),
    "특수 어태커 (특공·스피드 32, 조심)": Spread(_sp(h=2, c=32, s=32), "spa", "atk"),
    "특수 스피드형 (특공·스피드 32, 겁쟁이)": Spread(_sp(h=2, c=32, s=32), "spe", "atk"),
    "내구 물리형 (HP·공격 32, 고집)": Spread(_sp(h=32, a=32, d=2), "atk", "spa"),
    "내구 특수형 (HP·특공 32, 조심)": Spread(_sp(h=32, c=32, d=2), "spa", "atk"),
    "물리 내구형 (HP·방어 32, 장난꾸러기)": Spread(_sp(h=32, b=32, d=2), "def", "spa"),
    "특수 내구형 (HP·특방 32, 신중)": Spread(_sp(h=32, d=32, b=2), "spd", "spa"),
    "무투자 (성격 무보정)": Spread(),
}
DEFAULT_PRESET = next(iter(PRESETS))
