from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

import quant_strategies.evaluation._pipeline as evaluation_runner
from quant_strategies.causality import LookaheadCheckResult
from quant_strategies.core.accounting_model import SHARED_ACCOUNTING_MODEL
from quant_strategies.core.data_loader import LoadedData
from quant_strategies.core.portfolio_foundation import FeasibilityVerdict
from quant_strategies.evaluation._pipeline import _run_evaluation as run_evaluation
from quant_strategies.evaluation.benchmarks import benchmark_metrics_for_rows
from quant_strategies.evaluation.dependencies import EvaluationDependencyError
from quant_strategies.evaluation.results import PortfolioEvaluationResult, PortfolioTraceTables

AS_OF = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
DECISION = datetime(2026, 1, 1, 0, 1, tzinfo=UTC)
ANNUALIZED_RISK_METRICS = ("annualized_return", "volatility", "sharpe", "sortino", "calmar")


def rows() -> list[dict[str, Any]]:
    return [
        {
            "symbol": "BTC-PERP",
            "timestamp": AS_OF,
            "available_at": AS_OF,
            "open": 100.0,
            "high": 100.0,
            "low": 100.0,
            "close": 100.0,
            "volume": 1_000.0,
            "vwap": 100.0,
            "num_trades": 100,
            "has_funding_event": False,
        },
        {
            "symbol": "BTC-PERP",
            "timestamp": DECISION,
            "available_at": DECISION,
            "open": 101.0,
            "high": 101.0,
            "low": 101.0,
            "close": 101.0,
            "volume": 1_000.0,
            "vwap": 101.0,
            "num_trades": 100,
            "has_funding_event": False,
        },
        {
            "symbol": "BTC-PERP",
            "timestamp": datetime(2026, 1, 1, 0, 2, tzinfo=UTC),
            "available_at": datetime(2026, 1, 1, 0, 2, tzinfo=UTC),
            "open": 102.0,
            "high": 102.0,
            "low": 102.0,
            "close": 102.0,
            "volume": 1_000.0,
            "vwap": 102.0,
            "num_trades": 100,
            "has_funding_event": False,
        },
        {
            "symbol": "BTC-PERP",
            "timestamp": datetime(2026, 1, 1, 0, 3, tzinfo=UTC),
            "available_at": datetime(2026, 1, 1, 0, 3, tzinfo=UTC),
            "open": 103.0,
            "high": 103.0,
            "low": 103.0,
            "close": 103.0,
            "volume": 1_000.0,
            "vwap": 103.0,
            "num_trades": 100,
            "has_funding_event": False,
        },
    ]


def messy_raw_rows() -> list[dict[str, Any]]:
    messy = []
    for row in rows():
        raw = dict(row)
        raw["timestamp"] = row["timestamp"].isoformat()
        raw["available_at"] = row["available_at"].isoformat()
        for field in ("open", "high", "low", "close"):
            raw[field] = str(row[field])
        raw["VendorField"] = "kept but irrelevant"
        messy.append(raw)
    return messy


def rows_with_benchmark() -> list[dict[str, Any]]:
    benchmark_closes = {
        AS_OF: 200.0,
        DECISION: 205.0,
        datetime(2026, 1, 1, 0, 2, tzinfo=UTC): 210.0,
        datetime(2026, 1, 1, 0, 3, tzinfo=UTC): 220.0,
    }
    benchmark_rows = [
        {
            "symbol": "SPY",
            "timestamp": timestamp,
            "available_at": timestamp,
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": 1_000.0,
            "vwap": close,
            "num_trades": 100,
            "has_funding_event": False,
        }
        for timestamp, close in benchmark_closes.items()
    ]
    return [*rows(), *benchmark_rows]


def write_candidate(
    tmp_path: Path,
    *,
    with_param_validator: bool = True,
    data_kind: str = "bars",
    window_ids: Sequence[str] = ("eval_2026_h1",),
    annualization: int = 365,
    extra_config: str = "",
) -> Path:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    validator = (
        "def validate_params(params):\n    return dict(params)\n" if with_param_validator else ""
    )
    dataset_line = 'dataset = "demo_bars"\n' if data_kind == "bars" else ""
    (candidate / "strategy.py").write_text(
        "from quant_strategies.decisions import InstrumentRef, ObservationRef, TargetDecision\n"
        f"{validator}"
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
        "        observations=(ObservationRef(symbol='BTC-PERP', timestamp=btc_rows[1]['timestamp'], "
        "field='close', source='strategy_input'),),\n"
        "    )]\n"
    )
    windows_toml = "\n".join(
        f'''
[[windows]]
id = "{window_id}"
start = "2026-01-01"
end = "2026-06-30"
'''.strip()
        for window_id in window_ids
    )
    (candidate / "evaluation.toml").write_text(
        f'''
strategy_path = "strategy.py"
strategy_id = "demo"

{windows_toml}

[data]
kind = "{data_kind}"
{dataset_line}symbols = ["BTC-PERP"]

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
annualization_periods_per_year = {annualization}
{extra_config}

[output]
results_dir = "evaluation_results/demo"
'''.lstrip()
    )
    return candidate


