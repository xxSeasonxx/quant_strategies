# Artifact Replayability Simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace runner artifact trust-tier vocabulary with the factual `replayable_from_artifacts` flag across the Python API, active artifacts, docs, and handoff notes.

**Architecture:** Keep `artifact_profile` as the user/config choice and derive replayability from it in one semantics helper. Runner API and artifact writers consume that helper; validation replayability fields remain separate and unchanged.

**Tech Stack:** Python 3.12, dataclasses, Pydantic semantics models, pytest, TOML runner configs, markdown docs. Run Python commands through `conda run -n quant`.

---

## File Structure

- Modify `src/quant_strategies/evidence_semantics.py`: replace trust-tier type/helper with one boolean replayability helper.
- Modify `src/quant_strategies/runner/__init__.py`: rename `RunResult.artifact_trust_tier` to `RunResult.replayable_from_artifacts` and populate it on success/failure.
- Modify `src/quant_strategies/runner/artifacts.py`: emit `replayable_from_artifacts` in `summary.json`, `data_manifest.json`, and `run_manifest.json`.
- Modify `src/quant_strategies/runner/artifact_profiles.py`: emit `replayable_from_artifacts` in `artifact_profile_summary.json`.
- Modify `src/quant_strategies/runner/diagnostics.py`: emit `replayable_from_artifacts` in `diagnostics.json`.
- Modify `tests/test_runner_artifact_profiles.py`: direct unit coverage for replayability helper plus summary/diagnostic payload key changes.
- Modify `tests/test_runner_api_cli.py`: API and end-to-end artifact assertions for summary, diagnostic, full, and deterministic runner artifacts.
- Modify `README.md`, `docs/runner.md`, `docs/research-process.md`, and `docs/quant-autoresearch-consumer.md`: replace old trust-tier wording with replayability wording.
- Modify `TODOS.md`: mark PR 2 complete and make PR 3 the next open item.

---

### Task 1: Add Replayability Helper

**Files:**
- Modify: `tests/test_runner_artifact_profiles.py`
- Modify: `src/quant_strategies/evidence_semantics.py`

- [ ] **Step 1: Write the failing helper tests**

In `tests/test_runner_artifact_profiles.py`, add this import near the existing imports:

```python
from quant_strategies.evidence_semantics import replayable_from_artifacts_for_profile
```

Then add these tests after `test_runner_artifacts_do_not_expose_legacy_row_summary_owner()`:

```python
def test_replayable_from_artifacts_for_profile_maps_profiles():
    assert replayable_from_artifacts_for_profile("summary") is False
    assert replayable_from_artifacts_for_profile("diagnostic") is False
    assert replayable_from_artifacts_for_profile("full") is True


def test_replayable_from_artifacts_for_profile_rejects_unknown_profile():
    with pytest.raises(ValueError, match="unknown artifact profile: compact"):
        replayable_from_artifacts_for_profile("compact")
```

- [ ] **Step 2: Run helper tests to verify they fail**

Run:

```bash
conda run -n quant pytest tests/test_runner_artifact_profiles.py::test_replayable_from_artifacts_for_profile_maps_profiles tests/test_runner_artifact_profiles.py::test_replayable_from_artifacts_for_profile_rejects_unknown_profile -q
```

Expected: FAIL during import with `ImportError` because `replayable_from_artifacts_for_profile` does not exist yet.

- [ ] **Step 3: Replace the trust-tier helper with the replayability helper**

In `src/quant_strategies/evidence_semantics.py`, remove this type alias and function:

```python
ArtifactTrustTier = Literal["search_only", "audit_replayable"]
```

```python
def artifact_trust_tier_for_profile(artifact_profile: str) -> ArtifactTrustTier:
    if artifact_profile in {"diagnostic", "summary"}:
        return "search_only"
    if artifact_profile == "full":
        return "audit_replayable"
    raise ValueError(f"unknown artifact profile: {artifact_profile}")
```

Keep the other `Literal`-based type aliases and add this helper in the same location:

```python
def replayable_from_artifacts_for_profile(artifact_profile: str) -> bool:
    if artifact_profile in {"diagnostic", "summary"}:
        return False
    if artifact_profile == "full":
        return True
    raise ValueError(f"unknown artifact profile: {artifact_profile}")
```

- [ ] **Step 4: Run helper tests to verify they pass**

Run:

