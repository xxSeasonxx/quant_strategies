from __future__ import annotations

import dataclasses
from datetime import date

import pytest
from tests.test_runner_api_cli import rows, write_low_sample_config, write_strategy

from quant_strategies.core import execution
from quant_strategies.core.data_loader import (
    LoadedData,
    data_load_fingerprint,
    data_load_identity,
)
from quant_strategies.core.errors import PreparedDataMismatchError
from quant_strategies.core.execution import execute_strategy_run
from quant_strategies.data_contract import NormalizedRows
from quant_strategies.runner import PreparedRunData, prepare_run_data, run_config
from quant_strategies.runner import prepared as prepared_module
from quant_strategies.runner.config import load_config

CLOSES = (100.0, 101.0, 102.0, 104.0)


def _spec(tmp_path):
    config = load_config(write_low_sample_config(tmp_path), repo_root=tmp_path)
    return config.to_execution_spec()


# (e) producer: load once, pair with the data-identity fingerprint.
def test_prepare_run_data_loads_once_and_fingerprints(tmp_path, monkeypatch):
    write_strategy(tmp_path)
    config_path = write_low_sample_config(tmp_path)
    spec = load_config(config_path, repo_root=tmp_path).to_execution_spec()
    fixed = LoadedData(rows=rows(*CLOSES))
    calls: list[object] = []

    def fake_load(config, **_kwargs):
        calls.append(config)
        return fixed

    monkeypatch.setattr(prepared_module, "load_data", fake_load)

    prepared = prepare_run_data(config_path, repo_root=tmp_path)

    assert prepared.loaded_data is fixed
    assert prepared.fingerprint == data_load_fingerprint(spec)
    assert len(calls) == 1


# Seam: execute_strategy_run must not touch load_data when preloaded is supplied.
def test_execute_strategy_run_skips_load_when_preloaded(tmp_path, monkeypatch):
    write_strategy(tmp_path)
    spec = _spec(tmp_path)
    normalized = NormalizedRows.from_rows(spec, rows(*CLOSES))

    def boom(*_args, **_kwargs):
        raise AssertionError("load_data must not run when preloaded is supplied")

    monkeypatch.setattr(execution, "load_data", boom)

    result = execute_strategy_run(
        spec,
        repo_root=tmp_path,
        preloaded=LoadedData(rows=normalized, normalized_rows=normalized),
    )

    assert result.normalized_rows is normalized


# (a) run_config reuses prepared data (no reload) and still completes; control reloads.
def test_run_config_with_prepared_skips_reload(tmp_path, monkeypatch):
    write_strategy(tmp_path)
    config_path = write_low_sample_config(tmp_path)
    spec = load_config(config_path, repo_root=tmp_path).to_execution_spec()
    load_calls = {"n": 0}

    def counting_load(config, **_kwargs):
        load_calls["n"] += 1
        return LoadedData(rows=rows(*CLOSES))

    monkeypatch.setattr(execution, "load_data", counting_load)
    prepared = PreparedRunData(
        loaded_data=LoadedData(rows=rows(*CLOSES)),
        fingerprint=data_load_fingerprint(spec),
    )

    reused = run_config(config_path, repo_root=tmp_path, prepared=prepared)
    assert reused.outcome.completed is True
    assert load_calls["n"] == 0

    fresh = run_config(config_path, repo_root=tmp_path)
    assert fresh.outcome.completed is True
    assert load_calls["n"] == 1


# (b) reuse against an incompatible config fails closed by raising (not a failed RunResult).
def test_run_config_prepared_mismatch_raises(tmp_path, monkeypatch):
    write_strategy(tmp_path)
    config_path = write_low_sample_config(tmp_path)
    spec = load_config(config_path, repo_root=tmp_path).to_execution_spec()
    other_spec = dataclasses.replace(
        spec, data=spec.data.model_copy(update={"end": date(2024, 1, 8)})
    )

    def boom(*_args, **_kwargs):
        raise AssertionError("load must never run on a fingerprint mismatch")

    monkeypatch.setattr(execution, "load_data", boom)
    prepared = PreparedRunData(
        loaded_data=LoadedData(rows=rows(*CLOSES)),
        fingerprint=data_load_fingerprint(other_spec),
    )

    with pytest.raises(PreparedDataMismatchError):
        run_config(config_path, repo_root=tmp_path, prepared=prepared)


# (c) reuse yields identical scored evidence to a fresh load of the same window.
def test_run_config_prepared_matches_fresh_load(tmp_path, monkeypatch):
    write_strategy(tmp_path)
    config_path = write_low_sample_config(tmp_path)
    spec = load_config(config_path, repo_root=tmp_path).to_execution_spec()
    monkeypatch.setattr(
        execution, "load_data", lambda config, **_kwargs: LoadedData(rows=rows(*CLOSES))
    )

    fresh = run_config(config_path, repo_root=tmp_path)
    prepared = PreparedRunData(
        loaded_data=LoadedData(rows=rows(*CLOSES)),
        fingerprint=data_load_fingerprint(spec),
    )
    reused = run_config(config_path, repo_root=tmp_path, prepared=prepared)

    assert fresh.outcome.completed is True
    assert reused.outcome.completed is True
    assert fresh.foundation is not None and reused.foundation is not None
    assert reused.foundation.summary_payload() == fresh.foundation.summary_payload()


