from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from quant_strategies.decisions import ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision
from quant_strategies.validation.vectorbtpro_backend import VectorBTProBackend


AS_OF = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
DECISION = datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc)


def rows():
    return [
        {"symbol": "BTC-PERP", "timestamp": AS_OF, "close": 100.0},
        {"symbol": "BTC-PERP", "timestamp": DECISION, "close": 101.0},
        {
            "symbol": "BTC-PERP",
            "timestamp": datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc),
            "close": 102.0,
        },
        {
            "symbol": "BTC-PERP",
            "timestamp": datetime(2026, 1, 1, 0, 3, tzinfo=timezone.utc),
            "close": 103.0,
        },
    ]


def decision(
    *,
    symbol: str = "BTC-PERP",
    decision_time: datetime = DECISION,
    max_hold_bars: int = 1,
    sizing_kind: str = "target_weight",
    size: float = 1.0,
    **exit_kwargs,
):
    return StrategyDecision(
        strategy_id="demo",
        instrument=InstrumentRef(kind="crypto_perp", symbol=symbol),
        decision_time=decision_time,
        as_of_time=AS_OF,
        target=PositionTarget(direction="long", sizing_kind=sizing_kind, size=size),
        exit_policy=ExitPolicy(max_hold_bars=max_hold_bars, **exit_kwargs),
    )


def test_vectorbtpro_backend_reports_unsupported_threshold_exits():
    result = VectorBTProBackend().run(
        decisions=[decision(stop_loss_bps=100.0)],
        rows=rows(),
        config=None,
    )

    assert result.status == "unsupported"
    assert result.unsupported_semantics == ("threshold_exit_policy",)


def test_vectorbtpro_backend_runs_max_hold_decisions():
    pytest.importorskip("vectorbtpro")

    result = VectorBTProBackend().run(
        decisions=[decision()],
        rows=rows(),
        config=None,
    )

    assert result.status == "completed"
    assert result.backend == "vectorbtpro"
    assert result.metrics["trade_count"] >= 0
    assert "net_return" in result.metrics


def test_vectorbtpro_backend_fails_on_missing_symbol():
    pytest.importorskip("vectorbtpro")

    result = VectorBTProBackend().run(
        decisions=[decision(symbol="ETH-PERP")],
        rows=rows(),
        config=None,
    )

    assert result.status == "failed"
    assert any("missing_symbol" in warning for warning in result.warnings)


def test_vectorbtpro_backend_fails_on_missing_decision_bar():
    pytest.importorskip("vectorbtpro")

    result = VectorBTProBackend().run(
        decisions=[
            decision(
                decision_time=datetime(2026, 1, 1, 0, 10, tzinfo=timezone.utc),
            )
        ],
        rows=rows(),
        config=None,
    )

    assert result.status == "failed"
    assert any("missing_decision_bar" in warning for warning in result.warnings)


def test_vectorbtpro_backend_fails_on_unfillable_entry():
    pytest.importorskip("vectorbtpro")
    config = SimpleNamespace(fill_model=SimpleNamespace(entry_lag_bars=10, exit_lag_bars=0))

    result = VectorBTProBackend().run(
        decisions=[decision()],
        rows=rows(),
        config=config,
    )

    assert result.status == "failed"
    assert any("unfillable_entry" in warning for warning in result.warnings)


def test_vectorbtpro_backend_fails_on_unfillable_exit():
    pytest.importorskip("vectorbtpro")

    result = VectorBTProBackend().run(
        decisions=[decision(max_hold_bars=10)],
        rows=rows(),
        config=None,
    )

    assert result.status == "failed"
    assert any("unfillable_exit" in warning for warning in result.warnings)


def test_vectorbtpro_backend_reports_unsupported_non_target_weight_sizing():
    result = VectorBTProBackend().run(
        decisions=[decision(sizing_kind="notional")],
        rows=rows(),
        config=None,
    )

    assert result.status == "unsupported"
    assert "non_target_weight_sizing" in result.unsupported_semantics


def test_vectorbtpro_backend_passes_target_weight_size_to_vectorbtpro(monkeypatch):
    vbt = pytest.importorskip("vectorbtpro")
    captured_kwargs = {}

    class FakeTrades:
        def count(self):
            return 1

    class FakePortfolio:
        trades = FakeTrades()

        def get_total_return(self):
            return 0.05

    def from_signals(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return FakePortfolio()

    monkeypatch.setattr(vbt.Portfolio, "from_signals", from_signals)

    result = VectorBTProBackend().run(
        decisions=[decision(size=0.25)],
        rows=rows(),
        config=None,
    )

    assert result.status == "completed"
    assert "size" in captured_kwargs
    assert "size_type" in captured_kwargs
    assert captured_kwargs["size"].loc[DECISION, "BTC-PERP"] == 0.25
