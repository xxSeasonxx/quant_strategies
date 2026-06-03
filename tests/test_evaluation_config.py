from __future__ import annotations

from pathlib import Path

import pytest

from quant_strategies.core.config import CostModelConfig, DataConfig, FillModelConfig, StrategyExecutionSpec
from quant_strategies.evaluation.config import (
    EvaluationConfigError,
    load_evaluation_config,
    resolve_evaluation_config_path,
)


ROOT = Path(__file__).resolve().parents[1]


def write_strategy(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "def validate_params(params):\n"
        "    return dict(params)\n"
        "def generate_decisions(rows, params):\n"
        "    return []\n"
    )


def write_config(path: Path, *, strategy_path: str = "strategy.py", annualization: int = 252) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'''
strategy_path = "{strategy_path}"
strategy_id = "demo"

[[windows]]
id = "eval_2026_h1"
start = "2026-01-01"
end = "2026-06-30"

[data]
kind = "bars"
dataset = "equity_1min"
symbols = ["SPY", "QQQ"]
strict = true
start = "2026-01-01"
end = "2026-06-30"

[params]
weight = 0.5

[fill_model]
price = "close"
entry_lag_bars = 1
exit_lag_bars = 0

[cost_model]
fee_bps_per_side = 0.5
slippage_bps_per_side = 0.5

[metrics]
annualization_periods_per_year = {annualization}

[output]
results_dir = "evaluation_results/demo"
'''.lstrip()
    )


def test_load_evaluation_config_resolves_candidate_local_paths(tmp_path: Path):
    candidate = tmp_path / "candidate"
    write_strategy(candidate / "strategy.py")
    write_config(candidate / "evaluation.toml")

    config = load_evaluation_config(candidate / "evaluation.toml")

    assert config.base_dir == candidate
    assert config.strategy_path == candidate / "strategy.py"
    assert config.output.results_dir == candidate / "evaluation_results" / "demo"
    assert config.strategy_id == "demo"
    assert config.windows[0].id == "eval_2026_h1"
    assert config.data.symbols == ("SPY", "QQQ")
    assert config.metrics.annualization_periods_per_year == 252
    assert config.to_execution_spec(config.windows[0]) == StrategyExecutionSpec(
        strategy_path=candidate / "strategy.py",
        strategy_id="demo",
        data=DataConfig(
            kind="bars",
            dataset="equity_1min",
            symbols=("SPY", "QQQ"),
            strict=True,
            start=config.windows[0].start,
            end=config.windows[0].end,
        ),
        params={"weight": 0.5},
        fill_model=FillModelConfig(price="close", entry_lag_bars=1, exit_lag_bars=0),
        cost_model=CostModelConfig(fee_bps_per_side=0.5, slippage_bps_per_side=0.5),
        require_param_validator=True,
    )


def test_checked_in_simple_momentum_evaluation_example_loads():
    config_path = ROOT / "examples" / "strategies" / "simple_momentum_spy_daily_evaluation.toml"

    config = load_evaluation_config(config_path)

    assert config.base_dir == config_path.parent
    assert config.strategy_path == ROOT / "examples" / "strategies" / "simple_momentum.py"
    assert config.output.results_dir == ROOT / "examples" / "strategies" / "evaluation_results" / "simple_momentum"
    assert config.strategy_id == "simple_momentum"
    assert config.windows[0].id == "evaluation_2024_01"


def test_resolve_evaluation_config_rejects_directory_path(tmp_path: Path):
    candidate = tmp_path / "candidate"
    candidate.mkdir()

    with pytest.raises(EvaluationConfigError, match="evaluation config path must be a TOML file"):
        resolve_evaluation_config_path(candidate)


def test_load_evaluation_config_rejects_paths_outside_candidate_dir(tmp_path: Path):
    candidate = tmp_path / "candidate"
    outside = tmp_path / "outside.py"
    write_strategy(outside)
    write_config(candidate / "evaluation.toml", strategy_path="../outside.py")

    with pytest.raises(EvaluationConfigError, match="strategy_path must resolve inside config directory"):
        load_evaluation_config(candidate / "evaluation.toml")


def test_load_evaluation_config_requires_positive_annualization(tmp_path: Path):
    candidate = tmp_path / "candidate"
    write_strategy(candidate / "strategy.py")
    write_config(candidate / "evaluation.toml", annualization=0)

    with pytest.raises(EvaluationConfigError, match="annualization_periods_per_year"):
        load_evaluation_config(candidate / "evaluation.toml")


def test_load_evaluation_config_rejects_empty_or_duplicate_window_ids(tmp_path: Path):
    candidate = tmp_path / "candidate"
    write_strategy(candidate / "strategy.py")
    write_config(candidate / "evaluation.toml")
    payload = (candidate / "evaluation.toml").read_text()
    payload = payload.replace('id = "eval_2026_h1"', 'id = "dup"')
    payload += '''

[[windows]]
id = "dup"
start = "2026-07-01"
end = "2026-12-31"
'''
    (candidate / "evaluation.toml").write_text(payload)

    with pytest.raises(EvaluationConfigError, match="window ids cannot contain duplicates"):
        load_evaluation_config(candidate / "evaluation.toml")
