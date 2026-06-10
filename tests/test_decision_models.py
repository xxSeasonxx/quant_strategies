from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from quant_strategies.decisions import (
    InstrumentRef,
    ObservationRef,
    RiskRule,
    StrategyGenerator,
    TargetDecision,
    validate_decision_output,
)

DECISION_TIME = datetime(2026, 1, 2, 12, 1, tzinfo=UTC)
AS_OF_TIME = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)


def _decision(**overrides) -> TargetDecision:
    kwargs = {
        "strategy_id": "demo",
        "instrument": InstrumentRef(kind="crypto_perp", symbol="BTC-PERP"),
        "decision_time": DECISION_TIME,
        "as_of_time": AS_OF_TIME,
        "target": 0.2,
    }
    kwargs.update(overrides)
    return TargetDecision(**kwargs)


# --- Signed weight-of-NAV target (Requirement: standing signed target book) ---


def test_target_decision_accepts_signed_long_target():
    decision = _decision(
        strategy_id="crypto_perp_funding_crowding_reversal",
        target=0.2,
        metadata={"funding_pressure_bps": 3.5},
    )

    assert decision.instrument.symbol == "BTC-PERP"
    assert decision.target == 0.2
    assert decision.decision_id.startswith("crypto_perp_funding_crowding_reversal:")


def test_target_decision_accepts_signed_short_target():
    decision = _decision(target=-0.2)

    assert decision.target == -0.2


def test_target_decision_accepts_zero_flat_target():
    # Scenario: A zero target closes the position — 0 is a valid contract input.
    decision = _decision(target=0.0)

    assert decision.target == 0.0


def test_target_decision_accepts_leveraged_intent_target():
    # Scenario: Flat and leveraged-intent targets are valid contract inputs.
    # Intended gross > 1.0 is governed by the feasibility verdict, not a shape rejection.
    decision = _decision(target=2.5)

    assert decision.target == 2.5


def test_target_decision_rejects_non_finite_target():
    with pytest.raises(ValidationError, match="target must be finite"):
        _decision(target=float("inf"))
    with pytest.raises(ValidationError, match="target must be finite"):
        _decision(target=float("nan"))


def test_target_decision_rejects_coerced_target():
    with pytest.raises(ValidationError):
        _decision(target="0.2")


def test_target_decision_has_no_additive_stacking_surface():
    # Scenario: Stacking is structurally inexpressible — a single signed weight is the
    # only sizing field, so there is no additive/size-delta field to express a stack.
    fields = set(TargetDecision.model_fields)

    assert "target" in fields
    for additive in ("size", "add", "delta", "increment", "sizing_kind", "direction"):
        assert additive not in fields


# --- RiskRule (Requirement: price-path exits are declared engine-enforced risk rules) ---


def test_target_decision_accepts_declared_risk_rule():
    decision = _decision(
        target=-0.2,
        risk_rule=RiskRule(stop_loss=0.05, take_profit=0.1, trailing=0.03),
    )

    assert decision.risk_rule == RiskRule(stop_loss=0.05, take_profit=0.1, trailing=0.03)


def test_risk_rule_defaults_all_thresholds_to_none():
    rule = RiskRule()

    assert rule.stop_loss is None
    assert rule.take_profit is None
    assert rule.trailing is None


def test_target_decision_defaults_risk_rule_to_none():
    assert _decision().risk_rule is None


@pytest.mark.parametrize("field", ["stop_loss", "take_profit", "trailing"])
def test_risk_rule_rejects_non_positive_threshold(field: str):
    with pytest.raises(ValidationError, match=f"{field} must be finite and positive"):
        RiskRule(**{field: 0.0})


@pytest.mark.parametrize("field", ["stop_loss", "take_profit", "trailing"])
@pytest.mark.parametrize("value", [float("inf"), float("nan")])
def test_risk_rule_rejects_non_finite_threshold(field: str, value: float):
    with pytest.raises(ValidationError, match=f"{field} must be finite and positive"):
        RiskRule(**{field: value})


def test_risk_rule_rejects_unknown_threshold():
    with pytest.raises(ValidationError):
        RiskRule(max_hold_bars=5)


# --- Causality and determinism (Requirement: decisions remain pure and causal) ---


def test_target_decision_requires_timezone_aware_decision_time():
    with pytest.raises(ValidationError, match="decision_time must be timezone-aware"):
        _decision(decision_time=datetime(2026, 1, 2, 12, 1))


