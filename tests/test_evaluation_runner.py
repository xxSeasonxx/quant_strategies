from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

import quant_strategies.evaluation.runner as evaluation_runner
from quant_strategies.evaluation.backend import PortfolioEvaluationResult, PortfolioTraceTables
from quant_strategies.evaluation.dependencies import EvaluationDependencyError
from quant_strategies.evaluation.runner import run_evaluation
from quant_strategies.runner.data_loader import LoadedData


AS_OF = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
DECISION = datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc)


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
            "has_funding_event": False,
        },
        {
            "symbol": "BTC-PERP",
            "timestamp": datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc),
            "available_at": datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc),
            "open": 102.0,
            "high": 102.0,
            "low": 102.0,
            "close": 102.0,
            "has_funding_event": False,
        },
        {
            "symbol": "BTC-PERP",
            "timestamp": datetime(2026, 1, 1, 0, 3, tzinfo=timezone.utc),
            "available_at": datetime(2026, 1, 1, 0, 3, tzinfo=timezone.utc),
            "open": 103.0,
            "high": 103.0,
            "low": 103.0,
            "close": 103.0,
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


def write_candidate(tmp_path: Path, *, with_param_validator: bool = True) -> Path:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    validator = "def validate_params(params):\n    return dict(params)\n" if with_param_validator else ""
    (candidate / "strategy.py").write_text(
        "from quant_strategies.decisions import ExitPolicy, InstrumentRef, ObservationRef, "
        "PositionTarget, StrategyDecision\n"
        f"{validator}"
        "def generate_decisions(rows, params):\n"
        "    return [StrategyDecision(\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='crypto_perp', symbol='BTC-PERP'),\n"
        "        decision_time=rows[1]['timestamp'],\n"
        "        as_of_time=rows[1]['timestamp'],\n"
        "        target=PositionTarget(direction='long', sizing_kind='target_weight', size=0.25),\n"
        "        exit_policy=ExitPolicy(max_hold_bars=1),\n"
        "        observations=(ObservationRef(symbol='BTC-PERP', timestamp=rows[1]['timestamp'], "
        "field='close', source='strategy_input'),),\n"
        "    )]\n"
    )
    (candidate / "evaluation.toml").write_text(
        '''
strategy_path = "strategy.py"
strategy_id = "demo"

[[windows]]
id = "eval_2026_h1"
start = "2026-01-01"
end = "2026-06-30"

[data]
kind = "crypto_perp_funding"
symbols = ["BTC-PERP"]
strict = true
start = "2026-01-01"
end = "2026-06-30"

[params]
weight = 0.25

[fill_model]
price = "close"
entry_lag_bars = 1
exit_lag_bars = 0

[cost_model]
fee_bps_per_side = 0.5
slippage_bps_per_side = 0.5

[metrics]
annualization_periods_per_year = 365

[output]
results_dir = "evaluation_results/demo"
'''.lstrip()
    )
    return candidate


class FakeBackend:
    name = "fake_evaluation"

    def run(self, *, decisions: Sequence[Any], rows: Sequence[dict[str, Any]], scenario: Any, metrics: Any):
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
            positions=pd.DataFrame({"scenario_id": [scenario.scenario_id], "asset": ["BTC-PERP"], "weight": [0.25]}),
            per_asset_metrics=pd.DataFrame(
                {"scenario_id": [scenario.scenario_id], "asset": ["BTC-PERP"], "trade_count": [1]}
            ),
        )
        return PortfolioEvaluationResult(
            scenario_id=scenario.scenario_id,
            backend=self.name,
            status="completed",
            metrics={"total_return": 0.01, "trade_count": 1},
            tables=tables,
        )


