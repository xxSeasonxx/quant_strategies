# Project Foundation Review: `quant_strategies`

Date: 2026-06-03
Reviewer: Codex, senior quant researcher lens
Target: `/Users/Season_Yang/Personal/quant_strategies`

## Review Objective

I reviewed `quant_strategies` to determine whether it is a sound foundation for diagnostic quick runs, mechanical evidence validation, and stateless research evaluation for supplied frozen candidates.

Objective lock used for this review:

> `quant_strategies` should serve `quant_autoresearch`, Season, and future strategy authors by enabling diagnostic quick runs, mechanical evidence validation, and stateless research evaluation for frozen candidates in a non-production research lifecycle. A solid foundation should make math-correct, causal, deterministic, auditable advisory evidence easy and prevent lookahead, misleading metrics, legacy-shim bias, artifact mutation, data-platform creep, auto-promotion, and layered over-engineering, while data comes from `quant_data`, strategies are pure, artifacts are tiered, and this is not a general backtester or trading system.

Additional user concerns applied: be honest, do not let existing outputs bias the review, challenge the design if needed, check for critical math errors, assess whether the workflow is simple enough, and do not inflate low-priority issues.

Subagent limitation: the `project-foundation-review` skill prefers fresh-context lens subagents, but this session's multi-agent tool contract only allows subagents when the user explicitly asks for subagents, delegation, or parallel agent work. I therefore ran the onboarding, architecture, senior engineering, adversarial, and quant math lenses locally and disclose that limitation here.

## Executive Verdict

The source foundation is good enough to begin running quick runs, validation runs, and research evaluation as advisory research infrastructure, but the local `quant` environment needs its editable install refreshed before using the literal `quant-strategies` console command. I found no critical math blocker in the inspected trade PnL, funding, cost, causality, or NAV/evaluation metric paths, and the full test suite plus the explicit real VectorBT Pro evaluation smoke passed. The main caveats are auditability and verification coverage, not current math: evaluation artifacts are not yet self-contained for artifact-only replay, the validation agreement oracle is opt-in and single-trade-only, and annualized evaluation metrics trust the caller-supplied cadence. Fix those before letting an autonomous loop rank many candidates on these numbers. The public source workflow is simple enough; the internal layering is heavier than ideal in result/status vocabulary and a few orchestrators, but the core boundaries mostly earn their existence.

Severity summary:

| Severity | Count | Summary |
|---|---:|---|
| Critical | 0 | No critical math, lookahead, or promotion-boundary blocker found. |
| Important | 2 | Local installed CLI entry point is stale; evaluation artifact replayability is weaker than the PRD-level audit objective. |
| Medium | 5 | Legacy/test validation backends remain visible; real backend smoke should become an explicit pre-run or CI check; independent agreement coverage is thin on multi-trade/perp paths; annualization cadence is unchecked; result/status vocabulary has accreted. |
| Low | 3 | Large orchestrator modules, PRD backend-contract wording, and failure-artifact write observability are real debt but not reasons to delay running. |

## Scope And Evidence Inspected

Primary source and docs inspected:

| Area | Evidence |
|---|---|
| Product objective | `PRD.md`, `FOUNDATION_LOCK.md`, `README.md`, `docs/foundation-surfaces.md`, `docs/vectorbtpro.md` |
| Public surface | `src/quant_strategies/cli.py`, `src/quant_strategies/runner/__init__.py`, `src/quant_strategies/validation/__init__.py`, `src/quant_strategies/evaluation/runner.py` |
| Strategy contract | `src/quant_strategies/decisions/models.py`, `strategy_loader.py`, `purity.py`, `output_validation.py`, `params.py` |
| Shared execution and data | `src/quant_strategies/core/execution.py`, `core/data_loader.py`, `data_contract.py`, `causality.py` |
| Math and backends | `src/quant_strategies/engine/evaluation.py`, `funding.py`, `engine/models.py`, `evaluation/backend.py`, `evaluation/metrics.py`, `validation/engine_backend.py`, `validation/policy.py` |
| Artifacts | `runner/artifacts.py`, `validation/artifacts.py`, `validation/manifest.py`, `evaluation/artifacts.py` |
| Tests | Full `tests/` suite, with focused attention on engine, funding, causality, validation, evaluation backend, evaluation runner, artifact integrity, docs, and repository boundary tests |

Commands run:

```bash
conda run -n quant pytest tests/test_engine_screen.py tests/test_funding.py tests/test_validation_lookahead.py tests/test_validation_runner.py tests/test_evaluation_backend.py tests/test_evaluation_runner.py tests/test_evaluation_artifacts.py
conda run -n quant pytest
conda run -n quant env RUN_VECTORBTPRO_SMOKE=1 pytest tests/test_evaluation_backend.py::test_vectorbtpro_evaluation_backend_real_smoke_if_installed
conda run -n quant python -c "from quant_strategies.cli import main; main(['--help'])"
conda run -n quant pytest tests/test_validation_cli.py tests/test_evaluation_cli.py tests/test_evaluation_docs.py tests/test_validation_config.py tests/test_evaluation_config.py
```

Follow-up operational check:

