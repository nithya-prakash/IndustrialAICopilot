.PHONY: up down build logs test test-live lint migrate revision shell eval eval-diagnosis

up:
	docker compose up --build

down:
	docker compose down

build:
	docker compose build

logs:
	docker compose logs -f backend

test:
	docker compose run --rm backend pytest -q

test-live:
	docker compose run --rm backend pytest tests/live -v

lint:
	docker compose run --rm backend ruff check .

migrate:
	docker compose run --rm backend alembic upgrade head

revision:
	docker compose run --rm backend alembic revision --autogenerate -m "$(m)"

shell:
	docker compose run --rm backend bash

eval:
	docker compose run --rm backend python -m evaluation.run

eval-diagnosis:
	docker compose run --rm backend python -m evaluation.diagnosis_eval
