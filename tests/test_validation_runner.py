from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import quant_strategies.validation._pipeline as validation
from quant_strategies.causality import strict_replay_boundaries
from quant_strategies.core.data_loader import LoadedData
from quant_strategies.core.errors import DataLoadError
from quant_strategies.data_contract import NormalizedRows
from quant_strategies.decisions import (
    InstrumentRef,
    ObservationRef,
    TargetDecision,
)
from quant_strategies.validation._pipeline import _run_validation as run_validation
from quant_strategies.validation.backends import BackendRunResult

AS_OF = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
DECISION = datetime(2026, 1, 1, 0, 1, tzinfo=UTC)


class FakeBackend:
    name = "fake"

    def __init__(self, result: BackendRunResult | None = None) -> None:
        self._result = result or BackendRunResult(
            backend=self.name,
            status="completed",
            metrics={"net_return": 0.0, "trade_count": 0},
            warnings=(),
            unsupported_semantics=(),
        )

    def run(self, *, decisions, rows, config):
        return self._result


def _validated(generate):
    # Validation requires a strategy-level validate_params; injected test
    # strategies attach a trivial one so they reach the stage under test.
    generate.validate_params = lambda params: dict(params)
    return generate


def write_candidate(
    tmp_path: Path,
    *,
    window_ids: tuple[str, ...] = ("validation_2026_h1",),
    search_pressure: str = 'prior_search = "none"',
    extra_config: str = "",
) -> Path:
    candidate = tmp_path / "candidate"
    candidate.mkdir(parents=True)
    strategy_text = (
        "from quant_strategies.decisions import InstrumentRef, ObservationRef, TargetDecision\n"
        "def validate_params(params):\n"
        "    return dict(params)\n"
        "def generate_decisions(rows, params):\n"
        "    return [TargetDecision(\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='crypto_perp', symbol='BTC-PERP'),\n"
        "        decision_time=rows[0]['timestamp'],\n"
        "        as_of_time=rows[0]['timestamp'],\n"
        "        target=-float(params.get('weight', 1.0)),\n"
        "        observations=(ObservationRef(symbol='BTC-PERP', timestamp=rows[0]['timestamp'], field='close', source='strategy_input'),),\n"
        "    )]\n"
    )
    (candidate / "strategy.py").write_text(strategy_text)
    window_blocks = "\n".join(
        f"""
[[windows]]
id = "{window_id}"
start = "2026-01-01"
end = "2026-06-30"
""".strip()
        for window_id in window_ids
    )
    search_pressure_section = f"""
[search_pressure]
{search_pressure}
"""
    (candidate / "validation.toml").write_text(
        f"""
strategy_path = "strategy.py"
strategy_id = "demo"

{window_blocks}

[data]
kind = "bars"
dataset = "unit-test-bars"
symbols = ["BTC-PERP"]

[params]
weight = 1.0

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
{extra_config}

[readiness]
min_observations_per_decision = 1
required_observation_fields = ["close"]

[output]
results_dir = "validation_results/demo"
{search_pressure_section}
""".lstrip()
    )
    return candidate


def decision(strategy_id: str = "demo") -> TargetDecision:
    return TargetDecision(
        strategy_id=strategy_id,
        instrument=InstrumentRef(kind="crypto_perp", symbol="BTC-PERP"),
        decision_time=DECISION,
        as_of_time=AS_OF,
        target=-1.0,
        observations=(
            ObservationRef(
                symbol="BTC-PERP", timestamp=AS_OF, field="close", source="strategy_input"
            ),
        ),
    )


def rows():
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
    ]


def _bar(symbol: str, timestamp: datetime, close: float) -> dict[str, Any]:
    return {
        "symbol": symbol,
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


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def expected_row_records() -> list[dict[str, Any]]:
    return [
        {
            "available_at": AS_OF.isoformat(),
            "close": 100.0,
            "has_funding_event": False,
            "high": 100.0,
            "low": 100.0,
            "num_trades": 100,
            "open": 100.0,
            "symbol": "BTC-PERP",
            "timestamp": AS_OF.isoformat(),
            "volume": 1000.0,
            "vwap": 100.0,
        },
        {
            "available_at": DECISION.isoformat(),
            "close": 101.0,
            "has_funding_event": False,
            "high": 101.0,
            "low": 101.0,
            "num_trades": 100,
            "open": 101.0,
            "symbol": "BTC-PERP",
            "timestamp": DECISION.isoformat(),
            "volume": 1000.0,
            "vwap": 101.0,
        },
        {
            "available_at": datetime(2026, 1, 1, 0, 2, tzinfo=UTC).isoformat(),
            "close": 102.0,
            "has_funding_event": False,
            "high": 102.0,
            "low": 102.0,
            "num_trades": 100,
            "open": 102.0,
            "symbol": "BTC-PERP",
            "timestamp": datetime(2026, 1, 1, 0, 2, tzinfo=UTC).isoformat(),
            "volume": 1000.0,
            "vwap": 102.0,
        },
    ]


def test_run_validation_writes_mechanical_caution_artifacts_for_one_positive_window(
    tmp_path: Path,
    monkeypatch,
):
    candidate = write_candidate(tmp_path)
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
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

    assert not hasattr(result, "success")
    assert result.run_completed is True
    assert result.failure_stage is None
    assert result.decision.decision == "mechanical_caution"
    assert result.decision.reasons == ("mechanical_threshold_gates_failed",)
    assert "min_windows" in result.decision.failed_gates
    assert "min_total_trades" in result.decision.failed_gates
    assert "realistic_activity_positive" in result.decision.passed_gates
    assert result.result_dir is not None
    decision_payload = json.loads((result.result_dir / "validation_decision.json").read_text())
    assert decision_payload["decision"] == "mechanical_caution"
    assert decision_payload["evidence_class"] == "validation_advisory"
    assert decision_payload["advisory_decision"] == "mechanical_caution"
    assert decision_payload["paper_trade_eligible"] is False
    assert decision_payload["live_eligible"] is False
    assert decision_payload["requires_manual_approval"] is True
    assert decision_payload["failure_details"] == []
    backend_summary = json.loads((result.result_dir / "backend_runs" / "summary.json").read_text())
    assert set(backend_summary["metric_semantics"]) == {
        "net_return",
        "trade_count",
        "gross_return",
        "funding_return",
        "cost_return",
        "impact_return",
    }
    assert backend_summary["metric_semantics"]["net_return"]["tolerance"] is None
    assert len(backend_summary["results"]) == 4
    assert len([item for item in backend_summary["results"] if item["required"]]) == 4
    base_decision_path = "backend_runs/decision_records/validation_2026_h1/base.jsonl"
    base_decision_file = result.result_dir / base_decision_path
    assert backend_summary["results"][0] == {
        "window_id": "validation_2026_h1",
        "scenario_id": "validation_2026_h1/base",
        "scenario_kind": "base",
        "required": True,
        "scoreability_bearing": False,
        "diagnostic_only": True,
        "decision_count": 1,
        "decision_records_path": base_decision_path,
        "decision_records_sha256": file_sha256(base_decision_file),
        "trade_ledger_path": None,
        "trade_ledger_sha256": None,
        "result": {
            "backend": "fake",
            "status": "completed",
            "metrics": {"net_return": 0.02, "trade_count": 20},
            "warnings": [],
            "unsupported_semantics": [],
            "feasibility": {
                "feasible": True,
                "reason": None,
                "observed_gross": None,
                "observed_net": None,
                "detail": None,
            },
        },
    }
    base_decision_line = base_decision_file.read_text().splitlines()[0]
    assert base_decision_line.startswith('{"as_of_time":')
    assert ',"decision_time":' in base_decision_line
    assert '": ' not in base_decision_line
    assert read_jsonl(base_decision_file)[0]["target"] == -1.0
    main_decision_file = result.result_dir / "decision_records.jsonl"
    main_decision_line = main_decision_file.read_text().splitlines()[0]
    assert main_decision_line.startswith('{"as_of_time":')
    assert '": ' not in main_decision_line
    assert main_decision_file.exists()
    assert (result.result_dir / "data_audit.json").exists()
    data_audit = json.loads((result.result_dir / "data_audit.json").read_text())
    assert data_audit["windows"][0]["replay_scope"] == "complete"
    assert not (result.result_dir / "backend_capability_matrix.json").exists()
    assert (result.result_dir / "validation_config.toml").exists()
    assert (result.result_dir / "strategy_snapshot.py").exists()
    assert (result.result_dir / "decision_schema.json").exists()
    legacy_sensitivity_artifact = "robustness" + "_matrix.json"
    assert not (result.result_dir / legacy_sensitivity_artifact).exists()
    cost_fill_sensitivity = json.loads(
        (result.result_dir / "cost_fill_sensitivity.json").read_text()
    )
    assert cost_fill_sensitivity["decision"]["decision"] == "mechanical_caution"
    assert "min_windows" in cost_fill_sensitivity["decision"]["failed_gates"]
    assert len(cost_fill_sensitivity["scenarios"]) == 4
    assert cost_fill_sensitivity["failure_details"] == []
    report = (result.result_dir / "validation_report.md").read_text()
    assert "Decision: `mechanical_caution`" in report
    assert "Reasons: mechanical_threshold_gates_failed" in report
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
    row_path = "data_rows/validation_2026_h1.jsonl"
    row_file = result.result_dir / row_path
    assert manifest["data"]["windows"][0]["rows_path"] == row_path
    assert manifest["data"]["windows"][0]["rows_sha256"] == file_sha256(row_file)
    row_line = row_file.read_text().splitlines()[0]
    assert row_line.startswith('{"available_at":')
    assert '": ' not in row_line
    assert read_jsonl(row_file) == expected_row_records()
    assert manifest["backend"]["status_counts"] == {"completed": 4}
    assert "capability_matrix" not in manifest["backend"]
    assert manifest["backend"]["scenarios"][0]["decision_records_path"] == base_decision_path
    assert manifest["backend"]["scenarios"][0]["decision_records_sha256"] == file_sha256(
        base_decision_file
    )
    assert manifest["core_hashes"]["decision_records.jsonl"] == file_sha256(
        result.result_dir / "decision_records.jsonl"
    )
    assert "backend_capability_matrix.json" not in manifest["core_hashes"]
    assert manifest["core_hashes"]["validation_decision.json"] == file_sha256(
        result.result_dir / "validation_decision.json"
    )
    assert manifest["core_hashes"][row_path] == file_sha256(row_file)
    assert manifest["artifacts"]["backend_runs/summary.json"]["sha256"] == file_sha256(
        result.result_dir / "backend_runs" / "summary.json"
    )
    assert manifest["artifacts"][row_path]["sha256"] == file_sha256(row_file)
    assert manifest["artifacts"][base_decision_path]["sha256"] == file_sha256(base_decision_file)
    assert (result.result_dir / "environment.json").exists()
    assert "python" not in manifest
    assert "packages" not in manifest
    assert "environment.json" not in manifest["artifacts"]
    environment = json.loads((result.result_dir / "environment.json").read_text())
    assert environment["python"]["version"]
    assert "packages" in environment


def test_run_validation_bounded_causality_records_replay_scope(
    tmp_path: Path,
    monkeypatch,
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

    assert result.run_completed is True
    assert result.result_dir is not None
    audit = json.loads((result.result_dir / "data_audit.json").read_text())
    window = audit["windows"][0]
    assert window["replay_scope"] == "bounded"
    assert window["replay_mode"] == "strict"
    assert window["candidate_probe_count"] >= window["selected_probe_count"]
    assert window["timed_out"] is False


def test_retained_validation_strict_replay_detects_suppressed_same_bar_decision(
    tmp_path: Path,
    monkeypatch,
):
    candidate = write_candidate(tmp_path)
    (candidate / "strategy.py").write_text(
        "from quant_strategies.decisions import InstrumentRef, ObservationRef, TargetDecision\n"
        "def validate_params(params):\n"
        "    return dict(params)\n"
        "def generate_decisions(rows, params):\n"
        "    if any(row['timestamp'].isoformat() == '2026-01-01T00:02:00+00:00' for row in rows):\n"
        "        return []\n"
        "    return [TargetDecision(\n"
        "        decision_id='demo:suppressed',\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='crypto_perp', symbol='BTC-PERP'),\n"
        "        decision_time=rows[0]['timestamp'],\n"
        "        as_of_time=rows[0]['timestamp'],\n"
        "        target=-(1.0),\n"
        "        observations=(ObservationRef(symbol='BTC-PERP', timestamp=rows[0]['timestamp'], field='close', source='strategy_input'),),\n"
        "    )]\n"
    )
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )
    backend = RecordingBackend()

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path, backend=backend)

    assert result.decision.decision == "mechanical_fail"
    assert result.decision.reasons == ("hidden_lookahead_suppression_detected",)
    assert result.failure_stage == "data_audit"
    audit = json.loads((result.result_dir / "data_audit.json").read_text())
    assert audit["windows"][0]["violations"] == ["hidden_lookahead_suppression_detected"]


