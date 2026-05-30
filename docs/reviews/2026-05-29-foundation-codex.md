# Foundation Review: quant_strategies

Date: 2026-05-29
Reviewer: Codex, senior quant researcher lens
Target: repository root, with emphasis on `src/quant_strategies/`, `untested/`, `runs/`, tests, and PRD/docs

## Review Objective

I reviewed `quant_strategies` as a lightweight research sandbox and disciplined pure-strategy library for coding agents and `quant_autoresearch`.

The locked objective: the repo should make strategy authoring, quick runs, validation runs, and runner API integration simple and auditable. A solid foundation should make new agent-generated strategies easy to author, quick-run, and validation-run; keep strategy modules pure; make validation failures explicit and reproducible; and let `quant_autoresearch` reuse public runner APIs. It should prevent vocabulary sprawl, artifact-driven bias, overbuilt runner/config design, hidden side effects, and silently unvalidated validation runs.

This review is not a request for a broad rewrite. The goal is to identify whether the current foundation is sound, where it fights the intended research workflow, and what should be preserved, refactored, simplified, added, or retired.

## Executive Verdict

The foundation is directionally strong but not yet fully trustworthy for validation semantics. The right spine exists: flat pure strategies, `StrategyDecision`, shared `StrategyExecutionSpec`, one quick-run path, validation reusing the execution kernel, explicit row contracts, strict replay, advisory-only verdict flags, and ignored result directories. That should be preserved.

The main problem is not that the repo is generally over-engineered. The problem is that several concepts now drift against the two actual workflows, quick run and validation run. Most importantly, validation compounds `net_return` even though `net_return` is explicitly defined as a linear signed trade-activity sum, not a NAV-path return. That is a foundation-level quant semantics bug. The next risks are public API/documentation ambiguity for validation, validation examples that are not validation-ready, and artifact behavior that can still leak raw failures or stale vocabulary into agent workflows.

Bottom line: do not rewrite the core architecture. Fix the validation metric contract first, then simplify the workflow surface and retire stale artifact authority.

## Scope And Evidence Inspected

Primary evidence inspected:

- Repo instructions and constraints: `AGENTS.md`.
- Target intent and claims: `PRD.md`, `README.md`, `docs/runner.md`, `docs/validation.md`, `docs/quant-autoresearch-consumer.md`, `TODOS.md`.
- Package metadata: `pyproject.toml`.
- Core source: `src/quant_strategies/core/`, `decisions/`, `runner/`, `validation/`, `engine/`, `data_contract.py`, `causality.py`, `evidence_semantics.py`.
- Strategy surface: `untested/*.py`, `examples/strategies/simple_momentum.py`, `runs/*.toml`.
- Tests: full suite and targeted runner/validation/decision tests.
- Generated/legacy artifact evidence: sampled `researched/` and ignored `results/` only to assess artifact-bias risk.

Explicitly not inspected:

- `review-claude.md`. I did not open, grep, summarize, or rely on it.
- `quant_data` internals, live database connectivity, real market data quality, or actual `quant_autoresearch` source.
- VectorBT Pro runtime behavior beyond source and tests.
- Every generated package under `researched/`; those artifacts were treated as low-authority evidence.

Perspective lenses used:

- Onboarding lens.
- Architecture lens.
- Senior software engineering and workflow ergonomics lens.
- Adversarial lens.
- Senior quant researcher and quant math/code lens.

Verification run:

```bash
conda run -n quant pytest -q
```

Result: `644 passed in 22.60s`.

## Intended Foundation Model

From first principles, the minimal foundation should have two user-facing workflows:

1. Quick run: cheap, deterministic, search/ranking evidence.
2. Validation run: stricter, parameter-validated, advisory evidence for human review.

Everything else should serve those workflows, not become a third workflow or a parallel vocabulary.

