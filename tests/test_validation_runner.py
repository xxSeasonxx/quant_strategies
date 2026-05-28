from __future__ import annotations

import hashlib
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from quant_strategies.decisions import ExitPolicy, InstrumentRef, ObservationRef, PositionTarget, StrategyDecision
from quant_strategies.runner.data_loader import LoadedData
from quant_strategies.runner.errors import DataLoadError
from quant_strategies.validation import run_validation
from quant_strategies.validation.backends import BackendRunResult, FakeBackend
from quant_strategies.validation.errors import ValidationConfigError


AS_OF = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
DECISION = datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc)


def write_candidate(
    tmp_path: Path,
    *,
    backend: str | None = "fake",
    window_ids: tuple[str, ...] = ("validation_2026_h1",),
) -> Path:
    candidate = tmp_path / "candidate"
    candidate.mkdir(parents=True)
    strategy_text = (
        "from quant_strategies.decisions import ExitPolicy, InstrumentRef, ObservationRef, PositionTarget, StrategyDecision\n"
        "def generate_decisions(rows, params):\n"
        "    return [StrategyDecision(\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='crypto_perp', symbol='BTC-PERP'),\n"
        "        decision_time=rows[0]['timestamp'],\n"
        "        as_of_time=rows[0]['timestamp'],\n"
        "        target=PositionTarget(direction='short', sizing_kind='target_weight', size=1.0),\n"
        "        exit_policy=ExitPolicy(max_hold_bars=1),\n"
        "        observations=(ObservationRef(symbol='BTC-PERP', timestamp=rows[0]['timestamp'], field='close', source='strategy_input'),),\n"
        "    )]\n"
    ).replace("size=1.0", "size=float(params.get('weight', 1.0))")
    (candidate / "strategy.py").write_text(strategy_text)
    backend_line = f'backend = "{backend}"\n' if backend is not None else ""
    window_blocks = "\n".join(
        f"""
[[windows]]
id = "{window_id}"
start = "2026-01-01"
end = "2026-06-30"
""".strip()
        for window_id in window_ids
    )
    (candidate / "validation.toml").write_text(
        f"""
strategy_path = "strategy.py"
strategy_id = "demo"
{backend_line}

{window_blocks}

[data]
kind = "crypto_perp_funding"
symbols = ["BTC-PERP"]
strict = true
start = "2026-01-01"
end = "2026-06-30"

[params]
weight = 1.0

[fill_model]
price = "close"
entry_lag_bars = 1
exit_lag_bars = 0

[cost_model]
fee_bps_per_side = 0.5
slippage_bps_per_side = 0.5

[readiness]
min_observations_per_decision = 1
required_observation_fields = ["close"]

[output]
results_dir = "validation_results/demo"
""".lstrip()
    )
    return candidate


def decision(strategy_id: str = "demo") -> StrategyDecision:
    return StrategyDecision(
        strategy_id=strategy_id,
        instrument=InstrumentRef(kind="crypto_perp", symbol="BTC-PERP"),
        decision_time=DECISION,
        as_of_time=AS_OF,
        target=PositionTarget(direction="short", sizing_kind="target_weight", size=1.0),
        exit_policy=ExitPolicy(max_hold_bars=1),
        observations=(ObservationRef(symbol="BTC-PERP", timestamp=AS_OF, field="close", source="strategy_input"),),
    )


