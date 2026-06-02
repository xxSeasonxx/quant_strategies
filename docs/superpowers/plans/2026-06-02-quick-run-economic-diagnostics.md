# Quick-Run Economic Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add factual quick-run economic metric outputs to completed runner artifacts without adding ranking, policy, validation, or portfolio evaluation semantics.

**Architecture:** Keep the core engine contract unchanged and derive metrics in a small runner-owned helper from the completed in-memory engine trade ledger. `summary.json` gets compact `economic_metrics` for every completed quick run, while diagnostic-profile runs also get grouped `economic_slices` in `diagnostics.json`.

**Tech Stack:** Python 3.12, standard-library arithmetic, pytest, existing runner artifacts, markdown docs. Run Python commands through `conda run -n quant`.

---

## Scope Check

The approved spec covers one subsystem: quick-run runner artifacts. It does not require a new public CLI/API surface, validation changes, evaluation changes, VectorBT Pro integration, or `quant_autoresearch` behavior. This can be implemented as one focused plan.

## File Structure

- Create `src/quant_strategies/runner/economic_metrics.py`: pure helper functions for summary economic metrics and diagnostic economic slices.
- Create `tests/test_runner_economic_metrics.py`: arithmetic unit tests for the helper, including zero trades, winners, losers, mixed trades, zero gross, and signed funding shares.
- Modify `src/quant_strategies/runner/__init__.py`: keep complete in-memory trades available for completed quick runs, derive summary metrics before trimming compact artifacts, and pass metrics into `summary_payload`.
- Modify `src/quant_strategies/runner/artifacts.py`: accept optional completed-run `economic_metrics` in `summary_payload`.
- Modify `src/quant_strategies/runner/diagnostics.py`: attach diagnostic-only `economic_slices` while preserving existing diagnostic fields.
- Modify `tests/test_runner_api_cli.py`: assert completed quick-run summaries expose compact metrics and diagnostic-profile artifacts expose slices without leaking full trades into compact artifacts.
- Modify `README.md`, `PRD.md`, `TODOS.md`, `docs/foundation-surfaces.md`, `docs/runner.md`, and `docs/quant-autoresearch-consumer.md`: document the factual metric outputs and remove stale B planning language.

---

### Task 1: Add Economic Metrics Helper Tests

**Files:**
- Create: `tests/test_runner_economic_metrics.py`

- [ ] **Step 1: Write the failing helper tests**

Create `tests/test_runner_economic_metrics.py` with this content:

