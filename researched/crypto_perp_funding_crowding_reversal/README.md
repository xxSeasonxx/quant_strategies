# Crypto Perp Funding Crowding Reversal

This package is a curated handoff from `quant_autoresearch` for downstream evaluation.

This package is Train-only research evidence. It is not OOS, paper, live, or deployability evidence.

## Current Train Survivor

- Current survivor: `attempt-0099`
- Strategy file: `strategy.py`
- Train score: `0.21735915161032543`
- Gates: all pass
- Subwindow trade counts: `258,100,51,12,100,55`
- Trade count: `576`
- Net return sum: `1.4319279628946049`
- Cost stress score: `0.18345328245288353`
- Profit factor: `2.118590347460084`

The survivor is a long-only crypto perp funding-dislocation strategy:

- trade non-BTC symbols only;
- use negative summed funding pressure plus negative price extension;
- require stronger funding pressure during broad selloff regimes;
- skip ADA early-session timing noise;
- use 8-hour ADA holds and extended DOGE/ETH/LINK holds;
- use Train-only next-bar fills and protocol-owned costs.

## Authoritative Files

- `strategy.py`: final Train survivor strategy snapshot from `attempt-0099`.
- `experiment.toml`: bounded params from `attempt-0099`.
- `protocol.train.toml`: Train protocol used for the survivor.
- `results.tsv`: canonical Train ledger from the source research bench.
- `rationale.md`: curated thesis and research summary.
- `candidates/`: retained structurally distinct attempts.
- `diagnostics/`: flat diagnostic/summary copies for retained attempts.

## Train Setup

- Source repo: `/Users/Season_Yang/Personal/quant_autoresearch`
- Data kind: `crypto_perp_funding`
- Symbols: `BTC-PERP`, `ETH-PERP`, `DOGE-PERP`, `ADA-PERP`, `LINK-PERP`
- Train window: `2025-03-01` through `2025-12-31`
- Execution buffer: `load_end = 2026-01-07`
- Fill price: close
- Entry lag: 1 bar
- Exit lag: 0 bars
- Fee: 5 bps per side
- Slippage: 1 bps per side
- Objective: worst subwindow, 6 subwindows
- Key gates: trade floor, subwindow coverage, breadth, cost stress, complexity, train score floor

## Retention Policy

Retained candidates were selected for structural diversity and diagnostic value, not only performance rank. The goal is to preserve distinct thesis expressions and useful failures while dropping dominated variants and noisy boundary sweeps.

Buckets:

- `survivors`: keep rows and meaningful structural survivor steps.
- `gated_candidates`: all gates pass but did not update the best survivor.
- `near_misses`: high-score or diagnostic one-gate misses.
- `anti_patterns`: representative failed ideas that should not be repeated blindly.

Bad candidates were dropped when they were not survivors, not near-misses, and not uniquely informative.

## Retained Candidates

