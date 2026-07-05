"""
Streamlit-чат AI-ассистента студенческого офиса (ТЗ §3.3, этап 4).
Тонкий клиент → FastAPI /v1/chat (foundation §2.7). Под каждым ответом —
ОБЯЗАТЕЛЬНЫЕ кликабельные цитаты (название документа + страница).

Запуск (два сервиса):
  1) uvicorn api.main:app --port 8000        # бэкенд (нужен docker + OPENAI_API_KEY)
  2) streamlit run ui/streamlit_app.py       # интерфейс
"""
import os
import sys

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ui.rag_client import API_URL, CATEGORIES, ask_api, citations_md  # noqa: E402

st.set_page_config(page_title="Smart University — AI-ассистент", page_icon="🎓")

st.title("🎓 AI-ассистент студенческого офиса")
st.caption("Отвечаю только по официальным документам вуза, с ссылками на источники. "
           "Если данных нет — честно скажу и направлю в Студенческий офис.")

with st.sidebar:
    st.header("Настройки")
    label = st.selectbox("Категория поиска", list(CATEGORIES), index=0,
                         help="Ограничить поиск: напр. «Абитуриент» → только правила приёма.")
    category = CATEGORIES[label]
    api_url = st.text_input("Адрес API", API_URL)
    st.divider()
    st.caption("Примеры вопросов:")
    for ex in ("Как рассчитывается GPA?", "Можно ли пересдать экзамен с FX?",
               "Какие документы нужны для поступления?"):
        st.markdown(f"- {ex}")

if "messages" not in st.session_state:
    st.session_state.messages = []

for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

if prompt := st.chat_input("Задайте вопрос…"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Ищу в документах…"):
            try:
                res = ask_api(prompt, category, api_url=api_url)
            except Exception as e:  # noqa: BLE001
                err = f"⚠️ Не удалось получить ответ от бэкенда ({e}). Запущен ли `uvicorn api.main:app`?"
                st.error(err)
                st.session_state.messages.append({"role": "assistant", "content": err})
                st.stop()

        body = res["answer"] + ("\n" + citations_md(res["citations"]) if res["citations"] else "")
        st.markdown(body)
        meta = []
        if res.get("chunks_used") is not None:
            meta.append(f"фрагментов: {res['chunks_used']}")
        if res.get("latency_ms") is not None:
            meta.append(f"{res['latency_ms']} мс")
        if res.get("tokens"):
            meta.append(f"токенов: {res['tokens'].get('total')}")
        if meta:
            st.caption(" · ".join(meta))
    st.session_state.messages.append({"role": "assistant", "content": body})
