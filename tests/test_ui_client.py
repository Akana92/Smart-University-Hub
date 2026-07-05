"""Тест чистой логики Streamlit-клиента (TASK-013): рендер кликабельных цитат."""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from ui.rag_client import CATEGORIES, citations_md  # noqa: E402


def test_citations_render_clickable_markdown():
    md = citations_md([
        {"n": 1, "label": "КС ИСМ КБТУ 51-2-25", "page": 20, "section": "9.23 GPA",
         "url": "https://kbtu.edu.kz/images/51-2-25_2025.pdf"},
    ])
    # markdown-ссылка [текст](url) с названием документа и страницей (требование ТЗ §3.3)
    assert "[КС ИСМ КБТУ 51-2-25 · стр. 20 · 9.23 GPA](https://kbtu.edu.kz/images/51-2-25_2025.pdf)" in md
    assert "Источники" in md


def test_citations_web_no_page():
    # веб-страница student_life: page_number=None → «стр.» не показываем, ссылка на URL страницы
    md = citations_md([
        {"n": 1, "label": "Психологическая служба", "page": None,
         "section": "Сервис психологического консультирования",
         "url": "https://kbtu.edu.kz/ru/studentam/psikholog"},
    ])
    assert "[Психологическая служба · Сервис психологического консультирования](https://kbtu.edu.kz/ru/studentam/psikholog)" in md
    assert "стр." not in md


def test_no_citations_empty():
    assert citations_md([]) == ""


def test_categories_map():
    assert CATEGORIES["Абитуриент"] == "abiturient"
    assert CATEGORIES["Все документы"] is None
