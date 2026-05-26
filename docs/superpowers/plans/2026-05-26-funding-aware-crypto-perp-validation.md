# Funding-Aware Crypto Perp Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the validation backend include crypto perpetual funding cashflows so a funding-crowding strategy is not evaluated from close-only price returns.

**Architecture:** Add a small deterministic funding cashflow module and integrate it into `VectorBTProBackend` after fill-window validation. Keep the current v1 backend limits: no overlapping same-symbol windows, no multi-asset target-weight portfolio semantics, no threshold exits. Funding support changes only the economics for already-supported non-overlapping time-hold windows.

**Tech Stack:** Python 3.12, pytest, Pydantic decision models, current `ValidationBackend` interface, optional VectorBT PRO import behind `VectorBTProBackend`.

---

## Scope Check

This plan implements funding-aware PnL for crypto perpetual validation. It does not implement:

- stateful target-weight rebalance semantics
- multi-asset portfolio allocation
- overlapping same-symbol target updates
- intrabar stop/take-profit/trailing-stop ordering
- exchange liquidation, margin, borrow, capacity, or market impact

Those are separate validation capabilities. The next strategy coming back from `quant_autoresearch` may still need stateful rebalance support after this funding slice lands.

## File Structure

- Create `src/quant_strategies/validation/funding.py`
  - Owns funding-event parsing and cashflow math.
  - Has no VectorBT dependency.
  - Raises a validation-local exception for incomplete or conflicting funding events.

- Create `tests/test_validation_funding.py`
  - Pins funding sign, interval inclusivity, duplicate handling, and invalid event behavior.

- Modify `src/quant_strategies/validation/vectorbtpro_backend.py`
  - Stops treating funding rows as unsupported.
  - Adds funding return to backend metrics for crypto perp funding rows.
  - Keeps data/fill failures higher priority than unsupported semantic checks.

- Modify `tests/test_vectorbtpro_backend.py`
  - Replaces the old funding-unsupported tests with funding-aware completed/failed tests.
  - Uses a fake `vectorbtpro` module where possible so tests do not require the commercial package.

- Modify `README.md`
  - Updates validation docs from "funding unsupported" to "funding-aware for non-overlapping time-hold windows."

- Modify `docs/superpowers/specs/2026-05-25-researched-strategy-validation-design.md`
  - Updates backend capability language and residual limitations.

---

### Task 1: Add Deterministic Funding Cashflow Math

**Files:**
- Create: `src/quant_strategies/validation/funding.py`
- Test: `tests/test_validation_funding.py`

- [ ] **Step 1: Write failing funding math tests**

Create `tests/test_validation_funding.py`:

```python
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from quant_strategies.validation.funding import (
    FundingEventError,
    funding_return_for_window,
    has_funding_cashflow_rows,
)


START = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)


def row(
    minute: int,
    *,
    symbol: str = "BTC-PERP",
    funding_rate: float | None = None,
    funding_minute: int | None = None,
    has_funding_event: bool = False,
) -> dict[str, object]:
    return {
        "symbol": symbol,
        "timestamp": START + timedelta(minutes=minute),
        "close": 100.0,
        "funding_timestamp": START + timedelta(minutes=funding_minute)
        if funding_minute is not None
        else None,
        "funding_rate": funding_rate,
        "has_funding_event": has_funding_event,
    }


def test_has_funding_cashflow_rows_detects_event_fields():
    assert has_funding_cashflow_rows([row(0)]) is False
    assert has_funding_cashflow_rows([row(0, funding_rate=0.0001)]) is True
    assert has_funding_cashflow_rows([row(0, funding_minute=0)]) is True
    assert has_funding_cashflow_rows([row(0, has_funding_event=True)]) is True


def test_long_pays_positive_funding_and_short_receives_it():
    rows = [row(1, funding_rate=0.0003, funding_minute=1, has_funding_event=True)]

    long_return = funding_return_for_window(
        rows,
        symbol="BTC-PERP",
        entry_time=START,
        exit_time=START + timedelta(minutes=2),
        direction="long",
        weight=0.5,
    )
    short_return = funding_return_for_window(
        rows,
        symbol="BTC-PERP",
        entry_time=START,
        exit_time=START + timedelta(minutes=2),
        direction="short",
        weight=0.5,
    )

    assert long_return == pytest.approx(-0.00015)
    assert short_return == pytest.approx(0.00015)


def test_funding_window_is_entry_exclusive_and_exit_inclusive():
    rows = [
        row(0, funding_rate=0.0010, funding_minute=0, has_funding_event=True),
        row(1, funding_rate=0.0020, funding_minute=1, has_funding_event=True),
        row(2, funding_rate=0.0030, funding_minute=2, has_funding_event=True),
        row(3, funding_rate=0.0040, funding_minute=3, has_funding_event=True),
    ]

    result = funding_return_for_window(
        rows,
        symbol="BTC-PERP",
        entry_time=START + timedelta(minutes=1),
        exit_time=START + timedelta(minutes=2),
        direction="short",
        weight=1.0,
    )

    assert result == pytest.approx(0.0030)


def test_duplicate_matching_funding_events_are_counted_once():
    rows = [
        row(1, funding_rate=0.0002, funding_minute=1, has_funding_event=True),
        row(1, funding_rate=0.0002, funding_minute=1, has_funding_event=True),
    ]

    result = funding_return_for_window(
        rows,
        symbol="BTC-PERP",
        entry_time=START,
        exit_time=START + timedelta(minutes=2),
        direction="short",
        weight=1.0,
    )

    assert result == pytest.approx(0.0002)


def test_conflicting_duplicate_funding_rates_fail_closed():
    rows = [
        row(1, funding_rate=0.0002, funding_minute=1, has_funding_event=True),
        row(1, funding_rate=0.0003, funding_minute=1, has_funding_event=True),
    ]

    with pytest.raises(FundingEventError, match="conflicting funding rates"):
        funding_return_for_window(
            rows,
            symbol="BTC-PERP",
            entry_time=START,
            exit_time=START + timedelta(minutes=2),
            direction="short",
            weight=1.0,
        )


def test_incomplete_funding_event_fails_closed():
    rows = [row(1, funding_rate=None, funding_minute=1, has_funding_event=True)]

    with pytest.raises(FundingEventError, match="incomplete funding event"):
        funding_return_for_window(
            rows,
            symbol="BTC-PERP",
            entry_time=START,
            exit_time=START + timedelta(minutes=2),
            direction="long",
            weight=1.0,
        )
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run:

```bash
conda run -n quant pytest tests/test_validation_funding.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'quant_strategies.validation.funding'
```

- [ ] **Step 3: Implement the funding module**

Create `src/quant_strategies/validation/funding.py`:

```python
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
import math
from typing import Any, Literal


Direction = Literal["long", "short"]


class FundingEventError(ValueError):
    """Raised when funding event rows cannot be interpreted safely."""


def has_funding_cashflow_rows(rows: Sequence[Mapping[str, Any]]) -> bool:
    for row in rows:
        if row.get("has_funding_event") is True:
            return True
        if row.get("funding_rate") is not None:
            return True
        if row.get("funding_timestamp") is not None:
            return True
    return False


def funding_return_for_window(
    rows: Sequence[Mapping[str, Any]],
    *,
    symbol: str,
    entry_time: datetime,
    exit_time: datetime,
    direction: Direction,
    weight: float,
) -> float:
    if direction not in {"long", "short"}:
        raise FundingEventError(f"unsupported funding direction: {direction}")
    if not math.isfinite(weight) or weight < 0.0:
        raise FundingEventError(f"invalid funding weight: {weight}")

    entry = _timezone_aware(entry_time, "entry_time")
    exit_ = _timezone_aware(exit_time, "exit_time")
    if exit_ < entry:
        raise FundingEventError("exit_time must be on or after entry_time")

    rates_by_timestamp: dict[datetime, float] = {}
    for row in rows:
        if str(row.get("symbol", "")).strip() != symbol:
            continue
        if row.get("has_funding_event") is not True:
            continue

        raw_timestamp = row.get("funding_timestamp")
        raw_rate = row.get("funding_rate")
        if raw_timestamp is None or raw_rate is None:
            row_time = row.get("timestamp")
            raise FundingEventError(f"incomplete funding event: {symbol} at {row_time}")

        funding_timestamp = _timezone_aware(raw_timestamp, "funding_timestamp")
        if not entry < funding_timestamp <= exit_:
            continue

        funding_rate = _finite_float(raw_rate, "funding_rate")
        existing = rates_by_timestamp.get(funding_timestamp)
        if existing is not None and not math.isclose(
            existing,
            funding_rate,
            rel_tol=0.0,
            abs_tol=1e-15,
        ):
            raise FundingEventError(
                f"conflicting funding rates at {funding_timestamp.isoformat()}"
            )
        rates_by_timestamp[funding_timestamp] = funding_rate

    side_multiplier = 1.0 if direction == "long" else -1.0
    return sum(-side_multiplier * rate for rate in rates_by_timestamp.values()) * weight


