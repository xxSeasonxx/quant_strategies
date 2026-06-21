"""Property tests for the scale-homogeneity book-scale sizing.

The frontier and the volatility target are no longer found by blind bisection: the
leverage cap is exact in the book scale ``s``, and capacity participation and at-risk
volatility are first-order linear in ``s`` (with a NAV-compounding + market-impact
residual), so they are seeded analytically and refined with a safeguarded bracketed
secant. These tests pin the durable properties of that design:

- **Equivalence to tolerance** — the analytic+secant ``book_scale`` matches an independent
  bisection reference (the pre-redesign algorithm, rebuilt here on the public single
  walk) within the volatility tolerance, across a representative book battery.
- **Feasibility** — a walk at the returned ``book_scale`` is feasible for every book.
- **Homogeneity invariants** — exact leverage linearity, first-order participation/volatility
  linearity, and monotonicity in ``s``.

The reference bisection lives here, not in product code: the redesign removed it, and an
equivalence test needs an oracle independent of the code under test.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

# Reuse the established synthetic-book builders (the repo allows cross-test imports;
# pythonpath includes the repo root).
from tests.test_portfolio_foundation import (
    calibrating_config,
    capacity_model,
    data_config,
    target,
    volatile_bar_rows,
)

import quant_strategies.core.portfolio_foundation as foundation_module
from quant_strategies.core.config import CostModelConfig, FillModelConfig, RiskBudgetConfig
from quant_strategies.core.portfolio_foundation import (
    REASON_UNPRICED_SHORT_FINANCING,
    FeasibilityError,
    PortfolioFoundationConfig,
    build_portfolio_foundation,
    walk_portfolio_book,
)

FILL = FillModelConfig(price="close", entry_lag_bars=1)
COST = CostModelConfig(fee_bps_per_side=1.0, slippage_bps_per_side=0.5)


# --------------------------------------------------------------------------------------
# Independent reference: the pre-redesign frontier + volatility bisection, rebuilt on the
# public single-walk entry. ``walk_portfolio_book`` under a ``fixed_scale`` budget at
# scale ``s`` runs the exact candidate walk the calibrator scores, raising the same
# fail-closed verdict and reporting the same deployed volatility.
# --------------------------------------------------------------------------------------

_ITERATIONS = foundation_module._CALIBRATION_ITERATIONS


def _fixed_scale_config(
    config: PortfolioFoundationConfig, scale: float
) -> PortfolioFoundationConfig:
    fixed = RiskBudgetConfig(
        mode="fixed_scale",
        annualization_periods_per_year=config.risk_budget.annualization_periods_per_year,
        book_scale=scale,
    )
    return replace(config, risk_budget=fixed)


def _deployed_vol(walk) -> float | None:
    assert walk.sizing_report is not None
    return walk.sizing_report.deployed_volatility


def _leverage_cap(rows, decisions, fill_model, config) -> float:
    raw_plan = foundation_module._DecisionPlan(
        foundation_module._RowIndex(rows, ()), decisions, fill_model=fill_model
    )
    _, shape = foundation_module._normalized_shape_plan(raw_plan)
    if shape.normalized_max_gross <= foundation_module._EXPOSURE_TOLERANCE:
        return 0.0
    scale, _ = foundation_module._leverage_frontier_scale(shape, config)
    return scale


def _oracle_book_scale(
    *, rows, decisions, data, fill_model, cost_model, capacity_model, config
) -> float:
    """Pre-redesign frontier+volatility bisection, computed independently of the
    analytic+secant code under test."""
    target_volatility = config.risk_budget.target_volatility
    leverage_scale = _leverage_cap(rows, decisions, fill_model, config)
    if leverage_scale <= 0.0:
        return 0.0

    def probe(scale: float) -> tuple[bool, float | None]:
        try:
            walk = walk_portfolio_book(
                rows=rows,
                decisions=decisions,
                data=data,
                fill_model=fill_model,
                cost_model=cost_model,
                capacity_model=capacity_model,
                config=_fixed_scale_config(config, scale),
            )
        except FeasibilityError:
            return False, None
        return True, _deployed_vol(walk)

    # Frontier: feasibility bisection in [0, leverage_scale].
    feasible_at_cap, _ = probe(leverage_scale)
    if feasible_at_cap:
        frontier = leverage_scale
    else:
        low, high = 0.0, leverage_scale
        for _ in range(_ITERATIONS):
            mid = (low + high) / 2.0
            feasible, _ = probe(mid)
            if feasible:
                low = mid
            else:
                high = mid
        frontier = low

    ceiling = foundation_module._volatility_ceiling(target_volatility)
    _, frontier_vol = probe(frontier)
    if frontier_vol is None or frontier_vol <= ceiling:
        return frontier

    # Volatility-target bisection in [0, frontier].
    low, high = 0.0, frontier
    best = 0.0
    for _ in range(_ITERATIONS):
        mid = (low + high) / 2.0
        _, vol = probe(mid)
        if vol is None or vol <= ceiling:
            best = mid
            low = mid
        else:
            high = mid
    return best


# --------------------------------------------------------------------------------------
# Representative book battery
# --------------------------------------------------------------------------------------


def _single_symbol_book():
    return {
        "rows": volatile_bar_rows(),
        "decisions": [target(0, 1.0), target(8, 0.0)],
        "data": data_config(9),
        "fill_model": FILL,
        "cost_model": COST,
    }


def _multi_symbol_book():
    rows = volatile_bar_rows(symbol="SPY") + volatile_bar_rows(symbol="QQQ")
    return {
        "rows": rows,
        "decisions": [target(0, 0.6, symbol="SPY"), target(0, 0.4, symbol="QQQ"), target(8, 0.0)],
        "data": data_config(9, symbols=("SPY", "QQQ")),
        "fill_model": FILL,
        "cost_model": COST,
    }


@pytest.mark.parametrize("target_volatility", [0.05, 0.1, 0.2, 0.5])
def test_vol_bound_book_scale_matches_bisection_reference(target_volatility):
    book = _single_symbol_book()
    config = calibrating_config(target_volatility)
    capacity = capacity_model(portfolio_notional=1_000.0)

    foundation = build_portfolio_foundation(capacity_model=capacity, config=config, **book)
    reference = _oracle_book_scale(capacity_model=capacity, config=config, **book)

    report = foundation.sizing_report
    assert report.book_scale == pytest.approx(reference, rel=2e-3)
    assert report.deployed_volatility is not None
    assert report.deployed_volatility <= foundation_module._volatility_ceiling(target_volatility)
    # Deployed volatility lands within the target tolerance band (the calibration goal).
    assert report.deployed_volatility == pytest.approx(target_volatility, rel=5e-4)


def test_multi_asset_book_scale_matches_bisection_reference():
    book = _multi_symbol_book()
    config = calibrating_config(0.15)
    capacity = capacity_model(portfolio_notional=1_000.0)

    foundation = build_portfolio_foundation(capacity_model=capacity, config=config, **book)
    reference = _oracle_book_scale(capacity_model=capacity, config=config, **book)

    assert foundation.sizing_report.book_scale == pytest.approx(reference, rel=2e-3)


def test_capacity_bound_book_scale_matches_bisection_reference():
    book = _single_symbol_book()
    config = calibrating_config(10.0)
    capacity = capacity_model(
        portfolio_notional=1_000.0, max_bar_participation=1e-5, max_adv_participation=1e-5
    )

    foundation = build_portfolio_foundation(capacity_model=capacity, config=config, **book)
    reference = _oracle_book_scale(capacity_model=capacity, config=config, **book)

    report = foundation.sizing_report
    # The feasibility boundary carries an absolute participation tolerance, so the frontier
    # is fuzzy by ~_EXPOSURE_TOLERANCE/limit in utilization (~1e-4 at limit 1e-5). The
    # analytic search stops at utilization 1.0 (conservative); the bisection reference rides
    # the tolerance edge just above it. They agree within that fuzz, with the analytic side
    # at or below the reference.
    assert report.book_scale == pytest.approx(reference, rel=1e-3)
    assert report.book_scale <= reference * (1.0 + 1e-9)
    assert report.capacity_bound is True
    assert "capacity" in report.binding_dimensions


def test_capacity_frontier_first_breach_below_peak_converges():
    # The chronologically-first breach (the small early entry) is NOT the
    # max-participation bar (the later scale-up), so the breach-seeded secant endpoint
    # understates the true peak. The midpoint-capped safeguard must still converge to a
    # positive frontier matching the bisection reference, never stalling at 0.
    rows = volatile_bar_rows()
    decisions = [target(0, 0.1), target(3, 1.0), target(8, 0.0)]
    config = calibrating_config(10.0)
    capacity = capacity_model(
        portfolio_notional=1_000.0, max_bar_participation=1e-4, max_adv_participation=1e-4
    )
    book = {
        "rows": rows,
        "decisions": decisions,
        "data": data_config(9),
        "fill_model": FILL,
        "cost_model": COST,
    }

    foundation = build_portfolio_foundation(capacity_model=capacity, config=config, **book)
    reference = _oracle_book_scale(capacity_model=capacity, config=config, **book)

    report = foundation.sizing_report
    assert report.book_scale > 0.0
    assert report.book_scale == pytest.approx(reference, rel=1e-3)
    assert report.book_scale <= reference * (1.0 + 1e-9)
    assert report.capacity_bound is True
    assert "capacity" in report.binding_dimensions


def test_leverage_bound_book_scale_is_exact():
    # A high target volatility leaves the book frontier-bound at the exact analytic
    # leverage cap. The single long position normalizes to gross == net == 1.0 and the
    # operator gross/net budgets are 1.0, so the cap is exactly 1.0 with no secant
    # residual. (An equity net above 1.0 is correctly an unfinanced fail-closed, so the
    # operator budget cannot exceed 1.0 here.)
    book = _single_symbol_book()
    config = calibrating_config(50.0)
    capacity = capacity_model(portfolio_notional=1_000.0)

    foundation = build_portfolio_foundation(capacity_model=capacity, config=config, **book)

    report = foundation.sizing_report
    assert report.book_scale == pytest.approx(1.0, rel=1e-12)
    assert report.final_max_intended_gross == pytest.approx(1.0, rel=1e-12)
    assert set(report.binding_dimensions) == {"gross_leverage", "net_leverage"}


def test_flat_book_has_zero_scale():
    foundation = build_portfolio_foundation(
        rows=volatile_bar_rows(),
        decisions=[],
        data=data_config(9),
        fill_model=FILL,
        cost_model=COST,
        capacity_model=capacity_model(portfolio_notional=1_000.0),
        config=calibrating_config(0.2),
    )
    report = foundation.sizing_report
    assert report.book_scale == pytest.approx(0.0)
    assert report.capacity_bound is False
    assert report.binding_dimensions == ()


def test_unpriced_short_fails_closed_at_every_scale():
    # An unfinanced short is a scale-independent hard fail; calibration must surface it as
    # a typed fail-closed verdict, never size around it.
    with pytest.raises(FeasibilityError) as excinfo:
        build_portfolio_foundation(
            rows=volatile_bar_rows(),
            decisions=[target(0, -1.0), target(8, 0.0)],
            data=data_config(9),
            fill_model=FILL,
            cost_model=COST,
            capacity_model=capacity_model(portfolio_notional=1_000.0),
            config=calibrating_config(0.2),
        )
    assert excinfo.value.verdict.reason == REASON_UNPRICED_SHORT_FINANCING


# --------------------------------------------------------------------------------------
# Homogeneity invariants and result feasibility
# --------------------------------------------------------------------------------------


def test_returned_book_scale_is_feasible_for_each_book():
    cases = [
        (
            _single_symbol_book(),
            calibrating_config(0.2),
            capacity_model(portfolio_notional=1_000.0),
        ),
        (
            _multi_symbol_book(),
            calibrating_config(0.15),
            capacity_model(portfolio_notional=1_000.0),
        ),
        (
            _single_symbol_book(),
            calibrating_config(10.0),
            capacity_model(
                portfolio_notional=1_000.0, max_bar_participation=1e-5, max_adv_participation=1e-5
            ),
        ),
    ]
    for book, config, capacity in cases:
        foundation = build_portfolio_foundation(capacity_model=capacity, config=config, **book)
        scale = foundation.sizing_report.book_scale
        # Re-walk at the recorded scale under a fixed-scale budget: must not raise and must
        # be feasible.
        walk = walk_portfolio_book(
            capacity_model=capacity,
            config=_fixed_scale_config(config, scale),
            **book,
        )
        assert walk.feasibility.feasible is True


def test_intended_exposure_is_exactly_linear_in_scale():
    book = _single_symbol_book()
    capacity = capacity_model(portfolio_notional=1_000.0)
    config = calibrating_config(0.2)

    def intended_gross(scale: float) -> float:
        walk = walk_portfolio_book(
            capacity_model=capacity,
            config=_fixed_scale_config(config, scale),
            **book,
        )
        assert walk.sizing_report is not None
        return walk.sizing_report.final_max_intended_gross

    base = intended_gross(0.3)
    assert intended_gross(0.6) == pytest.approx(2.0 * base, rel=1e-12)
    assert intended_gross(0.9) == pytest.approx(3.0 * base, rel=1e-12)


def test_participation_and_volatility_are_first_order_linear_and_monotone():
    book = _single_symbol_book()
    # Negligible cost so the linear term dominates and the NAV/impact residual is tiny.
    book["cost_model"] = CostModelConfig(fee_bps_per_side=0.1, slippage_bps_per_side=0.1)
    capacity = capacity_model(portfolio_notional=1_000.0)
    config = calibrating_config(0.2)

    def metrics(scale: float) -> tuple[float, float]:
        walk = walk_portfolio_book(
            capacity_model=capacity,
            config=_fixed_scale_config(config, scale),
            **book,
        )
        util = foundation_module._capacity_utilization(walk, capacity)
        vol = _deployed_vol(walk)
        assert vol is not None
        return util, vol

    util_s, vol_s = metrics(0.4)
    util_2s, vol_2s = metrics(0.8)

    # First-order linear: doubling the scale ~doubles participation and volatility.
    assert util_2s / util_s == pytest.approx(2.0, rel=5e-2)
    assert vol_2s / vol_s == pytest.approx(2.0, rel=5e-2)
    # Monotone increasing.
    assert util_2s > util_s
    assert vol_2s > vol_s