```text
agent or quant_autoresearch
  |
  | writes
  v
flat strategy.py + experiment.toml
  |
  | quick run
  v
quant_strategies.runner.run_config
  |
  v
strategy import -> validate/flag params -> load quant_data rows
  -> normalize/freeze rows -> generate StrategyDecision
  -> decision contract -> observation audit -> strict replay
  -> engine screen/gate -> search artifacts
  |
  | retained candidate only
  v
strategy.py + validation.toml
  |
  | validation run
  v
quant_strategies.validation.run_validation or CLI
  -> same execution kernel by window
  -> validation row contract
  -> scenarios
  -> advisory verdict + audit artifacts
  |
  v
human promotion process outside this repo
```

Core invariants:

- Strategy files are pure, flat, and single-purpose.
- Strategy files do not load data, call engines, write artifacts, start loops, or own stateful execution.
- Params are either schema-validated or explicitly marked exploratory.
- Validation refuses candidates without `validate_params`.
- Data loading belongs to `quant_data`; this repo validates row shape and reports feedback.
- The engine owns the executable PnL/smoke primitive.
- Metric names must match the math actually computed.
- Search artifacts are not validation evidence.
- Validation artifacts are advisory, not promotion authority.
- Generated artifacts are lower authority than source, tests, configs, and rerunnable evidence.

## Project Ontology

| Concept / boundary | Responsibility | Key contracts or invariants | Current-code fit |
|---|---|---|---|
| Strategy file | Pure decision generator plus rationale | `generate_decisions(rows, params)`, optional/required `validate_params` depending on workflow | Mostly good, but committed examples are not validation-ready |
| Parameter contract | Make config typos and stale params explicit | Quick run may pass through and flag; validation must fail closed | Good in kernel, weak in examples |
| Row contract | Normalize and validate external data shape | `search` versus `validation` strictness, `available_at`, issue reasons | Good and right-sized |
| `StrategyDecision` | Single executable decision ontology | Narrow default, extended ontology opt-in, stable decision IDs | Good |
| Execution kernel | Shared import/param/data/freeze/decision path | Runner and validation adapt into `StrategyExecutionSpec` | Good and should be preserved |
| Quick run | Cheap search evidence | `screen` or `gate`, `search_only` by default, no promotion semantics | Mostly good |
| Validation run | Advisory retained-candidate evidence | Requires `validate_params`, windows/scenarios, audit artifacts, no promotion bits | Structurally good, metric semantics need fix |
| Artifact layer | Persist reproducible evidence | Tiered artifacts, immutable run dirs, manifest hashes | Useful but has format drift and mid-pipeline failure gaps |
| Promotion | Human process outside code | No autonomous paper/live flags | Good |

## What Already Exists And Should Be Reused

| Existing code/flow | What it does | Reuse / concern |
|---|---|---|
| `src/quant_strategies/core/config.py:68` | Defines neutral `StrategyExecutionSpec` with no output policy | Preserve |
| `src/quant_strategies/runner/execution.py:74` | Shared strategy import, param validation, data load, freeze, and decision validation | Preserve |
| `src/quant_strategies/validation/config.py:199` | Adapts validation windows directly into the neutral execution spec | Preserve |
| `src/quant_strategies/decisions/models.py:135` | Strict, frozen `StrategyDecision` schema | Preserve |
| `src/quant_strategies/data_contract.py:19` | Explicit `RowContractMode.SEARCH` and `VALIDATION` | Preserve |
| `src/quant_strategies/causality.py:55` | Strict hidden-lookahead replay | Preserve, but monitor cost |
| `src/quant_strategies/evidence_semantics.py:43` | Metric semantics for runner smoke scores | Preserve and align validation policy with it |
| `src/quant_strategies/engine/evaluation.py:50` | One engine screen path used by quick run and validation backend | Preserve, but clarify exit trigger semantics |
| `src/quant_strategies/validation/policy.py` | Central advisory verdict policy | Refactor metric aggregation semantics |

## Architecture And Boundary Review

### Finding A1: validation metric policy violates its own metric ontology

