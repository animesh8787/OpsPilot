.PHONY: up down demo test lint
up:
	docker compose up -d --build
down:
	docker compose down -v
demo:
	python scripts/demo.py
test:
	LLM_PROVIDER=mock python -m pytest -q
lint:
	ruff check . && ruff format --check .
