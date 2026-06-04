from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from quant_strategies.core.config import CostModelConfig, FillModelConfig
from quant_strategies.decisions import DecisionIntent, ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision
from quant_strategies.engine.bar_index import build_bar_index
from quant_strategies.engine.evaluation import EvaluationError, _funding_return
from quant_strategies.engine.models import Bar, Side
from quant_strategies.evaluation.vectorbtpro_backend import VectorBTProEvaluationBackend
from quant_strategies.evaluation.config import EvaluationMetricsConfig
from quant_strategies.evaluation.scenarios import EvaluationScenario
from quant_strategies.funding import funding_rates_match, funding_return_over_window

START = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)


def _ts(minute: int) -> datetime:
    return START + timedelta(minutes=minute)


def _conflict(ts: datetime) -> Exception:
    return ValueError(f"conflicting funding rates at {ts.isoformat()}")


# --- the shared funding-window function (single source of the invariants) ----


@pytest.mark.parametrize(
    "direction_sign, expected",
    [(1.0, -0.00015), (-1.0, 0.00015)],
)
def test_sign_convention_long_pays_short_receives(direction_sign: float, expected: float):
    result = funding_return_over_window(
        [(_ts(1), 0.0003)],
        entry_time=_ts(0),
        exit_time=_ts(2),
        direction_sign=direction_sign,
        weight=0.5,
        conflict_error=_conflict,
    )
    assert result == pytest.approx(expected)


def test_window_is_entry_exclusive_and_exit_inclusive():
    events = [(_ts(1), 0.001), (_ts(2), 0.002), (_ts(3), 0.003)]
    result = funding_return_over_window(
        events,
        entry_time=_ts(1),  # minute 1 excluded
        exit_time=_ts(3),  # minute 3 included
        direction_sign=-1.0,
        weight=1.0,
        conflict_error=_conflict,
    )
    assert result == pytest.approx(0.002 + 0.003)


def test_duplicate_matching_timestamp_counted_once():
    events = [(_ts(1), 0.0002), (_ts(1), 0.0002)]
    result = funding_return_over_window(
        events,
        entry_time=_ts(0),
        exit_time=_ts(2),
        direction_sign=-1.0,
        weight=1.0,
        conflict_error=_conflict,
    )
    assert result == pytest.approx(0.0002)


def test_conflicting_duplicate_timestamp_raises_via_callback():
    events = [(_ts(1), 0.0002), (_ts(1), 0.0003)]
    with pytest.raises(ValueError, match="conflicting funding rates"):
        funding_return_over_window(
            events,
            entry_time=_ts(0),
            exit_time=_ts(2),
            direction_sign=-1.0,
            weight=1.0,
            conflict_error=_conflict,
        )


def test_weight_scales_and_empty_window_is_zero():
    assert (
        funding_return_over_window(
            [],
            entry_time=_ts(0),
            exit_time=_ts(2),
            direction_sign=1.0,
            weight=1.0,
            conflict_error=_conflict,
        )
        == 0.0
    )
    assert funding_return_over_window(
        [(_ts(1), 0.001)],
        entry_time=_ts(0),
        exit_time=_ts(2),
        direction_sign=-1.0,
        weight=2.0,
        conflict_error=_conflict,
    ) == pytest.approx(0.002)


def test_funding_rates_match_tolerance():
    assert funding_rates_match(0.0002, 0.0002 + 5e-13)
    assert not funding_rates_match(0.0002, 0.0003)


# --- the engine adapter (Bar-sourced) over the same shared function -----------


def _engine_indexed(events: list[tuple[int, int, float]]):
    bars = tuple(
        Bar(
            symbol="BTC-PERP",
            timestamp=_ts(bar_minute),
            open=100.0,
            high=100.0,
            low=100.0,
            close=100.0,
            funding_timestamp=_ts(funding_minute),
            funding_rate=rate,
            has_funding_event=True,
        )
        for bar_minute, funding_minute, rate in events
    )
    return build_bar_index(bars, error_factory=EvaluationError)


def test_engine_funding_adapter_signs_and_dedups():
    indexed = _engine_indexed([(1, 1, 0.0002), (2, 1, 0.0002)])  # same funding ts, two bars
    short = _funding_return(indexed, "BTC-PERP", _ts(0), _ts(3), Side.SHORT, 1.0)
    long = _funding_return(indexed, "BTC-PERP", _ts(0), _ts(3), Side.LONG, 1.0)
    assert short == pytest.approx(0.0002)  # short receives positive funding, counted once
    assert long == pytest.approx(-0.0002)


# --- the research-evaluation perp ledger over funding cashflows --------------


