from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from tests.candidate_loader import load_candidate_strategy

from quant_strategies.core.data_audit import audit_decision_rows
from quant_strategies.core.engine_runner import build_request, evaluate_request
from quant_strategies.decisions import StrategyDecision
from quant_strategies.runner.config import CostModelConfig, FillModelConfig

strategy = load_candidate_strategy("fx_session_activity_profile_rejection")
generate_decisions = strategy.generate_decisions
validate_params = strategy.validate_params

DAY = datetime(2024, 1, 2, tzinfo=UTC)
ASIA_START = DAY - timedelta(hours=2)


def fx_row(
    timestamp: datetime,
    close: float,
    *,
    symbol: str = "EURUSD",
    volume: float = 100.0,
    high: float | None = None,
    low: float | None = None,
    relative_spread: float = 0.00005,
    has_quote: bool = True,
) -> dict[str, object]:
    bid = close - 0.00005
    ask = close + 0.00005
    return {
        "symbol": symbol,
        "timestamp": timestamp,
        "available_at": timestamp + timedelta(minutes=1),
        "open": close,
        "high": close if high is None else high,
        "low": close if low is None else low,
        "close": close,
        "volume": volume,
        "bid": bid,
        "ask": ask,
        "mid": close,
        "spread": ask - bid,
        "relative_spread": relative_spread,
        "has_quote": has_quote,
    }


def asia_profile_rows(*, symbol: str = "EURUSD") -> list[dict[str, object]]:
    return [
        fx_row(ASIA_START + timedelta(minutes=0), 1.0990, symbol=symbol, volume=250.0),
        fx_row(ASIA_START + timedelta(minutes=1), 1.1000, symbol=symbol, volume=1000.0),
        fx_row(ASIA_START + timedelta(minutes=2), 1.1000, symbol=symbol, volume=900.0),
        fx_row(ASIA_START + timedelta(minutes=3), 1.1010, symbol=symbol, volume=250.0),
    ]


def asia_profile_rows_with_upper_lvn(*, symbol: str = "EURUSD") -> list[dict[str, object]]:
    return [
        fx_row(ASIA_START + timedelta(minutes=0), 1.0990, symbol=symbol, volume=800.0),
        fx_row(ASIA_START + timedelta(minutes=1), 1.1000, symbol=symbol, volume=1000.0),
        fx_row(ASIA_START + timedelta(minutes=2), 1.1010, symbol=symbol, volume=900.0),
        fx_row(ASIA_START + timedelta(minutes=3), 1.1000, symbol=symbol, volume=950.0),
    ]


def decision_baseline_rows(*, symbol: str = "EURUSD") -> list[dict[str, object]]:
    return [
        fx_row(DAY + timedelta(hours=7, minutes=0), 1.1001, symbol=symbol, volume=100.0),
        fx_row(DAY + timedelta(hours=7, minutes=1), 1.1002, symbol=symbol, volume=120.0),
    ]


def params(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "profile_bin_count": 10,
        "min_profile_bars": 4,
        "min_activity_observations": 2,
        "activity_window_bars": 10,
        "min_activity_z": 1.0,
        "max_spread_percentile": 1.0,
        "acceptance_confirm_bars": 2,
        "rejection_lookback_bars": 60,
        "decision_lag_minutes": 1,
        "weight": 0.25,
        "max_hold_bars": 3,
    }
    values.update(overrides)
    return values


def decision_payload(decision: StrategyDecision) -> dict[str, object]:
    return {
        "symbol": decision.instrument.symbol,
        "decision_time": decision.decision_time,
        "as_of_time": decision.as_of_time,
        "side": decision.target.direction,
        "weight": decision.target.size,
        "max_hold_bars": decision.exit_policy.max_hold_bars,
        **dict(decision.metadata),
    }


def assert_payload_contains(payload: dict[str, object], expected: dict[str, object]) -> None:
    for key, value in expected.items():
        assert payload[key] == value


