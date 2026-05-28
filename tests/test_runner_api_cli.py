from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from quant_strategies.data_contract import NormalizedRows
import quant_strategies.runner.artifacts as artifacts
import quant_strategies.runner.execution as execution
from quant_strategies.runner import RunResult, cli, config as config_module, engine_runner, run_config
from quant_strategies.runner.data_loader import LoadedData
from quant_strategies.runner.errors import DataLoadError, EvaluationRunError, RunnerError


SUMMARY_KEYS = {
    "strategy_id",
    "mode",
    "status",
    "stage",
    "failure_stage",
    "message",
    "artifacts",
    "engine",
    "run_completed",
    "assessment_status",
    "artifact_profile",
    "artifact_trust_tier",
    "evidence_class",
    "strategy_contract",
    "return_model",
    "funding_model",
    "metric_semantics",
    "promotion_eligible",
    "paper_trade_eligible",
    "live_eligible",
    "requires_manual_approval",
    "data_availability_status",
    "availability_coverage",
    "row_contract",
    "causality_verified",
    "evidence_quality_warnings",
}
SMOKE_SCORE_KEYS = {
    "smoke_score.sum_signed_trade_activity_gross",
    "smoke_score.sum_signed_trade_activity_funding",
    "smoke_score.sum_signed_trade_activity_cost",
    "smoke_score.sum_signed_trade_activity_net",
}
LEGACY_DISTRIBUTION = "quant" + "-engine"


def rows(
    *closes: float,
    quotes: bool = False,
    research_fields: bool = False,
    readiness_lag: timedelta = timedelta(0),
) -> list[dict[str, object]]:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    result: list[dict[str, object]] = []
    for index, close in enumerate(closes):
        timestamp = start + timedelta(days=index)
        row = {
            "symbol": "SPY" if not quotes else "EURUSD",
            "timestamp": timestamp,
            "open": close,
            "high": close,
            "low": close,
            "close": close,
        }
        if quotes:
            row.update({"bid": close - 0.01, "ask": close + 0.01, "mid": close})
        if research_fields:
            available_at = timestamp + readiness_lag
            row.update(
                {
                    "available_at": available_at,
                    "bar_ingested_at": available_at,
                    "quote_ingested_at": available_at if quotes else None,
                    "joined_refreshed_at": available_at,
                    "funding_timestamp": row["timestamp"] if index == 0 else None,
                    "funding_rate": 0.0001 if index == 0 else None,
                    "funding_ingested_at": available_at if index == 0 else None,
                    "has_funding_event": index == 0,
                    "nullable": None,
                }
            )
        result.append(row)
    return result


def write_strategy(repo_root: Path, *, fixed_quote_signal: bool = False) -> None:
    strategy = repo_root / "tested" / "demo.py"
    strategy.parent.mkdir(parents=True, exist_ok=True)
    if fixed_quote_signal:
        strategy.write_text(
            "from quant_strategies.decisions import ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision\n"
            "def generate_decisions(rows, params):\n"
            "    return [StrategyDecision(\n"
            "        strategy_id='demo',\n"
            "        instrument=InstrumentRef(kind='fx_pair', symbol='EURUSD'),\n"
            "        decision_time=rows[1]['timestamp'],\n"
            "        as_of_time=rows[1]['timestamp'],\n"
            "        target=PositionTarget(direction='long', sizing_kind='target_weight', size=1.0),\n"
            "        exit_policy=ExitPolicy(max_hold_bars=1),\n"
            "    )]\n"
        )
        return
    strategy.write_text(
        "from quant_strategies.decisions import ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision\n"
        "def generate_decisions(rows, params):\n"
        "    return [StrategyDecision(\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='equity_or_etf', symbol=rows[1]['symbol']),\n"
        "        decision_time=rows[1]['timestamp'],\n"
        "        as_of_time=rows[1]['timestamp'],\n"
        "        target=PositionTarget(direction='long', sizing_kind='target_weight', size=1.0),\n"
        "        exit_policy=ExitPolicy(max_hold_bars=1),\n"
        "    )]\n"
    )


def write_config(
    repo_root: Path,
    *,
    relative_path: str = "run.toml",
    kind: str = "bars",
    symbol: str = "SPY",
    dataset: str | None = "equity_1min",
    fill_price: str = "close",
    entry_lag_bars: int = 1,
    allow_same_bar_close_fill: bool = False,
    mode: str = "validate",
    artifact_profile: str = "full",
) -> Path:
    dataset_line = f'dataset = "{dataset}"\n' if dataset is not None else ""
    allow_line = "allow_same_bar_close_fill = true\n" if allow_same_bar_close_fill else ""
    config_path = repo_root / relative_path
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        f'''
strategy_path = "tested/demo.py"
strategy_id = "demo"

[data]
kind = "{kind}"
{dataset_line}symbols = ["{symbol}"]
start = "2024-01-01"
end = "2024-01-05"
strict = true

[params]

[fill_model]
price = "{fill_price}"
entry_lag_bars = {entry_lag_bars}
{allow_line}

[cost_model]
fee_bps_per_side = 0.0
slippage_bps_per_side = 0.0

[output]
results_dir = "results"
mode = "{mode}"
artifact_profile = "{artifact_profile}"
'''.lstrip()
    )
    return config_path


def read_summary(result_dir: Path) -> dict[str, object]:
    summary = json.loads((result_dir / "summary.json").read_text())
    assert set(summary) == SUMMARY_KEYS
    assert all((result_dir / name).exists() for name in summary["artifacts"])
    if summary["stage"] == "completed":
        assert summary["failure_stage"] is None
    else:
        assert summary["failure_stage"] == summary["stage"]
    return summary


def assert_assessment(
    result: RunResult,
    summary: dict[str, object],
    *,
    assessment_status: str,
    run_completed: bool = True,
    promotion_eligible: bool = False,
    artifact_profile: str = "full",
    failure_stage: str | None = None,
) -> None:
    expected_trust = "audit_replayable" if artifact_profile == "full" else "search_only"
    assert result.run_completed is run_completed
    assert result.failure_stage == failure_stage
    assert result.assessment_status == assessment_status
    assert result.promotion_eligible is promotion_eligible
    assert result.artifact_trust_tier == expected_trust
    assert result.data_availability_status == summary["data_availability_status"]
    assert result.availability_coverage == summary["availability_coverage"]
    assert result.row_contract == summary["row_contract"]
    assert result.causality_verified is summary["causality_verified"]
    assert result.evidence_quality_warnings == tuple(summary["evidence_quality_warnings"])
    assert summary["run_completed"] is run_completed
    assert summary["failure_stage"] == failure_stage
    assert summary["assessment_status"] == assessment_status
    assert summary["artifact_profile"] == artifact_profile
    assert summary["artifact_trust_tier"] == expected_trust
    assert summary["evidence_class"] == "runner_smoke"
    assert summary["strategy_contract"] == "decision"
    assert summary["return_model"] == "smoke_score.sum_signed_trade_activity_net"
    assert summary["funding_model"] == "none"
    assert_smoke_metric_semantics(summary)
    assert summary["promotion_eligible"] is promotion_eligible
    assert summary["paper_trade_eligible"] is False
    assert summary["live_eligible"] is False
    assert summary["requires_manual_approval"] is True


def assert_smoke_metric_semantics(payload: dict[str, object]) -> None:
    metric_semantics = payload["metric_semantics"]
    assert set(metric_semantics) == SMOKE_SCORE_KEYS
    for name in SMOKE_SCORE_KEYS:
        semantics = metric_semantics[name]
        assert set(semantics) == {
            "name",
            "unit",
            "base",
            "aggregation",
            "backend",
            "return_path_model",
            "comparability",
            "tolerance",
            "asymmetry",
        }
        assert semantics["name"] == name
        assert semantics["unit"] == "decimal_fraction"
        assert semantics["base"] == "signed target-weighted trade activity; not portfolio NAV"
        assert semantics["backend"] == "smoke_engine"
        assert semantics["comparability"] == "not_comparable_to_nav_path_returns_without_backend_agreement_test"
        assert semantics["tolerance"] is None
        assert semantics["asymmetry"]


