from __future__ import annotations

import re
from pathlib import Path


def test_readme_uses_generic_foundation_contract_language():
    text = Path("README.md").read_text()

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

    assert "generate_decisions(rows, params) -> list[StrategyDecision]" in text
    assert "validation_decision.json" in text
    assert "quant-strategies validate path/to/candidate/validation.toml" in text
    assert "validation does not treat it as special" in text
    assert "hard_no" in text
    assert "mechanical_pass" in text
    assert "watchlist" in text
    assert "mechanical_review_candidate" in text
    assert "unsupported execution semantics is a `hard_no`" in text
    assert "Validation backend summaries include `metric_semantics`" in text
    assert "[paper_readiness]" in text
    assert "min_windows = 2" in text
    assert "min_total_trades = 30" in text
    assert "max_stressed_net_loss = -0.02" in text
    assert "max_fill_lag_net_loss = -0.02" in text
    assert "smoke_score.sum_signed_trade_activity_*" in text
    assert "metric_semantics" in text
    assert "artifact_trust_tier" in text
    assert "search_only" in text
    assert "audit_replayable" in text
    assert "smoke_unverified" in text
    assert "causality_verified" in text
    assert "decision_id" in text
    assert "decisions.extended_ontology" in text
    assert "target_notional" in text
    assert "target_contracts" in text
    assert "target_vol" in text
    assert "multiple_testing_not_corrected_advisory_only" in text
    assert "deflation_not_evaluated" not in text
    assert "backend_capability_matrix.json" not in text
    assert "Explicitly extended decisions are rejected by unsupported" in text


def test_prd_matches_runner_public_api_contract():
    prd = Path("PRD.md").read_text()
    readme = Path("README.md").read_text()
    consumer = Path("docs/quant-autoresearch-consumer.md").read_text()

    assert "`quant_strategies.runner.run_config`" in prd
    assert "`quant_strategies.runner.RunResult`" in prd
    assert "The public consumer surface is re-exported" not in prd
    assert "top-level facade" in prd

    assert "`quant_strategies.runner.run_config`" in readme
    assert "`quant_strategies.runner.RunResult`" in readme
    assert "`quant_strategies.runner.run_config`" in consumer
    assert "`quant_strategies.runner.RunResult`" in consumer
    assert "decisions.extended_ontology" in consumer
    assert "multiple_testing_not_corrected_advisory_only" in consumer

    import quant_strategies

    assert not hasattr(quant_strategies, "run_config")


def test_docs_keep_validation_layout_agnostic_and_promotion_human_controlled():
    readme = Path("README.md").read_text()
    consumer = Path("docs/quant-autoresearch-consumer.md").read_text()
    prd = Path("PRD.md").read_text()
    agents = Path("AGENTS.md").read_text()

    assert "validator does not special-case `researched/`" in readme
    assert "validation does not treat it as special" in readme
    assert re.search(
        r"Moving a strategy to `tested/` requires the separate validation process\s+Season\s+approves",
        readme,
    )

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
