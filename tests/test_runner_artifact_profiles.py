from __future__ import annotations

import hashlib
import inspect
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from quant_strategies.decisions import ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision
from quant_strategies.evidence_semantics import replayable_from_artifacts_for_profile


LEGACY_REPLAYABILITY_METADATA_KEY = "_".join(("artifact", "trust", "tier"))


def test_runner_artifacts_do_not_expose_legacy_row_summary_owner():
    import quant_strategies.runner as runner_package
    import quant_strategies.runner.artifacts as artifacts
    import quant_strategies.core.execution as runner_execution

    for module in (artifacts, runner_execution, runner_package):
        assert not hasattr(module, "RowSummary")
    assert "row_summary" not in inspect.signature(artifacts.write_data_manifest).parameters
    assert "row_summary" not in inspect.signature(runner_execution.StrategyExecutionError).parameters


def test_replayable_from_artifacts_for_profile_maps_profiles():
    assert replayable_from_artifacts_for_profile("summary") is False
    assert replayable_from_artifacts_for_profile("diagnostic") is False
    assert replayable_from_artifacts_for_profile("full") is True


def test_replayable_from_artifacts_for_profile_rejects_unknown_profile():
    with pytest.raises(ValueError, match="unknown artifact profile: compact"):
        replayable_from_artifacts_for_profile("compact")


def test_row_contract_issue_compaction_samples_each_failure_class():
    import quant_strategies.runner.artifacts as artifacts

    issues = [
        {
            "severity": "warning",
            "reason": "row_missing_available_at",
            "field": "available_at",
            "symbol": "SPY",
            "timestamp": f"2024-01-{index + 1:02d}T00:00:00+00:00",
            "message": "row is missing available_at",
        }
        for index in range(27)
    ]
    issues.extend(
        [
            {
                "severity": "error",
                "reason": "row_missing_required_field",
                "field": "high",
                "symbol": "SPY",
                "timestamp": "2024-02-01T00:00:00+00:00",
                "message": "row is missing required field 'high'",
            },
            {
                "severity": "error",
                "reason": "row_invalid_numeric_field",
                "field": "close",
                "symbol": "SPY",
                "timestamp": "2024-02-02T00:00:00+00:00",
                "message": "close must be a finite numeric value",
            },
            {
                "severity": "error",
                "reason": "row_invalid_funding_fields",
                "field": "funding_rate",
                "symbol": "BTC-PERP",
                "timestamp": "2024-02-03T00:00:00+00:00",
                "message": "funding_rate must be finite",
            },
        ]
    )
    evidence = {
        "data_availability_status": "invalid",
        "row_contract": {
            "issues": issues,
            "issue_reasons": {
                "row_invalid_funding_fields": 1,
                "row_invalid_numeric_field": 1,
                "row_missing_available_at": 27,
                "row_missing_required_field": 1,
            },
            "quant_data_feedback": [
                "row_invalid_funding_fields:funding_rate:1",
                "row_invalid_numeric_field:close:1",
                "row_missing_required_field:high:1",
            ],
        },
    }

    compacted = artifacts.compact_evidence_quality(evidence)
    row_contract = compacted["row_contract"]
    sampled_keys = {
        (issue["severity"], issue["reason"], issue["field"])
        for issue in row_contract["issues"]
    }

    assert row_contract["issue_count"] == 30
    assert row_contract["issue_sample_count"] == 25
    assert row_contract["issues_truncated"] is True
    assert row_contract["issue_reasons"] == evidence["row_contract"]["issue_reasons"]
    assert row_contract["quant_data_feedback"] == evidence["row_contract"]["quant_data_feedback"]
    assert sampled_keys >= {
        ("warning", "row_missing_available_at", "available_at"),
        ("error", "row_missing_required_field", "high"),
        ("error", "row_invalid_numeric_field", "close"),
        ("error", "row_invalid_funding_fields", "funding_rate"),
    }


def row(symbol: str, timestamp: datetime, close: float) -> dict[str, object]:
    return {
        "symbol": symbol,
        "timestamp": timestamp,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
    }


def decision(symbol: str, timestamp: datetime, direction: str = "long") -> StrategyDecision:
    return StrategyDecision(
        strategy_id="demo",
        instrument=InstrumentRef(kind="equity_or_etf", symbol=symbol),
        decision_time=timestamp,
        as_of_time=timestamp,
        target=PositionTarget(direction=direction, sizing_kind="target_weight", size=0.5),
        exit_policy=ExitPolicy(max_hold_bars=2),
        metadata={"family": "test"},
    )


