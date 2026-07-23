"""Strategy: crypto_perp_tsmom_vol_target

Source / provenance:
Per-symbol time-series momentum with an engine-owned volatility-managed overlay.
Time-series momentum: Moskowitz, Ooi & Pedersen, "Time Series Momentum", Journal
of Financial Economics 104(2) 2012, doi:10.1016/j.jfineco.2011.11.003
(https://www.sciencedirect.com/science/article/abs/pii/S0304405X11002613).
Volatility-managed overlay: Moreira & Muir, "Volatility-Managed Portfolios",
Journal of Finance 2017, NBER WP 22208
(https://www.nber.org/system/files/working_papers/w22208/w22208.pdf; SSRN
2659431). Crypto replication and cost/robustness framing:
internal_note: docs/research/crypto/README.md candidate #1 and
docs/research/crypto/06_volatility_seasonality_trend.md families 1 and 4
(Grayscale "The Trend is Your Friend"; Finance Research Letters 2025,
"Cryptocurrency market risk-managed momentum strategies").

Market rationale:
Crypto perpetuals under-react to information and herd, so each instrument's own
trailing return predicts its next-horizon return over a weeks-scale clock. The
edge is computed from each symbol's own history, so it does not depend on a broad
survivor cross-section and dodges the survivorship bias that inflates
cross-sectional crypto claims. Sizing the whole book to a target volatility is a
near-free Sharpe multiplier because volatility is persistent and forecastable
while expected return is not, so cutting risk in high-vol regimes truncates the
trend-crash tail.

Required observables:
Symbol, timezone-aware bar timestamp, available_at, and close for crypto
perpetual bars. Funding is not read for the signal; the book runs under the
financed data kind only so multi-day holds pay or collect funding honestly. A row
is used only when its available_at is at or before the emitted decision_time.

Decision rule:
On a fixed rebalance clock, for each symbol form the trailing return
r_L = close_now / close_L - 1 over lookback_days. signal="sign" targets the sign
of r_L; signal="vol_scaled" targets r_L divided by the name's expected horizon
move (per-minute realized vol over vol_lookback_days times sqrt(horizon)), so
weaker or noisier trends carry less weight. An optional ma_gate_days moving-average
gate zeroes a name whose price has not confirmed the trend direction; allow_short
false clamps negative targets to flat. Emit one signed weight-of-NAV target per
symbol whenever its target changes from the last emitted value, including a zero
target to close a name that has gone flat, so the standing book rebalances by
netting. Book-level volatility targeting and the leverage ceiling are the engine's
operator-frozen risk budget, not strategy knobs.

Assumptions:
Input bars are timezone-aware and ordered by causal availability through
available_at; the rebalance clock fires at UTC midnight every rebalance_days days
and each per-symbol decision fires at that name's signal-bar available_at plus
decision_lag_minutes, so it is never look-ahead. Warmup happens inside the decision
window: rebalances before enough lookback and volatility history simply emit no
target. The single signed target per symbol nets by construction; a zero target is
a data-driven flat and declares the same close observations as a directional one.

Falsifier:
If net return after realistic costs and ADV/impact capacity is not positive across
the bounded lookbacks, or all return is concentrated in a single mega-trend
window (for example the 2020-21 bull) rather than pervasive across symbols and
subwindows, reject the thesis rather than adding signals or per-name exceptions.
"""

import math
from bisect import bisect_left, bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

from quant_strategies.decisions import (
    InstrumentRef,
    ObservationRef,
    TargetDecision,
)

__all__ = ["generate_decisions", "validate_params"]

_STRATEGY_ID = "crypto_perp_tsmom_vol_target"
_SOURCE = "crypto_perp_1min_with_funding"
_REQUIRED_FIELDS = {"symbol", "timestamp", "available_at", "close"}
_MINUTES_PER_DAY = 1440
_DEFAULT_PARAMS: dict[str, object] = {
    "lookback_days": 30,
    "signal": "vol_scaled",
    "rebalance_days": 1,
    "ma_gate_days": 0,
    "vol_lookback_days": 30,
    "allow_short": True,
    "decision_lag_minutes": 1,
    "base_weight": 1.0,
}


