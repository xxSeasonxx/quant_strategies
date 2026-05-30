# Research Handoff Archive

This package is a frozen upstream research handoff. It is not an active
validation package and it is not market, paper-trading, or live-trading
evidence.

The `families/*/variants/*` tree preserves candidate snapshots and smoke-screen
artifacts from upstream research. The validator does not special-case this
layout. To validate a candidate, copy the selected `strategy.py` and a matching
`validation.toml` into a normal candidate workspace and run validation on that
explicit TOML file.

Old selection evidence has been removed from this package. Use only the compact
`new_15_locked_recent_2026` rerun evidence for archive context, and rerun a
candidate from its tracked config before drawing any new conclusion.
