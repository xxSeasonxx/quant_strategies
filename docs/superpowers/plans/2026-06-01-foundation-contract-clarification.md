# Foundation Contract Clarification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clarify the active foundation contract so quick run, mechanical evidence validation, and the future research evaluation surface are distinct without changing code, commands, public APIs, or artifact schemas.

**Architecture:** This is a docs-only contract update. `PRD.md`, `README.md`, `FOUNDATION_LOCK.md`, and `TODOS.md` become the first-read roadmap for A -> C -> B; `docs/validation.md` and `docs/quant-autoresearch-consumer.md` get narrow wording corrections where old "paper-readiness" language implies more than mechanical review. `docs/foundation-surfaces.md` is intentionally not modified because it remains the factual I/O map for implemented surfaces.

**Tech Stack:** Markdown docs, `rg`, `git diff --check`; no Python source, no tests unless an implementation step unexpectedly touches code.

---

## File Structure

- Modify: `PRD.md`
  - Responsibility: target contract and durable product intent.
  - Clarify that the project has two implemented public surfaces today and one approved missing research-evaluation job.
- Modify: `README.md`
  - Responsibility: concise current-state orientation.
  - Keep current commands factual while adding the three-job mental model.
- Modify: `FOUNDATION_LOCK.md`
  - Responsibility: disposition anchor for future reviews.
  - Lock current implemented surfaces and record research evaluation as approved next direction.
- Modify: `TODOS.md`
  - Responsibility: active open work queue.
  - Collapse the product-contract item after A lands; leave C and B as current open work.
- Modify: `docs/validation.md`
  - Responsibility: current validation reference.
  - Keep the literal `[paper_readiness]` config key if code still uses it, but describe it as a legacy-named mechanical review policy, not paper-trading readiness.
- Modify if needed: `docs/quant-autoresearch-consumer.md`
  - Responsibility: downstream consumer contract.
  - Remove stale wording that makes validation sound like paper-readiness or strategy-quality evaluation.
- Do not modify: `docs/foundation-surfaces.md`
  - It remains the current implemented I/O reference and should be updated only when the research evaluation surface is implemented.
- Do not modify unless a direct contradiction is found: `docs/vectorbtpro.md`
  - Current wording already places VectorBT Pro in evaluation/research-workbench territory and says it does not prove alpha or readiness.

## Task 1: Worktree Preflight And Edit Boundary

**Files:**
- Inspect: `PRD.md`
- Inspect: `README.md`
- Inspect: `FOUNDATION_LOCK.md`
- Inspect: `TODOS.md`
- Inspect: `docs/validation.md`
- Inspect: `docs/quant-autoresearch-consumer.md`
- Inspect only: `docs/foundation-surfaces.md`

- [ ] **Step 1: Confirm the dirty worktree before editing**

Run:

```bash
git status --short
```

Expected: the repository may already contain uncommitted foundation-doc work. Do not revert any existing changes. Treat this plan as a continuation of that docs work.

- [ ] **Step 2: Record the files this plan is allowed to stage**

Allowed files:

```text
PRD.md
README.md
FOUNDATION_LOCK.md
TODOS.md
docs/validation.md
docs/quant-autoresearch-consumer.md
docs/vectorbtpro.md
```

Forbidden for this plan:

```text
docs/foundation-surfaces.md
src/
tests/
```

- [ ] **Step 3: Capture stale-language baseline**

Run:

```bash
rg -n "two-surface|two foundation surfaces|two main foundation surfaces|paper-readiness|paper readiness|paper_candidate|promotion ready|live ready|live readiness|VectorBT Pro.*quick run|quick run.*VectorBT Pro" \
  PRD.md README.md TODOS.md FOUNDATION_LOCK.md docs/validation.md docs/quant-autoresearch-consumer.md docs/vectorbtpro.md
```

Expected before editing: hits in `PRD.md`, `README.md`, `TODOS.md`, `FOUNDATION_LOCK.md`, `docs/validation.md`, and `docs/quant-autoresearch-consumer.md` are likely. These hits drive the edits below.

## Task 2: Update `PRD.md`

