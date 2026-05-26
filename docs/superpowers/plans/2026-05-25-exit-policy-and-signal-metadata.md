# Exit Policy And Signal Metadata Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic per-signal exit policies, trade exit reasons, and signal metadata pass-through, then update the two current research strategies to emit audit metadata.

**Architecture:** Keep strategy files pure and flat. Extend the existing strict engine models, evaluate exits inside the deterministic `screen()` path, normalize runner signal dictionaries before model construction, and preserve the normalized metadata through request, evidence, and trade artifacts. Keep the first version close-price/configured-fill based; do not add intrabar stop simulation or policy registries.

```text
strategy row dicts
  -> runner normalizes reserved fields + metadata
  -> engine Signal(max_hold/tp/sl/trailing, metadata)
  -> screen() scans completed trigger bars and applies exit lag
  -> Trade(exit_reason, signal_metadata)
  -> EvidencePacket v2 + runner artifacts
```

**Tech Stack:** Python 3.12, Pydantic v2 models, pytest, `conda run -n quant` for all Python commands.

---

## File Structure

- Modify `src/quant_strategies/engine/models.py`: add `ExitReason`, v2 evidence schema string, signal exit fields, JSON-compatible signal metadata, and trade `exit_reason` plus `signal_metadata`.
- Modify `src/quant_strategies/engine/__init__.py`: export `ExitReason` from the public engine API.
- Modify `src/quant_strategies/engine/evaluation.py`: replace fixed-horizon exit selection with deterministic trigger-bar scanning while preserving old `hold_bars` behavior.
- Modify `src/quant_strategies/runner/engine_runner.py`: normalize raw signal rows, fold extra flat fields into metadata, pass exit controls to `Signal`, and update fillability checks for trigger and exit lag.
- Modify `src/quant_strategies/runner/artifacts.py`: prefer new signal exit and audit columns in `signals.csv`; evidence schema v2 flows through the existing manifest writer.
- Modify `untested/crypto_perp_funding_crowding_reversal.py`: emit max hold, optional exit controls, and funding/return audit fields.
- Modify `untested/fx_triangular_residual_reversion.py`: emit max hold, optional exit controls, and residual/attribution audit fields.
- Modify `README.md`: document exit fields, exit reason, metadata pass-through, and the close-confirmed trigger limitation.
- Modify tests under `tests/`: add focused model, engine, runner, artifact, and strategy coverage.
- Modify `tests/test_engine_validate_and_evidence.py`: update the existing evidence schema regression assertion to v2.

## Task 1: Extend Engine Models

**Files:**
- Modify: `tests/test_engine_models.py`
- Modify: `tests/test_engine_validate_and_evidence.py`
- Modify: `src/quant_strategies/engine/models.py`
- Modify: `src/quant_strategies/engine/__init__.py`

- [ ] **Step 1: Write failing engine model tests**

Append these tests to `tests/test_engine_models.py`:

```python
def test_signal_accepts_exit_controls_and_metadata():
    aware_time = datetime(2024, 1, 1, tzinfo=timezone.utc)

    signal = Signal(
        symbol="BTC",
        decision_time=aware_time,
        side=Side.LONG,
        hold_bars=10,
        max_hold_bars=3,
        take_profit_bps=125.0,
        stop_loss_bps=50.0,
        trailing_stop_bps=25.0,
        metadata={"funding_pressure_bps": 3.5, "signal_family": "demo"},
    )

    assert signal.max_hold_bars == 3
    assert signal.take_profit_bps == 125.0
    assert signal.stop_loss_bps == 50.0
    assert signal.trailing_stop_bps == 25.0
    assert signal.metadata == {"funding_pressure_bps": 3.5, "signal_family": "demo"}


def test_signal_rejects_invalid_exit_controls_and_metadata():
    aware_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
    base = {"symbol": "BTC", "decision_time": aware_time, "side": Side.LONG}

    with pytest.raises(ValidationError, match="max_hold_bars"):
        Signal(**base, max_hold_bars=0)

    with pytest.raises(ValidationError, match="exit bps values must be finite and positive"):
        Signal(**base, take_profit_bps=float("inf"))

    with pytest.raises(ValidationError, match="exit bps values must be finite and positive"):
        Signal(**base, stop_loss_bps=0.0)

    with pytest.raises(ValidationError, match="metadata must be JSON-compatible"):
        Signal(**base, metadata={"timestamp": aware_time})

    with pytest.raises(ValidationError, match="metadata must be JSON-compatible"):
        Signal(**base, metadata={"bad": float("nan")})
```

Update the existing deterministic evidence test in `tests/test_engine_validate_and_evidence.py`:

```python
    assert json.loads(first)["schema_version"] == "quant_strategies.engine.evidence/v2"
```

- [ ] **Step 2: Run the failing model tests**

Run:

```bash
conda run -n quant python -m pytest tests/test_engine_models.py::test_signal_accepts_exit_controls_and_metadata tests/test_engine_models.py::test_signal_rejects_invalid_exit_controls_and_metadata -v
```

Expected: FAIL because `Signal` does not accept the new fields.

- [ ] **Step 3: Update engine model definitions**

In `src/quant_strategies/engine/models.py`, update imports:

```python
import json
import math
from datetime import datetime
from enum import Enum
from typing import Any, Literal
```

Change the evidence version and add an exit reason alias near `Side`:

```python
EVIDENCE_SCHEMA_VERSION = "quant_strategies.engine.evidence/v2"
ExitReason = Literal["stop_loss", "take_profit", "trailing_stop", "max_hold"]
```

Also change `EvidencePacket.schema_version` to use the v2 literal and default:

```python
schema_version: Literal["quant_strategies.engine.evidence/v2"] = "quant_strategies.engine.evidence/v2"
```

Replace the current `Signal` and `Trade` classes with:

```python
class Signal(EngineModel):
    symbol: str = Field(min_length=1)
    decision_time: datetime
    side: Side
    weight: float = Field(default=1.0, gt=0)
    hold_bars: int = Field(default=1, ge=1)
    max_hold_bars: int | None = Field(default=None, ge=1)
    take_profit_bps: float | None = Field(default=None, gt=0)
    stop_loss_bps: float | None = Field(default=None, gt=0)
    trailing_stop_bps: float | None = Field(default=None, gt=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("decision_time")
    @classmethod
    def validate_decision_time(cls, value: datetime) -> datetime:
        return _timezone_aware(value, "decision_time")

    @model_validator(mode="after")
    def validate_signal(self) -> Signal:
        if not math.isfinite(self.weight):
            raise ValueError("weight must be finite")
        exit_bps_values = (self.take_profit_bps, self.stop_loss_bps, self.trailing_stop_bps)
        if any(value is not None and (not math.isfinite(value) or value <= 0.0) for value in exit_bps_values):
            raise ValueError("exit bps values must be finite and positive")
        try:
            json.dumps(self.metadata, sort_keys=True, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("metadata must be JSON-compatible") from exc
        return self
```

```python
class Trade(EngineModel):
    symbol: str
    side: Side
    decision_time: datetime
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    exit_reason: ExitReason
    weight: float
    gross_return: float
    funding_return: float = 0.0
    cost_return: float
    net_return: float
    signal_metadata: dict[str, Any] = Field(default_factory=dict)
```

- [ ] **Step 4: Export `ExitReason`**

In `src/quant_strategies/engine/__init__.py`, add `ExitReason` to the model import block and `__all__`:

```python
from quant_strategies.engine.models import (
    Bar,
    CostModel,
    EVIDENCE_SCHEMA_VERSION,
    EvaluationRequest,
    EvidencePacket,
    ExitReason,
    FillModel,
    GateResult,
    ScreeningResult,
    Side,
    Signal,
    StrategySpec,
    Trade,
    ValidationConfig,
    ValidationReport,
)
```

```python
__all__ = [
    "Bar",
    "CostModel",
    "EVIDENCE_SCHEMA_VERSION",
    "EvaluationRequest",
    "EvidencePacket",
    "ExitReason",
    "FillModel",
    "GateResult",
    "ScreeningResult",
    "Side",
    "Signal",
    "StrategySpec",
    "Trade",
    "ValidationConfig",
    "ValidationReport",
    "build_evidence_packet",
    "evidence_json",
    "screen",
    "validate",
]
```

- [ ] **Step 5: Run model tests**

Run:

```bash
conda run -n quant python -m pytest tests/test_engine_models.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit model contract**

```bash
git add src/quant_strategies/engine/models.py src/quant_strategies/engine/__init__.py tests/test_engine_models.py tests/test_engine_validate_and_evidence.py
git commit -m "feat: extend signal and trade model contract"
```

## Task 2: Implement Deterministic Exit Selection

**Files:**
- Modify: `tests/test_engine_screen.py`
- Modify: `src/quant_strategies/engine/evaluation.py`

- [ ] **Step 1: Add failing engine exit tests**

Append these tests to `tests/test_engine_screen.py`:

```python
def test_screen_old_hold_bars_exits_with_max_hold_reason():
    request = EvaluationRequest(
        spec=StrategySpec(
            strategy_id="old_hold",
            signals=(Signal(symbol="BTC", decision_time=DECISION, side=Side.LONG, hold_bars=2),),
        ),
        bars=bars_for("BTC", [100.0, 100.0, 101.0, 103.0]),
        fill_model=FillModel(price="close", entry_lag_bars=1),
    )

    result = screen(request)
    trade = result.trades[0]

    assert trade.exit_time == DECISION.replace(minute=33)
    assert trade.exit_reason == "max_hold"
    assert trade.gross_return == pytest.approx(0.03)


def test_screen_max_hold_bars_overrides_hold_bars():
    request = EvaluationRequest(
        spec=StrategySpec(
            strategy_id="max_hold",
            signals=(
                Signal(
                    symbol="BTC",
                    decision_time=DECISION,
                    side=Side.LONG,
                    hold_bars=5,
                    max_hold_bars=1,
                ),
            ),
        ),
        bars=bars_for("BTC", [100.0, 100.0, 102.0, 110.0, 120.0, 130.0, 140.0]),
        fill_model=FillModel(price="close", entry_lag_bars=1),
    )

    trade = screen(request).trades[0]

    assert trade.exit_time == DECISION.replace(minute=32)
    assert trade.exit_reason == "max_hold"
    assert trade.gross_return == pytest.approx(0.02)
```

```python
def test_screen_exits_on_take_profit_before_max_hold():
    request = EvaluationRequest(
        spec=StrategySpec(
            strategy_id="take_profit",
            signals=(
                Signal(
                    symbol="BTC",
                    decision_time=DECISION,
                    side=Side.LONG,
                    max_hold_bars=3,
                    take_profit_bps=150.0,
                ),
            ),
        ),
        bars=bars_for("BTC", [100.0, 100.0, 102.0, 101.0, 104.0]),
        fill_model=FillModel(price="close", entry_lag_bars=1),
    )

    trade = screen(request).trades[0]

    assert trade.exit_time == DECISION.replace(minute=32)
    assert trade.exit_reason == "take_profit"
    assert trade.gross_return == pytest.approx(0.02)


def test_screen_exits_on_stop_loss_before_max_hold():
    request = EvaluationRequest(
        spec=StrategySpec(
            strategy_id="stop_loss",
            signals=(
                Signal(
                    symbol="BTC",
                    decision_time=DECISION,
                    side=Side.LONG,
                    max_hold_bars=3,
                    stop_loss_bps=100.0,
                ),
            ),
        ),
        bars=bars_for("BTC", [100.0, 100.0, 98.0, 99.0, 104.0]),
        fill_model=FillModel(price="close", entry_lag_bars=1),
    )

    trade = screen(request).trades[0]

    assert trade.exit_time == DECISION.replace(minute=32)
    assert trade.exit_reason == "stop_loss"
    assert trade.gross_return == pytest.approx(-0.02)