```python
from __future__ import annotations

import pytest

from quant_strategies.runner.economic_metrics import (
    diagnostic_slices,
    summary_metrics,
)


def trade(
    net_return: float,
    *,
    symbol: str = "SPY",
    side: str = "long",
    exit_reason: str = "max_hold",
) -> dict[str, object]:
    return {
        "symbol": symbol,
        "side": side,
        "exit_reason": exit_reason,
        "net_return": net_return,
    }


def trade_result(
    *,
    gross: float,
    funding: float = 0.0,
    cost: float = 0.0,
    net: float | None = None,
) -> dict[str, object]:
    return {
        "sum_signed_trade_activity_gross": gross,
        "sum_signed_trade_activity_funding": funding,
        "sum_signed_trade_activity_cost": cost,
        "sum_signed_trade_activity_net": gross + funding - cost if net is None else net,
    }


def test_summary_metrics_for_no_trades_emit_zero_counts_and_null_rates():
    metrics = summary_metrics([], trade_result(gross=0.0))

    assert metrics == {
        "schema_version": "quant_strategies.runner.economic_metrics/v1",
        "basis": "engine_trade_ledger",
        "trade_count": 0,
        "winning_trade_count": 0,
        "losing_trade_count": 0,
        "flat_trade_count": 0,
        "hit_rate": None,
        "average_trade_net": None,
        "average_win_net": None,
        "average_loss_net": None,
        "profit_factor": None,
        "cost_share_of_abs_gross": None,
        "funding_share_of_abs_gross": None,
    }


def test_summary_metrics_for_mixed_trades_and_signed_components():
    metrics = summary_metrics(
        [trade(0.03), trade(-0.01), trade(0.0)],
        trade_result(gross=0.10, funding=-0.005, cost=0.02, net=0.075),
    )

    assert metrics["trade_count"] == 3
    assert metrics["winning_trade_count"] == 1
    assert metrics["losing_trade_count"] == 1
    assert metrics["flat_trade_count"] == 1
    assert metrics["hit_rate"] == pytest.approx(1 / 3)
    assert metrics["average_trade_net"] == pytest.approx(0.02 / 3)
    assert metrics["average_win_net"] == pytest.approx(0.03)
    assert metrics["average_loss_net"] == pytest.approx(-0.01)
    assert metrics["profit_factor"] == pytest.approx(3.0)
    assert metrics["cost_share_of_abs_gross"] == pytest.approx(0.2)
    assert metrics["funding_share_of_abs_gross"] == pytest.approx(-0.05)


def test_summary_metrics_for_all_winners_do_not_emit_infinite_profit_factor():
    metrics = summary_metrics(
        [trade(0.01), trade(0.02)],
        trade_result(gross=0.03),
    )

    assert metrics["hit_rate"] == 1.0
    assert metrics["average_trade_net"] == pytest.approx(0.015)
    assert metrics["average_win_net"] == pytest.approx(0.015)
    assert metrics["average_loss_net"] is None
    assert metrics["profit_factor"] is None


def test_summary_metrics_for_all_losers_emit_zero_profit_factor():
    metrics = summary_metrics(
        [trade(-0.01), trade(-0.03)],
        trade_result(gross=-0.04),
    )

    assert metrics["hit_rate"] == 0.0
    assert metrics["average_trade_net"] == pytest.approx(-0.02)
    assert metrics["average_win_net"] is None
    assert metrics["average_loss_net"] == pytest.approx(-0.02)
    assert metrics["profit_factor"] == 0.0


def test_summary_metrics_null_cost_and_funding_shares_when_gross_is_zero():
    metrics = summary_metrics(
        [trade(0.01), trade(-0.01)],
        trade_result(gross=0.0, funding=0.004, cost=0.002, net=0.002),
    )

    assert metrics["cost_share_of_abs_gross"] is None
    assert metrics["funding_share_of_abs_gross"] is None


def test_diagnostic_slices_group_economic_summaries_and_distribution():
    slices = diagnostic_slices(
        [
            trade(0.03, symbol="SPY", side="long", exit_reason="max_hold"),
            trade(-0.01, symbol="SPY", side="short", exit_reason="stop_loss"),
            trade(0.0, symbol="QQQ", side="long", exit_reason="max_hold"),
        ]
    )

    assert slices["schema_version"] == "quant_strategies.runner.economic_slices/v1"
    assert slices["basis"] == "engine_trade_ledger"
    assert slices["by_symbol"]["SPY"]["count"] == 2
    assert slices["by_symbol"]["SPY"]["winning_trade_count"] == 1
    assert slices["by_symbol"]["SPY"]["losing_trade_count"] == 1
    assert slices["by_symbol"]["SPY"]["hit_rate"] == pytest.approx(0.5)
    assert slices["by_symbol"]["QQQ"]["flat_trade_count"] == 1
    assert slices["by_direction"]["long"]["count"] == 2
    assert slices["by_exit_reason"]["stop_loss"]["average_loss_net"] == pytest.approx(-0.01)
    assert slices["win_loss_distribution"] == {
        "largest_win_net": 0.03,
        "largest_loss_net": -0.01,
        "median_trade_net": 0.0,
        "sum_positive_net": 0.03,
        "sum_negative_net": -0.01,
    }
```

- [ ] **Step 2: Run the helper tests to verify they fail**

Run:

```bash
conda run -n quant pytest tests/test_runner_economic_metrics.py -q
```

Expected: FAIL during collection with `ModuleNotFoundError: No module named 'quant_strategies.runner.economic_metrics'`.

---

### Task 2: Implement Economic Metrics Helper

**Files:**
- Create: `src/quant_strategies/runner/economic_metrics.py`
- Test: `tests/test_runner_economic_metrics.py`

- [ ] **Step 1: Add the helper implementation**

Create `src/quant_strategies/runner/economic_metrics.py` with this content:

```python
from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from statistics import median
from typing import Any

from quant_strategies.core.serialization import json_safe_value


SUMMARY_SCHEMA_VERSION = "quant_strategies.runner.economic_metrics/v1"
SLICES_SCHEMA_VERSION = "quant_strategies.runner.economic_slices/v1"
BASIS = "engine_trade_ledger"


def summary_metrics(
    trades: Sequence[Mapping[str, Any]],
    trade_result: Mapping[str, Any],
) -> dict[str, Any]:
    nets = _net_values(trades)
    positive = [value for value in nets if value > 0.0]
    negative = [value for value in nets if value < 0.0]
    flat_count = sum(1 for value in nets if value == 0.0)
    trade_count = len(nets)
    gross = _optional_float(trade_result.get("sum_signed_trade_activity_gross"))
    cost = _optional_float(trade_result.get("sum_signed_trade_activity_cost"))
    funding = _optional_float(trade_result.get("sum_signed_trade_activity_funding"))

    return json_safe_value(
        {
            "schema_version": SUMMARY_SCHEMA_VERSION,
            "basis": BASIS,
            "trade_count": trade_count,
            "winning_trade_count": len(positive),
            "losing_trade_count": len(negative),
            "flat_trade_count": flat_count,
            "hit_rate": None if trade_count == 0 else len(positive) / trade_count,
            "average_trade_net": _mean(nets),
            "average_win_net": _mean(positive),
            "average_loss_net": _mean(negative),
            "profit_factor": _profit_factor(positive, negative),
            "cost_share_of_abs_gross": _share_of_abs_gross(cost, gross),
            "funding_share_of_abs_gross": _share_of_abs_gross(funding, gross),
        }
    )


def diagnostic_slices(trades: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    trade_rows = [dict(trade) for trade in trades]
    return json_safe_value(
        {
            "schema_version": SLICES_SCHEMA_VERSION,
            "basis": BASIS,
            "by_symbol": _group_summaries(trade_rows, "symbol"),
            "by_direction": _group_summaries(trade_rows, "side"),
            "by_exit_reason": _group_summaries(trade_rows, "exit_reason"),
            "win_loss_distribution": _win_loss_distribution(trade_rows),
        }
    )


def trades_from_engine_summary(engine: Mapping[str, Any]) -> list[dict[str, Any]]:
    trades = engine.get("diagnostic_trades")
    if not isinstance(trades, Sequence) or isinstance(trades, str | bytes):
        return []
    return [dict(item) for item in trades if isinstance(item, Mapping)]


def trade_result_from_engine_summary(engine: Mapping[str, Any]) -> dict[str, Any]:
    trade_result = engine.get("trade_result")
    return dict(trade_result) if isinstance(trade_result, Mapping) else {}


def _group_summaries(
    trades: Sequence[Mapping[str, Any]],
    key: str,
) -> dict[str, dict[str, Any]]:
    groups: defaultdict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for trade in trades:
        groups[str(trade.get(key, "unknown"))].append(trade)
    return {
        name: _trade_summary(group_trades)
        for name, group_trades in sorted(groups.items())
    }


def _trade_summary(trades: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    nets = _net_values(trades)
    positive = [value for value in nets if value > 0.0]
    negative = [value for value in nets if value < 0.0]
    trade_count = len(nets)
    return {
        "count": trade_count,
        "winning_trade_count": len(positive),
        "losing_trade_count": len(negative),
        "flat_trade_count": sum(1 for value in nets if value == 0.0),
        "net_sum": sum(nets),
        "average_trade_net": _mean(nets),
        "hit_rate": None if trade_count == 0 else len(positive) / trade_count,
        "average_win_net": _mean(positive),
        "average_loss_net": _mean(negative),
    }


def _win_loss_distribution(trades: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    nets = _net_values(trades)
    positive = [value for value in nets if value > 0.0]
    negative = [value for value in nets if value < 0.0]
    return {
        "largest_win_net": max(positive) if positive else None,
        "largest_loss_net": min(negative) if negative else None,
        "median_trade_net": median(nets) if nets else None,
        "sum_positive_net": sum(positive),
        "sum_negative_net": sum(negative),
    }


def _net_values(trades: Sequence[Mapping[str, Any]]) -> list[float]:
    return [_required_float(trade.get("net_return"), field_name="net_return") for trade in trades]


def _mean(values: Sequence[float]) -> float | None:
    return None if not values else sum(values) / len(values)


def _profit_factor(positive: Sequence[float], negative: Sequence[float]) -> float | None:
    if not positive and not negative:
        return None
    if not negative:
        return None
    return sum(positive) / abs(sum(negative))


def _share_of_abs_gross(value: float | None, gross: float | None) -> float | None:
    if value is None or gross is None or gross == 0.0:
        return None
    return value / abs(gross)


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"expected numeric trade_result value, got {value!r}") from exc


def _required_float(value: object, *, field_name: str) -> float:
    result = _optional_float(value)
    if result is None:
        raise ValueError(f"expected numeric {field_name}, got {value!r}")
    return result
```

