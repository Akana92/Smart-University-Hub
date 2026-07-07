"""
Детерминированное определение языка сообщения (TASK-030): 0 токенов, без LLM.
Продукт отвечает «на языке сообщения» (выбор пользователя): казах пишет по-казахски —
советник отвечает по-казахски. Эвристика: спец-буквы казахского алфавита → kk;
преобладание латиницы → en; иначе → ru (кириллица без казах-специфики).
"""
import re

# буквы, которые есть в казахском, но НЕ в русском алфавите — надёжный маркер kk
_KK_CHARS = set("әғқңөұүһі")
_CYR = re.compile(r"[а-яёіў]")
_LAT = re.compile(r"[a-z]")

SUPPORTED = ("ru", "kk", "en")


def detect_lang(text: str) -> str:
    """Вернуть 'ru' | 'kk' | 'en' по тексту сообщения. По умолчанию — 'ru'."""
    t = (text or "").lower()
    if any(ch in _KK_CHARS for ch in t):
        return "kk"
    cyr = len(_CYR.findall(t))
    lat = len(_LAT.findall(t))
    if lat > cyr and lat >= 2:
        return "en"
    return "ru"


_LANG_ALIASES = {"kaz": "kk", "qaz": "kk", "rus": "ru", "eng": "en"}


def normalize_lang(lang: str | None) -> str:
    """Привести код языка к поддерживаемому ('ru' по умолчанию). Понимает 2- и 3-буквенные коды."""
    lang = (lang or "").strip().lower()
    lang = _LANG_ALIASES.get(lang, lang[:2])
    return lang if lang in SUPPORTED else "ru"