# (d) the fingerprint covers exactly the data-identity inputs — no more, no less.
def test_data_load_fingerprint_covers_identity_fields(tmp_path):
    write_strategy(tmp_path)
    base = _spec(tmp_path)
    base_fp = data_load_fingerprint(base)

    data = base.data
    identity_variants = {
        "kind": dataclasses.replace(
            base, data=data.model_copy(update={"kind": "crypto_perp_funding"})
        ),
        "dataset": dataclasses.replace(
            base, data=data.model_copy(update={"dataset": "equity_5min"})
        ),
        "symbols": dataclasses.replace(base, data=data.model_copy(update={"symbols": ("QQQ",)})),
        "start": dataclasses.replace(
            base, data=data.model_copy(update={"start": date(2024, 1, 2)})
        ),
        "end": dataclasses.replace(base, data=data.model_copy(update={"end": date(2024, 1, 8)})),
        "load_start": dataclasses.replace(
            base, data=data.model_copy(update={"load_start": date(2023, 12, 1)})
        ),
        "load_end": dataclasses.replace(
            base, data=data.model_copy(update={"load_end": date(2024, 2, 1)})
        ),
        "fill_price": dataclasses.replace(
            base, fill_model=base.fill_model.model_copy(update={"price": "open"})
        ),
        "capacity_mode": dataclasses.replace(
            base, capacity_model=base.capacity_model.model_copy(update={"mode": "off"})
        ),
    }
    for label, variant in identity_variants.items():
        assert data_load_fingerprint(variant) != base_fp, label

    # Inputs that do NOT determine the loaded/normalized panel must not change it.
    non_identity = {
        "params": dataclasses.replace(base, params={"weight": 99.0}),
        "strategy_id": dataclasses.replace(base, strategy_id="other"),
        "cost_model": dataclasses.replace(
            base, cost_model=base.cost_model.model_copy(update={"fee_bps_per_side": 9.0})
        ),
        "risk_budget": dataclasses.replace(
            base, risk_budget=base.risk_budget.model_copy(update={"target_volatility": 0.5})
        ),
    }
    for label, variant in non_identity.items():
        assert data_load_fingerprint(variant) == base_fp, label

    # Sanity: the identity payload exposes the same field set the fingerprint hashes.
    assert set(data_load_identity(base)) == {
        "kind",
        "dataset",
        "symbols",
        "start",
        "end",
        "load_start",
        "load_end",
        "fill_price",
        "capacity_mode",
    }


# Reusing ONE PreparedRunData across many runs is a pure replay (no cross-run mutation
# of the shared rows / normalized_rows / mark frame).
def test_run_config_prepared_reused_across_runs_is_pure_replay(tmp_path, monkeypatch):
    write_strategy(tmp_path)
    config_path = write_low_sample_config(tmp_path)
    spec = load_config(config_path, repo_root=tmp_path).to_execution_spec()

    def boom(*_args, **_kwargs):
        raise AssertionError("reused runs must not reload")

    monkeypatch.setattr(execution, "load_data", boom)
    normalized = NormalizedRows.from_rows(spec, rows(*CLOSES))
    prepared = PreparedRunData(
        loaded_data=LoadedData(rows=normalized, normalized_rows=normalized),
        fingerprint=data_load_fingerprint(spec),
    )

    summaries = []
    for _ in range(3):
        result = run_config(config_path, repo_root=tmp_path, prepared=prepared)
        assert result.outcome.completed is True
        assert result.foundation is not None
        summaries.append(result.foundation.summary_payload())

    assert summaries[0] == summaries[1] == summaries[2]


# A fingerprint mismatch fails closed BEFORE any side effect: no result dir is created.
def test_run_config_prepared_mismatch_creates_no_result_dir(tmp_path, monkeypatch):
    write_strategy(tmp_path)
    config_path = write_low_sample_config(tmp_path)
    spec = load_config(config_path, repo_root=tmp_path).to_execution_spec()
    other_spec = dataclasses.replace(
        spec, data=spec.data.model_copy(update={"end": date(2024, 1, 8)})
    )

    def boom(*_args, **_kwargs):
        raise AssertionError("load must never run on a fingerprint mismatch")

    monkeypatch.setattr(execution, "load_data", boom)
    prepared = PreparedRunData(
        loaded_data=LoadedData(rows=rows(*CLOSES)),
        fingerprint=data_load_fingerprint(other_spec),
    )

    with pytest.raises(PreparedDataMismatchError):
        run_config(config_path, repo_root=tmp_path, prepared=prepared)

    results_dir = tmp_path / "results"
    assert not results_dir.exists() or not any(results_dir.iterdir())