- [ ] **Step 2: Run the helper tests**

Run:

```bash
conda run -n quant pytest tests/test_runner_economic_metrics.py -q
```

Expected: PASS.

- [ ] **Step 3: Commit the helper tests and implementation**

Run:

```bash
git add src/quant_strategies/runner/economic_metrics.py tests/test_runner_economic_metrics.py
git commit -m "feat: add quick-run economic metric helpers"
```

---

### Task 3: Wire Summary Economic Metrics

**Files:**
- Modify: `tests/test_runner_api_cli.py`
- Modify: `src/quant_strategies/runner/__init__.py`
- Modify: `src/quant_strategies/runner/artifacts.py`
- Test: `tests/test_runner_api_cli.py`

- [ ] **Step 1: Add completed-run summary artifact assertions**

In `tests/test_runner_api_cli.py`, add this helper after `assert_trade_result_metric_semantics`:

```python
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
```

In `test_summary_profile_writes_compact_artifacts`, add these assertions after `assert summary["engine"]["gates"][0]["name"] == "valid_inputs"`:

```python
    metrics = assert_summary_economic_metrics(summary)
    assert metrics["trade_count"] == summary["engine"]["trade_count"]
    assert metrics["hit_rate"] is not None
    assert "diagnostic_trades" not in summary["engine"]
```

In the same test, add this assertion after `assert profile["engine"]["trade_result"]["sum_signed_trade_activity_net"] is not None`:

```python
    assert "diagnostic_trades" not in profile["engine"]
```

In `test_default_quick_run_writes_diagnostics_without_full_replay_artifacts`, add this assertion after `assert "diagnostic_trades" not in summary["engine"]`:

```python
    assert_summary_economic_metrics(summary)
```

In `test_diagnostics_empty_decisions_complete_as_zero_trade_result`, add these assertions after the `summary["engine"]["trade_result"]` assertion:

```python
    metrics = assert_summary_economic_metrics(summary)
    assert metrics["trade_count"] == 0
    assert metrics["hit_rate"] is None
    assert metrics["average_trade_net"] is None
    assert metrics["profit_factor"] is None
```

- [ ] **Step 2: Run the focused artifact tests to verify they fail**

Run:

```bash
conda run -n quant pytest tests/test_runner_api_cli.py::test_summary_profile_writes_compact_artifacts tests/test_runner_api_cli.py::test_default_quick_run_writes_diagnostics_without_full_replay_artifacts tests/test_runner_api_cli.py::test_diagnostics_empty_decisions_complete_as_zero_trade_result -q
```

Expected: FAIL with `KeyError: 'economic_metrics'`.

- [ ] **Step 3: Let `summary_payload` accept completed-run economic metrics**

In `src/quant_strategies/runner/artifacts.py`, replace `summary_payload` with:

```python
def summary_payload(
    config: RunConfig,
    *,
    status: str,
    stage: str,
    failure_stage: str | None,
    message: str,
    engine: dict[str, object],
    assessment_status: str,
    evidence_quality: dict[str, object],
    param_contract: str = "unknown",
    economic_metrics: Mapping[str, object] | None = None,
) -> dict[str, object]:
    semantics = runner_evidence_semantics(config.data.kind)
    engine_payload = dict(engine)
    payload: dict[str, object] = {
        "strategy_id": config.strategy_id,
        "quick_checks": config.output.quick_checks,
        "artifact_profile": config.output.artifact_profile,
        "replayable_from_artifacts": replayable_from_artifacts_for_profile(config.output.artifact_profile),
        "status": status,
        "stage": stage,
        "failure_stage": failure_stage,
        "message": message,
        "artifacts": [],
        "engine": engine_payload,
        "run_completed": True,
        "assessment_status": assessment_status,
        # "unvalidated_passthrough" when the strategy defines no validate_params:
        # the quick-run still ran but its params were not schema-checked.
        "param_contract": param_contract,
        **semantics,
        **evidence_quality,
    }
    if economic_metrics is not None:
        payload["economic_metrics"] = json_safe_value(dict(economic_metrics))
    return payload
```