```

```python
def test_screen_exits_on_trailing_stop_after_favorable_move():
    request = EvaluationRequest(
        spec=StrategySpec(
            strategy_id="trailing_stop",
            signals=(
                Signal(
                    symbol="BTC",
                    decision_time=DECISION,
                    side=Side.LONG,
                    max_hold_bars=4,
                    trailing_stop_bps=150.0,
                ),
            ),
        ),
        bars=bars_for("BTC", [100.0, 100.0, 104.0, 102.0, 105.0, 106.0]),
        fill_model=FillModel(price="close", entry_lag_bars=1),
    )

    trade = screen(request).trades[0]

    assert trade.exit_time == DECISION.replace(minute=33)
    assert trade.exit_reason == "trailing_stop"
    assert trade.gross_return == pytest.approx(0.02)


def test_screen_short_take_profit_uses_falling_price():
    request = EvaluationRequest(
        spec=StrategySpec(
            strategy_id="short_take_profit",
            signals=(
                Signal(
                    symbol="BTC",
                    decision_time=DECISION,
                    side=Side.SHORT,
                    max_hold_bars=3,
                    take_profit_bps=150.0,
                ),
            ),
        ),
        bars=bars_for("BTC", [100.0, 100.0, 98.0, 101.0, 104.0]),
        fill_model=FillModel(price="close", entry_lag_bars=1),
    )

    trade = screen(request).trades[0]

    assert trade.exit_time == DECISION.replace(minute=32)
    assert trade.exit_reason == "take_profit"
    assert trade.gross_return == pytest.approx(0.02)


def test_screen_short_stop_loss_over_trailing_stop_on_same_trigger_bar():
    request = EvaluationRequest(
        spec=StrategySpec(
            strategy_id="short_priority_stop_loss",
            signals=(
                Signal(
                    symbol="BTC",
                    decision_time=DECISION,
                    side=Side.SHORT,
                    max_hold_bars=3,
                    stop_loss_bps=50.0,
                    trailing_stop_bps=100.0,
                ),
            ),
        ),
        bars=bars_for("BTC", [100.0, 100.0, 98.0, 101.0, 102.0]),
        fill_model=FillModel(price="close", entry_lag_bars=1),
    )

    trade = screen(request).trades[0]

    assert trade.exit_time == DECISION.replace(minute=33)
    assert trade.exit_reason == "stop_loss"


def test_screen_prioritizes_stop_loss_over_trailing_stop_on_same_trigger_bar():
    request = EvaluationRequest(
        spec=StrategySpec(
            strategy_id="priority_stop_loss",
            signals=(
                Signal(
                    symbol="BTC",
                    decision_time=DECISION,
                    side=Side.LONG,
                    max_hold_bars=3,
                    stop_loss_bps=50.0,
                    trailing_stop_bps=100.0,
                ),
            ),
        ),
        bars=bars_for("BTC", [100.0, 100.0, 102.0, 99.0, 98.0]),
        fill_model=FillModel(price="close", entry_lag_bars=1),
    )

    trade = screen(request).trades[0]

    assert trade.exit_time == DECISION.replace(minute=33)
    assert trade.exit_reason == "stop_loss"
```

```python
def test_screen_exit_lag_fills_after_trigger_bar():
    request = EvaluationRequest(
        spec=StrategySpec(
            strategy_id="exit_lag",
            signals=(
                Signal(
                    symbol="BTC",
                    decision_time=DECISION,
                    side=Side.LONG,
                    max_hold_bars=3,
                    take_profit_bps=150.0,
                ),
            ),
        ),
        bars=bars_for("BTC", [100.0, 100.0, 102.0, 101.0, 99.0, 98.0]),
        fill_model=FillModel(price="close", entry_lag_bars=1, exit_lag_bars=1),
    )

    trade = screen(request).trades[0]

    assert trade.exit_time == DECISION.replace(minute=33)
    assert trade.exit_reason == "take_profit"
    assert trade.exit_price == 101.0


def test_screen_early_exit_shortens_funding_exposure():
    request = EvaluationRequest(
        spec=StrategySpec(
            strategy_id="funding_shortened",
            signals=(
                Signal(
                    symbol="BTC-PERP",
                    decision_time=DECISION,
                    side=Side.LONG,
                    max_hold_bars=2,
                    take_profit_bps=50.0,
                ),
            ),
        ),
        bars=funding_bars_for("BTC-PERP"),
        fill_model=FillModel(price="close", entry_lag_bars=1),
    )

    trade = screen(request).trades[0]

    assert trade.exit_time == DECISION.replace(minute=33)
    assert trade.exit_reason == "take_profit"
    assert trade.funding_return == pytest.approx(-0.001)
```

- [ ] **Step 2: Run the failing engine exit tests**

Run:

```bash
conda run -n quant python -m pytest tests/test_engine_screen.py -v
```

Expected: FAIL on missing `exit_reason` and fixed-horizon exit behavior.

- [ ] **Step 3: Implement exit selection**

In `src/quant_strategies/engine/evaluation.py`, add imports:

```python
from dataclasses import dataclass
```

Extend the model imports:

```python
    Bar,
    EvaluationRequest,
    ExitReason,
    FillModel,
    GateResult,
    ScreeningResult,
    Side,
    Signal,
    Trade,
    ValidationConfig,
    ValidationReport,
)
```

Add this helper dataclass below `EvaluationError`:

```python
@dataclass(frozen=True)
class _ExitSelection:
    exit_bar: Bar
    reason: ExitReason
```

In `screen()`, replace the current fixed `exit_index` block with:

```python
        decision_index = _decision_index(symbol_bars, signal.decision_time)
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
```

When constructing `Trade`, include:

```python
                exit_reason=exit_selection.reason,
                signal_metadata=signal.metadata,
