from __future__ import annotations

import hashlib
import importlib.util
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from quant_strategies.decisions import StrategyDecision
from quant_strategies.runner.config import default_repo_root
from quant_strategies.validation.errors import ValidationStrategyLoadError


DecisionStrategyCallable = Callable[[Sequence[Mapping[str, object]], Mapping[str, object]], list[StrategyDecision]]


def load_decision_strategy(path: str | Path, *, repo_root: Path | None = None) -> DecisionStrategyCallable:
    root = Path(repo_root).resolve() if repo_root is not None else default_repo_root()
    strategy_path = Path(path).resolve()
    try:
        strategy_path.relative_to(root)
    except ValueError as exc:
        raise ValidationStrategyLoadError(f"strategy_path must resolve inside repository: {root}") from exc
    if not strategy_path.exists():
        raise ValidationStrategyLoadError(f"strategy file does not exist: {strategy_path}")
    if strategy_path.suffix != ".py":
        raise ValidationStrategyLoadError(f"strategy file must be a Python file: {strategy_path}")

    module_name = f"_quant_validation_strategy_{hashlib.sha1(str(strategy_path).encode()).hexdigest()}"
    spec = importlib.util.spec_from_file_location(module_name, strategy_path)
    if spec is None or spec.loader is None:
        raise ValidationStrategyLoadError(f"could not import strategy file: {strategy_path}")

    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise ValidationStrategyLoadError(f"strategy import failed: {exc}") from exc

    generate_decisions = getattr(module, "generate_decisions", None)
    if not callable(generate_decisions):
        raise ValidationStrategyLoadError(
            "validation strategy file must define callable generate_decisions(rows, params)"
        )
    return generate_decisions
