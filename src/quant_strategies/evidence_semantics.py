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