@dataclass(frozen=True)
class _BarRow:
    symbol: str
    timestamp: datetime
    available_at: datetime
    close: float


@dataclass(frozen=True)
class _SymbolRows:
    bars: tuple[_BarRow, ...]
    timestamps: tuple[datetime, ...]


def validate_params(params: Mapping[str, object]) -> dict[str, object]:
    """Validate the bounded time-series-momentum parameters."""

    unknown = set(params) - set(_DEFAULT_PARAMS)
    if unknown:
        raise ValueError(f"unknown params: {sorted(unknown)}")

    merged = {**_DEFAULT_PARAMS, **dict(params)}
    validated: dict[str, object] = {
        "lookback_days": _positive_int(merged["lookback_days"], "lookback_days"),
        "signal": _signal(merged["signal"]),
        "rebalance_days": _positive_int(merged["rebalance_days"], "rebalance_days"),
        "ma_gate_days": _non_negative_int(merged["ma_gate_days"], "ma_gate_days"),
        "vol_lookback_days": _positive_int(merged["vol_lookback_days"], "vol_lookback_days"),
        "allow_short": _bool_param(merged["allow_short"], "allow_short"),
        "decision_lag_minutes": _non_negative_int(
            merged["decision_lag_minutes"], "decision_lag_minutes"
        ),
        "base_weight": _positive_float(merged["base_weight"], "base_weight"),
    }
    return validated


def generate_decisions(
    bars: Sequence[Mapping[str, object]], params: Mapping[str, object]
) -> list[TargetDecision]:
    """Emit standing per-symbol time-series-momentum target decisions."""

    if not bars:
        return []
    validated = validate_params(params)
    rows_by_symbol = _rows_by_symbol(bars)
    if not rows_by_symbol:
        return []

    lookback_days = _param_int(validated, "lookback_days")
    rebalance_days = _param_int(validated, "rebalance_days")
    vol_lookback_minutes = _param_int(validated, "vol_lookback_days") * _MINUTES_PER_DAY
    ma_gate_minutes = _param_int(validated, "ma_gate_days") * _MINUTES_PER_DAY
    signal = _param_str(validated, "signal")
    allow_short = _param_bool(validated, "allow_short")
    base_weight = _param_float(validated, "base_weight")
    lag = _param_int(validated, "decision_lag_minutes")

    rebalance_times = _rebalance_times(rows_by_symbol, rebalance_days)
    last_target: dict[str, float] = {}
    decisions: list[TargetDecision] = []
    seen_keys: set[tuple[str, datetime]] = set()

    for signal_time in rebalance_times:
        for symbol in sorted(rows_by_symbol):
            rows = rows_by_symbol[symbol]
            evaluated = _symbol_target(
                rows=rows,
                signal_time=signal_time,
                lookback_days=lookback_days,
                vol_lookback_minutes=vol_lookback_minutes,
                ma_gate_minutes=ma_gate_minutes,
                signal=signal,
                allow_short=allow_short,
                base_weight=base_weight,
            )
            if evaluated is None:
                continue
            target, signal_row, lookback_row = evaluated
            previous = last_target.get(symbol, 0.0)
            if target == previous:
                continue
            decision_time = signal_row.available_at + timedelta(minutes=lag)
            key = (symbol, decision_time)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            last_target[symbol] = target
            decisions.append(
                TargetDecision(
                    strategy_id=_STRATEGY_ID,
                    instrument=InstrumentRef(kind="crypto_perp", symbol=symbol),
                    decision_time=decision_time,
                    as_of_time=signal_row.timestamp,
                    target=target,
                    observations=_observations(symbol, signal_row, lookback_row),
                    metadata={
                        "signal_family": _STRATEGY_ID,
                        "signal": signal,
                        "formation_return_bps": (signal_row.close / lookback_row.close - 1.0)
                        * 10_000.0,
                    },
                )
            )

    return sorted(
        decisions,
        key=lambda decision: (decision.decision_time, decision.instrument.symbol),
    )


