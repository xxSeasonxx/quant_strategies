from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text()


def test_public_docs_describe_evaluate_surface_without_promotion_authority():
    for path in [
        "README.md",
        "PRD.md",
        "FOUNDATION_LOCK.md",
        "docs/foundation-surfaces.md",
        "docs/vectorbtpro.md",
    ]:
        text = read(path)
        assert "quant-strategies evaluate" in text, path
        assert "run_evaluation" in text, path
        assert "evaluation.toml" in text, path
        assert "Parquet" in text, path
        assert "pyarrow" in text, path
        assert "does not authorize promotion, paper trading, or live trading" in text, path
        assert "Benchmark-relative metrics are deferred" in text, path


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
        "evaluation hard_no",
        "evaluation watchlist",
        "evaluation validates alpha",
        "evaluation proves alpha",
        "evaluation authorizes paper",
        "evaluation authorizes live",
        "fallback to JSONL",
        "JSONL fallback is allowed",
    ]
    lowered = docs.lower()
    assert not any(term.lower() in lowered for term in forbidden)
