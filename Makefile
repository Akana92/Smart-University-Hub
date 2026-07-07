# Smart University — dev-ярлыки (нужен GNU make; на Windows проще ./start.ps1).
.DEFAULT_GOAL := help
PORT ?= 8000

.PHONY: help up down start db test gate

help:  ## показать команды
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-8s %s\n", $$1, $$2}'

up:    ## поднять БД (pgvector, :55432)
	docker compose up -d

down:  ## остановить БД (контейнер сохраняется)
	docker compose stop

start: up  ## БД + API на http://localhost:$(PORT)  (/admin — админка)
	python -m uvicorn api.main:app --port $(PORT)

db: up  ## только база (без сервера)

test:  ## герметичные тесты (без БД/OpenAI)
	python -m pytest tests -q

gate:  ## гейт качества против baseline (0 токенов)
	python eval/gate.py
