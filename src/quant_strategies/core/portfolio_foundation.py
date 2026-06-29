from __future__ import annotations

import math
from bisect import bisect_left
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from typing import Any, cast

from quant_strategies.core.accounting_model import SHARED_ACCOUNTING_MODEL
from quant_strategies.core.config import (
    CapacityModelConfig,
    CostModelConfig,
    DataConfig,
    DataKind,
    FillModelConfig,
    RiskBudgetConfig,
)
from quant_strategies.core.serialization import json_safe_value
from quant_strategies.datetime_utils import parse_aware_datetime
from quant_strategies.decisions import RiskRule, TargetDecision
from quant_strategies.funding import funding_rates_match

FOUNDATION_SCHEMA_VERSION = "quant_strategies.quick_run.portfolio_foundation/v2"
SIZING_REPORT_SCHEMA_VERSION = "quant_strategies.portfolio_sizing/v1"
FOUNDATION_BASIS = SHARED_ACCOUNTING_MODEL
FOUNDATION_EVIDENCE_CLASS = "quick_run_portfolio_foundation_diagnostic"
INITIAL_EQUITY = 100.0
MAX_FOUNDATION_SUBWINDOWS = 64
DEFAULT_MIN_RETURN_SAMPLE = 20
# Default adverse slippage (fraction of the barrier price) applied to RiskRule exit fills
# in the diagnostic ``fill_stress`` scenario. 10 bps; the realistic scored path uses 0.0.
DEFAULT_FILL_STRESS_FRACTION = 0.0010

# Asset classes whose financing is modeled inside the book. Holding net leverage
# above 1.0 is only honestly scoreable when the financing of that leverage is
# priced; today only crypto-perp funding is modeled, so every other kind triggers
# the ``unfinanced_leverage`` feasibility verdict above net 1.0.
_FINANCED_DATA_KINDS: frozenset[DataKind] = frozenset({"crypto_perp_funding"})

FeasibilityReason = str  # one of the constants below

REASON_LEVERAGE_BUDGET_BREACH = "leverage_budget_breach"
REASON_ZERO_COST = "zero_cost"
REASON_ZERO_SLIPPAGE = "zero_slippage"
REASON_INSUFFICIENT_SAMPLES = "insufficient_samples"
REASON_UNFINANCED_LEVERAGE = "unfinanced_leverage"
REASON_UNPRICED_SHORT_FINANCING = "unpriced_short_financing"
REASON_CAPACITY_UNPRICED = "capacity_unpriced"
REASON_CAPACITY_UNSUPPORTED_VOLUME_SEMANTICS = "capacity_unsupported_volume_semantics"
REASON_CAPACITY_MISSING_VOLUME = "capacity_missing_volume"
REASON_CAPACITY_INSUFFICIENT_ADV_HISTORY = "capacity_insufficient_adv_history"
REASON_CAPACITY_LIMIT_BREACH = "capacity_limit_breach"

_EXPOSURE_TOLERANCE = 1e-9
# Maximum book-scale calibration steps. The analytic seed + safeguarded secant converge
# in 1-3 steps; this is only a fail-safe iteration cap, not a precision knob.
_CALIBRATION_ITERATIONS = 24
_VOLATILITY_TOLERANCE_FRACTION = 1e-4
# Relative bracket width below which a scale search has converged.
_SIZING_SCALE_TOLERANCE = 1e-12
# Capacity utilization (participation / limit) this close to 1.0 from below is at the
# frontier; the search stops rather than tightening an already-converged bracket.
_FRONTIER_UTILIZATION_TOLERANCE = 1e-6


@dataclass(frozen=True)
class PortfolioFoundationConfig:
    risk_budget: RiskBudgetConfig
    subwindows: int = 6
    cost_stress_multiplier: float = 2.0
    fill_stress_fraction: float = DEFAULT_FILL_STRESS_FRACTION
    max_gross_exposure: float = 1.0
    max_net_exposure: float = 1.0
    min_return_sample: int = DEFAULT_MIN_RETURN_SAMPLE

    def __post_init__(self) -> None:
        if self.subwindows < 1:
            raise ValueError("foundation_subwindows must be >= 1")
        if self.subwindows > MAX_FOUNDATION_SUBWINDOWS:
            raise ValueError(f"foundation_subwindows must be <= {MAX_FOUNDATION_SUBWINDOWS}")
        if not math.isfinite(self.cost_stress_multiplier) or self.cost_stress_multiplier < 1.0:
            raise ValueError("foundation_cost_stress_multiplier must be >= 1")
        if not math.isfinite(self.fill_stress_fraction) or not (
            0.0 <= self.fill_stress_fraction < 1.0
        ):
            raise ValueError("foundation_fill_stress_fraction must be in [0, 1)")
        if not math.isfinite(self.max_gross_exposure) or self.max_gross_exposure < 1.0:
            raise ValueError("foundation_max_gross_exposure must be >= 1")
        if not math.isfinite(self.max_net_exposure) or self.max_net_exposure < 1.0:
            raise ValueError("foundation_max_net_exposure must be >= 1")
        if self.min_return_sample < 2:
            raise ValueError("foundation_min_return_sample must be >= 2")


@dataclass(frozen=True)
class FeasibilityVerdict:
    """Typed, fail-closed feasibility outcome for one book walk.

    ``feasible`` gates whether the book is scoreable. A breach names the breached
    dimension (``reason``) and the observed value; the book is never clamped,
    normalized, or collapsed into an untyped ``None`` (design D5).
    """

    feasible: bool
    reason: FeasibilityReason | None = None
    observed_gross: float | None = None
    observed_net: float | None = None
    # Capacity breach observables: the breaching participation ratio and the limit it
    # exceeded. Set only on a capacity-limit breach (mirrors observed_gross/observed_net
    # for leverage). They make the breach self-describing so the sizing search can seed
    # the capacity frontier analytically instead of probing for it.
    observed_participation: float | None = None
    participation_limit: float | None = None
    detail: str | None = None

    def payload(self) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            json_safe_value(
                {
                    "feasible": self.feasible,
                    "reason": self.reason,
                    "observed_gross": self.observed_gross,
                    "observed_net": self.observed_net,
                    "observed_participation": self.observed_participation,
                    "participation_limit": self.participation_limit,
                    "detail": self.detail,
                }
            ),
        )


class FeasibilityError(ValueError):
    """Raised by the book walk when the run is infeasible (fail-closed)."""

    def __init__(self, verdict: FeasibilityVerdict) -> None:
        self.verdict = verdict
        super().__init__(verdict.reason or "infeasible")


@dataclass(frozen=True)
class NormalizedShapeMetadata:
    method: str
    raw_gross_normalization_scalar: float
    raw_max_gross: float
    raw_max_net: float
    normalized_max_gross: float
    normalized_max_net: float
    decision_count: int

    def payload(self) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            json_safe_value(
                {
                    "method": self.method,
                    "raw_gross_normalization_scalar": self.raw_gross_normalization_scalar,
                    "raw_max_gross": self.raw_max_gross,
                    "raw_max_net": self.raw_max_net,
                    "normalized_max_gross": self.normalized_max_gross,
                    "normalized_max_net": self.normalized_max_net,
                    "decision_count": self.decision_count,
                }
            ),
        )


@dataclass(frozen=True)
class PortfolioSizingReport:
    schema_version: str
    mode: str
    shape: NormalizedShapeMetadata
    annualization_periods_per_year: int
    book_scale: float
    target_volatility: float | None
    deployed_volatility: float | None
    max_feasible_volatility: float | None
    capacity_bound: bool
    max_feasible_book_scale: float | None
    binding_dimensions: tuple[str, ...]
    final_max_intended_gross: float
    final_max_intended_net: float

    def payload(self) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            json_safe_value(
                {
                    "schema_version": self.schema_version,
                    "mode": self.mode,
                    "shape": self.shape.payload(),
                    "annualization_periods_per_year": self.annualization_periods_per_year,
                    "book_scale": self.book_scale,
                    "target_volatility": self.target_volatility,
                    "deployed_volatility": self.deployed_volatility,
                    "max_feasible_volatility": self.max_feasible_volatility,
                    "capacity_bound": self.capacity_bound,
                    "max_feasible_book_scale": self.max_feasible_book_scale,
                    "binding_dimensions": list(self.binding_dimensions),
                    "final_max_intended_gross": self.final_max_intended_gross,
                    "final_max_intended_net": self.final_max_intended_net,
                }
            ),
        )


@dataclass(frozen=True)
class ReturnStatistics:
    return_sample_count: int
    mean_return: float | None
    return_volatility: float | None
    effective_sample_size: float | None
    sharpe: float | None
    sharpe_standard_error: float | None
    skew: float | None
    kurtosis: float | None
    warnings: tuple[str, ...] = ()

    def payload(self) -> dict[str, Any]:
        payload = {
            "return_sample_count": self.return_sample_count,
            "mean_return": self.mean_return,
            "return_volatility": self.return_volatility,
            "effective_sample_size": self.effective_sample_size,
            "sharpe": self.sharpe,
            "sharpe_standard_error": self.sharpe_standard_error,
            "skew": self.skew,
            "kurtosis": self.kurtosis,
            "warnings": list(self.warnings),
        }
        return cast(dict[str, Any], json_safe_value(payload))


@dataclass(frozen=True)
class PortfolioPathPoint:
    timestamp: datetime
    portfolio_value: float
    period_return: float
    at_risk: bool
    drawdown: float
    gross_exposure: float
    net_exposure: float
    concentration: float


@dataclass(frozen=True)
class RoundTrip:
    """A net position that opened (flat -> non-flat) and returned to flat.

    ``realized_pnl`` is the cash attribution of the position lifecycle (proceeds
    over cost basis, plus funding accrued while held, minus the traded costs). The
    sum of closed round-trip ``realized_pnl`` reconciles with NAV realized PnL
    (design D4); it is an attribution view of the same walk, never an independent
    scored number. The cash split (``gross_cash`` price proceeds, ``funding_cash``
    accrued funding, ``cost_cash`` traded cost) lets the derived per-trade ledger
    expose ``gross/funding/cost`` returns that sum to ``net`` without an independent
    summation. ``entry_weight`` is the signed weight-of-NAV the leg opened at;
    ``entry_mark``/``exit_mark`` are the leg's entry/exit fill marks. Per-trip
    ``cost_cash`` is approximate on a reversal (the crossing trade books the whole
    reversal-bar cost on the closing trip; see ``_close_leg``); the total and NAV stay
    exact.
    """

    symbol: str
    direction: str
    decision_time: datetime
    entry_time: datetime
    exit_time: datetime
    realized_pnl: float
    gross_cash: float
    funding_cash: float
    cost_cash: float
    entry_weight: float
    entry_mark: float
    exit_mark: float
    exit_reason: str
    decision_id: str | None
    impact_cost_cash: float = 0.0


@dataclass(frozen=True)
class FundingEvent:
    """One funding cashflow applied to the live net position at a funding-apply bar.

    The same per-event detail the book charged against cash, exposed so a heavy
    surface (evaluation) can serialize the funding trace without re-deriving funding
    (the single funding home stays the book; design D8). ``cashflow`` is signed cash
    on the account (`-signed_qty * mark * rate`): a long pays positive funding, a
    short receives.
    """

    symbol: str
    timestamp: datetime
    funding_rate: float
    position_units: float
    mark_price: float
    cashflow: float


@dataclass(frozen=True)
class ExecutionEvent:
    """One executed net delta and its capacity/impact accounting."""

    symbol: str
    timestamp: datetime
    reason: str
    side: str
    fill_price: float
    delta_units: float
    normalized_notional: float
    real_notional: float
    base_cost: float
    impact_cost: float
    total_cost: float
    bar_notional_volume: float
    adv_notional_volume: float
    bar_participation: float
    adv_participation: float
    decision_time: datetime | None = None
    decision_id: str | None = None


@dataclass(frozen=True)
class FoundationMetric:
    window_id: str
    start_time: datetime
    end_time: datetime
    total_return: float | None
    max_drawdown: float | None
    closed_trade_count: int
    max_symbol_concentration: float
    max_gross_utilization: float
    mean_gross_utilization: float
    max_net_utilization: float
    mean_net_utilization: float
    statistics: ReturnStatistics

    def payload(self) -> dict[str, Any]:
        payload = {
            "window_id": self.window_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "total_return": self.total_return,
            "max_drawdown": self.max_drawdown,
            "closed_trade_count": self.closed_trade_count,
            "max_symbol_concentration": self.max_symbol_concentration,
            "max_gross_utilization": self.max_gross_utilization,
            "mean_gross_utilization": self.mean_gross_utilization,
            "max_net_utilization": self.max_net_utilization,
            "mean_net_utilization": self.mean_net_utilization,
            **self.statistics.payload(),
        }
        return cast(dict[str, Any], json_safe_value(payload))