class FakeBackend:
    name = "fake_evaluation"

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
    ):
        frame = pd.DataFrame(
            {
                "scenario_id": [scenario.scenario_id],
                "timestamp": [rows[0]["timestamp"]],
                "portfolio_value": [100.0],
                "period_return": [0.0],
                "drawdown": [0.0],
            }
        )
        tables = PortfolioTraceTables(
            portfolio_path=frame,
            trades=pd.DataFrame({"scenario_id": [scenario.scenario_id], "trade_id": [1]}),
            target_positions=pd.DataFrame(
                {
                    "scenario_id": [scenario.scenario_id],
                    "timestamp": [rows[0]["timestamp"]],
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


class CadenceFakeBackend(FakeBackend):
    def __init__(self, timestamps: Sequence[datetime]) -> None:
        self._timestamps = tuple(timestamps)

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
    ):
        frame = pd.DataFrame(
            {
                "scenario_id": [scenario.scenario_id] * len(self._timestamps),
                "timestamp": list(self._timestamps),
                "portfolio_value": [
                    100.0 + index for index, _timestamp in enumerate(self._timestamps)
                ],
                "period_return": [0.0, *([0.01] * (len(self._timestamps) - 1))],
                "drawdown": [0.0] * len(self._timestamps),
            }
        )
        tables = PortfolioTraceTables(
            portfolio_path=frame,
            trades=pd.DataFrame({"scenario_id": [scenario.scenario_id], "trade_id": [1]}),
            target_positions=pd.DataFrame(
                {
                    "scenario_id": [scenario.scenario_id],
                    "timestamp": [self._timestamps[0]],
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


class MixedCadenceFakeBackend(CadenceFakeBackend):
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
    ):
        spacing = (
            timedelta(minutes=1)
            if scenario.scenario_id.endswith("/zero_costs/base_fill")
            else timedelta(days=1)
        )
        timestamps = [AS_OF + spacing * index for index in range(4)]
        return CadenceFakeBackend(timestamps).run(
            decisions=decisions,
            rows=rows,
            scenario=scenario,
            metrics=metrics,
        )


class MixedSparseCadenceFakeBackend(FakeBackend):
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
    ):
        if scenario.scenario_id.endswith("/sparse"):
            return FakeBackend.run(
                self, decisions=decisions, rows=rows, scenario=scenario, metrics=metrics
            )
        timestamps = [AS_OF + timedelta(days=index) for index in range(4)]
        return CadenceFakeBackend(timestamps).run(
            decisions=decisions,
            rows=rows,
            scenario=scenario,
            metrics=metrics,
        )


class MixedMismatchAndSparseCadenceFakeBackend(FakeBackend):
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
    ):
        if scenario.scenario_id.endswith("/sparse"):
            return FakeBackend.run(
                self, decisions=decisions, rows=rows, scenario=scenario, metrics=metrics
            )
        timestamps = [AS_OF + timedelta(minutes=index) for index in range(4)]
        return CadenceFakeBackend(timestamps).run(
            decisions=decisions,
            rows=rows,
            scenario=scenario,
            metrics=metrics,
        )


def completed_metrics() -> dict[str, int | float | str]:
    return {
        "total_return": 0.01,
        "ending_value": 101.0,
        "max_drawdown": -0.01,
        "annualized_return": 0.10,
        "volatility": 0.20,
        "sharpe": 0.50,
        "sortino": 0.75,
        "calmar": 10.0,
        "worst_period_return": -0.005,
        "trade_count": 1,
        "return_total_count_excluding_initial": 1,
        "return_sample_count": 1,
        "return_nonfinite_count": 0,
        "funding_cashflow_total": 0.0,
        "funding_event_count": 0,
        "funding_model": SHARED_ACCOUNTING_MODEL,
    }


class PreparedFakeBackend(FakeBackend):
    def __init__(self) -> None:
        self.prepare_calls: list[tuple[Sequence[Any], Sequence[dict[str, Any]]]] = []
        self.run_prepared_scenario_ids: list[str] = []

    def prepare_inputs(
        self,
        *,
        decisions: Sequence[Any],
        rows: Sequence[dict[str, Any]],
        data_kind: str = "bars",
        capacity_model: Any = None,
        risk_budget: Any = None,
        leverage_budget: Any = None,
    ) -> dict[str, Any]:
        self.prepare_calls.append((decisions, rows))
        return {"decisions": decisions, "rows": rows}

    def run_prepared(self, *, prepared: dict[str, Any], scenario: Any, metrics: Any):
        self.run_prepared_scenario_ids.append(scenario.scenario_id)
        return self.run(
            decisions=prepared["decisions"],
            rows=prepared["rows"],
            scenario=scenario,
            metrics=metrics,
        )


def assert_failure_artifacts(
    result: evaluation_runner.EvaluationRunResult,
    *,
    failure_stage: str,
    assessment_status: str,
    message_fragment: str | None = None,
    unsupported_semantics: Sequence[str] = (),
) -> dict[str, Any]:
    assert result.result_dir is not None
    failure_path = result.result_dir / "evaluation_failure.json"
    notes_path = result.result_dir / "notes.md"
    assert failure_path.exists()
    assert notes_path.exists()
    payload = json.loads(failure_path.read_text())
    assert payload["schema_version"] == "quant_strategies.evaluation.failure/v1"
    assert payload["strategy_id"] == "demo"
    assert payload["failure_stage"] == failure_stage
    assert payload["assessment_status"] == assessment_status
    assert (
        payload["not_authority"]
        == "not validation, promotion, paper trading, or live trading authority"
    )
    assert "generated_at_utc" in payload
    assert "scenario_coverage" in payload["scenario_summary"]
    assert "data_windows" in payload
    if message_fragment is not None:
        assert message_fragment in payload["message"]
        assert message_fragment in notes_path.read_text()
    for semantic in unsupported_semantics:
        assert semantic in payload["unsupported_semantics"]
    return payload


def test_run_evaluation_writes_evidence_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    candidate = write_candidate(tmp_path)
    backend = PreparedFakeBackend()
    events: list[dict[str, object]] = []
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=messy_raw_rows()),
    )

    result = run_evaluation(
        candidate / "evaluation.toml",
        repo_root=tmp_path,
        backend=backend,
        event_sink=events.append,
    )

    assert result.run_completed is True
    assert result.failure_stage is None
    assert result.assessment_status == "evaluation_complete"
    assert result.result_dir is not None
    assert (result.result_dir / "evaluation_config.toml").exists()
    assert (result.result_dir / "strategy_snapshot.py").exists()
    assert (result.result_dir / "data_manifest.json").exists()
    assert (result.result_dir / "evaluation_metrics.json").exists()
    assert (result.result_dir / "scenario_summary.json").exists()
    assert (result.result_dir / "notes.md").exists()
    assert (result.result_dir / "evaluation_manifest.json").exists()
    input_row_files = list((result.result_dir / "audit" / "input_rows").glob("*.parquet"))
    decision_record_files = list((result.result_dir / "audit" / "decision_records").glob("*.jsonl"))
    assert len(input_row_files) == 1
    assert len(decision_record_files) == 1
    input_rows_path = input_row_files[0]
    decision_records_path = decision_record_files[0]
    assert input_rows_path.exists()
    assert decision_records_path.exists()
    assert (result.result_dir / "tables" / "portfolio_path.parquet").exists()
    assert (result.result_dir / "tables" / "trades.parquet").exists()
    assert (result.result_dir / "tables" / "target_positions.parquet").exists()
    assert (result.result_dir / "tables" / "target_exposure_summary.parquet").exists()
    assert (result.result_dir / "tables" / "execution_events.parquet").exists()
    assert (result.result_dir / "tables" / "funding_cashflows.parquet").exists()
    assert not (result.result_dir / "tables_staging").exists()
    assert len(backend.prepare_calls) == 1
    assert len(backend.run_prepared_scenario_ids) == 6
    prepared_rows = backend.prepare_calls[0][1]
    assert prepared_rows[0]["timestamp"] == AS_OF
    assert prepared_rows[0]["available_at"] == AS_OF
    assert prepared_rows[0]["close"] == 100.0
    assert prepared_rows[1]["timestamp"] == DECISION
    assert isinstance(prepared_rows[0]["timestamp"], datetime)
    assert prepared_rows[0]["timestamp"].tzinfo is not None
    assert isinstance(prepared_rows[0]["open"], float)
    assert isinstance(prepared_rows[0]["high"], float)
    assert isinstance(prepared_rows[0]["low"], float)
    assert isinstance(prepared_rows[0]["close"], float)
    data_manifest = json.loads((result.result_dir / "data_manifest.json").read_text())
    assert data_manifest["schema_version"] == "quant_strategies.evaluation.data_manifest/v1"
    assert data_manifest["windows"][0]["window_id"] == "eval_2026_h1"
    assert data_manifest["windows"][0]["row_count"] == 4
    assert len(data_manifest["windows"][0]["normalized_rows_sha256"]) == 64
    assert data_manifest["windows"][0]["row_contract"]["status"] == "passed"
    evidence_quality = data_manifest["windows"][0]["evidence_quality"]
    assert isinstance(evidence_quality, dict)
    assert evidence_quality["causality_verified"] is False
    assert evidence_quality["evidence_quality_warnings"] == ["runner_causality_not_verified"]
    assert "EvidenceQuality(" not in json.dumps(evidence_quality)
    assert data_manifest["windows"][0]["decision_count"] == 1
    assert data_manifest["windows"][0]["causality_replay"]["replay_scope"] == "complete"
    assert data_manifest["windows"][0]["causality_replay"]["replay_mode"] == "strict"
    assert (
        data_manifest["windows"][0]["input_rows_artifact"]["path"]
        == input_rows_path.relative_to(result.result_dir).as_posix()
    )
    assert data_manifest["windows"][0]["input_rows_artifact"]["row_count"] == 4
    assert len(data_manifest["windows"][0]["input_rows_artifact"]["file_sha256"]) == 64
    assert (
        data_manifest["windows"][0]["input_rows_artifact"]["normalized_rows_sha256"]
        == (data_manifest["windows"][0]["normalized_rows_sha256"])
    )
    assert (
        data_manifest["windows"][0]["decision_records_artifact"]["path"]
        == decision_records_path.relative_to(result.result_dir).as_posix()
    )
    assert data_manifest["windows"][0]["decision_records_artifact"]["row_count"] == 1
    assert len(data_manifest["windows"][0]["decision_records_artifact"]["sha256"]) == 64
    input_rows = pd.read_parquet(input_rows_path)
    assert input_rows["symbol"].tolist() == ["BTC-PERP", "BTC-PERP", "BTC-PERP", "BTC-PERP"]
    assert input_rows["close"].tolist() == [100.0, 101.0, 102.0, 103.0]
    decision_records = decision_records_path.read_text().splitlines()
    assert len(decision_records) == 1
    decision_payload = json.loads(decision_records[0])
    assert decision_payload["strategy_id"] == "demo"
    assert decision_payload["decision_id"].startswith("demo:")
    assert decision_payload["instrument"]["symbol"] == "BTC-PERP"
    manifest = json.loads((result.result_dir / "evaluation_manifest.json").read_text())
    assert manifest["evaluation"]["evidence_class"] == "research_evaluation"
    assert (
        manifest["evaluation"]["not_authority"]
        == "not validation, promotion, paper trading, or live trading authority"
    )
    assert manifest["audit_artifacts"]["input_rows"] == [
        data_manifest["windows"][0]["input_rows_artifact"]
    ]
    assert manifest["audit_artifacts"]["decision_records"] == [
        data_manifest["windows"][0]["decision_records_artifact"]
    ]
    assert manifest["replayability"]["replayable_from_artifacts"] is True
    assert manifest["replayability"]["input_rows_embedded"] is True
    assert manifest["replayability"]["decision_records_embedded"] is True
    assert len(manifest["tables"]) == 6
    assert {item["artifact_kind"] for item in manifest["tables"]} == {
        "portfolio_path",
        "trades",
        "target_positions",
        "target_exposure_summary",
        "execution_events",
        "funding_cashflows",
    }
    assert {item["path"] for item in manifest["tables"]} == {
        "tables/portfolio_path.parquet",
        "tables/trades.parquet",
        "tables/target_positions.parquet",
        "tables/target_exposure_summary.parquet",
        "tables/execution_events.parquet",
        "tables/funding_cashflows.parquet",
    }
    assert all(len(item["scenario_ids"]) == 6 for item in manifest["tables"])
    assert manifest["scenario_coverage"]["expected_count"] == 6
    assert manifest["scenario_coverage"]["completed_count"] == 6
    assert (
        manifest["scenario_coverage"]["expected_ids"]
        == manifest["scenario_coverage"]["completed_ids"]
    )
    assert manifest["scenario_coverage"]["missing_ids"] == []
    assert manifest["scenario_coverage"]["unexpected_ids"] == []
    assert {event["event"] for event in events} == {"evaluation_stage"}
    assert not [event for event in events if event["status"] == "failed"]
    completed_stages = {event["stage"] for event in events if event["status"] == "completed"}
    assert {
        "config_load",
        "artifact_initialization",
        "window_execution",
        "causality_check",
        "portfolio_input_preparation",
        "portfolio_evaluation",
        "artifact_writes",
    } <= completed_stages
    completed_scenario_events = [
        event
        for event in events
        if event["stage"] == "portfolio_evaluation" and event["status"] == "completed"
    ]
    assert len(completed_scenario_events) == 6
    assert {event["scenario_id"] for event in completed_scenario_events} == set(
        manifest["scenario_coverage"]["expected_ids"]
    )
    assert all("duration_ms" in event for event in events if event["status"] == "completed")


def test_run_evaluation_uses_configured_custom_scenarios(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    candidate = write_candidate(tmp_path)
    config_path = candidate / "evaluation.toml"
    config_path.write_text(
        config_path.read_text()
        + """

[[scenarios]]
id = "realistic_base"
cost_scenario = "realistic_costs"
fill_scenario = "base_fill"

[[scenarios]]
id = "stressed_delay"
cost_scenario = "stressed_costs"
fill_scenario = "fill_lag_plus_1"

[scenarios.cost_model]
fee_bps_per_side = 3.0
slippage_bps_per_side = 5.0

[scenarios.fill_model]
price = "close"
entry_lag_bars = 2
"""
    )
    backend = PreparedFakeBackend()
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )

    result = run_evaluation(candidate / "evaluation.toml", repo_root=tmp_path, backend=backend)

    assert result.run_completed is True
    assert backend.run_prepared_scenario_ids == [
        "eval_2026_h1/realistic_base",
        "eval_2026_h1/stressed_delay",
    ]
    summary = json.loads((result.result_dir / "scenario_summary.json").read_text())
    assert summary["scenario_coverage"]["expected_ids"] == backend.run_prepared_scenario_ids
    manifest = json.loads((result.result_dir / "evaluation_manifest.json").read_text())
    assert manifest["scenario_coverage"]["expected_count"] == 2


def test_run_evaluation_bounded_causality_records_replay_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    candidate = write_candidate(
        tmp_path,
        extra_config="""

[causality_replay]
scope = "bounded"
probe_limit = 2
timeout_seconds = 5.0
""",
    )
    backend = FakeBackend()
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )

    result = run_evaluation(candidate / "evaluation.toml", repo_root=tmp_path, backend=backend)

    assert result.run_completed is True
    assert result.provenance["causality_replay_scope"] == "bounded"
    data_manifest = json.loads((result.result_dir / "data_manifest.json").read_text())
    replay = data_manifest["windows"][0]["causality_replay"]
    assert replay["replay_scope"] == "bounded"
    assert replay["replay_mode"] == "strict"
    assert replay["candidate_probe_count"] >= replay["selected_probe_count"]
    assert replay["timed_out"] is False


def test_run_evaluation_causality_failure_result_records_replay_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    candidate = write_candidate(
        tmp_path,
        extra_config="""

[causality_replay]
scope = "bounded"
probe_limit = 2
timeout_seconds = 5.0
""",
    )
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )
    monkeypatch.setattr(
        evaluation_runner,
        "check_bounded_causality",
        lambda *_args, **_kwargs: LookaheadCheckResult(
            passed=False,
            mode="strict",
            violations=("hidden_lookahead_detected",),
            replay_scope="bounded",
        ),
    )

    result = run_evaluation(
        candidate / "evaluation.toml", repo_root=tmp_path, backend=FakeBackend()
    )

    assert result.run_completed is False
    assert result.failure_stage == "preflight"
    assert result.provenance["causality_replay_scope"] == "bounded"


