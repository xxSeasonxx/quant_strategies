from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

import quant_strategies.core.execution as execution
import quant_strategies.runner as runner_module
import quant_strategies.runner.artifacts as artifacts
from quant_strategies.causality import (
    FOCUSED_CAUSALITY_PROFILE_VERSION,
    FocusedCausalityResult,
    LookaheadCheckResult,
)
from quant_strategies.core import engine_runner
from quant_strategies.core.data_loader import LoadedData
from quant_strategies.core.errors import DataLoadError, EvaluationRunError, RunnerError
from quant_strategies.data_contract import NormalizedRows
from quant_strategies.runner import (
    RunEconomics,
    RunOutcome,
    RunPortfolioFoundation,
    RunResult,
    RunTrade,
    run_config,
)
from quant_strategies.runner import config as config_module

SUMMARY_KEYS = {
    "strategy_id",
    "quick_checks",
    "status",
    "stage",
    "failure_stage",
    "message",
    "artifacts",
    "engine",
    "run_completed",
    "assessment_status",
    "param_contract",
    "artifact_profile",
    "replayable_from_artifacts",
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
    "causality_check",
    "causality_verified",
    "deterministic_replay_verified",
    "emitted_replay_verified",
    "strict_no_emission_verified",
    "strict_replay_capped",
    "strict_probe_count",
    "strict_probe_limit",
    "skipped_probe_count",
    "skipped_probe_reasons",
    "evidence_quality_warnings",
}
TRADE_RESULT_KEYS = {
    "trade_result.sum_signed_trade_activity_gross",
    "trade_result.sum_signed_trade_activity_funding",
    "trade_result.sum_signed_trade_activity_cost",
    "trade_result.sum_signed_trade_activity_net",
}
LEGACY_DISTRIBUTION = "quant" + "-engine"
LEGACY_REPLAYABILITY_METADATA_KEY = "_".join(("artifact", "trust", "tier"))


def rows(
    *closes: float,
    quotes: bool = False,
    research_fields: bool = False,
    include_available_at: bool = True,
    readiness_lag: timedelta = timedelta(0),
) -> list[dict[str, object]]:
    start = datetime(2024, 1, 1, tzinfo=UTC)
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
        if include_available_at:
            row["available_at"] = timestamp + readiness_lag
        if quotes:
            row.update({"bid": close - 0.01, "ask": close + 0.01, "mid": close})
        if research_fields:
            available_at = row["available_at"]
            row.update(
                {
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
    strategy = repo_root / "strategies" / "demo.py"
    strategy.parent.mkdir(parents=True, exist_ok=True)
    if fixed_quote_signal:
        strategy.write_text(
            "from quant_strategies.decisions import ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision\n"
            "def generate_decisions(rows, params):\n"
            "    if len(rows) < 2:\n"
            "        return []\n"
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
        "    if len(rows) < 2:\n"
        "        return []\n"
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
    strategy_path: str = "strategies/demo.py",
    kind: str = "bars",
    symbol: str = "SPY",
    dataset: str | None = "equity_1min",
    start: str = "2024-01-01",
    end: str = "2024-01-05",
    fill_price: str = "close",
    entry_lag_bars: int = 1,
    quick_checks: bool = True,
    artifact_profile: str | None = "full",
    diagnostic_sample_trades: int | None = None,
    causality_check: str | None = None,
    strict_probe_limit: object | None = None,
    focused_probe_limit: object | None = None,
    focused_timeout_seconds: object | None = None,
    micro_probe_limit: object | None = None,
    micro_timeout_seconds: object | None = None,
    foundation_enabled: bool | None = None,
    foundation_subwindows: object | None = None,
    foundation_trial_count: object | None = None,
    foundation_benchmark_sharpe: object | None = None,
    foundation_cost_stress_multiplier: object | None = None,
    foundation_max_gross_exposure: object | None = None,
    params_extra: str = "",
    data_extra: str = "",
) -> Path:
    dataset_line = f'dataset = "{dataset}"\n' if dataset is not None else ""
    artifact_profile_line = (
        f'artifact_profile = "{artifact_profile}"\n' if artifact_profile is not None else ""
    )
    diagnostic_sample_trades_line = (
        f"diagnostic_sample_trades = {diagnostic_sample_trades}\n"
        if diagnostic_sample_trades is not None
        else ""
    )
    causality_check_line = (
        f'causality_check = "{causality_check}"\n' if causality_check is not None else ""
    )
    strict_probe_limit_line = (
        f"strict_probe_limit = {strict_probe_limit}\n" if strict_probe_limit is not None else ""
    )
    focused_probe_limit_line = (
        f"focused_probe_limit = {focused_probe_limit}\n" if focused_probe_limit is not None else ""
    )
    focused_timeout_seconds_line = (
        f"focused_timeout_seconds = {focused_timeout_seconds}\n"
        if focused_timeout_seconds is not None
        else ""
    )
    micro_probe_limit_line = (
        f"micro_probe_limit = {micro_probe_limit}\n" if micro_probe_limit is not None else ""
    )
    micro_timeout_seconds_line = (
        f"micro_timeout_seconds = {micro_timeout_seconds}\n"
        if micro_timeout_seconds is not None
        else ""
    )
    foundation_enabled_line = (
        f"foundation_enabled = {str(foundation_enabled).lower()}\n"
        if foundation_enabled is not None
        else ""
    )
    foundation_subwindows_line = (
        f"foundation_subwindows = {foundation_subwindows}\n"
        if foundation_subwindows is not None
        else ""
    )
    foundation_trial_count_line = (
        f"foundation_trial_count = {foundation_trial_count}\n"
        if foundation_trial_count is not None
        else ""
    )
    foundation_benchmark_sharpe_line = (
        f"foundation_benchmark_sharpe = {foundation_benchmark_sharpe}\n"
        if foundation_benchmark_sharpe is not None
        else ""
    )
    foundation_cost_stress_multiplier_line = (
        f"foundation_cost_stress_multiplier = {foundation_cost_stress_multiplier}\n"
        if foundation_cost_stress_multiplier is not None
        else ""
    )
    foundation_max_gross_exposure_line = (
        f"foundation_max_gross_exposure = {foundation_max_gross_exposure}\n"
        if foundation_max_gross_exposure is not None
        else ""
    )
    config_path = repo_root / relative_path
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        f'''
strategy_path = "{strategy_path}"
strategy_id = "demo"

[data]
kind = "{kind}"
{dataset_line}symbols = ["{symbol}"]
start = "{start}"
end = "{end}"
{data_extra}

[params]
{params_extra}

[fill_model]
price = "{fill_price}"
entry_lag_bars = {entry_lag_bars}

[cost_model]
fee_bps_per_side = 0.0
slippage_bps_per_side = 0.0

[output]
	results_dir = "results"
	quick_checks = {str(quick_checks).lower()}
			{artifact_profile_line}{diagnostic_sample_trades_line}{causality_check_line}{strict_probe_limit_line}{focused_probe_limit_line}{focused_timeout_seconds_line}{micro_probe_limit_line}{micro_timeout_seconds_line}{foundation_enabled_line}{foundation_subwindows_line}{foundation_trial_count_line}{foundation_benchmark_sharpe_line}{foundation_cost_stress_multiplier_line}{foundation_max_gross_exposure_line}
				'''.lstrip()
    )
    return config_path


def read_summary(result_dir: Path) -> dict[str, object]:
    summary = json.loads((result_dir / "summary.json").read_text())
    assert set(summary) >= SUMMARY_KEYS
    assert all((result_dir / name).exists() for name in summary["artifacts"])
    if summary["stage"] == "completed":
        assert summary["failure_stage"] is None
    else:
        assert summary["failure_stage"] == summary["stage"]
    assert summary["run_completed"] is (summary["failure_stage"] is None)
    return summary


def assert_assessment(
    result: RunResult,
    summary: dict[str, object],
    *,
    assessment_status: str,
    run_completed: bool | None = None,
    promotion_eligible: bool = False,
    artifact_profile: str = "full",
    failure_stage: str | None = None,
) -> None:
    expected_run_completed = failure_stage is None if run_completed is None else run_completed
    expected_replayable = artifact_profile == "full"
    assert result.outcome.completed is expected_run_completed
    assert result.outcome.failure_stage == failure_stage
    assert result.outcome.assessment_status == assessment_status
    assert result.outcome.promotion_eligible is promotion_eligible
    assert result.evidence.replayable_from_artifacts is expected_replayable
    assert result.evidence.data_availability_status == summary["data_availability_status"]
    assert result.evidence.availability_coverage == summary["availability_coverage"]
    assert result.evidence.row_contract == summary["row_contract"]
    assert result.evidence.causality.verified is summary["causality_verified"]
    assert result.evidence.causality.emitted_replay_verified is summary["emitted_replay_verified"]
    assert (
        result.evidence.causality.strict_no_emission_verified
        is summary["strict_no_emission_verified"]
    )
    assert result.evidence.warnings == tuple(summary["evidence_quality_warnings"])
    assert summary["run_completed"] is expected_run_completed
    assert summary["failure_stage"] == failure_stage
    assert summary["assessment_status"] == assessment_status
    assert summary["artifact_profile"] == artifact_profile
    assert summary["replayable_from_artifacts"] is expected_replayable
    assert summary["evidence_class"] == "quick_run_diagnostic"
    assert summary["strategy_contract"] == "decision"
    assert summary["return_model"] == "trade_result.sum_signed_trade_activity_net"
    assert summary["funding_model"] == "none"
    assert_trade_result_metric_semantics(summary)
    assert summary["promotion_eligible"] is promotion_eligible
    assert summary["paper_trade_eligible"] is False
    assert summary["live_eligible"] is False
    assert summary["requires_manual_approval"] is True


def assert_trade_result_metric_semantics(payload: dict[str, object]) -> None:
    metric_semantics = payload["metric_semantics"]
    assert set(metric_semantics) == TRADE_RESULT_KEYS
    for name in TRADE_RESULT_KEYS:
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
        assert semantics["backend"] == "execution_kernel"
        assert (
            semantics["comparability"]
            == "not_comparable_to_nav_path_returns_without_backend_agreement_test"
        )
        assert semantics["tolerance"] is None
        assert semantics["asymmetry"]


def assert_summary_economic_metrics(payload: dict[str, object]) -> dict[str, object]:
    metrics = payload["economic_metrics"]
    assert isinstance(metrics, dict)
    assert metrics["schema_version"] == "quant_strategies.runner.economic_metrics/v1"
    assert metrics["basis"] == "engine_trade_ledger"
    assert set(metrics) == {
        "schema_version",
        "basis",
        "trade_count",
        "winning_trade_count",
        "losing_trade_count",
        "flat_trade_count",
        "hit_rate",
        "average_trade_net",
        "average_win_net",
        "average_loss_net",
        "profit_factor",
        "cost_share_of_abs_gross",
        "funding_share_of_abs_gross",
    }
    return metrics


def assert_no_mode_fields(value: object) -> None:
    if isinstance(value, dict):
        assert "mode" not in value
        for item in value.values():
            assert_no_mode_fields(item)
    elif isinstance(value, list):
        for item in value:
            assert_no_mode_fields(item)


def test_runner_config_accepts_causality_policy_fields(tmp_path: Path):
    default_config = config_module.load_config(write_config(tmp_path), repo_root=tmp_path)

    assert default_config.output.causality_check == "strict"
    assert default_config.output.strict_probe_limit is None

    for mode in ("off", "emitted", "strict", "focused", "micro"):
        config = config_module.load_config(
            write_config(tmp_path, relative_path=f"{mode}.toml", causality_check=mode),
            repo_root=tmp_path,
        )
        assert config.output.causality_check == mode
        assert config.output.strict_probe_limit is None

    capped = config_module.load_config(
        write_config(
            tmp_path,
            relative_path="capped.toml",
            causality_check="strict",
            strict_probe_limit=10,
        ),
        repo_root=tmp_path,
    )
    assert capped.output.causality_check == "strict"
    assert capped.output.strict_probe_limit == 10

    focused = config_module.load_config(
        write_config(
            tmp_path,
            relative_path="focused-custom.toml",
            causality_check="focused",
            focused_probe_limit=7,
            focused_timeout_seconds=12.5,
        ),
        repo_root=tmp_path,
    )
    assert focused.output.causality_check == "focused"
    assert focused.output.focused_probe_limit == 7
    assert focused.output.focused_timeout_seconds == 12.5

    micro = config_module.load_config(
        write_config(
            tmp_path,
            relative_path="micro-custom.toml",
            causality_check="micro",
            micro_probe_limit=3,
            micro_timeout_seconds=1.5,
        ),
        repo_root=tmp_path,
    )
    assert micro.output.causality_check == "micro"
    assert micro.output.micro_probe_limit == 3
    assert micro.output.micro_timeout_seconds == 1.5


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"causality_check": "sampled"}, "causality_check"),
        ({"strict_probe_limit": -1}, "strict_probe_limit"),
        ({"strict_probe_limit": "true"}, "strict_probe_limit"),
        ({"strict_probe_limit": "1.0"}, "strict_probe_limit"),
        ({"focused_probe_limit": 0}, "focused_probe_limit"),
        ({"focused_timeout_seconds": "inf"}, "focused_timeout_seconds"),
        ({"micro_probe_limit": 0}, "micro_probe_limit"),
        ({"micro_timeout_seconds": "inf"}, "micro_timeout_seconds"),
    ],
)
def test_runner_config_rejects_invalid_causality_policy_fields(
    tmp_path: Path,
    kwargs: dict[str, object],
    message: str,
):
    config_path = write_config(tmp_path, **kwargs)

    with pytest.raises(RunnerError, match=message):
        config_module.load_config(config_path, repo_root=tmp_path)


