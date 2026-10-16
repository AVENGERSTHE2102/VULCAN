.PHONY: up down install dev-api dev-web dev-services check retest prepare offline branches
up:
	docker compose --profile prepare build task-image
	docker compose --profile prepare run --rm task-image
	docker compose up -d --build

down:
	docker compose down

install:
	uv sync --frozen
	cd frontend && npm ci

dev-api:
	PYTHONPATH=backend uv run uvicorn lab.api:app --host 127.0.0.1 --port 8000 --no-access-log

dev-web:
	cd frontend && npm run dev

dev-services:
	PYTHONPATH=backend:. uv run python scripts/dev_services.py

check:
	uv run pytest -q
	cd frontend && npm run build
	uv run python scripts/contracts.py --check

retest:
	uv run pytest -q backend/tests/test_missions.py

prepare:
	docker compose build
	docker compose --profile prepare build task-image
	docker compose --profile prepare run --rm task-image
	docker compose --profile ollama pull ollama

offline:
	docker compose -f compose.yaml -f compose.offline.yaml up -d --no-build --pull never

branches:
	uv run python scripts/branches.py
