# `quant_strategies` — Foundation Review (Senior Quant Researcher Lens)

**Date:** 2026-05-28
**Reviewer:** Claude (Opus 4.7, 1M ctx) — synthesizing 5 fresh-context lens subagents (onboarding, architecture, senior engineering, adversarial, senior quant researcher) plus first-hand source inspection and a measured `run_config` profile.
**Repo state at review:** branch `main`, working tree dirty (`?? PRD.md` untracked at review start), index has 81 source files, 5,817 LOC src + ~10,600 LOC tests/docs.
**User concerns (locked scope):**

1. Whole-repo foundation; no bias toward existing artifacts — rewrites are on the table.
2. Over-engineering vs the actual ontology.
3. Wall-clock latency of one `run_config()` call and iteration cost for `quant_autoresearch`.
4. Docs vs code drift.

> **No subagent saw this review's draft findings.** Each lens read source independently.
> The PRD is treated as a claim to verify, not authority.

---

## 1. Executive verdict

**The foundation is honest at the artifact layer, materially under-built at the schema layer, mis-named at the metrics layer, and structurally heavier than its actual ontology warrants.**

You should not green-light promotion decisions off this foundation today. The single most consequential gap is that the **runner never executes the lookahead replay check** that `PRD.md` §NFR-CAUSALITY calls "foundational," yet completes runs with `assessment_status="smoke_passed"`. Several PRD G1 axes (options, futures, multi-leg, intent, vol-target sizing, side-of-book distinct from direction) are simply absent from `StrategyDecision`. The `sum_weighted_trade_*_return` family of metrics is named exactly the way `PRD.md` §G2 forbids — a sum of weighted per-trade activity dressed as "return". The `paper_candidate` label is awarded on mechanical gates with no statistical evidence, again exactly the pattern §G2 forbids by name.

The good news: bounded contexts are clean, no cycles, `StrategyDecision` is a tight authoritative contract at the strategy boundary, `validation/lookahead.py` is well-shaped, the smoke engine math is internally consistent and the auditability chain (`strategy_snapshot.py` → `config.toml` → `data_manifest.json` → `decision_records.jsonl` → `signals.csv` → `evidence.json`) actually reconstructs every reported number. None of the bad news justifies a rewrite; every BLOCKER and HIGH below has a focused root-cause refactor.

**Over-engineering verdict:** Mild but real. Two files (validation god-function, engine parallel ontology) absorb complexity that belongs elsewhere. `runner/strategy_loader.py` is a dead pass-through. `_FrozenDict` is a duplicate of `boundary.FrozenMapping`. `ValidationBackendError`/`ValidationDataError` are defined and never raised. `ValidationBackend` Protocol has one production impl. None of this is catastrophic; all of it is fixable with deletions and method extractions, not new layers.

**Performance verdict:** A single `run_config` of `runs/simple_momentum_spy_daily.toml` (1 month SPY 1-min, ~16,640 rows, 1 decision) measures **~2.9 s wall-clock** in-process and **~3.6 s cold-CLI** (1.6 s of which is just `import quant_strategies.runner` because `quant_data → polygon SDK` are eagerly imported transitively). The hot path is dominated by overhead the strategy never asked for: `boundary.frozen_rows` deepcopy of every row (~0.55 s), `runner/artifacts.write_strategy_input_rows` JSONL+CSV write of every input row (~0.53 s), `psycopg2._connect` per run (~0.62 s), `engine_runner.request_json` (~0.35 s). All five `runs/*.toml` configs use default `artifact_profile="full"`, which writes **12 artifact files per run**, two of them (`strategy_input_rows.csv` and `.jsonl`) duplicating the same input data. For `quant_autoresearch` driving 100 candidates this is a 100× tax on overhead instead of research. Realistic budget to land: **< 1 s per candidate** with no change to math correctness.

---

## 2. Scope and evidence inspected

| Surface | What was read | Reviewer |
|---|---|---|
| Repo manifests | `pyproject.toml`, `runs/*.toml`, `.gitignore`, top-level structure | self |
| Agent contract | `AGENTS.md` (= `CLAUDE.md` symlink), `PRD.md`, `README.md`, `docs/quant-autoresearch-consumer.md` | self |
| Decision contract | `decisions/*` | self, onboarding, architecture, quant |
| Smoke engine | `engine/*` | self, architecture, quant, adversarial |
| Runner | `runner/*` (12 modules) | self, onboarding, architecture, eng, adversarial |
| Validation | `validation/*` (16 modules incl. `lookahead.py`, `policy.py`, `vectorbtpro_backend.py`, `capabilities.py`) | onboarding, architecture, eng, adversarial, quant |
| Cross-cutting | `boundary.py`, `evidence_semantics.py`, `provenance.py` | self, eng, quant |
| Tests | `tests/test_*.py` (36 files, ~10.6k LOC) — sampled `test_phase5_performance.py`, `test_strategy_docstrings.py`, `test_validation_lookahead.py`, `test_validation_backends_and_policy.py`, `test_validation_artifacts.py` | eng, quant |
| Strategies | `examples/strategies/simple_momentum.py`, `untested/crypto_perp_funding_crowding_reversal.py` (head), `untested/*` LOC | self, onboarding, quant |
| Live run | `runs/simple_momentum_spy_daily.toml` → `results/2026-05-28T051332Z-simple_momentum/` with cProfile | self |
| Docs hygiene | `docs/superpowers/{plans,specs}` (empty), `docs/reviews/` (empty), PRD git status | self |

Skipped (out of locked scope): `openspec/`, `.codex/`, `.cursor/`, `.worktrees/`, `.claude/`, `researched/<frozen-package>/` internals.

---

## 3. Intended foundation model (first principles)

Strip everything back to what the PRD actually says this thing is *for*:

> One autonomous research agent (`quant_autoresearch`) and one senior quant researcher (Season) iterate on strategies. For each candidate, the foundation:
>
> 1. accepts a pure strategy function and a config,
> 2. loads data once via `quant-data`,
> 3. runs the strategy in a way that proves the strategy could not have peeked into the future,
> 4. converts decisions to a deterministic trade-level PnL with honestly-labelled units,
> 5. writes immutable artifacts that let any reviewer reconstruct every number,
> 6. classifies the candidate into `hard_no` / `mechanical_pass` / `watchlist` / `paper_candidate` — **none of which authorizes paper or live trading**.

Anything that is not in service of those six is dead weight. Anything that *is* in service of those six but isn't shipped is a gap.

**The minimal foundation has six load-bearing things, no more:**

```
decisions/        : Strategy contract (Protocol + frozen schema, JSON-roundtrippable)
boundary.py       : One immutable view of rows+params, used by every executor
runner/           : One thin orchestrator: load → execute (frozen) → screen → write
engine/           : One pure smoke kernel: rows + signals → trades + scores
validation/       : One pure harness on top of the runner: multi-window × scenarios + lookahead + policy
artifacts/        : One artifact taxonomy with a strict naming + hashing contract
```

Backends are a real variability point (smoke vs vbt vs future). One Protocol earns its keep there. Everywhere else, abstractions should justify themselves by exhibiting two real implementations or a real boundary.

---

