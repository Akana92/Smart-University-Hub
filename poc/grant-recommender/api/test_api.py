"""
Смоук-тесты API (без поднятия сервера — через TestClient).
Запуск из папки poc/grant-recommender:  python -m api.test_api
"""
import sys

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    return cond


def main():
    ok = True

    r = client.get("/healthz").json()
    ok &= check("healthz status ok", r.get("status") == "ok")
    ok &= check(f"healthz rows>0 (={r.get('passing_scores_rows')})", (r.get("passing_scores_rows") or 0) > 0)
    ok &= check(f"healthz unis>0 (={r.get('universities')})", (r.get("universities") or 0) > 0)

    r = client.get("/v1/recommend", params={"score": 100, "profile": "математика,информатика"}).json()
    ok &= check("recommend has results", len(r.get("results", [])) > 0)
    ok &= check(f"recommend summary buckets present ({r.get('summary')})", "summary" in r)
    ok &= check("recommend disclaimer present", "disclaimer" in r)
    passes = [x for x in r["results"] if x["bucket"] == "pass"]
    ok &= check(f"recommend has ✅ options ({len(passes)})", len(passes) > 0)

    r = client.get("/v1/recommend", params={"score": 200, "profile": "математика,информатика"})
    ok &= check("recommend rejects score>140 (422)", r.status_code == 422)

    r = client.post("/v1/ask", json={"question": "у меня 100 баллов, профиль информатика, куда пройду на грант?"}).json()
    ok &= check(f"ask routes score-question -> engine B ({r.get('engine')})", r.get("engine") == "B")

    r = client.post("/v1/ask", json={"question": "как перевестись с платного на грант?", "tenant_id": "kbtu"}).json()
    ok &= check(f"ask routes doc-question -> engine A stub ({r.get('engine')})", r.get("engine") == "A")

    r = client.get("/v1/universities").json()
    ok &= check(f"universities list ({len(r)})", len(r) > 5)

    print("\nALL PASS" if ok else "\nSOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
