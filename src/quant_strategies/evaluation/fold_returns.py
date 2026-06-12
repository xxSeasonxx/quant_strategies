"""Typed, in-process per-fold OOS return-series accessor objects.

These value objects let a consumer (the `quant_autoresearch` harness) read each
evaluation fold's out-of-sample per-period return series and summary risk scalars
directly from the evaluate result, without scraping `tables/portfolio_path.parquet`
across the repository boundary (PRD FR-J2, AC-10).

The arrays are numpy (the harness core is numpy); pandas stays internal to the
evaluation pipeline. The `values` use the same observed-return definition the
summary metrics already apply — the synthetic first period return is dropped and
non-finite returns are excluded — so the typed series is the same sample that feeds
`return_sample_count`/`sharpe` and the on-disk trace.

This module adds no deflated or significance statistics (PSR/DSR/PBO); significance
is the consumer's responsibility.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from quant_strategies.core.portfolio_foundation import FeasibilityVerdict
from quant_strategies.evaluation.metrics import MetricValue, finite_metric_or_none


@dataclass(frozen=True)
class FoldReturnSeries:
    """Per-`(window, scenario)` OOS return series at fixed grouped exposure.

    `timestamps` and `values` are aligned numpy arrays; `values` are per-period
    portfolio returns net of the scenario's configured costs. `per_symbol` is
    populated only by a backend that actually computes per-symbol return paths;
    the current grouped cash-shared backends leave it `None`.
    """

    window_id: str
    scenario_id: str
    timestamps: np.ndarray  # datetime64[ns], strictly increasing
    values: np.ndarray  # float64 per-period returns (net of costs)
    periods_per_year: float
    per_symbol: Mapping[str, FoldReturnSeries] | None = None


@dataclass(frozen=True)
class FoldScenarioMetrics:
    """Per-`(window, scenario)` undeflated summary risk scalars + provenance.

    Scalars mirror the backend's completed metrics and honor the annualized-metric
    trust boundary (annualized/risk scalars are `None` under a non-ok cadence or an
    insufficient return sample). No significance statistics are included.
    """

    window_id: str
    scenario_id: str
    sharpe: float | None
    sortino: float | None
    calmar: float | None
    max_drawdown: float | None
    worst_period_return: float | None
    trade_count: int | None
    return_sample_count: int | None
    causal_ok: bool
    scoreability_bearing: bool = True
    feasibility: FeasibilityVerdict = field(
        default_factory=lambda: FeasibilityVerdict(feasible=True)
    )
    provenance: Mapping[str, str] = field(default_factory=dict)


def _series_pairs_from_frame(frame: Any) -> tuple[np.ndarray, np.ndarray]:
    """Return aligned (timestamps[ns], values[f64]) from a portfolio_path frame.

    Applies the evaluation's observed-return semantics: drop the synthetic first
    period return, then exclude non-finite returns (keeping timestamps aligned).
    """
    import pandas as pd

    if frame is None or "period_return" not in getattr(frame, "columns", ()):
        return (
            np.empty(0, dtype="datetime64[ns]"),
            np.empty(0, dtype=np.float64),
        )

    returns = frame["period_return"].to_numpy()
    if "timestamp" in frame.columns:
        # Normalize to UTC then drop the tz to land on naive datetime64[ns]
        # (matches the seam contract) without the tz-representation warning.
        timestamps = (
            pd.to_datetime(frame["timestamp"], utc=True)
            .dt.tz_convert(None)
            .to_numpy()
            .astype("datetime64[ns]")
        )
    else:
        timestamps = np.array([np.datetime64("NaT")] * len(returns), dtype="datetime64[ns]")
    # drop the synthetic first period return
    returns = returns[1:]
    timestamps = timestamps[1:]
    values = np.asarray([float(value) for value in returns], dtype=np.float64)
    finite_mask = np.isfinite(values)
    return timestamps[finite_mask], values[finite_mask]


def fold_series_from_portfolio_path(
    window_id: str,
    scenario_id: str,
    frame: Any,
    *,
    periods_per_year: float,
) -> FoldReturnSeries:
    timestamps, values = _series_pairs_from_frame(frame)
    return FoldReturnSeries(
        window_id=window_id,
        scenario_id=scenario_id,
        timestamps=timestamps,
        values=values,
        periods_per_year=float(periods_per_year),
        per_symbol=None,
    )


def _optional_float(value: MetricValue) -> float | None:
    return finite_metric_or_none(value)


def _optional_int(value: MetricValue) -> int | None:
    metric = finite_metric_or_none(value)
    if metric is None or not metric.is_integer() or metric < 0.0:
        return None
    return int(metric)


def fold_metrics_from_scenario(
    window_id: str,
    scenario_id: str,
    metrics_map: Mapping[str, MetricValue],
    *,
    provenance: Mapping[str, str],
    causal_ok: bool,
    scoreability_bearing: bool = True,
    feasibility: FeasibilityVerdict | None = None,
) -> FoldScenarioMetrics:
    return FoldScenarioMetrics(
        window_id=window_id,
        scenario_id=scenario_id,
        sharpe=_optional_float(metrics_map.get("sharpe")),
        sortino=_optional_float(metrics_map.get("sortino")),
        calmar=_optional_float(metrics_map.get("calmar")),
        max_drawdown=_optional_float(metrics_map.get("max_drawdown")),
        worst_period_return=_optional_float(metrics_map.get("worst_period_return")),
        trade_count=_optional_int(metrics_map.get("trade_count")),
        return_sample_count=_optional_int(metrics_map.get("return_sample_count")),
        causal_ok=causal_ok,
        scoreability_bearing=scoreability_bearing,
        feasibility=FeasibilityVerdict(feasible=True) if feasibility is None else feasibility,
        provenance=dict(provenance),
    )


def split_portfolio_path_by_scenario(frame: Any) -> dict[str, Any]:
    """Split a (possibly combined) portfolio_path frame into per-scenario frames.

    A single scenario's trace result carries only its own rows, but the schema
    includes `scenario_id`; honoring it keeps this robust to combined frames.
    """
    if frame is None or "scenario_id" not in getattr(frame, "columns", ()):
        return {}
    if not hasattr(frame, "groupby"):
        return {}
    return {str(scenario_id): group for scenario_id, group in frame.groupby("scenario_id")}


def window_id_for_scenario(scenario_id: str, known_window_ids: Sequence[str]) -> str:
    """Recover the window id of a scenario id (`"{window_id}/..."`).

    A window id may itself contain `/`, so resolve against the known window ids
    (longest matching `"{window_id}/"` prefix wins) rather than splitting on the
    first slash. Falls back to the first-segment prefix if nothing matches.
    """
    matches = [
        window_id
        for window_id in known_window_ids
        if scenario_id == window_id or scenario_id.startswith(f"{window_id}/")
    ]
    if matches:
        return max(matches, key=len)
    return scenario_id.split("/", 1)[0]
