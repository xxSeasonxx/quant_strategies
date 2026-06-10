# Live-Feasibility Foundation Review

Date: 2026-06-10
Reviewer: Codex, local foundation, architecture, adversarial, and quant math lenses
Target: `/Users/Season_Yang/Personal/quant_strategies`

## Review Objective

I reviewed this repository as a strategy foundation for downstream
`quant_autoresearch`, with special attention to the quick-run path and whether
iteration can remain realistic enough that later live-trading review is not
poisoned by impossible evidence.

I used this objective lock:

`quant_strategies` should serve Season and downstream `quant_autoresearch` by
enabling pure candidate strategies, explicit quick runs, retained-candidate
validation, and frozen-candidate evaluation across a research-to-live-review
lifecycle. A solid foundation should make unrealistic strategy evidence hard to
mistake for live-shaped evidence, especially around causality, costs, sizing,
gross exposure, portfolio path, selection pressure, and stale artifacts. It
should not become an order router, broker adapter, or live risk system.

### Clarified Scope

- In scope: quick run, portfolio foundation, validation/evaluation exposure
  gates, strategy decision ontology, configs/docs/tests that define the
  consumer contract, and current researched artifacts where they reveal
  downstream misuse risk.
- Out of scope: implementing fixes, inspecting `quant_autoresearch`, inspecting
  `quant_data` internals, proving alpha, paper-trading readiness, live-trading
  readiness, and broker/exchange integration.
- Additional user concern: signal overstacking, portfolio gross exposure
  materially above 1.0, and unknown similar feasibility gaps.
- Process limitation: the foundation-review skill normally dispatches fresh
  subagents. The available subagent tool requires explicit user delegation, so I
  ran the required lenses locally and disclose that here.

## Executive Verdict

The foundation is directionally right but not yet safe for autonomous
live-feasibility-oriented iteration unless downstream scoring treats portfolio
admissibility, causality status, realistic costs, and selection pressure as hard
score prerequisites.

The specific overstacking concern is real, but the core code now has the right
first check: validation and evaluation reject aggregate active gross exposure
above 1.0, and the quick-run portfolio foundation also refuses to build a path
when active gross target exposure breaches its configured limit. The unresolved
problem is semantic: a quick run can still be "completed" and even have positive
quick-check trade economics while the portfolio foundation is unavailable. That
is acceptable for a diagnostic runner; it is not acceptable as an implicit Train
score contract.

I did find other live-feasibility risks. They are not evidence that the repo is
bad or needs a rewrite. They are missing gates or explicit contracts around the
research loop boundary: unverified causality being scoreable, optional
selection-pressure metadata, zero-cost stress scenarios, missing gross exposure
utilization metrics, open-ticket rather than rebalance-state semantics, archived
stale artifacts living in the repo, and live-market constraints that are
deliberately outside this repo but not yet represented as downstream blockers.

## Scope And Evidence

Primary code inspected:

- `src/quant_strategies/runner/__init__.py` - quick-run orchestration, result
  status, causality policy, portfolio foundation integration.
- `src/quant_strategies/runner/config.py` - quick-run output settings, foundation
  controls, causality controls.
- `src/quant_strategies/core/portfolio_foundation.py` - lightweight portfolio
  path, active gross exposure check, return statistics, DSR inputs.
- `src/quant_strategies/core/exposure.py` - validation exposure admissibility.
- `src/quant_strategies/engine/evaluation.py` and
  `src/quant_strategies/engine/executable.py` - trade-ticket economics and
  supported decision semantics.
- `src/quant_strategies/evaluation/_portfolio_common.py`,
  `src/quant_strategies/evaluation/vectorbtpro_backend.py`, and
  `src/quant_strategies/validation/_pipeline.py` - survivor-grade exposure
  checks and scenario behavior.

Tests/config/docs inspected:

- `tests/test_portfolio_foundation.py`
- `tests/test_runner_api_cli.py`
- `tests/test_validation_runner.py`
- `tests/test_evaluation_backend.py`
- `tests/test_runner_config.py`
- `PRD.md`, `README.md`, `FOUNDATION_LOCK.md`, `TODOS.md`
- `docs/consumer/README.md`, `docs/consumer/usage-guide.md`,
  `docs/consumer/reference.md`, `docs/foundation-surfaces.md`