def test_run_evaluation_keeps_optional_custom_scenario_failures_non_blocking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    class OptionalFailureBackend(FakeBackend):
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
        ):
            if scenario.scenario_id.endswith("/optional_stress"):
                return PortfolioEvaluationResult(
                    scenario_id=scenario.scenario_id,
                    backend=self.name,
                    status="failed",
                    warnings=("optional stress failed",),
                )
            return super().run(decisions=decisions, rows=rows, scenario=scenario, metrics=metrics)

    candidate = write_candidate(tmp_path)
    config_path = candidate / "evaluation.toml"
    config_path.write_text(
        config_path.read_text()
        + """

[[scenarios]]
id = "required_base"
required = true

[[scenarios]]
id = "optional_stress"
required = false
"""
    )
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )

    result = run_evaluation(
        candidate / "evaluation.toml", repo_root=tmp_path, backend=OptionalFailureBackend()
    )

    assert result.run_completed is True
    assert result.failure_stage is None
    assert any(
        "optional_scenario_failed:eval_2026_h1/optional_stress" in item
        for item in result.evidence_quality_warnings
    )
    summary = json.loads((result.result_dir / "scenario_summary.json").read_text())
    coverage = summary["scenario_coverage"]
    assert coverage["expected_ids"] == [
        "eval_2026_h1/required_base",
        "eval_2026_h1/optional_stress",
    ]
    assert coverage["completed_ids"] == ["eval_2026_h1/required_base"]
    assert coverage["missing_ids"] == []
    assert coverage["missing_required_ids"] == []
    assert coverage["missing_optional_ids"] == ["eval_2026_h1/optional_stress"]
    assert summary["status_counts"] == {"completed": 1, "failed": 1}
    manifest = json.loads((result.result_dir / "evaluation_manifest.json").read_text())
    assert manifest["scenario_coverage"]["completed_ids"] == ["eval_2026_h1/required_base"]
    assert all(
        item["scenario_ids"] == ["eval_2026_h1/required_base"] for item in manifest["tables"]
    )


def test_run_evaluation_fails_required_scoreability_bearing_infeasible_scenario(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    class NonScoreableRealisticBackend(FakeBackend):
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
        ):
            result = super().run(
                decisions=decisions,
                rows=rows,
                scenario=scenario,
                metrics=metrics,
                data_kind=data_kind,
                capacity_model=capacity_model,
                risk_budget=risk_budget,
                leverage_budget=leverage_budget,
            )
            if scenario.scenario_id.endswith("/realistic_costs/base_fill"):
                return result.model_copy(
                    update={
                        "feasibility": FeasibilityVerdict(
                            feasible=False,
                            reason="insufficient_samples",
                            detail="at-risk return sample 1 < minimum 2",
                        )
                    }
                )
            return result

    candidate = write_candidate(tmp_path)
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )

    result = run_evaluation(
        candidate / "evaluation.toml",
        repo_root=tmp_path,
        backend=NonScoreableRealisticBackend(),
    )

    assert result.run_completed is False
    assert result.failure_stage == "portfolio_evaluation"
    assert result.fold_returns == ()
    assert "insufficient_samples" in result.message
    failure_payload = json.loads((result.result_dir / "evaluation_failure.json").read_text())
    scenario_payload = next(
        item
        for item in failure_payload["scenario_summary"]["scenarios"]
        if item["scenario_id"] == "eval_2026_h1/realistic_costs/base_fill"
    )
    assert scenario_payload["status"] == "failed"
    assert scenario_payload["feasibility"]["reason"] == "insufficient_samples"
    assert any(
        "non_scoreable:insufficient_samples" in item for item in scenario_payload["warnings"]
    )


def test_run_evaluation_fails_real_spine_required_insufficient_sample_scenario(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    candidate = write_candidate(tmp_path)
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )

    result = run_evaluation(candidate / "evaluation.toml", repo_root=tmp_path)

    assert result.run_completed is False
    assert result.failure_stage == "portfolio_evaluation"
    assert result.fold_returns == ()
    assert "insufficient_samples" in result.message
    failure_payload = json.loads((result.result_dir / "evaluation_failure.json").read_text())
    scenario_payload = next(
        item
        for item in failure_payload["scenario_summary"]["scenarios"]
        if item["scenario_id"] == "eval_2026_h1/realistic_costs/base_fill"
    )
    assert scenario_payload["status"] == "failed"
    assert scenario_payload["scoreability_bearing"] is True
    assert scenario_payload["feasibility"]["reason"] == "insufficient_samples"
    assert any(
        "non_scoreable:insufficient_samples" in item for item in scenario_payload["warnings"]
    )


def test_run_evaluation_keeps_non_scoreability_bearing_zero_cost_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    class ZeroCostDiagnosticBackend(FakeBackend):
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
        ):
            result = super().run(
                decisions=decisions,
                rows=rows,
                scenario=scenario,
                metrics=metrics,
                data_kind=data_kind,
                capacity_model=capacity_model,
                risk_budget=risk_budget,
                leverage_budget=leverage_budget,
            )
            if scenario.cost_scenario == "zero_costs":
                return result.model_copy(
                    update={
                        "feasibility": FeasibilityVerdict(
                            feasible=False,
                            reason="zero_cost",
                            detail="zero cost on a scoreable run is below the operator cost floor",
                        )
                    }
                )
            return result

    candidate = write_candidate(tmp_path)
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )

    result = run_evaluation(
        candidate / "evaluation.toml",
        repo_root=tmp_path,
        backend=ZeroCostDiagnosticBackend(),
    )

    assert result.run_completed is True
    assert result.failure_stage is None
    zero_metrics = result.metrics_for("eval_2026_h1", "eval_2026_h1/zero_costs/base_fill")
    assert zero_metrics is not None
    assert zero_metrics.scoreability_bearing is False
    assert zero_metrics.feasibility.reason == "zero_cost"
    metrics_payload = json.loads((result.result_dir / "evaluation_metrics.json").read_text())
    zero_payload = next(
        item
        for item in metrics_payload["scenarios"]
        if item["scenario_id"] == "eval_2026_h1/zero_costs/base_fill"
    )
    assert zero_payload["required"] is True
    assert zero_payload["scoreability_bearing"] is False
    assert zero_payload["feasibility"]["reason"] == "zero_cost"


def test_run_evaluation_fails_when_backend_returns_wrong_scenario_id_with_expected_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    class SwappedScenarioBackend(FakeBackend):
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
        ):
            result = super().run(decisions=decisions, rows=rows, scenario=scenario, metrics=metrics)
            swapped_id = (
                "eval_2026_h1/scenario_b"
                if scenario.scenario_id.endswith("/scenario_a")
                else "eval_2026_h1/scenario_a"
            )
            return result.model_copy(update={"scenario_id": swapped_id})

    candidate = write_candidate(tmp_path)
    config_path = candidate / "evaluation.toml"
    config_path.write_text(
        config_path.read_text()
        + """

[[scenarios]]
id = "scenario_a"

[[scenarios]]
id = "scenario_b"
"""
    )
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )

    result = run_evaluation(
        candidate / "evaluation.toml", repo_root=tmp_path, backend=SwappedScenarioBackend()
    )

    assert result.run_completed is False
    assert result.failure_stage == "portfolio_evaluation"
    assert result.assessment_status == "portfolio_evaluation_failed"
    assert "backend scenario id mismatch" in result.message


def test_run_evaluation_attaches_benchmark_metrics_to_each_scenario(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    candidate = write_candidate(tmp_path)
    config_path = candidate / "evaluation.toml"
    config_path.write_text(
        config_path.read_text().replace('symbols = ["BTC-PERP"]', 'symbols = ["BTC-PERP", "SPY"]')
        + """

[benchmark]
symbol = "SPY"
"""
    )
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows_with_benchmark()),
    )

    result = run_evaluation(
        candidate / "evaluation.toml", repo_root=tmp_path, backend=FakeBackend()
    )

    assert result.run_completed is True
    metrics_payload = json.loads((result.result_dir / "evaluation_metrics.json").read_text())
    assert len(metrics_payload["scenarios"]) == 6
    for item in metrics_payload["scenarios"]:
        metrics = item["metrics"]
        assert metrics["benchmark_symbol"] == "SPY"
        assert metrics["benchmark_total_return"] == pytest.approx(0.10)
        assert metrics["excess_total_return"] == pytest.approx(-0.09)
    semantics = metrics_payload["metric_semantics"]
    assert semantics["benchmark_total_return"]["not_authority"] == (
        "benchmark-relative evidence only; not ranking, promotion, paper trading, or live trading authority"
    )


def test_benchmark_metrics_ignore_trailing_nonfinite_close_after_valid_endpoint_pair():
    benchmark_rows = [
        {"symbol": "SPY", "timestamp": AS_OF, "close": 200.0},
        {"symbol": "SPY", "timestamp": DECISION, "close": 220.0},
        {
            "symbol": "SPY",
            "timestamp": datetime(2026, 1, 1, 0, 2, tzinfo=UTC),
            "close": float("nan"),
        },
    ]

    assert benchmark_metrics_for_rows(benchmark_rows, symbol="SPY") == {
        "benchmark_symbol": "SPY",
        "benchmark_total_return": pytest.approx(0.10),
    }


def test_benchmark_metrics_use_first_and_final_finite_positive_closes():
    benchmark_rows = [
        {"symbol": "SPY", "timestamp": AS_OF, "close": float("nan")},
        {"symbol": "SPY", "timestamp": DECISION, "close": 200.0},
        {
            "symbol": "SPY",
            "timestamp": datetime(2026, 1, 1, 0, 2, tzinfo=UTC),
            "close": float("inf"),
        },
        {
            "symbol": "SPY",
            "timestamp": datetime(2026, 1, 1, 0, 3, tzinfo=UTC),
            "close": 220.0,
        },
        {
            "symbol": "SPY",
            "timestamp": datetime(2026, 1, 1, 0, 4, tzinfo=UTC),
            "close": float("nan"),
        },
    ]

    assert benchmark_metrics_for_rows(benchmark_rows, symbol="SPY") == {
        "benchmark_symbol": "SPY",
        "benchmark_total_return": pytest.approx(0.10),
    }


def test_benchmark_metrics_require_at_least_two_finite_positive_closes():
    invalid_rows = [
        {"symbol": "SPY", "timestamp": AS_OF, "close": float("nan")},
        {"symbol": "SPY", "timestamp": DECISION, "close": 0.0},
        {
            "symbol": "SPY",
            "timestamp": datetime(2026, 1, 1, 0, 2, tzinfo=UTC),
            "close": 200.0,
        },
    ]

    with pytest.raises(ValueError, match="insufficient_finite_benchmark_closes:SPY"):
        benchmark_metrics_for_rows(invalid_rows, symbol="SPY")


