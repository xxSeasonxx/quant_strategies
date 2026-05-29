from __future__ import annotations

import json
import math
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Any


def json_safe_value(value: Any) -> Any:
    """Coerce a value into a JSON-serializable form (no NaN/Inf, no exotic types).

    Shared serialization helper used by the row contract, the data loader, and the
    artifact writers — it is not row-contract-specific, so it lives in `core`.
    """
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