- Severity: Critical
- Action class: Refactor
- Evidence:
  - `src/quant_strategies/validation/policy.py:391` computes `compounded_realistic_net`.
  - `src/quant_strategies/validation/policy.py:492` implements `math.prod(1.0 + value for value in returns) - 1.0`.
  - `src/quant_strategies/validation/backends.py:78` defines `net_return` as an engine linear signed trade-activity sum.
  - `docs/validation.md:145` says `net_return` is a funding-inclusive signed trade-activity sum.
  - `src/quant_strategies/evidence_semantics.py:79` to `src/quant_strategies/evidence_semantics.py:82` labels the net smoke score `linear_trade_activity_sum`.
  - `tests/test_validation_backends_and_policy.py:694` codifies the current compounding behavior.
- What is wrong or risky: The validation policy treats a linear activity statistic like a per-window portfolio return. That can change `hard_no`, `watchlist`, and `mechanical_review_candidate` classifications based on math the metric explicitly does not support.
- First-principles reason it matters: A validation verdict is only as trustworthy as the unit contract behind its gates. If the metric is not a NAV-path return, compounding it is not a harmless naming issue; it is an invalid operation.
- Root cause: Metric contract and validation policy drifted apart.
- Recommendation: Choose one:
  - Near-term, simpler: make the gate additive/linear and rename it from `compounded_realistic_net_positive` to a name like `realistic_net_activity_positive`.
  - Larger: introduce a true NAV-path window return metric and only compound that.
- Tradeoff: Changing this will alter existing validation verdicts and tests. That is acceptable; rerun candidates rather than preserving wrong evidence.
- Verification needed: Add a policy test where realistic `net_return` values include pathological activity sums such as `1.0` and `-0.5`, and assert the gate math follows the declared metric semantics.

### Finding A2: public validation integration contract is contradictory

- Severity: High
- Action class: Refactor
- Evidence:
  - `PRD.md:58` says `quant_autoresearch` needs stable typed APIs for both `runner.run_config` and `validation.run_validation`.
  - `README.md:112` to `README.md:114` documents `run_validation` returning `ValidationRunResult`.
  - `docs/quant-autoresearch-consumer.md:346` to `docs/quant-autoresearch-consumer.md:354` says `quant_autoresearch` should not import `quant_strategies.validation`.
  - `src/quant_strategies/validation/__init__.py:98` exposes `run_validation`.
  - `src/quant_strategies/runner/cli.py:9` imports `run_validation` directly.
- What is wrong or risky: Agents cannot tell whether validation should be called as a Python API, via CLI, or treated as internal. That is exactly the workflow/vocabulary sprawl Season is worried about.
- First-principles reason it matters: The project has only two main workflows. Each needs one public integration surface with one documented authority.
- Root cause: Boundary contract and docs diverged as validation became more capable.
- Recommendation: Split the contract explicitly:
  - Search loop: `quant_autoresearch` uses `quant_strategies.runner.run_config`.
  - Retained-candidate handoff: either bless `quant_strategies.validation.run_validation` as public, or document CLI-only validation and remove API claims from PRD/README.
- Preferred design: bless `run_validation` as a narrow public retained-candidate API. CLI-only validation would push `quant_autoresearch` toward shelling out and parsing exit behavior.
- Verification needed: Add a docs contract test or README consumer test that checks the chosen import guidance is not contradictory.

### Finding A3: validation backend vocabulary remains public after the engine-only decision

- Severity: Medium
- Action class: Retire
- Evidence:
  - `src/quant_strategies/validation/config.py:28` says the engine smoke kernel is the single verdict PnL source and VectorBT Pro is only an agreement oracle.
  - `src/quant_strategies/validation/config.py:235` rejects legacy `backend` config fields.
  - `src/quant_strategies/validation/backends.py:223` to `src/quant_strategies/validation/backends.py:233` still accepts `engine`, `fake`, and `vectorbtpro` through `get_backend`.
  - `src/quant_strategies/validation/__init__.py:98` exposes `backend` injection on `run_validation`.
