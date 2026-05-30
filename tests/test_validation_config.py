from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from quant_strategies.core.config import StrategyExecutionSpec
from quant_strategies.validation.config import load_validation_config, resolve_validation_config_path
from quant_strategies.validation.errors import ValidationConfigError


def test_shared_config_primitives_are_neutral_not_runner_owned():
    from quant_strategies.core.config import CostModelConfig, DataConfig, FillModelConfig
    from quant_strategies.runner import config as runner_config
    from quant_strategies.validation.config import ScenarioRunConfig, ValidationConfig

    assert DataConfig.__module__ == "quant_strategies.core.config"
    assert FillModelConfig.__module__ == "quant_strategies.core.config"
    assert CostModelConfig.__module__ == "quant_strategies.core.config"
    assert runner_config.DataConfig is DataConfig
    assert runner_config.FillModelConfig is FillModelConfig
    assert runner_config.CostModelConfig is CostModelConfig
    assert ValidationConfig.model_fields["data"].annotation is DataConfig
    assert ValidationConfig.model_fields["fill_model"].annotation is FillModelConfig
    assert ValidationConfig.model_fields["cost_model"].annotation is CostModelConfig
    assert ScenarioRunConfig.model_fields["data"].annotation is DataConfig
    assert ScenarioRunConfig.model_fields["fill_model"].annotation is FillModelConfig
    assert ScenarioRunConfig.model_fields["cost_model"].annotation is CostModelConfig


def write_strategy(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("def generate_decisions(rows, params):\n    return []\n")


def write_config(
    path: Path,
    strategy_path: str = "strategy.py",
    *,
    include_readiness: bool = True,
    search_pressure: str | None = 'prior_search = "none"',
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
    search_pressure_section = (
        f"""

[search_pressure]
{search_pressure}
"""
        if search_pressure is not None
        else ""
    )
    path.write_text(
        f"""
strategy_path = "{strategy_path}"
strategy_id = "demo"

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
{search_pressure_section}
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
    assert config.search_pressure.prior_search == "none"


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


def test_load_validation_config_accepts_search_pressure_metadata(tmp_path: Path):
    candidate = tmp_path / "candidate"
    write_strategy(candidate / "strategy.py")
    config_path = candidate / "validation.toml"
    write_config(
        config_path,
        search_pressure="""
prior_search = "known"
candidate_count = 120
trial_count = 18
parameter_search_space = { lookback = [12, 24, 48], threshold = [0.5, 1.0] }
selection_rule = "top risk-adjusted smoke score"
split_ids = ["validation_2026_h1", "validation_2026_h2"]
""".strip(),
    )

    config = load_validation_config(config_path)

    assert config.search_pressure.prior_search == "known"
    assert config.search_pressure.candidate_count == 120
    assert config.search_pressure.trial_count == 18
    assert config.search_pressure.parameter_search_space == {
        "lookback": [12, 24, 48],
        "threshold": [0.5, 1.0],
    }
    assert config.search_pressure.selection_rule == "top risk-adjusted smoke score"
    assert config.search_pressure.split_ids == ("validation_2026_h1", "validation_2026_h2")


def test_load_validation_config_accepts_unknown_search_pressure_disclosure(tmp_path: Path):
    candidate = tmp_path / "candidate"
    write_strategy(candidate / "strategy.py")
    config_path = candidate / "validation.toml"
    write_config(config_path, search_pressure='prior_search = "unknown"')

    config = load_validation_config(config_path)

    assert config.search_pressure.prior_search == "unknown"
    assert config.search_pressure.candidate_count is None


def test_load_validation_config_requires_search_pressure_disclosure(tmp_path: Path):
    candidate = tmp_path / "candidate"
    write_strategy(candidate / "strategy.py")
    config_path = candidate / "validation.toml"
    write_config(config_path, search_pressure=None)

    with pytest.raises(ValidationConfigError, match=r"requires \[search_pressure\]"):
        load_validation_config(config_path)


def test_load_validation_config_requires_prior_search_field(tmp_path: Path):
    candidate = tmp_path / "candidate"
    write_strategy(candidate / "strategy.py")
    config_path = candidate / "validation.toml"
    write_config(config_path, search_pressure="candidate_count = 12")

    with pytest.raises(ValidationConfigError, match="search_pressure.prior_search is required"):
        load_validation_config(config_path)


@pytest.mark.parametrize("prior_search", ["none", "unknown"])
def test_load_validation_config_rejects_search_metadata_without_known_prior_search(
    tmp_path: Path,
    prior_search: str,
):
    candidate = tmp_path / "candidate"
    write_strategy(candidate / "strategy.py")
    config_path = candidate / "validation.toml"
    write_config(
        config_path,
        search_pressure=f"""
prior_search = "{prior_search}"
candidate_count = 120
""".strip(),
    )

    with pytest.raises(ValidationConfigError, match=f"prior_search='{prior_search}'"):
        load_validation_config(config_path)


@pytest.mark.parametrize(
    ("search_pressure", "message"),
    [
        ('prior_search = "known"', "requires: candidate_count, trial_count, selection_rule"),
        (
            'prior_search = "known"\ncandidate_count = 10\nselection_rule = "best score"',
            "requires: trial_count",
        ),
        (
            'prior_search = "known"\ncandidate_count = 10\ntrial_count = 3',
            "requires: selection_rule",
        ),
    ],
)
def test_load_validation_config_rejects_incomplete_known_search_pressure(
    tmp_path: Path,
    search_pressure: str,
    message: str,
):
    candidate = tmp_path / "candidate"
    write_strategy(candidate / "strategy.py")
    config_path = candidate / "validation.toml"
    write_config(config_path, search_pressure=search_pressure)

    with pytest.raises(ValidationConfigError, match=message):
        load_validation_config(config_path)


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


def test_validation_config_converts_to_execution_spec_with_config_base_dir(tmp_path: Path):
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

    spec = config.to_execution_spec(config.windows[0])

    assert isinstance(spec, StrategyExecutionSpec)
    assert spec.strategy_id == "demo"
    assert spec.fill_model == config.fill_model
    assert spec.cost_model == config.cost_model
    assert spec.data.start == date(2026, 1, 1)
    assert spec.data.end == date(2026, 6, 30)


def test_validation_does_not_import_runner_config_for_execution():
    # F9: validation adapts into the neutral StrategyExecutionSpec and must never
    # import the runner's RunConfig for execution.
    import ast
    import inspect

    import quant_strategies.validation as validation_pkg
    import quant_strategies.validation.config as validation_config

    def imported_modules(module: object) -> set[str]:
        tree = ast.parse(inspect.getsource(module))
        modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module)
            elif isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
        return modules

    for module in (validation_pkg, validation_config):
        assert "quant_strategies.runner.config" not in imported_modules(module)


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
