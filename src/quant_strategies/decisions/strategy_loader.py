from __future__ import annotations

import hashlib
import importlib.util
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol

from quant_strategies.decisions.models import StrategyDecision
from quant_strategies.decisions.purity import strategy_purity_violations


class StrategyGenerator(Protocol):
    def __call__(
        self,
        rows: Sequence[Mapping[str, object]],
        params: Mapping[str, object],
    ) -> Sequence[StrategyDecision]:
        ...


DecisionStrategyCallable = StrategyGenerator


class DecisionStrategyLoadError(Exception):
    """Raised when a strategy module cannot provide generate_decisions."""


def _default_repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def load_decision_strategy(
    path: str | Path,
    *,
    repo_root: Path | None = None,
    enforce_purity: bool = True,
) -> DecisionStrategyCallable:
    root = Path(repo_root).resolve() if repo_root is not None else _default_repo_root()
    strategy_path = Path(path).resolve()
    try:
        strategy_path.relative_to(root)
    except ValueError as exc:
        raise DecisionStrategyLoadError(
            f"strategy_path must resolve inside repository: {root}"
        ) from exc
    if not strategy_path.exists():
        raise DecisionStrategyLoadError(f"strategy file does not exist: {strategy_path}")
    if not strategy_path.is_file():
        raise DecisionStrategyLoadError(f"strategy path must be a file: {strategy_path}")
    if strategy_path.suffix != ".py":
        raise DecisionStrategyLoadError(f"strategy file must be a Python file: {strategy_path}")
    if enforce_purity:
        violations = strategy_purity_violations(strategy_path)
        if violations:
            raise DecisionStrategyLoadError(
                f"strategy purity violations: {'; '.join(violations)}"
            )

    module_name = f"_quant_decision_strategy_{hashlib.sha1(str(strategy_path).encode()).hexdigest()}"
    spec = importlib.util.spec_from_file_location(module_name, strategy_path)
    if spec is None or spec.loader is None:
        raise DecisionStrategyLoadError(f"could not import strategy file: {strategy_path}")

    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except SystemExit as exc:
        raise DecisionStrategyLoadError(f"strategy import exited: {exc}") from exc
    except Exception as exc:
        raise DecisionStrategyLoadError(f"strategy import failed: {exc}") from exc

    generate_decisions = getattr(module, "generate_decisions", None)
    if not callable(generate_decisions):
        raise DecisionStrategyLoadError(
            "strategy file must define callable generate_decisions(rows, params)"
        )
    validate_params = getattr(module, "validate_params", None)
    if validate_params is not None:
        if not callable(validate_params):
            raise DecisionStrategyLoadError(
                "strategy validate_params must be callable when defined"
            )
        setattr(generate_decisions, "validate_params", validate_params)
    return generate_decisions
