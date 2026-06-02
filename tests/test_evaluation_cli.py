from __future__ import annotations

from pathlib import Path

from quant_strategies.evaluation import EvaluationRunResult
from quant_strategies.runner import cli


def test_evaluate_cli_prints_result_artifact_path_on_success(monkeypatch, tmp_path: Path, capsys):
    calls: list[tuple[Path, Path | None]] = []
    result_dir = tmp_path / "evaluation_results" / "run"

    def fake_run_evaluation(path: Path, repo_root: Path | None = None) -> EvaluationRunResult:
        calls.append((path, repo_root))
        return EvaluationRunResult(
            result_dir=result_dir,
            message="evaluation completed",
            run_completed=True,
            failure_stage=None,
            assessment_status="completed",
        )

    monkeypatch.setattr("quant_strategies.runner.cli.run_evaluation", fake_run_evaluation)

    code = cli.main(["evaluate", "--repo-root", str(tmp_path), "candidate/evaluation.toml"])

    assert code == 0
    assert capsys.readouterr().out == f"{result_dir}\n"
    assert calls == [(Path("candidate/evaluation.toml"), tmp_path)]


def test_evaluate_cli_returns_three_for_data_load_failure(monkeypatch, tmp_path: Path, capsys):
    monkeypatch.setattr(
        "quant_strategies.runner.cli.run_evaluation",
        lambda path, repo_root=None: EvaluationRunResult(
            result_dir=None,
            message="data source missing",
            run_completed=False,
            failure_stage="data_load",
            assessment_status="data_unavailable",
        ),
    )

    code = cli.main(["evaluate", "--repo-root", str(tmp_path), "candidate/evaluation.toml"])

    assert code == 3
    assert capsys.readouterr().out == "evaluation failed: data source missing\n"


def test_evaluate_cli_returns_one_for_portfolio_failure_with_artifacts(
    monkeypatch,
    tmp_path: Path,
    capsys,
):
    result_dir = tmp_path / "evaluation_results" / "failed"
    result_dir.mkdir(parents=True)
    monkeypatch.setattr(
        "quant_strategies.runner.cli.run_evaluation",
        lambda path, repo_root=None: EvaluationRunResult(
            result_dir=result_dir,
            message="portfolio backend unavailable",
            run_completed=False,
            failure_stage="portfolio_evaluation",
            assessment_status="portfolio_unavailable",
        ),
    )

    code = cli.main(["evaluate", "--repo-root", str(tmp_path), "candidate/evaluation.toml"])

    assert code == 1
    assert capsys.readouterr().out == (
        f"evaluation failed: portfolio backend unavailable; artifacts: {result_dir}\n"
    )


def test_evaluate_cli_backstops_oserror_without_traceback(monkeypatch, tmp_path: Path, capsys):
    def raise_oserror(path: Path, repo_root: Path | None = None) -> EvaluationRunResult:
        raise OSError("disk full")

    monkeypatch.setattr("quant_strategies.runner.cli.run_evaluation", raise_oserror)

    code = cli.main(["evaluate", "--repo-root", str(tmp_path), "candidate/evaluation.toml"])
    captured = capsys.readouterr()

    assert code == 1
    assert captured.out == "evaluation failed: disk full\n"
    assert "Traceback" not in captured.err
