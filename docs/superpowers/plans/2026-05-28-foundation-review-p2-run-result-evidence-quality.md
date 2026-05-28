# RunResult Evidence Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add evidence-quality fields to the stable `RunResult` API so consumers can rank or reject runs without first parsing artifacts.

**Architecture:** `summary.json`, `data_manifest.json`, and `RunResult` will share one evidence-quality payload. A small helper converts that payload into `RunResult` fields, keeping success and failure paths consistent.

**Tech Stack:** Python 3.12 dataclasses, existing runner artifact payloads, pytest via `conda run -n quant`.

---

## File Structure

- Modify `src/quant_strategies/runner/__init__.py`: add `RunResult` fields and helper-based population.
- Modify `tests/test_runner_api_cli.py`: assert typed result fields mirror summary evidence quality.
- Modify `docs/quant-autoresearch-consumer.md`: list the newly typed result fields.
- Modify `progress.md`: record Phase 12 status and verification.

## Implementation Steps

- [x] **Step 1: Add RunResult API regression**

  Extend `assert_assessment()` or nearby tests to assert `RunResult` mirrors
  `summary.json` evidence-quality fields for successful and failed runs.

  Verify: focused test fails before implementation because `RunResult` lacks the
  fields.

- [x] **Step 2: Add RunResult fields and population helper**

  Add fields for `data_availability_status`, `availability_coverage`,
  `row_contract`, `causality_verified`, and `evidence_quality_warnings`. Add a
  helper that extracts those from an evidence-quality dict and use it in success
  and failure returns.

  Verify: focused runner API tests pass.

- [x] **Step 3: Update docs and progress**

  Update `docs/quant-autoresearch-consumer.md` so the stable Python surface
  includes the evidence-quality fields.

  Verify: `tests/test_readme_contract.py` and focused runner API tests pass.

- [x] **Step 4: Full verification and review**

  Run full suite, diff checks, compile checks, and code review before commit.

## Verification Commands

```bash
conda run -n quant pytest tests/test_runner_api_cli.py tests/test_runner_execution.py tests/test_readme_contract.py -q
conda run -n quant pytest -q
git diff --check
conda run -n quant python -m compileall -q src tests
```

## GSTACK REVIEW REPORT

### Scope Challenge

This phase intentionally avoids a larger `RunSummary` model. The immediate
contract gap is that current consumers get a typed object but must parse
artifacts to access the exact fields docs say they must consider.

### Architecture Review

Target flow:

```text
evidence_quality dict
        |
        +--> summary.json / data_manifest.json
        |
        +--> RunResult typed fields
```

### Edge Cases

- Config-load failure before a `RunConfig` exists: evidence fields stay unset or
  conservative.
- Decision-generation failure after rows load: evidence fields come from
  `StrategyExecutionError.evidence_quality`.
- Failures after causality/readiness/request/engine stages: evidence fields come
  from the already computed payload.
- Direct test instantiation of `RunResult`: new fields have defaults.

### Test Review

Tests must cover:

- successful run fields mirror summary;
- failure run fields mirror summary;
- direct CLI test `RunResult(...)` instantiation still works;
- docs mention the stable typed fields.
