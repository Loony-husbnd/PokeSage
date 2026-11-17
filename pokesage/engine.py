"""Node 워커(Showdown 포챔스 시뮬레이터) 풀. 세계를 워커들에 나눠 병렬로 굴리고 결과를 합산한다."""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .data import ROOT

ENGINE_DIR = ROOT / "engine"


class EngineError(RuntimeError):
    pass


def find_showdown() -> Path:
    for p in (os.environ.get("POKESAGE_SHOWDOWN"), ENGINE_DIR / ".showdown"):
        if p and (Path(p) / "dist" / "sim").exists():
            return Path(p)
    raise EngineError("Showdown 빌드를 찾을 수 없습니다. `bash engine/setup.sh` 를 먼저 실행하거나 POKESAGE_SHOWDOWN 환경변수를 지정해 주십시오.")


def wilson(wins: float, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = wins / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - m) / d, (c + m) / d


@dataclass
class Result:
    choice: str          # 'move 2', 'move 2 mega', 'switch 3'
    n: int               # 굴린 판 수
    value: float         # 평균 가치(종료된 판은 승=1/패=0, 미종료는 체력 평가)
    wins: int
    ended: int

    @property
    def interval(self) -> tuple[float, float]:
        return wilson(self.value * self.n, self.n)


@dataclass
class Recommendation:
    results: list[Result]
    worlds: int
    accepted: int      # 관측과 일치한 세계 수 (히스토리가 없으면 전부)
    relaxed: int       # 끝내 일치하지 못해 그대로 쓴 세계 수

    @property
    def best(self) -> Result:
        return self.results[0]


class Engine:
    def __init__(self, workers: int | None = None):
        if shutil.which("node") is None:
            raise EngineError("Node.js 가 필요합니다 (Colab 에는 기본 설치되어 있습니다).")
        self.showdown = find_showdown()
        self.n = max(1, workers or os.cpu_count() or 1)
        env = dict(os.environ, POKESAGE_SHOWDOWN=str(self.showdown), POKESAGE_DATA=str(ROOT / "data" / "champions"))
        self.procs = [subprocess.Popen(["node", str(ENGINE_DIR / "worker.js")], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       env=env, text=True, bufsize=1) for _ in range(self.n)]
        self._seq = 0
        r = self._call(self.procs[0], {"cmd": "ping"})
        if not r.get("ok"):
            raise EngineError(r.get("error", "워커 시작 실패"))

    # -- 저수준 --
    def _send(self, p, req):
        self._seq += 1
        req["id"] = self._seq
        p.stdin.write(json.dumps(req) + "\n")
        p.stdin.flush()
        return self._seq

    def _recv(self, p, rid):
        while True:
            line = p.stdout.readline()
            if not line:
                raise EngineError("워커가 종료되었습니다.")
            r = json.loads(line)
            if r.get("id") == rid:
                if not r.get("ok"):
                    raise EngineError(r.get("error", "워커 오류"))
                return r

    def _call(self, p, req):
        return self._recv(p, self._send(p, req))

    # -- 공개 API --
    def validate(self, team: list[dict]) -> list[str]:
        """Showdown 팀 검증기(현재 규정 Reg M-C). 문제가 없으면 빈 목록."""
        return self._call(self.procs[0], {"cmd": "validate", "team": team})["problems"]

    def recommend(self, state: dict, history: list[dict] | None = None, worlds: int = 300, seed: int = 1,
                  max_turns: int = 40, tolerance: int = 2) -> Recommendation:
        ids = []
        for k, p in enumerate(self.procs):
            ids.append(self._send(p, {"cmd": "recommend", "state": state, "history": history or [], "worlds": worlds,
                                      "shard": [k, self.n], "seed": seed, "maxTurns": max_turns, "tolerance": tolerance}))
        tot: dict[str, list[float]] = {}
        accepted = relaxed = nworlds = 0
        for p, rid in zip(self.procs, ids):
            r = self._recv(p, rid)
            accepted += r["accepted"]; relaxed += r["relaxed"]; nworlds += r["worlds"]
            for c, t in r["totals"].items():
                a = tot.setdefault(c, [0, 0.0, 0, 0])
                a[0] += t["n"]; a[1] += t["sum"]; a[2] += t["wins"]; a[3] += t["ended"]
        res = [Result(c, int(a[0]), a[1] / a[0], int(a[2]), int(a[3])) for c, a in tot.items() if a[0]]
        res.sort(key=lambda x: x.value, reverse=True)
        if not res:
            raise EngineError("추천할 수 있는 행동이 없습니다. 입력한 상태를 확인해 주십시오.")
        return Recommendation(res, nworlds, accepted, relaxed)

    def close(self):
        for p in self.procs:
            try:
                p.stdin.close(); p.terminate()
            except Exception:
                pass

    def __enter__(self): return self
    def __exit__(self, *a): self.close()
