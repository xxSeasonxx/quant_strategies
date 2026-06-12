# Foundation Review: `quant_strategies`

Date: 2026-06-12
Reviewer: Codex, local source-grounded foundation review
Target: root docs, `docs/`, and `src/`, with quick run end-to-end as the priority path
Compared artifact: `docs/reviews/2026-06-11-foundation-claude.md`

## Review Objective

I reviewed `quant_strategies` to determine whether root docs, `docs/`, and `src/`
are a solid foundation for `quant_autoresearch` iteration and Season's research
review workflow. The priority path is quick run end-to-end: strategies should
iterate quickly, but anything retained for validation/evaluation must be a
causal, feasible, single-account target-book portfolio rather than a PnL-only
signal stack.

Validation and evaluation are reviewed as one-run feasibility filters over the
same model, not as redesign targets. This consolidation also audits
`docs/reviews/2026-06-11-foundation-claude.md` for false positives, duplicates,
accepted debt, and unsupported claims before merging its useful findings here.

### Clarified Scope

- **In scope**: `PRD.md`, `README.md`, `FOUNDATION_LOCK.md`, `TODOS.md`,
  `docs/foundation-surfaces.md`, `docs/consumer/`, `docs/reviews/2026-06-11-foundation-claude.md`,
  and `src/quant_strategies/`.
- **Out of scope**: deep candidate review, `researched/`, generated artifacts,
  broad validation/evaluation redesign, and `quant_autoresearch` internals.
- **Additional concerns from user**: feasibility of generated strategies,
  signal-stacking / PnL-only anti-patterns, quick-run hot-path performance, author
  ergonomics, over-engineering, stale docs, and avoiding false positives.
- **Method limitation**: the foundation-review workflow prefers subagent lenses,
  but the available subagent tool requires an explicit user request for
  delegation. I ran onboarding, architecture, senior engineering, adversarial
  evidence-audit, and quant-math lenses locally.

## First-Principles Bar For A Material Finding

A finding stays material only if it can plausibly do one of these:

1. Let fake tradeability or lookahead-contaminated evidence enter the
   quick-run-to-retention path.
2. Make a valid target-book strategy impossible or misleading to express.
3. Materially violate G6 quick-run performance discipline.
4. Mislead a current strategy author or downstream consumer through active docs.

Everything else is either a preservation constraint, optional cleanup, or an
open question. This is the main false-positive filter applied to the Claude
review and to my earlier draft.

## Executive Verdict

The central foundation is sound: the target-book ontology and one netted
portfolio book are real, source-enforced, and worth preserving. The historical
failure mode of additive signal stacking is structurally hard to express because
strategies emit standing signed `TargetDecision(target=...)` objects, output
validation rejects duplicate same-symbol decision timestamps, and the book trades
only deltas toward the current target.

The remaining trust gap is at the boundary around the book:

- The quick-run `micro` mode is currently an iteration annotation, not a gating
  proof. That can be acceptable only if downstream retention never treats
  `RunResult.succeeded` under micro as "tradeable enough." Current docs/PRD do
  not state that distinction cleanly enough.
- The feasibility envelope can still be relaxed by config and has weak realism
  floors.
- Validation/evaluation share the book, but they do not consistently carry the
  same scoreability semantics as quick run for non-raising feasibility verdicts
  such as `zero_cost` and `insufficient_samples`.
- Asset-class financing remains incomplete, especially for shorts whose net
  exposure is <= 1.0.

The engine is not broadly over-engineered. The over-engineering that matters is
localized: significance/DSR and a few superlinear pieces sit in or near the
quick-run path even though statistical significance belongs to the downstream
search owner.

## Scope And Evidence

