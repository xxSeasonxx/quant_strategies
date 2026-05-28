from __future__ import annotations

import inspect

from quant_strategies.validation import errors


def test_validation_errors_expose_only_raised_error_classes():
    public_error_names = {
        name
        for name, value in vars(errors).items()
        if name.startswith("Validation")
        and inspect.isclass(value)
        and value.__module__ == errors.__name__
    }

    assert public_error_names == {"ValidationError", "ValidationConfigError"}