- `openspec/specs/quick-run-economics/spec.md`
- `openspec/specs/quick-run-portfolio-foundation/spec.md`
- Candidate and researched quick-run/protocol TOMLs under `candidates/` and
  `researched/`

Not inspected:

- `quant_autoresearch` source, so downstream score-policy findings are inferred
  from this repo's public contract and current artifacts.
- `quant_data` source, so data-quality, liquidity, adjustment, survivorship, and
  availability risks remain upstream assumptions.
- Live exchange/broker behavior, because it is explicitly outside this repo.

## Intended Foundation Model

First principles: a strategy iteration foundation is not a trading system. Its
job is to prevent the research loop from learning from numbers that would be
impossible, noncausal, non-reproducible, or impossible to map to a portfolio
state later.

```text
strategy.py + operator-owned protocol
        |
        v
quick run, diagnostic only
        |
        +-- causal evidence status
        +-- engine trade-ticket economics
        +-- portfolio foundation status and metrics
        +-- cost-stress and selection-pressure metadata
        |
        v
downstream Train score
        |
        | requires: causality admissible, foundation admissible,
        |           realistic costs, risk budget observed, trial count known
        v
retained candidate
        |
        v
validation and evaluation
        |
        v
human live-feasibility review outside this repo
```

Core invariants:

| Concept / boundary | Responsibility | Must be true | Current fit |
|---|---|---|---|
| Strategy file | Pure decision generation | No data loading, no engine calls, no future data | Strong |
| Decision | Target-weight ticket | Individually executable and causally timestamped | Strong, but ticket semantics are not rebalance-state semantics |
| Quick-run economics | Fast trade-ticket diagnostics | Not NAV, not live-shaped return | Correctly labeled |
| Portfolio foundation | Lightweight Train portfolio path | Admissibility and risk evidence must drive scoring | Computed, but nonfatal and under-reports risk utilization |
| Validation/evaluation | Stronger survivor evidence | Reject unsupported/leverage/gross exposure failures | Stronger than quick run |
| Downstream scorer | Candidate ranking | Must not score missing or unverified evidence | Not owned here; needs explicit contract |
| `quant_data` | Data product | Provides causal rows plus any future live-feasibility fields | Upstream assumption |

## What Already Exists And Should Be Preserved

- The public surface separation is correct: quick run, validation run, and
  evaluation run are separate and advisory only (`README.md:20`,
  `README.md:136`, `README.md:151`).
- The docs repeatedly say nothing here authorizes paper or live trading
  (`PRD.md:58`, `PRD.md:84`, `README.md:7`, `README.md:270`).
- Single-ticket leverage is rejected by executable decision semantics
  (`src/quant_strategies/engine/executable.py:30`).
- Validation fails before backend execution on leveraged target weight and
  aggregate exposure breaches (`src/quant_strategies/validation/_pipeline.py:449`,
  `src/quant_strategies/core/exposure.py:38`,
  `src/quant_strategies/core/exposure.py:102`).
- Evaluation prepares portfolio windows through the shared portfolio helper,
  which rejects aggregate gross exposure above one
  (`src/quant_strategies/evaluation/_portfolio_common.py:56`,
  `src/quant_strategies/evaluation/_portfolio_common.py:75`).
- Quick-run portfolio foundation computes a lightweight portfolio path without
  importing heavy evaluation dependencies and rejects aggregate gross exposure
  above the configured limit (`src/quant_strategies/core/portfolio_foundation.py:642`,
  `src/quant_strategies/core/portfolio_foundation.py:691`).
- Candidate run configs committed under `candidates/` are now tested to use
  `causality_check = "micro"` for iteration (`tests/test_runner_config.py:170`).

## Architecture And Boundary Findings

### 1. [P0] Quick-run success is not the same as live-shaped score admissibility

