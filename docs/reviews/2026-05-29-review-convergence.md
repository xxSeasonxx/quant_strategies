# Convergence Review: `review-codex.md` and `review-claude_v2.md`

Date: 2026-05-29
Reviewer: Codex
Scope: convergence of `review-codex.md` and `review-claude_v2.md`, with spot source verification

## Executive Verdict

The two reviews converge on the important answer: the foundation is worth
keeping, but it should not be trusted as a validation verdict producer until the
validation metric contract is fixed.

This is not a rewrite project. The correct roadmap is focused:

1. Fix the validation gate math and naming.
2. Make the lookahead checker honest when strict probes are skipped.
3. Simplify the public research workflow back to two steps: quick run and
   validation run.
4. Add one validation-ready example so agents learn the strict handoff path.
5. Retire or demote vocabulary and artifacts that imply more authority than
   the system actually has.

The main false-positive risk in both reviews is treating every confusing or
large surface as a foundation blocker. Some of those are real cleanup items, but
not all are worth doing before returning to actual research work. Low-impact
work is moved to `TODOS.md` with explicit limitations.

## Method And Evidence

I compared only:

- `review-codex.md`
- `review-claude_v2.md`

I did not open or rely on the original `review-claude.md`.

I spot-checked the claims against:

- `PRD.md`
- `README.md`
- `docs/runner.md`
- `docs/validation.md`
- `docs/quant-autoresearch-consumer.md`
- `src/quant_strategies/runner/`
- `src/quant_strategies/validation/`
- `src/quant_strategies/causality.py`
- `src/quant_strategies/evidence_semantics.py`
- `src/quant_strategies/engine/`
- `src/quant_strategies/decisions/`
- `runs/`
- targeted tests by source inspection

I did not run a new subagent round for this convergence pass. The two review
artifacts already represent independent review passes; this pass used source
verification and false-positive filtering rather than adding more opinions.

## Converged High-Confidence Findings

### P1. Validation compounds a non-NAV activity metric

Status: confirmed.

Both reviews are right. `validation/policy.py` computes
`compounded_realistic_net = prod(1 + net_return) - 1` and gates on
`compounded_realistic_net_positive`. The metric being compounded is documented
elsewhere as an engine linear signed trade-activity sum, not a NAV-path return.
`validation/agreement.py` explicitly says the linear sum equals a NAV path only
for a single trade, and skips the VectorBT Pro oracle for multi-trade scenarios.

Roadmap action: refactor the policy to either:

- aggregate the linear activity metric linearly and rename the gate, or
- introduce a true per-window NAV-path return and compound only that.

Do this before trusting any validation verdict label.

### P1. Strict lookahead replay can overstate verification

Status: confirmed, with scope clarified.

The checker skips pure suppression-probe boundaries when a strategy raises on a
short prefix. That is defensible for quick iteration, but the result can still
end as strict-suppression verified. That is the wrong evidence contract. Missing
or invalid `available_at` also falls back to timestamp-only visibility.

Roadmap action: make incomplete strict replay explicit. Count skipped strict
probes, set strict suppression verification false when probes are skipped, and
surface a reason such as `strict_suppression_incomplete`. Add a deterministic
double-run check for validation candidates.

### P1. The workflow vocabulary must collapse back to two user actions

Status: confirmed.

The mechanism is already mostly two steps: quick run and validation run. The
problem is the vocabulary around those steps: `screen`, `gate`, `validate`,
`row_contract`, `artifact_profile`, `artifact_trust_tier`, `paper_readiness`,
`search_pressure`, `backend`, `agreement_oracle`, and verdict labels all appear
near the user-facing path. Most terms are real, but many are at the wrong
altitude for the daily research loop.

Roadmap action:

- Keep quick run as the cheap ranking loop.
- Keep validation run as the strict retained-candidate loop.
- Push artifact/replay/backend terminology down into reference docs and
  artifacts, not the on-ramp.
