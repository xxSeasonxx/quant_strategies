from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from quant_strategies.core.config import CostModelConfig, DataConfig, FillModelConfig
from quant_strategies.decisions import (
    DecisionIntent,
    ExitPolicy,
    InstrumentRef,
    PositionTarget,
    StrategyDecision,
)
from quant_strategies.validation.agreement import compare, evaluate_agreement
from quant_strategies.validation.config import ScenarioRunConfig
from quant_strategies.validation.engine_backend import EngineBackend

AS_OF = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)

ATOL = 1e-6
RTOL = 1e-3


def bar(minute: int, close: float, *, symbol: str = "BTC-PERP") -> dict:
    ts = datetime(2026, 1, 1, 0, minute, tzinfo=UTC)
    return {
        "symbol": symbol,
        "timestamp": ts,
        "available_at": ts,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "has_funding_event": False,
    }


def decision(
    *,
    minute: int = 0,
    direction: str = "long",
    size: float = 1.0,
    symbol: str = "BTC-PERP",
    **exit_kwargs,
):
    ts = datetime(2026, 1, 1, 0, minute, tzinfo=UTC)
    return StrategyDecision(
        strategy_id="demo",
        instrument=InstrumentRef(kind="crypto_perp", symbol=symbol),
        intent=DecisionIntent(action="open"),
        decision_time=ts,
        as_of_time=ts,
        target=PositionTarget(direction=direction, sizing_kind="target_weight", size=size),
        exit_policy=ExitPolicy(max_hold_bars=1, **exit_kwargs),
    )


def scenario_config():
    return ScenarioRunConfig(
        scenario_id="base",
        fill_model=FillModelConfig(price="close", entry_lag_bars=1, exit_lag_bars=0),
        cost_model=CostModelConfig(fee_bps_per_side=5.0, slippage_bps_per_side=2.0),
        data=DataConfig(
            kind="bars",
            dataset="demo_bars",
            symbols=("BTC-PERP",),
            start=date(2026, 1, 1),
            end=date(2026, 1, 1),
        ),
    )


# --- pure comparator -------------------------------------------------------


def test_compare_passes_within_tolerance():
    result = compare(0.05, 0.0500005, tolerance_abs=ATOL, tolerance_rel=RTOL)
    assert result.status == "pass"
    assert result.abs_deviation == pytest.approx(5e-7)


def test_compare_fails_beyond_tolerance():
    result = compare(0.05, 0.06, tolerance_abs=ATOL, tolerance_rel=RTOL)
    assert result.status == "fail"
    assert result.vbt_return == 0.06


def test_compare_tolerance_scales_with_magnitude():
    # rel tolerance lets large returns absorb proportionally larger deviations.
    assert compare(1.0, 1.0009, tolerance_abs=ATOL, tolerance_rel=RTOL).status == "pass"
    assert compare(1.0, 1.01, tolerance_abs=ATOL, tolerance_rel=RTOL).status == "fail"


def _engine_metrics(decisions, rows, config):
    # The oracle reuses the verdict run's metrics; mirror that here.
    result = EngineBackend().run(decisions=decisions, rows=rows, config=config)
    return result.metrics


def _evaluate(decisions, rows, config):
    return evaluate_agreement(
        engine_metrics=_engine_metrics(decisions, rows, config),
        decisions=decisions,
        rows=rows,
        config=config,
        tolerance_abs=ATOL,
        tolerance_rel=RTOL,
    )


# --- applicability gating --------------------------------------------------


def test_evaluate_agreement_skips_multi_trade_scenarios():
    # The verdict gates on the engine's LINEAR per-trade sum; that equals a NAV
    # path only for one trade. Two sequential trades -> skipped, not compared.
    rows = [bar(m, close) for m, close in enumerate([100.0, 100.0, 110.0, 110.0, 121.0])]
    result = _evaluate([decision(minute=0), decision(minute=2)], rows, scenario_config())
    assert result.status == "skipped"
    assert "not_single_trade:trade_count=2" in result.note


def test_evaluate_agreement_skips_threshold_exit_decisions():
    # Single trade, but vbt cannot model threshold exits -> skip, not fail.
    rows = [bar(m, 100.0 + m) for m in range(4)]
    result = _evaluate([decision(stop_loss_bps=50.0)], rows, scenario_config())
    assert result.status == "skipped"
    assert "vbt_unsupported" in result.note


def test_evaluate_agreement_inconclusive_without_engine_gross():
    # If the verdict metrics lack gross_return (non-engine backend), stay inconclusive.
    result = evaluate_agreement(
        engine_metrics={"net_return": 0.05, "trade_count": 1},
        decisions=[decision(minute=0)],
        rows=[bar(0, 100.0), bar(1, 100.0), bar(2, 105.0)],
        config=scenario_config(),
        tolerance_abs=ATOL,
        tolerance_rel=RTOL,
    )
    assert result.status == "inconclusive"
    assert result.note == "engine_gross_return_missing"


# --- real-vbt golden agreement (the trust anchor) --------------------------


def test_golden_engine_and_vbt_agree_on_single_long():  # F4
    pytest.importorskip("vectorbtpro")
    # One long, target_weight=1, close fill, +5% over the hold, zero cost in the
    # comparison -> the verdict's engine gross == vbt total return.
    rows = [bar(0, 100.0), bar(1, 100.0), bar(2, 105.0)]
    result = _evaluate([decision(minute=0, direction="long", size=1.0)], rows, scenario_config())
    assert result.status == "pass", result
    assert result.engine_return == pytest.approx(0.05, rel=1e-3)
    assert result.vbt_return == pytest.approx(0.05, rel=1e-3)