```bash
conda run -n quant pytest tests/test_runner_artifact_profiles.py::test_replayable_from_artifacts_for_profile_maps_profiles tests/test_runner_artifact_profiles.py::test_replayable_from_artifacts_for_profile_rejects_unknown_profile -q
```

Expected: PASS.

- [ ] **Step 5: Commit the helper**

Run:

```bash
git add src/quant_strategies/evidence_semantics.py tests/test_runner_artifact_profiles.py
git commit -m "feat: derive artifact replayability from profile"
```

---

### Task 2: Rename Runner API And Summary Metadata

**Files:**
- Modify: `tests/test_runner_api_cli.py`
- Modify: `src/quant_strategies/runner/__init__.py`
- Modify: `src/quant_strategies/runner/artifacts.py`

- [ ] **Step 1: Update the API and summary assertions first**

In `tests/test_runner_api_cli.py`, change `SUMMARY_KEYS` by replacing:

```python
    "artifact_trust_tier",
```

with:

```python
    "replayable_from_artifacts",
```

In `assert_assessment()`, replace the current `expected_trust` and trust-tier assertions with:

```python
    expected_replayable = artifact_profile == "full"
    assert result.run_completed is run_completed
    assert result.failure_stage == failure_stage
    assert result.assessment_status == assessment_status
    assert result.promotion_eligible is promotion_eligible
    assert result.replayable_from_artifacts is expected_replayable
    assert result.data_availability_status == summary["data_availability_status"]
    assert result.availability_coverage == summary["availability_coverage"]
    assert result.row_contract == summary["row_contract"]
    assert result.causality_verified is summary["causality_verified"]
    assert result.evidence_quality_warnings == tuple(summary["evidence_quality_warnings"])
    assert summary["run_completed"] is run_completed
    assert summary["failure_stage"] == failure_stage
    assert summary["assessment_status"] == assessment_status
    assert summary["artifact_profile"] == artifact_profile
    assert summary["replayable_from_artifacts"] is expected_replayable
```

Do not keep any assertion for `result.artifact_trust_tier` or `summary["artifact_trust_tier"]`.

- [ ] **Step 2: Run a focused API test to verify it fails**

Run:

```bash
conda run -n quant pytest tests/test_runner_api_cli.py::test_run_config_success_writes_artifacts -q
```

Expected: FAIL with `AttributeError: 'RunResult' object has no attribute 'replayable_from_artifacts'` or a missing `replayable_from_artifacts` key in `summary.json`.

- [ ] **Step 3: Update `RunResult` and runner result construction**

In `src/quant_strategies/runner/__init__.py`, replace the import:

```python
from quant_strategies.evidence_semantics import artifact_trust_tier_for_profile, runner_evidence_semantics
```

with:

```python
from quant_strategies.evidence_semantics import replayable_from_artifacts_for_profile, runner_evidence_semantics
```

In `RunResult`, replace:

```python
    artifact_trust_tier: str | None = None
```

with:

```python
    replayable_from_artifacts: bool | None = None
```

In the success return near the end of `run_config()`, replace:

```python
        artifact_trust_tier=artifact_trust_tier_for_profile(config.output.artifact_profile),
```

with:

```python
        replayable_from_artifacts=replayable_from_artifacts_for_profile(config.output.artifact_profile),
```

In `_failure_result()`, replace:

```python
        artifact_trust_tier=artifact_trust_tier_for_profile(config.output.artifact_profile),
```

with:

```python
        replayable_from_artifacts=replayable_from_artifacts_for_profile(config.output.artifact_profile),
```

- [ ] **Step 4: Update summary, data-manifest, and run-manifest payloads**

In `src/quant_strategies/runner/artifacts.py`, replace the import:

```python
    artifact_trust_tier_for_profile,
```

with:

```python
    replayable_from_artifacts_for_profile,
```

In `write_data_manifest()`, replace:

```python
        "artifact_trust_tier": artifact_trust_tier_for_profile(config.output.artifact_profile),
```

with:

```python
        "replayable_from_artifacts": replayable_from_artifacts_for_profile(config.output.artifact_profile),
```

In `write_run_manifest()`, replace:

```python
        "artifact_trust_tier": artifact_trust_tier_for_profile(artifact_profile),
```

with:

```python
        "replayable_from_artifacts": replayable_from_artifacts_for_profile(artifact_profile),
```

In `summary_payload()`, replace:

```python
        "artifact_trust_tier": artifact_trust_tier_for_profile(config.output.artifact_profile),
```

