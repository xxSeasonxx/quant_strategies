# Claude Foundation Review

Date: 2026-06-03
Reviewer lens: senior quantitative researcher (engine/validation/evaluation math + audit boundaries)
Method: independent re-derivation from source + four fresh-context lens subagents + targeted test execution.
Disposition update: 2026-06-04 — the two P1 annualized/risk metric guards, all
three P2 operability findings, and the P3 simplification items identified here
are implemented in the active codebase. `make check` includes the real VectorBT
Pro smoke, quick-run runner-stage failures report `completed=False` /
`run_completed=false`, and `quant-data` is bounded as `>=0.1.0,<0.2.0`. The P3
work removed duplicate fill/cost model contracts, moved evaluation
portfolio/run result contracts and the validation run result into neutral
`results.py` modules, moved orchestration into `_pipeline.py`, renamed the
concrete evaluation backend to `vectorbtpro_backend.py`, replaced reflective
backend dispatch with declared Protocol checks, moved shared data-audit
ownership into `core.data_audit`, and trimmed `extended_ontology` to the
near-term multi-leg opt-in subset.
Path references in the review evidence below preserve review-time locations;
the disposition table records the current active-code locations where they
changed.

## Independence Note

Per Season's instruction, this review treats all prior reviews as **unverified claims**. I
re-derived the engine, funding, NAV, annualization, and causality math directly from source and
backed conclusions with executed tests. The then-root-level `review-codex.md`
was read only for artifact *format* before scope-lock; its technical
conclusions were not used as input. The four
lens subagents (onboarding, architecture, senior-engineering, adversarial) were explicitly barred
from reading the root review working notes and `docs/reviews/**`, so their findings are
uncontaminated by prior reviews. Where this review independently *confirms* or *contradicts* a
codex claim, that is stated explicitly.

## Executive Verdict

**The foundation is sound and safe to begin running.** There is **no critical math error** in the
shared engine: PnL signs, funding sign and timing, fee/slippage sidedness, NAV-at-mark accounting,
the annualization *formula*, and the causality/lookahead replay are all correct and test-backed.
The public workflow is genuinely simple, there is **zero legacy/back-compat code**, and the design
is not bent around stale artifacts. Season's instinct that the workflow is simple is correct; the
"layered on layered" worry is real only as a *naming/file-size* problem, not a logic problem.

At review time, two **new** quant findings — not raised in prior reviews — needed fixing before
anyone trusted the *risk-adjusted/annualized* metric family (`annualized_return`, `volatility`,
`sharpe`, `sortino`, `calmar`):

1. **P1 — cadence mismatch below 2× is silently undetected.** The annualization-cadence guard only
   warns when `mismatch_factor > 2.0` (`evaluation/runner.py:91,768`). A daily strategy annualized
   with `365` against an observed `252` cadence is factor `1.448` → **no warning**, run reports
   `evaluation_complete`, and all annualized/risk-ratio metrics are silently scaled wrong by ~45%.
2. **P1 — no minimum-sample floor on annualized metrics.** `annualized_return =
   (1+total_return)^(periods/sample_count)−1` (`evaluation/backend.py:812-815,881-883`) is computed
   whenever `sample_count >= 1`. On a short window this produces finite-but-absurd values that pass
   every finiteness gate (numerically verified: `P=252, sample_count=2 → 1.6e5`; `sample_count=1 →
   2.7e10`; minute-bar `P=525949, sample_count=1` overflows → that extreme case fails loudly, which
   is safe, but the moderate cases do not).

The **core trade economics** (`total_return`, `ending_value`, `max_drawdown`, `trade_count`,
`win_rate`, `profit_factor`, funding cashflow) are correctly finiteness-gated and are trustworthy.
The two P1 issues were confined to the annualized/risk-ratio family and were advisory-labeled, so
they did not block running — they bounded *which numbers a consumer may trust* before the current
guards landed.

Everything else I found is P2/P3 operability and maintainability, deliberately not overrated.

## Confirmation Of Prior-Review Claims (Independent)

