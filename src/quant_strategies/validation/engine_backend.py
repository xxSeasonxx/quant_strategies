from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from quant_strategies.decisions import StrategyDecision
from quant_strategies.engine import screen
from quant_strategies.engine.evaluation import EvaluationError
from quant_strategies.runner.engine_runner import build_request
from quant_strategies.runner.errors import EvaluationRunError, RequestBuildError
from quant_strategies.validation.backends import BackendRunResult
from quant_strategies.validation.config import ScenarioRunConfig


class EngineBackend:
    """The engine smoke kernel as the single verdict PnL source.

    Runs the same `screen()` path the runner quick-run audits, so the number the
    verdict is computed from *is* the number a human audits. `net_return` is the
    engine's funding-inclusive signed-trade-activity sum — a linear per-trade
    aggregate, not a NAV path (see `evidence_semantics`). VectorBT Pro is no
    longer a co-equal verdict source; it is an opt-in agreement oracle.
    """

    name = "engine"

    def run(
        self,
        *,
        decisions: list[StrategyDecision],
        rows: Sequence[Mapping[str, Any]],
        config: ScenarioRunConfig,
    ) -> BackendRunResult:
        try:
            request = build_request(
                strategy_id=config.scenario_id,
                rows=rows,
                decisions=list(decisions),
                fill_model=config.fill_model,
                cost_model=config.cost_model,
            )
            result = screen(request)
        except (RequestBuildError, EvaluationRunError, EvaluationError) as exc:
            return BackendRunResult(
                backend=self.name,
                status="failed",
                metrics={},
                warnings=(str(exc),),
            )

        smoke = result.smoke_score
        metrics = {
            # funding-inclusive net == the audited smoke net; this is the gated number.
            "net_return": smoke.sum_signed_trade_activity_net,
            "trade_count": result.trade_count,
            # gross price path: the agreement oracle cross-checks this against vbt.
            "gross_return": smoke.sum_signed_trade_activity_gross,
            "funding_return": smoke.sum_signed_trade_activity_funding,
            "cost_return": smoke.sum_signed_trade_activity_cost,
        }
        return BackendRunResult(
            backend=self.name,
            status="completed",
            metrics=metrics,
            # The trades that produced the scalar metrics; emitted as a per-scenario
            # ledger so the gated net_return is recomputable from artifacts.
            trades=tuple(result.trades),
        )