def assert_profile_extrema_metadata(payload: dict[str, object]) -> None:
    assert payload["profile_upper_lvn"] is not None
    assert payload["profile_lower_lvn"] is not None
    assert payload["profile_upper_hvn"] is not None
    assert payload["profile_lower_hvn"] is not None
    assert payload["profile_boundary"] is not None


def test_generate_decisions_returns_empty_for_empty_input():
    assert generate_decisions([], {}) == []


def test_validate_params_returns_typed_defaults():
    parsed = validate_params({})

    assert parsed["asia_start_hour"] == 22
    assert parsed["asia_end_hour"] == 7
    assert parsed["decision_start_hour"] == 7
    assert parsed["decision_end_hour"] == 10
    assert parsed["profile_bin_count"] == 40
    assert parsed["value_area_fraction"] == pytest.approx(0.70)
    assert parsed["enable_acceptance"] is True
    assert parsed["enable_rejection"] is True
    assert parsed["use_lvn_boundaries"] is True
    assert isinstance(parsed["weight"], float)


def test_validate_params_normalizes_valid_overrides():
    parsed = validate_params(
        {
            "profile_bin_count": "12",
            "value_area_fraction": "0.8",
            "min_profile_bars": "4",
            "min_activity_z": "1.25",
            "max_spread_percentile": "0.9",
            "enable_acceptance": False,
            "enable_rejection": True,
            "use_lvn_boundaries": False,
            "weight": "0.5",
            "max_hold_bars": "5",
        }
    )

    assert parsed["profile_bin_count"] == 12
    assert parsed["value_area_fraction"] == pytest.approx(0.8)
    assert parsed["min_activity_z"] == pytest.approx(1.25)
    assert parsed["max_spread_percentile"] == pytest.approx(0.9)
    assert parsed["enable_acceptance"] is False
    assert parsed["enable_rejection"] is True
    assert parsed["use_lvn_boundaries"] is False
    assert parsed["weight"] == pytest.approx(0.5)
    assert parsed["max_hold_bars"] == 5


def test_validate_params_rejects_invalid_and_unknown_values():
    with pytest.raises(ValueError, match="unknown params: typo"):
        validate_params({"typo": 1})
    with pytest.raises(ValueError, match="enable_acceptance"):
        validate_params({"enable_acceptance": "true"})
    with pytest.raises(ValueError, match="use_lvn_boundaries"):
        validate_params({"use_lvn_boundaries": "true"})
    with pytest.raises(ValueError, match="profile_bin_count"):
        validate_params({"profile_bin_count": 1})
    with pytest.raises(ValueError, match="value_area_fraction"):
        validate_params({"value_area_fraction": 1.5})
    with pytest.raises(ValueError, match="decision_lag_minutes"):
        validate_params({"decision_lag_minutes": 0})
    with pytest.raises(ValueError, match="asia_end_hour"):
        validate_params({"asia_start_hour": 8, "asia_end_hour": 24})


def test_generate_decisions_rejects_missing_required_fields():
    rows = asia_profile_rows() + decision_baseline_rows()
    rows.append({"symbol": "EURUSD", "timestamp": DAY + timedelta(hours=7, minutes=2)})

    with pytest.raises(ValueError, match="missing required fields"):
        generate_decisions(rows, params())


