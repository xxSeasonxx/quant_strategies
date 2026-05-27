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


def write_config(
    path: Path,
    strategy_path: str = "strategy.py",
    *,
    include_readiness: bool = True,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    readiness = (
        """

[readiness]
min_observations_per_decision = 1
required_observation_fields = ["close"]
"""
        if include_readiness
        else ""
    )
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
{readiness}

[output]
results_dir = "validation_results/demo"
""".lstrip()
    )


def test_resolve_validation_config_from_file_path(tmp_path: Path):
    candidate = tmp_path / "candidate"
    config_path = candidate / "validation.toml"
    write_config(config_path)

    resolved = resolve_validation_config_path(config_path)

    assert resolved == config_path


def test_resolve_validation_config_from_relative_path_uses_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    candidate = tmp_path / "candidate"
    config_path = candidate / "validation.toml"
    write_config(config_path)
    monkeypatch.chdir(tmp_path)

    resolved = resolve_validation_config_path("candidate/validation.toml")

    assert resolved == config_path


def test_resolve_validation_config_rejects_directory_path(tmp_path: Path):
    candidate = tmp_path / "candidate"
    write_config(candidate / "validation.toml")

    with pytest.raises(ValidationConfigError, match="validation config path must be a TOML file"):
        resolve_validation_config_path(candidate)


def test_resolve_validation_config_rejects_non_toml_path(tmp_path: Path):
    candidate = tmp_path / "candidate"
    not_toml = candidate / "validation.txt"
    not_toml.parent.mkdir()
    not_toml.write_text("")

    with pytest.raises(ValidationConfigError, match="validation config path must be a TOML file"):
        resolve_validation_config_path(not_toml)


def test_load_validation_config_resolves_paths_from_config_directory(tmp_path: Path):
    candidate = tmp_path / "scratch" / "candidate_a"
    write_strategy(candidate / "strategy.py")
    write_config(candidate / "validation.toml")

    config = load_validation_config(candidate / "validation.toml")

    assert config.base_dir == candidate
    assert config.strategy_path == candidate / "strategy.py"
    assert config.output.results_dir == candidate / "validation_results" / "demo"
    assert config.windows[0].id == "validation_2026_h1"
    assert config.readiness.min_observations_per_decision == 1
    assert config.readiness.required_observation_fields == ("close",)
    assert config.paper_readiness.enabled is True
    assert config.paper_readiness.min_windows == 2
    assert config.paper_readiness.min_total_trades == 30
    assert config.paper_readiness.min_positive_window_fraction == 0.5
    assert config.paper_readiness.max_stressed_net_loss == -0.02
    assert config.paper_readiness.max_fill_lag_net_loss == -0.02


def test_load_validation_config_accepts_paper_readiness_overrides(tmp_path: Path):
    candidate = tmp_path / "candidate"
    write_strategy(candidate / "strategy.py")
    config_path = candidate / "validation.toml"
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

    config = load_validation_config(config_path)

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
    candidate = tmp_path / "candidate"
    write_strategy(candidate / "strategy.py")
    config_path = candidate / "validation.toml"
    write_config(config_path)
    config_path.write_text(config_path.read_text() + paper_readiness_text)

    with pytest.raises(ValidationConfigError, match=message):
        load_validation_config(config_path)


def test_validation_config_converts_to_run_config_with_config_base_dir(tmp_path: Path):
    candidate = tmp_path / "candidate"
    write_strategy(candidate / "strategy.py")
    config_path = candidate / "validation.toml"
    write_config(config_path)
    config_path.write_text(
        config_path.read_text().replace(
            'strict = true\nstart = "2026-01-01"\nend = "2026-06-30"',
            'strict = true\nstart = "2025-01-01"\nend = "2026-12-31"',
        )
    )
    config = load_validation_config(config_path)
    results_dir = candidate / "validation_results" / "demo" / "run"

    run_config = config.to_run_config(config.windows[0], results_dir=results_dir)

    assert isinstance(run_config, RunConfig)
    assert run_config.output.mode == "validate"
    assert run_config.output.results_dir == results_dir
    assert run_config.data.start == date(2026, 1, 1)
    assert run_config.data.end == date(2026, 6, 30)


def test_load_validation_config_rejects_strategy_path_outside_config_directory(tmp_path: Path):
    candidate = tmp_path / "candidate"
    outside = tmp_path / "outside.py"
    outside.write_text("def generate_decisions(rows, params):\n    return []\n")
    write_config(candidate / "validation.toml", strategy_path="../outside.py")

    with pytest.raises(ValidationConfigError, match="strategy_path must resolve inside config directory"):
        load_validation_config(candidate / "validation.toml")


def test_load_validation_config_rejects_absolute_strategy_path_outside_config_directory(
    tmp_path: Path,
):
    candidate = tmp_path / "candidate"
    outside = tmp_path / "outside.py"
    outside.write_text("def generate_decisions(rows, params):\n    return []\n")
    write_config(candidate / "validation.toml", strategy_path=str(outside))

    with pytest.raises(ValidationConfigError, match="strategy_path must resolve inside config directory"):
        load_validation_config(candidate / "validation.toml")


def test_load_validation_config_rejects_absolute_results_dir_outside_config_directory(
    tmp_path: Path,
):
    candidate = tmp_path / "candidate"
    outside_results = tmp_path / "validation_results"
    write_config(candidate / "validation.toml")
    config_path = candidate / "validation.toml"
    config_path.write_text(
        config_path.read_text().replace(
            'results_dir = "validation_results/demo"',
            f'results_dir = "{outside_results}"',
        )
    )

    with pytest.raises(ValidationConfigError, match="output.results_dir must resolve inside config directory"):
        load_validation_config(config_path)


def test_load_validation_config_rejects_missing_windows(tmp_path: Path):
    candidate = tmp_path / "candidate"
    config_path = candidate / "validation.toml"
    write_config(config_path)
    config_text = config_path.read_text()
    config_path.write_text(
        config_text.replace(
            '[[windows]]\nid = "validation_2026_h1"\nstart = "2026-01-01"\nend = "2026-06-30"\n\n',
            "",
        )
    )

    with pytest.raises(ValidationConfigError, match="windows"):
        load_validation_config(config_path)


def test_load_validation_config_rejects_empty_windows(tmp_path: Path):
    candidate = tmp_path / "candidate"
    config_path = candidate / "validation.toml"
    write_config(config_path)
    config_text = config_path.read_text()
    config_path.write_text(
        config_text.replace(
            '[[windows]]\nid = "validation_2026_h1"\nstart = "2026-01-01"\nend = "2026-06-30"\n\n',
            "windows = []\n\n",
        )
    )

    with pytest.raises(ValidationConfigError, match="windows"):
        load_validation_config(config_path)


def test_load_validation_config_requires_readiness_for_every_validation_config(
    tmp_path: Path,
):
    candidate = tmp_path / "candidate"
    write_strategy(candidate / "strategy.py")
    write_config(candidate / "validation.toml", include_readiness=False)

    with pytest.raises(ValidationConfigError, match="readiness"):
        load_validation_config(candidate / "validation.toml")


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
    candidate = tmp_path / "candidate"
    write_strategy(candidate / "strategy.py")
    config_path = candidate / "validation.toml"
    write_config(config_path, include_readiness=False)
    config_path.write_text(config_path.read_text() + readiness_text)

    with pytest.raises(ValidationConfigError, match=message):
        load_validation_config(config_path)
