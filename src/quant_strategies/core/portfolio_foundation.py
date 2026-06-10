from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from statistics import NormalDist
from typing import Any, cast

from quant_strategies.core.config import CostModelConfig, DataConfig, DataKind, FillModelConfig
from quant_strategies.core.serialization import json_safe_value
from quant_strategies.decisions import RiskRule, TargetDecision
from quant_strategies.funding import funding_rates_match

FOUNDATION_SCHEMA_VERSION = "quant_strategies.quick_run.portfolio_foundation/v2"
FOUNDATION_BASIS = "quick_run_netted_portfolio_book"
FOUNDATION_EVIDENCE_CLASS = "quick_run_portfolio_foundation_diagnostic"
INITIAL_EQUITY = 100.0
MAX_FOUNDATION_SUBWINDOWS = 64
DEFAULT_MIN_RETURN_SAMPLE = 2
EULER_MASCHERONI = 0.5772156649015329
DSR_FORMULA = "bailey_lopez_de_prado_expected_max_sharpe"

# Asset classes whose financing is modeled inside the book. Holding net leverage
# above 1.0 is only honestly scoreable when the financing of that leverage is
# priced; today only crypto-perp funding is modeled, so every other kind triggers
# the ``unfinanced_leverage`` feasibility verdict above net 1.0.
_FINANCED_DATA_KINDS: frozenset[DataKind] = frozenset({"crypto_perp_funding"})

FeasibilityReason = str  # one of the constants below

REASON_LEVERAGE_BUDGET_BREACH = "leverage_budget_breach"
REASON_ZERO_COST = "zero_cost"
REASON_INSUFFICIENT_SAMPLES = "insufficient_samples"
REASON_UNFINANCED_LEVERAGE = "unfinanced_leverage"

_EXPOSURE_TOLERANCE = 1e-9


@dataclass(frozen=True)
class PortfolioFoundationConfig:
    subwindows: int = 6
    trial_count: int | None = None
    benchmark_sharpe: float = 0.0
    cost_stress_multiplier: float = 2.0
    max_gross_exposure: float = 1.0
    max_net_exposure: float = 1.0
    min_return_sample: int = DEFAULT_MIN_RETURN_SAMPLE

    def __post_init__(self) -> None:
        if self.subwindows < 1:
            raise ValueError("foundation_subwindows must be >= 1")
        if self.subwindows > MAX_FOUNDATION_SUBWINDOWS:
            raise ValueError(f"foundation_subwindows must be <= {MAX_FOUNDATION_SUBWINDOWS}")
        if self.trial_count is not None and self.trial_count < 1:
            raise ValueError("foundation_trial_count must be >= 1 when provided")
        if not math.isfinite(self.benchmark_sharpe):
            raise ValueError("foundation_benchmark_sharpe must be finite")
        if not math.isfinite(self.cost_stress_multiplier) or self.cost_stress_multiplier < 1.0:
            raise ValueError("foundation_cost_stress_multiplier must be >= 1")
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
class DsrInputs:
    sample_length: int
    effective_sample_size: float | None
    skew: float | None
    kurtosis: float | None
    trial_count: int | None
    benchmark_sharpe: float
    deflated_sharpe_threshold: float | None
    formula: str = DSR_FORMULA

    def payload(self) -> dict[str, Any]:
        return cast(dict[str, Any], json_safe_value(self.__dict__))


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
    dsr_inputs: DsrInputs | None
    dsr: float | None
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
            "dsr_inputs": None if self.dsr_inputs is None else self.dsr_inputs.payload(),
            "dsr": self.dsr,
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

    def summary_payload(self) -> dict[str, Any]:
        dsrs = [item.statistics.dsr for item in self.subwindows if item.statistics.dsr is not None]
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
            "subwindow_count": len(self.subwindows),
            "min_dsr": min(dsrs) if dsrs else None,
            "median_dsr": _median(dsrs) if dsrs else None,
            "dsr_available_count": len(dsrs),
            "dsr_null_count": len(self.subwindows) - len(dsrs),
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
    scenarios: tuple[FoundationScenarioResult, ...]
    # The realistic-cost scenario's single causal walk. Its NAV ``path`` is the
    # authoritative scored object and its ``round_trips`` are the derived attribution
    # ledger the per-trade economics view is reconstructed from (design D4) — one
    # model of money, never an independent summation.
    ledger: BookWalkResult

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
                    "scenarios": {
                        scenario.scenario_id: scenario.summary_payload()
                        for scenario in self.scenarios
                    },
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
    funding_events: tuple[FundingEvent, ...] = ()


