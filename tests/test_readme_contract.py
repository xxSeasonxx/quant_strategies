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
    )
    for term in forbidden_terms:
        assert term not in text
    assert re.search(r"(?<!max_)hold" + "_bars", text) is None

    assert "generate_decisions(rows, params) -> list[StrategyDecision]" in text
    assert "validation_decision.json" in text
    assert "mechanical_pass" in text
    assert "smoke_score.sum_weighted_trade_*" in text