- Action class: Add
- Evidence:
  - `RunResult.succeeded` is only `outcome.completed and failure_stage is None`
    (`src/quant_strategies/runner/__init__.py:130`).
  - Foundation exceptions are caught and converted to warnings, returning
    `foundation=None` without failing the run
    (`src/quant_strategies/runner/__init__.py:852`).
  - The spec explicitly says foundation unavailability must not invalidate an
    otherwise completed quick run
    (`openspec/specs/quick-run-portfolio-foundation/spec.md:12`).
  - A current artifact shows `quick_check_result: passed` while
    `portfolio_foundation_unavailable:...portfolio_target_weight_exceeds_one...1.2`
    is only a warning
    (`researched/crypto_perp_funding_crowding_reversal/candidates/survivors/attempt-99new/artifacts/summary.json:75`).
- Why it matters: the downstream loop can optimize the trade-ticket ledger even
  when the portfolio path is missing. From first principles, a strategy cannot be
  live-feasible if its intended position path cannot be constructed under the
  risk budget.
- Root cause: result contract. Quick run has a run-completion status but no
  first-class "Train score admissibility" state.
- Recommendation: keep quick-run completion nonfatal, but add a typed
  score-admissibility contract that downstream must use. At minimum it should
  distinguish `run_completed`, `causality_admissible`,
  `portfolio_foundation_admissible`, `cost_stress_admissible`,
  `trial_count_admissible`, and `score_allowed`.
- Tradeoff: this adds one public concept. The alternative is relying on warning
  string parsing, which is exactly the misuse path this foundation should avoid.

### 2. [P0] Causality-unverified quick runs can still look like winners

- Action class: Add
- Evidence:
  - `causality_check = "off"` returns a passed lookahead result
    (`src/quant_strategies/runner/__init__.py:971`).
  - `micro` causality intentionally returns `passed=True` for scoring while
    recording unverified replay dimensions
    (`src/quant_strategies/runner/__init__.py:451`,
    `src/quant_strategies/runner/__init__.py:467`).
  - The active researched Train protocols say "focused replay" in comments but
    set `causality_check = "off"`
    (`researched/crypto_perp_funding_crowding_reversal/protocol.train.toml:95`,
    `researched/fx_session_activity_profile_rejection/protocol.train.toml:90`).
  - The same artifact above has `causality_check = "off"`,
    `causality_verified = false`, and positive quick-check gates
    (`researched/crypto_perp_funding_crowding_reversal/candidates/survivors/attempt-99new/artifacts/summary.json:21`,
    `researched/crypto_perp_funding_crowding_reversal/candidates/survivors/attempt-99new/artifacts/summary.json:43`).
- Why it matters: if an agent can receive a positive score with causality off or
  micro-failed, it can accidentally learn from noncausal rules. The docs warn
  about this, but autonomous scoring needs an enforceable contract.
- Root cause: process boundary between quick-run diagnostics and downstream
  scoring.
- Recommendation: add a protocol linter or scoring helper that refuses
  `causality_check = "off"` for scored Train attempts, and that returns no-score
  when micro replay fails, times out, or records unverified causality unless the
  run is explicitly marked profiling-only.
- Tradeoff: this may reduce iteration throughput when micro catches issues, but
  it prevents the loop from reinforcing invalid strategies.

### 3. [P1] Admissible portfolio paths do not expose risk-budget utilization

- Action class: Add
- Evidence:
  - The quick-run foundation enforces active gross exposure at entry time
    (`src/quant_strategies/core/portfolio_foundation.py:689`), but the emitted
    metric record includes `max_symbol_concentration`, not max/average gross
    exposure (`src/quant_strategies/core/portfolio_foundation.py:112`).
  - The concentration metric is share of active gross by top symbol, not active
    gross exposure itself (`src/quant_strategies/core/portfolio_foundation.py:1017`).
  - Docs list quick foundation metric fields without gross exposure utilization
    (`docs/consumer/reference.md:357`).
- Why it matters: two candidates can both be admissible under 1.0 gross, but one
  may use 0.20 gross and another 1.00 gross. Better returns from larger risk
  usage are not the same as better signal quality.
- Root cause: artifact schema under-represents a live-shaped invariant after it
  passes the hard cap.