```bash
conda run -n quant quant-strategies --help
```

That command currently fails because the installed console script in `/opt/anaconda3/envs/quant/bin/quant-strategies` imports `quant_strategies.runner.cli`, while current `pyproject.toml` correctly points `quant-strategies` at `quant_strategies.cli:main`.

Not inspected or not proven:

| Gap | Residual risk |
|---|---|
| Real `quant_data` datasets and loader outputs | Row contract can validate shape and `available_at`, but not economic truth, vendor correctness, survivorship, or corporate-action quality. |
| `quant_autoresearch` integration repo | This review checked the public API this repo exposes, not downstream consumer behavior. |
| Large real runs at the PRD scale of up to 1M rows | Tests cover correctness and some performance discipline, not end-to-end production-scale timing. |
| Market validity or alpha | Explicitly out of scope. These outputs are advisory evidence, not proof of edge. |

## Cross-Compare With `review-claude.md`

I cross-checked `review-claude.md` against the current source before importing findings. I did not copy claims that were already covered, false in the current repo, or too speculative for the action map.

| Claude-only point | Disposition | Reason |
|---|---|---|
| Installed CLI is stale | Accepted, already added before this comparison | Source `pyproject.toml` is correct, but installed `quant-strategies` imports deleted `quant_strategies.runner.cli`. |
| No validation/evaluation TOML | Rejected as stated | `examples/strategies/simple_momentum_spy_daily_validation.toml` and `examples/strategies/simple_momentum_spy_daily_evaluation.toml` exist and config tests pass. It is only true that `runs/` currently contains quick-run TOMLs. |
| Evaluation artifacts are not artifact-alone replayable | Accepted, already captured | Evaluation manifest explicitly says raw rows are not embedded, and evaluation does not write decision records. |
| Dominant validation path is self-certified when agreement oracle is disabled/skipped | Accepted, added as a medium verification-coverage finding | The oracle is opt-in and skips multi-trade scenarios by design; this is not a current math bug, but it is worth exposing before autonomous ranking scales. |
| `project_perp_ledger_v1` has no numeric pin tests | Rejected as overstated | `tests/test_funding.py` numerically pins funding signs, funding window, full-weight funding return, duplicate funding handling, and fee/slippage realized PnL. A combined funding-plus-price-drift case could still be added, but "no numeric pin" is false. |
| Annualization cadence can be misconfigured | Accepted, added as a medium quant evidence finding | `annualization_periods_per_year` is required and positive, but no code checks it against observed bar cadence; metrics use full-grid portfolio returns. |
| `evaluation/backend.py` hides several responsibilities | Accepted as low/P3 refactor only | True by file shape, but not a blocker; split only when touching evaluation backend code. |
| Multiple status/verdict vocabularies and `RunResult` internals leak into public surface | Accepted as P3 simplify/refactor | True from source shape; do not trim fields until `quant_autoresearch` usage is checked. |
| `_write_failure_artifacts` swallows write errors | Accepted as low operability finding | True at `src/quant_strategies/evaluation/runner.py:698` to `:712`; not a math/trust blocker. |
| PRD says any PnL backend implements one execution-model contract | Accepted as doc/decision ambiguity | Code intentionally has validation backend and evaluation portfolio backend families; amend wording rather than force an abstraction. |
| Engine same-bar fill risk | Not added as material | Public `core.config.FillModelConfig` enforces `entry_lag_bars >= 1`; direct `engine.models.FillModel` allows `0`, but engine is an internal boundary. |
| Evaluation manifest timestamp prevents byte reproducibility | Not added as material | True but low-value: manifest self-excludes from artifact hashes and this does not affect evidence identity. |
| `conda run` may fail in non-interactive shells | Rejected for this environment | `conda run -n quant ...` worked throughout this review; installed console-script drift is the real local CLI issue. |

## Intended Foundation Model

The minimal correct foundation is not a general backtester. It is a causal evidence pipeline:

1. A strategy is a pure, flat Python module that receives already-loaded rows and params.
2. The strategy emits typed `StrategyDecision` objects in one ontology.
3. Rows are normalized, hashed, availability-audited, and frozen before decision generation.
4. A shared causality kernel checks deterministic replay, emitted-decision replay, and strict suppression replay.
5. Quick runs produce fast diagnostic evidence for one version.
6. Validation produces advisory mechanical evidence for retained candidates.
7. Evaluation produces stateless portfolio/path/economic evidence for frozen candidates.
8. No output authorizes promotion, paper trading, or live trading.
9. Artifacts state exactly what can and cannot be replayed from artifacts alone.

```text
Season / quant_autoresearch
        |
        | explicit TOML config + pure strategy file
        v
CLI/API: run | validate | evaluate
        |
        v
core.execute_strategy_run
  - import strategy inside repo
  - validate params
  - load rows through quant_data
  - normalize/hash/freeze rows and params
  - validate typed decisions
        |
        +--> quick run: engine trade-activity diagnostics + tiered artifacts
        |
        +--> validation: strict causality + data audit + engine scenarios + advisory verdict
        |
        +--> evaluation: strict causality + portfolio/NAV backend + Parquet traces

External boundaries:
  quant_data owns data acquisition/materialization.
  quant_autoresearch owns candidate generation and iteration.
  humans own promotion decisions.
```