def test_validation_marks_skipped_strict_probe_as_incomplete_evidence(
    tmp_path: Path,
    monkeypatch,
):
    candidate = write_candidate(tmp_path)
    (candidate / "strategy.py").write_text(
        "def validate_params(params):\n"
        "    return dict(params)\n"
        "def generate_decisions(rows, params):\n"
        "    if not any(row['timestamp'].isoformat() == '2026-01-01T00:02:00+00:00' for row in rows):\n"
        "        raise RuntimeError('prefix too short')\n"
        "    return []\n"
    )
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )
    backend = RecordingBackend()

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path, backend=backend)

    assert result.decision.decision == "mechanical_fail"
    assert result.decision.reasons == ("strict_suppression_replay_not_verified",)
    assert result.failure_stage == "data_audit"
    assert backend.calls == 0
    audit = json.loads((result.result_dir / "data_audit.json").read_text())
    window = audit["windows"][0]
    assert window["violations"] == ["strict_suppression_replay_not_verified"]
    assert window["deterministic_replay_verified"] is True
    assert window["emitted_replay_verified"] is True
    assert window["strict_suppression_verified"] is False
    assert window["skipped_probe_count"] > 0
    assert "RuntimeError: prefix too short" in window["skipped_probe_reasons"]


def test_validation_rejects_nondeterministic_strategy_generation(
    tmp_path: Path,
    monkeypatch,
):
    candidate = write_candidate(tmp_path)
    (candidate / "strategy.py").write_text(
        "from quant_strategies.decisions import InstrumentRef, ObservationRef, TargetDecision\n"
        "CALLS = 0\n"
        "def validate_params(params):\n"
        "    return dict(params)\n"
        "def generate_decisions(rows, params):\n"
        "    global CALLS\n"
        "    CALLS += 1\n"
        "    size = 1.0 if CALLS % 2 else 0.5\n"
        "    return [TargetDecision(\n"
        "        decision_id='demo:stable-id',\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='crypto_perp', symbol='BTC-PERP'),\n"
        "        decision_time=rows[0]['timestamp'],\n"
        "        as_of_time=rows[0]['timestamp'],\n"
        "        target=-(size),\n"
        "        observations=(ObservationRef(symbol='BTC-PERP', timestamp=rows[0]['timestamp'], field='close', source='strategy_input'),),\n"
        "    )]\n"
    )
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )
    backend = RecordingBackend()

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path, backend=backend)

    assert result.decision.decision == "mechanical_fail"
    assert result.decision.reasons == ("strategy_generation_not_deterministic",)
    assert result.failure_stage == "data_audit"
    assert backend.calls == 0
    audit = json.loads((result.result_dir / "data_audit.json").read_text())
    window = audit["windows"][0]
    assert window["violations"] == ["strategy_generation_not_deterministic"]
    assert window["deterministic_replay_verified"] is False
    assert window["emitted_replay_verified"] is False
    assert window["strict_suppression_verified"] is False


def test_validation_strict_replay_detects_suppression_even_with_mechanical_thresholds_disabled(
    tmp_path: Path,
    monkeypatch,
):
    # F3: strict suppression replay is decoupled from mechanical_thresholds. Even with
    # mechanical_thresholds explicitly disabled, a peek-to-suppress strategy is caught on
    # the default validation path (previously this path ran emitted-only replay).
    candidate = write_candidate(tmp_path)
    (candidate / "validation.toml").write_text(
        (candidate / "validation.toml").read_text() + "\n[mechanical_thresholds]\nenabled = false\n"
    )
    (candidate / "strategy.py").write_text(
        "from quant_strategies.decisions import InstrumentRef, ObservationRef, TargetDecision\n"
        "def validate_params(params):\n"
        "    return dict(params)\n"
        "def generate_decisions(rows, params):\n"
        "    if any(row['timestamp'].isoformat() == '2026-01-01T00:02:00+00:00' for row in rows):\n"
        "        return []\n"
        "    return [TargetDecision(\n"
        "        decision_id='demo:suppressed',\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='crypto_perp', symbol='BTC-PERP'),\n"
        "        decision_time=rows[0]['timestamp'],\n"
        "        as_of_time=rows[0]['timestamp'],\n"
        "        target=-(1.0),\n"
        "        observations=(ObservationRef(symbol='BTC-PERP', timestamp=rows[0]['timestamp'], field='close', source='strategy_input'),),\n"
        "    )]\n"
    )
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path)

    assert result.decision.decision == "mechanical_fail"
    assert result.decision.reasons == ("hidden_lookahead_suppression_detected",)
    assert result.failure_stage == "data_audit"


