"""
Реестр вузов платформы (TASK-025, раздел «Университеты»). Курированные метаданные +
живой счётчик чанков из индекса. Детали (документы/баллы) отвечает ассистент, если
пользователь выбрал вуз (фильтр tenant_id) — данные уже в pgvector.
"""
UNIVERSITIES = [
    {
        "id": "kbtu", "name": "KBTU", "full": "Казахстанско-Британский технический университет",
        "city": "Алматы", "model": "ЕНТ · грант", "ready": True,
        "tagline": "Технический вуз с британскими программами: IT, инженерия, нефтегаз, бизнес.",
        "highlights": ["Академполитика: GPA, пересдачи, FX/ретейк", "Правила приёма, документы, гранты",
                       "Студенческая жизнь: клубы, общежитие Jastar City", "Военная кафедра, психолог, библиотека"],
        "apply_url": "https://kbtu.edu.kz/ru/studentam/dokumenty-dlya-obuchayushchikhsya",
    },
    {
        "id": "kaznu", "name": "КазНУ", "full": "Казахский национальный университет им. аль-Фараби",
        "city": "Алматы", "model": "ЕНТ · грант (порог ≥65)", "ready": True,
        "tagline": "Крупнейший национальный университет РК, 16 факультетов, широкий выбор программ.",
        "highlights": ["Правила приёма и перечень документов", "Образовательные программы бакалавриата",
                       "Иностранным студентам", "Государственные и социальные гранты"],
        "apply_url": "https://welcome.kaznu.kz/ru",
    },
    {
        "id": "nu", "name": "Nazarbayev University", "full": "Nazarbayev University",
        "city": "Астана", "model": "NUET · IELTS · Foundation", "ready": True,
        "tagline": "Англоязычный вуз с международной моделью поступления — «зарубеж, не уезжая».",
        "highlights": ["NUET: математика + critical thinking (≥130)", "IELTS 5.5 (или TOEFL)",
                       "Foundation Year (NUFYP)", "Гранты и стипендии (в т.ч. Abay Kunanbayev)"],
        "apply_url": "https://apply.nu.edu.kz/en/admissions",
    },
]


def universities(chunk_counts: dict | None = None) -> list[dict]:
    cc = chunk_counts or {}
    return [{**u, "chunks": cc.get(u["id"], 0)} for u in UNIVERSITIES]