- What is wrong or risky: The code has an internal testing seam, but externally it still reads like validation has multiple verdict backends. That fights the simplified model.
- First-principles reason it matters: A validation run should have one verdict source. Optional agreement checks should not look like alternative verdict providers.
- Root cause: Test seam and old backend abstraction share public vocabulary.
- Recommendation: Keep backend injection test-private or explicitly mark it internal. Public docs should say one verdict source: engine. VectorBT Pro remains `agreement_oracle`, not a backend choice.
- Verification needed: Confirm no public docs suggest selecting a validation backend.

### Finding A4: public API modules are large orchestrators

- Severity: Medium
- Action class: Refactor
- Evidence:
  - `src/quant_strategies/validation/__init__.py` is 989 lines and owns public export, orchestration, scenario execution, failure handling, and artifact writes.
  - `src/quant_strategies/runner/__init__.py` is 608 lines and owns public export plus runner orchestration helpers.
  - `PRD.md:116` says orchestrator god-functions are forbidden.
- What is wrong or risky: The design is conceptually cleaner than the file layout. A competent agent can trace it, but not quickly. This raises onboarding cost and makes future changes more likely to land in the wrong layer.
- First-principles reason it matters: The public facade and workflow orchestration have different reasons to change.
- Root cause: Public package modules became implementation modules.
- Recommendation: Keep imports stable, but move orchestration into `runner/run.py` and `validation/run.py` or equivalent. Let `__init__.py` re-export `RunResult`, `run_config`, `ValidationRunResult`, and `run_validation`.
- Tradeoff: This is not a P1 bug. Do it after semantic fixes to reduce future churn.

## Engineering, Testability, And Operability Review

### Finding E1: mid-pipeline artifact writes can still escape structured API results

- Severity: Medium-high
- Action class: Refactor
- Evidence:
  - `TODOS.md:3` to `TODOS.md:10` acknowledges residual mid-pipeline artifact I/O failures.
  - `src/quant_strategies/runner/__init__.py:106` writes full-profile strategy input rows outside the final artifact-write guard.
  - `src/quant_strategies/runner/__init__.py:250` raises on strategy input row hash mismatch.
  - `src/quant_strategies/validation/__init__.py:233` writes validation window rows during window execution.
  - `src/quant_strategies/validation/__init__.py:494` and `src/quant_strategies/validation/__init__.py:529` write scenario decision records and trade ledgers mid-run.
- What is wrong or risky: Direct API callers can still receive raw errors for some artifact failures. The CLI catches some `OSError`, but `quant_autoresearch` is supposed to call APIs directly.
- First-principles reason it matters: A research runner should fail in typed stages. Raw filesystem exceptions are hard for an agent to classify and retry safely.
- Root cause: Artifact writes are not owned by one stage boundary.
- Recommendation: Add one outer structured `artifact_write` boundary around mid-pipeline artifact writes. Do not add scattered ad hoc guards at every call site.
- Verification needed: Update tests that currently expect raw exceptions so direct API callers receive `failure_stage="artifact_write"` with partial artifact context when possible.

### Finding E2: output paths are contained, but not constrained to ignored artifact roots

- Severity: Medium
- Action class: Add
- Evidence:
  - `PRD.md:261` says results are written under ignored `results/` directories and do not land in `src/` or version-controlled trees.
  - `.gitignore:6` and `.gitignore:7` ignore `results/` and `validation_results/`.
  - `src/quant_strategies/runner/config.py:60` to `src/quant_strategies/runner/config.py:63` only require `output.results_dir` to resolve inside the repo.
  - `src/quant_strategies/validation/config.py:94` to `src/quant_strategies/validation/config.py:97` only require validation `output.results_dir` to resolve inside the config directory.
- What is wrong or risky: A bad config can write generated artifacts into source or tracked folders while still passing path containment.
- First-principles reason it matters: Artifact authority and source authority must not mix. Generated outputs should be physically hard to confuse with source.
- Root cause: Contract is documented but not enforced.
- Recommendation: Enforce an artifact root allowlist: `results/` for quick run and `results/` or `validation_results/` inside candidate workspaces for validation. Keep the existing containment check as a second line.
- Verification needed: Config tests that reject `output.results_dir = "src/..."` and accept candidate-local ignored result roots.