```

Add these helpers below `_decision_index()`:

```python
def _select_exit(
    bars: tuple[Bar, ...],
    signal: Signal,
    entry_index: int,
    entry_price: float,
    fill_model: FillModel,
) -> _ExitSelection:
    max_hold_bars = signal.max_hold_bars or signal.hold_bars
    last_trigger_index = entry_index + max_hold_bars
    last_exit_index = last_trigger_index + fill_model.exit_lag_bars
    if last_exit_index >= len(bars):
        raise EvaluationError(f"exit fill is outside available bars: {signal.symbol}")

    best_return_bps = 0.0
    for trigger_index in range(entry_index + 1, last_trigger_index + 1):
        trigger_bar = bars[trigger_index]
        trigger_price = _fill_price(trigger_bar, fill_model.price, signal.side, is_entry=False)
        side_return_bps = _side_return_bps(entry_price, trigger_price, signal.side)
        if side_return_bps > best_return_bps:
            best_return_bps = side_return_bps

        reason = _exit_reason(signal, side_return_bps, best_return_bps)
        if reason is None and trigger_index == last_trigger_index:
            reason = "max_hold"
        if reason is None:
            continue

        exit_index = trigger_index + fill_model.exit_lag_bars
        return _ExitSelection(
            exit_bar=bars[exit_index],
            reason=reason,
        )

    raise EvaluationError(f"exit fill is outside available bars: {signal.symbol}")


def _side_return_bps(entry_price: float, current_price: float, side: Side) -> float:
    if side is Side.LONG:
        return (current_price / entry_price - 1.0) * 10_000.0
    return (entry_price / current_price - 1.0) * 10_000.0


def _exit_reason(signal: Signal, side_return_bps: float, best_return_bps: float) -> ExitReason | None:
    if signal.stop_loss_bps is not None and side_return_bps <= -signal.stop_loss_bps:
        return "stop_loss"
    if signal.take_profit_bps is not None and side_return_bps >= signal.take_profit_bps:
        return "take_profit"
    if (
        signal.trailing_stop_bps is not None
        and best_return_bps > 0.0
        and best_return_bps - side_return_bps >= signal.trailing_stop_bps
    ):
        return "trailing_stop"
    return None
```

- [ ] **Step 4: Run engine screen tests**

Run:

```bash
conda run -n quant python -m pytest tests/test_engine_screen.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit deterministic exits**

```bash
git add src/quant_strategies/engine/evaluation.py tests/test_engine_screen.py
git commit -m "feat: evaluate deterministic signal exits"
```

## Task 3: Normalize Runner Signal Metadata And Fillability

**Files:**
- Modify: `tests/test_runner_engine_runner.py`
- Modify: `src/quant_strategies/runner/engine_runner.py`

- [ ] **Step 1: Add failing runner request tests**

Update the import in `tests/test_runner_engine_runner.py`:

```python
from quant_strategies.runner.engine_runner import build_request, evaluate_request, request_json
```

Append these tests:

```python
def test_build_request_preserves_exit_controls_and_flat_signal_metadata():
    raw_signal = signal(index=0, hold_bars=5)
    raw_signal.update(
        {
            "max_hold_bars": 2,
            "take_profit_bps": 150.0,
            "stop_loss_bps": 75.0,
            "trailing_stop_bps": 50.0,
            "metadata": {"source": "explicit"},
            "funding_pressure_bps": 3.25,
            "entry_return_extension_bps": 42.0,
        }
    )

    request = build_request(
        strategy_id="demo",
        rows=bars(100.0, 100.0, 102.0, 101.0),
        signals=[raw_signal],
        fill_model=close_fill(),
        cost_model=zero_cost(),
    )

    engine_signal = request.spec.signals[0]
    assert engine_signal.max_hold_bars == 2
    assert engine_signal.take_profit_bps == 150.0
    assert engine_signal.stop_loss_bps == 75.0
    assert engine_signal.trailing_stop_bps == 50.0
    assert engine_signal.metadata == {
        "entry_return_extension_bps": 42.0,
        "funding_pressure_bps": 3.25,
        "source": "explicit",
    }
    assert '"funding_pressure_bps": 3.25' in request_json(request)


def test_build_request_rejects_duplicate_flat_and_nested_metadata_keys():
    raw_signal = signal()
    raw_signal.update({"metadata": {"funding_pressure_bps": 1.0}, "funding_pressure_bps": 2.0})

    with pytest.raises(RequestBuildError, match="duplicate signal metadata key"):
        build_request(
            strategy_id="demo",
            rows=bars(100.0, 101.0, 102.0, 103.0),
            signals=[raw_signal],
            fill_model=close_fill(),
            cost_model=zero_cost(),
        )


def test_build_request_uses_max_hold_and_exit_lag_for_fillability():
    with pytest.raises(RequestBuildError, match="exit fill is outside"):
        build_request(
            strategy_id="demo",
            rows=bars(100.0, 100.0, 101.0),
            signals=[{**signal(index=0, hold_bars=1), "max_hold_bars": 2}],
            fill_model=FillModelConfig(price="close", entry_lag_bars=1, exit_lag_bars=1),
            cost_model=zero_cost(),
        )
```

- [ ] **Step 2: Run the failing runner request tests**

Run:

```bash
conda run -n quant python -m pytest tests/test_runner_engine_runner.py::test_build_request_preserves_exit_controls_and_flat_signal_metadata tests/test_runner_engine_runner.py::test_build_request_rejects_duplicate_flat_and_nested_metadata_keys tests/test_runner_engine_runner.py::test_build_request_uses_max_hold_and_exit_lag_for_fillability -v
```

Expected: FAIL because raw signal extras are not normalized into the engine request.

- [ ] **Step 3: Implement runner signal normalization**

In `src/quant_strategies/runner/engine_runner.py`, add these constants near `EngineMode`:

```python
_RESERVED_SIGNAL_FIELDS = {
    "symbol",
    "decision_time",
    "as_of_time",
    "side",
    "weight",
    "hold_bars",
    "max_hold_bars",
    "take_profit_bps",
    "stop_loss_bps",
    "trailing_stop_bps",
    "metadata",
}
```

Replace `_signal_from_row()` with:

