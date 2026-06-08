from __future__ import annotations

import re
from pathlib import Path

import pytest

from quant_strategies.core.errors import ConfigError
from quant_strategies.decisions import load_decision_strategy
from quant_strategies.runner.config import load_config

REPO_ROOT = Path(__file__).resolve().parents[1]


def write_strategy(repo_root: Path) -> None:
    strategy = repo_root / "strategies" / "demo.py"
    strategy.parent.mkdir(parents=True, exist_ok=True)
    strategy.write_text("def generate_decisions(rows, params):\n    return []\n")


def write_config(
    repo_root: Path,
    *,
    strategy_path: str = "strategies/demo.py",
    data_kind: str = "bars",
    dataset: str | None = "equity_1min",
    quick_checks: bool | None = None,
    results_dir: str = "results",
    fill_price: str = "close",
    entry_lag_bars: int = 1,
    fill_model_extra: str = "",
    artifact_profile: str | None = None,
    output_extra: str = "",
    data_extra: str = "",
) -> Path:
    dataset_line = f'dataset = "{dataset}"\n' if dataset is not None else ""
    artifact_profile_line = (
        f'artifact_profile = "{artifact_profile}"\n' if artifact_profile is not None else ""
    )
    quick_checks_line = (
        f"quick_checks = {str(quick_checks).lower()}\n" if quick_checks is not None else ""
    )
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
	{data_extra}

	[params]
weight = 1.0

[fill_model]
price = "{fill_price}"
entry_lag_bars = {entry_lag_bars}
exit_lag_bars = 0
{fill_model_extra}

[cost_model]
fee_bps_per_side = 0.0
slippage_bps_per_side = 0.0

