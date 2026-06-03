from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from quant_strategies.data_contract import NormalizedRows
from quant_strategies.decisions import ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision
from quant_strategies.core import execution
from quant_strategies.runner.config import load_config
from quant_strategies.core.data_loader import LoadedData
from quant_strategies.core.errors import DataLoadError, StrategyLoadError
from quant_strategies.core.execution import (
    StrategyExecutionError,
    execute_strategy_run,
)


TIMESTAMP = datetime(2024, 1, 1, tzinfo=timezone.utc)


def rows() -> list[dict[str, Any]]:
    return [
        {
            "symbol": "SPY",
            "timestamp": TIMESTAMP,
            "available_at": TIMESTAMP,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
        }
    ]


def decision(
    strategy_id: str = "demo",
    *,
    direction: str = "long",
    size: float = 1.0,
) -> StrategyDecision:
    return StrategyDecision(
        strategy_id=strategy_id,
        instrument=InstrumentRef(kind="equity_or_etf", symbol="SPY"),
        decision_time=TIMESTAMP,
        as_of_time=TIMESTAMP,
        target=PositionTarget(direction=direction, sizing_kind="target_weight", size=size),
        exit_policy=ExitPolicy(max_hold_bars=1),
    )


def write_strategy(repo_root: Path, body: str) -> None:
    strategy = repo_root / "tested" / "demo.py"
    strategy.parent.mkdir(parents=True, exist_ok=True)
    strategy.write_text(body)


def write_config(repo_root: Path):
    config_path = repo_root / "run.toml"
    config_path.write_text(
        """
strategy_path = "tested/demo.py"
strategy_id = "demo"

[data]
kind = "bars"
dataset = "equity_1min"
symbols = ["SPY"]
start = "2024-01-01"
end = "2024-01-05"
strict = true

[params]
weight = 1.0

[fill_model]
price = "close"
entry_lag_bars = 1

[cost_model]
fee_bps_per_side = 0.0
slippage_bps_per_side = 0.0

[output]
results_dir = "results"
""".lstrip()
    )
    return load_config(config_path, repo_root=repo_root)


def test_execute_strategy_run_completed_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    loaded_rows = rows()
    write_strategy(
        tmp_path,
        "from quant_strategies.decisions import ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision\n"
        "def validate_params(params):\n"
        "    return {'weight': float(params['weight'])}\n"
        "def generate_decisions(rows, params):\n"
        "    return [StrategyDecision(\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='equity_or_etf', symbol=rows[0]['symbol']),\n"
        "        decision_time=rows[0]['timestamp'],\n"
        "        as_of_time=rows[0]['timestamp'],\n"
        "        target=PositionTarget(direction='long', sizing_kind='target_weight', size=params['weight']),\n"
        "        exit_policy=ExitPolicy(max_hold_bars=1),\n"
        "    )]\n",
    )
    config = write_config(tmp_path)
    monkeypatch.setattr(execution, "load_data", lambda config, **_kwargs: LoadedData(rows=loaded_rows))

    result = execute_strategy_run(config.to_execution_spec(), repo_root=tmp_path)

    assert result.validated_params == {"weight": 1.0}
    assert tuple(dict(row) for row in result.loaded_rows) == tuple(loaded_rows)
    assert result.loaded_rows == result.normalized_rows.projection_rows()
    assert result.normalized_rows.normalized_rows_sha256 == result.normalized_rows_sha256
    assert result.decisions == [decision()]
    assert len(result.normalized_rows_sha256) == 64
    assert result.evidence_quality["data_availability_status"] == "complete"


def test_execute_strategy_run_reuses_loaded_rows_when_already_normalized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    config = write_config(tmp_path)
    normalized = NormalizedRows.from_rows(config, rows())

    def generate_decisions(loaded_rows, params):
        assert loaded_rows[0]["symbol"] == "SPY"
        return [decision()]

    monkeypatch.setattr(execution, "_load_strategy", lambda path, repo_root: generate_decisions)
    monkeypatch.setattr(execution, "load_data", lambda config, **_kwargs: LoadedData(rows=normalized))

    result = execute_strategy_run(config.to_execution_spec(), repo_root=tmp_path)

    assert result.normalized_rows is normalized
    assert result.loaded_rows is normalized.projection_rows()
    assert result.normalized_rows_sha256 == normalized.normalized_rows_sha256


