from __future__ import annotations

from pathlib import Path

import pytest

from quant_strategies.core.config import (
    CostModelConfig,
    DataConfig,
    FillModelConfig,
    StrategyExecutionSpec,
    WindowedDataConfig,
)
from quant_strategies.evaluation.config import (
    EvaluationConfig,
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


def write_config(
    path: Path,
    *,
    strategy_path: str = "strategy.py",
    annualization: int = 252,
    min_annualized_samples: int | None = None,
    extra: str = "",
) -> None:
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
{f"min_annualized_samples = {min_annualized_samples}" if min_annualized_samples is not None else ""}

[output]
results_dir = "evaluation_results/demo"
{extra}
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
    assert EvaluationConfig.model_fields["data"].annotation is WindowedDataConfig
    assert config.data.symbols == ("SPY", "QQQ")
    assert not hasattr(config.data, "start")
    assert not hasattr(config.data, "end")
    assert config.metrics.annualization_periods_per_year == 252
    assert config.metrics.min_annualized_samples == 20
    assert config.to_execution_spec(config.windows[0]) == StrategyExecutionSpec(
        strategy_path=candidate / "strategy.py",
        strategy_id="demo",
        data=DataConfig(
            kind="bars",
            dataset="equity_1min",
            symbols=("SPY", "QQQ"),
            start=config.windows[0].start,
            end=config.windows[0].end,
        ),
        params={"weight": 0.5},
        fill_model=FillModelConfig(price="close", entry_lag_bars=1, exit_lag_bars=0),
        cost_model=CostModelConfig(fee_bps_per_side=0.5, slippage_bps_per_side=0.5),
        require_param_validator=True,
    )


def test_evaluation_causality_replay_defaults_to_complete(tmp_path: Path):
    candidate = tmp_path / "candidate"
    write_strategy(candidate / "strategy.py")
    write_config(candidate / "evaluation.toml")

    config = load_evaluation_config(candidate / "evaluation.toml")

    assert config.causality_replay.scope == "complete"


def test_evaluation_accepts_bounded_causality_replay(tmp_path: Path):
    candidate = tmp_path / "candidate"
    write_strategy(candidate / "strategy.py")
    write_config(
        candidate / "evaluation.toml",
        extra="""

[causality_replay]
scope = "bounded"
probe_limit = 7
timeout_seconds = 1.5
""",
    )

    config = load_evaluation_config(candidate / "evaluation.toml")

    assert config.causality_replay.scope == "bounded"
    assert config.causality_replay.probe_limit == 7
    assert config.causality_replay.timeout_seconds == 1.5


def test_checked_in_simple_momentum_evaluation_example_loads():
    config_path = ROOT / "examples" / "simple_momentum" / "evaluation.toml"

    config = load_evaluation_config(config_path)

    assert config.base_dir == config_path.parent
    assert config.strategy_path == ROOT / "examples" / "simple_momentum" / "strategy.py"
    assert (
        config.output.results_dir
        == ROOT / "examples" / "simple_momentum" / "evaluation_results" / "simple_momentum"
    )
    assert config.strategy_id == "simple_momentum"
    assert config.windows[0].id == "evaluation_2024_01"
    assert config.metrics.annualization_periods_per_year == 525949
    assert config.metrics.min_annualized_samples == 20


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

    with pytest.raises(
        EvaluationConfigError, match="strategy_path must resolve inside config directory"
    ):
        load_evaluation_config(candidate / "evaluation.toml")


def test_load_evaluation_config_requires_positive_annualization(tmp_path: Path):
    candidate = tmp_path / "candidate"
    write_strategy(candidate / "strategy.py")
    write_config(candidate / "evaluation.toml", annualization=0)

    with pytest.raises(EvaluationConfigError, match="annualization_periods_per_year"):
        load_evaluation_config(candidate / "evaluation.toml")


def test_load_evaluation_config_accepts_min_annualized_samples_override(tmp_path: Path):
    candidate = tmp_path / "candidate"
    write_strategy(candidate / "strategy.py")
    write_config(candidate / "evaluation.toml", min_annualized_samples=4)

    config = load_evaluation_config(candidate / "evaluation.toml")

    assert config.metrics.min_annualized_samples == 4


def test_load_evaluation_config_rejects_legacy_data_window_dates(tmp_path: Path):
    candidate = tmp_path / "candidate"
    write_strategy(candidate / "strategy.py")
    config_path = candidate / "evaluation.toml"
    write_config(config_path)
    config_path.write_text(
        config_path.read_text().replace(
            'symbols = ["SPY", "QQQ"]\n\n[params]',
            'symbols = ["SPY", "QQQ"]\nstart = "2025-01-01"\nend = "2025-12-31"\n\n[params]',
        )
    )

    with pytest.raises(EvaluationConfigError, match="start|end|extra"):
        load_evaluation_config(config_path)


def test_load_evaluation_config_rejects_min_annualized_samples_below_two(tmp_path: Path):
    candidate = tmp_path / "candidate"
    write_strategy(candidate / "strategy.py")
    write_config(candidate / "evaluation.toml", min_annualized_samples=1)

    with pytest.raises(EvaluationConfigError, match="min_annualized_samples"):
        load_evaluation_config(candidate / "evaluation.toml")


def test_load_evaluation_config_rejects_empty_or_duplicate_window_ids(tmp_path: Path):
    candidate = tmp_path / "candidate"
    write_strategy(candidate / "strategy.py")
    write_config(candidate / "evaluation.toml")
    payload = (candidate / "evaluation.toml").read_text()
    payload = payload.replace('id = "eval_2026_h1"', 'id = "dup"')
    payload += """

[[windows]]
id = "dup"
start = "2026-07-01"
end = "2026-12-31"
"""
    (candidate / "evaluation.toml").write_text(payload)

    with pytest.raises(EvaluationConfigError, match="window ids cannot contain duplicates"):
        load_evaluation_config(candidate / "evaluation.toml")


def test_load_evaluation_config_accepts_custom_scenarios_and_benchmark(tmp_path: Path):
    candidate = tmp_path / "candidate"
    write_strategy(candidate / "strategy.py")
    write_config(
        candidate / "evaluation.toml",
        extra="""

[benchmark]
symbol = "SPY"

[[scenarios]]
id = "realistic_base"
cost_scenario = "realistic_costs"
fill_scenario = "base_fill"
required = true

[scenarios.cost_model]
fee_bps_per_side = 0.25
slippage_bps_per_side = 0.75

[scenarios.fill_model]
price = "close"
entry_lag_bars = 2
exit_lag_bars = 1

[[scenarios]]
id = "stress_fill"
cost_scenario = "custom_costs"
fill_scenario = "custom_fill"
required = false
""",
    )

    config = load_evaluation_config(candidate / "evaluation.toml")

    assert config.benchmark is not None
    assert config.benchmark.symbol == "SPY"
    assert [item.id for item in config.scenarios] == ["realistic_base", "stress_fill"]
    assert config.scenarios[0].cost_model == CostModelConfig(
        fee_bps_per_side=0.25,
        slippage_bps_per_side=0.75,
    )
    assert config.scenarios[0].fill_model == FillModelConfig(
        price="close",
        entry_lag_bars=2,
        exit_lag_bars=1,
    )
    assert config.scenarios[1].cost_model is None
    assert config.scenarios[1].fill_model is None
    assert config.scenarios[1].required is False


def test_load_evaluation_config_rejects_all_optional_custom_scenarios(tmp_path: Path):
    candidate = tmp_path / "candidate"
    write_strategy(candidate / "strategy.py")
    write_config(
        candidate / "evaluation.toml",
        extra="""

[[scenarios]]
id = "optional_a"
required = false

[[scenarios]]
id = "optional_b"
required = false
""",
    )

    with pytest.raises(EvaluationConfigError, match="at least one required scenario"):
        load_evaluation_config(candidate / "evaluation.toml")


def test_load_evaluation_config_rejects_duplicate_custom_scenario_ids(tmp_path: Path):
    candidate = tmp_path / "candidate"
    write_strategy(candidate / "strategy.py")
    write_config(
        candidate / "evaluation.toml",
        extra="""

[[scenarios]]
id = "dup"

[[scenarios]]
id = "dup"
""",
    )

    with pytest.raises(EvaluationConfigError, match="scenario ids cannot contain duplicates"):
        load_evaluation_config(candidate / "evaluation.toml")


def test_load_evaluation_config_rejects_benchmark_symbol_outside_data_symbols(tmp_path: Path):
    candidate = tmp_path / "candidate"
    write_strategy(candidate / "strategy.py")
    write_config(
        candidate / "evaluation.toml",
        extra="""

[benchmark]
symbol = "IWM"
""",
    )

    with pytest.raises(
        EvaluationConfigError, match="benchmark.symbol must be included in data.symbols"
    ):
        load_evaluation_config(candidate / "evaluation.toml")


def test_load_evaluation_config_rejects_invalid_custom_scenario_model(tmp_path: Path):
    candidate = tmp_path / "candidate"
    write_strategy(candidate / "strategy.py")
    write_config(
        candidate / "evaluation.toml",
        extra="""

[[scenarios]]
id = "bad_cost"

[scenarios.cost_model]
fee_bps_per_side = -0.01
slippage_bps_per_side = 0.0
""",
    )

    with pytest.raises(EvaluationConfigError, match="fee_bps_per_side"):
        load_evaluation_config(candidate / "evaluation.toml")