def rows():
    return [
        {"symbol": "BTC-PERP", "timestamp": AS_OF, "available_at": AS_OF, "close": 100.0},
        {"symbol": "BTC-PERP", "timestamp": DECISION, "available_at": DECISION, "close": 101.0},
        {"symbol": "BTC-PERP", "timestamp": datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc), "close": 102.0},
    ]


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_run_validation_writes_watchlist_artifacts_for_one_positive_window(
    tmp_path: Path,
    monkeypatch,
):
    candidate = write_candidate(tmp_path)
    monkeypatch.setattr(
        "quant_strategies.runner.execution.load_data",
        lambda config: LoadedData(rows=rows()),
    )
    backend = FakeBackend(
        BackendRunResult(
            backend="fake",
            status="completed",
            metrics={"net_return": 0.02, "trade_count": 20},
            warnings=(),
            unsupported_semantics=(),
        )
    )

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path, backend=backend)

    assert result.success is True
    assert result.decision.decision == "watchlist"
    assert result.decision.reasons == ("paper_readiness_gates_failed",)
    assert "min_windows" in result.decision.failed_gates
    assert "min_total_trades" in result.decision.failed_gates
    assert "aggregate_realistic_net_positive" in result.decision.passed_gates
    assert result.result_dir is not None
    decision_payload = json.loads((result.result_dir / "validation_decision.json").read_text())
    assert decision_payload["decision"] == "watchlist"
    assert decision_payload["evidence_class"] == "validation_advisory"
    assert decision_payload["advisory_decision"] == "watchlist"
    assert decision_payload["promotion_eligible"] is False
    assert decision_payload["paper_trade_eligible"] is False
    assert decision_payload["live_eligible"] is False
    assert decision_payload["requires_manual_approval"] is True
    assert decision_payload["failure_details"] == []
    backend_summary = json.loads((result.result_dir / "backend_runs" / "summary.json").read_text())
    assert set(backend_summary["metric_semantics"]) == {"net_return", "trade_count"}
    assert backend_summary["metric_semantics"]["net_return"]["tolerance"] == 1e-9
    assert len(backend_summary["results"]) == 6
    assert len([item for item in backend_summary["results"] if item["required"]]) == 4
    base_decision_path = "backend_runs/decision_records/validation_2026_h1/base.jsonl"
    base_decision_file = result.result_dir / base_decision_path
    assert backend_summary["results"][0] == {
        "window_id": "validation_2026_h1",
        "scenario_id": "validation_2026_h1/base",
        "scenario_kind": "base",
        "required": True,
        "diagnostic_only": False,
        "decisions_regenerated": False,
        "decision_generation_status": "base_reused",
        "decision_count": 1,
        "decision_records_path": base_decision_path,
        "decision_records_sha256": file_sha256(base_decision_file),
        "result": {
            "backend": "fake",
            "status": "completed",
            "metrics": {"net_return": 0.02, "trade_count": 20},
            "warnings": [],
            "unsupported_semantics": [],
        },
    }
    base_decision_line = base_decision_file.read_text().splitlines()[0]
    assert base_decision_line.startswith('{"as_of_time":')
    assert ',"decision_time":' in base_decision_line
    assert '": ' not in base_decision_line
    assert read_jsonl(base_decision_file)[0]["target"]["size"] == 1.0
    main_decision_file = result.result_dir / "decision_records.jsonl"
    main_decision_line = main_decision_file.read_text().splitlines()[0]
    assert main_decision_line.startswith('{"as_of_time":')
    assert '": ' not in main_decision_line
    assert main_decision_file.exists()
    assert (result.result_dir / "data_audit.json").exists()
    assert (result.result_dir / "backend_capability_matrix.json").exists()
    assert (result.result_dir / "validation_config.toml").exists()
    assert (result.result_dir / "strategy_snapshot.py").exists()
    assert (result.result_dir / "decision_schema.json").exists()
    robustness_matrix = json.loads((result.result_dir / "robustness_matrix.json").read_text())
    assert robustness_matrix["decision"]["decision"] == "watchlist"
    assert "min_windows" in robustness_matrix["decision"]["failed_gates"]
    assert len(robustness_matrix["scenarios"]) == 6
    assert robustness_matrix["failure_details"] == []
    report = (result.result_dir / "validation_report.md").read_text()
    assert "Decision: `watchlist`" in report
    assert "Reasons: paper_readiness_gates_failed" in report
    assert "Passed gates: " in report
    assert "Failed gates: " in report
    assert "Gate details:" in report
    assert "- min_windows: 1 >= 2" in report
    assert "- min_total_trades: 20 >= 30" in report
    manifest = json.loads((result.result_dir / "validation_manifest.json").read_text())
    assert manifest["validation"]["strategy_id"] == "demo"
    assert manifest["validation"]["backend"] == "fake"
    assert manifest["validation"]["config_path"] == "validation.toml"
    assert manifest["strategy"]["path"] == "strategy.py"
    assert "research_manifest" not in manifest
    assert manifest["data"]["windows"][0]["status"] == "loaded"
    assert manifest["data"]["windows"][0]["row_count"] == len(rows())
    assert manifest["data"]["windows"][0]["rows_sha256"]
    assert manifest["backend"]["status_counts"] == {"completed": 6}
    capability_matrix = json.loads((result.result_dir / "backend_capability_matrix.json").read_text())
    assert capability_matrix == {
        "backend": "fake",
        "observed_unsupported_semantics": [],
        "semantics": [
            {
                "semantic": "test_double",
                "status": "supported",
                "details": "Deterministic validation test double.",
                "observed_unsupported": False,
            }
        ],
    }
    assert manifest["backend"]["capability_matrix"] == capability_matrix
    assert manifest["backend"]["scenarios"][0]["decision_records_path"] == base_decision_path
    assert manifest["backend"]["scenarios"][0]["decision_records_sha256"] == file_sha256(
        base_decision_file
    )
    assert manifest["core_hashes"]["decision_records.jsonl"] == file_sha256(
        result.result_dir / "decision_records.jsonl"
    )
    assert manifest["core_hashes"]["backend_capability_matrix.json"] == file_sha256(
        result.result_dir / "backend_capability_matrix.json"
    )
    assert manifest["core_hashes"]["validation_decision.json"] == file_sha256(
        result.result_dir / "validation_decision.json"
    )
    assert manifest["artifacts"]["backend_runs/summary.json"]["sha256"] == file_sha256(
        result.result_dir / "backend_runs" / "summary.json"
    )
    assert manifest["artifacts"][base_decision_path]["sha256"] == file_sha256(
        base_decision_file
    )


def test_run_validation_writes_mechanical_review_candidate_artifacts_for_two_robust_windows(
    tmp_path: Path,
    monkeypatch,
):
    candidate = write_candidate(
        tmp_path,
        window_ids=("validation_2026_h1", "validation_2026_h2"),
    )
    (candidate / "validation.toml").write_text(
        (candidate / "validation.toml").read_text()
        + """

[search_pressure]
candidate_count = 120
trial_count = 18
parameter_search_space = { weight = [0.5, 1.0, 1.5] }
selection_rule = "top risk-adjusted smoke score"
split_ids = ["validation_2026_h1", "validation_2026_h2"]
"""
    )
    monkeypatch.setattr(
        "quant_strategies.runner.execution.load_data",
        lambda config: LoadedData(rows=rows()),
    )
    backend = ScenarioAwareBackend(
        {
            "validation_2026_h1/base": BackendRunResult(
                backend="scenario_aware",
                status="completed",
                metrics={"net_return": 0.03, "trade_count": 20},
                warnings=(),
                unsupported_semantics=(),
            ),
            "validation_2026_h1/realistic_costs": BackendRunResult(
                backend="scenario_aware",
                status="completed",
                metrics={"net_return": 0.02, "trade_count": 20},
                warnings=(),
                unsupported_semantics=(),
            ),
            "validation_2026_h1/stressed_costs": BackendRunResult(
                backend="scenario_aware",
                status="completed",
                metrics={"net_return": -0.005, "trade_count": 20},
                warnings=(),
                unsupported_semantics=(),
            ),
            "validation_2026_h1/fill_lag_plus_1": BackendRunResult(
                backend="scenario_aware",
                status="completed",
                metrics={"net_return": -0.004, "trade_count": 20},
                warnings=(),
                unsupported_semantics=(),
            ),
            "validation_2026_h2/base": BackendRunResult(
                backend="scenario_aware",
                status="completed",
                metrics={"net_return": 0.025, "trade_count": 20},
                warnings=(),
                unsupported_semantics=(),
            ),
            "validation_2026_h2/realistic_costs": BackendRunResult(
                backend="scenario_aware",
                status="completed",
                metrics={"net_return": 0.015, "trade_count": 20},
                warnings=(),
                unsupported_semantics=(),
            ),
            "validation_2026_h2/stressed_costs": BackendRunResult(
                backend="scenario_aware",
                status="completed",
                metrics={"net_return": -0.005, "trade_count": 20},
                warnings=(),
                unsupported_semantics=(),
            ),
            "validation_2026_h2/fill_lag_plus_1": BackendRunResult(
                backend="scenario_aware",
                status="completed",
                metrics={"net_return": -0.004, "trade_count": 20},
                warnings=(),
                unsupported_semantics=(),
            ),
        }
    )

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path, backend=backend)

    assert result.success is True
    assert result.decision.decision == "mechanical_review_candidate"
    assert result.result_dir is not None
    assert backend.calls == 12
    decision_payload = json.loads((result.result_dir / "validation_decision.json").read_text())
    assert decision_payload["decision"] == "mechanical_review_candidate"
    assert decision_payload["advisory_decision"] == "mechanical_review_candidate"
    assert decision_payload["promotion_eligible"] is False
    assert decision_payload["paper_trade_eligible"] is False
    assert decision_payload["live_eligible"] is False
    assert decision_payload["requires_manual_approval"] is True
    assert decision_payload["failed_gates"] == []
    assert decision_payload["failure_details"] == []
    assert decision_payload["overfit_controls"] == {
        "candidate_count": 120,
        "trial_count": 18,
        "parameter_search_space": {"weight": [0.5, 1.0, 1.5]},
        "selection_rule": "top risk-adjusted smoke score",
        "split_ids": ["validation_2026_h1", "validation_2026_h2"],
        "deflated_sharpe": None,
        "monte_carlo": None,
    }
    assert set(decision_payload["passed_gates"]) >= {
        "mechanical_validation",
        "min_windows",
        "min_total_trades",
        "no_zero_trade_windows",
        "aggregate_realistic_net_positive",
        "positive_window_fraction",
        "stressed_net_floor",
        "fill_lag_net_floor",
    }
    assert decision_payload["gate_details"]["min_windows"] == "2 >= 2"
    assert decision_payload["gate_details"]["min_total_trades"] == "40 >= 30"

    robustness_matrix = json.loads((result.result_dir / "robustness_matrix.json").read_text())
    assert robustness_matrix["decision"]["decision"] == "mechanical_review_candidate"
    assert robustness_matrix["decision"]["overfit_controls"] == decision_payload["overfit_controls"]
    assert robustness_matrix["decision"]["failed_gates"] == []
    assert "gate_details" in robustness_matrix["decision"]
    assert len(robustness_matrix["scenarios"]) == 12
    assert robustness_matrix["failure_details"] == []

    report = (result.result_dir / "validation_report.md").read_text()
    assert "Decision: `mechanical_review_candidate`" in report
    assert "Reasons: none" in report
    assert "Passed gates: " in report
    assert "Failed gates: none" in report
    assert "Gate details:" in report
    assert "- min_total_trades: 40 >= 30" in report
    assert "- stressed_net_floor: -0.005 >= -0.02" in report


