"""AC-10 — per-fold OOS returns via a typed in-process foundation accessor.

These tests pin the foundation-side contract that lets the `quant_autoresearch`
harness populate its `FoldReturns` / `FoldEvalResult` seam WITHOUT scraping
`tables/portfolio_path.parquet`. They reuse the evaluation runner's existing
`FakeBackend` injection so they need neither VectorBT Pro nor live data, plus a
parity check against the on-disk Parquet the same run writes.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from tests.test_evaluation_runner import (
    AS_OF,
    CadenceFakeBackend,
    FakeBackend,
    completed_metrics,
    rows,
    write_candidate,
)

from quant_strategies.core.data_loader import LoadedData
from quant_strategies.evaluation import (
    EvaluationRunResult,
    FoldReturnSeries,
    FoldScenarioMetrics,
)
from quant_strategies.evaluation._pipeline import _run_evaluation as run_evaluation
from quant_strategies.evaluation.results import PortfolioEvaluationResult, PortfolioTraceTables

ANNUALIZED_RISK_METRICS = ("sharpe", "sortino", "calmar")


class MultiBarFakeBackend(FakeBackend):
    """Emits a multi-row portfolio_path with a mix of finite returns.

    The first period_return is the synthetic initial 0.0 (dropped by the
    observed-return semantics); the rest are the OOS sample.
    """

    def run(
        self,
        *,
        decisions: Sequence[Any],
        rows: Sequence[dict[str, Any]],
        scenario: Any,
        metrics: Any,
        data_kind: str = "bars",
        capacity_model: Any = None,
        risk_budget: Any = None,
        leverage_budget: Any = None,
    ) -> PortfolioEvaluationResult:
        timestamps = [AS_OF + timedelta(days=index) for index in range(4)]
        period_returns = [0.0, 0.01, -0.02, 0.03]
        values = [100.0]
        for ret in period_returns[1:]:
            values.append(values[-1] * (1.0 + ret))
        frame = pd.DataFrame(
            {
                "scenario_id": [scenario.scenario_id] * len(timestamps),
                "timestamp": timestamps,
                "portfolio_value": values,
                "period_return": period_returns,
                "drawdown": [0.0, 0.0, -0.02, 0.0],
            }
        )
        tables = PortfolioTraceTables(
            portfolio_path=frame,
            trades=pd.DataFrame({"scenario_id": [scenario.scenario_id], "trade_id": [1]}),
            target_positions=pd.DataFrame(
                {
                    "scenario_id": [scenario.scenario_id],
                    "timestamp": [timestamps[0]],
                    "asset": ["BTC-PERP"],
                    "target_weight": [0.25],
                }
            ),
            target_exposure_summary=pd.DataFrame(
                {
                    "scenario_id": [scenario.scenario_id],
                    "asset": ["BTC-PERP"],
                    "decision_count": [1],
                }
            ),
            execution_events=pd.DataFrame({"scenario_id": []}),
            funding_cashflows=pd.DataFrame({"scenario_id": []}),
        )
        return PortfolioEvaluationResult(
            scenario_id=scenario.scenario_id,
            backend=self.name,
            status="completed",
            metrics=completed_metrics(),
            tables=tables,
        )


def _complete_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    backend: Any,
    window_ids: Sequence[str] = ("eval_2026_h1",),
    annualization: int = 365,
) -> EvaluationRunResult:
    candidate = write_candidate(tmp_path, window_ids=window_ids, annualization=annualization)
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )
    return run_evaluation(candidate / "evaluation.toml", repo_root=tmp_path, backend=backend)


# --- AC-10: per-fold OOS returns via the typed API ---------------------------


def test_completed_run_exposes_typed_fold_returns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    result = _complete_run(tmp_path, monkeypatch, backend=MultiBarFakeBackend())

    assert result.run_completed is True
    # one series per completed (window, scenario) — default fanout is 6 scenarios
    assert len(result.fold_returns) == 6
    assert all(isinstance(series, FoldReturnSeries) for series in result.fold_returns)

    series = result.returns_for("eval_2026_h1", "eval_2026_h1/realistic_costs/base_fill")
    assert series is not None
    assert isinstance(series.timestamps, np.ndarray)
    assert isinstance(series.values, np.ndarray)
    assert series.values.dtype == np.float64
    assert np.issubdtype(series.timestamps.dtype, np.datetime64)
    # synthetic first return dropped -> 3 observed OOS returns
    assert series.values.tolist() == pytest.approx([0.01, -0.02, 0.03])
    assert series.timestamps.shape == series.values.shape
    assert series.periods_per_year == pytest.approx(365.0)
    assert series.per_symbol is None
    # strictly increasing timestamps
    assert (np.diff(series.timestamps.astype("datetime64[ns]")) > np.timedelta64(0)).all()


def test_fold_returns_obtained_without_reading_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The series must come from the result object, not from result_dir."""
    result = _complete_run(tmp_path, monkeypatch, backend=MultiBarFakeBackend())

    # Delete the on-disk traces entirely; the in-process accessor must still work.
    assert result.result_dir is not None
    tables_dir = result.result_dir / "tables"
    assert (tables_dir / "portfolio_path.parquet").exists()
    for parquet in tables_dir.glob("*.parquet"):
        parquet.unlink()

    series = result.returns_for("eval_2026_h1", "eval_2026_h1/zero_costs/base_fill")
    assert series is not None
    assert series.values.tolist() == pytest.approx([0.01, -0.02, 0.03])


