from __future__ import annotations

import re
from pathlib import Path

import pytest

from quant_strategies.runner.config import load_config
from quant_strategies.runner.errors import ConfigError
from quant_strategies.runner.strategy_loader import load_strategy


REPO_ROOT = Path(__file__).resolve().parents[1]


def write_strategy(repo_root: Path) -> None:
    strategy = repo_root / "tested" / "demo.py"
    strategy.parent.mkdir(parents=True, exist_ok=True)
    strategy.write_text("def generate_decisions(rows, params):\n    return []\n")


def write_config(
    repo_root: Path,
    *,
    strategy_path: str = "tested/demo.py",
    data_kind: str = "bars",
    dataset: str | None = "equity_1min",
    output_mode: str = "validate",
    results_dir: str = "results",
    fill_price: str = "close",
    entry_lag_bars: int = 1,
    allow_same_bar_close_fill: bool = False,
) -> Path:
    dataset_line = f'dataset = "{dataset}"\n' if dataset is not None else ""
    allow_line = "allow_same_bar_close_fill = true\n" if allow_same_bar_close_fill else ""
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
entry_lag_bars = {entry_lag_bars}
exit_lag_bars = 0
{allow_line}

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
    assert config.output.artifact_profile == "full"
    assert config.params == {"weight": 1.0}


def test_committed_run_configs_parse_without_live_data_access():
    repo_root = REPO_ROOT
    paths = sorted((repo_root / "runs").glob("*.toml"))
    assert paths, "expected at least one committed run config"

    for path in paths:
        load_config(path, repo_root=repo_root)


def test_committed_run_configs_use_decision_strategy_contract():
    repo_root = REPO_ROOT
    paths = sorted((repo_root / "runs").glob("*.toml"))
    assert paths, "expected at least one committed run config"

    for path in paths:
        config = load_config(path, repo_root=repo_root)
        assert callable(load_strategy(config.strategy_path, repo_root=repo_root))


def test_readme_does_not_document_named_run_configs():
    repo_root = REPO_ROOT
    readme = (repo_root / "README.md").read_text()
    assert re.search(r"\bruns/[A-Za-z0-9_.-]+\.toml\b", readme) is None
    assert "_smoke.toml" not in readme


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


def test_summary_artifact_profile_is_accepted(tmp_path: Path):
    write_strategy(tmp_path)
    path = write_config(tmp_path)
    path.write_text(path.read_text().replace('mode = "validate"\n', 'mode = "validate"\nartifact_profile = "summary"\n'))

    config = load_config(path, repo_root=tmp_path)

    assert config.output.artifact_profile == "summary"


def test_unknown_artifact_profile_is_rejected(tmp_path: Path):
    write_strategy(tmp_path)
    path = write_config(tmp_path)
    path.write_text(path.read_text().replace('mode = "validate"\n', 'mode = "validate"\nartifact_profile = "compact"\n'))

    with pytest.raises(ConfigError, match="artifact_profile"):
        load_config(path, repo_root=tmp_path)


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


def test_missing_relative_config_reports_resolved_path(tmp_path: Path):
    missing = tmp_path / "runs" / "missing.toml"

    with pytest.raises(ConfigError, match=re.escape(str(missing))):
        load_config("runs/missing.toml", repo_root=tmp_path)


def test_close_fill_zero_lag_is_rejected_by_default(tmp_path: Path):
    write_strategy(tmp_path)

    with pytest.raises(ConfigError, match="allow_same_bar_close_fill"):
        load_config(write_config(tmp_path, entry_lag_bars=0), repo_root=tmp_path)


def test_close_fill_zero_lag_accepts_explicit_opt_in(tmp_path: Path):
    write_strategy(tmp_path)

    config = load_config(
        write_config(tmp_path, entry_lag_bars=0, allow_same_bar_close_fill=True),
        repo_root=tmp_path,
    )

    assert config.fill_model.entry_lag_bars == 0
    assert config.fill_model.allow_same_bar_close_fill is True


def test_future_bar_close_fill_remains_accepted(tmp_path: Path):
    write_strategy(tmp_path)

    config = load_config(write_config(tmp_path, entry_lag_bars=1), repo_root=tmp_path)

    assert config.fill_model.entry_lag_bars == 1


def test_quote_fill_is_supported_by_internal_evaluator(tmp_path: Path):
    write_strategy(tmp_path)

    config = load_config(
        write_config(tmp_path, data_kind="forex_with_quotes", dataset=None, fill_price="quote"),
        repo_root=tmp_path,
    )

    assert config.fill_model.price == "quote"
