# attempt-99new Target-Book Baseline Run

Date: 2026-06-13

Purpose: run the `attempt-99new` survivor snapshot as a current target-book
baseline over the saved quick-run window.

Command:

```bash
/usr/bin/time -p conda run -n quant quant-strategies run researched/crypto_perp_funding_crowding_reversal/candidates/survivors/attempt-99new/snapshot/quick_config.toml
```

Walltime:

```text
real 274.21
user 262.82
sys 5.03
```

Generated result directory:

```text
results/crypto_perp_funding_crowding_reversal/attempt-99new/2026-06-13T061735Z-crypto_perp_funding_crowding_reversal_stateful_rebalance
```

Copied artifact directory:

```text
researched/crypto_perp_funding_crowding_reversal/candidates/survivors/attempt-99new/artifacts
```

Run result:

- `status`: `completed`
- `failure_stage`: `null`
- `assessment_status`: `quick_check_unverified`
- `artifact_profile`: `diagnostic`
- generated decisions: `367`
- excluded decisions: `0`
- economic trade count: `183`
- `sum_net_return`: `0.0016314202803836154`
- `profit_factor`: `1.6293969755751903`
- `portfolio_foundation`: present and feasible

Portfolio foundation:

- realistic max bar participation: `0.1287217407296239`
- realistic max ADV participation: `0.01589477344490286`
- realistic closed trades: `183`
- realistic total return: `0.0015613021320175502`

Causality note:

The run uses `causality_check = "micro"` with `micro_timeout_seconds = 60.0`.
Micro replay completed without timeout or hidden-lookahead failure, but the run
is not retainable promotion evidence because micro replay is not complete
retention proof.
