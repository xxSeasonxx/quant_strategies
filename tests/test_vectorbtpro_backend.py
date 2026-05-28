from __future__ import annotations

import sys
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from quant_strategies.decisions import (
    DecisionIntent,
    ExitPolicy,
    FutureRef,
    InstrumentLeg,
    InstrumentRef,
    MultiLegInstrumentRef,
    OptionRef,
    PositionTarget,
    StrategyDecision,
)
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


def multi_symbol_rows():
    return rows() + [
        {"symbol": "ETH-PERP", "timestamp": AS_OF, "close": 200.0},
        {"symbol": "ETH-PERP", "timestamp": DECISION, "close": 200.0},
        {
            "symbol": "ETH-PERP",
            "timestamp": datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc),
            "close": 200.0,
        },
        {
            "symbol": "ETH-PERP",
            "timestamp": datetime(2026, 1, 1, 0, 3, tzinfo=timezone.utc),
            "close": 200.0,
        },
    ]


def sparse_symbol_rows():
    return rows() + [
        {"symbol": "ETH-PERP", "timestamp": AS_OF, "close": 200.0},
        {
            "symbol": "ETH-PERP",
            "timestamp": datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc),
            "close": 201.0,
        },
        {
            "symbol": "ETH-PERP",
            "timestamp": datetime(2026, 1, 1, 0, 3, tzinfo=timezone.utc),
            "close": 202.0,
        },
    ]


def overlapping_window_rows():
    return rows() + [
        {
            "symbol": "BTC-PERP",
            "timestamp": datetime(2026, 1, 1, 0, 4, tzinfo=timezone.utc),
            "close": 104.0,
        },
    ]


def unrelated_symbol_timestamp_rows():
    return rows() + [
        {
            "symbol": "ETH-PERP",
            "timestamp": datetime(2026, 1, 1, 0, 1, 30, tzinfo=timezone.utc),
            "close": 200.0,
        },
    ]


def decision(
    *,
    symbol: str = "BTC-PERP",
    decision_time: datetime = DECISION,
    max_hold_bars: int = 1,
    direction: str = "long",
    sizing_kind: str = "target_weight",
    size: float = 1.0,
    instrument=None,
    intent=None,
    **exit_kwargs,
):
    return StrategyDecision(
        strategy_id="demo",
        instrument=instrument or InstrumentRef(kind="crypto_perp", symbol=symbol),
        intent=intent or DecisionIntent(action="open"),
        decision_time=decision_time,
        as_of_time=AS_OF,
        target=PositionTarget(direction=direction, sizing_kind=sizing_kind, size=size),
        exit_policy=ExitPolicy(max_hold_bars=max_hold_bars, **exit_kwargs),
    )


def install_fake_vectorbtpro(monkeypatch, *, total_return: float = 0.0, trade_count: int = 1):
    class FakeTrades:
        def count(self):
            return trade_count

    class FakePortfolio:
        trades = FakeTrades()

        def get_total_return(self):
            return total_return

    fake_vbt = SimpleNamespace(
        Portfolio=SimpleNamespace(from_signals=lambda *args, **kwargs: FakePortfolio())
    )
    monkeypatch.setitem(sys.modules, "vectorbtpro", fake_vbt)
    return fake_vbt


def funding_rows():
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
            "funding_timestamp": datetime(2026, 1, 1, 0, 3, tzinfo=timezone.utc),
            "funding_rate": 0.0003,
            "has_funding_event": True,
        },
    ]


def test_vectorbtpro_backend_extracts_available_optional_metrics(monkeypatch):
    class FakeTrades:
        def count(self):
            return 1

        def profit_factor(self):
            return 2.5

        def win_rate(self):
            return 0.75

    class FakePortfolio:
        trades = FakeTrades()

        def get_total_return(self):
            return 0.04

        def get_max_drawdown(self):
            return -0.12

    fake_vbt = SimpleNamespace(
        Portfolio=SimpleNamespace(from_signals=lambda *args, **kwargs: FakePortfolio())
    )
    monkeypatch.setitem(sys.modules, "vectorbtpro", fake_vbt)

    result = VectorBTProBackend().run(
        decisions=[decision()],
        rows=rows(),
        config=None,
    )

    assert result.status == "completed"
    assert result.metrics["net_return"] == pytest.approx(0.04)
    assert result.metrics["trade_count"] == 1
    assert result.metrics["max_drawdown"] == pytest.approx(-0.12)
    assert result.metrics["profit_factor"] == pytest.approx(2.5)
    assert result.metrics["win_rate"] == pytest.approx(0.75)