def test_run_config_writes_completed_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path)
    monkeypatch.setattr(execution, "load_data", lambda config: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)))

    result = run_config(config_path, repo_root=tmp_path)

    assert not hasattr(result, "success")
    assert result.run_completed is True
    assert result.result_dir is not None
    expected = {
        "config.toml",
        "strategy_snapshot.py",
        "strategy_input_rows.jsonl",
        "decision_records.jsonl",
        "engine_request.json",
        "data_manifest.json",
        "run_manifest.json",
        "summary.json",
        "evidence.json",
        "notes.md",
    }
    assert {path.name for path in result.result_dir.iterdir() if path.is_file()} == expected
    decision_records = (result.result_dir / "decision_records.jsonl").read_text().splitlines()
    assert len(decision_records) == 1
    assert decision_records[0].startswith('{"as_of_time":')
    assert ',"decision_time":' in decision_records[0]
    assert '": ' not in decision_records[0]
    assert json.loads(decision_records[0])["strategy_id"] == "demo"
    summary = read_summary(result.result_dir)
    assert "success" not in summary
    assert summary["stage"] == "completed"
    assert summary["status"] == "passed"
    assert summary["engine"]["passed"] is True
    assert summary["engine"]["trade_count"] == 1
    assert summary["engine"]["smoke_score"]["sum_signed_trade_activity_gross"] > 0
    assert summary["engine"]["smoke_score"]["sum_signed_trade_activity_funding"] == 0.0
    assert summary["engine"]["smoke_score"]["sum_signed_trade_activity_cost"] == 0.0
    assert summary["engine"]["smoke_score"]["sum_signed_trade_activity_net"] > 0
    assert summary["engine"]["gates"][0]["name"] == "valid_inputs"
    assert summary["data_availability_status"] == "missing"
    assert summary["availability_coverage"] == {
        "field": "available_at",
        "present": 0,
        "total": 4,
        "fraction": 0.0,
    }
    assert summary["row_contract"]["status"] == "passed"
    assert summary["row_contract"]["required_fields"] == [
        "symbol",
        "timestamp",
        "open",
        "high",
        "low",
        "close",
    ]
    assert summary["row_contract"]["quant_data_feedback"] == []
    assert summary["causality_verified"] is False
    assert summary["evidence_quality_warnings"] == [
        "available_at_missing",
        "runner_causality_not_verified",
    ]
    data_manifest = json.loads((result.result_dir / "data_manifest.json").read_text())
    assert data_manifest["artifact_trust_tier"] == "audit_replayable"
    assert_smoke_metric_semantics(data_manifest)
    assert data_manifest["data_availability_status"] == summary["data_availability_status"]
    assert data_manifest["availability_coverage"] == summary["availability_coverage"]
    assert data_manifest["row_contract"] == summary["row_contract"]
    assert data_manifest["causality_verified"] is False
    assert data_manifest["evidence_quality_warnings"] == summary["evidence_quality_warnings"]
    assert_assessment(result, summary, assessment_status="smoke_unverified")
    assert "runner smoke evidence only" in (result.result_dir / "notes.md").read_text()


def test_run_config_summary_profile_writes_compact_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path, artifact_profile="summary")
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0, 105.0, 106.0)),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.run_completed is True
    assert result.result_dir is not None
    names = {path.name for path in result.result_dir.iterdir() if path.is_file()}
    assert names == {
        "config.toml",
        "strategy_snapshot.py",
        "data_manifest.json",
        "artifact_profile_summary.json",
        "run_manifest.json",
        "summary.json",
        "notes.md",
    }
    assert "strategy_input_rows.csv" not in names
    assert "strategy_input_rows.jsonl" not in names
    assert "decision_records.jsonl" not in names
    assert "signals.csv" not in names
    assert "engine_request.json" not in names
    assert "evidence.json" not in names

    summary = read_summary(result.result_dir)
    assert_assessment(result, summary, assessment_status="smoke_unverified", artifact_profile="summary")
    assert summary["engine"]["passed"] is True
    assert summary["engine"]["trade_count"] == 1
    assert summary["engine"]["smoke_score"]["sum_signed_trade_activity_gross"] is not None
    assert summary["engine"]["smoke_score"]["sum_signed_trade_activity_funding"] == 0.0
    assert summary["engine"]["smoke_score"]["sum_signed_trade_activity_cost"] == 0.0
    assert summary["engine"]["smoke_score"]["sum_signed_trade_activity_net"] is not None
    assert summary["engine"]["gates"][0]["name"] == "valid_inputs"

    profile = json.loads((result.result_dir / "artifact_profile_summary.json").read_text())
    assert profile["artifact_profile"] == "summary"
    assert profile["artifact_trust_tier"] == "search_only"
    assert profile["rows"]["row_count"] == 6
    assert profile["rows"]["sample_count"] == 5
    assert profile["decisions"]["count"] == 1
    assert "signals" not in profile
    assert profile["engine"]["passed"] is True
    assert profile["engine"]["trade_count"] == 1
    assert profile["engine"]["smoke_score"]["sum_signed_trade_activity_gross"] is not None
    assert profile["engine"]["smoke_score"]["sum_signed_trade_activity_cost"] is not None
    assert profile["engine"]["smoke_score"]["sum_signed_trade_activity_net"] is not None
    assert_smoke_metric_semantics(profile)

    data_manifest = json.loads((result.result_dir / "data_manifest.json").read_text())
    assert data_manifest["artifact_profile"] == "summary"
    assert data_manifest["artifact_trust_tier"] == "search_only"
    assert "strategy_input_rows_jsonl_sha256" not in data_manifest
    assert len(data_manifest["normalized_rows_sha256"]) == 64
    assert profile["rows"]["normalized_rows_sha256"] == data_manifest["normalized_rows_sha256"]
    assert_smoke_metric_semantics(data_manifest)

    run_manifest = json.loads((result.result_dir / "run_manifest.json").read_text())
    assert run_manifest["artifact_profile"] == "summary"
    assert run_manifest["artifact_trust_tier"] == "search_only"
    assert run_manifest["evidence"]["metric_semantics"] == profile["metric_semantics"]
    assert "artifact_profile_summary.json" in run_manifest["artifacts"]
    assert "engine_request.json" not in run_manifest["artifacts"]


def test_summary_profile_does_not_build_full_evidence_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path, artifact_profile="summary")
    monkeypatch.setattr(execution, "load_data", lambda config: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)))
    monkeypatch.setattr(
        engine_runner,
        "evidence_json",
        lambda packet: (_ for _ in ()).throw(AssertionError("summary mode should not serialize evidence")),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.run_completed is True
    assert result.result_dir is not None
    assert not (result.result_dir / "evidence.json").exists()


def test_screen_mode_completion_is_screened_not_validation_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path, mode="screen")
    monkeypatch.setattr(execution, "load_data", lambda config: LoadedData(rows=rows(100.0, 101.0, 90.0, 89.0)))

    result = run_config(config_path, repo_root=tmp_path)

    assert result.run_completed is True
    assert result.result_dir is not None
    summary = read_summary(result.result_dir)
    assert summary["mode"] == "screen"
    assert summary["stage"] == "completed"
    assert summary["status"] == "screened"
    assert summary["engine"]["passed"] is None
    assert summary["engine"]["trade_count"] == 1
    assert summary["engine"]["smoke_score"]["sum_signed_trade_activity_gross"] < 0
    assert summary["engine"]["smoke_score"]["sum_signed_trade_activity_funding"] == 0.0
    assert summary["engine"]["smoke_score"]["sum_signed_trade_activity_cost"] == 0.0
    assert summary["engine"]["smoke_score"]["sum_signed_trade_activity_net"] < 0
    assert_assessment(result, summary, assessment_status="screened")
    notes = (result.result_dir / "notes.md").read_text()
    assert "status: screened" in notes
    assert "status: passed" not in notes
    assert "not validation pass" in notes


def test_screen_mode_empty_decisions_complete_as_zero_trade_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    strategy = tmp_path / "tested" / "demo.py"
    strategy.parent.mkdir(parents=True, exist_ok=True)
    strategy.write_text("def generate_decisions(rows, params):\n    return []\n")
    config_path = write_config(tmp_path, mode="screen")
    monkeypatch.setattr(execution, "load_data", lambda config: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)))

    result = run_config(config_path, repo_root=tmp_path)

    assert result.run_completed is True
    assert result.result_dir is not None
    summary = read_summary(result.result_dir)
    assert summary["mode"] == "screen"
    assert summary["stage"] == "completed"
    assert summary["status"] == "screened"
    assert summary["engine"]["passed"] is None
    assert summary["engine"]["trade_count"] == 0
    assert summary["engine"]["smoke_score"] == {
        "sum_signed_trade_activity_gross": 0.0,
        "sum_signed_trade_activity_funding": 0.0,
        "sum_signed_trade_activity_cost": 0.0,
        "sum_signed_trade_activity_net": 0.0,
    }
    assert_assessment(result, summary, assessment_status="screened")
    request = json.loads((result.result_dir / "engine_request.json").read_text())
    evidence = json.loads((result.result_dir / "evidence.json").read_text())
    assert request["spec"]["decisions"] == []
    assert evidence["screening_result"]["trade_count"] == 0
    assert evidence["screening_result"]["trades"] == []


