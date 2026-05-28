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
    assert "[paper_readiness]" in text
    assert "min_windows = 2" in text
    assert "min_total_trades = 30" in text
    assert "max_stressed_net_loss = -0.02" in text
    assert "max_fill_lag_net_loss = -0.02" in text
    assert "smoke_score.sum_signed_trade_activity_*" in text
    assert "smoke_unverified" in text
    assert "causality_verified" in text
