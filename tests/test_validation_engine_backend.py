from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

import quant_strategies.validation.engine_backend as engine_backend_module
from quant_strategies.core.config import (
    CapacityModelConfig,
    CostModelConfig,
    DataConfig,
    FillModelConfig,
    RiskBudgetConfig,
)
from quant_strategies.decisions import InstrumentRef, RiskRule, TargetDecision
from quant_strategies.validation.backends import BackendMetrics
from quant_strategies.validation.config import ScenarioRunConfig
from quant_strategies.validation.engine_backend import SpineBackend

AS_OF = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)


def bar(minute: int, close: float) -> dict:
    # OHLC bars; flat bars (o=h=l=c) keep close-fills exact.
    ts = datetime(2026, 1, 1, 0, minute, tzinfo=UTC)
    return {
        "symbol": "BTC-PERP",
        "timestamp": ts,
        "available_at": ts,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": 1_000.0,
        "vwap": close,
        "num_trades": 100,
    }


def rows():
    return [bar(0, 100.0), bar(1, 101.0), bar(2, 102.0), bar(3, 103.0)]


def funding_rows(rate: float = 0.0003):
    base = rows()
    base[-1] = {
        **base[-1],
        "funding_timestamp": datetime(2026, 1, 1, 0, 3, tzinfo=UTC),
        "funding_rate": rate,
        "has_funding_event": True,
    }
    return base


def target(
    minute: int,
    weight: float,
    *,
    risk_rule: RiskRule | None = None,
) -> TargetDecision:
    ts = datetime(2026, 1, 1, 0, minute, tzinfo=UTC)
    return TargetDecision(
        strategy_id="demo",
        instrument=InstrumentRef(kind="crypto_perp", symbol="BTC-PERP"),
        decision_time=ts,
        as_of_time=ts,
        target=weight,
        risk_rule=risk_rule,
    )


def long_round_trip() -> list[TargetDecision]:
    # Standing base-shape book: open long at bar0 (fills bar1 close 101), flatten
    # at bar2 (fills bar3 close 103). One netted-book round trip held across
    # at-risk bars.
    return [target(0, 1.0), target(2, 0.0)]


def scenario_config(
    *,
    fee_bps: float = 1.0,
    slippage_bps: float = 0.0,
    impact_coefficient_bps: float = 0.0,
    data_kind: str = "bars",
    entry_lag_bars: int = 1,
    book_scale: float = 1.0,
):
    dataset = "demo_bars" if data_kind == "bars" else None
    return ScenarioRunConfig(
        scenario_id="realistic",
        fill_model=FillModelConfig(price="close", entry_lag_bars=entry_lag_bars),
        cost_model=CostModelConfig(fee_bps_per_side=fee_bps, slippage_bps_per_side=slippage_bps),
        capacity_model=CapacityModelConfig(
            mode="adv_impact",
            portfolio_notional=1_000.0,
            adv_lookback_bars=3,
            adv_min_observations=1,
            max_bar_participation=1.0,
            max_adv_participation=1.0,
            impact_coefficient_bps=impact_coefficient_bps,
            impact_exponent=1.0,
        ),
        risk_budget=RiskBudgetConfig(
            mode="fixed_scale",
            annualization_periods_per_year=525949,
            book_scale=book_scale,
        ),
        data=DataConfig(
            kind=data_kind,
            dataset=dataset,
            symbols=("BTC-PERP",),
            start=date(2026, 1, 1),
            end=date(2026, 1, 1),
        ),
    )


def test_validation_engine_backend_exposes_only_spine_backend():
    assert not hasattr(engine_backend_module, "EngineBackend")
    assert SpineBackend().name == "engine"


def test_spine_backend_maps_netted_book_round_trip_to_net_return():
    result = SpineBackend().run(decisions=long_round_trip(), rows=rows(), config=scenario_config())

    assert result.backend == "engine"
    assert result.status == "completed"
    assert result.metrics["trade_count"] == 1
    # qty = 1.0 * 100 / 101 (entry close 101); price proceeds = qty*(103-101); /100 NAV base.
    expected_gross = (1.0 * 100.0 / 101.0) * (103.0 - 101.0) / 100.0
    assert result.metrics["gross_return"] == pytest.approx(expected_gross)
    # One netted-book round trip is emitted as the per-scenario ledger.
    assert len(result.round_trips) == 1


def test_spine_backend_metrics_reconcile_net_equals_gross_plus_funding_minus_cost():
    result = SpineBackend().run(
        decisions=long_round_trip(),
        rows=rows(),
        config=scenario_config(fee_bps=5.0, slippage_bps=2.0),
    )
    m = result.metrics
    # The netted-book ledger cash split reconciles by construction (design D4).
    assert m["net_return"] == pytest.approx(
        m["gross_return"] + m["funding_return"] - m["cost_return"]
    )
    # Round-trip cost = 2 sides * (fee + slippage) bps on the traded notional / NAV base.
    qty = 1.0 * 100.0 / 101.0
    traded_notional = qty * 101.0 + qty * 103.0  # entry fill 101, exit fill 103
    expected_cost = traded_notional * (5.0 + 2.0) / 10_000.0 / 100.0
    assert m["cost_return"] == pytest.approx(expected_cost)


def test_spine_backend_metrics_include_impact_return():
    result = SpineBackend().run(
        decisions=long_round_trip(),
        rows=rows(),
        config=scenario_config(fee_bps=0.0, impact_coefficient_bps=100.0),
    )

    assert result.status == "completed"
    assert result.metrics["impact_return"] > 0.0
    assert result.metrics["cost_return"] == pytest.approx(result.metrics["impact_return"])