def test_execute_strategy_run_maps_strategy_import_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path, "def generate_decisions(rows, params): return []\n")
    config = write_config(tmp_path)

    def fail_load_strategy(path: Path, *, repo_root: Path):
        raise StrategyLoadError("strategy file missing")

    monkeypatch.setattr(execution, "_load_strategy", fail_load_strategy)

    with pytest.raises(StrategyExecutionError) as error:
        execute_strategy_run(config.to_execution_spec(), repo_root=tmp_path)

    assert str(error.value) == "strategy file missing"
    assert error.value.stage == "strategy_import"
    assert error.value.loaded_rows is None
    assert error.value.normalized_rows_sha256 is None
    assert error.value.evidence_quality is None


def test_execute_strategy_run_maps_param_validation_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(
        tmp_path,
        "def validate_params(params):\n"
        "    raise ValueError('unknown weight')\n"
        "def generate_decisions(rows, params): return []\n",
    )
    config = write_config(tmp_path)
    load_calls = 0

    def load_data(config, **_kwargs):
        nonlocal load_calls
        load_calls += 1
        return LoadedData(rows=rows())

    monkeypatch.setattr(execution, "load_data", load_data)

    with pytest.raises(StrategyExecutionError) as error:
        execute_strategy_run(config.to_execution_spec(), repo_root=tmp_path)

    assert str(error.value) == "param validation failed: unknown weight"
    assert error.value.stage == "param_validation"
    assert error.value.loaded_rows is None
    assert error.value.normalized_rows_sha256 is None
    assert error.value.evidence_quality is None
    assert load_calls == 0


def test_execute_strategy_run_maps_param_validation_system_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(
        tmp_path,
        "def validate_params(params):\n"
        "    raise SystemExit('params exited')\n"
        "def generate_decisions(rows, params): return []\n",
    )
    config = write_config(tmp_path)
    load_calls = 0

    def load_data(config, **_kwargs):
        nonlocal load_calls
        load_calls += 1
        return LoadedData(rows=rows())

    monkeypatch.setattr(execution, "load_data", load_data)

    with pytest.raises(StrategyExecutionError) as error:
        execute_strategy_run(config.to_execution_spec(), repo_root=tmp_path)

    assert str(error.value) == "param validation exited: params exited"
    assert error.value.stage == "param_validation"
    assert error.value.loaded_rows is None
    assert error.value.normalized_rows_sha256 is None
    assert error.value.evidence_quality is None
    assert load_calls == 0


def test_execute_strategy_run_maps_data_load_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path, "def generate_decisions(rows, params): return []\n")
    config = write_config(tmp_path)

    def fail_load_data(config, **_kwargs):
        raise DataLoadError("data load returned no rows")

    monkeypatch.setattr(execution, "load_data", fail_load_data)

    with pytest.raises(StrategyExecutionError) as error:
        execute_strategy_run(config.to_execution_spec(), repo_root=tmp_path)

    assert str(error.value) == "data load returned no rows"
    assert error.value.stage == "data_load"
    assert error.value.loaded_rows is None
    assert error.value.normalized_rows_sha256 is None
    assert error.value.evidence_quality is None


def test_execute_strategy_run_invalid_decision_output_carries_loaded_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    loaded_rows = rows()
    write_strategy(tmp_path, "def generate_decisions(rows, params): return ['not a decision']\n")
    config = write_config(tmp_path)
    monkeypatch.setattr(execution, "load_data", lambda config, **_kwargs: LoadedData(rows=loaded_rows))

    with pytest.raises(StrategyExecutionError) as error:
        execute_strategy_run(config.to_execution_spec(), repo_root=tmp_path)

    assert str(error.value) == "invalid_decision_output[0]"
    assert error.value.stage == "decision_generation"
    assert tuple(dict(row) for row in error.value.loaded_rows or ()) == tuple(loaded_rows)
    assert error.value.normalized_rows is not None
    assert error.value.loaded_rows == error.value.normalized_rows.projection_rows()
    assert error.value.normalized_rows_sha256 is not None
    assert len(error.value.normalized_rows_sha256) == 64
    assert error.value.evidence_quality is not None
    assert error.value.evidence_quality["data_availability_status"] == "complete"
    assert error.value.violations == ("invalid_decision_output[0]",)
    assert error.value.decision_count == 0