- **Code inspected**:
  - `src/quant_strategies/runner/__init__.py` - quick-run orchestration,
    causality, portfolio foundation, feasibility gating, artifacts.
  - `src/quant_strategies/core/execution.py` - shared strategy execution kernel.
  - `src/quant_strategies/core/portfolio_foundation.py` - target-book walk,
    capacity, funding, risk rules, feasibility verdicts, and statistics.
  - `src/quant_strategies/decisions/models.py` and
    `src/quant_strategies/decisions/output_validation.py` - public decision schema
    and strategy output contract.
  - `src/quant_strategies/validation/_pipeline.py`,
    `src/quant_strategies/validation/engine_backend.py`,
    `src/quant_strategies/validation/policy.py`, and
    `src/quant_strategies/core/exposure.py` - validation as one-run filter.
  - `src/quant_strategies/evaluation/_pipeline.py`,
    `src/quant_strategies/evaluation/spine_backend.py`,
    `src/quant_strategies/evaluation/scenarios.py`, and
    `src/quant_strategies/evaluation/_spine_metrics.py` - evaluation as one-run
    filter.
  - `src/quant_strategies/core/config.py`,
    `src/quant_strategies/runner/config.py`,
    `src/quant_strategies/core/data_loader.py`, and
    `src/quant_strategies/data_contract.py` - envelope/config/data/performance
    boundaries.
- **Tests inspected**:
  - `tests/test_portfolio_foundation.py`,
    `tests/test_validation_engine_backend.py`,
    `tests/test_validation_runner.py`,
    `tests/test_validation_backends_and_policy.py`,
    `tests/test_evaluation_backend.py`,
    `tests/test_evaluation_runner.py`,
    `tests/test_performance_regressions.py`,
    `tests/test_runner_api_cli.py`.
- **Docs treated as claims**:
  - `PRD.md`, `README.md`, `FOUNDATION_LOCK.md`, `TODOS.md`,
    `docs/foundation-surfaces.md`, `docs/consumer/README.md`,
    `docs/consumer/usage-guide.md`, `docs/consumer/reference.md`,
    `docs/reviews/2026-06-11-foundation-claude.md`.
- **Not verified**:
  - Full test suite, real `quant_data` runtime, absolute 1M-row wall-clock, and
    downstream `quant_autoresearch` config behavior.

## Project Ontology And Foundation Model

The irreducible model is:

```text
pure strategy.py
  -> TargetDecision[]: standing signed weight-of-NAV targets
  -> shared execution kernel: params, rows, row contract, causality
  -> one netted single-account book: funding, costs, capacity, risk exits, NAV
  -> surface result:
       quick run: fast Train diagnostics
       validation: retained-candidate mechanical filter
       evaluation: frozen-candidate portfolio/path evidence
```

| Concept / boundary | Responsibility | Key contracts or invariants | Current-code fit |
|---|---|---|---|
| Strategy contract | Author declares complete portfolio intent | Pure `generate_decisions(rows, params)` returns `TargetDecision`s | Strong |
| Target book | One standing signed target per symbol/time | Same-symbol exposure nets; repeated target is no-op | Strong |
| Execution kernel | Imports strategy, validates params, loads/freeze rows, validates output | Shared by run/validate/evaluate through `StrategyExecutionSpec` | Strong |
| Causality | No retained evidence from future-dependent decisions | Replay must gate the retention boundary, not hide as a warning | Mixed: validation/evaluation gate; quick-run micro annotates |
| Portfolio book | One model of money | NAV path is scored; ledger is derived attribution | Strong |
| Feasibility envelope | Frozen costs/fills/capacity/leverage/sample adequacy | Breaches are typed, fail-closed, never clamped | Strong in quick run, inconsistent across filters and weakly bounded |
| Docs | State current contracts once | Active docs should not contradict source | Mixed |

## What Already Exists And Should Be Preserved

- `TargetDecision` is the right default strategy ontology: frozen, strict, finite
  signed `target`, causal `as_of_time <= decision_time`, deterministic ID when
  omitted (`src/quant_strategies/decisions/models.py:132`).
- `validate_decision_output` rejects non-sequence output, non-`TargetDecision`
  items, wrong strategy IDs, duplicate decision IDs, and duplicate
  `(symbol, decision_time)` execution keys
  (`src/quant_strategies/decisions/output_validation.py:8`).
- All three public surfaces adapt to `StrategyExecutionSpec`; validation and
  evaluation require `validate_params`
  (`src/quant_strategies/runner/config.py:161`,
  `src/quant_strategies/validation/config.py:257`,
  `src/quant_strategies/evaluation/config.py:178`).
- `_walk_book` is a real single-account walk: funding, risk rules, decisions
  against one equity snapshot, and mark-to-market NAV
  (`src/quant_strategies/core/portfolio_foundation.py:791`).