def test_run_config_routes_default_causality_policy_to_strict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path, artifact_profile="diagnostic")
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)),
    )
    modes: list[str] = []

    def fake_check_hidden_lookahead(*args, mode="missing", **kwargs):
        modes.append(mode)
        return LookaheadCheckResult(
            passed=True,
            mode=mode,
            deterministic_replay_verified=True,
            emitted_replay_verified=True,
            strict_suppression_verified=mode == "strict",
        )

    monkeypatch.setattr(runner_module, "check_hidden_lookahead", fake_check_hidden_lookahead)

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is True
    assert modes == ["strict"]
    assert result.evidence.causality.causality_check == "strict"
    assert result.evidence.causality.deterministic_replay_verified is True
    summary = read_summary(result.result_dir)
    assert summary["causality_check"] == "strict"
    assert summary["deterministic_replay_verified"] is True
    assert summary["strict_no_emission_verified"] is True


def test_run_config_emitted_policy_completes_without_strict_suppression_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    strategy = tmp_path / "strategies" / "demo.py"
    strategy.parent.mkdir(parents=True, exist_ok=True)
    strategy.write_text(
        "from quant_strategies.decisions import ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision\n"
        "def generate_decisions(rows, params):\n"
        "    if len(rows) < 2:\n"
        "        return []\n"
        "    as_of_row = rows[1]\n"
        "    future = [row for row in rows if row['timestamp'] > as_of_row['timestamp']]\n"
        "    if any(row['close'] < as_of_row['close'] for row in future):\n"
        "        return []\n"
        "    return [StrategyDecision(\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='equity_or_etf', symbol=as_of_row['symbol']),\n"
        "        decision_time=as_of_row['timestamp'],\n"
        "        as_of_time=as_of_row['timestamp'],\n"
        "        target=PositionTarget(direction='long', sizing_kind='target_weight', size=1.0),\n"
        "        exit_policy=ExitPolicy(max_hold_bars=1),\n"
        "    )]\n"
    )
    config_path = write_config(
        tmp_path,
        artifact_profile="diagnostic",
        causality_check="emitted",
    )
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=rows(100.0, 101.0, 99.0, research_fields=True)),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is True
    assert result.economics is not None
    assert result.evidence.causality.causality_check == "emitted"
    assert result.evidence.causality.deterministic_replay_verified is True
    assert result.evidence.causality.emitted_replay_verified is True
    assert result.evidence.causality.strict_no_emission_verified is False
    summary = read_summary(result.result_dir)
    data_manifest = json.loads((result.result_dir / "data_manifest.json").read_text())
    diagnostics = json.loads((result.result_dir / "diagnostics.json").read_text())
    assert summary["stage"] == "completed"
    assert summary["causality_check"] == "emitted"
    assert summary["causality_verified"] is False
    assert summary["deterministic_replay_verified"] is True
    assert summary["emitted_replay_verified"] is True
    assert summary["strict_no_emission_verified"] is False
    assert summary["evidence_quality_warnings"] == [
        "strict_suppression_replay_not_verified",
        "runner_causality_not_verified",
    ]
    assert data_manifest["causality_check"] == summary["causality_check"]
    assert data_manifest["deterministic_replay_verified"] is True
    assert diagnostics["evidence_quality"]["causality_check"] == "emitted"
    assert diagnostics["evidence_quality"]["strict_no_emission_verified"] is False


def test_run_config_off_policy_marks_replay_unverified_but_keeps_other_gates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    strategy = tmp_path / "strategies" / "demo.py"
    strategy.parent.mkdir(parents=True, exist_ok=True)
    strategy.write_text(
        "from quant_strategies.decisions import ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision\n"
        "def generate_decisions(rows, params):\n"
        "    as_of_row = rows[1]\n"
        "    future_rows = [row for row in rows if row['timestamp'] > as_of_row['timestamp']]\n"
        "    decision_id = 'future-visible' if future_rows else 'prefix-only'\n"
        "    return [StrategyDecision(\n"
        "        decision_id=decision_id,\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='equity_or_etf', symbol=as_of_row['symbol']),\n"
        "        decision_time=as_of_row['timestamp'],\n"
        "        as_of_time=as_of_row['timestamp'],\n"
        "        target=PositionTarget(direction='long', sizing_kind='target_weight', size=1.0),\n"
        "        exit_policy=ExitPolicy(max_hold_bars=1),\n"
        "    )]\n"
    )
    config_path = write_config(tmp_path, artifact_profile="diagnostic", causality_check="off")
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is True
    assert result.economics is not None
    assert result.evidence.causality.causality_check == "off"
    assert result.evidence.causality.deterministic_replay_verified is False
    assert result.evidence.causality.emitted_replay_verified is False
    assert result.evidence.causality.strict_no_emission_verified is False
    summary = read_summary(result.result_dir)
    data_manifest = json.loads((result.result_dir / "data_manifest.json").read_text())
    diagnostics = json.loads((result.result_dir / "diagnostics.json").read_text())
    assert summary["stage"] == "completed"
    assert summary["causality_check"] == "off"
    assert summary["causality_verified"] is False
    assert summary["evidence_quality_warnings"] == [
        "causality_replay_skipped",
        "runner_causality_not_verified",
    ]
    assert summary["promotion_eligible"] is False
    assert summary["paper_trade_eligible"] is False
    assert summary["live_eligible"] is False
    assert data_manifest["causality_check"] == "off"
    assert diagnostics["evidence_quality"]["causality_check"] == "off"


def test_run_config_emitted_policy_failure_before_causality_keeps_selected_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    config_path = write_config(
        tmp_path,
        artifact_profile="summary",
        causality_check="emitted",
    )

    def fail_data_load(config, **_kwargs):
        raise DataLoadError("strict data window failed")

    monkeypatch.setattr(execution, "load_data", fail_data_load)

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is False
    assert result.evidence.causality.causality_check == "emitted"
    summary = read_summary(result.result_dir)
    assert summary["stage"] == "data_load"
    assert summary["causality_check"] == "emitted"
    assert summary["deterministic_replay_verified"] is False
    assert summary["emitted_replay_verified"] is False
    assert summary["strict_no_emission_verified"] is False


def test_run_config_capped_strict_replay_records_incomplete_strict_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    config_path = write_config(
        tmp_path,
        artifact_profile="diagnostic",
        causality_check="strict",
        strict_probe_limit=1,
    )
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is True
    assert result.evidence.causality.causality_check == "strict"
    assert result.evidence.causality.deterministic_replay_verified is True
    assert result.evidence.causality.emitted_replay_verified is True
    assert result.evidence.causality.strict_no_emission_verified is False
    assert result.evidence.causality.strict_replay_capped is True
    assert result.evidence.causality.strict_probe_limit == 1
    summary = read_summary(result.result_dir)
    data_manifest = json.loads((result.result_dir / "data_manifest.json").read_text())
    assert summary["causality_check"] == "strict"
    assert summary["strict_probe_limit"] == 1
    assert summary["strict_replay_capped"] is True
    assert summary["strict_no_emission_verified"] is False
    assert summary["evidence_quality_warnings"] == [
        "strict_suppression_replay_not_verified",
        "strict_replay_capped",
        "runner_causality_not_verified",
    ]
    assert data_manifest["strict_replay_capped"] is True
    assert data_manifest["strict_no_emission_verified"] is False


def test_run_config_focused_policy_pass_allows_scoring_and_writes_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    config_path = write_config(
        tmp_path,
        artifact_profile="diagnostic",
        causality_check="focused",
        focused_probe_limit=5,
        focused_timeout_seconds=60.0,
    )
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)),
    )
    calls = 0

    def fake_check_focused_causality(*args, key, config, **kwargs):
        nonlocal calls
        calls += 1
        return FocusedCausalityResult(
            status="passed",
            scoring_allowed=True,
            key=key,
            profile_version=config.profile_version,
            timeout_seconds=config.timeout_seconds,
            candidate_probe_count=9,
            selected_probe_count=5,
        )

    monkeypatch.setattr(runner_module, "check_focused_causality", fake_check_focused_causality)

    result = run_config(config_path, repo_root=tmp_path)

    assert calls == 1
    assert result.outcome.completed is True
    assert result.evidence.focused_causality.status == "passed"
    assert result.evidence.focused_causality.scoring_allowed is True
    assert result.evidence.focused_causality.strategy_id == "demo"
    assert result.evidence.focused_causality.data_kind == "bars"
    assert result.evidence.focused_causality.normalized_rows_sha256 is not None
    assert result.evidence.focused_causality.params_sha256 is not None
    assert result.evidence.focused_causality.max_probes == 5
    assert result.evidence.focused_causality.timeout_seconds_key == 60.0
    summary = read_summary(result.result_dir)
    data_manifest = json.loads((result.result_dir / "data_manifest.json").read_text())
    diagnostics = json.loads((result.result_dir / "diagnostics.json").read_text())
    assert summary["focused_causality"]["status"] == "passed"
    assert summary["focused_causality"]["scoring_allowed"] is True
    assert summary["focused_causality"]["selected_probe_count"] == 5
    assert summary["focused_causality"]["max_probes"] == 5
    assert summary["deterministic_replay_verified"] is False
    assert summary["emitted_replay_verified"] is False
    assert summary["strict_no_emission_verified"] is False
    assert data_manifest["focused_causality"]["status"] == "passed"
    assert diagnostics["evidence_quality"]["focused_causality"]["status"] == "passed"


def test_run_config_focused_policy_real_replay_keeps_low_level_flags_unverified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    config_path = write_config(
        tmp_path,
        artifact_profile="diagnostic",
        causality_check="focused",
    )
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)),
    )

    first = run_config(config_path, repo_root=tmp_path)
    second = run_config(config_path, repo_root=tmp_path)

    assert first.outcome.completed is True
    assert second.outcome.completed is True
    for result in (first, second):
        assert result.evidence.focused_causality.status == "passed"
        assert result.evidence.causality.deterministic_replay_verified is False
        assert result.evidence.causality.emitted_replay_verified is False
        assert result.evidence.causality.strict_no_emission_verified is False
        summary = read_summary(result.result_dir)
        assert summary["focused_causality"]["status"] == "passed"
        assert summary["deterministic_replay_verified"] is False
        assert summary["emitted_replay_verified"] is False
        assert summary["strict_no_emission_verified"] is False
    assert second.evidence.focused_causality.cache_hit is True


def test_run_config_micro_policy_timeout_still_scores_and_writes_unverified_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    config_path = write_config(
        tmp_path,
        artifact_profile="diagnostic",
        causality_check="micro",
        micro_probe_limit=3,
        micro_timeout_seconds=0.01,
    )
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)),
    )

    def fake_check_micro_causality(*args, **kwargs):
        return LookaheadCheckResult(
            passed=False,
            mode="strict",
            violations=("micro_causality_timeout",),
            replay_scope="micro",
            candidate_probe_count=9,
            selected_probe_count=3,
            elapsed_seconds=0.02,
            timeout_seconds=0.01,
            timed_out=True,
            replay_warning="micro_causality_timeout",
        )

    monkeypatch.setattr(runner_module, "check_micro_causality", fake_check_micro_causality)

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is True
    assert result.economics is not None
    assert result.evidence.causality.causality_check == "micro"
    assert result.evidence.causality.verified is False
    assert result.evidence.causality.replay_scope == "micro"
    assert result.evidence.causality.timed_out is True
    assert result.evidence.causality.replay_warning == "micro_causality_timeout"
    summary = read_summary(result.result_dir)
    assert summary["status"] == "completed"
    assert summary["causality_check"] == "micro"
    assert summary["causality_verified"] is False
    assert summary["replay_scope"] == "micro"
    assert summary["timed_out"] is True
    assert "economic_metrics" in summary


