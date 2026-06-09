from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest
from tests.candidate_loader import load_candidate_strategy

from quant_strategies.core.data_audit import audit_decision_rows

strategy = load_candidate_strategy("crypto_perp_multivote_trend_following")
_atr_bps = strategy._atr_bps
_bollinger_width_percentile = strategy._bollinger_width_percentile
_dynamic_threshold_bps = strategy._dynamic_threshold_bps
_ema = strategy._ema
_macd_histogram = strategy._macd_histogram
_rsi = strategy._rsi
generate_decisions = strategy.generate_decisions
validate_params = strategy.validate_params

START = datetime(2024, 1, 1, tzinfo=UTC)


def hourly_bar(
    symbol: str,
    hour: int,
    close: float,
    *,
    open_price: float | None = None,
    funding_rate: float | None = None,
) -> dict[str, object]:
    opened = close if open_price is None else open_price
    return {
        "symbol": symbol,
        "timestamp": START + timedelta(hours=hour),
        "open": opened,
        "high": max(opened, close) + 0.5,
        "low": max(0.01, min(opened, close) - 0.5),
        "close": close,
        **({"funding_rate": funding_rate} if funding_rate is not None else {}),
    }


def trend_rows(
    symbol: str = "BTC-PERP", *, direction: int = 1, hours: int = 90
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    previous_close = 100.0 if direction > 0 else 120.0
    for hour in range(hours):
        if direction > 0:
            close = 100.0 + 0.01 * hour + max(0, hour - 55) ** 2 * 0.04
        else:
            close = 120.0 + 0.01 * hour - max(0, hour - 55) ** 2 * 0.04
        rows.append(hourly_bar(symbol, hour, close, open_price=previous_close))
        previous_close = close
    return rows


def minute_rows(symbol: str = "BTC-PERP", *, hours: int = 80) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    previous_close = 100.0
    for minute in range(hours * 60):
        hour = minute / 60.0
        close = 100.0 + 0.01 * hour + max(0.0, hour - 55.0) ** 2 * 0.04
        opened = previous_close
        rows.append(
            {
                "symbol": symbol,
                "timestamp": START + timedelta(minutes=minute),
                "open": opened,
                "high": max(opened, close) + 0.05,
                "low": max(0.01, min(opened, close) - 0.05),
                "close": close,
            }
        )
        previous_close = close
    return rows


def params(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "symbols": ["BTC-PERP"],
        "decision_lag_minutes": 0,
        "max_hold_bars": 1,
        "cooldown_bars": 0,
    }
    values.update(overrides)
    return values


def auditable_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return [{**row, "available_at": row["timestamp"]} for row in rows]


def test_ema_uses_standard_recursive_smoothing():
    assert _ema([10.0, 20.0, 30.0], 2) == pytest.approx(25.5555555556)


def test_rsi_uses_documented_rolling_average():
    assert _rsi([100.0, 102.0, 101.0, 103.0, 102.0], 4) == pytest.approx(66.6666666667)
    assert _rsi([100.0, 101.0, 102.0, 103.0, 104.0], 4) == pytest.approx(100.0)
    assert _rsi([100.0, 110.0, 100.0, 105.0, 104.0, 103.0], 4) == pytest.approx(29.4117647059)


def test_macd_histogram_calculation():
    histogram = _macd_histogram([1.0, 2.0, 3.0, 4.0, 5.0], fast_span=2, slow_span=3, signal_span=2)

    assert histogram == pytest.approx(0.0336934156)


def test_atr_bps_calculation():
    assert _atr_bps([11.0, 12.0, 14.0], [9.0, 10.0, 13.0], [10.0, 11.0, 13.0], 2) == pytest.approx(
        1923.0769230769
    )


def test_bollinger_width_percentile_calculation():
    percentile = _bollinger_width_percentile(
        [10.0, 12.0, 10.0, 10.0, 10.0],
        window_hours=2,
        percentile_window_hours=4,
        std_mult=2.0,
    )

    assert percentile == pytest.approx(50.0)


def test_dynamic_threshold_scales_hourly_volatility_to_momentum_horizon():
    closes = [100.0, 101.0, 100.0, 102.0, 101.0]
    returns = [math.log(closes[index] / closes[index - 1]) for index in range(1, len(closes))]
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / len(returns)
    realized_vol = math.sqrt(variance)
    threshold = 0.012 * (0.5 + (realized_vol / 0.015) * 0.5)

    threshold_bps = _dynamic_threshold_bps(
        closes,
        vol_lookback_hours=4,
        base_threshold=0.012,
        target_volatility=0.015,
        floor=0.006,
        ceiling=0.025,
    )

    assert threshold_bps == pytest.approx(min(max(threshold, 0.006), 0.025) * 10_000.0)


def test_generate_decisions_returns_empty_for_empty_input():
    assert generate_decisions([], {}) == []


def test_validate_params_returns_typed_defaults():
    parsed = validate_params({})

    assert parsed["symbols"] == ("BTC-PERP", "ETH-PERP", "SOL-PERP")
    assert parsed["min_votes"] == 4
    assert isinstance(parsed["min_votes"], int)
    assert parsed["base_position_pct"] == pytest.approx(0.08)
    assert isinstance(parsed["base_position_pct"], float)
    assert parsed["vol_lookback_hours"] == 48


def test_validate_params_normalizes_aliases_and_valid_overrides():
    parsed = validate_params(
        {
            "symbols": ["BTC-PERP", "ETH-PERP"],
            "min_votes": "5",
            "base_position_pct": "0.17",
            "decision_lag_minutes": "0",
            "dynamic_threshold_window_hours": "24",
            "bb_percentile_threshold": "80.0",
        }
    )

    assert parsed["symbols"] == ("BTC-PERP", "ETH-PERP")
    assert parsed["min_votes"] == 5
    assert parsed["base_position_pct"] == pytest.approx(0.17)
    assert parsed["decision_lag_minutes"] == 0
    assert parsed["vol_lookback_hours"] == 24
    assert "dynamic_threshold_window_hours" not in parsed
    assert parsed["bb_percentile_threshold"] == pytest.approx(80.0)


def test_validate_params_rejects_invalid_and_unknown_values():
    with pytest.raises(ValueError, match="min_votes"):
        validate_params({"min_votes": 7})
    with pytest.raises(ValueError, match="symbols"):
        validate_params({"symbols": []})
    with pytest.raises(ValueError, match="unknown params: typo"):
        validate_params({"typo": 1})


def test_generate_decisions_preserves_behavior_with_validated_params():
    rows = trend_rows(direction=1)
    raw_params = params(base_position_pct="0.17", dynamic_threshold_window_hours="48")

    assert generate_decisions(rows, validate_params(raw_params)) == generate_decisions(
        rows, raw_params
    )


def test_generate_decisions_requires_ohlc_and_timezone_aware_timestamps():
    with pytest.raises(ValueError, match="missing required"):
        generate_decisions([{"symbol": "BTC-PERP", "timestamp": START}], params())

    row = hourly_bar("BTC-PERP", 0, 100.0)
    row["timestamp"] = datetime(2024, 1, 1)
    with pytest.raises(ValueError, match="timezone-aware"):
        generate_decisions([row], params())


def test_generate_decisions_rejects_duplicate_symbol_timestamps():
    rows = [hourly_bar("BTC-PERP", 0, 100.0), hourly_bar("BTC-PERP", 0, 101.0)]

    with pytest.raises(ValueError, match="duplicate rows for BTC-PERP"):
        generate_decisions(rows, params())


def test_generate_decisions_emits_bullish_four_of_six_vote_decision():
    decisions = generate_decisions(trend_rows(direction=1), params())

    first = next(
        decision
        for decision in decisions
        if decision.metadata["momentum_12h_bps"] > decision.metadata["dynamic_threshold_bps"]
    )
    metadata = dict(first.metadata)
    assert first.strategy_id == "crypto_perp_multivote_trend_following"
    assert first.instrument.symbol == "BTC-PERP"
    assert first.target.direction == "long"
    assert metadata["signal_family"] == "crypto_perp_multivote_trend_following"
    assert metadata["long_votes"] >= 4
    assert metadata["short_votes"] < metadata["long_votes"]
    assert metadata["momentum_12h_bps"] > metadata["dynamic_threshold_bps"]
    assert metadata["momentum_6h_bps"] > 0.5 * metadata["dynamic_threshold_bps"]
    assert metadata["ema_fast"] > metadata["ema_slow"]
    assert metadata["rsi"] > 50.0
    assert metadata["macd_histogram"] > 0.0
    assert metadata["stateful_rsi_exit_supported"] is False
    assert metadata["signal_flip_supported"] is False
    assert metadata["upstream_defaults"]["TAKE_PROFIT_PCT"] == 99.0


def test_generate_decisions_emits_bearish_four_of_six_vote_decision():
    decisions = generate_decisions(trend_rows(direction=-1), params())

    first = next(
        decision
        for decision in decisions
        if decision.target.direction == "short"
        and decision.metadata["momentum_12h_bps"] < -decision.metadata["dynamic_threshold_bps"]
    )
    metadata = dict(first.metadata)
    assert first.target.direction == "short"
    assert metadata["short_votes"] >= 4
    assert metadata["long_votes"] < metadata["short_votes"]
    assert metadata["momentum_12h_bps"] < -metadata["dynamic_threshold_bps"]
    assert metadata["momentum_6h_bps"] < -0.5 * metadata["dynamic_threshold_bps"]
    assert metadata["ema_fast"] < metadata["ema_slow"]
    assert metadata["rsi"] < 50.0
    assert metadata["macd_histogram"] < 0.0


def test_generate_decisions_splits_portfolio_budget_across_configured_symbols():
    symbols = ["BTC-PERP", "ETH-PERP", "SOL-PERP"]
    rows = [row for symbol in symbols for row in trend_rows(symbol=symbol, direction=1)]

    decisions = generate_decisions(rows, params(symbols=symbols))
    first_by_symbol = {decision.instrument.symbol: decision for decision in decisions}

    assert set(first_by_symbol) == set(symbols)
    for decision in first_by_symbol.values():
        assert decision.target.size == pytest.approx(0.08 / 3.0)
        assert decision.metadata["portfolio_budget_pct"] == pytest.approx(0.08)
        assert decision.metadata["symbol_weight_fraction"] == pytest.approx(1.0 / 3.0)
        assert decision.metadata["effective_target_weight"] == pytest.approx(0.08 / 3.0)


def test_generate_decisions_waits_for_sufficient_lookback_history():
    assert generate_decisions(trend_rows(hours=30), params()) == []


def test_generate_decisions_does_not_require_future_hold_window_rows():
    rows = trend_rows(direction=1, hours=70)

    assert generate_decisions(rows, params(max_hold_bars=1))
    assert generate_decisions(rows, params(max_hold_bars=40))


def test_generate_decisions_are_stable_when_future_rows_after_boundary_are_removed():
    rows = trend_rows(direction=1, hours=90)
    decisions = generate_decisions(rows, params(max_hold_bars=1, cooldown_bars=0))
    boundary = decisions[0].as_of_time
    truncated_rows = [row for row in rows if row["timestamp"] <= boundary]

    truncated_decisions = generate_decisions(
        truncated_rows, params(max_hold_bars=1, cooldown_bars=0)
    )

    assert [
        decision for decision in decisions if decision.as_of_time <= boundary
    ] == truncated_decisions


def test_generate_decisions_builds_hourly_snapshots_from_minute_rows():
    decisions = generate_decisions(minute_rows(hours=80), params())

    assert decisions
    assert all(decision.as_of_time.minute == 0 for decision in decisions)


def test_generate_decisions_uses_causal_observations_that_pass_data_audit():
    rows = trend_rows(direction=1)
    decisions = generate_decisions(rows, params())

    assert all(
        observation.timestamp <= decision.as_of_time
        for decision in decisions
        for observation in decision.observations
    )
    assert audit_decision_rows(auditable_rows(rows), decisions).passed is True


def test_generate_decisions_consumes_optional_funding_rate_when_present():
    rows = trend_rows(direction=1)
    rows[66]["funding_rate"] = 0.0002

    decision = next(
        decision
        for decision in generate_decisions(rows, params())
        if decision.metadata.get("latest_funding_rate") is not None
    )

    assert decision.metadata["latest_funding_rate"] == pytest.approx(0.0002)
    assert any(observation.field == "funding_rate" for observation in decision.observations)


def test_generate_decisions_suppresses_overlapping_entries_and_applies_cooldown():
    decisions = generate_decisions(
        trend_rows(direction=1), params(max_hold_bars=1, cooldown_bars=2)
    )
    gaps = [
        int((current.as_of_time - previous.as_of_time).total_seconds() / 3600)
        for previous, current in zip(decisions, decisions[1:])
    ]

    assert decisions
    assert all(gap >= 3 for gap in gaps)


def test_generate_decisions_suppresses_same_symbol_overlap_for_assumed_hold_window():
    max_hold_bars = 12
    decisions = generate_decisions(
        trend_rows(direction=1, hours=140), params(max_hold_bars=max_hold_bars, cooldown_bars=0)
    )
    gaps = [
        int((current.as_of_time - previous.as_of_time).total_seconds() / 3600)
        for previous, current in zip(decisions, decisions[1:])
    ]

    assert len(decisions) > 1
    assert all(gap > max_hold_bars for gap in gaps)
    assert {decision.metadata["same_symbol_overlap_policy"] for decision in decisions} == {
        "suppress_until_assumed_hold_window_end"
    }


def test_generate_decisions_applies_param_overrides_to_votes_sizing_and_exit():
    rows = trend_rows(direction=1)

    assert generate_decisions(rows, params(min_votes=6, bb_percentile_threshold=0.0)) == []

    decision = generate_decisions(
        rows,
        params(
            min_votes=5,
            bb_percentile_threshold=0.0,
            base_position_pct=0.17,
            max_hold_bars=5,
            atr_stop_mult=2.0,
        ),
    )[0]

    assert decision.target.size == pytest.approx(0.17)
    assert decision.exit_policy.max_hold_bars == 5
    assert decision.exit_policy.trailing_stop_bps == pytest.approx(
        decision.metadata["atr_bps"] * 2.0
    )
    assert decision.metadata["min_votes"] == 5


def test_generate_decisions_rejects_invalid_position_budget():
    with pytest.raises(ValueError, match="base_position_pct must be finite and positive"):
        generate_decisions(trend_rows(), params(base_position_pct=0.0))


def test_generate_decisions_rejects_invalid_dynamic_threshold_bounds():
    with pytest.raises(ValueError, match="dynamic_threshold_floor"):
        generate_decisions(
            trend_rows(),
            params(dynamic_threshold_floor=0.02, dynamic_threshold_ceiling=0.01),
        )