## Project Ontology: Concepts, Contracts, Boundaries, Invariants

| Concept / boundary | Responsibility | Key contracts or invariants | Current-code fit |
|---|---|---|---|
| Strategy module | Express one hypothesis/rule as pure code | Flat file, no data loading, no side effects, `generate_decisions(rows, params)` | Good. Loader enforces repo-local file and AST purity lint; purity is correctly documented as best effort, not a sandbox. |
| `StrategyDecision` | Single strategy-output ontology | Strict frozen Pydantic model, aware timestamps, `as_of_time <= decision_time`, generated stable ID, target-weight sizing | Good. This is one of the strongest foundation pieces. |
| Row contract | Convert external data rows into a trusted research input shape | Required OHLC, quotes/funding where relevant, duplicate detection, `available_at` strict in validation/evaluation, normalized row hash | Good. Important limitation remains upstream data truth. |
| Shared execution kernel | Keep import, params, data load, normalization, freezing, and decision validation in one path | Quick run, validation, and evaluation must not fork strategy execution semantics | Good. This is the right abstraction. |
| Causality kernel | Prevent hidden lookahead and future-based suppression | Deterministic replay, emitted subset replay, strict no-emission suppression replay | Good. The suppression replay model is unusually important and should be preserved. |
| Engine PnL | Linear per-trade trade-activity math for quick/validation | Signed target-weighted price return, additive funding, round-trip bps cost, not NAV | Good. Naming mostly avoids overstating this as portfolio return. |
| Validation | Mechanical retained-candidate evidence | Advisory vocabulary, scenario matrix, data/causality gates, no promotion authority | Good. Some legacy backend visibility should be retired. |
| Evaluation | Frozen-candidate portfolio/path/economic evidence | Strict preflight, scenario coverage, NAV/path metrics, detailed traces | Mostly good. Artifact-only replayability is underbuilt. |
| Artifacts | Make evidence inspectable and bounded | Tiered profile semantics, hashes, manifests, strategy/config snapshots | Good for quick-run full and validation; weaker for evaluation. |

Core invalid states are mostly hard to represent: bad decision timestamps, unsupported target shapes, missing required validation rows, failed causality, failed backend execution, and promotion authority are all explicit states rather than silent defaults.

## What Already Exists And Should Be Reused

| Existing code/flow | What it does | Reuse / concern |
|---|---|---|
| `src/quant_strategies/decisions/models.py:14` to `:199` | Defines the narrow default decision ontology and stable decision IDs | Preserve. This is the right center of the system. |
| `src/quant_strategies/decisions/strategy_loader.py:33` to `:85` | Loads repo-local strategy files and attaches optional `validate_params` | Preserve. Simple, direct, and hard to misuse. |
| `src/quant_strategies/decisions/purity.py:1` to `:9` | States the AST purity lint is not a sandbox | Preserve the honesty. Do not turn this into a false security claim. |
| `src/quant_strategies/core/execution.py:74` to `:187` | Shared import, params, data load, row normalization, freezing, and decision validation | Preserve. This prevents workflow drift. |
| `src/quant_strategies/data_contract.py:188` to `:260` | Normalizes rows, checks required fields, and escalates missing `available_at` in validation mode | Preserve. This is the right boundary with `quant_data`. |
| `src/quant_strategies/causality.py:72` to `:97` and `:310` to `:369` | Checks deterministic replay, emitted decisions, and strict suppression replay | Preserve. This is a foundation-level trust mechanism. |
| `src/quant_strategies/engine/evaluation.py:70` to `:81` | Computes signed gross return, funding, cost, and net return | Preserve. Formula matches stated linear trade-activity semantics. |
| `src/quant_strategies/funding.py:24` to `:44` | Centralizes funding window, dedup, conflict, and sign rules | Preserve. Shared funding semantics reduce sign drift. |
| `src/quant_strategies/validation/policy.py:12` to `:54` | Keeps validation labels advisory and non-promotional | Preserve. This prevents downstream overclaiming. |
| `src/quant_strategies/evaluation/metrics.py:20` to `:191` | Declares NAV/path metric units, bases, null behavior, and non-authority | Preserve. This avoids misleading metric labels. |

## Architecture And Boundary Review

### Finding 1: Installed console script in the `quant` env is stale

- Severity: Important
- Action class: Add
- Evidence: current source `pyproject.toml:27` points `quant-strategies = "quant_strategies.cli:main"`, and `src/quant_strategies/cli.py:28` to `:41` defines `run`, `validate`, and `evaluate`. But `/opt/anaconda3/envs/quant/bin/quant-strategies` currently imports `quant_strategies.runner.cli`, which no longer exists. `conda run -n quant quant-strategies --help` fails with `ModuleNotFoundError: No module named 'quant_strategies.runner.cli'`. The source CLI itself works via `conda run -n quant python -c "from quant_strategies.cli import main; main(['--help'])"`.
- Why it matters: The source workflow is correct, but the actual command documented for users will fail in the current local environment until the editable install is refreshed. That is an operational blocker for starting runs via CLI, not a math or source architecture blocker.
- Root cause: Installed editable metadata/script drift. The installed package metadata still lists the old entry point and `quant-engine` dependency while source `pyproject.toml` has moved on.
- Recommendation: Refresh the editable install with `conda run -n quant python -m pip install -e .`, then add a lightweight smoke check such as `conda run -n quant quant-strategies --help` to the pre-run checklist or tests that exercise the installed console script.
- Tradeoff: This changes environment state, not repo source. The code-side fix is already present in `pyproject.toml`; the remaining issue is installation hygiene.
- Verify: `conda run -n quant quant-strategies --help` should print `{run,validate,evaluate}`.

