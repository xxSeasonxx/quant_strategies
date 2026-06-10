from __future__ import annotations

# The bar/decision/request DTOs (``Bar``/``StrategySpec``/``EvaluationRequest`` and the
# ``CostModel``/``FillModel`` aliases) were retired by the ``portfolio-book-spine``
# change: the single causal, single-account netted book (``core.portfolio_foundation``)
# is the only PnL/NAV computation on every surface, and the validation/evaluation
# backends consume it directly rather than these models. Only the evidence-schema
# version constant remains live (used by ``runner.artifacts``).
EVIDENCE_SCHEMA_VERSION = "quant_strategies.engine.evidence/v4"