@pytest.mark.parametrize(
    ("micro_result", "verified", "warning"),
    [
        (
            LookaheadCheckResult(
                passed=True,
                mode="strict",
                deterministic_replay_verified=True,
                emitted_replay_verified=True,
                strict_suppression_verified=True,
                replay_scope="micro",
                candidate_probe_count=9,
                selected_probe_count=3,
                elapsed_seconds=0.01,
                timeout_seconds=2.0,
            ),
            False,
            None,
        ),
        (
            LookaheadCheckResult(
                passed=False,
                mode="strict",
                violations=("hidden_lookahead_detected",),
                replay_scope="micro",
                candidate_probe_count=9,
                selected_probe_count=3,
                elapsed_seconds=0.01,
                timeout_seconds=2.0,
                replay_warning="hidden_lookahead_detected",
            ),
            False,
            "hidden_lookahead_detected",
        ),
    ],
)
def test_run_config_micro_policy_pass_or_failure_still_scores(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    micro_result: LookaheadCheckResult,
    verified: bool,
    warning: str | None,
):
    write_strategy(tmp_path)
    config_path = write_config(
        tmp_path,
        artifact_profile="diagnostic",
        causality_check="micro",
        micro_probe_limit=3,
        micro_timeout_seconds=2.0,
    )
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)),
    )
    monkeypatch.setattr(
        runner_module,
        "check_micro_causality",
        lambda *_args, **_kwargs: micro_result,
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is True
    assert result.economics is not None
    assert result.evidence.causality.verified is verified
    assert result.evidence.causality.replay_scope == "micro"
    assert result.evidence.causality.selected_probe_count == 3
    assert result.evidence.causality.replay_warning == warning
    summary = read_summary(result.result_dir)
    assert summary["status"] == "completed"
    assert summary["replay_scope"] == "micro"
    assert summary["selected_probe_count"] == 3
    assert "economic_metrics" in summary


def test_run_config_focused_policy_failure_rejects_before_engine_scoring(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    config_path = write_config(
        tmp_path,
        artifact_profile="diagnostic",
        causality_check="focused",
    )
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)),
    )

    def fake_check_focused_causality(*args, key, config, **kwargs):
        return FocusedCausalityResult(
            status="failed",
            scoring_allowed=False,
            key=key,
            profile_version=config.profile_version,
            timeout_seconds=config.timeout_seconds,
            candidate_probe_count=9,
            selected_probe_count=5,
            rejection_reason="hidden_lookahead_detected",
        )

    monkeypatch.setattr(runner_module, "check_focused_causality", fake_check_focused_causality)
    monkeypatch.setattr(
        engine_runner,
        "build_request",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("focused failure should stop before engine scoring")
        ),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is False
    assert result.outcome.failure_stage == "causality"
    assert result.evidence.focused_causality.status == "failed"
    assert result.evidence.focused_causality.scoring_allowed is False
    assert result.evidence.focused_causality.rejection_reason == "hidden_lookahead_detected"
    summary = read_summary(result.result_dir)
    assert summary["focused_causality"]["status"] == "failed"
    assert summary["focused_causality"]["scoring_allowed"] is False
    assert summary["focused_causality"]["rejection_reason"] == "hidden_lookahead_detected"


def test_run_config_focused_policy_timeout_rejects_before_engine_scoring(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    config_path = write_config(
        tmp_path,
        artifact_profile="diagnostic",
        causality_check="focused",
    )
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)),
    )

    def fake_check_focused_causality(*args, key, config, **kwargs):
        return FocusedCausalityResult(
            status="timeout",
            scoring_allowed=False,
            key=key,
            profile_version=config.profile_version,
            timeout_seconds=config.timeout_seconds,
            candidate_probe_count=9,
            selected_probe_count=5,
            rejection_reason="focused_causality_timeout",
        )

    monkeypatch.setattr(runner_module, "check_focused_causality", fake_check_focused_causality)
    monkeypatch.setattr(
        engine_runner,
        "build_request",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("focused timeout should stop before engine scoring")
        ),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is False
    assert result.outcome.failure_stage == "causality"
    assert result.evidence.focused_causality.status == "timeout"
    assert result.evidence.focused_causality.rejection_reason == "focused_causality_timeout"
    summary = read_summary(result.result_dir)
    assert summary["focused_causality"]["status"] == "timeout"
    assert summary["focused_causality"]["scoring_allowed"] is False


def test_run_config_focused_policy_pass_cache_skips_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    config_path = write_config(
        tmp_path,
        artifact_profile="diagnostic",
        causality_check="focused",
    )
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)),
    )
    calls = 0

    def fake_check_focused_causality(*args, key, config, **kwargs):
        nonlocal calls
        calls += 1
        return FocusedCausalityResult(
            status="passed",
            scoring_allowed=True,
            key=key,
            profile_version=config.profile_version,
            timeout_seconds=config.timeout_seconds,
            candidate_probe_count=9,
            selected_probe_count=5,
        )

    monkeypatch.setattr(runner_module, "check_focused_causality", fake_check_focused_causality)

    first = run_config(config_path, repo_root=tmp_path)
    second = run_config(config_path, repo_root=tmp_path)

    assert first.outcome.completed is True
    assert second.outcome.completed is True
    assert calls == 1
    assert second.evidence.focused_causality.cache_hit is True
    second_summary = read_summary(second.result_dir)
    assert second_summary["focused_causality"]["cache_hit"] is True
    assert (
        second_summary["focused_causality"]["profile_version"] == FOCUSED_CAUSALITY_PROFILE_VERSION
    )


def test_run_config_focused_policy_failed_cache_rejects_without_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    config_path = write_config(
        tmp_path,
        artifact_profile="diagnostic",
        causality_check="focused",
    )
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)),
    )
    calls = 0

    def fake_check_focused_causality(*args, key, config, **kwargs):
        nonlocal calls
        calls += 1
        return FocusedCausalityResult(
            status="failed",
            scoring_allowed=False,
            key=key,
            profile_version=config.profile_version,
            timeout_seconds=config.timeout_seconds,
            candidate_probe_count=9,
            selected_probe_count=5,
            rejection_reason="hidden_lookahead_detected",
        )

    monkeypatch.setattr(runner_module, "check_focused_causality", fake_check_focused_causality)

    first = run_config(config_path, repo_root=tmp_path)
    second = run_config(config_path, repo_root=tmp_path)

    assert first.outcome.completed is False
    assert second.outcome.completed is False
    assert calls == 1
    assert second.evidence.focused_causality.cache_hit is True
    second_summary = read_summary(second.result_dir)
    assert second_summary["focused_causality"]["cache_hit"] is True
    assert second_summary["focused_causality"]["status"] == "failed"


def test_run_config_focused_policy_profile_version_change_invalidates_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    config_path = write_config(
        tmp_path,
        artifact_profile="diagnostic",
        causality_check="focused",
    )
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)),
    )
    calls = 0

    def fake_check_focused_causality(*args, key, config, **kwargs):
        nonlocal calls
        calls += 1
        return FocusedCausalityResult(
            status="passed",
            scoring_allowed=True,
            key=key,
            profile_version=config.profile_version,
            timeout_seconds=config.timeout_seconds,
            candidate_probe_count=9,
            selected_probe_count=5,
        )

    monkeypatch.setattr(runner_module, "check_focused_causality", fake_check_focused_causality)

    first = run_config(config_path, repo_root=tmp_path)
    monkeypatch.setattr(runner_module, "FOCUSED_CAUSALITY_PROFILE_VERSION", "focused-test/v2")
    second = run_config(config_path, repo_root=tmp_path)

    assert first.outcome.completed is True
    assert second.outcome.completed is True
    assert calls == 2
    assert second.evidence.focused_causality.cache_hit is False
    second_summary = read_summary(second.result_dir)
    assert second_summary["focused_causality"]["profile_version"] == "focused-test/v2"


def test_run_config_focused_policy_source_change_invalidates_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    config_path = write_config(
        tmp_path,
        artifact_profile="diagnostic",
        causality_check="focused",
    )
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)),
    )
    calls = 0

    def fake_check_focused_causality(*args, key, config, **kwargs):
        nonlocal calls
        calls += 1
        return FocusedCausalityResult(
            status="passed",
            scoring_allowed=True,
            key=key,
            profile_version=config.profile_version,
            timeout_seconds=config.timeout_seconds,
            candidate_probe_count=9,
            selected_probe_count=5,
        )

    monkeypatch.setattr(runner_module, "check_focused_causality", fake_check_focused_causality)

    first = run_config(config_path, repo_root=tmp_path)
    strategy = tmp_path / "strategies" / "demo.py"
    strategy.write_text(strategy.read_text() + "\n# source hash changed\n")
    second = run_config(config_path, repo_root=tmp_path)

    assert first.outcome.completed is True
    assert second.outcome.completed is True
    assert calls == 2
    assert second.evidence.focused_causality.cache_hit is False


def test_run_config_focused_policy_probe_limit_change_invalidates_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    first_config = write_config(
        tmp_path,
        relative_path="focused-small.toml",
        artifact_profile="diagnostic",
        causality_check="focused",
        focused_probe_limit=1,
    )
    second_config = write_config(
        tmp_path,
        relative_path="focused-large.toml",
        artifact_profile="diagnostic",
        causality_check="focused",
        focused_probe_limit=8,
    )
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)),
    )
    calls = 0

    def fake_check_focused_causality(*args, key, config, **kwargs):
        nonlocal calls
        calls += 1
        return FocusedCausalityResult(
            status="passed",
            scoring_allowed=True,
            key=key,
            profile_version=config.profile_version,
            timeout_seconds=config.timeout_seconds,
            candidate_probe_count=9,
            selected_probe_count=config.max_probes,
        )

    monkeypatch.setattr(runner_module, "check_focused_causality", fake_check_focused_causality)

    first = run_config(first_config, repo_root=tmp_path)
    second = run_config(second_config, repo_root=tmp_path)

    assert first.outcome.completed is True
    assert second.outcome.completed is True
    assert calls == 2
    assert second.evidence.focused_causality.cache_hit is False
    second_summary = read_summary(second.result_dir)
    assert second_summary["focused_causality"]["max_probes"] == 8


def test_run_config_focused_policy_row_hash_change_invalidates_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    config_path = write_config(
        tmp_path,
        artifact_profile="diagnostic",
        causality_check="focused",
    )
    loaded_batches = [
        rows(100.0, 101.0, 102.0, 104.0),
        rows(100.0, 101.0, 103.0, 104.0),
    ]

    def load_data(config, **_kwargs):
        return LoadedData(rows=loaded_batches.pop(0))

    monkeypatch.setattr(execution, "load_data", load_data)
    calls = 0

    def fake_check_focused_causality(*args, key, config, **kwargs):
        nonlocal calls
        calls += 1
        return FocusedCausalityResult(
            status="passed",
            scoring_allowed=True,
            key=key,
            profile_version=config.profile_version,
            timeout_seconds=config.timeout_seconds,
            candidate_probe_count=9,
            selected_probe_count=5,
        )

    monkeypatch.setattr(runner_module, "check_focused_causality", fake_check_focused_causality)

    first = run_config(config_path, repo_root=tmp_path)
    second = run_config(config_path, repo_root=tmp_path)

    assert first.outcome.completed is True
    assert second.outcome.completed is True
    assert calls == 2
    assert second.evidence.focused_causality.cache_hit is False


def test_run_config_focused_policy_params_hash_change_invalidates_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    first_config = write_config(
        tmp_path,
        relative_path="focused-param-a.toml",
        artifact_profile="diagnostic",
        causality_check="focused",
        params_extra="threshold = 1\n",
    )
    second_config = write_config(
        tmp_path,
        relative_path="focused-param-b.toml",
        artifact_profile="diagnostic",
        causality_check="focused",
        params_extra="threshold = 2\n",
    )
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)),
    )
    calls = 0

    def fake_check_focused_causality(*args, key, config, **kwargs):
        nonlocal calls
        calls += 1
        return FocusedCausalityResult(
            status="passed",
            scoring_allowed=True,
            key=key,
            profile_version=config.profile_version,
            timeout_seconds=config.timeout_seconds,
            candidate_probe_count=9,
            selected_probe_count=5,
        )

    monkeypatch.setattr(runner_module, "check_focused_causality", fake_check_focused_causality)

    first = run_config(first_config, repo_root=tmp_path)
    second = run_config(second_config, repo_root=tmp_path)

    assert first.outcome.completed is True
    assert second.outcome.completed is True
    assert calls == 2
    assert second.evidence.focused_causality.cache_hit is False


def test_run_config_focused_policy_timeout_budget_change_invalidates_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    first_config = write_config(
        tmp_path,
        relative_path="focused-timeout-a.toml",
        artifact_profile="diagnostic",
        causality_check="focused",
        focused_timeout_seconds=30.0,
    )
    second_config = write_config(
        tmp_path,
        relative_path="focused-timeout-b.toml",
        artifact_profile="diagnostic",
        causality_check="focused",
        focused_timeout_seconds=60.0,
    )
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)),
    )
    calls = 0

    def fake_check_focused_causality(*args, key, config, **kwargs):
        nonlocal calls
        calls += 1
        return FocusedCausalityResult(
            status="passed",
            scoring_allowed=True,
            key=key,
            profile_version=config.profile_version,
            timeout_seconds=config.timeout_seconds,
            candidate_probe_count=9,
            selected_probe_count=5,
        )

    monkeypatch.setattr(runner_module, "check_focused_causality", fake_check_focused_causality)

    first = run_config(first_config, repo_root=tmp_path)
    second = run_config(second_config, repo_root=tmp_path)

    assert first.outcome.completed is True
    assert second.outcome.completed is True
    assert calls == 2
    assert second.evidence.focused_causality.cache_hit is False