## 4. Project ontology — intended vs implemented

| Concept | Intended (PRD §G1/§G3/§Glossary) | Implemented | Gap |
|---|---|---|---|
| `Strategy` | Protocol-typed pure function | `Callable[[Sequence[Mapping], Mapping], list[StrategyDecision]]` alias (`decisions/strategy_loader.py`) | **No `Protocol` exported.** Authors copy `simple_momentum.py`. (quant H10) |
| `StrategyDecision` | The single authoritative output | Frozen Pydantic, `as_of_time ≤ decision_time` enforced at construction | Solid as far as it goes. |
| `Direction` | long / short / **flat** | `Literal["long","short","flat"]` — but `flat` is rejected by smoke adapter and unsupported by vbt | "Flat" is type-legal, unexecutable. Two adapters reject independently. |
| `Side of book` (buy/sell distinct from net direction) | Required | Not modeled — `Direction` IS side | **Missing.** |
| `Intent` (open/close/adjust/roll) | Required | Not modeled — implicit "enter on `decision_time + entry_lag`, hold `max_hold_bars`" | **Missing.** |
| `InstrumentKind` | equity, FX, crypto-perp, **futures (expiry+multiplier)**, **options (strike/expiry/put-call/settlement)** | `Literal["equity_or_etf","fx_pair","crypto_perp"]` | **Futures, options absent at the type level.** |
| Multi-leg structures | Required ("one decision, multiple legs, joint exit policy") | `StrategyDecision.instrument: InstrumentRef` — singular | **Missing.** A pair trade is two unrelated decisions, no joint exit. |
| `SizingKind` | target_weight / target_notional / target_contracts / **vol-targeted** | `Literal["target_weight","notional"]` — but `notional` is rejected by smoke and vbt | Only one sizing mode actually works. |
| `ExitPolicy` | Time, threshold, **expiry**, **event** | `max_hold_bars`, stop/take/trailing in bps — and vbt drops the thresholds silently as `unsupported_semantics` | Threshold exits exist in the smoke model only; expiry/event exits absent. |
| `Observation` lineage | `ObservationRef(symbol, timestamp, field, source)` carried with every decision | Schema present, **never inspected by runner/engine** | Carries the data but no foundation code consumes it. (onboarding M2) |
| `Signal` (engine-layer) | "No parallel representation in the math layer" (§G3) | `engine.Signal`, `engine.Bar`, `engine.FillModel`, `engine.CostModel`, `engine.ValidationConfig`, `engine.ValidationReport` mirror decision+runner shapes; dict-intermediate `signal row` is implicit at `runner→engine` boundary | **G3 violation.** Three contract shapes in flight: `StrategyDecision` → signal-row-dict → `Signal`. |
| `Kernel` (shared execution boundary) | "A single causal-invariant kernel shared by runner and validation" | `runner/execution.execute_strategy_run` is shared (validation imports it) — confirmed | Real and working. ✓ |
| `Frozen` idiom | "A single declared freezing idiom" (§G3) | `boundary.FrozenMapping` AND `validation.matrix._FrozenDict` | Two idioms. (onboarding S6, eng F8) |
| `paper_candidate` | "no `paper_candidate` without statistical evidence" (§G2) | Awarded on six mechanical gates only (`policy.py:461-466`) | **G2 violation by label.** (adversarial H1, quant H3) |
| `return_model` | Numbers must be "named in a way that does not overstate" (§G2) | `evidence_semantics.return_model = "smoke_score.sum_weighted_trade_net_return"`, a sum of per-trade activity | **G2 violation by name.** (adversarial H2, quant H2) |
| Eligibility flags | "all outputs are advisory; no output flips eligibility autonomously" (§NG1, §NFR-AGENT-FRIENDLY) | Hard-coded `False` in `evidence_semantics.py`; reinforced via `object.__setattr__` in `ValidationPolicyDecision.default_advisory_fields` | **Holds** — but only via a side-effect inside a model_validator. Removing that validator silently regresses. |
| Causality invariant | "no run completes with `assessment_status` other than `runner_failed` if any decision violates [causality]" (§NFR-CAUSALITY) | Runner **never** calls `check_hidden_lookahead`. Hard-codes `causality_verified: False`. Completes as `smoke_passed`. | **Blocker.** The PRD's central invariant is enforced only inside the validation harness. (adversarial BLOCKER, quant BLOCKER) |

---

## 5. ASCII map — actual vs minimal

### Actual (post-shared-boundary refactor)

```
   ┌──────────────────────────┐
   │      decisions/          │  StrategyDecision (frozen, Pydantic)
   └────────┬─────────────────┘
            │
   ┌────────▼─────────────────┐         ┌─────────────────────────────┐
   │      boundary.py          │←───────│   evidence_semantics.py     │
   │  frozen_rows/frozen_params│         │   (hard-coded "advisory")   │
   │   ⚠️ deepcopy on every    │         └─────────────────────────────┘
   │   call, called 3–6× per   │
   │   validation scenario     │
   └────────┬─────────────────┘
            │
            │                            ┌─────────────────────────────────┐
            │                            │     engine/                     │
            │                            │  Signal/Bar/FillModel/CostModel │
            │                            │  ⚠ parallel ontology vs decisions
            │                            │  ⚠ engine.validate/ValidationConfig
            │                            │     collides with validation/    │
            │                            └────────▲────────────────────────┘
            │                                     │
   ┌────────▼─────────────────┐                   │
   │      runner/             │───────────────────┘
   │  __init__.run_config()   │  ⚠ 367-LOC orchestrator god-fn
   │  execution.execute_strategy_run() (shared)
   │  decision_adapter        ←  pass-through over decisions; one impl
   │  strategy_loader         ←  21-LOC re-raise shim, dead-weight
   │  engine_runner           ←  three jobs in one file (build, fillable-check, JSON)
   │  artifacts (417 LOC)     ←  evidence_quality(rows) is O(N), runs ≥2× per run
   │  data_loader             ←  ⚠ imports quant_data at module top
   └────────┬─────────────────┘
            │
            │     (validation imports runner.execution + runner.config)
            │
   ┌────────▼─────────────────┐
   │      validation/         │
   │  __init__.run_validation │  ⚠ 737-LOC orchestrator god-fn (PRD §G3 forbids)
   │  policy.py (505 LOC)     │  awards "paper_candidate" on mechanical gates only
   │  vectorbtpro_backend     │  silently drops SL/TP/trailing & non-close fills
   │  backends.Protocol       │  one prod impl; 1 fake
   │  capabilities.py         │  hard-codes vbt name; leaks backend identity
   │  matrix.py._FrozenDict   │  duplicate freezing idiom
   │  lookahead.py (105 LOC)  │  ✓ correct shape, only invoked from validation
   └──────────────────────────┘
```

### Minimal (target after focused refactors)

