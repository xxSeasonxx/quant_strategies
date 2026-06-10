from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from quant_strategies.provenance import file_sha256
from quant_strategies.validation.backends import BackendRunResult, ScenarioBackendRunResult
from quant_strategies.validation.manifest import write_validation_manifest


def scenario(
    scenario_id: str,
    *,
    required: bool = True,
    status: str = "completed",
    trade_ledger_path: str | None = None,
) -> ScenarioBackendRunResult:
    return ScenarioBackendRunResult(
        window_id="validation_2026_h1",
        scenario_id=scenario_id,
        required=required,
        result=BackendRunResult(
            backend="engine",
            status=status,
            metrics={"net_return": 0.01, "trade_count": 1},
        ),
        scenario_kind="cost",
        trade_ledger_path=trade_ledger_path,
        trade_ledger_sha256="abc" if trade_ledger_path else None,
    )


def write_manifest(tmp_path: Path, backend_results: list[ScenarioBackendRunResult]) -> dict:
    result_dir = tmp_path / "validation_results"
    result_dir.mkdir()
    config_path = tmp_path / "validation.toml"
    config_path.write_text("strategy_id = 'demo'\n")
    strategy_path = tmp_path / "strategy.py"
    strategy_path.write_text("def generate_decisions(rows, params):\n    return []\n")

    for item in backend_results:
        if item.trade_ledger_path:
            ledger_path = result_dir / item.trade_ledger_path
            ledger_path.parent.mkdir(parents=True, exist_ok=True)
            ledger_path.write_text('{"net_return": 0.01}\n')

    path = write_validation_manifest(
        result_dir,
        repo_root=tmp_path,
        path_base=tmp_path,
        config=SimpleNamespace(strategy_id="demo", strategy_path=strategy_path),
        config_path=config_path,
        backend_name="engine",
        data_provenance=[],
        backend_results=backend_results,
    )
    return json.loads(path.read_text())


def test_validation_manifest_replayable_when_all_required_completed_scenarios_have_ledgers(
    tmp_path: Path,
):
    manifest = write_manifest(
        tmp_path,
        [
            scenario("base", trade_ledger_path="backend_runs/trade_ledgers/base.jsonl"),
            scenario("cost", trade_ledger_path="backend_runs/trade_ledgers/cost.jsonl"),
        ],
    )

    assert manifest["validation"]["verdict_replayable"] is True
    assert all(
        item["replayable_from_trade_ledger"] is True for item in manifest["backend"]["scenarios"]
    )
    for item in manifest["backend"]["scenarios"]:
        ledger_path = tmp_path / "validation_results" / item["trade_ledger_path"]
        assert manifest["artifacts"][item["trade_ledger_path"]]["sha256"] == file_sha256(
            ledger_path
        )


def test_validation_manifest_does_not_overclaim_mixed_replayability(tmp_path: Path):
    manifest = write_manifest(
        tmp_path,
        [
            scenario("base", trade_ledger_path="backend_runs/trade_ledgers/base.jsonl"),
            scenario("zero_trade"),
        ],
    )

    assert manifest["validation"]["verdict_replayable"] is False
    scenarios = {item["scenario_id"]: item for item in manifest["backend"]["scenarios"]}
    assert scenarios["base"]["replayable_from_trade_ledger"] is True
    assert scenarios["zero_trade"]["replayable_from_trade_ledger"] is False


def test_validation_manifest_ignores_incomplete_required_scenarios_for_global_replayability(
    tmp_path: Path,
):
    manifest = write_manifest(
        tmp_path,
        [
            scenario("base", trade_ledger_path="backend_runs/trade_ledgers/base.jsonl"),
            scenario("failed", status="failed"),
        ],
    )

    assert manifest["validation"]["verdict_replayable"] is True
    scenarios = {item["scenario_id"]: item for item in manifest["backend"]["scenarios"]}
    assert scenarios["failed"]["replayable_from_trade_ledger"] is False


def test_validation_manifest_does_not_report_retired_agreement_oracle(tmp_path: Path):
    # The single-trade agreement oracle and its cross-check were retired (design D9);
    # the manifest carries no agreement_oracle field on any scenario.
    manifest = write_manifest(
        tmp_path,
        [
            scenario("base"),
            scenario("not_run", status="failed"),
        ],
    )

    scenarios = {item["scenario_id"]: item for item in manifest["backend"]["scenarios"]}
    assert "agreement_oracle" not in scenarios["base"]
    assert "agreement_oracle" not in scenarios["not_run"]
    assert "agreement" not in scenarios["base"]
    assert "agreement" not in scenarios["not_run"]
