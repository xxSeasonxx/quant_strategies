from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from quant_strategies.decisions import (
    ExitPolicy,
    InstrumentRef,
    ObservationRef,
    PositionTarget,
    StrategyDecision,
)
from quant_strategies.core.data_audit import audit_decision_rows


AS_OF = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
DECISION = datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc)
FUTURE = datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc)


def row(symbol: str, timestamp: datetime, close: float) -> dict[str, object]:
    return {
        "symbol": symbol,
        "timestamp": timestamp,
        "available_at": timestamp,
        "close": close,
    }


def close_by_symbol(rows: Sequence[Mapping[str, Any]], timestamp: datetime) -> dict[str, float]:
    return {
        str(item["symbol"]): float(item["close"])
        for item in rows
        if item.get("timestamp") == timestamp
    }


def generate_cross_sectional_decisions(rows: Sequence[Mapping[str, Any]]) -> list[StrategyDecision]:
    closes = close_by_symbol(rows, AS_OF)
    if len(closes) < 2:
        return []
    winner = max(closes, key=closes.__getitem__)
    observations = tuple(
        ObservationRef(symbol=symbol, timestamp=AS_OF, field="close", source="synthetic")
        for symbol in sorted(closes)
    )
    return [
        StrategyDecision(
            strategy_id="synthetic_cross_section",
            instrument=InstrumentRef(kind="crypto_perp", symbol=winner),
            decision_time=DECISION,
            as_of_time=AS_OF,
            target=PositionTarget(direction="long", sizing_kind="target_weight", size=0.5),
            exit_policy=ExitPolicy(max_hold_bars=3),
            observations=observations,
            metadata={"cross_section_count": len(closes)},
        )
    ]


def generate_fx_triangle_decisions(rows: Sequence[Mapping[str, Any]]) -> list[StrategyDecision]:
    closes = close_by_symbol(rows, AS_OF)
    if not {"EURUSD", "USDJPY", "EURJPY"}.issubset(closes):
        return []
    residual = math.log(closes["EURJPY"] / (closes["EURUSD"] * closes["USDJPY"]))
    if abs(residual) < 0.0001:
        return []
    direction = "short" if residual > 0 else "long"
    observations = tuple(
        ObservationRef(symbol=symbol, timestamp=AS_OF, field="close", source="synthetic")
        for symbol in ("EURUSD", "USDJPY", "EURJPY")
    )
    return [
        StrategyDecision(
            strategy_id="synthetic_fx_triangle",
            instrument=InstrumentRef(kind="fx_pair", symbol="EURJPY"),
            decision_time=DECISION,
            as_of_time=AS_OF,
            target=PositionTarget(direction=direction, sizing_kind="target_weight", size=0.25),
            exit_policy=ExitPolicy(max_hold_bars=2),
            observations=observations,
            metadata={"residual_bps": round(residual * 10_000, 6)},
        )
    ]


def decision_fingerprint(decisions: list[StrategyDecision]) -> str:
    payload = [decision.model_dump(mode="json") for decision in decisions]
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def poison_future_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return rows + [
        row("BTC-PERP", FUTURE, 1.0),
        row("ETH-PERP", FUTURE, 1_000.0),
        row("EURUSD", FUTURE, 99.0),
        row("USDJPY", FUTURE, 1.0),
        row("EURJPY", FUTURE, 99_000.0),
    ]


def test_cross_sectional_synthetic_generator_uses_only_as_of_rows_and_typed_observations():
    decisions = generate_cross_sectional_decisions(
        [
            row("BTC-PERP", AS_OF, 100.0),
            row("ETH-PERP", AS_OF, 105.0),
            row("BTC-PERP", FUTURE, 1_000.0),
        ]
    )

    assert decisions[0].instrument.symbol == "ETH-PERP"
    assert decisions[0].observations == (
        ObservationRef(symbol="BTC-PERP", timestamp=AS_OF, field="close", source="synthetic"),
        ObservationRef(symbol="ETH-PERP", timestamp=AS_OF, field="close", source="synthetic"),
    )


def test_fx_triangle_synthetic_generator_uses_only_as_of_rows_and_typed_observations():
    decisions = generate_fx_triangle_decisions(
        [
            row("EURUSD", AS_OF, 1.0),
            row("USDJPY", AS_OF, 100.0),
            row("EURJPY", AS_OF, 101.0),
            row("EURJPY", FUTURE, 1.0),
        ]
    )

    assert decisions[0].target.direction == "short"
    assert decisions[0].observations == (
        ObservationRef(symbol="EURUSD", timestamp=AS_OF, field="close", source="synthetic"),
        ObservationRef(symbol="USDJPY", timestamp=AS_OF, field="close", source="synthetic"),
        ObservationRef(symbol="EURJPY", timestamp=AS_OF, field="close", source="synthetic"),
    )


def test_poisoning_future_rows_does_not_change_generated_decision_ids():
    cross_section_rows = [
        row("BTC-PERP", AS_OF, 100.0),
        row("ETH-PERP", AS_OF, 105.0),
    ]
    fx_rows = [
        row("EURUSD", AS_OF, 1.0),
        row("USDJPY", AS_OF, 100.0),
        row("EURJPY", AS_OF, 101.0),
    ]

    assert decision_fingerprint(generate_cross_sectional_decisions(cross_section_rows)) == decision_fingerprint(
        generate_cross_sectional_decisions(poison_future_rows(cross_section_rows))
    )
    assert decision_fingerprint(generate_fx_triangle_decisions(fx_rows)) == decision_fingerprint(
        generate_fx_triangle_decisions(poison_future_rows(fx_rows))
    )


def test_declared_future_fx_observation_is_caught_by_audit():
    rows = [
        row("EURUSD", AS_OF, 1.0),
        row("USDJPY", AS_OF, 100.0),
        row("EURJPY", AS_OF, 101.0),
        row("EURJPY", FUTURE, 99.0),
    ]
    clean_decision = generate_fx_triangle_decisions(rows)[0]
    poisoned_decision = clean_decision.model_copy(
        update={
            "observations": clean_decision.observations
            + (ObservationRef(symbol="EURJPY", timestamp=FUTURE, field="close", source="synthetic"),)
        }
    )

    audit = audit_decision_rows(rows, [poisoned_decision])

    assert audit.passed is False
    assert audit.violations == (
        "observation for EURJPY references future row EURJPY at 2026-01-01T00:02:00+00:00",
    )