**Files:**
- Modify: `PRD.md`

- [ ] **Step 1: Replace the one-line summary**

Replace section `## 1. One-Line Summary` with:

```markdown
## 1. One-Line Summary

`quant_strategies` is a **stateless research foundation**: it has two
implemented public surfaces today — diagnostic quick runs and mechanical
evidence validation — and its next missing product job is stateless research
evaluation for frozen candidates.
```

- [ ] **Step 2: Update the "What the project is" list**

In `## 2. Background and Problem Statement`, replace the current five-item list
under `### What the project is` with:

```markdown
A disciplined Python library and CLI that:

1. Defines a **declarative strategy contract** (pure function -> typed decisions).
2. Provides a **mathematically explicit execution kernel** that turns decisions into
   trade-level PnL with declared assumptions.
3. Provides a **diagnostic quick-run harness** that computes quick-run evidence,
   causality hygiene, and bounded behavior diagnostics for one strategy version.
4. Provides a **mechanical evidence validation harness** that runs a retained
   candidate across windows and scenarios with hidden-lookahead protection and
   mechanically auditable artifacts.
5. Separates the missing **research evaluation** job from validation: evaluation
   is where frozen candidates should receive portfolio, path, robustness, and
   economic evidence under explicit assumptions.
6. Exposes a **stable, minimal consumer surface** for `quant_autoresearch` to drive
   strategy iteration without touching internals.
```

- [ ] **Step 3: Add the three-job distinction after "What the project is not"**

After the `### What the project is not` bullet list, insert:

```markdown
### Foundation jobs

The product contract distinguishes three jobs:

| Job | Status | Purpose |
| --- | --- | --- |
| Quick run | Implemented public surface | Fast causal diagnostics for one strategy version. |
| Mechanical evidence validation | Implemented public surface through `quant-strategies validate` | Retained-candidate integrity checks across windows and scenarios. |
| Research evaluation | Approved missing surface | Stateless economic, path, and portfolio evidence for frozen candidates. |

Validation is not research evaluation. It verifies that evidence was produced
honestly, causally, reproducibly, and audibly under explicit config. It does not
answer whether a strategy has durable alpha, statistical significance, regime
robustness, benchmark-relative edge, capacity, or portfolio quality.
```

- [ ] **Step 4: Rename G2 away from paper-readiness**

Replace this heading:

```markdown
**G2. Math correctness adequate for paper-readiness research.**
```

with:

```markdown
**G2. Math correctness adequate for advisory research evidence.**
```

Keep the existing bullets below it, but verify they still read correctly with the new heading.

- [ ] **Step 5: Expand G4 consumer integration without promising an implemented evaluation API**

In `G4`, after the validation-run bullet:

```markdown
- For validation runs, it uses the result object and structured artifacts as advisory
retained-candidate triage.
```

insert:

```markdown
- For future research evaluation runs, it should pass frozen candidate inputs and
  explicit assumptions to a separate stateless evaluation surface. That surface
  is not part of the current public API.
```

Then replace the user-facing vocabulary paragraph:

```markdown
- User-facing foundation-surface vocabulary MUST remain small. Project-facing
language centers on `quick run`, `validation run`, and advisory validation
verdicts. Terms such as
```

with:

```markdown
- User-facing foundation vocabulary MUST remain small. Current implemented
surface language centers on `quick run`, `validation run`, and advisory
validation verdicts. Product-direction language may name `research evaluation`
as the missing stateless surface, but must not imply it is implemented before it
exists. Terms such as
```

- [ ] **Step 6: Add evaluation to strategic goals without changing current surfaces**

After `G6`, insert a new `G7`:

```markdown
**G7. Research evaluation is a separate stateless surface.**
The next missing product surface SHOULD evaluate frozen candidates under
explicit assumptions and emit portfolio/economic/path evidence. It should accept
strategy and config references, params, data references or splits, portfolio
model assumptions, cost/slippage/fill assumptions, and optional search-pressure
metadata supplied by the caller.

It SHOULD return NAV/path metrics, drawdown, turnover, exposure and
concentration summaries, cost/slippage sensitivity, per-asset or per-regime
breakdowns where configured, and explicit non-claims. It MUST NOT own candidate
generation, search memory, ranking across variants, stopping rules, promotion,
paper-trading authorization, or live-trading authorization.

VectorBT Pro is appropriate here when portfolio/NAV semantics are the
deliverable. It remains out of the quick-run hot path.
```