def _ledger_decision(
    *,
    direction: str = "long",
    size: float = 1.0,
    max_hold_bars: int = 2,
    decision_minute: int = 0,
) -> StrategyDecision:
    return StrategyDecision(
        strategy_id="demo",
        instrument=InstrumentRef(kind="crypto_perp", symbol="BTC-PERP"),
        intent=DecisionIntent(action="open"),
        decision_time=_ts(decision_minute),
        as_of_time=_ts(decision_minute),
        target=PositionTarget(direction=direction, sizing_kind="target_weight", size=size),
        exit_policy=ExitPolicy(max_hold_bars=max_hold_bars),
    )


def _ledger_scenario(
    *,
    fee_bps_per_side: float = 0.0,
    slippage_bps_per_side: float = 0.0,
) -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="w/zero_costs/base_fill",
        window_id="w",
        cost_scenario="zero_costs",
        fill_scenario="base_fill",
        cost_model=CostModelConfig(
            fee_bps_per_side=fee_bps_per_side,
            slippage_bps_per_side=slippage_bps_per_side,
        ),
        fill_model=FillModelConfig(price="close", entry_lag_bars=1, exit_lag_bars=0),
    )


def _ledger_rows(
    *,
    closes: tuple[float, ...] = (100.0, 100.0, 100.0, 100.0),
    events: tuple[tuple[int, int, float], ...] = (),
) -> list[dict[str, object]]:
    by_bar: dict[int, list[tuple[int, float]]] = {}
    for bar_minute, funding_minute, rate in events:
        by_bar.setdefault(bar_minute, []).append((funding_minute, rate))

    rows: list[dict[str, object]] = []
    for minute, close in enumerate(closes):
        bar_events = by_bar.get(minute, [])
        if not bar_events:
            rows.append(
                {
                    "symbol": "BTC-PERP",
                    "timestamp": _ts(minute),
                    "close": close,
                    "has_funding_event": False,
                }
            )
            continue
        first_event, *extra_events = bar_events
        rows.append(
            {
                "symbol": "BTC-PERP",
                "timestamp": _ts(minute),
                "close": close,
                "has_funding_event": True,
                "funding_timestamp": _ts(first_event[0]),
                "funding_rate": first_event[1],
            }
        )
        for offset, (funding_minute, rate) in enumerate(extra_events, start=1):
            duplicate_minute = len(closes) + minute + offset
            rows.append(
                {
                    "symbol": "BTC-PERP",
                    "timestamp": _ts(duplicate_minute),
                    "close": close,
                    "has_funding_event": True,
                    "funding_timestamp": _ts(funding_minute),
                    "funding_rate": rate,
                }
            )
    return rows


def _run_ledger(
    *,
    direction: str = "long",
    decisions: list[StrategyDecision] | None = None,
    rows: list[dict[str, object]] | None = None,
    scenario: EvaluationScenario | None = None,
    max_hold_bars: int = 2,
):
    return VectorBTProEvaluationBackend().run(
        decisions=decisions or [_ledger_decision(direction=direction, max_hold_bars=max_hold_bars)],
        rows=rows or _ledger_rows(),
        scenario=scenario or _ledger_scenario(),
        metrics=EvaluationMetricsConfig(annualization_periods_per_year=365),
        data_kind="crypto_perp_funding",
    )


@pytest.mark.parametrize(
    ("rate", "long_funding", "short_funding"),
    [
        (0.01, -1.0, 1.0),
        (-0.01, 1.0, -1.0),
    ],
)
def test_perp_ledger_funding_signs_longs_and_shorts(rate: float, long_funding: float, short_funding: float):
    rows = _ledger_rows(events=((2, 2, rate),))

    long = _run_ledger(direction="long", rows=rows)
    short = _run_ledger(direction="short", rows=rows)

    assert long.status == "completed"
    assert short.status == "completed"
    assert long.metrics["funding_cashflow_total"] == pytest.approx(long_funding)
    assert short.metrics["funding_cashflow_total"] == pytest.approx(short_funding)
    assert long.metrics["ending_value"] == pytest.approx(100.0 + long_funding)
    assert short.metrics["ending_value"] == pytest.approx(100.0 + short_funding)
    assert long.metrics["funding_model"] == "project_perp_ledger_v1"


def test_perp_ledger_excludes_entry_timestamp_funding_and_includes_exit_timestamp_funding():
    entry_event = _run_ledger(rows=_ledger_rows(events=((1, 1, 0.01),)))
    exit_event = _run_ledger(rows=_ledger_rows(events=((3, 3, 0.01),)))

    assert entry_event.status == "completed"
    assert entry_event.metrics["funding_cashflow_total"] == pytest.approx(0.0)
    assert entry_event.metrics["funding_event_count"] == 0
    assert entry_event.tables is not None
    assert entry_event.tables.funding_cashflows.empty
    assert exit_event.status == "completed"
    assert exit_event.metrics["funding_cashflow_total"] == pytest.approx(-1.0)
    assert exit_event.metrics["funding_event_count"] == 1


def test_perp_ledger_full_weight_exposure_pays_funding():
    result = _run_ledger(rows=_ledger_rows(events=((2, 2, 0.005),)))

    assert result.status == "completed"
    assert result.metrics["funding_cashflow_total"] == pytest.approx(-0.5)
    assert result.metrics["total_return"] == pytest.approx(-0.005)