[output]
results_dir = "{results_dir}"
{quick_checks_line}{artifact_profile_line}{output_extra}
'''.lstrip()
    )
    return config_path


def test_valid_run_config_is_accepted(tmp_path: Path):
    write_strategy(tmp_path)
    config = load_config(write_config(tmp_path), repo_root=tmp_path)

    assert config.strategy_path == tmp_path / "strategies" / "demo.py"
    assert config.strategy_id == "demo"
    assert config.data.symbols == ("SPY",)
    assert config.output.results_dir == tmp_path / "results"
    assert config.output.quick_checks is False
    assert config.output.artifact_profile == "diagnostic"
    assert config.output.diagnostic_sample_trades == 5
    assert config.params == {"weight": 1.0}
    assert config.data.load_start is None
    assert config.data.load_end is None


def test_data_load_window_fields_are_optional_and_validated(tmp_path: Path):
    write_strategy(tmp_path)
    config = load_config(
        write_config(
            tmp_path,
            data_extra='load_start = "2023-12-31"\nload_end = "2024-01-07"\n',
        ),
        repo_root=tmp_path,
    )

    assert config.data.start.isoformat() == "2024-01-01"
    assert config.data.end.isoformat() == "2024-01-05"
    assert config.data.load_start is not None
    assert config.data.load_start.isoformat() == "2023-12-31"
    assert config.data.load_end is not None
    assert config.data.load_end.isoformat() == "2024-01-07"


@pytest.mark.parametrize(
    ("data_extra", "message"),
    [
        ('load_end = "2024-01-04"\n', "load_end"),
        ('load_start = "2024-01-02"\n', "load_start"),
    ],
)
def test_data_load_window_must_cover_decision_window(
    tmp_path: Path,
    data_extra: str,
    message: str,
):
    write_strategy(tmp_path)

    with pytest.raises(ConfigError, match=message):
        load_config(write_config(tmp_path, data_extra=data_extra), repo_root=tmp_path)


def test_committed_run_configs_parse_without_live_data_access():
    repo_root = REPO_ROOT
    paths = sorted((repo_root / "runs").glob("*.toml"))
    assert paths, "expected at least one committed run config"

    for path in paths:
        load_config(path, repo_root=repo_root)


def test_committed_run_configs_default_to_diagnostic_profile():
    repo_root = REPO_ROOT
    paths = sorted((repo_root / "runs").glob("*.toml"))
    assert paths, "expected at least one committed run config"

    for path in paths:
        text = path.read_text()
        config = load_config(path, repo_root=repo_root)
        if "artifact_profile" not in text:
            assert config.output.artifact_profile == "diagnostic"


def test_committed_run_configs_use_focused_causality_for_iteration():
    repo_root = REPO_ROOT
    paths = sorted((repo_root / "runs").glob("*.toml"))
    assert paths, "expected at least one committed run config"

    for path in paths:
        config = load_config(path, repo_root=repo_root)
        assert config.output.causality_check == "focused", path


def test_output_quick_checks_accepts_explicit_true_and_false(tmp_path: Path):
    write_strategy(tmp_path)

    enabled = load_config(write_config(tmp_path, quick_checks=True), repo_root=tmp_path)
    disabled = load_config(write_config(tmp_path, quick_checks=False), repo_root=tmp_path)

    assert enabled.output.quick_checks is True
    assert disabled.output.quick_checks is False


def test_committed_run_configs_use_decision_strategy_contract():
    repo_root = REPO_ROOT
    paths = sorted((repo_root / "runs").glob("*.toml"))
    assert paths, "expected at least one committed run config"

    for path in paths:
        config = load_config(path, repo_root=repo_root)
        assert callable(load_decision_strategy(config.strategy_path, repo_root=repo_root))


def test_readme_does_not_document_named_run_configs():
    repo_root = REPO_ROOT
    readme = (repo_root / "README.md").read_text()
    assert re.search(r"\bruns/[A-Za-z0-9_.-]+\.toml\b", readme) is None
    assert "_smo" + "ke.toml" not in readme


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("strategy_id = 'demo'\n", "strategy_path"),
        ("strategy_path = 'strategies/demo.py'\nstrategy_id = 'demo'\n", "data"),
    ],
)
def test_missing_required_config_fields_are_rejected(tmp_path: Path, content: str, message: str):
    path = tmp_path / "run.toml"
    path.write_text(content)

    with pytest.raises(ConfigError, match=message):
        load_config(path, repo_root=tmp_path)


def test_legacy_output_mode_is_rejected(tmp_path: Path):
    write_strategy(tmp_path)
    legacy_mode_line = "mode = " + '"gate"' + "\n"

    with pytest.raises(ConfigError, match="mode"):
        load_config(write_config(tmp_path, output_extra=legacy_mode_line), repo_root=tmp_path)


@pytest.mark.parametrize("artifact_profile", ["diagnostic", "summary", "full"])
def test_supported_artifact_profiles_are_accepted(tmp_path: Path, artifact_profile: str):
    write_strategy(tmp_path)
    config = load_config(
        write_config(tmp_path, artifact_profile=artifact_profile), repo_root=tmp_path
    )

    assert config.output.artifact_profile == artifact_profile


def test_full_artifact_profile_is_accepted_with_explicit_opt_in(tmp_path: Path):
    write_strategy(tmp_path)
    config = load_config(write_config(tmp_path, artifact_profile="full"), repo_root=tmp_path)

    assert config.output.artifact_profile == "full"


def test_unknown_artifact_profile_is_rejected(tmp_path: Path):
    write_strategy(tmp_path)
    path = write_config(tmp_path)
    path.write_text(path.read_text() + 'artifact_profile = "compact"\n')

    with pytest.raises(ConfigError, match="artifact_profile"):
        load_config(path, repo_root=tmp_path)


@pytest.mark.parametrize("value", [1, 5, 20])
def test_diagnostic_sample_trades_range_is_accepted(tmp_path: Path, value: int):
    write_strategy(tmp_path)
    path = write_config(tmp_path)
    path.write_text(
        path.read_text().replace(
            '[output]\nresults_dir = "results"\n',
            f'[output]\nresults_dir = "results"\ndiagnostic_sample_trades = {value}\n',
        )
    )

    config = load_config(path, repo_root=tmp_path)

    assert config.output.diagnostic_sample_trades == value


@pytest.mark.parametrize("value", [0, 21])
def test_diagnostic_sample_trades_out_of_range_is_rejected(tmp_path: Path, value: int):
    write_strategy(tmp_path)
    path = write_config(tmp_path)
    path.write_text(
        path.read_text().replace(
            '[output]\nresults_dir = "results"\n',
            f'[output]\nresults_dir = "results"\ndiagnostic_sample_trades = {value}\n',
        )
    )

    with pytest.raises(ConfigError, match="diagnostic_sample_trades"):
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


@pytest.mark.parametrize(
    "results_dir",
    [
        "src/results",
        "tests/results",
        "docs/results",
        "runs/results",
        "examples/results",
        "strategies/results",
        "untested/results",
        "outputs/demo",
    ],
)
def test_output_path_outside_generated_results_root_is_rejected(tmp_path: Path, results_dir: str):
    write_strategy(tmp_path)

    with pytest.raises(
        ConfigError,
        match="output.results_dir must resolve inside generated output directory",
    ):
        load_config(write_config(tmp_path, results_dir=results_dir), repo_root=tmp_path)


def test_output_path_under_results_subdir_named_like_source_is_accepted(tmp_path: Path):
    write_strategy(tmp_path)

    config = load_config(write_config(tmp_path, results_dir="results/src/demo"), repo_root=tmp_path)

    assert config.output.results_dir == tmp_path / "results" / "src" / "demo"


def test_missing_relative_config_reports_resolved_path(tmp_path: Path):
    missing = tmp_path / "runs" / "missing.toml"

    with pytest.raises(ConfigError, match=re.escape(str(missing))):
        load_config("runs/missing.toml", repo_root=tmp_path)


@pytest.mark.parametrize("fill_price", ["close", "open", "quote"])
def test_zero_lag_entry_fill_is_rejected_for_every_price(tmp_path: Path, fill_price: str):
    write_strategy(tmp_path)

    with pytest.raises(ConfigError, match="greater than or equal to 1"):
        load_config(
            write_config(tmp_path, fill_price=fill_price, entry_lag_bars=0),
            repo_root=tmp_path,
        )


def test_removed_same_bar_close_fill_flag_is_rejected_as_unknown(tmp_path: Path):
    write_strategy(tmp_path)
    removed_flag = "allow_same_bar" + "_close_fill"

    with pytest.raises(ConfigError, match=removed_flag):
        load_config(
            write_config(tmp_path, fill_model_extra=f"{removed_flag} = true\n"),
            repo_root=tmp_path,
        )


def test_removed_data_strict_toggle_is_rejected_as_unknown(tmp_path: Path):
    # Loads are always strict now; a leftover `strict` key in [data] must fail loudly
    # (extra="forbid"), not be silently ignored.
    write_strategy(tmp_path)
    config_path = write_config(tmp_path)
    config_path.write_text(
        config_path.read_text().replace(
            'symbols = ["SPY"]\n',
            'symbols = ["SPY"]\nstrict = true\n',
        )
    )

    with pytest.raises(ConfigError, match="strict"):
        load_config(config_path, repo_root=tmp_path)


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