- `_apply_decision` trades only the delta to the new target and treats identical
  target re-emission as a no-op
  (`src/quant_strategies/core/portfolio_foundation.py:959`).
- Capacity impact is charged as part of execution events inside the NAV path, not
  bolted on after scoring (`src/quant_strategies/core/portfolio_foundation.py:1180`).
- Lazy `quant_data`, pandas, and pyarrow imports are right-sized for G6
  (`src/quant_strategies/core/data_loader.py:15`,
  `src/quant_strategies/evaluation/spine_backend.py:98`,
  `src/quant_strategies/evaluation/artifacts.py:211`).
- The staged extended ontology is correctly excluded from executable surfaces
  until execution semantics exist (`src/quant_strategies/decisions/extended_ontology.py`).

## Comparison With The 2026-06-11 Claude Review

| Claude finding | Consolidated disposition | Reason |
|---|---|---|
| F1 shorts pay no borrow at net <= 1 | **Kept, narrowed** | Source confirms only `crypto_perp_funding` is financed and `unfinanced_leverage` checks `net > 1.0`. It intersects accepted debt, but the net<=1 short case is still a tradeability gap. |
| F2 no realism floor on frozen envelope | **Kept** | Config validators allow weak/zero-ish costs, impact, capacity, and unbounded leverage; no operator provenance is enforced. |
| F3 micro causality cannot fail | **Kept, reframed** | Current TODO says micro is annotation, so this is a contract conflict rather than a simple bug. If quick-run micro scores are retained, the finding is P0. |
| O1/Q1/Q2 DSR/significance in quick path | **Kept, consolidated** | DSR belongs to search pressure and has avoidable quant/stat risk. It is a hot-path simplification finding, not a reason to distrust the NAV book. |
| O2/O4 stats extraction/dedup | **Kept as supporting action** | Real seam, but not a standalone foundation blocker. |
| O3 causality vocabulary | **Kept as supporting action** | Real complexity; subordinate to the micro/retention contract. |
| O5 `core/engine_runner.py` imports runner DTO | **Dropped as material finding** | It is behind `TYPE_CHECKING` and annotations are postponed. This is cleanup, not a foundation risk. |
| O6 config base duplication | **Demoted** | Real duplication, but low-risk maintainability cleanup. |
| P1 strict replay default | **Kept** | Source confirms default `strict` with no default probe limit; current perf test does not test strict-default integration. |
| P2/P3/P4/P5 ADV scan, hashing, double marking, diagnostics | **Kept, consolidated** | These are G6 risks; not correctness blockers. |
| D1 root README RiskRule semantics stale | **Kept** | Direct contradiction with current intrabar-barrier implementation. |
| D2 examples/candidates stale caveat | **Kept** | Source confirms checked-in examples/candidates now emit `TargetDecision`. |
| D3 doc MECE / no `HISTORY.md` | **Kept as doc-discipline support** | It explains drift, but the actionable blocker is the concrete stale contract docs. |
| Available-at absent from root/code contract | **Kept, narrowed** | Consumer docs cover it, but root README strategy contract and decision model docstring do not surface the row schema at the authoring boundary. |
| Non-aligned calendar raw `missing_mark` | **Moved to open question** | Source shows the behavior, but I did not verify current `quant_data` can produce such panels on supported loaders. |
| Concentration never gated | **Dropped as false positive for tradeability** | 100% single-name exposure can be a legitimate portfolio choice; concentration is an optional operator risk policy, not inherent feasibility. |
| `bars` parameter name, minimal example, RunResult accessors | **Demoted** | Ergonomic improvements, not foundation trust blockers. |

## Findings

### 1. P0 - Quick-run `micro` causality creates a retention-contract conflict

- **Action class**: Refactor
- **Evidence**:
  - `check_micro_causality` returns the underlying replay result and records
    warnings for violations (`src/quant_strategies/causality.py:268`, `:309`).
  - `_prepare_micro_causality_evidence` discards that pass/fail result and returns
    a synthetic `LookaheadCheckResult(passed=True, mode="emitted", replay_scope="micro")`
    (`src/quant_strategies/runner/__init__.py:447`, `:483`).
  - Quick run only fails at the causality stage when `not causality.passed`
    (`src/quant_strategies/runner/__init__.py:222`, `:231`).
  - `TODOS.md` states micro evidence is a Train/autoresearch replay annotation,
    not validation/evaluation/promotion evidence.