```
   decisions/        Strategy + Decision (Protocol-typed) ──┐
                                                            │
   boundary.py       FrozenMapping (one impl, freeze ONCE)  │
                                                            │
   core/config.py    DataConfig/FillModel/CostModel (shared)│
                                                            │
   engine/           pure smoke kernel — consumes Decision  │
                     no Signal/Bar/FillModel re-encoding    │
                                                            │
   runner/           load → execute_strategy_run → screen   │
                     enforces lookahead before completion ──┘
                     writes summary artifacts (default)
                     ┌─→ artifact_profile=summary by default
                     └─→ "full" only for retained / debug
   validation/       per-window orchestrator (≤150 LOC __init__)
                     gates declarative
                     backend BackendMetrics schema typed
```

---

## 6. Architecture & boundary review

### What's right (preserve)

1. **`decisions/models.py` is a tight, frozen, JSON-roundtrippable schema.** `as_of_time ≤ decision_time` enforced at construction (`models.py:142`). JSON-compatibility of metadata enforced at construction. ✓
2. **Bounded contexts are clean, dependency DAG is acyclic.** `decisions/` is leaf-pure; `engine/` never imports `runner/` or `validation/`; `runner/execution.execute_strategy_run` is genuinely shared between runner and validation. ✓ (architecture lens confirmed)
3. **`validation/lookahead.py` is the right shape** — replay with row-filter, compare `_decision_fingerprint`. Honest. ✓
4. **Auditability chain works end-to-end** for a single number. Verified manually by tracing `sum_weighted_trade_net_return = -0.000189...` through `strategy_snapshot.py → config.toml → data_manifest.json → decision_records.jsonl → signals.csv → evidence.json`. (quant lens confirmed.) ✓
5. **Backend lazy-imports vectorbtpro.** Cold path stays cheap when validation isn't run. ✓
6. **Advisory eligibility flags are hard-coded `False`.** Tried to flip via constructor — `default_advisory_fields` clobbers via `object.__setattr__` on a `frozen=True` Pydantic model. Works, but the *mechanism* is fragile. (adversarial: PASS with LOW caveat.)

### What's wrong (root causes, not symptoms)

**BLOCKER · Refactor · Runner does not enforce causality.** `runner/__init__.py:run_config` builds artifacts, runs the engine, writes `summary.json` with `assessment_status="smoke_passed"` and `"causality_verified": false` (`runner/artifacts.py:136`) — **without ever calling `check_hidden_lookahead`**. The PRD §NFR-CAUSALITY says "no run completes with `assessment_status` other than `runner_failed` if any decision violates [causality]." Today, a `quant_autoresearch` consumer that filters on `assessment_status == "smoke_passed"` is reading a number the runner never earned. *Root cause:* lookahead was retrofitted into the validation harness only. *Smallest fix:* call `check_hidden_lookahead` in the runner pipeline right after `execute_strategy_run` returns; on violation, return `assessment_status="runner_failed"` (or a new `causality_violated`). Delete the hard-coded `False` in `runner/artifacts.py:136`. If `available_at` is missing, either fail or rename the assessment to `smoke_unverified` — but stop completing as `smoke_passed`. (adversarial, quant — both BLOCKER.)

**BLOCKER · Refactor · `engine/` is a parallel ontology.** `engine/models.py:81 Signal`, `engine/models.py:33 Bar`, `engine/models.py:111 FillModel`, `engine/models.py:117 CostModel`, `engine/models.py:128 ValidationConfig`, `engine/models.py:155 ValidationReport` re-encode strategy + runner-config shapes that already exist. The dict-intermediate at `runner/engine_runner.py:167-203` is a third shape. PRD §G3: "no parallel representation in the math layer." *Smallest fix:* (a) consume `StrategyDecision` directly in `engine.screen` (no `Signal`); (b) drop `engine.FillModel`/`CostModel` in favor of `runner.config` (or a shared `core/config.py`); (c) inline `decision_adapter.decisions_to_signal_rows` into `build_request`; (d) **rename** `engine.validate / ValidationConfig / ValidationReport` to `engine.gate_screen / GatingConfig / GatingReport` so the name collision with `validation/` ends. (architecture BLOCKER + HIGH H3.)

**HIGH · Refactor · `validation/__init__.py` is a 737-LOC god-function (PRD §G3 forbids).** `run_validation` spans ~290 lines with 5 stage-specific failure branches and the scenario loop inlined. *Smallest fix:* extract three pure helpers, no new layer: `_run_window(window, …) → WindowOutcome`, `_run_scenario(scenario, …) → ScenarioOutcome`, `_handle_execution_failure(exc) → Result | Continue`. Top-level orchestration goes from 290 LOC to ~120 LOC. (architecture, eng — both HIGH.)

**HIGH · Refactor · Backend metrics are an unstructured `dict`.** `BackendRunResult.metrics: dict[str, float|int|str|bool|None]` (`backends.py:22`) and `validation/policy.py:74` reads `net_return`/`trade_count` positionally. No `BackendMetrics` schema mediates the backend↔policy contract. *Smallest fix:* `BackendMetrics(BaseModel, frozen=True)` with required `net_return: float` and `trade_count: int`, plus a typed `extras` mapping. (architecture H4.)

**HIGH · Simplify · Hard-coded backend identity in policy layer.** `validation/capabilities.py:62` `_vectorbtpro_records` keys off `name == "vectorbtpro"`. *Smallest fix:* move capability declaration into each `Backend` implementation (`backend.capability_matrix() → CapabilityMatrix`); `capabilities.py` becomes a 20-LOC dispatcher. (architecture H5.)

**MEDIUM · Refactor · `validation/config.py` reaches back into `runner/config.py` for 5 shared types.** `RunConfig`, `CostModelConfig`, `FillModelConfig`, `DataConfig`, `OutputConfig` all imported (`validation/config.py:19`). This is fine as a consumer pattern but cements `runner` as the canonical config owner. *Smallest fix:* lift those to `core/config.py`. (architecture M9.)

---

## 7. Engineering, performance, and operability

### Measured run profile (`runs/simple_momentum_spy_daily.toml`, 16,640 rows, 1 decision, mode `validate`)

| Stage | Cost (cProfile, cumulative) | Note |
|---|---|---|
| `import quant_strategies.runner` (cold) | **~1.6 s** | Dragged in by `quant_data → polygon SDK` at module top |
| `run_config()` total | **2.93 s** | In-process, warm imports |
| → `execute_strategy_run` | 1.68 s | |
|   → `load_data` (psycopg2 connect) | 0.80 s (0.62 s connect) | New connection per run, not pooled |
|   → `frozen_rows(rows)` (`boundary.py:17`) | **0.55 s** | `deepcopy` + recursive `_freeze_value` of every row |
| → `write_strategy_input_rows` | **0.53 s** | Default `artifact_profile="full"` writes JSONL+CSV with 99,843 `json.dumps` calls |
| → `engine_runner.request_json` | 0.35 s | Full pydantic `model_dump(mode="json")` |
| → `json_safe_value` (332,783 calls) | aggregated in above | Recursive isinstance/`hasattr` walk |
| Default artifacts written | **12 files** | Including `strategy_input_rows.csv` AND `.jsonl` (same data twice) |
| `data_manifest.json` even on failures | yes | Failure paths also write |

### Top performance findings (with root-cause fixes)

