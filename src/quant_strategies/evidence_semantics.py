from __future__ import annotations

from typing import Literal


EvidenceClass = Literal["runner_smoke", "validation_advisory"]
StrategyContract = Literal["decision"]
RunnerReturnModel = Literal["smoke_score.sum_weighted_trade_net_return"]
FundingModel = Literal["none", "linear_additive_adjustment"]


def funding_model_for_data_kind(data_kind: str) -> FundingModel:
    if data_kind == "crypto_perp_funding":
        return "linear_additive_adjustment"
    return "none"


def runner_evidence_semantics(data_kind: str) -> dict[str, object]:
    return {
        "evidence_class": "runner_smoke",
        "strategy_contract": "decision",
        "return_model": "smoke_score.sum_weighted_trade_net_return",
        "funding_model": funding_model_for_data_kind(data_kind),
        "promotion_eligible": False,
        "paper_trade_eligible": False,
        "live_eligible": False,
        "requires_manual_approval": True,
    }


def validation_evidence_semantics() -> dict[str, object]:
    return {
        "evidence_class": "validation_advisory",
        "promotion_eligible": False,
        "paper_trade_eligible": False,
        "live_eligible": False,
        "requires_manual_approval": True,
    }
