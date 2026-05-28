from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ArtifactTrustTier = Literal["search_only", "audit_replayable"]
EvidenceClass = Literal["runner_smoke", "validation_advisory"]
StrategyContract = Literal["decision"]
RunnerReturnModel = Literal["smoke_score.sum_signed_trade_activity_net"]
FundingModel = Literal["none", "linear_additive_adjustment"]


class MetricSemantics(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    base: str = Field(min_length=1)
    aggregation: str = Field(min_length=1)
    backend: str = Field(min_length=1)
    return_path_model: str = Field(min_length=1)
    comparability: str = Field(min_length=1)
    tolerance: float | None = None
    asymmetry: str | None = None


def artifact_trust_tier_for_profile(artifact_profile: str) -> ArtifactTrustTier:
    if artifact_profile == "summary":
        return "search_only"
    if artifact_profile == "full":
        return "audit_replayable"
    raise ValueError(f"unknown artifact profile: {artifact_profile}")


def funding_model_for_data_kind(data_kind: str) -> FundingModel:
    if data_kind == "crypto_perp_funding":
        return "linear_additive_adjustment"
    return "none"


def smoke_score_metric_semantics(data_kind: str) -> dict[str, dict[str, object]]:
    funding_model = funding_model_for_data_kind(data_kind)
    base = "signed target-weighted trade activity; not portfolio NAV"
    shared = {
        "unit": "decimal_fraction",
        "base": base,
        "backend": "smoke_engine",
        "comparability": "not_comparable_to_nav_path_returns_without_backend_agreement_test",
        "tolerance": None,
    }
    semantics = (
        MetricSemantics(
            name="smoke_score.sum_signed_trade_activity_gross",
            aggregation="sum over trades of signed target-weighted price return",
            return_path_model="linear_per_trade_price_return",
            asymmetry="not comparable to NAV-path total return without an explicit backend agreement test",
            **shared,
        ),
        MetricSemantics(
            name="smoke_score.sum_signed_trade_activity_funding",
            aggregation="sum over engine-held intervals of supplied funding adjustments",
            return_path_model=funding_model,
            asymmetry=(
                "linear additive funding adjustment; not a cash ledger or "
                "portfolio funding accrual model"
            ),
            **shared,
        ),
        MetricSemantics(
            name="smoke_score.sum_signed_trade_activity_cost",
            aggregation="sum over trades of target-weighted round-trip fee and slippage cost",
            return_path_model="linear_round_trip_bps_cost",
            asymmetry="linear cost approximation; not venue-specific execution cost accounting",
            **shared,
        ),
        MetricSemantics(
            name="smoke_score.sum_signed_trade_activity_net",
            aggregation="gross plus funding minus cost, summed over trades",
            return_path_model="linear_trade_activity_sum",
            asymmetry="not comparable to NAV-path total return without an explicit backend agreement test",
            **shared,
        ),
    )
    return {item.name: item.model_dump(mode="json") for item in semantics}


def runner_evidence_semantics(data_kind: str) -> dict[str, object]:
    return {
        "evidence_class": "runner_smoke",
        "strategy_contract": "decision",
        "return_model": "smoke_score.sum_signed_trade_activity_net",
        "funding_model": funding_model_for_data_kind(data_kind),
        "metric_semantics": smoke_score_metric_semantics(data_kind),
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
