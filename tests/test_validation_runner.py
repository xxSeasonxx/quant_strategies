from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from quant_strategies.decisions import ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision
from quant_strategies.runner.data_loader import LoadedData
from quant_strategies.runner.errors import DataLoadError
from quant_strategies.validation import run_validation
from quant_strategies.validation.backends import BackendRunResult, FakeBackend


AS_OF = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
DECISION = datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc)


def write_package(
    tmp_path: Path,
    *,
    backend: str | None = "fake",
    window_ids: tuple[str, ...] = ("validation_2026_h1",),
) -> Path:
    package = tmp_path / "researched" / "demo"
    package.mkdir(parents=True)
    strategy_text = (
        "from quant_strategies.decisions import ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision\n"
        "def generate_decisions(rows, params):\n"
        "    return [StrategyDecision(\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='crypto_perp', symbol='BTC-PERP'),\n"
        "        decision_time=rows[1]['timestamp'],\n"
        "        as_of_time=rows[0]['timestamp'],\n"
        "        target=PositionTarget(direction='short', sizing_kind='target_weight', size=1.0),\n"
        "        exit_policy=ExitPolicy(max_hold_bars=1),\n"
        "    )]\n"
    ).replace("size=1.0", "size=float(params.get('weight', 1.0))")
    (package / "strategy.py").write_text(strategy_text)
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
    (package / "validation.toml").write_text(
        f"""
strategy_path = "researched/demo/strategy.py"
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

[output]
results_dir = "validation_results/demo"
""".lstrip()
    )
    return package


