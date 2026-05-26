from __future__ import annotations

from pathlib import Path

from quant_strategies.decisions import (
    DecisionStrategyCallable,
    DecisionStrategyLoadError,
    load_decision_strategy,
)
from quant_strategies.runner.errors import StrategyLoadError


StrategyCallable = DecisionStrategyCallable


def load_strategy(path: str | Path, *, repo_root: Path | None = None) -> StrategyCallable:
    try:
        return load_decision_strategy(path, repo_root=repo_root)
    except DecisionStrategyLoadError as exc:
        raise StrategyLoadError(str(exc)) from exc
