from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from tests.candidate_loader import load_candidate_strategy

from quant_strategies.core.data_audit import audit_decision_rows
from quant_strategies.core.engine_runner import build_request, evaluate_request
from quant_strategies.decisions import StrategyDecision
from quant_strategies.runner.config import CostModelConfig, FillModelConfig

strategy = load_candidate_strategy("krohn_mueller_whelan_fix_reversal")
generate_decisions = strategy.generate_decisions
validate_params = strategy.validate_params

FIXES = {
    "tokyo": ("Asia/Tokyo", time(9, 55)),
    "frankfurt": ("Europe/Berlin", time(14, 15)),
    "london": ("Europe/London", time(16, 0)),
}


def fix_utc(local_date: date, fix_name: str) -> datetime:
    zone_name, local_time = FIXES[fix_name]
    local_fix = datetime.combine(local_date, local_time, tzinfo=ZoneInfo(zone_name))
    return local_fix.astimezone(UTC)


def decision_time(local_date: date, fix_name: str, lead_minutes: int = 2) -> datetime:
    return fix_utc(local_date, fix_name) - timedelta(minutes=lead_minutes)


def as_of_time(local_date: date, fix_name: str) -> datetime:
    return decision_time(local_date, fix_name) - timedelta(minutes=1)


def signal_times(local_date: date, fix_name: str) -> list[datetime]:
    return [as_of_time(local_date, fix_name), decision_time(local_date, fix_name)]


def quote_row(symbol: str, timestamp: datetime, mid: float = 1.25) -> dict[str, object]:
    return {
        "symbol": symbol,
        "timestamp": timestamp,
        "open": mid,
        "high": mid,
        "low": mid,
        "close": mid,
        "bid": mid * 0.9999,
        "ask": mid * 1.0001,
        "mid": mid,
    }


