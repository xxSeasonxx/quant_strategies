"""Strategy: crypto_perp_multivote_trend_following

Source / provenance:
Exp102-inspired hybrid port of the upstream Nunchi autoresearch crypto
perpetual futures ensemble documented in
https://github.com/Nunchi-trade/auto-researchtrading/blob/main/STRATEGIES.md.
This keeps the six hourly technical votes, BASE_POSITION_PCT = 0.08 as a
portfolio budget, ATR stop multiplier = 5.5, and TAKE_PROFIT_PCT = 99.0. The
upstream Sharpe claim is external benchmark context only; this module does not
reproduce it locally.

Market rationale:
Crypto perpetual trend bursts can persist across liquid instruments when
multi-horizon momentum, trend, oscillator, and volatility-regime signals agree.
The ATR trailing stop is the local runner-compatible proxy for the upstream
stateful risk exit.

Required observables:
Symbol, timezone-aware timestamp, open, high, low, and close for crypto
perpetual bars. funding_rate is consumed when present for audit metadata but is
not required because the upstream final funding boost is effectively disabled.

Decision rule:
Build completed hourly snapshots from rows available at or before the as-of
timestamp. Emit a long or short target-weight decision when at least four of six
votes agree: 12h momentum versus a dynamic volatility threshold, 6h momentum
versus 0.5 of that threshold, EMA(12) versus EMA(26), RSI(8) versus 50,
MACD(12,26,9) histogram sign, and Bollinger Band width percentile below 85 as a
bidirectional volatility-regime vote. The exit policy uses ATR(24) * 5.5 as a
trailing stop in basis points and no take-profit by default. The default 8%
portfolio budget is split equally across configured symbols.

Assumptions:
Input bars are sorted by causal availability through the runner's available_at
field when present, hourly snapshots can be labeled by existing bar timestamps,
and max_hold_bars is expressed in the runner's native input-bar cadence. The
local engine has no explicit flat target or portfolio-aware state, so this port
suppresses overlapping same-symbol entries until the assumed local hold window
ends instead of reproducing upstream portfolio state or signal flips.

Falsifier:
If decisions fail causal data audit, require overlapping same-symbol exposure to
work, or depend on unmodeled flat exits/signal flips for most return, reject
this port before any promotion decision.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from quant_strategies.decisions import (
    ExitPolicy,
    InstrumentRef,
    ObservationRef,
    PositionTarget,
    StrategyDecision,
)

__all__ = ["generate_decisions", "validate_params"]

_REQUIRED_FIELDS = {"symbol", "timestamp", "open", "high", "low", "close"}
_DEFAULT_SYMBOLS = ("BTC-PERP", "ETH-PERP", "SOL-PERP")
_DEFAULT_STRATEGY_ID = "crypto_perp_multivote_trend_following"
_SIGNAL_FAMILY = "crypto_perp_multivote_trend_following"
_UPSTREAM_DEFAULTS = {
    "BASE_POSITION_PCT": 0.08,
    "TAKE_PROFIT_PCT": 99.0,
    "ATR_STOP_MULT": 5.5,
    "MIN_VOTES": 4,
    "MOMENTUM_LONG_HOURS": 12,
    "MOMENTUM_SHORT_HOURS": 6,
    "VSHORT_THRESHOLD_MULT": 0.5,
    "EMA_FAST_SPAN": 12,
    "EMA_SLOW_SPAN": 26,
    "RSI_PERIOD": 8,
    "MACD_FAST_SPAN": 12,
    "MACD_SLOW_SPAN": 26,
    "MACD_SIGNAL_SPAN": 9,
    "ATR_PERIOD": 24,
    "BB_WINDOW_HOURS": 10,
    "BB_PERCENTILE_THRESHOLD": 85.0,
    "BASE_MOMENTUM_THRESHOLD": 0.012,
    "TARGET_VOLATILITY": 0.015,
    "VOL_LOOKBACK_HOURS": 48,
    "DYNAMIC_THRESHOLD_FLOOR": 0.006,
    "DYNAMIC_THRESHOLD_CEILING": 0.025,
}
_PARAM_KEYS = {
    "symbols",
    "min_votes",
    "base_position_pct",
    "cooldown_bars",
    "decision_interval_minutes",
    "decision_lag_minutes",
    "max_hold_bars",
    "atr_stop_mult",
    "rsi_period",
    "bb_percentile_threshold",
    "momentum_long_hours",
    "momentum_short_hours",
    "vshort_threshold_mult",
    "vol_lookback_hours",
    "dynamic_threshold_window_hours",
    "base_momentum_threshold",
    "target_volatility",
    "dynamic_threshold_floor",
    "dynamic_threshold_ceiling",
    "ema_fast_span",
    "ema_slow_span",
    "macd_fast_span",
    "macd_slow_span",
    "macd_signal_span",
    "atr_period",
    "bb_window_hours",
    "bb_percentile_window_hours",
    "bb_std_mult",
}


@dataclass(frozen=True)
class _Params:
    symbols: tuple[str, ...]
    min_votes: int
    base_position_pct: float
    cooldown_bars: int
    decision_interval_minutes: int
    decision_lag_minutes: int
    max_hold_bars: int
    atr_stop_mult: float
    rsi_period: int
    bb_percentile_threshold: float
    momentum_long_hours: int
    momentum_short_hours: int
    vshort_threshold_mult: float
    vol_lookback_hours: int
    base_momentum_threshold: float
    target_volatility: float
    dynamic_threshold_floor: float
    dynamic_threshold_ceiling: float
    ema_fast_span: int
    ema_slow_span: int
    macd_fast_span: int
    macd_slow_span: int
    macd_signal_span: int
    atr_period: int
    bb_window_hours: int
    bb_percentile_window_hours: int
    bb_std_mult: float


@dataclass(frozen=True)
class _InputRow:
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    funding_rate: float | None


@dataclass(frozen=True)
class _HourlySnapshot:
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    funding_rate: float | None
    observations: tuple[ObservationRef, ...]


@dataclass(frozen=True)
class _Indicators:
    momentum_12h_bps: float
    momentum_6h_bps: float
    dynamic_threshold_bps: float
    ema_fast: float
    ema_slow: float
    rsi: float
    macd_histogram: float
    bb_width_percentile: float
    atr_bps: float
    long_votes: int
    short_votes: int
    vote_details: dict[str, str]
    dynamic_threshold: float
    realized_vol: float
    vol_ratio: float


@dataclass(frozen=True)
class _DynamicThreshold:
    threshold: float
    threshold_bps: float
    realized_vol: float
    vol_ratio: float


def validate_params(params: Mapping[str, object]) -> dict[str, object]:
    return _params_mapping(_parse_params(params))


def generate_decisions(
    bars: Sequence[Mapping[str, object]],
    params: Mapping[str, object],
) -> list[StrategyDecision]:
    if not bars:
        return []

    parsed_params = _Params(**validate_params(params))
    _require_fields(bars, _REQUIRED_FIELDS)
    rows_by_symbol = _rows_by_symbol(bars, parsed_params.symbols)
    required_history = _required_history_hours(parsed_params)

    decisions: list[StrategyDecision] = []
    for symbol in parsed_params.symbols:
        rows = rows_by_symbol.get(symbol, [])
        if not rows:
            continue
        snapshots = _hourly_snapshots(rows, parsed_params.decision_interval_minutes)
        if len(snapshots) < required_history:
            continue
        bar_minutes = _median_bar_minutes(rows)
        hold_signal_bars = max(
            1,
            math.ceil(
                parsed_params.max_hold_bars * bar_minutes / parsed_params.decision_interval_minutes
            ),
        )
        next_allowed_index = 0

        for index in range(required_history - 1, len(snapshots)):
            if index < next_allowed_index:
                continue
            history = snapshots[index - required_history + 1 : index + 1]
            indicators = _indicator_values(history, parsed_params)
            if indicators is None:
                continue

            side = _entry_side(indicators, parsed_params.min_votes)
            if side is None:
                continue

            effective_target_weight = parsed_params.base_position_pct / len(parsed_params.symbols)
            decision = _decision(
                history=history,
                indicators=indicators,
                side=side,
                parsed_params=parsed_params,
                effective_target_weight=effective_target_weight,
            )
            decisions.append(decision)
            next_allowed_index = index + max(hold_signal_bars, parsed_params.cooldown_bars) + 1

    return sorted(
        decisions, key=lambda decision: (decision.decision_time, decision.instrument.symbol)
    )


def _parse_params(params: Mapping[str, object]) -> _Params:
    _reject_unknown_params(params, _PARAM_KEYS)
    bb_window_hours = _positive_int(params.get("bb_window_hours", 10), "bb_window_hours")
    parsed = _Params(
        symbols=_symbols_param(params.get("symbols", _DEFAULT_SYMBOLS)),
        min_votes=_bounded_int(params.get("min_votes", 4), "min_votes", minimum=1, maximum=6),
        base_position_pct=_positive_float(
            params.get("base_position_pct", 0.08), "base_position_pct"
        ),
        cooldown_bars=_non_negative_int(params.get("cooldown_bars", 2), "cooldown_bars"),
        decision_interval_minutes=_positive_int(
            params.get("decision_interval_minutes", 60),
            "decision_interval_minutes",
        ),
        decision_lag_minutes=_non_negative_int(
            params.get("decision_lag_minutes", 1), "decision_lag_minutes"
        ),
        max_hold_bars=_positive_int(params.get("max_hold_bars", 720), "max_hold_bars"),
        atr_stop_mult=_positive_float(params.get("atr_stop_mult", 5.5), "atr_stop_mult"),
        rsi_period=_positive_int(params.get("rsi_period", 8), "rsi_period"),
        bb_percentile_threshold=_percentile_float(
            params.get("bb_percentile_threshold", 85.0),
            "bb_percentile_threshold",
        ),
        momentum_long_hours=_positive_int(
            params.get("momentum_long_hours", 12), "momentum_long_hours"
        ),
        momentum_short_hours=_positive_int(
            params.get("momentum_short_hours", 6), "momentum_short_hours"
        ),
        vshort_threshold_mult=_positive_float(
            params.get("vshort_threshold_mult", 0.5), "vshort_threshold_mult"
        ),
        vol_lookback_hours=_positive_int(
            _param_or_alias(params, "vol_lookback_hours", "dynamic_threshold_window_hours", 48),
            "vol_lookback_hours",
        ),
        base_momentum_threshold=_positive_float(
            params.get("base_momentum_threshold", 0.012),
            "base_momentum_threshold",
        ),
        target_volatility=_positive_float(
            params.get("target_volatility", 0.015), "target_volatility"
        ),
        dynamic_threshold_floor=_positive_float(
            params.get("dynamic_threshold_floor", 0.006),
            "dynamic_threshold_floor",
        ),
        dynamic_threshold_ceiling=_positive_float(
            params.get("dynamic_threshold_ceiling", 0.025),
            "dynamic_threshold_ceiling",
        ),
        ema_fast_span=_positive_int(params.get("ema_fast_span", 12), "ema_fast_span"),
        ema_slow_span=_positive_int(params.get("ema_slow_span", 26), "ema_slow_span"),
        macd_fast_span=_positive_int(params.get("macd_fast_span", 12), "macd_fast_span"),
        macd_slow_span=_positive_int(params.get("macd_slow_span", 26), "macd_slow_span"),
        macd_signal_span=_positive_int(params.get("macd_signal_span", 9), "macd_signal_span"),
        atr_period=_positive_int(params.get("atr_period", 24), "atr_period"),
        bb_window_hours=bb_window_hours,
        bb_percentile_window_hours=_positive_int(
            params.get("bb_percentile_window_hours", 2 * bb_window_hours),
            "bb_percentile_window_hours",
        ),
        bb_std_mult=_positive_float(params.get("bb_std_mult", 1.0), "bb_std_mult"),
    )
    if parsed.dynamic_threshold_floor > parsed.dynamic_threshold_ceiling:
        raise ValueError(
            "dynamic_threshold_floor must be less than or equal to dynamic_threshold_ceiling"
        )
    return parsed


def _params_mapping(params: _Params) -> dict[str, object]:
    return {
        "symbols": params.symbols,
        "min_votes": params.min_votes,
        "base_position_pct": params.base_position_pct,
        "cooldown_bars": params.cooldown_bars,
        "decision_interval_minutes": params.decision_interval_minutes,
        "decision_lag_minutes": params.decision_lag_minutes,
        "max_hold_bars": params.max_hold_bars,
        "atr_stop_mult": params.atr_stop_mult,
        "rsi_period": params.rsi_period,
        "bb_percentile_threshold": params.bb_percentile_threshold,
        "momentum_long_hours": params.momentum_long_hours,
        "momentum_short_hours": params.momentum_short_hours,
        "vshort_threshold_mult": params.vshort_threshold_mult,
        "vol_lookback_hours": params.vol_lookback_hours,
        "base_momentum_threshold": params.base_momentum_threshold,
        "target_volatility": params.target_volatility,
        "dynamic_threshold_floor": params.dynamic_threshold_floor,
        "dynamic_threshold_ceiling": params.dynamic_threshold_ceiling,
        "ema_fast_span": params.ema_fast_span,
        "ema_slow_span": params.ema_slow_span,
        "macd_fast_span": params.macd_fast_span,
        "macd_slow_span": params.macd_slow_span,
        "macd_signal_span": params.macd_signal_span,
        "atr_period": params.atr_period,
        "bb_window_hours": params.bb_window_hours,
        "bb_percentile_window_hours": params.bb_percentile_window_hours,
        "bb_std_mult": params.bb_std_mult,
    }


def _require_fields(bars: Sequence[Mapping[str, object]], required: set[str]) -> None:
    for index, row in enumerate(bars):
        missing = required.difference(row.keys())
        if missing:
            raise ValueError(f"bar {index} missing required fields: {sorted(missing)}")


def _rows_by_symbol(
    bars: Sequence[Mapping[str, object]],
    symbols: tuple[str, ...],
) -> dict[str, list[_InputRow]]:
    allowed = set(symbols)
    seen: set[tuple[str, datetime]] = set()
    rows_by_symbol: dict[str, list[_InputRow]] = {symbol: [] for symbol in symbols}

    for row in bars:
        symbol = str(row["symbol"])
        if symbol not in allowed:
            continue
        timestamp = _as_datetime(row["timestamp"])
        key = (symbol, timestamp)
        if key in seen:
            raise ValueError(f"duplicate rows for {symbol} at {timestamp.isoformat()}")
        seen.add(key)
        rows_by_symbol[symbol].append(
            _InputRow(
                symbol=symbol,
                timestamp=timestamp,
                open=_positive_price(row["open"], "open"),
                high=_positive_price(row["high"], "high"),
                low=_positive_price(row["low"], "low"),
                close=_positive_price(row["close"], "close"),
                funding_rate=_optional_finite_float(row.get("funding_rate"), "funding_rate"),
            )
        )

    for rows in rows_by_symbol.values():
        rows.sort(key=lambda item: item.timestamp)
    return rows_by_symbol


def _hourly_snapshots(rows: list[_InputRow], interval_minutes: int) -> list[_HourlySnapshot]:
    snapshots: list[_HourlySnapshot] = []
    window: list[_InputRow] = []
    interval = timedelta(minutes=interval_minutes)

    for row in rows:
        window.append(row)
        cutoff = row.timestamp - interval
        while window and window[0].timestamp <= cutoff:
            window.pop(0)
        if not _is_decision_time(row.timestamp, interval_minutes):
            continue
        if not window:
            continue

        open_row = window[0]
        high_row = max(window, key=lambda item: item.high)
        low_row = min(window, key=lambda item: item.low)
        close_row = window[-1]
        funding_row = next(
            (item for item in reversed(window) if item.funding_rate is not None), None
        )
        observations = (
            ObservationRef(
                symbol=row.symbol,
                timestamp=open_row.timestamp,
                field="open",
                source="strategy_input",
            ),
            ObservationRef(
                symbol=row.symbol,
                timestamp=high_row.timestamp,
                field="high",
                source="strategy_input",
            ),
            ObservationRef(
                symbol=row.symbol, timestamp=low_row.timestamp, field="low", source="strategy_input"
            ),
            ObservationRef(
                symbol=row.symbol,
                timestamp=close_row.timestamp,
                field="close",
                source="strategy_input",
            ),
        )
        if funding_row is not None:
            observations = (
                *observations,
                ObservationRef(
                    symbol=row.symbol,
                    timestamp=funding_row.timestamp,
                    field="funding_rate",
                    source="strategy_input",
                ),
            )

        snapshots.append(
            _HourlySnapshot(
                symbol=row.symbol,
                timestamp=row.timestamp,
                open=open_row.open,
                high=high_row.high,
                low=low_row.low,
                close=close_row.close,
                funding_rate=funding_row.funding_rate if funding_row is not None else None,
                observations=observations,
            )
        )

    return snapshots


def _indicator_values(history: Sequence[_HourlySnapshot], params: _Params) -> _Indicators | None:
    closes = [snapshot.close for snapshot in history]
    highs = [snapshot.high for snapshot in history]
    lows = [snapshot.low for snapshot in history]

    momentum_long_bps = _momentum_bps(closes, params.momentum_long_hours)
    momentum_short_bps = _momentum_bps(closes, params.momentum_short_hours)
    dynamic_threshold = _dynamic_threshold(
        closes,
        vol_lookback_hours=params.vol_lookback_hours,
        base_threshold=params.base_momentum_threshold,
        target_volatility=params.target_volatility,
        floor=params.dynamic_threshold_floor,
        ceiling=params.dynamic_threshold_ceiling,
    )
    rsi = _rsi(closes, params.rsi_period)
    macd_histogram = _macd_histogram(
        closes,
        fast_span=params.macd_fast_span,
        slow_span=params.macd_slow_span,
        signal_span=params.macd_signal_span,
    )
    bb_width_percentile = _bollinger_width_percentile(
        closes,
        window_hours=params.bb_window_hours,
        percentile_window_hours=params.bb_percentile_window_hours,
        std_mult=params.bb_std_mult,
    )
    atr_bps = _atr_bps(highs, lows, closes, params.atr_period)
    if (
        momentum_long_bps is None
        or momentum_short_bps is None
        or dynamic_threshold is None
        or rsi is None
        or macd_histogram is None
        or bb_width_percentile is None
        or atr_bps is None
        or atr_bps <= 0.0
    ):
        return None

    ema_fast = _ema(closes, params.ema_fast_span)
    ema_slow = _ema(closes, params.ema_slow_span)
    if ema_fast is None or ema_slow is None:
        return None

    long_votes = 0
    short_votes = 0
    vote_details: dict[str, str] = {}

    if momentum_long_bps > dynamic_threshold.threshold_bps:
        long_votes += 1
        vote_details["momentum_12h"] = "long"
    elif momentum_long_bps < -dynamic_threshold.threshold_bps:
        short_votes += 1
        vote_details["momentum_12h"] = "short"
    else:
        vote_details["momentum_12h"] = "neutral"

    short_threshold = params.vshort_threshold_mult * dynamic_threshold.threshold_bps
    if momentum_short_bps > short_threshold:
        long_votes += 1
        vote_details["momentum_6h"] = "long"
    elif momentum_short_bps < -short_threshold:
        short_votes += 1
        vote_details["momentum_6h"] = "short"
    else:
        vote_details["momentum_6h"] = "neutral"

    if ema_fast > ema_slow:
        long_votes += 1
        vote_details["ema"] = "long"
    elif ema_fast < ema_slow:
        short_votes += 1
        vote_details["ema"] = "short"
    else:
        vote_details["ema"] = "neutral"

    if rsi > 50.0:
        long_votes += 1
        vote_details["rsi"] = "long"
    elif rsi < 50.0:
        short_votes += 1
        vote_details["rsi"] = "short"
    else:
        vote_details["rsi"] = "neutral"

    if macd_histogram > 0.0:
        long_votes += 1
        vote_details["macd_histogram"] = "long"
    elif macd_histogram < 0.0:
        short_votes += 1
        vote_details["macd_histogram"] = "short"
    else:
        vote_details["macd_histogram"] = "neutral"

    if bb_width_percentile < params.bb_percentile_threshold:
        long_votes += 1
        short_votes += 1
        vote_details["bb_width_percentile"] = "both"
    else:
        vote_details["bb_width_percentile"] = "neutral"

    return _Indicators(
        momentum_12h_bps=momentum_long_bps,
        momentum_6h_bps=momentum_short_bps,
        dynamic_threshold_bps=dynamic_threshold.threshold_bps,
        ema_fast=ema_fast,
        ema_slow=ema_slow,
        rsi=rsi,
        macd_histogram=macd_histogram,
        bb_width_percentile=bb_width_percentile,
        atr_bps=atr_bps,
        long_votes=long_votes,
        short_votes=short_votes,
        vote_details=vote_details,
        dynamic_threshold=dynamic_threshold.threshold,
        realized_vol=dynamic_threshold.realized_vol,
        vol_ratio=dynamic_threshold.vol_ratio,
    )


def _entry_side(indicators: _Indicators, min_votes: int) -> str | None:
    if indicators.long_votes >= min_votes and indicators.long_votes > indicators.short_votes:
        return "long"
    if indicators.short_votes >= min_votes and indicators.short_votes > indicators.long_votes:
        return "short"
    return None


def _decision(
    history: Sequence[_HourlySnapshot],
    indicators: _Indicators,
    side: str,
    parsed_params: _Params,
    effective_target_weight: float,
) -> StrategyDecision:
    snapshot = history[-1]
    decision_time = snapshot.timestamp + timedelta(minutes=parsed_params.decision_lag_minutes)
    trailing_stop_bps = indicators.atr_bps * parsed_params.atr_stop_mult
    metadata: dict[str, Any] = {
        "signal_family": _SIGNAL_FAMILY,
        "long_votes": indicators.long_votes,
        "short_votes": indicators.short_votes,
        "vote_details": indicators.vote_details,
        "min_votes": parsed_params.min_votes,
        "momentum_12h_bps": indicators.momentum_12h_bps,
        "momentum_6h_bps": indicators.momentum_6h_bps,
        "vshort_threshold_mult": parsed_params.vshort_threshold_mult,
        "dynamic_threshold": indicators.dynamic_threshold,
        "dynamic_threshold_bps": indicators.dynamic_threshold_bps,
        "realized_vol": indicators.realized_vol,
        "vol_ratio": indicators.vol_ratio,
        "ema_fast": indicators.ema_fast,
        "ema_slow": indicators.ema_slow,
        "rsi": indicators.rsi,
        "macd_histogram": indicators.macd_histogram,
        "bb_width_percentile": indicators.bb_width_percentile,
        "atr_bps": indicators.atr_bps,
        "trailing_stop_bps": trailing_stop_bps,
        "upstream_reference": "Nunchi STRATEGIES.md exp102-inspired",
        "portfolio_budget_pct": parsed_params.base_position_pct,
        "symbol_weight_fraction": 1.0 / len(parsed_params.symbols),
        "effective_target_weight": effective_target_weight,
        "stateful_rsi_exit_supported": False,
        "signal_flip_supported": False,
        "same_symbol_overlap_policy": "suppress_until_assumed_hold_window_end",
        "upstream_defaults": _UPSTREAM_DEFAULTS,
    }
    if snapshot.funding_rate is not None:
        metadata["latest_funding_rate"] = snapshot.funding_rate

    return StrategyDecision(
        strategy_id=_DEFAULT_STRATEGY_ID,
        instrument=InstrumentRef(kind="crypto_perp", symbol=snapshot.symbol),
        decision_time=decision_time,
        as_of_time=snapshot.timestamp,
        target=PositionTarget(
            direction=side,
            sizing_kind="target_weight",
            size=effective_target_weight,
        ),
        exit_policy=ExitPolicy(
            max_hold_bars=parsed_params.max_hold_bars,
            trailing_stop_bps=trailing_stop_bps,
        ),
        observations=_dedupe_observations(history),
        metadata=metadata,
    )


def _dedupe_observations(snapshots: Sequence[_HourlySnapshot]) -> tuple[ObservationRef, ...]:
    observations: list[ObservationRef] = []
    seen: set[tuple[str, datetime, str | None, str | None]] = set()
    for snapshot in snapshots:
        for observation in snapshot.observations:
            key = (observation.symbol, observation.timestamp, observation.field, observation.source)
            if key not in seen:
                observations.append(observation)
                seen.add(key)
    return tuple(observations)


def _required_history_hours(params: _Params) -> int:
    return max(
        params.momentum_long_hours + 1,
        params.momentum_short_hours + 1,
        params.vol_lookback_hours + 1,
        params.ema_slow_span,
        params.macd_slow_span + params.macd_signal_span,
        params.rsi_period + 1,
        params.atr_period + 1,
        params.bb_window_hours + params.bb_percentile_window_hours - 1,
    )


def _momentum_bps(closes: Sequence[float], lookback_hours: int) -> float | None:
    if len(closes) <= lookback_hours:
        return None
    base = closes[-lookback_hours - 1]
    if base <= 0.0:
        return None
    return (closes[-1] / base - 1.0) * 10_000.0


def _ema(values: Sequence[float], span: int) -> float | None:
    series = _ema_series(values, span)
    return series[-1] if series else None


def _ema_series(values: Sequence[float], span: int) -> list[float]:
    if not values:
        return []
    alpha = 2.0 / (span + 1.0)
    ema = float(values[0])
    output = [ema]
    for value in values[1:]:
        ema = alpha * float(value) + (1.0 - alpha) * ema
        output.append(ema)
    return output


def _rsi(closes: Sequence[float], period: int) -> float | None:
    if len(closes) <= period:
        return None
    recent = closes[-(period + 1) :]
    diffs = [recent[index] - recent[index - 1] for index in range(1, len(recent))]
    gains = [max(diff, 0.0) for diff in diffs]
    losses = [max(-diff, 0.0) for diff in diffs]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_gain == 0.0 and avg_loss == 0.0:
        return 50.0
    if avg_loss == 0.0:
        return 100.0
    if avg_gain == 0.0:
        return 0.0
    relative_strength = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + relative_strength)


def _macd_histogram(
    closes: Sequence[float],
    *,
    fast_span: int,
    slow_span: int,
    signal_span: int,
) -> float | None:
    if len(closes) < slow_span + signal_span:
        return None
    fast = _ema_series(closes, fast_span)
    slow = _ema_series(closes, slow_span)
    macd = [fast_value - slow_value for fast_value, slow_value in zip(fast, slow)]
    signal = _ema_series(macd, signal_span)
    return macd[-1] - signal[-1]


def _atr_bps(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int,
) -> float | None:
    if len(closes) <= period or len(highs) != len(closes) or len(lows) != len(closes):
        return None
    true_ranges = []
    for index in range(1, len(closes)):
        high = highs[index]
        low = lows[index]
        previous_close = closes[index - 1]
        true_ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    atr = sum(true_ranges[-period:]) / period
    return atr / closes[-1] * 10_000.0


def _bollinger_width_percentile(
    closes: Sequence[float],
    *,
    window_hours: int,
    percentile_window_hours: int,
    std_mult: float,
) -> float | None:
    if len(closes) < window_hours + percentile_window_hours - 1:
        return None

    widths = []
    for end in range(window_hours, len(closes) + 1):
        window = closes[end - window_hours : end]
        mean = sum(window) / window_hours
        if mean <= 0.0:
            return None
        variance = sum((value - mean) ** 2 for value in window) / window_hours
        width = (2.0 * std_mult * math.sqrt(variance)) / mean
        widths.append(width)

    recent = widths[-percentile_window_hours:]
    current = recent[-1]
    return 100.0 * sum(1 for width in recent if width <= current) / len(recent)


def _dynamic_threshold(
    closes: Sequence[float],
    *,
    vol_lookback_hours: int,
    base_threshold: float,
    target_volatility: float,
    floor: float,
    ceiling: float,
) -> _DynamicThreshold | None:
    if len(closes) <= vol_lookback_hours:
        return None
    returns = [
        math.log(closes[index] / closes[index - 1])
        for index in range(len(closes) - vol_lookback_hours, len(closes))
    ]
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / len(returns)
    realized_vol = math.sqrt(variance)
    vol_ratio = realized_vol / target_volatility
    threshold = base_threshold * (0.5 + vol_ratio * 0.5)
    threshold = min(max(threshold, floor), ceiling)
    return _DynamicThreshold(
        threshold=threshold,
        threshold_bps=threshold * 10_000.0,
        realized_vol=realized_vol,
        vol_ratio=vol_ratio,
    )


def _dynamic_threshold_bps(
    closes: Sequence[float],
    *,
    vol_lookback_hours: int,
    base_threshold: float,
    target_volatility: float,
    floor: float,
    ceiling: float,
) -> float | None:
    threshold = _dynamic_threshold(
        closes,
        vol_lookback_hours=vol_lookback_hours,
        base_threshold=base_threshold,
        target_volatility=target_volatility,
        floor=floor,
        ceiling=ceiling,
    )
    return threshold.threshold_bps if threshold is not None else None


def _median_bar_minutes(rows: Sequence[_InputRow]) -> float:
    if len(rows) < 2:
        return 1.0
    gaps = [
        (rows[index].timestamp - rows[index - 1].timestamp).total_seconds() / 60.0
        for index in range(1, len(rows))
        if rows[index].timestamp > rows[index - 1].timestamp
    ]
    if not gaps:
        return 1.0
    ordered = sorted(gaps)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _is_decision_time(timestamp: datetime, decision_interval_minutes: int) -> bool:
    if timestamp.second or timestamp.microsecond:
        return False
    minute_of_day = timestamp.hour * 60 + timestamp.minute
    return minute_of_day % decision_interval_minutes == 0


def _symbols_param(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        raw_symbols = tuple(part.strip() for part in value.split(","))
    elif isinstance(value, Sequence):
        raw_symbols = tuple(str(part).strip() for part in value)
    else:
        raise ValueError("symbols must be a string or sequence")
    symbols = tuple(symbol for symbol in raw_symbols if symbol)
    if not symbols:
        raise ValueError("symbols must contain at least one symbol")
    return symbols


def _bounded_int(value: object, name: str, *, minimum: int, maximum: int) -> int:
    parsed = _integer(value, name)
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return parsed


def _positive_int(value: object, name: str) -> int:
    parsed = _integer(value, name)
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _non_negative_int(value: object, name: str) -> int:
    parsed = _integer(value, name)
    if parsed < 0:
        raise ValueError(f"{name} must be non-negative")
    return parsed


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not math.isfinite(parsed) or not parsed.is_integer():
        raise ValueError(f"{name} must be an integer")
    return int(parsed)


def _positive_float(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be finite and positive")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be finite and positive") from exc
    if not math.isfinite(parsed) or parsed <= 0.0:
        raise ValueError(f"{name} must be finite and positive")
    return parsed


def _non_negative_float(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be finite and non-negative")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be finite and non-negative") from exc
    if not math.isfinite(parsed) or parsed < 0.0:
        raise ValueError(f"{name} must be finite and non-negative")
    return parsed


def _percentile_float(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be between 0 and 100")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be between 0 and 100") from exc
    if not math.isfinite(parsed) or parsed < 0.0 or parsed > 100.0:
        raise ValueError(f"{name} must be between 0 and 100")
    return parsed


def _positive_price(value: object, name: str) -> float:
    parsed = _positive_float(value, name)
    return parsed


def _optional_finite_float(value: object, name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{name} must be finite when present")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be finite when present") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{name} must be finite when present")
    return parsed


def _param_or_alias(
    params: Mapping[str, object], canonical: str, alias: str, default: object
) -> object:
    if canonical in params:
        return params[canonical]
    if alias in params:
        return params[alias]
    return default


def _reject_unknown_params(params: Mapping[str, object], allowed: set[str]) -> None:
    unknown = sorted(set(params).difference(allowed))
    if unknown:
        raise ValueError(f"unknown params: {', '.join(unknown)}")


def _as_datetime(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"expected datetime timestamp, got {type(value).__name__}")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value
