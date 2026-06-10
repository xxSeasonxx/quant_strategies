# VectorBT Pro

> **Status (portfolio-book-spine, 2026-06-10): VectorBT Pro is retired from
> `quant_strategies`.** It is no longer an evaluation backend, a validation
> backend, or an agreement-oracle cross-check. Every surface — quick run,
> validation, and evaluation — now runs the **single pure-Python causal netted
> portfolio book** (`netted_portfolio_book_v1`); evaluation adds only `pandas` /
> `pyarrow` Parquet trace serialization around that book. VBT cannot model
> crypto-perp funding, so it could not honestly evaluate the asset class, and the
> single-trade agreement oracle provided no multi-trade verification — both were
> removed (design D9). This note is retained as a **factual library reference** (and
> for the named follow-on: a future independent cross-check that must agree with the
> spine, generalized from single-trade to the netted book). The sections below
> marked *(retired)* describe surfaces that no longer exist.

This note records the package facts that matter if VectorBT Pro is reintroduced as
an independent cross-check. It is not an official VectorBT Pro guide.

## Package Facts

Local package inspection in Season's `quant` environment on 2026-06-01:

| Fact | Value |
| --- | --- |
| Import | `import vectorbtpro as vbt` |
| Version | `2026.4.7` |
| Package root | `/opt/anaconda3/envs/quant/lib/python3.12/site-packages/vectorbtpro/` |
| `Portfolio` module | `vectorbtpro/portfolio/base.py` |
| Project optional extra | `pip install -e '.[vectorbtpro]'` installs `pandas>=2.2` and `vectorbtpro` |
| Evaluation extra | `pip install -e '.[evaluation]'` installs `pandas>=2.2`, `pyarrow>=16`, and (still, pending build-file cleanup) `vectorbtpro`. The evaluation **accounting path no longer needs `vectorbtpro`** — only `pandas`/`pyarrow` for Parquet traces; the lingering `vectorbtpro` entry in the extra is a residual to trim with the code/test cutover. |

Verify the local install with:

```bash
conda run -n quant python -c "import inspect, vectorbtpro as vbt; print(vbt.__version__); print(vbt.__file__); print(inspect.getmodule(vbt.Portfolio).__file__)"
```

The package is broad. The pieces relevant to this project are the portfolio
simulation APIs:

| API | Factual role |
| --- | --- |
| `vbt.Portfolio.from_signals(...)` | Simulates a portfolio from entry/exit signal arrays, including long/short entries and exits. |
| `vbt.Portfolio.from_orders(...)` | Simulates a portfolio from explicit order arrays: size, price, fees, slippage, direction, and related fields. |
| `vbt.Portfolio.from_order_func(...)` | Builds a portfolio from custom order functions, with Numba-oriented callback paths. |

The installed source shows the simulation kernels under
`vectorbtpro/portfolio/nb/`, including `from_signals.py`, `from_orders.py`, and
`from_order_func.py`. `Portfolio.from_signals` prepares and broadcasts inputs,
then delegates to those kernels.

Relevant `Portfolio.from_signals` inputs include:

| Input | Meaning |
| --- | --- |
| `close` | Close prices or OHLC data used for simulation. |
| `entries`, `exits` | Long entry and exit signal arrays. |
| `long_entries`, `long_exits`, `short_entries`, `short_exits` | Direction-specific signal arrays. |
| `size`, `size_type` | Position sizing inputs. |
| `price`, `fees`, `slippage` | Execution price, percentage fee, and percentage slippage inputs. |
| `cash_sharing`, `group_by`, `init_cash` | Portfolio grouping and capital model inputs. |
| `open`, `high`, `low` | Optional OHLC inputs used by stop/limit features. |
| `jitted`, `chunked`, `broadcast_kwargs` | Performance and broadcasting controls. |

Relevant `Portfolio` outputs include:

| Output | Meaning |
| --- | --- |
| `get_total_return()` / `total_return` | Portfolio total return. |
| `returns` | Portfolio return series. |
| `orders` | Order records. |
| `trades` | Trade records and trade analytics. |
| `stats(...)` | Metric builder for selected portfolio statistics. |
| `get_max_drawdown()` | Drawdown metric. |

Portfolio defaults observed in `vbt.settings["portfolio"]` include
`init_cash = 100.0`, `price = "close"`, `fees = 0.0`, `slippage = 0.0`, and
`cash_sharing = False`. A project adapter should still set every semantic field
it depends on explicitly.

## What It Could Be Helpful For (if reintroduced as a cross-check)

VectorBT Pro is a fast vectorized portfolio-simulation workbench (signal matrices
across assets/windows/grids; cost/slippage/sizing sensitivity; NAV-path, drawdown,
order, and trade distributions). It is **not currently used by `quant_strategies`**.
The only place it could return is as an *independent cross-check* that must agree
with the spine's netted book — and only after the agreement oracle is generalized
from single-trade to the full netted book (a named follow-on). It would never be a
divergent money-model routed by data kind, and it cannot model crypto-perp funding.

## Project Boundary (current)

There is **one accounting model on every surface** — the pure-Python causal netted
portfolio book. No surface uses VectorBT Pro.

| Surface | Backend |
| --- | --- |
| Quick run | Single causal netted portfolio book (`core.portfolio_foundation`) |
| Validation verdict | The same spine book (`SpineBackend`); `verdict_source = "engine"` only |
| Evaluation run | The same spine book + `pandas`/`pyarrow` Parquet trace serialization |

The scored object is the book's **NAV path** on every surface; the per-trade ledger
is a derived attribution view of the same walk (one model of money). Funding is
computed once, in the book, as a NAV cashflow on the net held position — there is no
separate engine-vs-evaluation funding basis. Strategy purity forbids calling any
backtest library inside strategy files. hidden-lookahead replay proves point-in-time
causal replay; it does not prove out-of-sample validity or freedom from in-sample
fitting.

## Retired surfaces

The following described surfaces **no longer exist** and are recorded here only so
older references resolve:

- *(retired)* **VectorBT Pro evaluation backend** — evaluation no longer routes
  non-funding data to VBT; it runs the spine book. `evaluation/vectorbtpro_backend.py`
  is deleted.
- *(retired)* **`project_perp_ledger_v1`** — the hand-rolled perp-ledger money-model
  is gone; crypto-perp funding lives in the one shared book and the metric payload
  reports `netted_portfolio_book_v1`. `evaluation/project_perp_ledger.py` is deleted.
- *(retired)* **Single-trade agreement oracle** — `validation/agreement.py` and
  `validation/vectorbtpro_backend.py` are deleted; the `[agreement_oracle]` config
  section is rejected. It compared engine `gross_return` against a VBT zero-cost
  total return and was sound only for a single-trade, close-fill, threshold-free
  scenario, so it gave no multi-trade verification.

Evaluation trace artifacts (still produced, now from the spine book) are documented
in [`docs/foundation-surfaces.md`](foundation-surfaces.md) and
[`docs/consumer/reference.md`](consumer/reference.md).