- [ ] **Step 4: Keep complete in-memory trades and wire summary metrics**

In `src/quant_strategies/runner/__init__.py`, add `economic_metrics` to the existing runner package import:

```python
from quant_strategies.runner import (
    artifacts,
    config as config_module,
    data_readiness,
    economic_metrics,
    engine_runner,
)
```

In `_evaluate_engine_request`, replace the `include_diagnostics` argument with this:

```python
                    # Completed quick-run summary metrics need the in-memory trade ledger
                    # for every artifact profile; compact artifacts trim it before writing.
                    include_diagnostics=True,
```

In `_write_completion_artifacts`, replace the initial `engine_summary` block through the diagnostic-profile trimming with this:

```python
        engine_summary_with_trades = artifacts.compact_engine_summary(
            engine_run,
            include_diagnostic_trades=True,
        )
        completed_trades = economic_metrics.trades_from_engine_summary(engine_summary_with_trades)
        economic_metrics_payload = economic_metrics.summary_metrics(
            completed_trades,
            economic_metrics.trade_result_from_engine_summary(engine_summary_with_trades),
        )
        engine_summary = dict(engine_summary_with_trades)
        engine_summary.pop("diagnostic_trades", None)
        assessment_status = artifacts.assessment_status(
            engine_run,
            quick_checks=config.output.quick_checks,
            evidence_quality=evidence_quality,
        )
        if config.output.artifact_profile == "full" and engine_run.evidence_json:
            artifacts.write_evidence(
                result_dir,
                engine_run.evidence_json,
                quick_checks=config.output.quick_checks,
            )
        if config.output.artifact_profile == "summary":
            from quant_strategies.runner.artifact_profiles import write_summary_profile_artifact

            write_summary_profile_artifact(
                result_dir,
                config=config,
                rows=execution.loaded_rows,
                decisions=execution.decisions,
                engine=engine_summary,
                normalized_rows_hash=execution.normalized_rows_sha256,
                row_ranges=execution.normalized_rows.ranges_by_symbol,
            )
        if config.output.artifact_profile == "diagnostic":
            from quant_strategies.runner import diagnostics

            diagnostics.write_diagnostics(
                result_dir,
                diagnostics.diagnostic_payload(
                    config=config,
                    engine=engine_summary_with_trades,
                    assessment_status=assessment_status,
                    evidence_quality=evidence_quality,
                ),
            )
```

In the later `artifacts.summary_payload(...)` call in the same function, add:

```python
                economic_metrics=economic_metrics_payload,
```

- [ ] **Step 5: Run the focused artifact tests**

Run:

```bash
conda run -n quant pytest tests/test_runner_api_cli.py::test_summary_profile_writes_compact_artifacts tests/test_runner_api_cli.py::test_default_quick_run_writes_diagnostics_without_full_replay_artifacts tests/test_runner_api_cli.py::test_diagnostics_empty_decisions_complete_as_zero_trade_result -q
```

Expected: PASS.

- [ ] **Step 6: Confirm summary mode still does not build full evidence JSON**

Run:

```bash
conda run -n quant pytest tests/test_runner_api_cli.py::test_summary_profile_does_not_build_full_evidence_json -q
```

Expected: PASS.

- [ ] **Step 7: Commit summary metric wiring**

Run:

```bash
git add src/quant_strategies/runner/__init__.py src/quant_strategies/runner/artifacts.py tests/test_runner_api_cli.py
git commit -m "feat: write quick-run summary economic metrics"
```

---

### Task 4: Add Diagnostic Economic Slices

**Files:**
- Modify: `tests/test_runner_api_cli.py`
- Modify: `src/quant_strategies/runner/diagnostics.py`
- Test: `tests/test_runner_api_cli.py`

- [ ] **Step 1: Add diagnostic slice artifact assertions**

