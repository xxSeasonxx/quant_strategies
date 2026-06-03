from __future__ import annotations

import math
import numbers
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from quant_strategies.decisions import StrategyDecision
from quant_strategies.engine.executable import base_unsupported_semantics
from quant_strategies.evaluation.config import EvaluationMetricsConfig
from quant_strategies.evaluation.dependencies import (
    EvaluationDependencyError,
    require_evaluation_dependencies,
    require_pandas_dependency,
)
from quant_strategies.evaluation.metrics import MetricValue, finite_metric_or_none
from quant_strategies.evaluation.scenarios import EvaluationScenario
from quant_strategies.funding import funding_rates_match


EvaluationBackendStatus = Literal["completed", "failed", "unsupported", "unavailable"]
_INITIAL_EQUITY = 100.0
_PROJECT_PERP_FUNDING_MODEL = "project_perp_ledger_v1"


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


@dataclass(frozen=True)
class _ReturnCoverage:
    observed: tuple[float, ...]
    total_count: int
    sample_count: int
    nonfinite_count: int


@dataclass
class _PerpPosition:
    symbol: str
    direction: str
    decision_time: Any
    entry_time: Any
    exit_time: Any
    target_weight: float
    signed_units: float
    entry_fill_price: float
    entry_notional: float
    entry_fee: float
    funding_cashflow: float = 0.0