def test_vectorbtpro_backend_ignores_missing_optional_metrics(monkeypatch):
    install_fake_vectorbtpro(monkeypatch, total_return=0.04, trade_count=1)

    result = VectorBTProBackend().run(
        decisions=[decision()],
        rows=rows(),
        config=None,
    )

    assert result.status == "completed"
    assert result.metrics["net_return"] == pytest.approx(0.04)
    assert result.metrics["trade_count"] == 1
    assert "max_drawdown" not in result.metrics
    assert "profit_factor" not in result.metrics
    assert "win_rate" not in result.metrics


def test_vectorbtpro_backend_ignores_failed_and_nonfinite_optional_metrics(monkeypatch):
    class FakeTrades:
        def count(self):
            return 1

        def profit_factor(self):
            raise RuntimeError("optional metric unavailable")

    class FakePortfolio:
        trades = FakeTrades()

        def get_total_return(self):
            return 0.04

        def get_max_drawdown(self):
            return float("nan")

    fake_vbt = SimpleNamespace(
        Portfolio=SimpleNamespace(from_signals=lambda *args, **kwargs: FakePortfolio())
    )
    monkeypatch.setitem(sys.modules, "vectorbtpro", fake_vbt)

    result = VectorBTProBackend().run(
        decisions=[decision()],
        rows=rows(),
        config=None,
    )

    assert result.status == "completed"
    assert result.metrics["net_return"] == pytest.approx(0.04)
    assert result.metrics["trade_count"] == 1
    assert "max_drawdown" not in result.metrics
    assert "profit_factor" not in result.metrics
    assert "win_rate" not in result.metrics


def test_vectorbtpro_backend_reports_unsupported_threshold_exits():
    result = VectorBTProBackend().run(
        decisions=[decision(stop_loss_bps=100.0)],
        rows=rows(),
        config=None,
    )

    assert result.status == "unsupported"
    assert result.unsupported_semantics == ("threshold_exit_policy",)


def test_vectorbtpro_backend_adds_funding_return_for_crypto_perp_rows(monkeypatch):
    install_fake_vectorbtpro(monkeypatch, total_return=0.01, trade_count=1)
    config = SimpleNamespace(data=SimpleNamespace(kind="crypto_perp_funding"))

    result = VectorBTProBackend().run(
        decisions=[decision()],
        rows=funding_rows(),
        config=config,
    )

    assert result.status == "completed"
    assert result.unsupported_semantics == ()
    assert result.metrics["net_return"] == pytest.approx(0.01)
    assert result.metrics["funding_return"] == pytest.approx(-0.0003)
    assert result.metrics["linear_funding_adjusted_return"] == pytest.approx(0.0097)
    assert result.metrics["funding_model"] == "linear_additive_adjustment"


def test_vectorbtpro_backend_ignores_non_event_funding_observables(monkeypatch):
    install_fake_vectorbtpro(monkeypatch, total_return=0.01, trade_count=1)
    observable_rows = funding_rows()
    observable_rows[3] = {
        **observable_rows[3],
        "has_funding_event": False,
    }

    result = VectorBTProBackend().run(
        decisions=[decision()],
        rows=observable_rows,
        config=SimpleNamespace(data=SimpleNamespace(kind="crypto_perp_funding")),
    )

    assert result.status == "completed"
    assert result.metrics["net_return"] == pytest.approx(0.01)
    assert result.metrics["funding_return"] == pytest.approx(0.0)
    assert result.metrics["linear_funding_adjusted_return"] == pytest.approx(0.01)
    assert result.metrics["funding_model"] == "linear_additive_adjustment"