def test_run_validation_records_data_audit_failure(tmp_path: Path, monkeypatch):
    candidate = write_candidate(tmp_path)

    def raise_data_load_error(config: Any) -> LoadedData:
        raise DataLoadError("data load returned no rows")

    monkeypatch.setattr("quant_strategies.runner.execution.load_data", raise_data_load_error)

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path, backend=FakeBackend())

    assert result.decision.decision == "hard_no"
    assert "data_audit_failed" in result.decision.reasons
    assert result.result_dir is not None
    audit = json.loads((result.result_dir / "data_audit.json").read_text())
    assert audit["windows"][0]["passed"] is False
    assert audit["windows"][0]["violations"] == ["data_load_failed: data load returned no rows"]
    assert (result.result_dir / "validation_decision.json").exists()
    capability_matrix = json.loads((result.result_dir / "backend_capability_matrix.json").read_text())
    manifest = json.loads((result.result_dir / "validation_manifest.json").read_text())
    assert manifest["data"]["windows"][0]["status"] == "failed"
    assert manifest["data"]["windows"][0]["row_count"] == 0
    assert manifest["data"]["windows"][0]["rows_sha256"] is None
    assert manifest["backend"]["capability_matrix"] == capability_matrix
    assert manifest["core_hashes"]["backend_capability_matrix.json"] == file_sha256(
        result.result_dir / "backend_capability_matrix.json"
    )


def test_run_validation_records_strategy_import_failure_details(tmp_path: Path):
    candidate = write_candidate(tmp_path)
    (candidate / "validation.toml").write_text(
        (candidate / "validation.toml")
        .read_text()
        .replace('strategy_path = "strategy.py"', 'strategy_path = "missing.py"')
        + """

[search_pressure]
candidate_count = 20
trial_count = 5
selection_rule = "manual shortlist"
"""
    )

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path, backend=RecordingBackend())

    assert result.decision.decision == "hard_no"
    assert result.decision.reasons == ("strategy_import_failed",)
    assert result.result_dir is not None
    decision_payload = json.loads((result.result_dir / "validation_decision.json").read_text())
    assert decision_payload["failure_details"][0]["stage"] == "strategy_import"
    assert decision_payload["failure_details"][0]["type"] == "StrategyLoadError"
    assert decision_payload["failure_details"][0]["type"] != "StrategyExecutionError"
    assert "missing.py" in decision_payload["failure_details"][0]["message"]
    assert decision_payload["overfit_controls"]["candidate_count"] == 20
    assert decision_payload["overfit_controls"]["trial_count"] == 5
    assert decision_payload["overfit_controls"]["selection_rule"] == "manual shortlist"
    robustness_matrix = json.loads((result.result_dir / "robustness_matrix.json").read_text())
    assert robustness_matrix["failure_details"] == decision_payload["failure_details"]
    assert robustness_matrix["decision"]["overfit_controls"] == decision_payload["overfit_controls"]


def test_run_validation_records_backend_selection_failure_details(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    candidate = write_candidate(tmp_path)

    def fail_backend_selection(name: str):
        raise RuntimeError("backend registry down")

    monkeypatch.setattr("quant_strategies.validation.get_backend", fail_backend_selection)

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path)

    assert result.decision.decision == "hard_no"
    assert result.decision.reasons == ("backend_selection_failed",)
    assert result.result_dir is not None
    decision_payload = json.loads((result.result_dir / "validation_decision.json").read_text())
    assert decision_payload["failure_details"] == [
        {
            "stage": "backend_selection",
            "type": "RuntimeError",
            "message": "backend registry down",
        }
    ]


def test_run_validation_ignores_unconfigured_manifest_next_to_config(
    tmp_path: Path,
    monkeypatch,
):
    candidate = write_candidate(tmp_path)
    (candidate / "manifest.json").write_text(
        json.dumps(
            {
                "variants": [
                    {
                        "directory": ".",
                        "lifecycle_status": "draft",
                        "strategy_sha256": "stale-strategy-hash",
                        "validation_config_sha256": "stale-config-hash",
                    }
                ]
            }
        )
    )
    monkeypatch.setattr("quant_strategies.runner.execution.load_data", lambda config: LoadedData(rows=rows()))
    backend = RecordingBackend()

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path, backend=backend)

    assert result.decision.decision == "watchlist"
    assert backend.calls == 6
    assert result.result_dir is not None
    manifest = json.loads((result.result_dir / "validation_manifest.json").read_text())
    assert "research_manifest" not in manifest


