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
        decisions=[decision(sizing_kind="notional")],
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


def test_vectorbtpro_backend_reports_unsupported_multi_asset_target_weights():
    result = VectorBTProBackend().run(
        decisions=[
            decision(symbol="BTC-PERP", size=0.9),
            decision(symbol="ETH-PERP", size=0.1),
        ],
        rows=multi_symbol_rows(),
        config=None,
    )

    assert result.status == "unsupported"
    assert "multi_asset_target_weight" in result.unsupported_semantics


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