def test_validation_event_sink_marks_semantic_audit_and_causality_failures(
    tmp_path: Path,
    monkeypatch,
):
    candidate = write_candidate(tmp_path)
    (candidate / "strategy.py").write_text(
        "from quant_strategies.decisions import InstrumentRef, ObservationRef, TargetDecision\n"
        "def validate_params(params):\n"
        "    return dict(params)\n"
        "def generate_decisions(rows, params):\n"
        "    return [TargetDecision(\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='crypto_perp', symbol='BTC-PERP'),\n"
        "        decision_time=rows[0]['timestamp'],\n"
        "        as_of_time=rows[0]['timestamp'],\n"
        "        target=-(1.0),\n"
        "        observations=(ObservationRef(symbol='BTC-PERP', timestamp=rows[-1]['timestamp'], field='close', source='strategy_input'),),\n"
        "    )]\n"
    )
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )
    events: list[dict[str, object]] = []

    result = run_validation(
        candidate / "validation.toml", repo_root=tmp_path, event_sink=events.append
    )

    assert result.decision.decision == "mechanical_fail"
    assert any(event["stage"] == "data_audit" and event["status"] == "failed" for event in events)
    assert not any(
        event["stage"] == "data_audit" and event["status"] == "completed" for event in events
    )

    suppressed = write_candidate(tmp_path / "suppressed")
    (suppressed / "strategy.py").write_text(
        "from quant_strategies.decisions import InstrumentRef, ObservationRef, TargetDecision\n"
        "def validate_params(params):\n"
        "    return dict(params)\n"
        "def generate_decisions(rows, params):\n"
        "    if any(row['timestamp'].isoformat() == '2026-01-01T00:02:00+00:00' for row in rows):\n"
        "        return []\n"
        "    return [TargetDecision(\n"
        "        decision_id='demo:suppressed',\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='crypto_perp', symbol='BTC-PERP'),\n"
        "        decision_time=rows[0]['timestamp'],\n"
        "        as_of_time=rows[0]['timestamp'],\n"
        "        target=-(1.0),\n"
        "        observations=(ObservationRef(symbol='BTC-PERP', timestamp=rows[0]['timestamp'], field='close', source='strategy_input'),),\n"
        "    )]\n"
    )
    events.clear()

    result = run_validation(
        suppressed / "validation.toml", repo_root=tmp_path / "suppressed", event_sink=events.append
    )

    assert result.decision.decision == "mechanical_fail"
    assert any(
        event["stage"] == "causality_check" and event["status"] == "failed" for event in events
    )
    assert not any(
        event["stage"] == "causality_check" and event["status"] == "completed" for event in events
    )


def test_strict_replay_boundaries_dedupe_shared_row_information_sets():
    eth_rows = [
        {
            **item,
            "symbol": "ETH-PERP",
        }
        for item in rows()
    ]
    normalized = NormalizedRows.from_rows(
        SimpleNamespace(
            data=SimpleNamespace(kind="crypto_perp_funding"),
            fill_model=SimpleNamespace(price="close"),
            capacity_model=SimpleNamespace(mode="off"),
        ),
        [*rows(), *eth_rows],
    )

    boundaries = strict_replay_boundaries(normalized, [])

    assert [
        (boundary.as_of_time, boundary.decision_time, boundary.symbols) for boundary in boundaries
    ] == [
        (AS_OF, DECISION, frozenset({"BTC-PERP", "ETH-PERP"})),
        (
            DECISION,
            datetime(2026, 1, 1, 0, 2, tzinfo=UTC),
            frozenset({"BTC-PERP", "ETH-PERP"}),
        ),
        (
            datetime(2026, 1, 1, 0, 2, tzinfo=UTC),
            datetime(2026, 1, 1, 0, 2, tzinfo=UTC),
            frozenset({"BTC-PERP", "ETH-PERP"}),
        ),
    ]


def test_validation_row_snapshot_hash_uses_written_payload(
    tmp_path: Path,
    monkeypatch,
):
    candidate = write_candidate(tmp_path)
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
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
    original_file_sha256 = validation.file_sha256

    def forbid_row_file_hash(path: Path) -> str:
        if "data_rows" in path.parts:
            raise AssertionError("row snapshot hash should use the written payload")
        return original_file_sha256(path)

    monkeypatch.setattr(validation, "file_sha256", forbid_row_file_hash)

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path, backend=backend)

    assert result.result_dir is not None
    manifest = json.loads((result.result_dir / "validation_manifest.json").read_text())
    row_path = "data_rows/validation_2026_h1.jsonl"
    row_file = result.result_dir / row_path
    assert manifest["data"]["windows"][0]["rows_path"] == row_path
    assert manifest["data"]["windows"][0]["rows_sha256"] == file_sha256(row_file)
    assert read_jsonl(row_file) == expected_row_records()


def test_run_validation_downgrades_search_pressure_candidate_artifacts(
    tmp_path: Path,
    monkeypatch,
):
    candidate = write_candidate(
        tmp_path,
        window_ids=("validation_2026_h1", "validation_2026_h2"),
        search_pressure="""
prior_search = "known"
candidate_count = 120
trial_count = 18
parameter_search_space = { weight = [0.5, 1.0, 1.5] }
selection_rule = "top risk-adjusted trade result"
split_ids = ["validation_2026_h1", "validation_2026_h2"]
""".strip(),
    )
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
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

    assert result.run_completed is True
    assert result.decision.decision == "mechanical_caution"
    assert result.decision.reasons == ("multiple_testing_not_corrected_advisory_only",)
    assert result.result_dir is not None
    assert backend.calls == 8
    decision_payload = json.loads((result.result_dir / "validation_decision.json").read_text())
    assert decision_payload["decision"] == "mechanical_caution"
    assert decision_payload["advisory_decision"] == "mechanical_caution"
    assert decision_payload["paper_trade_eligible"] is False
    assert decision_payload["live_eligible"] is False
    assert decision_payload["requires_manual_approval"] is True
    assert decision_payload["reasons"] == ["multiple_testing_not_corrected_advisory_only"]
    assert decision_payload["failed_gates"] == []
    assert decision_payload["failure_details"] == []
    assert decision_payload["overfit_controls"] == {
        "prior_search": "known",
        "candidate_count": 120,
        "trial_count": 18,
        "parameter_search_space": {"weight": [0.5, 1.0, 1.5]},
        "selection_rule": "top risk-adjusted trade result",
        "split_ids": ["validation_2026_h1", "validation_2026_h2"],
    }
    assert set(decision_payload["passed_gates"]) >= {
        "mechanical_validation",
        "min_windows",
        "min_total_trades",
        "no_zero_trade_windows",
        "realistic_activity_positive",
        "positive_window_fraction",
        "stressed_activity_floor",
        "fill_lag_activity_floor",
    }
    assert decision_payload["gate_details"]["min_windows"] == "2 >= 2"
    assert decision_payload["gate_details"]["min_total_trades"] == "40 >= 30"

    cost_fill_sensitivity = json.loads(
        (result.result_dir / "cost_fill_sensitivity.json").read_text()
    )
    assert cost_fill_sensitivity["decision"]["decision"] == "mechanical_caution"
    assert cost_fill_sensitivity["decision"]["reasons"] == [
        "multiple_testing_not_corrected_advisory_only"
    ]
    assert (
        cost_fill_sensitivity["decision"]["overfit_controls"]
        == decision_payload["overfit_controls"]
    )
    assert cost_fill_sensitivity["decision"]["failed_gates"] == []
    assert "gate_details" in cost_fill_sensitivity["decision"]
    assert len(cost_fill_sensitivity["scenarios"]) == 8
    assert cost_fill_sensitivity["failure_details"] == []

    report = (result.result_dir / "validation_report.md").read_text()
    assert "Decision: `mechanical_caution`" in report
    assert "Reasons: multiple_testing_not_corrected_advisory_only" in report
    assert "Passed gates: " in report
    assert "Failed gates: none" in report
    assert "Gate details:" in report
    assert "- min_total_trades: 40 >= 30" in report
    assert "- stressed_activity_floor: -0.005 >= -0.02" in report


def test_run_validation_records_data_audit_failure(tmp_path: Path, monkeypatch):
    candidate = write_candidate(tmp_path)

    def raise_data_load_error(config: Any, **_kwargs: object) -> LoadedData:
        raise DataLoadError("data load returned no rows")

    monkeypatch.setattr("quant_strategies.core.execution.load_data", raise_data_load_error)

    result = run_validation(
        candidate / "validation.toml", repo_root=tmp_path, backend=FakeBackend()
    )

    assert result.decision.decision == "mechanical_fail"
    assert "data_audit_failed" in result.decision.reasons
    assert result.result_dir is not None
    audit = json.loads((result.result_dir / "data_audit.json").read_text())
    assert audit["windows"][0]["passed"] is False
    assert audit["windows"][0]["violations"] == ["data_load_failed: data load returned no rows"]
    assert (result.result_dir / "validation_decision.json").exists()
    manifest = json.loads((result.result_dir / "validation_manifest.json").read_text())
    assert manifest["data"]["windows"][0]["status"] == "failed"
    assert manifest["data"]["windows"][0]["row_count"] == 0
    assert manifest["data"]["windows"][0]["rows_path"] is None
    assert manifest["data"]["windows"][0]["rows_sha256"] is None
    assert not (result.result_dir / "data_rows").exists()
    assert not (result.result_dir / "backend_capability_matrix.json").exists()
    assert "capability_matrix" not in manifest["backend"]
    assert "backend_capability_matrix.json" not in manifest["core_hashes"]


def test_run_validation_normalizes_nonfinite_research_fields_in_row_snapshot(
    tmp_path: Path,
    monkeypatch,
):
    candidate = write_candidate(tmp_path)
    loaded_rows = rows()
    loaded_rows[0]["research_nan"] = float("nan")
    loaded_rows[1]["research_inf"] = float("inf")
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=loaded_rows),
    )

    result = run_validation(
        candidate / "validation.toml", repo_root=tmp_path, backend=FakeBackend()
    )

    assert result.result_dir is not None
    manifest = json.loads((result.result_dir / "validation_manifest.json").read_text())
    row_path = manifest["data"]["windows"][0]["rows_path"]
    row_file = result.result_dir / row_path
    row_records = read_jsonl(row_file)
    assert row_records[0]["research_nan"] is None
    assert row_records[1]["research_inf"] is None
    assert manifest["data"]["windows"][0]["rows_sha256"] == file_sha256(row_file)
    assert manifest["core_hashes"][row_path] == file_sha256(row_file)