def test_run_validation_requires_explicit_toml_path(tmp_path: Path):
    candidate = write_candidate(tmp_path)
    backend = RecordingBackend()

    with pytest.raises(ValidationConfigError, match="validation config path must be a TOML file"):
        run_validation(candidate, repo_root=tmp_path, backend=backend)

    assert backend.calls == 0


def test_run_validation_rejects_nested_config_strategy_escape(tmp_path: Path):
    candidate = write_candidate(tmp_path)
    nested = candidate / "variant"
    nested.mkdir()
    (nested / "validation.toml").write_text(
        (candidate / "validation.toml")
        .read_text()
        .replace('strategy_path = "strategy.py"', 'strategy_path = "../strategy.py"')
    )
    backend = RecordingBackend()

    with pytest.raises(ValidationConfigError, match="strategy_path must resolve inside config directory"):
        run_validation(nested / "validation.toml", repo_root=tmp_path, backend=backend)

    assert backend.calls == 0


def test_run_validation_rejects_external_config_pointing_at_candidate_strategy(tmp_path: Path):
    candidate = write_candidate(tmp_path)
    external_config = tmp_path / "external" / "validation.toml"
    external_config.parent.mkdir()
    external_config.write_text(
        (candidate / "validation.toml")
        .read_text()
        .replace('strategy_path = "strategy.py"', 'strategy_path = "../candidate/strategy.py"')
        .replace('results_dir = "validation_results/demo"', 'results_dir = "validation_results/external"')
    )
    backend = RecordingBackend()

    with pytest.raises(ValidationConfigError, match="strategy_path must resolve inside config directory"):
        run_validation(external_config, repo_root=tmp_path, backend=backend)

    assert backend.calls == 0


def test_run_validation_requires_readiness_at_config_load(tmp_path: Path):
    candidate = write_candidate(tmp_path)
    validation_text = (candidate / "validation.toml").read_text()
    validation_text = validation_text.replace(
        '\n[readiness]\nmin_observations_per_decision = 1\nrequired_observation_fields = ["close"]\n',
        "\n",
    )
    (candidate / "validation.toml").write_text(validation_text)
    backend = RecordingBackend()

    with pytest.raises(ValidationConfigError, match="readiness"):
        run_validation(candidate / "validation.toml", repo_root=tmp_path, backend=backend)

    assert backend.calls == 0


def test_run_validation_blocks_missing_required_observations(tmp_path: Path, monkeypatch):
    candidate = write_candidate(tmp_path)
    (candidate / "strategy.py").write_text(
        "from quant_strategies.decisions import ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision\n"
        "def generate_decisions(rows, params):\n"
        "    return [StrategyDecision(\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='crypto_perp', symbol='BTC-PERP'),\n"
        "        decision_time=rows[0]['timestamp'],\n"
        "        as_of_time=rows[0]['timestamp'],\n"
        "        target=PositionTarget(direction='short', sizing_kind='target_weight', size=1.0),\n"
        "        exit_policy=ExitPolicy(max_hold_bars=1),\n"
        "    )]\n"
    )
    monkeypatch.setattr("quant_strategies.runner.execution.load_data", lambda config: LoadedData(rows=rows()))
    backend = RecordingBackend()

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path, backend=backend)

    assert result.decision.decision == "hard_no"
    assert result.decision.reasons == ("validation_readiness_failed",)
    assert backend.calls == 0
    assert result.result_dir is not None
    audit = json.loads((result.result_dir / "data_audit.json").read_text())
    assert audit["windows"][0]["violations"] == [
        "decision[0] has 0 observations; requires at least 1",
        "decision[0] missing required observation fields: ['close']",
    ]


def test_run_validation_blocks_hidden_lookahead_strategy(tmp_path: Path, monkeypatch):
    candidate = write_candidate(tmp_path)
    (candidate / "strategy.py").write_text(
        "from quant_strategies.decisions import ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision\n"
        "def generate_decisions(rows, params):\n"
        "    future_rows = [row for row in rows if row['timestamp'] > rows[0]['timestamp']]\n"
        "    size = 2.0 if len(future_rows) > 1 else 1.0\n"
        "    return [StrategyDecision(\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='crypto_perp', symbol='BTC-PERP'),\n"
        "        decision_time=rows[0]['timestamp'],\n"
        "        as_of_time=rows[0]['timestamp'],\n"
        "        target=PositionTarget(direction='short', sizing_kind='target_weight', size=size),\n"
        "        exit_policy=ExitPolicy(max_hold_bars=1),\n"
        "    )]\n"
    )
    monkeypatch.setattr("quant_strategies.runner.execution.load_data", lambda config: LoadedData(rows=rows()))
    backend = RecordingBackend()

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path, backend=backend)

    assert result.decision.decision == "hard_no"
    assert result.decision.reasons == ("hidden_lookahead_detected",)
    assert backend.calls == 0
    assert result.result_dir is not None
    audit = json.loads((result.result_dir / "data_audit.json").read_text())
    assert audit["windows"][0]["passed"] is False
    assert audit["windows"][0]["violations"] == ["hidden_lookahead_detected"]


def test_run_validation_records_hidden_lookahead_replay_failure(tmp_path: Path, monkeypatch):
    candidate = write_candidate(tmp_path)
    (candidate / "strategy.py").write_text(
        "from quant_strategies.decisions import ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision\n"
        "def generate_decisions(rows, params):\n"
        "    if len(rows) < 3:\n"
        "        raise RuntimeError('need future row')\n"
        "    return [StrategyDecision(\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='crypto_perp', symbol='BTC-PERP'),\n"
        "        decision_time=rows[0]['timestamp'],\n"
        "        as_of_time=rows[0]['timestamp'],\n"
        "        target=PositionTarget(direction='short', sizing_kind='target_weight', size=1.0),\n"
        "        exit_policy=ExitPolicy(max_hold_bars=1),\n"
        "    )]\n"
    )
    monkeypatch.setattr("quant_strategies.runner.execution.load_data", lambda config: LoadedData(rows=rows()))
    backend = RecordingBackend()

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path, backend=backend)

    assert result.decision.decision == "hard_no"
    assert result.decision.reasons == ("hidden_lookahead_check_failed",)
    assert backend.calls == 0
    assert result.result_dir is not None
    audit = json.loads((result.result_dir / "data_audit.json").read_text())
    assert audit["windows"][0]["violations"] == [
        "hidden_lookahead_check_failed: RuntimeError: need future row"
    ]


