from __future__ import annotations

from datetime import datetime
from typing import Any


def parse_aware_datetime(value: Any) -> tuple[datetime | None, str | None]:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        raw_value = value.strip()
        if raw_value.endswith("Z"):
            raw_value = f"{raw_value[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(raw_value)
        except ValueError:
            return None, "invalid datetime"
    else:
        return None, "expected aware datetime"

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None, "expected aware datetime"
    return parsed, None