### Finding 2: Evaluation artifacts are not self-contained enough for artifact-only replay

- Severity: Important
- Action class: Add
- Evidence: `src/quant_strategies/evaluation/runner.py:459` to `:503` writes the evaluation data manifest, trace tables, metrics, scenario summary, notes, and evaluation manifest. It does not write decision records or embedded input rows. `src/quant_strategies/evaluation/artifacts.py:296` to `:300` explicitly states `input_rows_embedded: False` and says raw rows are not embedded. In contrast, quick-run full artifacts write strategy input rows and decision records at `src/quant_strategies/runner/__init__.py:109` to `:143`, and validation writes `decision_records.jsonl` at `src/quant_strategies/validation/__init__.py:935`.
- Why it matters: A reviewer can verify an evaluation artifact hash chain and inspect Parquet traces, but cannot reconstruct the exact decisions and input row set from artifacts alone without rerunning `quant_data` and strategy code. That is weaker than the PRD-level goal that full evidence can be traced to strategy snapshot, input row set, decisions, fills/exits, funding/cost, and config.
- Root cause: Artifact contract gap. Evaluation has strong trace tables but lacks the same row/decision audit chain as quick-run full and validation.
- Recommendation: Add `decision_records` and a normalized input row artifact for evaluation. Use Parquet for row snapshots if size matters, and include hashes, schema version, row count, and window ID in `evaluation_manifest.json`. If the intended contract is "replayable only with upstream `quant_data` still available," make that explicit in PRD and docs and do not call evaluation artifact output artifact-alone replayable.
- Tradeoff: More storage and artifact write time. That is acceptable for frozen-candidate evaluation; it should not affect quick-run summary or diagnostic profiles.
- Verify: Add tests that `run_evaluation` writes decision records and normalized row snapshots, that the manifest hashes them, and that a metric can be traced from metric -> scenario -> trace table -> decision -> input rows.

### Finding 3: Validation still exposes legacy/test backend names behind a config that says engine-only

- Severity: Medium
- Action class: Retire
- Evidence: `src/quant_strategies/validation/config.py:29` to `:32` declares `VerdictSource = Literal["engine"]` and says VectorBT Pro is no longer a co-equal verdict backend. But `src/quant_strategies/validation/backends.py:220` to `:230` still exposes `engine`, `fake`, and `vectorbtpro` through `get_backend`.
- Why it matters: This does not appear to affect normal config-driven validation, but it preserves a misleading mental model: future work can accidentally treat fake or VectorBT Pro validation as a first-class verdict path.
- Root cause: Legacy compatibility/test convenience remained in a production-looking registry.
- Recommendation: Move `FakeBackend` into tests or a test-only helper. Rename or remove validation `VectorBTProBackend` from the public registry and keep cross-check behavior only through the explicit agreement oracle path.
- Tradeoff: Some tests need small fixture rewrites. The payoff is less legacy gravity and less ambiguity for future agents.
- Verify: `pytest tests/test_validation_backends_and_policy.py tests/test_agreement_oracle.py tests/test_validation_config.py`.

### Finding 4: Real VectorBT Pro evaluation smoke is present but skipped by default

- Severity: Medium
- Action class: Add
- Evidence: `tests/test_evaluation_backend.py:837` to `:854` defines a real VectorBT Pro smoke test, but it skips unless `RUN_VECTORBTPRO_SMOKE=1`. The default full suite therefore passed with the real smoke skipped; the explicit smoke passed when run with the env var during this review.
- Why it matters: If evaluation is a public foundation job and non-funding evaluation uses VectorBT Pro, the team needs a repeatable pre-run or optional CI command that proves the installed dependency path still works.
- Root cause: The smoke exists as a developer escape hatch, not as an operational pre-run contract.
- Recommendation: Document and optionally automate a `pre-run` or CI-optional command that includes `RUN_VECTORBTPRO_SMOKE=1`. Do not make every local test require VectorBT Pro if that dependency is intentionally optional.
- Tradeoff: Optional CI needs an environment with licensed/installed VectorBT Pro. The local command is cheap and already passed here.
- Verify: `conda run -n quant env RUN_VECTORBTPRO_SMOKE=1 pytest tests/test_evaluation_backend.py::test_vectorbtpro_evaluation_backend_real_smoke_if_installed`.

### Finding 5: Independent agreement coverage is thin beyond single-trade validation cases