def _symbol_target(
    *,
    rows: _SymbolRows,
    signal_time: datetime,
    lookback_days: int,
    vol_lookback_minutes: int,
    ma_gate_minutes: int,
    signal: str,
    allow_short: bool,
    base_weight: float,
) -> tuple[float, _BarRow, _BarRow] | None:
    """Signed target for one symbol at a rebalance time, or ``None``.

    ``None`` means the symbol has no usable formation history at this rebalance and
    no decision should be emitted. Otherwise returns the signed target plus the
    signal and lookback bars so the caller can time and attribute the decision. A
    zero target with bars present is a valid data-driven flat.
    """

    signal_index = bisect_right(rows.timestamps, signal_time) - 1
    if signal_index < 0:
        return None
    signal_row = rows.bars[signal_index]

    lookback_time = signal_time - timedelta(days=lookback_days)
    lookback_index = bisect_right(rows.timestamps, lookback_time) - 1
    if lookback_index < 0 or lookback_index == signal_index:
        return None
    lookback_row = rows.bars[lookback_index]

    formation_return = signal_row.close / lookback_row.close - 1.0
    if formation_return == 0.0:
        return 0.0, signal_row, lookback_row

    if signal == "sign":
        raw = base_weight * (1.0 if formation_return > 0.0 else -1.0)
    else:
        expected_move = _expected_move(rows, signal_index, vol_lookback_minutes, lookback_days)
        if expected_move is None:
            return 0.0, signal_row, lookback_row
        raw = base_weight * (formation_return / expected_move)

    if not allow_short and raw < 0.0:
        raw = 0.0
    if (
        ma_gate_minutes > 0
        and raw != 0.0
        and not _trend_confirmed(
            raw, signal_row.close, _moving_average(rows, signal_index, ma_gate_minutes)
        )
    ):
        raw = 0.0
    return raw, signal_row, lookback_row


def _trend_confirmed(raw: float, close: float, moving_average: float | None) -> bool:
    """Whether price confirms the signed signal's direction against the MA gate.

    A long needs price above the moving average, a short below it. An unknown
    moving average never confirms, so the gate flattens the name.
    """

    if moving_average is None:
        return False
    if raw > 0.0:
        return close > moving_average
    return close < moving_average


def _expected_move(
    rows: _SymbolRows, signal_index: int, vol_lookback_minutes: int, lookback_days: int
) -> float | None:
    """Random-walk expected move over the formation horizon, or ``None``.

    ``per_minute_vol * sqrt(lookback_days * 1440)`` scales the formation return
    into units of its own expected magnitude, so the vol-scaled signal is
    comparable across names of different volatility. Returns ``None`` when the
    volatility window is too short or degenerate.
    """

    per_minute_vol = _realized_volatility(rows, signal_index, vol_lookback_minutes)
    if per_minute_vol is None:
        return None
    move = per_minute_vol * math.sqrt(lookback_days * _MINUTES_PER_DAY)
    return move if move > 0.0 else None


def _realized_volatility(
    rows: _SymbolRows, signal_index: int, lookback_minutes: int
) -> float | None:
    """Std of 1-minute close-to-close returns over the lookback ending at the signal bar.

    Causal: uses only bars at or before the signal bar. Returns ``None`` when the
    window is too short or degenerate.
    """

    lookback_time = rows.bars[signal_index].timestamp - timedelta(minutes=lookback_minutes)
    start = bisect_left(rows.timestamps, lookback_time)
    window = rows.bars[start : signal_index + 1]
    if len(window) < 3:
        return None
    returns = [window[i].close / window[i - 1].close - 1.0 for i in range(1, len(window))]
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
    vol = math.sqrt(variance)
    return vol if vol > 0.0 else None