with:

```python
        "replayable_from_artifacts": replayable_from_artifacts_for_profile(config.output.artifact_profile),
```

- [ ] **Step 5: Update full-profile manifest assertions**

In `tests/test_runner_api_cli.py::test_completed_run_writes_minimal_manifests`, replace:

```python
    assert run_manifest["artifact_trust_tier"] == "audit_replayable"
```

with:

```python
    assert run_manifest["replayable_from_artifacts"] is True
    assert "artifact_trust_tier" not in run_manifest
```

and replace:

```python
    assert data_manifest["artifact_trust_tier"] == "audit_replayable"
```

with:

```python
    assert data_manifest["replayable_from_artifacts"] is True
    assert "artifact_trust_tier" not in data_manifest
```

In `test_repeated_runner_artifacts_are_byte_deterministic`, replace:

```python
    assert first.artifact_trust_tier == "audit_replayable"
    assert second.artifact_trust_tier == "audit_replayable"
```

with:

```python
    assert first.replayable_from_artifacts is True
    assert second.replayable_from_artifacts is True
```

- [ ] **Step 6: Run focused API tests**

Run:

```bash
conda run -n quant pytest tests/test_runner_api_cli.py::test_run_config_success_writes_artifacts tests/test_runner_api_cli.py::test_completed_run_writes_minimal_manifests tests/test_runner_api_cli.py::test_repeated_runner_artifacts_are_byte_deterministic -q
```

Expected: PASS for the edited full-profile paths.

- [ ] **Step 7: Commit the runner API and summary metadata**

Run:

```bash
git add src/quant_strategies/runner/__init__.py src/quant_strategies/runner/artifacts.py tests/test_runner_api_cli.py
git commit -m "feat: expose runner artifact replayability flag"
```

---

### Task 3: Update Summary And Diagnostic Profile Artifacts

**Files:**
- Modify: `tests/test_runner_artifact_profiles.py`
- Modify: `tests/test_runner_api_cli.py`
- Modify: `src/quant_strategies/runner/artifact_profiles.py`
- Modify: `src/quant_strategies/runner/diagnostics.py`

- [ ] **Step 1: Update direct payload tests**

In `tests/test_runner_artifact_profiles.py::test_summary_profile_payload_contains_rows_decisions_and_engine`, replace:

```python
    assert payload["artifact_trust_tier"] == "search_only"
```

with:

```python
    assert payload["replayable_from_artifacts"] is False
    assert "artifact_trust_tier" not in payload
```

In `test_write_summary_profile_artifact_writes_json`, replace:

```python
    assert parsed["artifact_trust_tier"] == "search_only"
```

with:

```python
    assert parsed["replayable_from_artifacts"] is False
    assert "artifact_trust_tier" not in parsed
```

In `test_diagnostic_payload_contains_bounded_behavior_slices`, replace:

```python
    assert payload["artifact_trust_tier"] == "search_only"
```

with:

```python
    assert payload["replayable_from_artifacts"] is False
    assert "artifact_trust_tier" not in payload
```

- [ ] **Step 2: Update end-to-end summary and diagnostic assertions**

In `tests/test_runner_api_cli.py::test_run_config_summary_profile_writes_compact_artifacts`, replace the profile and manifest assertions:

```python
    assert profile["artifact_trust_tier"] == "search_only"
```

```python
    assert data_manifest["artifact_trust_tier"] == "search_only"
```

```python
    assert run_manifest["artifact_trust_tier"] == "search_only"
```

with:

```python
    assert profile["replayable_from_artifacts"] is False
    assert "artifact_trust_tier" not in profile
```

```python
    assert data_manifest["replayable_from_artifacts"] is False
    assert "artifact_trust_tier" not in data_manifest
```

```python
    assert run_manifest["replayable_from_artifacts"] is False
    assert "artifact_trust_tier" not in run_manifest
```

In `test_default_quick_run_writes_diagnostics_without_full_replay_artifacts`, replace:

```python
    assert diagnostics["artifact_trust_tier"] == "search_only"
```

```python
    assert data_manifest["artifact_trust_tier"] == "search_only"
```

```python
    assert run_manifest["artifact_trust_tier"] == "search_only"
```

with:

```python
    assert diagnostics["replayable_from_artifacts"] is False
    assert "artifact_trust_tier" not in diagnostics
```

