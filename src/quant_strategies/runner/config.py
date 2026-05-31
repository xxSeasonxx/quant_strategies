from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, ValidationError, ValidationInfo, field_validator

from quant_strategies.core.config import (
    CostModelConfig,
    DataConfig,
    FillModelConfig,
    SharedConfigModel,
    StrategyExecutionSpec,
    default_repo_root,
)
from quant_strategies.runner.errors import ConfigError


RunMode = Literal["screen", "gate"]
ArtifactProfile = Literal["diagnostic", "full", "summary"]
# Row-contract strictness is an EXPLICIT run policy, independent of artifact
# verbosity (`artifact_profile`). The quick-run defaults to the lenient "search"
# contract; set "validation" to make missing/invalid `available_at` fail the run.
RowContractStrictness = Literal["search", "validation"]

_SOURCE_LIKE_OUTPUT_ROOTS = frozenset(
    {
        "src",
        "tests",
        "docs",
        "runs",
        "examples",
        "tested",
        "untested",
        "researched",
    }
)


class RunnerConfigModel(SharedConfigModel):
    pass


def _repo_root(info: ValidationInfo) -> Path:
    root = info.context.get("repo_root") if info.context else None
    return Path(root).resolve() if root is not None else default_repo_root()


def _resolve_inside_repo(value: Path, repo_root: Path, field_name: str) -> Path:
    resolved = value if value.is_absolute() else repo_root / value
    resolved = resolved.resolve()
    try:
        resolved.relative_to(repo_root)
    except ValueError as exc:
        raise ValueError(f"{field_name} must resolve inside repository: {repo_root}") from exc
    return resolved


def _reject_source_like_output_dir(path: Path, repo_root: Path, field_name: str) -> None:
    for name in sorted(_SOURCE_LIKE_OUTPUT_ROOTS):
        source_root = repo_root / name
        try:
            path.relative_to(source_root)
        except ValueError:
            continue
        raise ValueError(
            f"{field_name} must not resolve inside source or input directory: {name}/"
        )


def resolve_config_path(path: str | Path, *, repo_root: Path | None = None) -> Path:
    root = Path(repo_root).resolve() if repo_root is not None else default_repo_root()
    config_path = Path(path)
    if config_path.is_absolute():
        return config_path.resolve()
    return (root / config_path).resolve()


class OutputConfig(RunnerConfigModel):
    results_dir: Path
    mode: RunMode
    artifact_profile: ArtifactProfile = "diagnostic"
    diagnostic_sample_trades: int = Field(default=5, ge=1, le=20)

    @field_validator("results_dir")
    @classmethod
    def validate_results_dir(cls, value: Path, info: ValidationInfo) -> Path:
        repo_root = _repo_root(info)
        resolved = _resolve_inside_repo(value, repo_root, "output.results_dir")
        _reject_source_like_output_dir(resolved, repo_root, "output.results_dir")
        return resolved


class RunConfig(RunnerConfigModel):
    strategy_path: Path
    strategy_id: str = Field(min_length=1)
    data: DataConfig
    params: dict[str, Any] = Field(default_factory=dict)
    fill_model: FillModelConfig
    cost_model: CostModelConfig
    output: OutputConfig
    row_contract: RowContractStrictness = "search"

    @field_validator("strategy_path")
    @classmethod
    def validate_strategy_path(cls, value: Path, info: ValidationInfo) -> Path:
        return _resolve_inside_repo(value, _repo_root(info), "strategy_path")

    @field_validator("strategy_id")
    @classmethod
    def validate_strategy_id(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("strategy_id cannot be empty")
        return stripped

    def to_execution_spec(self) -> StrategyExecutionSpec:
        return StrategyExecutionSpec(
            strategy_path=self.strategy_path,
            strategy_id=self.strategy_id,
            data=self.data,
            params=self.params,
            fill_model=self.fill_model,
            cost_model=self.cost_model,
        )


def load_config(path: str | Path, *, repo_root: Path | None = None) -> RunConfig:
    root = Path(repo_root).resolve() if repo_root is not None else default_repo_root()
    config_path = resolve_config_path(path, repo_root=root)
    try:
        payload = tomllib.loads(config_path.read_text())
    except OSError as exc:
        raise ConfigError(f"could not read config: {config_path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML in config: {exc}") from exc

    try:
        return RunConfig.model_validate(payload, context={"repo_root": root})
    except ValidationError as exc:
        raise ConfigError(str(exc)) from exc
