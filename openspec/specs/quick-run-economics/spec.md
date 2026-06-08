# quick-run-economics Specification

## Purpose
Expose quick-run after-cost trade-level economics as typed in-process results so
programmatic consumers can rank and slice Train runs without scraping artifacts.

## Requirements
### Requirement: Quick-run per-trade economics are exposed typed and in-process

`run_config` SHALL expose, on its returned `RunResult`, the after-cost per-trade ledger of a
completed run as a typed, frozen in-process value object. Each per-trade record SHALL carry
the engine's after-cost economics and the fields needed to slice the sample by time and by
symbol: `symbol`, `side`, `weight`, `decision_time`, `entry_time`, `exit_time` (tz-aware
datetimes), `entry_price`, `exit_price`, `exit_reason`, `gross_return`, `funding_return`,
`cost_return`, `net_return`, and `decision_id`. A consumer MUST be able to obtain the ledger
from the result object alone, without reading `summary.json` or any other artifact under
`result_dir`.

The exposed `net_return` SHALL be the same after-cost value the engine computes for the trade
(`gross_return + funding_return - cost_return`), so the typed ledger is the same sample that
feeds the summary scalars and the on-disk `economic_metrics`.

#### Scenario: Per-trade ledger available without artifacts
- **WHEN** a quick run completes its engine evaluation
- **THEN** `RunResult` carries a typed economics object whose per-trade ledger has one record per completed trade
- **AND** each record exposes `symbol`, `side`, `weight`, tz-aware `decision_time`/`entry_time`/`exit_time`, `entry_price`/`exit_price`, `exit_reason`, and `gross_return`/`funding_return`/`cost_return`/`net_return`
- **AND** the consumer obtains the ledger without reading any file under `result_dir`

#### Scenario: Ledger record count matches the engine trade count
- **WHEN** a quick run completes with N engine trades
- **THEN** the in-process per-trade ledger contains exactly N records
- **AND** their order matches the engine's trade order

### Requirement: Quick-run summary economics scalars and slices are reachable from the result

The typed economics object SHALL also carry the summary scalars and groupings already
produced by the runner's economics layer: `trade_count`, winning/losing/flat counts,
`hit_rate`, `average_trade_net`, `profit_factor`, cost/funding share of absolute gross, and
the by-symbol / by-direction / by-exit-reason slices. These scalars and slices MUST be
reachable from the result object without reading any artifact, and MUST equal the values the
same run writes to `summary.json`'s `economic_metrics` (and the diagnostic `economic_slices`),
because they are produced by a single shared computation.

#### Scenario: Summary scalars and slices present in-process
- **WHEN** a quick run completes
- **THEN** the result's economics object exposes `trade_count`, `hit_rate`, `profit_factor`, and the cost/funding share scalars
- **AND** it exposes by-symbol, by-direction, and by-exit-reason slices

#### Scenario: In-process scalars equal the on-disk economic_metrics
- **WHEN** the same completed run also writes `summary.json`
- **THEN** the result's economics summary scalars equal the `economic_metrics` payload in `summary.json` for that run

### Requirement: The economics accessor is independent of artifact profile

The in-process economics SHALL populate on every completed run regardless of
`artifact_profile` — including `summary` — and reading them MUST NOT require writing any
artifact. The per-trade ledger and the slices MUST be present even under profiles that do not
write per-trade diagnostics to disk.

#### Scenario: Summary profile still yields full economics
- **WHEN** a quick run completes with `artifact_profile = "summary"`
- **THEN** `RunResult` carries the full per-trade ledger and the summary scalars/slices
- **AND** they are identical to those produced under the `diagnostic` and `full` profiles for the same inputs

#### Scenario: Economics do not depend on artifact writes
- **WHEN** the economics object is read from a completed `RunResult`
- **THEN** its contents are derived from the in-memory engine result, not from any file under `result_dir`

### Requirement: The Train path stays trade-unit and dependency-light

This capability SHALL expose only the trade-level (point-to-point, per-trade) economics the
engine computes. It MUST NOT add a per-period / bar-level return series, a portfolio/NAV path,
or any significance statistic (PSR/DSR/PBO) to the quick-run surface. The quick-run code path
MUST NOT introduce a runtime dependency on `vectorbtpro`, `pandas`, `numpy`, or
`quant_strategies.evaluation`.

