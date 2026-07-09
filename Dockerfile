# Smart University — образ рантайма (FastAPI API + встроенный веб-UI на / и /admin).
#
# Движок B (навигатор грантов), клик-FAQ, реестр вузов и таблица сравнения работают БЕЗ ключа.
# Для ответов AI-советника (движок A) задайте OPENAI_API_KEY в .env — иначе ассистент честно
# скажет «недоступен», а всё остальное продолжит работать.
#
# Собирается и запускается через docker compose (см. docker-compose.yml): образ приложения +
# Postgres/pgvector с уже загруженным индексом (db/seed) — переиндексация не нужна.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 1) только рантайм-зависимости (тонкий слой — быстрый и небольшой образ)
COPY requirements-app.txt .
RUN pip install -r requirements-app.txt

# 2) код + рантайм-данные (конфиги, FAQ, реестр вузов, БД навигатора движка B, веб-UI)
#    .env, .git, тесты, eval, PDF-исходники и т.п. исключены через .dockerignore
COPY . .

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