def test_acceptance_breakout_emits_long_decision_with_profile_metadata():
    rows = (
        asia_profile_rows()
        + decision_baseline_rows()
        + [
            fx_row(DAY + timedelta(hours=7, minutes=2), 1.1020, volume=500.0),
            fx_row(DAY + timedelta(hours=7, minutes=3), 1.1022, volume=520.0),
            fx_row(DAY + timedelta(hours=7, minutes=4), 1.1023, volume=100.0),
            fx_row(DAY + timedelta(hours=7, minutes=5), 1.1024, volume=100.0),
            fx_row(DAY + timedelta(hours=7, minutes=6), 1.1025, volume=100.0),
            fx_row(DAY + timedelta(hours=7, minutes=7), 1.1026, volume=100.0),
        ]
    )

    decisions = generate_decisions(rows, params(enable_rejection=False))
    payloads = [decision_payload(decision) for decision in decisions]

    assert len(payloads) == 1
    assert_payload_contains(
        payloads[0],
        {
            "symbol": "EURUSD",
            "decision_time": DAY + timedelta(hours=7, minutes=4),
            "as_of_time": DAY + timedelta(hours=7, minutes=3),
            "side": "long",
            "weight": 0.25,
            "max_hold_bars": 3,
            "signal_family": "fx_session_activity_profile_rejection",
            "rule": "acceptance_breakout",
            "session": "london_morning",
            "profile_poc": pytest.approx(1.1, abs=0.0003),
            "profile_vah": pytest.approx(1.1, abs=0.0008),
            "profile_val": pytest.approx(1.1, abs=0.0008),
            "activity_z": pytest.approx(39.0, rel=0.2),
            "relative_spread": pytest.approx(0.00005),
        },
    )
    assert_profile_extrema_metadata(payloads[0])


def test_failed_break_rejection_emits_short_decision_toward_value():
    rows = (
        asia_profile_rows()
        + decision_baseline_rows()
        + [
            fx_row(DAY + timedelta(hours=7, minutes=2), 1.1020, volume=500.0),
            fx_row(DAY + timedelta(hours=7, minutes=3), 1.1000, volume=520.0),
            fx_row(DAY + timedelta(hours=7, minutes=4), 1.0999, volume=100.0),
            fx_row(DAY + timedelta(hours=7, minutes=5), 1.0998, volume=100.0),
            fx_row(DAY + timedelta(hours=7, minutes=6), 1.0997, volume=100.0),
            fx_row(DAY + timedelta(hours=7, minutes=7), 1.0996, volume=100.0),
        ]
    )

    decisions = generate_decisions(rows, params(enable_acceptance=False))
    payloads = [decision_payload(decision) for decision in decisions]

    assert len(payloads) == 1
    assert_payload_contains(
        payloads[0],
        {
            "symbol": "EURUSD",
            "decision_time": DAY + timedelta(hours=7, minutes=4),
            "as_of_time": DAY + timedelta(hours=7, minutes=3),
            "side": "short",
            "weight": 0.25,
            "max_hold_bars": 3,
            "signal_family": "fx_session_activity_profile_rejection",
            "rule": "failed_break_rejection",
            "session": "london_morning",
            "profile_poc": pytest.approx(1.1, abs=0.0003),
            "profile_vah": pytest.approx(1.1, abs=0.0008),
            "profile_val": pytest.approx(1.1, abs=0.0008),
            "activity_z": pytest.approx(41.0, rel=0.2),
            "relative_spread": pytest.approx(0.00005),
        },
    )
    assert_profile_extrema_metadata(payloads[0])


def test_lvn_boundary_does_not_trigger_inside_value_area():
    rows = (
        asia_profile_rows_with_upper_lvn()
        + [
            fx_row(DAY + timedelta(hours=7, minutes=0), 1.0998, volume=100.0),
            fx_row(DAY + timedelta(hours=7, minutes=1), 1.1000, volume=120.0),
        ]
        + [
            fx_row(DAY + timedelta(hours=7, minutes=2), 1.1004, volume=500.0),
            fx_row(DAY + timedelta(hours=7, minutes=3), 1.1005, volume=520.0),
            fx_row(DAY + timedelta(hours=7, minutes=4), 1.1006, volume=100.0),
            fx_row(DAY + timedelta(hours=7, minutes=5), 1.1007, volume=100.0),
            fx_row(DAY + timedelta(hours=7, minutes=6), 1.1008, volume=100.0),
            fx_row(DAY + timedelta(hours=7, minutes=7), 1.1009, volume=100.0),
        ]
    )

    with_lvn = [
        decision_payload(decision)
        for decision in generate_decisions(
            rows,
            params(enable_rejection=False, use_lvn_boundaries=True),
        )
    ]
    without_lvn = [
        decision_payload(decision)
        for decision in generate_decisions(
            rows,
            params(enable_rejection=False, use_lvn_boundaries=False),
        )
    ]

    assert with_lvn == []
    assert len(without_lvn) == 1
    assert without_lvn[0]["profile_boundary"] == without_lvn[0]["profile_vah"]