def test_run_validation_rejects_wrong_strategy_id(tmp_path: Path, monkeypatch):
    candidate = write_candidate(tmp_path)
    backend = RecordingBackend()
    monkeypatch.setattr("quant_strategies.runner.execution.load_data", lambda config: LoadedData(rows=rows()))
    monkeypatch.setattr(
        "quant_strategies.runner.execution.load_strategy",
        lambda path, repo_root: lambda loaded_rows, params: [decision("other")],
    )

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path, backend=backend)

    assert result.decision.decision == "hard_no"
    assert backend.calls == 0
    assert result.result_dir is not None
    audit = json.loads((result.result_dir / "data_audit.json").read_text())
    assert audit["windows"][0]["violations"] == [
        "decision_strategy_id_mismatch[0]: expected demo, got other"
    ]


def test_run_validation_rejects_non_decision_output(tmp_path: Path, monkeypatch):
    candidate = write_candidate(tmp_path)
    backend = RecordingBackend()
    monkeypatch.setattr("quant_strategies.runner.execution.load_data", lambda config: LoadedData(rows=rows()))
    monkeypatch.setattr(
        "quant_strategies.runner.execution.load_strategy",
        lambda path, repo_root: lambda loaded_rows, params: "not decisions",
    )

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path, backend=backend)

    assert result.decision.decision == "hard_no"
    assert backend.calls == 0
    assert result.result_dir is not None
    audit = json.loads((result.result_dir / "data_audit.json").read_text())
    assert audit["windows"][0]["violations"] == ["invalid_decision_output"]
    manifest = json.loads((result.result_dir / "validation_manifest.json").read_text())
    assert manifest["data"]["windows"][0]["status"] == "loaded"
    assert manifest["data"]["windows"][0]["row_count"] == len(rows())
    assert manifest["data"]["windows"][0]["rows_sha256"] is not None


def test_run_validation_default_vectorbtpro_backend_fails_closed(tmp_path: Path, monkeypatch):
    candidate = write_candidate(tmp_path, backend=None)
    (candidate / "strategy.py").write_text(
        (candidate / "strategy.py")
        .read_text()
        .replace("decision_time=rows[0]['timestamp']", "decision_time=rows[1]['timestamp']")
        .replace("as_of_time=rows[0]['timestamp']", "as_of_time=rows[1]['timestamp']")
    )
    monkeypatch.setattr("quant_strategies.runner.execution.load_data", lambda config: LoadedData(rows=rows()))
    monkeypatch.setitem(sys.modules, "vectorbtpro", SimpleNamespace())

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path)

    assert result.decision.decision == "hard_no"
    assert result.result_dir is not None
    backend_summary = json.loads((result.result_dir / "backend_runs" / "summary.json").read_text())
    assert backend_summary["results"][0] == {
        "window_id": "validation_2026_h1",
        "scenario_id": "validation_2026_h1/base",
        "scenario_kind": "base",
        "required": True,
        "diagnostic_only": False,
        "decisions_regenerated": False,
        "decision_generation_status": "base_reused",
        "decision_count": 1,
        "decision_records_path": "backend_runs/decision_records/validation_2026_h1/base.jsonl",
        "decision_records_sha256": file_sha256(
            result.result_dir / "backend_runs/decision_records/validation_2026_h1/base.jsonl"
        ),
        "result": {
            "backend": "vectorbtpro",
            "status": "failed",
            "metrics": {},
            "warnings": ["unfillable_exit:BTC-PERP:2026-01-01T00:01:00+00:00"],
            "unsupported_semantics": [],
        },
    }


def test_run_validation_passes_valid_flat_decisions_to_backend(tmp_path: Path, monkeypatch):
    candidate = write_candidate(tmp_path, backend=None)
    (candidate / "strategy.py").write_text(
        "from quant_strategies.decisions import ExitPolicy, InstrumentRef, ObservationRef, PositionTarget, StrategyDecision\n"
        "def generate_decisions(rows, params):\n"
        "    return [StrategyDecision(\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='crypto_perp', symbol='BTC-PERP'),\n"
        "        decision_time=rows[0]['timestamp'],\n"
        "        as_of_time=rows[0]['timestamp'],\n"
        "        target=PositionTarget(direction='flat', sizing_kind='target_weight', size=0.0),\n"
        "        exit_policy=ExitPolicy(max_hold_bars=1),\n"
        "        observations=(ObservationRef(symbol='BTC-PERP', timestamp=rows[0]['timestamp'], field='close', source='strategy_input'),),\n"
        "    )]\n"
    )
    loaded_rows = rows() + [
        {
            "symbol": "BTC-PERP",
            "timestamp": datetime(2026, 1, 1, 0, 3, tzinfo=timezone.utc),
            "close": 103.0,
        }
    ]
    monkeypatch.setattr(
        "quant_strategies.runner.execution.load_data",
        lambda config: LoadedData(rows=loaded_rows),
    )

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path)

    assert result.decision.decision == "hard_no"
    assert result.decision.reasons == ("unsupported_semantics",)
    assert "strategy_generation_failed" not in result.decision.reasons
    assert result.result_dir is not None
    backend_summary = json.loads((result.result_dir / "backend_runs" / "summary.json").read_text())
    base_result = backend_summary["results"][0]
    assert base_result["decision_generation_status"] == "base_reused"
    assert base_result["decision_count"] == 1
    assert base_result["result"]["status"] == "unsupported"
    assert "flat_target" in base_result["result"]["unsupported_semantics"]


def test_run_validation_gates_on_each_required_matrix_scenario(tmp_path: Path, monkeypatch):
    candidate = write_candidate(tmp_path)
    monkeypatch.setattr("quant_strategies.runner.execution.load_data", lambda config: LoadedData(rows=rows()))
    backend = ScenarioAwareBackend(
        {
            "validation_2026_h1/stressed_costs": BackendRunResult(
                backend="scenario_aware",
                status="completed",
                metrics={"net_return": 0.01, "trade_count": 5},
                warnings=(),
                unsupported_semantics=(),
            )
        }
    )

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path, backend=backend)

    assert result.decision.decision == "hard_no"
    assert "insufficient_trades" in result.decision.reasons
    assert backend.calls == 6