def _timezone_aware(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise FundingEventError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise FundingEventError(f"{field_name} must be timezone-aware")
    return value


def _finite_float(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise FundingEventError(f"{field_name} must be numeric")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise FundingEventError(f"{field_name} must be finite")
    return parsed
```

- [ ] **Step 4: Run the funding tests and verify they pass**

Run:

```bash
conda run -n quant pytest tests/test_validation_funding.py -q
```

Expected:

```text
6 passed
```

- [ ] **Step 5: Commit Task 1**

Run:

```bash
git add src/quant_strategies/validation/funding.py tests/test_validation_funding.py
git commit -m "feat: add crypto perp funding cashflow math"
```

---

### Task 2: Integrate Funding Into VectorBTProBackend Metrics

**Files:**
- Modify: `src/quant_strategies/validation/vectorbtpro_backend.py`
- Test: `tests/test_vectorbtpro_backend.py`

- [ ] **Step 1: Replace funding-unsupported tests with funding-aware tests**

In `tests/test_vectorbtpro_backend.py`, replace:

```python
def test_vectorbtpro_backend_reports_unsupported_crypto_perp_funding_cashflows():
    ...


def test_vectorbtpro_backend_reports_unsupported_funding_rows_without_config():
    ...
```

with:

```python
def install_fake_vectorbtpro(monkeypatch, *, total_return: float = 0.0, trade_count: int = 1):
    class FakeTrades:
        def count(self):
            return trade_count

    class FakePortfolio:
        trades = FakeTrades()

        def get_total_return(self):
            return total_return

    fake_vbt = SimpleNamespace(
        Portfolio=SimpleNamespace(from_signals=lambda *args, **kwargs: FakePortfolio())
    )
    monkeypatch.setitem(sys.modules, "vectorbtpro", fake_vbt)
    return fake_vbt


def funding_rows():
    return [
        {"symbol": "BTC-PERP", "timestamp": AS_OF, "close": 100.0},
        {"symbol": "BTC-PERP", "timestamp": DECISION, "close": 101.0},
        {
            "symbol": "BTC-PERP",
            "timestamp": datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc),
            "close": 102.0,
            "funding_timestamp": datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc),
            "funding_rate": 0.0003,
            "has_funding_event": True,
        },
        {
            "symbol": "BTC-PERP",
            "timestamp": datetime(2026, 1, 1, 0, 3, tzinfo=timezone.utc),
            "close": 103.0,
        },
    ]


def test_vectorbtpro_backend_adds_funding_return_for_crypto_perp_rows(monkeypatch):
    install_fake_vectorbtpro(monkeypatch, total_return=0.01, trade_count=1)
    config = SimpleNamespace(data=SimpleNamespace(kind="crypto_perp_funding"))

    result = VectorBTProBackend().run(
        decisions=[decision()],
        rows=funding_rows(),
        config=config,
    )

    assert result.status == "completed"
    assert result.unsupported_semantics == ()
    assert result.metrics["price_cost_return"] == pytest.approx(0.01)
    assert result.metrics["funding_return"] == pytest.approx(-0.0003)
    assert result.metrics["net_return"] == pytest.approx(0.0097)


def test_vectorbtpro_backend_fails_on_incomplete_funding_event(monkeypatch):
    install_fake_vectorbtpro(monkeypatch, total_return=0.01, trade_count=1)
    bad_rows = funding_rows()
    bad_rows[2] = {**bad_rows[2], "funding_rate": None}

    result = VectorBTProBackend().run(
        decisions=[decision()],
        rows=bad_rows,
        config=SimpleNamespace(data=SimpleNamespace(kind="crypto_perp_funding")),
    )

    assert result.status == "failed"
    assert any("invalid_funding_events:incomplete funding event" in warning for warning in result.warnings)
```

If a helper named `install_fake_vectorbtpro` already exists after editing nearby tests, reuse that exact helper and keep only one definition in the file.

- [ ] **Step 2: Run the backend tests and verify they fail**

Run:

```bash
conda run -n quant pytest tests/test_vectorbtpro_backend.py::test_vectorbtpro_backend_adds_funding_return_for_crypto_perp_rows tests/test_vectorbtpro_backend.py::test_vectorbtpro_backend_fails_on_incomplete_funding_event -q
```

Expected:

```text
FAILED ... result.status == "unsupported"
```

The incomplete-event test may also fail as `unsupported`; both failures prove the backend still treats funding rows as unsupported.

- [ ] **Step 3: Update VectorBTProBackend imports**

At the top of `src/quant_strategies/validation/vectorbtpro_backend.py`, add:

```python
from quant_strategies.validation.funding import (
    FundingEventError,
    funding_return_for_window,
    has_funding_cashflow_rows,
)
```

- [ ] **Step 4: Remove funding from unsupported semantics**

In `_unsupported_semantics(...)`, delete this logic:

```python
    if _config_value(config, "data", "kind", default=None) == "crypto_perp_funding" or _has_funding_fields(rows):
        unsupported.append("crypto_perp_funding_cashflows")
