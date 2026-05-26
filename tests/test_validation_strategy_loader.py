from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from quant_strategies.validation.errors import ValidationStrategyLoadError
from quant_strategies.validation.strategy_loader import load_decision_strategy


def write_strategy(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return path


def test_load_decision_strategy_requires_generate_decisions(tmp_path: Path):
    strategy = write_strategy(tmp_path / "researched" / "demo" / "strategy.py", "def generate_signals(rows, params):\n    return []\n")

    with pytest.raises(ValidationStrategyLoadError, match="generate_decisions"):
        load_decision_strategy(strategy, repo_root=tmp_path)


def test_load_decision_strategy_rejects_outside_repo(tmp_path: Path):
    outside = write_strategy(tmp_path.parent / "outside_strategy.py", "def generate_decisions(rows, params):\n    return []\n")

    with pytest.raises(ValidationStrategyLoadError, match="inside repository"):
        load_decision_strategy(outside, repo_root=tmp_path)


def test_load_decision_strategy_returns_callable(tmp_path: Path):
    strategy = write_strategy(
        tmp_path / "researched" / "demo" / "strategy.py",
        "from quant_strategies.decisions import ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision\n"
        "def generate_decisions(rows, params):\n"
        "    return [StrategyDecision(\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='crypto_perp', symbol='BTC-PERP'),\n"
        "        decision_time=rows[1]['timestamp'],\n"
        "        as_of_time=rows[0]['timestamp'],\n"
        "        target=PositionTarget(direction='long', sizing_kind='target_weight', size=1.0),\n"
        "        exit_policy=ExitPolicy(max_hold_bars=1),\n"
        "    )]\n",
    )

    generate_decisions = load_decision_strategy(strategy, repo_root=tmp_path)
    rows = [
        {"timestamp": datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)},
        {"timestamp": datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc)},
    ]

    decisions = generate_decisions(rows, {})

    assert decisions[0].strategy_id == "demo"


def test_load_decision_strategy_attaches_validate_params(tmp_path: Path):
    strategy = write_strategy(
        tmp_path / "researched" / "demo" / "strategy.py",
        "def validate_params(params):\n"
        "    return {'weight': float(params['weight'])}\n"
        "def generate_decisions(rows, params):\n"
        "    return []\n",
    )

    generate_decisions = load_decision_strategy(strategy, repo_root=tmp_path)

    assert generate_decisions.validate_params({"weight": 1}) == {"weight": 1.0}


def test_load_decision_strategy_rejects_noncallable_validate_params(tmp_path: Path):
    strategy = write_strategy(
        tmp_path / "researched" / "demo" / "strategy.py",
        "validate_params = {}\n"
        "def generate_decisions(rows, params):\n"
        "    return []\n",
    )

    with pytest.raises(ValidationStrategyLoadError, match="validate_params"):
        load_decision_strategy(strategy, repo_root=tmp_path)