### Finding E3: audit artifact format diverges from the PRD

- Severity: Medium
- Action class: Simplify
- Evidence:
  - `PRD.md:269` to `PRD.md:274` requires parquet for bulk audit artifacts and reserves JSONL for human-streaming debug.
  - `src/quant_strategies/runner/artifacts.py:55` writes `strategy_input_rows.jsonl`.
  - `src/quant_strategies/validation/__init__.py:856` writes trade ledgers as JSONL.
  - `src/quant_strategies/validation/__init__.py:868` writes validation rows as JSONL.
  - `docs/validation.md:156` to `docs/validation.md:160` documents JSONL as current validation artifacts.
- What is wrong or risky: The source, tests, and docs have accepted JSONL, but the PRD says parquet is the target. Agents will optimize against different rules depending on which file they read.
- First-principles reason it matters: Artifact format is a contract for replay, scale, and audit tooling.
- Root cause: PRD target changed or implementation pragmatically diverged without updating the PRD.
- Recommendation: For this lightweight sandbox, update the PRD to bless canonical JSONL as v1 unless large audit runs prove JSONL is too slow or too large. Do not add parquet just to satisfy a stale target.
- Verification needed: A PRD/docs consistency test or explicit ADR saying when parquet becomes necessary.

### Finding E4: purity lint is honest but still leaves cheap generated-code escapes

- Severity: Medium
- Action class: Add
- Evidence:
  - `src/quant_strategies/decisions/purity.py:1` to `src/quant_strategies/decisions/purity.py:9` correctly says the lint is best-effort, not a sandbox.
  - `src/quant_strategies/decisions/purity.py:19` to `src/quant_strategies/decisions/purity.py:23` bans `quant_data`, `quant_strategies.engine`, and `quant_strategies.runner`, but not `quant_strategies.validation`.
  - `src/quant_strategies/decisions/purity.py:53` to `src/quant_strategies/decisions/purity.py:75` bans many side-effect primitives, but leaves obvious generated-code escapes such as `os.system`, `os.popen`, `threading`, and `multiprocessing`.
- What is wrong or risky: This is not a security issue under the current contract, but it is an agent-reliability issue. Generated code can accidentally create side effects.
- First-principles reason it matters: Strategy purity is the core boundary. Cheap lint coverage should catch likely mistakes before import.
- Root cause: Denylist is incomplete by nature.
- Recommendation: Either move toward a small import allowlist for strategies, or at least ban the obvious remaining side-effect modules and artifact writers such as `to_csv` and `to_parquet`.
- Verification needed: Add regression tests for `os.system`, `threading.Thread`, `multiprocessing`, `to_csv`, and `quant_strategies.validation` imports.

### Finding E5: backend `SystemExit` escapes structured validation handling

- Severity: Low
- Action class: Refactor
- Evidence:
  - `src/quant_strategies/validation/__init__.py:507` catches `Exception` around backend execution, not `SystemExit`.
  - `tests/test_validation_runner.py:1620` to `tests/test_validation_runner.py:1625` expects backend `SystemExit` to propagate.
  - Strategy import, param validation, and generation `SystemExit` are normalized elsewhere, for example `src/quant_strategies/runner/execution.py:82` to `src/quant_strategies/runner/execution.py:99`.
- What is wrong or risky: Direct API callers can get a hard process-style exit from backend execution rather than an advisory `hard_no`/failure artifact.
- Recommendation: Convert backend `SystemExit` into a failed backend result with warning context. Continue allowing `KeyboardInterrupt` to interrupt.
- Verification needed: Replace the propagation test with a structured failure test.

## Domain-Specific Quant Findings

### Finding Q1: validation replayability can be overstated at manifest level

- Severity: Medium-high
- Action class: Refactor
- Evidence:
  - `src/quant_strategies/validation/__init__.py:528` writes a trade ledger only when `backend_result.trades` is truthy.
  - `src/quant_strategies/validation/manifest.py:35` to `src/quant_strategies/validation/manifest.py:38` sets `verdict_replayable` true when any scenario has a ledger.
  - `docs/validation.md:172` to `docs/validation.md:177` says the gated `net_return` is recomputable from per-scenario trade ledgers and that the manifest sets `verdict_replayable`.
