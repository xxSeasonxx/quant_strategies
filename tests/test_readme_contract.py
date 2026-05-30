from __future__ import annotations

import re
from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text()


def _flat(text: str) -> str:
    # Collapse whitespace so doc line-wrapping never breaks a contract assertion.
    return re.sub(r"\s+", " ", text)


# The foundation contract is documented across the README front page plus the
# reference docs it links to. These checks guard the *contract*, not which file
# holds each sentence — the README itself stays a high-level overview.
DOC_PATHS = (
    "README.md",
    "docs/runner.md",
    "docs/validation.md",
    "docs/quant-autoresearch-consumer.md",
)


def _doc_set() -> str:
    return _flat("\n".join(_read(p) for p in DOC_PATHS))


def test_readme_stays_generic_and_high_level():
    text = _read("README.md")

    forbidden_terms = (
        "clear" + "_yes",
        "promotion" + "_decision",
        "simple" + "_momentum",
        "fx" + "_triangular_residual",
        "crypto" + "_perp_funding_crowding_reversal",
        "_smoke.toml",
        "maybe",
    )
    for term in forbidden_terms:
        assert term not in text
    assert re.search(r"(?<!max_)hold" + "_bars", text) is None

    # Front-page essentials that must stay in the README itself.
    assert "generate_decisions(rows, params) -> list[StrategyDecision]" in text
    for verdict in ("hard_no", "mechanical_pass", "watchlist", "mechanical_review_candidate"):
        assert verdict in text
    assert "decision_id" in text
    assert "decisions.extended_ontology" in text
    assert "smoke_score.sum_signed_trade_activity_*" in text
    assert "search_only" in text
    assert "quant-strategies validate path/to/candidate/validation.toml" in text
    assert "validation does not treat it as special" in text

    # The README links out to the reference docs rather than inlining them.
    assert "docs/runner.md" in text
    assert "docs/validation.md" in text
    assert "docs/quant-autoresearch-consumer.md" in text


def test_contract_detail_is_documented_in_the_doc_set():
    docs = _doc_set()
    required = (
        "validation_decision.json",
        "unsupported execution semantics is a `hard_no`",
        "Validation backend summaries include `metric_semantics`",
        "[paper_readiness]",
        "min_windows = 2",
        "min_total_trades = 30",
        "max_stressed_net_loss = -0.02",
        "max_fill_lag_net_loss = -0.02",
        "metric_semantics",
        "artifact_trust_tier",
        "search_only",
        "audit_replayable",
        "smoke_unverified",
        "causality_verified",
        "target_notional",
        "target_contracts",
        "target_vol",
        "multiple_testing_not_corrected_advisory_only",
        "search_pressure_unknown_advisory_only",
        "Explicitly extended decisions are rejected by unsupported",
    )
    for token in required:
        assert _flat(token) in docs, token

    # Retired vocabulary must not resurface anywhere in the doc set.
    assert "deflation_not_evaluated" not in docs
    assert "backend_capability_matrix.json" not in docs


def test_docs_demote_vectorbt_to_single_trade_agreement_check():
    readme = _flat(_read("README.md"))
    docs = _doc_set()
    prd = _flat(_read("PRD.md"))

    assert "VectorBT Pro<br/>agreement oracle" not in readme
    assert "single-trade" in readme
    assert "never produces verdict metrics" in readme

    assert "no separate VectorBT Pro verdict metric" in docs
    assert "single-trade" in docs
    assert "fails the run with `backend_agreement_failed`" in docs
    assert "co-equal validation backend" not in docs

    assert "one validation backend" not in prd
    assert "single-trade agreement check" in prd
    assert "not a validation backend or verdict source" in prd


def test_prd_keeps_output_contract_precise():
    prd = _flat(_read("PRD.md"))

    assert "No results land in `src/` or in version-controlled trees" not in prd
    assert "Runner results are written under ignored `results/` directories" in prd
    assert "Validation outputs remain candidate-local" in prd
    assert "example configs are templates" in prd


def test_runner_docs_describe_normalized_row_contract():
    runner = _flat(_read("docs/runner.md"))
    consumer = _flat(_read("docs/quant-autoresearch-consumer.md"))
    row_issue_reasons = (
        "row_missing_required_field",
        "row_invalid_timestamp",
        "row_invalid_numeric_field",
        "row_invalid_ohlc_order",
        "row_duplicate_symbol_timestamp",
        "row_invalid_available_at",
        "row_missing_available_at",
        "row_missing_quote_field",
        "row_invalid_funding_fields",
    )

    for doc in (runner, consumer):
        assert "`quant_strategies.data_contract.NormalizedRows`" in doc
        assert "`Sequence[Mapping[str, Any]]`" in doc

    assert "they do not receive row model objects" in runner
    assert "not free-form issue messages" in consumer
    assert "Missing `available_at` in search mode is warning evidence" in runner
    assert "Invalid `available_at` is a row contract failure" in runner
    assert "`row_contract.issues`" in runner
    assert "`issue_count` and `issue_reasons` preserve" in runner

    for reason in row_issue_reasons:
        assert reason in runner
        assert reason in consumer


def test_runner_public_api_is_documented():
    prd = _read("PRD.md")
    readme = _read("README.md")
    consumer = _read("docs/quant-autoresearch-consumer.md")

    assert "`quant_strategies.runner.run_config`" in prd
    assert "`quant_strategies.runner.RunResult`" in prd
    assert "The public consumer surface is re-exported" not in prd
    assert "top-level facade" in prd

    assert "`quant_strategies.runner.run_config`" in readme
    assert "`quant_strategies.runner.RunResult`" in readme
    assert "`quant_strategies.validation.run_validation`" in readme
    assert "`quant_strategies.runner.run_config`" in consumer
    assert "`quant_strategies.runner.RunResult`" in consumer
    assert "from quant_strategies.validation import run_validation" in consumer
    assert 'prior_search = "none"' in consumer
    assert "`prior_search = \"none\"`, `\"known\"`, or `\"unknown\"`" in consumer
    assert "decisions.extended_ontology" in consumer

    import quant_strategies

    assert not hasattr(quant_strategies, "run_config")
    assert not hasattr(quant_strategies, "run_validation")


def test_docs_keep_validation_layout_agnostic_and_promotion_human_controlled():
    readme = _read("README.md")
    validation = _flat(_read("docs/validation.md"))
    consumer = _read("docs/quant-autoresearch-consumer.md")
    prd = _read("PRD.md")
    agents = _read("AGENTS.md")

    assert "validator does not special-case `researched/`" in validation
    assert "validation does not treat it as special" in readme
    assert _flat("Moving a strategy to `tested/` requires the separate validation process") in _flat(readme)

    assert "Validation is not based on `researched/`, package manifests, or family/variant" in consumer
    assert re.search(
        r"Old artifacts that need validation should be copied into a normal\s+candidate workspace",
        consumer,
    )

    assert "candidate workspaces driven by consumers" in prd
    assert "Promotion into `tested/` from `untested/` or `researched/`" in prd
    assert "The foundation never auto-promotes" in prd

    assert "Do not treat `researched/` as market validated" in agents
    assert re.search(
        r"Move from `researched/` to `tested/` only through the separate validation\s+process",
        agents,
    )