- Severity: Medium
- Action class: Add
- Evidence: `src/quant_strategies/validation/config.py:40` to `:47` makes the agreement oracle opt-in and disabled by default. `src/quant_strategies/validation/agreement.py:82` to `:100` states and enforces that the oracle runs only on single-trade scenarios because the engine's linear trade sum and a VectorBT Pro NAV path diverge by construction for multi-trade cases. `tests/test_agreement_oracle.py:107` to `:113` pins the multi-trade skip behavior.
- Why it matters: This is not a present math error. It is a regression-tripwire gap: common multi-trade validation evidence can be mechanically complete while being corroborated only by the engine's own tests and formulas, not an independent agreement check. That is acceptable for first runs but should be visible before an autonomous loop ranks many candidates on validation metrics.
- Root cause: The existing agreement oracle compares an aggregate quantity that is only comparable in one-trade cases.
- Recommendation: Add explicit agreement/cross-check status to validation scenario summaries and manifests, including `not_run`, `skipped`, `pass`, `fail`, and `unavailable`, so consumers cannot mistake uncorroborated evidence for corroborated evidence. Then consider a per-trade gross price-path comparison that can cover multi-trade cases without pretending a linear trade sum equals NAV.
- Tradeoff: More metadata and a modest oracle refactor. Do not collapse engine linear activity and NAV semantics to force comparability.
- Verify: Agreement oracle tests plus validation manifest/backend summary tests.

### Finding 6: Facade modules are large, but this is accepted debt and not a blocker

- Severity: Low
- Action class: Refactor
- Evidence: `FOUNDATION_LOCK.md:45` to `:52` explicitly accepts large facade modules as non-blocking debt. The important public paths are still narrow and tested.
- Why it matters: Rewriting large orchestrators now would likely add risk before the first real running cycle. The boundary risk is manageable because shared execution, row contract, causality, and artifacts are separated.
- Root cause: Orchestration accumulated around workflow lifecycles.
- Recommendation: Do not pause running to refactor facades. Refactor only when touching a specific behavior: extract artifact writing, event stages, or scenario loops behind existing contracts. If evaluation backend work starts, split `src/quant_strategies/evaluation/backend.py` into the VectorBT Pro adapter, the project perp ledger, and shared portfolio metric/table helpers so the most math-sensitive code is easier to review.
- Tradeoff: Some files remain long. That is less risky than a broad rewrite before real run feedback.
- Verify: Keep boundary tests green, especially `tests/test_repository_boundaries.py` and `tests/test_internal_engine_boundary.py`.

### Finding 7: Evaluation failure-artifact write errors are swallowed

- Severity: Low
- Action class: Refactor
- Evidence: `_write_failure_artifacts` catches all exceptions and does `pass` at `src/quant_strategies/evaluation/runner.py:698` to `:712`.
- Why it matters: The primary failure result still returns to the caller, so this is not a run-correctness issue. But if failure diagnostics cannot be written, the secondary artifact-write failure disappears, which makes operational debugging harder.
- Root cause: Best-effort diagnostics are implemented without emitting the secondary failure.
- Recommendation: Keep failure artifacts best-effort, but emit a structured event or warning when the write fails.
- Tradeoff: Slightly noisier failure payloads; better debuggability.
- Verify: Add a test that forces failure-artifact write failure and asserts the result or event stream reports the secondary write error.

## Engineering, Testability, And Operability Review

The engineering foundation is stronger than the concern "layered over layered" suggests. There are layers, but most correspond to real contracts:

| Boundary | Why it earns its place |
|---|---|
| Pydantic config and decision models | External/system boundaries need validation, freezing, and explicit invalid states. |
| `core.execute_strategy_run` | Prevents quick run, validation, and evaluation from forking strategy execution semantics. |
| `data_contract.NormalizedRows` | Owns row normalization, hashing, availability, and row-contract feedback to `quant_data`. |
| `causality.check_hidden_lookahead` | Shared hidden-lookahead and suppression invariant. |
| Engine vs evaluation backend | Linear trade-activity math and NAV/path portfolio evidence are different models and should not be collapsed. |

The workflow is simple enough at the user surface:

```text
quant-strategies run <run.toml>
quant-strategies validate <validation.toml>
quant-strategies evaluate <evaluation.toml>
```

The CLI maps directly to three public jobs in `src/quant_strategies/cli.py:28` to `:41`, and the exit-code mapping separates data failures from mechanical failures at `src/quant_strategies/cli.py:121` to `:148`.

Repository boundary tests are valuable and should stay. `tests/test_repository_boundaries.py:79` to `:147` checks that the research archive is absent, generated result roots are ignored, the CLI entry point is neutral, and validation/evaluation do not import runner internals. `tests/test_internal_engine_boundary.py:11` to `:24` checks the project does not depend on the legacy `quant-engine` package. These tests directly address the legacy/artifact concern.

The strongest "layered on layered" evidence is vocabulary and result shape, not dependency direction. Engine internals still have `screen`/`gate`, runner completion uses `quick_check_*` and `assessment_status`, validation uses `mechanical_*`, and evaluation has backend `status` plus run `assessment_status`. `RunResult` also mixes the user answer with internal evidence fields such as replay flags and a raw `row_contract` dict at `src/quant_strategies/runner/__init__.py:32` to `:51`. Do not delete these blindly; first verify `quant_autoresearch` usage, then nest/type the evidence fields and document a single status map.