def test_vectorbtpro_backend_fails_on_incomplete_funding_event(monkeypatch):
    install_fake_vectorbtpro(monkeypatch, total_return=0.01, trade_count=1)
    bad_rows = funding_rows()
    bad_rows[3] = {**bad_rows[3], "funding_rate": None}

    result = VectorBTProBackend().run(
        decisions=[decision()],
        rows=bad_rows,
        config=SimpleNamespace(data=SimpleNamespace(kind="crypto_perp_funding")),
    )

    assert result.status == "failed"
    assert any("invalid_funding_events:incomplete funding event" in warning for warning in result.warnings)


def test_vectorbtpro_backend_runs_max_hold_decisions():
    pytest.importorskip("vectorbtpro")

    full_result = VectorBTProBackend().run(
        decisions=[decision()],
        rows=rows(),
        config=None,
    )
    quarter_result = VectorBTProBackend().run(
        decisions=[decision(size=0.25)],
        rows=rows(),
        config=None,
    )

    assert full_result.status == "completed"
    assert full_result.backend == "vectorbtpro"
    assert full_result.metrics["trade_count"] == 1
    assert full_result.metrics["net_return"] == pytest.approx((103.0 / 102.0) - 1.0)
    assert quarter_result.status == "completed"
    assert quarter_result.metrics["trade_count"] == 1
    assert 0.0 < quarter_result.metrics["net_return"] < full_result.metrics["net_return"]
    assert quarter_result.metrics["net_return"] == pytest.approx(full_result.metrics["net_return"] * 0.25, rel=0.05)


def test_vectorbtpro_backend_fails_on_missing_symbol():
    result = VectorBTProBackend().run(
        decisions=[decision(symbol="ETH-PERP")],
        rows=rows(),
        config=None,
    )

    assert result.status == "failed"
    assert any("missing_symbol" in warning for warning in result.warnings)


def test_vectorbtpro_backend_prioritizes_missing_symbol_before_unsupported_semantics():
    result = VectorBTProBackend().run(
        decisions=[decision(symbol="ETH-PERP", stop_loss_bps=100.0)],
        rows=rows(),
        config=None,
    )

    assert result.status == "failed"
    assert result.unsupported_semantics == ()
    assert any("missing_symbol" in warning for warning in result.warnings)


def test_vectorbtpro_backend_fails_on_missing_decision_bar():
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


def test_vectorbtpro_backend_requires_symbol_close_at_decision_bar():
    config = SimpleNamespace(fill_model=SimpleNamespace(entry_lag_bars=1, exit_lag_bars=0))

    result = VectorBTProBackend().run(
        decisions=[decision(symbol="ETH-PERP")],
        rows=sparse_symbol_rows(),
        config=config,
    )

    assert result.status == "failed"
    assert any("missing_decision_bar" in warning for warning in result.warnings)


def test_vectorbtpro_backend_fails_on_unfillable_entry():
    config = SimpleNamespace(fill_model=SimpleNamespace(entry_lag_bars=10, exit_lag_bars=0))

    result = VectorBTProBackend().run(
        decisions=[decision()],
        rows=rows(),
        config=config,
    )

    assert result.status == "failed"
    assert any("unfillable_entry" in warning for warning in result.warnings)


def test_vectorbtpro_backend_fails_on_unfillable_exit():
    result = VectorBTProBackend().run(
        decisions=[decision(max_hold_bars=10)],
        rows=rows(),
        config=None,
    )

    assert result.status == "failed"
    assert any("unfillable_exit" in warning for warning in result.warnings)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("entry_lag_bars", -1),
        ("entry_lag_bars", 1.5),
        ("entry_lag_bars", float("nan")),
        ("entry_lag_bars", float("inf")),
        ("entry_lag_bars", "1"),
        ("entry_lag_bars", True),
        ("exit_lag_bars", -1),
        ("exit_lag_bars", 0.5),
        ("exit_lag_bars", float("-inf")),
        ("exit_lag_bars", False),
    ],
)
def test_vectorbtpro_backend_fails_on_invalid_fill_lag(field, value):
    config = {"fill_model": {"entry_lag_bars": 1, "exit_lag_bars": 0, field: value}}

    result = VectorBTProBackend().run(
        decisions=[decision()],
        rows=rows(),
        config=config,
    )

    assert result.status == "failed"
    assert any("invalid_fill_lag" in warning for warning in result.warnings)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("fee_bps_per_side", -0.1),
        ("fee_bps_per_side", float("nan")),
        ("fee_bps_per_side", float("inf")),
        ("fee_bps_per_side", True),
        ("fee_bps_per_side", "1.0"),
        ("slippage_bps_per_side", -0.1),
        ("slippage_bps_per_side", float("-inf")),
        ("slippage_bps_per_side", False),
    ],
)
def test_vectorbtpro_backend_fails_on_invalid_cost_bps(field, value):
    config = {"cost_model": {"fee_bps_per_side": 0.0, "slippage_bps_per_side": 0.0, field: value}}

    result = VectorBTProBackend().run(
        decisions=[decision()],
        rows=rows(),
        config=config,
    )

    assert result.status == "failed"
    assert any("invalid_cost_bps" in warning for warning in result.warnings)