```python
    assert data_manifest["replayable_from_artifacts"] is False
    assert "artifact_trust_tier" not in data_manifest
```

```python
    assert run_manifest["replayable_from_artifacts"] is False
    assert "artifact_trust_tier" not in run_manifest
```

- [ ] **Step 3: Run profile tests to verify they fail before implementation**

Run:

```bash
conda run -n quant pytest tests/test_runner_artifact_profiles.py::test_summary_profile_payload_contains_rows_decisions_and_engine tests/test_runner_artifact_profiles.py::test_write_summary_profile_artifact_writes_json tests/test_runner_artifact_profiles.py::test_diagnostic_payload_contains_bounded_behavior_slices tests/test_runner_api_cli.py::test_run_config_summary_profile_writes_compact_artifacts tests/test_runner_api_cli.py::test_default_quick_run_writes_diagnostics_without_full_replay_artifacts -q
```

Expected: FAIL with missing `replayable_from_artifacts` in profile payloads.

- [ ] **Step 4: Update summary-profile artifact writer**

In `src/quant_strategies/runner/artifact_profiles.py`, replace:

```python
from quant_strategies.evidence_semantics import artifact_trust_tier_for_profile, trade_result_metric_semantics
```

with:

```python
from quant_strategies.evidence_semantics import replayable_from_artifacts_for_profile, trade_result_metric_semantics
```

In `summary_profile_payload()`, replace:

```python
        "artifact_trust_tier": artifact_trust_tier_for_profile("summary"),
```

with:

```python
        "replayable_from_artifacts": replayable_from_artifacts_for_profile("summary"),
```

- [ ] **Step 5: Update diagnostic artifact writer**

In `src/quant_strategies/runner/diagnostics.py`, replace:

```python
from quant_strategies.evidence_semantics import artifact_trust_tier_for_profile
```

with:

```python
from quant_strategies.evidence_semantics import replayable_from_artifacts_for_profile
```

In `diagnostic_payload()`, replace:

```python
        "artifact_trust_tier": artifact_trust_tier_for_profile("diagnostic"),
```

with:

```python
        "replayable_from_artifacts": replayable_from_artifacts_for_profile("diagnostic"),
```

- [ ] **Step 6: Run profile tests to verify they pass**

Run:

```bash
conda run -n quant pytest tests/test_runner_artifact_profiles.py::test_summary_profile_payload_contains_rows_decisions_and_engine tests/test_runner_artifact_profiles.py::test_write_summary_profile_artifact_writes_json tests/test_runner_artifact_profiles.py::test_diagnostic_payload_contains_bounded_behavior_slices tests/test_runner_api_cli.py::test_run_config_summary_profile_writes_compact_artifacts tests/test_runner_api_cli.py::test_default_quick_run_writes_diagnostics_without_full_replay_artifacts -q
```

Expected: PASS.

- [ ] **Step 7: Commit profile artifact updates**

Run:

```bash
git add src/quant_strategies/runner/artifact_profiles.py src/quant_strategies/runner/diagnostics.py tests/test_runner_artifact_profiles.py tests/test_runner_api_cli.py
git commit -m "feat: write replayability in runner artifacts"
```

---

### Task 4: Verify Code And Test Vocabulary

**Files:**
- No planned file edits.

- [ ] **Step 1: Run the active code/test vocabulary grep after Tasks 1-3**

Run:

```bash
rg -n "search_only|audit_replayable|artifact_trust_tier" src tests
```

Expected: no output and exit code `1`.

- [ ] **Step 2: Run focused runner tests**

Run:

```bash
conda run -n quant pytest tests/test_runner_artifact_profiles.py tests/test_runner_api_cli.py -q
```

Expected: PASS.

- [ ] **Step 3: Confirm no commit is needed for this verification task**

Run:

```bash
git status --short
```

Expected: no uncommitted `src/` or `tests/` changes beyond commits already made in Tasks 1-3.

---

### Task 5: Update Product Docs And Handoff

**Files:**
- Modify: `README.md`
- Modify: `docs/runner.md`
- Modify: `docs/research-process.md`
- Modify: `docs/quant-autoresearch-consumer.md`
- Modify: `TODOS.md`

- [ ] **Step 1: Update README quick-run wording**

In `README.md`, replace the quick-run paragraph:

