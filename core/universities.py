"""
Реестр вузов платформы (TASK-025) + структурные поля для сравнения (TASK-027).
Сравнение — детерминированная таблица (0 токенов, по ресёрчу лучше графа); нарратив
(«сравни X и Y словами») закрывает существующий кросс-вуз ассистент. Детали — в pgvector.
"""
UNIVERSITIES = [
    {
        "id": "kbtu", "name": "KBTU", "full": "Казахстанско-Британский технический университет",
        "city": "Алматы", "model": "ЕНТ · грант", "ready": True,
        "tagline": "Британские программы и диплом-приложение: сильная база по IT, инженерии и нефтегазу.",
        "highlights": ["Академполитика: GPA, пересдачи, FX/ретейк", "Правила приёма, документы, гранты",
                       "Студенческая жизнь: клубы, общежитие Jastar City", "Военная кафедра, психолог, библиотека"],
        "apply_url": "https://kbtu.edu.kz/ru/studentam/dokumenty-dlya-obuchayushchikhsya",
        "compare": {"model": "ЕНТ + конкурс на грант", "ent": "Порог ЕНТ (по ГОП)",
                    "language": "Рус / каз / англ", "cost": "Вступительный взнос + платное",
                    "grants": "Гос. + вузовские", "foundation": "Нет"},
    },
    {
        "id": "kaznu", "name": "КазНУ", "full": "Казахский национальный университет им. аль-Фараби",
        "city": "Алматы", "model": "ЕНТ · грант (порог ≥65)", "ready": True,
        "tagline": "Самый большой выбор специальностей в стране: 16 факультетов и много грантовых мест.",
        "highlights": ["Правила приёма и перечень документов", "Образовательные программы бакалавриата",
                       "Иностранным студентам", "Государственные и социальные гранты"],
        "apply_url": "https://welcome.kaznu.kz/ru",
        "compare": {"model": "ЕНТ + конкурс на грант", "ent": "≥65 (пед/агро/вет ≥60)",
                    "language": "Рус / каз", "cost": "Платное по ГОП",
                    "grants": "Гос. + соц. («Қазақстан халқына»)", "foundation": "Нет"},
    },
    {
        "id": "nu", "name": "Nazarbayev University", "full": "Nazarbayev University",
        "city": "Астана", "model": "NUET · IELTS · Foundation", "ready": True,
        "tagline": "Англоязычный вуз с международной моделью поступления — «зарубеж, не уезжая».",
        "highlights": ["NUET: математика + critical thinking (≥130)", "IELTS 5.5 (или TOEFL)",
                       "Foundation Year (NUFYP)", "Гранты и стипендии (в т.ч. Abay Kunanbayev)"],
        "apply_url": "https://apply.nu.edu.kz/en/admissions",
        "compare": {"model": "NUET + IELTS (свой отбор)", "ent": "NUET ≥130 · IELTS 5.5",
                    "language": "Английский", "cost": "Заявка 5000 ₸ · Foundation ~$12 000/год",
                    "grants": "Гос-грант РК + Abay Kunanbayev", "foundation": "Да (NUFYP, 1 год)"},
    },
]

# порядок строк сравнительной таблицы: (ключ, подпись)
COMPARE_DIMS = [
    ("model", "Модель поступления"), ("ent", "Порог / вступительное"),
    ("language", "Язык обучения"), ("cost", "Стоимость / взнос"),
    ("grants", "Гранты"), ("foundation", "Foundation Year"),
]


def universities(chunk_counts: dict | None = None) -> list[dict]:
    cc = chunk_counts or {}
    return [{**u, "chunks": cc.get(u["id"], 0)} for u in UNIVERSITIES]


def compare_dims() -> list[dict]:
    return [{"key": k, "label": lbl} for k, lbl in COMPARE_DIMS]