def test_target_decision_requires_timezone_aware_as_of_time():
    with pytest.raises(ValidationError, match="as_of_time must be timezone-aware"):
        _decision(as_of_time=datetime(2026, 1, 2, 12, 0))


def test_target_decision_rejects_lookahead_as_of_time():
    # Scenario: Causal time invariant holds — as_of_time after decision_time is rejected.
    with pytest.raises(ValidationError, match="as_of_time must be on or before decision_time"):
        _decision(decision_time=AS_OF_TIME, as_of_time=DECISION_TIME)


def test_target_decision_accepts_equal_as_of_and_decision_time():
    decision = _decision(decision_time=AS_OF_TIME, as_of_time=AS_OF_TIME)

    assert decision.as_of_time == decision.decision_time


def test_target_decision_generates_deterministic_decision_id():
    # Scenario: Generation is deterministic — identical inputs yield identical ids.
    first = _decision(metadata={"reason": "same"})
    second = _decision(metadata={"reason": "same"})
    changed = _decision(metadata={"reason": "different"})

    assert first.decision_id == second.decision_id
    assert first.decision_id != changed.decision_id


def test_decision_id_changes_with_target_and_risk_rule():
    base = _decision(target=0.2)

    assert base.decision_id != _decision(target=0.3).decision_id
    assert base.decision_id != _decision(target=0.2, risk_rule=RiskRule(stop_loss=0.05)).decision_id


def test_target_decision_accepts_explicit_decision_id():
    decision = _decision(decision_id="manual-001")

    assert decision.decision_id == "manual-001"


# --- Observations ---


def test_target_decision_defaults_observations_to_empty_tuple():
    assert _decision().observations == ()


def test_target_decision_accepts_multiple_typed_observations():
    observations = (
        ObservationRef(symbol="AAPL", timestamp=AS_OF_TIME, field="close", source="quant_data"),
        ObservationRef(
            symbol="MSFT", timestamp=AS_OF_TIME, field="return_21d", source="quant_data"
        ),
    )
    decision = _decision(
        strategy_id="cross_sectional_momentum",
        instrument=InstrumentRef(kind="equity_or_etf", symbol="SPY"),
        target=0.1,
        observations=observations,
    )

    assert decision.observations == observations


def test_observation_ref_rejects_naive_timestamp():
    with pytest.raises(ValidationError, match="timestamp must be timezone-aware"):
        ObservationRef(symbol="BTC-PERP", timestamp=datetime(2026, 1, 2, 12, 0))


def test_observation_ref_rejects_empty_symbol():
    with pytest.raises(ValidationError, match="symbol must be non-empty"):
        ObservationRef(symbol=" ", timestamp=AS_OF_TIME)


def test_target_decision_serializes_observations_to_json():
    decision = _decision(
        observations=(
            ObservationRef(symbol="BTC-PERP", timestamp=AS_OF_TIME, field="funding_rate"),
        )
    )

    assert decision.model_dump(mode="json")["observations"] == [
        {
            "symbol": "BTC-PERP",
            "timestamp": "2026-01-02T12:00:00Z",
            "field": "funding_rate",
            "source": None,
        }
    ]


def test_target_decision_schema_includes_target_and_risk_rule():
    schema = TargetDecision.model_json_schema()

    assert "target" in schema["properties"]
    assert "risk_rule" in schema["properties"]
    assert "observations" in schema["properties"]
    assert "decision_id" in schema["properties"]


# --- validate_decision_output: netting / dedup over the target book ---


def test_validate_decision_output_rejects_duplicate_decision_id():
    decision = _decision(decision_id="duplicate", target=0.2)

    decisions, violations = validate_decision_output([decision, decision], strategy_id="demo")

    assert decisions == [decision]
    assert violations == ("duplicate_decision_id[1]: duplicate",)


def test_validate_decision_output_rejects_duplicate_symbol_decision_time():
    # Same instrument and decision time cannot carry two targets (netting is one position).
    first = _decision(decision_id="decision-1", target=0.2)
    second = _decision(decision_id="decision-2", target=-0.2)

    decisions, violations = validate_decision_output([first, second], strategy_id="demo")

    assert decisions == [first]
    assert violations == (
        f"duplicate_decision_execution_key[1]: BTC-PERP@{DECISION_TIME.isoformat()}",
    )