def test_run_validation_records_strategy_import_failure_details(tmp_path: Path):
    candidate = write_candidate(
        tmp_path,
        search_pressure="""
prior_search = "known"
candidate_count = 20
trial_count = 5
selection_rule = "manual shortlist"
""".strip(),
    )
    (candidate / "validation.toml").write_text(
        (candidate / "validation.toml")
        .read_text()
        .replace('strategy_path = "strategy.py"', 'strategy_path = "missing.py"')
    )

    result = run_validation(
        candidate / "validation.toml", repo_root=tmp_path, backend=RecordingBackend()
    )

    assert result.decision.decision == "mechanical_fail"
    assert result.decision.reasons == ("strategy_import_failed",)
    assert result.result_dir is not None
    decision_payload = json.loads((result.result_dir / "validation_decision.json").read_text())
    assert decision_payload["failure_details"][0]["stage"] == "strategy_import"
    assert decision_payload["failure_details"][0]["type"] == "StrategyLoadError"
    assert decision_payload["failure_details"][0]["type"] != "StrategyExecutionError"
    assert "missing.py" in decision_payload["failure_details"][0]["message"]
    assert decision_payload["overfit_controls"]["prior_search"] == "known"
    assert decision_payload["overfit_controls"]["candidate_count"] == 20
    assert decision_payload["overfit_controls"]["trial_count"] == 5
    assert decision_payload["overfit_controls"]["selection_rule"] == "manual shortlist"
    cost_fill_sensitivity = json.loads(
        (result.result_dir / "cost_fill_sensitivity.json").read_text()
    )
    assert cost_fill_sensitivity["failure_details"] == decision_payload["failure_details"]
    assert (
        cost_fill_sensitivity["decision"]["overfit_controls"]
        == decision_payload["overfit_controls"]
    )


def test_validation_pipeline_does_not_use_backend_registry():
    import quant_strategies.validation._pipeline as pipeline

    assert not hasattr(pipeline, "get_backend")


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
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )
    backend = RecordingBackend()

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path, backend=backend)

    assert result.decision.decision == "mechanical_caution"
    assert backend.calls == 4
    assert result.result_dir is not None
    manifest = json.loads((result.result_dir / "validation_manifest.json").read_text())
    assert "research_manifest" not in manifest


def test_run_validation_requires_explicit_toml_path(tmp_path: Path):
    candidate = write_candidate(tmp_path)
    backend = RecordingBackend()

    result = run_validation(candidate, repo_root=tmp_path, backend=backend)

    assert result.result_dir is None
    assert result.run_completed is False
    assert result.failure_stage == "config_load"
    assert result.decision.decision == "mechanical_fail"
    assert result.decision.reasons == ("validation_config_failed",)
    assert "validation config path must be a TOML file" in result.message
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

    result = run_validation(nested / "validation.toml", repo_root=tmp_path, backend=backend)

    assert result.result_dir is None
    assert result.run_completed is False
    assert result.failure_stage == "config_load"
    assert result.decision.reasons == ("validation_config_failed",)
    assert "strategy_path must resolve inside config directory" in result.message
    assert backend.calls == 0


def test_run_validation_rejects_external_config_pointing_at_candidate_strategy(tmp_path: Path):
    candidate = write_candidate(tmp_path)
    external_config = tmp_path / "external" / "validation.toml"
    external_config.parent.mkdir()
    external_config.write_text(
        (candidate / "validation.toml")
        .read_text()
        .replace('strategy_path = "strategy.py"', 'strategy_path = "../candidate/strategy.py"')
        .replace(
            'results_dir = "validation_results/demo"', 'results_dir = "validation_results/external"'
        )
    )
    backend = RecordingBackend()

    result = run_validation(external_config, repo_root=tmp_path, backend=backend)

    assert result.result_dir is None
    assert result.run_completed is False
    assert result.failure_stage == "config_load"
    assert result.decision.reasons == ("validation_config_failed",)
    assert "strategy_path must resolve inside config directory" in result.message
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

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path, backend=backend)

    assert result.result_dir is None
    assert result.run_completed is False
    assert result.failure_stage == "config_load"
    assert result.decision.reasons == ("validation_config_failed",)
    assert "readiness" in result.message
    assert backend.calls == 0


def test_run_validation_blocks_missing_required_observations(tmp_path: Path, monkeypatch):
    candidate = write_candidate(tmp_path)
    (candidate / "strategy.py").write_text(
        "from quant_strategies.decisions import InstrumentRef, TargetDecision\n"
        "def validate_params(params):\n"
        "    return dict(params)\n"
        "def generate_decisions(rows, params):\n"
        "    return [TargetDecision(\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='crypto_perp', symbol='BTC-PERP'),\n"
        "        decision_time=rows[0]['timestamp'],\n"
        "        as_of_time=rows[0]['timestamp'],\n"
        "        target=-(1.0),\n"
        "    )]\n"
    )
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )
    backend = RecordingBackend()

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path, backend=backend)

    assert result.decision.decision == "mechanical_fail"
    assert result.decision.reasons == ("validation_readiness_failed",)
    assert backend.calls == 0
    assert result.result_dir is not None
    audit = json.loads((result.result_dir / "data_audit.json").read_text())
    assert audit["windows"][0]["violations"] == [
        "decision[0] has 0 observations; requires at least 1",
        "decision[0] has 0 distinct observation symbols; requires at least 1",
        "decision[0] missing required observation fields: ['close']",
    ]


def test_run_validation_applies_crypto_perp_funding_readiness_defaults(
    tmp_path: Path,
    monkeypatch,
):
    candidate = write_candidate(tmp_path)
    (candidate / "validation.toml").write_text(
        (candidate / "validation.toml")
        .read_text()
        .replace('kind = "bars"\ndataset = "unit-test-bars"', 'kind = "crypto_perp_funding"')
    )
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )
    backend = RecordingBackend()

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path, backend=backend)

    assert result.decision.decision == "mechanical_fail"
    assert result.decision.reasons == ("validation_readiness_failed",)
    assert result.failure_stage == "validation_readiness"
    assert backend.calls == 0
    assert result.result_dir is not None
    audit = json.loads((result.result_dir / "data_audit.json").read_text())
    assert audit["windows"][0]["violations"] == [
        "decision[0] missing required observation fields: "
        "['funding_rate', 'funding_timestamp', 'has_funding_event']"
    ]


def test_run_validation_blocks_hidden_lookahead_strategy(tmp_path: Path, monkeypatch):
    candidate = write_candidate(tmp_path)
    (candidate / "strategy.py").write_text(
        "from quant_strategies.decisions import InstrumentRef, TargetDecision\n"
        "def validate_params(params):\n"
        "    return dict(params)\n"
        "def generate_decisions(rows, params):\n"
        "    future_rows = [row for row in rows if row['timestamp'] > rows[0]['timestamp']]\n"
        "    size = 2.0 if len(future_rows) > 1 else 1.0\n"
        "    return [TargetDecision(\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='crypto_perp', symbol='BTC-PERP'),\n"
        "        decision_time=rows[0]['timestamp'],\n"
        "        as_of_time=rows[0]['timestamp'],\n"
        "        target=-(size),\n"
        "    )]\n"
    )
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )
    backend = RecordingBackend()

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path, backend=backend)

    assert result.decision.decision == "mechanical_fail"
    assert result.decision.reasons == ("hidden_lookahead_detected",)
    assert backend.calls == 0
    assert result.result_dir is not None
    audit = json.loads((result.result_dir / "data_audit.json").read_text())
    assert audit["windows"][0]["passed"] is False
    assert audit["windows"][0]["violations"] == ["hidden_lookahead_detected"]


def test_run_validation_records_hidden_lookahead_replay_failure(tmp_path: Path, monkeypatch):
    candidate = write_candidate(tmp_path)
    (candidate / "strategy.py").write_text(
        "from quant_strategies.decisions import InstrumentRef, TargetDecision\n"
        "def validate_params(params):\n"
        "    return dict(params)\n"
        "def generate_decisions(rows, params):\n"
        "    if len(rows) < 3:\n"
        "        raise RuntimeError('need future row')\n"
        "    return [TargetDecision(\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='crypto_perp', symbol='BTC-PERP'),\n"
        "        decision_time=rows[0]['timestamp'],\n"
        "        as_of_time=rows[0]['timestamp'],\n"
        "        target=-(1.0),\n"
        "    )]\n"
    )
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )
    backend = RecordingBackend()

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path, backend=backend)

    assert result.decision.decision == "mechanical_fail"
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
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )
    monkeypatch.setattr(
        "quant_strategies.core.execution._load_strategy",
        lambda path, repo_root: _validated(lambda loaded_rows, params: [decision("other")]),
    )

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path, backend=backend)

    assert result.decision.decision == "mechanical_fail"
    assert backend.calls == 0
    assert result.result_dir is not None
    audit = json.loads((result.result_dir / "data_audit.json").read_text())
    assert audit["windows"][0]["violations"] == [
        "decision_strategy_id_mismatch[0]: expected demo, got other"
    ]