def test_vectorbtpro_backend_prioritizes_unfillable_exit_before_unsupported_fill_price():
    config = SimpleNamespace(fill_model=SimpleNamespace(price="open"))

    result = VectorBTProBackend().run(
        decisions=[decision(max_hold_bars=10)],
        rows=rows(),
        config=config,
    )

    assert result.status == "failed"
    assert result.unsupported_semantics == ()
    assert any("unfillable_exit" in warning for warning in result.warnings)


def test_vectorbtpro_backend_reports_unsupported_non_target_weight_sizing():
    result = VectorBTProBackend().run(
        decisions=[decision(sizing_kind="target_notional")],
        rows=rows(),
        config=None,
    )

    assert result.status == "unsupported"
    assert "non_target_weight_sizing" in result.unsupported_semantics


@pytest.mark.parametrize("fill_price", ["open", "quote"])
def test_vectorbtpro_backend_reports_unsupported_non_close_fill_price(fill_price):
    config = SimpleNamespace(fill_model=SimpleNamespace(price=fill_price))

    result = VectorBTProBackend().run(
        decisions=[decision()],
        rows=rows(),
        config=config,
    )

    assert result.status == "unsupported"
    assert "non_close_fill_price" in result.unsupported_semantics


def test_vectorbtpro_backend_reports_unsupported_leveraged_target_weight():
    result = VectorBTProBackend().run(
        decisions=[decision(size=1.25)],
        rows=rows(),
        config=None,
    )

    assert result.status == "unsupported"
    assert "leveraged_target_weight" in result.unsupported_semantics


def test_vectorbtpro_backend_reports_unsupported_flat_target():
    result = VectorBTProBackend().run(
        decisions=[decision(direction="flat", size=0.0)],
        rows=rows(),
        config=None,
    )

    assert result.status == "unsupported"
    assert "flat_target" in result.unsupported_semantics


def test_vectorbtpro_backend_reports_unsupported_non_open_intent():
    result = VectorBTProBackend().run(
        decisions=[decision(intent=DecisionIntent(action="roll", book_side="buy"))],
        rows=rows(),
        config=None,
    )

    assert result.status == "unsupported"
    assert "non_open_intent" in result.unsupported_semantics


@pytest.mark.parametrize(
    ("instrument", "semantic"),
    [
        (
            FutureRef(
                kind="future",
                symbol="ESM26",
                expiry=DECISION,
                multiplier=1.0,
                settlement="cash",
            ),
            "future_instrument",
        ),
        (
            OptionRef(
                kind="option",
                symbol="SPY260116C00450000",
                underlying_symbol="BTC",
                option_type="call",
                strike=100.0,
                expiry=DECISION,
                multiplier=1.0,
                settlement="cash",
            ),
            "option_instrument",
        ),
        (
            MultiLegInstrumentRef(
                kind="multi_leg",
                symbol="BTC_ETH_SPREAD",
                legs=(
                    InstrumentLeg(
                        instrument=InstrumentRef(kind="crypto_perp", symbol="BTC-PERP"),
                        direction="long",
                        ratio=1.0,
                    ),
                    InstrumentLeg(
                        instrument=InstrumentRef(kind="crypto_perp", symbol="ETH-PERP"),
                        direction="short",
                        ratio=1.0,
                    ),
                ),
            ),
            "multi_leg_decision",
        ),
    ],
)
def test_vectorbtpro_backend_reports_unsupported_instrument_shapes(instrument, semantic):
    result = VectorBTProBackend().run(
        decisions=[decision(instrument=instrument)],
        rows=rows(),
        config=None,
    )

    assert result.status == "unsupported"
    assert semantic in result.unsupported_semantics