- [ ] **Step 7: Update non-goal language to include evaluation**

In `NG1`, replace:

```markdown
The validation
verdict label (see G5) is itself advisory — it summarizes mechanical evidence, not
market-validated alpha.
```

with:

```markdown
The validation verdict label (see G5) is itself advisory — it summarizes
mechanical evidence, not market-validated alpha. Future research evaluation
metrics are also advisory evidence, not promotion authority.
```

- [ ] **Step 8: Update NFR simplicity**

Replace:

```markdown
- **NFR-SIMPLICITY.** New strategy authors can read one Protocol + one decision schema
and write a working strategy quickly. Researchers can understand the foundation as
quick run followed, when warranted, by validation run.
```

with:

```markdown
- **NFR-SIMPLICITY.** New strategy authors can read one Protocol + one decision schema
and write a working strategy quickly. Researchers can distinguish fast quick-run
diagnostics, mechanical evidence validation, and the approved missing research
evaluation job without learning implementation vocabulary first.
```

- [ ] **Step 9: Update success criteria surface simplicity**

Replace:

```markdown
- **Surface simplicity.** A user can distinguish quick run from validation run without
knowing implementation vocabulary such as screen/gate modes or replayability metadata.
```

with:

```markdown
- **Surface simplicity.** A user can distinguish quick run, mechanical evidence
validation, and research evaluation without knowing implementation vocabulary
such as screen/gate modes or replayability metadata. Current docs must also make
clear which of those jobs are implemented today.
```

- [ ] **Step 10: Verify `PRD.md`**

Run:

```bash
rg -n "two-surface|two-surface research foundation|paper-readiness|paper readiness|quick run followed.*validation" PRD.md
git diff -- PRD.md
```

Expected: no stale wording hits. The diff should be docs-only and should not add a public `evaluate` API contract.

## Task 3: Update `README.md`

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace the opening description**

Replace the opening paragraph:

```markdown
A disciplined research harness for **pure strategy functions**, deterministic
**quick runs**, and **advisory validation**.
```

with:

```markdown
A disciplined research foundation for **pure strategy functions**,
deterministic **quick runs**, **mechanical evidence validation**, and the
approved missing **research evaluation** layer.
```

- [ ] **Step 2: Replace the job sentence**

Replace:

```markdown
job is to take a strategy idea from "pure function" to "auditable advisory
evidence" without ever letting a number you can't reproduce drive a conclusion.
```

with:

```markdown
job is to take a strategy idea from "pure function" to trustworthy evidence
without ever letting a number with unclear semantics drive a conclusion.
```

- [ ] **Step 3: Add a concise foundation-jobs section before Architecture**

Insert before `## Architecture`:

```markdown
## Foundation jobs

The project contract separates three jobs:

- **Quick run**: implemented today through `quant-strategies run`; fast causal
  diagnostics for one strategy version.
- **Mechanical evidence validation**: implemented today through
  `quant-strategies validate`; retained-candidate integrity checks across
  windows and scenarios.
- **Research evaluation**: approved missing surface; stateless portfolio,
  economic, and path evidence for frozen candidates under explicit assumptions.

Validation is not research evaluation. None of these jobs authorizes paper
trading, live trading, or autonomous promotion.
```

- [ ] **Step 4: Update the architecture bullet that says "Two foundation surfaces"**

Replace:

```markdown
- **Two foundation surfaces.** A fast *quick run* for diagnostic evidence, and an
  *advisory validation run* for retained-candidate evidence. VectorBT Pro is optional,
  single-trade only, and never produces verdict metrics.
```

with:

```markdown
- **Two implemented public surfaces today.** A fast *quick run* for diagnostic
  evidence, and an *advisory validation run* for retained-candidate mechanical
  evidence. Research evaluation is the approved missing surface. VectorBT Pro is
  optional today, single-trade only, and never produces validation verdict metrics.
```