def test_run_artifacts_preserve_exit_reason_and_decision_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    strategy = tmp_path / "tested" / "demo.py"
    strategy.parent.mkdir(parents=True, exist_ok=True)
    strategy.write_text(
        "from quant_strategies.decisions import ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision\n"
        "def generate_decisions(rows, params):\n"
        "    return [StrategyDecision(\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='equity_or_etf', symbol=rows[1]['symbol']),\n"
        "        decision_time=rows[1]['timestamp'],\n"
        "        as_of_time=rows[1]['timestamp'],\n"
        "        target=PositionTarget(direction='long', sizing_kind='target_weight', size=1.0),\n"
        "        exit_policy=ExitPolicy(max_hold_bars=2, take_profit_bps=50.0),\n"
        "        metadata={\n"
        "            'funding_pressure_bps': 3.25,\n"
        "            'entry_return_extension_bps': 42.0,\n"
        "            'signal_family': 'demo',\n"
        "        },\n"
        "    )]\n"
    )
    config_path = write_config(tmp_path, mode="screen")
    monkeypatch.setattr(execution, "load_data", lambda config: LoadedData(rows=rows(100.0, 100.0, 102.0, 103.0, 104.0)))

    result = run_config(config_path, repo_root=tmp_path)

    assert result.run_completed is True
    assert result.result_dir is not None
    request = json.loads((result.result_dir / "engine_request.json").read_text())
    evidence = json.loads((result.result_dir / "evidence.json").read_text())
    decision_payload = request["spec"]["decisions"][0]
    trade = evidence["screening_result"]["trades"][0]

    assert evidence["schema_version"] == "quant_strategies.engine.evidence/v3"
    assert decision_payload["exit_policy"]["max_hold_bars"] == 2
    assert decision_payload["exit_policy"]["take_profit_bps"] == 50.0
    assert decision_payload["metadata"]["funding_pressure_bps"] == 3.25
    assert decision_payload["metadata"]["entry_return_extension_bps"] == 42.0
    assert decision_payload["metadata"]["signal_family"] == "demo"
    assert trade["exit_reason"] == "take_profit"
    assert trade["decision_metadata"]["funding_pressure_bps"] == 3.25


def test_validation_gate_failure_remains_failed_summary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path, mode="validate")
    monkeypatch.setattr(execution, "load_data", lambda config: LoadedData(rows=rows(100.0, 101.0, 90.0, 89.0)))

    result = run_config(config_path, repo_root=tmp_path)

    assert result.run_completed is True
    assert result.result_dir is not None
    summary = read_summary(result.result_dir)
    assert summary["mode"] == "validate"
    assert summary["stage"] == "completed"
    assert summary["status"] == "failed"
    assert summary["engine"]["passed"] is False
    assert summary["engine"]["trade_count"] == 1
    assert summary["engine"]["smoke_score"]["sum_signed_trade_activity_gross"] < 0
    assert summary["engine"]["smoke_score"]["sum_signed_trade_activity_net"] < 0
    assert summary["engine"]["gates"][0]["name"] == "valid_inputs"
    assert_assessment(result, summary, assessment_status="smoke_failed")
    assert "status: failed validation gates" in (result.result_dir / "notes.md").read_text()


def test_run_config_treats_empty_decisions_as_zero_trade_smoke_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    strategy = tmp_path / "tested" / "demo.py"
    strategy.parent.mkdir(parents=True, exist_ok=True)
    strategy.write_text("def generate_decisions(rows, params):\n    return []\n")
    config_path = write_config(tmp_path, mode="validate")
    monkeypatch.setattr(execution, "load_data", lambda config: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)))

    result = run_config(config_path, repo_root=tmp_path)

    assert result.run_completed is True
    assert result.result_dir is not None
    summary = read_summary(result.result_dir)
    assert summary["mode"] == "validate"
    assert summary["stage"] == "completed"
    assert summary["status"] == "failed"
    assert summary["engine"]["passed"] is False
    assert summary["engine"]["trade_count"] == 0
    assert summary["engine"]["smoke_score"] == {
        "sum_signed_trade_activity_gross": 0.0,
        "sum_signed_trade_activity_funding": 0.0,
        "sum_signed_trade_activity_cost": 0.0,
        "sum_signed_trade_activity_net": 0.0,
    }
    assert {gate["name"]: gate["passed"] for gate in summary["engine"]["gates"]} == {
        "valid_inputs": True,
        "min_trades": False,
        "positive_gross": False,
        "positive_net": False,
    }
    assert_assessment(result, summary, assessment_status="smoke_failed")

    assert (result.result_dir / "decision_records.jsonl").read_text() == ""
    request = json.loads((result.result_dir / "engine_request.json").read_text())
    evidence = json.loads((result.result_dir / "evidence.json").read_text())
    assert request["spec"]["decisions"] == []
    assert evidence["validation_report"]["screening_result"]["trade_count"] == 0
    assert evidence["validation_report"]["screening_result"]["trades"] == []
    assert "status: failed validation gates" in (result.result_dir / "notes.md").read_text()


def test_run_config_writes_data_failure_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path)

    def fail_data_load(config):
        raise DataLoadError("strict data window failed")

    monkeypatch.setattr(execution, "load_data", fail_data_load)

    result = run_config(config_path, repo_root=tmp_path)

    assert result.run_completed is True
    assert result.result_dir is not None
    assert (result.result_dir / "config.toml").exists()
    assert (result.result_dir / "strategy_snapshot.py").exists()
    assert "strict data window failed" in (result.result_dir / "notes.md").read_text()
    summary = read_summary(result.result_dir)
    assert summary["stage"] == "data_load"
    assert "smoke_score" not in summary["engine"]
    assert summary["data_availability_status"] == "missing"
    assert summary["availability_coverage"] == {
        "field": "available_at",
        "present": 0,
        "total": 0,
        "fraction": None,
    }
    assert summary["causality_verified"] is False
    assert summary["evidence_quality_warnings"] == [
        "available_at_missing",
        "runner_causality_not_verified",
    ]
    assert_assessment(result, summary, assessment_status="runner_failed", failure_stage=str(summary["stage"]))
    assert (result.result_dir / "run_manifest.json").exists()
    assert not (result.result_dir / "strategy_input_rows.csv").exists()


def test_consumer_contract_run_completed_does_not_make_runner_failed_rankable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path)

    def fail_data_load(config):
        raise DataLoadError("strict data window failed")

    monkeypatch.setattr(execution, "load_data", fail_data_load)

    result = run_config(config_path, repo_root=tmp_path)

    assert result.run_completed is True
    assert result.failure_stage == "data_load"
    assert result.assessment_status == "runner_failed"
    assert cli._run_exit_code(result) == 1