Operational gap: there is no single documented "ready to run foundation" command that refreshes/verifies the installed console script and includes the real VectorBT Pro smoke. The tests exist and passed, but the installed command currently fails until the editable install is refreshed.

The previous "no validation/evaluation TOML" claim is not true for the current repo if it meant "no examples exist": `examples/strategies/simple_momentum_spy_daily_validation.toml` and `examples/strategies/simple_momentum_spy_daily_evaluation.toml` are present and config tests pass. It is only true in the narrower sense that `runs/` currently contains quick-run TOMLs, not validation/evaluation candidate TOMLs.

## Domain-Specific Lens Findings: Quant Math And Research Evidence

### Math verdict

No critical math error found in the inspected foundation paths.

| Area | Assessment |
|---|---|
| Trade gross return | Correct for stated linear trade-activity semantics: `direction * (exit - entry) / entry * weight` at `src/quant_strategies/engine/evaluation.py:70` to `:71`. |
| Costs | Round-trip bps cost is converted by `/ 10_000` and multiplied by target weight at `src/quant_strategies/engine/evaluation.py:80`; tests cover cost behavior. |
| Funding | Shared funding function uses `entry < ts <= exit`, duplicate timestamp tolerance, and `sum(-direction * rate) * weight` at `src/quant_strategies/funding.py:24` to `:44`; tests cover long/short signs, windows, duplicates, and conflicts. |
| Quote fills | Existing engine tests cover quote fill sign behavior. No sign issue found. |
| Exit thresholds | Declared as bar-sampled thresholds, not intrabar OHLC barrier orders, at `src/quant_strategies/decisions/models.py:121` to `:127`. This is acceptable because it is explicit. |
| Causality | Strict replay includes emitted-decision subset and strict suppression replay at row-grid boundaries, described at `src/quant_strategies/causality.py:82` to `:97` and implemented at `:310` to `:369`. |
| Evaluation NAV metrics | Units, bases, annualization, null behavior, and non-authority are explicit at `src/quant_strategies/evaluation/metrics.py:20` to `:191`. |
| Evaluation annualization | Formula implementation is coherent, but `annualization_periods_per_year` is caller-supplied and not checked against observed bar cadence. This is a configuration/ranking risk, not a formula bug. |
| Crypto perp evaluation ledger | Funding cashflow, fees, realized PnL, NAV path, and drawdown are implemented in the project perp ledger at `src/quant_strategies/evaluation/backend.py:489` to `:661`. Tests cover this path. |

Quant caveats that are not bugs:

| Caveat | Why it is acceptable now |
|---|---|
| Linear engine trade activity is not portfolio NAV | The semantics say this directly at `src/quant_strategies/evidence_semantics.py:42` to `:85`. Evaluation owns NAV/path evidence. |
| Validation is not market validation | `src/quant_strategies/validation/policy.py:20` to `:25` keeps promotion, paper, and live eligibility false. |
| No statistical alpha claims | PRD defers benchmark-relative metrics and this code does not overclaim `validated_alpha`. |
| Strategy purity is not a sandbox | `src/quant_strategies/decisions/purity.py:1` to `:9` says this explicitly. This is fine if strategy authors are trusted or reviewed. |

### Quant Finding: Evaluation annualization cadence is unchecked

- Severity: Medium
- Action class: Add
- Evidence: `src/quant_strategies/evaluation/config.py:75` to `:76` only requires `annualization_periods_per_year > 0`. `src/quant_strategies/evaluation/backend.py:812` to `:835` and `:881` to `:905` annualize from the observed portfolio return series using that configured value. The project perp ledger writes `period_return` on every timestamp in the prepared close index at `src/quant_strategies/evaluation/backend.py:594` to `:605`, so metrics are full-grid portfolio-return metrics, including flat/no-position bars.
- Why it matters: If `annualization_periods_per_year` does not match the data cadence, Sharpe, volatility, Sortino, Calmar, and annualized return are mis-scaled. Within one config, relative ordering may still be usable; across configs or against absolute thresholds, the number can mislead.
- Root cause: The metric contract depends on a caller-supplied cadence but does not verify or surface cadence consistency.
- Recommendation: Add a cadence summary/warning derived from the portfolio path or normalized rows, and document that evaluation risk metrics are full-grid portfolio-return metrics, not trade-only returns. Do not infer and silently replace the configured value; warn when observed spacing and configured annualization disagree materially.
- Tradeoff: Irregular sessions, DST, and sparse crypto/equity calendars make exact inference messy. A warning plus explicit observed cadence summary is enough for the first hardening pass.
- Verify: Add config/runner tests for cadence warnings on obvious mismatch and no warning on a matching regular grid.

## Unknown Unknowns And Assumption Risks