```

Delete the local `_has_funding_fields(...)` helper from `vectorbtpro_backend.py`.

- [ ] **Step 5: Add funding adjustment after VectorBT metric extraction**

In `VectorBTProBackend.run(...)`, replace:

```python
        try:
            metrics = _portfolio_metrics(portfolio)
        except ValueError as exc:
            return _failed(self.name, f"invalid_metrics:{exc}")
        except Exception as exc:
            return _failed(self.name, f"metric_extraction_failed:{exc}")
        if metrics["trade_count"] != len(windows):
            return _failed(self.name, f"unexpected_trade_count:{metrics['trade_count']}:{len(windows)}")
```

with:

```python
        try:
            metrics = _portfolio_metrics(portfolio)
        except ValueError as exc:
            return _failed(self.name, f"invalid_metrics:{exc}")
        except Exception as exc:
            return _failed(self.name, f"metric_extraction_failed:{exc}")
        if metrics["trade_count"] != len(windows):
            return _failed(self.name, f"unexpected_trade_count:{metrics['trade_count']}:{len(windows)}")

        try:
            metrics = _funding_adjusted_metrics(metrics, rows, windows, config)
        except FundingEventError as exc:
            return _failed(self.name, f"invalid_funding_events:{exc}")
```

- [ ] **Step 6: Add funding-adjusted metric helper**

In `src/quant_strategies/validation/vectorbtpro_backend.py`, add this helper below `_unsupported_semantics(...)`:

```python
def _funding_adjusted_metrics(
    metrics: dict[str, float | int],
    rows: list[dict[str, Any]],
    windows: list[dict[str, Any]],
    config: Any,
) -> dict[str, float | int]:
    data_kind = _config_value(config, "data", "kind", default=None)
    if data_kind != "crypto_perp_funding" and not has_funding_cashflow_rows(rows):
        return metrics

    funding_return = 0.0
    for window in windows:
        decision = window["decision"]
        if decision.target.direction == "flat":
            continue
        funding_return += funding_return_for_window(
            rows,
            symbol=window["symbol"],
            entry_time=window["entry_time"],
            exit_time=window["exit_time"],
            direction=decision.target.direction,
            weight=decision.target.size,
        )

    price_cost_return = float(metrics["net_return"])
    return {
        **metrics,
        "price_cost_return": price_cost_return,
        "funding_return": funding_return,
        "net_return": price_cost_return + funding_return,
    }
```

- [ ] **Step 7: Run the focused backend tests and verify they pass**

Run:

```bash
conda run -n quant pytest tests/test_vectorbtpro_backend.py::test_vectorbtpro_backend_adds_funding_return_for_crypto_perp_rows tests/test_vectorbtpro_backend.py::test_vectorbtpro_backend_fails_on_incomplete_funding_event -q
```

Expected:

```text
2 passed
```

- [ ] **Step 8: Run all VectorBT backend tests**

Run:

```bash
conda run -n quant pytest tests/test_vectorbtpro_backend.py -q
```

Expected:

```text
passed
```

- [ ] **Step 9: Commit Task 2**

Run:

```bash
git add src/quant_strategies/validation/vectorbtpro_backend.py tests/test_vectorbtpro_backend.py
git commit -m "feat: include funding returns in vectorbt validation metrics"
```

---

### Task 3: Document Funding-Aware Semantics

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-05-25-researched-strategy-validation-design.md`

- [ ] **Step 1: Update README validation language**

In `README.md`, replace the sentence:

```markdown
The VectorBT PRO adapter currently rejects crypto
perp funding cashflow rows as `unsupported_semantics` rather than simulating
close-only returns that omit funding PnL.
```

with:

```markdown
For crypto perpetual funding rows, the VectorBT PRO adapter reports funding-aware
metrics for the current v1 supported shape: non-overlapping time-held target
exposure windows. The validation metric is `price_cost_return + funding_return`.
The adapter still rejects unsupported sizing, threshold exits, overlapping
same-symbol windows, and multi-asset target-weight portfolio semantics rather
than approximating them silently.
```