def test_run_evaluation_reports_benchmark_metric_failure_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    candidate = write_candidate(tmp_path)
    config_path = candidate / "evaluation.toml"
    config_path.write_text(
        config_path.read_text().replace('symbols = ["BTC-PERP"]', 'symbols = ["BTC-PERP", "SPY"]')
        + """

[benchmark]
symbol = "SPY"
"""
    )
    events: list[dict[str, object]] = []
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )
    monkeypatch.setattr(
        evaluation_runner,
        "benchmark_metrics_for_rows",
        lambda rows, *, symbol: (_ for _ in ()).throw(
            ValueError("missing_finite_benchmark_close:SPY")
        ),
    )

    result = run_evaluation(
        candidate / "evaluation.toml",
        repo_root=tmp_path,
        backend=FakeBackend(),
        event_sink=events.append,
    )

    assert result.run_completed is False
    assert result.failure_stage == "benchmark_metrics"
    assert result.assessment_status == "portfolio_evaluation_failed"
    assert "missing_finite_benchmark_close:SPY" in result.message
    failed_events = [event for event in events if event["status"] == "failed"]
    assert any(event["stage"] == "benchmark_metrics" for event in failed_events)


def test_run_evaluation_records_matching_annualization_cadence_without_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    candidate = write_candidate(tmp_path, annualization=365)
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )
    timestamps = [AS_OF + timedelta(days=index) for index in range(4)]

    result = run_evaluation(
        candidate / "evaluation.toml",
        repo_root=tmp_path,
        backend=CadenceFakeBackend(timestamps),
    )

    assert result.run_completed is True
    assert result.evidence_quality_warnings == ()
    metrics_payload = json.loads((result.result_dir / "evaluation_metrics.json").read_text())
    assert (
        "full-grid periodic portfolio returns"
        in metrics_payload["metric_semantics"]["annualized_return"]["base"]
    )
    cadence = metrics_payload["annualization_cadence"]
    assert cadence["status"] == "ok"
    assert cadence["configured_periods_per_year"] == 365
    assert cadence["observed_median_spacing_seconds"] == pytest.approx(86_400.0)
    assert cadence["implied_periods_per_year"] == pytest.approx(365.2425)
    assert cadence["warning"] is None
    assert metrics_payload["evidence_quality_warnings"] == []
    for item in metrics_payload["scenarios"]:
        for name in ANNUALIZED_RISK_METRICS:
            assert item["metrics"][name] is not None
        assert item["metrics"]["worst_period_return"] == pytest.approx(-0.005)
        assert "annualized_metrics_null_due_to_cadence_mismatch" not in item["warnings"]
    manifest = json.loads((result.result_dir / "evaluation_manifest.json").read_text())
    assert manifest["annualization_cadence"] == cadence
    assert manifest["evaluation"]["evidence_quality_warnings"] == []


def test_run_evaluation_warns_on_252_observed_periods_against_365_configured_annualization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    candidate = write_candidate(tmp_path, annualization=365)
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )
    observed_spacing = timedelta(seconds=365.2425 * 24 * 60 * 60 / 252)
    timestamps = [AS_OF + observed_spacing * index for index in range(4)]

    result = run_evaluation(
        candidate / "evaluation.toml",
        repo_root=tmp_path,
        backend=CadenceFakeBackend(timestamps),
    )

    assert result.run_completed is True
    assert len(result.evidence_quality_warnings) == 1
    assert result.evidence_quality_warnings[0].startswith("annualization_cadence_mismatch:")
    metrics_payload = json.loads((result.result_dir / "evaluation_metrics.json").read_text())
    cadence = metrics_payload["annualization_cadence"]
    assert cadence["status"] == "warning"
    assert cadence["configured_periods_per_year"] == 365
    assert cadence["implied_periods_per_year"] == pytest.approx(252.0)
    assert cadence["mismatch_factor"] == pytest.approx(365 / 252)


def test_run_evaluation_warns_on_obvious_annualization_cadence_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    candidate = write_candidate(tmp_path, annualization=365)
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )
    timestamps = [AS_OF + timedelta(minutes=index) for index in range(4)]

    result = run_evaluation(
        candidate / "evaluation.toml",
        repo_root=tmp_path,
        backend=CadenceFakeBackend(timestamps),
    )

    assert result.run_completed is True
    assert len(result.evidence_quality_warnings) == 1
    assert result.evidence_quality_warnings[0].startswith("annualization_cadence_mismatch:")
    metrics_payload = json.loads((result.result_dir / "evaluation_metrics.json").read_text())
    cadence = metrics_payload["annualization_cadence"]
    assert cadence["status"] == "warning"
    assert cadence["configured_periods_per_year"] == 365
    assert cadence["observed_median_spacing_seconds"] == pytest.approx(60.0)
    assert cadence["implied_periods_per_year"] == pytest.approx(525_949.2)
    assert cadence["mismatch_factor"] > 1000.0
    assert cadence["warning"] == result.evidence_quality_warnings[0]
    assert metrics_payload["evidence_quality_warnings"] == list(result.evidence_quality_warnings)
    for item in metrics_payload["scenarios"]:
        metrics = item["metrics"]
        for name in ANNUALIZED_RISK_METRICS:
            assert metrics[name] is None
        assert metrics["total_return"] == pytest.approx(0.01)
        assert metrics["ending_value"] == pytest.approx(101.0)
        assert metrics["max_drawdown"] == pytest.approx(-0.01)
        assert metrics["return_sample_count"] == 1
        assert metrics["return_total_count_excluding_initial"] == 1
        assert metrics["worst_period_return"] == pytest.approx(-0.005)
        assert "annualized_metrics_null_due_to_cadence_mismatch" in item["warnings"]
    manifest = json.loads((result.result_dir / "evaluation_manifest.json").read_text())
    assert manifest["annualization_cadence"] == cadence
    assert manifest["evaluation"]["evidence_quality_warnings"] == list(
        result.evidence_quality_warnings
    )


def test_run_evaluation_nulls_annualized_metrics_when_cadence_is_insufficient(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    candidate = write_candidate(tmp_path, annualization=365)
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )

    result = run_evaluation(
        candidate / "evaluation.toml",
        repo_root=tmp_path,
        backend=FakeBackend(),
    )

    assert result.run_completed is True
    assert result.evidence_quality_warnings == (
        "annualization_cadence_insufficient:spacing_observation_count=0:"
        "insufficient_scenario_ids=eval_2026_h1/realistic_costs/base_fill,"
        "eval_2026_h1/realistic_costs/fill_lag_plus_1,"
        "eval_2026_h1/stressed_costs/base_fill,"
        "eval_2026_h1/stressed_costs/fill_lag_plus_1,"
        "eval_2026_h1/zero_costs/base_fill,"
        "eval_2026_h1/zero_costs/fill_lag_plus_1",
    )
    metrics_payload = json.loads((result.result_dir / "evaluation_metrics.json").read_text())
    cadence = metrics_payload["annualization_cadence"]
    assert cadence["status"] == "insufficient"
    assert cadence["warning"] == result.evidence_quality_warnings[0]
    assert cadence["insufficient_scenario_ids"] == [
        "eval_2026_h1/realistic_costs/base_fill",
        "eval_2026_h1/realistic_costs/fill_lag_plus_1",
        "eval_2026_h1/stressed_costs/base_fill",
        "eval_2026_h1/stressed_costs/fill_lag_plus_1",
        "eval_2026_h1/zero_costs/base_fill",
        "eval_2026_h1/zero_costs/fill_lag_plus_1",
    ]
    for item in metrics_payload["scenarios"]:
        metrics = item["metrics"]
        for name in ANNUALIZED_RISK_METRICS:
            assert metrics[name] is None
        assert metrics["total_return"] == pytest.approx(0.01)
        assert metrics["ending_value"] == pytest.approx(101.0)
        assert metrics["max_drawdown"] == pytest.approx(-0.01)
        assert metrics["worst_period_return"] == pytest.approx(-0.005)
        assert "annualized_metrics_null_due_to_insufficient_cadence" in item["warnings"]
        assert "annualized_metrics_null_due_to_cadence_mismatch" not in item["warnings"]


def test_run_evaluation_marks_cadence_insufficient_when_any_completed_scenario_has_no_spacing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    candidate = write_candidate(tmp_path, annualization=365)
    (candidate / "evaluation.toml").write_text(
        (candidate / "evaluation.toml").read_text()
        + """

[[scenarios]]
id = "dense"

[[scenarios]]
id = "sparse"
"""
    )
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )

    result = run_evaluation(
        candidate / "evaluation.toml",
        repo_root=tmp_path,
        backend=MixedSparseCadenceFakeBackend(),
    )

    assert result.run_completed is True
    assert len(result.evidence_quality_warnings) == 1
    assert result.evidence_quality_warnings[0].startswith("annualization_cadence_insufficient:")
    metrics_payload = json.loads((result.result_dir / "evaluation_metrics.json").read_text())
    cadence = metrics_payload["annualization_cadence"]
    assert cadence["status"] == "insufficient"
    assert cadence["insufficient_scenario_ids"] == ["eval_2026_h1/sparse"]
    assert cadence["observed_group_count"] == 1
    assert "eval_2026_h1/sparse" in cadence["warning"]
    assert "eval_2026_h1/dense" not in cadence["warning"]
    for item in metrics_payload["scenarios"]:
        for name in ANNUALIZED_RISK_METRICS:
            assert item["metrics"][name] is None
        assert item["metrics"]["total_return"] == pytest.approx(0.01)
        assert item["metrics"]["ending_value"] == pytest.approx(101.0)
        assert item["metrics"]["max_drawdown"] == pytest.approx(-0.01)
        assert item["metrics"]["worst_period_return"] == pytest.approx(-0.005)
        assert "annualized_metrics_null_due_to_insufficient_cadence" in item["warnings"]


def test_run_evaluation_keeps_offending_cadence_ids_when_other_scenarios_are_insufficient(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    candidate = write_candidate(tmp_path, annualization=365)
    (candidate / "evaluation.toml").write_text(
        (candidate / "evaluation.toml").read_text()
        + """

[[scenarios]]
id = "fast"

[[scenarios]]
id = "sparse"
"""
    )
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )

    result = run_evaluation(
        candidate / "evaluation.toml",
        repo_root=tmp_path,
        backend=MixedMismatchAndSparseCadenceFakeBackend(),
    )

    assert result.run_completed is True
    assert len(result.evidence_quality_warnings) == 1
    assert result.evidence_quality_warnings[0].startswith("annualization_cadence_insufficient:")
    metrics_payload = json.loads((result.result_dir / "evaluation_metrics.json").read_text())
    cadence = metrics_payload["annualization_cadence"]
    assert cadence["status"] == "insufficient"
    assert cadence["insufficient_scenario_ids"] == ["eval_2026_h1/sparse"]
    assert cadence["offending_scenario_ids"] == ["eval_2026_h1/fast"]
    assert "eval_2026_h1/sparse" in cadence["warning"]
    assert "eval_2026_h1/fast" not in cadence["warning"]


