## Baseline Before Migration

Captured before moving evaluator code.

### quant_strategies

Dirty tracked files:

- `PRODUCT_REQUIREMENTS.md`
- `README.md`
- `docs/superpowers/specs/2026-05-20-quant-strategy-runner-design.md`
- `src/quant_strategies/runner/__init__.py`
- `src/quant_strategies/runner/artifacts.py`
- `src/quant_strategies/runner/engine_runner.py`
- `tests/test_fx_triangular_residual_reversion.py`
- `tests/test_runner_api_cli.py`
- `tests/test_runner_engine_runner.py`
- `untested/fx_triangular_residual_reversion.py`

Untracked OpenSpec changes:

- `openspec/changes/correct-research-evidence-semantics/`
- `openspec/changes/internalize-quant-engine/`

Focused baseline verification:

- `conda run -n quant pytest tests/test_runner_engine_runner.py tests/test_runner_api_cli.py`
  passed: 24 passed.

### quant_engine

Dirty tracked files:

- `AGENTS.md`
- `PRODUCT_REQUIREMENTS.md`
- `README.md`
- `docs/write_strategy.md`
- `src/quant_engine/cli.py`
- `src/quant_engine/evaluation.py`
- `src/quant_engine/models.py`
- `tests/test_cli.py`
- `tests/test_models.py`
- `tests/test_screen.py`
- `tests/test_validate_and_evidence.py`

Untracked:

- `.claude/`
- `.codex/`

Baseline verification:

- `conda run -n quant pytest` passed: 34 passed.

### quant_autoresearch

Dirty tracked files:

- `experiment.yml`
- `strategy.py`

Untracked:

- `.claude/`
- `.codex/`
- `docs/superpowers/plans/`
- `openspec/`

Baseline verification:

- `conda run -n quant pytest` failed before this migration: 2 failed, 2
  passed. Failing tests expected `validate_summary.json`, which current
  `run_once` did not write.

### Active Standalone Engine References

Active source references before migration:

- `quant_strategies/src/quant_strategies/runner/engine_runner.py` imports
  `quant_engine`.
- `quant_strategies/src/quant_strategies/runner/config.py` imports
  `quant_engine.FillModel`.
- `quant_strategies/pyproject.toml` depends on `quant-engine`.
- `quant_strategies/src/quant_strategies/runner/artifacts.py` captures
  `quant-engine` package version.
- `quant_autoresearch/runner.py` shells `quant-engine`.
- `quant_autoresearch` README and historical docs mention direct
  `quant_engine` / `quant-engine` usage.