- [ ] **Step 2: Update the validation design spec**

In `docs/superpowers/specs/2026-05-25-researched-strategy-validation-design.md`, replace:

```markdown
The VectorBT PRO adapter must mark crypto perpetual funding cashflows as
unsupported until funding PnL is modeled explicitly; close-only returns are not
valid funding strategy evidence.
```

with:

```markdown
The VectorBT PRO adapter must include crypto perpetual funding cashflows for
supported non-overlapping time-held windows. Funding-aware validation metrics
must report `price_cost_return`, `funding_return`, and `net_return`, where
`net_return = price_cost_return + funding_return`. Close-only returns are not
valid funding strategy evidence.
```

- [ ] **Step 3: Run docs grep to verify unsupported wording is gone**

Run:

```bash
rg -n "funding cashflow rows as `unsupported_semantics`|crypto_perp_funding_cashflows" README.md docs/superpowers/specs/2026-05-25-researched-strategy-validation-design.md
```

Expected:

```text
```

No output.

- [ ] **Step 4: Commit Task 3**

Run:

```bash
git add README.md docs/superpowers/specs/2026-05-25-researched-strategy-validation-design.md
git commit -m "docs: document funding-aware validation semantics"
```

---

### Task 4: Full Verification And Reality Check

**Files:**
- No planned file edits.

- [ ] **Step 1: Run focused validation tests**

Run:

```bash
conda run -n quant pytest tests/test_validation_funding.py tests/test_vectorbtpro_backend.py tests/test_validation_backends_and_policy.py tests/test_validation_runner.py -q
```

Expected:

```text
passed
```

- [ ] **Step 2: Run the full suite**

Run:

```bash
conda run -n quant pytest -q
```

Expected:

```text
passed
```

- [ ] **Step 3: Run CLI help**

Run:

```bash
conda run -n quant quant-strategies validate --help
```

Expected:

```text
usage: quant-strategies validate [-h] [--repo-root REPO_ROOT] package_or_config
```

- [ ] **Step 4: Run the current researched rank_03 dry run**

Run:

```bash
conda run -n quant quant-strategies validate researched/crypto_perp_funding_crowding_reversal/families/family_03_exploratory_time_only_exit/variants/rank_03
```

Expected current-state result:

```text
validation decision: hard_no
```

The expected blocker is still `overlapping_decision_window` until the strategy
is redesigned in `quant_autoresearch`. If this run reports
`crypto_perp_funding_cashflows`, the funding integration is incomplete.

- [ ] **Step 5: Inspect latest validation artifacts**

Run:

```bash
latest_dir=$(find validation_results/researched/crypto_perp_funding_crowding_reversal/family_03_exploratory_time_only_exit/rank_03 -maxdepth 1 -type d -name '2026-*' | sort | tail -1)
cat "$latest_dir/promotion_decision.json"
rg -n "crypto_perp_funding_cashflows|funding_return|price_cost_return|overlapping_decision_window" "$latest_dir"
```

Expected:

```text
"decision": "hard_no"
overlapping_decision_window
```

The dry run may not reach funding metrics because overlap fails before backend
simulation. That is acceptable for this current researched package. Funding
metrics are pinned by unit tests in Task 2.

- [ ] **Step 6: Commit verification note if docs changed during verification**

If verification requires no file edits, skip this step. If a doc clarification
is added during verification, run:

```bash
git add README.md docs/superpowers/specs/2026-05-25-researched-strategy-validation-design.md
git commit -m "docs: clarify funding validation verification"
```

---

## Self-Review

### Spec Coverage

- Funding cashflow math is covered by Task 1.
- Backend integration is covered by Task 2.
- Artifact honesty and docs are covered by Task 3.
- Focused/full verification and current rank_03 reality check are covered by Task 4.
- State-aware target rebalance is intentionally outside this plan.
- Multi-asset portfolio target weights are intentionally outside this plan.

### Placeholder Scan

This plan avoids placeholder instructions. Each code-producing step includes concrete code or an exact replacement.

### Type Consistency

- `direction` uses the existing decision target values: `"long"` and `"short"`.
- Funding helper accepts raw row mappings because validation data rows are plain dictionaries.
- Backend metrics remain `dict[str, float | int]` compatible with `BackendRunResult.metrics`.
- `net_return` remains the classification metric and becomes funding-aware when funding rows exist.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-26-funding-aware-crypto-perp-validation.md`.

Two execution options:

1. **Subagent-Driven (recommended)** - Dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints.