def test_run_config_strategy_and_replay_do_not_see_execution_buffer_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    strategy = tmp_path / "strategies" / "demo.py"
    strategy.parent.mkdir(parents=True, exist_ok=True)
    strategy.write_text(
        "from quant_strategies.decisions import ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision\n"
        "def generate_decisions(rows, params):\n"
        "    if any(row['timestamp'].isoformat().startswith('2024-01-03') for row in rows):\n"
        "        raise RuntimeError('strategy saw execution buffer row')\n"
        "    return [StrategyDecision(\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='equity_or_etf', symbol=rows[-1]['symbol']),\n"
        "        decision_time=rows[-1]['timestamp'],\n"
        "        as_of_time=rows[-1]['timestamp'],\n"
        "        target=PositionTarget(direction='long', sizing_kind='target_weight', size=1.0),\n"
        "        exit_policy=ExitPolicy(max_hold_bars=1),\n"
        "        metadata={'strategy_row_count': len(rows)},\n"
        "    )]\n"
    )
    config_path = write_config(
        tmp_path,
        end="2024-01-02",
        data_extra='load_end = "2024-01-04"\n',
        artifact_profile="full",
        causality_check="emitted",
    )
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is True
    assert result.economics is not None
    assert result.economics.trade_count == 1
    decision_record = json.loads(
        (result.result_dir / "decision_records.jsonl").read_text().splitlines()[0]
    )
    assert decision_record["metadata"]["strategy_row_count"] == 2
    strategy_rows = (result.result_dir / "strategy_input_rows.jsonl").read_text().splitlines()
    assert len(strategy_rows) == 2
    data_manifest = json.loads((result.result_dir / "data_manifest.json").read_text())
    assert data_manifest["rows"]["total"] == 2
    assert data_manifest["execution_rows"]["total"] == 4


def test_run_config_execution_buffer_fills_late_decision_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    strategy = tmp_path / "strategies" / "demo.py"
    strategy.parent.mkdir(parents=True, exist_ok=True)
    strategy.write_text(
        "from quant_strategies.decisions import ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision\n"
        "def generate_decisions(rows, params):\n"
        "    return [StrategyDecision(\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='equity_or_etf', symbol=rows[-1]['symbol']),\n"
        "        decision_time=rows[-1]['timestamp'],\n"
        "        as_of_time=rows[-1]['timestamp'],\n"
        "        target=PositionTarget(direction='long', sizing_kind='target_weight', size=1.0),\n"
        "        exit_policy=ExitPolicy(max_hold_bars=1),\n"
        "    )]\n"
    )
    config_path = write_config(
        tmp_path,
        end="2024-01-02",
        data_extra='load_end = "2024-01-04"\n',
        artifact_profile="diagnostic",
        causality_check="emitted",
    )
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is True
    assert result.economics is not None
    assert result.economics.trade_count == 1
    assert result.economics.trades[0].decision_time.isoformat().startswith("2024-01-02")
    data_manifest = json.loads((result.result_dir / "data_manifest.json").read_text())
    assert data_manifest["rows"]["total"] == 2
    assert data_manifest["execution_rows"]["total"] == 4


def test_run_config_fails_when_buffer_has_no_decision_window_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    config_path = write_config(
        tmp_path,
        end="2024-01-02",
        data_extra='load_end = "2024-01-04"\n',
        artifact_profile="diagnostic",
    )
    buffer_only = rows(102.0, 104.0)
    for row in buffer_only:
        row["timestamp"] = row["timestamp"] + timedelta(days=2)
        row["available_at"] = row["available_at"] + timedelta(days=2)
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=buffer_only),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is False
    assert result.outcome.failure_stage == "data_load"
    assert "decision window returned no rows" in result.message


def test_run_config_reports_execution_row_contract_failure_with_buffer_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    config_path = write_config(
        tmp_path,
        end="2024-01-02",
        data_extra='load_end = "2024-01-03"\n',
        artifact_profile="diagnostic",
    )
    loaded_rows = rows(100.0, 101.0, 102.0)
    loaded_rows[-1]["timestamp"] = "not-a-timestamp"
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=loaded_rows),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is False
    assert result.outcome.failure_stage == "request_build"
    data_manifest = json.loads((result.result_dir / "data_manifest.json").read_text())
    assert data_manifest["rows"]["total"] == 2
    assert data_manifest["execution_rows"]["total"] == 3
    assert data_manifest["execution_rows"]["row_contract"]["status"] == "failed"
    assert "row_invalid_timestamp" in result.message


def test_run_config_engine_artifacts_use_only_decision_window_decisions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    strategy = tmp_path / "strategies" / "demo.py"
    strategy.parent.mkdir(parents=True, exist_ok=True)
    strategy.write_text(
        "from quant_strategies.decisions import ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision\n"
        "def generate_decisions(rows, params):\n"
        "    decisions = []\n"
        "    for row in rows:\n"
        "        decisions.append(StrategyDecision(\n"
        "            strategy_id='demo',\n"
        "            instrument=InstrumentRef(kind='equity_or_etf', symbol=row['symbol']),\n"
        "            decision_time=row['timestamp'],\n"
        "            as_of_time=row['timestamp'],\n"
        "            target=PositionTarget(direction='long', sizing_kind='target_weight', size=1.0),\n"
        "            exit_policy=ExitPolicy(max_hold_bars=1),\n"
        "        ))\n"
        "    return decisions\n"
    )
    config_path = write_config(
        tmp_path,
        end="2024-01-02",
        data_extra='load_end = "2024-01-04"\n',
        artifact_profile="full",
        causality_check="off",
    )
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is True
    decision_records = (result.result_dir / "decision_records.jsonl").read_text().splitlines()
    request = json.loads((result.result_dir / "engine_request.json").read_text())
    summary = read_summary(result.result_dir)
    assert len(decision_records) == 2
    assert len(request["spec"]["decisions"]) == 2
    assert summary["generated_decision_count"] == 2
    assert summary["excluded_decision_count"] == 0


def test_run_config_success_writes_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path)
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert not hasattr(result, "success")
    assert result.outcome.completed is True
    assert result.result_dir is not None
    expected = {
        "config.toml",
        "strategy_snapshot.py",
        "strategy_input_rows.jsonl",
        "decision_records.jsonl",
        "engine_request.json",
        "data_manifest.json",
        "run_manifest.json",
        "environment.json",
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
    assert summary["status"] == "completed"
    assert summary["engine"]["passed"] is True
    assert summary["engine"]["trade_count"] == 1
    assert summary["engine"]["trade_result"]["sum_signed_trade_activity_gross"] > 0
    assert summary["engine"]["trade_result"]["sum_signed_trade_activity_funding"] == 0.0
    assert summary["engine"]["trade_result"]["sum_signed_trade_activity_cost"] == 0.0
    assert summary["engine"]["trade_result"]["sum_signed_trade_activity_net"] > 0
    assert summary["engine"]["gates"][0]["name"] == "valid_inputs"
    assert summary["data_availability_status"] == "complete"
    assert summary["availability_coverage"] == {
        "field": "available_at",
        "present": 4,
        "total": 4,
        "fraction": 1.0,
    }
    assert summary["row_contract"]["status"] == "passed"
    # available_at is an unconditional required field; the data carries it
    # (availability "complete"), so the contract passes.
    assert summary["row_contract"]["required_fields"] == [
        "symbol",
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "available_at",
    ]
    assert summary["row_contract"]["quant_data_feedback"] == []
    assert summary["causality_verified"] is True
    assert summary["evidence_quality_warnings"] == []
    data_manifest = json.loads((result.result_dir / "data_manifest.json").read_text())
    assert data_manifest["replayable_from_artifacts"] is True
    assert LEGACY_REPLAYABILITY_METADATA_KEY not in data_manifest
    assert_trade_result_metric_semantics(data_manifest)
    assert data_manifest["data_availability_status"] == summary["data_availability_status"]
    assert data_manifest["availability_coverage"] == summary["availability_coverage"]
    assert data_manifest["row_contract"] == summary["row_contract"]
    assert data_manifest["causality_verified"] is True
    assert data_manifest["evidence_quality_warnings"] == summary["evidence_quality_warnings"]
    evidence = json.loads((result.result_dir / "evidence.json").read_text())
    assert evidence["schema_version"] == artifacts.RUNNER_EVIDENCE_SCHEMA_VERSION
    assert evidence["quick_checks"] is True
    assert_no_mode_fields(evidence)
    assert_assessment(result, summary, assessment_status="quick_check_passed")
    assert "runner quick checks only" in (result.result_dir / "notes.md").read_text()


def test_summary_profile_writes_compact_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path, artifact_profile="summary")
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0, 105.0, 106.0)),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is True
    assert result.result_dir is not None
    assert result.economics is not None
    names = {path.name for path in result.result_dir.iterdir() if path.is_file()}
    assert names == {
        "config.toml",
        "strategy_snapshot.py",
        "data_manifest.json",
        "artifact_profile_summary.json",
        "run_manifest.json",
        "environment.json",
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
    assert_assessment(
        result, summary, assessment_status="quick_check_passed", artifact_profile="summary"
    )
    assert summary["engine"]["passed"] is True
    assert summary["engine"]["trade_count"] == 1
    assert summary["engine"]["trade_result"]["sum_signed_trade_activity_gross"] is not None
    assert summary["engine"]["trade_result"]["sum_signed_trade_activity_funding"] == 0.0
    assert summary["engine"]["trade_result"]["sum_signed_trade_activity_cost"] == 0.0
    assert summary["engine"]["trade_result"]["sum_signed_trade_activity_net"] is not None
    assert summary["engine"]["gates"][0]["name"] == "valid_inputs"
    metrics = assert_summary_economic_metrics(summary)
    assert metrics["trade_count"] == summary["engine"]["trade_count"]
    assert metrics["hit_rate"] is not None
    assert "diagnostic_trades" not in summary["engine"]

    profile = json.loads((result.result_dir / "artifact_profile_summary.json").read_text())
    assert profile["artifact_profile"] == "summary"
    assert profile["replayable_from_artifacts"] is False
    assert LEGACY_REPLAYABILITY_METADATA_KEY not in profile
    assert profile["rows"]["row_count"] == 6
    assert profile["rows"]["sample_count"] == 5
    assert profile["decisions"]["count"] == 1
    assert "signals" not in profile
    assert profile["engine"]["passed"] is True
    assert profile["engine"]["trade_count"] == 1
    assert profile["engine"]["trade_result"]["sum_signed_trade_activity_gross"] is not None
    assert profile["engine"]["trade_result"]["sum_signed_trade_activity_cost"] is not None
    assert profile["engine"]["trade_result"]["sum_signed_trade_activity_net"] is not None
    assert "diagnostic_trades" not in profile["engine"]
    assert_trade_result_metric_semantics(profile)

    data_manifest = json.loads((result.result_dir / "data_manifest.json").read_text())
    assert data_manifest["artifact_profile"] == "summary"
    assert data_manifest["replayable_from_artifacts"] is False
    assert LEGACY_REPLAYABILITY_METADATA_KEY not in data_manifest
    assert "strategy_input_rows_jsonl_sha256" not in data_manifest
    assert len(data_manifest["normalized_rows_sha256"]) == 64
    assert profile["rows"]["normalized_rows_sha256"] == data_manifest["normalized_rows_sha256"]
    assert_trade_result_metric_semantics(data_manifest)

    run_manifest = json.loads((result.result_dir / "run_manifest.json").read_text())
    assert run_manifest["artifact_profile"] == "summary"
    assert run_manifest["replayable_from_artifacts"] is False
    assert LEGACY_REPLAYABILITY_METADATA_KEY not in run_manifest
    assert run_manifest["evidence"]["metric_semantics"] == profile["metric_semantics"]
    assert "artifact_profile_summary.json" in run_manifest["artifacts"]
    assert "engine_request.json" not in run_manifest["artifacts"]


def test_run_config_exposes_typed_in_process_economics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path)
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is True
    assert isinstance(result.economics, RunEconomics)
    assert len(result.economics.trades) == 1
    trade = result.economics.trades[0]
    assert isinstance(trade, RunTrade)
    assert trade.symbol == "SPY"
    assert trade.side == "long"
    assert trade.weight == pytest.approx(1.0)
    assert trade.decision_time.tzinfo is not None
    assert trade.entry_time.tzinfo is not None
    assert trade.exit_time.tzinfo is not None
    assert trade.entry_price == pytest.approx(102.0)
    assert trade.exit_price == pytest.approx(104.0)
    assert trade.exit_reason == "max_hold"
    assert trade.net_return == pytest.approx(
        trade.gross_return + trade.funding_return - trade.cost_return
    )


def test_run_config_economics_summary_matches_summary_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path, artifact_profile="summary")
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.economics is not None
    summary = read_summary(result.result_dir)
    assert result.economics.summary_payload() == summary["economic_metrics"]
    assert result.economics.trade_count == summary["economic_metrics"]["trade_count"]
    assert result.economics.hit_rate == summary["economic_metrics"]["hit_rate"]
    assert result.economics.by_symbol["SPY"]["count"] == 1
    assert result.economics.by_direction["long"]["count"] == 1
    assert result.economics.by_exit_reason["max_hold"]["count"] == 1