def build_portfolio_foundation(
    *,
    rows: Sequence[Mapping[str, Any]],
    decisions: Sequence[TargetDecision],
    data: DataConfig,
    fill_model: FillModelConfig,
    cost_model: CostModelConfig,
    config: PortfolioFoundationConfig,
) -> RunPortfolioFoundation:
    """Build the authoritative scored portfolio book over the two cost scenarios.

    The book is one causal, single-account, per-symbol-netted walk that consumes the
    standing ``TargetDecision`` stream and the execution ``rows``, applies frictions
    at one localized step, and derives all scored statistics from the NAV path.
    Infeasible scenarios raise :class:`FeasibilityError` carrying the typed verdict;
    the caller (Phase 1b) gates ``RunResult.succeeded`` on it.
    """
    row_index = _RowIndex(rows)
    decision_plan = _DecisionPlan(row_index, decisions, fill_model=fill_model)
    realistic, realistic_walk = _build_scenario(
        "realistic_costs",
        row_index=row_index,
        decision_plan=decision_plan,
        data=data,
        cost_model=cost_model,
        cost_multiplier=1.0,
        config=config,
    )
    stress, _ = _build_scenario(
        "cost_stress",
        row_index=row_index,
        decision_plan=decision_plan,
        data=data,
        cost_model=cost_model,
        cost_multiplier=config.cost_stress_multiplier,
        config=config,
    )
    return RunPortfolioFoundation(
        schema_version=FOUNDATION_SCHEMA_VERSION,
        basis=FOUNDATION_BASIS,
        evidence_class=FOUNDATION_EVIDENCE_CLASS,
        scenarios=(realistic, stress),
        ledger=realistic_walk,
    )


def walk_portfolio_book(
    *,
    rows: Sequence[Mapping[str, Any]],
    decisions: Sequence[TargetDecision],
    data: DataConfig,
    fill_model: FillModelConfig,
    cost_model: CostModelConfig,
    config: PortfolioFoundationConfig,
) -> BookWalkResult:
    """Run the single causal book once over ``rows`` at one cost/fill configuration.

    This is the lower-level entry beneath :func:`build_portfolio_foundation`: it is the
    same one causal, single-account, per-symbol-netted walk, but for exactly one cost
    scenario (no internal cost-stress fan-out, no subwindow/DSR scoring, no zero-cost or
    insufficient-sample scoring gate). It is the book a heavy surface (evaluation) runs
    per ``(window, scenario)`` to derive that fold's NAV ``period_return`` series and the
    fold scalars — one model of money on every surface (design D9). A
    :class:`FeasibilityError` (leverage-budget / unfinanced-leverage breach) is still
    raised mid-walk and never clamped (design D5); the cost-floor and minimum-sample
    verdicts are scoring-scenario concerns owned by ``build_portfolio_foundation`` and
    are intentionally not applied here, so a legitimate zero-cost evaluation scenario
    is not spuriously infeasible.
    """
    row_index = _RowIndex(rows)
    decision_plan = _DecisionPlan(row_index, decisions, fill_model=fill_model)
    per_side_cost_fraction = _cost_fraction(
        cost_model.fee_bps_per_side + cost_model.slippage_bps_per_side
    )
    return _walk_book(
        row_index,
        decision_plan,
        per_side_cost_fraction=per_side_cost_fraction,
        data_kind=data.kind,
        config=config,
    )


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
    def __init__(self, rows: Sequence[Mapping[str, Any]]) -> None:
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
        self.by_key = by_key
        self.timestamps = tuple(sorted({row["timestamp"] for row in by_key.values()}))
        self.funding_events_by_apply_time = {
            timestamp: tuple(events)
            for timestamp, events in sorted(funding_events_by_apply_time.items())
        }

    def row_at(self, symbol: str, timestamp: datetime) -> Mapping[str, Any]:
        try:
            return self.by_key[(symbol, timestamp)]
        except KeyError as exc:
            raise ValueError(f"missing_mark:{symbol}:{timestamp.isoformat()}") from exc

    def mark_at(self, symbol: str, timestamp: datetime) -> float:
        row = self.row_at(symbol, timestamp)
        close = row.get("close")
        # Happy path runs once per open position per bar; keep it allocation-free.
        # The error string (with isoformat) is built only on the failure branch, so a
        # successful lookup never pays for ``timestamp.isoformat()`` (perf review Major).
        if isinstance(close, (int, float)) and not isinstance(close, bool):
            value = float(close)
            if value > 0.0 and math.isfinite(value):
                return value
        return _positive_float(close, f"missing_mark:{symbol}:{timestamp.isoformat()}")


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


