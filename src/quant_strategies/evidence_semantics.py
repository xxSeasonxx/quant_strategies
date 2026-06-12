from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

EvidenceClass = Literal["quick_run_diagnostic", "validation_advisory"]
StrategyContract = Literal["target_book"]
RunnerReturnModel = Literal["portfolio_book_nav_path"]
FundingModel = Literal["none", "netted_cash_funding_accrual"]


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
        return "netted_cash_funding_accrual"
    return "none"


def trade_result_metric_semantics(data_kind: str) -> dict[str, dict[str, object]]:
    """Semantics for the book's realized NAV attribution totals.

    These describe the single causal netted-book walk (`core.portfolio_foundation`):
    the per-trade ledger and these totals are one model of money, derived from the same
    NAV path. The retired per-trade ``sum_signed_trade_activity_*`` linear-sum metrics
    no longer exist.
    """
    funding_model = funding_model_for_data_kind(data_kind)
    base = "realized attribution of the single netted-book NAV walk, as a fraction of NAV"
    shared = {
        "unit": "decimal_fraction",
        "base": base,
        "backend": "portfolio_book_spine",
        "comparability": "reconciles_with_nav_path_realized_pnl",
        "tolerance": None,
    }
    semantics = (
        MetricSemantics(
            name="nav_attribution.sum_gross_return",
            aggregation="sum over book round-trips of realized price proceeds / NAV",
            return_path_model="netted_book_price_return",
            asymmetry="realized round-trip price attribution of the netted book NAV path",
            **shared,
        ),
        MetricSemantics(
            name="nav_attribution.sum_funding_return",
            aggregation="sum over book round-trips of accrued funding cash / NAV",
            return_path_model=funding_model,
            asymmetry="netted cash funding accrual on the net held position",
            **shared,
        ),
        MetricSemantics(
            name="nav_attribution.sum_cost_return",
            aggregation=(
                "sum over book round-trips of total traded cost on the netted delta / NAV"
            ),
            return_path_model="netted_book_delta_cost",
            asymmetry=(
                "total cost charged on the traded delta of the netted book, including impact"
            ),
            **shared,
        ),
        MetricSemantics(
            name="nav_attribution.sum_impact_return",
            aggregation="sum over book round-trips of market-impact cost / NAV",
            return_path_model="netted_book_adv_impact_cost",
            asymmetry="component of sum_cost_return, not a second subtraction from net",
            **shared,
        ),
        MetricSemantics(
            name="nav_attribution.sum_net_return",
            aggregation="gross plus funding minus cost, summed over book round-trips",
            return_path_model="netted_book_nav_attribution",
            asymmetry="reconciles with the NAV path's realized PnL",
            **shared,
        ),
    )
    return {item.name: item.model_dump(mode="json") for item in semantics}


def runner_evidence_semantics(data_kind: str) -> dict[str, object]:
    return {
        "evidence_class": "quick_run_diagnostic",
        "strategy_contract": "target_book",
        "return_model": "portfolio_book_nav_path",
        "funding_model": funding_model_for_data_kind(data_kind),
        "metric_semantics": trade_result_metric_semantics(data_kind),
        "paper_trade_eligible": False,
        "live_eligible": False,
        "requires_manual_approval": True,
    }


def validation_evidence_semantics() -> dict[str, object]:
    return {
        "evidence_class": "validation_advisory",
        "paper_trade_eligible": False,
        "live_eligible": False,
        "requires_manual_approval": True,
    }


def causality_evidence_fields(
    data_availability_status: object,
    *,
    causality_check: str = "micro",
    deterministic_replay_verified: bool | None = None,
    emitted_replay_verified: bool,
    strict_no_emission_verified: bool,
    strict_replay_capped: bool = False,
    strict_probe_count: int | None = None,
    strict_probe_limit: int | None = None,
    skipped_probe_count: int = 0,
    skipped_probe_reasons: tuple[str, ...] = (),
    replay_scope: str | None = None,
    candidate_probe_count: int | None = None,
    selected_probe_count: int | None = None,
    elapsed_seconds: float | None = None,
    timeout_seconds: float | None = None,
    timed_out: bool = False,
    replay_warning: str | None = None,
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
        deterministic = (
            emitted and strict
            if deterministic_replay_verified is None
            else bool(deterministic_replay_verified)
        )
        verified = emitted and strict
        warnings: list[str] = []
        if causality_check == "off":
            warnings.append("causality_replay_skipped")
        if emitted and not strict:
            # Emitted-replay subset check passed but strict suppression replay did
            # not run; surface that the run did not earn full causal verification.
            warnings.append("strict_suppression_replay_not_verified")
        if strict_replay_capped:
            warnings.append("strict_replay_capped")
        if replay_warning:
            warnings.append(replay_warning)
        if not verified:
            warnings.append("runner_causality_not_verified")
    else:
        deterministic = False
        emitted = False
        strict = False
        verified = False
        availability_warning = {
            "invalid": "available_at_invalid",
            "partial": "available_at_partial",
        }.get(str(data_availability_status), "available_at_missing")
        warnings = [availability_warning, "runner_causality_not_verified"]
    return {
        "causality_check": causality_check,
        "causality_verified": verified,
        "deterministic_replay_verified": deterministic,
        "emitted_replay_verified": emitted,
        "strict_no_emission_verified": strict,
        "strict_replay_capped": bool(strict_replay_capped),
        "strict_probe_count": strict_probe_count,
        "strict_probe_limit": strict_probe_limit,
        "skipped_probe_count": int(skipped_probe_count),
        "skipped_probe_reasons": list(skipped_probe_reasons),
        "evidence_quality_warnings": warnings,
        "replay_scope": replay_scope or causality_check,
        "candidate_probe_count": candidate_probe_count,
        "selected_probe_count": selected_probe_count,
        "elapsed_seconds": elapsed_seconds,
        "timeout_seconds": timeout_seconds,
        "timed_out": bool(timed_out),
        "replay_warning": replay_warning,
    }
