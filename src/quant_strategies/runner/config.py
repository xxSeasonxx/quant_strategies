from __future__ import annotations

import tomllib
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, ValidationInfo, field_validator, model_validator

from quant_strategies.runner.errors import ConfigError


DataKind = Literal["bars", "crypto_perp_funding", "forex_with_quotes"]
RunMode = Literal["screen", "validate"]
ArtifactProfile = Literal["full", "summary"]


class RunnerConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


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


def resolve_config_path(path: str | Path, *, repo_root: Path | None = None) -> Path:
    root = Path(repo_root).resolve() if repo_root is not None else default_repo_root()
    config_path = Path(path)
    if config_path.is_absolute():
        return config_path.resolve()
    return (root / config_path).resolve()


class DataConfig(RunnerConfigModel):
    kind: DataKind
    dataset: str | None = None
    symbols: tuple[str, ...] = Field(min_length=1)
    start: date
    end: date
    strict: bool = True

    @field_validator("symbols")
    @classmethod
    def validate_symbols(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        symbols = tuple(symbol.strip() for symbol in value)
        if any(not symbol for symbol in symbols):
            raise ValueError("data.symbols cannot contain empty symbols")
        return symbols

    @model_validator(mode="after")
    def validate_window(self) -> DataConfig:
        if self.end < self.start:
            raise ValueError("data.end must be on or after data.start")
        if self.kind == "bars" and not self.dataset:
            raise ValueError("data.dataset is required when data.kind = 'bars'")
        return self


class FillModelConfig(RunnerConfigModel):
    price: Literal["open", "close", "quote"] = "close"
    entry_lag_bars: int = Field(default=1, ge=0)
    exit_lag_bars: int = Field(default=0, ge=0)
    allow_same_bar_close_fill: bool = False

    @model_validator(mode="after")
    def validate_fill_model(self) -> FillModelConfig:
        if self.price == "close" and self.entry_lag_bars == 0 and not self.allow_same_bar_close_fill:
            raise ValueError(
                'fill_model.price = "close" with entry_lag_bars = 0 requires '
                "fill_model.allow_same_bar_close_fill = true"
            )
        return self


class CostModelConfig(RunnerConfigModel):
    fee_bps_per_side: float = Field(default=0.0, ge=0)
    slippage_bps_per_side: float = Field(default=0.0, ge=0)


class OutputConfig(RunnerConfigModel):
    results_dir: Path
    mode: RunMode
    artifact_profile: ArtifactProfile = "summary"

    @field_validator("results_dir")
    @classmethod
    def validate_results_dir(cls, value: Path, info: ValidationInfo) -> Path:
        return _resolve_inside_repo(value, _repo_root(info), "output.results_dir")


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
        return _resolve_inside_repo(value, _repo_root(info), "strategy_path")

    @field_validator("strategy_id")
    @classmethod
    def validate_strategy_id(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("strategy_id cannot be empty")
        return stripped


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