| Prior claim | My independent verdict | Evidence |
| --- | --- | --- |
| Evaluation runs the same `audit_decision_rows` as validation, before metrics | **Confirmed TRUE** | grep: `evaluation/runner.py:312` and `validation/__init__.py:377`; gate order `evaluation/runner.py:238→241→244` (audit → causality → portfolio). CodeGraph under-reported callers (re-exports); grep + read confirm. |
| `ending_value` = actual final portfolio value; non-finite final fails the scenario | **Confirmed TRUE** | `evaluation/backend.py:1088 _required_final_metric` takes `values[-1]`, raises `invalid_required_metric:ending_value` if non-finite. No `_last_finite` skipping. |
| No critical funding sign inversion | **Confirmed TRUE** | `funding.py:44` `Σ(-direction*rate)*weight`; perp ledger `backend.py:519` `-units*mark*rate`. Long pays positive funding, short receives, on both paths. |

## Scope And Evidence Inspected

Scope:

- Repo: `/Users/Season_Yang/Personal/quant_strategies`.
- Objective source: `PRD.md` (three public jobs §2/§4; non-goals §4.2/§8; math-correctness goal G2).
- Math scope locked to **engine/validation/evaluation semantics + audit boundaries**; the four
  `untested/*.py` strategies were treated as opaque inputs (strategy alpha out of scope).
- Artifact originally requested as root-level `review-claude.md`; archived as
  `docs/reviews/2026-06-03-foundation-claude-disposition.md`.

Evidence inspected directly (source, not docs):

- Math core: `funding.py`, `engine/evaluation.py` (`screen`/`_select_exit`/`_funding_return`),
  `engine/executable.py`, `evaluation/backend.py` (vbt path + `project_perp_ledger_v1`),
  `evaluation/metrics.py`, `evidence_semantics.py`.
- Causality/audit: `causality.py` (`check_hidden_lookahead`, strict + emitted boundaries),
  `validation/data_audit.py`, gate order in `evaluation/runner.py` and `validation/__init__.py`.
- Contracts/spine: `core/config.py` (`StrategyExecutionSpec`, `FillModelConfig`), `PRD.md`.

Tests executed (conda env `quant`):

- `pytest` over `test_funding`, `test_engine_screen`, `test_engine_executable`,
  `test_evaluation_backend`, `test_evaluation_runner`, `test_validation_lookahead`,
  `test_validation_future_poison`, `test_validation_data_audit`,
  `test_validation_backends_and_policy` → **202 passed, 1 skipped** (the skip is the real-VBT smoke).
- With `RUN_VECTORBTPRO_SMOKE=1` over `test_evaluation_backend`, `test_vectorbtpro_backend`,
  `test_agreement_oracle` → **101 passed** (real VectorBT Pro bars-path NAV math verified live;
  `vectorbtpro`, `pandas`, `pyarrow` all present in the env).
- Direct numeric check of the annualization blow-up and the 2.0 cadence threshold (results above).

Verification not performed:

- I did not inspect `quant_autoresearch` or `quant_data` source.
- I did not assess strategy alpha, regime robustness, capacity, or benchmark-relative edge.
- I did not run a full `run_validation`/`run_evaluation` against live `quant_data` (no dataset in scope).

## Intended Foundation Model

From first principles, this project is a **narrow, stateless evidence engine**:

- Accepts a pure strategy module + explicit config.
- Loads/normalizes rows from upstream `quant_data`; validates params at the boundary.
- Generates typed decisions from only the rows/params the strategy can see.
- Audits row lineage + observation availability, then strict-replays for hidden lookahead **before**
  evidence is trusted.
- Emits artifacts with explicit units and `not_authority` labels.
- Never ranks, compares, promotes, updates search memory, or sets stopping rules.

```text
quant_autoresearch / Season
      | frozen strategy.py + explicit TOML
      v
quant_strategies public job (run | validate | evaluate)
      | StrategyExecutionSpec + execute_strategy_run
      v
point-in-time rows -> pure strategy -> typed decisions
      | audit_decision_rows + strict hidden-lookahead replay  (BOTH gate before metrics)
      v
quick-run diagnostics | validation evidence | evaluation NAV/path evidence
      | typed result + artifacts (advisory only)
      v
ranking / comparison / promotion  ---> OUTSIDE this repo
```

The current code matches this model. The vertical layering (`config → spec → execution →
engine/backend`) is *necessary* layering — each level has a distinct reason to change — not
decoration.

