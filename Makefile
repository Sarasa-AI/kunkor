SHELL := /bin/bash
ROOT_DIR := $(CURDIR)
VENV ?= $(ROOT_DIR)/.venv
PYTHON := $(if $(wildcard $(VENV)/bin/python),$(VENV)/bin/python,python3)
RUFF := $(if $(wildcard $(VENV)/bin/ruff),$(VENV)/bin/ruff,ruff)
MYPY := $(if $(wildcard $(VENV)/bin/mypy),$(VENV)/bin/mypy,mypy)
PYTEST := $(if $(wildcard $(VENV)/bin/pytest),$(VENV)/bin/pytest,pytest)

.PHONY: up down lint typecheck test authz-matrix import-check migrate migrate-check seed-dev check

up:
	docker compose up -d --build

down:
	docker compose down

lint:
	cd $(ROOT_DIR)/services/api && $(RUFF) check .
	cd $(ROOT_DIR)/apps/web && npm run lint

typecheck:
	cd $(ROOT_DIR)/services/api && $(MYPY) app
	cd $(ROOT_DIR)/apps/web && npm run typecheck

test:
	cd $(ROOT_DIR)/services/api && $(PYTEST)

authz-matrix:
	PYTHONPATH=$(ROOT_DIR)/services/api $(PYTHON) $(ROOT_DIR)/services/api/scripts/check_authz_matrix.py

import-check:
	PYTHONPATH=$(ROOT_DIR)/services/api $(PYTHON) $(ROOT_DIR)/services/api/scripts/check_imports.py

migrate:
	$(PYTHON) $(ROOT_DIR)/services/api/scripts/migrate.py

migrate-check:
	$(PYTHON) $(ROOT_DIR)/services/api/scripts/migrate_check.py

seed-dev:
	$(PYTHON) $(ROOT_DIR)/services/api/scripts/seed_dev.py

check: lint typecheck test authz-matrix import-check
	@echo "All verification checks passed successfully."