def test_run_validation_rejects_non_decision_output(tmp_path: Path, monkeypatch):
    candidate = write_candidate(tmp_path)
    backend = RecordingBackend()
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )
    monkeypatch.setattr(
        "quant_strategies.core.execution._load_strategy",
        lambda path, repo_root: _validated(lambda loaded_rows, params: "not decisions"),
    )

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path, backend=backend)

    assert result.decision.decision == "mechanical_fail"
    assert backend.calls == 0
    assert result.result_dir is not None
    audit = json.loads((result.result_dir / "data_audit.json").read_text())
    assert audit["windows"][0]["violations"] == ["invalid_decision_output"]
    manifest = json.loads((result.result_dir / "validation_manifest.json").read_text())
    assert manifest["data"]["windows"][0]["status"] == "loaded"
    assert manifest["data"]["windows"][0]["row_count"] == len(rows())
    row_path = "data_rows/validation_2026_h1.jsonl"
    row_file = result.result_dir / row_path
    assert manifest["data"]["windows"][0]["rows_path"] == row_path
    assert manifest["data"]["windows"][0]["rows_sha256"] == file_sha256(row_file)
    assert read_jsonl(row_file) == expected_row_records()


def test_run_validation_default_engine_backend_fails_closed_on_unfillable_window(
    tmp_path: Path, monkeypatch
):
    # No backend injected -> the engine is the default (and only) verdict source.
    candidate = write_candidate(tmp_path)
    (candidate / "validation.toml").write_text(
        (candidate / "validation.toml").read_text() + "\n[mechanical_thresholds]\nenabled = false\n"
    )
    (candidate / "strategy.py").write_text(
        (candidate / "strategy.py")
        .read_text()
        .replace(
            "def generate_decisions(rows, params):\n",
            "def generate_decisions(rows, params):\n    if len(rows) < 2:\n        return []\n",
        )
        .replace("decision_time=rows[0]['timestamp']", "decision_time=rows[1]['timestamp']")
        .replace("as_of_time=rows[0]['timestamp']", "as_of_time=rows[1]['timestamp']")
    )
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path)

    # The fill_lag_plus_1 scenario (entry_lag_bars=2) pushes the bar-1 decision's fill
    # past the 3 available bars, so the spine raises a structured unfillable decision and
    # the engine backend reports a failed run for that required scenario.
    assert result.decision.decision == "mechanical_fail"
    assert result.decision.reasons == ("engine_failed",)
    assert result.result_dir is not None
    backend_summary = json.loads((result.result_dir / "backend_runs" / "summary.json").read_text())
    fill_lag_result = next(
        item
        for item in backend_summary["results"]
        if item["scenario_id"].endswith("/fill_lag_plus_1")
    )
    assert fill_lag_result["result"]["backend"] == "engine"
    assert fill_lag_result["result"]["status"] == "failed"
    assert fill_lag_result["result"]["metrics"] == {}
    assert fill_lag_result["result"]["unsupported_semantics"] == []
    assert any(
        "unfillable_decision:BTC-PERP" in warning
        for warning in fill_lag_result["result"]["warnings"]
    )


def test_run_validation_engine_backend_validates_threshold_exit_strategy(
    tmp_path: Path, monkeypatch
):
    # F7: a strategy with a stop-loss (threshold exit) was un-validatable under the
    # retired alternate backend (unsupported -> mechanical_fail). The engine verdict
    # source completes it, so the validation step no longer forks away from the quick run.
    candidate = write_candidate(tmp_path)
    (candidate / "strategy.py").write_text(
        "from quant_strategies.decisions import InstrumentRef, ObservationRef, RiskRule, TargetDecision\n"
        "def validate_params(params):\n"
        "    return dict(params)\n"
        "def generate_decisions(rows, params):\n"
        "    return [TargetDecision(\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='crypto_perp', symbol='BTC-PERP'),\n"
        "        decision_time=rows[0]['timestamp'],\n"
        "        as_of_time=rows[0]['timestamp'],\n"
        "        target=1.0,\n"
        "        risk_rule=RiskRule(stop_loss=0.005, take_profit=0.03),\n"
        "        observations=(ObservationRef(symbol='BTC-PERP', timestamp=rows[0]['timestamp'], field='close', source='strategy_input'),),\n"
        "    )]\n"
    )
    # Enough bars that every matrix scenario (incl. fill_lag_plus_1) is fillable.
    long_rows = [
        {
            "symbol": "BTC-PERP",
            "timestamp": datetime(2026, 1, 1, 0, minute, tzinfo=UTC),
            "available_at": datetime(2026, 1, 1, 0, minute, tzinfo=UTC),
            "open": 100.0 + minute,
            "high": 100.0 + minute,
            "low": 100.0 + minute,
            "close": 100.0 + minute,
            "volume": 1_000.0,
            "vwap": 100.0 + minute,
            "num_trades": 100,
            "has_funding_event": False,
        }
        for minute in range(5)
    ]
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=long_rows),
    )

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path)

    backend_summary = json.loads((result.result_dir / "backend_runs" / "summary.json").read_text())
    statuses = {
        item["result"]["backend"]: item["result"]["status"] for item in backend_summary["results"]
    }
    # The capability gap is gone: the engine completes the threshold-exit decision
    # across every scenario (the retired backend returned unsupported -> mechanical_fail).
    assert statuses == {"engine": "completed"}
    assert all(item["result"]["unsupported_semantics"] == [] for item in backend_summary["results"])
    assert "unsupported_semantics" not in result.decision.reasons
    assert "engine_failed" not in result.decision.reasons


def _long_strategy_text() -> str:
    return (
        "from quant_strategies.decisions import InstrumentRef, ObservationRef, TargetDecision\n"
        "def validate_params(params):\n"
        "    return dict(params)\n"
        "def generate_decisions(rows, params):\n"
        "    return [TargetDecision(\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='crypto_perp', symbol='BTC-PERP'),\n"
        "        decision_time=rows[0]['timestamp'],\n"
        "        as_of_time=rows[0]['timestamp'],\n"
        "        target=1.0,\n"
        "        observations=(ObservationRef(symbol='BTC-PERP', timestamp=rows[0]['timestamp'], field='close', source='strategy_input'),),\n"
        "    )]\n"
    )


def _upward_rows(n: int = 5) -> list[dict[str, Any]]:
    return [
        {
            "symbol": "BTC-PERP",
            "timestamp": datetime(2026, 1, 1, 0, minute, tzinfo=UTC),
            "available_at": datetime(2026, 1, 1, 0, minute, tzinfo=UTC),
            "open": 100.0 + minute,
            "high": 100.0 + minute,
            "low": 100.0 + minute,
            "close": 100.0 + minute,
            "volume": 1_000.0,
            "vwap": 100.0 + minute,
            "num_trades": 100,
            "has_funding_event": False,
        }
        for minute in range(n)
    ]


def test_run_validation_default_engine_backend_accepts_flat_target_as_zero_activity_book(
    tmp_path: Path, monkeypatch
):
    # The target-book contract accepts a flat (0) target as a valid decision (it is a
    # complete, no-position book), so the spine backend completes it with zero closed
    # trades rather than rejecting the decision shape. The run still fails mechanically,
    # but on the no-evidence trade gate -- never on an "engine_failed"/unsupported shape.
    candidate = write_candidate(tmp_path)
    (candidate / "strategy.py").write_text(
        "from quant_strategies.decisions import InstrumentRef, ObservationRef, TargetDecision\n"
        "def validate_params(params):\n"
        "    return dict(params)\n"
        "def generate_decisions(rows, params):\n"
        "    return [TargetDecision(\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='crypto_perp', symbol='BTC-PERP'),\n"
        "        decision_time=rows[0]['timestamp'],\n"
        "        as_of_time=rows[0]['timestamp'],\n"
        "        target=0.0,\n"
        "        observations=(ObservationRef(symbol='BTC-PERP', timestamp=rows[0]['timestamp'], field='close', source='strategy_input'),),\n"
        "    )]\n"
    )
    loaded_rows = rows() + [
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
        }
    ]
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=loaded_rows),
    )

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path)

    assert result.decision.decision == "mechanical_fail"
    # Flat target is accepted: the backend completes with no closed trades, so the
    # failure is the no-evidence trade gate, not an unsupported/engine-failed shape.
    assert "engine_failed" not in result.decision.reasons
    assert "unsupported_semantics" not in result.decision.reasons
    assert "strategy_generation_failed" not in result.decision.reasons
    assert result.result_dir is not None
    backend_summary = json.loads((result.result_dir / "backend_runs" / "summary.json").read_text())
    base_result = backend_summary["results"][0]
    assert base_result["decision_count"] == 1
    assert base_result["result"]["status"] == "completed"
    assert base_result["result"]["metrics"]["trade_count"] == 0


def test_run_validation_reports_budget_breach_from_spine_for_leveraged_target_weight(
    tmp_path: Path, monkeypatch
):
    candidate = write_candidate(tmp_path)
    config_path = candidate / "validation.toml"
    config_path.write_text(config_path.read_text().replace("weight = 1.0", "weight = 1.01"))
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path)

    assert result.decision.decision == "mechanical_fail"
    assert result.decision.reasons == ("non_scoreable_required_scenario",)
    assert result.decision.failed_gates == ("required_scenario_scoreability",)
    assert (
        "leverage_budget_breach" in result.decision.gate_details["required_scenario_scoreability"]
    )
    assert result.failure_stage is None
    backend_summary = json.loads((result.result_dir / "backend_runs" / "summary.json").read_text())
    assert {item["result"]["feasibility"]["reason"] for item in backend_summary["results"]} == {
        "leverage_budget_breach"
    }