## Project Ontology

Hard invariants, and whether they hold in code:

- Strategies cannot load data, write artifacts, call engines, use clocks/RNG, or read future rows.
  → Enforced by purity AST lint + frozen rows/params at `core/execution.py` + strict replay. **Holds.**
- A decision's information set must be available no later than its decision time.
  → `data_audit.py:68` (`available_at > decision_time` → violation) + causality replay. **Holds.**
- Validation and evaluation require `validate_params`; quick run may flag schema-less runs.
  → `StrategyExecutionSpec.require_param_validator` (`core/config.py:77`). **Holds.**
- Quick-run/validation `net_return` is signed linear trade activity, **not** NAV.
  → Labeled `evidence_semantics.py:78` ("not portfolio NAV"). **Holds** (but see P3 dual-key note).
- Evaluation owns NAV/path; not forced behind validation's PnL semantics.
  → Separate `PortfolioEvaluationResult` + `project_perp_ledger_v1`. **Holds.**
- No result authorizes promotion/paper/live/ranking.
  → `not_authority` on every metric; verdicts advisory. **Holds.**
- Generated artifacts are rerun, not back-compat'd.
  → Fresh per-run timestamped dirs; `results/` git-ignored; no cross-run input reads. **Holds.**

## Math Re-Derivation (Engine Lens)

What I verified line-by-line and found **correct**:

- **Engine trade PnL** (`engine/evaluation.py:71-81`): `gross = direction·(exit−entry)/entry·weight`
  (long/short sign correct); `net = gross + funding − cost`; round-trip cost subtracted once.
- **Fill sidedness** (`engine/evaluation.py:253-263`): long buys ask / sells bid, short sells bid /
  buys ask — pays the spread both ways. Entry fills `decision_idx + entry_lag_bars`
  (config enforces `entry_lag_bars ≥ 1`, so never same-bar). Exit triggers scan
  `entry_index+1 … +max_hold`; threshold exits are **bar-sampled** at the fill field (a labeled
  modeling approximation, *not* intrabar high/low — a research caveat, not a bug).
- **Funding window + sign** (`funding.py:38-44`): window `(entry, exit]`, dedup on matching rate,
  conflict raises; `Σ(-direction·rate)·weight`. Long pays positive funding, short receives. ✔
- **Perp ledger `project_perp_ledger_v1`** (`evaluation/backend.py:489-661`): a real cash ledger.
  Funding `-units·mark·rate` (sign matches kernel); funding/exit/entry ordering at each timestamp
  exactly implements the `(entry, exit]` window; realized PnL `units·(exit_fill−entry_fill)` (sign
  correct); fees on notional; slippage sidedness correct; NAV = cash + Σ units·(mark−entry_fill);
  positions sized as `target_weight · equity_snapshot`; gross-exposure ≤ 1 enforced
  (`_validate_max_gross_target_weight`); dangling open positions raise. **Correct end to end.**
- **Metrics** (`evaluation/backend.py:761-901`): `total_return = ending/100 − 1`;
  annualization `(1+total)^(P/n)−1`; `volatility = sample_stdev·√P` (n−1 denominator);
  `sharpe = (mean·P)/vol` = `(mean/σ)·√P` (rf=0); `sortino` uses downside semivariance over full N;
  `calmar = annualized/|maxDD|`; `profit_factor`/`sortino` report `None` (not `∞`) when undefined.
  Formulas correct.
- **`ending_value`** is the actual final NAV and fails on non-finite (`_required_final_metric`).
- **Audit + causality gate before metrics** in both validation and evaluation. **Verified.**

The annualization findings below are about *robustness/guarding*, not the formula.

## Domain-Specific Quant Lens Findings (Prioritized)

### P1 — Annualization cadence mismatch < 2× is silently undetected → wrong risk metrics on a "complete" run
- Evidence: `evaluation/runner.py:91` `_ANNUALIZATION_CADENCE_MISMATCH_FACTOR_THRESHOLD = 2.0`, used
  at `:768`; warning is advisory only (`:160-161`, never fails the run).
