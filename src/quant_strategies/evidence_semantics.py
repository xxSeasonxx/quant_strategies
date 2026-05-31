from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


EvidenceClass = Literal["quick_run_diagnostic", "validation_advisory"]
StrategyContract = Literal["decision"]
RunnerReturnModel = Literal["trade_result.sum_signed_trade_activity_net"]
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


def replayable_from_artifacts_for_profile(artifact_profile: str) -> bool:
    if artifact_profile in {"diagnostic", "summary"}:
        return False
    if artifact_profile == "full":
        return True
    raise ValueError(f"unknown artifact profile: {artifact_profile}")


def funding_model_for_data_kind(data_kind: str) -> FundingModel:
    if data_kind == "crypto_perp_funding":
        return "linear_additive_adjustment"
    return "none"


def trade_result_metric_semantics(data_kind: str) -> dict[str, dict[str, object]]:
    funding_model = funding_model_for_data_kind(data_kind)
    base = "signed target-weighted trade activity; not portfolio NAV"
    shared = {
        "unit": "decimal_fraction",
        "base": base,
        "backend": "execution_kernel",
        "comparability": "not_comparable_to_nav_path_returns_without_backend_agreement_test",
        "tolerance": None,
    }
    semantics = (
        MetricSemantics(
            name="trade_result.sum_signed_trade_activity_gross",
            aggregation="sum over trades of signed target-weighted price return",
            return_path_model="linear_per_trade_price_return",
            asymmetry="not comparable to NAV-path total return without an explicit backend agreement test",
            **shared,
        ),
        MetricSemantics(
            name="trade_result.sum_signed_trade_activity_funding",
            aggregation="sum over engine-held intervals of supplied funding adjustments",
            return_path_model=funding_model,
            asymmetry=(
                "linear additive funding adjustment; not a cash ledger or "
                "portfolio funding accrual model"
            ),
            **shared,
        ),
        MetricSemantics(
            name="trade_result.sum_signed_trade_activity_cost",
            aggregation="sum over trades of target-weighted round-trip fee and slippage cost",
            return_path_model="linear_round_trip_bps_cost",
            asymmetry="linear cost approximation; not venue-specific execution cost accounting",
            **shared,
        ),
        MetricSemantics(
            name="trade_result.sum_signed_trade_activity_net",
            aggregation="gross plus funding minus cost, summed over trades",
            return_path_model="linear_trade_activity_sum",
            asymmetry="not comparable to NAV-path total return without an explicit backend agreement test",
            **shared,
        ),
    )
    return {item.name: item.model_dump(mode="json") for item in semantics}


def runner_evidence_semantics(data_kind: str) -> dict[str, object]:
    return {
        "evidence_class": "quick_run_diagnostic",
        "strategy_contract": "decision",
        "return_model": "trade_result.sum_signed_trade_activity_net",
        "funding_model": funding_model_for_data_kind(data_kind),
        "metric_semantics": trade_result_metric_semantics(data_kind),
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


def causality_evidence_fields(
    data_availability_status: object,
    *,
    emitted_replay_verified: bool,
    strict_no_emission_verified: bool,
) -> dict[str, object]:
    """Single home for the availability->causal-verification policy.

    Shared by the row contract (`data_contract`) and the runner artifacts so the
    mapping from data availability + replay results to the audited
    ``causality_verified`` flag lives in exactly one place. ``causality_verified``
    is True only when the information set is complete *and* both replay halves
    verified: the emitted-replay subset check and the strict no-emission
    suppression check. A run can never claim full causal verification it did not
    perform.
    """
    if data_availability_status == "complete":
        emitted = bool(emitted_replay_verified)
        strict = bool(strict_no_emission_verified)
        verified = emitted and strict
        warnings: list[str] = []
        if emitted and not strict:
            # Emitted-replay subset check passed but strict suppression replay did
            # not run; surface that the run did not earn full causal verification.
            warnings.append("strict_suppression_replay_not_verified")
        if not verified:
            warnings.append("runner_causality_not_verified")
    else:
        emitted = False
        strict = False
        verified = False
        availability_warning = {
            "invalid": "available_at_invalid",
            "partial": "available_at_partial",
        }.get(str(data_availability_status), "available_at_missing")
        warnings = [availability_warning, "runner_causality_not_verified"]
    return {
        "causality_verified": verified,
        "emitted_replay_verified": emitted,
        "strict_no_emission_verified": strict,
        "evidence_quality_warnings": warnings,
    }
