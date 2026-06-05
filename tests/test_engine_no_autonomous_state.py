from __future__ import annotations

import pkgutil

import quant_strategies.engine as internal_engine


def test_engine_package_has_no_autonomous_state_modules():
    forbidden = ("autoresearch", "current_program", "program_log", "strategy_switch")
    module_names = [
        name
        for _, name, _ in pkgutil.walk_packages(
            internal_engine.__path__, internal_engine.__name__ + "."
        )
    ]

    assert module_names
    assert not any(token in module_name for token in forbidden for module_name in module_names)
