.PHONY: fix install lint lint/ruff lint/mypy test

fix:
	ruff check --fix .

install:
	pip install -e .
	cd foreman/static && npm install

lint: lint/ruff lint/mypy

lint/mypy:
	mypy foreman

lint/ruff:
	ruff check .

test:
	python -m pytest --cov=foreman
