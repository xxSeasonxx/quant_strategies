from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from quant_strategies.data_contract import NormalizedRows, RowContractMode, json_safe_value
from quant_strategies.datetime_utils import parse_aware_datetime
from quant_strategies.core.config import StrategyExecutionSpec
from quant_strategies.runner.errors import DataLoadError

_UNSET = object()


class _LazyLoaderProxy:
    _loader_attributes = (
        "load_bars",
        "load_universe_bars",
        "load_crypto_perp_bars_with_funding",
        "load_fx_bars_with_quotes",
    )

    def __init__(self) -> None:
        object.__setattr__(self, "_overrides", set())
        for name in self._loader_attributes:
            object.__setattr__(self, name, _UNSET)

    def __setattr__(self, name: str, value: object) -> None:
        object.__setattr__(self, name, value)
        if name in self._loader_attributes:
            overrides = self._overrides
            if value is _UNSET:
                overrides.discard(name)
            else:
                overrides.add(name)

    def has_overrides(self) -> bool:
        return bool(self._overrides)


get_engine: Any | None = None
loader: Any = _LazyLoaderProxy()
_default_engine_factory: Any | None = None
_default_engine_value: object = _UNSET


@dataclass(frozen=True)
class LoadedData:
    rows: Sequence[Mapping[str, Any]]
    normalized_rows: NormalizedRows | None = None


def load_data(
    config: StrategyExecutionSpec,
    *,
    engine: object | None = None,
    row_contract_mode: RowContractMode | str = RowContractMode.SEARCH,
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
    rows.sort(key=_row_sort_key)
    normalized_rows = NormalizedRows.from_rows(config, rows, mode=row_contract_mode)
    return LoadedData(rows=normalized_rows.projection_rows(), normalized_rows=normalized_rows)


def _row_sort_key(row: Mapping[str, Any]) -> tuple[str, tuple[int, Any]]:
    raw_timestamp = row.get("timestamp")
    parsed_timestamp, _ = parse_aware_datetime(raw_timestamp)
    if parsed_timestamp is not None:
        timestamp_key = (0, parsed_timestamp)
    elif raw_timestamp is None:
        timestamp_key = (2, "")
    else:
        timestamp_key = (1, _json_sort_value(raw_timestamp))
    return (str(row.get("symbol", "")), timestamp_key)


def _json_sort_value(value: Any) -> str:
    return json.dumps(
        json_safe_value(value),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _load_rows(config: StrategyExecutionSpec, engine: object) -> list[dict[str, Any]]:
    data = config.data
    quant_data_loader = _loader()
    if data.kind == "bars":
        if data.dataset is None:
            raise DataLoadError("data.dataset is required for bars")
        if len(data.symbols) == 1:
            frame = _loader_attribute(quant_data_loader, "load_bars")(
                engine,
                data.symbols[0],
                data.dataset,
                data.start,
                data.end,
                research=True,
                strict=data.strict,
            )
            return _rows_from_frame(frame)
        universe = _loader_attribute(quant_data_loader, "load_universe_bars")(
            engine,
            list(data.symbols),
            data.dataset,
            data.start,
            data.end,
            research=True,
            strict=data.strict,
        )
        return _rows_from_universe(universe)

    if data.kind == "crypto_perp_funding":
        rows: list[dict[str, Any]] = []
        for symbol in data.symbols:
            frame = _loader_attribute(quant_data_loader, "load_crypto_perp_bars_with_funding")(
                engine,
                symbol,
                data.start,
                data.end,
                research=True,
                strict=data.strict,
            )
            rows.extend(_rows_from_frame(frame))
        return rows

    if data.kind == "forex_with_quotes":
        rows = []
        require_quotes = config.fill_model.price == "quote"
        for symbol in data.symbols:
            frame = _loader_attribute(quant_data_loader, "load_fx_bars_with_quotes")(
                engine,
                symbol,
                data.start,
                data.end,
                research=True,
                strict=data.strict,
                require_quotes=require_quotes,
            )
            rows.extend(_rows_from_frame(frame))
        return rows

    raise DataLoadError(f"unsupported data kind: {data.kind}")


def _rows_from_universe(universe: object) -> list[dict[str, Any]]:
    if not isinstance(universe, dict):
        raise DataLoadError("load_universe_bars must return a dict of frames")
    rows: list[dict[str, Any]] = []
    for frame in universe.values():
        rows.extend(_rows_from_frame(frame))
    return rows


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


def _loader() -> Any:
    global loader
    if isinstance(loader, _LazyLoaderProxy) and not loader.has_overrides():
        loader = _import_quant_data_loader()
    return loader


def _loader_attribute(quant_data_loader: Any, name: str) -> Any:
    value = getattr(quant_data_loader, name, _UNSET)
    if value is _UNSET and isinstance(quant_data_loader, _LazyLoaderProxy):
        return getattr(_import_quant_data_loader(), name)
    return value


def _import_quant_data_loader() -> Any:
    from quant_data import loader as quant_data_loader

    return quant_data_loader


def _get_engine() -> Any:
    global get_engine
    if get_engine is None:
        from quant_data.db import get_engine as quant_data_get_engine

        get_engine = quant_data_get_engine
    return get_engine
