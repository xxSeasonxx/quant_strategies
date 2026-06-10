from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from quant_strategies.core.config import CostModelConfig, DataConfig, FillModelConfig
from quant_strategies.decisions import InstrumentRef, RiskRule, TargetDecision
from quant_strategies.validation.backends import BackendMetrics
from quant_strategies.validation.config import ScenarioRunConfig
from quant_strategies.validation.engine_backend import EngineBackend, SpineBackend

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
    # Standing weight-of-NAV book: open long at bar0 (fills bar1 close 101), flatten at
    # bar2 (fills bar3 close 103). One netted-book round trip held across at-risk bars.
    return [target(0, 1.0), target(2, 0.0)]


def scenario_config(
    *,
    fee_bps: float = 1.0,
    slippage_bps: float = 0.0,
    data_kind: str = "bars",
    entry_lag_bars: int = 1,
):
    dataset = "demo_bars" if data_kind == "bars" else None
    return ScenarioRunConfig(
        scenario_id="realistic",
        fill_model=FillModelConfig(price="close", entry_lag_bars=entry_lag_bars, exit_lag_bars=0),
        cost_model=CostModelConfig(fee_bps_per_side=fee_bps, slippage_bps_per_side=slippage_bps),
        data=DataConfig(
            kind=data_kind,
            dataset=dataset,
            symbols=("BTC-PERP",),
            start=date(2026, 1, 1),
            end=date(2026, 1, 1),
        ),
    )


def test_engine_backend_alias_is_the_spine_backend():
    # The public backend name stayed ``engine`` when the per-trade scorer was retired
    # for the netted-book spine; the alias keeps configs/artifacts unchanged.
    assert EngineBackend is SpineBackend
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
    # Intended gross > the operator budget is a fail-closed leverage verdict, surfaced
    # as a typed ``unsupported`` reason rather than a clamped score.
    result = SpineBackend().run(
        decisions=[target(0, 2.0), target(2, 0.0)],
        rows=rows(),
        config=scenario_config(),
    )
    assert result.status == "unsupported"
    assert result.metrics == {}
    assert result.unsupported_semantics == ("leverage_budget_breach",)
    assert any("feasibility:" in warning for warning in result.warnings)


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