@dataclass(frozen=True)
class FoundationScenarioResult:
    scenario_id: str
    cost_multiplier: float
    feasibility: FeasibilityVerdict
    full_train: FoundationMetric
    subwindows: tuple[FoundationMetric, ...]
    capacity: Mapping[str, Any]

    def summary_payload(self) -> dict[str, Any]:
        closed_counts = [item.closed_trade_count for item in self.subwindows]
        concentrations = [item.max_symbol_concentration for item in self.subwindows]
        warning_counts: dict[str, int] = defaultdict(int)
        for item in self.subwindows:
            for warning in item.statistics.warnings:
                warning_counts[warning] += 1
        payload = {
            "scenario_id": self.scenario_id,
            "cost_multiplier": self.cost_multiplier,
            "feasibility": self.feasibility.payload(),
            "full_train": self.full_train.payload(),
            "capacity": dict(self.capacity),
            "subwindow_count": len(self.subwindows),
            "min_closed_trade_count": min(closed_counts) if closed_counts else 0,
            "max_symbol_concentration": max(concentrations) if concentrations else 0.0,
            "warning_counts": dict(sorted(warning_counts.items())),
        }
        return cast(dict[str, Any], json_safe_value(payload))

    def matrix_payload(self) -> dict[str, Any]:
        payload = self.summary_payload()
        payload["subwindows"] = [item.payload() for item in self.subwindows]
        return cast(dict[str, Any], json_safe_value(payload))


@dataclass(frozen=True)
class RunPortfolioFoundation:
    schema_version: str
    basis: str
    evidence_class: str
    sizing_report: PortfolioSizingReport
    scenarios: tuple[FoundationScenarioResult, ...]
    # The realistic-cost scenario's single causal walk. Its NAV ``path`` is the
    # authoritative scored object and its ``round_trips`` are the derived attribution
    # ledger the per-trade economics view is reconstructed from (design D4) — one
    # model of money, never an independent summation.
    ledger: BookWalkResult
    # Repair-aware mark audit: the upstream repair summary plus the synthetic marks the
    # scored walk actually consumed in P&L. ``None`` only when no repair was available in
    # the window and none was consumed; non-``None`` (with ``consumed_repaired_mark_count``
    # possibly 0) when the upstream summary reported repaired rows.
    mark_repair: Mapping[str, Any] | None = None

    @property
    def feasible(self) -> bool:
        return all(scenario.feasibility.feasible for scenario in self.scenarios)

    def feasible_verdict(self) -> FeasibilityVerdict:
        """The governing feasibility verdict: the first infeasible scenario's verdict,
        else a feasible verdict. The mid-walk leverage/unfinanced breaches raise
        :class:`FeasibilityError` before this object exists; the verdicts surfaced here
        are the non-raising ones (zero-cost, insufficient samples) or feasible."""
        for scenario in self.scenarios:
            if not scenario.feasibility.feasible:
                return scenario.feasibility
        return FeasibilityVerdict(feasible=True)

    def summary_payload(self) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            json_safe_value(
                {
                    "schema_version": self.schema_version,
                    "basis": self.basis,
                    "evidence_class": self.evidence_class,
                    "sizing_report": self.sizing_report.payload(),
                    "scenarios": {
                        scenario.scenario_id: scenario.summary_payload()
                        for scenario in self.scenarios
                    },
                    **({"mark_repair": self.mark_repair} if self.mark_repair else {}),
                }
            ),
        )

    def matrix_payload(self) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            json_safe_value(
                {
                    "schema_version": self.schema_version,
                    "basis": self.basis,
                    "evidence_class": self.evidence_class,
                    "sizing_report": self.sizing_report.payload(),
                    "scenarios": {
                        scenario.scenario_id: scenario.matrix_payload()
                        for scenario in self.scenarios
                    },
                }
            ),
        )


@dataclass(frozen=True)
class BookWalkResult:
    """The single causal walk's outputs over one cost scenario.

    The NAV ``path`` is the authoritative scored object; ``round_trips`` is the
    derived attribution ledger that reconciles with realized NAV PnL; ``feasibility``
    is the typed fail-closed verdict.
    """

    path: tuple[PortfolioPathPoint, ...]
    round_trips: tuple[RoundTrip, ...]
    feasibility: FeasibilityVerdict
    final_nav: float
    realized_pnl: float
    execution_events: tuple[ExecutionEvent, ...] = ()
    funding_events: tuple[FundingEvent, ...] = ()
    sizing_report: PortfolioSizingReport | None = None


def build_portfolio_foundation(
    *,
    rows: Sequence[Mapping[str, Any]],
    decisions: Sequence[TargetDecision],
    data: DataConfig,
    fill_model: FillModelConfig,
    cost_model: CostModelConfig,
    capacity_model: CapacityModelConfig,
    config: PortfolioFoundationConfig,
    mark_rows: Sequence[Mapping[str, Any]] = (),
    mark_repair: Mapping[str, Any] | None = None,
) -> RunPortfolioFoundation:
    """Build the authoritative scored portfolio book over the two cost scenarios.

    The book is one causal, single-account, per-symbol-netted walk that consumes the
    standing ``TargetDecision`` stream and the execution ``rows``, applies frictions
    at one localized step, and derives all scored statistics from the NAV path.
    Infeasible scenarios raise :class:`FeasibilityError` carrying the typed verdict;
    the caller (Phase 1b) gates ``RunResult.succeeded`` on it.
    """
    row_index = _RowIndex(rows, mark_rows)
    raw_decision_plan = _DecisionPlan(row_index, decisions, fill_model=fill_model)
    decision_plan, sizing_report = _sized_decision_plan(
        row_index=row_index,
        raw_decision_plan=raw_decision_plan,
        data=data,
        cost_model=cost_model,
        capacity_model=capacity_model,
        config=config,
    )
    # Isolate the audit to the scored walk: sizing/calibration walks above share this
    # index and may have read repaired marks; clear so the set captures only the
    # authoritative realistic-costs scenario (the ledger), not unscored sizing/stress walks.
    row_index.consumed_repaired_marks.clear()
    realistic, realistic_walk = _build_scenario(
        "realistic_costs",
        row_index=row_index,
        decision_plan=decision_plan,
        data=data,
        cost_model=cost_model,
        capacity_model=capacity_model,
        cost_multiplier=1.0,
        config=config,
    )
    scored_consumed_marks = set(row_index.consumed_repaired_marks)
    sizing_report = _completed_sizing_report(sizing_report, realistic_walk)
    realistic_walk = replace(realistic_walk, sizing_report=sizing_report)
    stress, _ = _build_scenario(
        "cost_stress",
        row_index=row_index,
        decision_plan=decision_plan,
        data=data,
        cost_model=cost_model,
        capacity_model=capacity_model,
        cost_multiplier=config.cost_stress_multiplier,
        config=config,
    )
    scenarios = [realistic, stress]
    # Fill-price stress: realistic costs (1.0x bps) but barrier exits fill with adverse
    # slippage beyond the level, isolating stop/gap-fill sensitivity from fee sensitivity.
    # A diagnostic only — the loop climbs ``realistic_costs``. Opt out with fraction 0.0.
    if config.fill_stress_fraction > 0.0:
        fill_stress_scenario, _ = _build_scenario(
            "fill_stress",
            row_index=row_index,
            decision_plan=decision_plan,
            data=data,
            cost_model=cost_model,
            capacity_model=capacity_model,
            cost_multiplier=1.0,
            fill_stress=config.fill_stress_fraction,
            config=config,
        )
        scenarios.append(fill_stress_scenario)
    return RunPortfolioFoundation(
        schema_version=FOUNDATION_SCHEMA_VERSION,
        basis=FOUNDATION_BASIS,
        evidence_class=FOUNDATION_EVIDENCE_CLASS,
        sizing_report=sizing_report,
        scenarios=tuple(scenarios),
        ledger=realistic_walk,
        mark_repair=_mark_repair_audit(mark_repair, scored_consumed_marks),
    )


def _mark_repair_audit(
    summary: Mapping[str, Any] | None,
    consumed: set[tuple[str, datetime]],
) -> dict[str, Any] | None:
    """Compact repair audit: the upstream repair summary plus the synthetic marks the
    scored walk actually consumed in P&L. ``None`` when nothing was repaired or used."""
    if not consumed and not (summary and summary.get("repaired_row_count")):
        return None
    audit: dict[str, Any] = dict(summary) if summary else {}
    audit["consumed_repaired_mark_count"] = len(consumed)
    audit["consumed_repaired_marks"] = [
        {"symbol": symbol, "timestamp": timestamp.isoformat()}
        for symbol, timestamp in sorted(consumed)
    ]
    return audit


def walk_portfolio_book(
    *,
    rows: Sequence[Mapping[str, Any]],
    decisions: Sequence[TargetDecision],
    data: DataConfig,
    fill_model: FillModelConfig,
    cost_model: CostModelConfig,
    capacity_model: CapacityModelConfig,
    config: PortfolioFoundationConfig,
    mark_rows: Sequence[Mapping[str, Any]] = (),
) -> BookWalkResult:
    """Run the single causal book once over ``rows`` at one cost/fill configuration.

    This is the lower-level entry beneath :func:`build_portfolio_foundation`: it is the
    same one causal, single-account, per-symbol-netted walk, but for exactly one cost
    scenario (no internal cost-stress fan-out, no subwindow scoring, no zero-cost or
    insufficient-sample scoring gate). It is the book a heavy surface (evaluation) runs
    per ``(window, scenario)`` to derive that fold's NAV ``period_return`` series and the
    fold scalars — one model of money on every surface (design D9). A
    :class:`FeasibilityError` (leverage-budget / unfinanced-leverage breach) is still
    raised mid-walk and never clamped (design D5); the cost-floor and minimum-sample
    verdicts are scoring-scenario concerns owned by ``build_portfolio_foundation`` and
    are intentionally not applied here, so a legitimate zero-cost evaluation scenario
    is not spuriously infeasible.
    """
    row_index = _RowIndex(rows, mark_rows)
    raw_decision_plan = _DecisionPlan(row_index, decisions, fill_model=fill_model)
    decision_plan, sizing_report = _sized_decision_plan(
        row_index=row_index,
        raw_decision_plan=raw_decision_plan,
        data=data,
        cost_model=cost_model,
        capacity_model=capacity_model,
        config=config,
    )
    per_side_cost_fraction = cost_model_per_side_fraction(cost_model)
    walk = _walk_book(
        row_index,
        decision_plan,
        per_side_cost_fraction=per_side_cost_fraction,
        data_kind=data.kind,
        capacity_model=capacity_model,
        config=config,
    )
    sizing_report = _completed_sizing_report(sizing_report, walk)
    return replace(walk, sizing_report=sizing_report)


def at_risk_period_returns(path: Sequence[PortfolioPathPoint]) -> tuple[float, ...]:
    """Return the scoreable at-risk period returns from a book NAV path."""
    return tuple(
        point.period_return for index, point in enumerate(path) if index > 0 and point.at_risk
    )


def cost_model_per_side_fraction(
    cost_model: CostModelConfig,
    *,
    cost_multiplier: float = 1.0,
) -> float:
    return _cost_fraction(
        (cost_model.fee_bps_per_side + cost_model.slippage_bps_per_side) * cost_multiplier
    )


def cost_model_slippage_per_side_fraction(
    cost_model: CostModelConfig,
    *,
    cost_multiplier: float = 1.0,
) -> float:
    return _cost_fraction(cost_model.slippage_bps_per_side * cost_multiplier)


@dataclass
class _NetPosition:
    """Running signed quantity for one symbol on the shared account.

    ``cost_basis`` is the signed cash committed to the currently-open leg
    (Σ ``delta_qty * fill_price`` since it last opened from flat); ``entry_signed_qty``
    is the signed quantity the leg opened at (for round-trip direction labelling).
    ``target_weight`` is the standing signed weight last set by a decision and is the
    intent the leverage-budget check measures.
    """

    symbol: str
    signed_qty: float = 0.0
    target_weight: float = 0.0
    entry_signed_qty: float = 0.0
    entry_weight: float = 0.0
    entry_decision_time: datetime | None = None
    entry_time: datetime | None = None
    entry_mark: float | None = None
    peak_mark: float | None = None
    trough_mark: float | None = None
    risk_rule: RiskRule | None = None
    decision_id: str | None = None
    cost_basis: float = 0.0
    open_cost: float = 0.0  # costs charged while building the current open leg
    open_impact_cost: float = 0.0
    funding_cashflow: float = 0.0

    @property
    def is_flat(self) -> bool:
        return self.signed_qty == 0.0


@dataclass(frozen=True)
class _PlannedDecision:
    symbol: str
    signed_weight: float
    risk_rule: RiskRule | None
    fill_row: Mapping[str, Any]
    fill_field: str
    decision_time: datetime
    decision_id: str | None


