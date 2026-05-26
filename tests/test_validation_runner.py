from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

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
    (package / "strategy.py").write_text(
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
    )
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
    assert backend_summary["results"][0] == {
        "window_id": "validation_2026_h1",
        "scenario_id": "validation_2026_h1/base",
        "required": True,
        "result": {
            "backend": "fake",
            "status": "completed",
            "metrics": {"net_return": 0.02, "trade_count": 20},
            "warnings": [],
            "unsupported_semantics": [],
        },
    }
    assert (result.result_dir / "decision_records.jsonl").exists()
    assert (result.result_dir / "data_audit.json").exists()
    assert (result.result_dir / "validation_config.toml").exists()
    assert (result.result_dir / "strategy_snapshot.py").exists()
    assert (result.result_dir / "decision_schema.json").exists()
    robustness_matrix = json.loads((result.result_dir / "robustness_matrix.json").read_text())
    assert robustness_matrix["decision"]["decision"] == "clear_yes"
    assert len(robustness_matrix["scenarios"]) == 6


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
        "required": True,
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
    assert h1_row_ids == {loaded_row_ids[0]}
    assert h2_row_ids == {loaded_row_ids[1]}


def test_run_validation_passes_merged_scenario_config_to_backend(tmp_path: Path, monkeypatch):
    package = write_package(tmp_path)
    monkeypatch.setattr("quant_strategies.runner.data_loader.load_data", lambda config: LoadedData(rows=rows()))
    backend = RecordingBackend()

    result = run_validation(package, repo_root=tmp_path, backend=backend)

    assert result.decision.decision == "clear_yes"
    configs = {item.scenario_id: item for item in backend.configs}
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

    result = run_validation(package, repo_root=tmp_path, backend=RecordingBackend())

    assert result.decision.decision == "hard_no"
    assert result.decision.reasons == ("strategy_generation_failed",)
    assert result.result_dir is not None
    audit = json.loads((result.result_dir / "data_audit.json").read_text())
    assert audit["windows"][0]["violations"] == [
        "strategy_generation_failed: signal code exited"
    ]
    assert (result.result_dir / "promotion_decision.json").exists()


def test_run_validation_writes_failure_artifacts_for_strategy_import_system_exit(
    tmp_path: Path,
):
    package = write_package(tmp_path)
    (package / "strategy.py").write_text("raise SystemExit('import exited')\n")

    result = run_validation(package, repo_root=tmp_path, backend=RecordingBackend())

    assert result.decision.decision == "hard_no"
    assert result.decision.reasons == ("strategy_import_failed",)
    assert result.result_dir is not None
    assert (result.result_dir / "promotion_decision.json").exists()
    assert (result.result_dir / "validation_report.md").exists()
    summary = json.loads((result.result_dir / "backend_runs" / "summary.json").read_text())
    assert summary["results"] == []


class RecordingBackend:
    name = "recording"

    def __init__(self) -> None:
        self.calls = 0
        self.configs = []
        self.row_ids_by_scenario = []

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