- **Why it matters**: First principles: a quick-run score can be useful while
  still not being retention-safe. The problem is ambiguity. If
  `quant_autoresearch` treats micro-mode `RunResult.succeeded` as "ready for
  validation/evaluation," a detected lookahead can advance as a warning.
- **Root cause**: Contract boundary drift between fast iteration evidence and
  tradeability evidence.
- **Recommendation**: Pick one contract and encode it:
  - If micro is allowed to score for iteration, make that result explicitly
    non-retainable unless a gating replay has passed.
  - If quick-run `succeeded` is intended to mean retainable, make hard micro
    violations fail scoring.
- **Tradeoff**: Gating micro can create false negatives from tiny samples; allowing
  micro to score requires a separate retention flag or downstream rule.
- **Verify**: Add a fixture where micro detects a violation and assert either
  `succeeded=False` or `retainable=False` with a clear field name.

### 2. P0 - Required validation/evaluation scenarios do not consistently carry quick-run scoreability verdicts

- **Action class**: Refactor
- **Evidence**:
  - Quick run fails when `foundation is None or not foundation.feasible`
    (`src/quant_strategies/runner/__init__.py:257`, `:268`).
  - `build_portfolio_foundation` emits non-raising infeasible verdicts for
    `zero_cost` and `insufficient_samples`
    (`src/quant_strategies/core/portfolio_foundation.py:1537`).
  - Validation's `SpineBackend` calls `build_portfolio_foundation` but ignores
    `foundation.feasible` and returns `status="completed"` with metrics
    (`src/quant_strategies/validation/engine_backend.py:51`, `:76`).
  - Evaluation uses `walk_portfolio_book`, whose docstring says zero-cost and
    minimum-sample verdicts are intentionally not applied
    (`src/quant_strategies/core/portfolio_foundation.py:478`, `:498`).
  - Default evaluation includes required `zero_costs` scenarios
    (`src/quant_strategies/evaluation/scenarios.py:50`).
- **Why it matters**: The project can say "same book everywhere" and still have
  different meanings of scoreable evidence. A required scenario that would be
  non-scoreable in quick run should not silently become successful evidence in a
  later one-run filter.
- **Root cause**: Result contract. Feasibility exists in the book but is not a
  first-class validation/evaluation scenario result in all cases.
- **Recommendation**: Carry `FeasibilityVerdict` on validation/evaluation scenario
  results. Required base/realistic scenarios should fail closed on non-scoreable
  verdicts. Zero-cost/reference scenarios can remain diagnostic only if marked
  optional or explicitly `scoreability_bearing=false`.
- **Tradeoff**: This changes some current evaluation semantics, especially default
  required zero-cost scenarios. The safer alternative is to keep them but label
  them non-scoreability-bearing.
- **Verify**: Add tests where zero-cost or insufficient-sample books cannot yield a
  successful required validation/evaluation result without explicit diagnostic
  labeling.

### 3. P0 - The operator-frozen envelope is underbounded and lacks provenance

- **Action class**: Add
- **Evidence**:
  - Costs default to exact zero (`src/quant_strategies/core/config.py:74`).
  - Capacity participation limits require only `> 0`, and impact coefficient
    allows `0.0` (`src/quant_strategies/core/config.py:103`, `:105`).
  - Leverage budgets require only `>= 1.0`, with no upper bound or provenance
    marker (`src/quant_strategies/core/config.py:154`).
  - The zero-cost fail-closed check fires only after a scoreable book is walked
    and only in `build_portfolio_foundation`
    (`src/quant_strategies/core/portfolio_foundation.py:1551`).
- **Why it matters**: "Frozen" is currently a convention around TOML sections.
  Without realism floors or provenance, an agent can make an infeasible strategy
  look feasible by relaxing the envelope.