def test_execute_strategy_run_maps_generation_exception_with_loaded_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    loaded_rows = rows()
    write_strategy(
        tmp_path,
        "def generate_decisions(rows, params):\n"
        "    raise RuntimeError('boom')\n",
    )
    config = write_config(tmp_path)
    monkeypatch.setattr(execution, "load_data", lambda config, **_kwargs: LoadedData(rows=loaded_rows))

    with pytest.raises(StrategyExecutionError) as error:
        execute_strategy_run(config.to_execution_spec(), repo_root=tmp_path)

    assert str(error.value) == "strategy execution failed: boom"
    assert error.value.stage == "decision_generation"
    assert tuple(dict(row) for row in error.value.loaded_rows or ()) == tuple(loaded_rows)
    assert error.value.normalized_rows is not None
    assert error.value.loaded_rows == error.value.normalized_rows.projection_rows()
    assert error.value.normalized_rows_sha256 is not None
    assert len(error.value.normalized_rows_sha256) == 64
    assert error.value.evidence_quality is not None
    assert error.value.violations == ()
    assert error.value.decision_count == 0


def test_execute_strategy_run_accepts_valid_flat_decisions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    loaded_rows = rows()

    def flat_decision_strategy(loaded_rows, params):
        return [decision(direction="flat", size=0.0)]

    write_strategy(tmp_path, "def generate_decisions(rows, params): return []\n")
    config = write_config(tmp_path)
    monkeypatch.setattr(execution, "_load_strategy", lambda path, repo_root: flat_decision_strategy)
    monkeypatch.setattr(execution, "load_data", lambda config, **_kwargs: LoadedData(rows=loaded_rows))

    result = execute_strategy_run(config.to_execution_spec(), repo_root=tmp_path)

    assert tuple(dict(row) for row in result.loaded_rows) == tuple(loaded_rows)
    assert result.loaded_rows == result.normalized_rows.projection_rows()
    assert result.decisions == [decision(direction="flat", size=0.0)]
    assert len(result.normalized_rows_sha256) == 64
    assert result.evidence_quality["data_availability_status"] == "complete"


_SCHEMALESS_STRATEGY = (
    "from quant_strategies.decisions import ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision\n"
    "def generate_decisions(rows, params):\n"
    "    return [StrategyDecision(\n"
    "        strategy_id='demo',\n"
    "        instrument=InstrumentRef(kind='equity_or_etf', symbol=rows[0]['symbol']),\n"
    "        decision_time=rows[0]['timestamp'],\n"
    "        as_of_time=rows[0]['timestamp'],\n"
    "        target=PositionTarget(direction='long', sizing_kind='target_weight', size=1.0),\n"
    "        exit_policy=ExitPolicy(max_hold_bars=1),\n"
    "    )]\n"
)


def test_execute_strategy_run_flags_schemaless_passthrough(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # No validate_params + runner default (require_param_validator=False): the run
    # completes but the params are flagged as unvalidated passthrough.
    write_strategy(tmp_path, _SCHEMALESS_STRATEGY)
    config = write_config(tmp_path)
    monkeypatch.setattr(execution, "load_data", lambda config, **_kwargs: LoadedData(rows=rows()))

    result = execute_strategy_run(config.to_execution_spec(), repo_root=tmp_path)

    assert result.param_contract == "unvalidated_passthrough"
    assert result.validated_params == {"weight": 1.0}


def test_execute_strategy_run_requires_validate_params_when_spec_demands_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    # The validation run sets require_param_validator=True; a schema-less strategy
    # then fails fast at the param_validation stage (no verdict on unvalidated params).
    write_strategy(tmp_path, _SCHEMALESS_STRATEGY)
    config = write_config(tmp_path)
    spec = replace(config.to_execution_spec(), require_param_validator=True)
    monkeypatch.setattr(execution, "load_data", lambda config, **_kwargs: LoadedData(rows=rows()))

    with pytest.raises(StrategyExecutionError) as excinfo:
        execute_strategy_run(spec, repo_root=tmp_path)

    assert excinfo.value.stage == "param_validation"
    assert "validate_params" in str(excinfo.value)