def test_run_validation_loads_rows_once_per_window_and_reuses_across_matrix(
    tmp_path: Path, monkeypatch
):
    candidate = write_candidate(tmp_path, window_ids=("validation_2026_h1", "validation_2026_h2"))
    loaded_row_ids = []

    def load_data(config: Any) -> LoadedData:
        loaded_rows = rows()
        loaded_row_ids.append(id(loaded_rows))
        return LoadedData(rows=loaded_rows)

    monkeypatch.setattr("quant_strategies.runner.execution.load_data", load_data)
    backend = RecordingBackend()

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path, backend=backend)

    assert result.decision.decision == "watchlist"
    assert "min_total_trades" in result.decision.failed_gates
    assert len(loaded_row_ids) == 2
    assert backend.calls == 12
    h1_row_ids = {
        row_id
        for scenario_id, row_id in backend.row_ids_by_scenario
        if scenario_id.startswith("validation_2026_h1/")
    }
    h2_row_ids = {
        row_id
        for scenario_id, row_id in backend.row_ids_by_scenario
        if scenario_id.startswith("validation_2026_h2/")
    }
    assert loaded_row_ids[0] not in h1_row_ids
    assert loaded_row_ids[1] not in h2_row_ids
    assert len(h1_row_ids) == 1
    assert len(h2_row_ids) == 1
    assert h1_row_ids.isdisjoint(h2_row_ids)
    first_rows = backend.rows_by_scenario[0][1]
    with pytest.raises(TypeError):
        first_rows[0]["close"] = 999.0


def test_run_validation_passes_merged_scenario_config_to_backend(tmp_path: Path, monkeypatch):
    candidate = write_candidate(tmp_path)
    (candidate / "validation.toml").write_text(
        (candidate / "validation.toml")
        .read_text()
        .replace(
            'strict = true\nstart = "2026-01-01"\nend = "2026-06-30"',
            'strict = true\nstart = "2025-01-01"\nend = "2026-12-31"',
        )
    )
    monkeypatch.setattr("quant_strategies.runner.execution.load_data", lambda config: LoadedData(rows=rows()))
    backend = RecordingBackend()

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path, backend=backend)

    assert result.decision.decision == "watchlist"
    configs = {item.scenario_id: item for item in backend.configs}
    decision_sizes = {scenario_id: sizes for scenario_id, sizes in backend.decision_sizes_by_scenario}
    assert configs["validation_2026_h1/base"].params == {"weight": 1.0}
    assert configs["validation_2026_h1/base"].cost_model.fee_bps_per_side == 0.0
    assert configs["validation_2026_h1/base"].cost_model.slippage_bps_per_side == 0.0
    assert configs["validation_2026_h1/base"].fill_model.entry_lag_bars == 1
    assert configs["validation_2026_h1/base"].data.kind == "crypto_perp_funding"
    assert configs["validation_2026_h1/base"].data.start == date(2026, 1, 1)
    assert configs["validation_2026_h1/base"].data.end == date(2026, 6, 30)
    assert configs["validation_2026_h1/realistic_costs"].cost_model.fee_bps_per_side == 0.5
    assert configs["validation_2026_h1/stressed_costs"].cost_model.fee_bps_per_side == 1.0
    assert configs["validation_2026_h1/stressed_costs"].cost_model.slippage_bps_per_side == 1.0
    assert configs["validation_2026_h1/fill_lag_plus_1"].fill_model.entry_lag_bars == 2
    assert configs["validation_2026_h1/param_weight_up_10pct"].params == {"weight": 1.1}
    assert decision_sizes["validation_2026_h1/base"] == [1.0]
    assert decision_sizes["validation_2026_h1/param_weight_up_10pct"] == [1.1]
    summary = json.loads((result.result_dir / "backend_runs" / "summary.json").read_text())
    param_summary = {
        item["scenario_id"]: item
        for item in summary["results"]
        if item["scenario_kind"] == "parameter"
    }
    assert param_summary["validation_2026_h1/param_weight_up_10pct"]["diagnostic_only"] is True
    assert param_summary["validation_2026_h1/param_weight_up_10pct"]["decisions_regenerated"] is True
    assert (
        param_summary["validation_2026_h1/param_weight_up_10pct"]["decision_generation_status"]
        == "regenerated"
    )
    assert param_summary["validation_2026_h1/param_weight_up_10pct"]["decision_count"] == 1
    param_decision_path = param_summary["validation_2026_h1/param_weight_up_10pct"][
        "decision_records_path"
    ]
    param_decision_file = result.result_dir / param_decision_path
    assert file_sha256(param_decision_file) == param_summary[
        "validation_2026_h1/param_weight_up_10pct"
    ]["decision_records_sha256"]
    assert read_jsonl(param_decision_file)[0]["target"]["size"] == 1.1


def test_run_validation_records_failed_parameter_generation_without_backend_call(
    tmp_path: Path,
    monkeypatch,
):
    candidate = write_candidate(tmp_path)
    (candidate / "strategy.py").write_text(
        "from quant_strategies.decisions import ExitPolicy, InstrumentRef, ObservationRef, PositionTarget, StrategyDecision\n"
        "def validate_params(params):\n"
        "    if float(params['weight']) > 1.0:\n"
        "        raise ValueError('weight too high')\n"
        "    return dict(params)\n"
        "def generate_decisions(rows, params):\n"
        "    return [StrategyDecision(\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='crypto_perp', symbol='BTC-PERP'),\n"
        "        decision_time=rows[0]['timestamp'],\n"
        "        as_of_time=rows[0]['timestamp'],\n"
        "        target=PositionTarget(direction='short', sizing_kind='target_weight', size=float(params['weight'])),\n"
        "        exit_policy=ExitPolicy(max_hold_bars=1),\n"
        "        observations=(ObservationRef(symbol='BTC-PERP', timestamp=rows[0]['timestamp'], field='close', source='strategy_input'),),\n"
        "    )]\n"
    )
    monkeypatch.setattr("quant_strategies.runner.execution.load_data", lambda config: LoadedData(rows=rows()))
    backend = RecordingBackend()

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path, backend=backend)

    assert result.decision.decision == "watchlist"
    assert backend.calls == 5
    assert result.result_dir is not None
    summary = json.loads((result.result_dir / "backend_runs" / "summary.json").read_text())
    by_scenario = {item["scenario_id"]: item for item in summary["results"]}
    failed = by_scenario["validation_2026_h1/param_weight_up_10pct"]
    assert failed["diagnostic_only"] is True
    assert failed["decisions_regenerated"] is False
    assert failed["decision_generation_status"] == "failed"
    assert failed["decision_count"] == 0
    assert failed["decision_records_path"] is None
    assert failed["decision_records_sha256"] is None
    assert failed["result"]["status"] == "failed"
    assert failed["result"]["warnings"] == [
        "parameter_decision_generation_failed: weight too high"
    ]
    assert "validation_2026_h1/param_weight_up_10pct" not in {
        scenario_id for scenario_id, _ in backend.decision_sizes_by_scenario
    }