def test_validate_decision_output_allows_distinct_execution_keys():
    # Scenario: Same-symbol decisions net rather than stack — a later target for the same
    # symbol is its new total target, accepted at a distinct decision time.
    baseline = _decision(decision_id="decision-1", target=0.2)
    same_symbol_later = _decision(
        decision_id="decision-2",
        decision_time=datetime(2026, 1, 2, 12, 2, tzinfo=UTC),
        target=0.3,
    )
    different_symbol_same_time = _decision(
        decision_id="decision-3",
        instrument=InstrumentRef(kind="crypto_perp", symbol="ETH-PERP"),
        target=-0.2,
    )

    decisions, violations = validate_decision_output(
        [baseline, same_symbol_later, different_symbol_same_time],
        strategy_id="demo",
    )

    assert decisions == [baseline, same_symbol_later, different_symbol_same_time]
    assert violations == ()


def test_validate_decision_output_rejects_strategy_id_mismatch():
    decision = _decision(strategy_id="other")

    decisions, violations = validate_decision_output([decision], strategy_id="demo")

    assert decisions == []
    assert violations == ("decision_strategy_id_mismatch[0]: expected demo, got other",)


def test_validate_decision_output_rejects_non_decision_items():
    decisions, violations = validate_decision_output(["not-a-decision"], strategy_id="demo")

    assert decisions == []
    assert violations == ("invalid_decision_output[0]",)


# --- Metadata: JSON-safe, frozen, isolated ---


def test_metadata_must_be_json_compatible():
    with pytest.raises(ValidationError, match="metadata must be JSON-compatible"):
        _decision(metadata={"bad": {1, 2, 3}})


def test_metadata_rejects_non_standard_json_nan():
    with pytest.raises(ValidationError, match="metadata must be JSON-compatible"):
        _decision(metadata={"bad": float("nan")})


def test_metadata_rejects_nested_non_string_mapping_keys():
    with pytest.raises(ValidationError, match="metadata must be JSON-compatible"):
        _decision(metadata={"outer": [{1: "lossy"}]})


def test_metadata_is_immutable_after_construction():
    decision = _decision(metadata={"x": 1})

    with pytest.raises(TypeError):
        decision.metadata["x"] = 2


def test_nested_metadata_is_immutable_after_construction():
    decision = _decision(metadata={"outer": {"items": [{"x": 1}]}})

    with pytest.raises(TypeError):
        decision.metadata["outer"]["items"][0] = {"x": 2}
    with pytest.raises(TypeError):
        decision.metadata["outer"]["items"][0]["x"] = 2


def test_nested_metadata_is_isolated_from_caller_mutation():
    metadata = {"outer": {"items": [{"x": 1}]}}
    decision = _decision(metadata=metadata)

    metadata["outer"]["items"][0]["x"] = 2
    metadata["outer"]["items"].append({"x": 3})
    metadata["outer"]["new"] = "caller"

    assert decision.metadata["outer"]["items"][0]["x"] == 1
    assert len(decision.metadata["outer"]["items"]) == 1
    assert "new" not in decision.metadata["outer"]


# --- Strategy generator protocol ---


def test_strategy_generator_protocol_is_publicly_importable():
    def generate_decisions(rows, params):
        return []

    strategy: StrategyGenerator = generate_decisions

    assert strategy([], {}) == []


# --- Surface boundary: the default contract names no extended / order vocabulary ---


def test_default_import_boundary_excludes_extended_and_order_vocabulary():
    import quant_strategies.decisions as decision_api
    import quant_strategies.decisions.models as decision_models

    excluded = {
        "BookSide",
        "DecisionAction",
        "Direction",
        "ExitPolicy",
        "FutureRef",
        "InstrumentLeg",
        "LegDirection",
        "MultiLegInstrumentRef",
        "OptionRef",
        "OptionType",
        "PositionTarget",
        "Settlement",
        "SingleInstrumentRef",
        "SizingKind",
        "StrategyDecision",
    }

    for name in excluded:
        assert not hasattr(decision_api, name)
        assert not hasattr(decision_models, name)
        assert name not in decision_api.__all__


def test_default_model_source_does_not_name_legacy_or_extended_vocabulary():
    source = Path("src/quant_strategies/decisions/models.py").read_text()

    for name in (
        "BookSide",
        "DecisionAction",
        "ExitPolicy",
        "FutureRef",
        "InstrumentLeg",
        "LegDirection",
        "MultiLegInstrumentRef",
        "OptionRef",
        "OptionType",
        "PositionTarget",
        "Settlement",
        "SingleInstrumentRef",
        "SizingKind",
        "StrategyDecision",
        "book_side",
        "exit_policy",
        "max_hold_bars",
        "multi_leg",
        "sizing_kind",
        "target_contracts",
        "target_notional",
        "target_vol",
    ):
        assert name not in source
