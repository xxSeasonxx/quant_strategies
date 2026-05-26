from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from types import MappingProxyType
from typing import Any


FrozenMapping = MappingProxyType[str, Any]


def frozen_params(params: Mapping[str, Any]) -> FrozenMapping:
    return _freeze_mapping(deepcopy(dict(params)))


def frozen_rows(rows: Sequence[Mapping[str, Any]]) -> tuple[FrozenMapping, ...]:
    return tuple(_freeze_mapping(deepcopy(dict(row))) for row in rows)


def _freeze_mapping(value: Mapping[str, Any]) -> FrozenMapping:
    return MappingProxyType({key: _freeze_value(item) for key, item in value.items()})


def _freeze_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if isinstance(value, list | tuple):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, set | frozenset):
        return frozenset(_freeze_value(item) for item in value)
    return value