def test_run_evaluation_warns_when_one_completed_scenario_has_mismatched_cadence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    candidate = write_candidate(tmp_path, annualization=365)
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )

    result = run_evaluation(
        candidate / "evaluation.toml",
        repo_root=tmp_path,
        backend=MixedCadenceFakeBackend(()),
    )

    assert result.run_completed is True
    assert len(result.evidence_quality_warnings) == 1
    metrics_payload = json.loads((result.result_dir / "evaluation_metrics.json").read_text())
    cadence = metrics_payload["annualization_cadence"]
    assert cadence["status"] == "warning"
    assert cadence["offending_scenario_ids"] == ["eval_2026_h1/zero_costs/base_fill"]
    assert cadence["observed_median_spacing_seconds"] == pytest.approx(60.0)
    assert cadence["warning"] == result.evidence_quality_warnings[0]
    for item in metrics_payload["scenarios"]:
        assert item["status"] == "completed"
        for name in ANNUALIZED_RISK_METRICS:
            assert item["metrics"][name] is None
        assert item["metrics"]["total_return"] == pytest.approx(0.01)
        assert "annualized_metrics_null_due_to_cadence_mismatch" in item["warnings"]


def test_run_evaluation_uses_collision_proof_audit_paths_for_window_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    candidate = write_candidate(tmp_path, window_ids=("eval/2026", "eval 2026"))
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )

    result = run_evaluation(
        candidate / "evaluation.toml", repo_root=tmp_path, backend=PreparedFakeBackend()
    )

    assert result.run_completed is True
    assert result.result_dir is not None
    data_manifest = json.loads((result.result_dir / "data_manifest.json").read_text())
    manifest = json.loads((result.result_dir / "evaluation_manifest.json").read_text())
    row_paths = [window["input_rows_artifact"]["path"] for window in data_manifest["windows"]]
    decision_paths = [
        window["decision_records_artifact"]["path"] for window in data_manifest["windows"]
    ]
    assert len(row_paths) == 2
    assert len(decision_paths) == 2
    assert len(set(row_paths)) == 2
    assert len(set(decision_paths)) == 2
    for path in [*row_paths, *decision_paths]:
        assert (result.result_dir / path).exists()
    assert [item["path"] for item in manifest["audit_artifacts"]["input_rows"]] == row_paths
    assert [
        item["path"] for item in manifest["audit_artifacts"]["decision_records"]
    ] == decision_paths
    assert manifest["replayability"]["replayable_from_artifacts"] is True


def test_run_evaluation_resolves_relative_config_path_from_cwd_when_repo_root_omitted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_candidate(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )

    result = run_evaluation("candidate/evaluation.toml", backend=FakeBackend())

    assert result.run_completed is True
    assert result.result_dir is not None
    assert result.result_dir.parent == tmp_path / "candidate" / "evaluation_results" / "demo"


def test_run_evaluation_supports_crypto_perp_funding_through_the_spine_book(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    candidate = write_candidate(
        tmp_path,
        data_kind="crypto_perp_funding",
        extra_config="min_annualized_samples = 2\n",
    )
    events: list[dict[str, object]] = []
    funding_rows = rows()
    funding_rows[3] = {
        **funding_rows[3],
        "funding_timestamp": funding_rows[3]["timestamp"],
        "funding_rate": 0.0003,
        "has_funding_event": True,
    }
    funding_rows = funding_rows + [
        {
            "symbol": "BTC-PERP",
            "timestamp": datetime(2026, 1, 1, 0, 4, tzinfo=UTC),
            "available_at": datetime(2026, 1, 1, 0, 4, tzinfo=UTC),
            "open": 104.0,
            "high": 104.0,
            "low": 104.0,
            "close": 104.0,
            "volume": 1_000.0,
            "vwap": 104.0,
            "num_trades": 100,
            "funding_timestamp": datetime(2026, 1, 1, 0, 4, tzinfo=UTC),
            "funding_rate": 0.0003,
            "has_funding_event": True,
        },
        {
            "symbol": "BTC-PERP",
            "timestamp": datetime(2026, 1, 1, 0, 5, tzinfo=UTC),
            "available_at": datetime(2026, 1, 1, 0, 5, tzinfo=UTC),
            "open": 105.0,
            "high": 105.0,
            "low": 105.0,
            "close": 105.0,
            "volume": 1_000.0,
            "vwap": 105.0,
            "num_trades": 100,
            "funding_timestamp": datetime(2026, 1, 1, 0, 5, tzinfo=UTC),
            "funding_rate": 0.0003,
            "has_funding_event": True,
        },
    ]
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=funding_rows),
    )

    result = run_evaluation(
        candidate / "evaluation.toml",
        repo_root=tmp_path,
        event_sink=events.append,
    )

    assert result.run_completed is True
    assert result.failure_stage is None
    assert result.assessment_status == "evaluation_complete"
    assert result.result_dir is not None
    assert (result.result_dir / "tables" / "funding_cashflows.parquet").exists()
    metrics_payload = json.loads((result.result_dir / "evaluation_metrics.json").read_text())
    # The single shared netted-book model identifies every scenario; the retired
    # per-asset-class perp-ledger name is gone.
    assert {item["metrics"]["funding_model"] for item in metrics_payload["scenarios"]} == {
        SHARED_ACCOUNTING_MODEL
    }
    assert {item["backend"] for item in metrics_payload["scenarios"]} == {SHARED_ACCOUNTING_MODEL}
    assert (
        "project_perp_ledger_v1" not in (result.result_dir / "evaluation_metrics.json").read_text()
    )
    # The held position is charged funding while open; how many of the two funding
    # bars (0:03, 0:04) land after entry depends on the scenario's entry lag, so every
    # scenario sees at least one non-zero funding cashflow.
    for item in metrics_payload["scenarios"]:
        assert item["metrics"]["funding_event_count"] >= 1
        assert item["metrics"]["funding_cashflow_total"] != 0.0
    manifest = json.loads((result.result_dir / "evaluation_manifest.json").read_text())
    assert manifest["evaluation"]["backend"]["name"] == SHARED_ACCOUNTING_MODEL
    assert "funding_cashflows" in {item["artifact_kind"] for item in manifest["tables"]}
    assert not [event for event in events if event["status"] == "failed"]


def test_run_evaluation_allows_crypto_perp_funding_without_active_window_funding_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    candidate = write_candidate(
        tmp_path,
        data_kind="crypto_perp_funding",
        extra_config="min_annualized_samples = 2\n",
    )
    no_event_rows = rows() + [
        {
            "symbol": "BTC-PERP",
            "timestamp": datetime(2026, 1, 1, 0, 4, tzinfo=UTC),
            "available_at": datetime(2026, 1, 1, 0, 4, tzinfo=UTC),
            "open": 104.0,
            "high": 104.0,
            "low": 104.0,
            "close": 104.0,
            "volume": 1_000.0,
            "vwap": 104.0,
            "num_trades": 100,
            "has_funding_event": False,
        },
        {
            "symbol": "BTC-PERP",
            "timestamp": datetime(2026, 1, 1, 0, 5, tzinfo=UTC),
            "available_at": datetime(2026, 1, 1, 0, 5, tzinfo=UTC),
            "open": 105.0,
            "high": 105.0,
            "low": 105.0,
            "close": 105.0,
            "volume": 1_000.0,
            "vwap": 105.0,
            "num_trades": 100,
            "has_funding_event": False,
        },
    ]
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=no_event_rows),
    )

    result = run_evaluation(candidate / "evaluation.toml", repo_root=tmp_path)

    assert result.run_completed is True
    assert result.failure_stage is None
    assert result.result_dir is not None
    metrics_payload = json.loads((result.result_dir / "evaluation_metrics.json").read_text())
    for scenario in metrics_payload["scenarios"]:
        assert scenario["backend"] == SHARED_ACCOUNTING_MODEL
        assert scenario["metrics"]["funding_cashflow_total"] == 0.0
        assert scenario["metrics"]["funding_event_count"] == 0


def test_run_evaluation_requires_validate_params(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    candidate = write_candidate(tmp_path, with_param_validator=False)
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )

    result = run_evaluation(
        candidate / "evaluation.toml", repo_root=tmp_path, backend=FakeBackend()
    )

    assert result.run_completed is False
    assert result.failure_stage == "param_validation"
    assert result.assessment_status == "evaluation_failed"
    assert "param validation failed" in result.message
    assert_failure_artifacts(
        result,
        failure_stage="param_validation",
        assessment_status="evaluation_failed",
        message_fragment="param validation failed",
    )


def test_run_evaluation_fails_on_backend_unsupported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    class UnsupportedBackend(FakeBackend):
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
        ):
            return PortfolioEvaluationResult(
                scenario_id=scenario.scenario_id,
                backend=self.name,
                status="unsupported",
                unsupported_semantics=("non_target_weight_sizing",),
            )

    candidate = write_candidate(tmp_path)
    events: list[dict[str, object]] = []
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )

    result = run_evaluation(
        candidate / "evaluation.toml",
        repo_root=tmp_path,
        backend=UnsupportedBackend(),
        event_sink=events.append,
    )

    assert result.run_completed is False
    assert result.failure_stage == "portfolio_evaluation"
    assert result.assessment_status == "portfolio_evaluation_failed"
    assert "non_target_weight_sizing" in result.message
    assert_failure_artifacts(
        result,
        failure_stage="portfolio_evaluation",
        assessment_status="portfolio_evaluation_failed",
        message_fragment="non_target_weight_sizing",
        unsupported_semantics=("non_target_weight_sizing",),
    )
    failed_events = [event for event in events if event["status"] == "failed"]
    assert any(
        event["event"] == "evaluation_stage"
        and event["stage"] == "portfolio_evaluation"
        and "non_target_weight_sizing" in str(event["error"])
        for event in failed_events
    )


def test_run_evaluation_maps_backend_unavailable_to_public_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    class UnavailableBackend(FakeBackend):
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
        ):
            return PortfolioEvaluationResult(
                scenario_id=scenario.scenario_id,
                backend=self.name,
                status="unavailable",
                warnings=("pandas import failed",),
            )

    candidate = write_candidate(tmp_path)
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )

    result = run_evaluation(
        candidate / "evaluation.toml", repo_root=tmp_path, backend=UnavailableBackend()
    )

    assert result.run_completed is False
    assert result.failure_stage == "portfolio_evaluation"
    assert result.assessment_status == "portfolio_backend_unavailable"
    assert "pandas import failed" in result.message
    assert_failure_artifacts(
        result,
        failure_stage="portfolio_evaluation",
        assessment_status="portfolio_backend_unavailable",
        message_fragment="pandas import failed",
    )


