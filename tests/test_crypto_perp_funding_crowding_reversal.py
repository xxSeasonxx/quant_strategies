from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from untested.crypto_perp_funding_crowding_reversal import generate_decisions, validate_params

from quant_strategies.core.data_audit import audit_decision_rows
from quant_strategies.decisions import StrategyDecision

START = datetime(2024, 1, 1, tzinfo=UTC)


def bar(
    symbol: str,
    minute: int,
    close: float,
    *,
    funding_rate: float | None = None,
    funding_minute: int | None = None,
    has_funding_event: bool = False,
) -> dict[str, object]:
    return {
        "symbol": symbol,
        "timestamp": START + timedelta(minutes=minute),
        "close": close,
        "funding_timestamp": START + timedelta(minutes=funding_minute)
        if funding_minute is not None
        else None,
        "funding_rate": funding_rate,
        "has_funding_event": has_funding_event,
    }


def symbol_rows(
    symbol: str,
    base_close: float,
    observed_close: float,
    decision_close: float,
    funding_rate: float,
):
    return [
        bar(symbol, 0, base_close),
        bar(
            symbol,
            9,
            observed_close,
            funding_rate=funding_rate,
            funding_minute=9,
            has_funding_event=True,
        ),
        bar(symbol, 10, decision_close),
    ]


def params(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "decision_interval_minutes": 10,
        "return_lookback_minutes": 10,
        "funding_lookback_events": 1,
        "top_n": 1,
        "min_cross_section": 4,
        "min_abs_funding_bps": 1.0,
        "min_abs_return_bps": 25.0,
        "weight": 0.25,
        "max_hold_bars": 3,
    }
    values.update(overrides)
    return values


def decision_payload(decision: StrategyDecision) -> dict[str, object]:
    payload: dict[str, object] = {
        "symbol": decision.instrument.symbol,
        "decision_time": decision.decision_time,
        "as_of_time": decision.as_of_time,
        "side": decision.target.direction,
        "weight": decision.target.size,
        "max_hold_bars": decision.exit_policy.max_hold_bars,
        **dict(decision.metadata),
    }
    for field in ("take_profit_bps", "stop_loss_bps", "trailing_stop_bps"):
        value = getattr(decision.exit_policy, field)
        if value is not None:
            payload[field] = value
    return payload


def generate_payloads(
    bars: list[dict[str, object]], params: dict[str, object]
) -> list[dict[str, object]]:
    return [decision_payload(decision) for decision in generate_decisions(bars, params)]


def auditable_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return [{**row, "available_at": row["timestamp"]} for row in rows]


def test_generate_decisions_returns_empty_for_empty_input():
    assert generate_decisions([], {}) == []


def test_validate_params_returns_typed_defaults():
    parsed = validate_params({})

    assert parsed["funding_lookback_events"] == 3
    assert isinstance(parsed["funding_lookback_events"], int)
    assert parsed["return_lookback_minutes"] == 240
    assert parsed["decision_lag_minutes"] == 1
    assert parsed["weight"] == pytest.approx(1.0)
    assert isinstance(parsed["weight"], float)
    assert parsed["session_start_hour"] == 0
    assert parsed["session_end_hour"] == 24


def test_validate_params_normalizes_valid_overrides():
    parsed = validate_params(
        {
            "funding_lookback_events": "2",
            "return_lookback_minutes": "30",
            "decision_interval_minutes": "15",
            "decision_lag_minutes": "0",
            "top_n": "2",
            "min_cross_section": "3",
            "min_abs_funding_bps": "0.5",
            "min_abs_return_bps": "10.25",
            "weight": "0.25",
            "max_hold_bars": "6",
            "take_profit_bps": "12.5",
            "session_start_hour": "1",
            "session_end_hour": "23",
        }
    )

    assert parsed["funding_lookback_events"] == 2
    assert parsed["decision_lag_minutes"] == 0
    assert parsed["weight"] == pytest.approx(0.25)
    assert parsed["take_profit_bps"] == pytest.approx(12.5)
    assert parsed["session_start_hour"] == 1
    assert parsed["session_end_hour"] == 23


def test_validate_params_rejects_invalid_and_unknown_values():
    with pytest.raises(ValueError, match="funding_lookback_events"):
        validate_params({"funding_lookback_events": 0})
    with pytest.raises(ValueError, match="session_start_hour"):
        validate_params({"session_start_hour": 24})
    with pytest.raises(ValueError, match="session_end_hour"):
        validate_params({"session_start_hour": 12, "session_end_hour": 12})
    with pytest.raises(ValueError, match="unknown params: typo"):
        validate_params({"typo": 1})


def test_generate_decisions_preserves_behavior_with_validated_params():
    bars = symbol_rows("BTC-PERP", 100.0, 101.0, 102.0, 0.0003)
    raw_params = params(min_cross_section="1", weight="0.25", max_hold_bars="3")

    assert generate_payloads(bars, validate_params(raw_params)) == generate_payloads(
        bars, raw_params
    )


def test_generate_decisions_requires_expected_crypto_fields():
    with pytest.raises(ValueError, match="missing required"):
        generate_decisions([{"symbol": "BTC-PERP", "timestamp": START}], params())


