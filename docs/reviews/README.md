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

Historical review disposition:

| Review | Current disposition |
| --- | --- |
| `2026-06-02-foundation-codex.md` | Historical broad review; superseded by `../../FOUNDATION_LOCK.md` and current tests/docs. |
| `2026-06-02-foundation-codex-p3.md` | Historical P3 follow-up review; superseded by `../../FOUNDATION_LOCK.md` and current tests/docs. |
| `2026-06-03-foundation-claude-independent.md` | Historical independent review; superseded by `../../FOUNDATION_LOCK.md` and current tests/docs. |
| `2026-06-03-foundation-claude-disposition.md` | Historical root-level Claude working review copy; accepted findings are dispositioned and superseded by `../../FOUNDATION_LOCK.md` and current tests/docs. |
| `2026-06-03-foundation-codex-delta.md` | Historical Codex delta review; superseded by `../../FOUNDATION_LOCK.md` and current tests/docs. |
| `2026-06-03-foundation-codex-disposition.md` | Historical root-level Codex working review copy; accepted findings are dispositioned and superseded by `../../FOUNDATION_LOCK.md` and current tests/docs. |
| `2026-06-04-foundation-claude.md` | Historical Claude foundation working review; cleanup findings are dispositioned and superseded by `../../FOUNDATION_LOCK.md` and current tests/docs. |
| `2026-06-04-foundation-codex.md` | Historical Codex foundation working review; cleanup findings are dispositioned and superseded by `../../FOUNDATION_LOCK.md` and current tests/docs. |
| `2026-06-04-foundation-codex-quant.md` | Historical Codex quant-researcher-lens foundation working review; its row-order finding is implemented via the contract-loader migration (`../../openspec/specs/data-boundary/spec.md`) and superseded by `../../FOUNDATION_LOCK.md` and current tests/docs. |
| `2026-06-10-live-trade-feasibility-review.md` | **Retired (2026-06-11):** folded into `../../TODOS.md` (§2.3/§2.4 market-model follow-ons + §4/§5 residuals) and `../../FOUNDATION_LOCK.md`; no longer kept as a file — full text in git history. Accepted findings shipped via the `portfolio-book-spine` change and review No. 6/8/11/20; remaining work (No. 3 capacity, No. 7 frictions, No. 17 `researched/`) lives in `../../TODOS.md`. |

Future foundation reviews should be disposition-aware delta reviews by default:
read the current disposition anchor first, then classify findings as `new`,
`regression`, `fixed`, `accepted_debt`, `deferred_until_trigger`,
`false_positive`, or `superseded`. Run a fresh broad blind foundation review only
when Season explicitly asks for one.