def test_strategy_import_failure_prevents_data_load(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    strategy = tmp_path / "tested" / "demo.py"
    strategy.parent.mkdir(parents=True, exist_ok=True)
    strategy.write_text("VALUE = 1\n")
    config_path = write_config(tmp_path)

    def forbidden_data_load(config):
        raise AssertionError("data should not load after strategy import failure")

    monkeypatch.setattr(execution, "load_data", forbidden_data_load)

    result = run_config(config_path, repo_root=tmp_path)

    assert result.run_completed is True
    assert result.result_dir is not None
    summary = read_summary(result.result_dir)
    assert summary["stage"] == "strategy_import"
    assert_assessment(result, summary, assessment_status="runner_failed", failure_stage=str(summary["stage"]))
    assert (result.result_dir / "run_manifest.json").exists()


def test_strategy_path_directory_failure_writes_summary(tmp_path: Path):
    strategy_dir = tmp_path / "tested" / "demo.py"
    strategy_dir.mkdir(parents=True)
    config_path = write_config(tmp_path)

    result = run_config(config_path, repo_root=tmp_path)

    assert result.run_completed is True
    assert result.result_dir is not None
    assert not (result.result_dir / "strategy_snapshot.py").exists()
    summary = read_summary(result.result_dir)
    assert summary["stage"] == "strategy_import"
    assert_assessment(result, summary, assessment_status="runner_failed", failure_stage=str(summary["stage"]))
    assert (result.result_dir / "run_manifest.json").exists()


def test_raw_inputs_preserve_quote_and_funding_fields_in_engine_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path, fixed_quote_signal=True)
    config_path = write_config(
        tmp_path,
        kind="forex_with_quotes",
        symbol="EURUSD",
        dataset=None,
        fill_price="quote",
    )
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config: LoadedData(rows=rows(1.10, 1.11, 1.12, 1.13, quotes=True, research_fields=True)),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.result_dir is not None
    assert not (result.result_dir / "strategy_input_rows.csv").exists()
    jsonl_rows = [
        json.loads(line)
        for line in (result.result_dir / "strategy_input_rows.jsonl").read_text().splitlines()
    ]
    request = json.loads((result.result_dir / "engine_request.json").read_text())
    assert jsonl_rows[0]["timestamp"] == "2024-01-01T00:00:00+00:00"
    assert jsonl_rows[0]["available_at"] == "2024-01-01T00:00:00+00:00"
    assert jsonl_rows[0]["bar_ingested_at"] == "2024-01-01T00:00:00+00:00"
    assert jsonl_rows[0]["quote_ingested_at"] == "2024-01-01T00:00:00+00:00"
    assert jsonl_rows[0]["joined_refreshed_at"] == "2024-01-01T00:00:00+00:00"
    assert jsonl_rows[0]["bid"] == 1.09
    assert jsonl_rows[0]["ask"] == 1.11
    assert jsonl_rows[0]["funding_timestamp"] == "2024-01-01T00:00:00+00:00"
    assert jsonl_rows[0]["has_funding_event"] is True
    assert jsonl_rows[1]["nullable"] is None
    assert request["bars"][0]["bid"] == 1.09
    assert request["bars"][0]["ask"] == 1.11
    assert request["bars"][0]["funding_timestamp"] == "2024-01-01T00:00:00Z"
    assert request["bars"][0]["funding_rate"] == 0.0001
    assert request["bars"][0]["has_funding_event"] is True
    manifest = json.loads((result.result_dir / "data_manifest.json").read_text())
    assert manifest["metadata_field_coverage"]["available_at"] == {"present": 4, "total": 4}
    assert manifest["metadata_field_coverage"]["quote_ingested_at"] == {"present": 4, "total": 4}


def test_run_config_marks_complete_available_at_coverage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path)
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0, research_fields=True)),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.result_dir is not None
    summary = read_summary(result.result_dir)
    data_manifest = json.loads((result.result_dir / "data_manifest.json").read_text())
    assert summary["data_availability_status"] == "complete"
    assert summary["availability_coverage"] == {
        "field": "available_at",
        "present": 4,
        "total": 4,
        "fraction": 1.0,
    }
    assert summary["causality_verified"] is True
    assert summary["evidence_quality_warnings"] == []
    assert data_manifest["data_availability_status"] == "complete"
    assert data_manifest["availability_coverage"] == summary["availability_coverage"]
    assert data_manifest["causality_verified"] is True
    assert data_manifest["evidence_quality_warnings"] == summary["evidence_quality_warnings"]
    assert result.assessment_status == "smoke_passed"
    assert summary["assessment_status"] == "smoke_passed"


def test_run_config_reuses_execution_evidence_quality_after_causality(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path)
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0, research_fields=True)),
    )
    normalized_rows_calls = 0
    original_from_rows = NormalizedRows.from_rows

    def counting_from_rows(config, loaded_rows, **kwargs):
        nonlocal normalized_rows_calls
        normalized_rows_calls += 1
        return original_from_rows(config, loaded_rows, **kwargs)

    monkeypatch.setattr(NormalizedRows, "from_rows", staticmethod(counting_from_rows))

    result = run_config(config_path, repo_root=tmp_path)

    assert result.run_completed is True
    assert normalized_rows_calls == 1


def test_run_config_marks_partial_available_at_coverage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path)
    partial_rows = rows(100.0, 101.0, 102.0, 104.0, research_fields=True)
    partial_rows[1].pop("available_at")
    monkeypatch.setattr(execution, "load_data", lambda config: LoadedData(rows=partial_rows))

    result = run_config(config_path, repo_root=tmp_path)

    assert result.result_dir is not None
    summary = read_summary(result.result_dir)
    data_manifest = json.loads((result.result_dir / "data_manifest.json").read_text())
    assert summary["data_availability_status"] == "partial"
    coverage = summary["availability_coverage"]
    assert coverage["field"] == "available_at"
    assert coverage["present"] == 3
    assert coverage["total"] == 4
    assert coverage["fraction"] == pytest.approx(3 / 4)
    assert summary["causality_verified"] is False
    assert summary["evidence_quality_warnings"] == [
        "available_at_partial",
        "runner_causality_not_verified",
    ]
    assert data_manifest["data_availability_status"] == "partial"
    assert data_manifest["availability_coverage"]["field"] == "available_at"
    assert data_manifest["availability_coverage"]["present"] == 3
    assert data_manifest["availability_coverage"]["total"] == 4
    assert data_manifest["availability_coverage"]["fraction"] == pytest.approx(3 / 4)
    assert data_manifest["causality_verified"] is False
    assert data_manifest["evidence_quality_warnings"] == summary["evidence_quality_warnings"]
    assert result.assessment_status == "smoke_unverified"
    assert summary["assessment_status"] == "smoke_unverified"


def test_run_config_rejects_invalid_available_at_for_causality_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path)
    invalid_rows = rows(100.0, 101.0, 102.0, 104.0, research_fields=True)
    invalid_rows[1]["available_at"] = "not-a-datetime"
    monkeypatch.setattr(execution, "load_data", lambda config: LoadedData(rows=invalid_rows))

    result = run_config(config_path, repo_root=tmp_path)

    assert result.run_completed is True
    assert result.result_dir is not None
    summary = read_summary(result.result_dir)
    data_manifest = json.loads((result.result_dir / "data_manifest.json").read_text())
    assert summary["data_availability_status"] == "invalid"
    assert summary["availability_coverage"] == {
        "field": "available_at",
        "present": 3,
        "total": 4,
        "fraction": 0.75,
        "invalid": 1,
    }
    assert summary["causality_verified"] is False
    assert summary["evidence_quality_warnings"] == [
        "available_at_invalid",
        "runner_causality_not_verified",
    ]
    assert data_manifest["data_availability_status"] == "invalid"
    assert data_manifest["availability_coverage"] == summary["availability_coverage"]
    assert data_manifest["causality_verified"] is False
    assert data_manifest["evidence_quality_warnings"] == summary["evidence_quality_warnings"]
    assert result.assessment_status == "smoke_unverified"
    assert summary["assessment_status"] == "smoke_unverified"


def test_runner_catches_hidden_lookahead_before_request_build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    strategy = tmp_path / "tested" / "demo.py"
    strategy.parent.mkdir(parents=True, exist_ok=True)
    strategy.write_text(
        "from quant_strategies.decisions import ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision\n"
        "def generate_decisions(rows, params):\n"
        "    as_of_row = rows[1]\n"
        "    future_rows = [row for row in rows if row['timestamp'] > as_of_row['timestamp']]\n"
        "    size = 2.0 if future_rows else 1.0\n"
        "    return [StrategyDecision(\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='equity_or_etf', symbol=as_of_row['symbol']),\n"
        "        decision_time=as_of_row['timestamp'],\n"
        "        as_of_time=as_of_row['timestamp'],\n"
        "        target=PositionTarget(direction='long', sizing_kind='target_weight', size=size),\n"
        "        exit_policy=ExitPolicy(max_hold_bars=1),\n"
        "    )]\n"
    )
    config_path = write_config(tmp_path)
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config: LoadedData(rows=rows(100.0, 101.0, 102.0, research_fields=True)),
    )
    events: list[dict[str, object]] = []

    result = run_config(config_path, repo_root=tmp_path, event_sink=events.append)

    assert result.run_completed is True
    assert result.result_dir is not None
    summary = read_summary(result.result_dir)
    data_manifest = json.loads((result.result_dir / "data_manifest.json").read_text())
    assert summary["stage"] == "causality"
    assert summary["message"] == "hidden_lookahead_detected"
    assert summary["causality_verified"] is False
    assert summary["evidence_quality_warnings"] == ["runner_causality_not_verified"]
    assert data_manifest["causality_verified"] is False
    assert data_manifest["evidence_quality_warnings"] == summary["evidence_quality_warnings"]
    assert (result.result_dir / "strategy_input_rows.jsonl").exists()
    assert not (result.result_dir / "decision_records.jsonl").exists()
    assert not (result.result_dir / "signals.csv").exists()
    assert not (result.result_dir / "engine_request.json").exists()
    assert result.assessment_status == "runner_failed"
    assert summary["assessment_status"] == "runner_failed"
    assert any(
        event["stage"] == "causality_check"
        and event["status"] == "failed"
        and "hidden_lookahead_detected" in str(event["error"])
        for event in events
    )
    assert not any(
        event["stage"] == "causality_check" and event["status"] == "completed"
        for event in events
    )


