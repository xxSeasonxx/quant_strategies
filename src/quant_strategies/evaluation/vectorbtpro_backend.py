from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from quant_strategies.decisions import StrategyDecision
from quant_strategies.engine.executable import base_unsupported_semantics
from quant_strategies.evaluation._portfolio_common import (
    cost_bps_fraction as _cost_bps_fraction,
    downside_deviation as _downside_deviation,
    funding_cashflows_frame as _funding_cashflows_frame,
    index_position as _index_position,
    prepared_decision_windows as _prepared_decision_windows,
    required_final_metric as _required_final_metric,
    return_coverage as _return_coverage,
    sample_stdev as _sample_stdev,
    series_values as _series_values,
    target_exposure_summary_frame as _target_exposure_summary_frame,
    target_positions_frame as _target_positions_frame,
)
from quant_strategies.evaluation.config import EvaluationMetricsConfig
from quant_strategies.evaluation.dependencies import (
    EvaluationDependencyError,
    require_evaluation_dependencies,
    require_pandas_dependency,
)
from quant_strategies.evaluation.metrics import MetricValue, finite_metric_or_none
from quant_strategies.evaluation.results import (
    PortfolioEvaluationResult,
    PortfolioMetricPayload,
    PortfolioTraceTables,
    PreparedPortfolioInputs,
)
from quant_strategies.evaluation.project_perp_ledger import (
    PROJECT_PERP_FUNDING_MODEL as _PROJECT_PERP_FUNDING_MODEL,
    run_perp_ledger as _run_perp_ledger,
)
from quant_strategies.evaluation.scenarios import EvaluationScenario


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
        backend_name = self.name_for_data_kind(data_kind)
        unsupported = _unsupported_semantics(decisions, scenario)
        if unsupported:
            return PortfolioEvaluationResult(
                scenario_id=scenario.scenario_id,
                backend=backend_name,
                status="unsupported",
                unsupported_semantics=unsupported,
            )
        try:
            prepared = self.prepare_inputs(decisions=decisions, rows=rows, data_kind=data_kind)
        except EvaluationDependencyError as exc:
            return PortfolioEvaluationResult(
                scenario_id=scenario.scenario_id,
                backend=backend_name,
                status="unavailable",
                warnings=(str(exc),),
            )
        except ValueError as exc:
            return PortfolioEvaluationResult(
                scenario_id=scenario.scenario_id,
                backend=backend_name,
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
        backend_name = self.name_for_data_kind(prepared.data_kind)
        unsupported = _unsupported_semantics(list(prepared.decisions), scenario)
        if unsupported:
            return PortfolioEvaluationResult(
                scenario_id=scenario.scenario_id,
                backend=backend_name,
                status="unsupported",
                unsupported_semantics=unsupported,
            )
        if prepared.data_kind == "crypto_perp_funding":
            try:
                pd = require_pandas_dependency()
            except EvaluationDependencyError as exc:
                return PortfolioEvaluationResult(
                    scenario_id=scenario.scenario_id,
                    backend=backend_name,
                    status="unavailable",
                    warnings=(str(exc),),
                )
            try:
                windows = _prepared_decision_windows(prepared, scenario)
                return _run_perp_ledger(pd, prepared, scenario, metrics, windows)
            except ValueError as exc:
                return PortfolioEvaluationResult(
                    scenario_id=scenario.scenario_id,
                    backend=backend_name,
                    status="failed",
                    warnings=(str(exc),),
                )
            except Exception as exc:
                return PortfolioEvaluationResult(
                    scenario_id=scenario.scenario_id,
                    backend=backend_name,
                    status="failed",
                    warnings=(f"project_perp_ledger_failed:{type(exc).__name__}:{exc}",),
                )
        try:
            deps = require_evaluation_dependencies()
        except EvaluationDependencyError as exc:
            return PortfolioEvaluationResult(
                scenario_id=scenario.scenario_id,
                backend=backend_name,
                status="unavailable",
                warnings=(str(exc),),
            )
        pd = deps.pandas
        vbt = deps.vectorbtpro
        try:
            windows = _prepared_decision_windows(prepared, scenario)
            portfolio = _run_portfolio(vbt, pd, prepared.close, windows, scenario)
            metric_payload = _portfolio_metrics(
                portfolio,
                metrics.annualization_periods_per_year,
                min_annualized_samples=metrics.min_annualized_samples,
            )
            tables = _portfolio_tables(pd, portfolio, scenario.scenario_id, windows)
        except ValueError as exc:
            return PortfolioEvaluationResult(
                scenario_id=scenario.scenario_id,
                backend=backend_name,
                status="failed",
                warnings=(str(exc),),
            )
        except Exception as exc:
            return PortfolioEvaluationResult(
                scenario_id=scenario.scenario_id,
                backend=backend_name,
                status="failed",
                warnings=(f"vectorbtpro_evaluation_failed:{type(exc).__name__}:{exc}",),
            )
        return PortfolioEvaluationResult(
            scenario_id=scenario.scenario_id,
            backend=backend_name,
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


def _portfolio_metrics(
    portfolio: Any,
    annualization_periods_per_year: int,
    *,
    min_annualized_samples: int = 20,
) -> PortfolioMetricPayload:
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
    payload["ending_value"] = _required_final_metric("ending_value", values)
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
    if coverage.sample_count < min_annualized_samples:
        warnings.append(
            f"annualized_metrics_insufficient_samples:{coverage.sample_count}:"
            f"min_required={min_annualized_samples}"
        )

    if coverage.observed and coverage.nonfinite_count == 0:
        observed_returns = list(coverage.observed)
        payload["worst_period_return"] = min(observed_returns)
        if coverage.sample_count >= min_annualized_samples:
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