class _RowIndex:
    def __init__(
        self,
        rows: Sequence[Mapping[str, Any]],
        mark_rows: Sequence[Mapping[str, Any]] = (),
    ) -> None:
        by_symbol: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        by_key: dict[tuple[str, datetime], Mapping[str, Any]] = {}
        funding_rates_by_key: dict[tuple[str, datetime], float] = {}
        funding_events_by_apply_time: dict[datetime, list[tuple[str, datetime, float]]] = (
            defaultdict(list)
        )
        for row in rows:
            symbol = row.get("symbol")
            timestamp = row.get("timestamp")
            if not isinstance(symbol, str) or not isinstance(timestamp, datetime):
                continue
            by_symbol[symbol].append(row)
            by_key[(symbol, timestamp)] = row
            if row.get("has_funding_event") is True and isinstance(
                row.get("funding_timestamp"), datetime
            ):
                funding_timestamp = row["funding_timestamp"]
                funding_rate = _finite_float(row.get("funding_rate"), "invalid_funding_rate")
                funding_key = (symbol, funding_timestamp)
                existing = funding_rates_by_key.get(funding_key)
                if existing is not None:
                    if not funding_rates_match(existing, funding_rate):
                        raise ValueError(
                            f"conflicting_funding_rates:{symbol}:{funding_timestamp.isoformat()}"
                        )
                    continue
                funding_rates_by_key[funding_key] = funding_rate
                funding_events_by_apply_time[timestamp].append(
                    (symbol, funding_timestamp, funding_rate)
                )
        self.by_symbol = {
            symbol: tuple(sorted(items, key=lambda item: item["timestamp"]))
            for symbol, items in by_symbol.items()
        }
        self.positions = {
            symbol: {row["timestamp"]: index for index, row in enumerate(items)}
            for symbol, items in self.by_symbol.items()
        }
        self.timestamps_by_symbol = {
            symbol: tuple(row["timestamp"] for row in items)
            for symbol, items in self.by_symbol.items()
        }
        self._adv_notional_prefix_by_symbol: dict[str, tuple[float, ...]] = {}
        self.by_key = by_key
        self.timestamps = tuple(sorted({row["timestamp"] for row in by_key.values()}))
        self.funding_events_by_apply_time = {
            timestamp: tuple(events)
            for timestamp, events in sorted(funding_events_by_apply_time.items())
        }
        # Valuation-only mark index: observed + policy-bounded repaired rows. Consulted
        # only when the signal index lacks a bar for a held symbol (a data gap). Never
        # read by fills, capacity, or funding — those stay strictly on ``by_key``.
        mark_by_key: dict[tuple[str, datetime], Mapping[str, Any]] = {}
        for row in mark_rows:
            symbol = row.get("symbol")
            # Normalize the mark timestamp through the same parser the signal frame uses
            # (``NormalizedRows`` → ``parse_aware_datetime``), so the mark index keys
            # identically to ``by_key`` and the gap lookup cannot miss on a representation
            # difference between the two loaders.
            timestamp, _ = parse_aware_datetime(row.get("timestamp"))
            if isinstance(symbol, str) and timestamp is not None:
                mark_by_key[(symbol, timestamp)] = row
        self.mark_by_key = mark_by_key
        self.consumed_repaired_marks: set[tuple[str, datetime]] = set()

    def _adv_notional_prefix(
        self,
        symbol: str,
        rows: Sequence[Mapping[str, Any]],
    ) -> tuple[float, ...]:
        prefix = [0.0]
        for row in rows:
            timestamp = row["timestamp"]
            notional = _row_notional_volume(
                row,
                fallback_price=_positive_row_field(row, "close", symbol, timestamp),
                symbol=symbol,
                timestamp=timestamp,
            )
            prefix.append(prefix[-1] + notional)
        return tuple(prefix)

    def _adv_notional_prefix_for(self, symbol: str) -> tuple[float, ...]:
        prefix = self._adv_notional_prefix_by_symbol.get(symbol)
        if prefix is None:
            prefix = self._adv_notional_prefix(symbol, self.by_symbol.get(symbol, ()))
            self._adv_notional_prefix_by_symbol[symbol] = prefix
        return prefix

    def row_at(self, symbol: str, timestamp: datetime) -> Mapping[str, Any]:
        try:
            return self.by_key[(symbol, timestamp)]
        except KeyError as exc:
            raise ValueError(f"missing_mark:{symbol}:{timestamp.isoformat()}") from exc

    def _valuation_row(self, symbol: str, timestamp: datetime) -> Mapping[str, Any]:
        """Resolve a valuation row: the observed signal bar, else the repair-aware mark.

        Observed bars carry the same close in both frames, so the signal lookup is a
        trivially-equal fast path; the mark index is consulted only on a signal gap.
        A repaired mark consumed here is recorded for the ``is_repaired`` audit trail.
        A bar absent from both frames is a fail-closed ``missing_mark``."""
        row = self.by_key.get((symbol, timestamp))
        if row is not None:
            return row
        mark_row = self.mark_by_key.get((symbol, timestamp))
        if mark_row is None:
            raise ValueError(f"missing_mark:{symbol}:{timestamp.isoformat()}")
        if mark_row.get("is_repaired") is True:
            self.consumed_repaired_marks.add((symbol, timestamp))
        return mark_row

    def mark_at(self, symbol: str, timestamp: datetime) -> float:
        row = self._valuation_row(symbol, timestamp)
        close = row.get("close")
        # Happy path runs once per open position per bar; keep it allocation-free.
        # The error string (with isoformat) is built only on the failure branch, so a
        # successful lookup never pays for ``timestamp.isoformat()`` (perf review Major).
        if isinstance(close, (int, float)) and not isinstance(close, bool):
            value = float(close)
            if value > 0.0 and math.isfinite(value):
                return value
        return _positive_float(close, f"missing_mark:{symbol}:{timestamp.isoformat()}")

    def bar_at(self, symbol: str, timestamp: datetime) -> tuple[float, float, float, float]:
        """Return the bar's ``(open, high, low, close)`` for intrabar barrier evaluation.

        The row contract guarantees these fields are present, positive, and order-valid
        (``high >= max(open, close, low)``), so a ``RiskRule`` can be evaluated against the
        intrabar range rather than the close alone. Resolves through the valuation row, so
        a repaired flat bar (``open=high=low=close``) cannot fire a barrier and the rule
        resolves on the next observed bar. Like :meth:`mark_at`, the failure-only
        ``isoformat()`` keeps the happy path allocation-free."""
        row = self._valuation_row(symbol, timestamp)
        return (
            _positive_row_field(row, "open", symbol, timestamp),
            _positive_row_field(row, "high", symbol, timestamp),
            _positive_row_field(row, "low", symbol, timestamp),
            _positive_row_field(row, "close", symbol, timestamp),
        )

    def adv_notional_before(
        self,
        symbol: str,
        timestamp: datetime,
        *,
        lookback_bars: int,
        min_observations: int,
    ) -> float:
        timestamps = self.timestamps_by_symbol.get(symbol, ())
        prior_count = bisect_left(timestamps, timestamp)
        observation_count = min(lookback_bars, prior_count)
        if observation_count < min_observations:
            raise FeasibilityError(
                FeasibilityVerdict(
                    feasible=False,
                    reason=REASON_CAPACITY_INSUFFICIENT_ADV_HISTORY,
                    detail=(
                        f"capacity ADV history {observation_count} < minimum {min_observations} "
                        f"for {symbol} before {timestamp.isoformat()}"
                    ),
                )
            )
        prefix = self._adv_notional_prefix_for(symbol)
        start = prior_count - observation_count
        return (prefix[prior_count] - prefix[start]) / observation_count


class _DecisionPlan:
    """Resolves each standing target to its effective fill bar (entry-lag honored).

    A decision at ``decision_time`` becomes effective at the per-symbol bar
    ``decision_index + entry_lag_bars`` (the engine fill convention), so the book is
    lookahead-free and reuses the reference fill mechanics. Decisions are grouped by
    their effective fill timestamp on the global bar grid.
    """

    def __init__(
        self,
        row_index: _RowIndex,
        decisions: Sequence[TargetDecision],
        *,
        fill_model: FillModelConfig,
    ) -> None:
        by_time: dict[datetime, list[_PlannedDecision]] = defaultdict(list)
        for item in decisions:
            symbol = item.instrument.symbol
            symbol_rows = row_index.by_symbol.get(symbol)
            if not symbol_rows:
                raise ValueError(f"missing_symbol:{symbol}")
            position_by_time = row_index.positions[symbol]
            if item.decision_time not in position_by_time:
                raise ValueError(f"missing_decision_bar:{symbol}:{item.decision_time.isoformat()}")
            decision_index = position_by_time[item.decision_time]
            fill_index = decision_index + fill_model.entry_lag_bars
            if fill_index >= len(symbol_rows):
                raise ValueError(f"unfillable_decision:{symbol}:{item.decision_time.isoformat()}")
            fill_row = symbol_rows[fill_index]
            by_time[fill_row["timestamp"]].append(
                _PlannedDecision(
                    symbol=symbol,
                    signed_weight=float(item.target),
                    risk_rule=item.risk_rule,
                    fill_row=fill_row,
                    fill_field=fill_model.price,
                    decision_time=item.decision_time,
                    decision_id=item.decision_id,
                )
            )
        self.by_time = {timestamp: tuple(items) for timestamp, items in sorted(by_time.items())}
        self.symbols = tuple(sorted({item.instrument.symbol for item in decisions}))

    def scaled(self, scale: float) -> _DecisionPlan:
        plan = object.__new__(_DecisionPlan)
        plan.by_time = {
            timestamp: tuple(
                replace(item, signed_weight=item.signed_weight * scale) for item in items
            )
            for timestamp, items in self.by_time.items()
        }
        plan.symbols = self.symbols
        return plan


@dataclass(frozen=True)
class _FrontierResult:
    book_scale: float
    binding_dimensions: tuple[str, ...]


def _sized_decision_plan(
    *,
    row_index: _RowIndex,
    raw_decision_plan: _DecisionPlan,
    data: DataConfig,
    cost_model: CostModelConfig,
    capacity_model: CapacityModelConfig,
    config: PortfolioFoundationConfig,
) -> tuple[_DecisionPlan, PortfolioSizingReport]:
    normalized_plan, shape = _normalized_shape_plan(raw_decision_plan)
    risk_budget = config.risk_budget
    if risk_budget.mode == "fixed_scale":
        book_scale = cast(float, risk_budget.book_scale)
        report = _sizing_report(
            risk_budget,
            shape=shape,
            book_scale=book_scale,
            deployed_volatility=None,
            max_feasible_volatility=None,
            capacity_bound=False,
            max_feasible_book_scale=None,
            binding_dimensions=(),
        )
        return normalized_plan.scaled(book_scale), report

    target_volatility = cast(float, risk_budget.target_volatility)
    if shape.normalized_max_gross <= _EXPOSURE_TOLERANCE:
        report = _sizing_report(
            risk_budget,
            shape=shape,
            book_scale=0.0,
            deployed_volatility=None,
            max_feasible_volatility=None,
            capacity_bound=False,
            max_feasible_book_scale=0.0,
            binding_dimensions=(),
        )
        return normalized_plan.scaled(0.0), report

    frontier = _feasible_frontier(
        row_index=row_index,
        normalized_plan=normalized_plan,
        data=data,
        cost_model=cost_model,
        capacity_model=capacity_model,
        config=config,
        shape=shape,
    )
    if frontier.book_scale <= 0.0:
        report = _sizing_report(
            risk_budget,
            shape=shape,
            book_scale=0.0,
            deployed_volatility=0.0,
            max_feasible_volatility=0.0,
            capacity_bound=True,
            max_feasible_book_scale=0.0,
            binding_dimensions=frontier.binding_dimensions,
        )
        return normalized_plan.scaled(0.0), report

    frontier_walk = _priced_candidate_walk(
        row_index=row_index,
        normalized_plan=normalized_plan,
        book_scale=frontier.book_scale,
        data=data,
        cost_model=cost_model,
        capacity_model=capacity_model,
        config=config,
    )
    frontier_volatility = _annualized_volatility(
        frontier_walk,
        periods_per_year=risk_budget.annualization_periods_per_year,
    )
    if frontier_volatility is None:
        book_scale = frontier.book_scale
        deployed_volatility = None
    elif frontier_volatility <= _volatility_ceiling(target_volatility):
        book_scale = frontier.book_scale
        deployed_volatility = frontier_volatility
    else:
        book_scale, deployed_volatility = _calibrated_book_scale(
            row_index=row_index,
            normalized_plan=normalized_plan,
            data=data,
            cost_model=cost_model,
            capacity_model=capacity_model,
            config=config,
            target_volatility=target_volatility,
            max_book_scale=frontier.book_scale,
            max_volatility=frontier_volatility,
        )
    capacity_bound = (
        frontier_volatility is not None
        and frontier_volatility < target_volatility - _volatility_tolerance(target_volatility)
    )
    report = _sizing_report(
        risk_budget,
        shape=shape,
        book_scale=book_scale,
        deployed_volatility=deployed_volatility,
        max_feasible_volatility=frontier_volatility,
        capacity_bound=capacity_bound,
        max_feasible_book_scale=frontier.book_scale,
        binding_dimensions=frontier.binding_dimensions,
    )
    return normalized_plan.scaled(book_scale), report


