.PHONY: fix lint lint/ruff lint/mypy test

fix:
	ruff check --fix .

lint: lint/ruff lint/mypy

lint/mypy:
	mypy foreman

lint/ruff:
	ruff check .

test:
	python -m pytest --cov=foreman