def _moving_average(rows: _SymbolRows, signal_index: int, lookback_minutes: int) -> float | None:
    """Mean close over the trailing window ending at the signal bar, or ``None``."""

    lookback_time = rows.bars[signal_index].timestamp - timedelta(minutes=lookback_minutes)
    start = bisect_left(rows.timestamps, lookback_time)
    window = rows.bars[start : signal_index + 1]
    if not window:
        return None
    return sum(row.close for row in window) / len(window)


def _rebalance_times(
    rows_by_symbol: Mapping[str, _SymbolRows], rebalance_days: int
) -> tuple[datetime, ...]:
    """UTC-midnight rebalance clock firing every ``rebalance_days`` days.

    Uses the union of bar timestamps so the clock only fires where data exists;
    the day-ordinal modulo fixes a consistent phase across the window.
    """

    times = {
        timestamp
        for rows in rows_by_symbol.values()
        for timestamp in rows.timestamps
        if timestamp.hour == 0
        and timestamp.minute == 0
        and timestamp.date().toordinal() % rebalance_days == 0
    }
    return tuple(sorted(times))


def _rows_by_symbol(bars: Sequence[Mapping[str, object]]) -> dict[str, _SymbolRows]:
    grouped: dict[str, list[_BarRow]] = {}
    for index, bar in enumerate(bars):
        missing = _REQUIRED_FIELDS - set(bar)
        if missing:
            raise ValueError(f"bar {index} missing fields: {sorted(missing)}")
        symbol = str(bar["symbol"])
        grouped.setdefault(symbol, []).append(
            _BarRow(
                symbol=symbol,
                timestamp=_datetime_value(bar["timestamp"], "timestamp"),
                available_at=_datetime_value(bar["available_at"], "available_at"),
                close=_positive_float(bar["close"], "close"),
            )
        )

    result: dict[str, _SymbolRows] = {}
    for symbol, symbol_bars in grouped.items():
        ordered = tuple(sorted(symbol_bars, key=lambda row: row.timestamp))
        result[symbol] = _SymbolRows(
            bars=ordered,
            timestamps=tuple(row.timestamp for row in ordered),
        )
    return result


def _observations(
    symbol: str, signal_row: _BarRow, lookback_row: _BarRow
) -> tuple[ObservationRef, ...]:
    return (
        ObservationRef(
            symbol=symbol,
            timestamp=lookback_row.timestamp,
            field="close",
            source=_SOURCE,
        ),
        ObservationRef(
            symbol=symbol,
            timestamp=signal_row.timestamp,
            field="close",
            source=_SOURCE,
        ),
    )


def _param_int(params: Mapping[str, object], key: str) -> int:
    return cast(int, params[key])


def _param_float(params: Mapping[str, object], key: str) -> float:
    return cast(float, params[key])


def _param_bool(params: Mapping[str, object], key: str) -> bool:
    return cast(bool, params[key])


def _param_str(params: Mapping[str, object], key: str) -> str:
    return cast(str, params[key])


def _datetime_value(value: object, field_name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError(f"{field_name} must be a datetime or ISO string")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _finite_float(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{name} must be numeric")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"{name} must be finite")
    return parsed


def _positive_float(value: object, name: str) -> float:
    parsed = _finite_float(value, name)
    if parsed <= 0.0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _int_value(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


def _positive_int(value: object, name: str) -> int:
    parsed = _int_value(value, name)
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _non_negative_int(value: object, name: str) -> int:
    parsed = _int_value(value, name)
    if parsed < 0:
        raise ValueError(f"{name} must be non-negative")
    return parsed


def _bool_param(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be boolean")
    return value


def _signal(value: object) -> str:
    parsed = str(value)
    if parsed not in {"sign", "vol_scaled"}:
        raise ValueError("signal must be one of: sign, vol_scaled")
    return parsed