def test_vectorbtpro_backend_runs_conservative_multi_asset_target_weights(monkeypatch):
    captured = {}

    class FakeTrades:
        def count(self):
            return 2

    class FakePortfolio:
        trades = FakeTrades()

        def get_total_return(self):
            return 0.05

    def from_signals(close, **kwargs):
        captured["close"] = close
        captured.update(kwargs)
        return FakePortfolio()

    fake_vbt = SimpleNamespace(Portfolio=SimpleNamespace(from_signals=lambda *args, **kwargs: None))
    monkeypatch.setitem(sys.modules, "vectorbtpro", fake_vbt)
    monkeypatch.setattr(fake_vbt.Portfolio, "from_signals", from_signals)

    result = VectorBTProBackend().run(
        decisions=[
            decision(symbol="BTC-PERP", size=0.6),
            decision(symbol="ETH-PERP", size=0.4),
        ],
        rows=multi_symbol_rows(),
        config=None,
    )

    entry_time = datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc)
    assert result.status == "completed"
    assert result.unsupported_semantics == ()
    assert captured["size_type"] == "valuepercent"
    assert captured["cash_sharing"] is True
    assert captured["group_by"] is True
    assert captured["size"].loc[entry_time, "BTC-PERP"] == pytest.approx(0.6)
    assert captured["size"].loc[entry_time, "ETH-PERP"] == pytest.approx(0.4)
    assert result.metrics["portfolio_target_weight_model"] == "vectorbtpro_valuepercent_cash_sharing"
    assert result.metrics["max_gross_target_weight"] == pytest.approx(1.0)


def test_vectorbtpro_backend_fails_when_simultaneous_portfolio_target_weight_exceeds_one():
    result = VectorBTProBackend().run(
        decisions=[
            decision(symbol="BTC-PERP", size=0.7),
            decision(symbol="ETH-PERP", direction="short", size=0.4),
        ],
        rows=multi_symbol_rows(),
        config=None,
    )

    assert result.status == "failed"
    assert any("portfolio_target_weight_exceeds_one" in warning for warning in result.warnings)


def test_vectorbtpro_backend_fails_when_staggered_active_portfolio_target_weight_exceeds_one():
    config = SimpleNamespace(fill_model=SimpleNamespace(entry_lag_bars=0, exit_lag_bars=0))

    result = VectorBTProBackend().run(
        decisions=[
            decision(symbol="BTC-PERP", decision_time=AS_OF, max_hold_bars=3, size=0.6),
            decision(
                symbol="ETH-PERP",
                decision_time=datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc),
                max_hold_bars=1,
                size=0.5,
            ),
        ],
        rows=multi_symbol_rows(),
        config=config,
    )

    assert result.status == "failed"
    assert any("portfolio_target_weight_exceeds_one" in warning for warning in result.warnings)


def test_vectorbtpro_backend_fails_on_duplicate_entry_signal():
    result = VectorBTProBackend().run(
        decisions=[
            decision(size=0.25),
            decision(size=0.50),
        ],
        rows=rows(),
        config=None,
    )

    assert result.status == "failed"
    assert any("duplicate_entry_signal" in warning for warning in result.warnings)


def test_vectorbtpro_backend_fails_on_duplicate_exit_signal():
    config = SimpleNamespace(fill_model=SimpleNamespace(entry_lag_bars=0, exit_lag_bars=0))

    result = VectorBTProBackend().run(
        decisions=[
            decision(max_hold_bars=2),
            decision(
                decision_time=datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc),
                max_hold_bars=1,
            ),
        ],
        rows=rows(),
        config=config,
    )

    assert result.status == "failed"
    assert any("duplicate_exit_signal" in warning for warning in result.warnings)


def test_vectorbtpro_backend_fails_on_overlapping_same_symbol_windows():
    config = SimpleNamespace(fill_model=SimpleNamespace(entry_lag_bars=0, exit_lag_bars=0))

    result = VectorBTProBackend().run(
        decisions=[
            decision(max_hold_bars=3),
            decision(
                decision_time=datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc),
                max_hold_bars=1,
            ),
        ],
        rows=overlapping_window_rows(),
        config=config,
    )

    assert result.status == "failed"
    assert any("overlapping_decision_window" in warning for warning in result.warnings)


