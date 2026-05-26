# Foundation Phase 5 Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep broad `quant_autoresearch` quick runs on the shared `quant_strategies.runner.run_config` path by adding compact summary artifacts and removing avoidable per-signal bar scans without changing strategy semantics.

**Architecture:** Add an explicit runner artifact profile with `full` as the default and `summary` as a compact quick-research mode. Keep all strategy execution, decision validation, data readiness, and engine evaluation semantics unchanged; only change which artifacts are written and how bar lookups are indexed internally. Add performance tests with generous but meaningful runtime and artifact-byte budgets so future regressions are caught before `quant_autoresearch` needs a private runner again.

**Tech Stack:** Python 3.12, Pydantic v2, pytest, existing `quant_strategies.runner`, `quant_strategies.engine`, and `quant_strategies.provenance` modules.

---

## Scope Check

This plan implements Phase 5 from `docs/superpowers/specs/2026-05-26-foundation-repair-design.md`:

- Pre-index bars by `(symbol, timestamp)` once per engine request.
- Reuse the index for runner fillability checks and engine evaluation.
- Skip funding scans when there are no funding events and pre-index funding events when they exist.
- Add `artifact_profile = "summary"` for quick research.
- Keep full artifacts for curated reruns and promotion candidates.
- Add an autoresearch-scale benchmark with runtime and artifact-byte limits.

This plan does not implement Phase 6:

- No observation/dependency metadata schema.
- No future-poison causality tests.
- No backend capability matrix.
- No portfolio target-weight support.

## Engineering Review Decisions

These decisions supersede any older snippet below where they differ.

- Keep Phase 5 as one coherent change: summary artifacts and engine indexing ship together because either half alone leaves `quant_autoresearch` with a reason to bypass the shared runner.
- Summary mode must keep scoreable compact engine evidence. Do not reduce engine output to only `passed` and `trade_count`; include compact totals such as `gross_return`, `funding_return`, `cost_return`, `net_return`, and validation gate summaries when present, while still omitting full trades, full engine request JSON, and full evidence JSON.
- Make `src/quant_strategies/runner/artifact_profiles.py` the authoritative home for artifact JSON normalization, row-range summaries, normalized row hashing, and summary-profile payload helpers. Remove the duplicated old helper logic from `artifacts.py` by importing the new shared helpers.
- Compute the normalized row hash exactly once per successful run and pass it to both `data_manifest.json` and `artifact_profile_summary.json`; do not normalize/hash the same row set twice.
- Replace the draft performance benchmark with a late-decision worst-case benchmark. Signals should target bars near the end of each symbol series so the current repeated scan path is measurably exercised before indexing.

## Data Flow

```text
run_config(config)
  -> load_config(output.artifact_profile)
  -> load_data(rows)
  -> normalized_rows_sha256(rows)  # once
  -> write data_manifest.json
       full:    also write strategy_input_rows.csv/jsonl
       summary: no full row files
  -> generate_decisions(frozen rows, frozen params)
  -> validate_decision_output
  -> decisions_to_signal_rows
       full:    write decision_records.jsonl + signals.csv
       summary: keep compact decision/signal counts only
  -> build_request(rows, signals)
       runner fillability check uses indexed bars
       full: write engine_request.json
  -> engine screen/validate
       engine evaluation uses indexed bars and indexed funding events
       full: write evidence.json
       summary: write compact engine metrics
  -> write run_manifest.json + summary.json + notes.md
```

## What Already Exists

- `run_config` already owns the shared quick-research orchestration path; this plan reuses it instead of adding a private `quant_autoresearch` runner.
- `runner/artifacts.py` already writes config snapshots, strategy snapshots, manifests, notes, summaries, and artifact hashes; this plan extends those writers rather than replacing the artifact system.
- `engine/evaluation.py` and `runner/engine_runner.py` already group bars by symbol; this plan changes the grouped representation to include timestamp indexes instead of adding a separate evaluation engine.
- Existing runner tests already assert full artifact presence and failure-stage artifact behavior; Phase 5 should update those expectations for the new `artifact_profile` field and add summary-mode-specific coverage.

## NOT In Scope

- Phase 6 validation-depth work is deferred: no observation/dependency metadata, future-poison tests, backend capability matrix, or portfolio target-weight support.
- No artifact compression format such as gzip or parquet is added; summary mode reduces artifact shape rather than changing storage technology.
- No runner API split is added for `quant_autoresearch`; `quant_autoresearch` should continue to call `quant_strategies.runner.run_config`.
- No live, paper-trading, or promotion eligibility semantics change; summary mode controls artifact size only.

## File Structure

- Modify `src/quant_strategies/runner/config.py`
  - Add `ArtifactProfile = Literal["full", "summary"]`.
  - Add `OutputConfig.artifact_profile` with default `"full"`.

- Create `src/quant_strategies/runner/artifact_profiles.py`
  - Own deterministic normalized row hashing.
  - Own shared JSON-safe value and row-range helpers used by both profile and manifest writers.
  - Own compact row, decision, signal, and engine summary payloads.
  - Write `artifact_profile_summary.json` for summary-mode runs.

- Modify `src/quant_strategies/runner/artifacts.py`
  - Let `write_strategy_input_rows(...)` return the raw JSONL hash it wrote.
  - Let `write_data_manifest(...)` work without raw input files.
  - Import shared JSON-safe value, row-range, and normalized-row-hash helpers from `artifact_profiles.py`.
  - Include `artifact_profile` in `run_manifest.json`.

- Modify `src/quant_strategies/runner/__init__.py`
  - Respect `config.output.artifact_profile`.
  - In `full`, keep current artifacts.
  - In `summary`, omit full row CSV/JSONL, decision JSONL, signal CSV, engine request JSON, and evidence JSON.
  - In `summary`, preserve compact scoreable engine metrics without full trades or full evidence.
  - Add `artifact_profile` to `summary.json`.

- Modify `src/quant_strategies/runner/engine_runner.py`
  - Replace repeated fillability decision-time scans with a per-request timestamp index.

- Modify `src/quant_strategies/engine/evaluation.py`
  - Replace repeated evaluation decision-time scans with a per-request timestamp index.
  - Pre-index funding-event bars by symbol.

- Modify `tests/test_runner_config.py`
  - Cover default, explicit, and invalid artifact profiles.

- Create `tests/test_runner_artifact_profiles.py`
  - Cover deterministic row hashing and compact summary payload shape.

- Modify `tests/test_runner_api_cli.py`
  - Cover summary artifact mode end-to-end.
  - Add `artifact_profile` to expected summary keys.

- Modify `tests/test_runner_engine_runner.py`
  - Cover runner fillability index behavior.

- Modify `tests/test_engine_screen.py`
  - Cover engine bar index behavior and funding event pre-indexing.

- Create `tests/test_phase5_performance.py`
  - Add a large synthetic engine benchmark with a runtime budget.
  - Add a summary-profile artifact byte-budget test.

- Modify `README.md`
  - Document `output.artifact_profile`.
  - Document which artifacts are omitted in summary mode.

## Task 1: Add Runner Artifact Profile Config

**Files:**
- Modify: `src/quant_strategies/runner/config.py`
- Modify: `tests/test_runner_config.py`

- [ ] **Step 1: Add failing config tests**

Append these tests to `tests/test_runner_config.py`:

```python
def test_artifact_profile_defaults_to_full(tmp_path: Path):
    write_strategy(tmp_path)

    config = load_config(write_config(tmp_path), repo_root=tmp_path)

    assert config.output.artifact_profile == "full"


def test_summary_artifact_profile_is_accepted(tmp_path: Path):
    write_strategy(tmp_path)
    path = write_config(tmp_path)
    text = path.read_text()
    path.write_text(text.replace('mode = "validate"\n', 'mode = "validate"\nartifact_profile = "summary"\n'))

    config = load_config(path, repo_root=tmp_path)

    assert config.output.artifact_profile == "summary"


def test_unknown_artifact_profile_is_rejected(tmp_path: Path):
    write_strategy(tmp_path)
    path = write_config(tmp_path)
    text = path.read_text()
    path.write_text(text.replace('mode = "validate"\n', 'mode = "validate"\nartifact_profile = "compact"\n'))

    with pytest.raises(ConfigError, match="artifact_profile"):
        load_config(path, repo_root=tmp_path)
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
conda run -n quant pytest tests/test_runner_config.py::test_artifact_profile_defaults_to_full tests/test_runner_config.py::test_summary_artifact_profile_is_accepted tests/test_runner_config.py::test_unknown_artifact_profile_is_rejected -q
```

Expected: the first two tests fail because `OutputConfig` has no `artifact_profile` field. The invalid-profile test may fail with a generic extra-field error before implementation.

- [ ] **Step 3: Add the config field**

Modify `src/quant_strategies/runner/config.py` near the existing type aliases:

```python
DataKind = Literal["bars", "crypto_perp_funding", "forex_with_quotes"]
RunMode = Literal["screen", "validate"]
ArtifactProfile = Literal["full", "summary"]
```

Modify `OutputConfig`:

```python
class OutputConfig(RunnerConfigModel):
    results_dir: Path
    mode: RunMode
    artifact_profile: ArtifactProfile = "full"

    @field_validator("results_dir")
    @classmethod
    def validate_results_dir(cls, value: Path, info: ValidationInfo) -> Path:
        return _resolve_inside_repo(value, _repo_root(info), "output.results_dir")
```

- [ ] **Step 4: Run config tests**

Run:

```bash
conda run -n quant pytest tests/test_runner_config.py -q
```

Expected: all config tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/quant_strategies/runner/config.py tests/test_runner_config.py
git commit -m "feat: add runner artifact profile config"
```

## Task 2: Add Compact Artifact Profile Helpers

**Files:**
- Create: `src/quant_strategies/runner/artifact_profiles.py`
- Create: `tests/test_runner_artifact_profiles.py`

- [ ] **Step 1: Write failing helper tests**

Create `tests/test_runner_artifact_profiles.py` with this content:

```python
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from quant_strategies.decisions import ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision
from quant_strategies.runner.artifact_profiles import (
    normalized_rows_sha256,
    summary_profile_payload,
    write_summary_profile_artifact,
)
from quant_strategies.runner.config import load_config


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


def config(tmp_path: Path):
    strategy = tmp_path / "tested" / "demo.py"
    strategy.parent.mkdir(parents=True)
    strategy.write_text("def generate_decisions(rows, params):\n    return []\n")
    config_path = tmp_path / "run.toml"
    config_path.write_text(
        '''
strategy_path = "tested/demo.py"
strategy_id = "demo"

[data]
kind = "bars"
dataset = "equity_1min"
symbols = ["SPY", "QQQ"]
start = "2024-01-01"
end = "2024-01-05"
strict = true

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
mode = "validate"
artifact_profile = "summary"
'''.lstrip()
    )
    return load_config(config_path, repo_root=tmp_path)


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


def test_summary_profile_payload_contains_rows_decisions_signals_and_engine(tmp_path: Path):
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
    signals = [
        {"symbol": "SPY", "decision_time": timestamp, "side": "long", "weight": 0.5, "hold_bars": 2},
        {"symbol": "QQQ", "decision_time": timestamp, "side": "short", "weight": 0.5, "hold_bars": 2},
    ]

    payload = summary_profile_payload(
        config=run_config,
        rows=rows,
        decisions=decisions,
        signals=signals,
        engine={
            "passed": True,
            "trade_count": 2,
            "gross_return": 0.03,
            "funding_return": 0.0,
            "cost_return": 0.0,
            "net_return": 0.03,
        },
    )

    assert payload["artifact_profile"] == "summary"
    assert payload["rows"]["row_count"] == 3
    assert payload["rows"]["sample_count"] == 3
    assert payload["rows"]["by_symbol"]["SPY"]["count"] == 2
    assert payload["decisions"]["count"] == 2
    assert payload["decisions"]["by_direction"] == {"long": 1, "short": 1}
    assert payload["signals"]["count"] == 2
    assert payload["signals"]["by_side"] == {"long": 1, "short": 1}
    assert payload["engine"] == {
        "passed": True,
        "trade_count": 2,
        "gross_return": 0.03,
        "funding_return": 0.0,
        "cost_return": 0.0,
        "net_return": 0.03,
    }


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
        signals=[{"symbol": "SPY", "decision_time": timestamp, "side": "long", "weight": 0.5, "hold_bars": 2}],
        engine={
            "passed": True,
            "trade_count": 1,
            "gross_return": 0.01,
            "funding_return": 0.0,
            "cost_return": 0.0,
            "net_return": 0.01,
        },
    )

    parsed = json.loads(path.read_text())
    assert path == result_dir / "artifact_profile_summary.json"
    assert parsed["rows"]["row_count"] == 1
    assert parsed["rows"]["normalized_rows_sha256"] == normalized_rows_sha256([row("SPY", timestamp, 100.0)])
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
conda run -n quant pytest tests/test_runner_artifact_profiles.py -q
```

Expected: import fails because `quant_strategies.runner.artifact_profiles` does not exist.

- [ ] **Step 3: Create the helper module**

Create `src/quant_strategies/runner/artifact_profiles.py` with this content:

Implementation requirements:

- Export `json_safe_value(...)` and `row_ranges_by_symbol(...)` from this module.
- Update `runner/artifacts.py` to use those exported helpers and delete its duplicated `_json_value(...)` and `_row_ranges_by_symbol(...)` implementations.
- Let `summary_profile_payload(...)` accept a precomputed `normalized_rows_hash: str | None = None`; compute the hash only when the caller does not pass one.
- Keep `normalized_rows_sha256(...)` deterministic with `sort_keys=True`, compact separators, and `allow_nan=False`.

```python
from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

from quant_strategies.decisions import StrategyDecision
from quant_strategies.provenance import text_sha256
from quant_strategies.runner.config import RunConfig


SUMMARY_SAMPLE_SIZE = 5


def normalized_rows_sha256(rows: Sequence[Mapping[str, Any]]) -> str:
    lines = [
        json.dumps(json_safe_value(row), sort_keys=True, separators=(",", ":"), allow_nan=False)
        for row in rows
    ]
    return text_sha256("\n".join(lines) + ("\n" if lines else ""))


def summary_profile_payload(
    *,
    config: RunConfig,
    rows: Sequence[Mapping[str, Any]],
    decisions: Sequence[StrategyDecision],
    signals: Sequence[Mapping[str, Any]],
    engine: Mapping[str, Any],
    normalized_rows_hash: str | None = None,
) -> dict[str, Any]:
    return {
        "artifact_profile": "summary",
        "strategy_id": config.strategy_id,
        "rows": _row_summary(config, rows, normalized_rows_hash=normalized_rows_hash),
        "decisions": _decision_summary(decisions),
        "signals": _signal_summary(signals),
        "engine": json_safe_value(engine),
    }


