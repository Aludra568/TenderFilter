import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Тесты работают на отдельной SQLite-базе, без Redis, LLM и внешних API.
TEST_DB = ROOT / "test.db"
if TEST_DB.exists() and not os.environ.get("_TF_TEST_DB_READY"):
    # модуль может импортироваться повторно как tests.conftest — базу удаляем только один раз
    TEST_DB.unlink()
os.environ["_TF_TEST_DB_READY"] = "1"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"
os.environ["REDIS_URL"] = ""
os.environ["LLM_PROVIDER"] = "none"
os.environ["EGRUL_PROVIDER"] = "mock"
os.environ["EGRUL_PUBLIC_FNS"] = "false"  # тесты не ходят в сеть
os.environ["EIS_TOKEN"] = ""

import pytest  # noqa: E402

SAMPLES = ROOT / "samples"


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c