| Attempt | Bucket | Score | Gates | Subwindows | Trades | Net | Cost stress | Why retained |
|---|---|---:|---|---|---:|---:|---:|---|
| attempt-0014 | Survivor | 0.095715 | true | 390,193,63,14,180,82 | 922 | 0.956822 | 0.066397 | first all-gates survivor |
| attempt-0018 | Survivor | 0.153675 | true | 333,156,55,12,146,76 | 778 | 0.852224 | 0.097935 | 90-minute/8-hour survivor |
| attempt-0033 | Survivor | 0.166732 | true | 308,114,53,13,115,63 | 666 | 1.220793 | 0.130939 | non-BTC long book |
| attempt-0059 | Survivor | 0.175855 | true | 283,108,53,12,104,58 | 618 | 1.157420 | 0.137665 | selloff-gated funding threshold |
| attempt-0068 | Survivor | 0.180674 | true | 283,108,53,12,104,58 | 618 | 1.285457 | 0.140247 | per-symbol hold improvement |
| attempt-0079 | Survivor | 0.194602 | true | 270,103,51,12,102,57 | 595 | 1.304473 | 0.159695 | skip exact ADA session start |
| attempt-0080 | Survivor | 0.196862 | true | 258,100,51,12,100,55 | 576 | 1.301654 | 0.162204 | skip ADA early window |
| attempt-0093 | Survivor | 0.209831 | true | 258,100,51,12,100,55 | 576 | 1.398901 | 0.175824 | 14-hour high-edge hold |
| attempt-0095 | Survivor | 0.211421 | true | 258,100,51,12,100,55 | 576 | 1.421436 | 0.177311 | 15-hour high-edge hold |
| attempt-0098 | Survivor | 0.215233 | true | 258,100,51,12,100,55 | 576 | 1.424205 | 0.181483 | 14.25-hour hold parent |
| attempt-0099 | Survivor | 0.217359 | true | 258,100,51,12,100,55 | 576 | 1.431928 | 0.183453 | final best survivor |
| attempt-0097 | Gated | 0.211904 | true | 258,100,51,12,100,55 | 576 | 1.445360 | 0.178128 | 14.5-hour boundary |
| attempt-0100 | Gated | 0.208370 | true | 258,100,51,12,100,55 | 576 | 1.394516 | 0.174423 | final boundary test |
| attempt-0013 | Near miss | 0.163191 | false | 192,93,33,9,93,43 | 463 | 0.683681 | 0.129455 | high-score long-only coverage miss |
| attempt-0046 | Near miss | 0.206772 | false | 251,84,50,2,73,38 | 498 | 1.109541 | 0.173302 | strong funding raw-score sparse miss |
| attempt-0049 | Near miss | 0.165565 | false | 459,160,88,11,138,62 | 918 | 1.775734 | 0.123118 | dense strong-funding sparse miss |
| attempt-0056 | Near miss | 0.185767 | false | 266,94,51,9,99,50 | 569 | 1.091551 | 0.148419 | selloff strong-threshold sparse miss |
| attempt-0057 | Near miss | 0.175855 | false | 281,108,51,11,104,58 | 613 | 1.141409 | 0.137704 | deep selloff one-trade sparse miss |
| attempt-0081 | Near miss | 0.203347 | false | 246,96,50,11,98,55 | 556 | 1.298137 | 0.169207 | wide ADA skip one-trade sparse miss |
| attempt-0087 | Near miss | 0.206309 | false | 194,70,36,10,89,49 | 448 | 1.123066 | 0.173756 | ADA latest-funding high-quality sparse miss |
| attempt-0010 | Anti-pattern | -0.082448 | false | 265,308,304,325,302,271 | 1775 | 0.417500 | -0.133917 | short coverage killed economics |
| attempt-0017 | Anti-pattern | 0.022209 | false | 333,156,55,12,146,76 | 778 | 0.201631 | -0.038761 | take-profit failure |
| attempt-0024 | Anti-pattern | 0.017164 | false | 333,156,55,12,146,76 | 778 | 0.354466 | -0.025225 | stop-loss failure |
| attempt-0025 | Anti-pattern | -0.347864 | false | 333,156,55,12,146,76 | 778 | -0.138006 | -0.537661 | trailing-stop failure |
| attempt-0053 | Anti-pattern | -0.234874 | false | 139,38,20,5,37,32 | 271 | 0.521966 | -0.275307 | hard funding acceleration failure |
| attempt-0055 | Anti-pattern | 0.075895 | false | 179,73,28,10,65,46 | 401 | 0.564220 | -0.021366 | tranche-cap failure |

## Lessons From Train

- Shorts repeatedly repaired coverage but damaged cost-stressed robustness.
- Fixed take-profit, fixed stop-loss, and trailing-stop exits were harmful.
- BTC behaved more like low-edge anchor flow than a clean dislocation signal.
- ADA was necessary for sparse-window coverage but needed session-timing controls.
- DOGE/ETH/LINK benefited from longer holds than ADA.
- Strong funding filters improved raw score but often starved the sparse subwindow.

## Evaluation Plan

Downstream evaluation should compare the final survivor with a small set of structurally distinct alternatives:

- `attempt-0099`: final survivor.
- `attempt-0098`: nearest parent.
- `attempt-0080`: ADA timing survivor before final hold tuning.
- `attempt-0068`: per-symbol hold survivor.
- `attempt-0059`: selloff-gated survivor.
- `attempt-0033`: first strong non-BTC survivor.
- selected near-misses if evaluation is explicitly designed to test boundary hypotheses.

Evaluation must be one-way. Do not use OOS results to patch this same Train thesis. If OOS fails, archive or start a fresh thesis using the learned principles.
