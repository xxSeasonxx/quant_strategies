.PHONY: check check-vectorbtpro-smoke check-quant-data-contract check-all

check:
	conda run -n quant python -m pip install -e .
	conda run -n quant quant-strategies --help
	conda run -n quant pytest -q
	$(MAKE) check-vectorbtpro-smoke

check-vectorbtpro-smoke:
	conda run -n quant env RUN_VECTORBTPRO_SMOKE=1 pytest tests/test_evaluation_backend.py::test_vectorbtpro_evaluation_backend_real_smoke_if_installed

check-quant-data-contract:
	conda run -n quant env RUN_QUANT_DATA_CONTRACT_SMOKE=1 pytest tests/test_quant_data_contract_smoke.py

check-all: check
