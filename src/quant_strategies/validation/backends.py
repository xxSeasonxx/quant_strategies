from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from quant_strategies.decisions import StrategyDecision
from quant_strategies.validation.config import ScenarioRunConfig


BackendStatus = Literal["completed", "failed", "unsupported", "unavailable"]
DecisionGenerationStatus = Literal["base_reused", "regenerated", "failed"]
MetricValue = float | int | str | bool | None
CapabilityRecord = dict[str, Any]


def capability_record(
    semantic: str,
    status: str,
    details: str,
    *,
    observed_unsupported: set[str],
) -> CapabilityRecord:
    return {
        "semantic": semantic,
        "status": status,
        "details": details,
        "observed_unsupported": semantic in observed_unsupported,
    }


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
    semantics = (
        BackendMetricSemantics(
            name="net_return",
            unit="decimal_fraction",
            base="backend portfolio price/cost return path",
            aggregation="scenario total over backend-executed decisions",
            backend="validation_backend",
            comparability="backend-specific; compare only within declared tolerance and matching execution assumptions",
            tolerance=1e-9,
            asymmetry=(
                "may differ from runner smoke signed trade-activity sums, "
                "other backend return paths, and linear funding adjustments"
            ),
        ),
        BackendMetricSemantics(
            name="trade_count",
            unit="count",
            base="backend-executed closed trades",
            aggregation="scenario total",
            backend="validation_backend",
            comparability="exact integer agreement expected for equivalent execution assumptions",
            tolerance=0.0,
            asymmetry="backend trade grouping may differ when execution semantics are not equivalent",
        ),
        BackendMetricSemantics(
            name="funding_return",
            unit="decimal_fraction",
            base="linear funding cashflow approximation",
            aggregation="scenario total over backend-executed decision windows",
            backend="validation_backend",
            comparability="compare only across matching funding event models and execution windows",
            tolerance=1e-9,
            asymmetry="linear cashflow approximation outside the backend NAV path",
        ),
        BackendMetricSemantics(
            name="linear_funding_adjusted_return",
            unit="decimal_fraction",
            base="backend net_return plus linear funding_return",
            aggregation="scenario total over backend-executed decisions",
            backend="validation_backend",
            comparability="diagnostic only unless the funding model is explicitly accepted",
            tolerance=1e-9,
            asymmetry="not a NAV-path funding return; policy gates use backend net_return",
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


@dataclass(frozen=True)
class ScenarioBackendRunResult:
    window_id: str
    scenario_id: str
    required: bool
    result: BackendRunResult
    scenario_kind: str = "unknown"
    decisions_regenerated: bool = False
    diagnostic_only: bool = False
    decision_generation_status: DecisionGenerationStatus = "base_reused"
    decision_count: int = 0
    decision_records_path: str | None = None
    decision_records_sha256: str | None = None


class ValidationBackend(Protocol):
    name: str

    def capability_records(self, observed_unsupported: set[str]) -> Sequence[CapabilityRecord]:
        raise NotImplementedError

    def run(
        self,
        *,
        decisions: list[StrategyDecision],
        rows: Sequence[Mapping[str, Any]],
        config: ScenarioRunConfig,
    ) -> BackendRunResult:
        raise NotImplementedError


class FakeBackend:
    name = "fake"

    def __init__(self, result: BackendRunResult | None = None) -> None:
        self._result = result or BackendRunResult(
            backend=self.name,
            status="completed",
            metrics={"net_return": 0.0, "trade_count": 0},
            warnings=(),
            unsupported_semantics=(),
        )

    def capability_records(self, observed_unsupported: set[str]) -> Sequence[CapabilityRecord]:
        return (
            capability_record(
                "test_double",
                "supported",
                "Deterministic validation test double.",
                observed_unsupported=observed_unsupported,
            ),
        )

    def run(
        self,
        *,
        decisions: list[StrategyDecision],
        rows: Sequence[Mapping[str, Any]],
        config: ScenarioRunConfig,
    ) -> BackendRunResult:
        return self._result


def get_backend(name: str) -> ValidationBackend:
    if name == "fake":
        return FakeBackend()
    if name == "vectorbtpro":
        from quant_strategies.validation.vectorbtpro_backend import VectorBTProBackend

        return VectorBTProBackend()
    raise ValueError(f"unsupported validation backend: {name}")