```markdown
Loads rows, runs the pure strategy, validates the decision contract, replays for
hidden lookahead, and screens the decisions through the engine. Fast, deterministic
`search_only` diagnostic evidence for ranking and iteration. The default quick-run
profile writes bounded `diagnostics.json` behavior slices without full replay/audit
artifacts. See [docs/runner.md](docs/runner.md).
```

with:

```markdown
Loads rows, runs the pure strategy, validates the decision contract, replays for
hidden lookahead, and screens the decisions through the engine. Fast, deterministic
quick-run evidence for ranking and iteration. The default quick-run profile writes
bounded `diagnostics.json` behavior slices with
`replayable_from_artifacts = false`; use `artifact_profile = "full"` when audit
replay from emitted artifacts is required. See [docs/runner.md](docs/runner.md).
```

- [ ] **Step 2: Update runner reference replayability section**

In `docs/runner.md`, replace the section headed:

```markdown
## Trust tiers and artifacts
```

through the paragraph ending:

```markdown
runner trade-result metrics.
```

with:

```markdown
## Replayability and artifacts

Runner artifacts declare `replayable_from_artifacts`. Diagnostic-profile runs are
the default and set `replayable_from_artifacts = false`: useful for one-strategy
iteration, but not enough to replay every reported number from artifacts alone.
Summary-profile runs also set `replayable_from_artifacts = false` and keep compact
sweep output. Full-profile runs (`artifact_profile = "full"`) set
`replayable_from_artifacts = true`: they include the row, decision, engine-request,
and evidence artifacts needed for audit replay of runner trade-result metrics.
```

Also replace this sentence in `docs/runner.md`:

```markdown
Programmatic callers should use `run_completed`, `failure_stage`,
`assessment_status`, verdicts, trust tier, causality/data fields, row contract, and
trade-result metrics rather than any single completion flag.
```

with:

```markdown
Programmatic callers should use `run_completed`, `failure_stage`,
`assessment_status`, verdicts, replayability, causality/data fields, row contract,
and trade-result metrics rather than any single completion flag.
```

- [ ] **Step 3: Update research-process API tables**

In `docs/research-process.md`, replace the `RunResult` field row:

```markdown
| `artifact_trust_tier`         | `str or None`     | Artifact replayability tier.                                                                                            |
```

with:

```markdown
| `replayable_from_artifacts`   | `bool or None`    | Whether reported quick-run metrics can be replayed from emitted artifacts alone.                                        |
```

Replace the two important-output rows:

```markdown
| `artifact_trust_tier = "search_only"`        | Compact quick-run evidence; not fully replayable from artifacts alone.       |
| `artifact_trust_tier = "audit_replayable"`   | Fuller artifact set intended for replay/audit of trade-result metrics.          |
```

with:

```markdown
| `replayable_from_artifacts = false`          | Compact quick-run evidence; not fully replayable from artifacts alone.       |
| `replayable_from_artifacts = true`           | Full artifact set intended for replay/audit of trade-result metrics.         |
```

- [ ] **Step 4: Update quant-autoresearch consumer contract**

In `docs/quant-autoresearch-consumer.md`, replace the artifact-profile explanation:

```markdown
`artifact_profile` controls **verbosity only** — which artifacts are written —
and never changes pass/fail. `diagnostic` is the default for one-strategy
iteration: it writes bounded `diagnostics.json` behavior slices and marks the
result `artifact_trust_tier = "search_only"`. `summary` is the compact sweep
profile and writes `summary.json` plus `artifact_profile_summary.json`. `full`
(for retained or debug runs) additionally writes input rows, decision records,
engine request JSON, and full evidence artifacts, and marks the result
`artifact_trust_tier = "audit_replayable"`.
```

with:

```markdown
`artifact_profile` controls **verbosity only** — which artifacts are written —
and never changes pass/fail. `diagnostic` is the default for one-strategy
iteration: it writes bounded `diagnostics.json` behavior slices and sets
`replayable_from_artifacts = false`. `summary` is the compact sweep profile and
writes `summary.json` plus `artifact_profile_summary.json`. `full` (for retained
or debug runs) additionally writes input rows, decision records, engine request
JSON, and full evidence artifacts, and sets `replayable_from_artifacts = true`.
```

In the vocabulary table, replace:

```markdown
| quick run | `quant-strategies run` / `run_config` | the fast `search_only` quick-run | iterate and rank here |
```

with:

```markdown
| quick run | `quant-strategies run` / `run_config` | the fast quick-run | iterate and rank here |
```

and replace:

```markdown
| `artifact_trust_tier` | `search_only` \| `audit_replayable` | derived replayability label | follows `artifact_profile`; not set directly |
```

with:

```markdown
| `replayable_from_artifacts` | `true` \| `false` | derived replayability flag | follows `artifact_profile`; not set directly |
```

Replace the Python result field:

```python
result.artifact_trust_tier
```

with:

```python
result.replayable_from_artifacts
```

Replace the sentence:

```markdown
contract failure. Treat `search_only` artifacts as ranking evidence only; rerun
retained candidates with `artifact_profile = "full"` before audit handoff to
obtain `audit_replayable` artifacts.
```

with:

```markdown
contract failure. Treat `replayable_from_artifacts = false` artifacts as ranking
evidence only; rerun retained candidates with `artifact_profile = "full"` before
audit handoff to obtain replayable artifacts.
```

- [ ] **Step 5: Update handoff status in `TODOS.md`**

In `TODOS.md`, replace:

```markdown
- Next open item: PR 2, Artifact Replayability Simplification.
```

with:

```markdown
- PR 2 is complete as of 2026-05-31. Runner outputs now expose
  `replayable_from_artifacts` as derived metadata, active output no longer emits
  `artifact_trust_tier`, `search_only`, or `audit_replayable`, compact profiles
  remain non-replayable, full profile remains replayable from emitted artifacts,
  and code/docs/tests were updated with full suite passing.
- Next open item: PR 3, Return Surface Honesty And Naming Cleanup.
```

Under the `## PR 2: Artifact Replayability Simplification` section, add this completion note after the "Why this matters" paragraph:

```markdown
**Completion note:** implemented as a hard public contract cutover. New runner
results and artifacts expose `replayable_from_artifacts` only: `summary` and
`diagnostic` derive `false`, while `full` derives `true`. No compatibility alias
or old trust-tier key remains in the active surface.
```

- [ ] **Step 6: Run active docs vocabulary grep**

Run:

```bash
rg -n "search_only|audit_replayable|artifact_trust_tier" TODOS.md PRD.md README.md docs src tests --glob '!docs/superpowers/**'
```

Expected: no output and exit code `1`.

- [ ] **Step 7: Commit docs and handoff**

Run:

```bash
git add README.md docs/runner.md docs/research-process.md docs/quant-autoresearch-consumer.md TODOS.md
git commit -m "docs: document artifact replayability flag"
```

---

### Task 6: Final Verification And Change Accounting

**Files:**
- No planned source edits.

- [ ] **Step 1: Run targeted runner verification**

Run:

```bash
conda run -n quant pytest tests/test_runner_artifact_profiles.py tests/test_runner_api_cli.py -q
```

Expected: PASS.

- [ ] **Step 2: Run full test suite**

Run:

```bash
conda run -n quant pytest -q
```

Expected: PASS.

- [ ] **Step 3: Run final active-surface grep**

Run:

```bash
rg -n "search_only|audit_replayable|artifact_trust_tier" TODOS.md PRD.md README.md docs src tests --glob '!docs/superpowers/**'
```

Expected: no output and exit code `1`.

- [ ] **Step 4: Report changed-line counts**

Run:

```bash
git diff --shortstat f45f821..HEAD -- src tests
git diff --shortstat f45f821..HEAD -- README.md docs/runner.md docs/research-process.md docs/quant-autoresearch-consumer.md TODOS.md
git diff --numstat f45f821..HEAD -- src tests README.md docs/runner.md docs/research-process.md docs/quant-autoresearch-consumer.md TODOS.md
```

Expected: output lists aggregate implementation changes since the approved design commit,
excluding `docs/superpowers/` design and plan files. Use these numbers in the
completion response, separating source/tests from docs/handoff.

- [ ] **Step 5: Confirm final git status**

Run:

```bash
git status --short
```

Expected: clean working tree, unless Season has unrelated changes.

---

## Self-Review Notes

- Spec coverage: tasks cover hard cutover, helper replacement, `RunResult`, all runner artifacts, validation non-change, active docs, `TODOS.md`, grep verification, targeted tests, and full suite.
- Scope check: this is one subsystem, the quick-run artifact replayability surface. It does not change validation verdict replayability or artifact profiles.
- Type consistency: all new public fields use `replayable_from_artifacts`; helper name is `replayable_from_artifacts_for_profile`; the field type is `bool | None` on `RunResult` and JSON boolean in artifacts.
