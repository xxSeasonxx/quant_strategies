from __future__ import annotations

from types import MappingProxyType

import pytest

from quant_strategies.boundary import FrozenMapping, frozen_params, frozen_rows


def test_frozen_rows_are_isolated_and_immutable():
    rows = [{"symbol": "SPY", "nested": {"levels": [1, 2]}, "tags": {"a", "b"}}]

    frozen = frozen_rows(rows)
    rows[0]["symbol"] = "QQQ"
    rows[0]["nested"]["levels"].append(3)
    rows[0]["tags"].add("c")

    assert frozen[0]["symbol"] == "SPY"
    assert frozen[0]["nested"]["levels"] == (1, 2)
    assert frozen[0]["tags"] == frozenset({"a", "b"})
    assert isinstance(frozen[0], FrozenMapping)
    with pytest.raises(TypeError):
        frozen[0]["symbol"] = "IWM"
    with pytest.raises(TypeError):
        frozen[0]["nested"]["extra"] = True
    with pytest.raises(TypeError):
        frozen[0]["nested"]["levels"][0] = 99


def test_frozen_params_are_isolated_and_immutable():
    params = {"threshold": 1.0, "nested": {"levels": [1, 2]}}

    frozen = frozen_params(params)
    params["threshold"] = 2.0
    params["nested"]["levels"].append(3)

    assert frozen["threshold"] == 1.0
    assert frozen["nested"]["levels"] == (1, 2)
    assert isinstance(frozen, FrozenMapping)
    with pytest.raises(TypeError):
        frozen["threshold"] = 3.0


def test_boundary_freezing_is_idempotent_for_frozen_inputs():
    rows = frozen_rows([{"symbol": "SPY", "nested": {"levels": [1, 2]}}])
    params = frozen_params({"threshold": 1.0, "nested": {"levels": [1, 2]}})

    assert frozen_rows(rows) is rows
    assert frozen_params(params) is params


def test_external_mapping_proxy_is_copied_before_freezing():
    backing = {"threshold": 1.0, "nested": {"levels": [1, 2]}}
    external_proxy = MappingProxyType(backing)

    frozen = frozen_params(external_proxy)
    backing["threshold"] = 2.0
    backing["nested"]["levels"].append(3)

    assert frozen["threshold"] == 1.0
    assert frozen["nested"]["levels"] == (1, 2)


def test_frozen_mapping_storage_cannot_be_reassigned():
    frozen = frozen_params({"threshold": 1.0})

    with pytest.raises(AttributeError):
        frozen._data = MappingProxyType({"threshold": 2.0})
    with pytest.raises(AttributeError):
        del frozen._data
    assert frozen["threshold"] == 1.0
