.PHONY: up down build logs test lint migrate revision shell

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

lint:
	docker compose run --rm backend ruff check .

migrate:
	docker compose run --rm backend alembic upgrade head

revision:
	docker compose run --rm backend alembic revision --autogenerate -m "$(m)"

shell:
	docker compose run --rm backend bash
