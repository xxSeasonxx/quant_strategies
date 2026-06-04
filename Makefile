.PHONY: check check-vectorbtpro-smoke check-all

check:
	conda run -n quant python -m pip install -e .
	conda run -n quant quant-strategies --help
	conda run -n quant pytest -q

check-vectorbtpro-smoke:
	conda run -n quant env RUN_VECTORBTPRO_SMOKE=1 pytest tests/test_evaluation_backend.py::test_vectorbtpro_evaluation_backend_real_smoke_if_installed

check-all: check check-vectorbtpro-smoke