def test_vectorbtpro_backend_ignores_unrelated_symbol_timestamps_for_single_symbol_lags(monkeypatch):
    vbt = pytest.importorskip("vectorbtpro")
    captured = {}
    config = SimpleNamespace(fill_model=SimpleNamespace(price="close", entry_lag_bars=1, exit_lag_bars=0))

    class FakeTrades:
        def count(self):
            return 1

    class FakePortfolio:
        trades = FakeTrades()

        def get_total_return(self):
            return 0.05

    def from_signals(close, **kwargs):
        captured["close"] = close
        captured.update(kwargs)
        return FakePortfolio()

    monkeypatch.setattr(vbt.Portfolio, "from_signals", from_signals)

    result = VectorBTProBackend().run(
        decisions=[decision()],
        rows=unrelated_symbol_timestamp_rows(),
        config=config,
    )

    assert result.status == "completed"
    assert list(captured["close"].columns) == ["BTC-PERP"]
    assert datetime(2026, 1, 1, 0, 1, 30, tzinfo=timezone.utc) not in captured["close"].index
    assert captured["long_entries"].loc[datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc), "BTC-PERP"]
    assert captured["long_exits"].loc[datetime(2026, 1, 1, 0, 3, tzinfo=timezone.utc), "BTC-PERP"]


def test_vectorbtpro_backend_reads_mapping_config_fill_and_cost_overrides(monkeypatch):
    vbt = pytest.importorskip("vectorbtpro")
    captured = {}
    config = {
        "fill_model": {"price": "close", "entry_lag_bars": 0, "exit_lag_bars": 1},
        "cost_model": {"fee_bps_per_side": 5.0, "slippage_bps_per_side": 2.5},
    }

    class FakeTrades:
        def count(self):
            return 1

    class FakePortfolio:
        trades = FakeTrades()

        def get_total_return(self):
            return 0.05

    def from_signals(close, **kwargs):
        captured["close"] = close
        captured.update(kwargs)
        return FakePortfolio()

    monkeypatch.setattr(vbt.Portfolio, "from_signals", from_signals)

    result = VectorBTProBackend().run(
        decisions=[decision()],
        rows=rows(),
        config=config,
    )

    assert result.status == "completed"
    assert captured["fees"] == pytest.approx(0.0005)
    assert captured["slippage"] == pytest.approx(0.00025)
    assert captured["long_entries"].loc[DECISION, "BTC-PERP"]
    assert captured["long_exits"].loc[datetime(2026, 1, 1, 0, 3, tzinfo=timezone.utc), "BTC-PERP"]


@pytest.mark.parametrize("close", [float("nan"), float("inf"), float("-inf")])
def test_vectorbtpro_backend_fails_on_nonfinite_close(close):
    bad_rows = rows()
    bad_rows[0] = {"symbol": "BTC-PERP", "timestamp": AS_OF, "close": close}

    result = VectorBTProBackend().run(
        decisions=[decision()],
        rows=bad_rows,
        config=None,
    )

    assert result.status == "failed"
    assert any("nonfinite_close" in warning for warning in result.warnings)


@pytest.mark.parametrize("close", [0.0, -1.0])
def test_vectorbtpro_backend_fails_on_nonpositive_close(close):
    bad_rows = rows()
    bad_rows[0] = {"symbol": "BTC-PERP", "timestamp": AS_OF, "close": close}

    result = VectorBTProBackend().run(
        decisions=[decision()],
        rows=bad_rows,
        config=None,
    )

    assert result.status == "failed"
    assert any("nonpositive_close" in warning for warning in result.warnings)


def test_vectorbtpro_backend_prioritizes_nonpositive_close_before_unsupported_semantics():
    bad_rows = rows()
    bad_rows[0] = {"symbol": "BTC-PERP", "timestamp": AS_OF, "close": 0.0}

    result = VectorBTProBackend().run(
        decisions=[decision(stop_loss_bps=100.0)],
        rows=bad_rows,
        config=None,
    )

    assert result.status == "failed"
    assert result.unsupported_semantics == ()
    assert any("nonpositive_close" in warning for warning in result.warnings)


