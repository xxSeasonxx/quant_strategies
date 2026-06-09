# FX Session Activity Profile Rejection

## Verdict

Failed on Train: no survivor after 81 logged attempts. The thesis produced several positive aggregate-net variants, but no variant cleared the configured worst-subwindow Train floor and cost-stress gates.

This package records a failed Train thesis. It is not a candidate for OOS, paper, live, or deployment review unless Season explicitly reopens it as a new thesis.

## Thesis

The prior Asia session defines an overnight FX balance area. London-morning behavior around that balance was expected to reveal tradable rejection, acceptance, POC reclaim, or opening-drive continuation/failure using quoted one-minute FX bars.

## Why It Failed

- The original activity-profile rejection surface showed weak aggregate promise but unstable robustness. Best old near-miss `attempt-0046` had positive net and profit factor just above 1, but worst-subwindow score stayed negative.
- Exit redesign did not fix the problem. Explicit target/stop variants often hit stops more than targets, showing that many entries were into adverse continuation rather than merely overstayed.
- Pair family mattered. `XXXUSD` variants improved materially while USD-base variants were poor, so the original five-pair universe hid inconsistent behavior.
- Stronger confirmation and phase filters improved aggregate expectancy in some cases, but usually failed trade-floor or subwindow-coverage gates. The possible edge was too sparse for this protocol.
- Tick-count activity profile did not prove it added robust information beyond simpler Asia range, POC, and London-phase structure.

## Train Protocol

- Data: `forex_with_quotes`
- Symbols: `EURUSD`, `USDJPY`, `GBPUSD`, `AUDUSD`, `USDCAD`
- Train window: `2025-03-01` through `2025-12-31`
- Fill model: quote fills, one-bar entry lag
- Costs: quoted spread only; no extra fee/slippage overlay
- Objective: worst-subwindow over 6 subwindows
- Gates: 120 total trades, 10 trades per subwindow, max symbol concentration 0.70, non-negative cost-stress score, non-negative Train score
- Causality replay: off, per Season's setup for this run

## Retained Failed Cases

- `attempt-0046-best-old-profile-near-miss`: original rejection-only surface with relaxed activity. Positive aggregate net and PF 1.006, but worst-subwindow score -0.115281. Keep as the best old near-miss and evidence that the thesis had only conditional edge.
- `attempt-0051-stop-loss-entry-failure`: first structural sweep reversal with explicit target/stop. Score -0.164806. Diagnostics showed stop-loss exits outnumbered take-profit exits, pointing to entry timing/trigger failure rather than a simple max-hold exit issue.
- `attempt-0062-xxxusd-confirmed-near-miss`: two-stage sweep retest on `XXXUSD` pairs only. Best score seen in the later structural phase at -0.084600 with positive net. Keep as evidence that pair-family split helped but did not pass.
- `attempt-0063-usdbase-negative-control`: same confirmed sweep family on USD-base pairs. Score -0.940138 and poor PF. Keep as negative-control evidence for not mixing USD-base pairs into the same rule.
- `attempt-0070-sparse-mid-reclaim-positive`: sweep plus Asia-mid reclaim without activity. Positive net and PF 1.259, but only 109 trades and failed coverage. Keep as evidence that late confirmation can improve trade quality but is too sparse here.
- `attempt-0081-final-paused-sparse-positive`: final paused case. Positive aggregate net and PF 1.036, but failed trade floor with 119 trades and score -0.251115. Keep as final-state evidence.

## What Not To Repeat

- Do not run more small threshold sweeps on profile bins, activity z-score, spread percentile, or hold length for this exact thesis.
- Do not treat `EURUSD/GBPUSD/AUDUSD` and `USDJPY/USDCAD` as one homogeneous universe without a documented reason.
- Do not add fixed bps target/stop exits before fixing the entry trigger; that path mostly converted noisy entries into stop-loss exits.
- Do not promote positive aggregate net when worst-subwindow score remains negative.

## Possible Fresh Thesis

The only reopenable thread is a narrower `XXXUSD` London-session thesis with explicit phase logic and a lower/smaller-sample protocol chosen before the run. That should be a fresh thesis with a new ledger, not a continuation of this failed Train loop.

## Authoritative Files

- `strategy.py`: archived final working strategy surface from `quant_autoresearch_2`
- `run.toml`: final paused quick-run config from `attempt-0081`
- `experiment.toml`: final archived parameter table
- `protocol.train.toml`: Train protocol used for the failed thesis
- `results.tsv`: canonical Train ledger through `attempt-0081`
- `failed_cases/`: selected failed-case snapshots and diagnostics
- `pre_offload_seed/`: original candidate files that existed here before this failed-thesis offload

## Cleanup State

No destructive cleanup has been performed in `quant_autoresearch_2` yet. The failed-thesis evidence has been copied here and validated; the source research bench can be reset after Season explicitly approves cleanup.

This package is Train-only research evidence. It is not OOS, paper, live, or deployability evidence.
