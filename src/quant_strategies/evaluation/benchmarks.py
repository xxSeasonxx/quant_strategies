from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from quant_strategies.evaluation.metrics import MetricValue, finite_metric_or_none


def benchmark_metrics_for_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    symbol: str,
) -> dict[str, MetricValue]:
    observed_rows: list[tuple[Any, Any]] = []
    for row in rows:
        if str(row.get("symbol", "")).strip() != symbol:
            continue
        observed_rows.append((row.get("timestamp"), row.get("close")))

    if not observed_rows:
        raise ValueError(f"missing_benchmark_rows:{symbol}")
    try:
        observed_rows.sort(key=lambda item: item[0])
    except TypeError as exc:
        raise ValueError(f"invalid_benchmark_timestamp:{symbol}") from exc

    benchmark_rows = [
        (timestamp, close)
        for timestamp, value in observed_rows
        if (close := finite_metric_or_none(value)) is not None and close > 0.0
    ]
    if len(benchmark_rows) < 2:
        raise ValueError(f"insufficient_finite_benchmark_closes:{symbol}")

    first_close = benchmark_rows[0][1]
    final_close = benchmark_rows[-1][1]
    return {
        "benchmark_symbol": symbol,
        "benchmark_total_return": (final_close / first_close) - 1.0,
    }
