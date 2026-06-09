from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


def load_candidate_strategy(candidate_id: str) -> ModuleType:
    path = Path("candidates") / candidate_id / "strategy.py"
    spec = importlib.util.spec_from_file_location(f"_candidate_{candidate_id}", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