| # | Finding | File:line | Root cause | Fix | Est. saving |
|---|---|---|---|---|---|
| P1 | `boundary.frozen_rows` deepcopies every row at every call; called 3–6× per validation | `boundary.py:13,17`; `validation/__init__.py:202,288,515,541`; `lookahead.py:34-36` | `MappingProxyType` already prevents mutation; deepcopy is redundant safety on top | Drop `deepcopy`; make `frozen_rows` idempotent on already-frozen input; freeze ONCE at runner boundary and pass through | ~0.55 s × N_frozen_calls |
| P2 | `quant_data` eagerly imported in `runner.data_loader` at module top → drags in `polygon` SDK (~520 ms cold) | `runner/data_loader.py:7-9` | Top-level import for a function-scope dependency | Lazy-import `quant_data.config/db/loader` inside `_default_engine` and `_load_rows` | ~0.5–1.0 s cold |
| P3 | Default `artifact_profile = "full"` for every shipped config; writes 12 files incl. duplicate CSV+JSONL | `runner/config.py:98`, all `runs/*.toml` | Convenience default is also the heaviest profile | Flip default to `"summary"`; mark `"full"` for retained/debug; **delete one of `strategy_input_rows.{csv,jsonl}` outright** — same data twice | ~0.5 s + ~10–50 MB I/O per run |
| P4 | Pydantic revalidation across boundaries | `engine_runner.py:73-74` (FillModel/CostModel rebuild), `validation/__init__.py:298` (`BackendRunResult.model_validate`) | Defensive paranoia at internal boundaries | Drop rebuild; trust internal contracts; revalidate only at system boundaries (CLI input, backend external output) | ~0.05–0.15 s |
| P5 | `psycopg2._connect` per run (~0.62 s) | `runner/data_loader.py:121-134` (`.env` discovery via `parents[2]` walk also costly) | New engine + connection per `run_config` | Cache engine at process level (singleton/factory) when `quant_autoresearch` runs in-process; document the contract. Independent of database tuning | ~0.6 s |
| P6 | `normalized_rows_sha256` walks all rows twice (once in `artifact_profiles.py:20-25`, again in `validation/manifest.py:21-26` per window) | as cited | Two implementations | Hash once at data-loader edge, propagate | ~1.7 s on 160k rows per validation (eng F2) |
| P7 | `decisions_to_signal_rows` does `decision.model_dump(mode="json")["metadata"]` per decision | `runner/decision_adapter.py:22` | Round-trips the whole decision through pydantic to extract one field | Use existing `_jsonable_metadata_value(decision.metadata)` directly | ~0.05 s per N decisions |
| P8 | `evidence_quality(config, rows)` walks all rows; recomputed twice per run | `runner/execution.py:84` and `runner/artifacts.py:190` | Result not cached between sites | Compute once in `runner/__init__.py`, pass through | ~0.05 s |

### Iteration-cost estimate for `quant_autoresearch`

Assuming `quant_autoresearch` calls `run_config()` in-process (per `docs/quant-autoresearch-consumer.md`):

| Scenario | Per-candidate cost today | Per-candidate cost after P1+P3+P4+P5 | Comment |
|---|---|---|---|
| Subprocess per candidate (worst case) | 3.6 s | ~0.7 s | 5× speedup, primarily from import + freeze + I/O |
| In-process loop (recommended) | 2.0 s | ~0.5 s | Import paid once; rest is freeze + DB connect + artifact I/O |
| 100 candidates, in-process | 200 s | ~50 s | |
| 1,000 candidates, in-process | ~33 min | ~8 min | |

None of these fixes touch math or determinism. Pure overhead removal.

### Test discipline

- **460 tests for 5,817 LOC source.** Strong on causality (`test_validation_lookahead.py` covers four invariants), policy decision tree (`test_validation_backends_and_policy.py` has 30+ `assert_advisory_only` on the eligibility-flag invariant), strategy contract docstrings (`test_strategy_docstrings.py` AST-bans engine/runner/`quant_data` imports inside strategies).
- **Weak on:**
  - **PRD §NFR-DETERMINISM byte-identical artifacts.** Only `test_write_json_artifact_is_stable` (one small payload). Nothing pins a full `run_config` rerun byte-for-byte.
  - **PRD §G2 unit/base semantics.** No test asserts `smoke_score.*` field names map to their formulas.
  - **`available_at` partial-coverage failure modes.** `data_readiness.assert_decision_rows_ready` keys on `(symbol, as_of_time)`; rows the strategy used but didn't reference at decision-time can pass readiness while violating causality.
  - **Same-bar-entry causality.** `entry_lag_bars=0` is type-legal (`engine/models.py:113`), runner never checks the resulting fill is causal.
  - **`paper_candidate` requires statistical evidence.** No test asserts the label is never awarded on purely-mechanical gates.
  - **Performance test budget.** `test_phase5_performance.py:153` covers an 8k-trade screen at 0.5 s — useful but does not budget end-to-end `run_config`, cold-import cost, or `quant_autoresearch` iteration cost where the real waste lives.

### Determinism

- `model_dump_json()` (`runner/artifacts.py:98`, `validation/__init__.py:577,638`) writes `decision_records.jsonl` with pydantic-default key order, **not** `sort_keys=True`. Stable within one pydantic build, **not** across pydantic patch versions. PRD NFR-DETERMINISM ("byte-identical artifact hashes") is violated by silent regression. (adversarial H4.) *Smallest fix:* always go through `json.dumps(..., sort_keys=True, separators=(",", ":"))` — there is already a fallback path on `runner/artifacts.py:100` for this exact pattern. Make it the only path.
- `git_identity` (`provenance.py:55-76`) runs `git status --porcelain --untracked-files=all` and hashes the result. Excludes `result_dir`, but not `__pycache__`, other result dirs, or transient detritus. Two replays from the same code+config+data can produce different `status_porcelain_sha256` if the working tree is messy. (adversarial M10.)

### Operability

- The CLI behaves as documented: `quant-strategies run path/to/config.toml` and `quant-strategies validate path/to/validation.toml`. (Verified.)
- `runs/*.toml` covers 4 strategy families (simple_momentum, crypto perp funding, FX triangular, FIX reversal). Adequate test surface.
- `pytest -ra` runs the full suite. (Not timed in this review.)

---

## 8. Senior-quant lens — math, fills, costs, units, auditability

### Smoke engine math (`engine/evaluation.py:42-113`)

```python
gross_return  = direction * ((exit - entry) / entry) * weight   # per trade
funding_return = Σ_(entry,exit] (-direction × rate) × weight    # per trade, per perp funding event
cost_return    = round_trip_bps / 10_000 × weight               # per trade
net_return     = gross_return + funding_return - cost_return    # per trade
SmokeScore.sum_weighted_trade_*  = Σ over trades                # NOT a portfolio NAV
```

The arithmetic is **honest** per-trade. The naming is **dishonest** at aggregation. PRD §G2: "no `return` for a sum-of-trade-activity figure." Three fields in `SmokeScore` plus `evidence_semantics.return_model` carry the noun "return" for a sum that has no portfolio meaning — two simultaneous full-weight long trades would sum 2× their average return. **Rename** to e.g. `sum_signed_trade_activity_{gross,funding,cost,net}` and update `return_model` accordingly.

### Fill semantics

