from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from statistics import NormalDist
from typing import Any, cast

from quant_strategies.core.config import CostModelConfig, DataConfig, FillModelConfig
from quant_strategies.core.serialization import json_safe_value
from quant_strategies.decisions import StrategyDecision
from quant_strategies.funding import funding_rates_match

FOUNDATION_SCHEMA_VERSION = "quant_strategies.quick_run.portfolio_foundation/v1"
FOUNDATION_BASIS = "quick_run_lightweight_portfolio_path"
FOUNDATION_EVIDENCE_CLASS = "quick_run_portfolio_foundation_diagnostic"
INITIAL_EQUITY = 100.0
MAX_FOUNDATION_SUBWINDOWS = 64
EULER_MASCHERONI = 0.5772156649015329
DSR_FORMULA = "bailey_lopez_de_prado_expected_max_sharpe"


@dataclass(frozen=True)
class PortfolioFoundationConfig:
    enabled: bool = True
    subwindows: int = 6
    trial_count: int | None = None
    benchmark_sharpe: float = 0.0
    cost_stress_multiplier: float = 2.0

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
    drawdown: float
    concentration: float


@dataclass(frozen=True)
class FoundationTrade:
    symbol: str
    entry_time: datetime
    exit_time: datetime
    net_pnl: float


@dataclass(frozen=True)
class FoundationSubwindowMetric:
    window_id: str
    start_time: datetime
    end_time: datetime
    max_drawdown: float | None
    closed_trade_count: int
    max_symbol_concentration: float
    statistics: ReturnStatistics

    def payload(self) -> dict[str, Any]:
        payload = {
            "window_id": self.window_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "max_drawdown": self.max_drawdown,
            "closed_trade_count": self.closed_trade_count,
            "max_symbol_concentration": self.max_symbol_concentration,
            **self.statistics.payload(),
        }
        return cast(dict[str, Any], json_safe_value(payload))


@dataclass(frozen=True)
class FoundationScenarioResult:
    scenario_id: str
    cost_multiplier: float
    subwindows: tuple[FoundationSubwindowMetric, ...]

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


def compute_return_statistics(
    returns: Sequence[float],
    *,
    trial_count: int | None,
    benchmark_sharpe: float,
) -> ReturnStatistics:
    values = [float(value) for value in returns if math.isfinite(float(value))]
    warnings: list[str] = []
    sample_count = len(values)
    if sample_count < 2:
        warnings.append("insufficient_return_sample")
        if trial_count is None:
            warnings.append("missing_trial_count")
        return ReturnStatistics(
            return_sample_count=sample_count,
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

    mean = sum(values) / sample_count
    stdev = _sample_stdev(values)
    if stdev == 0.0:
        warnings.append("zero_return_volatility")
        sharpe = None
    else:
        sharpe = mean / stdev
    skew, kurtosis = _shape(values, mean=mean, stdev=stdev)
    effective_n = _effective_sample_size(values)
    dsr_inputs = DsrInputs(
        sample_length=sample_count,
        effective_sample_size=effective_n,
        skew=skew,
        kurtosis=kurtosis,
        trial_count=trial_count,
        benchmark_sharpe=benchmark_sharpe,
        deflated_sharpe_threshold=None,
    )
    sharpe_se = _sharpe_standard_error(
        sharpe,
        effective_sample_size=effective_n,
        skew=skew,
        kurtosis=kurtosis,
    )
    dsr = None
    threshold = None
    if trial_count is None:
        warnings.append("missing_trial_count")
    elif sharpe is None or sharpe_se is None or effective_n is None:
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
        effective_sample_size=effective_n,
        skew=skew,
        kurtosis=kurtosis,
        trial_count=trial_count,
        benchmark_sharpe=benchmark_sharpe,
        deflated_sharpe_threshold=threshold,
    )
    return ReturnStatistics(
        return_sample_count=sample_count,
        effective_sample_size=effective_n,
        sharpe=sharpe,
        sharpe_standard_error=sharpe_se,
        skew=skew,
        kurtosis=kurtosis,
        dsr_inputs=dsr_inputs,
        dsr=dsr,
        warnings=tuple(warnings),
    )