```python
def _signal_from_row(row: dict[str, Any]) -> Signal:
    try:
        payload = {
            "symbol": row["symbol"],
            "decision_time": _as_datetime(row["decision_time"], "decision_time"),
            "side": row["side"],
            "weight": row.get("weight", 1.0),
            "hold_bars": row.get("hold_bars", 1),
            "metadata": _signal_metadata(row),
        }
        for field in ("max_hold_bars", "take_profit_bps", "stop_loss_bps", "trailing_stop_bps"):
            if field in row and row[field] is not None:
                payload[field] = row[field]
        return Signal(**payload)
    except KeyError as exc:
        field = str(exc.args[0])
        raise RequestBuildError(f"missing required signal field '{field}' for {row.get('symbol', '<unknown>')}") from exc
    except RequestBuildError:
        raise
    except Exception as exc:
        raise RequestBuildError(f"invalid signal for {row.get('symbol')}: {exc}") from exc
```

Add:

```python
def _signal_metadata(row: dict[str, Any]) -> dict[str, Any]:
    raw_metadata = row.get("metadata", {})
    if raw_metadata is None:
        metadata: dict[str, Any] = {}
    elif isinstance(raw_metadata, dict):
        metadata = dict(raw_metadata)
    else:
        raise RequestBuildError(f"signal metadata must be a mapping for {row.get('symbol', '<unknown>')}")

    for key in sorted(set(row).difference(_RESERVED_SIGNAL_FIELDS)):
        if key in metadata:
            raise RequestBuildError(f"duplicate signal metadata key '{key}' for {row.get('symbol', '<unknown>')}")
        metadata[key] = row[key]
    return metadata
```

- [ ] **Step 4: Update runner fillability checks**

In `_assert_fillable()`, replace the fixed exit index calculation with max-hold and exit-lag aware logic:

```python
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
```

Add helper:

```python
def _assert_quote_fill_bar(bar: Bar, fill_name: str) -> None:
    if bar.bid is None or bar.ask is None:
        raise RequestBuildError(
            f"quote fill requires bid and ask on {fill_name} bar: "
            f"{bar.symbol} at {bar.timestamp.isoformat()}"
        )
```

- [ ] **Step 5: Run runner request tests**

Run:

```bash
conda run -n quant python -m pytest tests/test_runner_engine_runner.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit runner normalization**

```bash
git add src/quant_strategies/runner/engine_runner.py tests/test_runner_engine_runner.py
git commit -m "feat: normalize signal metadata into engine requests"
```

## Task 4: Preserve Metadata And Exit Reasons In Artifacts

**Files:**
- Modify: `tests/test_runner_api_cli.py`
- Modify: `src/quant_strategies/runner/artifacts.py`

- [ ] **Step 1: Add failing artifact test**

Append this test to `tests/test_runner_api_cli.py`:

```python
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
    monkeypatch.setattr(data_loader, "load_data", lambda config: LoadedData(rows=rows(100.0, 100.0, 102.0, 103.0)))

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
```

In the existing `test_completed_run_writes_minimal_manifests()`, update the engine schema assertion to:

```python
    assert run_manifest["engine"] == {"evidence_schema": "quant_strategies.engine.evidence/v2"}
```

- [ ] **Step 2: Run the failing artifact test**

Run:

```bash
conda run -n quant python -m pytest tests/test_runner_api_cli.py::test_run_artifacts_preserve_exit_reason_and_signal_metadata -v
```

Expected: FAIL until artifact preferred fields and v2 evidence output are present.

- [ ] **Step 3: Update signal CSV preferred fields**

In `src/quant_strategies/runner/artifacts.py`, replace `write_signals()` with:

```python
def write_signals(result_dir: Path, signals: list[dict[str, Any]]) -> None:
    write_csv(
        result_dir / "signals.csv",
        signals,
        preferred_fields=[
            "symbol",
            "decision_time",
            "as_of_time",
            "side",
            "weight",
            "hold_bars",
            "max_hold_bars",
            "take_profit_bps",
            "stop_loss_bps",
            "trailing_stop_bps",
            "funding_pressure_bps",
            "entry_return_extension_bps",
            "residual_zscore",
            "residual_bps",
            "attribution_score",
            "signal_family",
        ],
    )
```

- [ ] **Step 4: Run artifact tests**

Run:

```bash
conda run -n quant python -m pytest tests/test_runner_api_cli.py::test_run_artifacts_preserve_exit_reason_and_signal_metadata tests/test_runner_api_cli.py::test_completed_run_writes_minimal_manifests -v
```

Expected: PASS, including the existing manifest schema version assertion updated from v1 to v2.

- [ ] **Step 5: Commit artifact preservation**

```bash
git add src/quant_strategies/runner/artifacts.py tests/test_runner_api_cli.py
git commit -m "feat: preserve exit metadata in run artifacts"
```

## Task 5: Update Current Research Strategies

**Files:**
- Modify: `tests/test_crypto_perp_funding_crowding_reversal.py`
- Modify: `tests/test_fx_triangular_residual_reversion.py`
- Modify: `untested/crypto_perp_funding_crowding_reversal.py`
- Modify: `untested/fx_triangular_residual_reversion.py`

- [ ] **Step 1: Update crypto strategy expectations**

In `tests/test_crypto_perp_funding_crowding_reversal.py`, update expected signal dictionaries in `test_generate_signals_fades_same_direction_funding_and_return_extremes()` to include:

```python
            "hold_bars": 3,
            "max_hold_bars": 3,
            "funding_pressure_bps": pytest.approx(2.0),
            "entry_return_extension_bps": pytest.approx(100.0),
            "signal_family": "crypto_perp_funding_crowding_reversal",
```

for BTC, and:

```python
            "hold_bars": 3,
            "max_hold_bars": 3,
            "funding_pressure_bps": pytest.approx(-2.0),
            "entry_return_extension_bps": pytest.approx(-100.0),
            "signal_family": "crypto_perp_funding_crowding_reversal",
