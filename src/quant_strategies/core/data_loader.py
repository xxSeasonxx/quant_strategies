from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from quant_strategies.core.config import StrategyExecutionSpec
from quant_strategies.core.errors import DataLoadError
from quant_strategies.data_contract import NormalizedRows

_UNSET = object()


get_engine: Any | None = None
_default_engine_factory: Any | None = None
_default_engine_value: object = _UNSET


@dataclass(frozen=True)
class LoadedData:
    rows: Sequence[Mapping[str, Any]]
    normalized_rows: NormalizedRows | None = None
    # Valuation-only mark frame: observed bars plus upstream policy-bounded
    # ``previous_close_mark`` repairs (``is_repaired=True``). Empty when the signal
    # dataset has no regular-series repair policy. Never feeds signals/fills/funding.
    mark_rows: Sequence[Mapping[str, Any]] = ()
    mark_repair: Mapping[str, Any] | None = None


def load_strategy_bars(*args: Any, **kwargs: Any) -> Any:
    from quant_data.contract_loaders import load_strategy_bars as upstream

    return upstream(*args, **kwargs)


def load_strategy_universe_bars(*args: Any, **kwargs: Any) -> Any:
    from quant_data.contract_loaders import load_strategy_universe_bars as upstream

    return upstream(*args, **kwargs)


def load_crypto_perp_bars_with_funding(*args: Any, **kwargs: Any) -> Any:
    from quant_data.loader import load_crypto_perp_bars_with_funding as upstream

    return upstream(*args, **kwargs)


def load_fx_bars_with_quotes(*args: Any, **kwargs: Any) -> Any:
    from quant_data.loader import load_fx_bars_with_quotes as upstream

    return upstream(*args, **kwargs)


def load_strategy_universe_mark_frame(*args: Any, **kwargs: Any) -> Any:
    from quant_data.contract_loaders import load_strategy_universe_mark_frame as upstream

    return upstream(*args, **kwargs)


def data_load_identity(config: StrategyExecutionSpec) -> dict[str, Any]:
    """The exact config inputs that determine ``LoadedData`` and its normalized rows.

    This is the single source of truth for data identity: every field the loader
    (`load_data`/`_load_rows`/`_load_mark_rows`) or normalizer
    (`NormalizedRows.from_rows`, via required-field rules) reads. ``symbols`` order is
    preserved because it drives multi-symbol row order and therefore the normalized
    hash. Keep this aligned with the loader whenever either changes.
    """
    data = config.data
    return {
        "kind": data.kind,
        "dataset": data.dataset,
        "symbols": list(data.symbols),
        "start": data.start.isoformat(),
        "end": data.end.isoformat(),
        "load_start": data.load_start.isoformat() if data.load_start is not None else None,
        "load_end": data.load_end.isoformat() if data.load_end is not None else None,
        "fill_price": config.fill_model.price,
        "capacity_mode": config.capacity_model.mode,
    }