- **Root cause**: Missing trust-boundary metadata and weak config validation.
- **Recommendation**: Add operator provenance and explicit realism floors:
  positive cost floor, positive impact coefficient for `adv_impact`, realistic
  max participation bounds, and explicit approval for unusually high leverage.
  Treat untrusted envelope provenance as non-retainable even if the run scores.
- **Tradeoff**: Profiling configs need an explicit non-scoreable mode.
- **Verify**: Config and quick-run tests for unrealistic but currently valid
  envelopes.

### 4. P0 - Shorts can be scored without borrow/carry when net exposure is <= 1.0

- **Action class**: Add
- **Evidence**:
  - Only `crypto_perp_funding` is marked as financed
    (`src/quant_strategies/core/portfolio_foundation.py:34`).
  - The unfinanced verdict checks `net > 1.0`
    (`src/quant_strategies/core/portfolio_foundation.py:1522`).
  - A long/short book with gross 1.2 and net 0.0 is tested feasible
    (`tests/test_portfolio_foundation.py:733`).
  - `FOUNDATION_LOCK.md` accepts asset-class financing realism beyond crypto-perp
    funding as follow-on debt, and `TODOS.md` says borrow/rollover/margin data
    coverage is blocked upstream.
- **Why it matters**: Accepted debt can still violate the current objective. A
  short equity/FX book with no borrow, locate, dividend, or carry term is not
  honestly tradeable just because net exposure stays within 1.0.
- **Root cause**: Market model incompleteness hidden behind a net-leverage guard.
- **Recommendation**: Add a typed fail-closed short-financing verdict for asset
  classes without modeled short/carry costs, or add an operator-frozen borrow/carry
  model and charge it inside the book.
- **Tradeoff**: This blocks some valid short research until data coverage/modeling
  lands. That is preferable to scoring free shorts as feasible.
- **Verify**: Equity/FX short fixtures with gross <= budget and net <= 1.0 fail
  with a typed financing verdict unless a financing model is configured.

### 5. P1 - Validation has a hard-coded gross > 1.0 preflight that bypasses the leverage budget

- **Action class**: Refactor
- **Evidence**:
  - `exposure_admissibility_violations` flags gross over 1.0 without reading
    `LeverageBudgetConfig` (`src/quant_strategies/core/exposure.py:13`).
  - Validation runs this before backend execution and sets
    `failure_stage="exposure_admissibility"` (`src/quant_strategies/validation/_pipeline.py:443`).
  - Tests assert the backend is not called for `weight = 1.01`
    (`tests/test_validation_runner.py:1519`).
  - The book itself supports configured gross/net budgets and typed
    `leverage_budget_breach` verdicts
    (`src/quant_strategies/core/portfolio_foundation.py:1496`).
- **Why it matters**: Validation can reject a deliberately financed leveraged
  book before the authoritative book applies the operator-frozen budget. That
  fights the target-book contract, where strategy declares intent and the engine
  owns feasibility.
- **Root cause**: Legacy guard retained beside the book's own feasibility owner.
- **Recommendation**: Remove the preflight or parameterize it with the scenario
  leverage budget; prefer letting the spine emit the typed verdict.
- **Verify**: Validation test where gross > 1.0 but within configured crypto-perp
  budget reaches the spine; breach still fails with `leverage_budget_breach`.

### 6. P1 - Quick-run hot path carries avoidable performance and significance weight

- **Action class**: Simplify
- **Evidence**:
  - `causality_check` defaults to `"strict"` with no default `strict_probe_limit`
    (`src/quant_strategies/runner/config.py:102`).
  - The performance test covers emitted grouping but only comments that strict
    integration budgets cover realistic default behavior
    (`tests/test_performance_regressions.py:636`).
  - `adv_notional_before` scans prior rows and recomputes notional per execution
    event (`src/quant_strategies/core/portfolio_foundation.py:641`).
  - Row hashing JSON-serializes each storage row
    (`src/quant_strategies/data_contract.py:926`).
  - Quick-run return statistics include DSR inputs, effective sample size,
    skew/kurtosis, and deflated-Sharpe threshold
    (`src/quant_strategies/core/portfolio_foundation.py:1570`, `:1694`).
  - Evaluation explicitly does not add PSR/DSR/PBO because significance is the
    consumer's responsibility (`src/quant_strategies/evaluation/_spine_metrics.py:15`).
  - `_shape` and `_shape_from_chunks` standardize with sample stdev but divide
    moments by `n`, so DSR inputs carry avoidable convention risk
    (`src/quant_strategies/core/portfolio_foundation.py:2137`, `:2176`).
