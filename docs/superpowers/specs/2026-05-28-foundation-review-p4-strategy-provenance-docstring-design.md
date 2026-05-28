# Phase 19 Design: Enforce Strategy Provenance Anchors

Date: 2026-05-28
Mode: Builder
Source review: `review-claude.md`

## Problem

`review-claude.md` notes that strategy docstring tests enforce the presence of a
`Source / provenance:` heading but do not require an auditable source anchor.
The repository instructions require provenance to be specific enough to audit:
paper title/authors/year plus DOI/SSRN/URL when available, web page or
repository URL, or an `internal_note:` path. A vague phrase under the heading can
currently pass.

## Assignment

Strengthen the strategy docstring contract so the `Source / provenance:` section
must include at least one audit anchor: `DOI`, `SSRN`, an HTTP(S) URL, or an
`internal_note:` prefix.

## Auto-Decisions

Season cannot answer questions during this run, so these decisions are fixed for
Phase 19:

- Enforce provenance anchors in the existing strategy docstring test module.
- Treat `DOI`, `SSRN`, `http://`, `https://`, and `internal_note:` as acceptable
  audit anchors.
- Keep the check syntactic; do not try to verify external URLs or DOI validity.
- Update the example smoke strategy to use `internal_note:` because it is an
  internal deterministic fixture, not an external alpha source.
- Do not rewrite researched strategy rationale blocks that already include DOI,
  SSRN, or URL anchors.

## Scope

- Add provenance-section extraction and audit-anchor enforcement to
  `tests/test_strategy_docstrings.py`.
- Update `examples/strategies/simple_momentum.py` provenance text.
- Update progress tracking.

## Not In Scope

- Candidate-time strategy purity enforcement.
- URL reachability checks.
- Rewriting all strategy docstrings.
- Moving strategies between `untested/`, `researched/`, and `tested/`.

## Success Criteria

- A strategy docstring with only a vague `Source / provenance:` block fails the
  test.
- Current committed strategy modules pass with DOI/SSRN/URL/internal-note
  anchors.
- Existing heading, flat-layout, import, and side-effect purity tests still pass.
- Full suite, diff check, compile check, and code review pass.