def _normalized_shape_plan(
    raw_decision_plan: _DecisionPlan,
) -> tuple[_DecisionPlan, NormalizedShapeMetadata]:
    raw_gross, raw_net = _decision_plan_exposure_bounds(raw_decision_plan)
    divisor = raw_gross if raw_gross > 0.0 else 1.0
    normalized_plan = raw_decision_plan.scaled(1.0 / divisor)
    normalized_gross, normalized_net = _decision_plan_exposure_bounds(normalized_plan)
    shape = NormalizedShapeMetadata(
        method="max_intended_raw_gross",
        raw_gross_normalization_scalar=raw_gross,
        raw_max_gross=raw_gross,
        raw_max_net=raw_net,
        normalized_max_gross=normalized_gross,
        normalized_max_net=normalized_net,
        decision_count=sum(len(items) for items in raw_decision_plan.by_time.values()),
    )
    return normalized_plan, shape


def _decision_plan_exposure_bounds(plan: _DecisionPlan) -> tuple[float, float]:
    intended: dict[str, float] = {}
    max_gross = 0.0
    max_net = 0.0
    for _timestamp, planned in plan.by_time.items():
        for decision in planned:
            if decision.signed_weight == 0.0:
                intended.pop(decision.symbol, None)
            else:
                intended[decision.symbol] = decision.signed_weight
        gross = sum(abs(weight) for weight in intended.values())
        net = abs(sum(intended.values()))
        max_gross = max(max_gross, gross)
        max_net = max(max_net, net)
    return max_gross, max_net


def _feasible_frontier(
    *,
    row_index: _RowIndex,
    normalized_plan: _DecisionPlan,
    data: DataConfig,
    cost_model: CostModelConfig,
    capacity_model: CapacityModelConfig,
    config: PortfolioFoundationConfig,
    shape: NormalizedShapeMetadata,
) -> _FrontierResult:
    if shape.normalized_max_gross <= _EXPOSURE_TOLERANCE:
        return _FrontierResult(book_scale=0.0, binding_dimensions=())
    leverage_scale, leverage_dimensions = _leverage_frontier_scale(shape, config)
    # The leverage cap is exact in ``s``: intended gross/net exposure is the declared
    # book shape scaled by ``s`` (NAV-independent, degree-1), so a leverage / unfinanced
    # / short breach cannot trip at or below ``leverage_scale``. Walk once at the cap; if
    # feasible, that is the frontier. Otherwise only capacity can bind below it.
    walk, verdict = _probe_scale(
        row_index=row_index,
        normalized_plan=normalized_plan,
        book_scale=leverage_scale,
        data=data,
        cost_model=cost_model,
        capacity_model=capacity_model,
        config=config,
    )
    if walk is not None:
        return _FrontierResult(book_scale=leverage_scale, binding_dimensions=leverage_dimensions)
    if verdict is None or verdict.reason != REASON_CAPACITY_LIMIT_BREACH:
        raise FeasibilityError(
            verdict
            or FeasibilityVerdict(
                feasible=False,
                reason="sizing_frontier_failed",
                detail="frontier candidate failed without a typed verdict",
            )
        )
    return _capacity_frontier(
        row_index=row_index,
        normalized_plan=normalized_plan,
        data=data,
        cost_model=cost_model,
        capacity_model=capacity_model,
        config=config,
        leverage_scale=leverage_scale,
        leverage_dimensions=leverage_dimensions,
        breach=verdict,
    )


def _capacity_frontier(
    *,
    row_index: _RowIndex,
    normalized_plan: _DecisionPlan,
    data: DataConfig,
    cost_model: CostModelConfig,
    capacity_model: CapacityModelConfig,
    config: PortfolioFoundationConfig,
    leverage_scale: float,
    leverage_dimensions: tuple[str, ...],
    breach: FeasibilityVerdict,
) -> _FrontierResult:
    """Capacity-bound frontier below the leverage cap via a safeguarded secant.

    The bracket ``[low, high]`` keeps ``low`` feasible and ``high`` infeasible; each
    candidate is verified by a real walk. Capacity utilization ``u(s) = max event
    participation / its limit`` is monotone-increasing and first-order linear in ``s``,
    so the secant predicts the ``u = 1`` crossing in 1-3 steps. The candidate is capped at
    the bracket midpoint (:func:`_bracketed_scale`), so a probe that still breaches halves
    the infeasible end of the bracket — the search reaches a feasible scale in bisection
    time and cannot creep or stall at ``0`` even when the breach seed (a first-breach
    utilization, a lower bound on the true peak) is uninformative; feasible probes then
    climb toward the frontier by verified secant steps. The returned scale is the largest
    verified-feasible candidate — never less conservative than a verified point, since the
    NAV/impact residual can locally kink ``u``.
    """
    binding_dimensions = tuple(sorted(set(leverage_dimensions) | {"capacity"}))
    low, util_low = 0.0, 0.0
    high, util_high = leverage_scale, _breach_utilization(breach)
    best_scale = 0.0
    for _ in range(_CALIBRATION_ITERATIONS):
        if high - low <= _SIZING_SCALE_TOLERANCE * max(high, 1.0):
            break
        candidate = _bracketed_scale(low, util_low, high, util_high, 1.0)
        walk, verdict = _probe_scale(
            row_index=row_index,
            normalized_plan=normalized_plan,
            book_scale=candidate,
            data=data,
            cost_model=cost_model,
            capacity_model=capacity_model,
            config=config,
        )
        if walk is not None:
            best_scale = candidate
            low, util_low = candidate, _capacity_utilization(walk, capacity_model)
            if util_low >= 1.0 - _FRONTIER_UTILIZATION_TOLERANCE:
                # At the frontier from below; tightening the bracket further cannot raise
                # the largest verified-feasible scale.
                break
            continue
        if verdict is None or verdict.reason != REASON_CAPACITY_LIMIT_BREACH:
            raise FeasibilityError(
                verdict
                or FeasibilityVerdict(
                    feasible=False,
                    reason="sizing_frontier_failed",
                    detail="frontier candidate failed without a typed verdict",
                )
            )
        high, util_high = candidate, _breach_utilization(verdict)
    return _FrontierResult(book_scale=best_scale, binding_dimensions=binding_dimensions)


def _breach_utilization(verdict: FeasibilityVerdict) -> float:
    """Capacity utilization (participation / limit, ``>= 1``) at an infeasible scale.

    A capacity breach always records both observables; the degenerate-limit guard returns
    ``inf`` so the secant falls back to bisection rather than dividing by zero.
    """
    observed = verdict.observed_participation
    limit = verdict.participation_limit
    if observed is None or limit is None or limit <= 0.0 or not math.isfinite(observed):
        return math.inf
    return observed / limit


def _capacity_utilization(walk: BookWalkResult, capacity_model: CapacityModelConfig) -> float:
    """Peak capacity utilization over a completed walk: the largest participation/limit
    ratio across executed events. ``0.0`` when capacity is not priced or nothing traded;
    ``1.0`` is the frontier."""
    if capacity_model.mode != "adv_impact":
        return 0.0
    max_adv = capacity_model.max_adv_participation
    max_bar = capacity_model.max_bar_participation
    utilization = 0.0
    for event in walk.execution_events:
        if max_adv is not None and max_adv > 0.0:
            utilization = max(utilization, event.adv_participation / max_adv)
        if max_bar is not None and max_bar > 0.0:
            utilization = max(utilization, event.bar_participation / max_bar)
    return utilization


def _secant_predict(
    low: float, f_low: float, high: float, f_high: float, target: float
) -> float | None:
    """Scale where a near-linear ``f(s)`` reaches ``target``, by secant through two
    bracket points. ``None`` when the slope is degenerate (the caller bisects instead)."""
    slope = f_high - f_low
    if not math.isfinite(slope) or abs(slope) <= _EXPOSURE_TOLERANCE:
        return None
    predicted = low + (target - f_low) * (high - low) / slope
    if not math.isfinite(predicted):
        return None
    return predicted


def _bracketed_scale(low: float, f_low: float, high: float, f_high: float, target: float) -> float:
    """Next probe scale for a ``[low, high]`` bracket: the secant prediction toward
    ``target``, capped at the bracket midpoint and bisected when degenerate or out of
    range. Because the candidate never exceeds the midpoint, a *rejecting* probe (one
    that moves the far, infeasible/above-target end) drops that end to at most the
    midpoint — the rejecting side halves each step — so the search reaches the feasible
    region in bisection time and cannot creep or stall at ``0`` on a poor endpoint
    estimate. A verified probe then advances the near end by a secant step, which can be
    below the midpoint (so the accepted bound may move less than half) and accelerates the
    common, near-linear case."""
    midpoint = low + (high - low) / 2.0
    predicted = _secant_predict(low, f_low, high, f_high, target)
    if predicted is None or not (low < predicted < high):
        return midpoint
    return min(predicted, midpoint)


def _leverage_frontier_scale(
    shape: NormalizedShapeMetadata,
    config: PortfolioFoundationConfig,
) -> tuple[float, tuple[str, ...]]:
    gross_scale = (
        math.inf
        if shape.normalized_max_gross <= _EXPOSURE_TOLERANCE
        else config.max_gross_exposure / shape.normalized_max_gross
    )
    net_scale = (
        math.inf
        if shape.normalized_max_net <= _EXPOSURE_TOLERANCE
        else config.max_net_exposure / shape.normalized_max_net
    )
    scale = min(gross_scale, net_scale)
    if not math.isfinite(scale):
        return 0.0, ()
    dimensions: list[str] = []
    if math.isclose(scale, gross_scale, rel_tol=1e-12, abs_tol=1e-12):
        dimensions.append("gross_leverage")
    if math.isclose(scale, net_scale, rel_tol=1e-12, abs_tol=1e-12):
        dimensions.append("net_leverage")
    return scale, tuple(dimensions)


def _probe_scale(
    *,
    row_index: _RowIndex,
    normalized_plan: _DecisionPlan,
    book_scale: float,
    data: DataConfig,
    cost_model: CostModelConfig,
    capacity_model: CapacityModelConfig,
    config: PortfolioFoundationConfig,
) -> tuple[BookWalkResult | None, FeasibilityVerdict | None]:
    """Walk the book at ``book_scale``. Return ``(walk, None)`` when feasible so the
    caller can reuse the walk's recorded utilization, or ``(None, verdict)`` on a
    fail-closed breach."""
    try:
        walk = _priced_candidate_walk(
            row_index=row_index,
            normalized_plan=normalized_plan,
            book_scale=book_scale,
            data=data,
            cost_model=cost_model,
            capacity_model=capacity_model,
            config=config,
        )
    except FeasibilityError as exc:
        return None, exc.verdict
    return walk, None


def _priced_candidate_walk(
    *,
    row_index: _RowIndex,
    normalized_plan: _DecisionPlan,
    book_scale: float,
    data: DataConfig,
    cost_model: CostModelConfig,
    capacity_model: CapacityModelConfig,
    config: PortfolioFoundationConfig,
) -> BookWalkResult:
    return _walk_book(
        row_index,
        normalized_plan.scaled(book_scale),
        per_side_cost_fraction=cost_model_per_side_fraction(cost_model),
        data_kind=data.kind,
        capacity_model=capacity_model,
        config=config,
    )


def _calibrated_book_scale(
    *,
    row_index: _RowIndex,
    normalized_plan: _DecisionPlan,
    data: DataConfig,
    cost_model: CostModelConfig,
    capacity_model: CapacityModelConfig,
    config: PortfolioFoundationConfig,
    target_volatility: float,
    max_book_scale: float,
    max_volatility: float,
) -> tuple[float, float | None]:
    """Largest book scale whose deployed volatility stays within the target ceiling.

    Below the feasible frontier every positive scale is feasible and its volatility is
    measurable, monotone-increasing, and first-order linear in ``s`` with a NAV-compounding
    + market-impact residual. The secant through the origin gives the linear seed
    ``s* = max_book_scale * target / vol(max_book_scale)``; a safeguarded bracketed secant
    then refines for the residual. ``max_book_scale`` / ``max_volatility`` are the frontier
    walk's already-computed (scale, volatility) — the upper, above-ceiling bracket end —
    passed in to avoid an extra walk. The result is the largest verified scale with
    volatility ``<= ceiling`` (never above it).
    """
    periods_per_year = config.risk_budget.annualization_periods_per_year
    ceiling = _volatility_ceiling(target_volatility)
    band = _volatility_tolerance(target_volatility)
    low, vol_low = 0.0, 0.0
    high, vol_high = max_book_scale, max_volatility
    best_scale: float = 0.0
    best_volatility: float | None = 0.0
    for _ in range(_CALIBRATION_ITERATIONS):
        if high - low <= _SIZING_SCALE_TOLERANCE * max(high, 1.0):
            break
        candidate = _bracketed_scale(low, vol_low, high, vol_high, target_volatility)
        walk = _priced_candidate_walk(
            row_index=row_index,
            normalized_plan=normalized_plan,
            book_scale=candidate,
            data=data,
            cost_model=cost_model,
            capacity_model=capacity_model,
            config=config,
        )
        volatility = _annualized_volatility(walk, periods_per_year=periods_per_year)
        # Volatility is defined for every ``s > 0`` here: the at-risk sample count is
        # scale-invariant, and the caller only calibrates when the frontier volatility is
        # defined. A ``None`` is therefore unreachable; treat it conservatively as below
        # target (scale up) and keep the secant's lower anchor on the last real value.
        if volatility is None or volatility <= ceiling:
            best_scale, best_volatility = candidate, volatility
            low = candidate
            if volatility is not None:
                vol_low = volatility
                if volatility >= target_volatility - band:
                    break
        else:
            # The upper anchor refreshes only on an above-ceiling probe. On the feasible
            # branch it is intentionally left pinned to the original frontier (a verified
            # above-ceiling bound), which keeps the bracket's infeasible end valid; do not
            # re-anchor it to a feasible point.
            high, vol_high = candidate, volatility
    return best_scale, best_volatility