- **Why it matters**: G6 needs seconds-scale iteration. Search-adjusted
  significance is not a property of one quick run, and only `quant_autoresearch`
  knows the search pressure.
- **Root cause**: Diagnostic/statistical concerns accumulated inside the execution
  spine instead of outside the hot scoring path.
- **Recommendation**: Default quick-run iteration to a bounded gating replay mode;
  add prefix-sum ADV lookup; reduce canonical hash overhead; retire DSR from the
  default spine or move it behind an explicit optional analysis utility. If DSR
  stays, fix the moment convention and raise the sample floor.
- **Verify**: Runtime-budget tests for default quick run and ADV impact; unit
  tests for any retained DSR/statistics convention.

### 7. P1 - Active docs mislead strategy authors on current executable semantics

- **Action class**: Retire
- **Evidence**:
  - Root `README.md` says `RiskRule` thresholds are evaluated on end-of-bar
    fill-price samples, not intrabar high/low barriers (`README.md:135`).
  - The book uses intrabar high/low barriers with conservative same-bar tie
    behavior and gap-worsened adverse fills
    (`src/quant_strategies/core/portfolio_foundation.py:1390`,
    `src/quant_strategies/core/portfolio_foundation.py:1436`).
  - `docs/foundation-surfaces.md` says checked-in examples/candidates do not yet
    implement the target-book contract (`docs/foundation-surfaces.md:344`).
  - Current checked-in candidates and `examples/simple_momentum` import and emit
    `TargetDecision` (`candidates/crypto_perp_funding_crowding_reversal/strategy.py:52`,
    `examples/simple_momentum/strategy.py:39`).
  - The root README strategy contract section covers params/observations/risk
    rules but does not surface the `available_at` row schema constraint; the row
    contract enforces `available_at` as required
    (`README.md:120`, `src/quant_strategies/data_contract.py:250`,
    `src/quant_strategies/data_contract.py:505`).
- **Why it matters**: Strategy-author ergonomics are a correctness boundary for
  agent-written strategies. Wrong stop semantics or missing causal row-schema
  guidance can produce non-retainable strategies before the engine even runs.
- **Root cause**: Active documentation duplicated migration-era statements instead
  of owning current contracts once.
- **Recommendation**: Fix root RiskRule wording, remove the stale example/candidate
  caveat, add root-level `available_at` guidance at the strategy-author boundary,
  and move migration chronology to `HISTORY.md` or an archive so active docs stay
  current-state only.
- **Verify**: Doc grep/tests for intrabar `RiskRule`, target-book examples, and
  `available_at` guidance.

## Open Questions / Demoted Concerns

| Concern | Disposition | Why not a main finding |
|---|---|---|
| Non-aligned multi-symbol calendars produce `missing_mark` raw failures | Open question | Source shows the behavior (`_RowIndex.mark_at` + union timestamps), but I did not verify supported `quant_data` loaders produce non-aligned panels. |
| Single-name concentration has no gate | Demoted | A 100% single-name target can be tradeable; concentration is an optional risk-policy envelope, not inherent feasibility. |
| `core/engine_runner.py` mentions `RunEconomics` | Dropped | The dependency is `TYPE_CHECKING`-only with postponed annotations; low-value cleanup, not a foundation issue. |
| Duplicate config base/path helpers | Demoted | Real maintainability cleanup, but no current evidence it can pass fake evidence. |
| Strategy function params named `bars` instead of `rows` | Demoted | Ergonomic consistency issue, not a foundation trust issue. |
| No tiny hello-world example | Demoted | Useful authoring improvement; not a blocker because `docs/consumer/README.md` has an inline minimal example. |
| `RunResult.foundation` / `economics` `None` preconditions | Demoted | Worth documenting, but consumer success check is already `result.succeeded`. |

## Overbuilt / Underbuilt / Right-Sized

- **Overbuilt**: DSR/significance in the quick-run spine, overlapping causality
  vocabularies, validation exposure preflight beside the book's budget verdict.
