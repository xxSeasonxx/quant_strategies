# History

Development chronology, migration rationale, review disposition, and rejected
alternatives for `quant_strategies`. This is the **only** home for history.

Active contracts and current state live elsewhere and stay history-free:
`PRD.md` (intent), `FOUNDATION_LOCK.md` (locked invariants, accepted debt,
deferred triggers), `README.md` (orientation), `docs/foundation-surfaces.md`
(surface I/O reference), `docs/consumer/` (consumer docs), and `TODOS.md`
(current open work). Entries below are newest-first and record **material
contract or behavior changes** only; routine refactors, test maintenance, and
review bookkeeping stay out — the review disposition index at the end is the one
exception.

---

## 2026-06-13 — Slippage cost floor (R4)

The scored cost floor now requires positive per-side slippage — a new fail-closed
`zero_slippage` feasibility verdict beside `zero_cost`. A `fee>0, slippage=0`
config (previously scored with stop/barrier exits filling at the level with no
execution slippage) is now non-scoreable, uniformly across quick run, validation,
and evaluation. Current contract in `FOUNDATION_LOCK.md`.

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

## 2026-06-10 — Intrabar OHLC stop fills

`RiskRule` stop / take-profit / trailing trigger on the bar's intrabar high/low
and fill at the barrier level (worsened to the bar open on a gap-through; adverse
barrier wins a same-bar tie). A diagnostic `fill_stress` scenario adds extra
adverse barrier-exit slippage without changing the climbed `realistic_costs`
path. Current contract in `FOUNDATION_LOCK.md`.

## Causality micro-default for quick-run scoring

Quick-run iteration uses micro causality so scoring is never blocked by replay
timeout (focused replay timed out on full-panel baselines); validation and
evaluation own complete or explicitly bounded replay evidence. Current contract
in `FOUNDATION_LOCK.md`.

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
