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

Current disposition anchor:

```text
../../FOUNDATION_LOCK.md
```

Future foundation reviews should be disposition-aware delta reviews by default:
read the current disposition anchor first, then classify findings as `new`,
`regression`, `fixed`, `accepted_debt`, `deferred_until_trigger`,
`false_positive`, or `superseded`. Run a fresh broad blind foundation review only
when Season explicitly asks for one.