| Assumption | Why it may be wrong | Smallest de-risking step |
|---|---|---|
| `quant_data` returns economically correct rows with valid `available_at` | Row contracts catch shape/timing fields, not data vendor truth, stale adjustments, survivorship, or exchange-specific funding quirks | Run a small known-symbol known-window audit against raw vendor records before the first serious candidate batch. |
| VectorBT Pro semantics match the project assumptions for all non-funding evaluation cases | The real smoke passed, but one smoke is not a full cross-product of sizing, overlap, multi-asset, and cash-sharing cases | Keep the smoke as a pre-run check and add scenario-specific regression tests as real strategies expose edge cases. |
| Validation agreement status is understood by downstream consumers | The agreement oracle can be disabled or skipped; without explicit status, consumers may treat self-certified and cross-checked evidence the same | Add agreement/cross-check status to artifacts and check `quant_autoresearch` consumption. |
| Evaluation annualization config matches data cadence | Code requires a positive annualization value but does not check it against observed spacing | Emit cadence summaries/warnings and document full-grid return semantics. |
| Evaluation artifacts only need upstream-replay, not artifact-alone replay | Current manifest says rows are not embedded, while the PRD direction leans toward full audit traceability | Make a deliberate decision and encode it in PRD/docs/manifest tests. |
| Strategy authors remain trusted | Static purity lint is not a runtime sandbox | If untrusted strategy code enters the workflow, add sandboxing as a separate security project. |
| Performance is good enough at 1M rows | Tests cover correctness and some performance discipline, not large real data runs with artifact writes | Time one diagnostic, validation, and evaluation run on representative data before scaling automated loops. |

## Overbuilt, Underbuilt, And Right-Sized Areas

Overbuilt:

- The validation backend registry still has legacy/test-looking options that are not part of the config surface.
- Result/status vocabulary has accreted across engine, runner, validation, and evaluation. The public workflow is simple, but interpretation has too many labels.
- The repo has many prior review docs under `docs/reviews/`; they are not active code risk, but future agents should not let them outrank source and tests.
- Some orchestrators are long. `evaluation/backend.py` in particular combines the VectorBT Pro adapter, project perp ledger, and metric/table helpers. This is maintenance debt, not foundation failure.

Underbuilt:

- Evaluation artifact self-containment. This is the one issue I would fix before relying on evaluation output as an audit package.
- An explicit "ready to run" verification command or optional CI job that verifies the installed CLI and includes real VectorBT Pro smoke.
- Explicit agreement/cross-check status for validation scenarios when the oracle is disabled or skipped.
- Annualization cadence warnings and documentation for full-grid portfolio returns.
- A durable decision record for what validation `VectorBTProBackend` still means, if anything, now that verdict source is engine-only.

Right-sized:

- The three public jobs are clear and map to the PRD.
- The default strategy ontology is narrow and honest.
- Pydantic is used at boundaries where validation and freezing matter; it is not sprayed everywhere.
- The shared execution kernel is the correct anti-duplication point.
- Engine trade-activity math and evaluation NAV/path math are separate because they represent different evidence models.
- Validation/evaluation remain advisory and do not auto-promote.

## Missing Docs, PRD, ADR, Or Decision Records

| Gap | Recommended doc/action |
|---|---|
| Installed CLI drift | Add `conda run -n quant python -m pip install -e .` and `conda run -n quant quant-strategies --help` to the pre-run checklist. |
| Evaluation replayability contract | Decide whether evaluation must be replayable from artifacts alone. If yes, add row and decision artifacts. If no, update PRD and manifest language so "replayability" means upstream-replay only. |
| Agreement/cross-check status | Document when validation scenarios are independently agreement-checked, skipped, unavailable, disabled, or self-certified by engine tests only. |
| Annualization and return-base semantics | Document that evaluation risk metrics use full-grid portfolio returns, including flat bars, and that `annualization_periods_per_year` must match bar cadence. |
| Validation backend registry disposition | Add a short ADR or `FOUNDATION_LOCK.md` note that fake/vectorbtpro validation backends are retired from production-facing registry, with agreement oracle as the only supported VectorBT Pro validation cross-check. |
| PRD execution-model wording | Amend `PRD.md:150` or add a decision note clarifying that validation backends and portfolio/NAV evaluation backends intentionally do not share one interchangeable PnL backend protocol. |
| Pre-run verification | Add a short command block to `docs/foundation-surfaces.md` or `README.md` with full suite plus `RUN_VECTORBTPRO_SMOKE=1` smoke. |
| First real run checklist | Document: clean ignored results dir, run tests/smoke, run one known small config, inspect artifacts, then run candidate batch. |

## Preserve / Refactor / Simplify / Add / Retire Action Map

| Action class | Findings / recommendations | Rationale |
|---|---|---|
| Preserve | Strategy decision ontology, shared execution kernel, row contract, strict causality replay, engine trade-activity math, funding sign/window logic, validation advisory policy, evaluation metric semantics | These are the foundation. They directly encode the PRD's core constraints. |
| Refactor | Large orchestrator modules only when changing related behavior; expose failure-artifact write errors; if evaluation backend work starts, split vbt adapter / perp ledger / metric helpers | Refactoring them now is lower priority than running and fixing artifact auditability, but targeted refactors improve reviewability. |
| Simplify | Keep public vocabulary to `run`, `validate`, `evaluate`; document a single status map; nest/type runner evidence fields after checking `quant_autoresearch` usage | The public workflow is simple, but result interpretation has accumulated too many labels and raw dicts. |
| Add | Installed CLI smoke/pre-run install check; evaluation decision records and input row snapshots; agreement/cross-check status; annualization cadence warnings; pre-run real backend smoke docs/CI | These close real trust and operability gaps. |
| Retire | Test/legacy validation backends from production-looking registry | Avoids future bias toward old backend models. |

