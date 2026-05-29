# Phase 1 — P1 Trust & Correctness (F2 / F3 / F4) Implementation Plan

> **For agentic workers:** Execute task-by-task with TDD. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Close the three P1 trust gaps that survive after the P0 "one PnL contract" work: make strict suppression-replay the *default* causal check for both the runner quick-run and the validation run (F3), pin the VectorBT Pro oracle's cash scale explicitly (F4), and lock in a regression test proving the validation gate's `net_return` is funding-inclusive (F2).

**Architecture:** The engine kernel is already the single verdict PnL source (P0#2), so F2/F7/F8 are structurally resolved. This phase hardens the *causal* guarantee. The two-directional replay algorithm in `causality.py` is excellent but its suppression half (`scoped ⊆ expected`) runs only under `mode="strict"`, which today is reached only when `paper_readiness.enabled`. We flip strict to the default everywhere, auto-derive row-grid boundaries inside `check_hidden_lookahead`, and split the single `causality_verified` boolean into honest sub-flags (`emitted_replay_verified`, `strict_no_emission_verified`) so a run can never claim a verification it did not perform. We also collapse the byte-identical `_causality_evidence` duplication (an F12 sub-item) because F3 changes that function's contract and editing one correctness policy in two files is the exact risk the review flagged.

**Tech Stack:** Python 3.12, pydantic v2, pytest, conda env `quant`. Run commands with `conda run -n quant <cmd>`.

---

## Re-audit summary (current tree, post-P0)

| Finding | Status now | Phase-1 action |
|---|---|---|
| F2 funding-aware net | **Core resolved** — verdict gates on `EngineBackend.net_return = smoke.sum_signed_trade_activity_net` (funding-inclusive); `verdict_source="engine"` default | Add one regression test; deliberately **defer** funding-stress scenario (avoid speculative addition) |
| F3 strict suppression-replay | **OPEN** — runner always `emitted`; validation strict only if `paper_readiness`; `TODOS.md` open | Make strict default for both; split evidence field; share boundary builder; close TODOS |
| F4 real-vbt golden + init_cash | **Golden tests exist** (`test_..._runs_max_hold_decisions`, `test_golden_engine_and_vbt_agree_on_single_long`); **`init_cash` not set** | Pin `init_cash` explicitly; confirm golden tests unchanged |

**Out of scope (deliberate):** funding-stress scenario (F2 secondary), RowContractMode collapse (F11/Phase 3), other seam dedup (F12/Phase 3). Replay strictness is decoupled from `RowContractMode` here; the `RETAINED` value's only remaining job (strict replay) becomes moot and is removed in Phase 3.

---

## File Structure

- `src/quant_strategies/causality.py` — gains public `strict_replay_boundaries(rows, decisions)` (moved from validation); `check_hidden_lookahead` defaults to strict, auto-derives boundaries, returns split flags; `LookaheadCheckResult` gains `mode`, `emitted_replay_verified`, `strict_suppression_verified`.
- `src/quant_strategies/evidence_semantics.py` — gains shared `causality_evidence_fields(...)`, the single home for the availability→verified policy.
- `src/quant_strategies/data_contract.py` — delete local `_causality_evidence`; call shared one; `NormalizedRows.evidence_quality` threads two flags.
- `src/quant_strategies/runner/artifacts.py` — delete local `_causality_evidence`; `evidence_quality()` + `with_causality_verification()` thread two flags.
- `src/quant_strategies/runner/__init__.py` — `RunResult` gains two flag fields; `_prepare_causality_evidence` passes split flags; `_run_result_evidence_fields` surfaces them.
- `src/quant_strategies/validation/__init__.py` — delete `_strict_replay_boundaries` (moved); always strict; remove `strict_replay` context coupling.
- `src/quant_strategies/validation/vectorbtpro_backend.py` — explicit `init_cash` in `from_signals`.
- `TODOS.md` — remove the closed item.
- Tests: `tests/test_validation_lookahead.py` (fallout), `tests/test_validation_runner.py` (boundary-builder import + new strict-default assertions), `tests/test_runner_*` (new runner peek-to-suppress test), `tests/test_validation_engine_backend.py` (F2 funding-inclusive test), `tests/test_vectorbtpro_backend.py` (init_cash assertion).

---

## Task 1: Move `strict_replay_boundaries` into `causality.py` (shared, generalized)

**Files:**
- Modify: `src/quant_strategies/causality.py` (add public function near `_emitted_boundaries`)
- Modify: `src/quant_strategies/validation/__init__.py` (delete local `_strict_replay_boundaries:801-845`, import from causality)
- Modify: `tests/test_validation_runner.py:458` (call `causality.strict_replay_boundaries`)

- [ ] **Step 1:** In `causality.py`, add a public `strict_replay_boundaries(rows, decisions)` that accepts `NormalizedRows | Sequence[Mapping[str, Any]]`. Body is the current `validation/__init__.py:_strict_replay_boundaries` (lines 801-845) with one change: derive the projection generically.

```python
def strict_replay_boundaries(
    rows: NormalizedRows | Sequence[Mapping[str, Any]],
    decisions: Sequence[StrategyDecision],
) -> tuple[ReplayBoundary, ...]:
    """Row-grid replay boundaries: one per (as_of_time, next_timestamp) per symbol,
    merged with emitted-decision boundaries. Used for strict suppression replay so a
    strategy that peeks ahead to *withhold* a trade is caught at the grid point where
    the trade would otherwise be emitted."""
    expected_by_key: dict[tuple[datetime, datetime], set[str | None]] = {}
    expected_by_asof_symbol: dict[tuple[datetime, str], set[str | None]] = {}
    symbols_by_key: dict[tuple[datetime, datetime], set[str]] = {}
    for decision in decisions:
        key = (decision.as_of_time, decision.decision_time)
        expected_by_key.setdefault(key, set()).add(decision.decision_id)
        symbols_by_key.setdefault(key, set()).add(decision.instrument.symbol)
        expected_by_asof_symbol.setdefault(
            (decision.as_of_time, decision.instrument.symbol), set()
        ).add(decision.decision_id)

    projection = rows.projection_rows() if isinstance(rows, NormalizedRows) else rows
    timestamps_by_symbol: dict[str, list[datetime]] = {}
    for row in projection:
        symbol = row.get("symbol")
        timestamp = row.get("timestamp")
        if isinstance(symbol, str) and _is_aware_datetime(timestamp):
            timestamps_by_symbol.setdefault(symbol, []).append(timestamp)

    for symbol, timestamps in timestamps_by_symbol.items():
        ordered = sorted(dict.fromkeys(timestamps))
        for index, timestamp in enumerate(ordered):
            decision_time = ordered[index + 1] if index + 1 < len(ordered) else timestamp
            key = (timestamp, decision_time)
            expected_by_key.setdefault(key, set())
            symbols_by_key.setdefault(key, set()).add(symbol)

    for (as_of_time, decision_time), symbols in symbols_by_key.items():
        expected = expected_by_key.setdefault((as_of_time, decision_time), set())
        for symbol in symbols:
            expected.update(expected_by_asof_symbol.get((as_of_time, symbol), set()))

    return tuple(
        ReplayBoundary(
            as_of_time=as_of_time,
            decision_time=decision_time,
            expected_decision_ids=frozenset(expected_by_key[(as_of_time, decision_time)]),
            symbols=frozenset(symbols_by_key[(as_of_time, decision_time)]),
        )
        for as_of_time, decision_time in sorted(expected_by_key)
    )
```

Note: `causality.py` already imports `NormalizedRows`, `StrategyDecision`, `ReplayBoundary`, `datetime`, `_is_aware_datetime`. The plain-sequence rows in tests carry `"symbol"`/`"timestamp"` keys, so the generic projection works.

- [ ] **Step 2:** In `validation/__init__.py`, delete `_strict_replay_boundaries` (801-845) and import `strict_replay_boundaries` from `causality`. (Its call site at line ~385 is removed in Task 5.)

- [ ] **Step 3:** Update `tests/test_validation_runner.py:458` from `validation._strict_replay_boundaries(normalized, [])` to `from quant_strategies.causality import strict_replay_boundaries` and `strict_replay_boundaries(normalized, [])`.

- [ ] **Step 4:** Run `conda run -n quant pytest tests/test_validation_runner.py -q`. Expected: PASS.

- [ ] **Step 5:** Commit: `git add -A && git commit -m "Move strict_replay_boundaries into causality (shared)"`

---

## Task 2: Strict-default `check_hidden_lookahead` with split verification flags

**Files:**
- Modify: `src/quant_strategies/causality.py` (`LookaheadCheckResult`, `check_hidden_lookahead`)
- Test: `tests/test_validation_lookahead.py`

- [ ] **Step 1 (TDD):** Add a failing test asserting the split flags and strict default. In `tests/test_validation_lookahead.py`:

```python
def test_strict_is_default_and_reports_split_flags():
    # A causal strategy: emits exactly the baseline decisions on any prefix.
    rows = [bar(0, 100.0), bar(1, 101.0), bar(2, 102.0)]  # helper already in module
    baseline = causal_decisions(rows)  # emits one long at minute 0
    result = check_hidden_lookahead(
        generate_decisions=lambda r, p: causal_decisions(r),
        rows=rows,
        params={},
        baseline_decisions=baseline,
        strategy_id="caus",
    )  # no mode= -> must default to strict
    assert result.mode == "strict"
    assert result.passed is True
    assert result.emitted_replay_verified is True
    assert result.strict_suppression_verified is True
```

(Reuse/添加 the module's existing `bar`/decision helpers; if no `causal_decisions` helper exists, inline a tiny generator that returns the baseline decision when its entry bar is present in `r`.)

- [ ] **Step 2:** Run it: `conda run -n quant pytest tests/test_validation_lookahead.py::test_strict_is_default_and_reports_split_flags -v`. Expected: FAIL (`mode` attr missing / defaults to emitted).

- [ ] **Step 3:** Extend `LookaheadCheckResult`:

```python
@dataclass(frozen=True)
class LookaheadCheckResult:
    passed: bool
    violations: tuple[str, ...] = ()
    mode: ReplayMode = "emitted"
    emitted_replay_verified: bool = False
    strict_suppression_verified: bool = False
```

- [ ] **Step 4:** Rewrite `check_hidden_lookahead` so it defaults to strict, auto-derives boundaries, and tracks both sub-flags. Signature default `mode: ReplayMode = "strict"`. Replace the early boundary guards (62-77) with auto-derivation; track `emitted_ok`/`suppression_ok`; build results with the new fields.

```python
def check_hidden_lookahead(
    generate_decisions: DecisionGenerator,
    *,
    rows: NormalizedRows | Sequence[Mapping[str, Any]],
    params: Mapping[str, Any],
    baseline_decisions: list[StrategyDecision],
    strategy_id: str,
    mode: ReplayMode = "strict",
    boundaries: Sequence[ReplayBoundary] | None = None,
) -> LookaheadCheckResult:
    if boundaries is not None:
        replay_boundaries = tuple(boundaries)
    elif mode == "strict":
        replay_boundaries = strict_replay_boundaries(rows, baseline_decisions)
    else:
        replay_boundaries = _emitted_boundaries(baseline_decisions)

    # Nothing to replay (no rows/decisions): vacuously verified, preserves empty-run behaviour.
    if not replay_boundaries:
        return LookaheadCheckResult(
            passed=True, mode=mode,
            emitted_replay_verified=True,
            strict_suppression_verified=(mode == "strict"),
        )

    row_index = _visible_row_index(rows)
    visible_rows_cache: dict[tuple[datetime, datetime], tuple[Mapping[str, Any], ...]] = {}
    replay_decision_ids_cache: dict[tuple[datetime, datetime], frozenset[str | None]] = {}
    replay_decisions_cache: dict[tuple[datetime, datetime], tuple[StrategyDecision, ...]] = {}
    replay_params = frozen_params(params)
    for boundary in replay_boundaries:
        cache_key = (boundary.as_of_time, boundary.decision_time)
        replay_decisions = replay_decisions_cache.get(cache_key)
        if replay_decisions is None:
            replay_rows = _visible_rows_for_boundary(
                row_index, boundary, visible_rows_cache=visible_rows_cache
            )
            try:
                replay_output = generate_decisions(replay_rows, replay_params)
            except SystemExit as exc:
                return LookaheadCheckResult(
                    passed=False, mode=mode,
                    violations=(f"hidden_lookahead_check_failed: SystemExit: {exc}",),
                )
            except Exception as exc:
                return LookaheadCheckResult(
                    passed=False, mode=mode,
                    violations=(f"hidden_lookahead_check_failed: {type(exc).__name__}: {exc}",),
                )
            parsed_decisions, violations = validate_decision_output(
                replay_output, strategy_id=strategy_id
            )
            if violations:
                return LookaheadCheckResult(
                    passed=False, mode=mode,
                    violations=(f"hidden_lookahead_check_failed: {'; '.join(violations)}",),
                )
            replay_decisions = tuple(parsed_decisions)
            replay_decisions_cache[cache_key] = replay_decisions

        replay_decision_ids = replay_decision_ids_cache.get(cache_key)
        if replay_decision_ids is None:
            replay_decision_ids = frozenset(r.decision_id for r in replay_decisions)
            replay_decision_ids_cache[cache_key] = replay_decision_ids

        if not boundary.expected_decision_ids.issubset(replay_decision_ids):
            return LookaheadCheckResult(
                passed=False, mode=mode, violations=("hidden_lookahead_detected",),
            )
        if mode == "strict":
            scoped_decision_ids = frozenset(
                r.decision_id for r in replay_decisions if _decision_matches_boundary(r, boundary)
            )
            if not scoped_decision_ids.issubset(boundary.expected_decision_ids):
                return LookaheadCheckResult(
                    passed=False, mode="strict",
                    emitted_replay_verified=True,
                    strict_suppression_verified=False,
                    violations=("hidden_lookahead_suppression_detected",),
                )

    return LookaheadCheckResult(
        passed=True, mode=mode,
        emitted_replay_verified=True,
        strict_suppression_verified=(mode == "strict"),
    )
```

- [ ] **Step 5:** Run the new test (PASS) and the whole lookahead suite: `conda run -n quant pytest tests/test_validation_lookahead.py -q`. Fix fallout: tests that called `check_hidden_lookahead` with no `mode=` now run strict. For each failure, decide: if it asserts genuine emitted-only behavior, pass `mode="emitted"` explicitly; if it tests a causal strategy it should still pass under strict. Keep the deliberately-emitted tests by adding `mode="emitted"`.

- [ ] **Step 6:** Commit: `git commit -am "Strict suppression-replay by default with split verification flags"`

---

## Task 3: Single `causality_evidence_fields`; thread split flags through evidence

**Files:**
- Modify: `src/quant_strategies/evidence_semantics.py` (add shared function)
- Modify: `src/quant_strategies/data_contract.py` (delete local copy:929; use shared; `evidence_quality` signature)
- Modify: `src/quant_strategies/runner/artifacts.py` (delete local copy:155; use shared; `evidence_quality`/`with_causality_verification` signatures)
- Modify: `src/quant_strategies/runner/__init__.py` (`RunResult` fields; `_run_result_evidence_fields`)

- [ ] **Step 1:** Add to `evidence_semantics.py`:

```python
def causality_evidence_fields(
    data_availability_status: object,
    *,
    emitted_replay_verified: bool,
    strict_no_emission_verified: bool,
) -> dict[str, object]:
    """Single home for the availability->verification policy shared by the row
    contract and the runner artifacts. `causality_verified` is True only when the
    information set is complete AND both replay halves verified."""
    if data_availability_status == "complete":
        emitted = bool(emitted_replay_verified)
        strict = bool(strict_no_emission_verified)
        verified = emitted and strict
        warnings: list[str] = []
        if not strict:
            warnings.append("strict_suppression_replay_not_verified")
        if not verified:
            warnings.append("runner_causality_not_verified")
    else:
        emitted = False
        strict = False
        verified = False
        availability_warning = {
            "invalid": "available_at_invalid",
            "partial": "available_at_partial",
        }.get(str(data_availability_status), "available_at_missing")
        warnings = [availability_warning, "runner_causality_not_verified"]
    return {
        "causality_verified": verified,
        "emitted_replay_verified": emitted,
        "strict_no_emission_verified": strict,
        "evidence_quality_warnings": warnings,
    }
```

- [ ] **Step 2:** In `data_contract.py`: delete `_causality_evidence` (929-949); `from quant_strategies.evidence_semantics import causality_evidence_fields`; change `NormalizedRows.evidence_quality` (458) to:

```python
    def evidence_quality(
        self, *, emitted_replay_verified: bool = False, strict_no_emission_verified: bool = False
    ) -> dict[str, Any]:
        payload = {
            "data_availability_status": self.data_availability_status,
            "availability_coverage": self.availability_coverage,
            "row_contract": self.row_contract_summary(),
        }
        payload.update(
            causality_evidence_fields(
                self.data_availability_status,
                emitted_replay_verified=emitted_replay_verified,
                strict_no_emission_verified=strict_no_emission_verified,
            )
        )
        return payload
```

- [ ] **Step 3:** In `runner/artifacts.py`: delete `_causality_evidence` (155-175); import `causality_evidence_fields`; update the two helpers:

```python
def evidence_quality(
    config: RunConfig,
    rows: Sequence[Mapping[str, Any]] | NormalizedRows,
    *,
    emitted_replay_verified: bool = False,
    strict_no_emission_verified: bool = False,
) -> dict[str, Any]:
    return compact_evidence_quality(
        _normalized_rows(config, rows).evidence_quality(
            emitted_replay_verified=emitted_replay_verified,
            strict_no_emission_verified=strict_no_emission_verified,
        )
    )


def with_causality_verification(
    evidence_quality_payload: Mapping[str, Any],
    *,
    emitted_replay_verified: bool,
    strict_no_emission_verified: bool,
) -> dict[str, Any]:
    payload = compact_evidence_quality(evidence_quality_payload)
    payload.update(
        causality_evidence_fields(
            payload.get("data_availability_status"),
            emitted_replay_verified=emitted_replay_verified,
            strict_no_emission_verified=strict_no_emission_verified,
        )
    )
    return payload
```

- [ ] **Step 4:** In `runner/__init__.py`: add to `RunResult` (after line 45):

```python
    emitted_replay_verified: bool = False
    strict_no_emission_verified: bool = False
```

and in `_run_result_evidence_fields` (576) add:

```python
        "emitted_replay_verified": bool(evidence_quality.get("emitted_replay_verified")),
        "strict_no_emission_verified": bool(evidence_quality.get("strict_no_emission_verified")),
```

- [ ] **Step 5:** Fix remaining callers of the changed signatures (search `artifacts.evidence_quality(`, `with_causality_verification(`, `.evidence_quality(causality_verified=`). Replace `causality_verified=X` keyword with the two-flag form. Run `conda run -n quant pytest tests/test_runner_artifacts.py tests/test_data_contract*.py -q` (adjust to actual filenames). Expected: PASS.

- [ ] **Step 6:** Commit: `git commit -am "Single causality_evidence_fields; surface emitted/strict replay flags"`

---

## Task 4: Runner runs strict by default; runner-level peek-to-suppress regression

**Files:**
- Modify: `src/quant_strategies/runner/__init__.py` (`_prepare_causality_evidence:249`)
- Test: a runner integration test file (use the existing one that drives `run_config`; e.g. `tests/test_runner.py` or `tests/test_runner_smoke.py` — pick the one with strategy fixtures)

- [ ] **Step 1 (TDD):** Add a failing runner-level test: a strategy that peeks ahead to suppress a losing trade must yield `causality_verified == False` (assessment `smoke_unverified`), not pass. Write a tiny strategy fixture file under the test's tmp strategy dir whose `generate_decisions` suppresses a trade when a *future* row is below threshold:

```python
def test_run_config_flags_peek_to_suppress_strategy(tmp_path, ...):
    # strategy: long at the first bar UNLESS a later bar dips >2% (peek-to-suppress)
    strategy_src = '''
from quant_strategies.decisions import StrategyDecision
def generate_decisions(rows, params):
    if len(rows) < 1:
        return []
    entry = rows[0]
    future_dip = any(r["close"] < entry["close"] * 0.98 for r in rows[1:])
    if future_dip:
        return []  # suppress using future knowledge
    return [ _long_decision(entry) ]
'''
    # rows include a later dip -> baseline suppresses -> emitted replay misses it
    result = run_config(write_config(..., rows_with_later_dip))
    assert result.causality_verified is False
    assert result.strict_no_emission_verified is False
    assert result.assessment_status == "smoke_unverified"
```

(Model the fixture on existing runner tests in the repo for config/rows/strategy wiring; `_long_decision` mirrors an existing fixture helper.)

- [ ] **Step 2:** Run it: expect FAIL today (emitted mode → `causality_verified` True / `smoke_passed`).

- [ ] **Step 3:** Change `_prepare_causality_evidence` to pass the split flags from the (now strict-by-default) result:

```python
def _prepare_causality_evidence(
    config: config_module.RunConfig,
    execution: StrategyExecutionResult,
    events: RunnerStageEmitter,
) -> tuple[LookaheadCheckResult, dict[str, object]]:
    with events.stage("causality_check", strategy_id=config.strategy_id, mode="strict"):
        causality = _check_causality(config, execution)
    evidence_quality = artifacts.with_causality_verification(
        execution.evidence_quality,
        emitted_replay_verified=causality.emitted_replay_verified,
        strict_no_emission_verified=causality.strict_suppression_verified,
    )
    return causality, evidence_quality
```

`_check_causality` (458) needs no `mode=`/`boundaries=` — strict is the default and boundaries auto-derive from `execution.normalized_rows`.

- [ ] **Step 4:** Run the new test (PASS) and the full runner test files. Fix fallout: any causal fixture should still report `causality_verified True`. If a fixture was secretly non-causal, fix the fixture, not the check.

- [ ] **Step 5:** Commit: `git commit -am "Runner quick-run runs strict suppression-replay by default"`

---

## Task 5: Validation runs strict by default

**Files:**
- Modify: `src/quant_strategies/validation/__init__.py` (context `strict_replay` field:81/167; causality call:374-389; `_validation_row_contract_mode` coupling unchanged for the *row contract*, only replay decoupled)
- Test: `tests/test_validation_lookahead.py` or `tests/test_validation_runner.py`

- [ ] **Step 1 (TDD):** Add/confirm a validation-level test that a peek-to-suppress strategy fails the validation run (`hard_no` with `hidden_lookahead_suppression_detected`) even when `paper_readiness` is disabled (the default). If an equivalent test exists only under paper_readiness, add the default-path variant.

- [ ] **Step 2:** Run it: expect FAIL today (default validation = emitted).

- [ ] **Step 3:** Simplify the causality call (lines 374-389) to always strict with auto-derived boundaries, and drop the `strict_replay`-conditional:

```python
        with context.event_emitter.stage(
            "causality_check",
            strategy_id=context.config.strategy_id,
            window_id=window.id,
            mode="strict",
            decision_count=len(decisions),
        ) as causality_event:
            lookahead = check_hidden_lookahead(
                execution.generate_decisions,
                rows=execution.normalized_rows,
                params=execution.frozen_params,
                baseline_decisions=decisions,
                strategy_id=context.config.strategy_id,
            )
            if not lookahead.passed:
                causality_event.fail(
                    _event_failure_message(lookahead.violations, "hidden_lookahead_check_failed")
                )
```

Remove the `strict_replay` field from the context dataclass (81) and its assignment (167); remove the now-unused `ReplayBoundary` import if nothing else uses it. Leave `_validation_row_contract_mode` (the row-contract strictness) intact — that is Phase 3's concern; only the *replay* strictness is decoupled here.

- [ ] **Step 4:** Run `conda run -n quant pytest tests/test_validation_runner.py tests/test_validation_lookahead.py -q`. Fix fallout (paper_readiness tests that assumed emitted on the default path).

- [ ] **Step 5:** Commit: `git commit -am "Validation runs strict suppression-replay by default"`

---

## Task 6: F4 — pin VectorBT Pro `init_cash` explicitly

**Files:**
- Modify: `src/quant_strategies/validation/vectorbtpro_backend.py:105-117`
- Test: `tests/test_vectorbtpro_backend.py`

- [ ] **Step 1:** Add `init_cash=100.0` to the `from_signals` call (vbt's conventional default, made explicit so the verdict-oracle's return scale is pinned and version-independent):

```python
            portfolio = vbt.Portfolio.from_signals(
                close,
                long_entries=long_entries,
                long_exits=long_exits,
                short_entries=short_entries,
                short_exits=short_exits,
                fees=fees,
                slippage=slippage,
                size=size,
                size_type="valuepercent",
                cash_sharing=True,
                group_by=True,
                init_cash=100.0,
            )
```

- [ ] **Step 2:** Run the real-vbt golden tests: `conda run -n quant pytest tests/test_vectorbtpro_backend.py::test_vectorbtpro_backend_runs_max_hold_decisions tests/test_agreement_oracle.py::test_golden_engine_and_vbt_agree_on_single_long -v`. Expected: PASS unchanged (proves `init_cash` does not move the return scale for `valuepercent` sizing within [0,1] weights).

- [ ] **Step 3:** Update any mocked test that asserts on the captured `from_signals` kwargs to include `init_cash` (search `from_signals` kwargs assertions in the test file). Run `conda run -n quant pytest tests/test_vectorbtpro_backend.py -q`.

- [ ] **Step 4:** Commit: `git commit -am "Pin VectorBT Pro init_cash explicitly (F4)"`

---

## Task 7: F2 — regression test proving the gated `net_return` is funding-inclusive

**Files:**
- Test: `tests/test_validation_engine_backend.py`

- [ ] **Step 1:** Add a test that builds a crypto-perp fixture (decisions + rows with funding events) where the price path is positive but funding is large and negative, runs `EngineBackend().run(...)`, and asserts the *gated* metric is funding-inclusive and negative:

```python
def test_engine_backend_net_return_is_funding_inclusive():  # F2
    # gross price path > 0, but funding cost drives the gated net below zero.
    backend = EngineBackend()
    result = backend.run(
        decisions=[long_perp_decision()],
        rows=perp_rows_with_negative_funding(),  # entry<exit price, funding rate strongly positive on a long => negative funding pnl
        config=scenario_run_config(data_kind="crypto_perp_funding"),
    )
    assert result.status == "completed"
    assert result.metrics["gross_return"] > 0.0
    assert result.metrics["funding_return"] < 0.0
    assert result.metrics["net_return"] < 0.0  # the number the verdict gates on includes funding
    assert result.metrics["net_return"] == pytest.approx(
        result.metrics["gross_return"] + result.metrics["funding_return"]
        - result.metrics["cost_return"]
    )
```

(Model fixtures on existing `tests/test_validation_engine_backend.py` helpers; funding sign for a long is `-direction*rate`, so a positive funding rate yields negative funding pnl for a long.)

- [ ] **Step 2:** Run it: `conda run -n quant pytest tests/test_validation_engine_backend.py::test_engine_backend_net_return_is_funding_inclusive -v`. Expected: PASS (this documents the already-correct P0#2 behavior and guards against regression).

- [ ] **Step 3:** Commit: `git commit -am "Regression test: validation gate net_return is funding-inclusive (F2)"`

---

## Task 8: Close TODOS.md and verify the whole suite

**Files:**
- Modify: `TODOS.md`

- [ ] **Step 1:** Remove the now-closed suppression-replay line from `TODOS.md` (the file's only entry). If it becomes empty, leave a single line noting no open items, or delete the file if the repo convention allows.

- [ ] **Step 2:** Full suite: `conda run -n quant pytest -q`. Expected: all green (≥615 + new tests).

- [ ] **Step 3:** Report changed-line counts (`git diff --stat <phase-base>..HEAD`), separating src/tests/docs.

- [ ] **Step 4:** Commit: `git commit -am "Close suppression-replay TODO"`

---

## Self-Review

1. **Spec coverage:** F2 → Task 7. F3 → Tasks 1-5 + Task 8 (strict default both paths, split evidence, shared boundary builder, TODOS). F4 → Task 6 (init_cash; golden tests pre-exist). _causality_evidence dedup (F12 sub-item, forced by F3) → Task 3.
2. **Placeholder scan:** Test fixtures reference repo helpers (`bar`, `decision`, `_long_decision`, perp helpers) that must be matched to the actual test modules at implementation time — that is fixture-wiring, not logic ambiguity; the assertions and production code are complete.
3. **Type consistency:** `emitted_replay_verified` / `strict_no_emission_verified` (evidence + RunResult) vs `strict_suppression_verified` (LookaheadCheckResult). The mapping is deliberate: the result's `strict_suppression_verified` flows into the evidence's `strict_no_emission_verified`. Keep these names exactly; do not unify (the result names the *check*, the evidence names the *guarantee*).
4. **Risk:** Flipping strict default changes behavior for every `check_hidden_lookahead` caller and validation default. Mitigation: run lookahead + runner + validation suites after Tasks 2/4/5 and fix fallout per-test (emitted-only tests get explicit `mode="emitted"`; non-causal fixtures get fixed). Watch `tests/test_phase5_performance.py:211` runtime budget — strict adds grid-boundary replays; the fixture is small so it should stay within budget, but verify.

## Verification gate for the phase
- `conda run -n quant pytest -q` fully green.
- New tests: runner peek-to-suppress (Task 4), validation peek-to-suppress default path (Task 5), funding-inclusive net (Task 7), split-flags/strict-default (Task 2).
- `/code-review` on the phase diff; address findings; re-run suite.