def test_lvn_boundary_can_make_acceptance_stricter_outside_value_area():
    rows = (
        asia_profile_rows_with_upper_lvn()
        + decision_baseline_rows()
        + [
            fx_row(DAY + timedelta(hours=7, minutes=2), 1.1020, volume=500.0),
            fx_row(DAY + timedelta(hours=7, minutes=3), 1.1022, volume=520.0),
            fx_row(DAY + timedelta(hours=7, minutes=4), 1.1023, volume=100.0),
            fx_row(DAY + timedelta(hours=7, minutes=5), 1.1024, volume=100.0),
            fx_row(DAY + timedelta(hours=7, minutes=6), 1.1025, volume=100.0),
            fx_row(DAY + timedelta(hours=7, minutes=7), 1.1026, volume=100.0),
        ]
    )

    with_lvn = [
        decision_payload(decision)
        for decision in generate_decisions(
            rows,
            params(enable_rejection=False, use_lvn_boundaries=True),
        )
    ]

    assert len(with_lvn) == 1
    assert with_lvn[0]["rule"] == "acceptance_breakout"
    assert with_lvn[0]["profile_boundary"] == with_lvn[0]["profile_upper_lvn"]
    assert with_lvn[0]["profile_boundary"] >= with_lvn[0]["profile_vah"]


def test_profile_rows_exclude_future_rows_when_sessions_overlap_decision_window():
    future_profile_row = fx_row(
        DAY + timedelta(hours=6, minutes=59),
        1.5000,
        volume=10_000.0,
    )
    rows = [
        fx_row(DAY - timedelta(hours=2), 1.0990, volume=250.0),
        fx_row(DAY - timedelta(hours=1, minutes=59), 1.1000, volume=1000.0),
        fx_row(DAY - timedelta(hours=1, minutes=58), 1.1000, volume=900.0),
        fx_row(DAY + timedelta(hours=6), 1.1010, volume=250.0),
        fx_row(DAY + timedelta(hours=6, minutes=28), 1.1001, volume=100.0),
        fx_row(DAY + timedelta(hours=6, minutes=29), 1.1002, volume=120.0),
        fx_row(DAY + timedelta(hours=6, minutes=30), 1.1020, volume=500.0),
        fx_row(DAY + timedelta(hours=6, minutes=31), 1.1022, volume=520.0),
        future_profile_row,
        fx_row(DAY + timedelta(hours=6, minutes=32), 1.1023, volume=100.0),
        fx_row(DAY + timedelta(hours=6, minutes=33), 1.1024, volume=100.0),
        fx_row(DAY + timedelta(hours=6, minutes=34), 1.1025, volume=100.0),
        fx_row(DAY + timedelta(hours=6, minutes=35), 1.1026, volume=100.0),
    ]

    decisions = generate_decisions(
        rows,
        params(
            decision_start_hour=6,
            decision_end_hour=8,
            enable_rejection=False,
        ),
    )

    assert decisions
    future_observations = [
        item
        for item in decisions[0].observations
        if item.timestamp == future_profile_row["timestamp"]
    ]
    assert future_observations == []


def test_zero_variance_activity_baseline_suppresses_signal_without_invalid_metadata():
    rows = asia_profile_rows() + [
        fx_row(DAY + timedelta(hours=7, minutes=0), 1.1001, volume=100.0),
        fx_row(DAY + timedelta(hours=7, minutes=1), 1.1002, volume=100.0),
        fx_row(DAY + timedelta(hours=7, minutes=2), 1.1020, volume=500.0),
        fx_row(DAY + timedelta(hours=7, minutes=3), 1.1022, volume=520.0),
    ]

    assert generate_decisions(rows, params(enable_rejection=False)) == []