- First-principles: `365` vs observed `252` → factor `1.448` (verified) → no warning. The annualized
  formula then scales by the wrong number of periods, and `annualized_return / volatility / sharpe /
  sortino / calmar` (`backend.py:812-833`) are wrong by the mismatch factor while the run reports
  `evaluation_complete`. Sharpe is the metric a quant most wants to trust; it is the one silently
  mis-scaled. The word "obvious mismatch" in the docs hides that 1.0×–2.0× is *not* caught.
- Root cause: contract — a loose, advisory-only guard on a metric presented as headline economic
  evidence.
- Action (**Add/Refactor**): tighten the threshold (any non-trivial mismatch, e.g. > ~1.1×, should
  warn), and/or require the consumer to confirm cadence, and/or null the annualized/risk-ratio
  family when cadence status is `warning`. Smallest fix: lower the threshold + null the dependent
  metrics on mismatch. Scope: one constant + one guard in `_perp_ledger_metrics`/`_portfolio_metrics`.

### P1 — No minimum-sample floor on annualized_return / Sharpe → finite-absurd values pass all gates
- Evidence: `evaluation/backend.py:810` gate is `if coverage.observed and coverage.nonfinite_count
  == 0:` (i.e., `sample_count >= 1`); annualization at `:812-815` and `:881-883` has no `sample_count`
  floor. Required-metric finiteness set (`runner.py:76-81`) does **not** include the annualized
  family, so absurd-but-finite values are written to `evaluation_metrics.json`.
- First-principles (numerically verified): `total_return=0.10`, `P=252`, `sample_count=2 →
  1.64e5`; `sample_count=1 → 2.70e10`. `volatility` requires ≥2 samples and `sharpe` is `None` when
  vol is `None`, so the 1-sample case nulls Sharpe — but `annualized_return` still blows up, and with
  2 near-identical returns the tiny stdev denominator makes Sharpe explode (finite).
- Root cause: contract — annualized/risk-ratio metrics lack a minimum-observations precondition.
- Action (**Add**): require a configurable minimum `return_sample_count` (e.g. ≥ ~20) before emitting
  `annualized_return`/`volatility`/`sharpe`/`sortino`/`calmar`; otherwise emit `None` with a warning.
  `return_sample_count` is already surfaced, so the consumer-side guard is trivial too.

### Preserve (correct quant choices)
- Linear `net_return` vs NAV-path evaluation are explicitly separate evidence models (PRD G3) — keep.
- Funding-inclusive economics on both the linear engine and the perp ledger — keep.
- `None`-not-`∞` for `profit_factor`/`sortino`; bar-sampled threshold exits (labeled) — keep.

## Architecture And Boundary Review

The public architecture is stronger than the file tree suggests. Dependency direction is clean
(`core`/`engine` import nothing upward from the three job facades), the public surface is exactly
three functions + three result types + one CLI, and `StrategyExecutionSpec` + `execute_strategy_run`
is a genuinely neutral spine both jobs adapt down into. **Preserve the spine.**

Structural findings disposition (maintainability, not correctness):

- **P3 — Duplicate fill/cost models:** addressed. `engine.FillModel` and
  `engine.CostModel` now reuse the neutral `core.config` contracts; same-bar
  entry remains rejected at the shared boundary.
- **P3 — Evaluation backend naming:** addressed. The concrete VectorBT Pro /
  project-ledger implementation lives in `evaluation/vectorbtpro_backend.py`,
  result contracts live in `evaluation/results.py`, and backend Protocols stay
  in `evaluation/backends.py`.
- **P3 — Public facades carrying orchestration:** addressed for validation and
  evaluation. Package `__init__.py` files are public facades, result types live
  in `results.py`, and orchestration lives in `_pipeline.py`.
- **P3 — Reflective backend dispatch:** addressed. Evaluation dispatch uses
  `PreparedEvaluationBackend` / `DataKindNamedEvaluationBackend` Protocol checks
  and always passes `data_kind` through the declared backend contract.
- **P3 — Shared audit homed in a peer bounded context:** addressed.
  Validation, evaluation, and strategy tests import `audit_decision_rows` from
  neutral `core.data_audit`; the validation-owned module was removed rather
  than kept as a compatibility layer.

## Engineering, Testability, And Operability Review

Strengths: contract-oriented tests (causality subset *and* suppression, funding sign/window/dedup,
NAV/`ending_value`, audit parity, param-validation-required, boundary immutability) are real and
green; typed result objects expose failure stage/status; strict replay is enforced, not promised.