def build_portfolio_foundation(
    *,
    rows: Sequence[Mapping[str, Any]],
    decisions: Sequence[StrategyDecision],
    executed_trades: Sequence[Any] | None = None,
    data: DataConfig,
    fill_model: FillModelConfig,
    cost_model: CostModelConfig,
    config: PortfolioFoundationConfig,
) -> RunPortfolioFoundation:
    if executed_trades is None:
        raise ValueError("executed_trades_required")
    row_index = _RowIndex(rows)
    scenarios = (
        _build_scenario(
            "realistic_costs",
            row_index=row_index,
            decisions=decisions,
            executed_trades=executed_trades,
            data=data,
            fill_model=fill_model,
            cost_model=cost_model,
            cost_multiplier=1.0,
            config=config,
        ),
        _build_scenario(
            "cost_stress",
            row_index=row_index,
            decisions=decisions,
            executed_trades=executed_trades,
            data=data,
            fill_model=fill_model,
            cost_model=cost_model,
            cost_multiplier=config.cost_stress_multiplier,
            config=config,
        ),
    )
    return RunPortfolioFoundation(
        schema_version=FOUNDATION_SCHEMA_VERSION,
        basis=FOUNDATION_BASIS,
        evidence_class=FOUNDATION_EVIDENCE_CLASS,
        scenarios=scenarios,
    )


@dataclass
class _Position:
    symbol: str
    direction: str
    target_weight: float
    signed_units: float
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    entry_fee: float
    funding_cashflow: float = 0.0
    applied_funding_timestamps: set[datetime] | None = None


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
        return _positive_float(row.get("close"), f"missing_mark:{symbol}:{timestamp.isoformat()}")


def _build_scenario(
    scenario_id: str,
    *,
    row_index: _RowIndex,
    decisions: Sequence[StrategyDecision],
    executed_trades: Sequence[Any],
    data: DataConfig,
    fill_model: FillModelConfig,
    cost_model: CostModelConfig,
    cost_multiplier: float,
    config: PortfolioFoundationConfig,
) -> FoundationScenarioResult:
    _ = decisions, fill_model
    decision_windows = _trade_windows(row_index, executed_trades)
    per_side_cost_fraction = _cost_fraction(
        (cost_model.fee_bps_per_side + cost_model.slippage_bps_per_side) * cost_multiplier
    )
    path, trades = _portfolio_path(
        row_index,
        decision_windows,
        per_side_cost_fraction=per_side_cost_fraction,
    )
    subwindows = _subwindow_metrics(
        path,
        trades,
        subwindows=config.subwindows,
        trial_count=config.trial_count,
        benchmark_sharpe=config.benchmark_sharpe,
        data_start=data.start,
        data_end=data.end,
    )
    return FoundationScenarioResult(
        scenario_id=scenario_id,
        cost_multiplier=cost_multiplier,
        subwindows=tuple(subwindows),
    )


def _decision_windows(
    row_index: _RowIndex,
    decisions: Sequence[StrategyDecision],
    *,
    fill_model: FillModelConfig,
) -> list[dict[str, Any]]:
    windows: list[dict[str, Any]] = []
    for item in decisions:
        symbol = item.instrument.symbol
        symbol_rows = row_index.by_symbol.get(symbol)
        if not symbol_rows:
            raise ValueError(f"missing_symbol:{symbol}")
        position_by_time = row_index.positions[symbol]
        if item.decision_time not in position_by_time:
            raise ValueError(f"missing_decision_bar:{symbol}:{item.decision_time.isoformat()}")
        decision_index = position_by_time[item.decision_time]
        entry_index = decision_index + fill_model.entry_lag_bars
        exit_index = entry_index + item.exit_policy.max_hold_bars + fill_model.exit_lag_bars
        if entry_index >= len(symbol_rows):
            raise ValueError(f"unfillable_entry:{symbol}:{item.decision_time.isoformat()}")
        if exit_index >= len(symbol_rows):
            raise ValueError(f"unfillable_exit:{symbol}:{item.decision_time.isoformat()}")
        entry_row = symbol_rows[entry_index]
        exit_row = symbol_rows[exit_index]
        windows.append(
            {
                "decision": item,
                "symbol": symbol,
                "direction": item.target.direction,
                "weight": float(item.target.size),
                "entry_time": entry_row["timestamp"],
                "exit_time": exit_row["timestamp"],
                "entry_price": _fill_price(
                    entry_row,
                    fill_model.price,
                    item.target.direction,
                    is_entry=True,
                ),
                "exit_price": _fill_price(
                    exit_row,
                    fill_model.price,
                    item.target.direction,
                    is_entry=False,
                ),
            }
        )
    return windows


def _trade_windows(row_index: _RowIndex, trades: Sequence[Any]) -> list[dict[str, Any]]:
    windows: list[dict[str, Any]] = []
    for trade in trades:
        symbol = _trade_field(trade, "symbol")
        direction = _trade_field(trade, "side")
        entry_time = _trade_datetime(trade, "entry_time")
        exit_time = _trade_datetime(trade, "exit_time")
        row_index.row_at(symbol, entry_time)
        row_index.row_at(symbol, exit_time)
        windows.append(
            {
                "symbol": symbol,
                "direction": direction,
                "weight": _trade_float(trade, "weight"),
                "entry_time": entry_time,
                "exit_time": exit_time,
                "entry_price": _trade_float(trade, "entry_price"),
                "exit_price": _trade_float(trade, "exit_price"),
            }
        )
    return windows


