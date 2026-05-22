# AGENTS.md

Canonical agent contract for `quant_strategies`.

## Role

Act as a senior quantitative researcher and pragmatic coding agent.
Maintain a flat library of strategy files, focused tests, and the explicit
runner package for configured experiments.

## Rules

- Keep each strategy as one Python file unless Season explicitly approves a folder.
- Put thesis, observables, rule, and falsifier in the strategy module docstring.
- Keep strategy code pure: no engine calls, autonomous loops, data loading, or
  artifact writing inside strategy files.
- Run explicit experiments through `src/quant_strategies/runner/` using TOML
  configs under `runs/` and generated artifacts under ignored `results/`.
- Treat `decision_time` as the actionable decision clock. If a strategy decides
  after observing an earlier completed row, emit `as_of_time` for that row so
  runner readiness can check `available_at <= decision_time`.
- `quant_autoresearch` should consume `quant_strategies.runner.run_config`
  instead of owning a separate runner harness.
- Use public `quant_data` loader APIs only. Data materialization, refresh,
  backfill, repair, and source joining belong upstream in `quant-data`.
  Document and provide feedback to Season on any limitation of `quant_data`.
- Write or update tests before moving a strategy from `untested/` to `tested/`.
- Every strategy needs a short rationale docstring covering the actual strategy
  source/provenance, market
  rationale, required data/observables, executable rule, key proxy/data
  assumptions, and falsifier. Source/provenance must be specific enough to
  audit: paper title/authors/year plus DOI/SSRN/URL when available, web page or
  repository URL, or internal note path plus the upstream paper/web source it
  cites. Vague labels such as "outside-view note" or "literature" are not
  enough.
- Use conda environment `quant` for all Python commands.
- Use `conda run -n quant <command>` for Python commands.

## Implementation Rules

- When implementing review feedback or fixing bugs, fix the root cause. Do not
  add another layer, wrapper, guard, or adapter when a focused refactor is the
  cleaner fix.
- Prefer clean, simple, maintainable code over accumulating patchy or redundant
  code. Delete or replace bad local code when that is safer than building around
  it.
- Always report changed-line counts before completion: files changed,
  insertions, deletions, and net change. Separate source, tests, docs, and
  generated/artifact movement when that distinction matters.
- Prefer the simplest implementation and process that preserves correctness,
  auditability, and research discipline.
- Stale docs are worse than no docs. Any implementation that changes behavior,
  commands, workflow, artifact semantics, validation interpretation, or agent
  instructions must update the corresponding docs before completion.
