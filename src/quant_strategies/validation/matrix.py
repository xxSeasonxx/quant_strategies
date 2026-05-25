from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ScenarioKind = Literal["base", "cost", "cost_stress", "fill_lag", "parameter"]


class _FrozenDict(dict[str, Any]):
    __slots__ = ()

    def __init__(self, values: Mapping[str, Any]) -> None:
        super().__init__(values)

    def _immutable(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("frozen mapping cannot be mutated")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable


def _freeze_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _FrozenDict({key: _freeze_value(nested) for key, nested in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, set | frozenset):
        return frozenset(_freeze_value(item) for item in value)
    return value


class MatrixScenario(BaseModel):
    """Validation scenario with immutable section override maps.

    Empty params, cost_model, or fill_model maps mean the scenario does not
    override that section of the base validation config.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    kind: ScenarioKind
    required: bool = True
    params: dict[str, Any] = Field(default_factory=dict)
    cost_model: dict[str, Any] = Field(default_factory=dict)
    fill_model: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def freeze_override_maps(self) -> MatrixScenario:
        object.__setattr__(self, "params", _freeze_value(self.params))
        object.__setattr__(self, "cost_model", _freeze_value(self.cost_model))
        object.__setattr__(self, "fill_model", _freeze_value(self.fill_model))
        return self


def expand_validation_matrix(
    *,
    window_id: str,
    base_params: dict[str, Any],
    base_costs: dict[str, Any],
    base_fill: dict[str, Any],
) -> tuple[MatrixScenario, ...]:
    """Build v1 validation scenarios as override maps for one validation window."""

    scenarios: list[MatrixScenario] = [
        MatrixScenario(id=f"{window_id}/base", kind="base", params=base_params),
        MatrixScenario(id=f"{window_id}/realistic_costs", kind="cost", cost_model=base_costs),
        MatrixScenario(
            id=f"{window_id}/stressed_costs",
            kind="cost_stress",
            cost_model={
                "fee_bps_per_side": float(base_costs.get("fee_bps_per_side", 0.0)) * 2.0,
                "slippage_bps_per_side": float(base_costs.get("slippage_bps_per_side", 0.0))
                * 2.0,
            },
        ),
        MatrixScenario(
            id=f"{window_id}/fill_lag_plus_1",
            kind="fill_lag",
            fill_model={
                **base_fill,
                "entry_lag_bars": int(base_fill.get("entry_lag_bars", 1)) + 1,
            },
        ),
    ]
    for name, value in base_params.items():
        if isinstance(value, bool) or not isinstance(value, int | float):
            continue
        scenarios.append(
            MatrixScenario(
                id=f"{window_id}/param_{name}_down_10pct",
                kind="parameter",
                params={**base_params, name: float(value) * 0.9},
            )
        )
        scenarios.append(
            MatrixScenario(
                id=f"{window_id}/param_{name}_up_10pct",
                kind="parameter",
                params={**base_params, name: float(value) * 1.1},
            )
        )
        break
    return tuple(scenarios)