- [ ] **Step 5: Remove paper-readiness implication from `validate_params` wording**

Replace:

```markdown
  **required** for the validation run, so a paper-readiness verdict never rests on
  params that were never schema-checked.
```

with:

```markdown
  **required** for the validation run, so a mechanical evidence verdict never
  rests on params that were never schema-checked.
```

- [ ] **Step 6: Tighten the validation surface paragraph**

Replace the validation paragraph under `## Foundation Surfaces` with:

```markdown
**Validation run** — `quant-strategies validate candidate/validation.toml`

Runs the same kernel across configured windows and stress scenarios, then returns
advisory retained-candidate mechanical evidence. It is an evidence audit, not
research evaluation: never statistical significance, regime robustness,
portfolio quality, capacity, or promotion authority. `promotion_eligible` /
`paper_trade_eligible` / `live_eligible` always stay false. See
[docs/foundation-surfaces.md](docs/foundation-surfaces.md) and
[docs/validation.md](docs/validation.md).
```

- [ ] **Step 7: Add the missing evaluation boundary**

In `## Boundaries`, after the engine reports activity sums bullet, insert:

```markdown
- **Research evaluation is separate and not implemented yet.** Future NAV/path,
  drawdown, exposure, benchmark-relative, and robustness evidence belongs in a
  stateless evaluation surface for frozen candidates, not in validation verdicts
  or quick-run hot paths.
```

- [ ] **Step 8: Verify `README.md`**

Run:

```bash
rg -n "two foundation surfaces|two-surface|paper-readiness|paper readiness|paper-readiness verdict" README.md
git diff -- README.md
```

Expected: no stale wording hits. The diff should keep current commands factual and should not document an implemented `evaluate` command.

## Task 4: Update `FOUNDATION_LOCK.md`

**Files:**
- Modify: `FOUNDATION_LOCK.md`

- [ ] **Step 1: Replace the foundation surfaces lock**

Replace:

```markdown
- **Foundation surfaces:** the project exposes two main foundation surfaces:
  quick run and validation run.
```

with:

```markdown
- **Implemented public surfaces:** the project currently exposes quick run and
  validation run. Quick run is diagnostic; validation run is mechanical evidence
  validation.
- **Approved missing surface:** research evaluation is the next missing stateless
  foundation surface for frozen-candidate portfolio, path, and economic evidence.
```

- [ ] **Step 2: Tighten the validation lock**

Replace:

```markdown
- **Validation run:** validation requires `validate_params` and returns advisory
  retained-candidate evidence.
```

with:

```markdown
- **Validation run:** validation requires `validate_params` and returns advisory
  retained-candidate mechanical evidence. It is not quant strategy evaluation.
```

- [ ] **Step 3: Update metric debt**

Replace:

```markdown
- Full NAV and portfolio accounting are deferred.
```

with:

```markdown
- Full NAV and portfolio accounting are deferred to the future research evaluation
  surface; they are not quick-run or validation verdict metrics.
```

- [ ] **Step 4: Add an explicit docs boundary**

After the artifact boundary locked contract, insert:

```markdown
- **Current I/O docs boundary:** `docs/foundation-surfaces.md` describes
  implemented surfaces only. Do not make it speculative before research
  evaluation is implemented.
```

- [ ] **Step 5: Add an approved direction section**

After `## Accepted Debt`, before `## Deferred Until Trigger`, insert:

```markdown
## Approved Next Direction

- Build contract clarity first: docs should distinguish quick run, mechanical
  evidence validation, and research evaluation without renaming current code,
  CLI commands, package paths, artifact names, or public APIs.
- Then design and implement a stateless research evaluation surface for frozen
  candidates.
- Then improve quick-run economic diagnostics from the existing engine trade
  ledger, without putting VectorBT Pro on the quick-run hot path.
```

- [ ] **Step 6: Verify `FOUNDATION_LOCK.md`**

Run:

```bash
rg -n "two main foundation surfaces|two foundation surfaces|Full NAV and portfolio accounting are deferred\\.$" FOUNDATION_LOCK.md
git diff -- FOUNDATION_LOCK.md
```

Expected: no stale wording hits. The lock should now make C an approved next direction, not an accidental reopening.

## Task 5: Update `TODOS.md`

**Files:**
- Modify: `TODOS.md`

- [ ] **Step 1: Update the closeout goal block**

Replace:

```markdown
quick run      -> diagnose one strategy version and decide whether to keep iterating
validation run -> advisory triage for a retained candidate
```

with:

```markdown
quick run                  -> diagnose one strategy version and decide whether to keep iterating
mechanical validation      -> audit retained-candidate evidence integrity
research evaluation        -> missing stateless surface for frozen-candidate portfolio/economic evidence
```

- [ ] **Step 2: Replace the open product-contract section**

Replace the entire section from:

```markdown
## Open Product Contract TODO
```

through the line before:

```markdown
## Locked Direction
```

with:

```markdown
## Current Open Work

### C. Research evaluation surface MVP

The next missing product layer is a stateless evaluation surface for frozen
candidates. It should accept strategy/config/data references and explicit
evaluation assumptions, then return economic, path, and portfolio evidence.

Initial design boundaries:

- keep it stateless; no candidate generation, search memory, ranking, stopping
  rules, or promotion policy;
- keep validation as mechanical evidence validation, not a renamed evaluation
  run;
- use VectorBT Pro where portfolio/NAV semantics are the deliverable;
- label all NAV/path/portfolio metrics separately from engine trade-activity
  sums;
- preserve the promotion boundary: evaluation evidence does not authorize paper
  trading, live trading, or autonomous promotion.

Acceptance criteria for the next C design:

- clear input contract for frozen candidate, params, data references or splits,
  and evaluation assumptions;
- clear output contract for NAV/path metrics, drawdown, turnover, exposure,
  concentration, per-asset evidence where supported, and explicit non-claims;
- no quick-run dependency on VectorBT Pro;
- no update to `docs/foundation-surfaces.md` until an implemented evaluation
  surface exists.

### B. Quick-run economic diagnostics improvement

After C is designed, improve quick-run keep/kill diagnostics using the existing
engine trade ledger.

Candidate diagnostics:

- hit rate;
- average trade net;
- win/loss distribution;
- cost and funding share;
- active exposure or concentration summaries.

Constraints:

- keep quick run on the internal causality-controlled engine;
- do not import VectorBT Pro on the quick-run hot path;
- do not relabel engine trade-activity sums as NAV/path returns;
- do not turn quick run into strategy-quality evaluation.
```

- [ ] **Step 3: Update locked direction bullets**

Replace:

```markdown
- quick run and validation run are the two foundation surfaces;
```

with:

```markdown
- quick run and validation run are the two implemented public surfaces;
- research evaluation is the approved missing next surface;
```

Replace:

```markdown
- validation is advisory and never promotion authority;
```

with:

```markdown
- validation is mechanical evidence validation, advisory, and never promotion
  authority;
```

- [ ] **Step 4: Verify `TODOS.md`**

Run:

```bash
rg -n "Open Product Contract|docs/foundation-surfaces.md.*update|update `docs/foundation-surfaces.md`|two foundation surfaces|paper-readiness|paper readiness" TODOS.md
git diff -- TODOS.md
```

Expected: no stale open product-contract section, no instruction to update `docs/foundation-surfaces.md` in A, and no stale "two foundation surfaces" wording.

## Task 6: Update Validation And Consumer Wording

**Files:**
- Modify: `docs/validation.md`
- Modify: `docs/quant-autoresearch-consumer.md`

- [ ] **Step 1: Update the validation intro**

In `docs/validation.md`, replace:

```markdown
Validation is mechanical only. Verdict labels are advisory inputs to human review,
never autonomous promotion signals; `promotion_eligible`, `paper_trade_eligible`, and
`live_eligible` always remain false.
```

with:

```markdown
Validation is mechanical evidence validation. Verdict labels are advisory inputs
to human review, never autonomous promotion signals; `promotion_eligible`,
`paper_trade_eligible`, and `live_eligible` always remain false. Validation does
not prove alpha, statistical significance, robustness, capacity, portfolio
quality, paper-trading readiness, or live-trading readiness.
```

- [ ] **Step 2: Rename the validation section while preserving the config key**

In `docs/validation.md`, replace the heading:

```markdown
## Paper-readiness gates
```

with:

```markdown
## Mechanical review policy
```

Then insert this paragraph immediately before the TOML block:

```markdown
The config key is still `[paper_readiness]` for compatibility with the current
implementation. Treat the key as a legacy name for mechanical review thresholds,
not as a claim that validation confers paper-trading readiness.
```

- [ ] **Step 3: Replace stale wording in that section**

In `docs/validation.md`, replace:

```markdown
Validation runs always use the validation row contract;
`[paper_readiness] enabled = true` controls only the paper-readiness gates. It no
longer governs replay strictness — strict replay is always on (see below).
```

with:

```markdown
Validation runs always use the validation row contract;
`[paper_readiness] enabled = true` controls only these mechanical review
thresholds. It no longer governs replay strictness — strict replay is always on
(see below).
```

- [ ] **Step 4: Update the verdict ladder wording**

In `docs/validation.md`, replace:

```markdown
- **`mechanical_complete`** — passing data audits, required backend scenarios, valid backend
  metrics, and at least `10` trades per required scenario. With paper-readiness enabled,
  nonpositive realistic net activity is a `hard_no`.
- **`mechanical_review_candidate`** — mechanical validation plus paper-readiness gates:
  multiple windows, enough realistic-cost trades, no zero-trade windows, positive
  realistic net activity, sufficient positive-window fraction, stressed-cost and
  fill-lag loss floors, and `prior_search = "none"`.
- **`watchlist`** — positive evidence that misses paper-readiness gates or carries
  uncorrected search pressure.
```

with:

```markdown
- **`mechanical_complete`** — passing data audits, required backend scenarios, valid backend
  metrics, and at least `10` trades per required scenario. When the mechanical
  review policy is enabled, nonpositive realistic net activity is a `hard_no`.
- **`mechanical_review_candidate`** — mechanical validation plus mechanical review
  thresholds: multiple windows, enough realistic-cost trades, no zero-trade windows,
  positive realistic net activity, sufficient positive-window fraction, stressed-cost
  and fill-lag loss floors, and `prior_search = "none"`.
- **`watchlist`** — positive evidence that misses mechanical review thresholds or
  carries uncorrected search pressure.
```

- [ ] **Step 5: Update consumer-contract wording**

In `docs/quant-autoresearch-consumer.md`, replace:

```markdown
`[paper_readiness] enabled = true` controls the paper-readiness gates (window count,
trade floors, stressed and fill-lag net floors) — it no longer governs replay
strictness.
```

with:

```markdown
`[paper_readiness] enabled = true` controls the legacy-named mechanical review
thresholds (window count, trade floors, stressed and fill-lag net floors) — it
does not confer paper-trading readiness and no longer governs replay strictness.
```

- [ ] **Step 6: Verify validation and consumer docs**

Run:

```bash
rg -n "paper-readiness|paper readiness|paper-readiness gates|paper-readiness verdict|live readiness|live ready" \
  docs/validation.md docs/quant-autoresearch-consumer.md README.md PRD.md
git diff -- docs/validation.md docs/quant-autoresearch-consumer.md
```

Expected: no hyphenated or spaced paper-readiness wording remains. Literal `[paper_readiness]` may remain only as the current config key and must be accompanied by language saying it is legacy-named mechanical review policy.

## Task 7: Final Verification

**Files:**
- Verify: all modified docs
- Do not modify: `docs/foundation-surfaces.md`

- [ ] **Step 1: Run focused stale-language checks**

Run:

```bash
rg -n "two-surface|two foundation surfaces|two main foundation surfaces|paper-readiness|paper readiness|paper_candidate|promotion ready|live ready|live readiness" \
  PRD.md README.md TODOS.md FOUNDATION_LOCK.md docs/validation.md docs/quant-autoresearch-consumer.md docs/vectorbtpro.md
```

