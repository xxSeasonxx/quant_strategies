# quant_data Upstream Contract

This note states what `quant_strategies` expects from upstream `quant_data`.
It is an interface contract for this repository, not a setup guide for
`quant_data` internals.

Upstream owns the strategy contract: deterministic row ordering and the causal
`available_at` stamp are produced by `quant_data`, not reconstructed here.
`quant_strategies` consumes that contract and preserves the supplied row order;
it does not sort, de-duplicate, join, or repair rows locally. The upstream-owned
contract is documented in the `quant-data` consumer guide
(`docs/consumer/README.md`, `usage-guide.md`, `reference.md`); this note is the
downstream-consumer view of the same boundary.

## Responsibility Split

`quant_data` owns the data product:

- data acquisition, refresh, repair, backfill, source joining, and caches;
- vendor/source truth, adjustment policy, survivorship policy, and data-quality
  repair;
- public loader behavior and supported loader arguments;
- deterministic row ordering for supplied rows;
- the causal `available_at` stamp on every row, derived from a single upstream
  availability policy;
- source-specific details such as funding timestamps, quote fields, corporate
  actions, missing-data semantics, and dataset coverage.

`quant_strategies` owns research evidence:

- calling only public `quant_data` loader APIs;
- preserving the supplied row order for strategy input, normalized hashes,
  execution inputs, and audit artifacts;
- row-contract validation and structured feedback to upstream;
- strategy execution, causality checks, decision validation, fills, costs,
  evaluation, and artifacts;
- refusing to patch, join, repair, backfill, or silently reinterpret upstream
  data locally.

## Loader Shape

The most helpful upstream setup is deterministic and explicit:

- the same loader call, dataset, symbols, and date window returns the same rows
  in the same order;
- multi-symbol loaders have a documented stable order, preferably timestamp
  first with a deterministic symbol/source tie-breaker;
- rows are mapping-like records with stable field names;
- timestamps are timezone-aware datetimes or ISO strings with timezone offsets;
- `available_at` is timezone-aware and means the earliest time the row values
  are valid for causal research consumption;
- missing or partial data is represented by loader errors or explicit row
  fields, not silent synthetic fills;
- duplicate `(symbol, timestamp)` rows are absent unless the loader contract
  explicitly defines how they are resolved.

`quant_strategies` selects the loader by data kind and always loads strictly:

- `bars`, single symbol → `quant_data.contract_loaders.load_strategy_bars`;
- `bars`, multiple symbols → `quant_data.contract_loaders.load_strategy_universe_bars`,
  which returns one frame ordered `(timestamp, symbol)` and raises when a
  requested symbol is missing;
- `crypto_perp_funding` → `quant_data.loader.load_crypto_perp_bars_with_funding`
  (precomputed bars+funding join, already carrying `available_at`);
- `forex_with_quotes` → `quant_data.loader.load_fx_bars_with_quotes`
  (precomputed bars+quotes join, already carrying `available_at`).

All four are called with strict loading: the window is validated upstream, an
empty result raises, and duplicate keys are rejected. There is no `data.strict`
toggle and no relaxed load path.

`quant_strategies` validates and reports row-contract violations, but it does
not sort, de-duplicate, infer, join, or repair rows at the data boundary. It
preserves the order each loader returns.
Execution internals may build per-symbol time indexes for fills; that is not a
replacement for the upstream row-order contract.

## Required Fields By Data Kind

Bar data should include:

- `symbol`
- `timestamp`
- `available_at`
- `open`
- `high`
- `low`
- `close`

`available_at` is an unconditional hard requirement on every row in every run
surface (quick run, validation, and evaluation). A missing or invalid
`available_at` is an error, never a tolerated warning, and the run fails at the
row-contract gate. Causal replay gates valid rows strictly on
`available_at <= decision_time`; because a missing or invalid `available_at` fails
the row contract first, a provenance defect surfaces as a data-quality failure,
never as a hidden-lookahead verdict.

FX quote workflows should also include:

- `bid`
- `ask`
- `mid`

with `bid <= mid <= ask` when all three are present.

Crypto perpetual funding workflows should also include:

- `funding_timestamp`
- `funding_rate`
- `has_funding_event`

Funding rows should make event semantics explicit. A row with
`has_funding_event = true` must have a valid funding timestamp and finite funding
rate. Duplicate funding timestamps for the same symbol should agree exactly
within the upstream source policy or be repaired before reaching this repo.

## Feedback To Upstream

`quant_strategies` row-contract feedback is meant to help `quant_data` tighten
or repair loader contracts. Common feedback includes:

- missing required fields;
- invalid, naive, or non-deterministic timestamps;
- missing or invalid `available_at`;
- invalid numeric fields;
- invalid OHLC ordering;
- duplicate symbol/timestamp keys;
- missing or invalid quote fields;
- invalid funding fields;
- malformed funding events or conflicting funding rates.

This feedback is not a request for local compatibility shims. When a row shape
is wrong, the preferred fix is upstream repair or an explicit upstream contract
change, followed by rerunning affected evidence.

## Useful Contract Smoke

A small upstream smoke test is enough to protect this boundary:

- one bars loader call for a known symbol/window;
- one multi-symbol loader call that proves documented stable ordering;
- one FX quote loader call when quote fills are in use;
- one crypto perpetual funding loader call when funding evidence is in use;
- assertions for required fields, timezone-aware `timestamp` and `available_at`,
  duplicate keys, numeric validity, and row order.

The smoke should not materialize data, repair data, or duplicate `quant_data`
test coverage inside this repository. It should only prove that the installed
upstream contract is the one `quant_strategies` is consuming.