def test_generate_decisions_fades_same_direction_funding_and_return_extremes():
    bars = (
        symbol_rows("BTC-PERP", 100.0, 101.0, 102.0, 0.0002)
        + symbol_rows("ETH-PERP", 100.0, 99.0, 98.0, -0.0002)
        + symbol_rows("SOL-PERP", 100.0, 99.0, 99.0, 0.0002)
        + symbol_rows("XRP-PERP", 100.0, 101.0, 101.0, 0.00005)
    )

    signals = sorted(generate_payloads(bars, params()), key=lambda item: str(item["symbol"]))

    assert signals == [
        {
            "symbol": "BTC-PERP",
            "decision_time": START + timedelta(minutes=11),
            "as_of_time": START + timedelta(minutes=10),
            "side": "short",
            "weight": 0.25,
            "max_hold_bars": 3,
            "funding_pressure_bps": pytest.approx(2.0),
            "entry_return_extension_bps": pytest.approx(100.0),
            "signal_family": "crypto_perp_funding_crowding_reversal",
        },
        {
            "symbol": "ETH-PERP",
            "decision_time": START + timedelta(minutes=11),
            "as_of_time": START + timedelta(minutes=10),
            "side": "long",
            "weight": 0.25,
            "max_hold_bars": 3,
            "funding_pressure_bps": pytest.approx(-2.0),
            "entry_return_extension_bps": pytest.approx(-100.0),
            "signal_family": "crypto_perp_funding_crowding_reversal",
        },
    ]


def test_generate_decisions_emits_close_and_funding_observation_lineage():
    bars = symbol_rows("BTC-PERP", 100.0, 101.0, 102.0, 0.0003)
    decisions = generate_decisions(bars, params(min_cross_section=1))
    observed = {
        (item.symbol, item.timestamp, item.field, item.source) for item in decisions[0].observations
    }

    assert observed == {
        ("BTC-PERP", START, "close", "strategy_input"),
        ("BTC-PERP", START + timedelta(minutes=9), "close", "strategy_input"),
        ("BTC-PERP", START + timedelta(minutes=9), "funding_timestamp", "strategy_input"),
        ("BTC-PERP", START + timedelta(minutes=9), "funding_rate", "strategy_input"),
        ("BTC-PERP", START + timedelta(minutes=9), "has_funding_event", "strategy_input"),
    }
    assert audit_decision_rows(auditable_rows(bars), decisions).passed is True


def test_crypto_lineage_audit_fails_for_missing_or_late_observed_rows():
    bars = symbol_rows("BTC-PERP", 100.0, 101.0, 102.0, 0.0003)
    decisions = generate_decisions(bars, params(min_cross_section=1))
    missing_rows = [
        row for row in auditable_rows(bars) if row["timestamp"] != START + timedelta(minutes=9)
    ]
    late_rows = auditable_rows(bars)
    for row in late_rows:
        if row["timestamp"] == START + timedelta(minutes=9):
            row["available_at"] = decisions[0].decision_time + timedelta(minutes=1)

    missing_audit = audit_decision_rows(missing_rows, decisions)
    late_audit = audit_decision_rows(late_rows, decisions)

    assert missing_audit.passed is False
    assert any("missing observation row" in violation for violation in missing_audit.violations)
    assert late_audit.passed is False
    assert any(
        "was available after decision_time" in violation for violation in late_audit.violations
    )


def test_generate_decisions_enforces_minimum_cross_section():
    bars = (
        symbol_rows("BTC-PERP", 100.0, 101.0, 101.0, 0.0002)
        + symbol_rows("ETH-PERP", 100.0, 99.0, 99.0, -0.0002)
        + symbol_rows("SOL-PERP", 100.0, 101.0, 101.0, 0.0002)
    )

    assert generate_decisions(bars, params(min_cross_section=4)) == []


def test_generate_decisions_uses_completed_prior_close_not_decision_close():
    bars = symbol_rows("BTC-PERP", 100.0, 100.0, 200.0, 0.0003)

    assert generate_decisions(bars, params(min_cross_section=1)) == []


def test_generate_decisions_allows_explicit_zero_decision_lag():
    bars = symbol_rows("BTC-PERP", 100.0, 101.0, 102.0, 0.0003)

    signals = generate_payloads(bars, params(min_cross_section=1, decision_lag_minutes=0))

    assert signals[0]["decision_time"] == START + timedelta(minutes=10)
    assert signals[0]["as_of_time"] == START + timedelta(minutes=10)


def test_generate_decisions_excludes_future_funding_events():
    bars = [
        bar("BTC-PERP", 0, 100.0),
        bar("BTC-PERP", 9, 101.0, funding_rate=0.0003, funding_minute=20, has_funding_event=True),
        bar("BTC-PERP", 10, 101.0),
    ]

    assert generate_decisions(bars, params(min_cross_section=1)) == []


def test_generate_decisions_requires_complete_funding_lookback():
    bars = symbol_rows("BTC-PERP", 100.0, 101.0, 101.0, 0.0003)

    assert generate_decisions(bars, params(min_cross_section=1, funding_lookback_events=2)) == []


def test_generate_decisions_emits_optional_exit_controls():
    bars = symbol_rows("BTC-PERP", 100.0, 101.0, 102.0, 0.0003)

    signals = generate_payloads(
        bars,
        params(
            min_cross_section=1,
            max_hold_bars=7,
            take_profit_bps=150.0,
            stop_loss_bps=80.0,
            trailing_stop_bps=40.0,
        ),
    )

    assert signals[0]["max_hold_bars"] == 7
    assert signals[0]["take_profit_bps"] == 150.0
    assert signals[0]["stop_loss_bps"] == 80.0
    assert signals[0]["trailing_stop_bps"] == 40.0
