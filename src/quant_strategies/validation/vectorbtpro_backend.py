from __future__ import annotations

from typing import Any

from quant_strategies.decisions import StrategyDecision
from quant_strategies.validation.backends import BackendRunResult


class VectorBTProBackend:
    name = "vectorbtpro"

    def run(
        self,
        *,
        decisions: list[StrategyDecision],
        rows: list[dict[str, Any]],
        config: Any,
    ) -> BackendRunResult:
        return BackendRunResult(
            backend=self.name,
            status="unavailable",
            metrics={},
            warnings=("vectorbtpro backend is not implemented yet",),
            unsupported_semantics=(),
        )