def test_typed_series_matches_on_disk_portfolio_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Parity: typed values/timestamps == Parquet period_return/timestamp after
    dropping the synthetic first return and excluding non-finite."""
    result = _complete_run(tmp_path, monkeypatch, backend=MultiBarFakeBackend())
    assert result.result_dir is not None

    parquet = pd.read_parquet(result.result_dir / "tables" / "portfolio_path.parquet")
    for series in result.fold_returns:
        scenario_rows = parquet[parquet["scenario_id"] == series.scenario_id]
        # same observed-return definition the metrics use
        observed = scenario_rows["period_return"].to_numpy()[1:]
        finite_mask = np.isfinite(observed)
        expected_values = observed[finite_mask]
        expected_timestamps = (
            pd.to_datetime(scenario_rows["timestamp"], utc=True)
            .dt.tz_convert(None)
            .to_numpy()[1:][finite_mask]
            .astype("datetime64[ns]")
        )
        assert series.values.tolist() == pytest.approx(expected_values.tolist())
        assert series.timestamps.astype("datetime64[ns]").tolist() == (expected_timestamps.tolist())


# --- one-evaluate-per-fold ----------------------------------------------------


def test_single_window_evaluate_returns_only_that_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    result = _complete_run(
        tmp_path, monkeypatch, backend=MultiBarFakeBackend(), window_ids=("only_fold",)
    )

    assert result.run_completed is True
    assert result.window_ids == ("only_fold",)
    assert {series.window_id for series in result.fold_returns} == {"only_fold"}
    assert all(series.scenario_id.startswith("only_fold/") for series in result.fold_returns)


def test_two_windows_key_series_by_window(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    result = _complete_run(
        tmp_path,
        monkeypatch,
        backend=MultiBarFakeBackend(),
        window_ids=("fold_a", "fold_b"),
    )

    assert result.run_completed is True
    assert set(result.window_ids) == {"fold_a", "fold_b"}
    assert all(sid.startswith("fold_a/") for sid in result.scenario_ids_for("fold_a"))
    assert all(sid.startswith("fold_b/") for sid in result.scenario_ids_for("fold_b"))
    # a series from fold_a never carries fold_b rows
    series_a = result.returns_for("fold_a", "fold_a/realistic_costs/base_fill")
    assert series_a is not None
    assert series_a.window_id == "fold_a"


def test_window_id_with_slash_resolves_against_known_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A window id containing '/' must resolve to the full window id, not the
    first scenario-id segment (matches the runner's collision-proof window ids)."""
    result = _complete_run(
        tmp_path, monkeypatch, backend=MultiBarFakeBackend(), window_ids=("eval/2026",)
    )

    assert result.run_completed is True
    assert result.window_ids == ("eval/2026",)
    assert {series.window_id for series in result.fold_returns} == {"eval/2026"}
    series = result.returns_for("eval/2026", "eval/2026/realistic_costs/base_fill")
    assert series is not None
    assert series.window_id == "eval/2026"


