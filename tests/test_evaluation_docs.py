from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text()


def test_reference_docs_describe_evaluate_surface_without_promotion_authority():
    for path in [
        "README.md",
        "FOUNDATION_LOCK.md",
        "docs/foundation-surfaces.md",
        "docs/vectorbtpro.md",
    ]:
        text = read(path)
        assert "quant-strategies evaluate candidate/evaluation.toml" in text, path
        assert "quant_strategies.evaluation.run_evaluation" in text, path
        assert "EvaluationRunResult" in text, path
        assert "evaluation.toml" in text, path
        assert "Parquet" in text, path
        assert "pyarrow" in text, path
        assert "does not authorize promotion, paper trading, or live trading" in text, path
        assert "Benchmark-relative metrics are deferred" in text, path


def test_docs_describe_evaluation_example_and_path_anchoring():
    foundation = read("docs/foundation-surfaces.md")
    readme = read("README.md")
    vectorbt = read("docs/vectorbtpro.md")

    for text in (foundation, vectorbt):
        assert "examples/strategies/simple_momentum_spy_daily_evaluation.toml" in text

    assert "candidate-local" in foundation
    assert "candidate-local" in readme
    assert "--repo-root" in foundation
    assert "--repo-root" in readme
    assert "output.results_dir" in foundation
    assert "output.results_dir" in readme


def test_prd_owns_product_intent_not_evaluate_command_schema():
    text = read("PRD.md")

    assert "Research evaluation" in text
    assert "frozen candidates" in text
    assert "No foundation job authorizes promotion, paper trading, or" in text
    assert "live trading" in text
    assert "quant-strategies evaluate" not in text
    assert "run_evaluation" not in text
    assert "pyarrow" not in text


def test_todos_collapses_c_to_follow_up_work_only():
    text = read("TODOS.md")

    assert "Research evaluation surface MVP" not in text
    assert "benchmark-relative metrics" in text
    assert "user-defined scenario matrices" in text


def test_docs_do_not_call_evaluation_validation_verdict():
    docs = "\n".join(
        read(path)
        for path in [
            "README.md",
            "PRD.md",
            "FOUNDATION_LOCK.md",
            "docs/foundation-surfaces.md",
            "docs/vectorbtpro.md",
            "docs/quant-autoresearch-consumer.md",
        ]
        if (ROOT / path).exists()
    )

    forbidden = [
        "evaluation verdict",
        "evaluation mechanical_fail",
        "evaluation mechanical_caution",
        "evaluation validates alpha",
        "evaluation proves alpha",
        "evaluation authorizes paper",
        "evaluation authorizes live",
        "fallback to JSONL",
        "JSONL fallback is allowed",
    ]
    lowered = docs.lower()
    assert not any(term.lower() in lowered for term in forbidden)


def test_active_docs_do_not_present_engine_as_user_api():
    docs = {
        path: read(path)
        for path in [
            "README.md",
            "FOUNDATION_LOCK.md",
            "PRD.md",
            "AGENTS.md",
            "docs/foundation-surfaces.md",
            "docs/vectorbtpro.md",
        ]
    }

    forbidden_import_snippets = [
        "from quant_strategies.engine",
        "import quant_strategies.engine",
        "quant_strategies.engine import",
    ]
    for path, text in docs.items():
        assert not any(snippet in text for snippet in forbidden_import_snippets), path

    active_text = " ".join("\n".join(docs.values()).lower().split())
    assert "quant_strategies.engine" in active_text
    assert "internal execution kernel" in active_text
    assert "not a fourth public" in active_text
