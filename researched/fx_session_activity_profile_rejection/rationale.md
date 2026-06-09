# Failed-Thesis Rationale

## Verdict

The FX session activity-profile rejection thesis failed on Train. It did not produce a gated Train survivor after 81 attempts.

## Mechanism Tested

The thesis assumed the Asia session creates a meaningful overnight FX balance area. London tests of that balance were expected to produce tradable rejection, continuation, POC reclaim, or opening-drive behavior using quoted one-minute FX bars and tick-count activity as an activity proxy.

## What Was Learned

- The original profile rejection rule was not robust. It could produce positive aggregate net, but worst-subwindow robustness remained negative.
- Acceptance-style variants were consistently weaker than rejection-style variants.
- Explicit target/stop exits exposed an entry problem: many structural sweep variants hit stops more often than targets.
- Pair family mattered. `XXXUSD` pairs behaved materially better than USD-base pairs.
- Later confirmation and phase-specific entries improved some aggregate metrics, but became too sparse for the configured gates.

## Retained Cases

```text
attempt-0046: best old profile-rejection near miss -> positive net but negative worst-subwindow score -> do not promote aggregate net without robustness.
attempt-0051: structural sweep with target/stop -> stop-loss exits dominated take-profit exits -> entry trigger was too early/noisy.
attempt-0062: two-stage sweep on XXXUSD -> best later structural score but still negative -> pair family helps but is insufficient.
attempt-0063: two-stage sweep on USD-base -> strongly negative -> do not mix USD-base pairs into the same rule without separate logic.
attempt-0070: sweep plus Asia-mid reclaim -> positive and high PF but too sparse -> late confirmation improves quality but fails evidence gates.
attempt-0081: final paused sparse positive case -> positive aggregate net but failed trade floor and Train floor -> final state remains failed.
```

## Residual Reopen Criteria

Only reopen this idea as a new thesis if the protocol is explicitly designed around a narrower question, such as `XXXUSD` London phase behavior with predeclared sample-size expectations. Do not continue this ledger or tune the current failed surface.

## Boundary

This is failed Train evidence only. It is not OOS, paper, live, or deployability evidence.
