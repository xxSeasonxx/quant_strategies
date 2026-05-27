from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict

from quant_strategies.decisions import StrategyDecision
from quant_strategies.validation.config import ScenarioRunConfig


BackendStatus = Literal["completed", "failed", "unsupported", "unavailable"]
DecisionGenerationStatus = Literal["base_reused", "regenerated", "failed"]


class BackendRunResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    backend: str
    status: BackendStatus
    metrics: dict[str, float | int | str | bool | None]
    warnings: tuple[str, ...] = ()
    unsupported_semantics: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScenarioBackendRunResult:
    window_id: str
    scenario_id: str
    required: bool
    result: BackendRunResult
    scenario_kind: str = "unknown"
    decisions_regenerated: bool = False
    diagnostic_only: bool = False
    decision_generation_status: DecisionGenerationStatus = "base_reused"
    decision_count: int = 0
    decision_records_path: str | None = None
    decision_records_sha256: str | None = None


class ValidationBackend(Protocol):
    name: str

    def run(
        self,
        *,
        decisions: list[StrategyDecision],
        rows: Sequence[Mapping[str, Any]],
        config: ScenarioRunConfig,
    ) -> BackendRunResult:
        raise NotImplementedError


class FakeBackend:
    name = "fake"

    def __init__(self, result: BackendRunResult | None = None) -> None:
        self._result = result or BackendRunResult(
            backend=self.name,
            status="completed",
            metrics={"net_return": 0.0, "trade_count": 0},
            warnings=(),
            unsupported_semantics=(),
        )

    def run(
        self,
        *,
        decisions: list[StrategyDecision],
        rows: Sequence[Mapping[str, Any]],
        config: ScenarioRunConfig,
    ) -> BackendRunResult:
        return self._result


def get_backend(name: str) -> ValidationBackend:
    if name == "fake":
        return FakeBackend()
    if name == "vectorbtpro":
        from quant_strategies.validation.vectorbtpro_backend import VectorBTProBackend

        return VectorBTProBackend()
    raise ValueError(f"unsupported validation backend: {name}")