- Recommendation: add `max_gross_exposure`, `mean_gross_exposure`,
  `gross_exposure_time_integral`, and possibly `return_per_unit_gross` to
  `full_train` and subwindow metrics.
- Tradeoff: these are still diagnostics, not live risk controls. They give the
  scorer enough information to avoid rewarding hidden risk-budget consumption.

### 4. [P1] Selection pressure is optional in quick-run foundation scoring

- Action class: Add
- Evidence:
  - `foundation_trial_count` defaults to `None`
    (`src/quant_strategies/runner/config.py:91`).
  - Missing trial count makes DSR null with a warning
    (`src/quant_strategies/core/portfolio_foundation.py:359`).
  - The consumer guide tells users they may omit it and receive null DSR
    (`docs/consumer/usage-guide.md:258`).
  - The Train protocol records loop budgets such as `max_iterations = 100`, but
    the quick-run `[output]` block does not pass that count into the foundation
    (`researched/crypto_perp_funding_crowding_reversal/protocol.train.toml:86`,
    `researched/crypto_perp_funding_crowding_reversal/protocol.train.toml:110`).
- Why it matters: autoresearch is multiple testing by construction. A candidate
  that only looks good after many attempts needs deflation or explicit "no
  DSR/PSR score" treatment.
- Root cause: search pressure lives downstream, but quick-run foundation exposes
  DSR without requiring the downstream attempt count.
- Recommendation: for scored Train runs, require
  `foundation_trial_count >= current attempted strategy count` or make scoring
  return no-score when DSR/PSR inputs are missing. Also record the source of the
  trial count.
- Tradeoff: exact trial accounting can be annoying for resumed loops, but an
  approximate lower bound is better than treating selection pressure as zero.

### 5. [P1] Cost stress can be vacuous when base costs are zero

- Action class: Add
- Evidence:
  - Foundation cost stress multiplies the configured fee plus slippage bps
    (`src/quant_strategies/core/portfolio_foundation.py:525`).
  - Several committed candidate quick-run configs use zero fees and zero
    slippage, so the cost-stress scenario remains zero-cost
    (`candidates/crypto_perp_funding_crowding_reversal/run.toml:36`,
    `candidates/crypto_perp_multivote_trend_following/run.toml:51`,
    `candidates/fx_triangular_residual_reversion/run.toml:42`).
- Why it matters: live feasibility cannot be inferred from a strategy that only
  survives a zero-cost base and zero-cost stress. This is especially dangerous
  for high-turnover minute strategies.
- Root cause: protocol/config boundary. The cost model is simple and explicit,
  but there is no scored-run policy requiring nonzero realistic costs or proving
  that spread is already in the fill price.
- Recommendation: add a scored-run config lint: either nonzero explicit costs are
  required, or the protocol must declare why costs are embedded in quote fills
  and what additional slippage stress is applied. `foundation_cost_stress_multiplier`
  should not be considered meaningful when base costs are zero.
- Tradeoff: examples and smoke tests can keep zero costs, but scored Train
  protocols should not.

### 6. [P1] The decision ontology is open-ticket, not target-state rebalance

- Action class: Refactor
- Evidence:
  - Default decision actions are only `open`
    (`src/quant_strategies/decisions/models.py:22`).
  - The executable kernel rejects non-open and flat targets
    (`src/quant_strategies/engine/executable.py:20`,
    `src/quant_strategies/engine/executable.py:26`).
  - The PRD explicitly defers close/adjust/roll and other richer actions behind
    future explicit ontology (`PRD.md:128`).
- Why it matters: live portfolios are stateful allocations. Repeated "open"
  tickets can model independent trade opportunities, but they do not naturally
  express "my total desired position in this symbol is 25 percent." The current
  code can reject overstacking after the fact, but it cannot let a strategy state
  its intended total portfolio allocation directly.
- Root cause: ontology. The current minimal executable model is right-sized for
  fast research, but it pushes rebalance semantics into strategy-side suppression
  patterns.
- Recommendation: do not rush this into quick run. First add a short ADR for
  when the project should introduce `target_state` or `rebalance` semantics. In
  the meantime, require strategies that claim live-shaped behavior to document
  same-symbol and portfolio-level suppression logic.
