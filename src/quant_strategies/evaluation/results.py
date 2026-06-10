from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from quant_strategies.core.config import LeverageBudgetConfig
from quant_strategies.decisions import TargetDecision
from quant_strategies.evaluation.fold_returns import FoldReturnSeries, FoldScenarioMetrics
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
    """Per-window inputs shared across the window's cost/fill scenarios.

    The single causal netted book consumes the standing ``TargetDecision`` stream and
    the execution ``rows`` directly; the only per-scenario inputs are the cost/fill
    config, so preparation just holds the window-constant decisions, rows, and data
    kind once for reuse across the scenario fan-out.
    """

    decisions: tuple[TargetDecision, ...]
    rows: tuple[Mapping[str, Any], ...]
    data_kind: str = "bars"
    leverage_budget: LeverageBudgetConfig = field(default_factory=LeverageBudgetConfig)


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
    fold_returns: tuple[FoldReturnSeries, ...] = ()
    scenario_metrics: tuple[FoldScenarioMetrics, ...] = ()
    causal_replay_passed: bool | None = None
    provenance: Mapping[str, str] = field(default_factory=dict)

    @property
    def succeeded(self) -> bool:
        return self.run_completed and self.failure_stage is None

    @property
    def window_ids(self) -> tuple[str, ...]:
        """Distinct window ids with at least one completed scenario series."""
        return tuple(dict.fromkeys(series.window_id for series in self.fold_returns))

    def scenario_ids_for(self, window_id: str) -> tuple[str, ...]:
        """Completed scenario ids for a window, in completion order."""
        return tuple(
            series.scenario_id for series in self.fold_returns if series.window_id == window_id
        )

    def returns_for(self, window_id: str, scenario_id: str) -> FoldReturnSeries | None:
        """Typed OOS return series for one `(window, scenario)`; `None` if absent."""
        for series in self.fold_returns:
            if series.window_id == window_id and series.scenario_id == scenario_id:
                return series
        return None

    def metrics_for(self, window_id: str, scenario_id: str) -> FoldScenarioMetrics | None:
        """Typed summary scalars for one `(window, scenario)`; `None` if absent."""
        for metrics in self.scenario_metrics:
            if metrics.window_id == window_id and metrics.scenario_id == scenario_id:
                return metrics
        return None
