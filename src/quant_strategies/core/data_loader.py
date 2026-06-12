from __future__ import annotations

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


def load_data(
    config: StrategyExecutionSpec,
    *,
    engine: object | None = None,
) -> LoadedData:
    db_engine = engine if engine is not None else _default_engine()
    try:
        rows = _load_rows(config, db_engine)
    except DataLoadError:
        raise
    except Exception as exc:
        raise DataLoadError(f"data load failed: {exc}") from exc
    if not rows:
        raise DataLoadError("data load returned no rows")
    normalized_rows = NormalizedRows.from_rows(config, rows)
    return LoadedData(rows=normalized_rows.projection_rows(), normalized_rows=normalized_rows)


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
