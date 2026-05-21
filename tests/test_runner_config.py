from __future__ import annotations

from pathlib import Path

import pytest

from quant_strategies.runner import config as config_module
from quant_strategies.runner.config import load_config
from quant_strategies.runner.errors import ConfigError


def write_strategy(repo_root: Path) -> None:
    strategy = repo_root / "tested" / "demo.py"
    strategy.parent.mkdir(parents=True, exist_ok=True)
    strategy.write_text("def generate_signals(bars, params):\n    return []\n")


def write_config(
    repo_root: Path,
    *,
    strategy_path: str = "tested/demo.py",
    data_kind: str = "bars",
    dataset: str | None = "equity_1min",
    output_mode: str = "validate",
    results_dir: str = "results",
    fill_price: str = "close",
) -> Path:
    dataset_line = f'dataset = "{dataset}"\n' if dataset is not None else ""
    config_path = repo_root / "run.toml"
    config_path.write_text(
        f'''
strategy_path = "{strategy_path}"
strategy_id = "demo"

[data]
kind = "{data_kind}"
{dataset_line}symbols = ["SPY"]
start = "2024-01-01"
end = "2024-01-05"
strict = true

[params]
weight = 1.0

[fill_model]
price = "{fill_price}"
entry_lag_bars = 1
exit_lag_bars = 0

[cost_model]
fee_bps_per_side = 0.0
slippage_bps_per_side = 0.0

[output]
results_dir = "{results_dir}"
mode = "{output_mode}"
'''.lstrip()
    )
    return config_path


def test_valid_run_config_is_accepted(tmp_path: Path):
    write_strategy(tmp_path)
    config = load_config(write_config(tmp_path), repo_root=tmp_path)

    assert config.strategy_path == tmp_path / "tested" / "demo.py"
    assert config.strategy_id == "demo"
    assert config.data.symbols == ("SPY",)
    assert config.output.results_dir == tmp_path / "results"
    assert config.params == {"weight": 1.0}


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("strategy_id = 'demo'\n", "strategy_path"),
        ("strategy_path = 'tested/demo.py'\nstrategy_id = 'demo'\n", "data"),
    ],
)
def test_missing_required_config_fields_are_rejected(tmp_path: Path, content: str, message: str):
    path = tmp_path / "run.toml"
    path.write_text(content)

    with pytest.raises(ConfigError, match=message):
        load_config(path, repo_root=tmp_path)


def test_unknown_output_mode_is_rejected(tmp_path: Path):
    write_strategy(tmp_path)

    with pytest.raises(ConfigError, match="output.mode"):
        load_config(write_config(tmp_path, output_mode="paper"), repo_root=tmp_path)


def test_unsupported_data_kind_is_rejected(tmp_path: Path):
    write_strategy(tmp_path)

    with pytest.raises(ConfigError, match="data.kind"):
        load_config(write_config(tmp_path, data_kind="options", dataset=None), repo_root=tmp_path)


def test_strategy_path_escape_is_rejected(tmp_path: Path):
    write_strategy(tmp_path)

    with pytest.raises(ConfigError, match="strategy_path must resolve inside repository"):
        load_config(write_config(tmp_path, strategy_path="../outside.py"), repo_root=tmp_path)


def test_output_path_escape_is_rejected(tmp_path: Path):
    write_strategy(tmp_path)

    with pytest.raises(ConfigError, match="output.results_dir must resolve inside repository"):
        load_config(write_config(tmp_path, results_dir="../results"), repo_root=tmp_path)


def test_quote_fill_fails_when_quant_engine_lacks_quote_support(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    write_strategy(tmp_path)

    class NoQuoteFill:
        def __init__(self, **_: object) -> None:
            raise ValueError("quote unsupported")

    monkeypatch.setattr(config_module, "EngineFillModel", NoQuoteFill)

    with pytest.raises(ConfigError, match="does not support fill_model.price"):
        load_config(
            write_config(tmp_path, data_kind="forex_with_quotes", dataset=None, fill_price="quote"),
            repo_root=tmp_path,
        )
