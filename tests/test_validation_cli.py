from __future__ import annotations

from pathlib import Path

from quant_strategies.runner import cli
from quant_strategies.validation import ValidationRunResult
from quant_strategies.validation.policy import PromotionDecision


def test_validate_cli_returns_zero_for_clear_yes(monkeypatch, tmp_path: Path, capsys):
    monkeypatch.setattr(
        "quant_strategies.runner.cli.run_validation",
        lambda path, repo_root=None: ValidationRunResult(
            success=True,
            result_dir=tmp_path / "validation_results" / "run",
            decision=PromotionDecision(decision="clear_yes"),
            message="validation decision: clear_yes",
        ),
    )

    code = cli.main(["validate", "--repo-root", str(tmp_path), "researched/demo"])

    assert code == 0
    assert "clear_yes" in capsys.readouterr().out


def test_validate_cli_returns_one_for_hard_no(monkeypatch, tmp_path: Path, capsys):
    monkeypatch.setattr(
        "quant_strategies.runner.cli.run_validation",
        lambda path, repo_root=None: ValidationRunResult(
            success=False,
            result_dir=tmp_path / "validation_results" / "run",
            decision=PromotionDecision(decision="hard_no", reasons=("negative_net_return",)),
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
            decision=PromotionDecision(decision="maybe", reasons=("unsupported_semantics",)),
            message="validation decision: maybe",
        ),
    )

    code = cli.main(["validate", "--repo-root", str(tmp_path), "researched/demo"])

    assert code == 2
    assert "maybe" in capsys.readouterr().out
