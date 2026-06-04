from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from quant_strategies.decisions import (
    DecisionStrategyLoadError,
    StrategyDecision,
    load_decision_strategy,
)


def test_load_decision_strategy_returns_generate_decisions_callable(tmp_path: Path):
    strategy = tmp_path / "strategies" / "demo.py"
    strategy.parent.mkdir(parents=True)
    strategy.write_text(
        "from quant_strategies.decisions import ExitPolicy, InstrumentRef, PositionTarget, StrategyDecision\n"
        "def generate_decisions(rows, params):\n"
        "    return [StrategyDecision(\n"
        "        strategy_id='demo',\n"
        "        instrument=InstrumentRef(kind='equity_or_etf', symbol='SPY'),\n"
        "        decision_time=rows[0]['timestamp'],\n"
        "        as_of_time=rows[0]['timestamp'],\n"
        "        target=PositionTarget(direction='long', sizing_kind='target_weight', size=1.0),\n"
        "        exit_policy=ExitPolicy(max_hold_bars=1),\n"
        "    )]\n"
    )

    generate_decisions = load_decision_strategy(strategy, repo_root=tmp_path)
    rows = [{"symbol": "SPY", "timestamp": datetime(2024, 1, 1, tzinfo=timezone.utc)}]

    decisions = generate_decisions(rows, {})

    assert callable(generate_decisions)
    assert isinstance(decisions[0], StrategyDecision)
    assert decisions[0].instrument.symbol == "SPY"


def test_load_decision_strategy_rejects_file_without_generate_decisions(tmp_path: Path):
    strategy = tmp_path / "strategies" / "demo.py"
    strategy.parent.mkdir(parents=True)
    strategy.write_text("def generate_signals(rows, params):\n    return []\n")

    with pytest.raises(DecisionStrategyLoadError, match="generate_decisions"):
        load_decision_strategy(strategy, repo_root=tmp_path)


def test_load_decision_strategy_rejects_directory_path(tmp_path: Path):
    strategy = tmp_path / "strategies" / "demo.py"
    strategy.mkdir(parents=True)

    with pytest.raises(DecisionStrategyLoadError, match="must be a file"):
        load_decision_strategy(strategy, repo_root=tmp_path)


def test_load_decision_strategy_rejects_side_effect_calls_before_import(tmp_path: Path):
    marker = tmp_path / "marker.txt"
    strategy = tmp_path / "strategy.py"
    strategy.write_text(
        f"open({str(marker)!r}, 'w').write('boom')\n"
        "def generate_decisions(rows, params):\n"
        "    return []\n"
    )

    with pytest.raises(DecisionStrategyLoadError, match=r"open\(\)|\.write\(\)"):
        load_decision_strategy(strategy, repo_root=tmp_path)

    assert not marker.exists()


@pytest.mark.parametrize(
    ("import_line", "message"),
    [
        ("import quant_data", "quant_data"),
        ("from quant_strategies.runner import run_config", "quant_strategies.runner"),
        ("import quant_strategies.evaluation", "quant_strategies.evaluation"),
        (
            "from quant_strategies.evaluation import run_evaluation",
            "quant_strategies.evaluation",
        ),
        ("from quant_strategies import evaluation", "quant_strategies.evaluation"),
        ("import vectorbtpro", "vectorbtpro"),
    ],
)
def test_load_decision_strategy_rejects_banned_imports_before_import(
    tmp_path: Path,
    import_line: str,
    message: str,
):
    strategy = tmp_path / "strategy.py"
    strategy.write_text(
        f"{import_line}\n"
        "def generate_decisions(rows, params):\n"
        "    return []\n"
    )

    with pytest.raises(DecisionStrategyLoadError, match=message):
        load_decision_strategy(strategy, repo_root=tmp_path)


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("import random as r\nr.random()\n", r"random\.random\(\)"),
        ("from random import random\nrandom()\n", r"random\.random\(\)"),
        ("import numpy as np\nnp.random.rand()\n", r"numpy\.random\.rand\(\)"),
        ("import time as t\nt.time()\n", r"time\.time\(\)"),
        ("from datetime import datetime\ndatetime.now()\n", r"datetime\.datetime\.now\(\)"),
        (
            "from builtins import __import__ as imp\ngetattr(imp('os'), 'system')('echo unsafe')\n",
            r"builtins\.__import__\(\)|getattr\(__import__",
        ),
        (
            "getattr(__import__('os'), 'system')('echo unsafe')\n",
            r"__import__\(\)|getattr\(__import__",
        ),
    ],
)
def test_load_decision_strategy_rejects_alias_aware_impure_calls(
    tmp_path: Path,
    source: str,
    message: str,
):
    strategy = tmp_path / "strategy.py"
    strategy.write_text(
        source
        + "def generate_decisions(rows, params):\n"
        + "    return []\n"
    )

    with pytest.raises(DecisionStrategyLoadError, match=message):
        load_decision_strategy(strategy, repo_root=tmp_path)