def test_run_config_rejects_future_declared_observation_before_request_build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    strategy = tmp_path / "tested" / "demo.py"
    strategy.parent.mkdir(parents=True, exist_ok=True)
    strategy.write_text(
        "from datetime import datetime, timezone\n"
        "from quant_strategies.decisions import ExitPolicy, InstrumentRef, ObservationRef, PositionTarget, StrategyDecision\n"
        "def generate_decisions(rows, params):\n"
        "    return [StrategyDecision(\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='equity_or_etf', symbol=rows[1]['symbol']),\n"
        "        decision_time=rows[1]['timestamp'],\n"
        "        as_of_time=rows[1]['timestamp'],\n"
        "        target=PositionTarget(direction='long', sizing_kind='target_weight', size=1.0),\n"
        "        exit_policy=ExitPolicy(max_hold_bars=1),\n"
        "        observations=(ObservationRef(symbol='SPY', timestamp=datetime(2024, 1, 3, tzinfo=timezone.utc), field='close'),),\n"
        "    )]\n"
    )
    config_path = write_config(tmp_path)
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0, research_fields=True)),
    )
    events: list[dict[str, object]] = []

    result = run_config(config_path, repo_root=tmp_path, event_sink=events.append)

    assert result.run_completed is True
    assert result.result_dir is not None
    summary = read_summary(result.result_dir)
    data_manifest = json.loads((result.result_dir / "data_manifest.json").read_text())
    assert summary["stage"] == "observation_audit"
    assert "references future row" in str(summary["message"])
    assert summary["assessment_status"] == "runner_failed"
    assert data_manifest["causality_verified"] is False
    assert data_manifest["evidence_quality_warnings"] == summary["evidence_quality_warnings"]
    assert not (result.result_dir / "engine_request.json").exists()
    assert any(
        event["stage"] == "observation_audit"
        and event["status"] == "failed"
        and "references future row" in str(event["error"])
        for event in events
    )
    assert not any(event["stage"] == "causality_check" for event in events)


def test_run_config_records_row_contract_feedback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path)
    contract_rows = rows(100.0, 101.0, 102.0, research_fields=True)
    contract_rows[1].pop("high")
    contract_rows[2]["timestamp"] = contract_rows[1]["timestamp"]
    monkeypatch.setattr(execution, "load_data", lambda config: LoadedData(rows=contract_rows))

    result = run_config(config_path, repo_root=tmp_path)

    assert result.run_completed is True
    assert result.result_dir is not None
    summary = read_summary(result.result_dir)
    data_manifest = json.loads((result.result_dir / "data_manifest.json").read_text())
    row_contract = summary["row_contract"]
    assert row_contract["status"] == "failed"
    assert row_contract["missing_required_fields"] == {"high": 1}
    assert row_contract["duplicate_key_count"] == 1
    assert row_contract["timestamp_status"] == "aware"
    assert row_contract["quant_data_feedback"] == [
        "row_duplicate_symbol_timestamp:1",
        "row_missing_required_field:high:1",
    ]
    assert row_contract["issue_reasons"] == {
        "row_duplicate_symbol_timestamp": 1,
        "row_missing_required_field": 1,
    }
    assert data_manifest["row_contract"] == row_contract


def test_run_config_requires_crypto_funding_event_indicator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    config_path = write_config(
        tmp_path,
        kind="crypto_perp_funding",
        symbol="BTC-PERP",
        dataset=None,
    )
    contract_rows = rows(100.0, 101.0, 102.0, 104.0, research_fields=True)
    for row in contract_rows:
        row["symbol"] = "BTC-PERP"
        row.pop("has_funding_event")
    monkeypatch.setattr(execution, "load_data", lambda config: LoadedData(rows=contract_rows))

    result = run_config(config_path, repo_root=tmp_path)

    assert result.result_dir is not None
    summary = read_summary(result.result_dir)
    row_contract = summary["row_contract"]
    assert row_contract["status"] == "failed"
    assert row_contract["missing_required_fields"] == {"has_funding_event": 4}
    assert row_contract["quant_data_feedback"] == [
        "row_missing_required_field:has_funding_event:4"
    ]


def test_completed_run_writes_minimal_manifests(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path)
    loaded_rows = rows(100.0, 101.0, 102.0, 104.0, research_fields=True)
    monkeypatch.setattr(execution, "load_data", lambda config: LoadedData(rows=loaded_rows))

    result = run_config(config_path, repo_root=tmp_path)

    assert result.run_completed is True
    assert result.result_dir is not None
    run_manifest = json.loads((result.result_dir / "run_manifest.json").read_text())
    data_manifest = json.loads((result.result_dir / "data_manifest.json").read_text())
    assert run_manifest["python"]["version"]
    assert {"quant-strategies", "quant-data", "pydantic"}.issubset(run_manifest["packages"])
    assert LEGACY_DISTRIBUTION not in run_manifest["packages"]
    assert run_manifest["engine"] == {"evidence_schema": "quant_strategies.engine.evidence/v3"}
    assert run_manifest["artifact_profile"] == "full"
    assert run_manifest["artifact_trust_tier"] == "audit_replayable"
    assert run_manifest["evidence"] == {
        "evidence_class": "runner_smoke",
        "strategy_contract": "decision",
        "return_model": "smoke_score.sum_signed_trade_activity_net",
        "funding_model": "none",
        "metric_semantics": run_manifest["evidence"]["metric_semantics"],
        "promotion_eligible": False,
        "paper_trade_eligible": False,
        "live_eligible": False,
        "requires_manual_approval": True,
    }
    assert_smoke_metric_semantics(run_manifest["evidence"])
    assert run_manifest["artifacts"]["config.toml"]["sha256"]
    assert run_manifest["artifacts"]["strategy_snapshot.py"]["sha256"]
    assert run_manifest["artifacts"]["strategy_input_rows.jsonl"]["sha256"]
    assert run_manifest["artifacts"]["decision_records.jsonl"]["sha256"]
    assert run_manifest["artifacts"]["engine_request.json"]["sha256"]
    assert data_manifest["data"] == {
        "kind": "bars",
        "dataset": "equity_1min",
        "symbols": ["SPY"],
        "start": "2024-01-01",
        "end": "2024-01-05",
        "strict": True,
    }
    assert data_manifest["artifact_profile"] == "full"
    assert data_manifest["artifact_trust_tier"] == "audit_replayable"
    assert_smoke_metric_semantics(data_manifest)
    assert data_manifest["rows"]["total"] == 4
    assert data_manifest["rows"]["by_symbol"]["SPY"]["count"] == 4
    assert data_manifest["rows"]["by_symbol"]["SPY"]["min_timestamp"] == "2024-01-01T00:00:00+00:00"
    assert data_manifest["rows"]["by_symbol"]["SPY"]["max_timestamp"] == "2024-01-04T00:00:00+00:00"
    assert "strategy_input_rows_jsonl_sha256" not in data_manifest
    assert "strategy_input_rows.jsonl" in run_manifest["artifacts"]
    assert len(data_manifest["normalized_rows_sha256"]) == 64
    summary = read_summary(result.result_dir)
    assert "run_manifest.json" in summary["artifacts"]
    assert "data_manifest.json" in summary["artifacts"]


def test_full_profile_accepts_nonfinite_research_fields_in_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path)
    loaded_rows = rows(100.0, 101.0, 102.0, 104.0)
    loaded_rows[0]["research_nan"] = float("nan")
    loaded_rows[0]["research_decimal"] = Decimal("1.25")
    monkeypatch.setattr(execution, "load_data", lambda config: LoadedData(rows=loaded_rows))

    result = run_config(config_path, repo_root=tmp_path)

    assert result.run_completed is True
    assert result.result_dir is not None
    jsonl_rows = [
        json.loads(line)
        for line in (result.result_dir / "strategy_input_rows.jsonl").read_text().splitlines()
    ]
    data_manifest = json.loads((result.result_dir / "data_manifest.json").read_text())
    assert jsonl_rows[0]["research_nan"] is None
    assert jsonl_rows[0]["research_decimal"] == 1.25
    assert len(data_manifest["normalized_rows_sha256"]) == 64


