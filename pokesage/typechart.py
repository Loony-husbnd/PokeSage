"""18타입 상성표 (공격 타입 -> {방어 타입: 배율}). 표에 없으면 1배."""
import json
import pathlib

TYPE_KO = {
    "normal": "노말", "fire": "불꽃", "water": "물", "electric": "전기", "grass": "풀",
    "ice": "얼음", "fighting": "격투", "poison": "독", "ground": "땅", "flying": "비행",
    "psychic": "에스퍼", "bug": "벌레", "rock": "바위", "ghost": "고스트", "dragon": "드래곤",
    "dark": "악", "steel": "강철", "fairy": "페어리",
}
TYPES = tuple(TYPE_KO)

CHART: dict[str, dict[str, float]] = {
    k: v for k, v in json.loads(
        (pathlib.Path(__file__).parent / "data" / "typechart.json").read_text(encoding="utf-8")).items()
    if k in TYPE_KO
}


def effectiveness(atk_type: str, def_types) -> float:
    m = 1.0
    row = CHART.get(atk_type, {})
    for t in def_types:
        m *= row.get(t, 1.0)
    return m
