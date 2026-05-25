from __future__ import annotations

import math
from typing import Any

from quant_strategies.decisions import StrategyDecision
from quant_strategies.validation.backends import BackendRunResult


class VectorBTProBackend:
    name = "vectorbtpro"

    def run(
        self,
        *,
        decisions: list[StrategyDecision],
        rows: list[dict[str, Any]],
        config: Any,
    ) -> BackendRunResult:
        unsupported = _unsupported_semantics(decisions)
        if unsupported:
            return BackendRunResult(
                backend=self.name,
                status="unsupported",
                metrics={},
                warnings=(),
                unsupported_semantics=unsupported,
            )

        try:
            import pandas as pd
            import vectorbtpro as vbt
        except ImportError as exc:
            return BackendRunResult(
                backend=self.name,
                status="unavailable",
                metrics={},
                warnings=(f"vectorbtpro import failed: {exc}",),
                unsupported_semantics=(),
            )

        try:
            close = _close_frame(pd, rows)
        except ValueError as exc:
            return _failed(self.name, f"invalid_rows:{exc}")

        decision_symbols = tuple(dict.fromkeys(item.instrument.symbol for item in decisions))
        missing_symbols = [symbol for symbol in decision_symbols if symbol not in close.columns]
        if missing_symbols:
            return _failed(self.name, f"missing_symbol:{missing_symbols[0]}")
        if decision_symbols:
            close = close.loc[:, list(decision_symbols)]

        long_entries = pd.DataFrame(False, index=close.index, columns=close.columns)
        long_exits = pd.DataFrame(False, index=close.index, columns=close.columns)
        short_entries = pd.DataFrame(False, index=close.index, columns=close.columns)
        short_exits = pd.DataFrame(False, index=close.index, columns=close.columns)
        size = pd.DataFrame(0.0, index=close.index, columns=close.columns)

        entry_lag = _entry_lag(config)
        exit_lag = _exit_lag(config)
        entry_signals: set[tuple[str, Any]] = set()
        exit_signals: set[tuple[str, Any]] = set()

        for item in decisions:
            symbol = item.instrument.symbol
            if symbol not in close.columns:
                return _failed(self.name, f"missing_symbol:{symbol}")

            decision_idx = _index_position(pd, close.index, item.decision_time)
            if decision_idx is None:
                return _failed(self.name, f"missing_decision_bar:{symbol}:{item.decision_time.isoformat()}")

            entry_idx = decision_idx + entry_lag
            if entry_idx >= len(close.index):
                return _failed(self.name, f"unfillable_entry:{symbol}:{item.decision_time.isoformat()}")

            entry_time = close.index[entry_idx]
            if pd.isna(close.loc[entry_time, symbol]):
                return _failed(self.name, f"unfillable_entry:{symbol}:{entry_time.isoformat()}")
            entry_key = (symbol, entry_time)
            if entry_key in entry_signals:
                return _failed(self.name, f"duplicate_entry_signal:{symbol}:{entry_time.isoformat()}")

            exit_idx = entry_idx + item.exit_policy.max_hold_bars + exit_lag
            if exit_idx >= len(close.index):
                return _failed(self.name, f"unfillable_exit:{symbol}:{item.decision_time.isoformat()}")

            exit_time = close.index[exit_idx]
            if pd.isna(close.loc[exit_time, symbol]):
                return _failed(self.name, f"unfillable_exit:{symbol}:{exit_time.isoformat()}")
            exit_key = (symbol, exit_time)
            if exit_key in exit_signals:
                return _failed(self.name, f"duplicate_exit_signal:{symbol}:{exit_time.isoformat()}")

            if item.target.direction == "long":
                long_entries.loc[entry_time, symbol] = True
                long_exits.loc[exit_time, symbol] = True
            elif item.target.direction == "short":
                short_entries.loc[entry_time, symbol] = True
                short_exits.loc[exit_time, symbol] = True

            entry_signals.add(entry_key)
            exit_signals.add(exit_key)
            size.loc[entry_time, symbol] = item.target.size

        fees = _bps_fraction(_config_value(config, "cost_model", "fee_bps_per_side", default=0.0))
        slippage = _bps_fraction(_config_value(config, "cost_model", "slippage_bps_per_side", default=0.0))
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

        return BackendRunResult(
            backend=self.name,
            status="completed",
            metrics={
                "net_return": _float_metric(portfolio.get_total_return()),
                "trade_count": _int_metric(portfolio.trades.count()),
            },
            warnings=(),
            unsupported_semantics=(),
        )


def _unsupported_semantics(decisions: list[StrategyDecision]) -> tuple[str, ...]:
    unsupported: list[str] = []
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
    return int(_config_value(config, "fill_model", "entry_lag_bars", default=0))


def _exit_lag(config: Any) -> int:
    return int(_config_value(config, "fill_model", "exit_lag_bars", default=0))


def _config_value(config: Any, section: str, field: str, *, default: Any) -> Any:
    section_value = getattr(config, section, None)
    if section_value is None:
        return default
    return getattr(section_value, field, default)


def _bps_fraction(value: Any) -> float:
    return float(value) / 10_000.0


def _float_metric(value: Any) -> float:
    if hasattr(value, "mean"):
        return float(value.mean())
    return float(value)


def _int_metric(value: Any) -> int:
    if hasattr(value, "sum"):
        return int(value.sum())
    return int(value)


def _failed(backend: str, warning: str) -> BackendRunResult:
    return BackendRunResult(
        backend=backend,
        status="failed",
        metrics={},
        warnings=(warning,),
        unsupported_semantics=(),
    )
