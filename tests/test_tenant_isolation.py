"""
Тест инварианта §2.4 (docs/00-foundation): обязательная изоляция тенантов в retrieval.
Появился по итогам аудита 2026-07-03 (P0-4), который прогоном ДОКАЗАЛ утечку:
dense-ветка занижала чужие чанки скором -1e9 вместо исключения, и при
тенанте с < k_each строк (включая несуществующий) чужие чанки попадали в выдачу.

Сценарии:
  1) обычный поиск возвращает ТОЛЬКО чанки своего тенанта;
  2) несуществующий тенант → пустая выдача (раньше: 5 чужих чанков);
  3) «маленький» тенант (строк меньше k_each=20) → без добора чужими;
  4) фильтр category не ломает изоляцию.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from retrieval.stores import SqliteHybridStore  # noqa: E402

DIM = 4


def rec(cid, tenant, text, category="student"):
    return {
        "chunk_id": cid, "tenant_id": tenant, "source": "doc.pdf", "source_url": "http://example/doc.pdf",
        "category": category, "doc_type": "academic_policy", "standard_code": "STD-1",
        "doc_version": "2025", "language": "ru", "page_number": 1,
        "section_title": "Раздел", "content_type": "text", "token_count": 5, "text": text,
    }


def build_store(tmp_path):
    st = SqliteHybridStore(str(tmp_path / "idx.db"))
    st.init_schema(DIM)
    records = [
        rec("a1", "uniA", "альфа документ про экзамен"),
        rec("a2", "uniA", "альфа правила пересдачи экзамена"),
        rec("a3", "uniA", "альфа стоимость обучения", category="abiturient"),
        rec("b1", "uniB", "бета документ про экзамен"),
        rec("b2", "uniB", "бета правила пересдачи"),
    ]
    vecs = [
        [1, 0, 0, 0],
        [0, 1, 0, 0],
        [0, 0, 1, 0],
        [1, 0, 0, 0],
        [0, 1, 0, 0],
    ]
    st.add(records, vecs)
    return st


def test_only_own_tenant_returned(tmp_path):
    st = build_store(tmp_path)
    res = st.search([1, 0, 0, 0], "экзамен", tenant_id="uniA", top_k=10)
    assert res, "поиск своего тенанта должен возвращать результаты"
    assert all(r["tenant_id"] == "uniA" for r in res), f"утечка: {[r['tenant_id'] for r in res]}"


def test_nonexistent_tenant_returns_empty(tmp_path):
    st = build_store(tmp_path)
    res = st.search([1, 0, 0, 0], "экзамен документ", tenant_id="ghost", top_k=10)
    assert res == [], f"несуществующий тенант получил чужие чанки: {[r['tenant_id'] for r in res]}"


def test_small_tenant_not_padded_with_foreign(tmp_path):
    # у uniB всего 2 чанка — раньше добор до k_each=20 тянул чужие строки uniA
    st = build_store(tmp_path)
    res = st.search([1, 0, 0, 0], "экзамен пересдача", tenant_id="uniB", top_k=10)
    assert res, "маленький тенант должен получать свои результаты"
    assert all(r["tenant_id"] == "uniB" for r in res), f"добор чужими: {[r['tenant_id'] for r in res]}"
    assert len(res) <= 2


def test_category_filter_keeps_isolation(tmp_path):
    st = build_store(tmp_path)
    res = st.search([0, 0, 1, 0], "стоимость обучения", tenant_id="uniA", top_k=10,
                    categories=["abiturient"])
    assert all(r["tenant_id"] == "uniA" and r["category"] == "abiturient" for r in res)
