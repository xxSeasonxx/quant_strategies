from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol, runtime_checkable

from quant_strategies.decisions import StrategyDecision
from quant_strategies.evaluation.config import EvaluationMetricsConfig
from quant_strategies.evaluation.results import (
    PortfolioEvaluationResult,
    PreparedPortfolioInputs,
)
from quant_strategies.evaluation.scenarios import EvaluationScenario


@runtime_checkable
class EvaluationBackend(Protocol):
    """Backend contract required by the evaluation runner."""

    name: str

    def run(
        self,
        *,
        decisions: Sequence[StrategyDecision],
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
        decisions: Sequence[StrategyDecision],
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


@runtime_checkable
class DataKindNamedEvaluationBackend(Protocol):
    """Optional naming hook for data-kind-specific backend labels."""

    def name_for_data_kind(self, data_kind: str) -> str: ...
