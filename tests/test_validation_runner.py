from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from quant_strategies.runner.data_loader import LoadedData
from quant_strategies.validation import run_validation
from quant_strategies.validation.backends import BackendRunResult, FakeBackend


AS_OF = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
DECISION = datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc)


def write_package(tmp_path: Path) -> Path:
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
    (package / "validation.toml").write_text(
        """
strategy_path = "researched/demo/strategy.py"
strategy_id = "demo"
backend = "fake"

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
    assert (result.result_dir / "decision_records.jsonl").exists()
    assert (result.result_dir / "data_audit.json").exists()


def test_run_validation_records_data_audit_failure(tmp_path: Path, monkeypatch):
    package = write_package(tmp_path)
    monkeypatch.setattr("quant_strategies.runner.data_loader.load_data", lambda config: LoadedData(rows=[]))

    result = run_validation(package, repo_root=tmp_path, backend=FakeBackend())

    assert result.decision.decision == "hard_no"
    assert "data_audit_failed" in result.decision.reasons