In `test_default_quick_run_writes_diagnostics_without_full_replay_artifacts`, add these assertions after `assert diagnostics["trade_result"] == summary["engine"]["trade_result"]`:

```python
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
```

- [ ] **Step 2: Run the diagnostic artifact test to verify it fails**

Run:

```bash
conda run -n quant pytest tests/test_runner_api_cli.py::test_default_quick_run_writes_diagnostics_without_full_replay_artifacts -q
```

Expected: FAIL with `KeyError: 'economic_slices'`.

- [ ] **Step 3: Attach `economic_slices` in the diagnostic payload**

In `src/quant_strategies/runner/diagnostics.py`, add this import near the existing imports:

```python
from quant_strategies.runner.economic_metrics import diagnostic_slices
```

In `diagnostic_payload`, add this key after `cost_funding_breakdown`:

```python
        "economic_slices": diagnostic_slices(trades),
```

- [ ] **Step 4: Run diagnostic tests**

Run:

```bash
conda run -n quant pytest tests/test_runner_api_cli.py::test_default_quick_run_writes_diagnostics_without_full_replay_artifacts tests/test_runner_economic_metrics.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit diagnostic slice wiring**

Run:

```bash
git add src/quant_strategies/runner/diagnostics.py tests/test_runner_api_cli.py
git commit -m "feat: write diagnostic economic slices"
```

---

### Task 5: Update Active Documentation

**Files:**
- Modify: `README.md`
- Modify: `PRD.md`
- Modify: `TODOS.md`
- Modify: `docs/foundation-surfaces.md`
- Modify: `docs/runner.md`
- Modify: `docs/quant-autoresearch-consumer.md`

- [ ] **Step 1: Update `docs/runner.md` with metric definitions**

Add this section after `## Quick Checks`:

```markdown
## Economic Metrics

Completed quick runs write factual engine trade-activity summaries in
`summary.json.economic_metrics`. The block is derived from the completed
in-memory engine trade ledger and existing `trade_result` fields. It is not a
ranking policy, validation verdict, portfolio/NAV return, drawdown path,
benchmark comparison, promotion signal, paper-trading signal, or live-trading
signal.

`economic_metrics.schema_version` is
`quant_strategies.runner.economic_metrics/v1` and `basis` is
`engine_trade_ledger`. Metrics include trade counts, hit rate, average trade
net, average win/loss net, profit factor, cost share of absolute gross activity,
and funding share of absolute gross activity. Rates and averages that cannot be
computed from completed trades are `null`; profit factor is also `null` when no
losses exist, so artifacts never emit infinity.

Diagnostic-profile runs additionally write
`diagnostics.json.economic_slices`, grouped by symbol, direction, and exit
reason, plus a bounded win/loss distribution. These slices remain bounded
diagnostics and are not full replay artifacts.
```

- [ ] **Step 2: Update `docs/foundation-surfaces.md` quick-run artifacts**

In the Quick Run section, replace the sentence starting with `Common artifacts include` with:

```markdown
Common artifacts include `config.toml`, `strategy_snapshot.py`,
`run_manifest.json`, `summary.json`, `environment.json`, `notes.md`,
`data_manifest.json` when data loading is reached, and optional diagnostic or
full-profile artifacts. Completed quick-run `summary.json` files include
`economic_metrics`, a compact factual summary derived from the engine trade
ledger. Diagnostic-profile runs additionally write `diagnostics.json` with
`economic_slices`.
```

- [ ] **Step 3: Update `README.md` quick-run wording**

In the `Foundation Surfaces` quick-run paragraph, replace the first paragraph with:

```markdown
Loads rows, runs the pure strategy, validates the decision contract, replays for
hidden lookahead, and computes trade-level diagnostic evidence for one strategy
version. Completed quick-run summaries include factual `economic_metrics`
derived from the internal engine trade ledger. See [docs/runner.md](docs/runner.md).
```

- [ ] **Step 4: Update `PRD.md` diagnostic usefulness wording**

In section `6. Success Criteria`, replace the `Diagnostic usefulness` bullet with:

```markdown
- **Diagnostic usefulness.** A quick run explains one strategy version with bounded
behavior diagnostics: aggregate trade-result metrics, factual `economic_metrics`
in `summary.json`, diagnostic-profile slices, cost/funding contribution,
concentration, holding-period summaries, and representative trade samples.
```

