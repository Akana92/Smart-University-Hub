"""
Адаптер движка B (навигатор грантов) + детерминированный парсер интента для единого
бэкенда (TASK-018, ADR-021, docs/06).

Движок B — точный SQL по историческим отсечкам ЕНТ (poc/grant-recommender/recommend.py),
переиспользуется как модуль (первый шаг интеграции A+B; целевое — баллы в общий Postgres).

Разбор «балл → куда» — Слой 1, БЕЗ LLM (0 токенов): регэксп по числу ЕНТ + словарь профильных
предметов из profile_map. Это и есть токен-экономия: массовый интент обслуживается детерминированно,
LLM (движок A) включается только на «длинный хвост».
"""
import importlib
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POC = os.path.join(ROOT, "poc", "grant-recommender")

_engine = None


def _b():
    """Ленивая загрузка движка B (не тянем его конфиги при импорте API).

    POC добавляем в КОНЕЦ sys.path (append), чтобы не перекрыть корневой пакет `api`
    одноимённым пакетом poc/grant-recommender/api (см. pytest.ini / коллизию имён)."""
    global _engine
    if _engine is None:
        if POC not in sys.path:
            sys.path.append(POC)
        _engine = importlib.import_module("recommend")
    return _engine


def available() -> bool:
    """Движок B доступен (модуль + БД грузятся без ошибок)?"""
    try:
        _b()
        return True
    except Exception:
        return False


def recommend(score, profile, city=None, budget=None):
    return _b().recommend(score, profile, city, budget)


def available_profiles() -> list[str]:
    return list(_b().PROFILE_MAP.keys())


def _subject_vocab() -> set[str]:
    """Профильные предметы из ключей profile_map (напр. {'математика','физика','химия',…})."""
    vocab: set[str] = set()
    for key in _b().PROFILE_MAP:  # ключи вида 'математика+физика'
        for s in key.split("+"):
            vocab.add(s.strip())
    return vocab


# ключевые слова интента «поступление/баллы» (детерминированно, без LLM)
_INTENT_KW = ["балл", "грант", "пройд", "поступ", "профил", "проходн", "специальност", " ент", "куда посту"]
_SCORE_RE = re.compile(r"\b(\d{2,3})\b")

# стемы предметов — ловим склонения («физики», «математике», «химии»), без морфо-библиотек
_STEMS = {
    "математика": "математ", "информатика": "информат", "физика": "физик",
    "химия": "хими", "биология": "биолог", "история": "истори",
    "география": "географ", "основы права": "основы прав",
}


def _match_subjects(q: str, vocab: set[str]) -> list[str]:
    return sorted(s for s in vocab if _STEMS.get(s, s) in q)


def parse_admission_query(question: str) -> dict:
    """
    Детерминированный разбор вопроса про поступление (Слой 1, 0 токенов).
    Возвращает: is_admission_intent, score, subjects, profile (валидная пара из карты | None).
    """
    q = (question or "").lower()
    score = None
    for m in _SCORE_RE.finditer(q):
        v = int(m.group(1))
        if 10 <= v <= 140:  # реалистичный диапазон балла ЕНТ
            score = v
            break

    try:
        vocab = _subject_vocab()
        pmap = _b().PROFILE_MAP
        norm = _b().norm_profile
    except Exception:  # движок B недоступен → интент не разбираем, уйдёт в движок A
        return {"is_admission_intent": False, "score": score, "subjects": [], "profile": None}

    subjects = _match_subjects(q, vocab)
    kw = any(k in q for k in _INTENT_KW)
    is_intent = bool(score) and (bool(subjects) or kw)

    # собрать валидную пару-профиль из найденных предметов
    profile = None
    if len(subjects) >= 2:
        cand = norm(",".join(subjects))
        if cand in pmap:
            profile = cand
        else:  # найти любую известную пару, целиком покрытую найденными предметами
            found = set(subjects)
            for key in pmap:
                if set(key.split("+")).issubset(found):
                    profile = key
                    break
    return {"is_admission_intent": is_intent, "score": score, "subjects": subjects, "profile": profile}