- Domain risk: A global replayability flag can imply every required scenario's gated number is ledger-backed when only some scenarios emitted ledgers. Zero-trade scenarios and failed/mixed scenarios are the edge cases.
- Recommendation: Emit an empty ledger for every completed engine scenario, or define replayability as `all_required_completed_scenarios_have_ledgers`. Prefer per-scenario replayability plus a conservative global aggregate.
- Verification needed: Tests for zero-trade completed scenarios and mixed completed/failed scenarios.

### Finding Q2: stop/take/trailing exits are selected-price triggers, not true bar-path thresholds

- Severity: Medium
- Action class: Refactor
- Evidence:
  - `src/quant_strategies/engine/evaluation.py:213` to `src/quant_strategies/engine/evaluation.py:221` evaluates thresholds against the selected fill price at each trigger bar.
  - `src/quant_strategies/engine/evaluation.py:284` to `src/quant_strategies/engine/evaluation.py:294` uses `open`, `close`, or bid/ask, not high/low path checks.
  - `src/quant_strategies/engine/models.py:37` to `src/quant_strategies/engine/models.py:40` has high/low available.
  - `untested/crypto_perp_autoresearch_ensemble.py:29` to `untested/crypto_perp_autoresearch_ensemble.py:30` describes ATR trailing stop behavior.
- Domain risk: Stop-loss, take-profit, and trailing-stop names imply path-sensitive threshold exits. The current engine implements close/open/quote-sampled threshold checks. That can materially change risk proxy interpretation.
- Recommendation: Either rename/document these as selected-price threshold exits, or implement explicit high/low trigger semantics with conservative same-bar ordering rules.
- Verification needed: Engine tests where intrabar high/low crosses a stop/take threshold but close does not.

### Finding Q3: checked-in strategies are quick-run examples, not validation-ready examples

- Severity: High
- Action class: Add
- Evidence:
  - `src/quant_strategies/validation/config.py:199` to `src/quant_strategies/validation/config.py:210` sets `require_param_validator=True`.
  - `src/quant_strategies/decisions/params.py:23` to `src/quant_strategies/decisions/params.py:27` fails validation runs without `validate_params`.
  - `untested/crypto_perp_autoresearch_ensemble.py:62` exports only `generate_decisions`.
  - `untested/crypto_perp_funding_crowding_reversal.py:52` exports only `generate_decisions`.
  - `examples/strategies/simple_momentum.py:35` defines `generate_decisions`, with no `validate_params`.
  - `runs/*.toml` are all quick-run configs, not validation configs.
- Domain risk: The code correctly refuses unvalidated validation runs, but the most visible strategy examples teach agents how to quick-run, not how to prepare retained candidates for validation.
- Recommendation: Add at least one canonical validation-ready example strategy with `validate_params` and a matching `validation.toml`. For any `untested/` strategy intended to be retained, add a real param schema before validation.
- Verification needed: A validation-ready example test that runs through `run_validation` without backend injection if feasible, or with a narrow fake backend if live data is unavailable.

### Finding Q4: search pressure metadata is advisory, not correction

- Severity: Low
- Action class: Preserve
- Evidence:
  - `docs/validation.md:69` to `docs/validation.md:73` says search pressure is metadata, not statistical correction.
  - `src/quant_strategies/validation/policy.py:78` to `src/quant_strategies/validation/policy.py:82` downgrades `mechanical_review_candidate` to `watchlist` when search pressure is present.
- Domain risk: This is the right conservative default. Do not overbuild multiple-testing correction into this repo yet.
- Recommendation: Preserve advisory treatment. If statistical correction is needed later, it should be a separate research validation process, not hidden inside mechanical validation.

## Unknown Unknowns And Assumption Risks

