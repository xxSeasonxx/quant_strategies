# AGENTS.md

Canonical agent contract for `quant_strategies`.

## Role

Maintain a flat library of strategy files and focused tests.

## Rules

- Keep each strategy as one Python file unless Season explicitly approves a
  folder.
- Put thesis, observables, rule, and falsifier in the strategy module docstring.
- Keep strategy code pure: no engine calls, no autonomous loop, no artifact
  writing.
- Write or update tests before moving a strategy from `untested/` to `tested/`.
- Use `conda run -n quant <command>` for Python commands.