## Prioritized Recommendations

| Priority | Action class | Recommendation | Why now | Verify |
|---|---|---|---|---|
| P1 | Add | Refresh the editable install and add an installed-console-script smoke to the pre-run checklist | The literal documented `quant-strategies` command currently fails in the `quant` env despite correct source | `conda run -n quant quant-strategies --help` |
| P1 | Add | Make evaluation artifacts include decision records and normalized input row snapshots, or deliberately downgrade the replayability contract in PRD/docs | This is the only material foundation gap before treating evaluation as independently auditable evidence | Add artifact tests and rerun evaluation runner/artifact tests |
| P2 | Add | Add explicit agreement/cross-check status for validation scenarios, including disabled/skipped/unavailable/pass/fail | Multi-trade validation evidence is intentionally not cross-backend comparable; consumers should see that status before ranking at scale | Agreement oracle and validation manifest tests |
| P2 | Add | Add annualization cadence warnings and document full-grid portfolio return semantics | Misconfigured annualization silently mis-scales risk metrics and can corrupt thresholds/cross-config comparisons | Evaluation config/runner metric tests |
| P2 | Retire | Remove or privatize `fake` and `vectorbtpro` from validation `get_backend`; keep VectorBT Pro only as explicit agreement oracle | Prevents legacy compatibility from biasing future architecture | Validation backend, agreement oracle, and config tests |
| P2 | Add | Add a documented pre-run verification command that includes the real VectorBT Pro smoke | Default suite skips the smoke; first real running should not depend on memory | Full suite plus `RUN_VECTORBTPRO_SMOKE=1` smoke |
| P3 | Simplify | Document a single config/status/result interpretation map and nest/type runner evidence fields after checking `quant_autoresearch` usage | Reduces the real "layered vocabulary" issue without breaking consumers | Docs tests plus downstream usage check |
| P3 | Refactor | Opportunistically extract smaller helpers from long orchestrators, especially `evaluation/backend.py`, when modifying them | Improves maintainability without front-loading rewrite risk | Existing full test suite and boundary tests |
| P3 | Refactor | Emit a warning/event when evaluation failure-artifact writes fail | Prevents silent loss of diagnostics on failing runs | Targeted runner failure-artifact test |
| P3 | Doc | Amend PRD/backend-contract wording around validation backends versus portfolio/NAV evaluation backends | Avoids forcing a bad abstraction to satisfy an over-broad sentence | Docs tests or PRD review |
| P3 | Preserve | Keep advisory language and no-promotion flags intact | Prevents false confidence from mechanical evidence | Docs tests and policy tests |

## NOT In Scope

- Rewriting the repository before running. The evidence does not justify a broad rewrite.
- General-purpose backtester ergonomics.
- Live trading, paper trading, order routing, or promotion automation.
- Benchmark-relative alpha metrics, DSR/PBO/CPCV, or market validation.
- Data acquisition, materialization, refresh, repair, or vendor truth checks owned by `quant_data`.
- Runtime sandboxing for untrusted strategy authors.

## Verification Summary

Verified:

- Focused correctness suite: `191 passed, 1 skipped` in `35.47s`.
- Full test suite: `889 passed, 1 skipped` in `29.25s`.
- Explicit real VectorBT Pro evaluation smoke: `1 passed` in `5.85s`.
- Source CLI help: printed `{run,validate,evaluate}` through `quant_strategies.cli.main`.
- CLI/docs/config tests: `68 passed` in `0.46s`.
- Cross-review focused suite for disputed findings: `52 passed, 1 skipped` across funding/perp ledger, agreement oracle, evaluation config, and evaluation backend tests.
- Cross-review source check against `review-claude.md`: accepted only verified gaps; rejected the overstated "no validation/evaluation TOML" and "no perp ledger numeric pin tests" claims.
- Source trace for PnL, funding, costs, row contracts, causality, validation policy, evaluation metrics, and artifact manifests.
- Repository boundary tests that guard against research archive pointers, ignored generated result roots, runner-internal coupling, and legacy `quant-engine` dependency.

Not verified:

- Real `quant_data` row correctness on production-scale datasets.
- Refreshed installed CLI command; `conda run -n quant quant-strategies --help` currently fails until editable install metadata is refreshed.
- Downstream `quant_autoresearch` behavior.
- Exact `quant_autoresearch` consumption of `RunResult` and validation agreement fields.
- Full 1M-row diagnostic/evaluation timing.
- Market validity or alpha.

Final answer: refresh the editable install, then begin running while keeping outputs advisory. Fix evaluation artifact self-containment before using evaluation artifacts as standalone audit evidence, and add agreement-status plus annualization-cadence hardening before autonomous ranking scales.
