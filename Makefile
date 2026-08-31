.PHONY: install test lint validate init-db run benchmark

CONFIG ?= configs/pipeline.yml
SOURCE ?= sample_daily_prices

install:
	python3 -m venv .venv
	. .venv/bin/activate && pip install -e ".[dev]"

test:
	. .venv/bin/activate && pytest -q

lint:
	. .venv/bin/activate && ruff check . && ruff format --check .

validate:
	. .venv/bin/activate && market-data-pipeline validate-config --config $(CONFIG)

init-db:
	. .venv/bin/activate && market-data-pipeline init-db --config $(CONFIG)

run:
	. .venv/bin/activate && market-data-pipeline run --config $(CONFIG) --source $(SOURCE)

benchmark:
	. .venv/bin/activate && python scripts/benchmark_load.py --rows 100000