def test_run_validation_fails_scoreability_bearing_insufficient_samples_from_spine(
    tmp_path: Path, monkeypatch
):
    candidate = write_candidate(tmp_path)
    (candidate / "strategy.py").write_text(
        "from quant_strategies.decisions import InstrumentRef, ObservationRef, TargetDecision\n"
        "def validate_params(params):\n"
        "    return dict(params)\n"
        "def generate_decisions(rows, params):\n"
        "    return [TargetDecision(\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='crypto_perp', symbol='BTC-PERP'),\n"
        "        decision_time=rows[0]['timestamp'],\n"
        "        as_of_time=rows[0]['timestamp'],\n"
        "        target=0.25,\n"
        "        observations=(ObservationRef(symbol='BTC-PERP', timestamp=rows[0]['timestamp'], field='close', source='strategy_input'),),\n"
        "    )]\n"
    )
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path)

    assert result.decision.decision == "mechanical_fail"
    assert result.decision.reasons == ("non_scoreable_required_scenario",)
    assert result.decision.failed_gates == ("required_scenario_scoreability",)
    assert "insufficient_samples" in result.decision.gate_details["required_scenario_scoreability"]
    backend_summary = json.loads((result.result_dir / "backend_runs" / "summary.json").read_text())
    realistic = next(item for item in backend_summary["results"] if item["scenario_kind"] == "cost")
    assert realistic["scoreability_bearing"] is True
    assert realistic["result"]["status"] == "completed"
    assert realistic["result"]["feasibility"]["reason"] == "insufficient_samples"


def test_run_validation_lets_configured_leveraged_book_reach_backend(tmp_path: Path, monkeypatch):
    candidate = write_candidate(
        tmp_path,
        extra_config="""
[leverage_budget]
max_gross_exposure = 2.0
max_net_exposure = 2.0
""",
    )
    config_path = candidate / "validation.toml"
    config_path.write_text(config_path.read_text().replace("weight = 1.0", "weight = 1.01"))
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )
    backend = RecordingBackend()

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path, backend=backend)

    assert result.failure_stage is None
    assert backend.calls == 4
    assert {config.leverage_budget.max_gross_exposure for config in backend.configs} == {2.0}
    assert all(weights == [1.01] for _, weights in backend.decision_sizes_by_scenario)


def test_run_validation_reports_budget_breach_from_spine_for_cross_symbol_gross_exposure(
    tmp_path: Path, monkeypatch
):
    # Same-symbol targets net by construction, so over-gross is only reachable across
    # distinct instruments: two simultaneous 0.6 standing targets are an intended gross
    # of 1.2 > 1.0. The shared book owns that budget verdict.
    candidate = write_candidate(tmp_path)
    (candidate / "validation.toml").write_text(
        (candidate / "validation.toml")
        .read_text()
        .replace('symbols = ["BTC-PERP"]', 'symbols = ["BTC-PERP", "ETH-PERP"]')
    )
    (candidate / "strategy.py").write_text(
        "from quant_strategies.decisions import InstrumentRef, ObservationRef, TargetDecision\n"
        "def validate_params(params):\n"
        "    return dict(params)\n"
        "def generate_decisions(rows, params):\n"
        "    by_symbol = {}\n"
        "    for row in rows:\n"
        "        by_symbol.setdefault(row['symbol'], row)\n"
        "    decisions = []\n"
        "    for symbol in ('BTC-PERP', 'ETH-PERP'):\n"
        "        if symbol in by_symbol:\n"
        "            row = by_symbol[symbol]\n"
        "            decisions.append(TargetDecision(\n"
        "                strategy_id='demo',\n"
        "                instrument=InstrumentRef(kind='crypto_perp', symbol=symbol),\n"
        "                decision_time=row['timestamp'],\n"
        "                as_of_time=row['timestamp'],\n"
        "                target=0.6,\n"
        "                observations=(ObservationRef(symbol=symbol, timestamp=row['timestamp'], field='close', source='strategy_input'),),\n"
        "            ))\n"
        "    return decisions\n"
    )
    base = datetime(2026, 1, 1, tzinfo=UTC)
    loaded_rows = [
        _bar(symbol, base + timedelta(minutes=minute), 100.0 + minute)
        for symbol in ("BTC-PERP", "ETH-PERP")
        for minute in range(8)
    ]
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=loaded_rows),
    )

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path)

    assert result.decision.decision == "mechanical_fail"
    assert result.decision.reasons == ("non_scoreable_required_scenario",)
    assert result.decision.failed_gates == ("required_scenario_scoreability",)
    assert (
        "leverage_budget_breach" in result.decision.gate_details["required_scenario_scoreability"]
    )
    assert result.failure_stage is None
    backend_summary = json.loads((result.result_dir / "backend_runs" / "summary.json").read_text())
    assert {item["result"]["feasibility"]["reason"] for item in backend_summary["results"]} == {
        "leverage_budget_breach"
    }


def test_run_validation_does_not_preflight_exposure_against_scenario_fill_models(
    tmp_path: Path, monkeypatch
):
    candidate = write_candidate(tmp_path)
    (candidate / "validation.toml").write_text(
        (candidate / "validation.toml")
        .read_text()
        .replace(
            'symbols = ["BTC-PERP"]',
            'symbols = ["BTC-PERP", "ETH-PERP"]',
        )
    )
    (candidate / "strategy.py").write_text(
        "from quant_strategies.decisions import InstrumentRef, ObservationRef, TargetDecision\n"
        "def validate_params(params):\n"
        "    return dict(params)\n"
        "def generate_decisions(rows, params):\n"
        "    by_symbol = {}\n"
        "    for row in rows:\n"
        "        by_symbol.setdefault(row['symbol'], row)\n"
        "    decisions = []\n"
        "    if 'BTC-PERP' in by_symbol:\n"
        "        row = by_symbol['BTC-PERP']\n"
        "        decisions.append(TargetDecision(\n"
        "            strategy_id='demo',\n"
        "            instrument=InstrumentRef(kind='crypto_perp', symbol='BTC-PERP'),\n"
        "            decision_time=row['timestamp'],\n"
        "            as_of_time=row['timestamp'],\n"
        "            target=0.6,\n"
        "            observations=(ObservationRef(symbol='BTC-PERP', timestamp=row['timestamp'], field='close', source='strategy_input'),),\n"
        "        ))\n"
        "    if 'ETH-PERP' in by_symbol:\n"
        "        row = by_symbol['ETH-PERP']\n"
        "        decisions.append(TargetDecision(\n"
        "            strategy_id='demo',\n"
        "            instrument=InstrumentRef(kind='crypto_perp', symbol='ETH-PERP'),\n"
        "            decision_time=row['timestamp'],\n"
        "            as_of_time=row['timestamp'],\n"
        "            target=-(0.6),\n"
        "            observations=(ObservationRef(symbol='ETH-PERP', timestamp=row['timestamp'], field='close', source='strategy_input'),),\n"
        "        ))\n"
        "    return decisions\n"
    )
    base = datetime(2026, 1, 1, tzinfo=UTC)
    loaded_rows = [
        _bar("BTC-PERP", base + timedelta(minutes=0), 100.0),
        _bar("BTC-PERP", base + timedelta(minutes=1), 101.0),
        _bar("BTC-PERP", base + timedelta(minutes=10), 102.0),
        _bar("BTC-PERP", base + timedelta(minutes=11), 103.0),
        _bar("ETH-PERP", base + timedelta(minutes=9), 200.0),
        _bar("ETH-PERP", base + timedelta(minutes=10), 201.0),
        _bar("ETH-PERP", base + timedelta(minutes=10, seconds=30), 202.0),
        _bar("ETH-PERP", base + timedelta(minutes=11, seconds=30), 203.0),
    ]
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=loaded_rows),
    )
    backend = RecordingBackend()

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path, backend=backend)

    assert result.failure_stage is None
    assert backend.calls == 4
    data_audit = json.loads((result.result_dir / "data_audit.json").read_text())
    assert data_audit["windows"][0]["passed"] is True


def test_run_validation_gates_on_each_required_matrix_scenario(tmp_path: Path, monkeypatch):
    candidate = write_candidate(tmp_path)
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )
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

    assert result.decision.decision == "mechanical_fail"
    assert "insufficient_trades" in result.decision.reasons
    assert backend.calls == 4


def test_run_validation_loads_rows_once_per_window_and_reuses_across_matrix(
    tmp_path: Path, monkeypatch
):
    candidate = write_candidate(tmp_path, window_ids=("validation_2026_h1", "validation_2026_h2"))
    loaded_row_ids = []

    def load_data(config: Any, **_kwargs: object) -> LoadedData:
        loaded_rows = rows()
        loaded_row_ids.append(id(loaded_rows))
        return LoadedData(rows=loaded_rows)

    monkeypatch.setattr("quant_strategies.core.execution.load_data", load_data)
    backend = RecordingBackend()

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path, backend=backend)

    assert result.decision.decision == "mechanical_caution"
    assert "min_total_trades" in result.decision.failed_gates
    assert len(loaded_row_ids) == 2
    assert backend.calls == 8
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
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )
    backend = RecordingBackend()

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path, backend=backend)

    assert result.decision.decision == "mechanical_caution"
    configs = {item.scenario_id: item for item in backend.configs}
    decision_sizes = {
        scenario_id: sizes for scenario_id, sizes in backend.decision_sizes_by_scenario
    }
    assert configs["validation_2026_h1/base"].cost_model.fee_bps_per_side == 0.0
    assert configs["validation_2026_h1/base"].cost_model.slippage_bps_per_side == 0.0
    assert configs["validation_2026_h1/base"].fill_model.entry_lag_bars == 1
    assert configs["validation_2026_h1/base"].data.kind == "bars"
    assert configs["validation_2026_h1/base"].data.dataset == "unit-test-bars"
    assert configs["validation_2026_h1/base"].data.start == date(2026, 1, 1)
    assert configs["validation_2026_h1/base"].data.end == date(2026, 6, 30)
    assert configs["validation_2026_h1/realistic_costs"].cost_model.fee_bps_per_side == 0.5
    assert configs["validation_2026_h1/stressed_costs"].cost_model.fee_bps_per_side == 1.0
    assert configs["validation_2026_h1/stressed_costs"].cost_model.slippage_bps_per_side == 1.0
    assert configs["validation_2026_h1/fill_lag_plus_1"].fill_model.entry_lag_bars == 2
    assert decision_sizes["validation_2026_h1/base"] == [1.0]
    summary = json.loads((result.result_dir / "backend_runs" / "summary.json").read_text())
    assert not any(item["scenario_kind"] == "parameter" for item in summary["results"])


