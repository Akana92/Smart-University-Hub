"""
Pytest-обёртка над смоук-тестами POC движка B (P0-4: единая точка запуска тестов).
Сам набор проверок живёт в poc/grant-recommender/api/test_api.py (11 чеков, exit code 0/1);
здесь он запускается subprocess'ом с корректным cwd, чтобы `pytest tests/` покрывал и его.
"""
import os
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def test_poc_engine_b_api_smoke():
    cwd = os.path.join(ROOT, "poc", "grant-recommender")
    env = dict(os.environ, PYTHONUTF8="1")
    env.pop("DATABASE_URL", None)  # движок B (POC) работает на СВОЁМ SQLite, не на общем Postgres движка A
    p = subprocess.run(
        [sys.executable, "-m", "api.test_api"],
        cwd=cwd, env=env, capture_output=True, text=True, timeout=300,
    )
    assert p.returncode == 0, f"POC smoke failed:\n{p.stdout}\n{p.stderr}"
    assert "ALL PASS" in p.stdout