- Smoke entry: `decision_index + entry_lag_bars` (default 1). Smoke exit: trigger walk → `trigger_index + exit_lag_bars` (default 0).
- Vbt accepts only `fill_model.price == "close"` (else `unsupported_semantics`, `vectorbtpro_backend.py:149`). It also drops `stop_loss_bps / take_profit_bps / trailing_stop_bps` as `unsupported`. So **the only backend that gates `paper_candidate` validates a *different* strategy** than the one the strategy author wrote.
- `validation/policy.py:299-310` classifies unsupported-semantics scenarios as `watchlist`, not `hard_no`. For paper-readiness, the wrong default. (quant H6.)

### Funding

- Per-event on `(entry_time, exit_time]` half-open; conflicting duplicate rates raise. Sign convention `-direction × rate` (long pays positive funding, short collects). Standard perp. ✓
- Vbt funding model is `linear_additive_adjustment` (`vectorbtpro_backend.py:404-410`) — bolted on after vbt's own NAV computation. Honest label, but ignores compounding interaction between funding and notional; matters on long crypto holds.
- Strict `math.isclose(abs_tol=1e-15)` on duplicate funding rates (`engine/evaluation.py:294`, `funding.py:53`) is brittle for floats from real upstream feeds. (quant L14.)

### Backend agreement

No declared tolerance between smoke `sum_weighted_trade_net_return` and vbt `net_return`. The two are not even measuring the same thing (sum-of-activity vs portfolio NAV). PRD §G2: backends "match within a declared tolerance, or declare the asymmetry explicitly". The asymmetry is partly declared via the capability matrix, but the tolerance is absent — and the policy mixes the two into gates anyway (`policy.py:411-421`). **HIGH** (quant H5).

### Causality replay

- `validation/lookahead.py` filters rows by `timestamp ≤ as_of_time` AND `available_at ≤ decision_time` (both inclusive — correct for an information cutoff). For each baseline decision, re-runs the strategy on the filter and compares `_decision_fingerprint`. Mechanically right.
- **Limitation:** catches only whole-output mismatches. A strategy that guards `if i+1 < len(rows): use rows[i+1]` would silently pass replay because the replay slice ends at `as_of_time` and the guard skips. Mitigation: enforce that `ObservationRef.timestamp ≤ decision.as_of_time` for every observation, and require `observations` non-empty in the decision schema. (quant M8.) The `validation/dependencies.py` module already has shape for this — push it into the runner path too.
- **Runner skips it.** See BLOCKER above.

### Search-pressure / overfit

`validation/policy.py:142-153` `overfit_controls_from_search_pressure` copies `candidate_count`, `trial_count`, `parameter_search_space`, `selection_rule`, `split_ids` into the decision payload but **no gate uses any of them**. The PRD glossary says "consumed for deflation; not for blocking" — the "not for blocking" half is honored, the "deflation" half does not exist. A `paper_candidate` is awarded with zero awareness of how many trials produced it. **MEDIUM**: at minimum add a `deflation_not_evaluated` reason on every `paper_candidate` result.

### Auditability chain (verified end-to-end)

For `results/2026-05-28T051332Z-simple_momentum/evidence.json.trades[0]`:

```
(476.03 − 476.12) / 476.12 × +1 × 1 = -0.00018902797614053565   ✓
```

Matches `summary.json.engine.smoke_score.sum_weighted_trade_gross_return`. All upstream artifacts (`strategy_snapshot.py`, `config.toml`, `data_manifest.json`, `decision_records.jsonl`, `signals.csv`) are sha256-pinned in `run_manifest.json`. **Chain works.** Caveats:

- The `decision↔trade` mapping is by `(symbol, decision_time)`, not via an explicit `decision_id`. For a multi-trade strategy where some decisions don't fill, the join is fragile. **Add** `decision_id` to `StrategyDecision` and propagate to `Trade`. (quant H7.)
- The auditability proves the *math*, not the *decision's causality* — because the runner never replayed lookahead. (See BLOCKER.)

---

## 9. Adversarial / unknown-unknown risks

Independent adversarial pass found:

1. **`smoke_passed` is the contract gap.** The status the consumer reads says causality was checked; the artifact warning admits it wasn't. Two different fields, two different stories. (already a BLOCKER.)
2. **Two decisions on the same `(symbol, decision_time)` double-count.** `engine/evaluation.py:185-187` raises on duplicate **bars**, but the signal list has no dedup. Strategy bug → silent doubled PnL. **HIGH.** *Fix:* validate signals for `(symbol, decision_time)` uniqueness in `engine_runner.build_request` (or fold this into the decision-output validator).
3. **`entry_lag_bars=0` is type-legal** (`engine/models.py:113`). Combined with the runner skipping causality, a strategy can legitimately fill on the same bar it decided on, and the runner never raises. **HIGH** (paired with the BLOCKER).
4. **Empty-decision strategy aliased to `runner_failed`.** A strategy that *legitimately* finds no opportunities in a window returns 0 decisions; `engine_runner.build_request` raises `RequestBuildError("strategy generated no signals")`; runner writes failure summary. For a screening search, "0 trades" is a useful signal, not a failure. **MEDIUM.**
5. **`researched/` is folder convention, not enforced.** `tests/test_strategy_docstrings.py:60` is the only code reference. A user could point `strategy_path` at a `researched/` strategy and the runner treats it identically to `untested/`. The PRD wants `researched/` to mean "frozen, not market-validated"; the foundation has no enforcement. **MEDIUM.**
6. **`paper_candidate` name overstates.** Already listed.
7. **`cost_return` is a positive-magnitude quantity named like a signed return.** Downstream `gross + funding + cost` will get the wrong net sign for unaware consumers. The PRD §G2 demands honest names. **LOW.**

### Over-engineering masquerade list

- `runner/strategy_loader.py` (21 LOC) — pure re-raise shim over `decisions.load_decision_strategy` with one-line exception translation. *Retire.*
- `runner/decision_adapter.py` (40 LOC, one impl) — folds naturally into `engine_runner.build_request` once `engine/` consumes `StrategyDecision` directly. *Retire.*
- `validation.errors.ValidationBackendError`, `ValidationDataError` — defined, exported, **never raised in src**. *Retire.*
- `validation.matrix._FrozenDict` — duplicate of `boundary.FrozenMapping`. *Retire* and consolidate.
- `engine.FundingModel = Literal["none","linear_additive_adjustment"]` — one selected branch, one nominal branch. Acceptable as a planned extension point; flag it if a third branch hasn't shipped in 6 months.
- `ValidationBackend` Protocol — has `FakeBackend` (test) + `VectorBTProBackend` (one prod). Protocol earns its weight only if a second real backend is on the roadmap; otherwise an ABC or plain class is cheaper. The capability matrix file is also written for one backend.
- `runner/__init__.py._summary_payload` writes `smoke_score: {None, None, None, None}` on every failure (`runner/__init__.py:248-256`). Consumers now must distinguish "not computed" from "0.0" via null vs number. Omit the key on failures instead.
- `untested/crypto_perp_autoresearch_ensemble.py` is **866 lines** for one strategy. Allowed by AGENTS.md ("one file per strategy"), but a strategy that long suggests either (a) it's actually doing engine-like aggregation work that belongs upstream, or (b) it's an exemplar of how `quant_autoresearch` generates code (no human author). Worth a one-time review with Season.