def test_spine_backend_net_return_is_funding_inclusive():
    # A long paying funding: net_return must be below the pure price path.
    result = SpineBackend().run(
        decisions=long_round_trip(),
        rows=funding_rows(),
        config=scenario_config(data_kind="crypto_perp_funding"),
    )
    m = result.metrics
    assert result.status == "completed"
    assert m["funding_return"] < 0.0  # long pays positive funding
    assert m["net_return"] == pytest.approx(
        m["gross_return"] + m["funding_return"] - m["cost_return"]
    )
    assert m["net_return"] < m["gross_return"]  # funding + cost drag net below the price path


def test_spine_backend_funding_can_flip_gated_net_negative():
    # The gated net_return is funding-inclusive: a profitable price path with a large
    # funding cost has a negative gated net_return, so it cannot clear the net floors.
    result = SpineBackend().run(
        decisions=long_round_trip(),
        rows=funding_rows(rate=0.05),
        config=scenario_config(data_kind="crypto_perp_funding"),
    )
    m = result.metrics
    assert m["gross_return"] > 0.0  # price path alone is profitable
    assert m["funding_return"] < 0.0
    assert m["net_return"] < 0.0  # but the funding-inclusive gated number is a loss


def test_spine_backend_net_return_is_marked_nav_for_held_open_fold():
    # A winner held open at the fold boundary has zero *closed* round-trips, so a
    # realized-only net_return would gate it as 0% / zero-trade and reject a real
    # open winner. The gated net_return must be the marked NAV fold return instead.
    held_open_long = [target(0, 1.0)]  # open long bar0 (fills bar1 @101); never closed
    result = SpineBackend().run(decisions=held_open_long, rows=rows(), config=scenario_config())

    assert result.status == "completed"
    # No closed round-trip: the realized-ledger sum is exactly 0.
    assert result.round_trips == ()
    assert result.metrics["gross_return"] == pytest.approx(0.0)
    # But the book ends with an open winner: qty = 1.0*100/101 entered @101 (paying
    # a 1bps entry cost), marked at the last close 103. The marked NAV return is
    # positive -- not the realized-only 0.
    qty = 1.0 * 100.0 / 101.0
    entry_cost = qty * 101.0 * (1.0 / 10_000.0)
    expected_marked = (qty * (103.0 - 101.0) - entry_cost) / 100.0
    assert result.metrics["net_return"] == pytest.approx(expected_marked)
    assert result.metrics["net_return"] > 0.0


def test_spine_backend_metrics_feed_backend_metrics_contract():
    result = SpineBackend().run(decisions=long_round_trip(), rows=rows(), config=scenario_config())
    metrics = BackendMetrics.from_mapping(result.metrics)
    assert metrics is not None
    assert metrics.trade_count == 1
    assert metrics.net_return == pytest.approx(result.metrics["net_return"])


def test_spine_backend_supports_threshold_risk_rule_decisions():
    # A declared RiskRule is enforced causally by the spine on the net position; the
    # netted-book book completes (no "unsupported" decision shape).
    result = SpineBackend().run(
        decisions=[target(0, 1.0, risk_rule=RiskRule(stop_loss=0.5, take_profit=3.0))],
        rows=rows(),
        config=scenario_config(),
    )
    assert result.status == "completed"
    assert result.unsupported_semantics == ()


def test_spine_backend_accepts_crypto_perp_without_funding_events_as_zero_funding():
    result = SpineBackend().run(
        decisions=long_round_trip(),
        rows=rows(),
        config=scenario_config(data_kind="crypto_perp_funding"),
    )

    assert result.status == "completed"
    assert result.metrics["funding_return"] == pytest.approx(0.0)
    assert result.warnings == ()


def test_spine_backend_leverage_breach_is_typed_unsupported_not_clamped():
    # Final sized gross > the operator budget is a fail-closed leverage verdict,
    # surfaced as a typed ``unsupported`` reason rather than a clamped score.
    result = SpineBackend().run(
        decisions=[target(0, 1.0), target(2, 0.0)],
        rows=rows(),
        config=scenario_config(book_scale=2.0),
    )
    assert result.status == "unsupported"
    assert result.metrics == {}
    assert result.unsupported_semantics == ("leverage_budget_breach",)
    assert any("feasibility:" in warning for warning in result.warnings)


def test_spine_backend_carries_zero_cost_feasibility_verdict():
    long_rows = [bar(minute, 100.0 + minute) for minute in range(23)]
    long_hold = [target(0, 1.0), target(21, 0.0)]
    result = SpineBackend().run(
        decisions=long_hold,
        rows=long_rows,
        config=scenario_config(fee_bps=0.0, slippage_bps=0.0),
    )

    assert result.status == "completed"
    assert result.feasibility.feasible is False
    assert result.feasibility.reason == "zero_cost"


def test_spine_backend_carries_insufficient_sample_feasibility_verdict():
    result = SpineBackend().run(
        decisions=[target(0, 1.0)],
        rows=rows()[:2],
        config=scenario_config(),
    )

    assert result.status == "completed"
    assert result.feasibility.feasible is False
    assert result.feasibility.reason == "insufficient_samples"


def test_spine_backend_returns_failed_on_unfillable_decision():
    # A decision whose entry-lagged fill bar is past the available rows -> the spine
    # raises a structured ValueError; the backend reports it as a failed run.
    result = SpineBackend().run(
        decisions=[target(3, 1.0)],
        rows=rows(),
        config=scenario_config(entry_lag_bars=2),
    )
    assert result.status == "failed"
    assert result.metrics == {}
    assert result.warnings  # carries the original error message
