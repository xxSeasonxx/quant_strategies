from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from quant_strategies import cli
from quant_strategies.validation import ValidationRunResult
from quant_strategies.validation.errors import ValidationError
from quant_strategies.validation.policy import ValidationPolicyDecision


@pytest.mark.parametrize("decision", ["mechanical_complete", "mechanical_caution", "mechanical_threshold_pass"])
def test_validate_cli_returns_zero_for_completed_advisory_decisions(
    decision: str,
    monkeypatch,
    tmp_path: Path,
    capsys,
):
    calls: list[tuple[Path, Path | None]] = []

    def fake_run_validation(path: Path, repo_root: Path | None = None) -> ValidationRunResult:
        calls.append((path, repo_root))
        return ValidationRunResult(
            result_dir=tmp_path / "validation_results" / "run",
            decision=ValidationPolicyDecision(decision=decision),
            message=f"validation decision: {decision}",
            run_completed=True,
            failure_stage=None,
        )

    monkeypatch.setattr(
        "quant_strategies.cli.run_validation",
        fake_run_validation,
    )

    code = cli.main(["validate", "--repo-root", str(tmp_path), "candidate/validation.toml"])

    assert code == 0
    assert decision in capsys.readouterr().out
    assert calls == [(Path("candidate/validation.toml"), tmp_path)]


def test_validate_cli_returns_two_for_mechanical_fail(monkeypatch, tmp_path: Path, capsys):
    monkeypatch.setattr(
        "quant_strategies.cli.run_validation",
        lambda path, repo_root=None: ValidationRunResult(
            result_dir=tmp_path / "validation_results" / "run",
            decision=ValidationPolicyDecision(decision="mechanical_fail", reasons=("nonpositive_net_return",)),
            message="validation decision: mechanical_fail",
            run_completed=True,
            failure_stage=None,
        ),
    )

    code = cli.main(["validate", "--repo-root", str(tmp_path), "candidate/validation.toml"])

    assert code == 2
    assert "mechanical_fail" in capsys.readouterr().out


def test_validate_cli_returns_three_for_data_audit_failure(monkeypatch, tmp_path: Path, capsys):
    monkeypatch.setattr(
        "quant_strategies.cli.run_validation",
        lambda path, repo_root=None: ValidationRunResult(
            result_dir=tmp_path / "validation_results" / "run",
            decision=ValidationPolicyDecision(decision="mechanical_fail", reasons=("data_audit_failed",)),
            message="validation decision: mechanical_fail",
            run_completed=True,
            failure_stage="data_audit",
        ),
    )

    code = cli.main(["validate", "--repo-root", str(tmp_path), "candidate/validation.toml"])

    assert code == 3
    assert "mechanical_fail" in capsys.readouterr().out


def test_validate_cli_returns_three_for_data_load_failure(monkeypatch, tmp_path: Path, capsys):
    monkeypatch.setattr(
        "quant_strategies.cli.run_validation",
        lambda path, repo_root=None: ValidationRunResult(
            result_dir=tmp_path / "validation_results" / "run",
            decision=ValidationPolicyDecision(decision="mechanical_fail", reasons=("data_load_failed",)),
            message="validation decision: mechanical_fail",
            run_completed=True,
            failure_stage="data_load",
        ),
    )

    code = cli.main(["validate", "--repo-root", str(tmp_path), "candidate/validation.toml"])

    assert code == 3
    assert "mechanical_fail" in capsys.readouterr().out


def test_validate_cli_exit_code_prefers_derived_succeeded_contract():
    result = SimpleNamespace(
        succeeded=False,
        run_completed=True,
        failure_stage=None,
        decision=ValidationPolicyDecision(decision="mechanical_caution"),
    )

    assert cli._validation_exit_code(result) == 1


def test_validate_cli_omits_artifacts_when_config_load_returns_no_result_dir(
    monkeypatch,
    tmp_path: Path,
    capsys,
):
    monkeypatch.setattr(
        "quant_strategies.cli.run_validation",
        lambda path, repo_root=None: ValidationRunResult(
            result_dir=None,
            decision=ValidationPolicyDecision(decision="mechanical_fail", reasons=("validation_config_failed",)),
            message="bad validation config",
            run_completed=False,
            failure_stage="config_load",
        ),
    )

    code = cli.main(["validate", "--repo-root", str(tmp_path), "candidate/validation.toml"])
    output = capsys.readouterr().out

    assert code == 1
    assert "validation failed: bad validation config" in output
    assert "artifacts: None" not in output


def test_validate_cli_returns_one_for_validation_error(monkeypatch, tmp_path: Path, capsys):
    def fake_run_validation(path: Path, repo_root: Path | None = None) -> ValidationRunResult:
        raise ValidationError("bad config")

    monkeypatch.setattr(
        "quant_strategies.cli.run_validation",
        fake_run_validation,
    )

    code = cli.main(["validate", "--repo-root", str(tmp_path), "candidate/validation.toml"])

    assert code == 1
    assert "validation failed: bad config" in capsys.readouterr().out


def test_validate_cli_events_jsonl_wires_validation_event_sink(
    monkeypatch,
    tmp_path: Path,
    capsys,
):
    calls: list[tuple[Path, Path | None, bool]] = []

    def fake_run_validation(path: Path, repo_root: Path | None = None, event_sink=None) -> ValidationRunResult:
        calls.append((path, repo_root, event_sink is not None))
        assert event_sink is not None
        event_sink(
            {
                "event": "validation_stage",
                "stage": "window_execution",
                "status": "completed",
            }
        )
        return ValidationRunResult(
            result_dir=tmp_path / "validation_results" / "run",
            decision=ValidationPolicyDecision(decision="mechanical_caution"),
            message="validation decision: mechanical_caution",
            run_completed=True,
            failure_stage=None,
        )

    monkeypatch.setattr(
        "quant_strategies.cli.run_validation",
        fake_run_validation,
    )

    code = cli.main(
        [
            "validate",
            "--events-jsonl",
            "--repo-root",
            str(tmp_path),
            "candidate/validation.toml",
        ]
    )
    captured = capsys.readouterr()

    assert code == 0
    assert calls == [(Path("candidate/validation.toml"), tmp_path, True)]
    assert "mechanical_caution" in captured.out
    assert json.loads(captured.err)["event"] == "validation_stage"
    assert json.loads(captured.err)["stage"] == "window_execution"


def test_validate_cli_backstops_oserror(monkeypatch, tmp_path: Path, capsys):
    def raise_oserror(path, repo_root=None, **_kwargs):
        raise PermissionError("results dir not writable")

    monkeypatch.setattr("quant_strategies.cli.run_validation", raise_oserror)

    code = cli.main(["validate", "--repo-root", str(tmp_path), "candidate/validation.toml"])

    assert code == 1
    assert "validation failed" in capsys.readouterr().out
