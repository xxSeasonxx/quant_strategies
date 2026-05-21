from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from quant_strategies.runner import RunResult, cli, config as config_module, data_loader, engine_runner, run_config
from quant_strategies.runner.data_loader import LoadedData
from quant_strategies.runner.errors import DataLoadError, EvaluationRunError


SUMMARY_KEYS = {"strategy_id", "mode", "success", "status", "stage", "message", "artifacts", "engine"}


def rows(*closes: float, quotes: bool = False, research_fields: bool = False) -> list[dict[str, object]]:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    result: list[dict[str, object]] = []
    for index, close in enumerate(closes):
        row = {
            "symbol": "SPY" if not quotes else "EURUSD",
            "timestamp": start + timedelta(days=index),
            "open": close,
            "high": close,
            "low": close,
            "close": close,
        }
        if quotes:
            row.update({"bid": close - 0.01, "ask": close + 0.01, "mid": close})
        if research_fields:
            row.update(
                {
                    "funding_timestamp": row["timestamp"] if index == 0 else None,
                    "funding_rate": 0.0001 if index == 0 else None,
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
mode = "validate"
'''.lstrip()
    )
    return config_path


def read_summary(result_dir: Path) -> dict[str, object]:
    summary = json.loads((result_dir / "summary.json").read_text())
    assert set(summary) == SUMMARY_KEYS
    assert all((result_dir / name).exists() for name in summary["artifacts"])
    return summary


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
        "summary.json",
        "evidence.json",
        "notes.md",
    }
    assert {path.name for path in result.result_dir.iterdir() if path.is_file()} == expected
    summary = read_summary(result.result_dir)
    assert summary["stage"] == "completed"
    assert summary["success"] is True
    assert summary["engine"] == {"passed": True, "trade_count": 1}
    assert "runner smoke evidence only" in (result.result_dir / "notes.md").read_text()


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
    assert read_summary(result.result_dir)["stage"] == "data_load"
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
    assert read_summary(result.result_dir)["stage"] == "strategy_import"


def test_strategy_path_directory_failure_writes_summary(tmp_path: Path):
    strategy_dir = tmp_path / "tested" / "demo.py"
    strategy_dir.mkdir(parents=True)
    config_path = write_config(tmp_path)

    result = run_config(config_path, repo_root=tmp_path)

    assert result.success is False
    assert result.result_dir is not None
    assert not (result.result_dir / "strategy_snapshot.py").exists()
    assert read_summary(result.result_dir)["stage"] == "strategy_import"


def test_raw_inputs_preserve_quote_and_funding_fields_while_engine_request_excludes_non_engine_fields(
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
    assert jsonl_rows[0]["bid"] == 1.09
    assert jsonl_rows[0]["ask"] == 1.11
    assert jsonl_rows[0]["funding_timestamp"] == "2024-01-01T00:00:00+00:00"
    assert jsonl_rows[0]["has_funding_event"] is True
    assert jsonl_rows[1]["nullable"] is None
    assert request["bars"][0]["bid"] == 1.09
    assert request["bars"][0]["ask"] == 1.11
    assert "funding_rate" not in request["bars"][0]
    assert "has_funding_event" not in request["bars"][0]


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
        lambda path: RunResult(success=False, result_dir=notes.parent, notes_path=notes, message="failed"),
    )

    exit_code = cli.main(["run", "bad.toml"])

    assert exit_code == 1
    assert str(notes) in capsys.readouterr().out
