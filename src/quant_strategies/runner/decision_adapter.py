from __future__ import annotations

from typing import Any

from quant_strategies.decisions import StrategyDecision
from quant_strategies.runner.errors import RequestBuildError


def decisions_to_signal_rows(decisions: list[StrategyDecision]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for decision in decisions:
        if decision.target.direction == "flat":
            raise RequestBuildError(
                f"smoke engine cannot represent flat target for {decision.instrument.symbol}"
            )
        if decision.target.sizing_kind != "target_weight":
            raise RequestBuildError(
                "smoke engine decision adapter requires target_weight sizing: "
                f"{decision.instrument.symbol}"
            )

        metadata = decision.model_dump(mode="json")["metadata"]
        row: dict[str, Any] = {
            "symbol": decision.instrument.symbol,
            "decision_time": decision.decision_time,
            "as_of_time": decision.as_of_time,
            "side": decision.target.direction,
            "weight": decision.target.size,
            "max_hold_bars": decision.exit_policy.max_hold_bars,
            "metadata": metadata,
        }
        if decision.exit_policy.stop_loss_bps is not None:
            row["stop_loss_bps"] = decision.exit_policy.stop_loss_bps
        if decision.exit_policy.take_profit_bps is not None:
            row["take_profit_bps"] = decision.exit_policy.take_profit_bps
        if decision.exit_policy.trailing_stop_bps is not None:
            row["trailing_stop_bps"] = decision.exit_policy.trailing_stop_bps
        rows.append(row)
    return rows