def test_run_config_exposes_portfolio_foundation_and_summary_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    config_path = write_config(
        tmp_path,
        artifact_profile="summary",
        foundation_subwindows=1,
        foundation_trial_count=10,
        foundation_benchmark_sharpe=0.0,
    )
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=rows(100.0, 101.0, 103.0, 102.0, 104.0, 105.0)),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is True
    assert isinstance(result.foundation, RunPortfolioFoundation)
    summary = read_summary(result.result_dir)
    assert result.foundation.summary_payload() == summary["portfolio_foundation"]
    payload = summary["portfolio_foundation"]
    assert payload["evidence_class"] == "quick_run_portfolio_foundation_diagnostic"
    assert payload["basis"] == "quick_run_lightweight_portfolio_path"
    assert set(payload["scenarios"]) == {"realistic_costs", "cost_stress"}
    realistic = payload["scenarios"]["realistic_costs"]
    assert realistic["full_train"]["window_id"] == "full_train"
    assert realistic["full_train"]["closed_trade_count"] == 1
    assert realistic["full_train"]["return_sample_count"] > 0
    assert realistic["full_train"]["mean_return"] is not None
    assert realistic["full_train"]["return_volatility"] is not None
    assert realistic["subwindow_count"] == 1
    assert realistic["min_closed_trade_count"] == 1
    assert realistic["max_symbol_concentration"] == pytest.approx(1.0)
    assert "subwindows" not in realistic
    payload_text = json.dumps(payload)
    for forbidden in (
        "period_return",
        "period_returns",
        "portfolio_value",
        "portfolio_values",
        "navs",
    ):
        assert forbidden not in payload_text


def test_run_config_pre_engine_failure_leaves_foundation_none(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path, artifact_profile="summary")

    def fail_data_load(config, **_kwargs):
        raise DataLoadError("strict data window failed")

    monkeypatch.setattr(execution, "load_data", fail_data_load)

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is False
    assert result.economics is None
    assert result.foundation is None


def test_run_config_foundation_can_be_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    config_path = write_config(
        tmp_path,
        artifact_profile="summary",
        foundation_enabled=False,
    )
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=rows(100.0, 101.0, 103.0, 102.0)),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is True
    assert result.economics is not None
    assert result.foundation is None
    summary = read_summary(result.result_dir)
    assert "portfolio_foundation" not in summary


def test_run_config_foundation_failure_is_nonblocking_diagnostic_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path, artifact_profile="summary")
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=rows(100.0, 101.0, 103.0, 102.0)),
    )

    def fail_foundation(**_kwargs):
        raise ValueError("foundation unavailable")

    monkeypatch.setattr(runner_module, "build_portfolio_foundation", fail_foundation)

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is True
    assert result.economics is not None
    assert result.foundation is None
    assert any(
        warning.startswith("portfolio_foundation_unavailable:")
        for warning in result.evidence.warnings
    )
    summary = read_summary(result.result_dir)
    assert "portfolio_foundation" not in summary
    data_manifest = json.loads((result.result_dir / "data_manifest.json").read_text())
    assert summary["evidence_quality_warnings"] == data_manifest["evidence_quality_warnings"]
    assert summary["evidence_quality_warnings"] == list(result.evidence.warnings)


def test_runner_config_rejects_unbounded_foundation_subwindows(tmp_path: Path):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path, foundation_subwindows=65)

    with pytest.raises(RunnerError, match="foundation_subwindows"):
        config_module.load_config(config_path, repo_root=tmp_path)


def test_runner_config_accepts_foundation_max_gross_exposure(tmp_path: Path):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path, foundation_max_gross_exposure=1.2)

    config = config_module.load_config(config_path, repo_root=tmp_path)

    assert config.output.foundation_max_gross_exposure == pytest.approx(1.2)


def test_runner_config_rejects_foundation_max_gross_exposure_below_one(tmp_path: Path):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path, foundation_max_gross_exposure=0.99)

    with pytest.raises(RunnerError, match="foundation_max_gross_exposure"):
        config_module.load_config(config_path, repo_root=tmp_path)


def test_run_config_economics_are_profile_independent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)),
    )

    economics_by_profile = []
    for profile in ("summary", "diagnostic", "full"):
        config_path = write_config(
            tmp_path, relative_path=f"{profile}.toml", artifact_profile=profile
        )
        result = run_config(config_path, repo_root=tmp_path)
        assert result.economics is not None
        economics_by_profile.append(result.economics)

    assert economics_by_profile[0] == economics_by_profile[1] == economics_by_profile[2]


def test_run_config_pre_engine_failure_leaves_economics_none(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path, artifact_profile="summary")

    def fail_data_load(config, **_kwargs):
        raise DataLoadError("strict data window failed")

    monkeypatch.setattr(execution, "load_data", fail_data_load)

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is False
    assert result.economics is None
    assert result.succeeded is False


