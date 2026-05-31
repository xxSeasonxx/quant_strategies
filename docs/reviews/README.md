# Review Archives

Use this directory for dated review artifacts after an active review is
published or archived.

Root-level `review-*.md` files are working notes only. Commit review artifacts
here with a dated name:

```text
YYYY-MM-DD-<topic>-<reviewer>.md
```

Each archived review should state the reviewed commit or branch, the scope, and
the resulting disposition: accepted, rejected as false positive, deferred, or
implemented in a named phase.

Current disposition note:

```text
2026-05-30-foundation-finalization-plan.md
```

Future foundation reviews should be disposition-aware delta reviews by default:
read the current disposition note first, then classify findings as new,
regression, fixed, accepted debt, deferred, false positive, or superseded. Run a
fresh blind review only when Season explicitly asks for one.