Material operability gaps, now dispositioned:

- **P2 fixed — `make check` exercises the real VBT bars-path smoke.** The `check` target invokes
  `check-vectorbtpro-smoke` after the normal suite, and `check-all` is only an alias for `check`.
  The smoke remains opt-in when run directly without `RUN_VECTORBTPRO_SMOKE=1`, but fails loudly on
  missing `pandas`, `pyarrow`, or `vectorbtpro` once enabled.
- **P2 fixed — failed quick runs no longer report completion.** Runner-stage failures return
  `RunOutcome.completed=False`, keep `failure_stage`, and write `summary.json` with
  `run_completed:false`.
- **P2 fixed — `quant-data` is version-bounded.** Package metadata now requires
  `quant-data>=0.1.0,<0.2.0`, matching the current tested contract while guarding against semantic
  drift.

Low, do-not-overrate:

- **P3** `net_return` carries linear-sum (engine) vs compounded-NAV (vbt) meaning under one key;
  contained today by the engine-only verdict lock + the oracle comparing `gross_return`. Document at
  the key level.
- **P3** `_is_true_flag` string coercion vs the contract's strict-bool `has_funding_event` (dead path
  on the gated evaluation route).
- **P3** `not_evaluated` (empty post-normalization) is not a hard stop in
  `_assert_row_contract_allows_engine_request` (currently unreachable; `load_data` raises first).
- **P3** causality's missing-`available_at` fallback returns "visible"; neutralized because the row
  contract makes missing `available_at` a hard error on validate/evaluate. Defense-in-depth only.

## Season's Four Concerns — Direct Verdicts

| Concern | Verdict | Basis |
| --- | --- | --- |
| (1) Over-engineering? | **No** at the workflow level. The speculative `extended_ontology` breadth was trimmed to the near-term multi-leg subset, and reflective backend dispatch was simplified against the declared Protocols. | Three jobs, neutral spine, two justified evidence models. |
| (2) Workflow simple? | **Yes — your instinct is right.** One pure `generate_decisions(rows, params)` file (+ optional `validate_params`), three commands, three result objects, one shared execution path. | `cli.py`, `core/execution.py`, `core/config.py`. |
| (3) Layered on layered / poor design? | **Partial — naming/file-size, not logic.** Vertical layering is necessary and clean; the smells are triple "engine" naming + duplicate `FillModel`, three backend stacks under similar names, large facades, and reflective dispatch. None are "layers for their own sake." | onboarding + architecture lenses, confirmed by source. |
| (4) Legacy / stale-artifact bias? | **No.** Zero shim/deprecated/alias markers in source; `validation/config.py` *rejects* a removed `backend` key with a migration error instead of shimming; fresh per-run dirs; `results/` git-ignored; no cross-run input reads. The design is not bent around old outputs. | grep + `causality`/`artifacts` read. |

## Unknown Unknowns And Assumption Risks

- `quant_autoresearch` and `quant_data` were not inspected; this review assumes narrow typed-surface
  consumption and upstream-owned data semantics.
- The vbt bars-path is correct *when run* (verified here), but its correctness is not guarded by the
  default CI gate — a future vbt API drift would degrade to `unavailable`/`failed`/warnings rather
  than silent wrong numbers (the backend treats vbt defensively), which is the safer failure mode.
- A reused `EvaluationRequest`/`bars` object with a stale cached bar index is a latent foot-gun
  (`engine/bar_index.py`); not triggered by the current per-scenario flow.
- Annualized/risk metrics are now guarded by annualization cadence
  (`annualization_cadence.status == "ok"`) and the minimum return-sample floor
  `[metrics].min_annualized_samples` (default `20`). Consumers should still
  treat null `sharpe`/`annualized_return`/`sortino`/`calmar` as an
  evidence-quality signal: cadence warnings or insufficient samples null the
  annualized/risk metrics family while preserving core economics.

## Overbuilt / Underbuilt / Right-Sized

Right-sized: three public jobs; flat pure strategies; shared spine; two evidence models; advisory
labels; audit + strict-replay gates; finiteness gating on core economics; fresh per-run artifacts.

