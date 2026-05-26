from __future__ import annotations

from pathlib import Path

from quant_strategies.decisions import (
    DecisionStrategyCallable,
    DecisionStrategyLoadError,
    load_decision_strategy as _load_decision_strategy,
)
from quant_strategies.validation.errors import ValidationStrategyLoadError


def load_decision_strategy(
    path: str | Path,
    *,
    repo_root: Path | None = None,
) -> DecisionStrategyCallable:
    try:
        return _load_decision_strategy(path, repo_root=repo_root)
    except DecisionStrategyLoadError as exc:
        raise ValidationStrategyLoadError(str(exc)) from exc