class PortfolioEvaluationResult(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    scenario_id: str
    backend: str
    status: EvaluationBackendStatus
    metrics: dict[str, MetricValue] = Field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    unsupported_semantics: tuple[str, ...] = ()
    tables: PortfolioTraceTables | None = None


class VectorBTProEvaluationBackend:
    name = "vectorbtpro"

    def name_for_data_kind(self, data_kind: str) -> str:
        if data_kind == "crypto_perp_funding":
            return _PROJECT_PERP_FUNDING_MODEL
        return self.name

    def prepare_inputs(
        self,
        *,
        decisions: list[StrategyDecision],
        rows: Sequence[Mapping[str, Any]],
        data_kind: str = "bars",
    ) -> PreparedPortfolioInputs:
        decision_symbols = tuple(dict.fromkeys(item.instrument.symbol for item in decisions))
        pd = (
            require_pandas_dependency()
            if data_kind == "crypto_perp_funding"
            else require_evaluation_dependencies().pandas
        )
        close = _close_frame(pd, rows, symbols=decision_symbols or None)
        symbol_indexes = _symbol_indexes(close, symbols=decision_symbols or tuple(close.columns))
        decision_positions = _decision_positions(pd, symbol_indexes, decisions)
        return PreparedPortfolioInputs(
            close=close,
            decisions=tuple(decisions),
            symbol_indexes=symbol_indexes,
            decision_positions=decision_positions,
            source_rows=tuple(dict(row) for row in rows),
            data_kind=data_kind,
        )

    def run(
        self,
        *,
        decisions: list[StrategyDecision],
        rows: Sequence[Mapping[str, Any]],
        scenario: EvaluationScenario,
        metrics: EvaluationMetricsConfig,
        data_kind: str = "bars",
    ) -> PortfolioEvaluationResult:
        unsupported = _unsupported_semantics(decisions, scenario)
        if unsupported:
            return PortfolioEvaluationResult(
                scenario_id=scenario.scenario_id,
                backend=self.name,
                status="unsupported",
                unsupported_semantics=unsupported,
            )
        try:
            prepared = self.prepare_inputs(decisions=decisions, rows=rows, data_kind=data_kind)
        except EvaluationDependencyError as exc:
            return PortfolioEvaluationResult(
                scenario_id=scenario.scenario_id,
                backend=self.name,
                status="unavailable",
                warnings=(str(exc),),
            )
        except ValueError as exc:
            return PortfolioEvaluationResult(
                scenario_id=scenario.scenario_id,
                backend=self.name,
                status="failed",
                warnings=(str(exc),),
            )
        return self.run_prepared(prepared=prepared, scenario=scenario, metrics=metrics)

    def run_prepared(
        self,
        *,
        prepared: PreparedPortfolioInputs,
        scenario: EvaluationScenario,
        metrics: EvaluationMetricsConfig,
    ) -> PortfolioEvaluationResult:
        unsupported = _unsupported_semantics(list(prepared.decisions), scenario)
        if unsupported:
            return PortfolioEvaluationResult(
                scenario_id=scenario.scenario_id,
                backend=self.name,
                status="unsupported",
                unsupported_semantics=unsupported,
            )
        if prepared.data_kind == "crypto_perp_funding":
            try:
                pd = require_pandas_dependency()
            except EvaluationDependencyError as exc:
                return PortfolioEvaluationResult(
                    scenario_id=scenario.scenario_id,
                    backend=_PROJECT_PERP_FUNDING_MODEL,
                    status="unavailable",
                    warnings=(str(exc),),
                )
            try:
                windows = _prepared_decision_windows(prepared, scenario)
                return _run_perp_ledger(pd, prepared, scenario, metrics, windows)
            except ValueError as exc:
                return PortfolioEvaluationResult(
                    scenario_id=scenario.scenario_id,
                    backend=_PROJECT_PERP_FUNDING_MODEL,
                    status="failed",
                    warnings=(str(exc),),
                )
            except Exception as exc:
                return PortfolioEvaluationResult(
                    scenario_id=scenario.scenario_id,
                    backend=_PROJECT_PERP_FUNDING_MODEL,
                    status="failed",
                    warnings=(f"project_perp_ledger_failed:{type(exc).__name__}:{exc}",),
                )
        try:
            deps = require_evaluation_dependencies()
        except EvaluationDependencyError as exc:
            return PortfolioEvaluationResult(
                scenario_id=scenario.scenario_id,
                backend=self.name,
                status="unavailable",
                warnings=(str(exc),),
            )
        pd = deps.pandas
        vbt = deps.vectorbtpro
        try:
            windows = _prepared_decision_windows(prepared, scenario)
            portfolio = _run_portfolio(vbt, pd, prepared.close, windows, scenario)
            metric_payload = _portfolio_metrics(portfolio, metrics.annualization_periods_per_year)
            tables = _portfolio_tables(pd, portfolio, scenario.scenario_id, windows)
        except ValueError as exc:
            return PortfolioEvaluationResult(
                scenario_id=scenario.scenario_id,
                backend=self.name,
                status="failed",
                warnings=(str(exc),),
            )
        except Exception as exc:
            return PortfolioEvaluationResult(
                scenario_id=scenario.scenario_id,
                backend=self.name,
                status="failed",
                warnings=(f"vectorbtpro_evaluation_failed:{type(exc).__name__}:{exc}",),
            )
        return PortfolioEvaluationResult(
            scenario_id=scenario.scenario_id,
            backend=self.name,
            status="completed",
            metrics=metric_payload.metrics,
            warnings=metric_payload.warnings,
            tables=tables,
        )


def _unsupported_semantics(decisions: list[StrategyDecision], scenario: EvaluationScenario) -> tuple[str, ...]:
    unsupported: list[str] = []
    for item in decisions:
        unsupported.extend(base_unsupported_semantics(item))
        if item.target.sizing_kind != "target_weight":
            unsupported.append("non_target_weight_sizing")
        if item.target.direction not in {"long", "short"}:
            unsupported.append("unsupported_direction")
        if item.target.size < 0:
            unsupported.append("negative_target_weight")
        if item.target.size > 1.0:
            unsupported.append("leveraged_target_weight")
        if (
            item.exit_policy.stop_loss_bps is not None
            or item.exit_policy.take_profit_bps is not None
            or item.exit_policy.trailing_stop_bps is not None
        ):
            unsupported.append("threshold_exit_policy")
    if scenario.fill_model.price != "close":
        unsupported.append("non_close_fill_price")
    return tuple(dict.fromkeys(unsupported))


def _close_frame(pd: Any, rows: Sequence[Mapping[str, Any]], symbols: Sequence[str] | None = None) -> Any:
    selected_symbols = None if symbols is None else set(symbols)
    symbol_order = tuple(dict.fromkeys(symbols or ()))
    if selected_symbols is not None and not selected_symbols:
        return pd.DataFrame(index=pd.DatetimeIndex([], name="timestamp"))

    records: list[dict[str, Any]] = []
    for row in rows:
        try:
            symbol = str(row["symbol"]).strip()
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid_row:{exc}") from exc
        if not symbol:
            raise ValueError("empty_symbol")
        if selected_symbols is not None and symbol not in selected_symbols:
            continue
        try:
            timestamp = pd.to_datetime(row["timestamp"], utc=True)
            close = float(row["close"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid_row:{exc}") from exc
        if pd.isna(timestamp):
            raise ValueError(f"invalid_timestamp:{row.get('timestamp')}")
        if not math.isfinite(close):
            raise ValueError(f"nonfinite_close:{symbol}:{timestamp.isoformat()}")
        if close <= 0.0:
            raise ValueError(f"nonpositive_close:{symbol}:{timestamp.isoformat()}")
        records.append({"symbol": symbol, "timestamp": timestamp, "close": close})

    if not records and selected_symbols is not None:
        return pd.DataFrame(index=pd.DatetimeIndex([], name="timestamp"))
    if not records:
        raise ValueError("no_rows")

    frame = pd.DataFrame.from_records(records)
    try:
        close = frame.pivot(index="timestamp", columns="symbol", values="close")
    except ValueError as exc:
        raise ValueError(f"duplicate_rows:{exc}") from exc
    close = close.sort_index()
    if symbols is not None:
        ordered_columns = [symbol for symbol in symbol_order if symbol in close.columns]
        close = close.loc[:, ordered_columns]
    return close


def _symbol_indexes(close: Any, *, symbols: Sequence[str]) -> dict[str, Any]:
    indexes: dict[str, Any] = {}
    for symbol in symbols:
        if symbol not in close.columns:
            raise ValueError(f"missing_symbol:{symbol}")
        indexes[symbol] = close.loc[close[symbol].notna(), [symbol]].index
    return indexes


def _decision_positions(
    pd: Any,
    symbol_indexes: Mapping[str, Any],
    decisions: Sequence[StrategyDecision],
) -> tuple[int, ...]:
    positions: list[int] = []
    for item in decisions:
        symbol = item.instrument.symbol
        try:
            symbol_index = symbol_indexes[symbol]
        except KeyError as exc:
            raise ValueError(f"missing_symbol:{symbol}") from exc
        decision_idx = _index_position(pd, symbol_index, item.decision_time)
        if decision_idx is None:
            raise ValueError(f"missing_decision_bar:{symbol}:{item.decision_time.isoformat()}")
        positions.append(decision_idx)
    return tuple(positions)


def _prepared_decision_windows(
    prepared: PreparedPortfolioInputs,
    scenario: EvaluationScenario,
) -> list[dict[str, Any]]:
    entry_lag = _fill_lag(scenario, "entry_lag_bars", default=1)
    exit_lag = _fill_lag(scenario, "exit_lag_bars", default=0)
    windows: list[dict[str, Any]] = []

    for item, decision_idx in zip(prepared.decisions, prepared.decision_positions, strict=True):
        symbol = item.instrument.symbol
        symbol_index = prepared.symbol_indexes[symbol]

        entry_idx = decision_idx + entry_lag
        if entry_idx >= len(symbol_index):
            raise ValueError(f"unfillable_entry:{symbol}:{item.decision_time.isoformat()}")
        entry_time = symbol_index[entry_idx]

        exit_idx = entry_idx + item.exit_policy.max_hold_bars + exit_lag
        if exit_idx >= len(symbol_index):
            raise ValueError(f"unfillable_exit:{symbol}:{item.decision_time.isoformat()}")
        exit_time = symbol_index[exit_idx]

        windows.append(
            {
                "decision": item,
                "symbol": symbol,
                "entry_idx": entry_idx,
                "exit_idx": exit_idx,
                "entry_time": entry_time,
                "exit_time": exit_time,
                "allow_same_symbol_touching": prepared.data_kind == "crypto_perp_funding",
            }
        )

    _validate_max_gross_target_weight(windows)
    _validate_duplicate_signals(windows)
    _validate_overlapping_symbol_windows(windows)
    return windows


def _validate_max_gross_target_weight(windows: list[dict[str, Any]]) -> float:
    max_gross = 0.0
    gross = 0.0
    events: list[tuple[Any, int, float]] = []
    for window in windows:
        weight = abs(float(window["decision"].target.size))
        events.append((window["exit_time"], 0, -weight))
        events.append((window["entry_time"], 1, weight))
    for timestamp, _event_order, delta in sorted(events, key=lambda item: (item[0], item[1])):
        gross += delta
        if gross < 1e-12:
            gross = 0.0
        max_gross = max(max_gross, gross)
        if gross > 1.0 + 1e-12:
            raise ValueError(f"portfolio_target_weight_exceeds_one:{timestamp.isoformat()}:{gross}")
    return max_gross


def _validate_duplicate_signals(windows: list[dict[str, Any]]) -> None:
    entry_signals: set[tuple[str, Any]] = set()
    exit_signals: set[tuple[str, Any]] = set()
    for window in windows:
        symbol = window["symbol"]
        entry_time = window["entry_time"]
        exit_time = window["exit_time"]
        entry_key = (symbol, entry_time)
        if entry_key in entry_signals:
            raise ValueError(f"duplicate_entry_signal:{symbol}:{entry_time.isoformat()}")
        exit_key = (symbol, exit_time)
        if exit_key in exit_signals:
            raise ValueError(f"duplicate_exit_signal:{symbol}:{exit_time.isoformat()}")
        entry_signals.add(entry_key)
        exit_signals.add(exit_key)


def _validate_overlapping_symbol_windows(windows: list[dict[str, Any]]) -> None:
    previous_by_symbol: dict[str, dict[str, Any]] = {}
    sorted_windows = sorted(windows, key=lambda item: (item["symbol"], item["entry_idx"], item["exit_idx"]))
    for window in sorted_windows:
        symbol = window["symbol"]
        previous = previous_by_symbol.get(symbol)
        if previous is None:
            previous_by_symbol[symbol] = window
            continue
        allow_touching = bool(window.get("allow_same_symbol_touching"))
        windows_overlap = (
            window["entry_idx"] < previous["exit_idx"]
            if allow_touching
            else window["entry_idx"] <= previous["exit_idx"]
        )
        if windows_overlap:
            raise ValueError(
                f"overlapping_decision_window:{symbol}:"
                f"{window['entry_time'].isoformat()}:{window['exit_time'].isoformat()}"
            )
        if window["exit_idx"] > previous["exit_idx"]:
            previous_by_symbol[symbol] = window


def _run_portfolio(
    vbt: Any,
    pd: Any,
    close: Any,
    windows: list[dict[str, Any]],
    scenario: EvaluationScenario,
) -> Any:
    decision_symbols = tuple(dict.fromkeys(window["symbol"] for window in windows))
    symbol_columns = list(decision_symbols)
    if len(decision_symbols) == 1:
        symbol = decision_symbols[0]
        if list(close.columns) != symbol_columns:
            close = close.loc[:, symbol_columns]
        if close[symbol].isna().any():
            close = close.loc[close[symbol].notna(), symbol_columns]
    elif decision_symbols:
        if list(close.columns) != symbol_columns:
            close = close.loc[:, symbol_columns]

    long_entries = pd.DataFrame(False, index=close.index, columns=close.columns)
    long_exits = pd.DataFrame(False, index=close.index, columns=close.columns)
    short_entries = pd.DataFrame(False, index=close.index, columns=close.columns)
    short_exits = pd.DataFrame(False, index=close.index, columns=close.columns)
    size = pd.DataFrame(0.0, index=close.index, columns=close.columns)

    for window in windows:
        item = window["decision"]
        symbol = window["symbol"]
        entry_time = window["entry_time"]
        exit_time = window["exit_time"]
        if item.target.direction == "long":
            long_entries.loc[entry_time, symbol] = True
            long_exits.loc[exit_time, symbol] = True
        elif item.target.direction == "short":
            short_entries.loc[entry_time, symbol] = True
            short_exits.loc[exit_time, symbol] = True
        size.loc[entry_time, symbol] = item.target.size

    return vbt.Portfolio.from_signals(
        close,
        long_entries=long_entries,
        long_exits=long_exits,
        short_entries=short_entries,
        short_exits=short_exits,
        fees=_cost_bps_fraction(scenario, "fee_bps_per_side"),
        slippage=_cost_bps_fraction(scenario, "slippage_bps_per_side"),
        size=size,
        size_type="valuepercent",
        cash_sharing=True,
        group_by=True,
        init_cash=100.0,
    )


def _run_perp_ledger(
    pd: Any,
    prepared: PreparedPortfolioInputs,
    scenario: EvaluationScenario,
    metrics_config: EvaluationMetricsConfig,
    windows: list[dict[str, Any]],
) -> PortfolioEvaluationResult:
    funding_events = _funding_events_by_symbol(pd, prepared.close, prepared.source_rows)
    fee_fraction = _cost_bps_fraction(scenario, "fee_bps_per_side")
    slippage_fraction = _cost_bps_fraction(scenario, "slippage_bps_per_side")
    entries_by_time: dict[Any, list[tuple[int, dict[str, Any]]]] = {}
    exits_by_time: dict[Any, list[tuple[int, dict[str, Any]]]] = {}
    for index, window in enumerate(windows):
        entries_by_time.setdefault(window["entry_time"], []).append((index, window))
        exits_by_time.setdefault(window["exit_time"], []).append((index, window))

    cash = _INITIAL_EQUITY
    active: dict[int, _PerpPosition] = {}
    nav_rows: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []
    funding_rows: list[dict[str, Any]] = []
    previous_nav: float | None = None
    peak_nav = _INITIAL_EQUITY

    for timestamp in prepared.close.index:
        for symbol, funding_rate in _funding_events_at(funding_events, timestamp):
            mark_price = _mark_price(prepared.close, symbol, timestamp)
            for position in list(active.values()):
                if position.symbol != symbol:
                    continue
                cashflow = -position.signed_units * mark_price * funding_rate
                cash += cashflow
                position.funding_cashflow += cashflow
                funding_rows.append(
                    {
                        "scenario_id": scenario.scenario_id,
                        "timestamp": timestamp,
                        "asset": symbol,
                        "funding_rate": funding_rate,
                        "position_units": position.signed_units,
                        "mark_price": mark_price,
                        "funding_cashflow": cashflow,
                    }
                )

        for position_key, _window in exits_by_time.get(timestamp, ()):
            position = active.pop(position_key)
            mark_price = _mark_price(prepared.close, position.symbol, timestamp)
            exit_fill_price = _exit_fill_price(mark_price, position.direction, slippage_fraction)
            realized_pnl = position.signed_units * (exit_fill_price - position.entry_fill_price)
            exit_notional = abs(position.signed_units * exit_fill_price)
            exit_fee = exit_notional * fee_fraction
            cash += realized_pnl - exit_fee
            net_pnl = realized_pnl + position.funding_cashflow - position.entry_fee - exit_fee
            trade_rows.append(
                {
                    "scenario_id": scenario.scenario_id,
                    "asset": position.symbol,
                    "direction": position.direction,
                    "decision_time": position.decision_time,
                    "entry_time": position.entry_time,
                    "exit_time": position.exit_time,
                    "target_weight": position.target_weight,
                    "signed_units": position.signed_units,
                    "entry_fill_price": position.entry_fill_price,
                    "exit_fill_price": exit_fill_price,
                    "entry_notional": position.entry_notional,
                    "exit_notional": exit_notional,
                    "entry_fee": position.entry_fee,
                    "exit_fee": exit_fee,
                    "realized_pnl": realized_pnl,
                    "funding_cashflow": position.funding_cashflow,
                    "net_pnl": net_pnl,
                }
            )

        entry_events = entries_by_time.get(timestamp, ())
        if entry_events:
            equity_snapshot = _equity_at_mark(prepared.close, active.values(), timestamp, cash)
            if equity_snapshot <= 0.0:
                raise ValueError(f"nonpositive_equity_for_entry:{timestamp.isoformat()}:{equity_snapshot}")
            for position_key, window in entry_events:
                item = window["decision"]
                symbol = window["symbol"]
                mark_price = _mark_price(prepared.close, symbol, timestamp)
                entry_fill_price = _entry_fill_price(mark_price, item.target.direction, slippage_fraction)
                target_weight = _signed_target_weight(window)
                signed_target_notional = target_weight * equity_snapshot
                signed_units = signed_target_notional / entry_fill_price
                entry_notional = abs(signed_units * entry_fill_price)
                entry_fee = entry_notional * fee_fraction
                cash -= entry_fee
                active[position_key] = _PerpPosition(
                    symbol=symbol,
                    direction=item.target.direction,
                    decision_time=item.decision_time,
                    entry_time=window["entry_time"],
                    exit_time=window["exit_time"],
                    target_weight=target_weight,
                    signed_units=signed_units,
                    entry_fill_price=entry_fill_price,
                    entry_notional=entry_notional,
                    entry_fee=entry_fee,
                )

        nav = _equity_at_mark(prepared.close, active.values(), timestamp, cash)
        period_return = 0.0 if previous_nav is None else (nav / previous_nav) - 1.0
        peak_nav = max(peak_nav, nav)
        drawdown = 0.0 if peak_nav == 0.0 else (nav / peak_nav) - 1.0
        nav_rows.append(
            {
                "scenario_id": scenario.scenario_id,
                "timestamp": timestamp,
                "portfolio_value": nav,
                "period_return": period_return,
                "drawdown": drawdown,
            }
        )
        previous_nav = nav

    if active:
        open_symbols = ",".join(sorted(position.symbol for position in active.values()))
        raise ValueError(f"open_positions_after_ledger:{open_symbols}")

    portfolio_path = pd.DataFrame.from_records(
        nav_rows,
        columns=("scenario_id", "timestamp", "portfolio_value", "period_return", "drawdown"),
    )
    trades = pd.DataFrame.from_records(
        trade_rows,
        columns=(
            "scenario_id",
            "asset",
            "direction",
            "decision_time",
            "entry_time",
            "exit_time",
            "target_weight",
            "signed_units",
            "entry_fill_price",
            "exit_fill_price",
            "entry_notional",
            "exit_notional",
            "entry_fee",
            "exit_fee",
            "realized_pnl",
            "funding_cashflow",
            "net_pnl",
        ),
    )
    funding_cashflows = _funding_cashflows_frame(pd, funding_rows)
    tables = PortfolioTraceTables(
        portfolio_path=portfolio_path,
        trades=trades,
        target_positions=_target_positions_frame(pd, windows, scenario.scenario_id),
        target_exposure_summary=_target_exposure_summary_frame(pd, windows, scenario.scenario_id),
        funding_cashflows=funding_cashflows,
    )
    metric_payload = _perp_ledger_metrics(
        portfolio_path,
        trades,
        annualization_periods_per_year=metrics_config.annualization_periods_per_year,
        funding_cashflow_total=sum(float(row["funding_cashflow"]) for row in funding_rows),
        funding_event_count=len(funding_rows),
    )
    return PortfolioEvaluationResult(
        scenario_id=scenario.scenario_id,
        backend=_PROJECT_PERP_FUNDING_MODEL,
        status="completed",
        metrics=metric_payload.metrics,
        warnings=metric_payload.warnings,
        tables=tables,
    )


def _funding_events_by_symbol(
    pd: Any,
    close: Any,
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, dict[Any, float]]:
    events: dict[str, dict[Any, float]] = {}
    for row in rows:
        if not _is_true_flag(row.get("has_funding_event")):
            continue
        try:
            symbol = str(row["symbol"]).strip()
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid_funding_event:{exc}") from exc
        if not symbol:
            raise ValueError("invalid_funding_event:empty_symbol")
        if symbol not in close.columns:
            continue
        funding_timestamp = _coerce_utc_timestamp(pd, row.get("funding_timestamp"), "funding_timestamp")
        try:
            funding_rate = float(row["funding_rate"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid_funding_rate:{symbol}:{funding_timestamp.isoformat()}") from exc
        if not math.isfinite(funding_rate):
            raise ValueError(f"invalid_funding_rate:{symbol}:{funding_timestamp.isoformat()}")
        try:
            _mark_price(close, symbol, funding_timestamp)
        except ValueError as exc:
            raise ValueError(f"funding_timestamp_not_aligned:{symbol}:{funding_timestamp.isoformat()}") from exc

        symbol_events = events.setdefault(symbol, {})
        existing = symbol_events.get(funding_timestamp)
        if existing is not None and not funding_rates_match(existing, funding_rate):
            raise ValueError(f"conflicting_funding_rates:{symbol}:{funding_timestamp.isoformat()}")
        symbol_events[funding_timestamp] = funding_rate
    return events


def _funding_events_at(events: Mapping[str, Mapping[Any, float]], timestamp: Any) -> list[tuple[str, float]]:
    return [
        (symbol, float(rate))
        for symbol, by_timestamp in events.items()
        for event_timestamp, rate in by_timestamp.items()
        if event_timestamp == timestamp
    ]


def _is_true_flag(value: Any) -> bool:
    return value is True or str(value).strip().lower() == "true"


def _coerce_utc_timestamp(pd: Any, value: Any, field: str) -> Any:
    try:
        timestamp = pd.to_datetime(value, utc=True)
    except Exception as exc:
        raise ValueError(f"invalid_{field}:{value}") from exc
    if pd.isna(timestamp):
        raise ValueError(f"invalid_{field}:{value}")
    return timestamp


def _equity_at_mark(close: Any, positions: Sequence[_PerpPosition], timestamp: Any, cash: float) -> float:
    equity = cash
    for position in positions:
        mark_price = _mark_price(close, position.symbol, timestamp)
        equity += position.signed_units * (mark_price - position.entry_fill_price)
    if not math.isfinite(equity):
        raise ValueError(f"nonfinite_equity:{timestamp.isoformat()}")
    return equity


def _mark_price(close: Any, symbol: str, timestamp: Any) -> float:
    try:
        value = close.loc[timestamp, symbol]
    except Exception as exc:
        raise ValueError(f"missing_mark:{symbol}:{timestamp.isoformat()}") from exc
    metric = finite_metric_or_none(value)
    if metric is None or metric <= 0.0:
        raise ValueError(f"missing_mark:{symbol}:{timestamp.isoformat()}")
    return metric


def _entry_fill_price(mark_price: float, direction: str, slippage_fraction: float) -> float:
    if direction == "long":
        return mark_price * (1.0 + slippage_fraction)
    if direction == "short":
        return mark_price * (1.0 - slippage_fraction)
    raise ValueError(f"unsupported_direction:{direction}")


def _exit_fill_price(mark_price: float, direction: str, slippage_fraction: float) -> float:
    if direction == "long":
        return mark_price * (1.0 - slippage_fraction)
    if direction == "short":
        return mark_price * (1.0 + slippage_fraction)
    raise ValueError(f"unsupported_direction:{direction}")


def _perp_ledger_metrics(
    portfolio_path: Any,
    trades: Any,
    *,
    annualization_periods_per_year: int,
    funding_cashflow_total: float,
    funding_event_count: int,
) -> PortfolioMetricPayload:
    values = portfolio_path["portfolio_value"] if "portfolio_value" in portfolio_path else []
    returns = portfolio_path["period_return"] if "period_return" in portfolio_path else []
    drawdowns = portfolio_path["drawdown"] if "drawdown" in portfolio_path else []
    ending_value = _last_finite(values)
    max_drawdown = min(_series_values(drawdowns)) if _series_values(drawdowns) else None
    if ending_value is None:
        raise ValueError("invalid_required_metric:ending_value")
    if finite_metric_or_none(max_drawdown) is None:
        raise ValueError("invalid_required_metric:max_drawdown")

    trade_pnls = [float(value) for value in _series_values(trades["net_pnl"])] if "net_pnl" in trades else []
    wins = [value for value in trade_pnls if value > 0.0]
    losses = [value for value in trade_pnls if value < 0.0]
    trade_count = len(trade_pnls)
    gross_profit = sum(wins)
    gross_loss = sum(losses)

    total_return = (ending_value / _INITIAL_EQUITY) - 1.0
    payload: dict[str, MetricValue] = {
        "total_return": total_return,
        "ending_value": ending_value,
        "max_drawdown": float(max_drawdown),
        "trade_count": trade_count,
        "win_rate": None if trade_count == 0 else len(wins) / trade_count,
        "profit_factor": None if gross_loss == 0.0 else gross_profit / abs(gross_loss),
        "annualized_return": None,
        "volatility": None,
        "sharpe": None,
        "sortino": None,
        "calmar": None,
        "worst_period_return": None,
        "funding_cashflow_total": funding_cashflow_total,
        "funding_event_count": funding_event_count,
        "funding_model": _PROJECT_PERP_FUNDING_MODEL,
    }
    warnings: list[str] = []
    coverage = _return_coverage(returns)
    payload["return_total_count_excluding_initial"] = coverage.total_count
    payload["return_sample_count"] = coverage.sample_count
    payload["return_nonfinite_count"] = coverage.nonfinite_count
    if coverage.nonfinite_count:
        warnings.append(f"return_coverage_nonfinite:{coverage.nonfinite_count}")

    if coverage.observed and coverage.nonfinite_count == 0:
        observed_returns = list(coverage.observed)
        annualized_return = (
            None
            if total_return <= -1.0
            else ((1.0 + total_return) ** (annualization_periods_per_year / coverage.sample_count)) - 1.0
        )
        mean_return = sum(observed_returns) / len(observed_returns)
        volatility = (
            None
            if len(observed_returns) < 2
            else _sample_stdev(observed_returns) * math.sqrt(annualization_periods_per_year)
        )
        downside_deviation = _downside_deviation(observed_returns, annualization_periods_per_year)
        payload["annualized_return"] = annualized_return
        payload["volatility"] = volatility
        annualized_mean = mean_return * annualization_periods_per_year
        payload["sharpe"] = None if not volatility else annualized_mean / volatility
        payload["sortino"] = None if not downside_deviation else annualized_mean / downside_deviation
        max_dd = finite_metric_or_none(payload["max_drawdown"])
        payload["calmar"] = (
            None if annualized_return is None or max_dd in (None, 0.0) else annualized_return / abs(max_dd)
        )
        payload["worst_period_return"] = min(observed_returns)
    return PortfolioMetricPayload(metrics=payload, warnings=tuple(warnings))


def _portfolio_metrics(portfolio: Any, annualization_periods_per_year: int) -> PortfolioMetricPayload:
    warnings: list[str] = []
    returns, return_warnings = _optional_accessor_value(portfolio, "returns", "returns")
    warnings.extend(return_warnings)
    values = _required_accessor_value(portfolio, "value", "ending_value")
    total_return = _required_accessor_value(portfolio, "get_total_return", "total_return")
    max_drawdown = _required_accessor_value(portfolio, "get_max_drawdown", "max_drawdown")
    trades, trades_warnings = _optional_accessor_value(portfolio, "trades", "trades")
    warnings.extend(trades_warnings)
    trade_count = _required_accessor_value(trades, "count", "trade_count")
    win_rate, win_rate_warnings = _optional_accessor_value(trades, "win_rate", "win_rate")
    warnings.extend(win_rate_warnings)
    profit_factor, profit_factor_warnings = _optional_accessor_value(trades, "profit_factor", "profit_factor")
    warnings.extend(profit_factor_warnings)

    payload: dict[str, MetricValue] = {}
    payload["total_return"] = _required_float_metric("total_return", total_return)
    ending_value = _last_finite(values)
    if ending_value is None:
        raise ValueError("invalid_required_metric:ending_value")
    payload["ending_value"] = ending_value
    payload["max_drawdown"] = _required_float_metric("max_drawdown", max_drawdown)
    payload["trade_count"] = _required_trade_count_metric(trade_count)
    _set_metric(payload, "win_rate", win_rate)
    _set_metric(payload, "profit_factor", profit_factor)
    payload["annualized_return"] = None
    payload["volatility"] = None
    payload["sharpe"] = None
    payload["sortino"] = None
    payload["calmar"] = None
    payload["worst_period_return"] = None

    coverage = _return_coverage(returns)
    payload["return_total_count_excluding_initial"] = coverage.total_count
    payload["return_sample_count"] = coverage.sample_count
    payload["return_nonfinite_count"] = coverage.nonfinite_count
    payload["funding_cashflow_total"] = 0.0
    payload["funding_event_count"] = 0
    payload["funding_model"] = "none"
    if coverage.nonfinite_count:
        warnings.append(f"return_coverage_nonfinite:{coverage.nonfinite_count}")

    if coverage.observed and coverage.nonfinite_count == 0:
        observed_returns = list(coverage.observed)
        total = finite_metric_or_none(payload["total_return"])
        annualized_return = (
            None
            if total is None or total <= -1.0
            else ((1.0 + total) ** (annualization_periods_per_year / coverage.sample_count)) - 1.0
        )
        mean_return = sum(observed_returns) / len(observed_returns)
        volatility = (
            None
            if len(observed_returns) < 2
            else _sample_stdev(observed_returns) * math.sqrt(annualization_periods_per_year)
        )
        downside_deviation = _downside_deviation(observed_returns, annualization_periods_per_year)
        payload["annualized_return"] = annualized_return
        payload["volatility"] = volatility
        annualized_mean = mean_return * annualization_periods_per_year
        payload["sharpe"] = None if not volatility else annualized_mean / volatility
        payload["sortino"] = None if not downside_deviation else annualized_mean / downside_deviation
        max_dd = finite_metric_or_none(payload["max_drawdown"])
        payload["calmar"] = (
            None if annualized_return is None or max_dd in (None, 0.0) else annualized_return / abs(max_dd)
        )
        payload["worst_period_return"] = min(observed_returns)
    return PortfolioMetricPayload(metrics=payload, warnings=tuple(warnings))


def _portfolio_tables(pd: Any, portfolio: Any, scenario_id: str, windows: list[dict[str, Any]]) -> PortfolioTraceTables:
    path = _frame_from_series(pd, _attribute_value_or_none(portfolio, "value"), "portfolio_value")
    returns = _frame_from_series(pd, _attribute_value_or_none(portfolio, "returns"), "period_return")
    drawdown = _frame_from_series(pd, _drawdown_series_or_none(portfolio), "drawdown")
    portfolio_path = path.join(returns, how="outer").join(drawdown, how="outer").reset_index()
    portfolio_path.insert(0, "scenario_id", scenario_id)
    trades = _records_frame(pd, getattr(getattr(portfolio, "trades", None), "records_readable", None), scenario_id)
    target_positions = _target_positions_frame(pd, windows, scenario_id)
    target_exposure_summary = _target_exposure_summary_frame(pd, windows, scenario_id)
    return PortfolioTraceTables(
        portfolio_path=portfolio_path,
        trades=trades,
        target_positions=target_positions,
        target_exposure_summary=target_exposure_summary,
        funding_cashflows=_funding_cashflows_frame(pd, ()),
    )


def _funding_cashflows_frame(pd: Any, rows: Sequence[Mapping[str, Any]]) -> Any:
    return pd.DataFrame.from_records(
        rows,
        columns=(
            "scenario_id",
            "timestamp",
            "asset",
            "funding_rate",
            "position_units",
            "mark_price",
            "funding_cashflow",
        ),
    )


def _target_positions_frame(pd: Any, windows: list[dict[str, Any]], scenario_id: str) -> Any:
    if not windows:
        return pd.DataFrame(
            {
                "scenario_id": [],
                "timestamp": [],
                "asset": [],
                "target_weight": [],
                "event": [],
                "decision_time": [],
                "direction": [],
            }
        )
    return pd.DataFrame(
        [
            record
            for window in windows
            for record in (
                {
                    "scenario_id": scenario_id,
                    "timestamp": window["entry_time"],
                    "asset": window["symbol"],
                    "target_weight": _signed_target_weight(window),
                    "event": "entry",
                    "decision_time": window["decision"].decision_time,
                    "direction": window["decision"].target.direction,
                },
                {
                    "scenario_id": scenario_id,
                    "timestamp": window["exit_time"],
                    "asset": window["symbol"],
                    "target_weight": 0.0,
                    "event": "exit",
                    "decision_time": window["decision"].decision_time,
                    "direction": window["decision"].target.direction,
                },
            )
        ]
    )


def _target_exposure_summary_frame(pd: Any, windows: list[dict[str, Any]], scenario_id: str) -> Any:
    if not windows:
        return pd.DataFrame(
            {
                "scenario_id": [],
                "asset": [],
                "decision_count": [],
                "target_round_trip_turnover": [],
            }
        )
    by_asset: dict[str, dict[str, float | int | str]] = {}
    for window in windows:
        asset = window["symbol"]
        metrics = by_asset.setdefault(
            asset,
            {
                "scenario_id": scenario_id,
                "asset": asset,
                "decision_count": 0,
                "target_round_trip_turnover": 0.0,
            },
        )
        metrics["decision_count"] = int(metrics["decision_count"]) + 1
        metrics["target_round_trip_turnover"] = float(metrics["target_round_trip_turnover"]) + (
            2.0 * abs(float(window["decision"].target.size))
        )
    return pd.DataFrame(list(by_asset.values()))


def _signed_target_weight(window: Mapping[str, Any]) -> float:
    weight = float(window["decision"].target.size)
    return -weight if window["decision"].target.direction == "short" else weight


def _index_position(pd: Any, index: Any, value: Any) -> int | None:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    position = index.get_indexer([timestamp])[0]
    if position == -1:
        return None
    return int(position)


def _fill_lag(scenario: EvaluationScenario, field: str, *, default: int) -> int:
    value = getattr(scenario.fill_model, field, default)
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise ValueError(f"invalid_fill_lag:{field}:{value}")
    float_value = float(value)
    if not math.isfinite(float_value) or not float_value.is_integer() or float_value < 0.0:
        raise ValueError(f"invalid_fill_lag:{field}:{value}")
    return int(float_value)


def _cost_bps_fraction(scenario: EvaluationScenario, field: str) -> float:
    value = getattr(scenario.cost_model, field, 0.0)
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise ValueError(f"invalid_cost_bps:{field}:{value}")
    float_value = float(value)
    if not math.isfinite(float_value) or float_value < 0.0:
        raise ValueError(f"invalid_cost_bps:{field}:{value}")
    return float_value / 10_000.0


def _attribute_value_or_none(owner: Any, name: str) -> Any | None:
    try:
        value = getattr(owner, name)
    except Exception:
        return None
    try:
        return value() if callable(value) else value
    except Exception:
        return None


def _required_accessor_value(owner: Any, name: str, metric_name: str) -> Any:
    if owner is None:
        raise ValueError(f"metric_extraction_failed:{metric_name}:owner_unavailable")
    try:
        value = getattr(owner, name)
    except Exception as exc:
        raise ValueError(f"metric_extraction_failed:{metric_name}:{exc}") from exc
    try:
        return value() if callable(value) else value
    except Exception as exc:
        raise ValueError(f"metric_extraction_failed:{metric_name}:{exc}") from exc


def _optional_accessor_value(owner: Any, name: str, metric_name: str) -> tuple[Any | None, tuple[str, ...]]:
    if owner is None:
        return None, (f"metric_extraction_unavailable:{metric_name}:owner_unavailable",)
    try:
        value = getattr(owner, name)
    except Exception as exc:
        return None, (f"metric_extraction_unavailable:{metric_name}:{exc}",)
    try:
        return (value() if callable(value) else value), ()
    except Exception as exc:
        return None, (f"metric_extraction_unavailable:{metric_name}:{exc}",)


def _required_float_metric(name: str, value: Any) -> float:
    metric = finite_metric_or_none(value)
    if metric is None:
        raise ValueError(f"invalid_required_metric:{name}")
    return metric


def _required_trade_count_metric(value: Any) -> int:
    metric = finite_metric_or_none(value)
    if metric is None or not metric.is_integer() or metric < 0.0:
        raise ValueError("invalid_required_metric:trade_count")
    return int(metric)


def _drawdown_series_or_none(portfolio: Any) -> Any | None:
    drawdown = _attribute_value_or_none(portfolio, "drawdown")
    if _is_series_like(drawdown):
        return drawdown

    drawdowns = _attribute_value_or_none(portfolio, "drawdowns")
    if _is_series_like(drawdowns):
        return drawdowns

    for name in ("drawdown", "drawdowns"):
        drawdown = _attribute_value_or_none(drawdowns, name)
        if _is_series_like(drawdown):
            return drawdown

    records = _attribute_value_or_none(drawdowns, "records_readable")
    if hasattr(records, "columns"):
        for column in records.columns:
            if str(column).lower().replace(" ", "_") == "drawdown":
                return records[column]
    return None


def _is_series_like(values: Any | None) -> bool:
    if values is None:
        return False
    if hasattr(values, "columns"):
        return True
    return any(hasattr(values, name) for name in ("to_frame", "tolist", "to_numpy", "_values"))


def _set_metric(payload: dict[str, MetricValue], name: str, value: Any) -> None:
    metric = finite_metric_or_none(value)
    if metric is None:
        payload[name] = None
        return
    if name == "trade_count" and metric.is_integer():
        payload[name] = int(metric)
        return
    payload[name] = metric


def _observed_returns(returns: Any | None) -> list[float]:
    return list(_return_coverage(returns).observed)


def _return_coverage(returns: Any | None) -> _ReturnCoverage:
    values = _series_values(returns)
    sampled_values = values[1:]
    observed = tuple(
        float(metric)
        for value in sampled_values
        if (metric := finite_metric_or_none(value)) is not None
    )
    return _ReturnCoverage(
        observed=observed,
        total_count=len(sampled_values),
        sample_count=len(observed),
        nonfinite_count=len(sampled_values) - len(observed),
    )


def _last_finite(values: Sequence[Any] | None) -> float | None:
    finite = [finite_metric_or_none(value) for value in _series_values(values)]
    finite = [value for value in finite if value is not None]
    return finite[-1] if finite else None


def _series_values(values: Any | None) -> list[Any]:
    if values is None:
        return []
    if hasattr(values, "tolist"):
        return list(values.tolist())
    if hasattr(values, "to_numpy"):
        raw_values = values.to_numpy()
        if hasattr(raw_values, "ravel"):
            return list(raw_values.ravel())
        return list(raw_values)
    if hasattr(values, "_values"):
        return list(values._values)
    try:
        return list(values)
    except TypeError:
        return []


def _sample_stdev(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance)


def _downside_deviation(values: Sequence[float], annualization_periods_per_year: int) -> float | None:
    downside_returns = [value for value in values if value < 0.0]
    if not downside_returns:
        return None
    periodic_deviation = math.sqrt(sum(value**2 for value in downside_returns) / len(values))
    annualized_deviation = periodic_deviation * math.sqrt(annualization_periods_per_year)
    return annualized_deviation if annualized_deviation > 0.0 else None


def _frame_from_series(pd: Any, values: Any, name: str) -> Any:
    if hasattr(values, "columns"):
        frame = values.copy()
    elif hasattr(values, "to_frame"):
        frame = values.to_frame(name)
    else:
        frame = pd.DataFrame({name: _series_values(values)})
    if name not in frame.columns and len(frame.columns) == 1:
        frame = frame.rename(columns={frame.columns[0]: name})
    return frame


def _records_frame(pd: Any, records: Any, scenario_id: str) -> Any:
    if callable(records):
        records = records()
    if records is None:
        return pd.DataFrame({"scenario_id": []})
    if hasattr(records, "copy"):
        frame = records.copy()
    else:
        frame = pd.DataFrame.from_records(records)
    if "scenario_id" not in frame.columns:
        frame.insert(0, "scenario_id", scenario_id)
    else:
        frame["scenario_id"] = scenario_id
    return frame