def _trade_field(trade: Any, field: str) -> str:
    value = trade.get(field) if isinstance(trade, Mapping) else getattr(trade, field, None)
    if not isinstance(value, str) or not value:
        raise ValueError(f"trade_{field}_missing")
    return value


def _trade_datetime(trade: Any, field: str) -> datetime:
    value = trade.get(field) if isinstance(trade, Mapping) else getattr(trade, field, None)
    if not isinstance(value, datetime):
        raise ValueError(f"trade_{field}_missing")
    return value


def _trade_float(trade: Any, field: str) -> float:
    value = trade.get(field) if isinstance(trade, Mapping) else getattr(trade, field, None)
    return _finite_float(value, f"trade_{field}_invalid")


def _portfolio_path(
    row_index: _RowIndex,
    windows: Sequence[Mapping[str, Any]],
    *,
    per_side_cost_fraction: float,
) -> tuple[list[PortfolioPathPoint], list[FoundationTrade]]:
    entries_by_time: dict[datetime, list[Mapping[str, Any]]] = defaultdict(list)
    exits_by_time: dict[datetime, list[Mapping[str, Any]]] = defaultdict(list)
    for window in windows:
        entries_by_time[window["entry_time"]].append(window)
        exits_by_time[window["exit_time"]].append(window)

    cash = INITIAL_EQUITY
    peak = INITIAL_EQUITY
    previous_nav: float | None = None
    active: dict[int, _Position] = {}
    path: list[PortfolioPathPoint] = []
    trades: list[FoundationTrade] = []
    window_keys = {id(window): index for index, window in enumerate(windows)}

    for timestamp in row_index.timestamps:
        _apply_funding(row_index, active, timestamp, cash_ref := {"cash": cash})
        cash = cash_ref["cash"]

        for window in exits_by_time.get(timestamp, ()):
            key = window_keys[id(window)]
            position = active.pop(key)
            exit_price = float(window["exit_price"])
            realized_pnl = position.signed_units * (exit_price - position.entry_price)
            exit_fee = abs(position.signed_units * exit_price) * per_side_cost_fraction
            cash += realized_pnl - exit_fee
            net_pnl = realized_pnl + position.funding_cashflow - position.entry_fee - exit_fee
            trades.append(
                FoundationTrade(
                    symbol=position.symbol,
                    entry_time=position.entry_time,
                    exit_time=position.exit_time,
                    net_pnl=net_pnl,
                )
            )

        for window in entries_by_time.get(timestamp, ()):
            equity = _equity_at_mark(row_index, active.values(), timestamp, cash)
            if equity <= 0.0:
                raise ValueError(f"nonpositive_equity_for_entry:{timestamp.isoformat()}:{equity}")
            signed_weight = _signed_weight(window)
            current_gross = sum(abs(position.target_weight) for position in active.values())
            next_gross = current_gross + abs(signed_weight)
            if next_gross > 1.0 + 1e-12:
                raise ValueError(
                    f"portfolio_target_weight_exceeds_one:{timestamp.isoformat()}:{next_gross}"
                )
            entry_price = float(window["entry_price"])
            signed_notional = signed_weight * equity
            signed_units = signed_notional / entry_price
            entry_fee = abs(signed_notional) * per_side_cost_fraction
            cash -= entry_fee
            active[window_keys[id(window)]] = _Position(
                symbol=str(window["symbol"]),
                direction=str(window["direction"]),
                target_weight=signed_weight,
                signed_units=signed_units,
                entry_time=window["entry_time"],
                exit_time=window["exit_time"],
                entry_price=entry_price,
                entry_fee=entry_fee,
                applied_funding_timestamps=set(),
            )

        nav = _equity_at_mark(row_index, active.values(), timestamp, cash)
        period_return = 0.0 if previous_nav is None else (nav / previous_nav) - 1.0
        peak = max(peak, nav)
        drawdown = 0.0 if peak == 0.0 else (nav / peak) - 1.0
        path.append(
            PortfolioPathPoint(
                timestamp=timestamp,
                portfolio_value=nav,
                period_return=period_return,
                drawdown=drawdown,
                concentration=_concentration(active.values()),
            )
        )
        previous_nav = nav
    return path, trades


