import pytest

from pokesage.engine import Engine, EngineError, find_showdown


@pytest.fixture(scope="session")
def eng():
    try:
        find_showdown()
    except EngineError:
        pytest.skip("Showdown 빌드가 없습니다 (bash engine/setup.sh)")
    e = Engine(workers=2)
    yield e
    e.close()