```

for ETH.

Append:

```python
def test_generate_signals_emits_optional_exit_controls():
    bars = symbol_rows("BTC-PERP", 100.0, 101.0, 102.0, 0.0003)

    signals = generate_signals(
        bars,
        params(
            min_cross_section=1,
            max_hold_bars=7,
            take_profit_bps=150.0,
            stop_loss_bps=80.0,
            trailing_stop_bps=40.0,
        ),
    )

    assert signals[0]["max_hold_bars"] == 7
    assert signals[0]["take_profit_bps"] == 150.0
    assert signals[0]["stop_loss_bps"] == 80.0
    assert signals[0]["trailing_stop_bps"] == 40.0
```

- [ ] **Step 2: Update FX strategy expectations**

In `tests/test_fx_triangular_residual_reversion.py`, update expected signal dictionaries in the direct and synthetic leg tests to include:

```python
            "hold_bars": 4,
            "max_hold_bars": 4,
            "residual_zscore": pytest.approx(3.0),
            "residual_bps": pytest.approx(20.0),
            "attribution_score": pytest.approx(10.0),
            "signal_family": "fx_triangular_residual_reversion",
```

Append:

```python
def test_generate_signals_emits_optional_exit_controls():
    signals = generate_signals(
        direct_residual_rows([0.0, 0.001, 0.002, 0.0]),
        params(
            max_hold_bars=8,
            take_profit_bps=120.0,
            stop_loss_bps=70.0,
            trailing_stop_bps=35.0,
        ),
    )

    assert signals[0]["max_hold_bars"] == 8
    assert signals[0]["take_profit_bps"] == 120.0
    assert signals[0]["stop_loss_bps"] == 70.0
    assert signals[0]["trailing_stop_bps"] == 35.0
```

- [ ] **Step 3: Run failing strategy tests**

Run:

```bash
conda run -n quant python -m pytest tests/test_crypto_perp_funding_crowding_reversal.py tests/test_fx_triangular_residual_reversion.py -v
```

Expected: FAIL because strategies do not emit the new fields yet.

- [ ] **Step 4: Implement shared exit-control helpers in each strategy file**

In each strategy file, add:

```python
def _optional_positive_float(value: object, name: str) -> float | None:
    if value is None:
        return None
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0.0:
        raise ValueError(f"{name} must be finite and positive")
    return parsed


def _exit_controls(params: Mapping[str, object]) -> dict[str, object]:
    controls: dict[str, object] = {}
    for name in ("take_profit_bps", "stop_loss_bps", "trailing_stop_bps"):
        value = _optional_positive_float(params.get(name), name)
        if value is not None:
            controls[name] = value
    return controls
```

- [ ] **Step 5: Update crypto strategy signal construction**

In `untested/crypto_perp_funding_crowding_reversal.py`, replace:

```python
    hold_bars = int(params.get("hold_bars", params.get("hold_minutes", 480)))
```

with:

```python
    max_hold_bars = _positive_int(
        params.get("max_hold_bars", params.get("hold_bars", params.get("hold_minutes", 480))),
        "max_hold_bars",
    )
    exit_controls = _exit_controls(params)
```

Update calls to `_signal()`:

```python
            signals.append(_signal(candidate, decision_time, as_of_time, "short", weight, max_hold_bars, exit_controls))
```

```python
            signals.append(_signal(candidate, decision_time, as_of_time, "long", weight, max_hold_bars, exit_controls))
```

Replace `_signal()` with:

```python
def _signal(
    candidate: dict[str, Any],
    decision_time: datetime,
    as_of_time: datetime,
    side: str,
    weight: float,
    max_hold_bars: int,
    exit_controls: Mapping[str, object],
) -> dict[str, object]:
    payload: dict[str, object] = {
        "symbol": candidate["symbol"],
        "decision_time": decision_time,
        "as_of_time": as_of_time,
        "side": side,
        "weight": weight,
        "hold_bars": max_hold_bars,
        "max_hold_bars": max_hold_bars,
        "funding_pressure_bps": candidate["funding_pressure_bps"],
        "entry_return_extension_bps": candidate["return_extension_bps"],
        "signal_family": "crypto_perp_funding_crowding_reversal",
    }
    payload.update(exit_controls)
    return payload
```

- [ ] **Step 6: Update FX strategy candidate metadata**

In `untested/fx_triangular_residual_reversion.py`, replace:

```python
    hold_bars = int(params.get("hold_bars", params.get("hold_minutes", 30)))
```

with:

```python
    max_hold_bars = _positive_int(
        params.get("max_hold_bars", params.get("hold_bars", params.get("hold_minutes", 30))),
        "max_hold_bars",
    )
    exit_controls = _exit_controls(params)
```

Change the candidate type inside `generate_signals()`:

```python
    candidates: dict[tuple[str, datetime], list[dict[str, float | int]]] = {}
```

When emitting a signal, replace the current payload with:

```python
        entries = candidates[(symbol, as_of_time)]
        score = sum(float(entry["signal"]) * float(entry["strength"]) for entry in entries)
        if abs(score) <= 1e-12:
            continue
        representative = max(entries, key=lambda entry: abs(float(entry["strength"])))
        decision_time = as_of_time + timedelta(minutes=decision_lag_minutes)
        payload: dict[str, object] = {
            "symbol": symbol,
            "decision_time": decision_time,
            "as_of_time": as_of_time,
            "side": "long" if score > 0.0 else "short",
            "weight": weight,
            "hold_bars": max_hold_bars,
            "max_hold_bars": max_hold_bars,
            "residual_zscore": representative["residual_zscore"],
            "residual_bps": representative["residual_bps"],
            "attribution_score": sum(float(entry["signal"]) * float(entry["attribution_score"]) for entry in entries),
            "signal_family": "fx_triangular_residual_reversion",
        }
        payload.update(exit_controls)
        signals.append(payload)
```

Change `_collect_candidates()` signature so `candidates` is:

```python
    candidates: dict[tuple[str, datetime], list[dict[str, float | int]]],