| Assumption | Why it may be wrong | How to test or de-risk |
|---|---|---|
| `quant_data` rows have reliable `available_at` | Causality verification depends on it; missing/invalid availability downgrades evidence | Run real loader integration checks for each data kind and inspect row-contract summaries |
| JSONL artifacts are adequate for current scale | PRD says parquet; results may be too large for full audit replay | Benchmark full-profile runs near 1M rows and compare JSONL size/time |
| Engine linear activity sum is enough for validation routing | It may be too crude for paper-readiness style language | Rename gates to smoke/activity language or add a NAV path metric |
| Agents will read docs over generated artifacts | Existing `results/` contains stale configs with retired vocabulary | Quarantine stale generated artifacts and keep source/docs authoritative |
| Validation scenario matrix is enough | Current fixed scenarios may miss regime, cost, and fill risks | Keep validation advisory and require separate human research review |
| VectorBT Pro agreement oracle is available | It is optional and may not import in the environment | Treat oracle as optional diagnostic only; do not gate core correctness on it |

## Overbuilt, Underbuilt, And Right-Sized Areas

Overbuilt or vocabulary-heavy:

- Validation backend vocabulary after the engine-only verdict-source decision.
- `screen`, `gate`, `row_contract`, `artifact_profile`, `artifact_trust_tier`, `evidence_class`, and validation verdict labels are each meaningful, but together they are too much unless docs keep mapping them back to the two workflows.
- `__init__.py` modules as large orchestration files.
- PRD parquet requirement may be premature for the current lightweight sandbox.

Underbuilt:

- Validation metric semantics: policy math does not match the declared metric unit.
- Public validation consumer contract.
- Validation-ready strategy examples and templates.
- Structured handling for mid-pipeline artifact write failures.
- Enforcement that generated artifacts stay in ignored result roots.
- Purity lint coverage for obvious generated-code side effects.

Right-sized:

- Flat strategy files.
- Pure `generate_decisions(rows, params)` contract.
- Optional quick-run `validate_params`, required validation `validate_params`.
- Shared `StrategyExecutionSpec`.
- Explicit row-contract strictness separated from artifact verbosity.
- Advisory-only validation verdicts and always-false promotion/paper/live flags.
- `quant_data` ownership of data loading and this repo's row-contract feedback.

## Missing Docs, PRD, ADR, Or Decision Records

- PRD conflict: `PRD.md:269` requires parquet, while source/tests/docs use JSONL. Decide and update PRD or implementation.
- Consumer contract conflict: PRD/README claim `run_validation` API, while consumer docs forbid importing `quant_strategies.validation`.
- Missing ADR: why the engine linear activity sum is the validation verdict source, and what gates are allowed to do with it.
- Missing ADR: JSONL versus parquet for audit artifacts.
- Missing example: a validation-ready candidate workspace with `strategy.py`, `experiment.toml`, `validation.toml`, and `validate_params`.
- Missing artifact-authority note: ignored `results/` and frozen `researched/` are not source of design truth and should not be copied blindly.

## Legacy And Artifact Bias Review

The repo currently has large artifact surfaces:

- `researched/`: 277 files on disk, 261 tracked files, about 27 MB.
- `results/`: 220 files on disk, about 3.3 GB, ignored by git.
- `results/notebook_configs/crypto_perp_autoresearch_ensemble_validate.toml:58` still has `mode = "validate"`, while the current quick-run config accepts only `screen | gate` (`src/quant_strategies/runner/config.py:20`) and docs reserve "validate" for `quant-strategies validate`.

This does not mean the source foundation is bad. It means generated artifacts are a real bias vector. Agents and humans will copy what is nearby. Generated outputs should be treated as disposable unless they are explicitly frozen for audit and tied to current contracts.

Recommendation: Retire or quarantine stale generated configs and old result trees. Keep `researched/` only as frozen, low-authority packages, not as examples of current workflow. Prefer rerunning from source over preserving compatibility with old artifacts.

## Preserve / Refactor / Simplify / Add / Retire Action Map