def rows_for(symbols: list[str], timestamps: list[datetime]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for timestamp in timestamps:
        for symbol in symbols:
            rows.append(quote_row(symbol, timestamp, 150.0 if symbol.endswith("JPY") else 1.25))
    return rows


def payload(decision: StrategyDecision) -> dict[str, object]:
    result: dict[str, object] = {
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
            result[field] = value
    return result


def payloads(
    rows: list[dict[str, object]], params: dict[str, object] | None = None
) -> list[dict[str, object]]:
    return [payload(decision) for decision in generate_decisions(rows, params or {})]


def auditable_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return [{**row, "available_at": row["timestamp"] + timedelta(minutes=1)} for row in rows]


def test_generate_decisions_returns_empty_for_empty_input():
    assert generate_decisions([], {}) == []


def test_validate_params_returns_typed_defaults():
    parsed = validate_params({})

    assert parsed["decision_lead_minutes"] == 2
    assert isinstance(parsed["decision_lead_minutes"], int)
    assert parsed["observation_lag_minutes"] == 1
    assert parsed["weight"] == pytest.approx(1.0)
    assert isinstance(parsed["weight"], float)
    assert parsed["max_hold_bars"] == 2


def test_validate_params_normalizes_valid_overrides():
    parsed = validate_params(
        {
            "decision_lead_minutes": "3",
            "observation_lag_minutes": "2",
            "weight": "0.5",
            "max_hold_bars": "5",
            "stop_loss_bps": "8.5",
        }
    )

    assert parsed["decision_lead_minutes"] == 3
    assert parsed["observation_lag_minutes"] == 2
    assert parsed["weight"] == pytest.approx(0.5)
    assert parsed["max_hold_bars"] == 5
    assert parsed["stop_loss_bps"] == pytest.approx(8.5)


def test_validate_params_rejects_invalid_and_unknown_values():
    with pytest.raises(ValueError, match="decision_lead_minutes"):
        validate_params({"decision_lead_minutes": 0})
    with pytest.raises(ValueError, match="weight"):
        validate_params({"weight": 0.0})
    with pytest.raises(ValueError, match="unknown params: typo"):
        validate_params({"typo": 1})


def test_generate_decisions_preserves_behavior_with_validated_params():
    rows = rows_for(["EURUSD"], signal_times(date(2024, 7, 1), "london"))
    raw_params = {"weight": "0.5", "max_hold_bars": "2"}

    assert payloads(rows, validate_params(raw_params)) == payloads(rows, raw_params)


def test_generate_decisions_requires_symbol_timestamp_and_mid():
    row = quote_row("EURUSD", decision_time(date(2024, 7, 1), "london"))
    del row["mid"]

    with pytest.raises(ValueError, match="missing required fields"):
        generate_decisions([row], {})


def test_generate_decisions_rejects_duplicate_symbol_timestamp_rows():
    timestamp = decision_time(date(2024, 7, 1), "london")
    rows = [quote_row("EURUSD", timestamp), quote_row("EURUSD", timestamp)]

    with pytest.raises(ValueError, match="duplicate"):
        generate_decisions(rows, {})


def test_generate_decisions_rejects_naive_timestamps():
    row = quote_row("EURUSD", datetime(2024, 7, 1, 14, 58))

    with pytest.raises(ValueError, match="timezone-aware"):
        generate_decisions([row], {})


def test_generate_decisions_uses_paper_fix_times_and_dst_offsets():
    local_date = date(2024, 7, 1)
    rows = rows_for(
        ["EURUSD"],
        signal_times(local_date, "tokyo")
        + signal_times(local_date, "frankfurt")
        + signal_times(local_date, "london"),
    )

    signals = payloads(rows, {"weight": 0.5, "max_hold_bars": 2})

    assert signals == [
        {
            "symbol": "EURUSD",
            "decision_time": datetime(2024, 7, 1, 0, 53, tzinfo=UTC),
            "as_of_time": datetime(2024, 7, 1, 0, 52, tzinfo=UTC),
            "side": "long",
            "weight": 0.5,
            "max_hold_bars": 2,
            "signal_family": "krohn_mueller_whelan_fix_reversal",
            "fix_name": "tokyo",
            "fix_local_time": "2024-07-01T09:55:00+09:00",
            "fix_utc_time": "2024-07-01T00:55:00+00:00",
            "usd_side": "sell",
            "entry_window_minutes": 1,
        },
        {
            "symbol": "EURUSD",
            "decision_time": datetime(2024, 7, 1, 12, 13, tzinfo=UTC),
            "as_of_time": datetime(2024, 7, 1, 12, 12, tzinfo=UTC),
            "side": "long",
            "weight": 0.5,
            "max_hold_bars": 2,
            "signal_family": "krohn_mueller_whelan_fix_reversal",
            "fix_name": "frankfurt",
            "fix_local_time": "2024-07-01T14:15:00+02:00",
            "fix_utc_time": "2024-07-01T12:15:00+00:00",
            "usd_side": "sell",
            "entry_window_minutes": 1,
        },
        {
            "symbol": "EURUSD",
            "decision_time": datetime(2024, 7, 1, 14, 58, tzinfo=UTC),
            "as_of_time": datetime(2024, 7, 1, 14, 57, tzinfo=UTC),
            "side": "long",
            "weight": 0.5,
            "max_hold_bars": 2,
            "signal_family": "krohn_mueller_whelan_fix_reversal",
            "fix_name": "london",
            "fix_local_time": "2024-07-01T16:00:00+01:00",
            "fix_utc_time": "2024-07-01T15:00:00+00:00",
            "usd_side": "sell",
            "entry_window_minutes": 1,
        },
    ]


def test_generate_decisions_uses_winter_frankfurt_and_london_offsets():
    local_date = date(2024, 1, 8)
    rows = rows_for(
        ["EURUSD"],
        signal_times(local_date, "frankfurt") + signal_times(local_date, "london"),
    )

    by_fix = {signal["fix_name"]: signal for signal in payloads(rows)}

    assert by_fix["frankfurt"]["fix_utc_time"] == "2024-01-08T13:15:00+00:00"
    assert by_fix["frankfurt"]["fix_local_time"] == "2024-01-08T14:15:00+01:00"
    assert by_fix["london"]["fix_utc_time"] == "2024-01-08T16:00:00+00:00"
    assert by_fix["london"]["fix_local_time"] == "2024-01-08T16:00:00+00:00"


def test_generate_decisions_maps_usd_sell_side_for_quote_convention():
    rows = rows_for(["EURUSD", "USDJPY"], signal_times(date(2024, 7, 1), "london"))

    sides = {signal["symbol"]: signal["side"] for signal in payloads(rows)}

    assert sides == {"EURUSD": "long", "USDJPY": "short"}


def test_generate_decisions_skips_missing_basket_symbols():
    signals = payloads(rows_for(["EURUSD"], signal_times(date(2024, 7, 1), "london")))

    assert [signal["symbol"] for signal in signals] == ["EURUSD"]


def test_generate_decisions_emits_from_as_of_quote_without_decision_time_quote():
    rows = rows_for(["EURUSD"], [as_of_time(date(2024, 7, 1), "london")])

    decisions = generate_decisions(rows, {})

    assert len(decisions) == 1
    assert decisions[0].instrument.symbol == "EURUSD"
    assert decisions[0].decision_time == decision_time(date(2024, 7, 1), "london")
    assert decisions[0].as_of_time == as_of_time(date(2024, 7, 1), "london")
    assert audit_decision_rows(auditable_rows(rows), decisions).passed is True


def test_generate_decisions_emits_mid_observation_lineage():
    timestamp = as_of_time(date(2024, 7, 1), "london")
    rows = rows_for(["EURUSD"], signal_times(date(2024, 7, 1), "london"))
    decisions = generate_decisions(rows, {})

    assert len(decisions[0].observations) == 1
    assert decisions[0].observations[0].symbol == "EURUSD"
    assert decisions[0].observations[0].timestamp == timestamp
    assert decisions[0].observations[0].field == "mid"
    assert decisions[0].observations[0].source == "strategy_input"
    assert audit_decision_rows(auditable_rows(rows), decisions).passed is True


def test_quote_fill_timing_enters_before_and_exits_after_fix():
    fix_time = fix_utc(date(2024, 7, 1), "london")
    rows = [
        quote_row("EURUSD", fix_time - timedelta(minutes=3), 1.1010),
        quote_row("EURUSD", fix_time - timedelta(minutes=2), 1.1000),
        quote_row("EURUSD", fix_time - timedelta(minutes=1), 1.0990),
        quote_row("EURUSD", fix_time, 1.0980),
        quote_row("EURUSD", fix_time + timedelta(minutes=1), 1.1010),
    ]
    decisions = generate_decisions(rows, {"max_hold_bars": 2})

    request = build_request(
        strategy_id="krohn_mueller_whelan_fix_reversal",
        rows=rows,
        decisions=decisions,
        fill_model=FillModelConfig(price="quote", entry_lag_bars=1, exit_lag_bars=0),
        cost_model=CostModelConfig(fee_bps_per_side=0.0, slippage_bps_per_side=0.0),
    )
    run = evaluate_request(request, mode="screen")
    trade = run.screen_summary["trades"][0]

    assert trade["decision_time"] == "2024-07-01T14:58:00Z"
    assert trade["entry_time"] == "2024-07-01T14:59:00Z"
    assert trade["exit_time"] == "2024-07-01T15:01:00Z"


def test_generate_decisions_emits_optional_exit_controls():
    signals = payloads(
        rows_for(["EURUSD"], signal_times(date(2024, 7, 1), "london")),
        {
            "max_hold_bars": 5,
            "take_profit_bps": 12.0,
            "stop_loss_bps": 8.0,
            "trailing_stop_bps": 4.0,
        },
    )

    assert signals[0]["max_hold_bars"] == 5
    assert signals[0]["take_profit_bps"] == 12.0
    assert signals[0]["stop_loss_bps"] == 8.0
    assert signals[0]["trailing_stop_bps"] == 4.0