def test_load_decision_strategy_allows_deterministic_numeric_imports(tmp_path: Path):
    strategy = tmp_path / "strategy.py"
    strategy.write_text(
        "import math as m\n"
        "def generate_decisions(rows, params):\n"
        "    return [] if m.sqrt(4) == 2 else None\n"
    )

    generate_decisions = load_decision_strategy(strategy, repo_root=tmp_path)

    assert generate_decisions([], {}) == []


def test_load_decision_strategy_allows_explicit_purity_opt_out(tmp_path: Path):
    marker = tmp_path / "marker.txt"
    strategy = tmp_path / "strategy.py"
    strategy.write_text(
        f"open({str(marker)!r}, 'w').write('boom')\n"
        "def generate_decisions(rows, params):\n"
        "    return []\n"
    )

    generate_decisions = load_decision_strategy(
        strategy,
        repo_root=tmp_path,
        enforce_purity=False,
    )

    assert callable(generate_decisions)
    assert marker.read_text() == "boom"


@pytest.mark.parametrize(
    ("source", "message"),
    [
        # File reads are data loading just as much as writes are.
        ("from pathlib import Path\nPath('x').read_text()\n", r"\.read_text\(\)"),
        ("from pathlib import Path\nPath('x').read_bytes()\n", r"\.read_bytes\(\)"),
        # Dataframe readers (alias-resolved or attribute-form).
        ("import pandas as pd\npd.read_csv('x.csv')\n", r"\.read_csv\(\)"),
        ("import pandas as pd\npd.read_parquet('x')\n", r"\.read_parquet\(\)"),
        ("import pandas\npandas.read_json('x')\n", r"\.read_json\(\)"),
        ("import pandas as pd\npd.DataFrame().to_csv('x.csv')\n", r"\.to_csv\(\)"),
        ("import pandas as pd\npd.DataFrame().to_parquet('x')\n", r"\.to_parquet\(\)"),
        ("from pathlib import Path\nlist(Path('.').glob('*.csv'))\n", r"\.glob\(\)"),
        ("from pathlib import Path\nlist(Path('.').iterdir())\n", r"\.iterdir\(\)"),
        # Dynamic import can reach any banned module at runtime.
        ("import importlib\nimportlib.import_module('os')\n", r"importlib\.import_module\(\)"),
        ("from importlib import import_module\nimport_module('os')\n", r"importlib\.import_module\(\)"),
        # Network access.
        ("from urllib.request import urlopen\nurlopen('http://x')\n", r"urllib\.request\.urlopen\(\)"),
        ("import urllib.request\nurllib.request.urlopen('http://x')\n", r"urllib"),
        ("import requests\nrequests.put('http://x')\n", r"requests\.put\(\)"),
        ("import httpx\nhttpx.get('http://x')\n", r"httpx\.get\(\)"),
        # Shell escapes.
        ("import os\nos.system('echo unsafe')\n", r"os\.system\(\)"),
        ("from os import popen\npopen('echo unsafe')\n", r"os\.popen\(\)"),
        # Process/threading escapes and runner/validation internals.
        ("import threading\nthreading.Thread(target=lambda: None).start()\n", r"import threading"),
        (
            "from multiprocessing import Process\nProcess(target=lambda: None).start()\n",
            r"from multiprocessing import \.\.\.",
        ),
        (
            "from quant_strategies.validation import run_validation\n",
            r"from quant_strategies.validation import \.\.\.",
        ),
    ],
)
def test_load_decision_strategy_rejects_data_loading_escapes(
    tmp_path: Path,
    source: str,
    message: str,
):
    strategy = tmp_path / "strategy.py"
    strategy.write_text(
        source
        + "def generate_decisions(rows, params):\n"
        + "    return []\n"
    )

    with pytest.raises(DecisionStrategyLoadError, match=message):
        load_decision_strategy(strategy, repo_root=tmp_path)


def test_load_decision_strategy_allows_pandas_compute(tmp_path: Path):
    # Computing on the rows already passed in is fine; only *loading* data is banned.
    strategy = tmp_path / "strategy.py"
    strategy.write_text(
        "import pandas as pd\n"
        "def generate_decisions(rows, params):\n"
        "    frame = pd.DataFrame(list(rows))\n"
        "    return [] if frame.empty else []\n"
    )

    generate_decisions = load_decision_strategy(strategy, repo_root=tmp_path)

    assert generate_decisions([], {}) == []
