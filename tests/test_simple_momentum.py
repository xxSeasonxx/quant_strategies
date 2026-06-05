from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from quant_strategies.core.data_loader import LoadedData
from quant_strategies.validation import run_validation


def load_example_strategy():
    path = Path("examples/strategies/simple_momentum.py")
    spec = importlib.util.spec_from_file_location("_simple_momentum_example", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bars_for(closes: list[float]) -> list[dict[str, object]]:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    return [
        {
            "symbol": "DEMO",
            "timestamp": start + timedelta(days=index),
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "available_at": start + timedelta(days=index),
        }
        for index, close in enumerate(closes)
    ]


def test_generate_decisions_emits_long_after_positive_close_change():
    bars = bars_for([100.0, 101.0, 100.0])
    decisions = load_example_strategy().generate_decisions(
        bars, {"weight": 1.0, "max_hold_bars": 1}
    )

    assert len(decisions) == 1
    decision = decisions[0]
    assert decision.instrument.symbol == "DEMO"
    assert decision.decision_time == datetime(2024, 1, 2, tzinfo=UTC)
    assert decision.as_of_time == bars[1]["timestamp"]
    assert decision.target.direction == "long"
    assert decision.target.size == 1.0
    assert decision.exit_policy.max_hold_bars == 1
    assert [item.field for item in decision.observations] == ["close", "close"]
    assert [item.timestamp for item in decision.observations] == [
        datetime(2024, 1, 1, tzinfo=UTC),
        datetime(2024, 1, 2, tzinfo=UTC),
    ]


def test_validate_params_returns_typed_contract():
    module = load_example_strategy()

    assert module.validate_params({"weight": "0.5", "max_hold_bars": "2"}) == {
        "weight": 0.5,
        "max_hold_bars": 2,
    }
    with pytest.raises(ValueError, match="weight must be finite and positive"):
        module.validate_params({"weight": 0.0})
    with pytest.raises(ValueError, match="max_hold_bars must be >= 1"):
        module.validate_params({"max_hold_bars": 0})


def test_generate_decisions_uses_current_bar_as_decision_time_without_lookahead():
    decisions = load_example_strategy().generate_decisions(
        bars_for([100.0, 99.0, 101.0, 100.0]),
        {"weight": 0.5, "max_hold_bars": 2},
    )

    assert len(decisions) == 1
    decision = decisions[0]
    assert decision.decision_time == datetime(2024, 1, 3, tzinfo=UTC)
    assert decision.as_of_time == decision.decision_time
    assert decision.target.direction == "long"
    assert decision.target.size == 0.5
    assert decision.exit_policy.max_hold_bars == 2


def test_generate_decisions_stops_after_first_positive_close_change():
    decisions = load_example_strategy().generate_decisions(
        bars_for([100.0, 101.0, 102.0, 103.0]),
        {"weight": 1.0, "max_hold_bars": 1},
    )

    assert len(decisions) == 1
    assert decisions[0].decision_time == datetime(2024, 1, 2, tzinfo=UTC)


def test_generate_decisions_returns_empty_list_for_degenerate_inputs():
    module = load_example_strategy()

    assert module.generate_decisions([], {}) == []
    assert module.generate_decisions(bars_for([100.0]), {}) == []


def test_generate_decisions_returns_empty_list_without_positive_close_change():
    assert load_example_strategy().generate_decisions(bars_for([100.0, 100.0, 99.0]), {}) == []


def test_validation_config_runs_with_fixture_loader_and_engine_backend(tmp_path: Path, monkeypatch):
    source_dir = Path("examples/strategies")
    workspace = tmp_path / "simple_momentum"
    workspace.mkdir()
    (workspace / "simple_momentum.py").write_text((source_dir / "simple_momentum.py").read_text())
    config_path = workspace / "simple_momentum_spy_daily_validation.toml"
    config_path.write_text((source_dir / "simple_momentum_spy_daily_validation.toml").read_text())
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=bars_for([100.0, 101.0, 102.0, 103.0, 104.0])),
    )

    result = run_validation(config_path, repo_root=tmp_path)

    assert result.run_completed is True
    assert result.failure_stage is None
    assert result.decision.decision == "mechanical_fail"
    assert result.decision.reasons == ("insufficient_trades",)
    assert result.result_dir is not None
    backend_summary = json.loads((result.result_dir / "backend_runs" / "summary.json").read_text())
    assert {item["result"]["backend"] for item in backend_summary["results"]} == {"engine"}
    assert {item["result"]["metrics"]["trade_count"] for item in backend_summary["results"]} == {1}
    audit = json.loads((result.result_dir / "data_audit.json").read_text())
    assert audit["windows"][0]["passed"] is True
    assert audit["windows"][0]["deterministic_replay_verified"] is True
    assert audit["windows"][0]["strict_suppression_verified"] is True