def test_full_profile_strategy_input_rows_hash_matches_normalized_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path)
    loaded_rows = rows(100.0, 101.0, 102.0, 104.0)
    for loaded_row in loaded_rows:
        timestamp = loaded_row["timestamp"]
        loaded_row["timestamp"] = timestamp.isoformat().replace("+00:00", "Z")
        loaded_row["available_at"] = loaded_row["timestamp"]
        for field in ("open", "high", "low", "close"):
            loaded_row[field] = str(loaded_row[field])
    config = config_module.load_config(config_path, repo_root=tmp_path)
    expected_normalized = NormalizedRows.from_rows(config, loaded_rows, mode="search")
    monkeypatch.setattr(execution, "load_data", lambda config: LoadedData(rows=loaded_rows))

    result = run_config(config_path, repo_root=tmp_path)

    assert result.run_completed is True
    assert result.result_dir is not None
    data_manifest = json.loads((result.result_dir / "data_manifest.json").read_text())
    jsonl_path = result.result_dir / "strategy_input_rows.jsonl"
    written_hash = hashlib.sha256(jsonl_path.read_bytes()).hexdigest()
    jsonl_rows = [json.loads(line) for line in jsonl_path.read_text().splitlines()]

    assert written_hash == expected_normalized.normalized_rows_sha256
    assert data_manifest["normalized_rows_sha256"] == expected_normalized.normalized_rows_sha256
    assert jsonl_rows[0]["timestamp"] == "2024-01-01T00:00:00+00:00"
    assert jsonl_rows[0]["available_at"] == "2024-01-01T00:00:00+00:00"
    assert jsonl_rows[0]["open"] == 100.0


def test_full_profile_strategy_input_rows_hash_mismatch_fails_artifact_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path)
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)),
    )
    original_write = artifacts.write_strategy_input_rows

    def write_wrong_hash(result_dir: Path, row_payload) -> str:
        original_write(result_dir, row_payload)
        return "0" * 64

    monkeypatch.setattr(artifacts, "write_strategy_input_rows", write_wrong_hash)

    with pytest.raises(RunnerError, match="strategy_input_rows.jsonl hash"):
        run_config(config_path, repo_root=tmp_path)


def test_decision_generation_failure_writes_run_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    strategy = tmp_path / "tested" / "demo.py"
    strategy.parent.mkdir(parents=True, exist_ok=True)
    strategy.write_text("def generate_decisions(rows, params):\n    raise RuntimeError('boom')\n")
    config_path = write_config(tmp_path)
    monkeypatch.setattr(execution, "load_data", lambda config: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)))

    result = run_config(config_path, repo_root=tmp_path)

    assert result.run_completed is True
    assert result.result_dir is not None
    assert (result.result_dir / "run_manifest.json").exists()
    summary = read_summary(result.result_dir)
    assert summary["stage"] == "decision_generation"
    assert "smoke_score" not in summary["engine"]
    assert_assessment(result, summary, assessment_status="runner_failed", failure_stage=str(summary["stage"]))


def test_runner_blocks_strategy_row_mutation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    strategy = tmp_path / "tested" / "demo.py"
    strategy.parent.mkdir(parents=True, exist_ok=True)
    strategy.write_text(
        "def generate_decisions(rows, params):\n"
        "    rows[0]['close'] = 999.0\n"
        "    return []\n"
    )
    config_path = write_config(tmp_path)
    loaded_rows = rows(100.0, 101.0, 102.0, 104.0)
    monkeypatch.setattr(execution, "load_data", lambda config: LoadedData(rows=loaded_rows))

    result = run_config(config_path, repo_root=tmp_path)

    assert result.run_completed is True
    assert loaded_rows[0]["close"] == 100.0
    assert result.result_dir is not None
    summary = read_summary(result.result_dir)
    assert summary["stage"] == "decision_generation"
    assert "strategy execution failed" in summary["message"]
    assert_assessment(result, summary, assessment_status="runner_failed", failure_stage=str(summary["stage"]))


def test_runner_blocks_strategy_param_mutation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    strategy = tmp_path / "tested" / "demo.py"
    strategy.parent.mkdir(parents=True, exist_ok=True)
    strategy.write_text(
        "def generate_decisions(rows, params):\n"
        "    params['weight'] = 2.0\n"
        "    return []\n"
    )
    config_path = write_config(tmp_path)
    monkeypatch.setattr(execution, "load_data", lambda config: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)))

    result = run_config(config_path, repo_root=tmp_path)

    assert result.run_completed is True
    assert result.result_dir is not None
    summary = read_summary(result.result_dir)
    assert summary["stage"] == "decision_generation"
    assert "strategy execution failed" in summary["message"]
    assert_assessment(result, summary, assessment_status="runner_failed", failure_stage=str(summary["stage"]))


def test_runner_validates_params_before_data_loading(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    strategy = tmp_path / "tested" / "demo.py"
    strategy.parent.mkdir(parents=True, exist_ok=True)
    strategy.write_text(
        "def validate_params(params):\n"
        "    raise ValueError('unknown params')\n"
        "def generate_decisions(rows, params):\n"
        "    return []\n"
    )
    config_path = write_config(tmp_path)
    load_calls = 0

    def load_data(config):
        nonlocal load_calls
        load_calls += 1
        return LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0))

    monkeypatch.setattr(execution, "load_data", load_data)

    result = run_config(config_path, repo_root=tmp_path)

    assert result.run_completed is True
    assert load_calls == 0
    assert result.result_dir is not None
    summary = read_summary(result.result_dir)
    assert summary["stage"] == "param_validation"
    assert summary["message"] == "param validation failed: unknown params"
    assert not (result.result_dir / "strategy_input_rows.jsonl").exists()
    assert_assessment(result, summary, assessment_status="runner_failed", failure_stage=str(summary["stage"]))


def test_runner_rejects_non_mapping_validate_params_return(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    strategy = tmp_path / "tested" / "demo.py"
    strategy.parent.mkdir(parents=True, exist_ok=True)
    strategy.write_text(
        "def validate_params(params):\n"
        "    return None\n"
        "def generate_decisions(rows, params):\n"
        "    return []\n"
    )
    config_path = write_config(tmp_path)
    monkeypatch.setattr(execution, "load_data", lambda config: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)))

    result = run_config(config_path, repo_root=tmp_path)

    assert result.run_completed is True
    assert result.result_dir is not None
    summary = read_summary(result.result_dir)
    assert summary["stage"] == "param_validation"
    assert summary["message"] == "param validation failed: validate_params must return a mapping"
    assert not (result.result_dir / "strategy_input_rows.jsonl").exists()
    assert_assessment(result, summary, assessment_status="runner_failed", failure_stage=str(summary["stage"]))


def test_runner_structures_validate_params_system_exit(tmp_path: Path):
    strategy = tmp_path / "tested" / "demo.py"
    strategy.parent.mkdir(parents=True, exist_ok=True)
    strategy.write_text(
        "def validate_params(params):\n"
        "    raise SystemExit('params exited')\n"
        "def generate_decisions(rows, params):\n"
        "    return []\n"
    )
    config_path = write_config(tmp_path)

    result = run_config(config_path, repo_root=tmp_path)

    assert result.run_completed is True
    assert result.failure_stage == "param_validation"
    assert result.result_dir is not None
    summary = read_summary(result.result_dir)
    assert summary["stage"] == "param_validation"
    assert summary["message"] == "param validation exited: params exited"
    assert not (result.result_dir / "strategy_input_rows.jsonl").exists()
    assert_assessment(result, summary, assessment_status="runner_failed", failure_stage=str(summary["stage"]))


def test_runner_structures_strategy_execution_system_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    strategy = tmp_path / "tested" / "demo.py"
    strategy.parent.mkdir(parents=True, exist_ok=True)
    strategy.write_text(
        "def generate_decisions(rows, params):\n"
        "    raise SystemExit('strategy exited')\n"
    )
    config_path = write_config(tmp_path)
    monkeypatch.setattr(execution, "load_data", lambda config: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)))

    result = run_config(config_path, repo_root=tmp_path)

    assert result.run_completed is True
    assert result.failure_stage == "decision_generation"
    assert result.result_dir is not None
    summary = read_summary(result.result_dir)
    assert summary["stage"] == "decision_generation"
    assert "strategy execution exited: strategy exited" in summary["message"]