---

## 10. Docs vs code drift (user's added concern)

| Doc claim | Code/state | Verdict |
|---|---|---|
| PRD §NFR-CAUSALITY: "no run completes with `assessment_status` other than `runner_failed` if any decision violates causality" | Runner never invokes `check_hidden_lookahead`; writes `causality_verified: false` and completes as `smoke_passed`. README §"Runner Runs" candidly admits this. | **PRD overstates. README accurate.** Code matches README. (BLOCKER.) |
| PRD §G1: strategy contract supports options/futures/multi-leg/intent/vol-target/side-of-book | `decisions/models.py` covers equity/FX/crypto-perp, long/short/flat, target_weight (notional rejected by adapters). | **PRD overstates.** Roughly 60% of G1 axes are absent at the type level. |
| PRD §G2: "name does not overstate", "no `paper_candidate` without statistical evidence" | `sum_weighted_trade_*_return` named `return`. `paper_candidate` awarded on mechanical gates only. | **Code violates PRD G2.** Rename. |
| PRD §G3: "no parallel representation in the math layer" | `engine.Signal/Bar/FillModel/CostModel/ValidationConfig/ValidationReport` mirror decisions + runner config. | **Code violates PRD G3.** Collapse parallel ontology. |
| PRD §G3: "single declared freezing idiom" | `boundary.FrozenMapping` + `matrix._FrozenDict`. | **Code violates.** Consolidate. |
| PRD §G3: "orchestrator god-functions are forbidden" | `validation/__init__.py:run_validation` is ~290 LOC; `runner/__init__.py:run_config` is 160 LOC. | **Code violates.** Split into helpers. |
| PRD §NFR-DETERMINISM: "byte-identical artifact hashes given same code+config+data" | `model_dump_json()` doesn't sort keys; no test pins this end-to-end. | **Cannot guarantee.** Fix encoder + add determinism test. |
| README artifact list (`decision_records.jsonl`, `data_audit.json`, `backend_runs/summary.json`, `backend_capability_matrix.json`, `robustness_matrix.json`, `validation_decision.json`, `validation_manifest.json`, `validation_report.md`) | Code writes all of these (not all verified in this review's `screen` run; `validation` artifacts present in `validation/__init__.py:_write_validation_artifacts`). | **Matches** for what we sampled. |
| README §"Runner Runs": `[output] mode = "screen"` and `"validate"`, status names `screened`/`smoke_passed`/`smoke_failed`/`runner_failed` | Matches `runner/__init__.py:329-338`. | **Matches.** |
| `docs/quant-autoresearch-consumer.md`: "`run_config` and `RunResult` are the stable Python consumer surface; no top-level facade is promised" | `quant_strategies/__init__.py` is one docstring line; consumers must import from `quant_strategies.runner`. | **Matches** by design, but the onboarding lens flagged this as a discoverability cost. Worth re-evaluating. |
| AGENTS.md: "Stale docs are worse than no docs. Any implementation that changes behavior… must update the corresponding docs before completion." | `docs/superpowers/plans/` and `docs/superpowers/specs/` are **empty directories**; `docs/reviews/` is empty; `PRD.md` is untracked at review start (`?? PRD.md`); the openspec config exists but its plans/specs directories are empty. | **Drift.** Either remove the empty scaffolding or document what it's for. PRD should be committed (it's load-bearing for this review). |
| AGENTS.md provenance bar ("paper title/authors/year plus DOI/SSRN/URL when available") | `tests/test_strategy_docstrings.py` enforces section *presence* but does not enforce a URL/DOI/internal_note prefix; `simple_momentum.py` provenance is "internal runner smoke fixture" — fine for fixture, but would pass the test for a real candidate too. | **Test under-enforces AGENTS.md rule.** Add regex check. |
| `tested/` lifecycle target | Empty (only `__init__.py`). The promotion `untested → tested` was never executed. | Not drift per se — but the lifecycle exists nominally only. |

---

## 11. Overbuilt, underbuilt, right-sized

| Area | Verdict | Why |
|---|---|---|
| `decisions/models.py` (154 LOC) | **Right-sized for what it covers, underbuilt for PRD G1** | Tight schema; absent: intent, multi-leg, options, futures, vol-target, side-of-book. |
| `boundary.py` (31 LOC) | **Slightly overbuilt** | `deepcopy` is redundant safety on top of `MappingProxyType`; called 3–6× per validation. |
| `engine/models.py` (201 LOC) | **Overbuilt** | Parallel ontology; collapse onto `decisions/` + shared config. |
| `engine/evaluation.py` (299 LOC) | **Right-sized** | One pure kernel; honest math. |
| `runner/__init__.py` (367 LOC) | **Mildly overbuilt (god-fn)** | Split summary, status, completion helpers. |
| `runner/strategy_loader.py` (21 LOC) | **Dead-weight** | Inline into `decisions.strategy_loader` consumers. |
| `runner/decision_adapter.py` (40 LOC) | **Dead-weight after engine collapse** | Folds into `build_request`. |
| `runner/engine_runner.py` (275 LOC) | **Three jobs in one file** | Split (a) build_request, (b) fillable assertions, (c) JSON serialization. |
| `runner/artifacts.py` (417 LOC) | **Right-sized** for artifact taxonomy, **overbuilt** at write time | Two writers for same data (csv+jsonl); evidence_quality computed twice. |
| `validation/__init__.py` (737 LOC) | **Overbuilt (god-fn)** | Extract per-window / per-scenario / failure-handler helpers. |
| `validation/policy.py` (505 LOC) | **Mildly overbuilt** | Declarative gate table in `_paper_readiness_decision` would cut ~80 LOC. |
| `validation/capabilities.py` (170 LOC) | **Overbuilt** | Backend identity leaks; should be Protocol method. |
| `validation/vectorbtpro_backend.py` (442 LOC) | **Right-sized** | Genuine adapter; carries its own complexity correctly. |
| `validation/lookahead.py` (105 LOC) | **Right-sized** | Underused — only invoked from validation, not runner. |
| `tests/` (36 files, ~10.6k LOC) | **Right-sized in count, underbuilt in invariant coverage** | Strong on policy/causality/contract; weak on determinism/units/`paper_candidate`-statistical-evidence. |

---

## 12. Preserve / Refactor / Simplify / Add / Retire — action map

### Preserve

- `decisions/models.py` field shapes that already work (long/short/flat × target_weight × `as_of_time ≤ decision_time` invariant).
- `validation/lookahead.py` algorithm.
- `runner/execution.execute_strategy_run` as the shared boundary (already correct).
- Acyclic dependency direction `decisions ← engine, runner; runner ← validation`.
- Eligibility flag enforcement via `evidence_semantics` (mechanism is fragile — see Add — but the policy is right).
- Audit-chain hashing in `provenance.py` and `run_manifest.json`.
- Test infrastructure for causality + advisory flag invariants.

### Refactor

