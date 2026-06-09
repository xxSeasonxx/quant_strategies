# Rationale

## Working Thesis

Crowded perpetual positioning reflected by persistent negative funding pressure and recent negative price extension mean-reverts after the funding pressure is observable.

## Final Train Survivor

`attempt-0099` is the selected Train survivor.

Core expression:

- Long-only.
- Excludes BTC-PERP from emitted trades.
- Uses BTC only as cross-sectional context.
- Trades ETH-PERP, DOGE-PERP, ADA-PERP, and LINK-PERP.
- Requires negative summed funding pressure and negative return extension.
- Applies a stricter funding threshold during broad selloff regimes.
- Skips early-session ADA entries to avoid timing noise.
- Uses longer holds for DOGE/ETH/LINK and a shorter ADA coverage hold.

This is Train-only evidence.

## Durable Decisions

- **Do not use the short book.** Short-side variants often repaired coverage but degraded cost-stressed robustness.
- **Do not add fixed price exits by default.** Take-profit, stop-loss, and trailing-stop variants repeatedly harmed cost stress and payoff.
- **BTC is not part of the emitted book.** BTC funding behaved more like low-edge anchor/hedge flow than clean crowding dislocation.
- **ADA is coverage ballast.** ADA is lower quality than DOGE/ETH/LINK but necessary for subwindow coverage.
- **High-edge symbols need longer holds.** DOGE/ETH/LINK improved with longer holds than ADA.
- **Strong funding filters are high quality but sparse.** They produced high raw scores but failed subwindow coverage unless carefully repaired.

## Retained Candidate Buckets

### Survivors

- `attempt-0014`: first all-gates survivor.
- `attempt-0018`: 90-minute/8-hour survivor.
- `attempt-0033`: strong non-BTC long-only book.
- `attempt-0059`: selloff-gated funding-threshold survivor.
- `attempt-0068`: per-symbol hold improvement.
- `attempt-0079`: exact ADA session-start skip.
- `attempt-0080`: ADA early-window skip.
- `attempt-0093`: 14-hour high-edge hold.
- `attempt-0095`: 15-hour high-edge hold.
- `attempt-0098`: 14.25-hour high-edge hold.
- `attempt-0099`: final best survivor.

### Gated Candidates

- `attempt-0097`: 14.5-hour boundary candidate.
- `attempt-0100`: final 14.05-hour boundary test.

### Near Misses

- `attempt-0013`: high-score long-only variant, failed sparse coverage.
- `attempt-0046`: strong 1.5 bps funding filter, high quality but sparse.
- `attempt-0049`: dense strong-funding book, one-trade sparse miss.
- `attempt-0056`: selloff strong-threshold sparse miss.
- `attempt-0057`: deep selloff one-trade sparse miss.
- `attempt-0081`: wide ADA skip, high raw score but sparse miss.
- `attempt-0087`: ADA latest-funding quality filter, sparse miss.

### Anti-Patterns

- `attempt-0010`: short coverage repaired coverage but killed economics.
- `attempt-0017`: take-profit exit failed.
- `attempt-0024`: stop-loss exit failed.
- `attempt-0025`: trailing-stop exit failed.
- `attempt-0053`: hard funding acceleration filter failed.
- `attempt-0055`: tranche-cap failed.

## Residual Risks

- Heavy Train-selection pressure: 100 attempts on one Train window.
- Candidate is not OOS, paper, live, or deployability evidence.
- Final structure has symbol-specific logic and timing controls; this is plausible but overfit-prone.
- Causality replay was not enabled during the Train loop; source review found no obvious lookahead, but downstream evaluation should include causality replay.

## Evaluation Boundary

Downstream evaluation may compare retained candidates, but OOS results must not feed back into this same Train thesis. If OOS fails, archive this package or start a fresh thesis from the learned principles.
