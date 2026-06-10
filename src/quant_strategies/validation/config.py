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

from quant_strategies.core.config import (
    CausalityReplayConfig,
    CostModelConfig,
    DataConfig,
    FillModelConfig,
    StrategyExecutionSpec,
    WindowedDataConfig,
)
from quant_strategies.validation.artifact_names import validation_artifact_path_collisions
from quant_strategies.validation.errors import ValidationConfigError

# The netted single-account portfolio book (the spine) is the single verdict PnL
# source on every surface (design D9). The VectorBT Pro backend and the
# single-trade agreement oracle are retired; ``engine`` selects the spine book.
VerdictSource = Literal["engine"]
PriorSearch = Literal["none", "known", "unknown"]


class ValidationConfigModel(BaseModel):
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
        return _resolve_inside_config_dir(value, _config_base(info), "output.results_dir")


class ValidationReadinessConfig(ValidationConfigModel):
    min_observations_per_decision: int = Field(ge=1)
    min_distinct_observation_symbols_per_decision: int = Field(default=1, ge=1)
    required_observation_fields: tuple[str, ...] = Field(min_length=1)

    @field_validator("required_observation_fields")
    @classmethod
    def normalize_required_fields(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        fields = tuple(field.strip() for field in value)
        if any(not field for field in fields):
            raise ValueError("readiness.required_observation_fields cannot contain empty fields")
        if len(fields) != len(set(fields)):
            raise ValueError("readiness.required_observation_fields cannot contain duplicates")
        return fields


class MechanicalThresholdsConfig(ValidationConfigModel):
    enabled: bool = True
    min_windows: int = Field(default=2, ge=1)
    min_total_trades: int = Field(default=30, ge=1)
    min_positive_window_fraction: float = Field(default=0.5, ge=0.0, le=1.0)
    max_stressed_activity_loss: float = Field(default=-0.02, le=0.0)
    max_fill_lag_activity_loss: float = Field(default=-0.02, le=0.0)


class SearchPressureConfig(ValidationConfigModel):
    prior_search: PriorSearch
    candidate_count: int | None = Field(default=None, ge=1)
    trial_count: int | None = Field(default=None, ge=1)
    parameter_search_space: dict[str, Any] = Field(default_factory=dict)
    selection_rule: str | None = None
    split_ids: tuple[str, ...] = ()

    @field_validator("selection_rule")
    @classmethod
    def normalize_selection_rule(cls, value: str | None) -> str | None:
        if value is None:
            return None
        rule = value.strip()
        if not rule:
            raise ValueError("search_pressure.selection_rule cannot be empty")
        return rule

    @field_validator("split_ids")
    @classmethod
    def normalize_split_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        split_ids = tuple(item.strip() for item in value)
        if any(not item for item in split_ids):
            raise ValueError("search_pressure.split_ids cannot contain empty ids")
        if len(split_ids) != len(set(split_ids)):
            raise ValueError("search_pressure.split_ids cannot contain duplicates")
        return split_ids

    @model_validator(mode="after")
    def validate_disclosure(self) -> SearchPressureConfig:
        populated_fields = tuple(
            field
            for field, populated in (
                ("candidate_count", self.candidate_count is not None),
                ("trial_count", self.trial_count is not None),
                ("parameter_search_space", bool(self.parameter_search_space)),
                ("selection_rule", self.selection_rule is not None),
                ("split_ids", bool(self.split_ids)),
            )
            if populated
        )
        if self.prior_search == "none" and populated_fields:
            raise ValueError(
                "search_pressure.prior_search='none' cannot include search metadata: "
                + ", ".join(populated_fields)
            )
        if self.prior_search == "unknown" and populated_fields:
            raise ValueError(
                "search_pressure.prior_search='unknown' cannot include search metadata: "
                + ", ".join(populated_fields)
            )
        if self.prior_search == "known":
            missing = tuple(
                field
                for field, value in (
                    ("candidate_count", self.candidate_count),
                    ("trial_count", self.trial_count),
                    ("selection_rule", self.selection_rule),
                )
                if value is None
            )
            if missing:
                raise ValueError(
                    "search_pressure.prior_search='known' requires: " + ", ".join(missing)
                )
        return self


class ScenarioRunConfig(ValidationConfigModel):
    scenario_id: str = Field(min_length=1)
    fill_model: FillModelConfig
    cost_model: CostModelConfig
    data: DataConfig


class ValidationConfig(ValidationConfigModel):
    _base_dir_path: Path = PrivateAttr(default_factory=lambda: Path.cwd().resolve())

    strategy_path: Path
    strategy_id: str = Field(min_length=1)
    verdict_source: VerdictSource = "engine"
    windows: tuple[ValidationWindow, ...] = Field(min_length=1)
    data: WindowedDataConfig
    params: dict[str, Any] = Field(default_factory=dict)
    fill_model: FillModelConfig
    cost_model: CostModelConfig
    causality_replay: CausalityReplayConfig = Field(default_factory=CausalityReplayConfig)
    output: ValidationOutputConfig
    readiness: ValidationReadinessConfig
    mechanical_thresholds: MechanicalThresholdsConfig = Field(
        default_factory=MechanicalThresholdsConfig
    )
    search_pressure: SearchPressureConfig

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
    def validate_window_identity(self) -> ValidationConfig:
        window_ids = [window.id for window in self.windows]
        duplicate_ids = sorted(
            {window_id for window_id in window_ids if window_ids.count(window_id) > 1}
        )
        if duplicate_ids:
            raise ValueError(f"windows.id values must be unique: {duplicate_ids}")

        collisions = validation_artifact_path_collisions(window_ids)
        if collisions:
            raise ValueError(
                "windows.id values must not collide after validation artifact path sanitization: "
                + "; ".join(collisions)
            )
        return self

    def to_execution_spec(self, window: ValidationWindow) -> StrategyExecutionSpec:
        # Validation adapts directly into the neutral execution kernel input — it
        # never builds a runner RunConfig (no output policy, no runner.config import).
        return StrategyExecutionSpec(
            strategy_path=self.strategy_path,
            strategy_id=self.strategy_id,
            data=DataConfig(
                **self.data.model_dump(),
                start=window.start,
                end=window.end,
            ),
            params=self.params,
            fill_model=self.fill_model,
            cost_model=self.cost_model,
            require_param_validator=True,
        )


def resolve_validation_config_path(path: str | Path, *, repo_root: Path | None = None) -> Path:
    anchor = _path_anchor(path, repo_root=repo_root)
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = anchor / candidate
    candidate = candidate.resolve()
    if candidate.is_dir():
        raise ValidationConfigError("validation config path must be a TOML file, not a directory")
    if candidate.suffix != ".toml":
        raise ValidationConfigError("validation config path must be a TOML file")
    return candidate


def load_validation_config(path: str | Path, *, repo_root: Path | None = None) -> ValidationConfig:
    config_path = resolve_validation_config_path(path, repo_root=repo_root)
    try:
        payload = tomllib.loads(config_path.read_text())
    except OSError as exc:
        raise ValidationConfigError(f"could not read validation config: {config_path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ValidationConfigError(f"invalid TOML in validation config: {exc}") from exc

    if isinstance(payload, dict) and "backend" in payload:
        raise ValidationConfigError(
            "validation config field 'backend' has been removed: the netted "
            "single-account portfolio book is now the sole verdict PnL source on every "
            "surface, so the verdict number is the audited number. Remove the 'backend' key."
        )
    if isinstance(payload, dict) and "agreement_oracle" in payload:
        raise ValidationConfigError(
            "validation config section '[agreement_oracle]' has been removed: the "
            "VectorBT Pro cross-check and the single-trade agreement oracle are retired "
            "(the spine book is the single model of money). Remove the section."
        )
    if isinstance(payload, dict) and "search_pressure" not in payload:
        raise ValidationConfigError(
            "validation config requires [search_pressure] with "
            'prior_search = "none", "known", or "unknown"'
        )
    search_pressure_payload = payload.get("search_pressure") if isinstance(payload, dict) else None
    if isinstance(search_pressure_payload, dict) and "prior_search" not in search_pressure_payload:
        raise ValidationConfigError(
            'search_pressure.prior_search is required; set it to "none", "known", or "unknown"'
        )

    try:
        return ValidationConfig.model_validate(
            payload,
            context={"base_dir": config_path.parent},
        )
    except ValidationError as exc:
        raise ValidationConfigError(str(exc)) from exc
