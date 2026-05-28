from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any


class FrozenMapping(Mapping[str, Any]):
    __slots__ = ("_data",)

    def __init__(self, values: Mapping[str, Any]) -> None:
        object.__setattr__(self, "_data", MappingProxyType(dict(values)))

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("frozen mapping cannot be mutated")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("frozen mapping cannot be mutated")

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __iter__(self):
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:
        return repr(self._data)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Mapping):
            return dict(self.items()) == dict(other.items())
        return NotImplemented


def frozen_params(params: Mapping[str, Any]) -> FrozenMapping:
    return _freeze_mapping(params)


def frozen_rows(rows: Sequence[Mapping[str, Any]]) -> tuple[FrozenMapping, ...]:
    if isinstance(rows, tuple) and all(isinstance(row, FrozenMapping) for row in rows):
        return rows
    return tuple(_freeze_mapping(row) for row in rows)


def _freeze_mapping(value: Mapping[str, Any]) -> FrozenMapping:
    if isinstance(value, FrozenMapping):
        return value
    return FrozenMapping({key: _freeze_value(item) for key, item in value.items()})


def _freeze_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if isinstance(value, list | tuple):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, set | frozenset):
        return frozenset(_freeze_value(item) for item in value)
    return value
