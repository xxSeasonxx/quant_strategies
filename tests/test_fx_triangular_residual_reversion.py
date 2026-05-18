from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math

import pytest

from untested.fx_triangular_residual_reversion import generate_signals


START = datetime(2024, 1, 1, tzinfo=timezone.utc)


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
        "hold_bars": 4,
    }
    values.update(overrides)
    return values


def test_generate_signals_returns_empty_for_empty_input():
    assert generate_signals([], {}) == []


def test_generate_signals_rejects_duplicate_symbol_timestamp_closes():
    bars = direct_residual_rows([0.0, 0.001, 0.002, 0.0])
    bars.append({"symbol": "EURJPY", "timestamp": START, "close": 100.0})

    with pytest.raises(ValueError, match="duplicate"):
        generate_signals(bars, params())


def test_generate_signals_uses_prior_residuals_for_direct_cross_short():
    signals = generate_signals(direct_residual_rows([0.0, 0.001, 0.002, 0.0]), params())

    assert signals == [
        {
            "symbol": "EURJPY",
            "decision_time": START + timedelta(minutes=3),
            "side": "short",
            "weight": 0.5,
            "hold_bars": 4,
        }
    ]


def test_generate_signals_maps_synthetic_leg_reversion_side():
    signals = generate_signals(usdjpy_residual_rows([0.0, 0.001, 0.002, 0.0]), params())

    assert signals == [
        {
            "symbol": "USDJPY",
            "decision_time": START + timedelta(minutes=3),
            "side": "long",
            "weight": 0.5,
            "hold_bars": 4,
        }
    ]


def test_generate_signals_suppresses_repeated_same_zone_entries():
    residuals = [-0.0001, 0.0, 0.0001, -0.0001, 0.0, 0.005, 0.006, 0.0]

    signals = generate_signals(
        direct_residual_rows(residuals),
        params(zscore_window_bars=5, min_zscore_observations=5),
    )

    assert signals == [
        {
            "symbol": "EURJPY",
            "decision_time": START + timedelta(minutes=6),
            "side": "short",
            "weight": 0.5,
            "hold_bars": 4,
        }
    ]


def test_generate_signals_requires_enough_residual_history():
    assert generate_signals(direct_residual_rows([0.005, 0.0]), params(min_zscore_observations=3)) == []


def test_generate_signals_rejects_unknown_triangle_set():
    with pytest.raises(ValueError, match="triangle_set"):
        generate_signals(direct_residual_rows([0.0, 0.001, 0.002, 0.0]), params(triangle_set="typo"))


def test_generate_signals_returns_empty_below_threshold():
    signals = generate_signals(direct_residual_rows([0.0, 0.001, 0.002, 0.0]), params(entry_zscore=100.0))

    assert signals == []


def test_generate_signals_returns_empty_for_zero_variance_history():
    signals = generate_signals(direct_residual_rows([0.0, 0.0, 0.005, 0.0]), params())

    assert signals == []