def _apply_funding(
    row_index: _RowIndex,
    active: Mapping[int, _Position],
    timestamp: datetime,
    cash_ref: dict[str, float],
) -> None:
    for symbol, funding_timestamp, funding_rate in row_index.funding_events_by_apply_time.get(
        timestamp, ()
    ):
        for position in active.values():
            if position.symbol != symbol:
                continue
            if position.applied_funding_timestamps is None:
                position.applied_funding_timestamps = set()
            if funding_timestamp in position.applied_funding_timestamps:
                continue
            if not position.entry_time < funding_timestamp <= position.exit_time:
                continue
            mark = row_index.mark_at(position.symbol, timestamp)
            cashflow = -position.signed_units * mark * funding_rate
            cash_ref["cash"] += cashflow
            position.funding_cashflow += cashflow
            position.applied_funding_timestamps.add(funding_timestamp)


def _subwindow_metrics(
    path: Sequence[PortfolioPathPoint],
    trades: Sequence[FoundationTrade],
    *,
    subwindows: int,
    trial_count: int | None,
    benchmark_sharpe: float,
    data_start: date,
    data_end: date,
) -> list[FoundationSubwindowMetric]:
    if not path:
        return []
    scoring_path = [point for point in path if data_start <= point.timestamp.date() <= data_end]
    if not scoring_path:
        return []
    bounds = _subwindow_bounds(scoring_path, subwindows=subwindows, start=data_start, end=data_end)
    assignments = _assign_subwindows(scoring_path, bounds=bounds)
    accumulators = [
        _SubwindowAccumulator(start_time=start_time, end_time=end_time)
        for start_time, end_time in bounds
    ]
    for path_index, (point, assigned) in enumerate(zip(scoring_path, assignments, strict=True)):
        accumulator = accumulators[assigned]
        accumulator.navs.append(point.portfolio_value)
        accumulator.max_concentration = max(accumulator.max_concentration, point.concentration)
        if path_index > 0:
            accumulator.returns.append(point.period_return)

    for trade in sorted(trades, key=lambda item: item.exit_time):
        bucket = _bucket_for_timestamp(trade.exit_time, bounds)
        if bucket is not None:
            accumulators[bucket].closed_trade_count += 1

    return [
        FoundationSubwindowMetric(
            window_id=f"train_{index + 1}",
            start_time=accumulator.start_time,
            end_time=accumulator.end_time,
            max_drawdown=_local_max_drawdown(accumulator.navs) if accumulator.navs else None,
            closed_trade_count=accumulator.closed_trade_count,
            max_symbol_concentration=accumulator.max_concentration,
            statistics=compute_return_statistics(
                accumulator.returns,
                trial_count=trial_count,
                benchmark_sharpe=benchmark_sharpe,
            ),
        )
        for index, accumulator in enumerate(accumulators)
    ]


@dataclass
class _SubwindowAccumulator:
    start_time: datetime
    end_time: datetime
    returns: list[float] = field(default_factory=list)
    navs: list[float] = field(default_factory=list)
    max_concentration: float = 0.0
    closed_trade_count: int = 0


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


def _assign_subwindows(
    path: Sequence[PortfolioPathPoint],
    *,
    bounds: Sequence[tuple[datetime, datetime]],
) -> list[int]:
    result: list[int] = []
    for point in path:
        for index, (start_time, end_time) in enumerate(bounds):
            if _timestamp_in_window(
                point.timestamp,
                start_time,
                end_time,
                is_last=index == len(bounds) - 1,
            ):
                result.append(index)
                break
        else:
            result.append(0 if point.timestamp < bounds[0][0] else len(bounds) - 1)
    return result


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


def _fill_price(
    row: Mapping[str, Any],
    field: str,
    direction: str,
    *,
    is_entry: bool,
) -> float:
    if field == "quote":
        if direction == "long":
            base = row.get("ask") if is_entry else row.get("bid")
        else:
            base = row.get("bid") if is_entry else row.get("ask")
        return _positive_float(base, "quote_fill_price")
    base = _positive_float(row.get(field), f"fill_price:{field}")
    if direction in {"long", "short"}:
        return base
    raise ValueError(f"unsupported_direction:{direction}")


def _equity_at_mark(
    row_index: _RowIndex,
    positions: Sequence[_Position] | Any,
    timestamp: datetime,
    cash: float,
) -> float:
    equity = cash
    for position in positions:
        mark = row_index.mark_at(position.symbol, timestamp)
        equity += position.signed_units * (mark - position.entry_price)
    return equity


def _concentration(positions: Sequence[_Position] | Any) -> float:
    by_symbol: dict[str, float] = defaultdict(float)
    for position in positions:
        by_symbol[position.symbol] += abs(position.target_weight)
    total = sum(by_symbol.values())
    if total == 0.0:
        return 0.0
    return max(by_symbol.values()) / total


def _signed_weight(window: Mapping[str, Any]) -> float:
    weight = float(window["weight"])
    return -weight if window["direction"] == "short" else weight


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


def _sample_stdev(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
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
