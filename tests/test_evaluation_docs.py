from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text()


def compact(text: str) -> str:
    return " ".join(text.split())


def test_reference_docs_describe_evaluate_surface_without_promotion_authority():
    for path in [
        "README.md",
        "FOUNDATION_LOCK.md",
        "docs/foundation-surfaces.md",
        "docs/vectorbtpro.md",
    ]:
        text = read(path)
        assert "quant-strategies evaluate candidates/<candidate_id>/evaluation.toml" in text, path
        assert "quant_strategies.evaluation.run_evaluation" in text, path
        assert "EvaluationRunResult" in text, path
        assert "evaluation.toml" in text, path
        assert "Parquet" in text, path
        assert "pyarrow" in text, path
        assert "does not authorize promotion, paper trading, or live trading" in text, path
        assert "Benchmark-relative metrics are evidence only" in text, path


def test_docs_describe_evaluation_example_and_path_anchoring():
    foundation = read("docs/foundation-surfaces.md")
    readme = read("README.md")
    vectorbt = read("docs/vectorbtpro.md")

    for text in (foundation, vectorbt):
        assert "examples/simple_momentum/evaluation.toml" in text

    assert "candidate-local" in foundation
    assert "candidate-local" in readme
    assert "--repo-root" in foundation
    assert "--repo-root" in readme
    assert "output.results_dir" in foundation
    assert "output.results_dir" in readme


def test_validation_and_evaluation_examples_keep_window_dates_out_of_data_sections():
    for path in [
        "examples/simple_momentum/validation.toml",
        "examples/simple_momentum/evaluation.toml",
    ]:
        text = read(path)
        data_section = text.split("[data]", 1)[1].split("\n[", 1)[0]

        assert "start =" not in data_section, path
        assert "end =" not in data_section, path


def test_docs_include_installed_cli_refresh_smoke():
    for path in ["README.md", "docs/foundation-surfaces.md"]:
        text = read(path)
        assert "make check" in text, path
        assert "make check-vectorbtpro-smoke" in text, path
        assert "conda run -n quant python -m pip install -e ." in text, path
        assert "conda run -n quant quant-strategies --help" in text, path
        assert (
            "conda run -n quant env RUN_VECTORBTPRO_SMOKE=1 pytest "
            "tests/test_evaluation_backend.py::test_vectorbtpro_evaluation_backend_real_smoke_if_installed"
        ) in text, path


def test_docs_describe_full_grid_returns_and_annualization_cadence_warnings():
    for path in ["README.md", "docs/foundation-surfaces.md", "docs/vectorbtpro.md"]:
        text = read(path)
        assert "full-grid portfolio returns" in text, path
        assert "flat/no-position bars" in text, path
        assert "annualization cadence" in text, path
        assert "annualization_cadence" in text, path
        assert "min_annualized_samples" in text, path
        assert "annualized/risk metrics" in text, path
        assert "minimum return-sample floor" in text, path


def test_docs_lock_row_order_policy_and_shared_kernel_boundaries():
    docs = compact(
        "\n".join(
            read(path)
            for path in ["README.md", "FOUNDATION_LOCK.md", "docs/foundation-surfaces.md"]
        )
    ).replace("`", "")

    assert "one shared decision/spec kernel plus separate price-evidence paths" in docs
    assert "quant_data owns stable row ordering for supplied rows" in docs
    assert (
        "quant_strategies preserves supplied row order for strategy input, hashing, and execution"
        in docs
    )
    assert "does not sort rows locally before hashing or execution" in docs


def test_docs_lock_sortino_funding_and_no_lookahead_semantics():
    docs = compact(
        "\n".join(
            read(path)
            for path in [
                "README.md",
                "FOUNDATION_LOCK.md",
                "docs/foundation-surfaces.md",
                "docs/vectorbtpro.md",
            ]
        )
    )

    assert "Sortino uses downside semivariance over the full return sample" in docs
    assert "returns `None`, not infinity, when undefined" in docs
    assert (
        "Engine funding is linear trade-activity funding folded into validation `net_return`"
        in docs
    )
    assert "evaluation funding is NAV-ledger cashflow" in docs
    assert "no funding events in the open interval accrue zero funding" in docs
    assert "flagged funding rows still fail when malformed, conflicting, or mark-misaligned" in docs
    assert "hidden-lookahead replay proves point-in-time causal replay" in docs
    assert "does not prove out-of-sample validity" in docs
    assert "does not prove freedom from in-sample fitting" in docs


def test_consumer_docs_route_autoresearch_to_micro_causality():
    usage = read("docs/consumer/usage-guide.md")
    reference = read("docs/consumer/reference.md")

    assert 'causality_check = "micro"' in usage
    assert "result.evidence.causality.replay_scope" in usage
    assert "result.evidence.causality.verified" in usage
    assert "micro causality" in usage
    assert "validation/evaluation" in usage
    assert "materialize emitted mode for Train iteration" not in usage
    assert '"emitted"' not in usage
    assert '"strict"' not in usage
    assert "`strict_probe_limit`" not in usage
    assert "RunFocusedCausalityEvidence" in reference
    assert "focused_causality" in reference
    assert '"micro"' in reference
    assert '"emitted"' in reference
    assert '"strict"' in reference
    assert "advanced" in reference


def test_lock_todos_and_review_track_p1_annualized_metric_guards():
    for path in [
        "FOUNDATION_LOCK.md",
        "TODOS.md",
        "docs/reviews/2026-06-03-foundation-claude-disposition.md",
    ]:
        text = read(path)
        assert "min_annualized_samples" in text, path
        assert "annualized/risk metrics" in text, path
        assert "annualization cadence" in text, path
        assert "minimum return-sample floor" in text, path


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
    assert "benchmark-relative metrics and user-defined scenario matrices are implemented" in text
    assert "Remaining follow-up work is limited to benchmark-relative metrics" not in text


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
