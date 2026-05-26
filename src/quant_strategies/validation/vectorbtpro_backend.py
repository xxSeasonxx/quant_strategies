from __future__ import annotations

from collections.abc import Mapping
import math
import numbers
from typing import Any

from quant_strategies.decisions import StrategyDecision
from quant_strategies.validation.backends import BackendRunResult
from quant_strategies.validation.funding import (
    FundingEventError,
    funding_return_for_window,
    has_funding_cashflow_rows,
)


class VectorBTProBackend:
    name = "vectorbtpro"

    def run(
        self,
        *,
        decisions: list[StrategyDecision],
        rows: list[dict[str, Any]],
        config: Any,
    ) -> BackendRunResult:
        try:
            import pandas as pd
        except ImportError as exc:
            return BackendRunResult(
                backend=self.name,
                status="unavailable",
                metrics={},
                warnings=(f"pandas import failed: {exc}",),
                unsupported_semantics=(),
            )

        try:
            close = _close_frame(pd, rows)
            windows = _validate_decision_windows(pd, close, decisions, config)
            fees = _cost_bps_fraction(config, "fee_bps_per_side")
            slippage = _cost_bps_fraction(config, "slippage_bps_per_side")
        except ValueError as exc:
            return _failed(self.name, str(exc))

        unsupported = _unsupported_semantics(decisions, rows, config)
        if unsupported:
            return BackendRunResult(
                backend=self.name,
                status="unsupported",
                metrics={},
                warnings=(),
                unsupported_semantics=unsupported,
            )

        try:
            import vectorbtpro as vbt
        except ImportError as exc:
            return BackendRunResult(
                backend=self.name,
                status="unavailable",
                metrics={},
                warnings=(f"vectorbtpro import failed: {exc}",),
                unsupported_semantics=(),
            )

        decision_symbols = tuple(dict.fromkeys(item.instrument.symbol for item in decisions))
        if len(decision_symbols) == 1:
            symbol = decision_symbols[0]
            close = close.loc[close[symbol].notna(), [symbol]]
        elif decision_symbols:
            close = close.loc[:, list(decision_symbols)]

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

        try:
            portfolio = vbt.Portfolio.from_signals(
                close,
                long_entries=long_entries,
                long_exits=long_exits,
                short_entries=short_entries,
                short_exits=short_exits,
                fees=fees,
                slippage=slippage,
                size=size,
                size_type="valuepercent",
            )
        except Exception as exc:
            return _failed(self.name, f"vectorbtpro_run_failed:{exc}")

        try:
            metrics = _portfolio_metrics(portfolio)
        except ValueError as exc:
            return _failed(self.name, f"invalid_metrics:{exc}")
        except Exception as exc:
            return _failed(self.name, f"metric_extraction_failed:{exc}")
        if metrics["trade_count"] != len(windows):
            return _failed(self.name, f"unexpected_trade_count:{metrics['trade_count']}:{len(windows)}")
        try:
            metrics = _funding_adjusted_metrics(metrics, rows, windows, config)
        except FundingEventError as exc:
            return _failed(self.name, f"invalid_funding_events:{exc}")

        return BackendRunResult(
            backend=self.name,
            status="completed",
            metrics=metrics,
            warnings=(),
            unsupported_semantics=(),
        )


def _unsupported_semantics(
    decisions: list[StrategyDecision],
    rows: list[dict[str, Any]],
    config: Any,
) -> tuple[str, ...]:
    unsupported: list[str] = []
    if _config_value(config, "fill_model", "price", default="close") != "close":
        unsupported.append("non_close_fill_price")
    for item in decisions:
        exit_policy = item.exit_policy
        if (
            exit_policy.stop_loss_bps is not None
            or exit_policy.take_profit_bps is not None
            or exit_policy.trailing_stop_bps is not None
        ):
            unsupported.append("threshold_exit_policy")
        if item.target.sizing_kind != "target_weight":
            unsupported.append("non_target_weight_sizing")
        elif item.target.size > 1.0:
            unsupported.append("leveraged_target_weight")
        if item.target.direction == "flat":
            unsupported.append("flat_target")
    target_weight_symbols = {
        item.instrument.symbol
        for item in decisions
        if item.target.sizing_kind == "target_weight" and item.target.direction != "flat"
    }
    if len(target_weight_symbols) > 1:
        unsupported.append("multi_asset_target_weight")
    return tuple(dict.fromkeys(unsupported))


