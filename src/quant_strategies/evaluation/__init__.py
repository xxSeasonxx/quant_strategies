from __future__ import annotations

from quant_strategies.evaluation._pipeline import run_evaluation
from quant_strategies.evaluation.backends import EvaluationBackend
from quant_strategies.evaluation.config import BenchmarkConfig, EvaluationConfig, EvaluationScenarioConfig
from quant_strategies.evaluation.results import EvaluationRunResult

__all__ = [
    "BenchmarkConfig",
    "EvaluationBackend",
    "EvaluationConfig",
    "EvaluationRunResult",
    "EvaluationScenarioConfig",
    "run_evaluation",
]
