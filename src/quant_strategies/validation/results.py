from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from quant_strategies.validation.policy import ValidationPolicyDecision


@dataclass(frozen=True)
class ValidationRunResult:
    result_dir: Path | None
    decision: ValidationPolicyDecision
    message: str
    run_completed: bool = True
    failure_stage: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.run_completed and self.failure_stage is None