- Resolve the current public API contradiction: `README.md` and `PRD.md` imply
  `run_validation` is a stable consumer API, while
  `docs/quant-autoresearch-consumer.md` says not to import
  `quant_strategies.validation`.

Preferred resolution: bless `quant_strategies.validation.run_validation` as the
retained-candidate API, while keeping quick-run autoresearch on
`quant_strategies.runner.run_config`.

### P1. There is no validation-ready example

Status: confirmed.

`runs/` contains quick-run configs only, and visible example strategies do not
define `validate_params`. Validation correctly requires `validate_params`, but
the repo does not teach the handoff path from a retained quick-run candidate to
a validation candidate.

Roadmap action: add one canonical validation-ready example with:

- a pure strategy
- `validate_params`
- a quick-run config
- a validation config with windows
- a focused test that exercises the validation handoff without requiring live
  market infrastructure

### P2. Search pressure is advisory, but absence is not explicit enough

Status: real issue, but the strongest proposed fix was too broad.

The Claude review recommends making search pressure mandatory at the gate. The
Codex review recommends preserving advisory treatment. The better design is in
between: validation should require an explicit disclosure, not necessarily a
statistical correction.

Roadmap action: require retained-candidate validation configs to state one of:

- no prior search
- search pressure known, with `candidate_count`/`trial_count`/selection rule
- search pressure unknown

If unknown or searched, keep the verdict advisory and downgrade or annotate
mechanical review status. Do not hide a multiple-testing correction inside this
repo.

### P2. The VectorBT Pro oracle is currently not a real multi-trade validator

Status: confirmed, with false-positive correction.

It is true that the agreement oracle is off by default and skips non-single
trade scenarios. It is also true that current docs describe it as an opt-in
single-trade agreement oracle, not a co-equal verdict backend. So the false
positive would be claiming production validation secretly depends on VectorBT
Pro. It does not.

Roadmap action: either retire the oracle from the foundation surface for now, or
rebuild it as a trade-ledger/path-level comparison that is meaningful for
multi-trade scenarios. Until then, it should not be used as comfort for
validation verdict correctness.

### P2. Executable decision semantics are duplicated

Status: confirmed.

The executable subset of `StrategyDecision` is checked separately in
`engine/evaluation.py`, `runner/engine_runner.py`, and
`validation/vectorbtpro_backend.py`. Extended ontology types are intentionally
outside the default path, but they remain easy to misread as executable because
they are schema-valid.

Roadmap action: create one engine-owned executable-decision adapter or
capability check, and make runner/validation consume it. Keep extended ontology
clearly opt-in and non-executable until there is an execution path.

### P2. Artifact authority boundaries need tightening, not broad artifact fear

Status: partially confirmed.

The stronger "artifact bias is currently driving conclusions" claim is not
proven. The better claim is narrower: stale generated artifacts and old result
configs are a bias vector for humans and agents because they are nearby and
look like examples.

Confirmed examples:

- `results/notebook_configs/crypto_perp_autoresearch_ensemble_validate.toml`
  still contains `mode = "validate"`.
- PRD says generated results should not land in source or version-controlled
  trees, but config validation currently checks containment more than ignored
  artifact-root policy.

Roadmap action: document generated artifacts as low authority, reject output
dirs under source/tracked areas, and avoid preserving compatibility with old
generated configs.

### P2. Replayability is overstated by a global manifest flag

Status: confirmed as an edge-case contract issue.

`validation_manifest.json` sets `verdict_replayable` true when any scenario has
a trade ledger. That can overstate replayability for mixed or zero-trade
scenario sets.

Roadmap action: track replayability per required scenario and compute the
global flag conservatively.

## Findings Downgraded Or Removed As Roadmap Drivers

### Large `__init__.py` modules are not immediate architecture blockers

The files are large, but the inspected `run_config` and `run_validation` flows
are staged orchestrators, not evidence of a failed architecture. Splitting them
may help later, but doing it now would create churn before the semantic fixes.

Disposition: defer to `TODOS.md`.

### Parquet is not justified yet

