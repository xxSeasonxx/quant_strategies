# Phase 7 Plan: Deterministic JSON Artifact Encoding

Date: 2026-05-28
Design: `docs/superpowers/specs/2026-05-28-foundation-review-p1-deterministic-json-design.md`

## Goal

Close the PRD determinism finding by removing pydantic-default JSONL artifact
encoding from runner and validation decision records.

## Implementation Steps

- [x] **Step 1: Canonical runner decision records**

  Replace `model_dump_json()` in `runner.artifacts.write_decision_records` with
  sorted compact `json.dumps` over `model_dump(mode="json")`.

  Verify: runner artifact test inspects raw `decision_records.jsonl`.

- [x] **Step 2: Canonical validation decision records**

  Replace validation base and per-scenario decision-record writes with the same
  canonical line encoding.

  Verify: validation runner test inspects raw base and scenario decision-record
  artifacts.

- [ ] **Step 3: Docs/progress, verification, review**

  Update README stale Phase 6 artifact wording and `progress.md`; run focused
  tests, full suite, diff checks, compile checks, and subagent code review before
  commit.

## Verification Commands

```bash
rg "model_dump_json\\(" src
conda run -n quant pytest tests/test_runner_api_cli.py tests/test_validation_runner.py tests/test_readme_contract.py -q
conda run -n quant pytest -q
git diff --check
conda run -n quant python -m compileall -q src tests
```

## GSTACK REVIEW REPORT

### Scope Challenge

The broader determinism topic includes git working-tree hashing and row hash
reuse. This phase targets the concrete artifact encoder bug because it is a
silent cross-version hash risk and is directly named in the review.

### Architecture Review

Target encoding:

```text
StrategyDecision
        |
        v
model_dump(mode="json")
        |
        v
json.dumps(sort_keys=True, separators=(",", ":"), allow_nan=False)
        |
        v
*.jsonl
```

Runner and validation keep separate artifact modules, but use equivalent
canonical encoding.

### Code Quality Review

- Keep the helper small and local to artifact modules.
- Avoid compatibility paths for old JSONL key order.
- Preserve existing newline behavior.
- Test raw artifact bytes, not only parsed dictionaries.

### Test Review

Tests must prove:

- raw JSONL starts with alphabetically sorted keys;
- compact separators are used;
- validation scenario decision records use the same encoding;
- no production `model_dump_json()` artifact writes remain.