def test_runner_structures_strategy_import_system_exit(tmp_path: Path):
    strategy = tmp_path / "tested" / "demo.py"
    strategy.parent.mkdir(parents=True, exist_ok=True)
    strategy.write_text("raise SystemExit('import exited')\n")
    config_path = write_config(tmp_path)

    result = run_config(config_path, repo_root=tmp_path)

    assert result.run_completed is True
    assert result.failure_stage == "strategy_import"
    assert result.result_dir is not None
    summary = read_summary(result.result_dir)
    assert summary["stage"] == "strategy_import"
    assert "strategy import exited: import exited" in summary["message"]


@pytest.mark.parametrize("readiness_lag", [-timedelta(minutes=1), timedelta(0)])
def test_data_readiness_allows_matching_decision_row_at_or_before_decision_time(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    readiness_lag: timedelta,
):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path)
    loaded_rows = rows(100.0, 101.0, 102.0, 104.0, research_fields=True, readiness_lag=readiness_lag)
    monkeypatch.setattr(execution, "load_data", lambda config: LoadedData(rows=loaded_rows))

    result = run_config(config_path, repo_root=tmp_path)

    assert result.run_completed is True
    assert result.result_dir is not None
    summary = read_summary(result.result_dir)
    assert summary["stage"] == "completed"


def test_unavailable_decision_row_fails_causality_before_adapter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path)
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0, research_fields=True, readiness_lag=timedelta(minutes=1))),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.run_completed is True
    assert result.result_dir is not None
    for name in (
        "strategy_input_rows.jsonl",
        "data_manifest.json",
        "run_manifest.json",
        "summary.json",
        "notes.md",
    ):
        assert (result.result_dir / name).exists()
    assert not (result.result_dir / "strategy_input_rows.csv").exists()
    assert not (result.result_dir / "decision_records.jsonl").exists()
    assert not (result.result_dir / "signals.csv").exists()
    assert not (result.result_dir / "engine_request.json").exists()
    summary = read_summary(result.result_dir)
    assert summary["stage"] == "causality"
    assert summary["message"].startswith("hidden_lookahead_check_failed:")
    assert summary["data_availability_status"] == "complete"
    assert summary["availability_coverage"] == {
        "field": "available_at",
        "present": 4,
        "total": 4,
        "fraction": 1.0,
    }
    assert summary["causality_verified"] is False
    assert summary["evidence_quality_warnings"] == ["runner_causality_not_verified"]
    assert result.assessment_status == "runner_failed"
    assert summary["assessment_status"] == "runner_failed"


def test_malformed_decision_time_remains_decision_generation_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    strategy = tmp_path / "tested" / "demo.py"
    strategy.parent.mkdir(parents=True, exist_ok=True)
    strategy.write_text(
        "from quant_strategies.decisions import ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision\n"
        "def generate_decisions(rows, params):\n"
        "    return [StrategyDecision(\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='equity_or_etf', symbol=rows[1]['symbol']),\n"
        "        decision_time='not-a-timestamp',\n"
        "        as_of_time=rows[1]['timestamp'],\n"
        "        target=PositionTarget(direction='long', sizing_kind='target_weight', size=1.0),\n"
        "        exit_policy=ExitPolicy(max_hold_bars=1),\n"
        "    )]\n"
    )
    config_path = write_config(tmp_path)
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0, research_fields=True)),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.run_completed is True
    assert result.result_dir is not None
    summary = read_summary(result.result_dir)
    assert summary["stage"] == "decision_generation"
    assert "decision_time" in summary["message"]
    assert_assessment(result, summary, assessment_status="runner_failed", failure_stage=str(summary["stage"]))


def test_invalid_decision_output_fails_before_writing_decision_records(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    strategy = tmp_path / "tested" / "demo.py"
    strategy.parent.mkdir(parents=True, exist_ok=True)
    strategy.write_text("def generate_decisions(rows, params):\n    return 'not decisions'\n")
    config_path = write_config(tmp_path)
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0, research_fields=True)),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.run_completed is True
    assert result.result_dir is not None
    summary = read_summary(result.result_dir)
    assert summary["stage"] == "decision_generation"
    assert "invalid_decision_output" in summary["message"]
    assert not (result.result_dir / "strategy_input_rows.csv").exists()
    assert (result.result_dir / "strategy_input_rows.jsonl").exists()
    assert (result.result_dir / "data_manifest.json").exists()
    assert not (result.result_dir / "decision_records.jsonl").exists()
    assert_assessment(result, summary, assessment_status="runner_failed", failure_stage=str(summary["stage"]))


def test_unsupported_smoke_decision_keeps_loaded_data_and_decision_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    strategy = tmp_path / "tested" / "demo.py"
    strategy.parent.mkdir(parents=True, exist_ok=True)
    strategy.write_text(
        "from quant_strategies.decisions import ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision\n"
        "def generate_decisions(rows, params):\n"
        "    return [StrategyDecision(\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='equity_or_etf', symbol=rows[1]['symbol']),\n"
        "        decision_time=rows[1]['timestamp'],\n"
        "        as_of_time=rows[1]['timestamp'],\n"
        "        target=PositionTarget(direction='flat', sizing_kind='target_weight', size=0.0),\n"
        "        exit_policy=ExitPolicy(max_hold_bars=1),\n"
        "    )]\n"
    )
    config_path = write_config(tmp_path)
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0, research_fields=True)),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.run_completed is True
    assert result.result_dir is not None
    summary = read_summary(result.result_dir)
    assert summary["stage"] == "request_build"
    assert "smoke engine cannot represent flat target for SPY" in summary["message"]
    assert not (result.result_dir / "strategy_input_rows.csv").exists()
    assert (result.result_dir / "strategy_input_rows.jsonl").exists()
    assert (result.result_dir / "data_manifest.json").exists()
    assert (result.result_dir / "decision_records.jsonl").exists()
    assert not (result.result_dir / "signals.csv").exists()
    assert_assessment(result, summary, assessment_status="runner_failed", failure_stage=str(summary["stage"]))


def test_decision_strategy_id_mismatch_fails_before_writing_decision_records(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    strategy = tmp_path / "tested" / "demo.py"
    strategy.parent.mkdir(parents=True, exist_ok=True)
    strategy.write_text(
        "from quant_strategies.decisions import ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision\n"
        "def generate_decisions(rows, params):\n"
        "    return [StrategyDecision(\n"
        "        strategy_id='other',\n"
        "        instrument=InstrumentRef(kind='equity_or_etf', symbol=rows[1]['symbol']),\n"
        "        decision_time=rows[1]['timestamp'],\n"
        "        as_of_time=rows[1]['timestamp'],\n"
        "        target=PositionTarget(direction='long', sizing_kind='target_weight', size=1.0),\n"
        "        exit_policy=ExitPolicy(max_hold_bars=1),\n"
        "    )]\n"
    )
    config_path = write_config(tmp_path)
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0, research_fields=True)),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.run_completed is True
    assert result.result_dir is not None
    summary = read_summary(result.result_dir)
    assert summary["stage"] == "decision_generation"
    assert "decision_strategy_id_mismatch[0]: expected demo, got other" in summary["message"]
    assert not (result.result_dir / "decision_records.jsonl").exists()
    assert_assessment(result, summary, assessment_status="runner_failed", failure_stage=str(summary["stage"]))


def test_run_manifest_marks_dirty_git_worktree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path)
    (tmp_path / ".gitignore").write_text("results/\n")
    (tmp_path / "README.md").write_text("clean\n")
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "baseline"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "README.md").write_text("dirty\n")
    (tmp_path / "scratch.txt").write_text("untracked\n")
    monkeypatch.setattr(execution, "load_data", lambda config: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)))

    result = run_config(config_path, repo_root=tmp_path)

    assert result.result_dir is not None
    run_manifest = json.loads((result.result_dir / "run_manifest.json").read_text())
    repository = run_manifest["repository"]
    result_exclusion = f":(exclude){result.result_dir.relative_to(tmp_path).as_posix()}"
    expected_status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no", "--", ".", result_exclusion],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.rstrip("\n")
    expected_diff = subprocess.run(
        ["git", "diff", "--binary", "HEAD", "--", ".", result_exclusion],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.rstrip("\n")
    expected_status_hash = hashlib.sha256(expected_status.encode("utf-8")).hexdigest()
    expected_diff_hash = hashlib.sha256(expected_diff.encode("utf-8")).hexdigest()
    assert repository["commit"]
    assert repository["dirty"] is True
    assert repository["status_porcelain_sha256"] == expected_status_hash
    assert repository["tracked_diff_sha256"] == expected_diff_hash


def test_run_manifest_ignores_untracked_detritus_for_repository_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path)
    (tmp_path / ".gitignore").write_text("results/\n")
    (tmp_path / "README.md").write_text("clean\n")
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "baseline"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "scratch.txt").write_text("untracked\n")
    monkeypatch.setattr(execution, "load_data", lambda config: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)))

    result = run_config(config_path, repo_root=tmp_path)

    assert result.result_dir is not None
    run_manifest = json.loads((result.result_dir / "run_manifest.json").read_text())
    repository = run_manifest["repository"]
    assert repository["dirty"] is False
    assert repository["status_porcelain_sha256"] is None
    assert repository["tracked_diff_sha256"] is None


