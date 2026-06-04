from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from quant_strategies.decisions import StrategyDecision
from quant_strategies.evaluation.metrics import MetricValue


EvaluationBackendStatus = Literal["completed", "failed", "unsupported", "unavailable"]


@dataclass(frozen=True)
class PortfolioTraceTables:
    portfolio_path: Any
    trades: Any
    target_positions: Any
    target_exposure_summary: Any
    funding_cashflows: Any = None


@dataclass(frozen=True)
class PortfolioMetricPayload:
    metrics: dict[str, MetricValue]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class PreparedPortfolioInputs:
    close: Any
    decisions: tuple[StrategyDecision, ...]
    symbol_indexes: Mapping[str, Any]
    decision_positions: tuple[int, ...]
    source_rows: tuple[Mapping[str, Any], ...] = ()
    data_kind: str = "bars"


class PortfolioEvaluationResult(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    scenario_id: str
    backend: str
    status: EvaluationBackendStatus
    metrics: dict[str, MetricValue] = Field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    unsupported_semantics: tuple[str, ...] = ()
    tables: PortfolioTraceTables | None = None


@dataclass(frozen=True)
class EvaluationRunResult:
    result_dir: Path | None
    message: str
    run_completed: bool = False
    failure_stage: str | None = None
    assessment_status: str = "evaluation_failed"
    evidence_quality_warnings: tuple[str, ...] = ()
