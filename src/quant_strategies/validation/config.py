from __future__ import annotations

import tomllib
from datetime import date
from pathlib import Path
from typing import Any, Literal

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

from quant_strategies.runner.config import (
    CostModelConfig,
    DataConfig,
    FillModelConfig,
    OutputConfig as RunnerOutputConfig,
    RunConfig,
    _resolve_inside_repo,
    default_repo_root,
)
from quant_strategies.validation.errors import ValidationConfigError


BackendName = Literal["fake", "vectorbtpro"]


class ValidationConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _repo_root(info: ValidationInfo) -> Path:
    root = info.context.get("repo_root") if info.context else None
    return Path(root).resolve() if root is not None else default_repo_root()


class ValidationWindow(ValidationConfigModel):
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
    def validate_window(self) -> ValidationWindow:
        if self.end < self.start:
            raise ValueError("window end must be on or after start")
        return self


class ValidationOutputConfig(ValidationConfigModel):
    results_dir: Path

    @field_validator("results_dir")
    @classmethod
    def validate_results_dir(cls, value: Path, info: ValidationInfo) -> Path:
        return _resolve_inside_repo(value, _repo_root(info), "output.results_dir")


class ValidationConfig(ValidationConfigModel):
    _repo_root_path: Path = PrivateAttr(default_factory=default_repo_root)

    strategy_path: Path
    strategy_id: str = Field(min_length=1)
    backend: BackendName = "vectorbtpro"
    windows: tuple[ValidationWindow, ...] = Field(min_length=1)
    data: DataConfig
    params: dict[str, Any] = Field(default_factory=dict)
    fill_model: FillModelConfig
    cost_model: CostModelConfig
    output: ValidationOutputConfig

    def model_post_init(self, context: Any, /) -> None:
        root = context.get("repo_root") if isinstance(context, dict) else None
        repo_root = Path(root).resolve() if root is not None else default_repo_root()
        object.__setattr__(self, "_repo_root_path", repo_root)

    @field_validator("strategy_path")
    @classmethod
    def validate_strategy_path(cls, value: Path, info: ValidationInfo) -> Path:
        return _resolve_inside_repo(value, _repo_root(info), "strategy_path")

    @field_validator("strategy_id")
    @classmethod
    def normalize_strategy_id(cls, value: str) -> str:
        strategy_id = value.strip()
        if not strategy_id:
            raise ValueError("strategy_id cannot be empty")
        return strategy_id

    def to_run_config(self, window: ValidationWindow, *, results_dir: Path) -> RunConfig:
        context = {"repo_root": self._repo_root_path}
        output = RunnerOutputConfig.model_validate(
            {"results_dir": results_dir, "mode": "validate"},
            context=context,
        )
        return RunConfig.model_validate(
            {
                "strategy_path": self.strategy_path,
                "strategy_id": self.strategy_id,
                "data": self.data.model_copy(update={"start": window.start, "end": window.end}),
                "params": self.params,
                "fill_model": self.fill_model,
                "cost_model": self.cost_model,
                "output": output,
            },
            context=context,
        )


def resolve_validation_config_path(path: str | Path, *, repo_root: Path | None = None) -> Path:
    root = Path(repo_root).resolve() if repo_root is not None else default_repo_root()
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve()
    if candidate.is_dir():
        candidate = candidate / "validation.toml"
    return candidate


def load_validation_config(path: str | Path, *, repo_root: Path | None = None) -> ValidationConfig:
    root = Path(repo_root).resolve() if repo_root is not None else default_repo_root()
    config_path = resolve_validation_config_path(path, repo_root=root)
    try:
        payload = tomllib.loads(config_path.read_text())
    except OSError as exc:
        raise ValidationConfigError(f"could not read validation config: {config_path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ValidationConfigError(f"invalid TOML in validation config: {exc}") from exc

    try:
        return ValidationConfig.model_validate(payload, context={"repo_root": root})
    except ValidationError as exc:
        raise ValidationConfigError(str(exc)) from exc
