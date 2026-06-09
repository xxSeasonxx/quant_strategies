# AGENTS.md

Canonical agent contract for `quant_strategies`.

## Role

Act as a senior quantitative researcher and pragmatic coding agent.
Maintain candidate folders with pure strategy files, local configs, focused
tests, and the explicit runner package for configured experiments.

## Rules

- Keep each candidate in one folder under `candidates/<candidate_id>/` with one
  pure `strategy.py` file unless Season explicitly approves a different shape.
- Put thesis, observables, rule, and falsifier in the strategy module docstring.
- Keep strategy code pure: no engine calls, autonomous loops, data loading, or
artifact writing inside strategy files. Purity is checked by a best-effort
static AST lint (`decisions/purity.py`), not a sandbox — it bans common
data-loading/side-effect calls (file reads/writes, dynamic imports, network,
clocks/RNG) but is not exhaustive; the contract plus review are the real
guarantee.
- Run explicit experiments through `src/quant_strategies/runner/` using
  candidate-local TOML configs such as `candidates/<candidate_id>/run.toml`;
  generated artifacts belong under ignored `results/`, not inside candidate
  folders.
- `quant_autoresearch` should consume the public `runner.run_config`,
`validation.run_validation`, and `evaluation.run_evaluation` APIs instead of
owning separate execution, validation, or evaluation harnesses.
- Use public `quant_data` loader APIs only. Data materialization, refresh,  
backfill, repair, and source joining belong upstream in `quant-data`.  
Document and provide feedback to Season on any limitation of `quant_data`.
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
- Use repo-owned Make targets for formatting and lint cleanup (for example,
`make fix` or the nearest available format/lint target); do not rely on LLM
agents to hand-format code.
- Always report changed-line counts before completion: files changed,
insertions, deletions, and net change. Separate source, tests, docs, and
generated/artifact movement when that distinction matters.
- Prefer the simplest implementation and process that preserves correctness,
auditability, and research discipline.
- Stale docs are worse than no docs. Any implementation that changes behavior,
commands, workflow, artifact semantics, validation interpretation, or agent
instructions must update the corresponding docs before completion.