Expected: no hits, except `paper_candidate` should already be absent. If any hit remains, either revise it or document why it is an explicit non-claim.

- [ ] **Step 2: Check VectorBT quick-run boundary language**

Run:

```bash
rg -n "VectorBT Pro.*quick run|quick run.*VectorBT Pro|VectorBT.*hot path|hot path.*VectorBT" \
  PRD.md README.md TODOS.md FOUNDATION_LOCK.md docs/validation.md docs/quant-autoresearch-consumer.md docs/vectorbtpro.md
```

Expected: any hits should say VectorBT Pro is not on the quick-run hot path or is not required for quick runs.

- [ ] **Step 3: Confirm `docs/foundation-surfaces.md` was not touched by this plan**

Run:

```bash
git diff -- docs/foundation-surfaces.md
```

Expected: no output from this command. If the file is untracked from pre-existing work, leave it unstaged.

- [ ] **Step 4: Run formatting check**

Run:

```bash
git diff --check
```

Expected: no trailing whitespace or whitespace-error output.

- [ ] **Step 5: Record changed-line counts**

Run:

```bash
git diff --stat -- PRD.md README.md FOUNDATION_LOCK.md TODOS.md docs/validation.md docs/quant-autoresearch-consumer.md docs/vectorbtpro.md
git diff --numstat -- PRD.md README.md FOUNDATION_LOCK.md TODOS.md docs/validation.md docs/quant-autoresearch-consumer.md docs/vectorbtpro.md
```

Expected: docs-only changes. Report files changed, insertions, deletions, and net change in the final response.

- [ ] **Step 6: Decide whether a Python test run is needed**

Expected decision: no Python tests are required if only Markdown docs changed. If any source or test file changed unexpectedly, stop and explain the scope violation before running tests.

## Task 8: Commit The A Implementation

**Files:**
- Stage if modified by this plan: `PRD.md`
- Stage if modified by this plan: `README.md`
- Stage if modified by this plan: `FOUNDATION_LOCK.md`
- Stage if modified by this plan: `TODOS.md`
- Stage if modified by this plan: `docs/validation.md`
- Stage if modified by this plan: `docs/quant-autoresearch-consumer.md`
- Stage only if modified by this plan: `docs/vectorbtpro.md`
- Do not stage: `docs/foundation-surfaces.md`
- Do not stage: dated review/synthesis docs unless Season explicitly asks

- [ ] **Step 1: Review the final unstaged diff**

Run:

```bash
git diff -- PRD.md README.md FOUNDATION_LOCK.md TODOS.md docs/validation.md docs/quant-autoresearch-consumer.md docs/vectorbtpro.md
```

Expected: every changed line should trace to A's contract clarification. If unrelated hunks are mixed into the same files, use `git add -p` in the next step and stage only A-related hunks.

- [ ] **Step 2: Stage allowed files**

Prefer patch staging if the files contain pre-existing unrelated hunks:

```bash
git add -p PRD.md README.md FOUNDATION_LOCK.md TODOS.md docs/validation.md docs/quant-autoresearch-consumer.md docs/vectorbtpro.md
```

If the full diffs are all A-related, this non-interactive command is acceptable:

```bash
git add -- PRD.md README.md FOUNDATION_LOCK.md TODOS.md docs/validation.md docs/quant-autoresearch-consumer.md docs/vectorbtpro.md
```

Do not stage `docs/foundation-surfaces.md`.

- [ ] **Step 3: Verify staged files**

Run:

```bash
git diff --cached --name-only
```

Expected staged names are limited to:

```text
PRD.md
README.md
FOUNDATION_LOCK.md
TODOS.md
docs/validation.md
docs/quant-autoresearch-consumer.md
docs/vectorbtpro.md
```

`docs/vectorbtpro.md` may be absent if no direct contradiction was found.

- [ ] **Step 4: Commit**

Run:

```bash
git commit -m "docs: clarify foundation evaluation contract"
```

Expected: one docs commit for A. The final response should mention that `docs/foundation-surfaces.md` was intentionally not updated.