def config(
    tmp_path: Path,
    *,
    artifact_profile: str = "summary",
    diagnostic_sample_trades: int | None = None,
):
    from quant_strategies.runner.config import load_config

    strategy = tmp_path / "strategies" / "demo.py"
    strategy.parent.mkdir(parents=True)
    strategy.write_text("def generate_decisions(rows, params):\n    return []\n")
    config_path = tmp_path / "run.toml"
    diagnostic_sample_trades_line = (
        f"diagnostic_sample_trades = {diagnostic_sample_trades}\n"
        if diagnostic_sample_trades is not None
        else ""
    )
    config_path.write_text(
        f'''
strategy_path = "strategies/demo.py"
strategy_id = "demo"

[data]
kind = "bars"
dataset = "equity_1min"
symbols = ["SPY", "QQQ"]
start = "2024-01-01"
end = "2024-01-05"

[params]

[fill_model]
price = "close"
entry_lag_bars = 1
exit_lag_bars = 0

[cost_model]
fee_bps_per_side = 0.0
slippage_bps_per_side = 0.0

[output]
results_dir = "results"
quick_checks = true
artifact_profile = "{artifact_profile}"
{diagnostic_sample_trades_line}
'''.lstrip()
    )
    return load_config(config_path, repo_root=tmp_path)


def canonical_rows_jsonl(rows):
    from quant_strategies.core.serialization import canonical_rows_jsonl as impl

    return impl(rows)


def normalized_rows_sha256(rows):
    from quant_strategies.core.serialization import normalized_rows_sha256 as impl

    return impl(rows)


def summary_profile_payload(*args, **kwargs):
    from quant_strategies.runner.artifact_profiles import summary_profile_payload as impl

    return impl(*args, **kwargs)


def write_summary_profile_artifact(*args, **kwargs):
    from quant_strategies.runner.artifact_profiles import write_summary_profile_artifact as impl

    return impl(*args, **kwargs)


def write_jsonl(*args, **kwargs):
    from quant_strategies.runner.artifacts import write_jsonl as impl

    return impl(*args, **kwargs)


def diagnostic_payload(*args, **kwargs):
    from quant_strategies.runner.diagnostics import diagnostic_payload as impl

    return impl(*args, **kwargs)


