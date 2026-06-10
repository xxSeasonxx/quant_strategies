from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol, runtime_checkable

from quant_strategies.decisions import TargetDecision
from quant_strategies.evaluation.config import EvaluationMetricsConfig
from quant_strategies.evaluation.results import (
    PortfolioEvaluationResult,
    PreparedPortfolioInputs,
)
from quant_strategies.evaluation.scenarios import EvaluationScenario


@runtime_checkable
class EvaluationBackend(Protocol):
    """Backend contract required by the evaluation runner.

    There is exactly one production implementation — the single causal netted
    portfolio book (``SpineEvaluationBackend``); the abstraction exists only so the
    runner stays decoupled and tests can inject a fake. No backend routes by data
    kind to a divergent money model (design D9)."""

    name: str

    def run(
        self,
        *,
        decisions: Sequence[TargetDecision],
        rows: Sequence[Mapping[str, Any]],
        scenario: EvaluationScenario,
        metrics: EvaluationMetricsConfig,
        data_kind: str = "bars",
    ) -> PortfolioEvaluationResult: ...


@runtime_checkable
class PreparedEvaluationBackend(EvaluationBackend, Protocol):
    """Optional prepare-once backend contract used for scenario fanout."""

    def prepare_inputs(
        self,
        *,
        decisions: Sequence[TargetDecision],
        rows: Sequence[Mapping[str, Any]],
        data_kind: str = "bars",
    ) -> PreparedPortfolioInputs: ...

    def run_prepared(
        self,
        *,
        prepared: PreparedPortfolioInputs,
        scenario: EvaluationScenario,
        metrics: EvaluationMetricsConfig,
    ) -> PortfolioEvaluationResult: ...