def test_run_validation_rejects_unknown_params_with_strategy_validator(tmp_path: Path, monkeypatch):
    candidate = write_candidate(tmp_path)
    (candidate / "strategy.py").write_text(
        "from quant_strategies.decisions import InstrumentRef, ObservationRef, TargetDecision\n"
        "def validate_params(params):\n"
        "    extra = set(params).difference({'weight'})\n"
        "    if extra:\n"
        "        raise ValueError(f'unknown params: {sorted(extra)}')\n"
        "    return dict(params)\n"
        "def generate_decisions(rows, params):\n"
        "    return [TargetDecision(\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='crypto_perp', symbol='BTC-PERP'),\n"
        "        decision_time=rows[0]['timestamp'],\n"
        "        as_of_time=rows[0]['timestamp'],\n"
        "        target=-float(params['weight']),\n"
        "        observations=(ObservationRef(symbol='BTC-PERP', timestamp=rows[0]['timestamp'], field='close', source='strategy_input'),),\n"
        "    )]\n"
    )
    validation_config = (candidate / "validation.toml").read_text()
    (candidate / "validation.toml").write_text(
        validation_config.replace("weight = 1.0", "weight = 1.0\ntypo = 2.0")
    )
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )
    backend = RecordingBackend()

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path, backend=backend)

    assert result.decision.decision == "mechanical_fail"
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
        "def validate_params(params):\n"
        "    return dict(params)\n"
        "def generate_decisions(rows, params):\n"
        "    rows[0]['close'] = 999.0\n"
        "    return []\n"
    )
    loaded_rows = rows()
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=loaded_rows),
    )

    result = run_validation(
        candidate / "validation.toml", repo_root=tmp_path, backend=RecordingBackend()
    )

    assert result.decision.decision == "mechanical_fail"
    assert result.decision.reasons == ("strategy_generation_failed",)
    assert loaded_rows[0]["close"] == 100.0
    assert result.result_dir is not None
    audit = json.loads((result.result_dir / "data_audit.json").read_text())
    assert "strategy_generation_failed" in audit["windows"][0]["violations"][0]


def test_run_validation_blocks_strategy_param_mutation(tmp_path: Path, monkeypatch):
    candidate = write_candidate(tmp_path)
    (candidate / "strategy.py").write_text(
        "def validate_params(params):\n"
        "    return dict(params)\n"
        "def generate_decisions(rows, params):\n"
        "    params['weight'] = 2.0\n"
        "    return []\n"
    )
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )

    result = run_validation(
        candidate / "validation.toml", repo_root=tmp_path, backend=RecordingBackend()
    )

    assert result.decision.decision == "mechanical_fail"
    assert result.decision.reasons == ("strategy_generation_failed",)
    assert result.result_dir is not None
    audit = json.loads((result.result_dir / "data_audit.json").read_text())
    assert "strategy_generation_failed" in audit["windows"][0]["violations"][0]


def test_run_validation_writes_failure_artifacts_for_strategy_generation_exception(
    tmp_path: Path, monkeypatch
):
    candidate = write_candidate(tmp_path)
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )

    def raise_generation_error(loaded_rows: list[dict[str, Any]], params: dict[str, Any]):
        raise RuntimeError("signal code failed")

    monkeypatch.setattr(
        "quant_strategies.core.execution._load_strategy",
        lambda path, repo_root: _validated(raise_generation_error),
    )

    result = run_validation(
        candidate / "validation.toml", repo_root=tmp_path, backend=RecordingBackend()
    )

    assert result.decision.decision == "mechanical_fail"
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


def test_run_validation_writes_failure_artifacts_for_backend_exception(tmp_path: Path, monkeypatch):
    candidate = write_candidate(tmp_path)
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )
    backend = ExplodingBackend()

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path, backend=backend)

    assert result.decision.decision == "mechanical_fail"
    assert result.decision.reasons == ("exploding_failed",)
    assert result.result_dir is not None
    assert (result.result_dir / "validation_decision.json").exists()
    assert (result.result_dir / "validation_report.md").exists()
    summary = json.loads((result.result_dir / "backend_runs" / "summary.json").read_text())
    assert len(summary["results"]) == 4
    assert summary["results"][0]["scenario_id"] == "validation_2026_h1/base"
    assert summary["results"][0]["result"]["status"] == "failed"
    assert summary["results"][0]["result"]["warnings"] == ["backend_exception: backend crashed"]


def test_run_validation_trusts_backend_run_result_without_pydantic_revalidation(
    tmp_path: Path, monkeypatch
):
    candidate = write_candidate(tmp_path)
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )

    def reject_revalidation(*args: object, **kwargs: object) -> None:
        raise AssertionError("BackendRunResult.model_validate should not be called")

    monkeypatch.setattr(BackendRunResult, "model_validate", reject_revalidation)
    backend = FakeBackend(
        BackendRunResult(
            backend="fake",
            status="completed",
            metrics={"net_return": 0.01, "trade_count": 10},
            warnings=(),
            unsupported_semantics=(),
        )
    )

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path, backend=backend)

    assert result.result_dir is not None
    summary = json.loads((result.result_dir / "backend_runs" / "summary.json").read_text())
    assert summary["results"][0]["result"]["status"] == "completed"
    assert summary["results"][0]["result"]["warnings"] == []


def test_run_validation_writes_failure_artifacts_for_malformed_backend_result(
    tmp_path: Path, monkeypatch
):
    candidate = write_candidate(tmp_path)
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )
    backend = MalformedBackend()

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path, backend=backend)

    assert result.decision.decision == "mechanical_fail"
    assert result.decision.reasons == ("malformed_failed",)
    assert result.result_dir is not None
    assert (result.result_dir / "validation_decision.json").exists()
    assert (result.result_dir / "validation_report.md").exists()
    summary = json.loads((result.result_dir / "backend_runs" / "summary.json").read_text())
    assert len(summary["results"]) == 4
    assert summary["results"][0]["scenario_id"] == "validation_2026_h1/base"
    assert summary["results"][0]["result"]["status"] == "failed"
    assert "invalid_backend_result" in summary["results"][0]["result"]["warnings"][0]


def test_run_validation_rejects_invalid_backend_status(tmp_path: Path, monkeypatch):
    candidate = write_candidate(tmp_path)
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )
    backend = InvalidStatusBackend()

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path, backend=backend)

    assert result.decision.decision == "mechanical_fail"
    assert result.decision.reasons == ("invalid_status_failed",)
    assert result.result_dir is not None
    summary = json.loads((result.result_dir / "backend_runs" / "summary.json").read_text())
    assert summary["results"][0]["result"]["status"] == "failed"
    assert "invalid_backend_result" in summary["results"][0]["result"]["warnings"][0]
    assert "expected BackendRunResult, got dict" in summary["results"][0]["result"]["warnings"][0]


def test_run_validation_propagates_backend_system_exit(tmp_path: Path, monkeypatch):
    candidate = write_candidate(tmp_path)
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )

    with pytest.raises(SystemExit, match="backend exited"):
        run_validation(candidate / "validation.toml", repo_root=tmp_path, backend=ExitingBackend())


def test_run_validation_writes_failure_artifacts_for_strategy_generation_system_exit(
    tmp_path: Path, monkeypatch
):
    candidate = write_candidate(tmp_path)
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )

    def exit_generation(loaded_rows: list[dict[str, Any]], params: dict[str, Any]):
        raise SystemExit("signal code exited")

    monkeypatch.setattr(
        "quant_strategies.core.execution._load_strategy",
        lambda path, repo_root: _validated(exit_generation),
    )

    result = run_validation(
        candidate / "validation.toml", repo_root=tmp_path, backend=RecordingBackend()
    )

    assert result.decision.decision == "mechanical_fail"
    assert result.failure_stage == "decision_generation"
    assert result.result_dir is not None
    decision_payload = json.loads((result.result_dir / "validation_decision.json").read_text())
    assert decision_payload["reasons"] == ["strategy_generation_failed"]


def test_run_validation_writes_failure_artifacts_for_validate_params_system_exit(
    tmp_path: Path,
):
    candidate = write_candidate(tmp_path)
    (candidate / "strategy.py").write_text(
        "def validate_params(params):\n"
        "    raise SystemExit('params exited')\n"
        "def generate_decisions(rows, params):\n"
        "    return []\n"
    )

    result = run_validation(
        candidate / "validation.toml", repo_root=tmp_path, backend=RecordingBackend()
    )

    assert result.decision.decision == "mechanical_fail"
    assert result.failure_stage == "param_validation"
    assert result.result_dir is not None
    decision_payload = json.loads((result.result_dir / "validation_decision.json").read_text())
    assert decision_payload["failure_details"][0]["stage"] == "param_validation"
    assert decision_payload["failure_details"][0]["type"] == "SystemExit"
    assert decision_payload["failure_details"][0]["message"] == "params exited"


