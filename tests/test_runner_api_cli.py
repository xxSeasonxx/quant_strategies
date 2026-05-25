from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from quant_strategies.runner import RunResult, cli, config as config_module, data_loader, engine_runner, run_config
from quant_strategies.runner.data_loader import LoadedData
from quant_strategies.runner.errors import DataLoadError, EvaluationRunError


SUMMARY_KEYS = {
    "strategy_id",
    "mode",
    "success",
    "status",
    "stage",
    "message",
    "artifacts",
    "engine",
    "run_completed",
    "assessment_status",
    "promotion_eligible",
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
            "def generate_signals(bars, params):\n"
            "    return [{'symbol': 'EURUSD', 'decision_time': bars[1]['timestamp'], "
            "'side': 'long', 'weight': 1.0, 'hold_bars': 1}]\n"
        )
        return
    strategy.write_text(
        "def generate_signals(bars, params):\n"
        "    return [{'symbol': bars[1]['symbol'], 'decision_time': bars[1]['timestamp'], "
        "'side': 'long', 'weight': 1.0, 'hold_bars': 1}]\n"
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
'''.lstrip()
    )
    return config_path


def read_summary(result_dir: Path) -> dict[str, object]:
    summary = json.loads((result_dir / "summary.json").read_text())
    assert set(summary) == SUMMARY_KEYS
    assert all((result_dir / name).exists() for name in summary["artifacts"])
    return summary


def assert_assessment(
    result: RunResult,
    summary: dict[str, object],
    *,
    assessment_status: str,
    run_completed: bool = True,
    promotion_eligible: bool = False,
) -> None:
    assert result.run_completed is run_completed
    assert result.assessment_status == assessment_status
    assert result.promotion_eligible is promotion_eligible
    assert summary["run_completed"] is run_completed
    assert summary["assessment_status"] == assessment_status
    assert summary["promotion_eligible"] is promotion_eligible


def test_run_config_writes_success_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path)
    monkeypatch.setattr(data_loader, "load_data", lambda config: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)))

    result = run_config(config_path, repo_root=tmp_path)

    assert result.success is True
    assert result.result_dir is not None
    expected = {
        "config.toml",
        "strategy_snapshot.py",
        "strategy_input_rows.csv",
        "strategy_input_rows.jsonl",
        "signals.csv",
        "engine_request.json",
        "data_manifest.json",
        "run_manifest.json",
        "summary.json",
        "evidence.json",
        "notes.md",
    }
    assert {path.name for path in result.result_dir.iterdir() if path.is_file()} == expected
    summary = read_summary(result.result_dir)
    assert summary["stage"] == "completed"
    assert summary["success"] is True
    assert summary["status"] == "passed"
    assert summary["engine"] == {"passed": True, "trade_count": 1}
    assert_assessment(result, summary, assessment_status="smoke_passed")
    assert "runner smoke evidence only" in (result.result_dir / "notes.md").read_text()


def test_screen_mode_completion_is_screened_not_validation_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path, mode="screen")
    monkeypatch.setattr(data_loader, "load_data", lambda config: LoadedData(rows=rows(100.0, 101.0, 90.0, 89.0)))

    result = run_config(config_path, repo_root=tmp_path)

    assert result.success is True
    assert result.result_dir is not None
    summary = read_summary(result.result_dir)
    assert summary["mode"] == "screen"
    assert summary["stage"] == "completed"
    assert summary["status"] == "screened"
    assert summary["engine"] == {"passed": None, "trade_count": 1}
    assert_assessment(result, summary, assessment_status="screened")
    notes = (result.result_dir / "notes.md").read_text()
    assert "status: screened" in notes
    assert "status: passed" not in notes
    assert "not validation pass" in notes


def test_run_artifacts_preserve_exit_reason_and_signal_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    strategy = tmp_path / "tested" / "demo.py"
    strategy.parent.mkdir(parents=True, exist_ok=True)
    strategy.write_text(
        "def generate_signals(bars, params):\n"
        "    return [{'symbol': bars[1]['symbol'], 'decision_time': bars[1]['timestamp'], "
        "'side': 'long', 'weight': 1.0, 'hold_bars': 5, 'max_hold_bars': 2, "
        "'take_profit_bps': 50.0, 'funding_pressure_bps': 3.25, "
        "'entry_return_extension_bps': 42.0, 'signal_family': 'demo'}]\n"
    )
    config_path = write_config(tmp_path, mode="screen")
    monkeypatch.setattr(data_loader, "load_data", lambda config: LoadedData(rows=rows(100.0, 100.0, 102.0, 103.0, 104.0)))

    result = run_config(config_path, repo_root=tmp_path)

    assert result.success is True
    assert result.result_dir is not None
    with (result.result_dir / "signals.csv").open() as handle:
        signal_rows = list(csv.DictReader(handle))
    request = json.loads((result.result_dir / "engine_request.json").read_text())
    evidence = json.loads((result.result_dir / "evidence.json").read_text())
    signal_payload = request["spec"]["signals"][0]
    trade = evidence["screening_result"]["trades"][0]

    assert signal_rows[0]["max_hold_bars"] == "2"
    assert signal_rows[0]["take_profit_bps"] == "50.0"
    assert signal_rows[0]["funding_pressure_bps"] == "3.25"
    assert evidence["schema_version"] == "quant_strategies.engine.evidence/v2"
    assert signal_payload["metadata"]["funding_pressure_bps"] == 3.25
    assert signal_payload["metadata"]["entry_return_extension_bps"] == 42.0
    assert signal_payload["metadata"]["signal_family"] == "demo"
    assert trade["exit_reason"] == "take_profit"
    assert trade["signal_metadata"]["funding_pressure_bps"] == 3.25


def test_validation_gate_failure_remains_failed_summary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path, mode="validate")
    monkeypatch.setattr(data_loader, "load_data", lambda config: LoadedData(rows=rows(100.0, 101.0, 90.0, 89.0)))

    result = run_config(config_path, repo_root=tmp_path)

    assert result.success is False
    assert result.result_dir is not None
    summary = read_summary(result.result_dir)
    assert summary["mode"] == "validate"
    assert summary["stage"] == "completed"
    assert summary["status"] == "failed"
    assert summary["engine"] == {"passed": False, "trade_count": 1}
    assert_assessment(result, summary, assessment_status="smoke_failed")
    assert "status: failed validation gates" in (result.result_dir / "notes.md").read_text()


def test_run_config_writes_data_failure_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path)

    def fail_data_load(config):
        raise DataLoadError("strict data window failed")

    monkeypatch.setattr(data_loader, "load_data", fail_data_load)

    result = run_config(config_path, repo_root=tmp_path)

    assert result.success is False
    assert result.result_dir is not None
    assert (result.result_dir / "config.toml").exists()
    assert (result.result_dir / "strategy_snapshot.py").exists()
    assert "strict data window failed" in (result.result_dir / "notes.md").read_text()
    summary = read_summary(result.result_dir)
    assert summary["stage"] == "data_load"
    assert_assessment(result, summary, assessment_status="runner_failed")
    assert (result.result_dir / "run_manifest.json").exists()
    assert not (result.result_dir / "strategy_input_rows.csv").exists()


def test_strategy_import_failure_prevents_data_load(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    strategy = tmp_path / "tested" / "demo.py"
    strategy.parent.mkdir(parents=True, exist_ok=True)
    strategy.write_text("VALUE = 1\n")
    config_path = write_config(tmp_path)

    def forbidden_data_load(config):
        raise AssertionError("data should not load after strategy import failure")

    monkeypatch.setattr(data_loader, "load_data", forbidden_data_load)

    result = run_config(config_path, repo_root=tmp_path)

    assert result.success is False
    assert result.result_dir is not None
    summary = read_summary(result.result_dir)
    assert summary["stage"] == "strategy_import"
    assert_assessment(result, summary, assessment_status="runner_failed")
    assert (result.result_dir / "run_manifest.json").exists()


def test_strategy_path_directory_failure_writes_summary(tmp_path: Path):
    strategy_dir = tmp_path / "tested" / "demo.py"
    strategy_dir.mkdir(parents=True)
    config_path = write_config(tmp_path)

    result = run_config(config_path, repo_root=tmp_path)

    assert result.success is False
    assert result.result_dir is not None
    assert not (result.result_dir / "strategy_snapshot.py").exists()
    summary = read_summary(result.result_dir)
    assert summary["stage"] == "strategy_import"
    assert_assessment(result, summary, assessment_status="runner_failed")
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
        data_loader,
        "load_data",
        lambda config: LoadedData(rows=rows(1.10, 1.11, 1.12, 1.13, quotes=True, research_fields=True)),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.result_dir is not None
    with (result.result_dir / "strategy_input_rows.csv").open() as handle:
        csv_rows = list(csv.DictReader(handle))
    jsonl_rows = [
        json.loads(line)
        for line in (result.result_dir / "strategy_input_rows.jsonl").read_text().splitlines()
    ]
    request = json.loads((result.result_dir / "engine_request.json").read_text())
    assert csv_rows[0]["bid"] == "1.09"
    assert csv_rows[0]["ask"] == "1.11"
    assert csv_rows[0]["funding_rate"] == "0.0001"
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


def test_completed_run_writes_minimal_manifests(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path)
    loaded_rows = rows(100.0, 101.0, 102.0, 104.0, research_fields=True)
    monkeypatch.setattr(data_loader, "load_data", lambda config: LoadedData(rows=loaded_rows))

    result = run_config(config_path, repo_root=tmp_path)

    assert result.success is True
    assert result.result_dir is not None
    run_manifest = json.loads((result.result_dir / "run_manifest.json").read_text())
    data_manifest = json.loads((result.result_dir / "data_manifest.json").read_text())
    assert run_manifest["python"]["version"]
    assert {"quant-strategies", "quant-data", "pydantic"}.issubset(run_manifest["packages"])
    assert LEGACY_DISTRIBUTION not in run_manifest["packages"]
    assert run_manifest["engine"] == {"evidence_schema": "quant_strategies.engine.evidence/v2"}
    assert run_manifest["artifacts"]["config.toml"]["sha256"]
    assert run_manifest["artifacts"]["strategy_snapshot.py"]["sha256"]
    assert run_manifest["artifacts"]["strategy_input_rows.jsonl"]["sha256"]
    assert run_manifest["artifacts"]["signals.csv"]["sha256"]
    assert run_manifest["artifacts"]["engine_request.json"]["sha256"]
    assert data_manifest["data"] == {
        "kind": "bars",
        "dataset": "equity_1min",
        "symbols": ["SPY"],
        "start": "2024-01-01",
        "end": "2024-01-05",
        "strict": True,
    }
    assert data_manifest["rows"]["total"] == 4
    assert data_manifest["rows"]["by_symbol"]["SPY"]["count"] == 4
    assert data_manifest["rows"]["by_symbol"]["SPY"]["min_timestamp"] == "2024-01-01T00:00:00+00:00"
    assert data_manifest["rows"]["by_symbol"]["SPY"]["max_timestamp"] == "2024-01-04T00:00:00+00:00"
    assert data_manifest["strategy_input_rows_jsonl_sha256"] == run_manifest["artifacts"]["strategy_input_rows.jsonl"]["sha256"]
    summary = read_summary(result.result_dir)
    assert "run_manifest.json" in summary["artifacts"]
    assert "data_manifest.json" in summary["artifacts"]


def test_signal_generation_failure_writes_run_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    strategy = tmp_path / "tested" / "demo.py"
    strategy.parent.mkdir(parents=True, exist_ok=True)
    strategy.write_text("def generate_signals(bars, params):\n    raise RuntimeError('boom')\n")
    config_path = write_config(tmp_path)
    monkeypatch.setattr(data_loader, "load_data", lambda config: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)))

    result = run_config(config_path, repo_root=tmp_path)

    assert result.success is False
    assert result.result_dir is not None
    assert (result.result_dir / "run_manifest.json").exists()
    summary = read_summary(result.result_dir)
    assert summary["stage"] == "signal_generation"
    assert_assessment(result, summary, assessment_status="runner_failed")


@pytest.mark.parametrize("readiness_lag", [-timedelta(minutes=1), timedelta(0)])
def test_data_readiness_allows_matching_decision_row_at_or_before_decision_time(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    readiness_lag: timedelta,
):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path)
    loaded_rows = rows(100.0, 101.0, 102.0, 104.0, research_fields=True, readiness_lag=readiness_lag)
    monkeypatch.setattr(data_loader, "load_data", lambda config: LoadedData(rows=loaded_rows))

    result = run_config(config_path, repo_root=tmp_path)

    assert result.success is True
    assert result.result_dir is not None
    summary = read_summary(result.result_dir)
    assert summary["stage"] == "completed"


def test_data_readiness_failure_preserves_prior_artifacts_and_skips_engine_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path)
    monkeypatch.setattr(
        data_loader,
        "load_data",
        lambda config: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0, research_fields=True, readiness_lag=timedelta(minutes=1))),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.success is False
    assert result.result_dir is not None
    for name in (
        "strategy_input_rows.csv",
        "strategy_input_rows.jsonl",
        "data_manifest.json",
        "signals.csv",
        "run_manifest.json",
        "summary.json",
        "notes.md",
    ):
        assert (result.result_dir / name).exists()
    assert not (result.result_dir / "engine_request.json").exists()
    summary = read_summary(result.result_dir)
    assert summary["stage"] == "data_readiness"
    assert "available after decision_time" in summary["message"]
    assert_assessment(result, summary, assessment_status="runner_failed")


def test_malformed_signal_decision_time_remains_request_build_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    strategy = tmp_path / "tested" / "demo.py"
    strategy.parent.mkdir(parents=True, exist_ok=True)
    strategy.write_text(
        "def generate_signals(bars, params):\n"
        "    return [{'symbol': bars[1]['symbol'], 'decision_time': 'not-a-timestamp', "
        "'side': 'long', 'weight': 1.0, 'hold_bars': 1}]\n"
    )
    config_path = write_config(tmp_path)
    monkeypatch.setattr(
        data_loader,
        "load_data",
        lambda config: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0, research_fields=True)),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.success is False
    assert result.result_dir is not None
    summary = read_summary(result.result_dir)
    assert summary["stage"] == "request_build"
    assert "decision_time must be a valid ISO timestamp" in summary["message"]
    assert_assessment(result, summary, assessment_status="runner_failed")


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
    monkeypatch.setattr(data_loader, "load_data", lambda config: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)))

    result = run_config(config_path, repo_root=tmp_path)

    assert result.result_dir is not None
    run_manifest = json.loads((result.result_dir / "run_manifest.json").read_text())
    repository = run_manifest["repository"]
    result_exclusion = f":(exclude){result.result_dir.relative_to(tmp_path).as_posix()}"
    expected_status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all", "--", ".", result_exclusion],
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


def test_crypto_perp_funding_notes_label_returns_as_funding_aware(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path, kind="crypto_perp_funding", symbol="BTC-PERP", dataset=None)
    monkeypatch.setattr(
        data_loader,
        "load_data",
        lambda config: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0, research_fields=True)),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.result_dir is not None
    notes = (result.result_dir / "notes.md").read_text()
    assert "return_scope: price-and-funding" in notes
    assert "supplied funding events are included" in notes


def test_request_build_failure_preserves_prior_stage_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path)
    monkeypatch.setattr(data_loader, "load_data", lambda config: LoadedData(rows=rows(100.0, 101.0, 102.0)))

    result = run_config(config_path, repo_root=tmp_path)

    assert result.success is False
    assert result.result_dir is not None
    for name in ("strategy_input_rows.csv", "strategy_input_rows.jsonl", "signals.csv", "summary.json", "notes.md"):
        assert (result.result_dir / name).exists()
    assert not (result.result_dir / "engine_request.json").exists()
    assert read_summary(result.result_dir)["stage"] == "request_build"


def test_engine_failure_preserves_engine_request_and_writes_stage_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path)
    monkeypatch.setattr(data_loader, "load_data", lambda config: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)))
    monkeypatch.setattr(
        engine_runner,
        "evaluate_request",
        lambda request, *, mode: (_ for _ in ()).throw(EvaluationRunError("engine unavailable")),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.success is False
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
    monkeypatch.setattr(data_loader, "load_data", lambda config: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)))
    monkeypatch.chdir(tmp_path)

    result = run_config("runs/demo.toml", repo_root=repo_root)

    assert result.success is True
    assert result.result_dir is not None
    assert (result.result_dir / "config.toml").read_text() == config_path.read_text()


def test_cli_run_accepts_explicit_repo_root_from_other_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    write_strategy(repo_root)
    write_config(repo_root, relative_path="runs/demo.toml")
    monkeypatch.setattr(data_loader, "load_data", lambda config: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)))
    monkeypatch.chdir(tmp_path)

    exit_code = cli.main(["run", "--repo-root", str(repo_root), "runs/demo.toml"])
    output = capsys.readouterr().out.strip()

    assert exit_code == 0, output
    assert Path(output).exists()


def test_cli_smoke_uses_runner_and_prints_result_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path)
    monkeypatch.setattr(config_module, "default_repo_root", lambda: tmp_path)
    monkeypatch.setattr(data_loader, "load_data", lambda config: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)))

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
            success=False,
            result_dir=notes.parent,
            notes_path=notes,
            message="failed",
        ),
    )

    exit_code = cli.main(["run", "bad.toml"])

    assert exit_code == 1
    assert str(notes) in capsys.readouterr().out