def test_failed_break_direction_uses_latest_breach_before_reentry():
    rows = (
        asia_profile_rows()
        + decision_baseline_rows()
        + [
            fx_row(DAY + timedelta(hours=7, minutes=2), 1.1020, volume=500.0),
            fx_row(DAY + timedelta(hours=7, minutes=3), 1.0980, volume=520.0),
            fx_row(DAY + timedelta(hours=7, minutes=4), 1.1000, volume=540.0),
            fx_row(DAY + timedelta(hours=7, minutes=5), 1.1001, volume=100.0),
            fx_row(DAY + timedelta(hours=7, minutes=6), 1.1002, volume=100.0),
            fx_row(DAY + timedelta(hours=7, minutes=7), 1.1003, volume=100.0),
        ]
    )

    decisions = generate_decisions(rows, params(enable_acceptance=False))
    payloads = [decision_payload(decision) for decision in decisions]

    assert len(payloads) == 1
    assert payloads[0]["rule"] == "failed_break_rejection"
    assert payloads[0]["side"] == "long"


def test_rejection_declares_activity_baseline_rows_before_breach():
    rows = asia_profile_rows() + [
        fx_row(DAY + timedelta(hours=7, minutes=0), 1.1001, volume=100.0),
        fx_row(DAY + timedelta(hours=7, minutes=1), 1.1002, volume=120.0),
        fx_row(DAY + timedelta(hours=7, minutes=2), 1.1020, volume=500.0),
        fx_row(DAY + timedelta(hours=7, minutes=3), 1.1021, volume=100.0),
        fx_row(DAY + timedelta(hours=7, minutes=4), 1.1022, volume=100.0),
        fx_row(DAY + timedelta(hours=7, minutes=5), 1.1000, volume=520.0),
    ]

    decisions = generate_decisions(
        rows,
        params(enable_acceptance=False, activity_window_bars=2, rejection_lookback_bars=5),
    )
    observed_times = {item.timestamp for item in decisions[0].observations}

    assert DAY + timedelta(hours=7, minutes=2) in observed_times
    assert DAY + timedelta(hours=7, minutes=3) in observed_times


def test_invalid_quote_breach_does_not_trigger_failed_break_rejection():
    rows = (
        asia_profile_rows()
        + decision_baseline_rows()
        + [
            fx_row(
                DAY + timedelta(hours=7, minutes=2),
                1.1020,
                volume=500.0,
                has_quote=False,
            ),
            fx_row(DAY + timedelta(hours=7, minutes=3), 1.1000, volume=520.0),
        ]
    )

    assert generate_decisions(rows, params(enable_acceptance=False)) == []


def test_negative_activity_volume_suppresses_signal():
    rows = asia_profile_rows() + [
        fx_row(DAY + timedelta(hours=7, minutes=0), 1.1001, volume=-100.0),
        fx_row(DAY + timedelta(hours=7, minutes=1), 1.1002, volume=120.0),
        fx_row(DAY + timedelta(hours=7, minutes=2), 1.1020, volume=500.0),
        fx_row(DAY + timedelta(hours=7, minutes=3), 1.1022, volume=520.0),
    ]

    assert generate_decisions(rows, params(enable_rejection=False)) == []


@pytest.mark.parametrize(
    "blocked_row",
    [
        fx_row(DAY + timedelta(hours=7, minutes=3), 1.1022, volume=520.0, has_quote=False),
        fx_row(
            DAY + timedelta(hours=7, minutes=3),
            1.1022,
            volume=520.0,
            relative_spread=0.01,
        ),
    ],
)
def test_invalid_quote_or_wide_spread_suppresses_signal(blocked_row: dict[str, object]):
    rows = (
        asia_profile_rows()
        + decision_baseline_rows()
        + [
            fx_row(DAY + timedelta(hours=7, minutes=2), 1.1020, volume=500.0),
            blocked_row,
        ]
    )

    assert generate_decisions(rows, params(enable_rejection=False, max_spread_percentile=0.5)) == []


