from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from quant_strategies.core.data_loader import LoadedData, data_load_fingerprint, load_data
from quant_strategies.runner import config as config_module


@dataclass(frozen=True)
class PreparedRunData:
    """A reusable, fingerprinted data load for one fixed data window.

    Produce it once with :func:`prepare_run_data` and pass it to
    ``run_config(prepared=...)`` for every run over the same window; ``run_config``
    fail-closed-verifies ``fingerprint`` against the live config's data identity before
    reuse. Treat it as opaque — the caller owns its lifetime (the engine holds no
    cache).
    """

    loaded_data: LoadedData
    fingerprint: str


def prepare_run_data(
    config_path: str | Path,
    *,
    repo_root: Path | None = None,
    engine: object | None = None,
) -> PreparedRunData:
    """Load + normalize one window once for reuse across many ``run_config`` calls.

    Symmetric with :func:`run_config`'s path-based entry: it resolves the config, loads
    the panel (signal rows plus the valuation mark frame) a single time, and pairs the
    result with a fingerprint over the data-identity inputs so reuse is fail-closed on a
    config-identity mismatch. ``engine=None`` uses the memoized default engine.
    """
    effective_repo_root = (
        Path(repo_root).resolve() if repo_root is not None else config_module.default_repo_root()
    )
    config_file = config_module.resolve_config_path(config_path, repo_root=effective_repo_root)
    config = config_module.load_config(config_file, repo_root=effective_repo_root)
    spec = config.to_execution_spec()
    loaded = load_data(spec, engine=engine)
    return PreparedRunData(loaded_data=loaded, fingerprint=data_load_fingerprint(spec))
