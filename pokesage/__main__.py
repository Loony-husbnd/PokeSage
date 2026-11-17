import argparse

from .cli import run


def main():
    ap = argparse.ArgumentParser(prog="pokesage", description="포챔스 턴별 최선수 추천")
    ap.add_argument("--worlds", type=int, default=300, help="턴마다 샘플링할 세계 수 (후보 행동마다 이만큼 판을 굴림)")
    ap.add_argument("--workers", type=int, default=None, help="Node 워커(병렬) 수. 기본은 CPU 코어 수")
    a = ap.parse_args()
    from .engine import Engine
    with Engine(workers=a.workers) as eng:
        run(eng=eng, worlds=a.worlds)


if __name__ == "__main__":
    main()