def _annualized_volatility(
    walk: BookWalkResult,
    *,
    periods_per_year: int,
) -> float | None:
    returns = [
        float(value) for value in at_risk_period_returns(walk.path) if math.isfinite(float(value))
    ]
    if len(returns) < 2:
        return None
    return _sample_stdev(returns) * math.sqrt(periods_per_year)


def _volatility_tolerance(target_volatility: float) -> float:
    return max(1e-12, target_volatility * _VOLATILITY_TOLERANCE_FRACTION)


def _volatility_ceiling(target_volatility: float) -> float:
    return target_volatility + _volatility_tolerance(target_volatility)


def _sizing_report(
    risk_budget: RiskBudgetConfig,
    *,
    shape: NormalizedShapeMetadata,
    book_scale: float,
    deployed_volatility: float | None,
    max_feasible_volatility: float | None,
    capacity_bound: bool,
    max_feasible_book_scale: float | None,
    binding_dimensions: tuple[str, ...],
) -> PortfolioSizingReport:
    return PortfolioSizingReport(
        schema_version=SIZING_REPORT_SCHEMA_VERSION,
        mode=risk_budget.mode,
        shape=shape,
        annualization_periods_per_year=risk_budget.annualization_periods_per_year,
        book_scale=book_scale,
        target_volatility=risk_budget.target_volatility,
        deployed_volatility=deployed_volatility,
        max_feasible_volatility=max_feasible_volatility,
        capacity_bound=capacity_bound,
        max_feasible_book_scale=max_feasible_book_scale,
        binding_dimensions=binding_dimensions,
        final_max_intended_gross=shape.normalized_max_gross * book_scale,
        final_max_intended_net=shape.normalized_max_net * book_scale,
    )


def _completed_sizing_report(
    report: PortfolioSizingReport,
    walk: BookWalkResult,
) -> PortfolioSizingReport:
    deployed_volatility = _annualized_volatility(
        walk,
        periods_per_year=report.annualization_periods_per_year,
    )
    return replace(report, deployed_volatility=deployed_volatility)


def _build_scenario(
    scenario_id: str,
    *,
    row_index: _RowIndex,
    decision_plan: _DecisionPlan,
    data: DataConfig,
    cost_model: CostModelConfig,
    capacity_model: CapacityModelConfig,
    cost_multiplier: float,
    fill_stress: float = 0.0,
    config: PortfolioFoundationConfig,
) -> tuple[FoundationScenarioResult, BookWalkResult]:
    per_side_cost_fraction = cost_model_per_side_fraction(
        cost_model,
        cost_multiplier=cost_multiplier,
    )
    walk = _walk_book(
        row_index,
        decision_plan,
        per_side_cost_fraction=per_side_cost_fraction,
        fill_stress=fill_stress,
        data_kind=data.kind,
        capacity_model=capacity_model,
        config=config,
    )
    full_train, subwindows = _scenario_metrics(
        walk.path,
        walk.round_trips,
        subwindows=config.subwindows,
        min_return_sample=config.min_return_sample,
        data_start=data.start,
        data_end=data.end,
    )
    verdict = scenario_feasibility(
        walk.feasibility,
        full_train.statistics,
        per_side_cost_fraction=per_side_cost_fraction,
        slippage_per_side_fraction=cost_model_slippage_per_side_fraction(
            cost_model, cost_multiplier=cost_multiplier
        ),
        min_return_sample=config.min_return_sample,
    )
    return (
        FoundationScenarioResult(
            scenario_id=scenario_id,
            cost_multiplier=cost_multiplier,
            feasibility=verdict,
            full_train=full_train,
            subwindows=tuple(subwindows),
            capacity=_capacity_diagnostics(walk),
        ),
        walk,
    )


def _capacity_diagnostics(walk: BookWalkResult) -> dict[str, Any]:
    events = walk.execution_events
    bar_participations = [event.bar_participation for event in events]
    adv_participations = [event.adv_participation for event in events]
    return {
        "execution_event_count": len(events),
        "total_normalized_turnover": sum(event.normalized_notional for event in events),
        "total_real_turnover": sum(event.real_notional for event in events),
        "total_impact_cost": sum(event.impact_cost for event in events),
        "max_bar_participation": max(bar_participations, default=0.0),
        "mean_bar_participation": _mean(bar_participations),
        "max_adv_participation": max(adv_participations, default=0.0),
        "mean_adv_participation": _mean(adv_participations),
    }


def _walk_book(
    row_index: _RowIndex,
    decision_plan: _DecisionPlan,
    *,
    per_side_cost_fraction: float,
    fill_stress: float = 0.0,
    data_kind: DataKind,
    capacity_model: CapacityModelConfig,
    config: PortfolioFoundationConfig,
) -> BookWalkResult:
    _check_capacity_supported(data_kind, capacity_model)
    cash = INITIAL_EQUITY
    peak = INITIAL_EQUITY
    previous_nav: float | None = None
    previous_gross = 0.0
    positions: dict[str, _NetPosition] = {}
    latched: dict[str, float] = {}
    path: list[PortfolioPathPoint] = []
    round_trips: list[RoundTrip] = []
    funding_events: list[FundingEvent] = []
    execution_events: list[ExecutionEvent] = []
    financed = data_kind in _FINANCED_DATA_KINDS

    for timestamp in row_index.timestamps:
        # 1. Funding/financing on the NET held position (single localized friction).
        cash += _apply_funding(row_index, positions, timestamp, funding_events)

        # 2. RiskRule overlay on the intrabar range BEFORE new entries this bar. Only a
        # position carrying a RiskRule reads the intrabar range; a stop-less position has
        # no barrier to evaluate, so it never needs more than the close used for marking.
        for symbol in tuple(positions):
            position = positions[symbol]
            if position.is_flat or position.risk_rule is None:
                continue
            bar_open, high, low, _close = row_index.bar_at(symbol, timestamp)
            fired = _risk_rule_fired(position, high=high, low=low)
            if fired is not None:
                exit_reason, level = fired
                fill_price = _barrier_fill_price(
                    position, level, bar_open, exit_reason, fill_stress
                )
                cash += _flatten(
                    row_index,
                    position,
                    fill_price,
                    per_side_cost_fraction,
                    capacity_model,
                    data_kind,
                    timestamp,
                    exit_reason,
                    round_trips,
                    execution_events,
                )
                # Latch the symbol flat at the standing weight that fired, so a
                # standing target does not re-enter until a different target arrives.
                latched[symbol] = position.target_weight
                position.signed_qty = 0.0
                position.risk_rule = None
            else:
                # Extend the trailing extremes only on a non-firing bar (prior-peak rule).
                _update_trailing(position, high=high, low=low)

        # 3. Apply decisions effective at t against one pre-entry equity snapshot.
        planned = decision_plan.by_time.get(timestamp, ())
        if planned:
            equity = _equity_at_mark(row_index, positions, timestamp, cash)
            if equity <= 0.0:
                raise ValueError(f"nonpositive_equity_for_entry:{timestamp.isoformat()}:{equity}")
            _check_intended_budget(
                positions,
                latched,
                planned,
                config=config,
                financed=financed,
                data_kind=data_kind,
                timestamp=timestamp,
            )
            for decision in planned:
                cash += _apply_decision(
                    row_index,
                    positions,
                    latched,
                    decision,
                    equity=equity,
                    per_side_cost_fraction=per_side_cost_fraction,
                    capacity_model=capacity_model,
                    data_kind=data_kind,
                    timestamp=timestamp,
                    round_trips=round_trips,
                    execution_events=execution_events,
                )

        # 4. Mark-to-market on one account -> NAV[t]; exposure series. Live marked
        # gross/net is a reported utilization series, never an infeasibility (D3):
        # a winner drifting above the ceiling is a risk signal, not a breach. The
        # fail-closed leverage/unfinanced verdicts are evaluated on intended exposure.
        nav = _equity_at_mark(row_index, positions, timestamp, cash)
        gross_exposure, net_exposure, concentration = _exposures(
            row_index, positions, timestamp, nav
        )
        period_return = 0.0 if previous_nav is None else (nav / previous_nav) - 1.0
        # "Return on capital deployed at the interval start": a bar is at-risk iff the
        # book held gross exposure entering it. This deliberately excludes the entry
        # (flat->position) bar's return — capital was flat at its start — but includes
        # the exit bar (capital was deployed at its start). The entry-cost and exit-cost
        # bars are therefore treated asymmetrically in the Sharpe *sample* (one
        # cost-sized return per episode); total-return/NAV capture both costs exactly,
        # so this is an accepted, internally consistent convention, not a leak (quant #4).
        at_risk = previous_gross > _EXPOSURE_TOLERANCE
        peak = max(peak, nav)
        drawdown = 0.0 if peak == 0.0 else (nav / peak) - 1.0
        path.append(
            PortfolioPathPoint(
                timestamp=timestamp,
                portfolio_value=nav,
                period_return=period_return,
                at_risk=at_risk,
                drawdown=drawdown,
                gross_exposure=gross_exposure,
                net_exposure=net_exposure,
                concentration=concentration,
            )
        )
        previous_nav = nav
        previous_gross = gross_exposure

    final_nav = previous_nav if previous_nav is not None else INITIAL_EQUITY
    return BookWalkResult(
        path=tuple(path),
        round_trips=tuple(round_trips),
        feasibility=FeasibilityVerdict(feasible=True),
        final_nav=final_nav,
        realized_pnl=_realized_so_far(round_trips),
        execution_events=tuple(execution_events),
        funding_events=tuple(funding_events),
    )


def _realized_so_far(round_trips: Sequence[RoundTrip]) -> float:
    return sum(trip.realized_pnl for trip in round_trips)


def _resolve_fill(
    decision: _PlannedDecision,
    *,
    equity: float,
    current_signed_qty: float,
) -> tuple[float, float]:
    """Resolve the executed fill price and target quantity for one decision.

    For ``close``/``open`` fills the price is direction-independent, so the target
    quantity follows directly. For the ``quote`` model the executed side depends on
    the **traded direction**: the target is first sized against the mid to decide buy
    (delta>0 → lift the ask) vs sell (delta<0 → hit the bid), then the quantity is
    re-sized at the crossed side. This makes a close-of-long or a reversal cross the
    correct side instead of taking a free favorable half-spread (quant review #3).
    """
    if decision.fill_field != "quote":
        fill_price = _fill_price_for_trade(decision.fill_row, decision.fill_field, buying=True)
        return fill_price, (decision.signed_weight * equity) / fill_price

    reference = _quote_reference_price(decision.fill_row)
    reference_qty = (decision.signed_weight * equity) / reference
    buying = (reference_qty - current_signed_qty) > 0.0
    fill_price = _fill_price_for_trade(decision.fill_row, "quote", buying=buying)
    return fill_price, (decision.signed_weight * equity) / fill_price


