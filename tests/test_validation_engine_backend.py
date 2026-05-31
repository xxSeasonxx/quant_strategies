from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from quant_strategies.core.config import CostModelConfig, DataConfig, FillModelConfig
from quant_strategies.decisions import (
    DecisionIntent,
    ExitPolicy,
    InstrumentRef,
    PositionTarget,
    StrategyDecision,
)
from quant_strategies.validation.config import ScenarioRunConfig
from quant_strategies.validation.engine_backend import EngineBackend

AS_OF = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
DECISION = datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc)


def bar(minute: int, close: float) -> dict:
    # Engine requires OHLC; flat bars (o=h=l=c) are valid and keep close-fills exact.
    return {
        "symbol": "BTC-PERP",
        "timestamp": datetime(2026, 1, 1, 0, minute, tzinfo=timezone.utc),
        "open": close,
        "high": close,
        "low": close,
        "close": close,
    }


def rows():
    return [bar(0, 100.0), bar(1, 101.0), bar(2, 102.0), bar(3, 103.0)]


def funding_rows():
    base = rows()
    base[-1] = {
        **base[-1],
        "funding_timestamp": datetime(2026, 1, 1, 0, 3, tzinfo=timezone.utc),
        "funding_rate": 0.0003,
        "has_funding_event": True,
    }
    return base


def decision(*, max_hold_bars: int = 1, direction: str = "long", size: float = 1.0, **exit_kwargs):
    return StrategyDecision(
        strategy_id="demo",
        instrument=InstrumentRef(kind="crypto_perp", symbol="BTC-PERP"),
        intent=DecisionIntent(action="open"),
        decision_time=DECISION,
        as_of_time=AS_OF,
        target=PositionTarget(direction=direction, sizing_kind="target_weight", size=size),
        exit_policy=ExitPolicy(max_hold_bars=max_hold_bars, **exit_kwargs),
    )


def scenario_config(*, fee_bps: float = 0.0, slippage_bps: float = 0.0):
    return ScenarioRunConfig(
        scenario_id="realistic",
        params={},
        fill_model=FillModelConfig(price="close", entry_lag_bars=1, exit_lag_bars=0),
        cost_model=CostModelConfig(fee_bps_per_side=fee_bps, slippage_bps_per_side=slippage_bps),
        data=DataConfig(
            kind="crypto_perp_funding",
            symbols=("BTC-PERP",),
            start=date(2026, 1, 1),
            end=date(2026, 1, 1),
        ),
    )


def test_engine_backend_maps_trade_result_net_to_net_return():
    result = EngineBackend().run(decisions=[decision()], rows=rows(), config=scenario_config())

    assert result.backend == "engine"
    assert result.status == "completed"
    assert result.metrics["trade_count"] == 1
    # entry at close 102, exit at close 103, long, weight 1.0, no funding/cost.
    expected_gross = (103.0 - 102.0) / 102.0
    assert result.metrics["net_return"] == pytest.approx(expected_gross)
    assert result.metrics["gross_return"] == pytest.approx(expected_gross)


def test_engine_backend_extras_are_internally_consistent():
    result = EngineBackend().run(
        decisions=[decision()], rows=rows(), config=scenario_config(fee_bps=5.0, slippage_bps=2.0)
    )
    m = result.metrics
    # net == gross + funding - cost.
    assert m["net_return"] == pytest.approx(m["gross_return"] + m["funding_return"] - m["cost_return"])
    # round-trip cost = 2*(fee+slippage)/1e4 * weight.
    assert m["cost_return"] == pytest.approx(2.0 * (5.0 + 2.0) / 10_000.0 * 1.0)


def test_engine_backend_net_return_is_funding_inclusive():
    # A long position paying funding: net_return must be below the pure price path.
    result = EngineBackend().run(decisions=[decision()], rows=funding_rows(), config=scenario_config())
    m = result.metrics
    assert m["funding_return"] == pytest.approx(-0.0003)  # long pays positive funding
    assert m["net_return"] == pytest.approx(m["gross_return"] + m["funding_return"])
    assert m["net_return"] < m["gross_return"]  # funding drags net below the price path


def test_engine_backend_funding_can_flip_gated_net_negative():
    # F2: the verdict gates on this net_return, and it is funding-inclusive. A perp
    # with a profitable price path but a large funding cost has a *negative* gated
    # net_return, so it cannot clear the validation net floors -- the exact economic
    # correctness the pre-P0 funding-excluded "net" gate violated.
    big_funding = rows()
    big_funding[-1] = {
        **big_funding[-1],
        "funding_timestamp": datetime(2026, 1, 1, 0, 3, tzinfo=timezone.utc),
        "funding_rate": 0.05,  # large positive funding rate; a long pays it
        "has_funding_event": True,
    }
    result = EngineBackend().run(decisions=[decision()], rows=big_funding, config=scenario_config())
    m = result.metrics
    assert m["gross_return"] > 0.0  # price path alone is profitable
    assert m["funding_return"] == pytest.approx(-0.05)
    assert m["net_return"] < 0.0  # but the funding-inclusive gated number is a loss
    assert m["net_return"] == pytest.approx(m["gross_return"] - 0.05)


def test_engine_backend_metrics_feed_backend_metrics_contract():
    from quant_strategies.validation.backends import BackendMetrics

    result = EngineBackend().run(decisions=[decision()], rows=rows(), config=scenario_config())
    metrics = BackendMetrics.from_mapping(result.metrics)
    assert metrics is not None
    assert metrics.trade_count == 1
    assert metrics.net_return == pytest.approx((103.0 - 102.0) / 102.0)


def test_engine_backend_supports_threshold_exit_decisions():
    # F7: a stop-loss/take-profit decision is screenable by the engine. The vbt
    # backend marked threshold_exit_policy "unsupported" -> hard_no; the engine
    # (the single verdict source) completes it, so quick-runnable candidates with
    # threshold exits are now validatable.
    result = EngineBackend().run(
        decisions=[decision(stop_loss_bps=50.0, take_profit_bps=300.0)],
        rows=rows(),
        config=scenario_config(),
    )
    assert result.status == "completed"
    assert result.unsupported_semantics == ()
    assert result.metrics["trade_count"] == 1


def test_engine_backend_returns_failed_on_unfillable_window():
    # max_hold pushes the exit past the available bars -> build_request raises.
    result = EngineBackend().run(
        decisions=[decision(max_hold_bars=10)], rows=rows(), config=scenario_config()
    )
    assert result.status == "failed"
    assert result.metrics == {}
    assert result.warnings  # carries the original error message
