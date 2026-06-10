.PHONY: format fix lint typecheck test check check-quant-data-contract check-all

format:
	conda run -n quant ruff format .

fix:
	conda run -n quant ruff format .
	conda run -n quant ruff check . --fix

lint:
	conda run -n quant ruff format --check .
	conda run -n quant ruff check .

typecheck:
	conda run -n quant mypy src tests

test:
	conda run -n quant pytest -q

check: lint test
	conda run -n quant python -m pip install -e .
	conda run -n quant quant-strategies --help

check-quant-data-contract:
	conda run -n quant env RUN_QUANT_DATA_CONTRACT_SMOKE=1 pytest tests/test_quant_data_contract_smoke.py

check-all: check typecheck check-quant-data-contract
