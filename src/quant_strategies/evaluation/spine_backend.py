"""The single evaluation backend: the one causal netted portfolio book (design D9).

Per ``(window, scenario)`` this runs ``walk_portfolio_book`` once over the fold's rows
at the scenario's costs/fills and projects the resulting NAV path + round-trip ledger
into the preserved ``PortfolioEvaluationResult`` observable contract. There is no
data-kind routing to a divergent money model: the same book prices every asset class,
modeling crypto-perp funding inside the walk and leaving funding inert otherwise. A
typed fail-closed feasibility breach (intended gross/net over budget, or unfinanced
leverage on an unmodeled-financing asset class) is surfaced as a ``failed`` scenario
with the verdict reason, never clamped.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from quant_strategies.core.config import CapacityModelConfig, DataConfig, LeverageBudgetConfig
from quant_strategies.core.portfolio_foundation import (
    REASON_CAPACITY_UNSUPPORTED_VOLUME_SEMANTICS,
    BookWalkResult,
    FeasibilityError,
    FeasibilityVerdict,
    PortfolioFoundationConfig,
    at_risk_period_returns,
    compute_return_statistics,
    cost_model_per_side_fraction,
    scenario_feasibility,
    walk_portfolio_book,
)
from quant_strategies.decisions import TargetDecision
from quant_strategies.evaluation._spine_metrics import spine_metric_payload, spine_trace_tables
from quant_strategies.evaluation.config import EvaluationMetricsConfig
from quant_strategies.evaluation.dependencies import (
    EvaluationDependencyError,
    require_pandas_dependency,
)
from quant_strategies.evaluation.metrics import SHARED_ACCOUNTING_MODEL
from quant_strategies.evaluation.results import (
    PortfolioEvaluationResult,
    PreparedPortfolioInputs,
)
from quant_strategies.evaluation.scenarios import EvaluationScenario

# The book walk only reads ``data.kind`` (the modeled-financing check); window
# start/end are scoring-scenario concerns owned by ``build_portfolio_foundation`` and
# are not used by a single fold walk, so a placeholder date keeps the typed config
# valid without coupling the evaluation fold to a scoring window.
_PLACEHOLDER_DATE = date(2000, 1, 1)
_BARS_DATASET = "evaluation_book"
# Shared immutable default operator budget (frozen model -> safe as an arg default).
_DEFAULT_LEVERAGE_BUDGET = LeverageBudgetConfig()


class SpineEvaluationBackend:
    name = SHARED_ACCOUNTING_MODEL

    def prepare_inputs(
        self,
        *,
        decisions: Sequence[TargetDecision],
        rows: Sequence[Mapping[str, Any]],
        capacity_model: CapacityModelConfig,
        data_kind: str = "bars",
        leverage_budget: LeverageBudgetConfig = _DEFAULT_LEVERAGE_BUDGET,
    ) -> PreparedPortfolioInputs:
        return PreparedPortfolioInputs(
            decisions=tuple(decisions),
            rows=tuple(dict(row) for row in rows),
            data_kind=data_kind,
            capacity_model=capacity_model,
            leverage_budget=leverage_budget,
        )

    def run(
        self,
        *,
        decisions: Sequence[TargetDecision],
        rows: Sequence[Mapping[str, Any]],
        scenario: EvaluationScenario,
        metrics: EvaluationMetricsConfig,
        capacity_model: CapacityModelConfig,
        data_kind: str = "bars",
        leverage_budget: LeverageBudgetConfig = _DEFAULT_LEVERAGE_BUDGET,
    ) -> PortfolioEvaluationResult:
        prepared = self.prepare_inputs(
            decisions=decisions,
            rows=rows,
            data_kind=data_kind,
            capacity_model=capacity_model,
            leverage_budget=leverage_budget,
        )
        return self.run_prepared(prepared=prepared, scenario=scenario, metrics=metrics)

    def run_prepared(
        self,
        *,
        prepared: PreparedPortfolioInputs,
        scenario: EvaluationScenario,
        metrics: EvaluationMetricsConfig,
    ) -> PortfolioEvaluationResult:
        try:
            pd = require_pandas_dependency()
        except EvaluationDependencyError as exc:
            return PortfolioEvaluationResult(
                scenario_id=scenario.scenario_id,
                backend=self.name,
                status="unavailable",
                warnings=(str(exc),),
                required=scenario.required,
                scoreability_bearing=scenario.scoreability_bearing,
            )
        try:
            walk = _walk_for_scenario(prepared, scenario)
        except FeasibilityError as exc:
            verdict = exc.verdict
            unsupported = (
                (verdict.reason,)
                if verdict.reason == REASON_CAPACITY_UNSUPPORTED_VOLUME_SEMANTICS
                else ()
            )
            return PortfolioEvaluationResult(
                scenario_id=scenario.scenario_id,
                backend=self.name,
                status="unsupported" if unsupported else "failed",
                unsupported_semantics=unsupported,
                warnings=() if unsupported else (_feasibility_warning(verdict),),
                required=scenario.required,
                scoreability_bearing=scenario.scoreability_bearing,
                feasibility=verdict,
            )
        except ValueError as exc:
            return PortfolioEvaluationResult(
                scenario_id=scenario.scenario_id,
                backend=self.name,
                status="failed",
                warnings=(str(exc),),
                required=scenario.required,
                scoreability_bearing=scenario.scoreability_bearing,
            )
        try:
            feasibility = _scenario_scoreability(walk, scenario, metrics)
            payload = spine_metric_payload(
                walk,
                annualization_periods_per_year=metrics.annualization_periods_per_year,
                min_annualized_samples=metrics.min_annualized_samples,
            )
            tables = spine_trace_tables(pd, walk, scenario.scenario_id)
        except ValueError as exc:
            return PortfolioEvaluationResult(
                scenario_id=scenario.scenario_id,
                backend=self.name,
                status="failed",
                warnings=(str(exc),),
                required=scenario.required,
                scoreability_bearing=scenario.scoreability_bearing,
            )
        return PortfolioEvaluationResult(
            scenario_id=scenario.scenario_id,
            backend=self.name,
            status="completed",
            metrics=payload.metrics,
            warnings=payload.warnings,
            required=scenario.required,
            scoreability_bearing=scenario.scoreability_bearing,
            feasibility=feasibility,
            tables=tables,
        )


def _walk_for_scenario(
    prepared: PreparedPortfolioInputs,
    scenario: EvaluationScenario,
) -> BookWalkResult:
    return walk_portfolio_book(
        rows=prepared.rows,
        decisions=prepared.decisions,
        data=_data_config(prepared.data_kind, prepared.rows),
        fill_model=scenario.fill_model,
        cost_model=scenario.cost_model,
        capacity_model=prepared.capacity_model,
        config=PortfolioFoundationConfig(
            max_gross_exposure=prepared.leverage_budget.max_gross_exposure,
            max_net_exposure=prepared.leverage_budget.max_net_exposure,
        ),
    )


def _data_config(data_kind: str, rows: Sequence[Mapping[str, Any]]) -> DataConfig:
    symbols = tuple(
        dict.fromkeys(
            str(row["symbol"]).strip()
            for row in rows
            if isinstance(row.get("symbol"), str) and str(row["symbol"]).strip()
        )
    ) or ("__book__",)
    return DataConfig(
        kind=data_kind,
        dataset=_BARS_DATASET if data_kind == "bars" else None,
        symbols=symbols,
        start=_PLACEHOLDER_DATE,
        end=_PLACEHOLDER_DATE,
    )


def _scenario_scoreability(
    walk: BookWalkResult,
    scenario: EvaluationScenario,
    metrics: EvaluationMetricsConfig,
) -> FeasibilityVerdict:
    statistics = compute_return_statistics(
        at_risk_period_returns(walk.path),
        trial_count=None,
        benchmark_sharpe=0.0,
        min_return_sample=metrics.min_annualized_samples,
    )
    return scenario_feasibility(
        walk.feasibility,
        statistics,
        per_side_cost_fraction=cost_model_per_side_fraction(scenario.cost_model),
        min_return_sample=metrics.min_annualized_samples,
    )


def _feasibility_warning(verdict: Any) -> str:
    parts = [f"feasibility_breach:{verdict.reason}"]
    if verdict.detail:
        parts.append(str(verdict.detail))
    return ": ".join(parts)
