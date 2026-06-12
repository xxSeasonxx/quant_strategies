# History

Development chronology, migration rationale, review disposition, and rejected
alternatives for `quant_strategies`. This is the **only** home for history.

Active contracts and current state live elsewhere and stay history-free:
`PRD.md` (intent), `FOUNDATION_LOCK.md` (locked invariants, accepted debt,
deferred triggers), `README.md` (orientation), `docs/foundation-surfaces.md`
(surface I/O reference), `docs/consumer/` (consumer docs), and `TODOS.md`
(current open work). Entries below are newest-first.

---

## 2026-06-12 — Foundation review (Codex)

Source-grounded foundation review of root docs, `docs/`, and `src/`, with quick
run end-to-end as the priority path. Archived at
`docs/reviews/2026-06-12-foundation-codex.md`. Disposition: a delta review
against `docs/reviews/2026-06-11-foundation-claude.md`; accepted findings flow
into `TODOS.md` open work and `FOUNDATION_LOCK.md`; the file is the dated
artifact, not active policy.

## 2026-06-11 — `researched/` archive-boundary test removed

A repository-boundary test asserted `researched/` must not exist (stale-artifact
concern from review No. 17). It was removed because Season is actively working in
`researched/`; the repo no longer enforces that boundary. The other
repository-boundary tests (loop-memory markers, archive-pointer scan) are
unchanged. The forward-looking item — restore the test or relocate the artifacts
once that work settles — is tracked in `TODOS.md`.

## 2026-06-11 — Live-trade-feasibility review retired

The `2026-06-10-live-trade-feasibility-review.md` working review was folded into
`TODOS.md` (market-model follow-ons and residuals) and `FOUNDATION_LOCK.md`, then
removed as a file; its full text remains in git history. Accepted findings
shipped via the portfolio-book-spine migration and reviews No. 6/8/11/20.
Remaining work (capacity No. 3, asset-class frictions No. 7, `researched/`
No. 17) lives in `TODOS.md`.

## 2026-06-10 — Portfolio-book-spine migration

This is the migration that made the **target book** the strategy contract and the
**single causal netted portfolio book** the one scored model of money on every
surface. The current contract is owned by `FOUNDATION_LOCK.md`; the consumer
integration steps are in `docs/consumer/migration.md`. Recorded here: what
changed, what was deleted, and the rejected alternatives.

**What changed (consumer-visible contract):**

- **Decision contract became a target book.** `generate_decisions(rows, params)`
  returns `Sequence[TargetDecision]` — a standing, signed weight-of-NAV target per
  instrument (`0` = flat/close), idempotent (re-emitting the current target trades
  nothing), with an optional declared `RiskRule` (`stop_loss` / `take_profit` /
  `trailing` as fractions of the entry mark, engine-enforced, latching flat on
  fire). Data/time exits became explicit `target=0` decisions.
- **NAV path became the single scored object.** `RunResult.foundation` is the
  authoritative scored portfolio book (schema `v2`, basis
  `quick_run_netted_portfolio_book`), not an optional diagnostic. The per-trade
  ledger (`RunResult.economics`) became a derived attribution view of the same book
  walk (`net_return = gross_return + funding_return − cost_return`, reconciling with
  NAV), never an independent scored number.
- **Feasibility became fail-closed.** `RunResult.feasibility` is a typed
  `FeasibilityVerdict`; a breach sets `failure_stage="feasibility"` and
  `succeeded=False`. The book is never clamped to fit the budget and never collapsed
  into a silent `None`. `succeeded` now means feasible and completed.
- **Leverage budget became operator-frozen.** The agent-editable
  `foundation_max_gross_exposure` `[output]` key was removed; the gross+net budget
  lives with the protocol. Intended exposure beyond it is non-scoreable.
- **Return statistics became at-risk-bar based** (capital-deployed), not a
  zero-padded calendar, with a minimum-sample gate; subwindows below the minimum
  report non-scoreable rather than a finite Sharpe from sample count alone.
- **One accounting model everywhere.** Quick run, validation, and evaluation run
  the same pure book (`netted_portfolio_book_v1`); evaluation adds only Parquet
  trace serialization.

