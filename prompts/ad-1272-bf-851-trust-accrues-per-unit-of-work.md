# AD-1272 + BF-851 — trust accrues per unit of work, and verdicts combine before it is spent

**Status:** ready to build
**Closes:** BF-851 (#1319)
**Dependencies:** AD-223/AD-224 (Shapley attribution + weighted trust), AD-410 (bridge alert on
trust drop), AD-558 (dampening, hard floor, cascade), AD-1130 (`trust_write_in_progress` degrade),
BF-850 (`MAX_EXACT_SHAPLEY`)
**Related, NOT a dependency:** AD-1263 (#1303) — the duplicate-participant key in `shapley.py`.
See *Relationship to AD-1263*.
**Estimated tests:** 18–22 new

---

## Numbering

Enumerated on 2026-08-26, not recalled. `docs/development/open-ads-report.md` is **not** an
authority here — it was measured 51 ADs stale on 2026-08-25 and is presently dirty in the
working tree.

| Authority | AD ceiling | BF ceiling | How |
|---|---|---|---|
| `docs/development/open-ads-report.md` | — | — | **NOT CONSULTED — known stale** |
| `git log --all --format='%s'` | AD-1271 | BF-854 | highest with code |
| GitHub issues, all states | AD-1270 (#1324) | **BF-855 (#1325)** | highest filed |
| In-flight `prompts/ad-*.md` | AD-1271 | — | `prompts/ad-1271-scaffolding-is-not-work.md` |

**Highest allocated across every authority: AD-1271 (on `main` @ `23794731`), BF-855.**
Next free: **AD-1272**, **BF-856**.

- **BF-851** is retained — the reported symptom is a genuine regression from a conserved
  quantity being spent more than once.
- **AD-1272 is newly minted here** because the fix requires a decision that has never been
  made: *how N verifier verdicts become one verdict*, *what the trust denominator is*, and
  *whether a deliberate 0.1 floor survives*. Restoring intended behaviour would be a BF alone;
  choosing a rule that never existed is an AD.

Two identifiers, one commit. Precedent: `d5939203` (AD-1168 + AD-1169 + AD-1170),
`prompts/ad-1269-*` (AD-1257 + AD-1269).

---

## The decision

### What was measured, and what the issue gets wrong

The issue names one multiplicity. There are **three**, and they compound multiplicatively.
Measured against the real `QuorumEngine.evaluate` / `compute_shapley_values` with a faithful
copy of the spend loop at `runtime.py:4022-4028` + `4092-4095`:

| case | available | spent | calls | ratio |
|---|---|---|---|---|
| `A×3 + B`, 1 red-team | 1.0000 | 2.0000 | 4 | 2.00× |
| `A×3 + B`, **2 red-team** | 1.0000 | **4.0000** | 8 | **4.00×** |
| 3 distinct agents, 2 red-team | 1.0000 | 2.0000 | 6 | 2.00× |
| mixed verdict (B fails), 2 red-team | 0.8000 | 1.6000 | 4 | 2.00× |
| 9 agents, 2 red-team | 1.0000 | 2.0020 | 18 | 2.002× |

1. **Result multiplicity** — an agent appearing in N successful results. *(the issue's case)*
2. **Verifier multiplicity** — `verify_tasks` at `runtime.py:4092-4095` is a full cross-product
   (`for result ... for rt_agent in self.red_team_agents`), so spend is **linear in the
   red-team pool size**.
3. **The 0.1 floor** at `runtime.py:4025-4028`.

**#2 is live at 2× on stock configuration, not hypothetical.** `red_team_pool_size: int = 2`
(`config.py:176`), `red_team_pool_size: 2` (`config/system.yaml:26`), and
`tests/test_consensus_integration.py:23` asserts `len(runtime.red_team_agents) == 2`. Every
vessel running default config is double-spending through the verifier dimension **before** any
result duplication. On the measured table it is the dominant term in three of five rows.

### The floor does not do what the issue says it does — and does not do what its own comment says

The issue describes the floor as handing 0.1 "to an agent that never voted". **That path is
unreachable.** `quorum.evaluate` builds `votes` from *every* result (`quorum.py:75-90`),
`compute_shapley_values` returns a dict keyed by every distinct voter on all three of its
branches (`shapley.py:74-82`, `shapley.py:110`, `shapley.py:137`), and the verify loop filters
to `results if result.success` — a strict subset of the voters. So the `.get(..., 0.0)` default
never fires for a verified agent:

```
CLAIM: a verified agent can be absent from a non-empty shapley_values
RUN:   evaluate() over 5 shapes (3 distinct / A×3+B / mixed / varied confidence / 9-agent MC)
FOUND: missing = NONE in all 5
HOLDS: no — the claim is false; the .get default is dead code on this path
```

What the floor *actually* reaches is a **genuinely low Shapley value**, and across probes the
only successful agent measured below 0.1 was `A0 = 0.098` in the **9-agent Monte Carlo** case —
i.e. sampling noise above `MAX_EXACT_SHAPLEY = 8`. Under the exact path the minimum measured for
a successful agent was `0.125` (8 agents, equal split). So the floor's sole live effect is
**masking Monte Carlo noise, nondeterministically**, and it is the term that turns `1.0000` into
`2.0020` in the table above.

Its stated reason — give a zero-weight agent *some* signal — does not survive either, because
the signal is not carried by the weight:

- the per-`(verifier, target)` Hebbian edge (`routing.py:234-249`) is weight-independent;
- the `verification_complete` event row (`runtime.py:4069-4077`) is weight-independent;
- the returned `verifications` list (`runtime.py:4127`) is weight-independent.

A zero-weight agent already gets three independent signals. The floor buys nothing and breaks
conservation.

### D1 — one trust update per (agent, round), keyed on the agent

Trust accrues **per unit of work**, not per result row and not per verifier. The unit of work is
"this agent contributed to this round". Both #1 and #2 collapse under the same grouping, so
this is a single change, not two.

### D2 — verdicts combine by confidence-weighted approval against the quorum threshold

**Reuse the rule the system already has.** `_evaluate_coalition` (`shapley.py:20-39`) is exactly
this rule — `weighted_approval / total_weight >= approval_threshold` — and it is already the
authority for "did a weighted set of booleans agree?" on the consensus path.

Do **not** call `_evaluate_coalition` directly: it is private and `Vote`-typed, and a
`VerificationResult` is not a ballot. Do **not** construct throwaway `Vote` objects to reach it —
that is a type lie. Instead add a public sibling that applies the same arithmetic to verdicts.

Why confidence-weighted rather than unanimous or plain majority:

- `VerificationResult` already carries `confidence: float` (`types.py:270`) alongside
  `verified: bool` — the shape is there, unused on this path.
- Verifier confidence is genuinely **per-agent and mutable**: `self.confidence` starts at
  `initial_confidence` (`agent.py:38, 46`) and is moved by `record_success`/`record_failure`
  (`agent.py:121-128`). Weighting is therefore not degenerate — a verifier with a poor track
  record carries less. Unanimity would discard that signal and hand any single verifier a veto.
- `RedTeamAgent` deliberately returns `confidence=0.1` for its benefit-of-the-doubt pass on
  unknown intents (`red_team.py:96-97`) while a real judgement carries `self.confidence`.
  Confidence weighting is the only rule that honours that distinction; majority would let a
  0.1-confidence shrug outvote a considered verdict.

**Threshold: reuse `policy.approval_threshold`** (default `0.6`, `quorum.py` policy). Do **not**
add a new config knob. The system has already decided what fraction constitutes agreement; a
second threshold would be an unasked-for setting with no principled default.

### D3 — the rule lives in the consensus layer; the runtime only sequences

The runtime spend loop is the only place that *sees* the multiplicity, but seeing is not owning.
This is the Design Principle #1 boundary: a service may own *when a durable step runs and
whether it may run twice*; it may not own *how good the work was*. Combining verdicts is a
judgement, and judgements about consensus belong in `consensus/`.

- **New module `src/probos/consensus/verification.py`** owns the rule as a pure function.
  Not `quorum.py`: that module already carries `QuorumEngine` + `vote_on_intent` and is about
  agreement among *producers*; verifier agreement is a second responsibility (SRP).
- **`runtime.py` owns sequencing only** — gather verdicts, group by target, call the rule once,
  apply once.

### D4 — the floor is removed

Weight is the agent's Shapley value as computed. The `weight = 1.0` branch when
`consensus.shapley_values` is empty/None (`runtime.py:4023`, the `INSUFFICIENT` outcome) is a
**different branch and is untouched**.

If an agent is somehow absent from a *non-empty* `shapley_values`, **skip the trust update** and
log a warning — do not fabricate a weight. Attribution from nowhere is worse than no
attribution. This is measured-unreachable today (see the enumeration above); it is one guarded
line, not a subsystem, and it is warranted because `_approximate_shapley` is a sampling path.

### D5 — the combined update's `verifier_id` is a deterministic sorted join

`record_outcome(verifier_id=...)` is a single `str` (`trust.py:311`) persisted onto `TrustEvent`
(`trust.py:420, 462`). Enumerated consumers of the *consensus-path* value:

```
CLAIM: nothing outside TrustEvent construction reads the consensus-path verifier_id
RUN:   grep -rn "verifier_id" src/probos/
FOUND: trust.py:420,462 (TrustEvent) — the only consumers of THIS path's value.
       renderer.py:597-600 reads VerificationResult.verifier_id (a different object).
       thread_fanout.py:928 passes o.verifier_id from source="conversation" (a different path).
       crew_trust*.py / crew_verifier.py use verifier_agent_id on the crew path (unrelated).
HOLDS: yes — no strict consumer constrains the format
```

Write `",".join(sorted(verifier_ids))` over the verifiers that actually returned a verdict.
This is deterministic (the `verification_results` list is appended from concurrent tasks at
`runtime.py:4020`, so arrival order is nondeterministic — sorting is required, not cosmetic),
and it **degenerates to exactly today's value when one verifier contributed**, keeping the
single-verifier case byte-identical.

### Supporting precedent — the newer path already avoids this

The crew verification path never fans out: `_pick_independent_verifier` returns `str | None`
(`crew_verifier.py:1099`, definition at the AD-866 selection-order docstring) and
`_pick_live_session_verifier` likewise (`crew_verifier.py:1341`). One verifier per unit of work
is already the established shape in the newer subsystem; the consensus path is the outlier.
This does not change the decision — the Captain has ruled that verdicts **combine** rather than
that one verifier is chosen — but it confirms "one trust update per unit of work" is the
house invariant, not a new invention.

---

## Relationship to AD-1263

`compute_shapley_values` builds `vote_by_id = {v.agent_id: v for v in votes}` (`shapley.py:66`),
so duplicate voters collapse there — that is #1303 / AD-1263, **not shipped** (no `AD-1263`
subject in `git log --all`).

The two are independent and this prompt does not depend on that fix:

- AD-1263 changes *what the dict contains* (it recovers a discarded ballot).
- AD-1272 changes *how many times the dict is spent*.

After this change the spend is keyed on distinct successful `agent_id`s, so a later AD-1263 fix
alters the **value** each agent draws without reintroducing any multiplicity. **Do not build
AD-1263 here.**

---

## Implementation

### Section 1 — `src/probos/consensus/verification.py` (new)

One public function, fully typed, no runtime imports (Dependency Inversion — it takes data,
not the runtime).

```python
"""Combining independent verification verdicts into one outcome (AD-1272)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from probos.types import VerificationResult
```

Public API:

```python
def combine_verdicts(
    verdicts: list[VerificationResult],
    approval_threshold: float,
    use_confidence_weights: bool = True,
) -> tuple[bool, tuple[str, ...]] | None:
    """Combine independent verification verdicts into a single outcome.

    Returns ``(verified, verifier_ids)`` where ``verifier_ids`` is sorted and
    deduplicated, or ``None`` when there is nothing to combine.
    """
```

Required behaviour:

| input | result | why |
|---|---|---|
| `[]` | `None` | nothing arrived — the caller must not update trust |
| one verdict | `(v.verified, (v.verifier_id,))` | byte-identical to today's single-verifier case |
| N verdicts, weights available | `weighted_approval / total_weight >= approval_threshold` | mirrors `_evaluate_coalition` (`shapley.py:30-39`) |
| N verdicts, `total_weight == 0` | fall back to **unweighted** majority against the same threshold | a verifier metadata gap must not read as "failed verification" |
| `use_confidence_weights=False` | unweighted majority against the threshold | mirrors the policy flag |

`total_weight == 0` is a real boundary, not defensive padding: `VerificationResult.confidence`
defaults to `0.0` (`types.py:270`) and two other modules construct the type
(`cognitive/observable_state.py`, `cognitive/repair_verification.py`). Note that
`_evaluate_coalition` returns `False` in this situation — **do not copy that**, because here
`False` is a trust penalty rather than a failed coalition.

### Section 2 — restructure the verify block in `runtime.py`

Current shape, `runtime.py:4006-4098`:

```
verification_results = []                       # 4008
async def _verify_one(rt_agent, result):        # 4012
    vr = await asyncio.wait_for(...)            # 4015-4019
    verification_results.append(vr)             # 4020
    ... shapley_weight w/ 0.1 floor             # 4022-4028
    ... _old_trust                              # 4029
    ... record_outcome (AD-1130 guarded)        # 4031-4053
    ... bridge alert (AD-410)                   # 4055-4061
    ... record_verification (Hebbian)           # 4063-4067
    ... event_log verification_complete         # 4069-4077
    except TimeoutError / Exception             # 4078-4090
verify_tasks = [ ... cross product ... ]        # 4092-4096
await asyncio.gather(*verify_tasks)             # 4098
```

Target shape — **`_verify_one` stops writing trust**:

1. `_verify_one` keeps: `wait_for`, `verification_results.append(vr)`, the per-`(verifier,
   target)` Hebbian `record_verification`, the per-verification `event_log` row, and its own
   `TimeoutError` / `Exception` handlers. It **must** keep its own exception isolation — a
   verifier that times out contributes no verdict and must not abort the others.
2. Delete the trust block (`4022-4061`) from `_verify_one`.
3. After `await asyncio.gather(*verify_tasks)` (line 4098), add a new phase:
   - group `verification_results` by `target_agent_id`;
   - for each group, call `combine_verdicts(...)` with
     `policy.approval_threshold` / `policy.use_confidence_weights`;
   - skip the agent when it returns `None`;
   - resolve the weight: `1.0` when `consensus.shapley_values` is empty, else
     `consensus.shapley_values.get(agent_id)` — **skip with a warning if that is `None`**;
   - capture `_old_trust`, call `record_outcome` **once** inside the existing AD-1130
     `try/except RuntimeError` shape, then run the AD-410 bridge-alert check **once**.

Keep the AD-1130 `except RuntimeError` body's log message accurate: it currently names a single
`verifier=%s`. Update it to report the combined verifier set, and keep the sentence that
verification/Hebbian/completion recording continue — that claim is still true, and
`tests/test_consensus_integration.py:124-149` enforces it.

### Section 3 — no config change

Do not add a verification-threshold setting. `policy.approval_threshold` is reused. If the
Builder finds itself editing `config.py`, stop — that is out of scope.

---

## What must NOT change — do not build

Each row was checked against the live tree.

| # | Property | Anchor | Requirement |
|---|---|---|---|
| 1 | AD-1130 `trust_write_in_progress` degrade | `runtime.py:4040-4053`; test at `tests/test_consensus_integration.py:124-149` | Verifications, Hebbian edges and the `verification_complete` event must all survive a raising `record_outcome`. The test monkeypatches it to **always** raise — with one combined call the degrade is now all-or-nothing per agent, and the assertions must still hold. |
| 2 | AD-410 bridge alert | `runtime.py:4029` (`_old_trust`), `4055-4061`; `bridge_alerts.py:310-345` | Now computed **once per agent** around the single update. Note the dedup key is `trust_drop:{agent_id}` gated by `_should_emit` (`bridge_alerts.py:329-331`), so today's N computations were already collapsing to at most one alert — observable behaviour should be unchanged. Verify, do not assume. |
| 3 | Per-`(verifier, target)` Hebbian | `runtime.py:4063-4067` → `routing.py:234-249` | **Stays per-pair.** Every `(verifier, target)` is a distinct edge with `rel_type=REL_AGENT`. Do **not** collapse this. |
| 4 | Per-verification `event_log` row | `runtime.py:4069-4077`; asserted at `tests/test_consensus_integration.py:122, 152` | **Stays per-verification.** N verifications still produce N `verification_complete` rows. |
| 5 | **`verification_results` stays per-verifier** | appended at `runtime.py:4020`, returned as `"verifications"` at `runtime.py:4127`, rendered at `renderer.py:594-601` | The renderer prints one `verifier_id -> target_agent_id verified=` line per element. Combination affects the **trust update only** — never this list. *(Not listed in the issue.)* |
| 6 | **`verification_count` stays N** | `runtime.py:4114` | `len(verification_results)` in the `intent_resolved` event is a count of verifications performed, not of trust updates. *(Not listed in the issue.)* |
| 7 | **Per-verifier failure isolation** | `runtime.py:4078-4090` | Each `_verify_one` catches its own `TimeoutError`/`Exception`. A timed-out verifier contributes no verdict; if an agent ends with **zero** verdicts it gets **no** trust update. *(Not listed in the issue.)* |
| 8 | **The `weight = 1.0` empty-Shapley branch** | `runtime.py:4023` | When the outcome is `INSUFFICIENT`, `shapley_values` is empty and weight stays `1.0`. Untouched. *(Not listed in the issue.)* |
| 9 | **Mutable verifier confidence** | `agent.py:46, 121-128` | Do not freeze or normalise `self.confidence`. The combinator reads it as-is. |
| 10 | AD-558 dampening / hard floor / cascade | `trust.py:410-451` | `effective_weight = outcome.weight * dampening_factor`, and the hard-floor branch applies **zero**. These are deliberate and downstream. Do not touch, and do not assert conservation on alpha/beta deltas — see *Tests*. |

**Also do not build:**

- **AD-1263 / #1303** — the `vote_by_id` collapse at `shapley.py:66`. Independent; see above.
- **`compute_shapley_values` itself** — measured conserved (sums to `1.0000`, or `0.8000` when
  negative marginals are clamped on a mixed-verdict round). The defect is entirely in the consumer.
- **`MAX_EXACT_SHAPLEY` / the Monte Carlo path** (BF-850). Removing the floor exposes sampling
  noise (`A0 = 0.098` at n=9) as a real weight. That is *correct* — it is the value the estimator
  produced. If the noise proves material, file it; do not tune the estimator here.
- **The conversation-trust path** — `thread_fanout.py:920-936` writes with `source="conversation"`.
  Different producer, not in scope.
- **The crew verification path** — `crew_verifier.py`, `crew_trust.py`, `crew_trust_effect.py`.
  Already single-verifier; no multiplicity to fix.
- **A new config knob.** See Section 3.
- **The AD-451 validation framework** (`cognitive/validation_framework.py:262`) also consumes
  `red_team_agents`. Out of scope — do not restructure it.

---

## Tests

New file `tests/test_ad1272_trust_accrues_per_unit_of_work.py`.

### The assertion that could not be written before

The issue states a literal conservation assertion cannot be written. **After this change it can**,
and it holds exactly. Measured form (equal to `1e-9` across all five shapes in the table above,
including the `0.8000` mixed-verdict round):

```python
sum(weights_passed_to_record_outcome_this_round)
    == sum(
        consensus.shapley_values[a]
        for a in {r.agent_id for r in results if r.success}
    )
```

Two constraints on its form — both measured, both mandatory:

1. **Assert on the weights PASSED to `record_outcome`, never on alpha/beta deltas.**
   `effective_weight = outcome.weight * dampening_factor` (`trust.py:446`) and the hard-floor
   branch (`trust.py:410-444`) applies zero. Those are AD-558 behaviours; an assertion on deltas
   would pin them by accident and fail for the wrong reason.
2. **The denominator is the sum over *verified* agents, not `1.0`.** A mixed-verdict round has an
   available total of `0.8000` because `max(0.0, v)` clamps negative marginals before normalising
   (`shapley.py:78-79`). Hard-coding `1.0` produces a test that passes only on all-approve rounds.

Add alongside it: `len(record_outcome calls) == len({r.agent_id for r in results if r.success})`
— one update per unit of work.

### Required cases

**`combine_verdicts` (unit, `consensus/verification.py`):**

1. empty list → `None`
2. single verdict → `(verified, (verifier_id,))`, both `True` and `False`
3. two agree `True` → `True`; two agree `False` → `False`
4. split with unequal confidence → the higher-confidence side wins
5. split where the **low-confidence** side is numerically larger → confidence decides, proving
   the weighting is live rather than a majority in disguise
6. all confidences `0.0` → unweighted majority, **not** `False`
7. `use_confidence_weights=False` → unweighted
8. exactly at `approval_threshold` → approves (`>=`, matching `shapley.py:39`)
9. `verifier_ids` sorted and deduplicated regardless of input order

**Spend conservation (integration, against the real `QuorumEngine`):**

10. `A×3 + B`, 1 verifier — spent equals available; 2 calls, not 4
11. `A×3 + B`, 2 verifiers — spent equals available; 2 calls, not 8
12. 3 distinct agents, 2 verifiers — 3 calls, not 6
13. mixed verdict — denominator is `0.8`, not `1.0`
14. 9 agents (Monte Carlo) — conserved; **no** `0.1` floor applied
15. `shapley_values` empty (`INSUFFICIENT`) → weight `1.0` per agent, floor branch untouched

**Preservation (must fail if the restructure regresses):**

16. `record_outcome` raising `trust_write_in_progress` → verifications, `REL_AGENT` Hebbian
    weights, and `verification_complete` events all survive *(mirrors
    `tests/test_consensus_integration.py:124-149`)*
17. N verifiers → N `verification_complete` rows and N `REL_AGENT` edges, but **one** trust update
18. `verification_count` in `intent_resolved` equals N, not the collapsed count
19. one verifier times out → its verdict is absent, the other still combines and updates once
20. **all** verifiers for an agent fail → **zero** trust updates for that agent, and no exception
21. `verifier_id` on the combined update is the sorted join; with one verifier it is byte-identical
    to that verifier's id

**Do not** delete or weaken `tests/test_consensus_integration.py`. If any assertion there fails,
the restructure is wrong — that file is the existing contract, not an obstacle.

### Running

```powershell
# focused, serial
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1272_trust_accrues_per_unit_of_work.py tests/test_consensus_integration.py -q -p no:randomly

# broad gate, ONCE, after the work is frozen and review findings are repaired
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q
```

Run the adversarial `Diff Reviewer` on the staged diff **before** the broad gate, with a
different model than the one that wrote the code. Repair its findings first — a source change
after a broad gate invalidates that gate.

---

## Scope — one issue, not three

The 0.1 floor and the verifier dimension **must not** be split out.

- Splitting the floor ships a "conservation fix" that **fails its own assertion**: at n=9 the
  collapsed-but-floored spend is `2.0020` against `1.0000` available. The conservation test could
  not be written until the floor is gone, so a floor-later split has no green acceptance criterion.
- Splitting the verifier dimension is not possible without duplicating work: multiplicities #1 and
  #2 collapse under **the same grouping key**. Fixing one leaves a loop that must be rewritten
  again for the other.
- Only #2 requires the verdict-combination decision, and #2 is live at 2× on stock config, so it
  cannot be deferred as a follow-up.

All three collapse in one restructure. Splitting manufactures a broken intermediate state.

---

## Acceptance criteria

1. `combine_verdicts` exists in `src/probos/consensus/verification.py`, is fully type-annotated,
   and imports nothing from `runtime`.
2. Exactly **one** `record_outcome` call per distinct successful `agent_id` per round, regardless
   of result count or red-team pool size.
3. The literal conservation assertion holds: total weight passed equals the sum of Shapley values
   over verified agents, to `1e-9`, on all six shapes in *Required cases* 10–15.
4. The `max(..., 0.1)` floor is gone from `runtime.py`. The `weight = 1.0` empty-Shapley branch
   remains.
5. An agent absent from a non-empty `shapley_values` is **skipped with a warning**, never
   defaulted to a weight.
6. All ten *must NOT change* properties verified by test, not by inspection — in particular #3
   (per-pair Hebbian), #4 (per-verification events), #5 (per-verifier `verifications` list),
   and #7 (an agent with zero surviving verdicts gets no update).
7. `tests/test_consensus_integration.py` passes **unmodified**.
8. No new configuration field.
9. Log messages carry context — what was combined, how many verdicts, what the system did next.
   The AD-1130 warning is updated to name the combined verifier set rather than a single verifier.
10. Full repository suite green, run once after the work is frozen; report the test count.
11. `Diff Reviewer` run on the staged diff with a different model, and its Critical/High findings
    repaired before commit.
12. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Tracking

| File | Update |
|---|---|
| `PROGRESS.md` | AD-1272 entry; BF-851 → CLOSED with a one-line cause |
| `DECISIONS.md` (era 5) | AD-1272 — one trust update per unit of work; confidence-weighted verdict combination at `policy.approval_threshold`; 0.1 floor removed |
| `docs/development/roadmap.md` | Bug Tracker row for BF-851 |
| GitHub | close #1319 with the measured before/after table |

Do **not** regenerate `docs/development/open-ads-report.md` as part of this work — it is
already dirty in the tree and is a separate concern.

---

## Verified Against Codebase (2026-08-26, `main` @ `23794731`)

Every claim below was grepped or executed. Nothing is from memory.

### The spend loop

```
runtime.py:3982   consensus = self.quorum_engine.evaluate(results, policy=policy)
runtime.py:4006   # Step 3: Red team verification (verify a sample of results)
runtime.py:4008   verification_results = []
runtime.py:4010   verification_timeout = self.config.consensus.verification_timeout_seconds
runtime.py:4012   async def _verify_one(
runtime.py:4020   verification_results.append(vr)
runtime.py:4022   # Step 4: Update trust network (AD-224: Shapley-weighted)
runtime.py:4023   shapley_weight = 1.0
runtime.py:4025   shapley_weight = max(
runtime.py:4026       consensus.shapley_values.get(result.agent_id, 0.0),
runtime.py:4027       0.1,
runtime.py:4029   _old_trust = self.trust_network.get_score(result.agent_id)  # AD-410
runtime.py:4042   if str(exc) != "trust_write_in_progress":
runtime.py:4063   self.hebbian_router.record_verification(
runtime.py:4071   event="verification_complete",
runtime.py:4078   except asyncio.TimeoutError:
runtime.py:4084   except Exception:
runtime.py:4092   verify_tasks = [
runtime.py:4094       for result in results if result.success
runtime.py:4095       for rt_agent in self.red_team_agents
runtime.py:4097   if verify_tasks:
runtime.py:4098   await asyncio.gather(*verify_tasks)
runtime.py:4114   "verification_count": len(verification_results),
runtime.py:4127   "verifications": verification_results,
```

Line 3982 and line 4094 consume **the same `results` list** — confirmed by reading both sites.

### Signatures

```
trust.py:304-312    def record_outcome(self, agent_id, success, weight=1.0, intent_type="",
                        episode_id="", verifier_id="", source="verification") -> float
trust.py:100        verifier_id: str  # which red-team agent verified
trust.py:420, 462   verifier_id=outcome.verifier_id   (TrustEvent construction — both branches)
trust.py:446        effective_weight = outcome.weight * dampening_factor
routing.py:234-249  def record_verification(self, verifier_id, target_id, verified) -> float
                        -> record_interaction(source=verifier_id, target=target_id,
                                              success=verified, rel_type=REL_AGENT)
bridge_alerts.py:310  def check_trust_change(self, agent_id, old_score, new_score) -> BridgeAlert | None
bridge_alerts.py:329  key = f"trust_drop:{agent_id}"   (dedup, gated by _should_emit)
types.py:262-273    class VerificationResult: verifier_id, target_agent_id, intent_id,
                        verified: bool, expected, actual, discrepancy,
                        confidence: float = 0.0, timestamp
shapley.py:17       MAX_EXACT_SHAPLEY = 8
shapley.py:20-39    def _evaluate_coalition(coalition_votes, approval_threshold,
                        use_confidence_weights) -> bool     # PRIVATE, Vote-typed
shapley.py:39       return (weighted_approval / total_weight) >= approval_threshold
shapley.py:66       vote_by_id = {v.agent_id: v for v in votes}   # AD-1263 / #1303
shapley.py:78-79    normalized = {aid: max(0.0, v) / total for aid, v in raw_values.items()}
quorum.py:47        def evaluate(self, results, policy=None) -> ConsensusResult
quorum.py:75-90     votes built from EVERY result
agent.py:38, 46     initial_confidence: float = 0.8 ; self.confidence = self.initial_confidence
agent.py:121-128    self.confidence moved by record_success / record_failure
red_team.py:96-97   verified=True, confidence=0.1   # benefit of the doubt, unknown intents
crew_verifier.py:1099  verifier_id = self._pick_independent_verifier(result.agent_id)  -> str | None
crew_verifier.py:1341  verifier_id = self._pick_live_session_verifier(excluded_agent_ids)
```

### Configuration — multiplicity #2 is live by default

```
config.py:176                    red_team_pool_size: int = 2
config/system.yaml:26            red_team_pool_size: 2
runtime.py:2392-2399             async def _spawn_red_team(self, count) -> appends N RedTeamAgents
tests/test_consensus_integration.py:23   assert len(runtime.red_team_agents) == 2
```

### Existing contract tests

```
tests/test_consensus_integration.py:122       assert "verification_complete" in event_types
tests/test_consensus_integration.py:124-149   test_busy_trust_preserves_verification_hebbian_and_event
                                              -> asserts result["verifications"], REL_AGENT weights,
                                                 and the verification_complete event survive a
                                                 record_outcome that always raises
tests/test_consensus_integration.py:152       assert any(event == "verification_complete" ...)
renderer.py:594-601                           iterates node_res["verifications"], one line per verdict
```

### Measured, not read

Executed against the real `QuorumEngine.evaluate` / `compute_shapley_values` with a faithful copy
of `runtime.py:4022-4028` + `4092-4095`. **Premise asserted first** — a normal 3-agent round
returns a non-empty `shapley_values` summing to `1.0000` — so the numbers below discriminate.

```
case                   outcome   avail_all  avail_ok   spent calls  collapsed
A x3 + B, 1 rt         approved     1.0000    1.0000  2.0000     4     1.0000 calls=2
A x3 + B, 2 rt         approved     1.0000    1.0000  4.0000     8     1.0000 calls=2
3 distinct, 2 rt       approved     1.0000    1.0000  2.0000     6     1.0000 calls=3
mixed B fails, 2rt     approved     0.8000    0.8000  1.6000     4     0.8000 calls=2
9 agents, 2 rt         approved     1.0000    1.0000  2.0020    18     1.0000 calls=9

--- collapsed + NO floor (the candidate invariant) ---
A x3 + B, 1 rt         spent=1.000000 avail_verified=1.000000 equal=True
A x3 + B, 2 rt         spent=1.000000 avail_verified=1.000000 equal=True
3 distinct, 2 rt       spent=1.000000 avail_verified=1.000000 equal=True
mixed B fails, 2rt     spent=0.800000 avail_verified=0.800000 equal=True
9 agents, 2 rt         spent=1.000000 avail_verified=1.000000 equal=True
```

The `2.0020` row is the floor: `A0 = 0.098` from Monte Carlo sampling was raised to `0.1`.
It is **nondeterministic** — a later run of the same shape produced no sub-floor value, because
`_approximate_shapley` reshuffles on every call (`shapley.py:124-125`).

### Absence verified

```
CLAIM: a verified agent can be missing from a non-empty shapley_values (the .get default fires)
RUN:   evaluate() over 5 shapes; missing = {r.agent_id for r in results if r.success} - set(sv)
FOUND: missing = NONE in all 5 (3 distinct / A x3 + B / mixed / varied confidence / 9-agent MC)
HOLDS: NO — the claim is FALSE. The .get(..., 0.0) default is unreachable on this path.

CLAIM: a successful (therefore verified) agent can draw a Shapley value below 0.1
RUN:   4 further shapes under the EXACT path (1 ok + 4 fail / 5 ok with one conf=0.01 /
       2 ok + 3 fail / 8 ok equal)
FOUND: zero = [] and under0.1 = [] in all 4; minimum measured 0.125 (8 agents, equal split)
HOLDS: not reproduced under the exact path. The ONLY sub-floor value measured for a successful
       agent was A0 = 0.098 in the 9-agent MONTE CARLO case — i.e. sampling noise above
       MAX_EXACT_SHAPLEY = 8. Stated as measured, not as "never".

CLAIM: nothing outside TrustEvent construction consumes the consensus-path verifier_id
RUN:   grep -rn "verifier_id" src/probos/   (full enumeration, 90+ hits reviewed)
FOUND: trust.py:420,462 only. renderer.py:597-600 reads VerificationResult.verifier_id (a
       different object); thread_fanout.py:928 is source="conversation" (a different path);
       crew_*.py use verifier_agent_id (a different path).
HOLDS: yes — the format is unconstrained, so a sorted join is safe.

CLAIM: AD-1263 has shipped
RUN:   git log --all --format='%h %s' | Select-String "AD-1263"
FOUND: (no results)
HOLDS: NO — not shipped. This prompt must not depend on it.
```
