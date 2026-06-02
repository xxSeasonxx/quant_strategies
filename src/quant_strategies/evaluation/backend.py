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
from quant_strategies.evaluation.dependencies import EvaluationDependencyError, require_evaluation_dependencies
from quant_strategies.evaluation.metrics import MetricValue, finite_metric_or_none
from quant_strategies.evaluation.scenarios import EvaluationScenario


EvaluationBackendStatus = Literal["completed", "failed", "unsupported", "unavailable"]


@dataclass(frozen=True)
class PortfolioTraceTables:
    portfolio_path: Any
    trades: Any
    positions: Any
    per_asset_metrics: Any


@dataclass(frozen=True)
class PreparedPortfolioInputs:
    close: Any
    decisions: tuple[StrategyDecision, ...]


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

    def prepare_inputs(
        self,
        *,
        decisions: list[StrategyDecision],
        rows: Sequence[Mapping[str, Any]],
    ) -> PreparedPortfolioInputs:
        decision_symbols = tuple(dict.fromkeys(item.instrument.symbol for item in decisions))
        if not decision_symbols:
            raise ValueError("no_decisions")
        deps = require_evaluation_dependencies()
        close = _close_frame(deps.pandas, rows, symbols=decision_symbols)
        return PreparedPortfolioInputs(close=close, decisions=tuple(decisions))

    def run(
        self,
        *,
        decisions: list[StrategyDecision],
        rows: Sequence[Mapping[str, Any]],
        scenario: EvaluationScenario,
        metrics: EvaluationMetricsConfig,
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
            prepared = self.prepare_inputs(decisions=decisions, rows=rows)
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
            windows = _decision_windows(pd, prepared.close, list(prepared.decisions), scenario)
            portfolio = _run_portfolio(vbt, pd, prepared.close, windows, scenario)
            metric_payload = _portfolio_metrics(portfolio, metrics.annualization_periods_per_year)
            tables = _portfolio_tables(pd, portfolio, scenario.scenario_id)
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
            metrics=metric_payload,
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

    if not records:
        raise ValueError("no_rows")

    frame = pd.DataFrame.from_records(records)
    try:
        close = frame.pivot(index="timestamp", columns="symbol", values="close")
    except ValueError as exc:
        raise ValueError(f"duplicate_rows:{exc}") from exc
    return close.sort_index()


def _decision_windows(
    pd: Any,
    close: Any,
    decisions: list[StrategyDecision],
    scenario: EvaluationScenario,
) -> list[dict[str, Any]]:
    entry_lag = _fill_lag(scenario, "entry_lag_bars", default=1)
    exit_lag = _fill_lag(scenario, "exit_lag_bars", default=0)
    windows: list[dict[str, Any]] = []

    for item in decisions:
        symbol = item.instrument.symbol
        if symbol not in close.columns:
            raise ValueError(f"missing_symbol:{symbol}")

        symbol_close = close.loc[close[symbol].notna(), [symbol]]
        decision_idx = _index_position(pd, symbol_close.index, item.decision_time)
        if decision_idx is None:
            raise ValueError(f"missing_decision_bar:{symbol}:{item.decision_time.isoformat()}")

        entry_idx = decision_idx + entry_lag
        if entry_idx >= len(symbol_close.index):
            raise ValueError(f"unfillable_entry:{symbol}:{item.decision_time.isoformat()}")
        entry_time = symbol_close.index[entry_idx]

        exit_idx = entry_idx + item.exit_policy.max_hold_bars + exit_lag
        if exit_idx >= len(symbol_close.index):
            raise ValueError(f"unfillable_exit:{symbol}:{item.decision_time.isoformat()}")
        exit_time = symbol_close.index[exit_idx]

        windows.append(
            {
                "decision": item,
                "symbol": symbol,
                "entry_idx": entry_idx,
                "exit_idx": exit_idx,
                "entry_time": entry_time,
                "exit_time": exit_time,
            }
        )

    _validate_max_gross_target_weight(windows)
    _validate_duplicate_signals(windows)
    _validate_overlapping_symbol_windows(windows)
    return windows


def _validate_max_gross_target_weight(windows: list[dict[str, Any]]) -> float:
    max_gross = 0.0
    for current in windows:
        timestamp = current["entry_time"]
        gross = 0.0
        for window in windows:
            if window["entry_time"] <= timestamp <= window["exit_time"]:
                gross += abs(float(window["decision"].target.size))
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
    active: dict[str, list[dict[str, Any]]] = {}
    for window in windows:
        symbol = window["symbol"]
        for existing in active.get(symbol, []):
            if window["entry_idx"] <= existing["exit_idx"] and window["exit_idx"] >= existing["entry_idx"]:
                raise ValueError(
                    f"overlapping_decision_window:{symbol}:"
                    f"{window['entry_time'].isoformat()}:{window['exit_time'].isoformat()}"
                )
        active.setdefault(symbol, []).append(window)


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


def _portfolio_metrics(portfolio: Any, annualization_periods_per_year: int) -> dict[str, MetricValue]:
    returns = _series_or_none(portfolio, "returns")
    values = _series_or_none(portfolio, "value")
    total_return = _call_metric(portfolio, "get_total_return")
    max_drawdown = _call_metric(portfolio, "get_max_drawdown")
    trades = _trades_or_none(portfolio)
    trade_count = _call_metric(trades, "count") if trades is not None else None
    win_rate = _call_metric(trades, "win_rate") if trades is not None else None
    profit_factor = _call_metric(trades, "profit_factor") if trades is not None else None

    payload: dict[str, MetricValue] = {}
    _set_metric(payload, "total_return", total_return)
    _set_metric(payload, "ending_value", _last_finite(values))
    _set_metric(payload, "max_drawdown", max_drawdown)
    _set_metric(payload, "trade_count", trade_count)
    _set_metric(payload, "win_rate", win_rate)
    _set_metric(payload, "profit_factor", profit_factor)
    payload["annualized_return"] = None
    payload["volatility"] = None
    payload["sharpe"] = None
    payload["sortino"] = None
    payload["calmar"] = None

    observed_returns = _observed_returns(returns)
    if observed_returns:
        total = finite_metric_or_none(total_return)
        annualized_return = (
            None
            if total is None or total <= -1.0
            else ((1.0 + total) ** (annualization_periods_per_year / len(observed_returns))) - 1.0
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
        max_dd = finite_metric_or_none(max_drawdown)
        payload["calmar"] = (
            None if annualized_return is None or max_dd in (None, 0.0) else annualized_return / abs(max_dd)
        )
        payload["worst_period_return"] = min(observed_returns)
    return payload


def _portfolio_tables(pd: Any, portfolio: Any, scenario_id: str) -> PortfolioTraceTables:
    path = _frame_from_series(pd, _series_or_none(portfolio, "value"), "portfolio_value")
    returns = _frame_from_series(pd, _series_or_none(portfolio, "returns"), "period_return")
    drawdown = _frame_from_series(pd, _drawdown_series_or_none(portfolio), "drawdown")
    portfolio_path = path.join(returns, how="outer").join(drawdown, how="outer").reset_index()
    portfolio_path.insert(0, "scenario_id", scenario_id)
    trades = _records_frame(pd, getattr(getattr(portfolio, "trades", None), "records_readable", None), scenario_id)
    positions = pd.DataFrame({"scenario_id": []})
    per_asset_metrics = pd.DataFrame({"scenario_id": []})
    return PortfolioTraceTables(
        portfolio_path=portfolio_path,
        trades=trades,
        positions=positions,
        per_asset_metrics=per_asset_metrics,
    )


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


def _series_or_none(owner: Any, name: str) -> Any | None:
    try:
        value = getattr(owner, name)
    except Exception:
        return None
    try:
        return value() if callable(value) else value
    except Exception:
        return None


def _call_metric(owner: Any, name: str) -> Any | None:
    try:
        value = getattr(owner, name)
    except Exception:
        return None
    try:
        return value() if callable(value) else value
    except Exception:
        return None


def _trades_or_none(portfolio: Any) -> Any | None:
    try:
        return getattr(portfolio, "trades")
    except Exception:
        return None


def _drawdown_series_or_none(portfolio: Any) -> Any | None:
    drawdown = _series_or_none(portfolio, "drawdown")
    if _is_series_like(drawdown):
        return drawdown

    drawdowns = _series_or_none(portfolio, "drawdowns")
    if _is_series_like(drawdowns):
        return drawdowns

    for name in ("drawdown", "drawdowns"):
        drawdown = _series_or_none(drawdowns, name)
        if _is_series_like(drawdown):
            return drawdown

    records = _series_or_none(drawdowns, "records_readable")
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
    values = _series_values(returns)
    return [float(value) for value in values[1:] if finite_metric_or_none(value) is not None]


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