def write_summary_profile_artifact(
    result_dir: Path,
    *,
    config: RunConfig,
    rows: Sequence[Mapping[str, Any]],
    decisions: Sequence[StrategyDecision],
    signals: Sequence[Mapping[str, Any]],
    engine: Mapping[str, Any],
    normalized_rows_hash: str | None = None,
) -> Path:
    path = result_dir / "artifact_profile_summary.json"
    payload = summary_profile_payload(
        config=config,
        rows=rows,
        decisions=decisions,
        signals=signals,
        engine=engine,
        normalized_rows_hash=normalized_rows_hash,
    )
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return path


def _row_summary(
    config: RunConfig,
    rows: Sequence[Mapping[str, Any]],
    *,
    normalized_rows_hash: str | None,
) -> dict[str, Any]:
    sample = [json_safe_value(row) for row in rows[:SUMMARY_SAMPLE_SIZE]]
    return {
        "kind": config.data.kind,
        "dataset": config.data.dataset,
        "symbols": list(config.data.symbols),
        "start": config.data.start.isoformat(),
        "end": config.data.end.isoformat(),
        "row_count": len(rows),
        "sample_count": len(sample),
        "sample": sample,
        "normalized_rows_sha256": normalized_rows_hash or normalized_rows_sha256(rows),
        "by_symbol": row_ranges_by_symbol(rows),
    }


def _decision_summary(decisions: Sequence[StrategyDecision]) -> dict[str, Any]:
    symbols = Counter(item.instrument.symbol for item in decisions)
    directions = Counter(item.target.direction for item in decisions)
    instrument_kinds = Counter(item.instrument.kind for item in decisions)
    decision_times = [item.decision_time for item in decisions]
    return {
        "count": len(decisions),
        "by_symbol": dict(sorted(symbols.items())),
        "by_direction": dict(sorted(directions.items())),
        "by_instrument_kind": dict(sorted(instrument_kinds.items())),
        "min_decision_time": _iso_or_none(min(decision_times) if decision_times else None),
        "max_decision_time": _iso_or_none(max(decision_times) if decision_times else None),
    }