- Tradeoff: keeping the narrow ontology avoids premature live-engine complexity,
  but the downstream loop must not treat repeated open tickets as a live
  allocation policy.

### 7. [P1] Research archives and stale quick-run artifacts live inside the active repo

- Action class: Retire
- Evidence:
  - Current README says research archives, ranks, and search-loop records do not
    live in the active foundation context (`README.md:220`).
  - Git currently tracks 351 paths under `researched/`, including generated
    `summary.json`, `diagnostics.json`, and `artifacts/` outputs.
  - Many of those artifacts have `quick_check_result: passed` and
    `causality_check = "off"` in snapshots or summaries.
- Why it matters: stale artifacts can look like current evidence. For a human
  this is confusing; for an autonomous agent it is a direct source of training
  contamination.
- Root cause: repository boundary drift. The docs describe an archive boundary
  that the current tree violates.
- Recommendation: either move generated research artifacts out of the active
  repo, or explicitly mark `researched/` as frozen historical input that is never
  used for current scoring. Add a repository-boundary test for generated
  artifacts under research archives if the desired policy is still "outside."
- Tradeoff: keeping examples of failed/survivor attempts can be useful for
  forensic review, but they should not sit where active agent context treats them
  as current evidence.

### 8. [P2] Quick-run Sharpe and DSR inputs are cadence-local, not cross-cadence comparable

- Action class: Add
- Evidence:
  - Quick-run foundation Sharpe is sample mean divided by sample stdev, not
    annualized (`src/quant_strategies/core/portfolio_foundation.py:239`).
  - The reference explicitly says the field is not annualized
    (`docs/consumer/reference.md:371`).
  - The quick-run foundation payload does not carry
    `annualization_periods_per_year`; evaluation has a separate annualization
    cadence guard (`README.md:160`).
- Why it matters: if downstream compares minute, daily, FX, and crypto strategies
  using raw quick-run Sharpe/PSR conventions, the ranking can be mathematically
  meaningless.
- Root cause: metric contract. The quick-run foundation is compact and
  dependency-light, but it omits cadence metadata needed for cross-cadence
  comparison.
- Recommendation: either add cadence metadata to the foundation payload or
  state in downstream scoring that quick-run Sharpe/DSR can only rank candidates
  within the same data kind and bar cadence.
- Tradeoff: annualization can create false precision when cadence is irregular;
  cadence metadata plus a same-cadence guard is the safer first step.

### 9. [P2] Capacity, liquidity, margin, liquidation, borrow, and venue constraints are not represented

- Action class: Add
- Evidence:
  - The PRD explicitly says validation does not answer capacity or portfolio
    quality (`PRD.md:79`) and live-trading features such as order routing, margin,
    broker integration, real-time data, and alerts are out of scope
    (`PRD.md:282`, `PRD.md:386`).
  - The current core cost model is only fixed fee and slippage bps
    (`src/quant_strategies/core/config.py:74`).
  - TODO already records missing margin, liquidation-buffer, funding-stress, and
    drawdown-under-leverage evidence as a live interpretation blocker
    (`TODOS.md:149`).
- Why it matters: a strategy can be causally valid, unlevered by target weight,
  and profitable after flat bps costs while still being non-tradable because it
  relies on unavailable liquidity, unstable borrow, unavailable shorting, venue
  limits, or liquidation risk.
- Root cause: product boundary, not a bug. `quant_strategies` should not become
  a live execution system, but downstream promotion needs a visible blocker list.
- Recommendation: create a separate "live feasibility preflight" contract owned
  outside quick run. It should consume evaluation traces plus upstream
  `quant_data` liquidity/venue metadata when available. Until then, all
  candidates should remain "research evidence only."
- Tradeoff: implementing full capacity/margin modeling here would overbuild the
  foundation. The right move is explicit downstream blocking criteria.

## Domain-Specific Quant Findings

### Math And Implementation