1. **Runner enforces causality.** Call `check_hidden_lookahead` inside `runner/__init__.py:run_config` after `execute_strategy_run`. On violation → `assessment_status="runner_failed"`; when `available_at` is fully missing, use `assessment_status="smoke_unverified"` (new) instead of `smoke_passed`. Delete `runner/artifacts.py:136` hard-coded `False`. **BLOCKER.**
2. **Collapse `engine/` ontology.** Make `engine.screen` consume `StrategyDecision` directly; drop `engine.Signal/Bar/FillModel/CostModel`; fold `decision_adapter` into `engine_runner.build_request`. Rename `engine.validate → engine.gate_screen`, `engine.ValidationConfig → engine.GatingConfig`, `engine.ValidationReport → engine.GatingReport`. **BLOCKER (G3).**
3. **Split `validation/__init__.run_validation`** into `_run_window`, `_run_scenario`, `_handle_execution_failure`. Top-level orchestrator ≤150 LOC. **HIGH.**
4. **Split `runner/__init__.run_config`** into stage helpers; keep the top-level as artifact-bracketing only. **HIGH.**
5. **Backend metrics typed** via `BackendMetrics(BaseModel, frozen=True)` with required `net_return`, `trade_count`, optional `extras`. Delete dict-positional reads in `policy.py:74`. **HIGH.**
6. **Lazy-import `quant_data`** in `runner/data_loader.py`. Cuts ~0.5–1.0 s cold. **HIGH.**
7. **Freeze rows ONCE** at the runner boundary; remove `deepcopy` from `boundary.py`; pass already-frozen rows through validation/lookahead/scenarios. **HIGH.**
8. **Deterministic JSON.** Replace every `model_dump_json()` artifact write with `json.dumps(decision.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))`. **HIGH.**
9. **Backend agreement check** with declared absolute tolerance on a defined shared quantity (per-trade gross_return, close-fill, no thresholds). **HIGH.**
10. **Vbt unsupported-semantics → `hard_no`** for required scenarios where the dropped capability is part of the strategy's risk profile. **HIGH.**
11. **Cache DB engine** at process level for `quant_autoresearch` in-process iteration. **MEDIUM.**
12. **Move shared config primitives** (`DataConfig`, `FillModelConfig`, `CostModelConfig`) to `core/config.py`; consumed by `runner/` and `validation/`. **MEDIUM.**
13. **Drop `BackendRunResult.model_validate(raw_backend_result)`** revalidation; trust the Protocol return type. **MEDIUM.**
14. **Backend capability is the backend's own concern.** `Backend.capability_matrix() → CapabilityMatrix`; `validation/capabilities.py` becomes a 20-LOC dispatcher. **MEDIUM.**

### Simplify

1. **Delete `runner/strategy_loader.py`** — inline its one-line exception translation. **LOW.**
2. **Delete `runner/decision_adapter.py`** once the engine collapse lands. **LOW.**
3. **Delete `_FrozenDict`** from `validation/matrix.py`; use `boundary.FrozenMapping`. **LOW.**
4. **Delete `ValidationBackendError`, `ValidationDataError`** — unused. **LOW.**
5. **Declarative gate table** in `validation/policy._paper_readiness_decision`. **LOW.**
6. **One artifact for input rows**, not two (`strategy_input_rows.csv` AND `.jsonl`). Keep JSONL only (richer than CSV for nested fields). **LOW.**
7. **Omit `smoke_score` key on failure** instead of writing `{None, None, None, None}`. **LOW.**

### Add