def decision(strategy_id: str = "demo") -> StrategyDecision:
    return StrategyDecision(
        strategy_id=strategy_id,
        instrument=InstrumentRef(kind="crypto_perp", symbol="BTC-PERP"),
        decision_time=DECISION,
        as_of_time=AS_OF,
        target=PositionTarget(direction="short", sizing_kind="target_weight", size=1.0),
        exit_policy=ExitPolicy(max_hold_bars=1),
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


def test_run_validation_writes_clear_yes_artifacts(tmp_path: Path, monkeypatch):
    package = write_package(tmp_path)
    monkeypatch.setattr(
        "quant_strategies.runner.data_loader.load_data",
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

    result = run_validation(package, repo_root=tmp_path, backend=backend)

    assert result.decision.decision == "clear_yes"
    assert result.result_dir is not None
    promotion = json.loads((result.result_dir / "promotion_decision.json").read_text())
    assert promotion["decision"] == "clear_yes"
    assert promotion["evidence_class"] == "validation_advisory"
    assert promotion["advisory_decision"] == "clear_yes"
    assert promotion["paper_trade_eligible"] is False
    assert promotion["live_eligible"] is False
    assert promotion["requires_manual_approval"] is True
    backend_summary = json.loads((result.result_dir / "backend_runs" / "summary.json").read_text())
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
    assert read_jsonl(base_decision_file)[0]["target"]["size"] == 1.0
    assert (result.result_dir / "decision_records.jsonl").exists()
    assert (result.result_dir / "data_audit.json").exists()
    assert (result.result_dir / "backend_capability_matrix.json").exists()
    assert (result.result_dir / "validation_config.toml").exists()
    assert (result.result_dir / "strategy_snapshot.py").exists()
    assert (result.result_dir / "decision_schema.json").exists()
    robustness_matrix = json.loads((result.result_dir / "robustness_matrix.json").read_text())
    assert robustness_matrix["decision"]["decision"] == "clear_yes"
    assert len(robustness_matrix["scenarios"]) == 6
    manifest = json.loads((result.result_dir / "validation_manifest.json").read_text())
    assert manifest["validation"]["strategy_id"] == "demo"
    assert manifest["validation"]["backend"] == "fake"
    assert manifest["strategy"]["path"] == "researched/demo/strategy.py"
    assert manifest["research_manifest"] == {"found": False, "passed": True, "violations": []}
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
    assert manifest["artifacts"]["backend_runs/summary.json"]["sha256"] == file_sha256(
        result.result_dir / "backend_runs" / "summary.json"
    )
    assert manifest["artifacts"][base_decision_path]["sha256"] == file_sha256(
        base_decision_file
    )


def test_run_validation_records_data_audit_failure(tmp_path: Path, monkeypatch):
    package = write_package(tmp_path)

    def raise_data_load_error(config: Any) -> LoadedData:
        raise DataLoadError("data load returned no rows")

    monkeypatch.setattr("quant_strategies.runner.data_loader.load_data", raise_data_load_error)

    result = run_validation(package, repo_root=tmp_path, backend=FakeBackend())

    assert result.decision.decision == "hard_no"
    assert "data_audit_failed" in result.decision.reasons
    assert result.result_dir is not None
    audit = json.loads((result.result_dir / "data_audit.json").read_text())
    assert audit["windows"][0]["passed"] is False
    assert audit["windows"][0]["violations"] == ["data_load_failed: data load returned no rows"]
    assert (result.result_dir / "promotion_decision.json").exists()
    capability_matrix = json.loads((result.result_dir / "backend_capability_matrix.json").read_text())
    manifest = json.loads((result.result_dir / "validation_manifest.json").read_text())
    assert manifest["data"]["windows"][0]["status"] == "failed"
    assert manifest["data"]["windows"][0]["row_count"] == 0
    assert manifest["data"]["windows"][0]["rows_sha256"] is None
    assert manifest["backend"]["capability_matrix"] == capability_matrix
    assert manifest["core_hashes"]["backend_capability_matrix.json"] == file_sha256(
        result.result_dir / "backend_capability_matrix.json"
    )


def test_run_validation_blocks_stale_validation_ready_research_manifest(tmp_path: Path):
    package = write_package(tmp_path)
    (package / "manifest.json").write_text(
        json.dumps(
            {
                "variants": [
                    {
                        "directory": ".",
                        "lifecycle_status": "validation_ready",
                        "strategy_sha256": "stale-strategy-hash",
                        "validation_config_sha256": "stale-config-hash",
                    }
                ]
            }
        )
    )
    backend = RecordingBackend()

    result = run_validation(package, repo_root=tmp_path, backend=backend)

    assert result.decision.decision == "hard_no"
    assert result.decision.reasons == ("research_manifest_integrity_failed",)
    assert backend.calls == 0
    assert result.result_dir is not None
    manifest = json.loads((result.result_dir / "validation_manifest.json").read_text())
    assert manifest["research_manifest"]["found"] is True
    assert manifest["research_manifest"]["passed"] is False
    assert manifest["research_manifest"]["lifecycle_status"] == "validation_ready"
    assert manifest["research_manifest"]["violations"] == [
        "research_manifest_strategy_hash_mismatch",
        "research_manifest_validation_config_hash_mismatch",
    ]


def test_run_validation_blocks_malformed_research_manifest_variants(tmp_path: Path):
    package = write_package(tmp_path)
    (package / "manifest.json").write_text(json.dumps({"variants": {"directory": "."}}))
    backend = RecordingBackend()

    result = run_validation(package, repo_root=tmp_path, backend=backend)

    assert result.decision.decision == "hard_no"
    assert result.decision.reasons == ("research_manifest_integrity_failed",)
    assert backend.calls == 0
    assert result.result_dir is not None
    manifest = json.loads((result.result_dir / "validation_manifest.json").read_text())
    assert manifest["research_manifest"]["found"] is True
    assert manifest["research_manifest"]["passed"] is False
    assert manifest["research_manifest"]["violations"] == [
        "research_manifest_variants_invalid"
    ]


def test_run_validation_records_missing_research_manifest_variant_without_blocking(
    tmp_path: Path,
    monkeypatch,
):
    package = write_package(tmp_path)
    (package / "manifest.json").write_text(
        json.dumps(
            {
                "variants": [
                    {
                        "directory": "other_variant",
                        "lifecycle_status": "validation_ready",
                    }
                ]
            }
        )
    )
    monkeypatch.setattr("quant_strategies.runner.data_loader.load_data", lambda config: LoadedData(rows=rows()))
    backend = RecordingBackend()

    result = run_validation(package, repo_root=tmp_path, backend=backend)

    assert result.decision.decision == "clear_yes"
    assert backend.calls == 6
    assert result.result_dir is not None
    manifest = json.loads((result.result_dir / "validation_manifest.json").read_text())
    assert manifest["research_manifest"]["passed"] is True
    assert manifest["research_manifest"]["warnings"] == ["research_manifest_variant_missing"]
    assert manifest["research_manifest"]["violations"] == []


def test_run_validation_rejects_wrong_strategy_id(tmp_path: Path, monkeypatch):
    package = write_package(tmp_path)
    backend = RecordingBackend()
    monkeypatch.setattr("quant_strategies.runner.data_loader.load_data", lambda config: LoadedData(rows=rows()))
    monkeypatch.setattr(
        "quant_strategies.validation.load_decision_strategy",
        lambda path, repo_root: lambda loaded_rows, params: [decision("other")],
    )

    result = run_validation(package, repo_root=tmp_path, backend=backend)

    assert result.decision.decision == "hard_no"
    assert backend.calls == 0
    assert result.result_dir is not None
    audit = json.loads((result.result_dir / "data_audit.json").read_text())
    assert audit["windows"][0]["violations"] == [
        "decision_strategy_id_mismatch[0]: expected demo, got other"
    ]


def test_run_validation_rejects_non_decision_output(tmp_path: Path, monkeypatch):
    package = write_package(tmp_path)
    backend = RecordingBackend()
    monkeypatch.setattr("quant_strategies.runner.data_loader.load_data", lambda config: LoadedData(rows=rows()))
    monkeypatch.setattr(
        "quant_strategies.validation.load_decision_strategy",
        lambda path, repo_root: lambda loaded_rows, params: "not decisions",
    )

    result = run_validation(package, repo_root=tmp_path, backend=backend)

    assert result.decision.decision == "hard_no"
    assert backend.calls == 0
    assert result.result_dir is not None
    audit = json.loads((result.result_dir / "data_audit.json").read_text())
    assert audit["windows"][0]["violations"] == ["invalid_decision_output"]


def test_run_validation_default_vectorbtpro_backend_fails_closed(tmp_path: Path, monkeypatch):
    package = write_package(tmp_path, backend=None)
    monkeypatch.setattr("quant_strategies.runner.data_loader.load_data", lambda config: LoadedData(rows=rows()))
    monkeypatch.setitem(sys.modules, "vectorbtpro", SimpleNamespace())

    result = run_validation(package, repo_root=tmp_path)

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


def test_run_validation_gates_on_each_required_matrix_scenario(tmp_path: Path, monkeypatch):
    package = write_package(tmp_path)
    monkeypatch.setattr("quant_strategies.runner.data_loader.load_data", lambda config: LoadedData(rows=rows()))
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

    result = run_validation(package, repo_root=tmp_path, backend=backend)

    assert result.decision.decision == "hard_no"
    assert "insufficient_trades" in result.decision.reasons
    assert backend.calls == 6


def test_run_validation_loads_rows_once_per_window_and_reuses_across_matrix(
    tmp_path: Path, monkeypatch
):
    package = write_package(tmp_path, window_ids=("validation_2026_h1", "validation_2026_h2"))
    loaded_row_ids = []

    def load_data(config: Any) -> LoadedData:
        loaded_rows = rows()
        loaded_row_ids.append(id(loaded_rows))
        return LoadedData(rows=loaded_rows)

    monkeypatch.setattr("quant_strategies.runner.data_loader.load_data", load_data)
    backend = RecordingBackend()

    result = run_validation(package, repo_root=tmp_path, backend=backend)

    assert result.decision.decision == "clear_yes"
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
    assert len(h1_row_ids) == 6
    assert len(h2_row_ids) == 6
    first_rows = backend.rows_by_scenario[0][1]
    with pytest.raises(TypeError):
        first_rows[0]["close"] = 999.0


def test_run_validation_passes_merged_scenario_config_to_backend(tmp_path: Path, monkeypatch):
    package = write_package(tmp_path)
    monkeypatch.setattr("quant_strategies.runner.data_loader.load_data", lambda config: LoadedData(rows=rows()))
    backend = RecordingBackend()

    result = run_validation(package, repo_root=tmp_path, backend=backend)

    assert result.decision.decision == "clear_yes"
    configs = {item.scenario_id: item for item in backend.configs}
    decision_sizes = {scenario_id: sizes for scenario_id, sizes in backend.decision_sizes_by_scenario}
    assert configs["validation_2026_h1/base"].params == {"weight": 1.0}
    assert configs["validation_2026_h1/base"].cost_model.fee_bps_per_side == 0.0
    assert configs["validation_2026_h1/base"].cost_model.slippage_bps_per_side == 0.0
    assert configs["validation_2026_h1/base"].fill_model.entry_lag_bars == 1
    assert configs["validation_2026_h1/base"].data.kind == "crypto_perp_funding"
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
    package = write_package(tmp_path)
    (package / "strategy.py").write_text(
        "from quant_strategies.decisions import ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision\n"
        "def validate_params(params):\n"
        "    if float(params['weight']) > 1.0:\n"
        "        raise ValueError('weight too high')\n"
        "    return dict(params)\n"
        "def generate_decisions(rows, params):\n"
        "    return [StrategyDecision(\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='crypto_perp', symbol='BTC-PERP'),\n"
        "        decision_time=rows[1]['timestamp'],\n"
        "        as_of_time=rows[0]['timestamp'],\n"
        "        target=PositionTarget(direction='short', sizing_kind='target_weight', size=float(params['weight'])),\n"
        "        exit_policy=ExitPolicy(max_hold_bars=1),\n"
        "    )]\n"
    )
    monkeypatch.setattr("quant_strategies.runner.data_loader.load_data", lambda config: LoadedData(rows=rows()))
    backend = RecordingBackend()

    result = run_validation(package, repo_root=tmp_path, backend=backend)

    assert result.decision.decision == "clear_yes"
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
    package = write_package(tmp_path)
    (package / "strategy.py").write_text(
        "from quant_strategies.decisions import ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision\n"
        "def validate_params(params):\n"
        "    extra = set(params).difference({'weight'})\n"
        "    if extra:\n"
        "        raise ValueError(f'unknown params: {sorted(extra)}')\n"
        "    return dict(params)\n"
        "def generate_decisions(rows, params):\n"
        "    return [StrategyDecision(\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='crypto_perp', symbol='BTC-PERP'),\n"
        "        decision_time=rows[1]['timestamp'],\n"
        "        as_of_time=rows[0]['timestamp'],\n"
        "        target=PositionTarget(direction='short', sizing_kind='target_weight', size=float(params['weight'])),\n"
        "        exit_policy=ExitPolicy(max_hold_bars=1),\n"
        "    )]\n"
    )
    validation_config = (package / "validation.toml").read_text()
    (package / "validation.toml").write_text(
        validation_config.replace("weight = 1.0", "weight = 1.0\ntypo = 2.0")
    )
    monkeypatch.setattr("quant_strategies.runner.data_loader.load_data", lambda config: LoadedData(rows=rows()))
    backend = RecordingBackend()

    result = run_validation(package, repo_root=tmp_path, backend=backend)

    assert result.decision.decision == "hard_no"
    assert result.decision.reasons == ("param_validation_failed",)
    assert backend.calls == 0
    assert result.result_dir is not None
    audit = json.loads((result.result_dir / "data_audit.json").read_text())
    assert "param_validation_failed: unknown params" in audit["windows"][0]["violations"][0]


def test_run_validation_blocks_strategy_row_mutation(tmp_path: Path, monkeypatch):
    package = write_package(tmp_path)
    (package / "strategy.py").write_text(
        "def generate_decisions(rows, params):\n"
        "    rows[0]['close'] = 999.0\n"
        "    return []\n"
    )
    loaded_rows = rows()
    monkeypatch.setattr(
        "quant_strategies.runner.data_loader.load_data",
        lambda config: LoadedData(rows=loaded_rows),
    )

    result = run_validation(package, repo_root=tmp_path, backend=RecordingBackend())

    assert result.decision.decision == "hard_no"
    assert result.decision.reasons == ("strategy_generation_failed",)
    assert loaded_rows[0]["close"] == 100.0
    assert result.result_dir is not None
    audit = json.loads((result.result_dir / "data_audit.json").read_text())
    assert "strategy_generation_failed" in audit["windows"][0]["violations"][0]


def test_run_validation_blocks_strategy_param_mutation(tmp_path: Path, monkeypatch):
    package = write_package(tmp_path)
    (package / "strategy.py").write_text(
        "def generate_decisions(rows, params):\n"
        "    params['weight'] = 2.0\n"
        "    return []\n"
    )
    monkeypatch.setattr(
        "quant_strategies.runner.data_loader.load_data",
        lambda config: LoadedData(rows=rows()),
    )

    result = run_validation(package, repo_root=tmp_path, backend=RecordingBackend())

    assert result.decision.decision == "hard_no"
    assert result.decision.reasons == ("strategy_generation_failed",)
    assert result.result_dir is not None
    audit = json.loads((result.result_dir / "data_audit.json").read_text())
    assert "strategy_generation_failed" in audit["windows"][0]["violations"][0]


def test_run_validation_writes_failure_artifacts_for_strategy_generation_exception(
    tmp_path: Path, monkeypatch
):
    package = write_package(tmp_path)
    monkeypatch.setattr("quant_strategies.runner.data_loader.load_data", lambda config: LoadedData(rows=rows()))

    def raise_generation_error(loaded_rows: list[dict[str, Any]], params: dict[str, Any]):
        raise RuntimeError("signal code failed")

    monkeypatch.setattr(
        "quant_strategies.validation.load_decision_strategy",
        lambda path, repo_root: raise_generation_error,
    )

    result = run_validation(package, repo_root=tmp_path, backend=RecordingBackend())

    assert result.decision.decision == "hard_no"
    assert result.decision.reasons == ("strategy_generation_failed",)
    assert result.result_dir is not None
    assert (result.result_dir / "promotion_decision.json").exists()
    assert (result.result_dir / "validation_report.md").exists()
    summary = json.loads((result.result_dir / "backend_runs" / "summary.json").read_text())
    assert summary["results"] == []


def test_run_validation_writes_failure_artifacts_for_backend_exception(
    tmp_path: Path, monkeypatch
):
    package = write_package(tmp_path)
    monkeypatch.setattr("quant_strategies.runner.data_loader.load_data", lambda config: LoadedData(rows=rows()))
    backend = ExplodingBackend()

    result = run_validation(package, repo_root=tmp_path, backend=backend)

    assert result.decision.decision == "hard_no"
    assert result.decision.reasons == ("exploding_failed",)
    assert result.result_dir is not None
    assert (result.result_dir / "promotion_decision.json").exists()
    assert (result.result_dir / "validation_report.md").exists()
    summary = json.loads((result.result_dir / "backend_runs" / "summary.json").read_text())
    assert len(summary["results"]) == 6
    assert summary["results"][0]["scenario_id"] == "validation_2026_h1/base"
    assert summary["results"][0]["result"]["status"] == "failed"
    assert summary["results"][0]["result"]["warnings"] == ["backend_exception: backend crashed"]


def test_run_validation_writes_failure_artifacts_for_malformed_backend_result(
    tmp_path: Path, monkeypatch
):
    package = write_package(tmp_path)
    monkeypatch.setattr("quant_strategies.runner.data_loader.load_data", lambda config: LoadedData(rows=rows()))
    backend = MalformedBackend()

    result = run_validation(package, repo_root=tmp_path, backend=backend)

    assert result.decision.decision == "hard_no"
    assert result.decision.reasons == ("malformed_failed",)
    assert result.result_dir is not None
    assert (result.result_dir / "promotion_decision.json").exists()
    assert (result.result_dir / "validation_report.md").exists()
    summary = json.loads((result.result_dir / "backend_runs" / "summary.json").read_text())
    assert len(summary["results"]) == 6
    assert summary["results"][0]["scenario_id"] == "validation_2026_h1/base"
    assert summary["results"][0]["result"]["status"] == "failed"
    assert "invalid_backend_result" in summary["results"][0]["result"]["warnings"][0]


def test_run_validation_rejects_invalid_backend_status(tmp_path: Path, monkeypatch):
    package = write_package(tmp_path)
    monkeypatch.setattr("quant_strategies.runner.data_loader.load_data", lambda config: LoadedData(rows=rows()))
    backend = InvalidStatusBackend()

    result = run_validation(package, repo_root=tmp_path, backend=backend)

    assert result.decision.decision == "hard_no"
    assert result.decision.reasons == ("invalid_status_failed",)
    assert result.result_dir is not None
    summary = json.loads((result.result_dir / "backend_runs" / "summary.json").read_text())
    assert summary["results"][0]["result"]["status"] == "failed"
    assert "invalid_backend_result" in summary["results"][0]["result"]["warnings"][0]
    assert "status" in summary["results"][0]["result"]["warnings"][0]


def test_run_validation_propagates_backend_system_exit(tmp_path: Path, monkeypatch):
    package = write_package(tmp_path)
    monkeypatch.setattr("quant_strategies.runner.data_loader.load_data", lambda config: LoadedData(rows=rows()))

    with pytest.raises(SystemExit, match="backend exited"):
        run_validation(package, repo_root=tmp_path, backend=ExitingBackend())


def test_run_validation_writes_failure_artifacts_for_strategy_generation_system_exit(
    tmp_path: Path, monkeypatch
):
    package = write_package(tmp_path)
    monkeypatch.setattr("quant_strategies.runner.data_loader.load_data", lambda config: LoadedData(rows=rows()))

    def exit_generation(loaded_rows: list[dict[str, Any]], params: dict[str, Any]):
        raise SystemExit("signal code exited")

    monkeypatch.setattr(
        "quant_strategies.validation.load_decision_strategy",
        lambda path, repo_root: exit_generation,
    )

    with pytest.raises(SystemExit, match="signal code exited"):
        run_validation(package, repo_root=tmp_path, backend=RecordingBackend())


def test_run_validation_writes_failure_artifacts_for_strategy_import_system_exit(
    tmp_path: Path,
):
    package = write_package(tmp_path)
    (package / "strategy.py").write_text("raise SystemExit('import exited')\n")

    with pytest.raises(SystemExit, match="import exited"):
        run_validation(package, repo_root=tmp_path, backend=RecordingBackend())


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
