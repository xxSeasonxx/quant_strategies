from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any


def json_safe_value(value: Any) -> Any:
    """Coerce a value into a JSON-serializable form (no NaN/Inf, no exotic types).

    Shared serialization helper used by the row contract, the data loader, and the
    artifact writers — it is not row-contract-specific, so it lives in `core`.
    """
    # Fast paths for the exact scalar types that dominate row values, so the
    # per-row canonical-JSON hot path skips the abc ``isinstance`` machinery. Each
    # returns exactly what the general logic below would for that value; anything
    # that is not an exact-type match (subclasses, numpy scalars, containers) falls
    # through unchanged, so output stays byte-identical for every input.
    value_type = type(value)
    if value_type is str or value_type is int or value_type is bool or value is None:
        return value
    if value_type is float:
        return value if math.isfinite(value) else None
    if value_type is datetime or value_type is date:
        return value.isoformat()
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Decimal):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    if hasattr(value, "item") and callable(value.item):
        try:
            return json_safe_value(value.item())
        except (TypeError, ValueError):
            pass
    if isinstance(value, Mapping):
        return {str(key): json_safe_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [json_safe_value(item) for item in value]
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError):
        return str(value)
    return value


def normalized_rows_sha256(rows: Sequence[Mapping[str, Any]]) -> str:
    digest = hashlib.sha256()
    for line in iter_canonical_row_lines(rows):
        digest.update(line.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def canonical_rows_jsonl(rows: Sequence[Mapping[str, Any]]) -> str:
    lines = list(canonical_row_lines(rows))
    return "\n".join(lines) + ("\n" if lines else "")


def canonical_row_lines(rows: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    return tuple(iter_canonical_row_lines(rows))


def iter_canonical_row_lines(rows: Iterable[Mapping[str, Any]]) -> Iterable[str]:
    for row in rows:
        yield canonical_row_line(row)


def canonical_row_line(row: Mapping[str, Any]) -> str:
    return json.dumps(json_safe_value(row), sort_keys=True, separators=(",", ":"), allow_nan=False)