**Deleted with no shim:** `StrategyDecision`, `PositionTarget`, `ExitPolicy`,
`DecisionIntent`, `Direction`, `SizingKind`, `DecisionAction`; the alternate
evaluation backend, the `project_perp_ledger_v1` model name, the single-trade
agreement oracle, and validation's `[agreement_oracle]` config section
(`verdict_source` is `"engine"` only).

**Rejected alternatives:** a compatibility shim or dual code path for the old
decision shapes (the no-legacy principle regenerates artifacts instead); a
fail-open `foundation=None` on breach (replaced by the typed fail-closed verdict);
a separate per-surface or per-data-kind money model (replaced by the one shared
netted book).

## 2026-06-10 — Intrabar OHLC stop fills shipped (review No. 8)

`RiskRule` stop / take-profit / trailing now trigger on the bar's intrabar
high/low and fill at the barrier level (worsened to the bar open on a gap-through;
adverse barrier wins a same-bar tie). A diagnostic `fill_stress` scenario
(`foundation_fill_stress_fraction`, default 10 bps) applies extra adverse
barrier-exit slippage; the climbed `realistic_costs` path is unaffected by the
knob. The current contract is in `FOUNDATION_LOCK.md`.

## Causality replay performance investigation (focused-replay timeouts)

Downstream `quant_autoresearch` full-baseline runs were blocked by focused
causality cost on large panels. The resolution adopted micro causality for
quick-run iteration so scoring is not blocked by replay timeout, while
validation/evaluation own complete or explicitly bounded replay evidence.

Observed failures:

- Full 2024-01-01 to 2025-12-31 baseline with `causality_check="focused"`,
  `focused_probe_limit=100`, `focused_timeout_seconds=60.0` crashed at the
  causality stage before engine scoring: `focused_causality_timeout`,
  `candidate_probe_count=5,265,156`, `selected_probe_count=100`, ~584.9s elapsed.
- A second full-baseline run with `focused_probe_limit=10`,
  `focused_timeout_seconds=180.0` also crashed at the causality stage:
  `focused_causality_timeout`, `candidate_probe_count=5,265,156`,
  `selected_probe_count=10`, ~699.7s elapsed.
- In both runs no score or trades were logged because failure happened before
  engine scoring.

Root cause:

- Probe count alone does not control runtime on full-panel runs.
- Each selected focused probe can still replay strategy generation on a large row
  prefix; strategies that rebuild large per-symbol indexes per replay make a small
  selected-probe count expensive.
- Focused causality cost stays coupled to full scoring-panel size in this path.
- The research loop should receive scored baseline evidence under micro replay
  even when replay times out or records unverified causality.

## Review disposition log

Dated review artifacts live in `docs/reviews/`; the openspec change archive lives
in `openspec/changes/archive/`. Current contracts supersede all of them — read
`FOUNDATION_LOCK.md` for the live disposition anchor.

| Review | Disposition |
| --- | --- |
| `2026-06-12-foundation-codex.md` | Delta review; accepted findings in `TODOS.md` + `FOUNDATION_LOCK.md`. |
| `2026-06-11-foundation-claude.md` | Broad first-principles review; accepted findings folded into `TODOS.md` + `FOUNDATION_LOCK.md`. |
| `2026-06-10-live-trade-feasibility-review.md` | Retired; folded into `TODOS.md` + `FOUNDATION_LOCK.md`; full text in git history. |
| `2026-06-04-foundation-codex-quant.md` | Quant-lens working review; row-order finding implemented via the contract-loader migration (`openspec/specs/data-boundary/spec.md`). |
| `2026-06-04-foundation-codex.md` | Codex foundation working review; cleanup findings dispositioned. |
| `2026-06-04-foundation-claude.md` | Claude foundation working review; cleanup findings dispositioned. |
| `2026-06-03-foundation-codex-disposition.md` | Root-level Codex working review copy; accepted findings dispositioned. |
| `2026-06-03-foundation-codex-delta.md` | Codex delta review. |
| `2026-06-03-foundation-claude-disposition.md` | Root-level Claude working review copy; accepted findings dispositioned. |
| `2026-06-03-foundation-claude-independent.md` | Independent review. |
| `2026-06-02-foundation-codex-p3.md` | P3 follow-up review. |
| `2026-06-02-foundation-codex.md` | Broad review. |

All rows superseded by `FOUNDATION_LOCK.md` and current tests/docs.