#### Scenario: No period series or significance statistics are added
- **WHEN** the quick-run economics object is read
- **THEN** it exposes per-trade records and undeflated summary scalars/slices only
- **AND** it exposes no per-period return series, no portfolio NAV path, and no PSR/DSR/PBO field

#### Scenario: Quick-run path imports no heavyweight backend dependency
- **WHEN** the quick-run path (`runner`, `engine`, `core`) is imported and exercised
- **THEN** it does not import `vectorbtpro`, `pandas`, `numpy`, or `quant_strategies.evaluation`

### Requirement: The economics accessor is additive and non-breaking

The new field and value objects SHALL be additive to `RunResult`. The new field MUST default
to `None` so existing programmatic consumers and the `succeeded` property are unaffected, and
the public `run_config` entry-point signature MUST be unchanged. A run that fails before a
completed engine evaluation MAY leave the field `None`; a completed run MUST populate it.

#### Scenario: Existing result contract preserved
- **WHEN** existing code constructs or reads a `RunResult` using only the prior fields
- **THEN** it continues to work unchanged
- **AND** `succeeded` is still `outcome.completed and outcome.failure_stage is None`

#### Scenario: Completed run populates economics; pre-engine failure leaves it None
- **WHEN** a quick run completes its engine evaluation
- **THEN** the economics field is populated
- **WHEN** a quick run fails before engine evaluation (for example `config_load` or `data_load`)
- **THEN** the economics field is `None`

### Requirement: Quick-run causality policy is configurable
The public quick-run config SHALL allow callers to select the causality replay
policy under `[output]` using `causality_check = "off" | "emitted" | "strict"`.
The default SHALL be `strict` when the field is omitted. The public `run_config`
Python signature SHALL remain unchanged.

#### Scenario: Existing config keeps strict replay
- **WHEN** a quick-run config omits `output.causality_check`
- **THEN** `run_config` runs strict hidden-lookahead replay
- **AND** existing strict evidence semantics are preserved

#### Scenario: Emitted replay mode is selected from config
- **WHEN** a quick-run config sets `output.causality_check = "emitted"`
- **THEN** `run_config` verifies deterministic full replay and emitted-decision replay
- **AND** it does not require strict no-emission replay to complete the run

#### Scenario: Replay can be explicitly disabled for profiling
- **WHEN** a quick-run config sets `output.causality_check = "off"`
- **THEN** `run_config` skips hidden-lookahead replay
- **AND** the result and artifacts mark causality replay as unverified

#### Scenario: Invalid causality mode is rejected
- **WHEN** a quick-run config sets `output.causality_check` to an unsupported value
- **THEN** config loading fails with a clear validation error before strategy execution

### Requirement: Quick-run strict replay can be bounded
The public quick-run config SHALL support an optional
`output.strict_probe_limit` for strict replay. When strict replay is selected and
the derived strict probe count exceeds the limit, the runner SHALL record strict
suppression evidence as capped or incomplete unless every required strict probe
actually ran.

#### Scenario: Strict probe limit caps evidence
- **WHEN** `output.causality_check = "strict"` and the strict boundary count exceeds `output.strict_probe_limit`
- **THEN** the run does not report strict suppression replay as fully verified
- **AND** the result and artifacts record that strict replay was capped or incomplete

#### Scenario: Strict probe limit does not affect emitted mode
- **WHEN** `output.causality_check = "emitted"` and `output.strict_probe_limit` is present
- **THEN** the runner ignores the strict probe limit for replay execution
- **AND** emitted replay evidence is determined only by deterministic and emitted-decision replay

#### Scenario: Invalid strict probe limit is rejected
- **WHEN** a quick-run config sets `output.strict_probe_limit` to an invalid value
- **THEN** config loading fails with a clear validation error before strategy execution

### Requirement: Quick-run causality evidence is reported by replay dimension
The public quick-run result and runner artifacts SHALL report deterministic
replay, emitted-decision replay, and strict suppression replay as separate
evidence dimensions. Summary compatibility fields MAY remain, but they MUST NOT
mark strict suppression replay as verified unless strict no-emission replay
completed without skipped or capped required probes.

#### Scenario: Emitted-only evidence is distinguishable
- **WHEN** a quick run completes with `output.causality_check = "emitted"`
- **THEN** `RunResult.evidence.causality` reports deterministic replay verified
- **AND** it reports emitted-decision replay verified
- **AND** it reports strict suppression replay not verified