def _validate_decision_windows(pd: Any, close: Any, decisions: list[StrategyDecision], config: Any) -> list[dict[str, Any]]:
    entry_lag = _entry_lag(config)
    exit_lag = _exit_lag(config)
    entry_signals: set[tuple[str, Any]] = set()
    exit_signals: set[tuple[str, Any]] = set()
    active_windows: dict[str, list[tuple[int, int]]] = {}
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
        entry_key = (symbol, entry_time)
        if entry_key in entry_signals:
            raise ValueError(f"duplicate_entry_signal:{symbol}:{entry_time.isoformat()}")

        exit_idx = entry_idx + item.exit_policy.max_hold_bars + exit_lag
        if exit_idx >= len(symbol_close.index):
            raise ValueError(f"unfillable_exit:{symbol}:{item.decision_time.isoformat()}")

        exit_time = symbol_close.index[exit_idx]
        exit_key = (symbol, exit_time)
        if exit_key in exit_signals:
            raise ValueError(f"duplicate_exit_signal:{symbol}:{exit_time.isoformat()}")

        for existing_entry_idx, existing_exit_idx in active_windows.get(symbol, []):
            if entry_idx <= existing_exit_idx and exit_idx >= existing_entry_idx:
                raise ValueError(
                    f"overlapping_decision_window:{symbol}:{entry_time.isoformat()}:{exit_time.isoformat()}"
                )

        entry_signals.add(entry_key)
        exit_signals.add(exit_key)
        active_windows.setdefault(symbol, []).append((entry_idx, exit_idx))
        windows.append(
            {
                "decision": item,
                "symbol": symbol,
                "entry_time": entry_time,
                "exit_time": exit_time,
            }
        )

    return windows


def _close_frame(pd: Any, rows: list[dict[str, Any]]) -> Any:
    records: list[dict[str, Any]] = []
    for row in rows:
        try:
            symbol = str(row["symbol"]).strip()
            timestamp = pd.to_datetime(row["timestamp"], utc=True)
            close = float(row["close"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid_row:{exc}") from exc
        if not symbol:
            raise ValueError("empty_symbol")
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


def _entry_lag(config: Any) -> int:
    return _fill_lag(config, "entry_lag_bars", default=1)


def _exit_lag(config: Any) -> int:
    return _fill_lag(config, "exit_lag_bars", default=0)


def _config_value(config: Any, section: str, field: str, *, default: Any) -> Any:
    if isinstance(config, Mapping):
        section_value = config.get(section)
    else:
        section_value = getattr(config, section, None)
    if section_value is None:
        return default
    if isinstance(section_value, Mapping):
        return section_value.get(field, default)
    return getattr(section_value, field, default)


def _fill_lag(config: Any, field: str, *, default: int) -> int:
    value = _config_value(config, "fill_model", field, default=default)
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise ValueError(f"invalid_fill_lag:{field}:{value}")
    float_value = float(value)
    if not math.isfinite(float_value) or not float_value.is_integer() or float_value < 0.0:
        raise ValueError(f"invalid_fill_lag:{field}:{value}")
    return int(float_value)


def _cost_bps_fraction(config: Any, field: str) -> float:
    value = _config_value(config, "cost_model", field, default=0.0)
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise ValueError(f"invalid_cost_bps:{field}:{value}")
    float_value = float(value)
    if not math.isfinite(float_value) or float_value < 0.0:
        raise ValueError(f"invalid_cost_bps:{field}:{value}")
    return float_value / 10_000.0


def _portfolio_metrics(portfolio: Any) -> dict[str, float | int]:
    net_return = _float_metric(portfolio.get_total_return())
    if not math.isfinite(net_return):
        raise ValueError(f"nonfinite_net_return:{net_return}")

    trade_count = _int_metric(portfolio.trades.count())
    if trade_count < 0:
        raise ValueError(f"invalid_trade_count:{trade_count}")

    return {"net_return": net_return, "trade_count": trade_count}


def _funding_adjusted_metrics(
    metrics: dict[str, float | int],
    rows: list[dict[str, Any]],
    windows: list[dict[str, Any]],
    config: Any,
) -> dict[str, float | int | str]:
    data_kind = _config_value(config, "data", "kind", default=None)
    if data_kind != "crypto_perp_funding" and not has_funding_cashflow_rows(rows):
        return metrics

    funding_return = 0.0
    for window in windows:
        decision = window["decision"]
        if decision.target.direction == "flat":
            continue
        funding_return += funding_return_for_window(
            rows,
            symbol=window["symbol"],
            entry_time=window["entry_time"],
            exit_time=window["exit_time"],
            direction=decision.target.direction,
            weight=decision.target.size,
        )

    price_cost_return = float(metrics["net_return"])
    return {
        **metrics,
        "price_cost_return": price_cost_return,
        "funding_return": funding_return,
        "funding_model": "linear_additive_adjustment",
        "net_return": price_cost_return + funding_return,
    }


def _float_metric(value: Any) -> float:
    if hasattr(value, "mean"):
        return float(value.mean())
    return float(value)


def _int_metric(value: Any) -> int:
    if hasattr(value, "sum"):
        value = value.sum()
    if isinstance(value, bool):
        raise ValueError("invalid_trade_count:bool")
    if isinstance(value, numbers.Integral):
        return int(value)
    if isinstance(value, numbers.Real):
        float_value = float(value)
        if not math.isfinite(float_value) or not float_value.is_integer():
            raise ValueError(f"invalid_trade_count:{value}")
        return int(float_value)
    raise ValueError(f"invalid_trade_count:{value}")


def _failed(backend: str, warning: str) -> BackendRunResult:
    return BackendRunResult(
        backend=backend,
        status="failed",
        metrics={},
        warnings=(warning,),
        unsupported_semantics=(),
    )