def _apply_decision(
    row_index: _RowIndex,
    positions: dict[str, _NetPosition],
    latched: dict[str, float],
    decision: _PlannedDecision,
    *,
    equity: float,
    per_side_cost_fraction: float,
    capacity_model: CapacityModelConfig,
    data_kind: DataKind,
    timestamp: datetime,
    round_trips: list[RoundTrip],
    execution_events: list[ExecutionEvent],
) -> float:
    """Net one standing target into the book; return the cash delta.

    Honors the re-entry latch: while a symbol is latched flat after a fired
    ``RiskRule``, a re-applied identical target is suppressed; a new (different)
    target clears the latch and trades.
    """
    symbol = decision.symbol
    latched_value = latched.get(symbol)
    if latched_value is not None:
        if _weights_match(latched_value, decision.signed_weight):
            return 0.0
        del latched[symbol]

    position = positions.setdefault(symbol, _NetPosition(symbol=symbol))
    position.target_weight = decision.signed_weight
    fill_price, target_qty = _resolve_fill(
        decision, equity=equity, current_signed_qty=position.signed_qty
    )
    delta = target_qty - position.signed_qty
    if delta == 0.0:
        # Idempotent re-emission of the current target: refresh the declared risk
        # rule so a newly-declared overlay takes effect, but trade nothing.
        position.risk_rule = decision.risk_rule
        return 0.0

    normalized_notional = abs(delta * fill_price)
    base_cost = normalized_notional * per_side_cost_fraction
    event = _capacity_execution_event(
        row_index,
        symbol=symbol,
        timestamp=timestamp,
        reason="signal",
        delta_units=delta,
        fill_price=fill_price,
        normalized_notional=normalized_notional,
        base_cost=base_cost,
        capacity_model=capacity_model,
        data_kind=data_kind,
        decision_time=decision.decision_time,
        decision_id=decision.decision_id,
    )
    execution_events.append(event)
    cash_delta = -event.total_cost
    crosses_zero = (position.signed_qty > 0.0 > target_qty) or (
        position.signed_qty < 0.0 < target_qty
    )

    if position.is_flat:
        position.cost_basis = delta * fill_price
        position.signed_qty = target_qty
        _open_leg(position, fill_price, timestamp, decision)
        position.open_cost = event.total_cost
        position.open_impact_cost = event.impact_cost
    elif target_qty == 0.0 or crosses_zero:
        # Close (and possibly reverse) the current net leg: realize the closed leg,
        # record the round-trip, then re-open any residual as a fresh leg. The
        # closing leg bears the full traded cost; a reversal's re-open starts a new
        # leg whose open cost is zero (the single trade's cost closed the old leg).
        cash_delta += _close_leg(
            position,
            fill_price,
            timestamp,
            event.total_cost,
            event.impact_cost,
            "signal",
            round_trips,
        )
        if target_qty == 0.0:
            position.signed_qty = 0.0
            position.risk_rule = None
        else:
            position.cost_basis = target_qty * fill_price
            position.signed_qty = target_qty
            _open_leg(position, fill_price, timestamp, decision)
            position.open_cost = 0.0
            position.open_impact_cost = 0.0
    else:
        # Add to / trim the same-sign leg without crossing zero.
        position.cost_basis += delta * fill_price
        position.signed_qty = target_qty
        position.open_cost += event.total_cost
        position.open_impact_cost += event.impact_cost
        position.risk_rule = decision.risk_rule

    return cash_delta


def _open_leg(
    position: _NetPosition,
    fill_price: float,
    timestamp: datetime,
    decision: _PlannedDecision,
) -> None:
    position.entry_time = timestamp
    position.entry_mark = fill_price
    position.peak_mark = fill_price
    position.trough_mark = fill_price
    position.risk_rule = decision.risk_rule
    position.funding_cashflow = 0.0
    position.open_impact_cost = 0.0
    position.entry_signed_qty = position.signed_qty
    position.entry_weight = decision.signed_weight
    position.entry_decision_time = decision.decision_time
    position.decision_id = decision.decision_id


def _close_leg(
    position: _NetPosition,
    exit_price: float,
    timestamp: datetime,
    close_cost: float,
    close_impact_cost: float,
    exit_reason: str,
    round_trips: list[RoundTrip],
) -> float:
    """Realize the open leg at ``exit_price``, record the round-trip, return cash.

    Returned cash is the price proceeds only (the caller charges ``close_cost``
    separately). The round-trip ``realized_pnl`` is the full economic PnL of the
    round trip - price proceeds + funding accrued while held - ``open_cost`` -
    ``close_cost`` - so that, when the book ends flat, sum of realized PnL
    reconciles exactly with realized NAV PnL (final NAV - initial equity) per D4.

    Cost attribution caveat (reversals): on a cross-zero reversal the caller passes
    the *whole* reversal-bar cost (close-of-old + open-of-new) as ``close_cost`` and
    re-opens the residual leg with ``open_cost = 0``. So the closing trip's
    ``cost_cash`` carries the entire reversal-bar cost and the reversed leg's eventual
    trip carries none of its own entry cost. The total cost across the two trips, and
    therefore NAV, is exact; only the per-trip split is approximate. ``cost_cash`` is
    a derived diagnostic (D4), not an independent score, so this attribution split never
    affects the authoritative NAV. The cash split (price proceeds, funding, total
    traded cost across open and close) is recorded so the derived per-trade ledger can
    expose reconciling gross/funding/cost returns.
    """
    proceeds = position.signed_qty * exit_price - position.cost_basis
    total_cost = position.open_cost + close_cost
    total_impact_cost = position.open_impact_cost + close_impact_cost
    round_trips.append(
        RoundTrip(
            symbol=position.symbol,
            direction=_direction(position.entry_signed_qty),
            decision_time=cast(datetime, position.entry_decision_time),
            entry_time=cast(datetime, position.entry_time),
            exit_time=timestamp,
            realized_pnl=proceeds + position.funding_cashflow - total_cost,
            gross_cash=proceeds,
            funding_cash=position.funding_cashflow,
            cost_cash=total_cost,
            impact_cost_cash=total_impact_cost,
            entry_weight=position.entry_weight,
            entry_mark=cast(float, position.entry_mark),
            exit_mark=exit_price,
            exit_reason=exit_reason,
            decision_id=position.decision_id,
        )
    )
    return proceeds


def _flatten(
    row_index: _RowIndex,
    position: _NetPosition,
    fill_price: float,
    per_side_cost_fraction: float,
    capacity_model: CapacityModelConfig,
    data_kind: DataKind,
    timestamp: datetime,
    exit_reason: str,
    round_trips: list[RoundTrip],
    execution_events: list[ExecutionEvent],
) -> float:
    """Flatten the net position at ``fill_price`` for a fired RiskRule; record round-trip.

    ``fill_price`` is the barrier fill from :func:`_barrier_fill_price` (level, gap-aware,
    optionally fill-stressed), not the bar close; cost scales with the executed notional."""
    delta = -position.signed_qty
    normalized_notional = abs(delta * fill_price)
    base_cost = normalized_notional * per_side_cost_fraction
    event = _capacity_execution_event(
        row_index,
        symbol=position.symbol,
        timestamp=timestamp,
        reason=exit_reason,
        delta_units=delta,
        fill_price=fill_price,
        normalized_notional=normalized_notional,
        base_cost=base_cost,
        capacity_model=capacity_model,
        data_kind=data_kind,
        decision_time=position.entry_decision_time,
        decision_id=position.decision_id,
    )
    execution_events.append(event)
    return (
        _close_leg(
            position,
            fill_price,
            timestamp,
            event.total_cost,
            event.impact_cost,
            exit_reason,
            round_trips,
        )
        - event.total_cost
    )


def _capacity_execution_event(
    row_index: _RowIndex,
    *,
    symbol: str,
    timestamp: datetime,
    reason: str,
    delta_units: float,
    fill_price: float,
    normalized_notional: float,
    base_cost: float,
    capacity_model: CapacityModelConfig,
    data_kind: DataKind,
    decision_time: datetime | None,
    decision_id: str | None,
) -> ExecutionEvent:
    if capacity_model.mode == "off":
        raise FeasibilityError(
            FeasibilityVerdict(
                feasible=False,
                reason=REASON_CAPACITY_UNPRICED,
                detail=f"capacity model is off for executed notional at {timestamp.isoformat()}",
            )
        )
    _check_capacity_supported(data_kind, capacity_model)
    if capacity_model.portfolio_notional is None:
        raise FeasibilityError(
            FeasibilityVerdict(
                feasible=False,
                reason=REASON_CAPACITY_UNPRICED,
                detail="capacity_model.portfolio_notional is required for ADV impact",
            )
        )

    real_notional = normalized_notional * capacity_model.portfolio_notional / INITIAL_EQUITY
    row = row_index.row_at(symbol, timestamp)
    bar_notional = _row_notional_volume(
        row, fallback_price=fill_price, symbol=symbol, timestamp=timestamp
    )
    adv_notional = row_index.adv_notional_before(
        symbol,
        timestamp,
        lookback_bars=capacity_model.adv_lookback_bars,
        min_observations=capacity_model.adv_min_observations,
    )
    bar_participation = real_notional / bar_notional
    adv_participation = real_notional / adv_notional
    _check_capacity_limit(
        "bar_participation",
        bar_participation,
        capacity_model.max_bar_participation,
        timestamp,
    )
    _check_capacity_limit(
        "adv_participation",
        adv_participation,
        capacity_model.max_adv_participation,
        timestamp,
    )
    impact_fraction = _cost_fraction(capacity_model.impact_coefficient_bps) * (
        adv_participation**capacity_model.impact_exponent
    )
    impact_cost = normalized_notional * impact_fraction
    total_cost = base_cost + impact_cost
    return ExecutionEvent(
        symbol=symbol,
        timestamp=timestamp,
        reason=reason,
        side="buy" if delta_units > 0.0 else "sell",
        fill_price=fill_price,
        delta_units=delta_units,
        normalized_notional=normalized_notional,
        real_notional=real_notional,
        base_cost=base_cost,
        impact_cost=impact_cost,
        total_cost=total_cost,
        bar_notional_volume=bar_notional,
        adv_notional_volume=adv_notional,
        bar_participation=bar_participation,
        adv_participation=adv_participation,
        decision_time=decision_time,
        decision_id=decision_id,
    )


def _check_capacity_supported(data_kind: DataKind, capacity_model: CapacityModelConfig) -> None:
    if capacity_model.mode != "adv_impact" or data_kind != "forex_with_quotes":
        return
    raise FeasibilityError(
        FeasibilityVerdict(
            feasible=False,
            reason=REASON_CAPACITY_UNSUPPORTED_VOLUME_SEMANTICS,
            detail="forex volume is tick-count activity, not notional capacity volume",
        )
    )


def _check_capacity_limit(
    name: str,
    observed: float,
    limit: float,
    timestamp: datetime,
) -> None:
    if observed <= limit + _EXPOSURE_TOLERANCE:
        return
    raise FeasibilityError(
        FeasibilityVerdict(
            feasible=False,
            reason=REASON_CAPACITY_LIMIT_BREACH,
            observed_participation=observed,
            participation_limit=limit,
            detail=f"{name} {observed:.6g} > limit {limit:.6g} at {timestamp.isoformat()}",
        )
    )


def _row_notional_volume(
    row: Mapping[str, Any],
    *,
    fallback_price: float,
    symbol: str,
    timestamp: datetime,
) -> float:
    raw_volume = row.get("volume")
    if not isinstance(raw_volume, (int, float)) or isinstance(raw_volume, bool):
        raise FeasibilityError(
            FeasibilityVerdict(
                feasible=False,
                reason=REASON_CAPACITY_MISSING_VOLUME,
                detail=f"missing positive capacity volume for {symbol} at {timestamp.isoformat()}",
            )
        )
    volume = float(raw_volume)
    if volume <= 0.0 or not math.isfinite(volume):
        raise FeasibilityError(
            FeasibilityVerdict(
                feasible=False,
                reason=REASON_CAPACITY_MISSING_VOLUME,
                detail=f"missing positive capacity volume for {symbol} at {timestamp.isoformat()}",
            )
        )
    raw_vwap = row.get("vwap")
    price = fallback_price
    try:
        maybe_vwap = _positive_float(raw_vwap, "invalid_vwap")
    except ValueError:
        maybe_vwap = None
    if maybe_vwap is not None:
        price = maybe_vwap
    if price <= 0.0 or not math.isfinite(price):
        raise FeasibilityError(
            FeasibilityVerdict(
                feasible=False,
                reason=REASON_CAPACITY_MISSING_VOLUME,
                detail=f"missing positive capacity price for {symbol} at {timestamp.isoformat()}",
            )
        )
    return volume * price


def _apply_funding(
    row_index: _RowIndex,
    positions: Mapping[str, _NetPosition],
    timestamp: datetime,
    funding_events: list[FundingEvent],
) -> float:
    """Charge funding on the live NET held quantity at each funding-apply time.

    Reuses the shared funding invariants (dedup via ``funding_rates_match`` upstream
    in ``_RowIndex``, window rule ``entry < funding_ts <= now`` on the held leg, sign
    ``-signed_qty * mark * rate``). A long pays positive funding, a short receives.
    Each applied cashflow is recorded into ``funding_events`` as the derived trace.
    """
    cash_delta = 0.0
    for symbol, funding_timestamp, funding_rate in row_index.funding_events_by_apply_time.get(
        timestamp, ()
    ):
        position = positions.get(symbol)
        if position is None or position.is_flat:
            continue
        if position.entry_time is None or not (
            position.entry_time < funding_timestamp <= timestamp
        ):
            continue
        # Funding apply-times are keyed by an observed signal bar's own timestamp, so this
        # ``mark_at`` always resolves via the signal fast path — never a repaired row.
        mark = row_index.mark_at(symbol, timestamp)
        cashflow = -position.signed_qty * mark * funding_rate
        cash_delta += cashflow
        position.funding_cashflow += cashflow
        funding_events.append(
            FundingEvent(
                symbol=symbol,
                timestamp=timestamp,
                funding_rate=funding_rate,
                position_units=position.signed_qty,
                mark_price=mark,
                cashflow=cashflow,
            )
        )
    return cash_delta