# --- per-fold causal / contract integrity observable --------------------------


def test_completed_run_reports_causal_replay_passed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    result = _complete_run(tmp_path, monkeypatch, backend=MultiBarFakeBackend())

    assert result.run_completed is True
    assert result.causal_replay_passed is True
    assert result.scenario_metrics
    assert all(metrics.causal_ok is True for metrics in result.scenario_metrics)


def test_data_audit_failure_reports_causal_replay_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A decision that references a future observation fails the data audit
    (a Tier-0 decision-contract integrity failure)."""
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "strategy.py").write_text(
        "from quant_strategies.decisions import InstrumentRef, ObservationRef, TargetDecision\n"
        "def validate_params(params):\n    return dict(params)\n"
        "def generate_decisions(rows, params):\n"
        "    btc_rows = [row for row in rows if row['symbol'] == 'BTC-PERP']\n"
        "    if len(btc_rows) < 2:\n"
        "        return []\n"
        "    return [TargetDecision(\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='crypto_perp', symbol='BTC-PERP'),\n"
        "        decision_time=btc_rows[1]['timestamp'],\n"
        "        as_of_time=btc_rows[1]['timestamp'],\n"
        "        target=0.25,\n"
        # observation references the LAST row -> not available by decision_time
        "        observations=(ObservationRef(symbol='BTC-PERP', timestamp=btc_rows[-1]['timestamp'], "
        "field='close', source='strategy_input'),),\n"
        "    )]\n"
    )
    (candidate / "evaluation.toml").write_text(
        """
strategy_path = "strategy.py"
strategy_id = "demo"

[[windows]]
id = "eval_2026_h1"
start = "2026-01-01"
end = "2026-06-30"

[data]
kind = "crypto_perp_funding"
symbols = ["BTC-PERP"]

[params]
weight = 0.25

[fill_model]
price = "close"
entry_lag_bars = 1

[cost_model]
fee_bps_per_side = 0.5
slippage_bps_per_side = 0.5

[capacity_model]
mode = "adv_impact"
portfolio_notional = 1000.0
adv_lookback_bars = 3
adv_min_observations = 1
max_bar_participation = 1.0
max_adv_participation = 1.0
impact_coefficient_bps = 0.0
impact_exponent = 1.0

[risk_budget]
mode = "fixed_scale"
annualization_periods_per_year = 252
book_scale = 1.0

[metrics]
annualization_periods_per_year = 365

