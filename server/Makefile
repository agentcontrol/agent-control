SHELL := /bin/bash

ALEMBIC := uv run --with alembic alembic -c alembic.ini

MSG ?= update
UP ?= head
DOWN ?= -1
SHOW ?= head
STAMP ?= head
AGENT_CONTROL_HOST ?= 0.0.0.0
AGENT_CONTROL_PORT ?= 8000
AGENT_CONTROL_DB_PORT ?= 5432
AGENT_CONTROL_DB_HOST_PORT ?= $(AGENT_CONTROL_DB_PORT)
AGENT_CONTROL_DOCKER_COMPOSE_PROJECT_NAME ?= $(notdir $(or $(PWD),$(CURDIR)))-dev

TEST_DB ?= agent_control_test
TEST_DB_ENV := env -u AGENT_CONTROL_DB_URL -u DATABASE_URL -u DB_URL AGENT_CONTROL_DB_HOST=localhost AGENT_CONTROL_DB_PORT=5432 AGENT_CONTROL_DB_USER=agent_control AGENT_CONTROL_DB_PASSWORD=agent_control AGENT_CONTROL_DB_DATABASE=$(TEST_DB) AGENT_CONTROL_DB_DRIVER=psycopg
.PHONY: help run start-dependencies test migrate alembic-migrate alembic-revision alembic-upgrade alembic-downgrade alembic-current alembic-history alembic-heads alembic-show alembic-stamp

help:
	@echo "Available targets:"
	@echo "  run                          - start FastAPI server (reload; honors AGENT_CONTROL_HOST/AGENT_CONTROL_PORT)"
	@echo "                                 local Postgres host mapping defaults to AGENT_CONTROL_DB_PORT"
	@echo "  start-dependencies           - docker compose up -d (start local dependencies; project=$(AGENT_CONTROL_DOCKER_COMPOSE_PROJECT_NAME))"
	@echo "  test                         - run server tests (uses $(TEST_DB_ENV))"
	@echo "  migrate                      - run database migrations (alembic upgrade head)"
	@echo "  alembic-migrate MSG='message'  - autogenerate alembic revision"
	@echo "  alembic-upgrade UP=head        - upgrade to revision"
	@echo "  alembic-downgrade DOWN=-1      - downgrade to revision"
	@echo "  alembic-current                - show current revision"
	@echo "  alembic-history                - show migration history"
	@echo "  alembic-heads                  - show heads"
	@echo "  alembic-show SHOW=<rev>        - show revision detail"
	@echo "  alembic-stamp STAMP=<rev>      - set head without running migrations"

migrate:
	@echo "Running database migrations..."
	$(ALEMBIC) upgrade head

alembic-migrate:
	$(ALEMBIC) revision --autogenerate -m "$(MSG)"

alembic-upgrade:
	$(ALEMBIC) upgrade $(UP)

alembic-downgrade:
	$(ALEMBIC) downgrade $(DOWN)

alembic-current:
	$(ALEMBIC) current

alembic-history:
	$(ALEMBIC) history

alembic-heads:
	$(ALEMBIC) heads

alembic-show:
	$(ALEMBIC) show $(SHOW)

alembic-stamp:
	$(ALEMBIC) stamp $(STAMP)

start-dependencies:
	AGENT_CONTROL_DB_HOST_PORT=$(AGENT_CONTROL_DB_HOST_PORT) docker compose -p $(AGENT_CONTROL_DOCKER_COMPOSE_PROJECT_NAME) -f ../docker-compose.dev.yml up -d
	@echo "Waiting for PostgreSQL to be ready..."
	@until docker compose -p $(AGENT_CONTROL_DOCKER_COMPOSE_PROJECT_NAME) -f ../docker-compose.dev.yml exec -T postgres pg_isready -U agent_control -d agent_control > /dev/null 2>&1; do \
		sleep 1; \
	done
	@echo "PostgreSQL is ready!"

test:
	$(TEST_DB_ENV) uv run --package agent-control-server pytest --cov=src --cov-report=xml:../coverage-server.xml -q

run: start-dependencies migrate run-server

run-server:
	uv run --package agent-control-server uvicorn agent_control_server.main:app --reload --host $(AGENT_CONTROL_HOST) --port $(AGENT_CONTROL_PORT)
	
