# Phase 22 Design: Default Runner Artifacts To Summary

Date: 2026-05-28
Mode: Builder
Source review: `review-claude.md`

## Problem

`review-claude.md` flags that shipped run configs omit `artifact_profile`, so
they inherit the heaviest default. That makes ordinary search and smoke runs
write full replay artifacts unless each config opts out. After Phase 21, full
profile no longer writes duplicate CSV rows, but it still writes input-row
JSONL, decision records, engine request JSON, and evidence JSON. Those artifacts
are valuable for retained/debug runs, not for every candidate sweep.

## Assignment

Change the runner default artifact profile from `full` to `summary`, while
preserving explicit `artifact_profile = "full"` for retained or debug runs that
need audit replay artifacts.

## Auto-Decisions

Season cannot answer questions during this run, so these decisions are fixed for
Phase 22:

- Default `RunnerOutputConfig.artifact_profile` to `summary`.
- Do not edit shipped `runs/*.toml`; their omitted profile should now inherit
  the lighter default.
- Keep explicit `artifact_profile = "full"` behavior unchanged.
- Keep test helpers that exercise full-profile artifacts explicitly full where
  they are testing full behavior.
- Update docs to state that summary is the default.

## Scope

- Add/update config tests for default summary and explicit full.
- Change the runner config default.
- Update README and quant-autoresearch consumer docs.
- Update progress tracking.

## Not In Scope

- Removing full-profile artifacts.
- Changing summary-profile artifact content.
- Changing validation backend artifacts.
- Performance benchmarking.

## Success Criteria

- Configs that omit `artifact_profile` load with `output.artifact_profile ==
  "summary"`.
- Explicit `artifact_profile = "full"` still loads as full and preserves
  full-profile runner behavior.
- All committed `runs/*.toml` parse and inherit summary unless they explicitly
  opt into full.
- Focused config/runner/docs tests, full suite, diff check, compile check, and
  code review pass.