| Action class | Findings / recommendations | Rationale |
|---|---|---|
| Preserve | Flat strategy files, shared `StrategyExecutionSpec`, row-contract strictness, strict replay, advisory-only verdict flags | These directly serve the two-workflow model |
| Refactor | Validation metric gate, public validation API contract, mid-pipeline artifact handling, replayability manifest, exit threshold semantics, orchestration module layout | Keep capabilities but fix ownership, semantics, and boundaries |
| Simplify | Artifact format target: bless JSONL v1 unless scale proves parquet is needed | Avoid adding parquet complexity only to satisfy stale PRD wording |
| Add | Validation-ready example, `validate_params` schemas for retained candidates, ignored-root enforcement, purity lint regressions, docs/ADR for metric semantics | Missing contracts make the workflow easy to misuse |
| Retire | Backend-as-verdict vocabulary, stale generated configs, old artifact authority, any compatibility with retired output shapes | Preserving them keeps the wrong mental model alive |

## Prioritized Recommendations

| Priority | Action class | Recommendation | Why now | Verify |
|---|---|---|---|---|
| P1 | Refactor | Fix validation's `compounded_realistic_net_positive` gate so policy math matches `net_return` semantics | Current validation verdicts can be mathematically misleading | Policy tests around linear activity sums and renamed gate |
| P1 | Refactor | Resolve public validation API contract for retained candidates | Agents need one obvious quick-run and validation-run surface | Docs contract test across PRD/README/consumer docs |
| P1 | Add | Add a validation-ready canonical example with `validate_params` and `validation.toml` | The current examples teach quick run but not validation handoff | Example validation test |
| P2 | Refactor | Wrap mid-pipeline artifact writes in structured `artifact_write` results | API consumers need typed failures | Tests for runner/validation write failures |
| P2 | Add | Enforce ignored artifact result roots | Prevent generated artifacts from entering source/tracked areas | Config rejection tests |
| P2 | Refactor | Make validation replayability per-scenario or all-required-scenarios, and emit empty ledgers for completed zero-trade scenarios | Avoid overstating audit replayability | Manifest tests for zero-trade and mixed scenarios |
| P2 | Simplify | Decide JSONL versus parquet, preferably update PRD to JSONL v1 unless scale requires parquet | Removes doc/source contradiction without premature complexity | PRD/docs consistency check |
| P2 | Retire | Quarantine stale `results/` configs and old `researched/` evidence from agent examples | Reduces artifact-driven bias | No stale `mode = "validate"` examples in visible/generated templates |
| P3 | Refactor | Move orchestration out of package `__init__.py` files while keeping imports stable | Improves maintainability after semantic fixes | Import compatibility tests |
| P3 | Add | Tighten purity lint or move toward import allowlist | Improves agent reliability | Static lint regression tests |
| P3 | Refactor | Clarify or implement true high/low stop/take/trailing semantics | Avoids overstating risk exits | Engine path-threshold tests |

## NOT In Scope

- Live trading, order routing, paper trading, real-time data, risk limits, broker integration.
- Market validation or statistical proof of alpha.
- Owning `quant_autoresearch`'s search loop.
- Data acquisition, repair, refresh, or source joining owned by `quant_data`.
- Notebook or UI ergonomics.
- Preserving compatibility with old generated artifact shapes.
- Reading or comparing against `review-claude.md`.

## Verification Summary

Verified:

- Full test suite: `conda run -n quant pytest -q` passed with `644 passed in 22.60s`.
- CodeGraph index was healthy: 97 indexed files, 2177 nodes, 2311 edges.
- Key source paths, configs, docs, tests, and sampled generated artifacts were inspected.
- Independent read-only lenses converged on the major issues: metric compounding, API contract drift, artifact format drift, mid-pipeline write handling, and validation-ready examples.

Not verified:

- Real `quant_data` loader/database behavior.
- Real `quant_autoresearch` integration.
- VectorBT Pro runtime behavior.
- Large-row full-profile performance.
- Every package under `researched/`.

Residual risk:

- A passing test suite currently proves the present behavior, including some behavior this review considers wrong for the foundation. In particular, tests lock in compounding over `net_return`. Fixing the foundation will require changing tests, not just code.
