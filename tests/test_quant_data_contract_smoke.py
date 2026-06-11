"""Opt-in smoke test for the real upstream ``quant_data`` strategy contract layer.

Purpose
-------
Prove that the live ``quant_data`` contract loaders return what the
``quant_strategies`` data boundary now assumes (tz-aware UTC timestamps, a
strictly-later ``available_at`` causality column, deterministic ordering, and
unique ``(symbol, timestamp)`` keys). This guards the integration seam between
the two repos against silent upstream drift.

Gating
------
The whole module is skipped unless ``RUN_QUANT_DATA_CONTRACT_SMOKE == "1"``.
With the flag unset the default offline test run reports these as skipped and
imports nothing that needs a database: ``quant_data`` imports happen *inside*
the test functions, so collection stays import-light and DB-free.

This test only loads a tiny recent window derived from the catalog. It never
materializes, repairs, refreshes, or duplicates upstream data — that work
belongs in ``quant-data``.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_QUANT_DATA_CONTRACT_SMOKE") != "1",
    reason="Set RUN_QUANT_DATA_CONTRACT_SMOKE=1 to run the live quant_data contract smoke (needs DB).",
)

EQUITY_DATASET = "equity_1min"
WINDOW_DAYS = 5
# Per-symbol live coverage can lag the dataset-level ``data_end`` (the strict readiness
# gate enforces the *per-symbol* live end), and equity bars skip weekends/holidays. Back
# off from ``data_end`` so the small window sits inside any single symbol's coverage —
# this sentinel guards contract SHAPE (tz/availability/ordering/uniqueness), not the
# freshness of the latest bar.
EDGE_MARGIN_DAYS = 10


def _smoke_window() -> tuple[date, date]:
    """Return a small recent ``(start, end)`` window safely inside per-symbol coverage."""
    from quant_data.catalog import DATASET_STATUS

    data_end = DATASET_STATUS[EQUITY_DATASET]["data_end"]
    assert isinstance(data_end, date), (
        f"DATASET_STATUS['{EQUITY_DATASET}']['data_end'] must be a date, got {type(data_end)!r}"
    )
    end = data_end - timedelta(days=EDGE_MARGIN_DAYS)
    return end - timedelta(days=WINDOW_DAYS), end


def _is_utc_datetime(value: object) -> bool:
    """True when ``value`` is a tz-aware datetime whose offset is exactly UTC."""
    if not isinstance(value, datetime):
        return False
    offset = value.utcoffset()
    return offset is not None and offset == timedelta(0)


def test_strategy_bars_contract_shape() -> None:
    from quant_data.catalog import EQUITY_1MIN_SYMBOLS
    from quant_data.contract_loaders import load_strategy_bars
    from quant_data.db import get_engine

    symbol = list(EQUITY_1MIN_SYMBOLS)[0]
    start, end = _smoke_window()

    engine = get_engine()
    frame = load_strategy_bars(engine, symbol, EQUITY_DATASET, start, end, strict=True)

    assert frame.height > 0, (
        f"load_strategy_bars returned no rows for {symbol} on {EQUITY_DATASET} in [{start}, {end}]"
    )

    required = {
        "symbol",
        "timestamp",
        "available_at",
        "open",
        "high",
        "low",
        "close",
        "volume",
    }
    missing = required - set(frame.columns)
    assert not missing, f"strategy bars frame is missing required columns: {sorted(missing)}"

    rows = frame.to_dicts()
    for row in rows:
        assert _is_utc_datetime(row["timestamp"]), (
            f"timestamp must be tz-aware UTC, got {row['timestamp']!r}"
        )
        assert _is_utc_datetime(row["available_at"]), (
            f"available_at must be tz-aware UTC, got {row['available_at']!r}"
        )
        assert row["available_at"] > row["timestamp"], (
            "available_at must be strictly after timestamp "
            f"(timestamp={row['timestamp']!r}, available_at={row['available_at']!r})"
        )

    timestamps = frame.get_column("timestamp").to_list()
    assert timestamps == sorted(timestamps), "strategy bars must be sorted by timestamp"


def test_universe_bars_ordering_and_uniqueness() -> None:
    from quant_data.catalog import EQUITY_1MIN_SYMBOLS
    from quant_data.contract_loaders import load_strategy_universe_bars
    from quant_data.db import get_engine

    symbols = list(EQUITY_1MIN_SYMBOLS)[:2]
    assert len(symbols) == 2, "need at least two equity_1min symbols for the universe smoke"
    start, end = _smoke_window()

    engine = get_engine()
    frame = load_strategy_universe_bars(engine, symbols, EQUITY_DATASET, start, end, strict=True)

    assert frame.height > 0, (
        f"load_strategy_universe_bars returned no rows for {symbols} on "
        f"{EQUITY_DATASET} in [{start}, {end}]"
    )

    for column in ("symbol", "timestamp", "available_at"):
        assert column in frame.columns, f"universe bars frame missing column {column!r}"

    # Single frame ordered by (timestamp, symbol).
    keys = list(
        zip(
            frame.get_column("timestamp").to_list(),
            frame.get_column("symbol").to_list(),
            strict=True,
        )
    )
    assert keys == sorted(keys), "universe bars must be ordered by (timestamp, symbol)"

    # No duplicate (symbol, timestamp) keys.
    dup_mask = frame.select("symbol", "timestamp").is_duplicated()
    assert not any(dup_mask.to_list()), "universe bars must have unique (symbol, timestamp) keys"

    # available_at is present, tz-aware UTC, and strictly after each row's timestamp.
    timestamps = frame.get_column("timestamp").to_list()
    availables = frame.get_column("available_at").to_list()
    for ts, value in zip(timestamps, availables, strict=True):
        assert _is_utc_datetime(value), f"available_at must be tz-aware UTC, got {value!r}"
        assert value > ts, f"available_at must be strictly after timestamp, got {value!r} <= {ts!r}"
