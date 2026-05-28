from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from quant_strategies.decisions import ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision
from quant_strategies.runner import execution
from quant_strategies.runner.config import load_config
from quant_strategies.runner.data_loader import LoadedData
from quant_strategies.runner.errors import DataLoadError, StrategyLoadError
from quant_strategies.runner.execution import (
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
mode = "screen"
""".lstrip()
    )
    return load_config(config_path, repo_root=repo_root)


def test_execute_strategy_run_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
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
    monkeypatch.setattr(execution, "load_data", lambda config: LoadedData(rows=loaded_rows))

    result = execute_strategy_run(config, repo_root=tmp_path)

    assert result.validated_params == {"weight": 1.0}
    assert result.loaded_rows is loaded_rows
    assert result.decisions == [decision()]
    assert len(result.normalized_rows_sha256) == 64
    assert result.evidence_quality["data_availability_status"] == "complete"


def test_execute_strategy_run_maps_strategy_import_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path, "def generate_decisions(rows, params): return []\n")
    config = write_config(tmp_path)

    def fail_load_strategy(path: Path, *, repo_root: Path):
        raise StrategyLoadError("strategy file missing")

    monkeypatch.setattr(execution, "load_strategy", fail_load_strategy)

    with pytest.raises(StrategyExecutionError) as error:
        execute_strategy_run(config, repo_root=tmp_path)

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

    def load_data(config):
        nonlocal load_calls
        load_calls += 1
        return LoadedData(rows=rows())

    monkeypatch.setattr(execution, "load_data", load_data)

    with pytest.raises(StrategyExecutionError) as error:
        execute_strategy_run(config, repo_root=tmp_path)

    assert str(error.value) == "param validation failed: unknown weight"
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

    def fail_load_data(config):
        raise DataLoadError("data load returned no rows")

    monkeypatch.setattr(execution, "load_data", fail_load_data)

    with pytest.raises(StrategyExecutionError) as error:
        execute_strategy_run(config, repo_root=tmp_path)

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
    monkeypatch.setattr(execution, "load_data", lambda config: LoadedData(rows=loaded_rows))

    with pytest.raises(StrategyExecutionError) as error:
        execute_strategy_run(config, repo_root=tmp_path)

    assert str(error.value) == "invalid_decision_output[0]"
    assert error.value.stage == "decision_generation"
    assert error.value.loaded_rows is loaded_rows
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
    monkeypatch.setattr(execution, "load_data", lambda config: LoadedData(rows=loaded_rows))

    with pytest.raises(StrategyExecutionError) as error:
        execute_strategy_run(config, repo_root=tmp_path)

    assert str(error.value) == "strategy execution failed: boom"
    assert error.value.stage == "decision_generation"
    assert error.value.loaded_rows is loaded_rows
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
    monkeypatch.setattr(execution, "load_strategy", lambda path, repo_root: flat_decision_strategy)
    monkeypatch.setattr(execution, "load_data", lambda config: LoadedData(rows=loaded_rows))

    result = execute_strategy_run(config, repo_root=tmp_path)

    assert result.loaded_rows is loaded_rows
    assert result.decisions == [decision(direction="flat", size=0.0)]
    assert len(result.normalized_rows_sha256) == 64
    assert result.evidence_quality["data_availability_status"] == "complete"
