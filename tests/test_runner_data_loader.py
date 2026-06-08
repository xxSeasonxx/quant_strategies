from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from quant_strategies.core import data_loader
from quant_strategies.core.errors import DataLoadError
from quant_strategies.runner.config import load_config

REPO_ROOT = Path(__file__).resolve().parents[1]


def row(symbol: str, close: float = 100.0, **extra: object) -> dict[str, object]:
    timestamp = datetime(2024, 1, 1, tzinfo=UTC)
    base = {
        "symbol": symbol,
        "timestamp": timestamp,
        "available_at": timestamp,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
    }
    base.update(extra)
    return base


def make_config(
    tmp_path: Path,
    *,
    kind: str = "bars",
    symbols: list[str] | None = None,
    dataset: str | None = "equity_1min",
    fill_price: str = "close",
    data_extra: str = "",
):
    strategy = tmp_path / "strategies" / "demo.py"
    strategy.parent.mkdir(parents=True, exist_ok=True)
    strategy.write_text("def generate_decisions(rows, params): return []\n")
    dataset_line = f'dataset = "{dataset}"\n' if dataset is not None else ""
    symbols_text = ", ".join(f'"{symbol}"' for symbol in (symbols or ["SPY"]))
    config_path = tmp_path / "run.toml"
    config_path.write_text(
        f'''
strategy_path = "strategies/demo.py"
strategy_id = "demo"

[data]
kind = "{kind}"
{dataset_line}symbols = [{symbols_text}]
start = "2024-01-01"
end = "2024-01-05"
{data_extra}

[fill_model]
price = "{fill_price}"
entry_lag_bars = 1

[cost_model]
fee_bps_per_side = 0.0
slippage_bps_per_side = 0.0

[output]
results_dir = "results"
'''.lstrip()
    )
    return load_config(config_path, repo_root=tmp_path)


def test_importing_data_loader_does_not_import_quant_data():
    env = os.environ.copy()
    src_path = str(REPO_ROOT / "src")
    pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = src_path if not pythonpath else os.pathsep.join((src_path, pythonpath))
    code = (
        "import sys\n"
        "import quant_strategies.core.data_loader\n"
        "loaded = [\n"
        "    name for name in sys.modules\n"
        "    if name == 'quant_data' or name.startswith('quant_data.')\n"
        "]\n"
        "assert not loaded, loaded\n"
    )

    subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, env=env, check=True)


def test_bars_adapter_loads_one_symbol_via_contract_loader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    config = make_config(tmp_path)
    engine = object()
    calls: list[tuple[object, str, str, bool]] = []

    def fake_load_strategy_bars(engine_arg, symbol, dataset, start, end, *, strict):
        calls.append((engine_arg, symbol, dataset, strict))
        return [row(symbol)]

    monkeypatch.setattr(data_loader.contract_loaders, "load_strategy_bars", fake_load_strategy_bars)

    loaded = data_loader.load_data(config, engine=engine)

    assert calls == [(engine, "SPY", "equity_1min", True)]
    assert [dict(item) for item in loaded.rows] == [row("SPY")]
    assert loaded.normalized_rows is not None
    assert loaded.rows == loaded.normalized_rows.projection_rows()


def test_bars_adapter_uses_explicit_load_window_when_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    config = make_config(
        tmp_path,
        data_extra='load_start = "2023-12-31"\nload_end = "2024-01-07"\n',
    )
    engine = object()
    calls: list[tuple[object, str, str, object, object, bool]] = []

    def fake_load_strategy_bars(engine_arg, symbol, dataset, start, end, *, strict):
        calls.append((engine_arg, symbol, dataset, start, end, strict))
        return [row(symbol)]

    monkeypatch.setattr(data_loader.contract_loaders, "load_strategy_bars", fake_load_strategy_bars)

    data_loader.load_data(config, engine=engine)

    assert calls == [
        (
            engine,
            "SPY",
            "equity_1min",
            config.data.load_start,
            config.data.load_end,
            True,
        )
    ]