#### Scenario: Strict evidence is distinguishable
- **WHEN** a quick run completes strict replay without skipped or capped required probes
- **THEN** `RunResult.evidence.causality` reports deterministic replay verified
- **AND** it reports emitted-decision replay verified
- **AND** it reports strict suppression replay verified

#### Scenario: Artifact payloads preserve evidence dimensions
- **WHEN** a quick run writes `summary.json`, `data_manifest.json`, or diagnostic artifacts
- **THEN** those artifacts expose the selected causality policy and the replay evidence dimensions
- **AND** emitted-only, off, capped, and complete-strict runs are distinguishable from artifacts alone

### Requirement: Quick-run engine evaluation can complete under emitted replay
The runner SHALL continue to request building and engine evaluation when
`output.causality_check = "emitted"` and deterministic plus emitted replay pass,
without requiring strict suppression replay. The resulting economics SHALL
remain Train quick-run evidence and SHALL NOT imply paper, live, promotion, or
strict audit eligibility.

#### Scenario: Emitted replay allows Train quick-run economics
- **WHEN** emitted replay passes for a valid quick-run config
- **THEN** `run_config` can complete engine evaluation and populate typed quick-run economics
- **AND** the result records strict suppression replay as not verified

#### Scenario: Emitted replay failure still blocks engine evaluation
- **WHEN** `output.causality_check = "emitted"` and emitted replay fails
- **THEN** `run_config` fails at the causality stage before request building or engine evaluation

#### Scenario: Replay disabled evidence is not promoted
- **WHEN** `output.causality_check = "off"` and engine evaluation completes
- **THEN** the result and artifacts include causality-unverified warnings
- **AND** promotion or eligibility fields remain false

### Requirement: Quick-run supports an execution buffer separate from the decision window
The public quick-run config SHALL allow callers to provide an execution/load
window that covers the existing decision window. The existing `data.start` and
`data.end` fields SHALL remain the decision window used for strategy visibility,
causality replay, and Train scoring. When execution-buffer fields are omitted,
quick-run behavior SHALL remain unchanged.

#### Scenario: Existing config keeps single-window behavior
- **WHEN** a quick-run config omits execution-buffer fields
- **THEN** the runner loads the same window it uses for strategy generation and engine execution

#### Scenario: Load window can extend past decision end
- **WHEN** a quick-run config sets `data.load_end` later than `data.end`
- **THEN** the runner may use rows through `load_end` for engine fill and exit coverage
- **AND** `data.end` remains the final strategy-visible decision-window date

#### Scenario: Invalid load window is rejected
- **WHEN** a quick-run config sets a load window that does not cover `data.start` through `data.end`
- **THEN** config loading fails before strategy execution

### Requirement: Strategy generation and causality replay use only decision-window rows
The runner SHALL pass only decision-window rows to quick-run strategy generation,
deterministic replay, emitted replay, and strict replay. Execution-buffer rows
SHALL NOT be visible to strategy code or causality replay.

#### Scenario: Strategy cannot see post-window buffer rows
- **WHEN** a quick run loads rows after `data.end` through `data.load_end`
- **THEN** `generate_decisions` receives no post-window buffer rows
- **AND** hidden-lookahead replay derives visible prefixes only from decision-window rows

#### Scenario: Buffer rows cannot repair strategy causality
- **WHEN** a strategy attempts to emit a decision that depends on rows after `data.end`
- **THEN** emitted replay fails rather than treating execution-buffer rows as strategy-visible evidence

### Requirement: Engine execution can use buffer rows for decision-window exits
Quick-run engine request construction SHALL use execution/load rows for fill and
exit coverage while evaluating only decisions eligible for the decision window.
Entries near the end of the decision window MAY resolve exits using buffer rows.

#### Scenario: Late decision exits inside buffer
- **WHEN** a decision-window decision requires exit bars after `data.end`
- **AND** those bars are present through `data.load_end`
- **THEN** request building succeeds and engine evaluation can complete

#### Scenario: Missing buffer still fails loudly
- **WHEN** a decision-window decision requires exit bars after the loaded execution window
- **THEN** request building fails with the existing fillability error

### Requirement: Quick-run economics exclude buffer-only entries
Quick-run economics SHALL report trades for decisions whose `decision_time` is
inside the decision window. Execution-buffer rows SHALL support fills and exits
only; they SHALL NOT introduce scored buffer-only entries.

