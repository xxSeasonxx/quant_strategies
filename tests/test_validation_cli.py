from __future__ import annotations

from pathlib import Path

from quant_strategies.runner import cli
from quant_strategies.validation import ValidationRunResult
from quant_strategies.validation.errors import ValidationError
from quant_strategies.validation.policy import ValidationPolicyDecision


def test_validate_cli_returns_zero_for_mechanical_pass(monkeypatch, tmp_path: Path, capsys):
    calls: list[tuple[Path, Path | None]] = []

    def fake_run_validation(path: Path, repo_root: Path | None = None) -> ValidationRunResult:
        calls.append((path, repo_root))
        return ValidationRunResult(
            success=True,
            result_dir=tmp_path / "validation_results" / "run",
            decision=ValidationPolicyDecision(decision="mechanical_pass"),
            message="validation decision: mechanical_pass",
        )

    monkeypatch.setattr(
        "quant_strategies.runner.cli.run_validation",
        fake_run_validation,
    )

    code = cli.main(["validate", "--repo-root", str(tmp_path), "researched/demo"])

    assert code == 0
    assert "mechanical_pass" in capsys.readouterr().out
    assert calls == [(Path("researched/demo"), tmp_path)]


def test_validate_cli_returns_one_for_hard_no(monkeypatch, tmp_path: Path, capsys):
    monkeypatch.setattr(
        "quant_strategies.runner.cli.run_validation",
        lambda path, repo_root=None: ValidationRunResult(
            success=False,
            result_dir=tmp_path / "validation_results" / "run",
            decision=ValidationPolicyDecision(decision="hard_no", reasons=("nonpositive_net_return",)),
            message="validation decision: hard_no",
        ),
    )

    code = cli.main(["validate", "--repo-root", str(tmp_path), "researched/demo"])

    assert code == 1
    assert "hard_no" in capsys.readouterr().out


def test_validate_cli_returns_two_for_maybe(monkeypatch, tmp_path: Path, capsys):
    monkeypatch.setattr(
        "quant_strategies.runner.cli.run_validation",
        lambda path, repo_root=None: ValidationRunResult(
            success=False,
            result_dir=tmp_path / "validation_results" / "run",
            decision=ValidationPolicyDecision(decision="maybe", reasons=("unsupported_semantics",)),
            message="validation decision: maybe",
        ),
    )

    code = cli.main(["validate", "--repo-root", str(tmp_path), "researched/demo"])

    assert code == 2
    assert "maybe" in capsys.readouterr().out


def test_validate_cli_returns_one_for_validation_error(monkeypatch, tmp_path: Path, capsys):
    def fake_run_validation(path: Path, repo_root: Path | None = None) -> ValidationRunResult:
        raise ValidationError("bad config")

    monkeypatch.setattr(
        "quant_strategies.runner.cli.run_validation",
        fake_run_validation,
    )

    code = cli.main(["validate", "--repo-root", str(tmp_path), "researched/demo"])

    assert code == 1
    assert "validation failed: bad config" in capsys.readouterr().out
