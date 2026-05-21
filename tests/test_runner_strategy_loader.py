from __future__ import annotations

from pathlib import Path

import pytest

from quant_strategies.runner.errors import StrategyLoadError
from quant_strategies.runner.strategy_loader import load_strategy


def test_load_strategy_returns_generate_signals_callable(tmp_path: Path):
    strategy = tmp_path / "tested" / "demo.py"
    strategy.parent.mkdir(parents=True)
    strategy.write_text(
        "def generate_signals(bars, params):\n"
        "    return [{'symbol': bars[0]['symbol'], 'decision_time': bars[0]['timestamp'], 'side': 'long'}]\n"
    )

    generate_signals = load_strategy(strategy, repo_root=tmp_path)

    assert callable(generate_signals)
    assert generate_signals([{"symbol": "SPY", "timestamp": "2024-01-01T00:00:00+00:00"}], {}) == [
        {"symbol": "SPY", "decision_time": "2024-01-01T00:00:00+00:00", "side": "long"}
    ]


def test_load_strategy_rejects_file_without_generate_signals(tmp_path: Path):
    strategy = tmp_path / "tested" / "demo.py"
    strategy.parent.mkdir(parents=True)
    strategy.write_text("VALUE = 1\n")

    with pytest.raises(StrategyLoadError, match="generate_signals"):
        load_strategy(strategy, repo_root=tmp_path)
