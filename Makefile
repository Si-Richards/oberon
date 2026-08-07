.PHONY: test lint check run

test:
	PYTHONPATH=. pytest -q

lint:
	ruff check app tests

check: lint test

run:
	python -m app.main