def _build_scenario(
    scenario_id: str,
    *,
    row_index: _RowIndex,
    decision_plan: _DecisionPlan,
    data: DataConfig,
    cost_model: CostModelConfig,
    cost_multiplier: float,
    config: PortfolioFoundationConfig,
) -> tuple[FoundationScenarioResult, BookWalkResult]:
    per_side_cost_fraction = _cost_fraction(
        (cost_model.fee_bps_per_side + cost_model.slippage_bps_per_side) * cost_multiplier
    )
    walk = _walk_book(
        row_index,
        decision_plan,
        per_side_cost_fraction=per_side_cost_fraction,
        data_kind=data.kind,
        config=config,
    )
    full_train, subwindows = _scenario_metrics(
        walk.path,
        walk.round_trips,
        subwindows=config.subwindows,
        trial_count=config.trial_count,
        benchmark_sharpe=config.benchmark_sharpe,
        min_return_sample=config.min_return_sample,
        data_start=data.start,
        data_end=data.end,
    )
    verdict = _scenario_feasibility(
        walk.feasibility,
        full_train.statistics,
        per_side_cost_fraction=per_side_cost_fraction,
        min_return_sample=config.min_return_sample,
    )
    return (
        FoundationScenarioResult(
            scenario_id=scenario_id,
            cost_multiplier=cost_multiplier,
            feasibility=verdict,
            full_train=full_train,
            subwindows=tuple(subwindows),
        ),
        walk,
    )


def _walk_book(
    row_index: _RowIndex,
    decision_plan: _DecisionPlan,
    *,
    per_side_cost_fraction: float,
    data_kind: DataKind,
    config: PortfolioFoundationConfig,
) -> BookWalkResult:
    cash = INITIAL_EQUITY
    peak = INITIAL_EQUITY
    previous_nav: float | None = None
    previous_gross = 0.0
    positions: dict[str, _NetPosition] = {}
    latched: dict[str, float] = {}
    path: list[PortfolioPathPoint] = []
    round_trips: list[RoundTrip] = []
    funding_events: list[FundingEvent] = []
    financed = data_kind in _FINANCED_DATA_KINDS

    for timestamp in row_index.timestamps:
        # 1. Funding/financing on the NET held position (single localized friction).
        cash += _apply_funding(row_index, positions, timestamp, funding_events)

        # 2. RiskRule overlay on the printed mark BEFORE new entries this bar.
        for symbol in tuple(positions):
            position = positions[symbol]
            if position.is_flat:
                continue
            mark = row_index.mark_at(symbol, timestamp)
            _update_trailing(position, mark)
            fired_reason = _risk_rule_fired(position, mark)
            if fired_reason is not None:
                cash += _flatten(
                    position, mark, per_side_cost_fraction, timestamp, fired_reason, round_trips
                )
                # Latch the symbol flat at the standing weight that fired, so a
                # standing target does not re-enter until a different target arrives.
                latched[symbol] = position.target_weight
                position.signed_qty = 0.0
                position.risk_rule = None

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
                    positions,
                    latched,
                    decision,
                    equity=equity,
                    per_side_cost_fraction=per_side_cost_fraction,
                    timestamp=timestamp,
                    round_trips=round_trips,
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
    positions: dict[str, _NetPosition],
    latched: dict[str, float],
    decision: _PlannedDecision,
    *,
    equity: float,
    per_side_cost_fraction: float,
    timestamp: datetime,
    round_trips: list[RoundTrip],
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

    cost = abs(delta * fill_price) * per_side_cost_fraction
    cash_delta = -cost
    crosses_zero = (position.signed_qty > 0.0 > target_qty) or (
        position.signed_qty < 0.0 < target_qty
    )

    if position.is_flat:
        position.cost_basis = delta * fill_price
        position.signed_qty = target_qty
        _open_leg(position, fill_price, timestamp, decision)
        position.open_cost = cost
    elif target_qty == 0.0 or crosses_zero:
        # Close (and possibly reverse) the current net leg: realize the closed leg,
        # record the round-trip, then re-open any residual as a fresh leg. The
        # closing leg bears the full traded cost; a reversal's re-open starts a new
        # leg whose open cost is zero (the single trade's cost closed the old leg).
        cash_delta += _close_leg(position, fill_price, timestamp, cost, "signal", round_trips)
        if target_qty == 0.0:
            position.signed_qty = 0.0
            position.risk_rule = None
        else:
            position.cost_basis = target_qty * fill_price
            position.signed_qty = target_qty
            _open_leg(position, fill_price, timestamp, decision)
            position.open_cost = 0.0
    else:
        # Add to / trim the same-sign leg without crossing zero.
        position.cost_basis += delta * fill_price
        position.signed_qty = target_qty
        position.open_cost += cost
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
    position.entry_signed_qty = position.signed_qty
    position.entry_weight = decision.signed_weight
    position.entry_decision_time = decision.decision_time
    position.decision_id = decision.decision_id