def test_run_validation_rejects_unknown_params_with_strategy_validator(
    tmp_path: Path, monkeypatch
):
    candidate = write_candidate(tmp_path)
    (candidate / "strategy.py").write_text(
        "from quant_strategies.decisions import ExitPolicy, InstrumentRef, ObservationRef, PositionTarget, StrategyDecision\n"
        "def validate_params(params):\n"
        "    extra = set(params).difference({'weight'})\n"
        "    if extra:\n"
        "        raise ValueError(f'unknown params: {sorted(extra)}')\n"
        "    return dict(params)\n"
        "def generate_decisions(rows, params):\n"
        "    return [StrategyDecision(\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='crypto_perp', symbol='BTC-PERP'),\n"
        "        decision_time=rows[0]['timestamp'],\n"
        "        as_of_time=rows[0]['timestamp'],\n"
        "        target=PositionTarget(direction='short', sizing_kind='target_weight', size=float(params['weight'])),\n"
        "        exit_policy=ExitPolicy(max_hold_bars=1),\n"
        "        observations=(ObservationRef(symbol='BTC-PERP', timestamp=rows[0]['timestamp'], field='close', source='strategy_input'),),\n"
        "    )]\n"
    )
    validation_config = (candidate / "validation.toml").read_text()
    (candidate / "validation.toml").write_text(
        validation_config.replace("weight = 1.0", "weight = 1.0\ntypo = 2.0")
    )
    monkeypatch.setattr("quant_strategies.runner.execution.load_data", lambda config: LoadedData(rows=rows()))
    backend = RecordingBackend()

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path, backend=backend)

    assert result.decision.decision == "hard_no"
    assert result.decision.reasons == ("param_validation_failed",)
    assert backend.calls == 0
    assert result.result_dir is not None
    audit = json.loads((result.result_dir / "data_audit.json").read_text())
    assert "param_validation_failed: unknown params" in audit["windows"][0]["violations"][0]
    report = (result.result_dir / "validation_report.md").read_text()
    assert "Failed gates: none" not in report
    assert "Failed gates: param_validation_failed" in report
    decision_payload = json.loads((result.result_dir / "validation_decision.json").read_text())
    assert decision_payload["failed_gates"] == ["param_validation_failed"]
    assert decision_payload["gate_details"]["param_validation_failed"] == "failed"
    assert decision_payload["failure_details"][0]["stage"] == "param_validation"
    assert decision_payload["failure_details"][0]["type"] == "ValueError"
    assert "unknown params" in decision_payload["failure_details"][0]["message"]


def test_run_validation_blocks_strategy_row_mutation(tmp_path: Path, monkeypatch):
    candidate = write_candidate(tmp_path)
    (candidate / "strategy.py").write_text(
        "def generate_decisions(rows, params):\n"
        "    rows[0]['close'] = 999.0\n"
        "    return []\n"
    )
    loaded_rows = rows()
    monkeypatch.setattr(
        "quant_strategies.runner.execution.load_data",
        lambda config: LoadedData(rows=loaded_rows),
    )

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path, backend=RecordingBackend())

    assert result.decision.decision == "hard_no"
    assert result.decision.reasons == ("strategy_generation_failed",)
    assert loaded_rows[0]["close"] == 100.0
    assert result.result_dir is not None
    audit = json.loads((result.result_dir / "data_audit.json").read_text())
    assert "strategy_generation_failed" in audit["windows"][0]["violations"][0]


def test_run_validation_blocks_strategy_param_mutation(tmp_path: Path, monkeypatch):
    candidate = write_candidate(tmp_path)
    (candidate / "strategy.py").write_text(
        "def generate_decisions(rows, params):\n"
        "    params['weight'] = 2.0\n"
        "    return []\n"
    )
    monkeypatch.setattr(
        "quant_strategies.runner.execution.load_data",
        lambda config: LoadedData(rows=rows()),
    )

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path, backend=RecordingBackend())

    assert result.decision.decision == "hard_no"
    assert result.decision.reasons == ("strategy_generation_failed",)
    assert result.result_dir is not None
    audit = json.loads((result.result_dir / "data_audit.json").read_text())
    assert "strategy_generation_failed" in audit["windows"][0]["violations"][0]


def test_run_validation_writes_failure_artifacts_for_strategy_generation_exception(
    tmp_path: Path, monkeypatch
):
    candidate = write_candidate(tmp_path)
    monkeypatch.setattr("quant_strategies.runner.execution.load_data", lambda config: LoadedData(rows=rows()))

    def raise_generation_error(loaded_rows: list[dict[str, Any]], params: dict[str, Any]):
        raise RuntimeError("signal code failed")

    monkeypatch.setattr(
        "quant_strategies.runner.execution.load_strategy",
        lambda path, repo_root: raise_generation_error,
    )

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path, backend=RecordingBackend())

    assert result.decision.decision == "hard_no"
    assert result.decision.reasons == ("strategy_generation_failed",)
    assert result.decision.failed_gates == ("strategy_generation_failed",)
    assert result.result_dir is not None
    assert (result.result_dir / "validation_decision.json").exists()
    report = (result.result_dir / "validation_report.md").read_text()
    assert "Failed gates: none" not in report
    assert "Failed gates: strategy_generation_failed" in report
    audit = json.loads((result.result_dir / "data_audit.json").read_text())
    assert audit["windows"][0]["violations"] == ["strategy_generation_failed: signal code failed"]
    summary = json.loads((result.result_dir / "backend_runs" / "summary.json").read_text())
    assert summary["results"] == []


def test_run_validation_writes_failure_artifacts_for_backend_exception(
    tmp_path: Path, monkeypatch
):
    candidate = write_candidate(tmp_path)
    monkeypatch.setattr("quant_strategies.runner.execution.load_data", lambda config: LoadedData(rows=rows()))
    backend = ExplodingBackend()

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path, backend=backend)

    assert result.decision.decision == "hard_no"
    assert result.decision.reasons == ("exploding_failed",)
    assert result.result_dir is not None
    assert (result.result_dir / "validation_decision.json").exists()
    assert (result.result_dir / "validation_report.md").exists()
    summary = json.loads((result.result_dir / "backend_runs" / "summary.json").read_text())
    assert len(summary["results"]) == 6
    assert summary["results"][0]["scenario_id"] == "validation_2026_h1/base"
    assert summary["results"][0]["result"]["status"] == "failed"
    assert summary["results"][0]["result"]["warnings"] == ["backend_exception: backend crashed"]