I did not find evidence of a new core PnL sign bug in the inspected quick-run
path. The engine computes per-trade gross return as side-signed price return
times weight, funding as a separate signed component, cost as round-trip bps
times weight, and net as `gross + funding - cost`
(`src/quant_strategies/engine/evaluation.py:76`,
`src/quant_strategies/engine/evaluation.py:86`). The quick-run economics object
preserves this as an engine trade ledger, not as portfolio NAV
(`src/quant_strategies/runner/economic_metrics.py:90`).

The main quant issue is not formula correctness. It is evidence admissibility:
which metric is allowed to drive iteration. Trade-ledger totals are useful for
debugging signal behavior, but the first live-shaped score should come from a
causal, costed, admissible portfolio path with selection-pressure metadata.

### Pre-Mortem Failure Narratives

1. **Passed quick checks, impossible portfolio.** Six months from now,
   `quant_autoresearch` has selected a "survivor" because trade-ticket net is
   strong. The portfolio foundation was missing due gross exposure 1.2, but that
   warning was not a hard no-score. The live review discovers the strategy was
   a leverage artifact, and 100+ iterations optimized the wrong behavior.

2. **Causality skip becomes hidden alpha.** An expensive full-panel run uses
   `causality_check = "off"` to avoid timeout. Quick checks pass. Later strict
   validation fails because the strategy uses future availability implicitly.
   The lost time came from treating "scoring completed" as "causally admissible."

3. **Cost stress is zero.** A high-turnover minute strategy survives because the
   protocol uses zero fees/slippage and cost stress multiplies zero. Evaluation
   with realistic spread/impact wipes out the edge. The root cause was not
   missing math; it was a scored-run config with unrealistic economics.

4. **Risk budget masquerades as signal quality.** Two variants have similar
   logic, but one emits more overlapping, still-under-1.0 exposure. It ranks
   higher because it uses more risk, not because the signal improved. The
   foundation lacks mean/max gross utilization in the score payload, so the
   downstream scorer cannot normalize or penalize it.

## Unknown Unknowns And Assumption Risks

| Assumption | Why it may be wrong | How to test or de-risk |
|---|---|---|
| `quant_autoresearch` reads warnings and foundation status correctly | The public success bit remains true when the foundation is missing | Add a typed score-admissibility helper and require it in downstream tests |
| `quant_data` rows represent live-executable tradable universes | This repo does not own liquidity, survivorship, adjustment, venue, borrow, or stale-row policy | Add upstream data-readiness fields or a live-feasibility preflight outside this repo |
| Flat bps costs are conservative enough | For minute crypto/FX, impact, spread regime, funding spikes, and latency can dominate | Require nonzero costs or documented embedded spread plus stress; add turnover metrics |
| Trial count can be reconstructed downstream | Archived attempts and resumed loops can make true search pressure ambiguous | Persist protocol-owned attempt count and selection rule with every scored run |
| Same target-weight semantics can support later live execution | Repeated open tickets are not a rebalance instruction | Add ADR for target-state/rebalance ontology before claiming live-shaped strategy behavior |
| Historical artifacts are not used as current evidence | `researched/` contains tracked summaries and diagnostics | Move archives out or mark them as excluded from active context |

## Overbuilt / Underbuilt / Right-Sized

- Overbuilt: the active repository contains tracked research artifacts and
  generated summaries under `researched/`; that is not foundation capability, it
  is stale context risk.
- Underbuilt: score-admissibility state, causality admissibility policy for
  scored quick runs, gross exposure utilization metrics, realistic-cost protocol
  linting, selection-pressure accounting, and downstream live-feasibility
  blockers.
- Right-sized: the split between quick-run diagnostics, validation, and
  evaluation; the pure strategy contract; the `available_at` causality boundary;
  and keeping broker/live execution out of this repo.

## Documentation And Decision Gaps

- Missing ADR: when to introduce target-state/rebalance semantics versus keeping
  open-ticket strategies only.
- Missing downstream contract: what exactly makes a quick-run result eligible
  for Train scoring.
- Missing protocol lint: scored runs should reject causality off, missing
  foundation, missing trial count, and vacuous cost stress.
- Stale context: docs say research archives live outside the repo, but tracked
  `researched/` artifacts are present.