def test_run_validation_writes_failure_artifacts_for_strategy_import_system_exit(
    tmp_path: Path,
):
    candidate = write_candidate(tmp_path)
    (candidate / "strategy.py").write_text("raise SystemExit('import exited')\n")

    result = run_validation(
        candidate / "validation.toml", repo_root=tmp_path, backend=RecordingBackend()
    )

    assert result.decision.decision == "mechanical_fail"
    assert result.failure_stage == "strategy_import"
    assert result.result_dir is not None
    decision_payload = json.loads((result.result_dir / "validation_decision.json").read_text())
    assert decision_payload["failure_details"][0]["stage"] == "strategy_import"
    assert (
        "strategy import exited: import exited" in decision_payload["failure_details"][0]["message"]
    )


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
        decisions: list[TargetDecision],
        rows: list[dict[str, Any]],
        config: Any,
    ) -> BackendRunResult:
        self.calls += 1
        self.configs.append(config)
        self.row_ids_by_scenario.append((config.scenario_id, id(rows)))
        self.rows_by_scenario.append((config.scenario_id, rows))
        self.decision_sizes_by_scenario.append(
            (config.scenario_id, [abs(decision.target) for decision in decisions])
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
        decisions: list[TargetDecision],
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
        decisions: list[TargetDecision],
        rows: list[dict[str, Any]],
        config: Any,
    ) -> BackendRunResult:
        raise RuntimeError("backend crashed")


class MalformedBackend:
    name = "malformed"

    def run(
        self,
        *,
        decisions: list[TargetDecision],
        rows: list[dict[str, Any]],
        config: Any,
    ) -> None:
        return None


class ExitingBackend:
    name = "exiting"

    def run(
        self,
        *,
        decisions: list[TargetDecision],
        rows: list[dict[str, Any]],
        config: Any,
    ) -> BackendRunResult:
        raise SystemExit("backend exited")


class InvalidStatusBackend:
    name = "invalid_status"

    def run(
        self,
        *,
        decisions: list[TargetDecision],
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


def test_run_validation_artifact_initialization_failure_returns_structured_result(
    tmp_path: Path,
    monkeypatch,
):
    candidate = write_candidate(tmp_path)

    def raise_oserror(results_root, strategy_id):
        raise PermissionError("results dir not writable")

    monkeypatch.setattr(validation, "create_validation_result_dir", raise_oserror)

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path)

    assert result.failure_stage == "artifact_initialization"
    assert result.result_dir is None
    assert result.run_completed is False
    assert result.decision.decision == "mechanical_fail"
    assert "artifact initialization failed" in result.message


def test_run_validation_artifact_write_failure_returns_structured_result(
    tmp_path: Path,
    monkeypatch,
):
    candidate = write_candidate(tmp_path)
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )
    backend = FakeBackend(
        BackendRunResult(
            backend="fake",
            status="completed",
            metrics={"net_return": 0.02, "trade_count": 20},
        )
    )

    def raise_oserror(**_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(validation, "_write_validation_artifacts", raise_oserror)

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path, backend=backend)

    assert result.failure_stage == "artifact_write"
    assert result.run_completed is False
    assert result.result_dir is not None
    # Verdict was computed before the failed write; the structured result still carries it.
    assert result.decision.decision == "mechanical_caution"
    assert "artifact write failed" in result.message


def test_run_validation_requires_strategy_validate_params(tmp_path: Path, monkeypatch):
    # F18: validation must not produce a mechanical-threshold verdict on unvalidated
    # params. A schema-less strategy fails fast at the param_validation stage.
    candidate = write_candidate(tmp_path)
    (candidate / "strategy.py").write_text(
        "from quant_strategies.decisions import InstrumentRef, ObservationRef, TargetDecision\n"
        "def generate_decisions(rows, params):\n"
        "    return [TargetDecision(\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='crypto_perp', symbol='BTC-PERP'),\n"
        "        decision_time=rows[0]['timestamp'],\n"
        "        as_of_time=rows[0]['timestamp'],\n"
        "        target=-(1.0),\n"
        "        observations=(ObservationRef(symbol='BTC-PERP', timestamp=rows[0]['timestamp'], field='close', source='strategy_input'),),\n"
        "    )]\n"
    )
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )
    backend = RecordingBackend()

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path, backend=backend)

    assert result.decision.decision == "mechanical_fail"
    assert result.decision.reasons == ("param_validation_failed",)
    assert result.failure_stage == "param_validation"
    assert backend.calls == 0
    assert result.result_dir is not None
    audit = json.loads((result.result_dir / "data_audit.json").read_text())
    assert "validate_params" in audit["windows"][0]["violations"][0]


def test_run_validation_emits_replayable_netted_book_ledger(tmp_path: Path, monkeypatch):
    # F16/D9: the gated net_return is recomputable from the emitted netted-book
    # round-trip ledger. No backend injected -> the spine is the verdict source and
    # emits the ledger. Open/close/open/close so each scenario ledger holds two closed
    # round trips -- otherwise `sum == metric` is the tautology `x == x`.
    from quant_strategies.core.portfolio_foundation import INITIAL_EQUITY

    candidate = write_candidate(tmp_path)
    (candidate / "strategy.py").write_text(
        "from quant_strategies.decisions import InstrumentRef, ObservationRef, TargetDecision\n"
        "def validate_params(params):\n"
        "    return dict(params)\n"
        "def generate_decisions(rows, params):\n"
        "    targets = {0: 1.0, 1: 0.0, 2: 1.0, 3: 0.0}\n"
        "    out = []\n"
        "    for i, row in enumerate(rows):\n"
        "        if i in targets:\n"
        "            out.append(TargetDecision(\n"
        "                strategy_id='demo',\n"
        "                instrument=InstrumentRef(kind='crypto_perp', symbol='BTC-PERP'),\n"
        "                decision_time=row['timestamp'],\n"
        "                as_of_time=row['timestamp'],\n"
        "                target=targets[i],\n"
        "                observations=(ObservationRef(symbol='BTC-PERP', timestamp=row['timestamp'], field='close', source='strategy_input'),),\n"
        "            ))\n"
        "    return out\n"
    )
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=_upward_rows(6)),
    )

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path)

    assert result.result_dir is not None
    manifest = json.loads((result.result_dir / "validation_manifest.json").read_text())
    assert manifest["validation"]["verdict_replayable"] is True
    assert manifest["validation"]["verdict_replay_basis"] == "netted_book_round_trip_ledger"

    backend_summary = json.loads((result.result_dir / "backend_runs" / "summary.json").read_text())
    ledgered = [item for item in backend_summary["results"] if item["trade_ledger_path"]]
    assert ledgered  # the spine emitted at least one netted-book round-trip ledger
    # Guard against regressing to the tautological single-trade case.
    assert any(item["result"]["metrics"]["trade_count"] >= 2 for item in ledgered)
    for item in ledgered:
        ledger_file = result.result_dir / item["trade_ledger_path"]
        assert item["trade_ledger_sha256"] == file_sha256(ledger_file)
        # the ledger is hash-pinned as an audit artifact in the manifest
        assert manifest["artifacts"][item["trade_ledger_path"]]["sha256"] == file_sha256(
            ledger_file
        )
        round_trips = read_jsonl(ledger_file)
        metrics = item["result"]["metrics"]
        assert len(round_trips) == metrics["trade_count"]
        # the verdict net_return is exactly the sum of the round-trip realized PnL as a
        # fraction of the standing NAV base (design D4 reconciliation).
        assert sum(t["realized_pnl"] for t in round_trips) / INITIAL_EQUITY == pytest.approx(
            metrics["net_return"], abs=1e-9
        )


def test_run_validation_failure_path_artifact_write_error_returns_structured_result(
    tmp_path: Path,
    monkeypatch,
):
    # A mechanical_fail path (here param_validation on a schema-less strategy) routes through
    # _failure_result; if its artifact write fails, the structured verdict must still
    # be returned, not raised -- API consumers have no CLI backstop.
    candidate = write_candidate(tmp_path)
    (candidate / "strategy.py").write_text(
        "from quant_strategies.decisions import InstrumentRef, ObservationRef, TargetDecision\n"
        "def generate_decisions(rows, params):\n"
        "    return [TargetDecision(\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='crypto_perp', symbol='BTC-PERP'),\n"
        "        decision_time=rows[0]['timestamp'],\n"
        "        as_of_time=rows[0]['timestamp'],\n"
        "        target=-(1.0),\n"
        "        observations=(ObservationRef(symbol='BTC-PERP', timestamp=rows[0]['timestamp'], field='close', source='strategy_input'),),\n"
        "    )]\n"
    )
    monkeypatch.setattr(
        "quant_strategies.core.execution.load_data",
        lambda config, **_kwargs: LoadedData(rows=rows()),
    )

    def raise_oserror(**_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(validation, "_write_validation_artifacts", raise_oserror)

    result = run_validation(candidate / "validation.toml", repo_root=tmp_path)

    assert result.decision.decision == "mechanical_fail"
    assert result.failure_stage == "param_validation"