def test_universe_adapter_preserves_upstream_row_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    config = make_config(tmp_path, symbols=["SPY", "QQQ"])
    calls: list[tuple[list[str], str, bool]] = []

    t_early = datetime(2024, 1, 1, tzinfo=UTC)
    t_late = datetime(2024, 1, 2, tzinfo=UTC)

    def fake_load_strategy_universe_bars(engine, symbols, dataset, start, end, *, strict):
        calls.append((symbols, dataset, strict))
        # Supplied order is deliberately sorted by NEITHER symbol (QQQ would lead)
        # NOR timestamp (the t_early row would lead); the boundary must preserve it
        # verbatim. The old adapter re-sorted symbol-first to ["QQQ", "SPY"].
        return [
            row("SPY", timestamp=t_late, available_at=t_late),
            row("QQQ", timestamp=t_early, available_at=t_early),
        ]

    monkeypatch.setattr(
        data_loader.contract_loaders,
        "load_strategy_universe_bars",
        fake_load_strategy_universe_bars,
    )

    loaded = data_loader.load_data(config, engine=object())

    assert calls == [(["SPY", "QQQ"], "equity_1min", True)]
    assert [(item["symbol"], item["timestamp"]) for item in loaded.rows] == [
        ("SPY", t_late),
        ("QQQ", t_early),
    ]


def test_load_data_returns_row_contract_issues_for_mixed_timestamp_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    config = make_config(tmp_path)
    available_at = datetime(2024, 1, 1, 9, 31, tzinfo=UTC)
    missing_timestamp = row("SPY", close=101.0, available_at=available_at)
    del missing_timestamp["timestamp"]

    def fake_load_strategy_bars(engine, symbol, dataset, start, end, *, strict):
        return [
            row(
                "SPY",
                close=102.0,
                timestamp=datetime(2024, 1, 2, tzinfo=UTC),
                available_at=available_at,
            ),
            missing_timestamp,
            row("SPY", close=103.0, timestamp="not-a-datetime", available_at=available_at),
        ]

    monkeypatch.setattr(data_loader.contract_loaders, "load_strategy_bars", fake_load_strategy_bars)

    loaded = data_loader.load_data(config, engine=object())

    assert loaded.normalized_rows is not None
    assert loaded.rows == loaded.normalized_rows.projection_rows()
    summary = loaded.normalized_rows.row_contract_summary()
    assert summary["issue_reasons"]["row_missing_required_field"] == 1
    assert summary["issue_reasons"]["row_invalid_timestamp"] == 1
    assert summary["missing_required_fields"] == {"timestamp": 1}


def test_loader_proxy_prefers_override_then_falls_back_to_real_module():
    # Use a real stdlib module to prove the unset-attr path imports the backing
    # module rather than relying on white-box internals.
    proxy = data_loader._LazyLoaderProxy("types", ("SimpleNamespace", "MappingProxyType"))
    sentinel = object()
    proxy.SimpleNamespace = lambda: sentinel

    import types as real_types

    assert proxy.resolve("SimpleNamespace")() is sentinel
    assert proxy.resolve("MappingProxyType") is real_types.MappingProxyType


def test_crypto_perp_funding_adapter_loads_funding_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    config = make_config(tmp_path, kind="crypto_perp_funding", symbols=["BTC-PERP"], dataset=None)
    calls: list[tuple[str, bool]] = []

    def fake_load_crypto(engine, symbol, start, end, *, strict):
        calls.append((symbol, strict))
        return [
            row(
                symbol,
                funding_rate=0.0001,
                funding_timestamp=row(symbol)["timestamp"],
                has_funding_event=True,
            )
        ]

    monkeypatch.setattr(data_loader.loader, "load_crypto_perp_bars_with_funding", fake_load_crypto)

    loaded = data_loader.load_data(config, engine=object())

    assert calls == [("BTC-PERP", True)]
    assert loaded.rows[0]["funding_rate"] == 0.0001


