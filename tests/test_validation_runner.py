from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from quant_strategies.decisions import ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision
from quant_strategies.runner.data_loader import LoadedData
from quant_strategies.runner.errors import DataLoadError
from quant_strategies.validation import run_validation
from quant_strategies.validation.backends import BackendRunResult, FakeBackend


AS_OF = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
DECISION = datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc)


def write_package(tmp_path: Path, *, backend: str | None = "fake") -> Path:
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
    (package / "validation.toml").write_text(
        f"""
strategy_path = "researched/demo/strategy.py"
strategy_id = "demo"
{backend_line}

[[windows]]
id = "validation_2026_h1"
start = "2026-01-01"
end = "2026-06-30"

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
    backend_summary = json.loads((result.result_dir / "backend_runs" / "summary.json").read_text())
    assert backend_summary["results"] == [
        {
            "window_id": "validation_2026_h1",
            "result": {
                "backend": "fake",
                "status": "completed",
                "metrics": {"net_return": 0.02, "trade_count": 20},
                "warnings": [],
                "unsupported_semantics": [],
            },
        }
    ]
    assert (result.result_dir / "decision_records.jsonl").exists()
    assert (result.result_dir / "data_audit.json").exists()


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

    result = run_validation(package, repo_root=tmp_path)

    assert result.decision.decision == "hard_no"
    assert result.result_dir is not None
    backend_summary = json.loads((result.result_dir / "backend_runs" / "summary.json").read_text())
    assert backend_summary["results"][0] == {
        "window_id": "validation_2026_h1",
        "result": {
            "backend": "vectorbtpro",
            "status": "failed",
            "metrics": {},
            "warnings": ["unfillable_exit:BTC-PERP:2026-01-01T00:01:00+00:00"],
            "unsupported_semantics": [],
        },
    }


class RecordingBackend:
    name = "recording"

    def __init__(self) -> None:
        self.calls = 0

    def run(
        self,
        *,
        decisions: list[StrategyDecision],
        rows: list[dict[str, Any]],
        config: Any,
    ) -> BackendRunResult:
        self.calls += 1
        return BackendRunResult(
            backend=self.name,
            status="completed",
            metrics={"net_return": 0.01, "trade_count": 10},
            warnings=(),
            unsupported_semantics=(),
        )