def test_run_validation_writes_failure_artifacts_for_malformed_backend_result(
    tmp_path: Path, monkeypatch
):
    candidate = write_candidate(tmp_path)
    monkeypatch.setattr("quant_strategies.runner.execution.load_data", lambda config: LoadedData(rows=rows()))
    backend = MalformedBackend()

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path, backend=backend)

    assert result.decision.decision == "hard_no"
    assert result.decision.reasons == ("malformed_failed",)
    assert result.result_dir is not None
    assert (result.result_dir / "validation_decision.json").exists()
    assert (result.result_dir / "validation_report.md").exists()
    summary = json.loads((result.result_dir / "backend_runs" / "summary.json").read_text())
    assert len(summary["results"]) == 6
    assert summary["results"][0]["scenario_id"] == "validation_2026_h1/base"
    assert summary["results"][0]["result"]["status"] == "failed"
    assert "invalid_backend_result" in summary["results"][0]["result"]["warnings"][0]


def test_run_validation_rejects_invalid_backend_status(tmp_path: Path, monkeypatch):
    candidate = write_candidate(tmp_path)
    monkeypatch.setattr("quant_strategies.runner.execution.load_data", lambda config: LoadedData(rows=rows()))
    backend = InvalidStatusBackend()

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path, backend=backend)

    assert result.decision.decision == "hard_no"
    assert result.decision.reasons == ("invalid_status_failed",)
    assert result.result_dir is not None
    summary = json.loads((result.result_dir / "backend_runs" / "summary.json").read_text())
    assert summary["results"][0]["result"]["status"] == "failed"
    assert "invalid_backend_result" in summary["results"][0]["result"]["warnings"][0]
    assert "status" in summary["results"][0]["result"]["warnings"][0]


def test_run_validation_propagates_backend_system_exit(tmp_path: Path, monkeypatch):
    candidate = write_candidate(tmp_path)
    monkeypatch.setattr("quant_strategies.runner.execution.load_data", lambda config: LoadedData(rows=rows()))

    with pytest.raises(SystemExit, match="backend exited"):
        run_validation(candidate / "validation.toml", repo_root=tmp_path, backend=ExitingBackend())


def test_run_validation_writes_failure_artifacts_for_strategy_generation_system_exit(
    tmp_path: Path, monkeypatch
):
    candidate = write_candidate(tmp_path)
    monkeypatch.setattr("quant_strategies.runner.execution.load_data", lambda config: LoadedData(rows=rows()))

    def exit_generation(loaded_rows: list[dict[str, Any]], params: dict[str, Any]):
        raise SystemExit("signal code exited")

    monkeypatch.setattr(
        "quant_strategies.runner.execution.load_strategy",
        lambda path, repo_root: exit_generation,
    )

    with pytest.raises(SystemExit, match="signal code exited"):
        run_validation(candidate / "validation.toml", repo_root=tmp_path, backend=RecordingBackend())


def test_run_validation_writes_failure_artifacts_for_strategy_import_system_exit(
    tmp_path: Path,
):
    candidate = write_candidate(tmp_path)
    (candidate / "strategy.py").write_text("raise SystemExit('import exited')\n")

    with pytest.raises(SystemExit, match="import exited"):
        run_validation(candidate / "validation.toml", repo_root=tmp_path, backend=RecordingBackend())


class RecordingBackend:
    name = "recording"

    def __init__(self) -> None:
        self.calls = 0
        self.configs = []
        self.row_ids_by_scenario = []
        self.rows_by_scenario = []
        self.decision_sizes_by_scenario = []

    def run(
        self,
        *,
        decisions: list[StrategyDecision],
        rows: list[dict[str, Any]],
        config: Any,
    ) -> BackendRunResult:
        self.calls += 1
        self.configs.append(config)
        self.row_ids_by_scenario.append((config.scenario_id, id(rows)))
        self.rows_by_scenario.append((config.scenario_id, rows))
        self.decision_sizes_by_scenario.append(
            (config.scenario_id, [decision.target.size for decision in decisions])
        )
        return BackendRunResult(
            backend=self.name,
            status="completed",
            metrics={"net_return": 0.01, "trade_count": 10},
            warnings=(),
            unsupported_semantics=(),
        )


class ScenarioAwareBackend(RecordingBackend):
    name = "scenario_aware"

    def __init__(self, overrides: dict[str, BackendRunResult]) -> None:
        super().__init__()
        self._overrides = overrides

    def run(
        self,
        *,
        decisions: list[StrategyDecision],
        rows: list[dict[str, Any]],
        config: Any,
    ) -> BackendRunResult:
        super().run(decisions=decisions, rows=rows, config=config)
        return self._overrides.get(
            config.scenario_id,
            BackendRunResult(
                backend=self.name,
                status="completed",
                metrics={"net_return": 0.01, "trade_count": 10},
                warnings=(),
                unsupported_semantics=(),
            ),
        )


class ExplodingBackend:
    name = "exploding"

    def run(
        self,
        *,
        decisions: list[StrategyDecision],
        rows: list[dict[str, Any]],
        config: Any,
    ) -> BackendRunResult:
        raise RuntimeError("backend crashed")


class MalformedBackend:
    name = "malformed"

    def run(
        self,
        *,
        decisions: list[StrategyDecision],
        rows: list[dict[str, Any]],
        config: Any,
    ) -> None:
        return None


class ExitingBackend:
    name = "exiting"

    def run(
        self,
        *,
        decisions: list[StrategyDecision],
        rows: list[dict[str, Any]],
        config: Any,
    ) -> BackendRunResult:
        raise SystemExit("backend exited")


class InvalidStatusBackend:
    name = "invalid_status"

    def run(
        self,
        *,
        decisions: list[StrategyDecision],
        rows: list[dict[str, Any]],
        config: Any,
    ) -> dict[str, object]:
        return {
            "backend": self.name,
            "status": "finished",
            "metrics": {"net_return": 0.01, "trade_count": 10},
            "warnings": (),
            "unsupported_semantics": (),
        }