def _update_trailing(position: _NetPosition, *, high: float, low: float) -> None:
    """Extend the trailing extremes with this bar's intrabar high/low.

    Called only on a bar that did *not* fire (see :func:`_risk_rule_fired`), so the
    trailing stop is always tested against the *prior* extreme — a single bar cannot both
    set a new peak/trough and stop off it."""
    if position.peak_mark is None or high > position.peak_mark:
        position.peak_mark = high
    if position.trough_mark is None or low < position.trough_mark:
        position.trough_mark = low


def _risk_rule_fired(
    position: _NetPosition, *, high: float, low: float
) -> tuple[str, float] | None:
    """Return the fired rule's ``(exit_reason, barrier_level)`` or ``None``.

    Thresholds are evaluated against the bar's intrabar range (high/low), not the close:
    a barrier pierced intrabar fires even if the close recovered. Adverse barriers
    (``stop_loss``, ``trailing``) are checked before ``take_profit``, so a bar that touches
    both an adverse and a favorable level resolves to the adverse one — the conservative
    same-bar assumption, since intrabar order is unobservable. Trailing is tested against
    the *prior* peak/trough (the caller updates the extreme only after a non-firing bar)."""
    rule = position.risk_rule
    if rule is None or position.entry_mark is None:
        return None
    entry = position.entry_mark
    is_long = position.signed_qty > 0.0
    if rule.stop_loss is not None:
        if is_long:
            level = entry * (1.0 - rule.stop_loss)
            if low <= level:
                return "stop_loss", level
        else:
            level = entry * (1.0 + rule.stop_loss)
            if high >= level:
                return "stop_loss", level
    if rule.trailing is not None:
        if is_long and position.peak_mark is not None:
            level = position.peak_mark * (1.0 - rule.trailing)
            if low <= level:
                return "trailing", level
        if not is_long and position.trough_mark is not None:
            level = position.trough_mark * (1.0 + rule.trailing)
            if high >= level:
                return "trailing", level
    if rule.take_profit is not None:
        if is_long:
            level = entry * (1.0 + rule.take_profit)
            if high >= level:
                return "take_profit", level
        else:
            level = entry * (1.0 - rule.take_profit)
            if low <= level:
                return "take_profit", level
    return None


def _barrier_fill_price(
    position: _NetPosition,
    level: float,
    bar_open: float,
    exit_reason: str,
    fill_stress: float,
) -> float:
    """Fill price for a fired barrier exit.

    Adverse barriers (``stop_loss``/``trailing``) fill at the barrier level, but worsen to
    the bar's open on a gap-through (a long that opened below its stop fills at the lower
    open, not the level) — the gap risk the close-only model hid. ``take_profit`` fills at
    the level and is never granted a gap-favorable bonus. ``fill_stress`` (in ``[0, 1)``)
    then applies adverse slippage in the executed direction: closing a long sells (lower
    fill), closing a short buys (higher fill). The realistic scenario passes ``0.0``."""
    is_long = position.signed_qty > 0.0
    if exit_reason == "take_profit":
        base = level
    elif is_long:
        base = min(level, bar_open)
    else:
        base = max(level, bar_open)
    if fill_stress > 0.0:
        base *= (1.0 - fill_stress) if is_long else (1.0 + fill_stress)
    return base


def _check_intended_budget(
    positions: Mapping[str, _NetPosition],
    latched: Mapping[str, float],
    planned: Sequence[_PlannedDecision],
    *,
    config: PortfolioFoundationConfig,
    financed: bool,
    data_kind: DataKind,
    timestamp: datetime,
) -> None:
    """Fail closed when the intended target book breaches gross or net budget.

    Intended exposure is the declared standing book after applying this bar's
    decisions: a signed weight per symbol. A latched symbol whose target is being
    re-applied identically contributes nothing (it is suppressed). The check never
    clamps; it raises a typed verdict. For an asset class without modeled financing,
    an intended net above 1.0 that the operator budget permits is still infeasible
    (``unfinanced_leverage``) — financing the leverage is unpriced.
    """
    intended: dict[str, float] = {}
    for symbol, position in positions.items():
        if not position.is_flat:
            intended[symbol] = position.target_weight
    for decision in planned:
        latched_value = latched.get(decision.symbol)
        if latched_value is not None and _weights_match(latched_value, decision.signed_weight):
            continue
        if decision.signed_weight == 0.0:
            intended.pop(decision.symbol, None)
        else:
            intended[decision.symbol] = decision.signed_weight
    gross = sum(abs(weight) for weight in intended.values())
    net = abs(sum(intended.values()))
    if gross > config.max_gross_exposure + _EXPOSURE_TOLERANCE:
        raise FeasibilityError(
            FeasibilityVerdict(
                feasible=False,
                reason=REASON_LEVERAGE_BUDGET_BREACH,
                observed_gross=gross,
                observed_net=net,
                detail=(
                    f"intended gross {gross:.6g} > budget {config.max_gross_exposure:.6g} "
                    f"at {timestamp.isoformat()}"
                ),
            )
        )
    if net > config.max_net_exposure + _EXPOSURE_TOLERANCE:
        raise FeasibilityError(
            FeasibilityVerdict(
                feasible=False,
                reason=REASON_LEVERAGE_BUDGET_BREACH,
                observed_gross=gross,
                observed_net=net,
                detail=(
                    f"intended net {net:.6g} > budget {config.max_net_exposure:.6g} "
                    f"at {timestamp.isoformat()}"
                ),
            )
        )
    if not financed:
        short_symbols = sorted(symbol for symbol, weight in intended.items() if weight < 0.0)
        if short_symbols:
            raise FeasibilityError(
                FeasibilityVerdict(
                    feasible=False,
                    reason=REASON_UNPRICED_SHORT_FINANCING,
                    observed_gross=gross,
                    observed_net=net,
                    detail=(
                        "short financing/carry is unpriced for data kind "
                        f"{data_kind} at {timestamp.isoformat()}: {','.join(short_symbols)}"
                    ),
                )
            )
    if not financed and net > 1.0 + _EXPOSURE_TOLERANCE:
        raise FeasibilityError(
            FeasibilityVerdict(
                feasible=False,
                reason=REASON_UNFINANCED_LEVERAGE,
                observed_gross=gross,
                observed_net=net,
                detail=(
                    f"intended net {net:.6g} > 1.0 with unmodeled financing for data "
                    f"kind {data_kind} at {timestamp.isoformat()}"
                ),
            )
        )


def scenario_feasibility(
    walk_verdict: FeasibilityVerdict,
    full_train_statistics: ReturnStatistics,
    *,
    per_side_cost_fraction: float,
    slippage_per_side_fraction: float,
    min_return_sample: int,
) -> FeasibilityVerdict:
    """Combine the walk verdict with cost-floor and sample-gate verdicts.

    Precedence (most fundamental first): leverage/unfinanced (raised mid-walk) >
    zero-cost on a scoreable run > zero per-side slippage on a scoreable run >
    insufficient at-risk samples.
    """
    if not walk_verdict.feasible:
        return walk_verdict
    scoreable = full_train_statistics.return_sample_count >= min_return_sample
    if scoreable and per_side_cost_fraction <= 0.0:
        return FeasibilityVerdict(
            feasible=False,
            reason=REASON_ZERO_COST,
            detail="zero cost on a scoreable run is below the operator cost floor",
        )
    if scoreable and slippage_per_side_fraction <= 0.0:
        return FeasibilityVerdict(
            feasible=False,
            reason=REASON_ZERO_SLIPPAGE,
            detail=(
                "zero per-side slippage on a scoreable run is below the operator "
                "cost floor: taker fills (including stop/barrier exits) cannot be "
                "modeled without slippage"
            ),
        )
    if not scoreable:
        return FeasibilityVerdict(
            feasible=False,
            reason=REASON_INSUFFICIENT_SAMPLES,
            detail=(
                f"at-risk return sample {full_train_statistics.return_sample_count} "
                f"< minimum {min_return_sample}"
            ),
        )
    return FeasibilityVerdict(feasible=True)


def compute_return_statistics(
    returns: Iterable[float],
    *,
    min_return_sample: int = DEFAULT_MIN_RETURN_SAMPLE,
) -> ReturnStatistics:
    values = [float(value) for value in returns if math.isfinite(float(value))]
    warnings: list[str] = []
    sample_count = len(values)
    mean_return = (sum(values) / sample_count) if sample_count else None
    if sample_count < max(2, min_return_sample):
        return _insufficient_return_statistics(
            sample_count=sample_count,
            mean_return=mean_return,
        )

    stdev = _sample_stdev(values)
    if stdev == 0.0:
        warnings.append("zero_return_volatility")
        sharpe = None
    else:
        sharpe = cast(float, mean_return) / stdev
    skew, kurtosis = _shape(values, mean=cast(float, mean_return))
    effective_n = _effective_sample_size(values)
    sharpe_se = _sharpe_standard_error(
        sharpe,
        effective_sample_size=effective_n,
        skew=skew,
        kurtosis=kurtosis,
    )
    return ReturnStatistics(
        return_sample_count=sample_count,
        mean_return=mean_return,
        return_volatility=stdev,
        effective_sample_size=effective_n,
        sharpe=sharpe,
        sharpe_standard_error=sharpe_se,
        skew=skew,
        kurtosis=kurtosis,
        warnings=tuple(warnings),
    )


def _insufficient_return_statistics(
    *,
    sample_count: int,
    mean_return: float | None,
) -> ReturnStatistics:
    warnings = ["insufficient_return_sample"]
    return ReturnStatistics(
        return_sample_count=sample_count,
        mean_return=mean_return,
        return_volatility=None,
        effective_sample_size=None,
        sharpe=None,
        sharpe_standard_error=None,
        skew=None,
        kurtosis=None,
        warnings=tuple(warnings),
    )


def _scenario_metrics(
    path: Sequence[PortfolioPathPoint],
    round_trips: Sequence[RoundTrip],
    *,
    subwindows: int,
    min_return_sample: int,
    data_start: date,
    data_end: date,
) -> tuple[FoundationMetric, list[FoundationMetric]]:
    default_start, default_end = _train_bound_times(data_start, data_end, tzinfo=None)
    if not path:
        full_train = _metric_from_accumulator(
            "full_train",
            _MetricAccumulator(start_time=default_start, end_time=default_end),
            min_return_sample=min_return_sample,
        )
        return full_train, []
    scoring_path = [point for point in path if data_start <= point.timestamp.date() <= data_end]
    if not scoring_path:
        start_time, end_time = _train_bound_times(
            data_start,
            data_end,
            tzinfo=path[0].timestamp.tzinfo,
        )
        full_train = _metric_from_accumulator(
            "full_train",
            _MetricAccumulator(start_time=start_time, end_time=end_time),
            min_return_sample=min_return_sample,
        )
        return full_train, []
    bounds = _subwindow_bounds(scoring_path, subwindows=subwindows, start=data_start, end=data_end)
    full_train_accumulator = _FullTrainAccumulator(
        start_time=bounds[0][0],
        end_time=bounds[-1][1],
    )
    accumulators = [
        _MetricAccumulator(start_time=start_time, end_time=end_time)
        for start_time, end_time in bounds
    ]
    for path_index, point in enumerate(scoring_path):
        assigned = _bucket_for_timestamp(point.timestamp, bounds)
        if assigned is None:
            assigned = 0 if point.timestamp < bounds[0][0] else len(bounds) - 1
        _record_full_train_path_point(full_train_accumulator, point)
        accumulator = accumulators[assigned]
        _record_path_point(accumulator, point, include_return=path_index > 0)

    for trip in round_trips:
        abs_pnl = abs(trip.realized_pnl)
        if _timestamp_in_window(
            trip.exit_time,
            full_train_accumulator.start_time,
            full_train_accumulator.end_time,
            is_last=True,
        ):
            full_train_accumulator.closed_trade_count += 1
            full_train_accumulator.abs_pnl_by_symbol[trip.symbol] = (
                full_train_accumulator.abs_pnl_by_symbol.get(trip.symbol, 0.0) + abs_pnl
            )
        bucket = _bucket_for_timestamp(trip.exit_time, bounds)
        if bucket is not None:
            accumulators[bucket].closed_trade_count += 1
            accumulators[bucket].abs_pnl_by_symbol[trip.symbol] = (
                accumulators[bucket].abs_pnl_by_symbol.get(trip.symbol, 0.0) + abs_pnl
            )

    return (
        _metric_from_accumulator(
            "full_train",
            full_train_accumulator,
            return_chunks=tuple(accumulator.returns for accumulator in accumulators),
            min_return_sample=min_return_sample,
        ),
        [
            _metric_from_accumulator(
                f"train_{index + 1}",
                accumulator,
                min_return_sample=min_return_sample,
            )
            for index, accumulator in enumerate(accumulators)
        ],
    )


@dataclass
class _MetricAccumulator:
    start_time: datetime
    end_time: datetime
    returns: list[float] = field(default_factory=list)
    navs: list[float] = field(default_factory=list)
    abs_pnl_by_symbol: dict[str, float] = field(default_factory=dict)
    gross_samples: list[float] = field(default_factory=list)
    net_samples: list[float] = field(default_factory=list)
    closed_trade_count: int = 0


