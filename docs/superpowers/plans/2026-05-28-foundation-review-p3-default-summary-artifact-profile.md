# Default Summary Artifact Profile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make summary artifacts the runner default so candidate sweeps avoid
full replay artifacts unless a config explicitly opts in.

**Architecture:** `RunnerOutputConfig` owns the default. Runner execution already
branches on the resolved profile, so changing the Pydantic field default is the
behavioral switch. Tests that need full artifacts should request full explicitly.

**Tech Stack:** Python 3.12, pytest via `conda run -n quant`.

---

## File Structure

- Modify `tests/test_runner_config.py`: default summary and explicit full tests.
- Modify `src/quant_strategies/runner/config.py`: default profile to `summary`.
- Modify `README.md` and `docs/quant-autoresearch-consumer.md`: state default.
- Modify `progress.md`: record Phase 22 status and verification.

## Implementation Steps

- [x] **Step 1: Update config expectations first**

  Change `test_valid_run_config_is_accepted()` to expect summary by default and
  add/keep a test proving explicit `artifact_profile = "full"` is accepted.
  Add a committed-runs check that configs omitting `artifact_profile` inherit
  summary.

  Verify it fails before implementation:

  ```bash
  conda run -n quant pytest tests/test_runner_config.py::test_valid_run_config_is_accepted tests/test_runner_config.py::test_committed_run_configs_default_to_summary_profile -q
  ```

- [x] **Step 2: Flip the default and update docs**

  Change `RunnerOutputConfig.artifact_profile` to `"summary"` and update docs:

  - README runner artifact section says summary is default.
  - quant-autoresearch consumer docs say summary is default for omitted profile.

  Verify:

  ```bash
  conda run -n quant pytest tests/test_runner_config.py tests/test_readme_contract.py -q
  ```

- [x] **Step 3: Full verification and review**

  Run:

  ```bash
  conda run -n quant pytest tests/test_runner_api_cli.py tests/test_runner_artifact_profiles.py tests/test_phase5_performance.py tests/test_runner_config.py tests/test_readme_contract.py -q
  conda run -n quant pytest -q
  git diff --check
  conda run -n quant python -m compileall -q src tests
  ```

  Request code review before commit. Fix valid findings and rerun focused checks
  plus any broader checks affected by the fix.

## GSTACK REVIEW REPORT

### Scope Challenge

The full profile remains necessary for audit replay. This phase changes the
default for omitted profile only; it does not weaken explicit full-profile
contracts.

### Architecture Review

Profile resolution remains centralized:

```text
TOML output.artifact_profile omitted -> RunnerOutputConfig default -> run_config branches
explicit "full"                       -> full replay artifacts
explicit "summary"                    -> compact search artifacts
```

### Edge Cases

- Test helpers that default to explicit full are intentionally unchanged when
  they test full artifacts.
- Validation `to_run_config()` will inherit summary for its internal runner
  config object; validation does not use runner artifact writing.
- Existing result artifacts are historical and not rewritten.

### Test Review

Tests cover config parsing defaults, explicit full opt-in, committed run config
parsing, runner full/summary artifact behavior, phase performance expectations,
docs contract, full suite, diff check, and compile check.