def test_vectorbtpro_backend_fails_on_duplicate_input_rows():
    bad_rows = rows() + [{"symbol": "BTC-PERP", "timestamp": AS_OF, "close": 100.1}]

    result = VectorBTProBackend().run(
        decisions=[decision()],
        rows=bad_rows,
        config=None,
    )

    assert result.status == "failed"
    assert any("duplicate_rows" in warning for warning in result.warnings)


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
    assert captured_kwargs["size"].loc[datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc), "BTC-PERP"] == 0.25


def test_vectorbtpro_backend_reports_vectorbtpro_run_failure(monkeypatch):
    def from_signals(*args, **kwargs):
        raise RuntimeError("simulation failed")

    fake_vbt = SimpleNamespace(Portfolio=SimpleNamespace(from_signals=from_signals))
    monkeypatch.setitem(sys.modules, "vectorbtpro", fake_vbt)

    result = VectorBTProBackend().run(
        decisions=[decision()],
        rows=rows(),
        config=None,
    )

    assert result.status == "failed"
    assert any("vectorbtpro_run_failed:simulation failed" in warning for warning in result.warnings)


@pytest.mark.parametrize("net_return", [float("nan"), float("inf")])
def test_vectorbtpro_backend_fails_on_nonfinite_net_return(monkeypatch, net_return):
    vbt = pytest.importorskip("vectorbtpro")

    class FakeTrades:
        def count(self):
            return 1

    class FakePortfolio:
        trades = FakeTrades()

        def get_total_return(self):
            return net_return

    monkeypatch.setattr(vbt.Portfolio, "from_signals", lambda *args, **kwargs: FakePortfolio())

    result = VectorBTProBackend().run(
        decisions=[decision()],
        rows=rows(),
        config=None,
    )

    assert result.status == "failed"
    assert any("invalid_metrics:nonfinite_net_return" in warning for warning in result.warnings)


@pytest.mark.parametrize("trade_count", [-1, 1.5])
def test_vectorbtpro_backend_fails_on_invalid_trade_count(monkeypatch, trade_count):
    vbt = pytest.importorskip("vectorbtpro")

    class FakeTrades:
        def count(self):
            return trade_count

    class FakePortfolio:
        trades = FakeTrades()

        def get_total_return(self):
            return 0.05

    monkeypatch.setattr(vbt.Portfolio, "from_signals", lambda *args, **kwargs: FakePortfolio())

    result = VectorBTProBackend().run(
        decisions=[decision()],
        rows=rows(),
        config=None,
    )

    assert result.status == "failed"
    assert any("invalid_metrics:invalid_trade_count" in warning for warning in result.warnings)


def test_vectorbtpro_backend_fails_when_metric_extraction_raises(monkeypatch):
    vbt = pytest.importorskip("vectorbtpro")

    class FakeTrades:
        def count(self):
            return 1

    class FakePortfolio:
        trades = FakeTrades()

        def get_total_return(self):
            raise RuntimeError("metrics unavailable")

    monkeypatch.setattr(vbt.Portfolio, "from_signals", lambda *args, **kwargs: FakePortfolio())

    result = VectorBTProBackend().run(
        decisions=[decision()],
        rows=rows(),
        config=None,
    )

    assert result.status == "failed"
    assert any("metric_extraction_failed:metrics unavailable" in warning for warning in result.warnings)


@pytest.mark.parametrize("trade_count", [0, 2])
def test_vectorbtpro_backend_fails_on_unexpected_trade_count(monkeypatch, trade_count):
    vbt = pytest.importorskip("vectorbtpro")

    class FakeTrades:
        def count(self):
            return trade_count

    class FakePortfolio:
        trades = FakeTrades()

        def get_total_return(self):
            return 0.05

    monkeypatch.setattr(vbt.Portfolio, "from_signals", lambda *args, **kwargs: FakePortfolio())

    result = VectorBTProBackend().run(
        decisions=[decision()],
        rows=rows(),
        config=None,
    )

    assert result.status == "failed"
    assert any("unexpected_trade_count" in warning for warning in result.warnings)
