.PHONY: test lint check

test:
	pytest -q

lint:
	ruff check app tests

check: test lint
