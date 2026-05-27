from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from quant_strategies.runner.config import RunConfig
from quant_strategies.validation.config import load_validation_config, resolve_validation_config_path
from quant_strategies.validation.errors import ValidationConfigError


def write_strategy(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("def generate_decisions(rows, params):\n    return []\n")


def write_config(path: Path, strategy_path: str = "researched/demo/strategy.py") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""
strategy_path = "{strategy_path}"
strategy_id = "demo"
backend = "fake"

[[windows]]
id = "validation_2026_h1"
start = "2026-01-01"
end = "2026-06-30"

[data]
kind = "crypto_perp_funding"
symbols = ["BTC-PERP"]
strict = true
start = "2026-01-01"
end = "2026-06-30"

[params]
weight = 1.0

[fill_model]
price = "close"
entry_lag_bars = 1
exit_lag_bars = 0

[cost_model]
fee_bps_per_side = 0.5
slippage_bps_per_side = 0.5

[output]
results_dir = "validation_results/demo"
""".lstrip()
    )


def test_resolve_validation_config_from_package_path(tmp_path: Path):
    package = tmp_path / "researched" / "demo"
    write_config(package / "validation.toml")

    resolved = resolve_validation_config_path(package, repo_root=tmp_path)

    assert resolved == package / "validation.toml"


def test_load_validation_config_resolves_paths_inside_repo(tmp_path: Path):
    write_strategy(tmp_path / "researched" / "demo" / "strategy.py")
    write_config(tmp_path / "researched" / "demo" / "validation.toml")

    config = load_validation_config(tmp_path / "researched" / "demo", repo_root=tmp_path)

    assert config.strategy_path == tmp_path / "researched" / "demo" / "strategy.py"
    assert config.output.results_dir == tmp_path / "validation_results" / "demo"
    assert config.windows[0].id == "validation_2026_h1"
    assert config.paper_readiness.enabled is True
    assert config.paper_readiness.min_windows == 2
    assert config.paper_readiness.min_total_trades == 30
    assert config.paper_readiness.min_positive_window_fraction == 0.5
    assert config.paper_readiness.max_stressed_net_loss == -0.02
    assert config.paper_readiness.max_fill_lag_net_loss == -0.02


def test_load_validation_config_accepts_paper_readiness_overrides(tmp_path: Path):
    write_strategy(tmp_path / "researched" / "demo" / "strategy.py")
    config_path = tmp_path / "researched" / "demo" / "validation.toml"
    write_config(config_path)
    config_path.write_text(
        config_path.read_text()
        + """

[paper_readiness]
enabled = false
min_windows = 3
min_total_trades = 45
min_positive_window_fraction = 0.75
max_stressed_net_loss = -0.05
max_fill_lag_net_loss = -0.03
"""
    )

    config = load_validation_config(config_path, repo_root=tmp_path)

    assert config.paper_readiness.enabled is False
    assert config.paper_readiness.min_windows == 3
    assert config.paper_readiness.min_total_trades == 45
    assert config.paper_readiness.min_positive_window_fraction == 0.75
    assert config.paper_readiness.max_stressed_net_loss == -0.05
    assert config.paper_readiness.max_fill_lag_net_loss == -0.03


@pytest.mark.parametrize(
    ("paper_readiness_text", "message"),
    [
        (
            """
[paper_readiness]
min_windows = 0
""",
            "greater than or equal to 1",
        ),
        (
            """
[paper_readiness]
min_total_trades = 0
""",
            "greater than or equal to 1",
        ),
        (
            """
[paper_readiness]
min_positive_window_fraction = -0.1
""",
            "greater than or equal to 0",
        ),
        (
            """
[paper_readiness]
min_positive_window_fraction = 1.1
""",
            "less than or equal to 1",
        ),
        (
            """
[paper_readiness]
max_stressed_net_loss = 0.01
""",
            "less than or equal to 0",
        ),
        (
            """
[paper_readiness]
max_fill_lag_net_loss = 0.01
""",
            "less than or equal to 0",
        ),
    ],
)
def test_load_validation_config_rejects_invalid_paper_readiness(
    tmp_path: Path,
    paper_readiness_text: str,
    message: str,
):
    write_strategy(tmp_path / "researched" / "demo" / "strategy.py")
    config_path = tmp_path / "researched" / "demo" / "validation.toml"
    write_config(config_path)
    config_path.write_text(config_path.read_text() + paper_readiness_text)

    with pytest.raises(ValidationConfigError, match=message):
        load_validation_config(config_path, repo_root=tmp_path)


def test_validation_config_converts_to_run_config_with_repo_root_override(tmp_path: Path):
    write_strategy(tmp_path / "researched" / "demo" / "strategy.py")
    config_path = tmp_path / "researched" / "demo" / "validation.toml"
    write_config(config_path)
    config_path.write_text(
        config_path.read_text().replace(
            'strict = true\nstart = "2026-01-01"\nend = "2026-06-30"',
            'strict = true\nstart = "2025-01-01"\nend = "2026-12-31"',
        )
    )
    config = load_validation_config(tmp_path / "researched" / "demo", repo_root=tmp_path)
    results_dir = tmp_path / "validation_results" / "demo" / "run"

    run_config = config.to_run_config(config.windows[0], results_dir=results_dir)

    assert isinstance(run_config, RunConfig)
    assert run_config.output.mode == "validate"
    assert run_config.output.results_dir == results_dir
    assert run_config.data.start == date(2026, 1, 1)
    assert run_config.data.end == date(2026, 6, 30)


def test_load_validation_config_rejects_generate_strategy_outside_repo(tmp_path: Path):
    outside = tmp_path.parent / "outside.py"
    outside.write_text("def generate_decisions(rows, params):\n    return []\n")
    write_config(tmp_path / "researched" / "demo" / "validation.toml", strategy_path=str(outside))

    with pytest.raises(ValidationConfigError, match="strategy_path must resolve inside repository"):
        load_validation_config(tmp_path / "researched" / "demo", repo_root=tmp_path)


def test_load_validation_config_rejects_missing_windows(tmp_path: Path):
    config_path = tmp_path / "researched" / "demo" / "validation.toml"
    write_config(config_path)
    config_text = config_path.read_text()
    config_path.write_text(config_text.replace("[[windows]]\nid = \"validation_2026_h1\"\nstart = \"2026-01-01\"\nend = \"2026-06-30\"\n\n", ""))

    with pytest.raises(ValidationConfigError, match="windows"):
        load_validation_config(tmp_path / "researched" / "demo", repo_root=tmp_path)


def test_load_validation_config_rejects_empty_windows(tmp_path: Path):
    config_path = tmp_path / "researched" / "demo" / "validation.toml"
    write_config(config_path)
    config_text = config_path.read_text()
    config_path.write_text(config_text.replace("[[windows]]\nid = \"validation_2026_h1\"\nstart = \"2026-01-01\"\nend = \"2026-06-30\"\n\n", "windows = []\n\n"))

    with pytest.raises(ValidationConfigError, match="windows"):
        load_validation_config(tmp_path / "researched" / "demo", repo_root=tmp_path)


@pytest.mark.parametrize(
    ("readiness_text", "message"),
    [
        (
            """
[readiness]
min_observations_per_decision = 0
required_observation_fields = ["close"]
""",
            "greater than or equal to 1",
        ),
        (
            """
[readiness]
min_observations_per_decision = 1
""",
            "required_observation_fields",
        ),
        (
            """
[readiness]
min_observations_per_decision = 1
required_observation_fields = []
""",
            "required_observation_fields",
        ),
        (
            """
[readiness]
min_observations_per_decision = 1
required_observation_fields = [""]
""",
            "cannot contain empty fields",
        ),
        (
            """
[readiness]
min_observations_per_decision = 1
required_observation_fields = ["close", "close"]
""",
            "cannot contain duplicates",
        ),
    ],
)
def test_load_validation_config_rejects_vacuous_readiness_metadata(
    tmp_path: Path,
    readiness_text: str,
    message: str,
):
    write_strategy(tmp_path / "researched" / "demo" / "strategy.py")
    config_path = tmp_path / "researched" / "demo" / "validation.toml"
    write_config(config_path)
    config_path.write_text(config_path.read_text() + readiness_text)

    with pytest.raises(ValidationConfigError, match=message):
        load_validation_config(config_path, repo_root=tmp_path)