class PreparedFakeBackend(FakeBackend):
    def __init__(self) -> None:
        self.prepare_calls: list[tuple[Sequence[Any], Sequence[dict[str, Any]]]] = []
        self.run_prepared_scenario_ids: list[str] = []

    def prepare_inputs(self, *, decisions: Sequence[Any], rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
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


def test_run_evaluation_writes_evidence_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    candidate = write_candidate(tmp_path)
    backend = PreparedFakeBackend()
    monkeypatch.setattr(
        "quant_strategies.runner.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=messy_raw_rows()),
    )

    result = run_evaluation(candidate / "evaluation.toml", repo_root=tmp_path, backend=backend)

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
    assert (result.result_dir / "tables" / "portfolio_path.parquet").exists()
    assert (result.result_dir / "tables" / "trades.parquet").exists()
    assert (result.result_dir / "tables" / "positions.parquet").exists()
    assert (result.result_dir / "tables" / "per_asset_metrics.parquet").exists()
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
    assert data_manifest["windows"][0]["row_contract"]["mode"] == "validation"
    assert data_manifest["windows"][0]["decision_count"] == 1
    manifest = json.loads((result.result_dir / "evaluation_manifest.json").read_text())
    assert manifest["evaluation"]["evidence_class"] == "research_evaluation"
    assert manifest["evaluation"]["not_authority"] == "not validation, promotion, paper trading, or live trading authority"
    assert len(manifest["tables"]) == 4
    assert {item["artifact_kind"] for item in manifest["tables"]} == {
        "portfolio_path",
        "trades",
        "positions",
        "per_asset_metrics",
    }
    assert {item["path"] for item in manifest["tables"]} == {
        "tables/portfolio_path.parquet",
        "tables/trades.parquet",
        "tables/positions.parquet",
        "tables/per_asset_metrics.parquet",
    }
    assert all(len(item["scenario_ids"]) == 6 for item in manifest["tables"])
    assert manifest["scenario_coverage"]["expected_count"] == 6
    assert manifest["scenario_coverage"]["completed_count"] == 6
    assert manifest["scenario_coverage"]["expected_ids"] == manifest["scenario_coverage"]["completed_ids"]
    assert manifest["scenario_coverage"]["missing_ids"] == []
    assert manifest["scenario_coverage"]["unexpected_ids"] == []


def test_run_evaluation_requires_validate_params(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    candidate = write_candidate(tmp_path, with_param_validator=False)
    monkeypatch.setattr("quant_strategies.runner.execution.load_data", lambda config, **_kwargs: LoadedData(rows=rows()))

    result = run_evaluation(candidate / "evaluation.toml", repo_root=tmp_path, backend=FakeBackend())

    assert result.run_completed is False
    assert result.failure_stage == "param_validation"
    assert result.assessment_status == "evaluation_failed"
    assert "param validation failed" in result.message


def test_run_evaluation_fails_on_backend_unsupported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    class UnsupportedBackend(FakeBackend):
        def run(self, *, decisions: Sequence[Any], rows: Sequence[dict[str, Any]], scenario: Any, metrics: Any):
            return PortfolioEvaluationResult(
                scenario_id=scenario.scenario_id,
                backend=self.name,
                status="unsupported",
                unsupported_semantics=("non_target_weight_sizing",),
            )

    candidate = write_candidate(tmp_path)
    monkeypatch.setattr("quant_strategies.runner.execution.load_data", lambda config, **_kwargs: LoadedData(rows=rows()))

    result = run_evaluation(candidate / "evaluation.toml", repo_root=tmp_path, backend=UnsupportedBackend())

    assert result.run_completed is False
    assert result.failure_stage == "portfolio_evaluation"
    assert result.assessment_status == "portfolio_evaluation_failed"
    assert "non_target_weight_sizing" in result.message


def test_run_evaluation_maps_backend_unavailable_to_public_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    class UnavailableBackend(FakeBackend):
        def run(self, *, decisions: Sequence[Any], rows: Sequence[dict[str, Any]], scenario: Any, metrics: Any):
            return PortfolioEvaluationResult(
                scenario_id=scenario.scenario_id,
                backend=self.name,
                status="unavailable",
                warnings=("vectorbtpro import failed",),
            )

    candidate = write_candidate(tmp_path)
    monkeypatch.setattr("quant_strategies.runner.execution.load_data", lambda config, **_kwargs: LoadedData(rows=rows()))

    result = run_evaluation(candidate / "evaluation.toml", repo_root=tmp_path, backend=UnavailableBackend())

    assert result.run_completed is False
    assert result.failure_stage == "portfolio_evaluation"
    assert result.assessment_status == "portfolio_backend_unavailable"
    assert "vectorbtpro import failed" in result.message


def test_run_evaluation_maps_prepared_backend_dependency_error_to_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    class UnavailablePreparedBackend(FakeBackend):
        def __init__(self) -> None:
            self.prepare_calls = 0
            self.run_prepared_calls = 0

        def prepare_inputs(self, *, decisions: Sequence[Any], rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
            self.prepare_calls += 1
            raise EvaluationDependencyError("vectorbtpro import failed")

        def run_prepared(self, *, prepared: dict[str, Any], scenario: Any, metrics: Any):
            self.run_prepared_calls += 1
            raise AssertionError("run_prepared should not be called after prepare_inputs fails")

    candidate = write_candidate(tmp_path)
    backend = UnavailablePreparedBackend()
    monkeypatch.setattr("quant_strategies.runner.execution.load_data", lambda config, **_kwargs: LoadedData(rows=rows()))

    result = run_evaluation(candidate / "evaluation.toml", repo_root=tmp_path, backend=backend)

    assert result.run_completed is False
    assert result.failure_stage == "portfolio_evaluation"
    assert result.assessment_status == "portfolio_backend_unavailable"
    assert result.message == "vectorbtpro import failed"
    assert backend.prepare_calls == 1
    assert backend.run_prepared_calls == 0


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

        def prepare_inputs(self, *, decisions: Sequence[Any], rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
            self.prepare_calls += 1
            raise exception

        def run_prepared(self, *, prepared: dict[str, Any], scenario: Any, metrics: Any):
            self.run_prepared_calls += 1
            raise AssertionError("run_prepared should not be called after prepare_inputs fails")

    candidate = write_candidate(tmp_path)
    backend = FailingPrepareBackend()
    monkeypatch.setattr("quant_strategies.runner.execution.load_data", lambda config, **_kwargs: LoadedData(rows=rows()))

    result = run_evaluation(candidate / "evaluation.toml", repo_root=tmp_path, backend=backend)

    assert result.run_completed is False
    assert result.failure_stage == "portfolio_evaluation"
    assert result.assessment_status == "portfolio_evaluation_failed"
    assert result.message == expected_message
    assert backend.prepare_calls == 1
    assert backend.run_prepared_calls == 0


@pytest.mark.parametrize(
    ("backend_status", "assessment_status", "message_fragment"),
    [
        ("unsupported", "portfolio_evaluation_failed", "non_target_weight_sizing"),
        ("failed", "portfolio_evaluation_failed", "prepared scenario failed"),
        ("unavailable", "portfolio_backend_unavailable", "vectorbtpro import failed"),
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
                unsupported_semantics=(message_fragment,) if backend_status == "unsupported" else (),
            )

    candidate = write_candidate(tmp_path)
    backend = FailingPreparedBackend()
    monkeypatch.setattr("quant_strategies.runner.execution.load_data", lambda config, **_kwargs: LoadedData(rows=rows()))

    result = run_evaluation(candidate / "evaluation.toml", repo_root=tmp_path, backend=backend)

    assert result.run_completed is False
    assert result.failure_stage == "portfolio_evaluation"
    assert result.assessment_status == assessment_status
    assert message_fragment in result.message
    assert len(backend.prepare_calls) == 1
    assert len(backend.run_prepared_scenario_ids) == 1


def test_run_evaluation_fails_on_completed_scenario_coverage_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    class DuplicateScenarioBackend(FakeBackend):
        def run(self, *, decisions: Sequence[Any], rows: Sequence[dict[str, Any]], scenario: Any, metrics: Any):
            result = super().run(decisions=decisions, rows=rows, scenario=scenario, metrics=metrics)
            return result.model_copy(update={"scenario_id": "duplicate_scenario"})

    candidate = write_candidate(tmp_path)
    monkeypatch.setattr("quant_strategies.runner.execution.load_data", lambda config, **_kwargs: LoadedData(rows=rows()))

    result = run_evaluation(candidate / "evaluation.toml", repo_root=tmp_path, backend=DuplicateScenarioBackend())

    assert result.run_completed is False
    assert result.failure_stage == "portfolio_evaluation"
    assert result.assessment_status == "portfolio_evaluation_failed"
    assert "scenario coverage mismatch" in result.message
    assert "duplicate_scenario" in result.message
    assert result.result_dir is not None
    assert not (result.result_dir / "tables").exists()
    assert not (result.result_dir / "evaluation_manifest.json").exists()


def test_run_evaluation_fails_when_completed_backend_emits_no_trace_tables(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    class MissingTraceTablesBackend(FakeBackend):
        def run(self, *, decisions: Sequence[Any], rows: Sequence[dict[str, Any]], scenario: Any, metrics: Any):
            return PortfolioEvaluationResult(
                scenario_id=scenario.scenario_id,
                backend=self.name,
                status="completed",
                metrics={"total_return": 0.01, "trade_count": 1},
                tables=None,
            )

    candidate = write_candidate(tmp_path)
    monkeypatch.setattr("quant_strategies.runner.execution.load_data", lambda config, **_kwargs: LoadedData(rows=rows()))

    result = run_evaluation(candidate / "evaluation.toml", repo_root=tmp_path, backend=MissingTraceTablesBackend())

    assert result.run_completed is False
    assert result.failure_stage == "portfolio_evaluation"
    assert result.assessment_status == "portfolio_evaluation_failed"
    assert "no trace tables" in result.message
    assert result.result_dir is not None
    assert not (result.result_dir / "tables").exists()
    assert not (result.result_dir / "evaluation_manifest.json").exists()


def test_run_evaluation_fails_before_portfolio_on_failed_row_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    class BackendShouldNotBeCalled(FakeBackend):
        def __init__(self) -> None:
            self.prepare_calls = 0
            self.run_calls = 0
            self.run_prepared_calls = 0

        def prepare_inputs(self, *, decisions: Sequence[Any], rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
            self.prepare_calls += 1
            raise AssertionError("prepare_inputs should not be called after row contract failure")

        def run(self, *, decisions: Sequence[Any], rows: Sequence[dict[str, Any]], scenario: Any, metrics: Any):
            self.run_calls += 1
            raise AssertionError("run should not be called after row contract failure")

        def run_prepared(self, *, prepared: dict[str, Any], scenario: Any, metrics: Any):
            self.run_prepared_calls += 1
            raise AssertionError("run_prepared should not be called after row contract failure")

    candidate = write_candidate(tmp_path)
    backend = BackendShouldNotBeCalled()
    invalid_rows = [{key: value for key, value in row.items() if key != "available_at"} for row in rows()]
    monkeypatch.setattr(
        "quant_strategies.runner.execution.load_data",
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


def test_run_evaluation_does_not_publish_partial_tables_when_a_late_scenario_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    class LateFailureBackend(FakeBackend):
        def __init__(self) -> None:
            self.calls = 0

        def run(self, *, decisions: Sequence[Any], rows: Sequence[dict[str, Any]], scenario: Any, metrics: Any):
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
    monkeypatch.setattr("quant_strategies.runner.execution.load_data", lambda config, **_kwargs: LoadedData(rows=rows()))

    result = run_evaluation(candidate / "evaluation.toml", repo_root=tmp_path, backend=LateFailureBackend())

    assert result.run_completed is False
    assert result.failure_stage == "portfolio_evaluation"
    assert result.assessment_status == "portfolio_evaluation_failed"
    assert "late scenario failed" in result.message
    assert result.result_dir is not None
    assert not (result.result_dir / "tables").exists()
    assert not (result.result_dir / "evaluation_manifest.json").exists()


def test_run_evaluation_removes_staged_tables_when_final_parquet_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    candidate = write_candidate(tmp_path)
    monkeypatch.setattr("quant_strategies.runner.execution.load_data", lambda config, **_kwargs: LoadedData(rows=rows()))

    real_write = evaluation_runner.write_parquet_artifact
    calls = 0

    def failing_write(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 4:
            raise OSError("disk full")
        return real_write(*args, **kwargs)

    monkeypatch.setattr(evaluation_runner, "write_parquet_artifact", failing_write)

    result = run_evaluation(candidate / "evaluation.toml", repo_root=tmp_path, backend=FakeBackend())

    assert result.run_completed is False
    assert result.failure_stage == "artifact_write"
    assert result.assessment_status == "evaluation_failed"
    assert "disk full" in result.message
    assert result.result_dir is not None
    assert not (result.result_dir / "tables").exists()
    assert not (result.result_dir / "tables_staging").exists()


def test_run_evaluation_uses_staged_write_table_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    candidate = write_candidate(tmp_path)
    monkeypatch.setattr("quant_strategies.runner.execution.load_data", lambda config, **_kwargs: LoadedData(rows=rows()))

    def forbidden_table_metadata(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise ValueError("runner-level metadata recompute should not run")

    monkeypatch.setattr(evaluation_runner, "table_metadata", forbidden_table_metadata, raising=False)

    result = run_evaluation(candidate / "evaluation.toml", repo_root=tmp_path, backend=FakeBackend())

    assert result.run_completed is True
    assert result.failure_stage is None
    assert result.result_dir is not None
    assert (result.result_dir / "tables" / "portfolio_path.parquet").exists()
    manifest = json.loads((result.result_dir / "evaluation_manifest.json").read_text())
    assert [item["artifact_kind"] for item in manifest["tables"]] == [
        "portfolio_path",
        "trades",
        "positions",
        "per_asset_metrics",
    ]


def test_run_evaluation_removes_published_tables_when_manifest_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    candidate = write_candidate(tmp_path)
    monkeypatch.setattr("quant_strategies.runner.execution.load_data", lambda config, **_kwargs: LoadedData(rows=rows()))

    def failing_manifest(*args: Any, **kwargs: Any) -> None:
        raise OSError("manifest failed")

    monkeypatch.setattr(evaluation_runner, "write_evaluation_manifest", failing_manifest)

    result = run_evaluation(candidate / "evaluation.toml", repo_root=tmp_path, backend=FakeBackend())

    assert result.run_completed is False
    assert result.failure_stage == "artifact_write"
    assert result.assessment_status == "evaluation_failed"
    assert "manifest failed" in result.message
    assert result.result_dir is not None
    assert not (result.result_dir / "evaluation_manifest.json").exists()
    assert not (result.result_dir / "tables").exists()
    assert not (result.result_dir / "tables_staging").exists()
