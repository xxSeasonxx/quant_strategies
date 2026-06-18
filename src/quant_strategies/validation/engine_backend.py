from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from quant_strategies.core.portfolio_foundation import (
    INITIAL_EQUITY,
    BookWalkResult,
    FeasibilityError,
    FeasibilityVerdict,
    PortfolioFoundationConfig,
    build_portfolio_foundation,
)
from quant_strategies.decisions import TargetDecision
from quant_strategies.validation.backends import BackendRunResult
from quant_strategies.validation.config import ScenarioRunConfig


class SpineBackend:
    """The one causal, single-account, netted portfolio book as the verdict source.

    Validation scores exactly the object the quick-run path scores: the spine's
    single causal walk (`core.portfolio_foundation`). For a validation scenario the
    book is walked at that scenario's frozen costs/fills; the realistic-cost walk's
    **marked NAV path** is the gated evidence. ``net_return`` is the marked fold
    return ``(final_nav - INITIAL_EQUITY) / INITIAL_EQUITY`` of that one scored object,
    so a fold ending with an open position is scored at its true marked return rather
    than a realized-only zero. ``gross``/``funding``/``cost`` are the realized
    round-trip cash attribution, reconciling with ``net_return`` exactly when the book
    ends flat (design D4/D9) — one model of money, never an independent summation.

    A fail-closed **leverage** breach (intended gross/net over the budget, or
    unfinanced leverage for an unmodelled asset class) raises mid-walk and surfaces
    as ``status="unsupported"`` carrying the typed reason — never a clamped score.
    The spine's non-raising scoring guards (``zero_cost`` on the no-cost reference
    scenario, ``insufficient_samples`` on thin evidence) keep the netted-book walk
    and ledger reportable, but their typed verdict is carried on the result so
    validation can fail scoreability-bearing scenarios without parsing warnings.
    """

    name = "engine"

    def run(
        self,
        *,
        decisions: list[TargetDecision],
        rows: Sequence[Mapping[str, Any]],
        config: ScenarioRunConfig,
    ) -> BackendRunResult:
        try:
            foundation = build_portfolio_foundation(
                rows=rows,
                decisions=list(decisions),
                data=config.data,
                fill_model=config.fill_model,
                cost_model=config.cost_model,
                capacity_model=config.capacity_model,
                config=PortfolioFoundationConfig(
                    risk_budget=config.risk_budget,
                    subwindows=1,
                    max_gross_exposure=config.leverage_budget.max_gross_exposure,
                    max_net_exposure=config.leverage_budget.max_net_exposure,
                ),
            )
        except FeasibilityError as exc:
            # Fail-closed leverage / unfinanced-leverage breach: a typed infeasibility.
            return _infeasible_result(self.name, exc.verdict)
        except ValueError as exc:
            return BackendRunResult(
                backend=self.name,
                status="failed",
                metrics={},
                warnings=(str(exc),),
            )

        return BackendRunResult(
            backend=self.name,
            status="completed",
            metrics=_ledger_metrics(foundation.ledger),
            round_trips=foundation.ledger.round_trips,
            feasibility=foundation.feasible_verdict(),
            sizing_report=foundation.sizing_report,
        )


def _ledger_metrics(walk: BookWalkResult) -> dict[str, float | int]:
    """Scalar backend metrics from the single walk's authoritative NAV path.

    ``net_return`` is the **marked** fold return of the one scored object — the book's
    NAV path: ``(final_nav - INITIAL_EQUITY) / INITIAL_EQUITY``. It is gated, not the
    realized round-trip sum, so a fold that ends with an open position (a winner held
    across the window boundary) is scored at its true marked return rather than the
    realized-only 0% it would show with no closed round-trip (design D4/D9).

    ``gross``/``funding``/``cost`` remain the realized round-trip cash attribution
    view. They reconcile with ``net_return`` (``net == gross + funding - cost``) only
    when the book ends flat; on a non-flat fold the open leg's unrealized PnL and
    accrued funding are in NAV but in no closed round-trip, so the attribution split
    sums to less than the marked ``net_return`` by exactly that open exposure.
    """
    gross = sum(trip.gross_cash for trip in walk.round_trips) / INITIAL_EQUITY
    funding = sum(trip.funding_cash for trip in walk.round_trips) / INITIAL_EQUITY
    cost = sum(trip.cost_cash for trip in walk.round_trips) / INITIAL_EQUITY
    impact = sum(trip.impact_cost_cash for trip in walk.round_trips) / INITIAL_EQUITY
    net = (walk.final_nav - INITIAL_EQUITY) / INITIAL_EQUITY
    return {
        "net_return": net,
        "trade_count": len(walk.round_trips),
        "gross_return": gross,
        "funding_return": funding,
        "cost_return": cost,
        "impact_return": impact,
    }


def _infeasible_result(backend: str, verdict: FeasibilityVerdict) -> BackendRunResult:
    detail = verdict.detail or verdict.reason or "infeasible"
    reason = verdict.reason or "infeasible"
    return BackendRunResult(
        backend=backend,
        status="unsupported",
        metrics={},
        warnings=(f"feasibility:{detail}",),
        unsupported_semantics=(reason,),
        feasibility=verdict,
    )