```

Change `_select_reversion_leg()` to return attribution score:

```python
def _select_reversion_leg(
    triangle: _Triangle,
    points: list[dict[str, Any]],
    index: int,
    residual_sign: int,
    attribution_bars: int,
) -> tuple[str, int, float] | None:
```

Inside `_select_reversion_leg()`, replace the final return logic with:

```python
    leg_type, symbol, synthetic_sign, contribution = max(aligned, key=lambda item: abs(item[3]))
    attribution_score = abs(float(contribution)) * 10_000.0
    if leg_type == "direct":
        return symbol, -residual_sign, attribution_score
    return symbol, residual_sign * synthetic_sign, attribution_score
```

In `_collect_candidates()`, replace:

```python
        symbol, signal = selected
```

with:

```python
        symbol, signal, attribution_score = selected
```

Replace the candidate append with:

```python
            candidates.setdefault((symbol, as_of_time), []).append(
                {
                    "signal": signal,
                    "strength": abs(float(residual_z)),
                    "residual_zscore": float(residual_z),
                    "residual_bps": float(residual_bps),
                    "attribution_score": attribution_score,
                }
            )
```

- [ ] **Step 7: Run strategy tests**

Run:

```bash
conda run -n quant python -m pytest tests/test_crypto_perp_funding_crowding_reversal.py tests/test_fx_triangular_residual_reversion.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit strategy updates**

```bash
git add untested/crypto_perp_funding_crowding_reversal.py untested/fx_triangular_residual_reversion.py tests/test_crypto_perp_funding_crowding_reversal.py tests/test_fx_triangular_residual_reversion.py
git commit -m "feat: emit strategy exit controls and audit metadata"
```

## Task 6: Update Documentation

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README artifact and runner semantics**

In `README.md`, add this paragraph after the existing close-fill causal paragraph:

```markdown
Signals may include optional exit controls: `max_hold_bars`,
`take_profit_bps`, `stop_loss_bps`, and `trailing_stop_bps`. Exit triggers are
confirmed from the configured fill price on completed bars; this runner does not
simulate intrabar stop or target touches. `exit_lag_bars` controls whether the
exit fills on the trigger bar or a later bar. Old `hold_bars`-only signals remain
valid and are treated as max-hold exits.
```

In the artifact section, add:

```markdown
Trade records in `evidence.json` include `exit_reason`, one of `max_hold`,
`take_profit`, `stop_loss`, or `trailing_stop`. Strategy-emitted signal metadata
is preserved as flat columns in `signals.csv`, normalized into signal `metadata`
in `engine_request.json`, and copied into each trade as `signal_metadata`.
Unknown top-level signal fields become metadata unless they are reserved signal
contract fields.
```

In the crypto funding paragraph, add:

```markdown
When an exit trigger closes a trade before max hold, funding cashflows are
computed only over the actual entry-to-exit interval.
```

- [ ] **Step 2: Verify README mentions the new contract**

Run:

```bash
rg -n "max_hold_bars|exit_reason|signal_metadata|intrabar|entry-to-exit" README.md
```

Expected: output includes all five terms.

- [ ] **Step 3: Commit docs**

```bash
git add README.md
git commit -m "docs: document exit controls and signal metadata"
```

## Task 7: Full Verification And Cleanup

**Files:**
- Review all modified files from Tasks 1-6.

- [ ] **Step 1: Run focused test files**

Run:

```bash
conda run -n quant python -m pytest tests/test_engine_models.py tests/test_engine_validate_and_evidence.py tests/test_engine_screen.py tests/test_runner_engine_runner.py tests/test_runner_api_cli.py tests/test_crypto_perp_funding_crowding_reversal.py tests/test_fx_triangular_residual_reversion.py -v
```

Expected: PASS.

- [ ] **Step 2: Run the full suite**

Run:

```bash
conda run -n quant python -m pytest
```

Expected: PASS.

- [ ] **Step 3: Inspect diff for scope**

Run:

```bash
git status --short
git diff --stat HEAD
git diff -- src/quant_strategies/engine/models.py src/quant_strategies/engine/evaluation.py src/quant_strategies/runner/engine_runner.py src/quant_strategies/runner/artifacts.py untested/crypto_perp_funding_crowding_reversal.py untested/fx_triangular_residual_reversion.py README.md
```

Expected: only the planned source, tests, and docs files are modified. Pre-existing untracked `.codegraph/` and `.cursor/` may remain untouched.

- [ ] **Step 4: Record changed-line counts for final report**

Run:

```bash
git diff --stat HEAD
git diff --numstat HEAD
```

Expected: output available for the final response, separated into source, tests, docs, and strategy files.

- [ ] **Step 5: Confirm final tracked state**

Run:

```bash
git status --short
```

Expected: no tracked implementation files remain unstaged. Pre-existing untracked `.codegraph/` and `.cursor/` may remain untouched.

## Engineering Review Addenda

### What Already Exists

- `screen()` already owns deterministic entry/exit fill selection, PnL, cost, and funding accounting; the plan extends this path instead of building a parallel evaluator.
- `Signal`, `Trade`, and `EvidencePacket` already provide strict Pydantic artifact contracts; the plan adds fields there rather than introducing a separate schema layer.
- Runner request construction already translates raw strategy dictionaries into engine models and fail-closed fillability checks; the plan reuses that boundary for exit controls and metadata.
- Existing artifact writers already preserve signals, engine requests, evidence, and manifests; the plan extends preferred fields and schema assertions rather than creating new artifact types.

### NOT In Scope

- Intrabar stop/target simulation: deferred because v1 intentionally uses completed bars and configured fill prices only.
- Exit policy registries/classes: deferred because four scalar controls cover the current downstream need without a new abstraction.
- Portfolio-level exits or cross-signal netting: deferred because this project currently screens independent per-signal trades.
- TOML run-config exit defaults: deferred so strategies own their emitted controls for this change.
- Trigger timestamp/price artifacts: deferred until a consumer needs them; v1 persists only `exit_reason` and `signal_metadata`.

### Failure Modes