def test_run_evaluation_maps_prepared_backend_dependency_error_to_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    class UnavailablePreparedBackend(FakeBackend):
        def __init__(self) -> None:
            self.prepare_calls = 0
            self.run_prepared_calls = 0

        def prepare_inputs(
            self,
            *,
            decisions: Sequence[Any],
            rows: Sequence[dict[str, Any]],
            data_kind: str = "bars",
            capacity_model: Any = None,
            risk_budget: Any = None,
            leverage_budget: Any = None,
        ) -> dict[str, Any]:
            self.prepare_calls += 1
            raise EvaluationDependencyError("pandas import failed")

        def run_prepared(self, *, prepared: dict[str, Any], scenario: Any, metrics: Any):
            self.run_prepared_calls += 1
            raise AssertionError("run_prepared should not be called after prepare_inputs fails")

    candidate = write_candidate(tmp_path)
    backend = UnavailablePreparedBackend()
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )

    result = run_evaluation(candidate / "evaluation.toml", repo_root=tmp_path, backend=backend)

    assert result.run_completed is False
    assert result.failure_stage == "portfolio_evaluation"
    assert result.assessment_status == "portfolio_backend_unavailable"
    assert result.message == "pandas import failed"
    assert backend.prepare_calls == 1
    assert backend.run_prepared_calls == 0
    assert_failure_artifacts(
        result,
        failure_stage="portfolio_evaluation",
        assessment_status="portfolio_backend_unavailable",
        message_fragment="pandas import failed",
    )


@pytest.mark.parametrize(
    ("exception", "expected_message"),
    [
        (ValueError("bad rows"), "bad rows"),
        (RuntimeError("shape drift"), "portfolio input preparation failed: shape drift"),
    ],
)
def test_run_evaluation_maps_prepare_inputs_failures_to_portfolio_evaluation_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    exception: Exception,
    expected_message: str,
):
    class FailingPrepareBackend(FakeBackend):
        def __init__(self) -> None:
            self.prepare_calls = 0
            self.run_prepared_calls = 0

        def prepare_inputs(
            self,
            *,
            decisions: Sequence[Any],
            rows: Sequence[dict[str, Any]],
            data_kind: str = "bars",
            capacity_model: Any = None,
            risk_budget: Any = None,
            leverage_budget: Any = None,
        ) -> dict[str, Any]:
            self.prepare_calls += 1
            raise exception

        def run_prepared(self, *, prepared: dict[str, Any], scenario: Any, metrics: Any):
            self.run_prepared_calls += 1
            raise AssertionError("run_prepared should not be called after prepare_inputs fails")

    candidate = write_candidate(tmp_path)
    backend = FailingPrepareBackend()
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )

    result = run_evaluation(candidate / "evaluation.toml", repo_root=tmp_path, backend=backend)

    assert result.run_completed is False
    assert result.failure_stage == "portfolio_evaluation"
    assert result.assessment_status == "portfolio_evaluation_failed"
    assert result.message == expected_message
    assert backend.prepare_calls == 1
    assert backend.run_prepared_calls == 0
    assert_failure_artifacts(
        result,
        failure_stage="portfolio_evaluation",
        assessment_status="portfolio_evaluation_failed",
        message_fragment=expected_message,
    )


@pytest.mark.parametrize(
    ("backend_status", "assessment_status", "message_fragment"),
    [
        ("unsupported", "portfolio_evaluation_failed", "non_target_weight_sizing"),
        ("failed", "portfolio_evaluation_failed", "prepared scenario failed"),
        ("unavailable", "portfolio_backend_unavailable", "pandas import failed"),
    ],
)
def test_run_evaluation_maps_run_prepared_failure_statuses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    backend_status: str,
    assessment_status: str,
    message_fragment: str,
):
    class FailingPreparedBackend(PreparedFakeBackend):
        def run_prepared(self, *, prepared: dict[str, Any], scenario: Any, metrics: Any):
            self.run_prepared_scenario_ids.append(scenario.scenario_id)
            return PortfolioEvaluationResult(
                scenario_id=scenario.scenario_id,
                backend=self.name,
                status=backend_status,
                warnings=(message_fragment,) if backend_status != "unsupported" else (),
                unsupported_semantics=(message_fragment,)
                if backend_status == "unsupported"
                else (),
            )

    candidate = write_candidate(tmp_path)
    backend = FailingPreparedBackend()
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )

    result = run_evaluation(candidate / "evaluation.toml", repo_root=tmp_path, backend=backend)

    assert result.run_completed is False
    assert result.failure_stage == "portfolio_evaluation"
    assert result.assessment_status == assessment_status
    assert message_fragment in result.message
    assert len(backend.prepare_calls) == 1
    assert len(backend.run_prepared_scenario_ids) == 1
    assert_failure_artifacts(
        result,
        failure_stage="portfolio_evaluation",
        assessment_status=assessment_status,
        message_fragment=message_fragment,
        unsupported_semantics=(message_fragment,) if backend_status == "unsupported" else (),
    )


def test_run_evaluation_fails_on_completed_scenario_coverage_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    class DuplicateScenarioBackend(FakeBackend):
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
        ):
            result = super().run(decisions=decisions, rows=rows, scenario=scenario, metrics=metrics)
            return result.model_copy(update={"scenario_id": "duplicate_scenario"})

    candidate = write_candidate(tmp_path)
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )

    result = run_evaluation(
        candidate / "evaluation.toml", repo_root=tmp_path, backend=DuplicateScenarioBackend()
    )

    assert result.run_completed is False
    assert result.failure_stage == "portfolio_evaluation"
    assert result.assessment_status == "portfolio_evaluation_failed"
    assert "backend scenario id mismatch" in result.message
    assert "duplicate_scenario" in result.message
    assert result.result_dir is not None
    assert not (result.result_dir / "tables").exists()
    assert not (result.result_dir / "evaluation_manifest.json").exists()
    assert_failure_artifacts(
        result,
        failure_stage="portfolio_evaluation",
        assessment_status="portfolio_evaluation_failed",
        message_fragment="backend scenario id mismatch",
    )


def test_run_evaluation_fails_when_completed_backend_emits_no_trace_tables(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    class MissingTraceTablesBackend(FakeBackend):
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
        ):
            return PortfolioEvaluationResult(
                scenario_id=scenario.scenario_id,
                backend=self.name,
                status="completed",
                metrics=completed_metrics(),
                tables=None,
            )

    candidate = write_candidate(tmp_path)
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )

    result = run_evaluation(
        candidate / "evaluation.toml", repo_root=tmp_path, backend=MissingTraceTablesBackend()
    )

    assert result.run_completed is False
    assert result.failure_stage == "portfolio_evaluation"
    assert result.assessment_status == "portfolio_evaluation_failed"
    assert "no trace tables" in result.message
    assert result.result_dir is not None
    assert not (result.result_dir / "tables").exists()
    assert not (result.result_dir / "evaluation_manifest.json").exists()
    assert_failure_artifacts(
        result,
        failure_stage="portfolio_evaluation",
        assessment_status="portfolio_evaluation_failed",
        message_fragment="no trace tables",
    )


def test_run_evaluation_fails_when_completed_backend_omits_execution_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    class MissingExecutionEventsBackend(FakeBackend):
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
        ):
            result = super().run(decisions=decisions, rows=rows, scenario=scenario, metrics=metrics)
            assert result.tables is not None
            result_tables = result.tables
            return result.model_copy(
                update={
                    "tables": PortfolioTraceTables(
                        portfolio_path=result_tables.portfolio_path,
                        trades=result_tables.trades,
                        target_positions=result_tables.target_positions,
                        target_exposure_summary=result_tables.target_exposure_summary,
                        execution_events=None,
                        funding_cashflows=result_tables.funding_cashflows,
                    )
                }
            )

    candidate = write_candidate(tmp_path)
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )

    result = run_evaluation(
        candidate / "evaluation.toml",
        repo_root=tmp_path,
        backend=MissingExecutionEventsBackend(),
    )

    assert result.run_completed is False
    assert result.failure_stage == "portfolio_evaluation"
    assert result.assessment_status == "portfolio_evaluation_failed"
    assert "missing trace table: execution_events" in result.message
    assert result.result_dir is not None
    assert not (result.result_dir / "tables").exists()
    assert not (result.result_dir / "evaluation_manifest.json").exists()
    assert_failure_artifacts(
        result,
        failure_stage="portfolio_evaluation",
        assessment_status="portfolio_evaluation_failed",
        message_fragment="missing trace table: execution_events",
    )


def test_run_evaluation_fails_when_completed_backend_metrics_are_incomplete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    class IncompleteMetricsBackend(FakeBackend):
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
        ):
            result = super().run(decisions=decisions, rows=rows, scenario=scenario, metrics=metrics)
            return result.model_copy(update={"metrics": {"total_return": 0.01, "trade_count": 1}})

    candidate = write_candidate(tmp_path)
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )

    result = run_evaluation(
        candidate / "evaluation.toml", repo_root=tmp_path, backend=IncompleteMetricsBackend()
    )

    assert result.run_completed is False
    assert result.failure_stage == "portfolio_evaluation"
    assert result.assessment_status == "portfolio_evaluation_failed"
    assert "invalid completed metrics: ending_value" in result.message
    assert result.result_dir is not None
    assert not (result.result_dir / "tables").exists()
    assert not (result.result_dir / "evaluation_manifest.json").exists()
    assert_failure_artifacts(
        result,
        failure_stage="portfolio_evaluation",
        assessment_status="portfolio_evaluation_failed",
        message_fragment="invalid completed metrics: ending_value",
    )


def test_run_evaluation_fails_when_completed_backend_omits_funding_metrics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    class MissingFundingMetricsBackend(FakeBackend):
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
        ):
            result = super().run(decisions=decisions, rows=rows, scenario=scenario, metrics=metrics)
            metrics_without_funding = {
                key: value
                for key, value in completed_metrics().items()
                if not key.startswith("funding_")
            }
            return result.model_copy(update={"metrics": metrics_without_funding})

    candidate = write_candidate(tmp_path)
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )

    result = run_evaluation(
        candidate / "evaluation.toml", repo_root=tmp_path, backend=MissingFundingMetricsBackend()
    )

    assert result.run_completed is False
    assert result.failure_stage == "portfolio_evaluation"
    assert result.assessment_status == "portfolio_evaluation_failed"
    assert "invalid completed metrics: funding_cashflow_total" in result.message
    assert_failure_artifacts(
        result,
        failure_stage="portfolio_evaluation",
        assessment_status="portfolio_evaluation_failed",
        message_fragment="invalid completed metrics: funding_cashflow_total",
    )


def test_run_evaluation_fails_before_portfolio_on_failed_row_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    class BackendShouldNotBeCalled(FakeBackend):
        def __init__(self) -> None:
            self.prepare_calls = 0
            self.run_calls = 0
            self.run_prepared_calls = 0

        def prepare_inputs(
            self,
            *,
            decisions: Sequence[Any],
            rows: Sequence[dict[str, Any]],
            data_kind: str = "bars",
            capacity_model: Any = None,
            risk_budget: Any = None,
            leverage_budget: Any = None,
        ) -> dict[str, Any]:
            self.prepare_calls += 1
            raise AssertionError("prepare_inputs should not be called after row contract failure")

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
        ):
            self.run_calls += 1
            raise AssertionError("run should not be called after row contract failure")

        def run_prepared(self, *, prepared: dict[str, Any], scenario: Any, metrics: Any):
            self.run_prepared_calls += 1
            raise AssertionError("run_prepared should not be called after row contract failure")

    candidate = write_candidate(tmp_path)
    backend = BackendShouldNotBeCalled()
    invalid_rows = [
        {key: value for key, value in row.items() if key != "available_at"} for row in rows()
    ]
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=invalid_rows),
    )

    result = run_evaluation(candidate / "evaluation.toml", repo_root=tmp_path, backend=backend)

    assert result.run_completed is False
    assert result.failure_stage == "data_load"
    assert result.assessment_status == "evaluation_failed"
    assert "row contract failed" in result.message
    assert backend.prepare_calls == 0
    assert backend.run_calls == 0
    assert backend.run_prepared_calls == 0
    assert_failure_artifacts(
        result,
        failure_stage="data_load",
        assessment_status="evaluation_failed",
        message_fragment="row contract failed",
    )


