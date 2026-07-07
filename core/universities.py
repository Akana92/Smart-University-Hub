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

# ─────────── Мультиязычность (TASK-030): переводы по вузам и подписям таблицы ───────────
# Переопределяют поля tagline/highlights/model/compare (kk/en). Русский — канон выше; фолбэк на него.
# Наполняется постепенно (workflow-перевод), поэтому пустые словари безопасны.
UNI_I18N: dict[str, dict[str, dict]] = {
    "kbtu": {
        "kk": {
            "tagline": "Британдық бағдарламалар мен диплом қосымшасы: IT, инженерия және мұнай-газ бойынша күшті база.",
            "highlights": [
                "Академиялық саясат: GPA, қайта тапсыру, FX/ретейк",
                "Қабылдау ережелері, құжаттар, гранттар",
                "Студенттік өмір: клубтар, Jastar City жатақханасы",
                "Әскери кафедра, психолог, кітапхана"
            ],
            "model": "ЕНТ · грант",
            "compare": {
                "model": "ЕНТ + грантқа конкурс",
                "ent": "ЕНТ шегі (ГОП бойынша)",
                "language": "Орыс / қазақ / ағылшын",
                "cost": "Қабылдау жарнасы + ақылы",
                "grants": "Мемлекеттік + университеттік",
                "foundation": "Жоқ"
            }
        },
        "en": {
            "tagline": "British programs and a diploma supplement: a strong foundation in IT, engineering, and oil & gas.",
            "highlights": [
                "Academic policy: GPA, retakes, FX/retake",
                "Admission rules, documents, grants",
                "Student life: clubs, Jastar City dormitory",
                "Military department, counselor, library"
            ],
            "model": "ENT · grant",
            "compare": {
                "model": "ENT + grant competition",
                "ent": "ENT cutoff (by ГОП)",
                "language": "Russian / Kazakh / English",
                "cost": "Application fee + tuition",
                "grants": "State + university",
                "foundation": "No"
            }
        }
    },
    "kaznu": {
        "kk": {
            "tagline": "Елдегі ең үлкен мамандық таңдауы: 16 факультет және көптеген гранттық орын.",
            "highlights": [
                "Қабылдау ережелері мен құжаттар тізбесі",
                "Бакалавриаттың білім беру бағдарламалары",
                "Шетелдік студенттерге",
                "Мемлекеттік және әлеуметтік гранттар"
            ],
            "model": "ЕНТ · грант (шегі ≥65)",
            "compare": {
                "model": "ЕНТ + грантқа конкурс",
                "ent": "≥65 (пед/агро/вет ≥60)",
                "language": "Орыс / қазақ",
                "cost": "ГОП бойынша ақылы",
                "grants": "Мемлекеттік + әлеуметтік («Қазақстан халқына»)",
                "foundation": "Жоқ"
            }
        },
        "en": {
            "tagline": "The widest choice of specialties in the country: 16 faculties and many grant-funded places.",
            "highlights": [
                "Admission rules and list of documents",
                "Bachelor's degree educational programs",
                "For international students",
                "State and social grants"
            ],
            "model": "ENT · grant (cutoff ≥65)",
            "compare": {
                "model": "ENT + grant competition",
                "ent": "≥65 (pedagogy/agro/vet ≥60)",
                "language": "Russian / Kazakh",
                "cost": "Tuition by ГОП",
                "grants": "State + social (\"Qazaqstan halqyna\")",
                "foundation": "No"
            }
        }
    },
    "nu": {
        "kk": {
            "tagline": "Халықаралық қабылдау моделі бар ағылшын тілді университет — «шетелге кетпей-ақ».",
            "highlights": [
                "NUET: математика + critical thinking (≥130)",
                "IELTS 5.5 (немесе TOEFL)",
                "Foundation Year (NUFYP)",
                "Гранттар мен стипендиялар (соның ішінде Abay Kunanbayev)"
            ],
            "model": "NUET · IELTS · Foundation",
            "compare": {
                "model": "NUET + IELTS (өз іріктеуі)",
                "ent": "NUET ≥130 · IELTS 5.5",
                "language": "Ағылшын",
                "cost": "Өтінім 5000 ₸ · Foundation ~$12 000/жыл",
                "grants": "ҚР мемлекеттік гранты + Abay Kunanbayev",
                "foundation": "Иә (NUFYP, 1 жыл)"
            }
        },
        "en": {
            "tagline": "An English-language university with an international admission model — \"study abroad without leaving home.\"",
            "highlights": [
                "NUET: math + critical thinking (≥130)",
                "IELTS 5.5 (or TOEFL)",
                "Foundation Year (NUFYP)",
                "Grants and scholarships (incl. Abay Kunanbayev)"
            ],
            "model": "NUET · IELTS · Foundation",
            "compare": {
                "model": "NUET + IELTS (own selection)",
                "ent": "NUET ≥130 · IELTS 5.5",
                "language": "English",
                "cost": "Application 5000 ₸ · Foundation ~$12 000/year",
                "grants": "RK state grant + Abay Kunanbayev",
                "foundation": "Yes (NUFYP, 1 year)"
            }
        }
    }
}
COMPARE_DIMS_I18N: dict[str, dict[str, str]] = {
    "kk": {
        "model": "Қабылдау моделі",
        "ent": "Шегі / қабылдау сынағы",
        "language": "Оқу тілі",
        "cost": "Құны / жарна",
        "grants": "Гранттар",
        "foundation": "Foundation Year"
    },
    "en": {
        "model": "Admission model",
        "ent": "Cutoff / entrance exam",
        "language": "Language of instruction",
        "cost": "Cost / fee",
        "grants": "Grants",
        "foundation": "Foundation Year"
    }
}

# локализуемые поля вуза (остальные — id/name/city/apply_url и т.п. — язык-независимы)
_UNI_L10N_FIELDS = ("tagline", "highlights", "model", "compare")


def universities(chunk_counts: dict | None = None, lang: str = "ru") -> list[dict]:
    cc = chunk_counts or {}
    out = []
    for u in UNIVERSITIES:
        card = {**u, "chunks": cc.get(u["id"], 0)}
        if lang and lang != "ru":
            tr = UNI_I18N.get(u["id"], {}).get(lang, {})
            for f in _UNI_L10N_FIELDS:
                if tr.get(f):
                    card[f] = tr[f]
        out.append(card)
    return out


def compare_dims(lang: str = "ru") -> list[dict]:
    tr = COMPARE_DIMS_I18N.get(lang, {}) if lang and lang != "ru" else {}
    return [{"key": k, "label": tr.get(k, lbl)} for k, lbl in COMPARE_DIMS]