def assert_trade_result_metric_semantics(payload: dict[str, object]) -> None:
    metric_semantics = payload["metric_semantics"]
    assert set(metric_semantics) == {
        "trade_result.sum_signed_trade_activity_gross",
        "trade_result.sum_signed_trade_activity_funding",
        "trade_result.sum_signed_trade_activity_cost",
        "trade_result.sum_signed_trade_activity_net",
    }
    net = metric_semantics["trade_result.sum_signed_trade_activity_net"]
    assert set(net) == {
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
    assert net["unit"] == "decimal_fraction"
    assert net["base"] == "signed target-weighted trade activity; not portfolio NAV"
    assert net["backend"] == "execution_kernel"
    assert net["comparability"] == "not_comparable_to_nav_path_returns_without_backend_agreement_test"
    assert net["tolerance"] is None
    assert "not comparable to NAV-path total return" in net["asymmetry"]


def test_normalized_rows_sha256_is_stable_for_json_equivalent_rows():
    timestamp = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows = [
        {"symbol": "SPY", "timestamp": timestamp, "close": 100.0, "nested": {"b": 2, "a": 1}},
        {"nested": {"a": 1, "b": 2}, "close": 101.0, "timestamp": timestamp, "symbol": "SPY"},
    ]

    first = normalized_rows_sha256(rows)
    second = normalized_rows_sha256([dict(item) for item in rows])

    assert first == second
    assert len(first) == 64


def test_write_jsonl_uses_same_canonical_rows_as_normalized_hash(tmp_path: Path):
    timestamp = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows = [
        {"symbol": "SPY", "timestamp": timestamp, "close": 100.0, "nested": {"b": 2, "a": 1}},
        {"nested": {"a": 1, "b": 2}, "close": 101.0, "timestamp": timestamp, "symbol": "SPY"},
    ]
    path = tmp_path / "rows.jsonl"

    written_hash = write_jsonl(path, rows)

    assert written_hash == normalized_rows_sha256(rows)
    assert written_hash == hashlib.sha256(path.read_bytes()).hexdigest()
    assert path.read_text() == canonical_rows_jsonl(rows)


def test_summary_profile_payload_contains_rows_decisions_and_engine(tmp_path: Path):
    timestamp = datetime(2024, 1, 1, tzinfo=timezone.utc)
    run_config = config(tmp_path)
    rows = [
        row("SPY", timestamp, 100.0),
        row("SPY", timestamp.replace(day=2), 101.0),
        row("QQQ", timestamp, 200.0),
    ]
    decisions = [
        decision("SPY", timestamp, "long"),
        decision("QQQ", timestamp, "short"),
    ]

    payload = summary_profile_payload(
        config=run_config,
        rows=rows,
        decisions=decisions,
        engine={
            "passed": True,
            "trade_count": 2,
            "trade_result": {
                "sum_signed_trade_activity_gross": 0.03,
                "sum_signed_trade_activity_funding": 0.0,
                "sum_signed_trade_activity_cost": 0.0,
                "sum_signed_trade_activity_net": 0.03,
            },
        },
    )

    assert payload["artifact_profile"] == "summary"
    assert payload["replayable_from_artifacts"] is False
    assert LEGACY_REPLAYABILITY_METADATA_KEY not in payload
    assert payload["rows"]["row_count"] == 3
    assert payload["rows"]["sample_count"] == 3
    assert payload["rows"]["by_symbol"]["SPY"]["count"] == 2
    assert payload["decisions"]["count"] == 2
    assert payload["decisions"]["by_direction"] == {"long": 1, "short": 1}
    assert "signals" not in payload
    assert payload["engine"] == {
        "passed": True,
        "trade_count": 2,
        "trade_result": {
            "sum_signed_trade_activity_gross": 0.03,
            "sum_signed_trade_activity_funding": 0.0,
            "sum_signed_trade_activity_cost": 0.0,
            "sum_signed_trade_activity_net": 0.03,
        },
    }
    assert_trade_result_metric_semantics(payload)


def test_summary_profile_payload_uses_precomputed_row_hash(tmp_path: Path):
    timestamp = datetime(2024, 1, 1, tzinfo=timezone.utc)
    payload = summary_profile_payload(
        config=config(tmp_path),
        rows=[row("SPY", timestamp, 100.0)],
        decisions=[decision("SPY", timestamp)],
        engine={"passed": True, "trade_count": 1},
        normalized_rows_hash="a" * 64,
    )

    assert payload["rows"]["normalized_rows_sha256"] == "a" * 64


def test_summary_profile_payload_normalizes_common_non_json_row_values(tmp_path: Path):
    timestamp = datetime(2024, 1, 1, tzinfo=timezone.utc)

    payload = summary_profile_payload(
        config=config(tmp_path),
        rows=[{**row("SPY", timestamp, 100.0), "research_nan": float("nan"), "research_decimal": Decimal("1.25")}],
        decisions=[decision("SPY", timestamp)],
        engine={"passed": True, "trade_count": 1},
    )

    sample = payload["rows"]["sample"][0]
    assert sample["research_nan"] is None
    assert sample["research_decimal"] == 1.25
    assert len(payload["rows"]["normalized_rows_sha256"]) == 64


def test_write_summary_profile_artifact_writes_json(tmp_path: Path):
    timestamp = datetime(2024, 1, 1, tzinfo=timezone.utc)
    run_config = config(tmp_path)
    result_dir = tmp_path / "results" / "run"
    result_dir.mkdir(parents=True)

    path = write_summary_profile_artifact(
        result_dir,
        config=run_config,
        rows=[row("SPY", timestamp, 100.0)],
        decisions=[decision("SPY", timestamp)],
        engine={
            "passed": True,
            "trade_count": 1,
            "trade_result": {
                "sum_signed_trade_activity_gross": 0.01,
                "sum_signed_trade_activity_funding": 0.0,
                "sum_signed_trade_activity_cost": 0.0,
                "sum_signed_trade_activity_net": 0.01,
            },
        },
    )

    parsed = json.loads(path.read_text())
    assert path == result_dir / "artifact_profile_summary.json"
    assert parsed["replayable_from_artifacts"] is False
    assert LEGACY_REPLAYABILITY_METADATA_KEY not in parsed
    assert parsed["rows"]["row_count"] == 1
    assert parsed["rows"]["normalized_rows_sha256"] == normalized_rows_sha256([row("SPY", timestamp, 100.0)])
    assert_trade_result_metric_semantics(parsed)


def test_diagnostic_payload_contains_bounded_behavior_slices(tmp_path: Path):
    timestamp = datetime(2024, 1, 1, tzinfo=timezone.utc)
    run_config = config(
        tmp_path,
        artifact_profile="diagnostic",
        diagnostic_sample_trades=2,
    )
    engine = {
        "passed": True,
        "trade_count": 3,
        "trade_result": {
            "sum_signed_trade_activity_gross": 0.06,
            "sum_signed_trade_activity_funding": -0.01,
            "sum_signed_trade_activity_cost": 0.03,
            "sum_signed_trade_activity_net": 0.02,
        },
        "diagnostic_trades": [
            {
                "decision_id": "winner",
                "symbol": "SPY",
                "side": "long",
                "decision_time": timestamp.isoformat(),
                "entry_time": timestamp.isoformat(),
                "exit_time": timestamp.replace(day=2).isoformat(),
                "entry_price": 100.0,
                "exit_price": 105.0,
                "exit_reason": "take_profit",
                "weight": 1.0,
                "gross_return": 0.05,
                "funding_return": 0.0,
                "cost_return": 0.0,
                "net_return": 0.05,
                "decision_metadata": {"family": "test"},
            },
            {
                "decision_id": "loser",
                "symbol": "SPY",
                "side": "short",
                "decision_time": timestamp.isoformat(),
                "entry_time": timestamp.replace(day=2).isoformat(),
                "exit_time": timestamp.replace(day=4).isoformat(),
                "entry_price": 105.0,
                "exit_price": 107.1,
                "exit_reason": "stop_loss",
                "weight": 1.0,
                "gross_return": -0.02,
                "funding_return": -0.01,
                "cost_return": 0.0,
                "net_return": -0.03,
                "decision_metadata": {"family": "test"},
            },
            {
                "decision_id": "costly",
                "symbol": "QQQ",
                "side": "long",
                "decision_time": timestamp.isoformat(),
                "entry_time": timestamp.replace(day=3).isoformat(),
                "exit_time": timestamp.replace(day=4).isoformat(),
                "entry_price": 200.0,
                "exit_price": 206.0,
                "exit_reason": "max_hold",
                "weight": 1.0,
                "gross_return": 0.03,
                "funding_return": 0.0,
                "cost_return": 0.03,
                "net_return": 0.0,
                "decision_metadata": {"family": "test"},
            },
        ],
    }

    payload = diagnostic_payload(
        config=run_config,
        engine=engine,
        assessment_status="quick_check_passed",
        evidence_quality={"causality_verified": True, "evidence_quality_warnings": []},
    )

    assert payload["artifact_profile"] == "diagnostic"
    assert payload["replayable_from_artifacts"] is False
    assert LEGACY_REPLAYABILITY_METADATA_KEY not in payload
    assert payload["trade_count"] == 3
    assert payload["trade_result"] == engine["trade_result"]
    assert payload["assessment_status"] == "quick_check_passed"
    assert payload["evidence_quality"]["causality_verified"] is True
    assert payload["by_symbol"]["SPY"] == {
        "count": 2,
        "gross": pytest.approx(0.03),
        "funding": pytest.approx(-0.01),
        "cost": pytest.approx(0.0),
        "net": pytest.approx(0.02),
    }
    assert payload["by_direction"]["long"]["count"] == 2
    assert payload["by_direction"]["long"]["net"] == pytest.approx(0.05)
    assert payload["by_exit_reason"]["take_profit"]["count"] == 1
    economic_slices = payload["economic_slices"]
    assert economic_slices["schema_version"] == "quant_strategies.runner.economic_slices/v1"
    assert economic_slices["basis"] == "engine_trade_ledger"
    assert economic_slices["by_symbol"]["SPY"]["count"] == 2
    assert economic_slices["by_symbol"]["QQQ"]["count"] == 1
    assert economic_slices["by_direction"]["long"]["count"] == 2
    assert economic_slices["by_direction"]["short"]["count"] == 1
    assert economic_slices["by_exit_reason"]["take_profit"]["count"] == 1
    assert economic_slices["by_exit_reason"]["stop_loss"]["count"] == 1
    assert economic_slices["by_exit_reason"]["max_hold"]["count"] == 1
    assert set(economic_slices["win_loss_distribution"]) == {
        "largest_win_net",
        "largest_loss_net",
        "median_trade_net",
        "sum_positive_net",
        "sum_negative_net",
    }
    assert payload["holding_period"] == {
        "count": 3,
        "min_seconds": 86400.0,
        "median_seconds": 86400.0,
        "max_seconds": 172800.0,
        "average_seconds": 115200.0,
    }
    assert payload["concentration"] == {
        "top_winner_net": 0.05,
        "top_loser_net": -0.03,
        "top_5_winners_net": pytest.approx(0.02),
        "top_5_losers_net": pytest.approx(0.02),
    }
    assert payload["cost_funding_breakdown"] == {
        "gross": 0.06,
        "funding": -0.01,
        "cost": 0.03,
        "net": 0.02,
        "cost_fraction_of_abs_gross": pytest.approx(0.5),
    }
    assert [item["decision_id"] for item in payload["sample_trades"]["largest_winners"]] == [
        "winner",
        "costly",
    ]
    assert [item["decision_id"] for item in payload["sample_trades"]["largest_losers"]] == [
        "loser",
        "costly",
    ]
    assert set(payload["sample_trades"]["largest_winners"][0]) == {
        "decision_id",
        "symbol",
        "side",
        "decision_time",
        "entry_time",
        "exit_time",
        "exit_reason",
        "weight",
        "gross_return",
        "funding_return",
        "cost_return",
        "net_return",
    }
    assert "decision_metadata" not in payload["sample_trades"]["largest_winners"][0]