def test_run_evaluation_fails_before_portfolio_on_missing_as_of_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    class BackendShouldNotBeCalled(FakeBackend):
        def __init__(self) -> None:
            self.prepare_calls = 0
            self.run_calls = 0
            self.run_prepared_calls = 0

        def prepare_inputs(
            self,
            *,
            decisions: Sequence[Any],
            rows: Sequence[dict[str, Any]],
            data_kind: str = "bars",
            capacity_model: Any = None,
            risk_budget: Any = None,
            leverage_budget: Any = None,
        ) -> dict[str, Any]:
            self.prepare_calls += 1
            raise AssertionError("prepare_inputs should not be called after data audit failure")

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
        ):
            self.run_calls += 1
            raise AssertionError("run should not be called after data audit failure")

        def run_prepared(self, *, prepared: dict[str, Any], scenario: Any, metrics: Any):
            self.run_prepared_calls += 1
            raise AssertionError("run_prepared should not be called after data audit failure")

    candidate = write_candidate(tmp_path)
    (candidate / "strategy.py").write_text(
        "from datetime import timedelta\n"
        "from quant_strategies.decisions import InstrumentRef, TargetDecision\n"
        "def validate_params(params):\n"
        "    return dict(params)\n"
        "def generate_decisions(rows, params):\n"
        "    if len(rows) < 2:\n"
        "        return []\n"
        "    return [TargetDecision(\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='crypto_perp', symbol='BTC-PERP'),\n"
        "        decision_time=rows[1]['timestamp'],\n"
        "        as_of_time=rows[0]['timestamp'] - timedelta(minutes=1),\n"
        "        target=0.25,\n"
        "    )]\n"
    )
    backend = BackendShouldNotBeCalled()
    events: list[dict[str, object]] = []
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )

    result = run_evaluation(
        candidate / "evaluation.toml",
        repo_root=tmp_path,
        backend=backend,
        event_sink=events.append,
    )

    assert result.run_completed is False
    assert result.failure_stage == "data_audit"
    assert result.assessment_status == "evaluation_preflight_failed"
    assert "missing as_of row for BTC-PERP" in result.message
    assert backend.prepare_calls == 0
    assert backend.run_calls == 0
    assert backend.run_prepared_calls == 0
    payload = assert_failure_artifacts(
        result,
        failure_stage="data_audit",
        assessment_status="evaluation_preflight_failed",
        message_fragment="missing as_of row for BTC-PERP",
    )
    data_window = payload["data_windows"][0]
    assert data_window["window_id"] == "eval_2026_h1"
    assert data_window["row_count"] == 4
    assert data_window["decision_count"] == 1
    assert data_window["data_audit"]["passed"] is False
    assert any(
        "missing as_of row for BTC-PERP" in item for item in data_window["data_audit"]["violations"]
    )
    failed_events = [event for event in events if event["status"] == "failed"]
    assert any(event["stage"] == "data_audit" for event in failed_events)
    assert not any(event["stage"] == "causality_check" for event in events)
    assert not any(event["stage"] == "portfolio_input_preparation" for event in events)


def test_run_evaluation_fails_before_portfolio_on_late_observation_dependency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    class BackendShouldNotBeCalled(FakeBackend):
        def __init__(self) -> None:
            self.prepare_calls = 0
            self.run_calls = 0

        def prepare_inputs(
            self,
            *,
            decisions: Sequence[Any],
            rows: Sequence[dict[str, Any]],
            data_kind: str = "bars",
            capacity_model: Any = None,
            risk_budget: Any = None,
            leverage_budget: Any = None,
        ) -> dict[str, Any]:
            self.prepare_calls += 1
            raise AssertionError("prepare_inputs should not be called after data audit failure")

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
        ):
            self.run_calls += 1
            raise AssertionError("run should not be called after data audit failure")

    candidate = write_candidate(tmp_path)
    (candidate / "strategy.py").write_text(
        "from quant_strategies.decisions import InstrumentRef, ObservationRef, TargetDecision\n"
        "def validate_params(params):\n"
        "    return dict(params)\n"
        "def generate_decisions(rows, params):\n"
        "    return [TargetDecision(\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='crypto_perp', symbol='BTC-PERP'),\n"
        "        decision_time=rows[1]['timestamp'],\n"
        "        as_of_time=rows[0]['timestamp'],\n"
        "        target=0.25,\n"
        "        observations=(ObservationRef(symbol='ETH-PERP', timestamp=rows[0]['timestamp'], "
        "field='close', source='strategy_input'),),\n"
        "    )]\n"
    )
    eth_row = {
        **rows()[0],
        "symbol": "ETH-PERP",
        "available_at": DECISION + timedelta(minutes=1),
    }
    backend = BackendShouldNotBeCalled()
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=[*rows(), eth_row]),
    )

    result = run_evaluation(candidate / "evaluation.toml", repo_root=tmp_path, backend=backend)

    assert result.run_completed is False
    assert result.failure_stage == "data_audit"
    assert result.assessment_status == "evaluation_preflight_failed"
    assert "observation row ETH-PERP" in result.message
    assert "was available after decision_time" in result.message
    assert backend.prepare_calls == 0
    assert backend.run_calls == 0
    payload = assert_failure_artifacts(
        result,
        failure_stage="data_audit",
        assessment_status="evaluation_preflight_failed",
        message_fragment="observation row ETH-PERP",
    )
    assert payload["data_windows"][0]["row_count"] == 5
    assert payload["data_windows"][0]["decision_count"] == 1
    assert any(
        "was available after decision_time" in item
        for item in payload["data_windows"][0]["data_audit"]["violations"]
    )


def test_run_evaluation_fails_before_portfolio_on_missing_decision_observations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    class BackendShouldNotBeCalled(FakeBackend):
        def __init__(self) -> None:
            self.prepare_calls = 0
            self.run_calls = 0

        def prepare_inputs(
            self,
            *,
            decisions: Sequence[Any],
            rows: Sequence[dict[str, Any]],
            data_kind: str = "bars",
            capacity_model: Any = None,
            risk_budget: Any = None,
            leverage_budget: Any = None,
        ) -> dict[str, Any]:
            self.prepare_calls += 1
            raise AssertionError("prepare_inputs should not be called after readiness failure")

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
        ):
            self.run_calls += 1
            raise AssertionError("run should not be called after readiness failure")

    candidate = write_candidate(tmp_path)
    (candidate / "strategy.py").write_text(
        "from quant_strategies.decisions import InstrumentRef, TargetDecision\n"
        "def validate_params(params):\n"
        "    return dict(params)\n"
        "def generate_decisions(rows, params):\n"
        "    return [TargetDecision(\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='crypto_perp', symbol='BTC-PERP'),\n"
        "        decision_time=rows[1]['timestamp'],\n"
        "        as_of_time=rows[0]['timestamp'],\n"
        "        target=0.25,\n"
        "    )]\n"
    )
    backend = BackendShouldNotBeCalled()
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )

    result = run_evaluation(candidate / "evaluation.toml", repo_root=tmp_path, backend=backend)

    assert result.run_completed is False
    assert result.failure_stage == "data_audit"
    assert result.assessment_status == "evaluation_preflight_failed"
    assert "requires at least 1" in result.message
    assert backend.prepare_calls == 0
    assert backend.run_calls == 0
    payload = assert_failure_artifacts(
        result,
        failure_stage="data_audit",
        assessment_status="evaluation_preflight_failed",
        message_fragment="requires at least 1",
    )
    assert payload["data_windows"][0]["data_audit"]["passed"] is False
    assert any(
        "requires at least 1" in item
        for item in payload["data_windows"][0]["data_audit"]["violations"]
    )


def test_run_evaluation_fails_on_incomplete_strict_causality_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    class BackendShouldNotBeCalled(FakeBackend):
        def __init__(self) -> None:
            self.prepare_calls = 0
            self.run_calls = 0
            self.run_prepared_calls = 0

        def prepare_inputs(
            self,
            *,
            decisions: Sequence[Any],
            rows: Sequence[dict[str, Any]],
            data_kind: str = "bars",
            capacity_model: Any = None,
            risk_budget: Any = None,
            leverage_budget: Any = None,
        ) -> dict[str, Any]:
            self.prepare_calls += 1
            raise AssertionError(
                "prepare_inputs should not be called after causality preflight failure"
            )

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
        ):
            self.run_calls += 1
            raise AssertionError("run should not be called after causality preflight failure")

        def run_prepared(self, *, prepared: dict[str, Any], scenario: Any, metrics: Any):
            self.run_prepared_calls += 1
            raise AssertionError(
                "run_prepared should not be called after causality preflight failure"
            )

    candidate = write_candidate(tmp_path)
    (candidate / "strategy.py").write_text(
        "def validate_params(params):\n"
        "    return dict(params)\n"
        "def generate_decisions(rows, params):\n"
        "    if not any(row['timestamp'].isoformat() == '2026-01-01T00:02:00+00:00' for row in rows):\n"
        "        raise RuntimeError('prefix too short')\n"
        "    return []\n"
    )
    backend = BackendShouldNotBeCalled()
    events: list[dict[str, object]] = []
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )

    result = run_evaluation(
        candidate / "evaluation.toml",
        repo_root=tmp_path,
        backend=backend,
        event_sink=events.append,
    )

    assert result.run_completed is False
    assert result.failure_stage == "preflight"
    assert result.assessment_status == "evaluation_preflight_failed"
    assert "strict_suppression_replay_not_verified" in result.message
    assert result.result_dir is not None
    assert not (result.result_dir / "evaluation_manifest.json").exists()
    assert backend.prepare_calls == 0
    assert backend.run_calls == 0
    assert backend.run_prepared_calls == 0
    assert "RuntimeError: prefix too short" in result.evidence_quality_warnings
    payload = assert_failure_artifacts(
        result,
        failure_stage="preflight",
        assessment_status="evaluation_preflight_failed",
        message_fragment="strict_suppression_replay_not_verified",
    )
    assert "RuntimeError: prefix too short" in payload["evidence_quality_warnings"]
    failed_events = [event for event in events if event["status"] == "failed"]
    assert any(
        event["event"] == "evaluation_stage"
        and event["stage"] == "causality_check"
        and "strict_suppression_replay_not_verified" in str(event["error"])
        for event in failed_events
    )
    assert not any(event["stage"] == "portfolio_input_preparation" for event in events)


