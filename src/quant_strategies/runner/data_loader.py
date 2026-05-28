from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from quant_strategies.runner.config import RunConfig
from quant_strategies.runner.errors import DataLoadError

_UNSET = object()


class _LazyLoaderProxy:
    _loader_attributes = (
        "__file__",
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


DataConfig: Any | None = None
get_engine: Any | None = None
loader: Any = _LazyLoaderProxy()


@dataclass(frozen=True)
class LoadedData:
    rows: list[dict[str, Any]]


def load_data(config: RunConfig, *, engine: object | None = None) -> LoadedData:
    db_engine = engine if engine is not None else _default_engine()
    try:
        rows = _load_rows(config, db_engine)
    except DataLoadError:
        raise
    except Exception as exc:
        raise DataLoadError(f"data load failed: {exc}") from exc
    if not rows:
        raise DataLoadError("data load returned no rows")
    rows.sort(key=lambda row: (str(row.get("symbol", "")), row.get("timestamp")))
    return LoadedData(rows=rows)


def _load_rows(config: RunConfig, engine: object) -> list[dict[str, Any]]:
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
    env_file = _quant_data_env_file()
    engine_factory = _get_engine()
    if env_file is not None:
        config_type = _data_config_type()
        return engine_factory(config_type(_env_file=env_file))
    return engine_factory()


def _quant_data_env_file() -> Path | None:
    package_file = _loader_attribute(_loader(), "__file__")
    if package_file is None or package_file is _UNSET:
        return None
    root = Path(package_file).resolve().parents[2]
    env_file = root / ".env"
    return env_file if env_file.exists() else None


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


def _data_config_type() -> Any:
    global DataConfig
    if DataConfig is None:
        from quant_data.config import DataConfig as QuantDataConfig

        DataConfig = QuantDataConfig
    return DataConfig


def _get_engine() -> Any:
    global get_engine
    if get_engine is None:
        from quant_data.db import get_engine as quant_data_get_engine

        get_engine = quant_data_get_engine
    return get_engine
