from __future__ import annotations

import tomllib
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

from quant_strategies.core.config import (
    CostModelConfig,
    DataConfig,
    FillModelConfig,
    StrategyExecutionSpec,
)
from quant_strategies.evaluation.errors import EvaluationConfigError


class EvaluationConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _path_anchor(path: str | Path, *, repo_root: Path | None = None) -> Path:
    if repo_root is not None:
        return Path(repo_root).resolve()
    if Path(path).is_absolute():
        return Path("/")
    return Path.cwd().resolve()


def _config_base(info: ValidationInfo) -> Path:
    base = info.context.get("base_dir") if info.context else None
    return Path(base).resolve() if base is not None else Path.cwd().resolve()


def _resolve_inside_config_dir(value: Path, base_dir: Path, field_name: str) -> Path:
    resolved = value if value.is_absolute() else base_dir / value
    resolved = resolved.resolve()
    try:
        resolved.relative_to(base_dir)
    except ValueError as exc:
        raise ValueError(f"{field_name} must resolve inside config directory: {base_dir}") from exc
    return resolved


class EvaluationWindow(EvaluationConfigModel):
    id: str = Field(min_length=1)
    start: date
    end: date

    @field_validator("id")
    @classmethod
    def normalize_id(cls, value: str) -> str:
        window_id = value.strip()
        if not window_id:
            raise ValueError("window id cannot be empty")
        return window_id

    @model_validator(mode="after")
    def validate_window(self) -> EvaluationWindow:
        if self.end < self.start:
            raise ValueError("window end must be on or after start")
        return self


class EvaluationMetricsConfig(EvaluationConfigModel):
    annualization_periods_per_year: int = Field(gt=0)


class EvaluationOutputConfig(EvaluationConfigModel):
    results_dir: Path

    @field_validator("results_dir")
    @classmethod
    def validate_results_dir(cls, value: Path, info: ValidationInfo) -> Path:
        return _resolve_inside_config_dir(value, _config_base(info), "output.results_dir")


class EvaluationConfig(EvaluationConfigModel):
    _base_dir_path: Path = PrivateAttr(default_factory=lambda: Path.cwd().resolve())

    strategy_path: Path
    strategy_id: str = Field(min_length=1)
    windows: tuple[EvaluationWindow, ...] = Field(min_length=1)
    data: DataConfig
    params: dict[str, Any] = Field(default_factory=dict)
    fill_model: FillModelConfig
    cost_model: CostModelConfig
    metrics: EvaluationMetricsConfig
    output: EvaluationOutputConfig

    def model_post_init(self, context: Any, /) -> None:
        base = context.get("base_dir") if isinstance(context, dict) else None
        base_dir = Path(base).resolve() if base is not None else Path.cwd().resolve()
        object.__setattr__(self, "_base_dir_path", base_dir)

    @property
    def base_dir(self) -> Path:
        return self._base_dir_path

    @field_validator("strategy_path")
    @classmethod
    def validate_strategy_path(cls, value: Path, info: ValidationInfo) -> Path:
        return _resolve_inside_config_dir(value, _config_base(info), "strategy_path")

    @field_validator("strategy_id")
    @classmethod
    def normalize_strategy_id(cls, value: str) -> str:
        strategy_id = value.strip()
        if not strategy_id:
            raise ValueError("strategy_id cannot be empty")
        return strategy_id

    @model_validator(mode="after")
    def validate_window_ids(self) -> EvaluationConfig:
        ids = tuple(window.id for window in self.windows)
        if len(ids) != len(set(ids)):
            raise ValueError("window ids cannot contain duplicates")
        return self

    def to_execution_spec(self, window: EvaluationWindow) -> StrategyExecutionSpec:
        return StrategyExecutionSpec(
            strategy_path=self.strategy_path,
            strategy_id=self.strategy_id,
            data=self.data.model_copy(update={"start": window.start, "end": window.end}),
            params=self.params,
            fill_model=self.fill_model,
            cost_model=self.cost_model,
            require_param_validator=True,
        )


def resolve_evaluation_config_path(path: str | Path, *, repo_root: Path | None = None) -> Path:
    anchor = _path_anchor(path, repo_root=repo_root)
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = anchor / candidate
    candidate = candidate.resolve()
    if candidate.is_dir() or candidate.suffix != ".toml":
        raise EvaluationConfigError("evaluation config path must be a TOML file")
    return candidate


def load_evaluation_config(path: str | Path, *, repo_root: Path | None = None) -> EvaluationConfig:
    config_path = resolve_evaluation_config_path(path, repo_root=repo_root)
    try:
        payload = tomllib.loads(config_path.read_text())
    except OSError as exc:
        raise EvaluationConfigError(f"could not read evaluation config: {config_path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise EvaluationConfigError(f"invalid TOML in evaluation config: {exc}") from exc
    try:
        return EvaluationConfig.model_validate(payload, context={"base_dir": config_path.parent})
    except ValidationError as exc:
        raise EvaluationConfigError(str(exc)) from exc
