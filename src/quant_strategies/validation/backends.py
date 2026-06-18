from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from quant_strategies.core.portfolio_foundation import (
    FeasibilityVerdict,
    PortfolioSizingReport,
    RoundTrip,
)
from quant_strategies.decisions import TargetDecision
from quant_strategies.validation.config import ScenarioRunConfig

BackendStatus = Literal["completed", "failed", "unsupported", "unavailable"]
MetricValue = float | int | str | bool | None


class BackendMetricSemantics(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    base: str = Field(min_length=1)
    aggregation: str = Field(min_length=1)
    backend: str = Field(min_length=1)
    comparability: str = Field(min_length=1)
    tolerance: float | None = None
    asymmetry: str | None = None


class BackendMetrics(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    net_return: float
    trade_count: int
    extras: dict[str, MetricValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_required_metrics(self) -> BackendMetrics:
        if not math.isfinite(self.net_return):
            raise ValueError("net_return must be finite")
        if self.trade_count < 0:
            raise ValueError("trade_count must be non-negative")
        return self

    @classmethod
    def from_mapping(cls, metrics: Mapping[str, MetricValue]) -> BackendMetrics | None:
        net_return = _metric_number(metrics, "net_return")
        trade_count = _metric_number(metrics, "trade_count")
        if net_return is None or trade_count is None:
            return None
        if trade_count < 0 or not trade_count.is_integer():
            return None
        try:
            return cls(
                net_return=net_return,
                trade_count=int(trade_count),
                extras={
                    str(key): value
                    for key, value in metrics.items()
                    if key not in {"net_return", "trade_count"}
                },
            )
        except ValueError:
            return None


def backend_metric_semantics() -> dict[str, dict[str, object]]:
    # The netted-book spine is the single verdict source, so these semantics describe
    # the book's marked NAV path -- the number a human audits IS the gated number,
    # recomputable from the artifacted NAV path as ``(final_nav - initial)/initial``.
    semantics = (
        BackendMetricSemantics(
            name="net_return",
            unit="decimal_fraction",
            base="netted single-account portfolio book marked NAV path, funding-inclusive",
            aggregation="marked fold return (final_nav - initial_equity) / initial_equity",
            backend="engine",
            comparability=(
                "the audited netted-book NAV path; recomputable from the artifacted "
                "portfolio path and equal to the realized round-trip sum when flat"
            ),
            tolerance=None,
            asymmetry="funding-inclusive net of costs; the single model of money",
        ),
        BackendMetricSemantics(
            name="trade_count",
            unit="count",
            base="netted-book round trips (flat -> non-flat -> flat)",
            aggregation="scenario total",
            backend="engine",
            comparability="exact integer agreement expected for equivalent execution assumptions",
            tolerance=0.0,
            asymmetry="netted round trips, not isolated per-decision tickets",
        ),
        BackendMetricSemantics(
            name="gross_return",
            unit="decimal_fraction",
            base="netted-book price proceeds, funding- and cost-exclusive",
            aggregation="sum of round-trip price proceeds as a fraction of NAV base",
            backend="engine",
            comparability="the price-path component of the gated net_return",
            tolerance=None,
            asymmetry="excludes funding and cost; not the gated number (net_return is)",
        ),
        BackendMetricSemantics(
            name="funding_return",
            unit="decimal_fraction",
            base="netted-book funding cashflow accrued on the held net position",
            aggregation="sum of round-trip funding as a fraction of NAV base",
            backend="engine",
            comparability="single shared funding-window function; no second implementation",
            tolerance=1e-9,
            asymmetry="funding accrual folded into net_return",
        ),
        BackendMetricSemantics(
            name="cost_return",
            unit="decimal_fraction",
            base=(
                "netted-book total traded cost on the |delta notional| of each fill, "
                "including base costs and market impact"
            ),
            aggregation="sum of round-trip cost as a fraction of NAV base",
            backend="engine",
            comparability=(
                "total transaction-cost component of the gated net_return; includes the "
                "impact_return component when ADV impact is enabled"
            ),
            tolerance=0.0,
            asymmetry="cost deduction folded into net_return as net = gross + funding - cost",
        ),
        BackendMetricSemantics(
            name="impact_return",
            unit="decimal_fraction",
            base="netted-book market-impact cash charged on capacity-priced execution events",
            aggregation="sum of round-trip impact cost as a fraction of NAV base",
            backend="engine",
            comparability=(
                "component of cost_return derived from the same execution events that update NAV"
            ),
            tolerance=0.0,
            asymmetry="impact is included in cost_return, not subtracted separately from net_return",
        ),
    )
    return {item.name: item.model_dump(mode="json") for item in semantics}


def _metric_number(metrics: Mapping[str, MetricValue], name: str) -> float | None:
    if name not in metrics:
        return None
    value = metrics[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


class BackendRunResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    backend: str
    status: BackendStatus
    metrics: dict[str, MetricValue]
    warnings: tuple[str, ...] = ()
    unsupported_semantics: tuple[str, ...] = ()
    feasibility: FeasibilityVerdict = Field(
        default_factory=lambda: FeasibilityVerdict(feasible=True)
    )
    sizing_report: PortfolioSizingReport | None = None
    # Netted-book round-trip ledger backing the scalar metrics. Excluded from
    # model_dump so the backend_runs summary stays scalar; it is written to its own
    # JSONL artifact (the gated net_return is recomputable as sum(round_trip.net)).
    round_trips: tuple[RoundTrip, ...] = Field(default=(), exclude=True)


@dataclass(frozen=True)
class ScenarioBackendRunResult:
    window_id: str
    scenario_id: str
    required: bool
    result: BackendRunResult
    scenario_kind: str = "unknown"
    scoreability_bearing: bool = True
    diagnostic_only: bool = False
    decision_count: int = 0
    decision_records_path: str | None = None
    decision_records_sha256: str | None = None
    # Per-scenario netted-book round-trip ledger; net_return is recomputable as
    # sum(round_trip.net). None when the walk produced no closed round trips.
    trade_ledger_path: str | None = None
    trade_ledger_sha256: str | None = None


class ValidationBackend(Protocol):
    name: str

    def run(
        self,
        *,
        decisions: list[TargetDecision],
        rows: Sequence[Mapping[str, Any]],
        config: ScenarioRunConfig,
    ) -> BackendRunResult:
        raise NotImplementedError
