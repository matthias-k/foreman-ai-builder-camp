.PHONY: clean fix install lint lint/ruff lint/mypy test

clean:
	rm -rf build
	rm -rf foreman.egg-info
	rm -rf foreman/static/node_modules
	rm -rf foreman/static/output.css
	rm -rf foreman/__pycache__
	rm -rf .mypy_cache
	rm -rf .ruff_cache
	rm -rf .pytest_cache

css:
	cd foreman/static && npx tailwindcss -i input.css -o output.css

fix:
	ruff check --fix .

install:
	pip install -e .
	cd foreman/static && npm install
	cd foreman/static && npx tailwindcss -i input.css -o output.css

lint: lint/ruff lint/mypy

lint/mypy:
	mypy foreman

lint/ruff:
	ruff check .

test:
	python -m pytest --cov=foreman
