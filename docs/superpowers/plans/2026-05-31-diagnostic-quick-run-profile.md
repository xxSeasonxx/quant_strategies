# Diagnostic Quick Run Profile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `diagnostic` as the default quick-run artifact profile with bounded diagnostics and configurable top win/loss samples.

**Architecture:** Make `diagnostic` a root runner contract, not a transitional layer. Keep artifact verbosity separate from pass/fail logic: `summary` stays compact, `diagnostic` writes bounded `diagnostics.json`, and `full` remains audit/replayable.

**Tech Stack:** Python 3.12, Pydantic v2, pytest, TOML configs, `conda run -n quant`.

---

## File Structure

- Modify `src/quant_strategies/runner/config.py`: add `diagnostic` profile, default it, and validate `diagnostic_sample_trades`.
- Modify `src/quant_strategies/evidence_semantics.py`: map `diagnostic` to `search_only`.
- Create `src/quant_strategies/runner/diagnostics.py`: owns `diagnostics.json` payload shaping.
- Modify `src/quant_strategies/runner/engine_runner.py`: separate full evidence from bounded trade diagnostics.
- Modify `src/quant_strategies/runner/__init__.py`: write `diagnostics.json` for diagnostic runs only.
- Modify tests in `tests/test_runner_config.py`, `tests/test_runner_artifact_profiles.py`, `tests/test_runner_api_cli.py`.
- Update `README.md`, `docs/runner.md`, `docs/research-process.md`, `docs/quant-autoresearch-consumer.md`, and `runs/*.toml`.

## Tasks

- [x] Add the root config contract for `diagnostic` and `diagnostic_sample_trades`.
- [x] Add the diagnostic payload builder and focused unit coverage.
- [x] Integrate diagnostics into runner completion artifacts.
- [x] Update docs, committed run configs, and verification checks.

## Verification

- `conda run -n quant pytest tests/test_runner_config.py tests/test_runner_artifact_profiles.py tests/test_runner_api_cli.py -q`
- `conda run -n quant pytest -q`
- `rg -n "default .*summary|summary.*default|artifact_profile = \"summary\"" README.md docs/runner.md docs/research-process.md docs/quant-autoresearch-consumer.md runs src tests`
- `rg -n "compat|legacy|alias|deprecated|backward|backwards" src/quant_strategies tests README.md docs/runner.md docs/research-process.md docs/quant-autoresearch-consumer.md`