[output]
results_dir = "evaluation_results/demo"
""".lstrip()
    )
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )

    result = run_evaluation(
        candidate / "evaluation.toml", repo_root=tmp_path, backend=MultiBarFakeBackend()
    )

    assert result.run_completed is False
    assert result.failure_stage in {"data_audit", "preflight"}
    assert result.causal_replay_passed is False
    assert result.fold_returns == ()


def test_config_load_failure_leaves_causal_replay_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    result = run_evaluation(tmp_path / "missing.toml", repo_root=tmp_path, backend=FakeBackend())

    assert result.run_completed is False
    assert result.failure_stage == "config_load"
    assert result.causal_replay_passed is None


# --- summary scalars + provenance + cadence guard ----------------------------


def test_scenario_metrics_expose_scalars_and_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    result = _complete_run(tmp_path, monkeypatch, backend=MultiBarFakeBackend())

    assert len(result.scenario_metrics) == 6
    metrics = result.metrics_for("eval_2026_h1", "eval_2026_h1/realistic_costs/base_fill")
    assert isinstance(metrics, FoldScenarioMetrics)
    assert metrics.sharpe == pytest.approx(0.50)
    assert metrics.sortino == pytest.approx(0.75)
    assert metrics.calmar == pytest.approx(10.0)
    assert metrics.max_drawdown == pytest.approx(-0.01)
    assert metrics.trade_count == 1
    assert metrics.worst_period_return == pytest.approx(-0.005)
    assert metrics.return_sample_count == 1
    # provenance is a typed string map sufficient to reproduce the metric
    assert isinstance(metrics.provenance, dict)
    assert metrics.provenance  # non-empty
    assert all(isinstance(value, str) for value in metrics.provenance.values())
    # run-level provenance also present
    assert result.provenance
    assert all(isinstance(value, str) for value in result.provenance.values())


def test_no_significance_statistics_on_accessor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """PSR/DSR/PBO must NOT leak into the foundation accessor."""
    result = _complete_run(tmp_path, monkeypatch, backend=MultiBarFakeBackend())

    metrics = result.metrics_for("eval_2026_h1", "eval_2026_h1/realistic_costs/base_fill")
    assert metrics is not None
    forbidden = {"psr", "dsr", "pbo", "deflated_sharpe", "probabilistic_sharpe"}
    metric_fields = {field.lower() for field in vars(metrics)}
    assert metric_fields.isdisjoint(forbidden)


def test_cadence_guard_nulls_scalars_but_keeps_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Mismatched cadence nulls annualized scalars; raw return values stay."""
    # minute spacing observed but 365 configured -> cadence mismatch warning,
    # annualized/risk scalars nulled by the existing trust boundary.
    minute_timestamps = [AS_OF + timedelta(minutes=index) for index in range(4)]
    result = _complete_run(
        tmp_path,
        monkeypatch,
        backend=CadenceFakeBackend(minute_timestamps),
        annualization=365,
    )

    assert result.run_completed is True
    metrics = result.metrics_for("eval_2026_h1", "eval_2026_h1/realistic_costs/base_fill")
    assert metrics is not None
    for name in ANNUALIZED_RISK_METRICS:
        assert getattr(metrics, name) is None
    # core economics (drawdown) survive
    assert metrics.max_drawdown == pytest.approx(-0.01)
    # the raw OOS return series is still populated
    series = result.returns_for("eval_2026_h1", "eval_2026_h1/realistic_costs/base_fill")
    assert series is not None
    assert series.values.size >= 1


# --- additive / non-breaking --------------------------------------------------


def test_default_result_is_backward_compatible():
    result = EvaluationRunResult(result_dir=None, message="x")
    assert result.fold_returns == ()
    assert result.scenario_metrics == ()
    assert result.causal_replay_passed is None
    assert result.provenance == {}
    assert result.succeeded is False
    # succeeded contract unchanged
    ok = EvaluationRunResult(result_dir=None, message="x", run_completed=True)
    assert ok.succeeded is True
    assert result.returns_for("w", "w/s") is None
    assert result.metrics_for("w", "w/s") is None
    assert result.window_ids == ()


# --- real backend smoke (opt-in) ---------------------------------------------


def test_spine_backend_fold_returns_smoke():
    """Prove the accessor extracts a typed series from the REAL single book backend's
    portfolio_path (drives ``SpineEvaluationBackend`` directly, the only money model)."""
    from datetime import datetime as _dt

    from tests.test_evaluation_backend import capacity_model, decision, flat, scenario
    from tests.test_evaluation_backend import rows as backend_rows

    from quant_strategies.core.config import RiskBudgetConfig
    from quant_strategies.evaluation.config import EvaluationMetricsConfig
    from quant_strategies.evaluation.fold_returns import fold_series_from_portfolio_path
    from quant_strategies.evaluation.spine_backend import SpineEvaluationBackend

    result = SpineEvaluationBackend().run(
        decisions=[
            decision(target=0.25),
            flat(when=_dt(2026, 1, 1, 0, 2, tzinfo=AS_OF.tzinfo)),
        ],
        rows=backend_rows(),
        scenario=scenario(),
        metrics=EvaluationMetricsConfig(annualization_periods_per_year=252),
        capacity_model=capacity_model(),
        risk_budget=RiskBudgetConfig(
            mode="fixed_scale",
            annualization_periods_per_year=252,
            book_scale=1.0,
        ),
    )
    assert result.status == "completed"
    assert result.tables is not None

    series = fold_series_from_portfolio_path(
        "w",
        result.scenario_id,
        result.tables.portfolio_path,
        periods_per_year=252.0,
    )
    assert isinstance(series.timestamps, np.ndarray)
    assert isinstance(series.values, np.ndarray)
    assert series.values.dtype == np.float64
    assert series.values.size >= 1
    assert series.timestamps.shape == series.values.shape
    assert series.per_symbol is None
    assert np.isfinite(series.values).all()
