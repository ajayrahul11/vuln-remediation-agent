.PHONY: install lint fmt type test up down migrate api poll poll-watch check

install:
	uv sync --extra dev

lint:
	uv run ruff check src tests

fmt:
	uv run ruff format src tests && uv run ruff check --fix src tests

type:
	uv run mypy src

test:
	uv run pytest

up:
	docker compose up -d postgres

down:
	docker compose down -v

migrate:
	uv run alembic upgrade head

api:
	uv run uvicorn vulnagent.api.main:app --reload --port 8080

poll:
	uv run vulnagent poll

poll-watch:
	uv run vulnagent poll --watch --interval 900

check: lint type test