1. **Rename `paper_candidate` → `mechanical_paper_eligible`** (or `paper_screening_pass`). Reserve `paper_candidate` for a future statistical gate. **HIGH.**
2. **Rename `sum_weighted_trade_*_return`** family → `sum_signed_trade_activity_{gross,funding,cost,net}`. Update `evidence_semantics.return_model` accordingly. **HIGH.**
3. **`Protocol` for `generate_decisions`** exported from `decisions/__init__.py` with full callable signature. **MEDIUM.**
4. **`decision_id`** on `StrategyDecision`; propagate to `Trade.decision_id` for explicit decision↔trade join. **HIGH.**
5. **Add `intent`** (`open|close|adjust|roll`) to `StrategyDecision`. **HIGH.** (PRD G1.)
6. **Add multi-leg shape** — discriminated union on `StrategyDecision.instrument` accepting `tuple[LegSpec, ...]` or first-class `MultiLegDecision`. **HIGH.** (PRD G1.)
7. **Add `OptionRef`, `FutureRef`** instrument subtypes with required strike/expiry/multiplier/settlement fields. **MEDIUM** (gate-driven by which assets you actually plan to run).
8. **Add sizing modes** — `target_notional`, `target_contracts`, `target_vol` — and stop rejecting `notional` at the smoke adapter. **HIGH.**
9. **Determinism test:** run the same canonical config twice with frozen `now=`; assert byte-identical hashes for `summary.json`, `data_manifest.json`, `decision_records.jsonl`, `signals.csv` (modulo `run_id`). **MEDIUM.**
10. **Unit-semantics test:** golden-string assertions that each `smoke_score.*` field name matches its formula. **MEDIUM.**
11. **`available_at` partial-coverage failure mode** test: rows mixed where some have `available_at > decision_time` → readiness should fail, not pass. **MEDIUM.**
12. **Whitelist for banned strategy imports** instead of blacklist in `test_strategy_docstrings.py`. **MEDIUM.**
13. **`deflation_not_evaluated` reason** on every `paper_candidate` (or its renamed successor) when `search_pressure` is non-empty. **MEDIUM.**
14. **Provenance test** that `Source / provenance:` block contains a URL, DOI, or `internal_note:` prefix. **LOW.**
15. **`docs/reviews/`** — this file goes here when published, with a date stamp. (Or keep at root per user's request; remove the empty `docs/reviews/` dir then.) **LOW.**

### Retire

1. `runner/strategy_loader.py`.
2. `runner/decision_adapter.py` (after engine collapse).
3. `validation.errors.{ValidationBackendError, ValidationDataError}`.
4. `validation.matrix._FrozenDict`.
5. `engine.{validate, ValidationConfig, ValidationReport}` names (rename, don't delete the math).
6. `engine.Signal/Bar/FillModel/CostModel` representations (after engine collapse).
7. Empty `docs/superpowers/plans/` and `docs/superpowers/specs/` (or document what populates them).
8. Duplicate input-row artifact (csv or jsonl, pick one).
9. `smoke_score: {None,None,None,None}` placeholder on failure paths.

---

## 13. Prioritized recommendations

### P0 — Blockers for "paper-readiness foundation" claim

1. **Runner enforces causality** (Refactor #1). Without this, `assessment_status="smoke_passed"` is a lie by omission. Single biggest correctness fix in this review.
2. **Collapse `engine/` parallel ontology** (Refactor #2). PRD §G3 directly violated. Removes one full pydantic pass per row from the hot path as a side benefit.
3. **Rename `paper_candidate` and `sum_weighted_trade_*_return`** (Add #1, #2). PRD §G2 directly violated by name. Cheap to do, expensive to leave because downstream consumers will absorb the wrong semantics.

### P1 — Foundation gaps the PRD explicitly mandates

4. Split `validation/__init__.run_validation` into helpers (Refactor #3). PRD §G3 "no orchestrator god-functions".
5. Add `intent`, multi-leg, `OptionRef`/`FutureRef`, real sizing modes to `StrategyDecision` (Add #4–8). PRD §G1 mandate. Decide whether to phase this in by asset class (e.g., crypto-perp + futures next, options later) or fix the schema once.
6. Backend metrics schema + agreement tolerance (Refactor #5, #9). PRD §G2 backend-tolerance clause.
7. Determinism: sort keys at every artifact write + add a regression test (Refactor #8 + Add #9). PRD §NFR-DETERMINISM.
8. `decision_id` propagation (Add #4). Auditability robustness.
9. Vbt unsupported-semantics → `hard_no` for required scenarios (Refactor #10).

### P2 — Performance, ergonomics, simplifications

10. Lazy-import `quant_data` (Refactor #6). Big iteration-cost win.
11. Freeze rows once (Refactor #7). Big iteration-cost win.
12. Default `artifact_profile = "summary"`, drop duplicate input-row artifacts (Simplify #6). Iteration-cost + clarity.
13. Delete dead code: `strategy_loader.py`, `_FrozenDict`, unused errors (Retire #1, #3, #4).
14. Split `runner/__init__.run_config` (Refactor #4).
15. Engine cached at process level for in-process autoresearch loop (Refactor #11).
16. Move shared config primitives to `core/config.py` (Refactor #12).

### P3 — Docs and discoverability

17. **Commit `PRD.md`.** It is load-bearing for review and consumer alignment.
18. Either populate or remove `docs/superpowers/{plans,specs}` and `docs/reviews/`.
19. Reconcile PRD vs README on causality/eligibility. README is currently the truthful one; either soften the PRD invariants or implement them.
20. Provenance regex test (Add #14).

---

## 14. Diagrams

### Run-time data flow (after BLOCKER fixes)

```
   experiment.toml ─────┐
                        │
   strategy.py ─────────┤
                        ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │                  runner.run_config                               │
   │                                                                  │
   │   load_config ─→ load_data ─→ execute_strategy_run               │
   │                                  │                               │
   │                                  ▼                               │
   │                       (rows frozen ONCE here)                    │
   │                                  │                               │
   │                   ┌──────────────┴──────────────┐                │
   │                   ▼                             ▼                │
   │            validate_decision_output     check_hidden_lookahead   │
   │                   │                             │                │
   │                   │            (causality fails → runner_failed) │
   │                   ▼                             │                │
   │            engine.screen / gate_screen          │                │
   │                   │                             │                │
   │                   ▼                             │                │
   │            write artifacts (summary by default) │                │
   └──────────────────────────────────────────────────────────────────┘
                        │
                        ▼
                  RunResult
```

### Lifecycle today vs intended

```
   untested/  ─── candidate generation by quant_autoresearch
        │
        │  (runner screening evidence; advisory only)
        ▼
   validation harness (validate config, multi-window, multi-scenario)
        │
        │  decision: hard_no / mechanical_pass / watchlist / mechanical_paper_eligible
        │           ─ none of which authorizes anything
        ▼
   researched/  ─── frozen package by upstream research
        │
        │  (separate human-led validation; out of foundation scope)
        ▼
   tested/    ─── promoted, validated (CURRENTLY EMPTY — lifecycle nominally exists)
```

---

## 15. Unknown unknowns and assumption risks

- **`quant_autoresearch`'s actual invocation pattern is not in this review's scope.** If it spawns subprocesses per candidate, the cold-import tax dominates. If it iterates in-process, the freeze + DB-connect tax dominates. Either way the fixes above help, but the relative priority differs. Recommend confirming with the autoresearch team.
- **Pydantic patch upgrades can silently change `model_dump_json()` key order.** Today nothing pins this. (See determinism fix.)
- **Vbt is the only non-fake backend.** If vbt's unsupported_semantics list ever shrinks (vbt adds stop-loss support), policy currently won't notice — the capability matrix needs to be data-driven.
- **No test exists** that asserts "every `paper_candidate` (or successor) requires a statistical-deflation pass." Until added, the rename is the only defence.
- **The empty `tested/` directory** suggests the promotion path has never actually been exercised. The lifecycle exists in docs, in code (folder convention), and in tests (one reference) — but no strategy has traversed it. Worth running one strategy through end-to-end before claiming the foundation is ready.
- **`untested/crypto_perp_autoresearch_ensemble.py` is 866 lines.** Either it earns that size or it's a sign that strategies are absorbing aggregation logic the foundation should provide (`rows_by_symbol`, sparse-cadence decision schedules, multi-symbol candidate ranking). Worth one focused review.

---

## 16. NOT in scope (per locked objective)

- Live trading, paper trading, order routing.
- Real-time market data feeds.
- A general-purpose backtesting framework.
- Strategy generation logic (owned by `quant_autoresearch`).
- Data acquisition/repair (owned by `quant-data`).
- Statistical gating beyond advisory metrics.
- Microsecond-latency optimization.
- A web UI / dashboard / notebook integration.
- Internal review of `researched/<frozen-package>/` contents.
- `openspec/`, `.codex/`, `.cursor/`, `.worktrees/` tool scaffolding.

---

## 17. What was verified vs what was not

**Verified in this review:**

- Repo structure, manifests, agent contract.
- `decisions/models.py` schema fields and `as_of_time` invariant.
- `engine/evaluation.py` math by line-by-line read + one numerical trace from artifacts.
- `runner/__init__.py:run_config` control flow + every failure branch (read).
- `validation/__init__.py:run_validation` control flow up to scenario loop (read; the rest is paraphrased from the architecture and engineering lens reports).
- `runner/artifacts.py` writers + `causality_verified` hard-code.
- `boundary.py` `frozen_rows` deepcopy.
- One full `run_config` execution with cProfile (`runs/simple_momentum_spy_daily.toml`).
- Import-time profiling (`python -X importtime`).
- Auditability chain on one numeric value.
- Lookahead enforcement sites (grep across repo).
- All five run TOML configs' `artifact_profile` defaults.

**Not verified (assumed from lens reports or stated as such):**

- Full read of `validation/policy.py:_paper_readiness_decision` gate semantics (line ranges 322–481; the engineering and quant lens reports describe it; I did not re-read each gate).
- Full read of `validation/vectorbtpro_backend.py` (442 LOC) beyond capability flags.
- Whether every artifact listed in README §"Validation Runs" is actually written by `_write_validation_artifacts` (architecture lens reported "yes"; not independently re-verified).
- Whether `untested/crypto_perp_autoresearch_ensemble.py` (866 LOC) is structurally sound — only the header docstring was read.
- Test execution (`pytest -ra`) was not run; coverage observations are from reading test files and the engineering lens's report.

**Residual risk:** The bulk of findings converge across at least two of the five independent lenses and my own reads. The biggest residual risk is on the validation policy gates (`policy.py:322-481`) — I leaned on the quant + engineering lens here; an independent re-read would harden the recommendations on `paper_readiness` gate semantics.

---

*End of review. Next session pitch: turn `P0` into a focused branch with three commits — one per blocker. Each is a root-cause refactor under ~300 net-changed lines.*
