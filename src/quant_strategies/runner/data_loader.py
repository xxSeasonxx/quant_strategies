from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from quant_data.config import DataConfig
from quant_data.db import get_engine
from quant_data import loader

from quant_strategies.runner.config import RunConfig
from quant_strategies.runner.errors import DataLoadError


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
    if data.kind == "bars":
        if data.dataset is None:
            raise DataLoadError("data.dataset is required for bars")
        if len(data.symbols) == 1:
            frame = loader.load_bars(
                engine,
                data.symbols[0],
                data.dataset,
                data.start,
                data.end,
                research=True,
                strict=data.strict,
            )
            return _rows_from_frame(frame)
        universe = loader.load_universe_bars(
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
            frame = loader.load_crypto_perp_bars_with_funding(
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
            frame = loader.load_fx_bars_with_quotes(
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
    if env_file is not None:
        return get_engine(DataConfig(_env_file=env_file))
    return get_engine()


def _quant_data_env_file() -> Path | None:
    package_file = getattr(loader, "__file__", None)
    if package_file is None:
        return None
    root = Path(package_file).resolve().parents[2]
    env_file = root / ".env"
    return env_file if env_file.exists() else None