def test_quick_run_economics_path_does_not_import_heavy_evaluation_dependencies():
    code = """
import sys
from types import SimpleNamespace

import quant_strategies.core.engine_runner
import quant_strategies.core.portfolio_foundation
import quant_strategies.engine
import quant_strategies.runner
from quant_strategies.runner.economic_metrics import build_run_economics

build_run_economics(SimpleNamespace(
    screen_summary={
        "trade_count": 0,
        "trade_result": {
            "sum_signed_trade_activity_gross": 0.0,
            "sum_signed_trade_activity_funding": 0.0,
            "sum_signed_trade_activity_cost": 0.0,
            "sum_signed_trade_activity_net": 0.0,
        },
        "trades": [],
    },
    validate_summary=None,
    passed=None,
))

forbidden = {
    "vectorbtpro",
    "pandas",
    "numpy",
    "quant_strategies.evaluation",
}
loaded = sorted(name for name in forbidden if name in sys.modules)
if loaded:
    raise SystemExit("loaded forbidden modules: " + ", ".join(loaded))
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout


def test_default_quick_run_writes_diagnostics_without_full_replay_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    config_path = write_config(
        tmp_path,
        artifact_profile=None,
        diagnostic_sample_trades=1,
    )
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=rows(100.0, 101.0, 103.0, 102.0)),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is True
    assert result.result_dir is not None
    names = {path.name for path in result.result_dir.iterdir() if path.is_file()}
    assert names == {
        "config.toml",
        "strategy_snapshot.py",
        "data_manifest.json",
        "diagnostics.json",
        "run_manifest.json",
        "environment.json",
        "summary.json",
        "notes.md",
    }
    assert "strategy_input_rows.jsonl" not in names
    assert "decision_records.jsonl" not in names
    assert "engine_request.json" not in names
    assert "evidence.json" not in names

    summary = read_summary(result.result_dir)
    assert_assessment(
        result,
        summary,
        assessment_status="quick_check_failed",
        artifact_profile="diagnostic",
    )
    assert "diagnostic_trades" not in summary["engine"]
    assert_summary_economic_metrics(summary)

    diagnostics = json.loads((result.result_dir / "diagnostics.json").read_text())
    assert diagnostics["artifact_profile"] == "diagnostic"
    assert diagnostics["replayable_from_artifacts"] is False
    assert LEGACY_REPLAYABILITY_METADATA_KEY not in diagnostics
    assert diagnostics["assessment_status"] == summary["assessment_status"]
    assert diagnostics["trade_count"] == 1
    assert diagnostics["trade_result"] == summary["engine"]["trade_result"]
    assert result.economics.slices_payload() == diagnostics["economic_slices"]
    assert result.foundation.matrix_payload() == diagnostics["portfolio_foundation"]
    foundation_text = json.dumps(diagnostics["portfolio_foundation"])
    for forbidden in (
        "period_return",
        "period_returns",
        "portfolio_value",
        "portfolio_values",
        "navs",
    ):
        assert forbidden not in foundation_text
    slices = diagnostics["economic_slices"]
    assert slices["schema_version"] == "quant_strategies.runner.economic_slices/v1"
    assert slices["basis"] == "engine_trade_ledger"
    assert slices["by_symbol"]["SPY"]["count"] == 1
    assert slices["by_direction"]["long"]["count"] == 1
    assert slices["by_exit_reason"]["max_hold"]["count"] == 1
    assert set(slices["win_loss_distribution"]) == {
        "largest_win_net",
        "largest_loss_net",
        "median_trade_net",
        "sum_positive_net",
        "sum_negative_net",
    }
    assert diagnostics["by_symbol"]["SPY"]["count"] == 1
    assert len(diagnostics["sample_trades"]["largest_winners"]) == 1
    assert len(diagnostics["sample_trades"]["largest_losers"]) == 1

    data_manifest = json.loads((result.result_dir / "data_manifest.json").read_text())
    assert data_manifest["artifact_profile"] == "diagnostic"
    assert data_manifest["replayable_from_artifacts"] is False
    assert LEGACY_REPLAYABILITY_METADATA_KEY not in data_manifest

    run_manifest = json.loads((result.result_dir / "run_manifest.json").read_text())
    assert run_manifest["artifact_profile"] == "diagnostic"
    assert run_manifest["replayable_from_artifacts"] is False
    assert LEGACY_REPLAYABILITY_METADATA_KEY not in run_manifest
    assert "diagnostics.json" in run_manifest["artifacts"]
    assert "engine_request.json" not in run_manifest["artifacts"]


def test_summary_profile_does_not_build_full_evidence_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path, artifact_profile="summary")
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)),
    )
    monkeypatch.setattr(
        engine_runner,
        "evidence_json",
        lambda packet: (_ for _ in ()).throw(
            AssertionError("summary mode should not serialize evidence")
        ),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is True
    assert result.result_dir is not None
    assert not (result.result_dir / "evidence.json").exists()


def test_diagnostics_completion_is_not_validation_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path, quick_checks=False)
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=rows(100.0, 101.0, 90.0, 89.0)),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is True
    assert result.result_dir is not None
    summary = read_summary(result.result_dir)
    assert summary["quick_checks"] is False
    assert summary["stage"] == "completed"
    assert summary["status"] == "completed"
    assert summary["engine"]["passed"] is None
    assert summary["engine"]["trade_count"] == 1
    assert summary["engine"]["trade_result"]["sum_signed_trade_activity_gross"] < 0
    assert summary["engine"]["trade_result"]["sum_signed_trade_activity_funding"] == 0.0
    assert summary["engine"]["trade_result"]["sum_signed_trade_activity_cost"] == 0.0
    assert summary["engine"]["trade_result"]["sum_signed_trade_activity_net"] < 0
    assert_assessment(result, summary, assessment_status="diagnostics_complete")
    notes = (result.result_dir / "notes.md").read_text()
    assert "status: completed" in notes
    assert "status: passed" not in notes
    assert "diagnostic evidence only" in notes
    assert "not validation" in notes


def test_diagnostics_empty_decisions_complete_as_zero_trade_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    strategy = tmp_path / "strategies" / "demo.py"
    strategy.parent.mkdir(parents=True, exist_ok=True)
    strategy.write_text("def generate_decisions(rows, params):\n    return []\n")
    config_path = write_config(tmp_path, quick_checks=False)
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is True
    assert result.result_dir is not None
    summary = read_summary(result.result_dir)
    assert summary["quick_checks"] is False
    assert summary["stage"] == "completed"
    assert summary["status"] == "completed"
    assert summary["engine"]["passed"] is None
    assert summary["engine"]["trade_count"] == 0
    assert summary["engine"]["trade_result"] == {
        "sum_signed_trade_activity_gross": 0.0,
        "sum_signed_trade_activity_funding": 0.0,
        "sum_signed_trade_activity_cost": 0.0,
        "sum_signed_trade_activity_net": 0.0,
    }
    metrics = assert_summary_economic_metrics(summary)
    assert metrics["trade_count"] == 0
    assert metrics["hit_rate"] is None
    assert metrics["average_trade_net"] is None
    assert metrics["profit_factor"] is None
    assert_assessment(result, summary, assessment_status="diagnostics_complete")
    request = json.loads((result.result_dir / "engine_request.json").read_text())
    evidence = json.loads((result.result_dir / "evidence.json").read_text())
    assert evidence["schema_version"] == artifacts.RUNNER_EVIDENCE_SCHEMA_VERSION
    assert evidence["quick_checks"] is False
    assert_no_mode_fields(evidence)
    assert request["spec"]["decisions"] == []
    assert evidence["screening_result"]["trade_count"] == 0
    assert evidence["screening_result"]["trades"] == []


def test_run_artifacts_preserve_exit_reason_and_decision_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    strategy = tmp_path / "strategies" / "demo.py"
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
    config_path = write_config(tmp_path, quick_checks=False)
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=rows(100.0, 100.0, 102.0, 103.0, 104.0)),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is True
    assert result.result_dir is not None
    request = json.loads((result.result_dir / "engine_request.json").read_text())
    evidence = json.loads((result.result_dir / "evidence.json").read_text())
    decision_payload = request["spec"]["decisions"][0]
    trade = evidence["screening_result"]["trades"][0]

    assert evidence["schema_version"] == artifacts.RUNNER_EVIDENCE_SCHEMA_VERSION
    assert evidence["quick_checks"] is False
    assert_no_mode_fields(evidence)
    assert decision_payload["exit_policy"]["max_hold_bars"] == 2
    assert decision_payload["exit_policy"]["take_profit_bps"] == 50.0
    assert decision_payload["metadata"]["funding_pressure_bps"] == 3.25
    assert decision_payload["metadata"]["entry_return_extension_bps"] == 42.0
    assert decision_payload["metadata"]["signal_family"] == "demo"
    assert trade["exit_reason"] == "take_profit"
    assert trade["decision_metadata"]["funding_pressure_bps"] == 3.25


def test_quick_check_failure_keeps_completed_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path, quick_checks=True)
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=rows(100.0, 101.0, 90.0, 89.0)),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is True
    assert result.result_dir is not None
    summary = read_summary(result.result_dir)
    assert summary["quick_checks"] is True
    assert summary["stage"] == "completed"
    assert summary["status"] == "completed"
    assert summary["engine"]["passed"] is False
    assert summary["engine"]["trade_count"] == 1
    assert summary["engine"]["trade_result"]["sum_signed_trade_activity_gross"] < 0
    assert summary["engine"]["trade_result"]["sum_signed_trade_activity_net"] < 0
    assert summary["engine"]["gates"][0]["name"] == "valid_inputs"
    assert_assessment(result, summary, assessment_status="quick_check_failed")
    assert "quick_check_result: failed" in (result.result_dir / "notes.md").read_text()


def test_run_config_treats_empty_decisions_as_zero_trade_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    strategy = tmp_path / "strategies" / "demo.py"
    strategy.parent.mkdir(parents=True, exist_ok=True)
    strategy.write_text("def generate_decisions(rows, params):\n    return []\n")
    config_path = write_config(tmp_path, quick_checks=True)
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is True
    assert result.result_dir is not None
    summary = read_summary(result.result_dir)
    assert summary["quick_checks"] is True
    assert summary["stage"] == "completed"
    assert summary["status"] == "completed"
    assert summary["engine"]["passed"] is False
    assert summary["engine"]["trade_count"] == 0
    assert summary["engine"]["trade_result"] == {
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
    assert_assessment(result, summary, assessment_status="quick_check_failed")

    assert (result.result_dir / "decision_records.jsonl").read_text() == ""
    request = json.loads((result.result_dir / "engine_request.json").read_text())
    evidence = json.loads((result.result_dir / "evidence.json").read_text())
    assert evidence["schema_version"] == artifacts.RUNNER_EVIDENCE_SCHEMA_VERSION
    assert evidence["quick_checks"] is True
    assert_no_mode_fields(evidence)
    assert request["spec"]["decisions"] == []
    assert evidence["validation_report"]["screening_result"]["trade_count"] == 0
    assert evidence["validation_report"]["screening_result"]["trades"] == []
    assert "quick_check_result: failed" in (result.result_dir / "notes.md").read_text()


def test_run_config_writes_data_failure_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path, artifact_profile="summary")

    def fail_data_load(config, **_kwargs):
        raise DataLoadError("strict data window failed")

    monkeypatch.setattr(execution, "load_data", fail_data_load)

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is False
    assert result.result_dir is not None
    assert (result.result_dir / "config.toml").exists()
    assert (result.result_dir / "strategy_snapshot.py").exists()
    assert "strict data window failed" in (result.result_dir / "notes.md").read_text()
    summary = read_summary(result.result_dir)
    assert summary["stage"] == "data_load"
    assert "trade_result" not in summary["engine"]
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
    assert_assessment(
        result,
        summary,
        assessment_status="runner_failed",
        artifact_profile="summary",
        failure_stage=str(summary["stage"]),
    )
    assert (result.result_dir / "run_manifest.json").exists()
    assert not (result.result_dir / "strategy_input_rows.csv").exists()


def test_consumer_contract_run_completed_does_not_make_runner_failed_rankable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import quant_strategies.cli as cli

    write_strategy(tmp_path)
    config_path = write_config(tmp_path, artifact_profile="summary")

    def fail_data_load(config, **_kwargs):
        raise DataLoadError("strict data window failed")

    monkeypatch.setattr(execution, "load_data", fail_data_load)

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is False
    assert result.outcome.failure_stage == "data_load"
    assert result.outcome.assessment_status == "runner_failed"
    assert cli._run_exit_code(result) == 3


def test_run_cli_exit_code_prefers_derived_succeeded_contract():
    from types import SimpleNamespace

    import quant_strategies.cli as cli

    result = SimpleNamespace(
        succeeded=False,
        outcome=RunOutcome(completed=True, failure_stage=None),
    )

    assert cli._run_exit_code(result) == 1


def test_strategy_import_failure_prevents_data_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    strategy = tmp_path / "strategies" / "demo.py"
    strategy.parent.mkdir(parents=True, exist_ok=True)
    strategy.write_text("VALUE = 1\n")
    config_path = write_config(tmp_path)

    def forbidden_data_load(config, **_kwargs):
        raise AssertionError("data should not load after strategy import failure")

    monkeypatch.setattr(execution, "load_data", forbidden_data_load)

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is False
    assert result.result_dir is not None
    summary = read_summary(result.result_dir)
    assert summary["stage"] == "strategy_import"
    assert_assessment(
        result, summary, assessment_status="runner_failed", failure_stage=str(summary["stage"])
    )
    assert (result.result_dir / "run_manifest.json").exists()


def test_strategy_path_directory_failure_writes_summary(tmp_path: Path):
    strategy_dir = tmp_path / "strategies" / "demo.py"
    strategy_dir.mkdir(parents=True)
    config_path = write_config(tmp_path)

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is False
    assert result.result_dir is not None
    assert not (result.result_dir / "strategy_snapshot.py").exists()
    summary = read_summary(result.result_dir)
    assert summary["stage"] == "strategy_import"
    assert_assessment(
        result, summary, assessment_status="runner_failed", failure_stage=str(summary["stage"])
    )
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
        lambda config, **_kwargs: LoadedData(
            rows=rows(1.10, 1.11, 1.12, 1.13, quotes=True, research_fields=True)
        ),
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


def test_run_config_marks_complete_available_at_coverage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path)
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(
            rows=rows(100.0, 101.0, 102.0, 104.0, research_fields=True)
        ),
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
    assert result.outcome.assessment_status == "quick_check_passed"
    assert summary["assessment_status"] == "quick_check_passed"


def test_run_config_reuses_execution_evidence_quality_after_causality(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path)
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(
            rows=rows(100.0, 101.0, 102.0, 104.0, research_fields=True)
        ),
    )
    normalized_rows_calls = 0
    original_from_rows = NormalizedRows.from_rows

    def counting_from_rows(config, loaded_rows, **kwargs):
        nonlocal normalized_rows_calls
        normalized_rows_calls += 1
        return original_from_rows(config, loaded_rows, **kwargs)

    monkeypatch.setattr(NormalizedRows, "from_rows", staticmethod(counting_from_rows))

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is True
    assert normalized_rows_calls == 1


def test_run_config_fails_row_contract_on_partial_available_at(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    # available_at is unconditionally required: a row missing it fails the row
    # contract, so the quick run fails at the engine row-contract gate. There is no
    # search-mode "partial coverage tolerated" path.
    write_strategy(tmp_path)
    config_path = write_config(tmp_path, artifact_profile="summary")
    partial_rows = rows(100.0, 101.0, 102.0, 104.0, research_fields=True)
    partial_rows[1].pop("available_at")
    monkeypatch.setattr(
        execution, "load_data", lambda config, **_kwargs: LoadedData(rows=partial_rows)
    )

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
    assert summary["row_contract"]["status"] == "failed"
    assert summary["row_contract"]["missing_required_fields"] == {"available_at": 1}
    assert summary["row_contract"]["quant_data_feedback"] == [
        "row_missing_available_at:available_at:1"
    ]
    assert data_manifest["row_contract"] == summary["row_contract"]
    assert result.outcome.completed is False
    assert result.outcome.failure_stage == "request_build"
    assert result.outcome.assessment_status == "runner_failed"
    assert summary["stage"] == "request_build"
    assert "row_contract_failed: row_missing_available_at:available_at:1" in summary["message"]
    assert not (result.result_dir / "engine_request.json").exists()


def test_run_config_rejects_invalid_available_at_for_causality_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path)
    invalid_rows = rows(100.0, 101.0, 102.0, 104.0, research_fields=True)
    invalid_rows[1]["available_at"] = "not-a-datetime"
    monkeypatch.setattr(
        execution, "load_data", lambda config, **_kwargs: LoadedData(rows=invalid_rows)
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is False
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
    assert result.outcome.failure_stage == "request_build"
    assert result.outcome.assessment_status == "runner_failed"
    assert summary["stage"] == "request_build"
    assert summary["assessment_status"] == "runner_failed"
    assert "row_contract_failed: row_invalid_available_at:available_at:1" in summary["message"]
    assert summary["row_contract"]["status"] == "failed"
    assert summary["row_contract"]["quant_data_feedback"] == [
        "row_invalid_available_at:available_at:1"
    ]
    assert not (result.result_dir / "engine_request.json").exists()


def test_runner_catches_hidden_lookahead_before_request_build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    strategy = tmp_path / "strategies" / "demo.py"
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
        lambda config, **_kwargs: LoadedData(rows=rows(100.0, 101.0, 102.0, research_fields=True)),
    )
    events: list[dict[str, object]] = []

    result = run_config(config_path, repo_root=tmp_path, event_sink=events.append)

    assert result.outcome.completed is False
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
    assert result.outcome.assessment_status == "runner_failed"
    assert summary["assessment_status"] == "runner_failed"
    assert any(
        event["stage"] == "causality_check"
        and event["status"] == "failed"
        and "hidden_lookahead_detected" in str(event["error"])
        for event in events
    )
    assert not any(
        event["stage"] == "causality_check" and event["status"] == "completed" for event in events
    )


def test_row_contract_status_is_independent_of_artifact_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    # F6: artifact_profile is pure verbosity and must NOT change the row-contract
    # verdict. The same data yields an identical row contract under every profile.
    write_strategy(tmp_path)

    def defective_rows():
        contract_rows = rows(100.0, 101.0, 102.0)
        contract_rows[1].pop("high")  # a row-contract defect, independent of profile
        return contract_rows

    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=defective_rows()),
    )

    def row_contract(config_path: Path) -> dict:
        result = run_config(config_path, repo_root=tmp_path)
        return json.loads((result.result_dir / "summary.json").read_text())["row_contract"]

    full = row_contract(write_config(tmp_path, artifact_profile="full"))
    summary = row_contract(
        write_config(tmp_path, relative_path="run_summary.toml", artifact_profile="summary")
    )
    assert full["status"] == "failed"
    assert full == summary


def test_quick_run_fails_row_contract_when_available_at_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    # available_at is unconditionally required now: a quick run surfaces a missing
    # available_at as a failed row contract — there is no search-mode tolerance.
    write_strategy(tmp_path)
    config_path = write_config(tmp_path)
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(
            rows=rows(100.0, 101.0, 102.0, include_available_at=False)
        ),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.result_dir is not None
    row_contract = json.loads((result.result_dir / "summary.json").read_text())["row_contract"]
    assert row_contract["status"] == "failed"
    assert row_contract["missing_required_fields"] == {"available_at": 3}
    assert "row_missing_available_at:available_at:3" in row_contract["quant_data_feedback"]


def test_runner_catches_peek_to_suppress_with_strict_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    # Strategy reads a future bar to *withhold* a losing trade. The baseline emits
    # nothing; strict row-grid replay re-runs at the suppressed bar without the
    # future and emits the trade -> suppression detected. Emitted-only replay would
    # miss it because there is no emitted boundary to replay.
    strategy = tmp_path / "strategies" / "demo.py"
    strategy.parent.mkdir(parents=True, exist_ok=True)
    strategy.write_text(
        "from quant_strategies.decisions import ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision\n"
        "def generate_decisions(rows, params):\n"
        "    if len(rows) < 2:\n"
        "        return []\n"
        "    as_of_row = rows[1]\n"
        "    future = [row for row in rows if row['timestamp'] > as_of_row['timestamp']]\n"
        "    if any(row['close'] < as_of_row['close'] for row in future):\n"
        "        return []\n"
        "    return [StrategyDecision(\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='equity_or_etf', symbol=as_of_row['symbol']),\n"
        "        decision_time=as_of_row['timestamp'],\n"
        "        as_of_time=as_of_row['timestamp'],\n"
        "        target=PositionTarget(direction='long', sizing_kind='target_weight', size=1.0),\n"
        "        exit_policy=ExitPolicy(max_hold_bars=1),\n"
        "    )]\n"
    )
    config_path = write_config(tmp_path)
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=rows(100.0, 101.0, 99.0, research_fields=True)),
    )
    events: list[dict[str, object]] = []

    result = run_config(config_path, repo_root=tmp_path, event_sink=events.append)

    assert result.outcome.completed is False
    assert result.result_dir is not None
    summary = read_summary(result.result_dir)
    assert summary["stage"] == "causality"
    assert summary["message"] == "hidden_lookahead_suppression_detected"
    assert summary["causality_verified"] is False
    assert summary["emitted_replay_verified"] is True
    assert summary["strict_no_emission_verified"] is False
    assert summary["evidence_quality_warnings"] == [
        "strict_suppression_replay_not_verified",
        "runner_causality_not_verified",
    ]
    assert result.outcome.assessment_status == "runner_failed"
    assert not (result.result_dir / "engine_request.json").exists()
    assert any(
        event["stage"] == "causality_check"
        and event["status"] == "failed"
        and "hidden_lookahead_suppression_detected" in str(event["error"])
        for event in events
    )


def test_run_config_rejects_future_declared_observation_before_request_build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    strategy = tmp_path / "strategies" / "demo.py"
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
        lambda config, **_kwargs: LoadedData(
            rows=rows(100.0, 101.0, 102.0, 104.0, research_fields=True)
        ),
    )
    events: list[dict[str, object]] = []

    result = run_config(config_path, repo_root=tmp_path, event_sink=events.append)

    assert result.outcome.completed is False
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
    monkeypatch.setattr(
        execution, "load_data", lambda config, **_kwargs: LoadedData(rows=contract_rows)
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is False
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


def test_run_config_records_engine_invalid_row_contract_before_engine_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    strategy = tmp_path / "strategies" / "demo.py"
    strategy.parent.mkdir(parents=True, exist_ok=True)
    strategy.write_text("def generate_decisions(rows, params):\n    raise RuntimeError('stop')\n")
    config_path = write_config(tmp_path)
    contract_rows = rows(100.0, 101.0, 102.0, research_fields=True)
    contract_rows[1]["close"] = 0.0
    monkeypatch.setattr(
        execution, "load_data", lambda config, **_kwargs: LoadedData(rows=contract_rows)
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is False
    assert result.result_dir is not None
    summary = read_summary(result.result_dir)
    data_manifest = json.loads((result.result_dir / "data_manifest.json").read_text())
    row_contract = summary["row_contract"]
    assert summary["stage"] == "decision_generation"
    assert row_contract["status"] == "failed"
    assert row_contract["issue_reasons"] == {"row_invalid_numeric_field": 1}
    assert row_contract["quant_data_feedback"] == ["row_invalid_numeric_field:close:1"]
    assert data_manifest["row_contract"] == row_contract
    assert not (result.result_dir / "decision_records.jsonl").exists()
    assert not (result.result_dir / "engine_request.json").exists()


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
    monkeypatch.setattr(
        execution, "load_data", lambda config, **_kwargs: LoadedData(rows=contract_rows)
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.result_dir is not None
    summary = read_summary(result.result_dir)
    row_contract = summary["row_contract"]
    assert row_contract["status"] == "failed"
    assert row_contract["missing_required_fields"] == {"has_funding_event": 4}
    assert row_contract["quant_data_feedback"] == ["row_missing_required_field:has_funding_event:4"]


def test_run_config_rejects_invalid_funding_indicator_before_engine_request(
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
    contract_rows[0]["has_funding_event"] = "yes"
    contract_rows[0]["funding_timestamp"] = contract_rows[0]["timestamp"]
    contract_rows[0]["funding_rate"] = Decimal("0.0001")
    monkeypatch.setattr(
        execution, "load_data", lambda config, **_kwargs: LoadedData(rows=contract_rows)
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is False
    assert result.outcome.failure_stage == "request_build"
    assert result.outcome.assessment_status == "runner_failed"
    assert result.result_dir is not None
    summary = read_summary(result.result_dir)
    data_manifest = json.loads((result.result_dir / "data_manifest.json").read_text())
    row_contract = summary["row_contract"]
    assert summary["stage"] == "request_build"
    assert summary["assessment_status"] != "quick_check_passed"
    assert (
        "row_contract_failed: row_invalid_funding_fields:has_funding_event:1" in summary["message"]
    )
    assert row_contract["status"] == "failed"
    assert row_contract["issue_reasons"] == {"row_invalid_funding_fields": 1}
    assert row_contract["funding_event_missing_fields"] == {"has_funding_event": 1}
    assert row_contract["quant_data_feedback"] == ["row_invalid_funding_fields:has_funding_event:1"]
    assert data_manifest["row_contract"] == row_contract
    assert not (result.result_dir / "engine_request.json").exists()


def test_completed_run_writes_minimal_manifests(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path)
    loaded_rows = rows(100.0, 101.0, 102.0, 104.0, research_fields=True)
    monkeypatch.setattr(
        execution, "load_data", lambda config, **_kwargs: LoadedData(rows=loaded_rows)
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is True
    assert result.result_dir is not None
    run_manifest = json.loads((result.result_dir / "run_manifest.json").read_text())
    environment = json.loads((result.result_dir / "environment.json").read_text())
    data_manifest = json.loads((result.result_dir / "data_manifest.json").read_text())
    assert "python" not in run_manifest
    assert "packages" not in run_manifest
    assert environment["python"]["version"]
    assert {"quant-strategies", "quant-data", "pydantic"}.issubset(environment["packages"])
    assert LEGACY_DISTRIBUTION not in environment["packages"]
    assert run_manifest["engine"] == {"evidence_schema": "quant_strategies.engine.evidence/v4"}
    assert run_manifest["artifact_profile"] == "full"
    assert run_manifest["replayable_from_artifacts"] is True
    assert LEGACY_REPLAYABILITY_METADATA_KEY not in run_manifest
    assert run_manifest["evidence"] == {
        "evidence_class": "quick_run_diagnostic",
        "strategy_contract": "decision",
        "return_model": "trade_result.sum_signed_trade_activity_net",
        "funding_model": "none",
        "metric_semantics": run_manifest["evidence"]["metric_semantics"],
        "promotion_eligible": False,
        "paper_trade_eligible": False,
        "live_eligible": False,
        "requires_manual_approval": True,
    }
    assert_trade_result_metric_semantics(run_manifest["evidence"])
    assert run_manifest["artifacts"]["config.toml"]["sha256"]
    assert run_manifest["artifacts"]["strategy_snapshot.py"]["sha256"]
    assert run_manifest["artifacts"]["strategy_input_rows.jsonl"]["sha256"]
    assert run_manifest["artifacts"]["decision_records.jsonl"]["sha256"]
    assert run_manifest["artifacts"]["engine_request.json"]["sha256"]
    assert "environment.json" not in run_manifest["artifacts"]
    assert data_manifest["data"] == {
        "kind": "bars",
        "dataset": "equity_1min",
        "symbols": ["SPY"],
        "start": "2024-01-01",
        "end": "2024-01-05",
    }
    assert data_manifest["artifact_profile"] == "full"
    assert data_manifest["replayable_from_artifacts"] is True
    assert LEGACY_REPLAYABILITY_METADATA_KEY not in data_manifest
    assert_trade_result_metric_semantics(data_manifest)
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
    monkeypatch.setattr(
        execution, "load_data", lambda config, **_kwargs: LoadedData(rows=loaded_rows)
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is True
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
    expected_normalized = NormalizedRows.from_rows(config, loaded_rows)
    monkeypatch.setattr(
        execution, "load_data", lambda config, **_kwargs: LoadedData(rows=loaded_rows)
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is True
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
        lambda config, **_kwargs: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)),
    )
    original_write = artifacts.write_strategy_input_rows

    def write_wrong_hash(result_dir: Path, row_payload) -> str:
        original_write(result_dir, row_payload)
        return "0" * 64

    monkeypatch.setattr(artifacts, "write_strategy_input_rows", write_wrong_hash)

    with pytest.raises(RunnerError, match="strategy_input_rows.jsonl hash"):
        run_config(config_path, repo_root=tmp_path)


def test_decision_generation_failure_writes_run_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    strategy = tmp_path / "strategies" / "demo.py"
    strategy.parent.mkdir(parents=True, exist_ok=True)
    strategy.write_text("def generate_decisions(rows, params):\n    raise RuntimeError('boom')\n")
    config_path = write_config(tmp_path)
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is False
    assert result.result_dir is not None
    assert (result.result_dir / "run_manifest.json").exists()
    data_manifest = json.loads((result.result_dir / "data_manifest.json").read_text())
    jsonl_path = result.result_dir / "strategy_input_rows.jsonl"
    assert jsonl_path.exists()
    assert (
        hashlib.sha256(jsonl_path.read_bytes()).hexdigest()
        == data_manifest["normalized_rows_sha256"]
    )
    summary = read_summary(result.result_dir)
    assert summary["stage"] == "decision_generation"
    assert "trade_result" not in summary["engine"]
    assert_assessment(
        result, summary, assessment_status="runner_failed", failure_stage=str(summary["stage"])
    )


def test_runner_blocks_strategy_row_mutation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    strategy = tmp_path / "strategies" / "demo.py"
    strategy.parent.mkdir(parents=True, exist_ok=True)
    strategy.write_text(
        "def generate_decisions(rows, params):\n    rows[0]['close'] = 999.0\n    return []\n"
    )
    config_path = write_config(tmp_path)
    loaded_rows = rows(100.0, 101.0, 102.0, 104.0)
    monkeypatch.setattr(
        execution, "load_data", lambda config, **_kwargs: LoadedData(rows=loaded_rows)
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is False
    assert loaded_rows[0]["close"] == 100.0
    assert result.result_dir is not None
    summary = read_summary(result.result_dir)
    assert summary["stage"] == "decision_generation"
    assert "strategy execution failed" in summary["message"]
    assert_assessment(
        result, summary, assessment_status="runner_failed", failure_stage=str(summary["stage"])
    )


def test_runner_blocks_strategy_param_mutation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    strategy = tmp_path / "strategies" / "demo.py"
    strategy.parent.mkdir(parents=True, exist_ok=True)
    strategy.write_text(
        "def generate_decisions(rows, params):\n    params['weight'] = 2.0\n    return []\n"
    )
    config_path = write_config(tmp_path)
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is False
    assert result.result_dir is not None
    summary = read_summary(result.result_dir)
    assert summary["stage"] == "decision_generation"
    assert "strategy execution failed" in summary["message"]
    assert_assessment(
        result, summary, assessment_status="runner_failed", failure_stage=str(summary["stage"])
    )


def test_runner_validates_params_before_data_loading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    strategy = tmp_path / "strategies" / "demo.py"
    strategy.parent.mkdir(parents=True, exist_ok=True)
    strategy.write_text(
        "def validate_params(params):\n"
        "    raise ValueError('unknown params')\n"
        "def generate_decisions(rows, params):\n"
        "    return []\n"
    )
    config_path = write_config(tmp_path)
    load_calls = 0

    def load_data(config, **_kwargs):
        nonlocal load_calls
        load_calls += 1
        return LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0))

    monkeypatch.setattr(execution, "load_data", load_data)

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is False
    assert load_calls == 0
    assert result.result_dir is not None
    summary = read_summary(result.result_dir)
    assert summary["stage"] == "param_validation"
    assert summary["message"] == "param validation failed: unknown params"
    assert not (result.result_dir / "strategy_input_rows.jsonl").exists()
    assert_assessment(
        result, summary, assessment_status="runner_failed", failure_stage=str(summary["stage"])
    )


def test_runner_rejects_non_mapping_validate_params_return(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    strategy = tmp_path / "strategies" / "demo.py"
    strategy.parent.mkdir(parents=True, exist_ok=True)
    strategy.write_text(
        "def validate_params(params):\n"
        "    return None\n"
        "def generate_decisions(rows, params):\n"
        "    return []\n"
    )
    config_path = write_config(tmp_path)
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is False
    assert result.result_dir is not None
    summary = read_summary(result.result_dir)
    assert summary["stage"] == "param_validation"
    assert summary["message"] == "param validation failed: validate_params must return a mapping"
    assert not (result.result_dir / "strategy_input_rows.jsonl").exists()
    assert_assessment(
        result, summary, assessment_status="runner_failed", failure_stage=str(summary["stage"])
    )


def test_runner_structures_validate_params_system_exit(tmp_path: Path):
    strategy = tmp_path / "strategies" / "demo.py"
    strategy.parent.mkdir(parents=True, exist_ok=True)
    strategy.write_text(
        "def validate_params(params):\n"
        "    raise SystemExit('params exited')\n"
        "def generate_decisions(rows, params):\n"
        "    return []\n"
    )
    config_path = write_config(tmp_path)

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is False
    assert result.outcome.failure_stage == "param_validation"
    assert result.result_dir is not None
    summary = read_summary(result.result_dir)
    assert summary["stage"] == "param_validation"
    assert summary["message"] == "param validation exited: params exited"
    assert not (result.result_dir / "strategy_input_rows.jsonl").exists()
    assert_assessment(
        result, summary, assessment_status="runner_failed", failure_stage=str(summary["stage"])
    )


def test_runner_structures_strategy_execution_system_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    strategy = tmp_path / "strategies" / "demo.py"
    strategy.parent.mkdir(parents=True, exist_ok=True)
    strategy.write_text(
        "def generate_decisions(rows, params):\n    raise SystemExit('strategy exited')\n"
    )
    config_path = write_config(tmp_path)
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is False
    assert result.outcome.failure_stage == "decision_generation"
    assert result.result_dir is not None
    summary = read_summary(result.result_dir)
    assert summary["stage"] == "decision_generation"
    assert "strategy execution exited: strategy exited" in summary["message"]


def test_runner_structures_strategy_import_system_exit(tmp_path: Path):
    strategy = tmp_path / "strategies" / "demo.py"
    strategy.parent.mkdir(parents=True, exist_ok=True)
    strategy.write_text("raise SystemExit('import exited')\n")
    config_path = write_config(tmp_path)

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is False
    assert result.outcome.failure_stage == "strategy_import"
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
    loaded_rows = rows(
        100.0, 101.0, 102.0, 104.0, research_fields=True, readiness_lag=readiness_lag
    )
    monkeypatch.setattr(
        execution, "load_data", lambda config, **_kwargs: LoadedData(rows=loaded_rows)
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is True
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
        lambda config, **_kwargs: LoadedData(
            rows=rows(
                100.0, 101.0, 102.0, 104.0, research_fields=True, readiness_lag=timedelta(minutes=1)
            )
        ),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is False
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
    assert summary["message"] == "hidden_lookahead_detected"
    assert summary["data_availability_status"] == "complete"
    assert summary["availability_coverage"] == {
        "field": "available_at",
        "present": 4,
        "total": 4,
        "fraction": 1.0,
    }
    assert summary["causality_verified"] is False
    assert summary["evidence_quality_warnings"] == ["runner_causality_not_verified"]
    assert result.outcome.assessment_status == "runner_failed"
    assert summary["assessment_status"] == "runner_failed"


def test_malformed_decision_time_remains_decision_generation_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    strategy = tmp_path / "strategies" / "demo.py"
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
        lambda config, **_kwargs: LoadedData(
            rows=rows(100.0, 101.0, 102.0, 104.0, research_fields=True)
        ),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is False
    assert result.result_dir is not None
    summary = read_summary(result.result_dir)
    assert summary["stage"] == "decision_generation"
    assert "decision_time" in summary["message"]
    assert_assessment(
        result, summary, assessment_status="runner_failed", failure_stage=str(summary["stage"])
    )


def test_invalid_decision_output_fails_before_writing_decision_records(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    strategy = tmp_path / "strategies" / "demo.py"
    strategy.parent.mkdir(parents=True, exist_ok=True)
    strategy.write_text("def generate_decisions(rows, params):\n    return 'not decisions'\n")
    config_path = write_config(tmp_path)
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(
            rows=rows(100.0, 101.0, 102.0, 104.0, research_fields=True)
        ),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is False
    assert result.result_dir is not None
    summary = read_summary(result.result_dir)
    assert summary["stage"] == "decision_generation"
    assert "invalid_decision_output" in summary["message"]
    assert not (result.result_dir / "strategy_input_rows.csv").exists()
    assert (result.result_dir / "strategy_input_rows.jsonl").exists()
    assert (result.result_dir / "data_manifest.json").exists()
    assert not (result.result_dir / "decision_records.jsonl").exists()
    assert_assessment(
        result, summary, assessment_status="runner_failed", failure_stage=str(summary["stage"])
    )


def test_unsupported_quick_run_decision_keeps_loaded_data_and_decision_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    strategy = tmp_path / "strategies" / "demo.py"
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
        lambda config, **_kwargs: LoadedData(
            rows=rows(100.0, 101.0, 102.0, 104.0, research_fields=True)
        ),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is False
    assert result.result_dir is not None
    summary = read_summary(result.result_dir)
    assert summary["stage"] == "request_build"
    assert "execution kernel cannot represent flat target for SPY" in summary["message"]
    assert not (result.result_dir / "strategy_input_rows.csv").exists()
    assert (result.result_dir / "strategy_input_rows.jsonl").exists()
    assert (result.result_dir / "data_manifest.json").exists()
    assert (result.result_dir / "decision_records.jsonl").exists()
    assert not (result.result_dir / "signals.csv").exists()
    assert_assessment(
        result, summary, assessment_status="runner_failed", failure_stage=str(summary["stage"])
    )


def test_decision_strategy_id_mismatch_fails_before_writing_decision_records(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    strategy = tmp_path / "strategies" / "demo.py"
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
        lambda config, **_kwargs: LoadedData(
            rows=rows(100.0, 101.0, 102.0, 104.0, research_fields=True)
        ),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is False
    assert result.result_dir is not None
    summary = read_summary(result.result_dir)
    assert summary["stage"] == "decision_generation"
    assert "decision_strategy_id_mismatch[0]: expected demo, got other" in summary["message"]
    assert not (result.result_dir / "decision_records.jsonl").exists()
    assert_assessment(
        result, summary, assessment_status="runner_failed", failure_stage=str(summary["stage"])
    )


def test_run_manifest_marks_dirty_git_worktree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path)
    (tmp_path / ".gitignore").write_text("results/\n")
    (tmp_path / "README.md").write_text("clean\n")
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "baseline"], cwd=tmp_path, check=True, capture_output=True
    )
    (tmp_path / "README.md").write_text("dirty\n")
    (tmp_path / "scratch.txt").write_text("untracked\n")
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.result_dir is not None
    run_manifest = json.loads((result.result_dir / "run_manifest.json").read_text())
    environment = json.loads((result.result_dir / "environment.json").read_text())
    repository = environment["repository"]
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
    assert run_manifest["repository"]["commit"] == repository["commit"]
    assert "dirty" not in run_manifest["repository"]
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
    subprocess.run(
        ["git", "commit", "-m", "baseline"], cwd=tmp_path, check=True, capture_output=True
    )
    (tmp_path / "scratch.txt").write_text("untracked\n")
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.result_dir is not None
    run_manifest = json.loads((result.result_dir / "run_manifest.json").read_text())
    environment = json.loads((result.result_dir / "environment.json").read_text())
    repository = environment["repository"]
    assert run_manifest["repository"]["commit"] == repository["commit"]
    assert "dirty" not in run_manifest["repository"]
    assert repository["dirty"] is False
    assert repository["status_porcelain_sha256"] is None
    assert repository["tracked_diff_sha256"] is None


def test_crypto_perp_funding_notes_label_returns_as_funding_aware(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    config_path = write_config(
        tmp_path, kind="crypto_perp_funding", symbol="BTC-PERP", dataset=None
    )
    funding_rows = rows(100.0, 101.0, 102.0, 104.0, research_fields=True)
    for row in funding_rows:
        row["symbol"] = "BTC-PERP"
    funding_rows[3].update(
        {
            "funding_timestamp": funding_rows[3]["timestamp"],
            "funding_rate": 0.0001,
            "funding_ingested_at": funding_rows[3]["available_at"],
            "has_funding_event": True,
        }
    )
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=funding_rows),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.result_dir is not None
    summary = json.loads((result.result_dir / "summary.json").read_text())
    assert summary["funding_model"] == "linear_additive_adjustment"
    run_manifest = json.loads((result.result_dir / "run_manifest.json").read_text())
    assert run_manifest["evidence"]["funding_model"] == "linear_additive_adjustment"
    funding = run_manifest["evidence"]["metric_semantics"][
        "trade_result.sum_signed_trade_activity_funding"
    ]
    assert funding["return_path_model"] == "linear_additive_adjustment"
    notes = (result.result_dir / "notes.md").read_text()
    assert "return_scope: price-and-funding" in notes
    assert "supplied funding events are included" in notes


def test_request_build_failure_preserves_prior_stage_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path)
    monkeypatch.setattr(
        execution, "load_data", lambda config, **_kwargs: LoadedData(rows=rows(100.0, 101.0, 102.0))
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is False
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
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)),
    )
    monkeypatch.setattr(
        engine_runner,
        "evaluate_request",
        lambda request, *, mode, include_evidence=True, include_diagnostics=False: (
            _ for _ in ()
        ).throw(EvaluationRunError("engine unavailable")),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is False
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
    candidate_dir = repo_root / "candidates" / "demo"
    candidate_dir.mkdir(parents=True)
    (candidate_dir / "strategy.py").write_text((repo_root / "strategies" / "demo.py").read_text())
    config_path = write_config(
        repo_root,
        relative_path="candidates/demo/run.toml",
        strategy_path="strategy.py",
    )
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)),
    )
    monkeypatch.chdir(tmp_path)

    result = run_config("candidates/demo/run.toml", repo_root=repo_root)

    assert result.outcome.completed is True
    assert result.result_dir is not None
    assert (result.result_dir / "config.toml").read_text() == config_path.read_text()


def test_run_config_emits_structured_stage_events(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path)
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)),
    )
    events: list[dict[str, object]] = []

    result = run_config(config_path, repo_root=tmp_path, event_sink=events.append)

    assert result.outcome.completed is True
    assert events
    assert all(event["event"] == "runner_stage" for event in events)
    assert all(isinstance(event["timestamp"], str) for event in events)
    completed_stages = {str(event["stage"]) for event in events if event["status"] == "completed"}
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
    import quant_strategies.cli as cli

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    write_strategy(repo_root)
    candidate_dir = repo_root / "candidates" / "demo"
    candidate_dir.mkdir(parents=True)
    (candidate_dir / "strategy.py").write_text((repo_root / "strategies" / "demo.py").read_text())
    write_config(
        repo_root,
        relative_path="candidates/demo/run.toml",
        strategy_path="strategy.py",
    )
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)),
    )
    monkeypatch.chdir(tmp_path)

    exit_code = cli.main(["run", "--repo-root", str(repo_root), "candidates/demo/run.toml"])
    output = capsys.readouterr().out.strip()

    assert exit_code == 0, output
    assert Path(output).exists()


def test_cli_run_events_jsonl_writes_events_to_stderr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    import quant_strategies.cli as cli

    write_strategy(tmp_path)
    config_path = write_config(tmp_path)
    monkeypatch.setattr(config_module, "default_repo_root", lambda: tmp_path)
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)),
    )

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
        event["stage"] == "engine_evaluation" and event["status"] == "completed" for event in events
    )


def test_cli_quick_run_uses_runner_and_prints_result_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    import quant_strategies.cli as cli

    write_strategy(tmp_path)
    config_path = write_config(tmp_path)
    monkeypatch.setattr(config_module, "default_repo_root", lambda: tmp_path)
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)),
    )

    exit_code = cli.main(["run", str(config_path)])
    output = capsys.readouterr().out.strip()

    assert exit_code == 0, output
    assert Path(output).exists()


def test_cli_reports_failure_with_notes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    import quant_strategies.cli as cli

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
            outcome=RunOutcome(completed=False, failure_stage="request_build"),
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
    import quant_strategies.cli as cli

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
            outcome=RunOutcome(completed=False, failure_stage="data_readiness"),
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

    def load_data(config, **_kwargs):
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
        "environment.json",
        "summary.json",
        "evidence.json",
        "notes.md",
    }

    assert first.outcome.completed is True
    assert second.outcome.completed is True
    assert first.evidence.replayable_from_artifacts is True
    assert second.evidence.replayable_from_artifacts is True
    assert first.result_dir is not None
    assert second.result_dir is not None
    assert first.result_dir != second.result_dir
    assert {
        path.name for path in first.result_dir.iterdir() if path.is_file()
    } == expected_artifacts
    assert {
        path.name for path in second.result_dir.iterdir() if path.is_file()
    } == expected_artifacts
    assert {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in first.result_dir.iterdir()
        if path.is_file()
    } == {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in second.result_dir.iterdir()
        if path.is_file()
    }


def test_run_config_artifact_initialization_failure_returns_structured_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path)

    def raise_oserror(config, **_kwargs):
        raise PermissionError("results dir not writable")

    monkeypatch.setattr(artifacts, "create_result_dir", raise_oserror)

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.failure_stage == "artifact_initialization"
    assert result.result_dir is None
    assert result.outcome.completed is False
    assert result.evidence.replayable_from_artifacts is True
    assert "artifact initialization failed" in result.message


def test_run_config_completion_write_failure_returns_structured_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import quant_strategies.runner as runner_pkg

    write_strategy(tmp_path)
    config_path = write_config(tmp_path)
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)),
    )

    def raise_oserror(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(runner_pkg, "_write_completion_artifacts", raise_oserror)

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.failure_stage == "artifact_write"
    assert result.outcome.completed is False
    assert result.result_dir is not None
    assert result.evidence.replayable_from_artifacts is True
    assert result.economics is not None
    assert result.economics.trade_count == 1
    assert "artifact write failed" in result.message


def test_run_cli_backstops_oserror(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys):
    import quant_strategies.cli as cli

    def raise_oserror(path, repo_root=None, **_kwargs):
        raise PermissionError("results dir not writable")

    monkeypatch.setattr("quant_strategies.cli.run_config", raise_oserror)

    code = cli.main(["run", "--repo-root", str(tmp_path), "run.toml"])

    assert code == 1
    assert "run failed" in capsys.readouterr().out


def test_run_config_flags_unvalidated_passthrough_on_quick_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    # The default demo strategy defines no validate_params: the quick run completes
    # but is visibly flagged as exploratory (params not schema-checked).
    write_strategy(tmp_path)
    config_path = write_config(tmp_path)
    monkeypatch.setattr(
        execution,
        "load_data",
        lambda config, **_kwargs: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.completed is True
    assert result.outcome.param_contract == "unvalidated_passthrough"
    summary = json.loads((result.result_dir / "summary.json").read_text())
    assert summary["param_contract"] == "unvalidated_passthrough"


def test_run_config_failure_path_artifact_write_error_returns_structured_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    # A failure path (data_load) routes through _failure_result; if its artifact
    # write also fails, run_config must return a structured result, not raise.
    write_strategy(tmp_path)
    config_path = write_config(tmp_path)

    def fail_data_load(config, **_kwargs):
        raise DataLoadError("no data")

    monkeypatch.setattr(execution, "load_data", fail_data_load)

    def raise_oserror(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(artifacts, "write_notes", raise_oserror)

    result = run_config(config_path, repo_root=tmp_path)

    assert result.outcome.failure_stage == "data_load"
    assert result.outcome.completed is False
    assert result.notes_path is None