def data_load_fingerprint(config: StrategyExecutionSpec) -> str:
    """Stable digest of :func:`data_load_identity` for fail-closed preloaded reuse."""
    canonical = json.dumps(data_load_identity(config), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def load_data(
    config: StrategyExecutionSpec,
    *,
    engine: object | None = None,
) -> LoadedData:
    db_engine = engine if engine is not None else _default_engine()
    try:
        rows = _load_rows(config, db_engine)
        # Load the valuation mark frame over the same window. An unrepairable gap
        # raises here and surfaces as a fail-closed data-load failure, before any walk.
        mark_rows, mark_repair = _load_mark_rows(config, db_engine)
    except DataLoadError:
        raise
    except Exception as exc:
        raise DataLoadError(f"data load failed: {exc}") from exc
    if not rows:
        raise DataLoadError("data load returned no rows")
    normalized_rows = NormalizedRows.from_rows(config, rows)
    return LoadedData(
        rows=normalized_rows.projection_rows(),
        normalized_rows=normalized_rows,
        mark_rows=mark_rows,
        mark_repair=mark_repair,
    )


def _load_rows(config: StrategyExecutionSpec, engine: object) -> list[dict[str, Any]]:
    data = config.data
    load_start = data.effective_load_start
    load_end = data.effective_load_end
    if data.kind == "bars":
        if data.dataset is None:
            raise DataLoadError("data.dataset is required for bars")
        if len(data.symbols) == 1:
            frame = load_strategy_bars(
                engine,
                data.symbols[0],
                data.dataset,
                load_start,
                load_end,
                strict=True,
            )
            return _rows_from_frame(frame)
        frame = load_strategy_universe_bars(
            engine,
            list(data.symbols),
            data.dataset,
            load_start,
            load_end,
            strict=True,
        )
        return _rows_from_frame(frame)

    if data.kind == "crypto_perp_funding":
        rows: list[dict[str, Any]] = []
        for symbol in data.symbols:
            frame = load_crypto_perp_bars_with_funding(
                engine,
                symbol,
                load_start,
                load_end,
                strict=True,
            )
            rows.extend(_rows_from_frame(frame))
        return rows

    if data.kind == "forex_with_quotes":
        rows = []
        require_quotes = config.fill_model.price == "quote"
        for symbol in data.symbols:
            frame = load_fx_bars_with_quotes(
                engine,
                symbol,
                load_start,
                load_end,
                strict=True,
                require_quotes=require_quotes,
            )
            rows.extend(_rows_from_frame(frame))
        return rows

    raise DataLoadError(f"unsupported data kind: {data.kind}")


def _mark_dataset(config: StrategyExecutionSpec) -> str | None:
    """Resolve the repair-aware mark dataset for a run, or ``None`` when none applies.

    The mark dataset is the base OHLCV dataset underlying the signal frame: the strict
    mark loader validates the window via a freshness lookup that only supports base
    datasets, not derived joins. Base bars are a superset of the derived signal grid (the
    join adds columns, not bar timestamps), so the mark grid covers the signal grid.
    Kinds/datasets without a repair policy have no mark frame; a within-window gap there
    stays a hard failure.
    """
    data = config.data
    if data.kind == "crypto_perp_funding":
        candidate: str | None = "crypto_perp_1min"
    elif data.kind == "bars":
        candidate = data.dataset
    else:
        candidate = None
    if candidate is None:
        return None
    from quant_data.dataset_policy import datasets_with_regular_series_repair

    return candidate if candidate in datasets_with_regular_series_repair() else None


def _load_mark_rows(
    config: StrategyExecutionSpec, engine: object
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    dataset = _mark_dataset(config)
    if dataset is None:
        return [], None
    data = config.data
    frame, summary = load_strategy_universe_mark_frame(
        engine,
        list(data.symbols),
        dataset,
        data.effective_load_start,
        data.effective_load_end,
        strict=True,
        return_summary=True,
    )
    mark_repair = {
        "dataset": summary.dataset,
        "repaired_row_count": summary.repaired_row_count,
        "affected_symbols": list(summary.affected_symbols),
        "classification_counts": dict(summary.classification_counts),
    }
    return _rows_from_frame(frame), mark_repair


def _rows_from_frame(frame: object) -> list[dict[str, Any]]:
    if frame is None:
        return []
    if isinstance(frame, list):
        return [dict(row) for row in frame]
    if isinstance(frame, tuple):
        return [dict(row) for row in frame]
    is_empty = getattr(frame, "is_empty", None)
    if callable(is_empty) and is_empty():
        return []
    if hasattr(frame, "to_dicts"):
        return [dict(row) for row in frame.to_dicts()]
    if hasattr(frame, "to_dict"):
        records = frame.to_dict("records")
        return [dict(row) for row in records]
    raise DataLoadError(f"unsupported data frame type: {type(frame).__name__}")


def _default_engine() -> object:
    global _default_engine_factory, _default_engine_value
    factory = _get_engine()
    if _default_engine_value is _UNSET or _default_engine_factory is not factory:
        _default_engine_value = factory()
        _default_engine_factory = factory
    return _default_engine_value


def _get_engine() -> Any:
    global get_engine
    if get_engine is None:
        from quant_data.db import get_engine as quant_data_get_engine

        get_engine = quant_data_get_engine
    return get_engine
