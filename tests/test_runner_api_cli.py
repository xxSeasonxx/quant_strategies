from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from quant_strategies.runner import RunResult, cli, config as config_module, data_loader, run_config, strategy_loader
from quant_strategies.runner.data_loader import LoadedData
from quant_strategies.runner.errors import DataLoadError


def rows(*closes: float, quotes: bool = False) -> list[dict[str, object]]:
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
    kind: str = "bars",
    symbol: str = "SPY",
    dataset: str | None = "equity_1min",
    fill_price: str = "close",
) -> Path:
    dataset_line = f'dataset = "{dataset}"\n' if dataset is not None else ""
    config_path = repo_root / "run.toml"
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
entry_lag_bars = 1

[cost_model]
fee_bps_per_side = 0.0
slippage_bps_per_side = 0.0

[output]
results_dir = "results"
mode = "validate"
'''.lstrip()
    )
    return config_path


def test_run_config_writes_success_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path)
    monkeypatch.setattr(data_loader, "load_data", lambda config: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0)))

    result = run_config(config_path, repo_root=tmp_path)

    assert result.success is True
    assert result.result_dir is not None
    for name in (
        "config.toml",
        "strategy_snapshot.py",
        "bars.csv",
        "signals.csv",
        "request.json",
        "screen_summary.json",
        "validate_summary.json",
        "evidence.json",
        "notes.md",
    ):
        assert (result.result_dir / name).exists()


def test_run_config_writes_pre_engine_failure_notes_and_does_not_call_strategy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path)

    def fail_data_load(config):
        raise DataLoadError("strict data window failed")

    def forbidden_strategy_load(*args, **kwargs):
        raise AssertionError("strategy should not load after data failure")

    monkeypatch.setattr(data_loader, "load_data", fail_data_load)
    monkeypatch.setattr(strategy_loader, "load_strategy", forbidden_strategy_load)

    result = run_config(config_path, repo_root=tmp_path)

    assert result.success is False
    assert result.result_dir is not None
    assert (result.result_dir / "config.toml").exists()
    assert (result.result_dir / "strategy_snapshot.py").exists()
    assert "strict data window failed" in (result.result_dir / "notes.md").read_text()


def test_quote_fields_survive_bars_csv_and_request_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
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
        lambda config: LoadedData(rows=rows(1.10, 1.11, 1.12, 1.13, quotes=True)),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.result_dir is not None
    with (result.result_dir / "bars.csv").open() as handle:
        csv_rows = list(csv.DictReader(handle))
    request = json.loads((result.result_dir / "request.json").read_text())
    assert csv_rows[0]["bid"] == "1.09"
    assert csv_rows[0]["ask"] == "1.11"
    assert request["bars"][0]["bid"] == 1.09
    assert request["bars"][0]["ask"] == 1.11


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
