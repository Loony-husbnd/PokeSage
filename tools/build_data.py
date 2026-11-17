"""포챔스 데이터 빌드: Showdown(포챔스 모드) + PokeAPI(한국어 이름) → pokesage/data/*.json

    python tools/build_data.py [--raw 원본 폴더] [--no-download]

원본은 GitHub에서 내려받으며(raw.githubusercontent.com), TypeScript 파일은 실행하지 않고
tsdata.py로 값만 읽는다. 결과 JSON은 저장소에 포함되므로 일반 사용자는 실행할 필요가 없다.
"""
from __future__ import annotations

import argparse
import csv
import json
import pathlib
import re
import sys
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import tsdata  # noqa: E402

SD = "https://raw.githubusercontent.com/smogon/pokemon-showdown/master"
PA = "https://raw.githubusercontent.com/PokeAPI/pokeapi/master/data/v2/csv"
FILES = {
    **{f"base/{f}.ts": f"{SD}/data/{f}.ts" for f in ("pokedex", "moves", "items", "abilities", "typechart")},
    **{f"champions/{f}.ts": f"{SD}/data/mods/champions/{f}.ts"
       for f in ("formats-data", "moves", "learnsets", "items", "abilities")},
    **{f"pokeapi/{f}.csv": f"{PA}/{f}.csv" for f in (
        "pokemon_species_names", "pokemon_forms", "pokemon_form_names", "moves", "move_names",
        "items", "item_names", "abilities", "ability_names")},
}
KO = "3"
ILLEGAL = {"Past", "Future", "LGPE", "CAP", "Unobtainable", "Gigantamax", "Custom"}
OUT = pathlib.Path(__file__).resolve().parent.parent / "pokesage" / "data"