#### Scenario: Decision-window trade is scored
- **WHEN** a decision has `decision_time` inside `data.start` through `data.end`
- **THEN** its completed engine trade can appear in `RunResult.economics`

#### Scenario: Buffer-only decision is excluded
- **WHEN** a decision has `decision_time` after the decision window
- **THEN** quick-run excludes it from engine evaluation and economics

### Requirement: Quick-run artifacts distinguish decision and execution rows
Quick-run artifacts SHALL distinguish strategy-visible decision-window rows from
execution/load rows when the load window differs from the decision window.
Artifacts MUST NOT silently relabel execution-buffer rows as strategy input
evidence.

#### Scenario: Manifest records both row windows
- **WHEN** a quick run uses an execution buffer
- **THEN** artifacts expose the decision window and the execution/load window
- **AND** row counts or hashes are labeled so strategy-visible evidence is distinguishable from execution support

#### Scenario: Replayability semantics remain honest
- **WHEN** a quick run writes replayable strategy-input artifacts
- **THEN** those artifacts correspond to strategy-visible rows, not execution-buffer rows

### Requirement: Quick run supports focused causality for Train iteration
The public quick-run surface SHALL support a focused causality policy for
Train/autoresearch iteration. When focused causality is selected, quick run SHALL
run or reuse focused source-hash certification before engine scoring and SHALL
not require emitted replay or strict replay over the scoring window to complete
the quick run.

#### Scenario: Focused causality allows quick-run scoring
- **WHEN** a quick-run config selects focused causality
- **AND** the focused causality gate passes or has a current passed cache record
- **THEN** quick run can build the engine request, evaluate the request, and populate quick-run economics
- **AND** the result records focused causality evidence

#### Scenario: Focused causality failure blocks quick-run scoring
- **WHEN** a quick-run config selects focused causality
- **AND** the focused causality gate fails or times out
- **THEN** quick run fails before engine scoring
- **AND** the result records the focused causality rejection status

#### Scenario: Focused causality does not require emitted or strict scoring-window replay
- **WHEN** a quick-run config selects focused causality
- **THEN** the runner is not required to run emitted replay or strict replay over the full scoring window
- **AND** artifacts distinguish focused hygiene evidence from emitted or strict replay evidence

### Requirement: Quick-run focused causality preserves existing low-level replay modes
Existing explicit quick-run causality modes SHALL remain supported for advanced
or audit callers. Adding focused causality SHALL NOT remove support for explicit
`off`, emitted replay, strict replay, or strict probe limits. Focused causality
SHALL be the recommended Train/autoresearch policy, while validation and
evaluation remain the robust survivor gates.

#### Scenario: Existing explicit low-level modes remain valid
- **WHEN** an existing quick-run config explicitly selects an existing low-level causality mode
- **THEN** the runner preserves the existing behavior for that mode

#### Scenario: Autoresearch documentation prefers focused causality
- **WHEN** consumer documentation describes Train/autoresearch quick-run iteration
- **THEN** it presents focused causality as the research-loop policy
- **AND** it directs survivor/audit checks to validation or evaluation instead of requiring the strategy LLM to select emitted or strict replay

### Requirement: Quick-run artifacts report focused causality status
When focused causality is selected, quick-run result objects and artifacts SHALL
record focused causality status, source hash, focused profile version, cache
usage, timeout budget, probe counts, focused cache-key inputs, and whether the
run was allowed to score. These fields SHALL be sufficient for a downstream
consumer to reject unscored or rejected variants without reading low-level replay
internals. Focused quick-run artifacts SHALL NOT mark full emitted replay or
strict replay as verified merely because focused sampled probes passed.

#### Scenario: Focused pass appears in summary
- **WHEN** focused causality passes and quick run completes scoring
- **THEN** `summary.json` records focused causality status `passed`
- **AND** it records that scoring was allowed
- **AND** low-level emitted and strict replay verification fields remain false unless those full replay modes actually ran

#### Scenario: Focused reject appears in summary
- **WHEN** focused causality fails or times out before scoring
- **THEN** `summary.json` records the focused causality rejection status
- **AND** it records that scoring was not allowed

#### Scenario: Programmatic result carries focused evidence
- **WHEN** a programmatic caller receives a `RunResult` from a focused quick run
- **THEN** the result carries focused causality evidence without requiring artifact scraping
