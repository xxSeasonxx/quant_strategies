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
    NAV-path round-trip ledger is the gated evidence. ``net_return`` is the sum of
    the netted-book round-trip realized PnL as a fraction of the standing NAV base,
    and ``gross``/``funding``/``cost`` are its cash split, so
    ``net == gross + funding - cost`` and the artifacted ledger reconciles with the
    NAV path's realized PnL (design D4/D9) — one model of money, never an
    independent summation.

    A fail-closed **leverage** breach (intended gross/net over the budget, or
    unfinanced leverage for an unmodelled asset class) raises mid-walk and surfaces
    as ``status="unsupported"`` carrying the typed reason — never a clamped score.
    The spine's non-raising scoring guards (``zero_cost`` on the no-cost reference
    scenario, ``insufficient_samples`` on thin evidence) are NOT mechanical
    infeasibilities: the netted-book walk and its ledger are valid, so the metrics
    are reported ``completed`` and validation's mechanical gates (min trades,
    positive activity, stressed/fill-lag floors) judge the evidence.
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
                config=PortfolioFoundationConfig(subwindows=1),
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
        )


# The verdict source was the per-trade ``screen()`` kernel before the netted-book
# spine retired it; the public backend name stays ``engine`` (the single verdict
# source) so configs and artifacts are unchanged.
EngineBackend = SpineBackend


def _ledger_metrics(ledger: BookWalkResult) -> dict[str, float | int]:
    """Scalar backend metrics derived from the single walk's round-trip ledger.

    The cash attribution of the netted-book round-trips, expressed as NAV fractions,
    reconciles by construction: ``net == gross + funding - cost``.
    """
    gross = sum(trip.gross_cash for trip in ledger.round_trips) / INITIAL_EQUITY
    funding = sum(trip.funding_cash for trip in ledger.round_trips) / INITIAL_EQUITY
    cost = sum(trip.cost_cash for trip in ledger.round_trips) / INITIAL_EQUITY
    net = sum(trip.realized_pnl for trip in ledger.round_trips) / INITIAL_EQUITY
    return {
        "net_return": net,
        "trade_count": len(ledger.round_trips),
        "gross_return": gross,
        "funding_return": funding,
        "cost_return": cost,
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
    )