def test_run_evaluation_fails_before_strategy_on_empty_row_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    class BackendShouldNotBeCalled(FakeBackend):
        def prepare_inputs(
            self,
            *,
            decisions: Sequence[Any],
            rows: Sequence[dict[str, Any]],
            data_kind: str = "bars",
            capacity_model: Any = None,
            risk_budget: Any = None,
            leverage_budget: Any = None,
        ) -> dict[str, Any]:
            raise AssertionError("prepare_inputs should not be called after empty row contract")

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
        ):
            raise AssertionError("run should not be called after empty row contract")

    candidate = write_candidate(tmp_path)
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=[]),
    )

    result = run_evaluation(
        candidate / "evaluation.toml", repo_root=tmp_path, backend=BackendShouldNotBeCalled()
    )

    assert result.run_completed is False
    assert result.failure_stage == "data_load"
    assert result.assessment_status == "evaluation_failed"
    assert "row_contract_not_evaluated:no_rows" in result.message
    assert_failure_artifacts(
        result,
        failure_stage="data_load",
        assessment_status="evaluation_failed",
        message_fragment="row_contract_not_evaluated:no_rows",
    )


def test_run_evaluation_does_not_publish_partial_tables_when_a_late_scenario_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    class LateFailureBackend(FakeBackend):
        def __init__(self) -> None:
            self.calls = 0

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
        ):
            self.calls += 1
            if self.calls == 6:
                return PortfolioEvaluationResult(
                    scenario_id=scenario.scenario_id,
                    backend=self.name,
                    status="failed",
                    warnings=("late scenario failed",),
                )
            return super().run(decisions=decisions, rows=rows, scenario=scenario, metrics=metrics)

    candidate = write_candidate(tmp_path)
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )

    result = run_evaluation(
        candidate / "evaluation.toml", repo_root=tmp_path, backend=LateFailureBackend()
    )

    assert result.run_completed is False
    assert result.failure_stage == "portfolio_evaluation"
    assert result.assessment_status == "portfolio_evaluation_failed"
    assert "late scenario failed" in result.message
    assert result.result_dir is not None
    assert not (result.result_dir / "tables").exists()
    assert not (result.result_dir / "evaluation_manifest.json").exists()
    assert_failure_artifacts(
        result,
        failure_stage="portfolio_evaluation",
        assessment_status="portfolio_evaluation_failed",
        message_fragment="late scenario failed",
    )


def test_run_evaluation_removes_staged_tables_when_final_parquet_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    candidate = write_candidate(tmp_path)
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )

    real_write = evaluation_runner.write_parquet_artifact
    calls = 0

    def failing_write(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 5:
            raise TypeError("arrow conversion failed")
        return real_write(*args, **kwargs)

    monkeypatch.setattr(evaluation_runner, "write_parquet_artifact", failing_write)

    result = run_evaluation(
        candidate / "evaluation.toml", repo_root=tmp_path, backend=FakeBackend()
    )

    assert result.run_completed is False
    assert result.failure_stage == "artifact_write"
    assert result.assessment_status == "evaluation_failed"
    assert "arrow conversion failed" in result.message
    assert result.result_dir is not None
    assert not (result.result_dir / "tables").exists()
    assert not (result.result_dir / "tables_staging").exists()
    assert_failure_artifacts(
        result,
        failure_stage="artifact_write",
        assessment_status="evaluation_failed",
        message_fragment="arrow conversion failed",
    )


def test_run_evaluation_failure_artifacts_include_window_when_audit_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    candidate = write_candidate(tmp_path)
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )

    def failing_input_rows(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise OSError("audit rows failed")

    monkeypatch.setattr(evaluation_runner, "write_input_rows_artifact", failing_input_rows)

    result = run_evaluation(
        candidate / "evaluation.toml", repo_root=tmp_path, backend=FakeBackend()
    )

    assert result.run_completed is False
    assert result.failure_stage == "artifact_write"
    assert result.assessment_status == "evaluation_failed"
    payload = assert_failure_artifacts(
        result,
        failure_stage="artifact_write",
        assessment_status="evaluation_failed",
        message_fragment="audit rows failed",
    )
    assert payload["data_windows"][0]["window_id"] == "eval_2026_h1"
    assert payload["data_windows"][0]["row_count"] == 4
    assert payload["data_windows"][0]["decision_count"] == 1
    assert "input_rows_artifact" not in payload["data_windows"][0]


def test_run_evaluation_reports_failure_artifact_write_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    class FailingBackend(FakeBackend):
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
        ):
            return PortfolioEvaluationResult(
                scenario_id=scenario.scenario_id,
                backend=self.name,
                status="failed",
                warnings=("backend failed",),
            )

    candidate = write_candidate(tmp_path)
    events: list[dict[str, object]] = []
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )

    def failing_failure_json(*args: Any, **kwargs: Any) -> None:
        raise OSError("failure artifact disk full")

    monkeypatch.setattr(evaluation_runner, "write_json_artifact", failing_failure_json)

    result = run_evaluation(
        candidate / "evaluation.toml",
        repo_root=tmp_path,
        backend=FailingBackend(),
        event_sink=events.append,
    )

    assert result.run_completed is False
    assert result.failure_stage == "portfolio_evaluation"
    assert result.assessment_status == "portfolio_evaluation_failed"
    assert "backend failed" in result.message
    assert (
        "evaluation_failure_artifact_write_failed: OSError: failure artifact disk full"
        in result.evidence_quality_warnings
    )
    assert result.result_dir is not None
    assert not (result.result_dir / "evaluation_failure.json").exists()
    assert any(
        event["event"] == "evaluation_stage"
        and event["stage"] == "failure_artifact_writes"
        and event["status"] == "failed"
        and "failure artifact disk full" in str(event["error"])
        for event in events
    )


def test_run_evaluation_rejects_mismatched_audit_artifact_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    candidate = write_candidate(tmp_path)
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )
    real_write = evaluation_runner.write_decision_records_artifact

    def bad_decision_records(*args: Any, **kwargs: Any) -> dict[str, Any]:
        metadata = real_write(*args, **kwargs)
        metadata["sha256"] = "0" * 64
        return metadata

    monkeypatch.setattr(evaluation_runner, "write_decision_records_artifact", bad_decision_records)

    result = run_evaluation(
        candidate / "evaluation.toml", repo_root=tmp_path, backend=FakeBackend()
    )

    assert result.run_completed is False
    assert result.failure_stage == "artifact_write"
    assert result.assessment_status == "evaluation_failed"
    assert result.result_dir is not None
    assert not (result.result_dir / "evaluation_manifest.json").exists()
    assert_failure_artifacts(
        result,
        failure_stage="artifact_write",
        assessment_status="evaluation_failed",
        message_fragment="decision_records audit artifact sha256 does not match file",
    )


def test_run_evaluation_rejects_audit_artifact_bound_to_wrong_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    candidate = write_candidate(tmp_path)
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )
    real_write = evaluation_runner.write_input_rows_artifact

    def wrong_window_input_rows(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return real_write(*args, **{**kwargs, "window_id": "other_window"})

    monkeypatch.setattr(evaluation_runner, "write_input_rows_artifact", wrong_window_input_rows)

    result = run_evaluation(
        candidate / "evaluation.toml", repo_root=tmp_path, backend=FakeBackend()
    )

    assert result.run_completed is False
    assert result.failure_stage == "artifact_write"
    assert result.assessment_status == "evaluation_failed"
    assert_failure_artifacts(
        result,
        failure_stage="artifact_write",
        assessment_status="evaluation_failed",
        message_fragment="input_rows audit artifact path does not match data window",
    )


def test_run_evaluation_rejects_audit_row_count_not_bound_to_data_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    candidate = write_candidate(tmp_path)
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )
    real_write = evaluation_runner.write_input_rows_artifact

    def truncated_input_rows(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return real_write(*args, **{**kwargs, "rows": rows()[:1]})

    monkeypatch.setattr(evaluation_runner, "write_input_rows_artifact", truncated_input_rows)

    result = run_evaluation(
        candidate / "evaluation.toml", repo_root=tmp_path, backend=FakeBackend()
    )

    assert result.run_completed is False
    assert result.failure_stage == "artifact_write"
    assert result.assessment_status == "evaluation_failed"
    assert_failure_artifacts(
        result,
        failure_stage="artifact_write",
        assessment_status="evaluation_failed",
        message_fragment="input_rows audit artifact row_count does not match data window row_count",
    )


def test_run_evaluation_rejects_audit_decision_count_not_bound_to_data_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    candidate = write_candidate(tmp_path)
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )
    real_write = evaluation_runner.write_decision_records_artifact

    def empty_decision_records(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return real_write(*args, **{**kwargs, "decisions": []})

    monkeypatch.setattr(
        evaluation_runner, "write_decision_records_artifact", empty_decision_records
    )

    result = run_evaluation(
        candidate / "evaluation.toml", repo_root=tmp_path, backend=FakeBackend()
    )

    assert result.run_completed is False
    assert result.failure_stage == "artifact_write"
    assert result.assessment_status == "evaluation_failed"
    assert_failure_artifacts(
        result,
        failure_stage="artifact_write",
        assessment_status="evaluation_failed",
        message_fragment="decision_records audit artifact row_count does not match data window decision_count",
    )


def test_run_evaluation_uses_staged_write_table_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    candidate = write_candidate(tmp_path)
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )

    result = run_evaluation(
        candidate / "evaluation.toml", repo_root=tmp_path, backend=FakeBackend()
    )

    assert result.run_completed is True
    assert result.failure_stage is None
    assert result.result_dir is not None
    assert (result.result_dir / "tables" / "portfolio_path.parquet").exists()
    manifest = json.loads((result.result_dir / "evaluation_manifest.json").read_text())
    assert [item["artifact_kind"] for item in manifest["tables"]] == [
        "portfolio_path",
        "trades",
        "target_positions",
        "target_exposure_summary",
        "execution_events",
        "funding_cashflows",
    ]


def test_run_evaluation_removes_published_tables_when_manifest_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    candidate = write_candidate(tmp_path)
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )

    def failing_manifest(*args: Any, **kwargs: Any) -> None:
        raise OSError("manifest failed")

    monkeypatch.setattr(evaluation_runner, "write_evaluation_manifest", failing_manifest)

    result = run_evaluation(
        candidate / "evaluation.toml", repo_root=tmp_path, backend=FakeBackend()
    )

    assert result.run_completed is False
    assert result.failure_stage == "artifact_write"
    assert result.assessment_status == "evaluation_failed"
    assert "manifest failed" in result.message
    assert result.result_dir is not None
    assert not (result.result_dir / "evaluation_manifest.json").exists()
    assert not (result.result_dir / "tables").exists()
    assert not (result.result_dir / "tables_staging").exists()
    assert_failure_artifacts(
        result,
        failure_stage="artifact_write",
        assessment_status="evaluation_failed",
        message_fragment="manifest failed",
    )