def test_crypto_perp_funding_adapter_uses_explicit_load_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    config = make_config(
        tmp_path,
        kind="crypto_perp_funding",
        symbols=["BTC-PERP"],
        dataset=None,
        data_extra='load_end = "2024-01-07"\n',
    )
    calls: list[tuple[str, object, object, bool]] = []

    def fake_load_crypto(engine, symbol, start, end, *, strict):
        calls.append((symbol, start, end, strict))
        return [
            row(
                symbol,
                funding_rate=0.0001,
                funding_timestamp=row(symbol)["timestamp"],
                has_funding_event=True,
            )
        ]

    monkeypatch.setattr(data_loader.loader, "load_crypto_perp_bars_with_funding", fake_load_crypto)

    data_loader.load_data(config, engine=object())

    assert calls == [("BTC-PERP", config.data.start, config.data.load_end, True)]


def test_forex_with_quotes_adapter_preserves_bid_ask_for_quote_fills(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    config = make_config(
        tmp_path, kind="forex_with_quotes", symbols=["EURUSD"], dataset=None, fill_price="quote"
    )
    calls: list[tuple[str, bool, bool]] = []

    def fake_load_fx(engine, symbol, start, end, *, strict, require_quotes):
        calls.append((symbol, strict, require_quotes))
        return [row(symbol, bid=1.0999, ask=1.1001, mid=1.1)]

    monkeypatch.setattr(data_loader.loader, "load_fx_bars_with_quotes", fake_load_fx)

    loaded = data_loader.load_data(config, engine=object())

    assert calls == [("EURUSD", True, True)]
    assert loaded.rows[0]["bid"] == 1.0999
    assert loaded.rows[0]["ask"] == 1.1001


def test_empty_loaded_data_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config = make_config(tmp_path)
    monkeypatch.setattr(
        data_loader.contract_loaders, "load_strategy_bars", lambda *args, **kwargs: []
    )

    with pytest.raises(DataLoadError, match="no rows"):
        data_loader.load_data(config, engine=object())


def test_strict_loader_failure_is_translated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config = make_config(tmp_path)

    def fail_load(*args, **kwargs):
        raise ValueError("strict window missing")

    monkeypatch.setattr(data_loader.contract_loaders, "load_strategy_bars", fail_load)

    with pytest.raises(DataLoadError, match="strict window missing"):
        data_loader.load_data(config, engine=object())


def test_default_engine_uses_public_quant_data_engine_factory_without_env_discovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    quant_data_root = tmp_path / "quant-data"
    package_dir = quant_data_root / "src" / "quant_data"
    package_dir.mkdir(parents=True)
    (quant_data_root / ".env").write_text("TIMESCALE_PASSWORD=secret\n")
    captured: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def fake_get_engine(*args: object, **kwargs: object):
        captured.append((args, kwargs))
        return object()

    monkeypatch.setattr(data_loader, "get_engine", fake_get_engine)

    data_loader._default_engine()

    assert captured == [((), {})]


def test_default_engine_reuses_current_factory_engine(monkeypatch: pytest.MonkeyPatch):
    engine = object()
    calls = 0

    def fake_get_engine():
        nonlocal calls
        calls += 1
        return engine

    monkeypatch.setattr(data_loader, "get_engine", fake_get_engine)

    first = data_loader._default_engine()
    second = data_loader._default_engine()

    assert first is engine
    assert second is engine
    assert calls == 1


def test_default_engine_refreshes_when_factory_changes(monkeypatch: pytest.MonkeyPatch):
    first_engine = object()
    second_engine = object()
    first_calls = 0
    second_calls = 0

    def first_factory():
        nonlocal first_calls
        first_calls += 1
        return first_engine

    def second_factory():
        nonlocal second_calls
        second_calls += 1
        return second_engine

    monkeypatch.setattr(data_loader, "get_engine", first_factory)
    assert data_loader._default_engine() is first_engine

    monkeypatch.setattr(data_loader, "get_engine", second_factory)
    assert data_loader._default_engine() is second_engine

    assert first_calls == 1
    assert second_calls == 1
