from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path


def load_example_strategy():
    path = Path("examples/strategies/simple_momentum.py")
    spec = importlib.util.spec_from_file_location("_simple_momentum_example", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bars_for(closes: list[float]) -> list[dict[str, object]]:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return [
        {
            "symbol": "DEMO",
            "timestamp": start + timedelta(days=index),
            "open": close,
            "high": close,
            "low": close,
            "close": close,
        }
        for index, close in enumerate(closes)
    ]


def test_generate_decisions_emits_long_after_positive_close_change():
    bars = bars_for([100.0, 101.0, 100.0])
    decisions = load_example_strategy().generate_decisions(bars, {"weight": 1.0, "max_hold_bars": 1})

    assert len(decisions) == 1
    decision = decisions[0]
    assert decision.instrument.symbol == "DEMO"
    assert decision.decision_time == datetime(2024, 1, 2, tzinfo=timezone.utc)
    assert decision.as_of_time == bars[1]["timestamp"]
    assert decision.target.direction == "long"
    assert decision.target.size == 1.0
    assert decision.exit_policy.max_hold_bars == 1


def test_generate_decisions_uses_current_bar_as_decision_time_without_lookahead():
    decisions = load_example_strategy().generate_decisions(
        bars_for([100.0, 99.0, 101.0, 100.0]),
        {"weight": 0.5, "max_hold_bars": 2},
    )

    assert len(decisions) == 1
    decision = decisions[0]
    assert decision.decision_time == datetime(2024, 1, 3, tzinfo=timezone.utc)
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
    assert decisions[0].decision_time == datetime(2024, 1, 2, tzinfo=timezone.utc)


def test_generate_decisions_returns_empty_list_for_degenerate_inputs():
    module = load_example_strategy()

    assert module.generate_decisions([], {}) == []
    assert module.generate_decisions(bars_for([100.0]), {}) == []


def test_generate_decisions_returns_empty_list_without_positive_close_change():
    assert load_example_strategy().generate_decisions(bars_for([100.0, 100.0, 99.0]), {}) == []