Previously underbuilt: default bars-path verification in `make check`. That P2 gap is now fixed.
The two P1 annualized/risk metrics guards also have explicit cadence and minimum return-sample floor
handling.

Overbuilt / at risk: deeper backend math extraction remains deferred until the backend is touched
for a real change. Do **not** add a ranking layer, scoring service, strategy registry,
search-memory adapter, or stale-artifact compatibility shim — those violate the boundary.

## Preserve / Refactor / Simplify / Add / Retire Action Map

| Priority | Action class | Finding | Evidence | Recommended action |
| --- | --- | --- | --- | --- |
| P1 | Add/Refactor | Annualized/risk metrics could be trusted with cadence mismatch or too few samples | `evaluation/runner.py`, `evaluation/backend.py` | Implemented: cadence warnings and `[metrics].min_annualized_samples` null the annualized/risk metrics family when evidence quality is insufficient. |
| P2 | Add | `make check` skipped real VBT bars-path math (FakeBackend + env-gated) | `Makefile`, `tests/test_evaluation_backend.py` | Fixed: `make check` invokes `check-vectorbtpro-smoke`, and enabled smoke imports fail loudly. |
| P2 | Refactor | `summary.json` `run_completed:true` next to `status:"failed"` (artifact-level trap) | `runner/artifacts.py`, `runner/__init__.py` | Fixed: runner-stage failures return `completed=False` and summary `run_completed=false`. |
| P2 | Add | `quant-data` unpinned — sole data source, silent semantic-drift risk | `pyproject.toml` | Fixed: dependency is bounded as `quant-data>=0.1.0,<0.2.0`. |
| P3 | Refactor | Triple "engine" naming + duplicate FillModel (`ge=1` vs `ge=0`) | `engine/`, `core/engine_runner.py`, `core/config.py:49` | Fixed: engine fill/cost models reuse the neutral `core.config` contracts. |
| P3 | Simplify | Reflective backend dispatch re-implements declared Protocols | `evaluation/_pipeline.py`, `evaluation/backends.py` | Fixed: dispatch uses Protocol checks and always passes `data_kind`. |
| P3 | Refactor | Large facades entangle contract + orchestration | `evaluation/_pipeline.py`, `validation/_pipeline.py`, `evaluation/vectorbtpro_backend.py` | Fixed for public facades/result contracts; deeper backend math extraction remains deferred until touched. |
| P3 | Refactor | Shared `audit_decision_rows` homed in `validation/` | `core/data_audit.py`, `evaluation/_pipeline.py`, `validation/_pipeline.py` | Fixed: shared audit ownership moved to neutral `core.data_audit` with no validation compatibility shim. |
| P3 | Retire(trim) | `extended_ontology` is test-only/speculative | `decisions/extended_ontology.py` | Fixed: opt-in surface now keeps only multi-leg instruments over existing base instruments and target-weight sizing. |
| P3 | Preserve | `net_return` dual semantics under one key; `_is_true_flag` coercion; `not_evaluated` soft-stop; causality `available_at` fallback | as cited above | Preserved/documented; contained today and not worth wrapper fixes. |

## Prioritized Recommendations

1. **Use the fixed gates before trusting evidence:** run `make check`; it now includes the real
   VectorBT Pro smoke. Core economics and guarded annualized/risk metrics have explicit evidence
   quality semantics.
2. **Do not rewrite the foundation.** Pay down naming/facade/dispatch debt only when touching those
   files for a real change.
3. **Keep ranking, comparison, search memory, and stopping rules outside this repo.**

## NOT In Scope

Ranking/comparison; candidate search memory; iteration/stopping policy; statistical alpha or
benchmark-relative selection; capacity modeling; live/paper trading or order routing; data
acquisition/refresh/repair; compatibility with stale generated artifacts; turning this into a
general-purpose backtester; strategy alpha/regime/capacity judgement of the four `untested/`
strategies.

## Final Assessment

This is not over-engineered, the workflow is simple, and there is no legacy or stale-artifact
coupling. The shared engine math — the part that would silently corrupt evidence at scale — is
correct and test-backed. The foundation is **good to begin running** with the active verification
gate. Annualized/risk metrics are now guarded by cadence and sample-count evidence quality, and the
P2 operability traps from this review are fixed.
