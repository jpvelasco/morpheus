PYTHON := uv run --python 3.12

.PHONY: bootstrap format format-check lint typecheck test-unit test-contract test-integration test-acceptance test-e2e test-coverage test-live-readonly security build gate

bootstrap:
	uv sync --python 3.12 --extra dev --frozen

format:
	$(PYTHON) ruff format src tests
	$(PYTHON) ruff check --fix src tests

format-check:
	$(PYTHON) ruff format --check src tests

lint:
	$(PYTHON) ruff check src tests

typecheck:
	$(PYTHON) mypy

test-unit:
	$(PYTHON) pytest tests/unit tests/test_*.py

test-contract:
	$(PYTHON) pytest tests/contract -m contract

test-integration:
	$(PYTHON) pytest tests/integration -m integration

test-acceptance:
	$(PYTHON) pytest tests/acceptance -m acceptance

test-e2e:
	$(PYTHON) pytest tests/e2e

test-coverage:
	$(PYTHON) pytest tests/contract tests/integration tests/e2e tests/unit tests/test_*.py tests/acceptance --cov --cov-branch --cov-report=term-missing

test-live-readonly:
	MORPHEUS_LIVE_TESTS=1 MORPHEUS_LIVE_MUTATION=0 $(PYTHON) pytest tests/live -m live

security:
	$(PYTHON) bandit -c pyproject.toml -r src
	$(PYTHON) pip-audit

build:
	uv build --offline

gate: format-check lint typecheck test-unit test-contract test-integration test-acceptance test-e2e test-coverage security build
