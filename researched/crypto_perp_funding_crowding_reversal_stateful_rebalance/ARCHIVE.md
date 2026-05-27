# Research Handoff Archive

This package is a frozen upstream research handoff. It is not an active
validation package and it is not market, paper-trading, or live-trading
evidence.

The `families/*/variants/*` tree preserves candidate snapshots and smoke-screen
artifacts from upstream research. The validator does not special-case this
layout. To validate a candidate, copy the selected `strategy.py` and a matching
`validation.toml` into a normal candidate workspace and run validation on that
explicit TOML file.

Directories named `evidence/legacy_selection` are retained only to explain the
old selection path. They must not be treated as current contracts or promotion
evidence.
