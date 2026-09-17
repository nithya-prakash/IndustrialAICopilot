.PHONY: up down build logs test test-live lint migrate revision shell eval eval-diagnosis

up:
	docker compose up --build

down:
	docker compose down

build:
	docker compose build

logs:
	docker compose logs -f backend

# Deliberately overrides any live-provider config from the developer's own
# .env (e.g. a local Ollama LLM_BASE_URL) so `make test` stays hermetic and
# matches CI, which never sets these at all. Without this, a local .env
# pointed at a real/local model makes the "no credentials configured" tests
# exercise a live call instead and fail on unrelated assumptions (timing,
# response shape) — see docs/architecture-decisions.md.
test:
	docker compose run --rm \
		-e ANTHROPIC_API_KEY= \
		-e OPENAI_API_KEY= \
		-e LLM_API_KEY= \
		-e LLM_BASE_URL= \
		-e VISION_API_KEY= \
		backend pytest -q

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
