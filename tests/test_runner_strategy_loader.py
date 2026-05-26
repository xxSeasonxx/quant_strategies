from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from quant_strategies.decisions import StrategyDecision
from quant_strategies.runner.errors import StrategyLoadError
from quant_strategies.runner.strategy_loader import load_strategy


def test_load_strategy_returns_generate_decisions_callable(tmp_path: Path):
    strategy = tmp_path / "tested" / "demo.py"
    strategy.parent.mkdir(parents=True)
    strategy.write_text(
        "from quant_strategies.decisions import ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision\n"
        "def generate_decisions(rows, params):\n"
        "    return [StrategyDecision(\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='equity_or_etf', symbol='SPY'),\n"
        "        decision_time=rows[0]['timestamp'],\n"
        "        as_of_time=rows[0]['timestamp'],\n"
        "        target=PositionTarget(direction='long', sizing_kind='target_weight', size=1.0),\n"
        "        exit_policy=ExitPolicy(max_hold_bars=1),\n"
        "    )]\n"
    )

    generate_decisions = load_strategy(strategy, repo_root=tmp_path)
    rows = [{"symbol": "SPY", "timestamp": datetime(2024, 1, 1, tzinfo=timezone.utc)}]

    decisions = generate_decisions(rows, {})

    assert callable(generate_decisions)
    assert isinstance(decisions[0], StrategyDecision)
    assert decisions[0].instrument.symbol == "SPY"


def test_load_strategy_rejects_file_without_generate_decisions(tmp_path: Path):
    strategy = tmp_path / "tested" / "demo.py"
    strategy.parent.mkdir(parents=True)
    strategy.write_text("def generate_signals(rows, params):\n    return []\n")

    with pytest.raises(StrategyLoadError, match="generate_decisions"):
        load_strategy(strategy, repo_root=tmp_path)