@dataclass
class _FullTrainAccumulator:
    start_time: datetime
    end_time: datetime
    first_nav: float | None = None
    last_nav: float | None = None
    peak_nav: float | None = None
    max_drawdown: float | None = None
    abs_pnl_by_symbol: dict[str, float] = field(default_factory=dict)
    gross_samples: list[float] = field(default_factory=list)
    net_samples: list[float] = field(default_factory=list)
    closed_trade_count: int = 0


def _record_path_point(
    accumulator: _MetricAccumulator,
    point: PortfolioPathPoint,
    *,
    include_return: bool,
) -> None:
    accumulator.navs.append(point.portfolio_value)
    accumulator.gross_samples.append(point.gross_exposure)
    accumulator.net_samples.append(point.net_exposure)
    if include_return and point.at_risk:
        accumulator.returns.append(point.period_return)


def _record_full_train_path_point(
    accumulator: _FullTrainAccumulator,
    point: PortfolioPathPoint,
) -> None:
    nav = point.portfolio_value
    if accumulator.first_nav is None:
        accumulator.first_nav = nav
        accumulator.peak_nav = nav
    accumulator.last_nav = nav
    peak = nav if accumulator.peak_nav is None else max(accumulator.peak_nav, nav)
    accumulator.peak_nav = peak
    drawdown = 0.0 if peak == 0.0 else (nav / peak) - 1.0
    accumulator.max_drawdown = (
        drawdown if accumulator.max_drawdown is None else min(accumulator.max_drawdown, drawdown)
    )
    accumulator.gross_samples.append(point.gross_exposure)
    accumulator.net_samples.append(point.net_exposure)


def _economic_concentration(abs_pnl_by_symbol: Mapping[str, float]) -> float:
    """Largest single symbol's share of the window's realized PnL.

    Economic dependence on one name, not the instantaneous gross-notional share: a
    diversified book whose PnL is spread across names scores low even when it holds
    one name at a time, and a genuine single-name book scores 1.0. A window with no
    realized PnL has no economic concentration and returns 0.0 (such a book is killed
    by the evidence and money-floor gates, not by breadth).
    """
    total = sum(abs_pnl_by_symbol.values())
    if total <= 0.0:
        return 0.0
    return max(abs_pnl_by_symbol.values()) / total


def _metric_from_accumulator(
    window_id: str,
    accumulator: _MetricAccumulator | _FullTrainAccumulator,
    *,
    returns: Iterable[float] | None = None,
    return_chunks: Sequence[Sequence[float]] | None = None,
    min_return_sample: int,
) -> FoundationMetric:
    if return_chunks is not None:
        statistics = compute_return_statistics(
            _iter_finite_chunk_values(return_chunks),
            min_return_sample=min_return_sample,
        )
    elif returns is None:
        if not isinstance(accumulator, _MetricAccumulator):
            raise ValueError("metric_returns_required")
        statistics = compute_return_statistics(
            accumulator.returns,
            min_return_sample=min_return_sample,
        )
    else:
        statistics = compute_return_statistics(
            returns,
            min_return_sample=min_return_sample,
        )
    return FoundationMetric(
        window_id=window_id,
        start_time=accumulator.start_time,
        end_time=accumulator.end_time,
        total_return=_accumulator_total_return(accumulator),
        max_drawdown=_accumulator_max_drawdown(accumulator),
        closed_trade_count=accumulator.closed_trade_count,
        max_symbol_concentration=_economic_concentration(accumulator.abs_pnl_by_symbol),
        max_gross_utilization=_max(accumulator.gross_samples),
        mean_gross_utilization=_mean(accumulator.gross_samples),
        max_net_utilization=_max(accumulator.net_samples),
        mean_net_utilization=_mean(accumulator.net_samples),
        statistics=statistics,
    )


def _train_bound_times(
    start: date,
    end: date,
    *,
    tzinfo: Any,
) -> tuple[datetime, datetime]:
    return (
        datetime.combine(start, datetime.min.time(), tzinfo=tzinfo),
        datetime.combine(end, datetime.max.time(), tzinfo=tzinfo),
    )


def _subwindow_bounds(
    path: Sequence[PortfolioPathPoint],
    *,
    subwindows: int,
    start: date,
    end: date,
) -> list[tuple[datetime, datetime]]:
    start_dt = datetime.combine(start, datetime.min.time(), tzinfo=path[0].timestamp.tzinfo)
    end_dt = datetime.combine(end, datetime.max.time(), tzinfo=path[-1].timestamp.tzinfo)
    bounds: list[tuple[datetime, datetime]] = []
    for index in range(subwindows):
        left = start_dt + (end_dt - start_dt) * (index / subwindows)
        right = start_dt + (end_dt - start_dt) * ((index + 1) / subwindows)
        bounds.append((left, right if index < subwindows - 1 else end_dt))
    return bounds


def _bucket_for_timestamp(
    timestamp: datetime,
    bounds: Sequence[tuple[datetime, datetime]],
) -> int | None:
    for index, (start_time, end_time) in enumerate(bounds):
        if _timestamp_in_window(
            timestamp,
            start_time,
            end_time,
            is_last=index == len(bounds) - 1,
        ):
            return index
    return None


def _timestamp_in_window(
    timestamp: datetime,
    start_time: datetime,
    end_time: datetime,
    *,
    is_last: bool,
) -> bool:
    if is_last:
        return start_time <= timestamp <= end_time
    return start_time <= timestamp < end_time


def _fill_price_for_trade(
    row: Mapping[str, Any],
    field: str,
    *,
    buying: bool,
) -> float:
    """Fill price for a trade, keyed on the executed direction (``buying``).

    For the ``quote`` model the executed side crosses the spread: a buy (``delta>0``)
    lifts the **ask**, a sell (``delta<0``) hits the **bid**. ``close``/``open`` fills
    are direction-independent. The traded direction is ``sign(delta)`` from netting —
    a close-of-long or a reversal sells, so it must cross the bid, not the ask.
    """
    if field == "quote":
        base = row.get("ask") if buying else row.get("bid")
        return _positive_float(base, "quote_fill_price")
    return _positive_float(row.get(field), f"fill_price:{field}")


def _quote_reference_price(row: Mapping[str, Any]) -> float:
    """Mid reference used only to determine the traded direction for a quote fill.

    The quote data contract guarantees ``mid`` on a quote-fill row; sizing the target
    against the mid decides buy vs sell, then the executed side (bid/ask) is crossed.
    """
    return _positive_float(row.get("mid"), "quote_reference_price")


def _equity_at_mark(
    row_index: _RowIndex,
    positions: Mapping[str, _NetPosition],
    timestamp: datetime,
    cash: float,
) -> float:
    equity = cash
    for position in positions.values():
        if position.is_flat:
            continue
        mark = row_index.mark_at(position.symbol, timestamp)
        equity += position.signed_qty * mark - position.cost_basis
    return equity


def _exposures(
    row_index: _RowIndex,
    positions: Mapping[str, _NetPosition],
    timestamp: datetime,
    nav: float,
) -> tuple[float, float, float]:
    """Marked-to-market gross, net, and per-symbol concentration on the netted book."""
    signed_notional: dict[str, float] = {}
    for symbol, position in positions.items():
        if position.is_flat:
            continue
        mark = row_index.mark_at(symbol, timestamp)
        signed_notional[symbol] = position.signed_qty * mark
    if not signed_notional or nav <= 0.0:
        return 0.0, 0.0, 0.0
    gross_notional = sum(abs(value) for value in signed_notional.values())
    net_notional = abs(sum(signed_notional.values()))
    gross = gross_notional / nav
    net = net_notional / nav
    concentration = (
        max(abs(value) for value in signed_notional.values()) / gross_notional
        if gross_notional > 0.0
        else 0.0
    )
    return gross, net, concentration


def _direction(signed_qty: float) -> str:
    return "long" if signed_qty >= 0.0 else "short"


def _weights_match(first: float, second: float) -> bool:
    return math.isclose(first, second, rel_tol=0.0, abs_tol=1e-12)


def _local_max_drawdown(values: Sequence[float]) -> float | None:
    if not values:
        return None
    peak = values[0]
    worst = 0.0
    for value in values:
        peak = max(peak, value)
        drawdown = 0.0 if peak == 0.0 else (value / peak) - 1.0
        worst = min(worst, drawdown)
    return worst


def _accumulator_total_return(
    accumulator: _MetricAccumulator | _FullTrainAccumulator,
) -> float | None:
    # Per-subwindow total_return compounds the bucket's at-risk returns, so (like the
    # at-risk Sharpe sample) it omits the excluded entry-cost bar; full_train uses NAV
    # endpoints (first/last NAV). The two definitions therefore differ by ~one entry
    # cost on a window that opens a position. Both are non-scored diagnostics (D4) and
    # the divergence is cost-sized; kept as-is so the praised half-open subwindow
    # return bucketing is not perturbed (quant #5, accepted approximation).
    if isinstance(accumulator, _MetricAccumulator):
        return _compound_return(accumulator.returns)
    if (
        accumulator.first_nav is None
        or accumulator.last_nav is None
        or accumulator.first_nav == 0.0
    ):
        return None
    return (accumulator.last_nav / accumulator.first_nav) - 1.0


def _compound_return(values: Sequence[float]) -> float | None:
    if not values:
        return None
    total = 1.0
    for value in values:
        total *= 1.0 + value
    return total - 1.0


def _accumulator_max_drawdown(
    accumulator: _MetricAccumulator | _FullTrainAccumulator,
) -> float | None:
    if isinstance(accumulator, _MetricAccumulator):
        return _local_max_drawdown(accumulator.navs) if accumulator.navs else None
    return accumulator.max_drawdown


def _max(values: Sequence[float]) -> float:
    return max(values) if values else 0.0


def _mean(values: Sequence[float]) -> float:
    return (sum(values) / len(values)) if values else 0.0


def _sample_stdev(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance)


def _iter_finite_chunk_values(chunks: Sequence[Sequence[float]]) -> Iterable[float]:
    for chunk in chunks:
        for value in chunk:
            metric = float(value)
            if math.isfinite(metric):
                yield metric


def _shape(values: Sequence[float], *, mean: float) -> tuple[float | None, float | None]:
    if len(values) < 2:
        return None, None
    second = sum((value - mean) ** 2 for value in values) / len(values)
    if second == 0.0:
        return None, None
    third = sum((value - mean) ** 3 for value in values) / len(values)
    fourth = sum((value - mean) ** 4 for value in values) / len(values)
    return third / (second**1.5), fourth / (second**2)


def _effective_sample_size(values: Sequence[float]) -> float | None:
    n = len(values)
    if n < 2:
        return None
    rho = _lag_one_autocorrelation(values)
    if rho is None or rho <= 0.0:
        return float(n)
    denominator = 1.0 + rho
    if denominator <= 0.0:
        return float(n)
    return max(1.0, min(float(n), float(n) * (1.0 - rho) / denominator))


def _lag_one_autocorrelation(values: Sequence[float]) -> float | None:
    if len(values) < 3:
        return None
    mean = sum(values) / len(values)
    denominator = sum((value - mean) ** 2 for value in values)
    if denominator == 0.0:
        return None
    numerator = sum(
        (values[index] - mean) * (values[index - 1] - mean) for index in range(1, len(values))
    )
    return numerator / denominator


def _sharpe_standard_error(
    sharpe: float | None,
    *,
    effective_sample_size: float | None,
    skew: float | None,
    kurtosis: float | None,
) -> float | None:
    if sharpe is None or effective_sample_size is None or effective_sample_size <= 1.0:
        return None
    skew_value = 0.0 if skew is None else skew
    kurtosis_value = 3.0 if kurtosis is None else kurtosis
    variance_term = 1.0 - (skew_value * sharpe) + (((kurtosis_value - 1.0) / 4.0) * sharpe**2)
    if variance_term <= 0.0:
        return None
    return math.sqrt(variance_term / (effective_sample_size - 1.0))


def _cost_fraction(value: float) -> float:
    if not math.isfinite(value) or value < 0.0:
        raise ValueError(f"invalid_cost_bps:{value}")
    return value / 10_000.0


def _positive_float(value: object, message: str) -> float:
    metric = _finite_float(value, message)
    if metric <= 0.0:
        raise ValueError(message)
    return metric


def _positive_row_field(
    row: Mapping[str, Any], field_name: str, symbol: str, timestamp: datetime
) -> float:
    """Positive OHLC field with a lazy failure message (allocation-free happy path)."""
    value = row.get(field_name)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        metric = float(value)
        if metric > 0.0 and math.isfinite(metric):
            return metric
    return _positive_float(value, f"missing_{field_name}:{symbol}:{timestamp.isoformat()}")


def _finite_float(value: object, message: str) -> float:
    if isinstance(value, bool) or value is None:
        raise ValueError(message)
    try:
        metric = float(cast(Any, value))
    except (TypeError, ValueError) as exc:
        raise ValueError(message) from exc
    if not math.isfinite(metric):
        raise ValueError(message)
    return metric