def _close_leg(
    position: _NetPosition,
    exit_price: float,
    timestamp: datetime,
    close_cost: float,
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
    a derived diagnostic (D4), not a scored number, so this attribution skew never
    affects the authoritative NAV. The cash split (price proceeds, funding, total
    traded cost across open and close) is recorded so the derived per-trade ledger can
    expose reconciling gross/funding/cost returns.
    """
    proceeds = position.signed_qty * exit_price - position.cost_basis
    total_cost = position.open_cost + close_cost
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
            entry_weight=position.entry_weight,
            entry_mark=cast(float, position.entry_mark),
            exit_mark=exit_price,
            exit_reason=exit_reason,
            decision_id=position.decision_id,
        )
    )
    return proceeds


def _flatten(
    position: _NetPosition,
    mark: float,
    per_side_cost_fraction: float,
    timestamp: datetime,
    exit_reason: str,
    round_trips: list[RoundTrip],
) -> float:
    """Flatten the net position at ``mark`` for a fired RiskRule; record round-trip."""
    cost = abs(position.signed_qty * mark) * per_side_cost_fraction
    return _close_leg(position, mark, timestamp, cost, exit_reason, round_trips) - cost


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


def _update_trailing(position: _NetPosition, mark: float) -> None:
    if position.peak_mark is None or mark > position.peak_mark:
        position.peak_mark = mark
    if position.trough_mark is None or mark < position.trough_mark:
        position.trough_mark = mark


def _risk_rule_fired(position: _NetPosition, mark: float) -> str | None:
    """Return the fired rule's exit reason (``stop_loss``/``take_profit``/``trailing``)
    or ``None`` when no declared threshold is crossed at this bar's printed mark."""
    rule = position.risk_rule
    if rule is None or position.entry_mark is None:
        return None
    entry = position.entry_mark
    is_long = position.signed_qty > 0.0
    if rule.stop_loss is not None:
        if is_long and mark <= entry * (1.0 - rule.stop_loss):
            return "stop_loss"
        if not is_long and mark >= entry * (1.0 + rule.stop_loss):
            return "stop_loss"
    if rule.take_profit is not None:
        if is_long and mark >= entry * (1.0 + rule.take_profit):
            return "take_profit"
        if not is_long and mark <= entry * (1.0 - rule.take_profit):
            return "take_profit"
    if rule.trailing is not None:
        if (
            is_long
            and position.peak_mark is not None
            and mark <= position.peak_mark * (1.0 - rule.trailing)
        ):
            return "trailing"
        if (
            not is_long
            and position.trough_mark is not None
            and mark >= position.trough_mark * (1.0 + rule.trailing)
        ):
            return "trailing"
    return None


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


def _scenario_feasibility(
    walk_verdict: FeasibilityVerdict,
    full_train_statistics: ReturnStatistics,
    *,
    per_side_cost_fraction: float,
    min_return_sample: int,
) -> FeasibilityVerdict:
    """Combine the walk verdict with cost-floor and sample-gate verdicts.

    Precedence (most fundamental first): leverage/unfinanced (raised mid-walk) >
    zero-cost on a scoreable run > insufficient at-risk samples.
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
    trial_count: int | None,
    benchmark_sharpe: float,
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
            trial_count=trial_count,
            benchmark_sharpe=benchmark_sharpe,
        )

    stdev = _sample_stdev(values)
    if stdev == 0.0:
        warnings.append("zero_return_volatility")
        sharpe = None
    else:
        sharpe = cast(float, mean_return) / stdev
    skew, kurtosis = _shape(values, mean=cast(float, mean_return), stdev=stdev)
    effective_n = _effective_sample_size(values)
    return _return_statistics_with_dsr(
        sample_count=sample_count,
        mean_return=mean_return,
        return_volatility=stdev,
        effective_sample_size=effective_n,
        sharpe=sharpe,
        skew=skew,
        kurtosis=kurtosis,
        trial_count=trial_count,
        benchmark_sharpe=benchmark_sharpe,
        warnings=warnings,
    )


def _compute_return_statistics_from_chunks(
    chunks: Sequence[Sequence[float]],
    *,
    trial_count: int | None,
    benchmark_sharpe: float,
    min_return_sample: int,
) -> ReturnStatistics:
    sample_count, total = _return_count_and_sum(chunks)
    mean_return = (total / sample_count) if sample_count else None
    if sample_count < max(2, min_return_sample):
        return _insufficient_return_statistics(
            sample_count=sample_count,
            mean_return=mean_return,
            trial_count=trial_count,
            benchmark_sharpe=benchmark_sharpe,
        )

    mean = cast(float, mean_return)
    stdev = _sample_stdev_from_chunks(chunks, sample_count=sample_count, mean=mean)
    if stdev == 0.0:
        warnings = ["zero_return_volatility"]
        sharpe = None
    else:
        warnings = []
        sharpe = mean / stdev
    skew, kurtosis = _shape_from_chunks(
        chunks,
        sample_count=sample_count,
        mean=mean,
        stdev=stdev,
    )
    effective_n = _effective_sample_size_from_chunks(
        chunks,
        sample_count=sample_count,
        mean=mean,
    )
    return _return_statistics_with_dsr(
        sample_count=sample_count,
        mean_return=mean_return,
        return_volatility=stdev,
        effective_sample_size=effective_n,
        sharpe=sharpe,
        skew=skew,
        kurtosis=kurtosis,
        trial_count=trial_count,
        benchmark_sharpe=benchmark_sharpe,
        warnings=warnings,
    )


def _insufficient_return_statistics(
    *,
    sample_count: int,
    mean_return: float | None,
    trial_count: int | None,
    benchmark_sharpe: float,
) -> ReturnStatistics:
    warnings = ["insufficient_return_sample"]
    if trial_count is None:
        warnings.append("missing_trial_count")
    return ReturnStatistics(
        return_sample_count=sample_count,
        mean_return=mean_return,
        return_volatility=None,
        effective_sample_size=None,
        sharpe=None,
        sharpe_standard_error=None,
        skew=None,
        kurtosis=None,
        dsr_inputs=DsrInputs(
            sample_length=sample_count,
            effective_sample_size=None,
            skew=None,
            kurtosis=None,
            trial_count=trial_count,
            benchmark_sharpe=benchmark_sharpe,
            deflated_sharpe_threshold=None,
        ),
        dsr=None,
        warnings=tuple(warnings),
    )


def _return_statistics_with_dsr(
    *,
    sample_count: int,
    mean_return: float | None,
    return_volatility: float | None,
    effective_sample_size: float | None,
    sharpe: float | None,
    skew: float | None,
    kurtosis: float | None,
    trial_count: int | None,
    benchmark_sharpe: float,
    warnings: list[str],
) -> ReturnStatistics:
    sharpe_se = _sharpe_standard_error(
        sharpe,
        effective_sample_size=effective_sample_size,
        skew=skew,
        kurtosis=kurtosis,
    )
    dsr = None
    threshold = None
    if trial_count is None:
        warnings.append("missing_trial_count")
    elif sharpe is None or sharpe_se is None or effective_sample_size is None:
        warnings.append("missing_dsr_statistic")
    else:
        threshold = _deflated_sharpe_threshold(
            benchmark_sharpe,
            trial_count=trial_count,
            sharpe_standard_error=sharpe_se,
        )
        dsr = _normal_cdf((sharpe - threshold) / sharpe_se)
    dsr_inputs = DsrInputs(
        sample_length=sample_count,
        effective_sample_size=effective_sample_size,
        skew=skew,
        kurtosis=kurtosis,
        trial_count=trial_count,
        benchmark_sharpe=benchmark_sharpe,
        deflated_sharpe_threshold=threshold,
    )
    return ReturnStatistics(
        return_sample_count=sample_count,
        mean_return=mean_return,
        return_volatility=return_volatility,
        effective_sample_size=effective_sample_size,
        sharpe=sharpe,
        sharpe_standard_error=sharpe_se,
        skew=skew,
        kurtosis=kurtosis,
        dsr_inputs=dsr_inputs,
        dsr=dsr,
        warnings=tuple(warnings),
    )


def _scenario_metrics(
    path: Sequence[PortfolioPathPoint],
    round_trips: Sequence[RoundTrip],
    *,
    subwindows: int,
    trial_count: int | None,
    benchmark_sharpe: float,
    min_return_sample: int,
    data_start: date,
    data_end: date,
) -> tuple[FoundationMetric, list[FoundationMetric]]:
    default_start, default_end = _train_bound_times(data_start, data_end, tzinfo=None)
    if not path:
        full_train = _metric_from_accumulator(
            "full_train",
            _MetricAccumulator(start_time=default_start, end_time=default_end),
            trial_count=trial_count,
            benchmark_sharpe=benchmark_sharpe,
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
            trial_count=trial_count,
            benchmark_sharpe=benchmark_sharpe,
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
        if _timestamp_in_window(
            trip.exit_time,
            full_train_accumulator.start_time,
            full_train_accumulator.end_time,
            is_last=True,
        ):
            full_train_accumulator.closed_trade_count += 1
        bucket = _bucket_for_timestamp(trip.exit_time, bounds)
        if bucket is not None:
            accumulators[bucket].closed_trade_count += 1

    return (
        _metric_from_accumulator(
            "full_train",
            full_train_accumulator,
            return_chunks=tuple(accumulator.returns for accumulator in accumulators),
            trial_count=trial_count,
            benchmark_sharpe=benchmark_sharpe,
            min_return_sample=min_return_sample,
        ),
        [
            _metric_from_accumulator(
                f"train_{index + 1}",
                accumulator,
                trial_count=trial_count,
                benchmark_sharpe=benchmark_sharpe,
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
    max_concentration: float = 0.0
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
    max_concentration: float = 0.0
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
    accumulator.max_concentration = max(accumulator.max_concentration, point.concentration)
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
    accumulator.max_concentration = max(accumulator.max_concentration, point.concentration)
    accumulator.gross_samples.append(point.gross_exposure)
    accumulator.net_samples.append(point.net_exposure)


def _metric_from_accumulator(
    window_id: str,
    accumulator: _MetricAccumulator | _FullTrainAccumulator,
    *,
    returns: Iterable[float] | None = None,
    return_chunks: Sequence[Sequence[float]] | None = None,
    trial_count: int | None,
    benchmark_sharpe: float,
    min_return_sample: int,
) -> FoundationMetric:
    if return_chunks is not None:
        statistics = _compute_return_statistics_from_chunks(
            return_chunks,
            trial_count=trial_count,
            benchmark_sharpe=benchmark_sharpe,
            min_return_sample=min_return_sample,
        )
    elif returns is None:
        if not isinstance(accumulator, _MetricAccumulator):
            raise ValueError("metric_returns_required")
        statistics = compute_return_statistics(
            accumulator.returns,
            trial_count=trial_count,
            benchmark_sharpe=benchmark_sharpe,
            min_return_sample=min_return_sample,
        )
    else:
        statistics = compute_return_statistics(
            returns,
            trial_count=trial_count,
            benchmark_sharpe=benchmark_sharpe,
            min_return_sample=min_return_sample,
        )
    return FoundationMetric(
        window_id=window_id,
        start_time=accumulator.start_time,
        end_time=accumulator.end_time,
        total_return=_accumulator_total_return(accumulator),
        max_drawdown=_accumulator_max_drawdown(accumulator),
        closed_trade_count=accumulator.closed_trade_count,
        max_symbol_concentration=accumulator.max_concentration,
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


def _return_count_and_sum(chunks: Sequence[Sequence[float]]) -> tuple[int, float]:
    count = 0
    total = 0.0
    for value in _iter_finite_chunk_values(chunks):
        count += 1
        total += value
    return count, total


def _sample_stdev_from_chunks(
    chunks: Sequence[Sequence[float]],
    *,
    sample_count: int,
    mean: float,
) -> float:
    if sample_count < 2:
        return 0.0
    variance = sum((value - mean) ** 2 for value in _iter_finite_chunk_values(chunks)) / (
        sample_count - 1
    )
    return math.sqrt(variance)


def _shape(
    values: Sequence[float], *, mean: float, stdev: float
) -> tuple[float | None, float | None]:
    if len(values) < 2 or stdev == 0.0:
        return None, None
    centered = [(value - mean) / stdev for value in values]
    skew = sum(value**3 for value in centered) / len(centered)
    kurtosis = sum(value**4 for value in centered) / len(centered)
    return skew, kurtosis


def _shape_from_chunks(
    chunks: Sequence[Sequence[float]],
    *,
    sample_count: int,
    mean: float,
    stdev: float,
) -> tuple[float | None, float | None]:
    if sample_count < 2 or stdev == 0.0:
        return None, None
    skew_sum = 0.0
    kurtosis_sum = 0.0
    for value in _iter_finite_chunk_values(chunks):
        centered = (value - mean) / stdev
        skew_sum += centered**3
        kurtosis_sum += centered**4
    return skew_sum / sample_count, kurtosis_sum / sample_count


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
    # ``values`` is the at-risk return series, which is non-contiguous when the book
    # goes flat between episodes. The lag-1 estimator treats it as contiguous, so the
    # (last-of-episode-A, first-of-episode-B) pair enters the autocorrelation though
    # the bars are not time-adjacent. The AR(1) effective-N formula is exact; only rho
    # picks up (#episodes - 1) seam pairs, and effective-N is clamped to [1, n], so it
    # cannot degenerate. Accepted approximation (quant #6); the chunked variant below
    # has the same seam behavior.
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


def _effective_sample_size_from_chunks(
    chunks: Sequence[Sequence[float]],
    *,
    sample_count: int,
    mean: float,
) -> float | None:
    if sample_count < 2:
        return None
    if sample_count < 3:
        return float(sample_count)
    denominator = 0.0
    numerator = 0.0
    previous_centered: float | None = None
    for value in _iter_finite_chunk_values(chunks):
        centered = value - mean
        denominator += centered**2
        if previous_centered is not None:
            numerator += centered * previous_centered
        previous_centered = centered
    if denominator == 0.0:
        return float(sample_count)
    rho = numerator / denominator
    if rho <= 0.0:
        return float(sample_count)
    effective_n = float(sample_count) * (1.0 - rho) / (1.0 + rho)
    return max(1.0, min(float(sample_count), effective_n))


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


def _deflated_sharpe_threshold(
    benchmark_sharpe: float,
    *,
    trial_count: int,
    sharpe_standard_error: float,
) -> float:
    if trial_count <= 1:
        return benchmark_sharpe
    trial_count_float = float(trial_count)
    expected_max_z = (
        (1.0 - EULER_MASCHERONI) * NormalDist().inv_cdf(1.0 - (1.0 / trial_count_float))
    ) + (EULER_MASCHERONI * NormalDist().inv_cdf(1.0 - (1.0 / (trial_count_float * math.e))))
    return benchmark_sharpe + (sharpe_standard_error * expected_max_z)


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _median(values: Sequence[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _cost_fraction(value: float) -> float:
    if not math.isfinite(value) or value < 0.0:
        raise ValueError(f"invalid_cost_bps:{value}")
    return value / 10_000.0


def _positive_float(value: object, message: str) -> float:
    metric = _finite_float(value, message)
    if metric <= 0.0:
        raise ValueError(message)
    return metric


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
