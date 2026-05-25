from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from quant_strategies.decisions import StrategyDecision


class BackendRunResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    backend: str
    status: str
    metrics: dict[str, float | int | str | bool | None]
    warnings: tuple[str, ...] = ()
    unsupported_semantics: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScenarioBackendRunResult:
    window_id: str
    scenario_id: str
    required: bool
    result: BackendRunResult


class ValidationBackend(Protocol):
    name: str

    def run(
        self,
        *,
        decisions: list[StrategyDecision],
        rows: list[dict[str, Any]],
        config: Any,
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
        rows: list[dict[str, Any]],
        config: Any,
    ) -> BackendRunResult:
        return self._result


def get_backend(name: str) -> ValidationBackend:
    if name == "fake":
        return FakeBackend()
    if name == "vectorbtpro":
        from quant_strategies.validation.vectorbtpro_backend import VectorBTProBackend

        return VectorBTProBackend()
    raise ValueError(f"unsupported validation backend: {name}")