- **Underbuilt**: Envelope provenance/floors, short financing fail-closed
  verdicts, cross-surface scoreability metadata, retention-safe causality state.
- **Right-sized**: `TargetDecision`, `StrategyExecutionSpec`, lazy data boundary,
  one netted book, typed `FeasibilityVerdict`, validation/evaluation as one-run
  filters over supplied candidates.

## Prioritized Recommendations

| No. | Status | Priority | Action class | Finding / recommendation | Rationale | Verify |
|---:|---|---|---|---|---|---|
| 1 | Addressed | P0 | Refactor | Resolve the quick-run micro retention contract: hard violations gate, or micro scores are explicitly non-retainable. | Implemented `RunResult.retainable` / `RunResult.retainability`; micro can score for diagnostics but is non-retainable when it is not complete retention proof or records replay warnings/timeouts. | Focused quick-run tests assert micro warning/timeout results have `retainable=False`. |
| 2 | Open | P0 | Refactor | Carry `FeasibilityVerdict` consistently through required validation/evaluation scenarios. | Same book is not enough; same scoreability semantics are required. | Zero-cost/flat required scenarios cannot silently succeed as scoreable evidence. |
| 3 | Addressed | P0 | Add | Add envelope realism floors and operator provenance. | Implemented `[envelope] operator_frozen = true` plus quick-run retainability checks for missing provenance, zero costs, zero ADV impact coefficient, and participation limits above `1.0`. | Focused quick-run tests assert unrealistic/untrusted envelopes score only as non-retainable diagnostics. |
| 4 | Addressed | P0 | Add | Fail closed or price shorts for asset classes without borrow/carry modeling. | Implemented typed `unpriced_short_financing` fail-closed verdict in the shared book for non-financed data kinds; crypto-perp funding remains exempt. | Focused book tests assert equity shorts fail and crypto-perp shorts remain financed. |
| 5 | Open | P1 | Refactor | Remove or budget-parameterize validation's hard gross > 1.0 preflight. | The spine should own leverage-budget feasibility. | Leveraged financed book reaches spine; breach returns typed verdict. |
| 6 | Open | P1 | Simplify | Trim quick-run hot-path weight: bounded replay default, ADV prefix sums, cheaper row hash, DSR outside default spine. | G6 depends on lean Train iteration. | Runtime-budget tests and DSR/stat tests if retained. |
| 7 | Open | P1 | Retire | Fix stale active docs: RiskRule semantics, example/candidate caveat, `available_at` authoring guidance. | Wrong docs create wrong strategies. | Doc grep/tests for current semantics. |

## Preservation Constraints

- Preserve the target-book ontology; do not reintroduce open/close ticket scoring
  or additive signal stacks.
- Preserve the one netted portfolio book as the money model for all three public
  surfaces.
- Preserve lazy imports and the `quant_data` ownership boundary.
- Preserve validation/evaluation as one-run filters over supplied candidates; do
  not turn this repo into a search/ranking/promotion system.
- Preserve `result.succeeded` as the consumer success check, but make its
  retention meaning unambiguous under quick-run causality modes.

## NOT in Scope

- Implementing the fixes listed above.
- Strategy generation, ranking, promotion, paper trading, or live trading.
- Reworking candidates beyond using them as evidence.
- Auditing `quant_autoresearch` internals.

## Verification Summary

- **Verified**: source traces through quick run, shared execution, target
  decisions, portfolio book, validation backend/policy, evaluation backend,
  config bounds, performance-sensitive code paths, active docs, and the
  2026-06-11 Claude review findings.
- **Narrowed or dropped**: concentration as feasibility blocker, `engine_runner`
  type-checking import, duplicate config base as a material risk, and several
  pure ergonomics items.
- **Not verified**: full test suite, real `quant_data` runtime, absolute 1M-row
  wall-clock, and downstream `quant_autoresearch` config behavior.
- **Phase 1 status**: recommendations No. 1, No. 3, and No. 4 are addressed for
  quick-run retainability. Recommendation No. 2 remains Phase 2 filter parity.
- **Residual risk**: until filter parity is resolved, validation/evaluation may
  still interpret scoreability differently from quick run.