def test_perp_ledger_pins_price_pnl_plus_funding_cashflow():
    result = _run_ledger(
        rows=_ledger_rows(
            closes=(100.0, 100.0, 110.0, 120.0),
            events=((2, 2, 0.01),),
        ),
    )

    assert result.status == "completed"
    assert result.tables is not None
    trade = result.tables.trades.iloc[0]
    assert trade["signed_units"] == pytest.approx(1.0)
    assert trade["entry_fill_price"] == pytest.approx(100.0)
    assert trade["exit_fill_price"] == pytest.approx(120.0)
    assert trade["realized_pnl"] == pytest.approx(20.0)
    assert trade["funding_cashflow"] == pytest.approx(-1.1)
    assert trade["net_pnl"] == pytest.approx(18.9)
    assert result.metrics["ending_value"] == pytest.approx(118.9)
    assert result.metrics["total_return"] == pytest.approx(0.189)
    assert result.metrics["funding_cashflow_total"] == pytest.approx(-1.1)
    assert result.metrics["funding_event_count"] == 1


def test_perp_ledger_duplicate_matching_funding_rates_dedupe():
    rows = _ledger_rows(closes=(100.0, 100.0, 100.0, 100.0, 100.0), events=((2, 2, 0.01), (4, 2, 0.01)))

    result = _run_ledger(rows=rows)

    assert result.status == "completed"
    assert result.metrics["funding_cashflow_total"] == pytest.approx(-1.0)
    assert result.metrics["funding_event_count"] == 1


def test_perp_ledger_ignores_unused_symbol_funding_events():
    rows = _ledger_rows(events=((2, 2, 0.01),))
    rows.extend(
        [
            {
                "symbol": "ETH-PERP",
                "timestamp": _ts(minute),
                "close": 200.0,
                "has_funding_event": minute == 2,
                **(
                    {"funding_timestamp": _ts(2), "funding_rate": 0.50}
                    if minute == 2
                    else {}
                ),
            }
            for minute in range(4)
        ]
    )

    result = _run_ledger(rows=rows)

    assert result.status == "completed"
    assert result.metrics["funding_cashflow_total"] == pytest.approx(-1.0)
    assert set(result.tables.funding_cashflows["asset"]) == {"BTC-PERP"}


def test_perp_ledger_allows_same_symbol_exit_and_reentry_on_same_timestamp():
    decisions = [
        _ledger_decision(max_hold_bars=1, decision_minute=0),
        _ledger_decision(max_hold_bars=1, decision_minute=1),
    ]
    result = _run_ledger(
        decisions=decisions,
        rows=_ledger_rows(events=((2, 2, 0.01),)),
    )

    assert result.status == "completed"
    assert result.metrics["trade_count"] == 2
    assert result.metrics["funding_cashflow_total"] == pytest.approx(-1.0)
    assert list(result.tables.funding_cashflows["timestamp"]) == [_ts(2)]


def test_perp_ledger_conflicting_duplicate_funding_rates_fail():
    rows = _ledger_rows(closes=(100.0, 100.0, 100.0, 100.0, 100.0), events=((2, 2, 0.01), (4, 2, 0.02)))

    result = _run_ledger(rows=rows)

    assert result.status == "failed"
    assert "conflicting_funding_rates:BTC-PERP:" in result.warnings[0]


def test_perp_ledger_missing_funding_timestamp_alignment_fails():
    result = _run_ledger(rows=_ledger_rows(events=((2, 9, 0.01),)))

    assert result.status == "failed"
    assert "funding_timestamp_not_aligned:BTC-PERP:" in result.warnings[0]


def test_perp_ledger_fees_and_slippage_affect_realized_pnl():
    scenario = _ledger_scenario(fee_bps_per_side=100.0, slippage_bps_per_side=100.0)
    result = _run_ledger(
        rows=_ledger_rows(closes=(100.0, 100.0, 110.0)),
        scenario=scenario,
        max_hold_bars=1,
    )

    assert result.status == "completed"
    assert result.tables is not None
    trade = result.tables.trades.iloc[0]
    units = 100.0 / 101.0
    realized_pnl = units * (108.9 - 101.0)
    exit_fee = abs(units * 108.9) * 0.01
    expected_net_pnl = realized_pnl - 1.0 - exit_fee
    assert trade["entry_fill_price"] == pytest.approx(101.0)
    assert trade["exit_fill_price"] == pytest.approx(108.9)
    assert trade["entry_fee"] == pytest.approx(1.0)
    assert trade["exit_fee"] == pytest.approx(exit_fee)
    assert trade["realized_pnl"] == pytest.approx(realized_pnl)
    assert trade["net_pnl"] == pytest.approx(expected_net_pnl)
    assert result.metrics["ending_value"] == pytest.approx(100.0 + expected_net_pnl)