- [ ] **Step 5: Collapse the B item in `TODOS.md` after implementation**

Replace the current `### B. Quick-run economic diagnostics improvement` section with:

```markdown
### B. Quick-run economic diagnostics improvement

Implemented by the quick-run economic diagnostics work. Completed quick-run
summaries now expose factual `economic_metrics` derived from the internal engine
trade ledger, and diagnostic-profile runs expose bounded `economic_slices`.

Preserved constraints:

- quick run stays on the internal causality-controlled engine;
- VectorBT Pro remains outside the quick-run hot path;
- engine trade-activity sums are not relabeled as NAV/path returns;
- quick run remains factual evidence output, not ranking, validation,
  evaluation, promotion, paper-trading, or live-trading authority.
```

- [ ] **Step 6: Update `docs/quant-autoresearch-consumer.md` as a consumer contract reference**

In `What autoresearch Reads`, replace the paragraph beginning `For ranking and iteration` with:

```markdown
For downstream consumption, read structured artifacts from `result.result_dir`,
especially `summary.json` for every completed run and `diagnostics.json` for
diagnostic-profile runs. `summary.json.economic_metrics` is the stable compact
factual economic summary for completed quick runs. It is derived from the engine
trade ledger and is not a ranking policy, validation verdict, evaluation result,
or promotion signal. Do not parse `notes.md` as the primary machine interface.
```

- [ ] **Step 7: Run documentation language checks**

Run:

```bash
rg -n "economic_metrics|economic_slices" README.md PRD.md TODOS.md docs/foundation-surfaces.md docs/runner.md docs/quant-autoresearch-consumer.md
rg -n "economic_metrics.*NAV|economic_metrics.*portfolio|economic_slices.*NAV|economic_slices.*portfolio|keep/kill|promotion signal|paper-trading signal|live-trading signal" README.md PRD.md TODOS.md docs/foundation-surfaces.md docs/runner.md docs/quant-autoresearch-consumer.md
```

Expected: first command finds the new docs. Second command may find explicit non-claim sentences such as `not a ... promotion signal`; inspect each match and confirm it is a denial, not an authority claim.

- [ ] **Step 8: Commit documentation updates**

Run:

```bash
git add README.md PRD.md TODOS.md docs/foundation-surfaces.md docs/runner.md docs/quant-autoresearch-consumer.md
git commit -m "docs: document quick-run economic metrics"
```

---

### Task 6: Final Verification And Accounting

**Files:**
- Verify: all changed source, tests, and docs

- [ ] **Step 1: Run focused Python tests**

Run:

```bash
conda run -n quant pytest tests/test_runner_economic_metrics.py tests/test_runner_api_cli.py::test_summary_profile_writes_compact_artifacts tests/test_runner_api_cli.py::test_summary_profile_does_not_build_full_evidence_json tests/test_runner_api_cli.py::test_default_quick_run_writes_diagnostics_without_full_replay_artifacts tests/test_runner_api_cli.py::test_diagnostics_empty_decisions_complete_as_zero_trade_result -q
```

Expected: PASS.

- [ ] **Step 2: Run the broader runner API test file**

Run:

```bash
conda run -n quant pytest tests/test_runner_api_cli.py -q
```

Expected: PASS.

- [ ] **Step 3: Run formatting and whitespace checks**

Run:

```bash
git diff --check
```

Expected: no output.

- [ ] **Step 4: Check for accidental VectorBT Pro or evaluation coupling in quick-run code**

Run:

```bash
rg -n "vectorbt|vectorbtpro|run_evaluation|evaluation" src/quant_strategies/runner src/quant_strategies/engine tests/test_runner_economic_metrics.py tests/test_runner_api_cli.py
```

Expected: no new quick-run dependency on VectorBT Pro or evaluation. Existing legitimate strings such as `engine/evaluation.py` paths or `EvaluationRunError` names should be inspected and left only if pre-existing.

- [ ] **Step 5: Report changed-line counts**

Run:

```bash
git diff --stat HEAD~4..HEAD
git diff --numstat HEAD~4..HEAD
```

Expected: report files changed, insertions, deletions, and net change, separated into source, tests, and docs in the final implementation summary.
