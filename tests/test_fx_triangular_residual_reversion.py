from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest
from tests.candidate_loader import load_candidate_strategy

from quant_strategies.core.data_audit import audit_decision_rows
from quant_strategies.core.engine_runner import build_request, evaluate_request
from quant_strategies.decisions import StrategyDecision
from quant_strategies.runner.config import CostModelConfig, FillModelConfig

strategy = load_candidate_strategy("fx_triangular_residual_reversion")
generate_decisions = strategy.generate_decisions
validate_params = strategy.validate_params

START = datetime(2024, 1, 1, tzinfo=UTC)


def direct_residual_rows(residuals: list[float]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index, residual in enumerate(residuals):
        timestamp = START + timedelta(minutes=index)
        rows.extend(
            [
                {"symbol": "EURUSD", "timestamp": timestamp, "close": 1.0},
                {"symbol": "USDJPY", "timestamp": timestamp, "close": 100.0},
                {"symbol": "EURJPY", "timestamp": timestamp, "close": 100.0 * math.exp(residual)},
            ]
        )
    return rows


def usdjpy_residual_rows(residuals: list[float]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index, residual in enumerate(residuals):
        timestamp = START + timedelta(minutes=index)
        rows.extend(
            [
                {"symbol": "EURUSD", "timestamp": timestamp, "close": 1.0},
                {"symbol": "USDJPY", "timestamp": timestamp, "close": 100.0 * math.exp(-residual)},
                {"symbol": "EURJPY", "timestamp": timestamp, "close": 100.0},
            ]
        )
    return rows


def params(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "triangle_set": "outside_view_8",
        "zscore_window_bars": 2,
        "min_zscore_observations": 2,
        "entry_zscore": 2.0,
        "min_abs_residual_bps": 1.0,
        "attribution_bars": 1,
        "crossing_only": True,
        "weight": 0.5,
        "max_hold_bars": 4,
    }
    values.update(overrides)
    return values


def engine_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for row in rows:
        close = float(row["close"])
        result.append(
            {
                **row,
                "open": close,
                "high": close,
                "low": close,
                "bid": close * 0.9999,
                "ask": close * 1.0001,
                "mid": close,
            }
        )
    return result


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

    assert parsed["triangle_set"] == "outside_view_8"
    assert parsed["zscore_window_bars"] == 240
    assert isinstance(parsed["zscore_window_bars"], int)
    assert parsed["attribution_bars"] == 5
    assert parsed["crossing_only"] is True
    assert parsed["weight"] == pytest.approx(1.0)
    assert isinstance(parsed["weight"], float)


def test_validate_params_normalizes_aliases_and_valid_overrides():
    parsed = validate_params(
        {
            "triangle_set": "all_available",
            "zscore_window_minutes": "3",
            "min_zscore_observations": "2",
            "entry_zscore": "2.0",
            "min_abs_residual_bps": "1.25",
            "attribution_minutes": "1",
            "decision_lag_minutes": "0",
            "crossing_only": False,
            "weight": "0.5",
            "max_hold_bars": "4",
            "take_profit_bps": "10.5",
        }
    )

    assert parsed["triangle_set"] == "all_available"
    assert parsed["zscore_window_bars"] == 3
    assert "zscore_window_minutes" not in parsed
    assert parsed["attribution_bars"] == 1
    assert "attribution_minutes" not in parsed
    assert parsed["crossing_only"] is False
    assert parsed["weight"] == pytest.approx(0.5)
    assert parsed["take_profit_bps"] == pytest.approx(10.5)


def test_validate_params_rejects_invalid_and_unknown_values():
    with pytest.raises(ValueError, match="triangle_set"):
        validate_params({"triangle_set": "typo"})
    with pytest.raises(ValueError, match="crossing_only"):
        validate_params({"crossing_only": "false"})
    with pytest.raises(ValueError, match="zscore_window_bars"):
        validate_params({"zscore_window_bars": 0})
    with pytest.raises(ValueError, match="unknown params: typo"):
        validate_params({"typo": 1})


def test_generate_decisions_preserves_behavior_with_validated_params():
    rows = direct_residual_rows([0.0, 0.001, 0.002, 0.0])
    raw_params = params(weight="0.5", max_hold_bars="4")

    assert generate_payloads(rows, validate_params(raw_params)) == generate_payloads(
        rows, raw_params
    )


def test_generate_decisions_rejects_duplicate_symbol_timestamp_closes():
    bars = direct_residual_rows([0.0, 0.001, 0.002, 0.0])
    bars.append({"symbol": "EURJPY", "timestamp": START, "close": 100.0})

    with pytest.raises(ValueError, match="duplicate"):
        generate_decisions(bars, params())


def test_generate_decisions_uses_prior_residuals_for_direct_cross_short():
    signals = generate_payloads(direct_residual_rows([0.0, 0.001, 0.002, 0.0]), params())

    assert signals == [
        {
            "symbol": "EURJPY",
            "decision_time": START + timedelta(minutes=3),
            "as_of_time": START + timedelta(minutes=2),
            "side": "short",
            "weight": 0.5,
            "max_hold_bars": 4,
            "residual_zscore": pytest.approx(3.0),
            "residual_bps": pytest.approx(20.0),
            "attribution_score": pytest.approx(10.0),
            "signal_family": "fx_triangular_residual_reversion",
        }
    ]


def test_generate_decisions_emits_complete_close_observation_lineage():
    rows = direct_residual_rows([0.0, 0.001, 0.002, 0.0])
    decisions = generate_decisions(rows, params())
    observed = {
        (item.symbol, item.timestamp, item.field, item.source) for item in decisions[0].observations
    }
    expected_times = [START + timedelta(minutes=index) for index in range(3)]
    expected = {
        (symbol, timestamp, "close", "strategy_input")
        for symbol in ("EURJPY", "EURUSD", "USDJPY")
        for timestamp in expected_times
    }

    assert observed == expected
    assert audit_decision_rows(auditable_rows(rows), decisions).passed is True


def test_fx_lineage_audit_fails_for_missing_or_late_observed_rows():
    rows = direct_residual_rows([0.0, 0.001, 0.002, 0.0])
    decisions = generate_decisions(rows, params())
    missing_rows = [
        row
        for row in auditable_rows(rows)
        if not (row["symbol"] == "EURUSD" and row["timestamp"] == START + timedelta(minutes=1))
    ]
    late_rows = auditable_rows(rows)
    for row in late_rows:
        if row["symbol"] == "EURUSD" and row["timestamp"] == START + timedelta(minutes=1):
            row["available_at"] = decisions[0].decision_time + timedelta(minutes=1)

    missing_audit = audit_decision_rows(missing_rows, decisions)
    late_audit = audit_decision_rows(late_rows, decisions)

    assert missing_audit.passed is False
    assert any("missing observation row" in violation for violation in missing_audit.violations)
    assert late_audit.passed is False
    assert any(
        "was available after decision_time" in violation for violation in late_audit.violations
    )


def test_generate_decisions_maps_synthetic_leg_reversion_side():
    signals = generate_payloads(usdjpy_residual_rows([0.0, 0.001, 0.002, 0.0]), params())

    assert signals == [
        {
            "symbol": "USDJPY",
            "decision_time": START + timedelta(minutes=3),
            "as_of_time": START + timedelta(minutes=2),
            "side": "long",
            "weight": 0.5,
            "max_hold_bars": 4,
            "residual_zscore": pytest.approx(3.0),
            "residual_bps": pytest.approx(20.0),
            "attribution_score": pytest.approx(10.0),
            "signal_family": "fx_triangular_residual_reversion",
        }
    ]


def test_quote_fill_timing_uses_configured_lag_only_after_residual_decision():
    rows = engine_rows(direct_residual_rows([0.0, 0.001, 0.002, 0.0, 0.0, 0.0]))
    decisions = generate_decisions(rows, params(max_hold_bars=1))
    signals = [decision_payload(decision) for decision in decisions]

    assert signals[0]["as_of_time"] == START + timedelta(minutes=2)
    assert signals[0]["decision_time"] == START + timedelta(minutes=3)

    request = build_request(
        strategy_id="fx_timing",
        rows=rows,
        decisions=decisions,
        fill_model=FillModelConfig(price="quote", entry_lag_bars=1, exit_lag_bars=0),
        cost_model=CostModelConfig(fee_bps_per_side=0.0, slippage_bps_per_side=0.0),
    )
    run = evaluate_request(request, mode="screen")
    trade = run.screen_summary["trades"][0]

    assert trade["decision_time"] == "2024-01-01T00:03:00Z"
    assert trade["entry_time"] == "2024-01-01T00:04:00Z"
    assert trade["exit_time"] == "2024-01-01T00:05:00Z"


def test_generate_decisions_allows_explicit_zero_decision_lag():
    signals = generate_payloads(
        direct_residual_rows([0.0, 0.001, 0.002, 0.0]),
        params(decision_lag_minutes=0),
    )

    assert signals[0]["as_of_time"] == START + timedelta(minutes=2)
    assert signals[0]["decision_time"] == START + timedelta(minutes=2)


def test_generate_decisions_suppresses_repeated_same_zone_entries():
    residuals = [-0.0001, 0.0, 0.0001, -0.0001, 0.0, 0.005, 0.006, 0.0]

    signals = generate_payloads(
        direct_residual_rows(residuals),
        params(zscore_window_bars=5, min_zscore_observations=5),
    )

    assert signals == [
        {
            "symbol": "EURJPY",
            "decision_time": START + timedelta(minutes=6),
            "as_of_time": START + timedelta(minutes=5),
            "side": "short",
            "weight": 0.5,
            "max_hold_bars": 4,
            "residual_zscore": pytest.approx(67.08257172001852),
            "residual_bps": pytest.approx(50.0),
            "attribution_score": pytest.approx(50.0),
            "signal_family": "fx_triangular_residual_reversion",
        }
    ]


def test_generate_decisions_requires_enough_residual_history():
    assert (
        generate_decisions(direct_residual_rows([0.005, 0.0]), params(min_zscore_observations=3))
        == []
    )


def test_generate_decisions_rejects_unknown_triangle_set():
    with pytest.raises(ValueError, match="triangle_set"):
        generate_decisions(
            direct_residual_rows([0.0, 0.001, 0.002, 0.0]), params(triangle_set="typo")
        )


def test_generate_decisions_returns_empty_below_threshold():
    signals = generate_decisions(
        direct_residual_rows([0.0, 0.001, 0.002, 0.0]), params(entry_zscore=100.0)
    )

    assert signals == []


def test_generate_decisions_returns_empty_for_zero_variance_history():
    signals = generate_decisions(direct_residual_rows([0.0, 0.0, 0.005, 0.0]), params())

    assert signals == []


def test_generate_decisions_emits_optional_exit_controls():
    signals = generate_payloads(
        direct_residual_rows([0.0, 0.001, 0.002, 0.0]),
        params(
            max_hold_bars=8,
            take_profit_bps=120.0,
            stop_loss_bps=70.0,
            trailing_stop_bps=35.0,
        ),
    )

    assert signals[0]["max_hold_bars"] == 8
    assert signals[0]["take_profit_bps"] == 120.0
    assert signals[0]["stop_loss_bps"] == 70.0
    assert signals[0]["trailing_stop_bps"] == 35.0