- Invalid metadata value such as datetime, NaN, or Infinity: covered by model tests and strict JSON validation; user sees a validation error.
- Missing bars for entry, trigger, or exit lag: covered by runner and engine tests; user sees fail-closed `RequestBuildError` or `EvaluationError`.
- Missing quote fields on a possible trigger/exit bar: covered by runner quote fillability checks; user sees a clear bid/ask error.
- Duplicate flat and nested metadata key: covered by runner tests; user sees a duplicate metadata key error.
- Funding cashflows counted over the wrong interval after early exit: covered by engine funding test; evidence return fields reveal the actual accounting.
- Existing evidence schema tests left at v1: covered by the plan update to `tests/test_engine_validate_and_evidence.py`.

### Test Coverage Diagram

```text
CODE PATHS                                             RESEARCH/USER FLOWS
[+] Signal model contract                              [+] Strategy emits signal dictionaries
  +-- [3/3] exit controls accepted                       +-- [3/3] crypto metadata + controls
  +-- [3/3] invalid bps rejected                         +-- [3/3] FX metadata + controls
  +-- [3/3] metadata strict JSON rejected                +-- [3/3] optional controls omitted/added
[+] screen() exit scan
  +-- [3/3] legacy hold_bars -> max_hold
  +-- [3/3] max_hold_bars override
  +-- [3/3] long take_profit / stop_loss / trailing
  +-- [3/3] short take_profit / stop_loss priority
  +-- [3/3] exit_lag_bars fill timing
  +-- [3/3] early exit funding interval
[+] runner build_request()
  +-- [3/3] reserved fields -> Signal fields
  +-- [3/3] flat extras -> metadata
  +-- [3/3] duplicate metadata rejected
  +-- [3/3] max_hold + exit_lag fillability
[+] artifacts
  +-- [3/3] signals.csv preferred fields
  +-- [3/3] engine_request metadata
  +-- [3/3] evidence v2 + trade exit fields
  +-- [3/3] existing manifest/evidence schema assertions

COVERAGE: planned coverage reaches all new branches; no E2E/browser/eval scope.
Legend: 3/3 means behavior plus edge/error coverage.
```

### Worktree Parallelization

| Step | Modules touched | Depends on |
|------|-----------------|------------|
| Engine contract + exit scan | `src/quant_strategies/engine/`, `tests/` | none |
| Runner request + artifacts | `src/quant_strategies/runner/`, `tests/` | Engine contract |
| Strategy updates | `untested/`, `tests/` | Runner metadata names |
| README + final verification | docs/root, full repo | All prior steps |

Lane A: engine contract -> deterministic exits.
Lane B: strategy updates can start after metadata field names are fixed, but should merge after Lane A.
Lane C: runner/artifacts depends on Lane A and should run sequentially with final docs.
Execution order: implement Lane A first, then Lane B and runner/artifacts with coordination, then docs and full verification.

### Implementation Tasks

- [ ] **T1 (P1, human: ~20min / CC: ~5min)** - engine models - Patch `EvidencePacket.schema_version` literal/default to v2.
  - Surfaced by: Architecture Review D2 - plan changed only `EVIDENCE_SCHEMA_VERSION`.
  - Files: `src/quant_strategies/engine/models.py`, `tests/test_engine_validate_and_evidence.py`
  - Verify: `conda run -n quant python -m pytest tests/test_engine_models.py tests/test_engine_validate_and_evidence.py -v`
- [ ] **T2 (P2, human: ~15min / CC: ~5min)** - plan clarity - Keep the ASCII data-flow diagram in the plan and use it to guide implementation boundaries.
  - Surfaced by: Architecture Review D3 - non-trivial data flow lacked a diagram.
  - Files: `docs/superpowers/plans/2026-05-25-exit-policy-and-signal-metadata.md`
  - Verify: `rg -n "strategy row dicts|EvidencePacket v2" docs/superpowers/plans/2026-05-25-exit-policy-and-signal-metadata.md`
- [ ] **T3 (P1, human: ~20min / CC: ~5min)** - metadata contract - Enforce strict JSON metadata with `allow_nan=False`.
  - Surfaced by: Architecture Review D4 - default `json.dumps()` accepts NaN/Infinity.
  - Files: `src/quant_strategies/engine/models.py`, `tests/test_engine_models.py`
  - Verify: `conda run -n quant python -m pytest tests/test_engine_models.py -v`
- [ ] **T4 (P2, human: ~10min / CC: ~3min)** - engine internals - Remove unused `trigger_bar` from `_ExitSelection`.
  - Surfaced by: Code Quality Review D5 - private helper carried unused state.
  - Files: `src/quant_strategies/engine/evaluation.py`
  - Verify: `conda run -n quant python -m pytest tests/test_engine_screen.py -v`
- [ ] **T5 (P1, human: ~30min / CC: ~8min)** - engine tests - Replace unreachable TP/trailing collision test with short-side exit tests.
  - Surfaced by: Test Review D6 - planned test name claimed an impossible same-bar collision.
  - Files: `tests/test_engine_screen.py`
  - Verify: `conda run -n quant python -m pytest tests/test_engine_screen.py -v`

## Self-Review Checklist

- Spec coverage: Tasks 1-4 cover engine contract, exit reasons, metadata pass-through, evidence v2, and artifacts. Task 5 covers both real research strategies. Task 6 covers README updates. Task 7 covers verification and changed-line counts.
- Scope check: no portfolio exits, intrabar stop simulation, registries, data-loader changes, or run TOML changes are included.
- Type consistency: `max_hold_bars`, `take_profit_bps`, `stop_loss_bps`, `trailing_stop_bps`, `metadata`, `exit_reason`, and `signal_metadata` use the same names across models, runner request JSON, evidence, strategies, tests, and docs.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | not run | none |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | not run | none |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 4 | clean | 6 issues, 0 critical gaps |
| Design Review | `/plan-design-review` | UI/UX gaps | 1 | clean | score: 10/10 -> 10/10, 1 decision |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | not run | none |

- **UNRESOLVED:** 0
- **VERDICT:** ENG CLEARED - ready to implement.
