from __future__ import annotations

from pathlib import Path

import pytest

from quant_strategies.runner import cli
from quant_strategies.validation import ValidationRunResult
from quant_strategies.validation.errors import ValidationError
from quant_strategies.validation.policy import ValidationPolicyDecision


@pytest.mark.parametrize("decision", ["mechanical_pass", "watchlist", "mechanical_review_candidate"])
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
        "quant_strategies.runner.cli.run_validation",
        fake_run_validation,
    )

    code = cli.main(["validate", "--repo-root", str(tmp_path), "candidate/validation.toml"])

    assert code == 0
    assert decision in capsys.readouterr().out
    assert calls == [(Path("candidate/validation.toml"), tmp_path)]


def test_validate_cli_returns_two_for_hard_no(monkeypatch, tmp_path: Path, capsys):
    monkeypatch.setattr(
        "quant_strategies.runner.cli.run_validation",
        lambda path, repo_root=None: ValidationRunResult(
            result_dir=tmp_path / "validation_results" / "run",
            decision=ValidationPolicyDecision(decision="hard_no", reasons=("nonpositive_net_return",)),
            message="validation decision: hard_no",
            run_completed=True,
            failure_stage=None,
        ),
    )

    code = cli.main(["validate", "--repo-root", str(tmp_path), "candidate/validation.toml"])

    assert code == 2
    assert "hard_no" in capsys.readouterr().out


def test_validate_cli_returns_three_for_data_audit_failure(monkeypatch, tmp_path: Path, capsys):
    monkeypatch.setattr(
        "quant_strategies.runner.cli.run_validation",
        lambda path, repo_root=None: ValidationRunResult(
            result_dir=tmp_path / "validation_results" / "run",
            decision=ValidationPolicyDecision(decision="hard_no", reasons=("data_audit_failed",)),
            message="validation decision: hard_no",
            run_completed=True,
            failure_stage="data_audit",
        ),
    )

    code = cli.main(["validate", "--repo-root", str(tmp_path), "candidate/validation.toml"])

    assert code == 3
    assert "hard_no" in capsys.readouterr().out


def test_validate_cli_returns_one_for_validation_error(monkeypatch, tmp_path: Path, capsys):
    def fake_run_validation(path: Path, repo_root: Path | None = None) -> ValidationRunResult:
        raise ValidationError("bad config")

    monkeypatch.setattr(
        "quant_strategies.runner.cli.run_validation",
        fake_run_validation,
    )

    code = cli.main(["validate", "--repo-root", str(tmp_path), "candidate/validation.toml"])

    assert code == 1
    assert "validation failed: bad config" in capsys.readouterr().out