def _signal_summary(signals: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    symbols = Counter(str(item.get("symbol", "")) for item in signals)
    sides = Counter(str(item.get("side", "")) for item in signals)
    return {
        "count": len(signals),
        "by_symbol": dict(sorted(symbols.items())),
        "by_side": dict(sorted(sides.items())),
    }


def row_ranges_by_symbol(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    by_symbol: dict[str, dict[str, Any]] = {}
    for row in rows:
        symbol = str(row.get("symbol", ""))
        timestamp = row.get("timestamp")
        summary = by_symbol.setdefault(
            symbol,
            {"count": 0, "min_timestamp": None, "max_timestamp": None},
        )
        summary["count"] += 1
        if timestamp is None:
            continue
        if summary["min_timestamp"] is None or timestamp < summary["min_timestamp"]:
            summary["min_timestamp"] = timestamp
        if summary["max_timestamp"] is None or timestamp > summary["max_timestamp"]:
            summary["max_timestamp"] = timestamp

    for summary in by_symbol.values():
        summary["min_timestamp"] = json_safe_value(summary["min_timestamp"])
        summary["max_timestamp"] = json_safe_value(summary["max_timestamp"])
    return dict(sorted(by_symbol.items()))


def _iso_or_none(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def json_safe_value(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): json_safe_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [json_safe_value(item) for item in value]
    return value
```

- [ ] **Step 4: Run helper tests**

Run:

```bash
conda run -n quant pytest tests/test_runner_artifact_profiles.py -q
```

Expected: all helper tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/quant_strategies/runner/artifact_profiles.py tests/test_runner_artifact_profiles.py
git commit -m "feat: add summary artifact profile helpers"
```

## Task 3: Wire Summary Profile Into Runner Artifacts

**Files:**
- Modify: `src/quant_strategies/runner/artifacts.py`
- Modify: `src/quant_strategies/runner/__init__.py`
- Modify: `tests/test_runner_api_cli.py`

- [ ] **Step 1: Add failing end-to-end runner tests**

In `tests/test_runner_api_cli.py`, update `SUMMARY_KEYS` to include `artifact_profile`:

```python
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
    "artifact_profile",
    "evidence_class",
    "strategy_contract",
    "return_model",
    "funding_model",
    "promotion_eligible",
    "paper_trade_eligible",
    "live_eligible",
    "requires_manual_approval",
}
```

Update the helper signature and config writer in the same file:

```python
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
    artifact_profile: str = "full",
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
artifact_profile = "{artifact_profile}"
'''.lstrip()
    )
    return config_path
```

Update `assert_assessment(...)`:

```python
def assert_assessment(
    result: RunResult,
    summary: dict[str, object],
    *,
    assessment_status: str,
    run_completed: bool = True,
    promotion_eligible: bool = False,
    artifact_profile: str = "full",
) -> None:
    assert result.run_completed is run_completed
    assert result.assessment_status == assessment_status
    assert result.promotion_eligible is promotion_eligible
    assert summary["run_completed"] is run_completed
    assert summary["assessment_status"] == assessment_status
    assert summary["artifact_profile"] == artifact_profile
    assert summary["evidence_class"] == "runner_smoke"
    assert summary["strategy_contract"] == "decision"
    assert summary["return_model"] == "sum_weighted_trade_return"
    assert summary["funding_model"] == "none"
    assert summary["promotion_eligible"] is promotion_eligible
    assert summary["paper_trade_eligible"] is False
    assert summary["live_eligible"] is False
    assert summary["requires_manual_approval"] is True
```

Append this test:

```python
def test_run_config_summary_profile_writes_compact_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    write_strategy(tmp_path)
    config_path = write_config(tmp_path, artifact_profile="summary")
    monkeypatch.setattr(
        data_loader,
        "load_data",
        lambda config: LoadedData(rows=rows(100.0, 101.0, 102.0, 104.0, 105.0, 106.0)),
    )

    result = run_config(config_path, repo_root=tmp_path)

    assert result.success is True
    assert result.result_dir is not None
    names = {path.name for path in result.result_dir.iterdir() if path.is_file()}
    assert names == {
        "config.toml",
        "strategy_snapshot.py",
        "data_manifest.json",
        "artifact_profile_summary.json",
        "run_manifest.json",
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
    assert_assessment(result, summary, assessment_status="smoke_passed", artifact_profile="summary")

    profile = json.loads((result.result_dir / "artifact_profile_summary.json").read_text())
    assert profile["artifact_profile"] == "summary"
    assert profile["rows"]["row_count"] == 6
    assert profile["rows"]["sample_count"] == 5
    assert profile["decisions"]["count"] == 1
    assert profile["signals"]["count"] == 1
    assert profile["engine"]["passed"] is True
    assert profile["engine"]["trade_count"] == 1
    assert profile["engine"]["gross_return"] is not None
    assert profile["engine"]["cost_return"] is not None
    assert profile["engine"]["net_return"] is not None

    data_manifest = json.loads((result.result_dir / "data_manifest.json").read_text())
    assert data_manifest["artifact_profile"] == "summary"
    assert data_manifest["strategy_input_rows_jsonl_sha256"] is None
    assert len(data_manifest["normalized_rows_sha256"]) == 64

    run_manifest = json.loads((result.result_dir / "run_manifest.json").read_text())
    assert run_manifest["artifact_profile"] == "summary"
    assert "artifact_profile_summary.json" in run_manifest["artifacts"]
    assert "engine_request.json" not in run_manifest["artifacts"]
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
conda run -n quant pytest tests/test_runner_api_cli.py::test_run_config_summary_profile_writes_compact_artifacts -q
```

Expected: fail because runner still writes full artifacts and summary keys do not include `artifact_profile`.

- [ ] **Step 3: Modify artifact writers**

In `src/quant_strategies/runner/artifacts.py`, import the shared artifact helpers:

```python
from quant_strategies.runner.artifact_profiles import json_safe_value, row_ranges_by_symbol
```

Change `write_strategy_input_rows(...)` to return the raw input JSONL hash:

```python
def write_strategy_input_rows(result_dir: Path, rows: list[dict[str, Any]]) -> str:
    preferred_fields = [
        "symbol",
        "timestamp",
        "available_at",
        "open",
        "high",
        "low",
        "close",
        "bid",
        "ask",
        "mid",
        "funding_timestamp",
        "funding_rate",
        "bar_ingested_at",
        "quote_ingested_at",
        "funding_ingested_at",
        "joined_refreshed_at",
        "has_funding_event",
    ]
    write_csv(result_dir / "strategy_input_rows.csv", rows, preferred_fields=preferred_fields)
    jsonl_path = result_dir / "strategy_input_rows.jsonl"
    write_jsonl(jsonl_path, rows)
    return _file_sha256(jsonl_path)
```

Change `write_data_manifest(...)`:

```python
def write_data_manifest(
    result_dir: Path,
    config: RunConfig,
    rows: list[dict[str, Any]],
    *,
    strategy_input_rows_jsonl_sha256: str | None,
    normalized_rows_hash: str,
) -> None:
    payload = {
        "artifact_profile": config.output.artifact_profile,
        "data": {
            "kind": config.data.kind,
            "dataset": config.data.dataset,
            "symbols": list(config.data.symbols),
            "start": config.data.start.isoformat(),
            "end": config.data.end.isoformat(),
            "strict": config.data.strict,
        },
        "rows": {
            "total": len(rows),
            "by_symbol": row_ranges_by_symbol(rows),
        },
        "strategy_input_rows_jsonl_sha256": strategy_input_rows_jsonl_sha256,
        "normalized_rows_sha256": normalized_rows_hash,
        "metadata_field_coverage": _metadata_field_coverage(rows),
    }
    _write_json(result_dir / "data_manifest.json", payload)
```

After this change, replace internal calls to `_json_value(...)` in `artifacts.py` with `json_safe_value(...)`, then delete `_json_value(...)` and `_row_ranges_by_symbol(...)` from `artifacts.py`.

Change `write_run_manifest(...)`:

```python
def write_run_manifest(
    result_dir: Path,
    *,
    repo_root: Path,
    evidence: dict[str, object],
    artifact_profile: str,
) -> None:
    payload = {
        "repository": _git_identity(repo_root, result_dir),
        "python": python_identity(),
        "packages": _package_versions(["quant-strategies", "quant-data", "pydantic"]),
        "engine": {"evidence_schema": EVIDENCE_SCHEMA_VERSION},
        "artifact_profile": artifact_profile,
        "evidence": evidence,
        "artifacts": _artifact_hashes(result_dir),
    }
    _write_json(result_dir / "run_manifest.json", payload)
```

- [ ] **Step 4: Modify runner orchestration**

In `src/quant_strategies/runner/__init__.py`, add the import:

```python
from quant_strategies.runner.artifact_profiles import normalized_rows_sha256, write_summary_profile_artifact
```

Replace the data-load artifact block:

```python
    try:
        loaded = data_loader.load_data(config)
        normalized_rows_hash = normalized_rows_sha256(loaded.rows)
        strategy_input_rows_jsonl_sha256 = None
        if config.output.artifact_profile == "full":
            strategy_input_rows_jsonl_sha256 = artifacts.write_strategy_input_rows(result_dir, loaded.rows)
        artifacts.write_data_manifest(
            result_dir,
            config,
            loaded.rows,
            strategy_input_rows_jsonl_sha256=strategy_input_rows_jsonl_sha256,
            normalized_rows_hash=normalized_rows_hash,
        )
    except RunnerError as exc:
        return _failure_result(config, result_dir, "data_load", str(exc), repo_root=effective_repo_root)
```

Replace the decision artifact writes:

```python
        decision_output = generate_decisions(frozen_rows(loaded.rows), frozen_params(validated_params))
        decisions = _validated_decisions(decision_output, strategy_id=config.strategy_id)
        signals = decisions_to_signal_rows(decisions)
        if config.output.artifact_profile == "full":
            artifacts.write_decision_records(result_dir, decisions)
            artifacts.write_signals(result_dir, signals)
```

Replace the engine request artifact write:

```python
        request = engine_runner.build_request(
            strategy_id=config.strategy_id,
            rows=loaded.rows,
            signals=signals,
            fill_model=config.fill_model,
            cost_model=config.cost_model,
        )
        if config.output.artifact_profile == "full":
            artifacts.write_engine_request(result_dir, engine_runner.request_json(request))
```

Replace the evidence and manifest block:

```python
    engine_summary = _compact_engine_summary(engine_run)
    if config.output.artifact_profile == "full" and engine_run.evidence_json:
        artifacts.write_evidence(result_dir, engine_run.evidence_json)
    if config.output.artifact_profile == "summary":
        write_summary_profile_artifact(
            result_dir,
            config=config,
            rows=loaded.rows,
            decisions=decisions,
            signals=signals,
            engine=engine_summary,
            normalized_rows_hash=normalized_rows_hash,
        )
    notes = _completion_notes(config, engine_run)
    artifacts.write_notes(result_dir, notes)
    artifacts.write_run_manifest(
        result_dir,
        repo_root=effective_repo_root,
        evidence=runner_evidence_semantics(config.data.kind),
        artifact_profile=config.output.artifact_profile,
    )
```

Use `engine_summary` in the final summary payload:

```python
            engine=engine_summary,
```

Add `_compact_engine_summary(...)` near `_trade_count(...)`:

```python
def _compact_engine_summary(engine_run: engine_runner.EngineRun) -> dict[str, object]:
    source = engine_run.screen_summary
    if source is None and engine_run.validate_summary is not None:
        screening_result = engine_run.validate_summary.get("screening_result")
        source = screening_result if isinstance(screening_result, dict) else None

    summary: dict[str, object] = {"passed": engine_run.passed, "trade_count": _trade_count(engine_run)}
    for key in ("gross_return", "funding_return", "cost_return", "net_return"):
        summary[key] = source.get(key) if isinstance(source, dict) else None
    if engine_run.validate_summary is not None:
        gates = engine_run.validate_summary.get("gates")
        if isinstance(gates, list):
            summary["gates"] = [
                {"name": gate.get("name"), "passed": gate.get("passed"), "detail": gate.get("detail")}
                for gate in gates
                if isinstance(gate, dict)
            ]
    return summary
```

Update `_failure_result(...)` to pass the profile:

```python
    artifacts.write_run_manifest(
        result_dir,
        repo_root=repo_root,
        evidence=runner_evidence_semantics(config.data.kind),
        artifact_profile=config.output.artifact_profile,
    )
```

Update `_summary_payload(...)`:

```python
        "artifact_profile": config.output.artifact_profile,
```

- [ ] **Step 5: Run runner API tests**

Run:

```bash
conda run -n quant pytest tests/test_runner_api_cli.py -q
```

Expected: all runner API tests pass.

- [ ] **Step 6: Run related artifact tests**

Run:

```bash
conda run -n quant pytest tests/test_runner_artifact_profiles.py tests/test_runner_config.py tests/test_runner_api_cli.py -q
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/quant_strategies/runner/artifacts.py src/quant_strategies/runner/__init__.py tests/test_runner_api_cli.py
git commit -m "feat: support summary runner artifacts"
```

## Task 4: Pre-Index Engine Evaluation Bars And Funding Events

**Files:**
- Modify: `src/quant_strategies/engine/evaluation.py`
- Modify: `tests/test_engine_screen.py`

- [ ] **Step 1: Add failing engine index tests**

Append these tests to `tests/test_engine_screen.py`:

```python
def test_index_bars_builds_positions_and_funding_event_subset():
    from quant_strategies.engine.evaluation import _index_bars

    indexed = _index_bars(
        funding_bars_for("BTC-PERP")
        + bars_for("ETH-PERP", [100.0, 101.0, 102.0], start=DECISION)
    )

    assert indexed.positions_by_symbol["BTC-PERP"][DECISION] == 0
    assert indexed.positions_by_symbol["ETH-PERP"][DECISION] == 0
    assert indexed.has_funding_events is True
    assert [bar.funding_rate for bar in indexed.funding_events_by_symbol["BTC-PERP"]] == [0.05, 0.001]
    assert indexed.funding_events_by_symbol["ETH-PERP"] == ()


def test_index_bars_rejects_duplicate_symbol_timestamp():
    from quant_strategies.engine.evaluation import _index_bars

    duplicate = (
        Bar(symbol="BTC", timestamp=DECISION, open=100.0, high=100.0, low=100.0, close=100.0),
        Bar(symbol="BTC", timestamp=DECISION, open=101.0, high=101.0, low=101.0, close=101.0),
    )

    with pytest.raises(EvaluationError, match="duplicate bar timestamp"):
        _index_bars(duplicate)
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
conda run -n quant pytest tests/test_engine_screen.py::test_index_bars_builds_positions_and_funding_event_subset tests/test_engine_screen.py::test_index_bars_rejects_duplicate_symbol_timestamp -q
```

Expected: fail because `_index_bars` does not exist.

- [ ] **Step 3: Add indexed bar structures**

In `src/quant_strategies/engine/evaluation.py`, add this dataclass after `_ExitSelection`:

```python
@dataclass(frozen=True)
class _IndexedBars:
    bars_by_symbol: dict[str, tuple[Bar, ...]]
    positions_by_symbol: dict[str, dict[datetime, int]]
    funding_events_by_symbol: dict[str, tuple[Bar, ...]]
    has_funding_events: bool
```

Replace `_bars_by_symbol(...)` with `_index_bars(...)`:

```python
def _index_bars(bars: tuple[Bar, ...]) -> _IndexedBars:
    grouped: dict[str, list[Bar]] = defaultdict(list)
    for bar in bars:
        grouped[bar.symbol].append(bar)

    bars_by_symbol: dict[str, tuple[Bar, ...]] = {}
    positions_by_symbol: dict[str, dict[datetime, int]] = {}
    funding_events_by_symbol: dict[str, tuple[Bar, ...]] = {}
    has_funding_events = False

    for symbol, symbol_bars in grouped.items():
        ordered = sorted(symbol_bars, key=lambda bar: bar.timestamp)
        positions: dict[datetime, int] = {}
        funding_events: list[Bar] = []
        for index, bar in enumerate(ordered):
            if bar.timestamp in positions:
                raise EvaluationError(f"duplicate bar timestamp for {symbol}: {bar.timestamp.isoformat()}")
            positions[bar.timestamp] = index
            if bar.has_funding_event:
                funding_events.append(bar)
                has_funding_events = True
        bars_by_symbol[symbol] = tuple(ordered)
        positions_by_symbol[symbol] = positions
        funding_events_by_symbol[symbol] = tuple(funding_events)

    return _IndexedBars(
        bars_by_symbol=bars_by_symbol,
        positions_by_symbol=positions_by_symbol,
        funding_events_by_symbol=funding_events_by_symbol,
        has_funding_events=has_funding_events,
    )
```

Replace `screen(...)` with the indexed version:

```python
def screen(request: EvaluationRequest) -> ScreeningResult:
    indexed = _index_bars(request.bars)
    if not indexed.bars_by_symbol:
        raise EvaluationError("bars are required")

    trades: list[Trade] = []
    for signal in request.spec.signals:
        symbol_bars = indexed.bars_by_symbol.get(signal.symbol)
        if not symbol_bars:
            raise EvaluationError(f"missing bars for signal symbol: {signal.symbol}")
        decision_index = _decision_index(indexed, signal.symbol, signal.decision_time)
        entry_index = decision_index + request.fill_model.entry_lag_bars
        if entry_index >= len(symbol_bars):
            raise EvaluationError(f"entry fill is outside available bars: {signal.symbol}")

        entry_bar = symbol_bars[entry_index]
        entry_price = _fill_price(entry_bar, request.fill_model.price, signal.side, is_entry=True)
        exit_selection = _select_exit(
            symbol_bars,
            signal,
            entry_index,
            entry_price,
            request.fill_model,
        )
        exit_bar = exit_selection.exit_bar
        exit_price = _fill_price(exit_bar, request.fill_model.price, signal.side, is_entry=False)
        direction = 1.0 if signal.side is Side.LONG else -1.0
        gross_return = direction * ((exit_price - entry_price) / entry_price) * signal.weight
        funding_return = _funding_return(
            indexed,
            signal.symbol,
            entry_bar.timestamp,
            exit_bar.timestamp,
            signal.side,
            signal.weight,
        )
        cost_return = (request.cost_model.round_trip_bps / 10_000.0) * signal.weight
        net_return = gross_return + funding_return - cost_return
        trades.append(
            Trade(
                symbol=signal.symbol,
                side=signal.side,
                decision_time=signal.decision_time,
                entry_time=entry_bar.timestamp,
                exit_time=exit_bar.timestamp,
                entry_price=entry_price,
                exit_price=exit_price,
                exit_reason=exit_selection.reason,
                weight=signal.weight,
                gross_return=gross_return,
                funding_return=funding_return,
                cost_return=cost_return,
                net_return=net_return,
                signal_metadata=signal.metadata,
            )
        )

    gross_total = sum(trade.gross_return for trade in trades)
    funding_total = sum(trade.funding_return for trade in trades)
    cost_total = sum(trade.cost_return for trade in trades)
    net_total = sum(trade.net_return for trade in trades)
    return ScreeningResult(
        strategy_id=request.spec.strategy_id,
        trade_count=len(trades),
        gross_return=gross_total,
        funding_return=funding_total,
        net_return=net_total,
        cost_return=cost_total,
        trades=tuple(trades),
    )
```

Replace `_decision_index(...)`:

```python
def _decision_index(indexed: _IndexedBars, symbol: str, decision_time: datetime) -> int:
    position = indexed.positions_by_symbol.get(symbol, {}).get(decision_time)
    if position is None:
        raise EvaluationError(f"decision_time does not match a bar timestamp: {decision_time.isoformat()}")
    return position
```

Replace `_funding_return(...)`:

```python
def _funding_return(
    indexed: _IndexedBars,
    symbol: str,
    entry_time: datetime,
    exit_time: datetime,
    side: Side,
    weight: float,
) -> float:
    if not indexed.has_funding_events:
        return 0.0

    rates_by_timestamp: dict[datetime, float] = {}
    for bar in indexed.funding_events_by_symbol.get(symbol, ()):
        if bar.funding_timestamp is None or bar.funding_rate is None:
            raise EvaluationError(f"incomplete funding event: {bar.symbol} at {bar.timestamp.isoformat()}")
        if not entry_time < bar.funding_timestamp <= exit_time:
            continue
        existing = rates_by_timestamp.get(bar.funding_timestamp)
        if existing is not None and not math.isclose(existing, bar.funding_rate, rel_tol=0.0, abs_tol=1e-15):
            raise EvaluationError(f"conflicting funding rates at {bar.funding_timestamp.isoformat()}")
        rates_by_timestamp[bar.funding_timestamp] = bar.funding_rate

    direction = 1.0 if side is Side.LONG else -1.0
    return sum(-direction * rate for rate in rates_by_timestamp.values()) * weight
```

- [ ] **Step 4: Run engine tests**

Run:

```bash
conda run -n quant pytest tests/test_engine_screen.py tests/test_engine_validate_and_evidence.py -q
```

Expected: all selected engine tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/quant_strategies/engine/evaluation.py tests/test_engine_screen.py
git commit -m "perf: index bars during engine evaluation"
```

## Task 5: Pre-Index Runner Fillability Checks

**Files:**
- Modify: `src/quant_strategies/runner/engine_runner.py`
- Modify: `tests/test_runner_engine_runner.py`

- [ ] **Step 1: Add failing runner index tests**

Append these tests to `tests/test_runner_engine_runner.py`:

```python
def test_runner_bar_index_builds_positions_by_symbol():
    from quant_strategies.runner.engine_runner import _build_bar_index

    request = build_request(
        strategy_id="demo",
        rows=bars(100.0, 101.0, 102.0, 104.0),
        signals=[signal()],
        fill_model=close_fill(),
        cost_model=zero_cost(),
    )

    indexed = _build_bar_index(request.bars)

    assert indexed.positions_by_symbol["SPY"][request.bars[0].timestamp] == 0
    assert indexed.positions_by_symbol["SPY"][request.bars[1].timestamp] == 1


def test_runner_bar_index_rejects_duplicate_symbol_timestamp():
    from quant_strategies.runner.engine_runner import _build_bar_index

    request = build_request(
        strategy_id="demo",
        rows=bars(100.0, 101.0, 102.0, 104.0),
        signals=[signal()],
        fill_model=close_fill(),
        cost_model=zero_cost(),
    )
    duplicate_bars = request.bars + (request.bars[0],)

    with pytest.raises(RequestBuildError, match="duplicate bar timestamp"):
        _build_bar_index(duplicate_bars)
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
conda run -n quant pytest tests/test_runner_engine_runner.py::test_runner_bar_index_builds_positions_by_symbol tests/test_runner_engine_runner.py::test_runner_bar_index_rejects_duplicate_symbol_timestamp -q
```

Expected: fail because `_build_bar_index` does not exist.

- [ ] **Step 3: Add runner bar index**

In `src/quant_strategies/runner/engine_runner.py`, update imports:

```python
from dataclasses import dataclass
from datetime import datetime
```

Add this dataclass after `EngineRun`:

```python
@dataclass(frozen=True)
class _BarIndex:
    bars_by_symbol: dict[str, tuple[Bar, ...]]
    positions_by_symbol: dict[str, dict[datetime, int]]
```

Replace `_assert_fillable(...)` and `_decision_index(...)` with:

```python
def _assert_fillable(request: EvaluationRequest) -> None:
    indexed = _build_bar_index(request.bars)

    for signal in request.spec.signals:
        symbol_bars = indexed.bars_by_symbol.get(signal.symbol)
        if not symbol_bars:
            raise RequestBuildError(f"missing bars for signal symbol: {signal.symbol}")
        decision_index = _decision_index(indexed, signal)
        entry_index = decision_index + request.fill_model.entry_lag_bars
        max_hold_bars = signal.max_hold_bars or signal.hold_bars
        last_trigger_index = entry_index + max_hold_bars
        last_exit_index = last_trigger_index + request.fill_model.exit_lag_bars
        if entry_index >= len(symbol_bars):
            raise RequestBuildError(f"entry fill is outside available bars: {signal.symbol}")
        if last_exit_index >= len(symbol_bars):
            raise RequestBuildError(f"exit fill is outside available bars: {signal.symbol}")
        if request.fill_model.price == "quote":
            _assert_quote_fill_bar(symbol_bars[entry_index], "entry")
            for trigger_index in range(entry_index + 1, last_trigger_index + 1):
                _assert_quote_fill_bar(symbol_bars[trigger_index], "trigger")
                exit_index = trigger_index + request.fill_model.exit_lag_bars
                _assert_quote_fill_bar(symbol_bars[exit_index], "exit")


def _build_bar_index(bars: tuple[Bar, ...]) -> _BarIndex:
    grouped: dict[str, list[Bar]] = {}
    for bar in bars:
        grouped.setdefault(bar.symbol, []).append(bar)

    bars_by_symbol: dict[str, tuple[Bar, ...]] = {}
    positions_by_symbol: dict[str, dict[datetime, int]] = {}
    for symbol, symbol_bars in grouped.items():
        ordered = sorted(symbol_bars, key=lambda bar: bar.timestamp)
        positions: dict[datetime, int] = {}
        for index, bar in enumerate(ordered):
            if bar.timestamp in positions:
                raise RequestBuildError(f"duplicate bar timestamp for {symbol}: {bar.timestamp.isoformat()}")
            positions[bar.timestamp] = index
        bars_by_symbol[symbol] = tuple(ordered)
        positions_by_symbol[symbol] = positions
    return _BarIndex(bars_by_symbol=bars_by_symbol, positions_by_symbol=positions_by_symbol)


def _decision_index(indexed: _BarIndex, signal: Signal) -> int:
    position = indexed.positions_by_symbol.get(signal.symbol, {}).get(signal.decision_time)
    if position is None:
        raise RequestBuildError(f"decision_time does not match a bar timestamp: {signal.decision_time.isoformat()}")
    return position
```

- [ ] **Step 4: Run runner engine tests**

Run:

```bash
conda run -n quant pytest tests/test_runner_engine_runner.py -q
```

Expected: all runner engine tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/quant_strategies/runner/engine_runner.py tests/test_runner_engine_runner.py
git commit -m "perf: index bars for runner fillability"
```

## Task 6: Add Phase 5 Performance And Artifact Budgets

**Files:**
- Create: `tests/test_phase5_performance.py`

- [ ] **Step 1: Create failing performance tests**

Create `tests/test_phase5_performance.py` with this content:

```python
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from quant_strategies.engine import Bar, EvaluationRequest, FillModel, Side, Signal, StrategySpec, screen
from quant_strategies.runner import data_loader, run_config
from quant_strategies.runner.data_loader import LoadedData


def large_engine_request(
    *,
    symbol_count: int = 80,
    bars_per_symbol: int = 2_000,
    signals_per_symbol: int = 100,
) -> EvaluationRequest:
    start = datetime(2024, 1, 1, 9, 30, tzinfo=timezone.utc)
    bars: list[Bar] = []
    signals: list[Signal] = []
    for symbol_index in range(symbol_count):
        symbol = f"SYM{symbol_index:03d}"
        for bar_index in range(bars_per_symbol):
            timestamp = start + timedelta(minutes=bar_index)
            close = 100.0 + symbol_index + (bar_index * 0.01)
            bars.append(
                Bar(
                    symbol=symbol,
                    timestamp=timestamp,
                    open=close,
                    high=close,
                    low=close,
                    close=close,
                )
            )
        first_decision_bar_index = bars_per_symbol - signals_per_symbol - 5
        for signal_index in range(signals_per_symbol):
            decision_bar_index = first_decision_bar_index + signal_index
            signals.append(
                Signal(
                    symbol=symbol,
                    decision_time=start + timedelta(minutes=decision_bar_index),
                    side=Side.LONG if signal_index % 2 == 0 else Side.SHORT,
                    hold_bars=2,
                )
            )
    return EvaluationRequest(
        spec=StrategySpec(strategy_id="phase5_perf", signals=tuple(signals)),
        bars=tuple(bars),
        fill_model=FillModel(price="close", entry_lag_bars=1),
    )


def strategy_source() -> str:
    return (
        "from quant_strategies.decisions import ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision\n"
        "def generate_decisions(rows, params):\n"
        "    decisions = []\n"
        "    symbols = []\n"
        "    for row in rows:\n"
        "        symbol = row['symbol']\n"
        "        if symbol not in symbols:\n"
        "            symbols.append(symbol)\n"
        "    for symbol in symbols[:5]:\n"
        "        symbol_rows = [row for row in rows if row['symbol'] == symbol]\n"
        "        timestamp = symbol_rows[1]['timestamp']\n"
        "        decisions.append(StrategyDecision(\n"
        "            strategy_id='phase5_summary',\n"
        "            instrument=InstrumentRef(kind='equity_or_etf', symbol=symbol),\n"
        "            decision_time=timestamp,\n"
        "            as_of_time=timestamp,\n"
        "            target=PositionTarget(direction='long', sizing_kind='target_weight', size=0.1),\n"
        "            exit_policy=ExitPolicy(max_hold_bars=2),\n"
        "        ))\n"
        "    return decisions\n"
    )


def runner_config(tmp_path: Path) -> Path:
    strategy = tmp_path / "tested" / "phase5_summary.py"
    strategy.parent.mkdir(parents=True)
    strategy.write_text(strategy_source())
    config_path = tmp_path / "run.toml"
    config_path.write_text(
        '''
strategy_path = "tested/phase5_summary.py"
strategy_id = "phase5_summary"

[data]
kind = "bars"
dataset = "synthetic"
symbols = ["SYM000", "SYM001", "SYM002", "SYM003", "SYM004"]
start = "2024-01-01"
end = "2024-01-05"
strict = true

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
mode = "screen"
artifact_profile = "summary"
'''.lstrip()
    )
    return config_path


def runner_rows(symbol_count: int = 5, bars_per_symbol: int = 400) -> list[dict[str, object]]:
    start = datetime(2024, 1, 1, 9, 30, tzinfo=timezone.utc)
    rows: list[dict[str, object]] = []
    for symbol_index in range(symbol_count):
        symbol = f"SYM{symbol_index:03d}"
        for bar_index in range(bars_per_symbol):
            timestamp = start + timedelta(minutes=bar_index)
            close = 100.0 + symbol_index + (bar_index * 0.01)
            rows.append(
                {
                    "symbol": symbol,
                    "timestamp": timestamp,
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                }
            )
    return rows


def artifact_bytes(result_dir: Path) -> int:
    return sum(path.stat().st_size for path in result_dir.rglob("*") if path.is_file())


def test_large_engine_screen_completes_under_runtime_budget():
    request = large_engine_request()

    start = time.perf_counter()
    result = screen(request)
    elapsed = time.perf_counter() - start

    assert result.trade_count == 8_000
    assert elapsed < 0.50


def test_summary_profile_artifacts_stay_under_byte_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    config_path = runner_config(tmp_path)
    monkeypatch.setattr(data_loader, "load_data", lambda config: LoadedData(rows=runner_rows()))

    result = run_config(config_path, repo_root=tmp_path)

    assert result.success is True
    assert result.result_dir is not None
    assert artifact_bytes(result.result_dir) < 75_000
    profile = json.loads((result.result_dir / "artifact_profile_summary.json").read_text())
    assert profile["rows"]["row_count"] == 2_000
    assert profile["decisions"]["count"] == 5
    assert not (result.result_dir / "strategy_input_rows.jsonl").exists()
    assert not (result.result_dir / "engine_request.json").exists()
    assert not (result.result_dir / "evidence.json").exists()
```

- [ ] **Step 2: Run performance tests**

Run:

```bash
conda run -n quant pytest tests/test_phase5_performance.py -q
```

Expected before Tasks 3-5 are complete: summary artifact budget test fails because summary mode is not wired, and the late-decision runtime benchmark should exceed the budget on the repeated-scan path. Expected after Tasks 3-5: both tests pass.

- [ ] **Step 3: Run the benchmark twice**

Run:

```bash
conda run -n quant pytest tests/test_phase5_performance.py -q
conda run -n quant pytest tests/test_phase5_performance.py -q
```

Expected: both runs pass. If the runtime test is close to 0.50 seconds twice, inspect the implementation for accidental repeated scans before changing the threshold.

- [ ] **Step 4: Commit**

```bash
git add tests/test_phase5_performance.py
git commit -m "test: add phase 5 performance budgets"
```

## Task 7: Update Docs And Run Final Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-05-26-foundation-repair-design.md`

- [ ] **Step 1: Update README config documentation**

In `README.md`, update the `[output]` config example:

```toml
[output]
results_dir = "results"
mode = "validate"
# Optional. Use "summary" for broad quick research loops.
artifact_profile = "full"
```

- [ ] **Step 2: Add artifact profile explanation to README**

In the `Artifacts` section of `README.md`, add this paragraph after the existing runner artifact semantics paragraph:

```markdown
Runner artifact profiles control artifact size, not strategy or engine semantics.
`artifact_profile = "full"` writes raw strategy input CSV/JSONL, decision
records, internal signal CSV, engine request JSON, and engine evidence JSON.
`artifact_profile = "summary"` is for broad quick-research loops: it writes
`artifact_profile_summary.json` with row counts, normalized row hash, sampled
rows, decision summary, signal summary, and engine summary, but it omits the
full row files, full decision records, internal signal CSV, full engine request,
and full evidence packet.
The summary engine payload remains scoreable: it includes trade count, pass
status, gross return, funding return, cost return, net return, and validation
gate summaries when validation mode is used.
```

- [ ] **Step 3: Update Phase 5 spec notes**

In `docs/superpowers/specs/2026-05-26-foundation-repair-design.md`, fix the typo in the Phase 5 bullet:

```markdown
  - row counts
```

Add this line to the Phase 5 design bullets:

```markdown
- `artifact_profile = "full"` remains the default for manual reruns and curated candidates.
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
conda run -n quant pytest tests/test_runner_config.py tests/test_runner_artifact_profiles.py tests/test_runner_api_cli.py tests/test_runner_engine_runner.py tests/test_engine_screen.py tests/test_engine_validate_and_evidence.py tests/test_phase5_performance.py -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Run full suite**

Run:

```bash
conda run -n quant pytest -q
```

Expected: all tests pass.

- [ ] **Step 6: Check staged diff hygiene**

Run:

```bash
git diff --check
```

Expected: no output.

- [ ] **Step 7: Commit docs**

```bash
git add README.md docs/superpowers/specs/2026-05-26-foundation-repair-design.md
git commit -m "docs: document phase 5 artifact profiles"
```

## Engineering Review Test Diagram

```text
CODE PATHS                                           TEST COVERAGE
[+] runner config artifact_profile                   [***] default/summary/invalid config tests
[+] artifact profile helpers                         [***] hash determinism, payload shape, writer output
  |-- json_safe_value shared by artifacts.py          [***] covered through manifest/profile JSON assertions
  |-- row_ranges_by_symbol shared by manifests        [***] covered through data_manifest/profile assertions
[+] run_config summary profile                       [***] compact artifact set and omitted full files
  |-- full mode remains default                       [***] existing full artifact tests plus profile field update
  |-- failure summary/manifests                       [** ] existing failure tests updated for artifact_profile
  |-- compact engine metrics                          [***] summary profile asserts gross/funding/cost/net fields
[+] runner fillability bar index                      [***] index shape, duplicate timestamp, fillability regressions
[+] engine evaluation bar index                       [***] index shape, duplicate timestamp, output equivalence
[+] funding-event index                               [***] no-event fast return, incomplete/conflicting events
[+] phase5 performance budgets                        [***] late-decision runtime budget, summary byte budget

COVERAGE TARGET: all changed branches covered by focused unit/integration tests.
Legend: *** behavior + edge/error, ** happy path, * smoke.
```

## Failure Modes

- Summary mode silently drops scoreable results: covered by compact engine metric assertions and by preserving full artifacts in `artifact_profile = "full"`.
- Summary and manifest row hashes drift: covered by computing one `normalized_rows_hash` and asserting the same value appears where expected.
- Duplicate `(symbol, timestamp)` bars change behavior after indexing: covered by duplicate-timestamp rejection tests in runner and engine indexes.
- Funding rows with incomplete or conflicting event data become hidden by the new index: covered by keeping existing funding error semantics and adding indexed funding tests.
- Timing benchmark becomes a no-op: covered by late-decision signals that exercise the current repeated scan path before indexing.

## Worktree Parallelization

| Step | Modules touched | Depends on |
|------|-----------------|------------|
| Artifact profile config/helpers | `runner/`, `tests/` | - |
| Runner summary orchestration | `runner/`, `tests/` | Artifact profile config/helpers |
| Engine indexing | `engine/`, `tests/` | - |
| Runner fillability indexing | `runner/`, `tests/` | - |
| Performance budgets/docs | `tests/`, docs | Runner summary orchestration + indexing |

Lane A: artifact profile config/helpers -> runner summary orchestration.

Lane B: engine indexing.

Lane C: runner fillability indexing.

Execution order: run Lane A, Lane B, and Lane C in parallel worktrees if desired; merge them, then add performance budgets and docs in the final lane.

Conflict flags: Lane A and Lane C both touch `runner/`, so run them sequentially if avoiding merge conflicts matters more than parallel speed.

## Implementation Tasks From Eng Review

Synthesized from `/plan-eng-review` findings. These are already reflected in the task details above.

- [ ] **T1 (P1, human: ~45min / CC: ~10min)** - Runner artifacts - Preserve compact scoreable engine metrics in summary mode.
  - Surfaced by: Architecture review - summary mode omitted `evidence.json` but only kept `passed` and `trade_count`.
  - Files: `src/quant_strategies/runner/__init__.py`, `src/quant_strategies/runner/artifact_profiles.py`, `tests/test_runner_api_cli.py`.
  - Verify: `conda run -n quant pytest tests/test_runner_api_cli.py::test_run_config_summary_profile_writes_compact_artifacts -q`.

- [ ] **T2 (P2, human: ~30min / CC: ~8min)** - Artifact helpers - Move duplicated JSON and row-range helpers into the new artifact profile helper module.
  - Surfaced by: Code quality review - planned helper code duplicated existing `artifacts.py` normalization and row summary behavior.
  - Files: `src/quant_strategies/runner/artifact_profiles.py`, `src/quant_strategies/runner/artifacts.py`, `tests/test_runner_artifact_profiles.py`.
  - Verify: `conda run -n quant pytest tests/test_runner_artifact_profiles.py tests/test_runner_api_cli.py -q`.

- [ ] **T3 (P1, human: ~30min / CC: ~8min)** - Performance tests - Replace the early-signal runtime smoke test with a late-decision benchmark.
  - Surfaced by: Test review - the draft benchmark passed on current code in about 0.009s and did not prove the index change.
  - Files: `tests/test_phase5_performance.py`.
  - Verify: `conda run -n quant pytest tests/test_phase5_performance.py -q`.

- [ ] **T4 (P2, human: ~20min / CC: ~5min)** - Summary profile performance - Compute normalized row hash once and pass it through.
  - Surfaced by: Performance review - both data manifest and summary artifact were normalizing and hashing the same row set.
  - Files: `src/quant_strategies/runner/__init__.py`, `src/quant_strategies/runner/artifacts.py`, `src/quant_strategies/runner/artifact_profiles.py`.
  - Verify: `conda run -n quant pytest tests/test_runner_artifact_profiles.py tests/test_runner_api_cli.py -q`.

## Final Review Checklist

- [ ] `output.artifact_profile` defaults to `"full"`, so existing run configs preserve full artifacts.
- [ ] Summary mode omits full row CSV/JSONL, decision JSONL, signal CSV, engine request JSON, and evidence JSON.
- [ ] Summary mode keeps compact scoreable engine metrics, including gross, funding, cost, and net returns.
- [ ] Normalized row hash is computed once per successful run and reused across summary/data artifacts.
- [ ] Summary mode still executes strategy generation, decision validation, readiness checks, request building, and engine evaluation.
- [ ] `run_manifest.json`, `summary.json`, and `data_manifest.json` record the artifact profile.
- [ ] Normalized row hash is deterministic for JSON-equivalent rows.
- [ ] Runner fillability checks use a timestamp index.
- [ ] Engine evaluation uses a timestamp index.
- [ ] Funding return scans only funding-event bars and returns immediately when no bars have funding events.
- [ ] Performance test covers runtime.
- [ ] Performance test covers artifact-byte budget.
- [ ] Full test suite passes with `conda run -n quant pytest -q`.

## Self-Review

Spec coverage:

- Bar indexing: Task 4 and Task 5.
- Reuse index for fillability and evaluation: Task 4 and Task 5.
- Skip/pre-index funding scans: Task 4.
- `artifact_profile = "summary"`: Task 1, Task 2, and Task 3.
- Full artifacts remain available: Task 1 default plus Task 3 full-mode preservation.
- Autoresearch-scale benchmark: Task 6.

Placeholder scan:

- No placeholder markers or undefined named functions are used in task steps.
- Each code-changing step includes concrete code blocks.

Type consistency:

- Config field name is consistently `artifact_profile`.
- Summary artifact filename is consistently `artifact_profile_summary.json`.
- Row hash field is consistently `normalized_rows_sha256`.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | - | Not run for this backend performance plan |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | - | Not run |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR | 4 issues found, 0 critical gaps; all accepted into this plan |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | - | Not applicable: no UI scope |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | - | Not run |

- **UNRESOLVED:** 0 decisions.
- **VERDICT:** ENG CLEARED - ready to implement Phase 5.
