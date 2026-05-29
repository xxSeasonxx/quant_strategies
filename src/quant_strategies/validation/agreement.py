from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from quant_strategies.core.config import CostModelConfig
from quant_strategies.decisions import StrategyDecision
from quant_strategies.validation.backends import MetricValue
from quant_strategies.validation.config import ScenarioRunConfig
from quant_strategies.validation.vectorbtpro_backend import VectorBTProBackend

AgreementStatus = Literal["pass", "fail", "skipped", "inconclusive", "unavailable"]


@dataclass(frozen=True)
class AgreementResult:
    """Outcome of cross-checking the engine verdict kernel against VectorBT Pro.

    Only ``fail`` should fail a validation run. ``skipped`` means the scenario is
    outside the regime where the engine's linear per-trade sum equals a NAV path
    (so a divergence would be meaningless, not a bug); ``inconclusive`` means vbt
    could not run the case; ``unavailable`` means vbt is not importable.
    """

    status: AgreementStatus
    note: str = ""
    engine_return: float | None = None
    vbt_return: float | None = None
    abs_deviation: float | None = None
    tolerance_abs: float = 0.0
    tolerance_rel: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "note": self.note,
            "engine_return": self.engine_return,
            "vbt_return": self.vbt_return,
            "abs_deviation": self.abs_deviation,
            "tolerance_abs": self.tolerance_abs,
            "tolerance_rel": self.tolerance_rel,
        }


def compare(
    engine_return: float,
    vbt_return: float,
    *,
    tolerance_abs: float,
    tolerance_rel: float,
) -> AgreementResult:
    """Pure comparator: pass iff ``|engine - vbt| <= atol + rtol*|vbt|``."""
    deviation = abs(engine_return - vbt_return)
    tolerance = tolerance_abs + tolerance_rel * abs(vbt_return)
    status: AgreementStatus = "pass" if deviation <= tolerance else "fail"
    note = (
        "engine and vbt price paths agree within tolerance"
        if status == "pass"
        else "engine vs vbt price-path divergence exceeds tolerance"
    )
    return AgreementResult(
        status=status,
        note=note,
        engine_return=engine_return,
        vbt_return=vbt_return,
        abs_deviation=deviation,
        tolerance_abs=tolerance_abs,
        tolerance_rel=tolerance_rel,
    )


def evaluate_agreement(
    *,
    engine_metrics: Mapping[str, MetricValue],
    decisions: list[StrategyDecision],
    rows: Sequence[Mapping[str, Any]],
    config: ScenarioRunConfig,
    tolerance_abs: float,
    tolerance_rel: float,
) -> AgreementResult:
    """Cross-check the engine verdict's price path against VectorBT Pro.

    The verdict gates on the engine's linear per-trade sum (``net_return``). That
    sum equals a NAV path only for a single trade — for two or more trades the
    linear sum and vbt's compounded NAV are different objects, so a divergence
    would be expected rather than a bug. The oracle therefore runs only on
    single-trade scenarios and compares the engine's already-computed
    ``gross_return`` (the price path that feeds the gated ``net_return``) against
    vbt's zero-cost total return. Funding is excluded (it has a single
    implementation, so there is nothing to cross-check) and cost is excluded
    (both sides run at zero cost). The engine metrics are reused from the verdict
    run; the oracle does not re-screen.
    """
    trade_count = engine_metrics.get("trade_count")
    if trade_count != 1:
        return AgreementResult(
            status="skipped",
            note=f"not_single_trade:trade_count={trade_count}",
        )

    engine_gross = engine_metrics.get("gross_return")
    if not isinstance(engine_gross, (int, float)) or isinstance(engine_gross, bool):
        return AgreementResult(status="inconclusive", note="engine_gross_return_missing")

    # Run vbt on the same case with costs zeroed so only the price path is compared.
    zero_cost_config = config.model_copy(update={"cost_model": CostModelConfig()})
    vbt_result = VectorBTProBackend().run(
        decisions=list(decisions), rows=rows, config=zero_cost_config
    )
    if vbt_result.status == "unavailable":
        return AgreementResult(status="unavailable", note=_first_warning(vbt_result.warnings))
    if vbt_result.status == "unsupported":
        return AgreementResult(
            status="skipped",
            note="vbt_unsupported:" + ",".join(vbt_result.unsupported_semantics),
        )
    if vbt_result.status != "completed":
        return AgreementResult(status="inconclusive", note=_first_warning(vbt_result.warnings))

    vbt_return = vbt_result.metrics.get("net_return")
    if not isinstance(vbt_return, (int, float)) or isinstance(vbt_return, bool):
        return AgreementResult(status="inconclusive", note="vbt_net_return_missing")

    return compare(
        float(engine_gross),
        float(vbt_return),
        tolerance_abs=tolerance_abs,
        tolerance_rel=tolerance_rel,
    )


def _first_warning(warnings: tuple[str, ...]) -> str:
    return warnings[0] if warnings else ""
