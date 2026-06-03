from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from quant_strategies.decisions import StrategyDecision
from quant_strategies.engine.models import Trade
from quant_strategies.validation.config import ScenarioRunConfig

if TYPE_CHECKING:
    from quant_strategies.validation.agreement import AgreementOracleStatus, AgreementResult


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
    # The execution kernel is the verdict source, so these semantics describe
    # the engine's emitted metrics -- the number a human audits IS the gated number.
    semantics = (
        BackendMetricSemantics(
            name="net_return",
            unit="decimal_fraction",
            base="engine linear signed trade-activity sum, funding-inclusive",
            aggregation="scenario total over engine-screened per-trade net returns",
            backend="engine",
            comparability=(
                "the audited trade-result net; cross-checked against VectorBT Pro on the "
                "price path by the opt-in agreement oracle"
            ),
            tolerance=None,
            asymmetry=(
                "a linear per-trade sum, not a NAV path; differs from a compounded "
                "portfolio return for multi-trade scenarios"
            ),
        ),
        BackendMetricSemantics(
            name="trade_count",
            unit="count",
            base="engine-screened closed trades",
            aggregation="scenario total",
            backend="engine",
            comparability="exact integer agreement expected for equivalent execution assumptions",
            tolerance=0.0,
            asymmetry="trade grouping may differ when execution semantics are not equivalent",
        ),
        BackendMetricSemantics(
            name="gross_return",
            unit="decimal_fraction",
            base="engine price path, funding- and cost-exclusive",
            aggregation="scenario total over engine-screened trades",
            backend="engine",
            comparability=(
                "the price path the agreement oracle cross-checks against VectorBT Pro "
                "(single-trade scenarios only)"
            ),
            tolerance=None,
            asymmetry="excludes funding and cost; not the gated number (net_return is)",
        ),
        BackendMetricSemantics(
            name="funding_return",
            unit="decimal_fraction",
            base="engine funding cashflow component included in net_return",
            aggregation="scenario total over engine-screened decision windows",
            backend="engine",
            comparability="single shared funding-window function; no second implementation to reconcile",
            tolerance=1e-9,
            asymmetry="linear funding accrual folded into net_return",
        ),
        BackendMetricSemantics(
            name="cost_return",
            unit="decimal_fraction",
            base="engine round-trip cost deduction folded into net_return",
            aggregation="scenario total over engine-screened trades",
            backend="engine",
            comparability="flat 2*(fee+slippage) bps per trade; deterministic from the cost model",
            tolerance=0.0,
            asymmetry="linear cost deduction; excluded from the agreement cross-check",
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
    # Per-trade ledger backing the scalar metrics. Excluded from model_dump so the
    # backend_runs summary stays scalar; it is written to its own JSONL artifact
    # (the verdict net_return is recomputable as sum(trade.net_return)). Only the
    # engine verdict backend populates it; the agreement-oracle vbt leaves it empty.
    trades: tuple[Trade, ...] = Field(default=(), exclude=True)


@dataclass(frozen=True)
class ScenarioBackendRunResult:
    window_id: str
    scenario_id: str
    required: bool
    result: BackendRunResult
    scenario_kind: str = "unknown"
    diagnostic_only: bool = False
    decision_count: int = 0
    decision_records_path: str | None = None
    decision_records_sha256: str | None = None
    # Per-trade ledger for the engine verdict backend; net_return is recomputable
    # as sum(trade.net_return). None when the backend emitted no trades.
    trade_ledger_path: str | None = None
    trade_ledger_sha256: str | None = None
    # Raw agreement is set only when the opt-in oracle actually ran. The explicit
    # status is always present so uncorroborated evidence cannot be mistaken for
    # agreement evidence.
    agreement: "AgreementResult | None" = None
    agreement_oracle_status: "AgreementOracleStatus" = "disabled"
    agreement_oracle_note: str = ""


class ValidationBackend(Protocol):
    name: str

    def run(
        self,
        *,
        decisions: list[StrategyDecision],
        rows: Sequence[Mapping[str, Any]],
        config: ScenarioRunConfig,
    ) -> BackendRunResult:
        raise NotImplementedError


def get_backend(name: str) -> ValidationBackend:
    if name == "engine":
        from quant_strategies.validation.engine_backend import EngineBackend

        return EngineBackend()
    raise ValueError(f"unsupported validation backend: {name}")