def toid(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def download(raw: pathlib.Path) -> None:
    for rel, url in FILES.items():
        p = raw / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        print("다운로드", url)
        with urllib.request.urlopen(url, timeout=120) as r:
            p.write_bytes(r.read())


def merged(base: dict, mod: dict) -> dict:
    """포챔스 모드의 덮어쓰기(inherit)를 기본 데이터에 반영한다."""
    out = {k: dict(v) for k, v in base.items()}
    for k, v in mod.items():
        if v.get("inherit") and k in out:
            out[k].update({kk: vv for kk, vv in v.items() if kk != "inherit"})
        else:
            out[k] = {kk: vv for kk, vv in v.items() if kk != "inherit"}
    return out


def ko_table(path: pathlib.Path, id_col: str, name_col: str = "name") -> dict[str, str]:
    out = {}
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["local_language_id"] == KO and row[name_col]:
                out[row[id_col]] = row[name_col]
    return out


def ident_map(path: pathlib.Path) -> dict[str, str]:
    """PokeAPI identifier(케밥) → id 를 Showdown식 id(영숫자) 기준으로."""
    with open(path, encoding="utf-8") as f:
        return {toid(r["identifier"]): r["id"] for r in csv.DictReader(f)}


FORME_KO = {"Paldea-Combat": "팔데아 컴뱃종", "Paldea-Blaze": "팔데아 블레이즈종",
            "Paldea-Aqua": "팔데아 워터종", "Blue": "블루", "White": "화이트", "Yellow": "옐로",
            "F": "암컷", "Low-Key": "로우한 모습"}
ITEM_KO_FIX = {"leek": "대파", "roseliberry": "로셀열매"}
MEGA_BASE_FIX = {"floettemega": "floetteeternal"}
REGION = {"Alola": "알로라", "Galar": "가라르", "Hisui": "히스이", "Paldea": "팔데아"}


def species_ko(sp: dict, base_ko: dict, form_ko: dict, form_ids: dict) -> str:
    base = base_ko.get(str(sp["num"]), sp["name"])
    forme = sp.get("forme")
    if not forme:
        return base
    if "Mega" in forme:
        pre, _, suffix = forme.partition("Mega")
        tag = pre.strip("-") or suffix.lstrip("-")
        return f"메가{base}{('(' + tag + ')') if pre.strip('-') else tag}"
    if forme in FORME_KO:
        return f"{base}({FORME_KO[forme]})"
    region = next((v for k, v in REGION.items() if forme.startswith(k)), None)
    if region:
        rest = forme.split("-", 1)[1] if "-" in forme else ""
        return f"{base}({region}{' ' + rest if rest else ''})"
    fid = form_ids.get(toid(sp["name"]))
    name = form_ko.get(fid, "") if fid else ""
    if name and base in name and "의 모습" not in name:
        return name
    if name:
        return f"{base}({name.replace('의 모습', '').replace('폼', '').strip()})"
    return f"{base}({forme})"


SECONDARY_KEYS = ("chance", "status", "volatileStatus", "boosts", "self")


def move_entry(m: dict, ko: str | None) -> dict:
    cat = {"Physical": "P", "Special": "S"}.get(m["category"], "Z")
    acc = m.get("accuracy", 100)
    e = {
        "name": m["name"], "ko": ko or m["name"], "type": m["type"].lower(), "cat": cat,
        "bp": m.get("basePower", 0), "acc": 0 if acc is True else acc, "pri": m.get("priority", 0),
        "target": m.get("target", "normal"),
    }
    flags = [f for f in ("contact", "sound", "punch", "bite", "pulse", "slicing", "powder", "bullet",
                         "wind", "heal") if m.get("flags", {}).get(f)]
    if flags:
        e["flags"] = flags
    secs = m.get("secondaries") or ([m["secondary"]] if m.get("secondary") else [])
    secs = [{k: s[k] for k in SECONDARY_KEYS if k in s} for s in secs if s]
    if secs:
        e["secondaries"] = secs
    for k in ("recoil", "drain", "heal", "boosts", "status", "volatileStatus", "sideCondition",
              "weather", "terrain", "pseudoWeather", "selfSwitch", "forceSwitch", "multihit", "critRatio",
              "selfdestruct", "ohko", "willCrit", "overrideOffensiveStat", "overrideDefensiveStat",
              "overrideOffensivePokemon", "ignoreDefensive", "ignoreEvasion", "breaksProtect",
              "stallingMove", "damage", "hasCrashDamage", "mindBlownRecoil", "thawsTarget",
              "selfBoost", "slotCondition", "isFutureMove", "multiaccuracy", "noPPBoosts", "pp"):
        if k in m and m[k] not in (None, False):
            e[k] = m[k]
    if m.get("self"):
        e["self"] = {k: v for k, v in m["self"].items() if k in ("boosts", "volatileStatus")}
        if not e["self"]:
            del e["self"]
    fns = [f for f in m.get("_fns", []) if f in ("basePowerCallback", "damageCallback", "onBasePower",
                                                  "onModifyType", "onModifyMove", "onTry", "onTryHit",
                                                  "onHit", "onAfterHit", "onAfterMove", "onPrepareHit",
                                                  "onTryMove", "onDamage", "onEffectiveness", "beforeTurnCallback",
                                                  "priorityChargeCallback", "onDisableMove")]
    if fns:
        e["fns"] = fns
    if m.get("condition", {}).get("duration") and e.get("volatileStatus"):
        e["duration"] = m["condition"]["duration"]
    return e


def build(raw: pathlib.Path) -> None:
    L = lambda rel: tsdata.load(str(raw / rel))  # noqa: E731
    dex = L("base/pokedex.ts")
    fmt = L("champions/formats-data.ts")
    moves = merged(L("base/moves.ts"), L("champions/moves.ts"))
    items = merged(L("base/items.ts"), L("champions/items.ts"))
    abilities = merged(L("base/abilities.ts"), L("champions/abilities.ts"))
    learn = L("champions/learnsets.ts")
    chart = L("base/typechart.ts")
    pa = raw / "pokeapi"
    sp_ko = ko_table(pa / "pokemon_species_names.csv", "pokemon_species_id")
    form_ko = ko_table(pa / "pokemon_form_names.csv", "pokemon_form_id", "form_name")
    form_ids = ident_map(pa / "pokemon_forms.csv")
    mv_ko = ko_table(pa / "move_names.csv", "move_id")
    mv_ids = ident_map(pa / "moves.csv")
    it_ko = ko_table(pa / "item_names.csv", "item_id")
    it_ids = ident_map(pa / "items.csv")
    ab_ko = ko_table(pa / "ability_names.csv", "ability_id")
    ab_ids = ident_map(pa / "abilities.csv")

    # ----- 기술 -----
    legal_moves = {}
    for mid, m in moves.items():
        if m.get("isNonstandard") in ILLEGAL or m.get("isZ") or m.get("isMax") or "name" not in m:
            continue
        legal_moves[mid] = move_entry(m, mv_ko.get(mv_ids.get(mid, ""), None))

    # ----- 포켓몬 -----
    def legal_sp(sid):
        f = fmt.get(sid, {})
        return (sid in fmt and sid in dex and "num" in dex[sid] and "baseStats" in dex[sid] and f.get("tier") != "Illegal"
                and f.get("isNonstandard") not in ILLEGAL)

    species, learnsets = {}, {}
    for sid, sp in dex.items():
        if not legal_sp(sid):
            continue
        base_id = toid(sp.get("baseSpecies", sp["name"]))
        ls = {}
        for src in (sid, toid(sp.get("changesFrom", "")), base_id):
            ls = learn.get(src, {}).get("learnset") or {}
            if ls:
                break
        mvs = sorted(m for m in ls if m in legal_moves)
        e = {
            "name": sp["name"], "ko": species_ko(sp, sp_ko, form_ko, form_ids), "num": sp["num"],
            "types": [t.lower() for t in sp["types"]],
            "bs": [sp["baseStats"][k] for k in ("hp", "atk", "def", "spa", "spd", "spe")],
            "abilities": [toid(a) for a in sp["abilities"].values()],
            "weight": sp.get("weightkg", 0),
        }
        if sp.get("baseSpecies"):
            e["base"] = base_id
        if "Mega" in sp.get("forme", ""):
            e["mega"] = True
            e["item"] = toid(sp.get("requiredItem", ""))
        elif sp.get("requiredItem"):
            e["item"] = toid(sp["requiredItem"])
        if sp.get("battleOnly"):
            e["battleOnly"] = True
        species[sid] = e
        if not e.get("mega"):
            learnsets[sid] = mvs
    for sid, b in MEGA_BASE_FIX.items():
        if sid in species:
            species[sid]["base"] = b
    for sid, e in species.items():  # 메가진화 형태 연결
        if e.get("mega") and e.get("base") in species:
            species[e["base"]].setdefault("megas", []).append(sid)
    for sid, e in list(species.items()):
        if e.get("mega") or e.get("battleOnly"):
            continue
        if not learnsets.get(sid):
            print("경고: 습득 기술 없음", sid)

    # ----- 도구 -----
    legal_items = {}
    for iid, it in items.items():
        if it.get("isNonstandard") in ILLEGAL or "name" not in it:
            continue
        e = {"name": it["name"], "ko": it_ko.get(it_ids.get(iid, ""), it["name"])}
        if it.get("megaStone"):
            ms = it["megaStone"]
            e["megaStone"] = {toid(k): toid(v) for k, v in ms.items()} if isinstance(ms, dict) else ms
        for k in ("onPlate", "isBerry", "isChoice", "naturalGift", "fling"):
            if k in it and k in ("onPlate", "isBerry", "isChoice"):
                e[k] = it[k]
        legal_items[iid] = e
    for iid, ko in ITEM_KO_FIX.items():
        if iid in legal_items:
            legal_items[iid]["ko"] = ko
    # 메가스톤 이름 보정: "메가스톤"류의 한국어 이름이 없으면 포켓몬 이름으로 만든다
    for sid, e in species.items():
        if e.get("mega") and e.get("item") in legal_items:
            it = legal_items[e["item"]]
            if it["ko"] == it["name"]:
                base_ko = species[e["base"]]["ko"]
                suffix = it["name"].split("ite")[-1].strip() if "ite" in it["name"] else ""
                it["ko"] = f"{base_ko}나이트{(' ' + suffix) if suffix else ''}"

    # ----- 특성 -----
    used_abs = {a for e in species.values() for a in e["abilities"]}
    legal_abs = {aid: {"name": a["name"], "ko": ab_ko.get(ab_ids.get(aid, ""), a["name"])}
                 for aid, a in abilities.items() if aid in used_abs and "name" in a}

    # ----- 상성표 -----
    types = {t: {} for t in chart}
    for dt, d in chart.items():
        for at, code in d.get("damageTaken", {}).items():
            at = at.lower()
            if at in chart:
                mult = {0: 1, 1: 2, 2: 0.5, 3: 0}[code]
                if mult != 1:
                    types[at][dt] = mult

    OUT.mkdir(parents=True, exist_ok=True)
    for name, obj in (("species", species), ("moves", legal_moves), ("items", legal_items),
                      ("abilities", legal_abs), ("learnsets", learnsets), ("typechart", types)):
        (OUT / f"{name}.json").write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":"),
                                                     sort_keys=True), encoding="utf-8")
    n_base = sum(1 for e in species.values() if not e.get("mega"))
    print(f"포켓몬 {len(species)}개 항목(메가 제외 {n_base}), 기술 {len(legal_moves)}, 도구 {len(legal_items)}, "
          f"특성 {len(legal_abs)}")
    miss = [e["name"] for e in legal_moves.values() if e["ko"] == e["name"]]
    print(f"한국어 이름 없는 기술 {len(miss)}: {miss[:20]}")
    miss = [e["name"] for e in legal_abs.values() if e["ko"] == e["name"]]
    print(f"한국어 이름 없는 특성 {len(miss)}: {miss}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="raw_data")
    ap.add_argument("--no-download", action="store_true")
    o = ap.parse_args(argv)
    raw = pathlib.Path(o.raw)
    if not o.no_download:
        download(raw)
    build(raw)


if __name__ == "__main__":
    main()