- Missing live-feasibility checklist: not as a `quant_strategies` feature, but as
  a downstream promotion blocker list.

## Prioritized Recommendations

| No. | Status | Priority | Action class | Finding / recommendation | Rationale | Verify |
|---:|---|---|---|---|---|---|
| 1 | Open | P0 | Add | Add a typed quick-run `score_admissibility` result or helper that requires completed run, admissible foundation, admissible causality, realistic cost stress, and required selection-pressure metadata. | Prevents `RunResult.succeeded` from being mistaken for Train-score eligibility. | Unit test a gross-exposure foundation failure returns `score_allowed = false` while `result.succeeded` can remain true. |
| 2 | Open | P0 | Add | Add downstream/protocol lint that rejects `causality_check = "off"` for scored Train runs and no-scores failed/timed-out micro replay. | Stops the loop from learning from unverified causality. | Test active scored protocols; allow only explicitly marked profiling configs to use `off`. |
| 3 | Open | P1 | Add | Emit max/mean gross exposure and gross exposure time integral in quick-run foundation metrics. | Distinguishes better signal from larger risk-budget usage. | Tests in `test_portfolio_foundation.py` for 0.25, 0.75, and 1.0 active gross paths. |
| 4 | Open | P1 | Add | Require `foundation_trial_count` or explicit no-score for scored Train runs. | Multiple testing is unavoidable in autoresearch. | Test missing trial count blocks score but still permits diagnostic quick run. |
| 5 | Open | P1 | Add | Add scored-run cost realism lint: nonzero costs, or documented embedded spread plus nonzero stress. | Avoids cost-stress scenarios that multiply zero. | Test candidate/scored configs fail when fee and slippage are both zero without an embedded-spread declaration. |
| 6 | Open | P1 | Refactor | Write an ADR for future target-state/rebalance semantics; until then, require strategies to document suppression/re-entry behavior. | Repeated open tickets are not live allocation state. | ADR plus strategy-docstring/test requirement for live-shaped candidates. |
| 7 | Open | P1 | Retire | Move tracked generated research artifacts out of active repo or mark `researched/` as excluded historical context. | Prevents stale artifact contamination. | Repository-boundary test for generated `summary.json` / `diagnostics.json` under active context. |
| 8 | Open | P2 | Add | Add cadence metadata or same-cadence-only scoring rule for quick-run Sharpe/DSR. | Avoids cross-cadence ranking errors. | Test payload includes cadence metadata or downstream rejects mixed-cadence comparisons. |
| 9 | Open | P2 | Add | Create a downstream live-feasibility preflight checklist for capacity, liquidity, margin, liquidation, borrow, venue limits, and funding stress. | Keeps live constraints visible without overbuilding this repo. | Checklist used before any paper/live promotion discussion. |

## Preservation Constraints

- Preserve the public vocabulary: quick run, validation run, evaluation run.
- Preserve quick-run as diagnostic and dependency-light; do not import
  VectorBT/Pandas/Numpy into the quick-run hot path.
- Preserve validation/evaluation as stronger survivor evidence, not promotion
  authority.
- Preserve the pure strategy contract and the rule that data acquisition,
  repair, and joining belong upstream in `quant_data`.
- Preserve the explicit "not paper/live eligible" fields until Season approves a
  separate promotion standard.

## NOT In Scope

- Building order routing, broker integration, real-time risk, or live position
  keeping inside `quant_strategies`.
- Proving any current candidate has alpha.
- Rewriting the engine into a general backtesting framework.
- Making quick-run portfolio foundation survivor-grade evaluation evidence.

## Verification Summary

- Verified: source and docs inspected with CodeGraph and line-numbered reads;
  reviewed current quick-run, portfolio foundation, validation/evaluation
  exposure paths; inspected active/researched configs and representative
  artifacts.
- Not verified: no tests were run because this was a review artifact only; no
  source behavior was changed. I did not inspect `quant_autoresearch` or
  `quant_data`.
- Residual risk: downstream may already enforce some of these rules. Without
  inspecting it, I treated missing contracts in this repo as integration risks,
  not proven downstream bugs.