def test_generate_decisions_emits_causal_observation_lineage():
    rows = (
        asia_profile_rows()
        + decision_baseline_rows()
        + [
            fx_row(DAY + timedelta(hours=7, minutes=2), 1.1020, volume=500.0),
            fx_row(DAY + timedelta(hours=7, minutes=3), 1.1022, volume=520.0),
        ]
    )
    decisions = generate_decisions(rows, params(enable_rejection=False))

    observed = {
        (item.symbol, item.timestamp, item.field, item.source) for item in decisions[0].observations
    }
    required_fields = {"close", "high", "low", "volume", "relative_spread", "has_quote"}
    required_context_times = {
        DAY + timedelta(hours=7, minutes=0),
        DAY + timedelta(hours=7, minutes=1),
        DAY + timedelta(hours=7, minutes=2),
        DAY + timedelta(hours=7, minutes=3),
    }

    assert required_fields.issubset({field for _, _, field, _ in observed})
    assert required_context_times.issubset({timestamp for _, timestamp, _, _ in observed})
    assert all(source == "strategy_input" for _, _, _, source in observed)
    assert audit_decision_rows(rows, decisions).passed is True


def test_lineage_audit_fails_for_missing_or_late_observed_rows():
    rows = (
        asia_profile_rows()
        + decision_baseline_rows()
        + [
            fx_row(DAY + timedelta(hours=7, minutes=2), 1.1020, volume=500.0),
            fx_row(DAY + timedelta(hours=7, minutes=3), 1.1022, volume=520.0),
        ]
    )
    decisions = generate_decisions(rows, params(enable_rejection=False))
    missing_rows = [row for row in rows if row["timestamp"] != ASIA_START + timedelta(minutes=1)]
    late_rows = [dict(row) for row in rows]
    late_rows[1]["available_at"] = decisions[0].decision_time + timedelta(minutes=1)

    assert audit_decision_rows(missing_rows, decisions).passed is False
    late_audit = audit_decision_rows(late_rows, decisions)

    assert late_audit.passed is False
    assert any(
        "was available after decision_time" in violation for violation in late_audit.violations
    )


def test_quote_fill_timing_uses_decision_lag_before_entry_lag():
    rows = (
        asia_profile_rows()
        + decision_baseline_rows()
        + [
            fx_row(DAY + timedelta(hours=7, minutes=2), 1.1020, volume=500.0),
            fx_row(DAY + timedelta(hours=7, minutes=3), 1.1022, volume=520.0),
            fx_row(DAY + timedelta(hours=7, minutes=4), 1.1023, volume=100.0),
            fx_row(DAY + timedelta(hours=7, minutes=5), 1.1024, volume=100.0),
            fx_row(DAY + timedelta(hours=7, minutes=6), 1.1025, volume=100.0),
            fx_row(DAY + timedelta(hours=7, minutes=7), 1.1026, volume=100.0),
        ]
    )
    decisions = generate_decisions(rows, params(enable_rejection=False, max_hold_bars=1))

    request = build_request(
        strategy_id="fx_session_activity_profile_rejection",
        rows=rows,
        decisions=decisions,
        fill_model=FillModelConfig(price="quote", entry_lag_bars=1, exit_lag_bars=0),
        cost_model=CostModelConfig(fee_bps_per_side=0.0, slippage_bps_per_side=0.0),
    )
    run = evaluate_request(request, mode="screen")
    trade = run.screen_summary["trades"][0]

    assert decisions[0].decision_time == DAY + timedelta(hours=7, minutes=4)
    assert trade["decision_time"] == "2024-01-02T07:04:00Z"
    assert trade["entry_time"] == "2024-01-02T07:05:00Z"
    assert trade["exit_time"] == "2024-01-02T07:06:00Z"