def test_crypto_perp_funding_notes_label_returns_as_funding_aware(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path, kind="crypto_perp_funding", symbol="BTC-PERP", dataset=None)
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0, research_fields=True)),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.result_dir is not None
    summary = json.loads((result.result_dir / "summary.json").read_text())
    assert summary["funding_model"] == "linear_additive_adjustment"
    run_manifest = json.loads((result.result_dir / "run_manifest.json").read_text())
    assert run_manifest["evidence"]["funding_model"] == "linear_additive_adjustment"
    funding = run_manifest["evidence"]["metric_semantics"]["smoke_score.sum_signed_trade_activity_funding"]
    assert funding["return_path_model"] == "linear_additive_adjustment"
    notes = (result.result_dir / "notes.md").read_text()
    assert "return_scope: price-and-funding" in notes
    assert "supplied funding events are included" in notes


def test_request_build_failure_preserves_prior_stage_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path)
    monkeypatch.setattr(execution, "load_data", lambda config: LoadedData(rows=rows(100.0, 101.0, 102.0)))

    result = run_config(config_path, repo_root=tmp_path)

    assert result.run_completed is True
    assert result.result_dir is not None
    for name in (
        "strategy_input_rows.jsonl",
        "decision_records.jsonl",
        "summary.json",
        "notes.md",
    ):
        assert (result.result_dir / name).exists()
    assert not (result.result_dir / "strategy_input_rows.csv").exists()
    assert not (result.result_dir / "engine_request.json").exists()
    assert read_summary(result.result_dir)["stage"] == "request_build"


def test_engine_failure_preserves_engine_request_and_writes_stage_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path)
    monkeypatch.setattr(execution, "load_data", lambda config: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)))
    monkeypatch.setattr(
        engine_runner,
        "evaluate_request",
        lambda request, *, mode, include_evidence=True: (_ for _ in ()).throw(
            EvaluationRunError("engine unavailable")
        ),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.run_completed is True
    assert result.result_dir is not None
    assert (result.result_dir / "engine_request.json").exists()
    assert read_summary(result.result_dir)["stage"] == "engine_evaluation"


def test_run_config_resolves_relative_config_path_against_repo_root_from_other_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    write_strategy(repo_root)
    config_path = write_config(repo_root, relative_path="runs/demo.toml")
    monkeypatch.setattr(execution, "load_data", lambda config: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)))
    monkeypatch.chdir(tmp_path)

    result = run_config("runs/demo.toml", repo_root=repo_root)

    assert result.run_completed is True
    assert result.result_dir is not None
    assert (result.result_dir / "config.toml").read_text() == config_path.read_text()


def test_run_config_emits_structured_stage_events(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path)
    monkeypatch.setattr(execution, "load_data", lambda config: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)))
    events: list[dict[str, object]] = []

    result = run_config(config_path, repo_root=tmp_path, event_sink=events.append)

    assert result.run_completed is True
    assert events
    assert all(event["event"] == "runner_stage" for event in events)
    assert all(isinstance(event["timestamp"], str) for event in events)
    completed_stages = {
        str(event["stage"])
        for event in events
        if event["status"] == "completed"
    }
    assert {
        "config_load",
        "artifact_initialization",
        "strategy_execution",
        "causality_check",
        "request_build",
        "data_readiness",
        "observation_audit",
        "engine_evaluation",
        "artifact_writes",
    }.issubset(completed_stages)
    completed_events = [event for event in events if event["status"] == "completed"]
    assert all(isinstance(event["duration_ms"], int | float) for event in completed_events)
    assert all(event["duration_ms"] >= 0 for event in completed_events)


def test_cli_run_accepts_explicit_repo_root_from_other_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    write_strategy(repo_root)
    write_config(repo_root, relative_path="runs/demo.toml")
    monkeypatch.setattr(execution, "load_data", lambda config: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)))
    monkeypatch.chdir(tmp_path)

    exit_code = cli.main(["run", "--repo-root", str(repo_root), "runs/demo.toml"])
    output = capsys.readouterr().out.strip()

    assert exit_code == 0, output
    assert Path(output).exists()


def test_cli_run_events_jsonl_writes_events_to_stderr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path)
    monkeypatch.setattr(config_module, "default_repo_root", lambda: tmp_path)
    monkeypatch.setattr(execution, "load_data", lambda config: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)))

    exit_code = cli.main(["run", "--events-jsonl", str(config_path)])
    captured = capsys.readouterr()
    stdout = captured.out.strip()
    stderr_lines = [line for line in captured.err.splitlines() if line.strip()]
    events = [json.loads(line) for line in stderr_lines]

    assert exit_code == 0, stdout
    assert Path(stdout).exists()
    assert events
    assert all(event["event"] == "runner_stage" for event in events)
    assert any(
        event["stage"] == "engine_evaluation" and event["status"] == "completed"
        for event in events
    )


def test_cli_smoke_uses_runner_and_prints_result_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path)
    monkeypatch.setattr(config_module, "default_repo_root", lambda: tmp_path)
    monkeypatch.setattr(execution, "load_data", lambda config: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)))

    exit_code = cli.main(["run", str(config_path)])
    output = capsys.readouterr().out.strip()

    assert exit_code == 0, output
    assert Path(output).exists()


def test_cli_reports_failure_with_notes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    notes = tmp_path / "results" / "run" / "notes.md"
    notes.parent.mkdir(parents=True)
    notes.write_text("failed")
    monkeypatch.setattr(
        cli,
        "run_config",
        lambda path, *, repo_root=None: RunResult(
            result_dir=notes.parent,
            notes_path=notes,
            message="failed",
            run_completed=True,
            failure_stage="request_build",
        ),
    )

    exit_code = cli.main(["run", "bad.toml"])

    assert exit_code == 1
    assert str(notes) in capsys.readouterr().out


def test_cli_returns_three_for_data_readiness_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    notes = tmp_path / "results" / "run" / "notes.md"
    notes.parent.mkdir(parents=True)
    notes.write_text("failed")
    monkeypatch.setattr(
        cli,
        "run_config",
        lambda path, *, repo_root=None: RunResult(
            result_dir=notes.parent,
            notes_path=notes,
            message="failed",
            run_completed=True,
            failure_stage="data_readiness",
        ),
    )

    exit_code = cli.main(["run", "bad.toml"])

    assert exit_code == 3
    assert str(notes) in capsys.readouterr().out


def test_repeated_runner_artifacts_are_byte_deterministic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path)
    loaded_rows = rows(100.0, 101.0, 102.0, 104.0, research_fields=True)

    def load_data(config):
        return LoadedData(rows=[dict(row) for row in loaded_rows])

    monkeypatch.setattr(execution, "load_data", load_data)

    first = run_config(config_path, repo_root=tmp_path)
    second = run_config(config_path, repo_root=tmp_path)

    expected_artifacts = {
        "config.toml",
        "strategy_snapshot.py",
        "strategy_input_rows.jsonl",
        "decision_records.jsonl",
        "engine_request.json",
        "data_manifest.json",
        "run_manifest.json",
        "summary.json",
        "evidence.json",
        "notes.md",
    }

    assert first.run_completed is True
    assert second.run_completed is True
    assert first.artifact_trust_tier == "audit_replayable"
    assert second.artifact_trust_tier == "audit_replayable"
    assert first.result_dir is not None
    assert second.result_dir is not None
    assert first.result_dir != second.result_dir
    assert {path.name for path in first.result_dir.iterdir() if path.is_file()} == expected_artifacts
    assert {path.name for path in second.result_dir.iterdir() if path.is_file()} == expected_artifacts
    assert {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in first.result_dir.iterdir()
        if path.is_file()
    } == {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in second.result_dir.iterdir()
        if path.is_file()
    }
