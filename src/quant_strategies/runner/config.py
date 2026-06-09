from __future__ import annotations

import math
import tomllib
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, StrictInt, ValidationError, ValidationInfo, field_validator

from quant_strategies.core.config import (
    CostModelConfig,
    DataConfig,
    FillModelConfig,
    SharedConfigModel,
    StrategyExecutionSpec,
    default_repo_root,
)
from quant_strategies.core.errors import ConfigError

ArtifactProfile = Literal["diagnostic", "full", "summary"]
CausalityCheck = Literal["off", "emitted", "strict", "focused", "micro"]

_GENERATED_OUTPUT_ROOT = "results"


class RunnerConfigModel(SharedConfigModel):
    pass


def _repo_root(info: ValidationInfo) -> Path:
    root = info.context.get("repo_root") if info.context else None
    return Path(root).resolve() if root is not None else default_repo_root()


def _config_base(info: ValidationInfo) -> Path:
    base = info.context.get("base_dir") if info.context else None
    return Path(base).resolve() if base is not None else _repo_root(info)


def _resolve_inside_repo(value: Path, repo_root: Path, field_name: str) -> Path:
    resolved = value if value.is_absolute() else repo_root / value
    resolved = resolved.resolve()
    try:
        resolved.relative_to(repo_root)
    except ValueError as exc:
        raise ValueError(f"{field_name} must resolve inside repository: {repo_root}") from exc
    return resolved


def _resolve_strategy_path(value: Path, base_dir: Path, repo_root: Path) -> Path:
    resolved = value if value.is_absolute() else base_dir / value
    resolved = resolved.resolve()
    try:
        resolved.relative_to(base_dir)
    except ValueError as exc:
        raise ValueError(f"strategy_path must resolve inside config directory: {base_dir}") from exc
    try:
        resolved.relative_to(repo_root)
    except ValueError as exc:
        raise ValueError(f"strategy_path must resolve inside repository: {repo_root}") from exc
    return resolved


def _reject_non_generated_output_dir(path: Path, repo_root: Path, field_name: str) -> None:
    generated_root = repo_root / _GENERATED_OUTPUT_ROOT
    try:
        path.relative_to(generated_root)
    except ValueError as exc:
        raise ValueError(
            f"{field_name} must resolve inside generated output directory: "
            f"{_GENERATED_OUTPUT_ROOT}/"
        ) from exc


def resolve_config_path(path: str | Path, *, repo_root: Path | None = None) -> Path:
    root = Path(repo_root).resolve() if repo_root is not None else default_repo_root()
    config_path = Path(path)
    if config_path.is_absolute():
        return config_path.resolve()
    return (root / config_path).resolve()


class OutputConfig(RunnerConfigModel):
    results_dir: Path
    quick_checks: bool = False
    artifact_profile: ArtifactProfile = "diagnostic"
    diagnostic_sample_trades: int = Field(default=5, ge=1, le=20)
    causality_check: CausalityCheck = "strict"
    strict_probe_limit: StrictInt | None = Field(default=None, ge=0)
    focused_probe_limit: StrictInt = Field(default=64, ge=1)
    focused_timeout_seconds: float = Field(default=60.0, ge=0.0)
    micro_probe_limit: StrictInt = Field(default=5, ge=1)
    micro_timeout_seconds: float = Field(default=2.0, ge=0.0)

    @field_validator("results_dir")
    @classmethod
    def validate_results_dir(cls, value: Path, info: ValidationInfo) -> Path:
        repo_root = _repo_root(info)
        resolved = _resolve_inside_repo(value, repo_root, "output.results_dir")
        _reject_non_generated_output_dir(resolved, repo_root, "output.results_dir")
        return resolved

    @field_validator("focused_timeout_seconds", "micro_timeout_seconds")
    @classmethod
    def validate_timeout_seconds(cls, value: float, info: ValidationInfo) -> float:
        if not math.isfinite(value):
            raise ValueError(f"output.{info.field_name} must be finite")
        return value


class RunConfig(RunnerConfigModel):
    strategy_path: Path
    strategy_id: str = Field(min_length=1)
    data: DataConfig
    params: dict[str, Any] = Field(default_factory=dict)
    fill_model: FillModelConfig
    cost_model: CostModelConfig
    output: OutputConfig

    @field_validator("strategy_path")
    @classmethod
    def validate_strategy_path(cls, value: Path, info: ValidationInfo) -> Path:
        return _resolve_strategy_path(value, _config_base(info), _repo_root(info))

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
        return RunConfig.model_validate(
            payload,
            context={"repo_root": root, "base_dir": config_path.parent},
        )
    except ValidationError as exc:
        raise ConfigError(str(exc)) from exc