The PRD conflicts with implementation and docs: PRD calls for parquet for bulk
audit artifacts, while current code/docs use JSONL. The conflict is real, but
the right first move is not to add parquet. Bless JSONL v1 unless a scale
benchmark proves it inadequate.

Disposition: include in roadmap as a docs/ADR decision, not an implementation
rewrite.

### Purity lint gaps are not a security finding

The purity lint is explicitly best-effort. Missing bans for some side-effect
modules are worth tightening for agent reliability, but this should not distract
from validation semantics and workflow simplification.

Disposition: defer to `TODOS.md`.

### Backend `SystemExit` escaping is low impact under current usage

The direct backend injection seam can propagate `SystemExit` in tests. Since the
normal engine path is not a user-authored backend and CLI backstops many raw
failures, this is not a top-roadmap item.

Disposition: defer to `TODOS.md` unless custom validation backends become a
real public extension point.

### Stop/take/trailing exits are a modeling limitation, not a foundation fire

The engine uses selected fill prices for threshold exits rather than high/low
bar-path triggers. That matters for stop-heavy strategies, but it is not the
same class of issue as compounding a non-NAV metric. The immediate fix is to
document the fill convention honestly; high/low path semantics can follow when
validated strategies need it.

Disposition: roadmap documentation first; implementation later.

## Execution Roadmap

### Phase 1: Make Validation Honest

1. Fix validation aggregation over `net_return`.
   - Rename the current gate if keeping linear activity aggregation.
   - Add regression tests where sum and compounding disagree.
   - Update `docs/validation.md`, `docs/quant-autoresearch-consumer.md`, and
     PRD wording so the metric unit and gate name agree.

2. Make strict lookahead evidence fail closed.
   - Track skipped strict probes.
   - Set `causality_verified = false` when strict probes are incomplete.
   - Add validation-candidate determinism checks.
   - Add tests for prefix-fragile and nondeterministic strategies.

3. Add the validation-ready example.
   - Keep it small and synthetic.
   - Include `validate_params`.
   - Include quick-run and validation configs.
   - Add one focused test for the handoff path.

### Phase 2: Make The Workflow Smaller

1. Resolve the validation API contract.
   - `run_config` is the quick-run API.
   - `run_validation` is the retained-candidate validation API.
   - `quant_autoresearch` should not import private validation modules or own
     validation internals.

2. Simplify the quick-run surface.
   - On the on-ramp, present only quick run and validation run.
   - Move replay/artifact/backend vocabulary to reference docs.
   - Decide whether autoresearch quick runs should use emitted-only replay by
     default or keep strict replay while exposing an explicit fast mode. If a
     quick run skips strict suppression replay, it must say so in the result.

3. Require explicit validation search-pressure disclosure.
   - Unknown is allowed, but not silent.
   - Unknown/searched candidates remain advisory and should not be mechanically
     promoted.

### Phase 3: Remove Misleading Comfort

1. Retire or rebuild the VectorBT Pro agreement oracle.
   - Do not present it as validation confidence until it handles multi-trade
     cases meaningfully.

2. Centralize executable-decision checks.
   - One engine-owned adapter/check.
   - Runner and validation reuse it.
   - Extended ontology remains opt-in and clearly non-executable until supported.

3. Tighten artifact authority.
   - Reject output roots under source/tracked trees.
   - Mark generated artifacts as lower authority than source/tests/configs.
   - Do not back-compat old generated result shapes.

4. Make validation replayability conservative.
   - Per-scenario replayability.
   - Global replayable only when all required completed scenarios are
     ledger-backed.

### Phase 4: Low-Churn Cleanup

1. Decide JSONL-vs-parquet by ADR or PRD edit.
2. Document selected-price stop/take/trailing semantics.
3. Opportunistically split large public package modules when already touching
   their internals.
4. Tighten purity lint and brittle tests as maintenance work.

## What To Do Next

The next actual work should be Phase 1, item 1: fix validation aggregation and
tests. It is the clearest correctness bug, and it will force the right naming
and documentation cleanup without touching unrelated architecture.
