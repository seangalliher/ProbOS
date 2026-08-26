# AD-1263 (revision 2) — one player per participant key, and an exact bound that can afford itself

**Status:** ready to build
**Supersedes:** `prompts/ad-1263-shapley-duplicate-participant-key.md` (revision 1 — BUILT, REVERTED)
**Closes:** BF-837 (#1303) · **BF-850** (new, minted here)
**Files (does not fix):** **BF-851** (new, minted here)
**Dependencies:** AD-223/AD-224 (`compute_shapley_values`), AD-289 (`MAX_EXACT_SHAPLEY`), AD-861 (`crew_synth` attribution), AD-1130 (`crew_trust` composite keys)
**Estimated tests:** 18 new in one new file; **1 existing test amended** (`test_performance_p0.py`, mandatory — see §Consumers)

---

## 1. Numbering — this stays AD-1263

| Question | Answer |
|---|---|
| Did anything ship under AD-1263? | **No.** Built, then reverted; `git log -S "votes_by_id" src/` is empty at HEAD. |
| Is the number consumed? | **No.** An AD number is consumed by a landed commit, not by an attempt. |
| Decision | **Stays AD-1263.** Minting AD-1267 would leave a permanent orphan hole and still require a "superseded by" pointer. Revision 2 of an unshipped number is the cheaper, more legible record. |
| Next free AD after this one | **AD-1267** (unchanged — AD-1265/1266 remain the backup redesign). |

Two BF numbers **are** minted, because the measurements below surfaced two live defects at HEAD that are *not* #1303 and must not be smuggled into it:

| New | Title | Status in this AD |
|---|---|---|
| **BF-850** | Exact Shapley enumerates 10! on the unguarded destructive-op consensus path — **measured 31.9 s** at HEAD | **CLOSED by this AD** (§4) |
| **BF-851** | `runtime` spends a Shapley weight once per *(successful result × red-team agent)*, so a duplicated `agent_id` spends its weight N times — **measured total 2.0 against 1.0 available** at HEAD | **FILED ONLY.** Explicitly out of scope; §5 pins that this AD does not move it. |

Next free BF after this one: **BF-852**.

---

## 2. Why revision 1 was reverted — both blockers re-measured, and both re-attributed

The Captain's two blockers are real. Re-measuring them changed *which component owns each one*, and that is the whole design difference in revision 2.

### Blocker A — "trust writes doubled"

**Measured, HEAD vs revision-1 prototype, simulating `runtime.py:4092-4095` faithfully:**

```
scenario                                HEAD shapley        HEAD spent   FIX shapley         FIX spent
dual-role A approves twice (BF-833)     {A:.5,  B:.5 } 1.00 {A:1.0,B:.5} {A:.5,  B:.5 } 1.00 {A:1.0,B:.5}   TOTAL 1.50 -> 1.50
A x3 + B                                {A:.5,  B:.5 } 1.00 {A:1.5,B:.5} {A:.5,  B:.5 } 1.00 {A:1.5,B:.5}   TOTAL 2.00 -> 2.00
3 distinct all approve (control)        {A:.33,B:.33,C:.33} {each .33}   identical            identical      TOTAL 1.00 -> 1.00
dual-role A, split verdicts             {A:.33,B:.33} 0.67 {A:.33}       {A:.5,  B:.0 } 0.50 {A:.5}         TOTAL 0.33 -> 0.50
```

**The doubling is a HEAD defect and revision 1 did not cause it.** `A x3 + B` spends
**2.00 against 1.00 available at HEAD today**, because the spend loop is

```python
verify_tasks = [                                   # runtime.py:4092-4095
    _verify_one(rt_agent, result)
    for result in results if result.success
    for rt_agent in self.red_team_agents
]
```

— one `record_outcome` per *result*, keyed `consensus.shapley_values.get(result.agent_id, 0.0)`
(`runtime.py:4025-4026`). The number of trust writes is a function of the **result list**,
never of the player set. Duplicate `agent_id` in `results` ⇒ N writes of the same weight,
at HEAD, before and after any change here.

**What revision 1 actually did to the spend: nothing, except in one case.** The value —
and therefore the spend — moves *only* where the Shapley value moves, and that is only the
mixed-verdict duplicate case (`A` gains `+0.167` because its discarded approving ballot is
finally counted, which is the fix working). Every all-approving case is **byte-identical**.

So revision 1's blocker A was a correct observation of a real defect attributed to the
wrong change. That defect is **BF-851**, filed, not fixed here. What revision 1 genuinely
lacked was any statement of *who spends and how many times* — §5 supplies it, and the
acceptance criteria pin spend **neutrality** against HEAD rather than a conservation
property that HEAD does not have (§7.2 — this corrects the Captain's brief).

### Blocker B — the latency cliff

Real, decisive, and **also a HEAD defect that revision 1 merely made reachable more often.**

```
HEAD, 11 ballots / 10 distinct players :  n = len(votes) = 11  -> MONTE CARLO -> 0.0081 s
FIX,  11 ballots / 10 distinct players :  n = len(players) = 10 -> EXACT      -> 10! = 3,628,800 perms

HEAD,  9 DISTINCT agents (n=9)  -> exact ->  2.0751 s
HEAD, 10 DISTINCT agents (n=10) -> exact -> 34.6517 s      <-- live at HEAD, no fix required to reach it
HEAD, 11 DISTINCT agents (n=11) -> monte carlo -> 0.0127 s
```

`MAX_EXACT_SHAPLEY = 10` has been unaffordable since AD-289 set it (`e33431f4`). HEAD's
`n = len(votes)` **accidentally** protected the duplicate case by overcounting, while
leaving the distinct case wide open. Revision 1 correctly made `n` the player count and
thereby removed the accident — without re-deriving the bound for the quantity that now
selects it. **That is the actual defect in revision 1: it changed the units of `n` and left
the threshold calibrated for the old units.**

---

## 3. Decision D1 — a player is a participant key. Attribution is per-agent, not per-role.

**A key appearing more than once is ONE player who cast more than one ballot, and that
player contributes ALL of their ballots to any coalition they join.** A dual-role agent
receives **one** attribution value that folds both roles — *not* two.

### Why not per-role (the shape #1303 proposes)

Four independent blocks, three of them measured:

| Block | Evidence |
|---|---|
| Not JSON-serialisable | `episodic.py:3436` does `json.dumps(ep.shapley_values)`. Measured: `TypeError: keys must be str, int, float, bool or None, not tuple`. |
| Three bare-id lookups break | `panels.py:267` `shapley_values.get(agent.id)`; `runtime.py:4026`; `crew_synth._record_trust` `for agent_id in shapley`. |
| HXI type | `ui/src/store/types.ts:349` — `Record<string, number>`. |
| **The trust spend silently floors** | `runtime.py:4025-4026` is `max(shapley_values.get(result.agent_id, 0.0), 0.1)`. Under per-role keys **no** `result.agent_id` matches any key, every lookup returns `0.0`, and **every agent in every consensus round is written at the 0.1 floor.** Silent, total, and worse than the defect being fixed. |

The fourth is the one revision 1's rejected-alternatives table did not have, and it is on its
own sufficient. **Per-role keys are unavailable, not merely inconvenient.**

### Where the collapse happens, and why that layer

> **Inside `compute_shapley_values`, at player-map construction, before any enumeration.**

That is the right layer for exactly one reason: **it is the only layer that sees every
ballot at once, and it is upstream of every consumer that keys by agent id.** Collapsing
later (in `quorum`, in `runtime`, in `crew_synth`) means each consumer re-derives the fold
and they will drift. Collapsing earlier (at `_build_votes`) means `crew_synth` must
un-collapse before `_record_trust`, `_store_episode`, the `CREW_TASK_COMPLETED` payload
and `SynthesisResult.shapley_values` — four seams changed to fix a defect one level down.

The dual-role agent therefore gets **one attribution and one weight lookup**. It may still
receive *several trust writes* — one per successful `IntentResult` — but that count is
owned by `runtime`'s result loop and is **BF-851**, not this AD. Attribution and the
*spending* of attribution are different concerns living in different layers; revision 1's
omission was failing to say so.

`Vote.agent_id` is already an opaque participant key in production, not an agent identity —
`crew_trust.py:252-253` writes `child:<work_item_id>` and `facilitator:<session_id>`. The
model here is the generalisation of that existing precedent, and needs **zero** changes in
`crew_synth` or `crew_trust`.

---

## 4. Decision D2 — the bound is stated in post-split players, and lowered to where it is affordable

### The rule

> **`MAX_EXACT_SHAPLEY` bounds `n = len(agent_ids)` — the POST-SPLIT PLAYER COUNT — and
> nothing else. Any quantity that selects the enumeration strategy must be measured in the
> same units as the thing enumerated.**

Revision 1 obeyed half of this (it made `n` the player count) and broke the other half (it
left the bound calibrated for ballots). Both halves ship together or neither does.

### The measured budget

Exact enumeration is `n!` permutations × `n` coalition evaluations. Measured on this machine
against the real `_exact_shapley`:

| players | permutations | exact elapsed | verdict |
|---:|---:|---:|---|
| 6 | 720 | 0.0034 s | fine |
| 7 | 5,040 | 0.0261 s | fine |
| **8** | **40,320** | **0.2456 s** | **largest that holds the budget** |
| 9 | 362,880 | 2.0807 s | busts it by 4× |
| 10 | 3,628,800 | 31.8825 s | busts it by 64× |

**Budget: the exact path must complete in < 0.5 s at the maximum permitted player count.**
Chosen because `quorum.py:114` runs **synchronously and unguarded** on the destructive-op
consensus path — there is no timeout, no `try/except`, and no async yield, so this number is
wall-clock latency the Captain waits through before a destructive intent resolves.

> **`MAX_EXACT_SHAPLEY: 10 -> 8`.** Worst case 0.246 s, a 130× improvement on the reachable
> worst case at HEAD, and it makes the cliff unreachable from *any* ballot count: 11 ballots
> collapsing to 10 players now selects Monte Carlo, exactly as 11 ballots did before.

### Blast radius of lowering the constant — enumerated, not assumed

Only coalitions of **exactly 9 or 10 players** change behaviour (exact → Monte Carlo /
`_all_approved_shapley`).

```
CLAIM: no test constructs a 9- or 10-player Shapley coalition.
RUN:   scanned every tests/*.py containing "Vote(" or "shapley" for range(9|10),
       _make_votes(9|10), and per-test-function literal Vote( counts of 9 or 10.
FOUND: test_ad1126_verified_finalization.py:4096  range(9)  -> 9 ROUNDS inside ONE child,
                                                    not 9 players; asserts a ValidationError
       test_anchor_indexed_recall.py:442          range(10) -> 10 episodes, no Shapley
HOLDS: yes. Coalition sizes actually exercised are 2, 3, 7, 11, 12, 15, 20.
       2/3/7 stay exact; 11/12/15/20 stay approximate. Nothing crosses the new bound.
```

`crew_trust.py:267` (`if len(votes) <= MAX_EXACT_SHAPLEY`) inherits the new value with **no
code change**. Its keys are distinct by construction — it raises `crew_trust_evidence_invalid`
on duplicate `work_item_id`s — so there `len(votes) == n players` and the pre-check remains
correct in the new units. A 9-child crew (9 children + 1 facilitator = 10 votes) moves from
exact to `_all_approved_shapley`, which is deterministic and bounded and was built by AD-1130
for precisely the large-crew case. **That also removes a live 31.9 s stall from the crew trust
path.** Declare it in the commit; do not describe it as "no change".

---

## 5. Consumers — every one, including private names and tests

Revision 1's inventory listed production call sites and missed both the spend path's
*multiplicity* and a mandatory test amendment. This is the complete set.

### 5.1 Production

| Consumer | Line | Reads | What changes | Code change? |
|---|---|---|---|---|
| `consensus/quorum.py` | `:114` | calls, **unguarded, synchronous** | Values move only for duplicate-key mixed-verdict rounds. Latency for 9-10 voters: **34.7 s → ~0.01 s**. | **No** |
| `runtime.py` — HXI event | `:3990` | `consensus.shapley_values` → `EventType.CONSENSUS` payload | Same keys, `dict[str, float]`. | **No** |
| `runtime.py` — **trust spend** | `:4025-4026`, loop at `:4092-4095` | `.get(result.agent_id, 0.0)`, floored at `0.1` | **See 5.3 — this is the one revision 1 missed.** | **No** |
| `runtime.py` — introspection | `:3995` | `_last_shapley_values` | Unchanged. | **No** |
| `cognitive/crew_synth.py` | `:513` `_attribute` | calls | Every ballot it builds is approving (`:163`, `:499`), so **values are unchanged**; what is recovered is the discarded `confidence`/`reason`. | **Docstring only** (§6.4) |
| `cognitive/crew_trust.py` | `:267-274` | `len(votes) <= MAX_EXACT_SHAPLEY` pre-check | Inherits the lowered bound; 9-10-vote crews move to `_all_approved_shapley`. | **No** |
| `cognitive/self_improvement/qa_pool.py` | `:59` | injected, `try/except`-guarded | Pool default is 3. Unreached. | **No** |
| `cognitive/episodic.py` | `:3436` | `json.dumps(ep.shapley_values)` | **Constrains the return shape.** Test 18 pins it. | **No** |
| `experience/panels.py` | `:267` | `.get(agent.id)` | Bare-id lookup preserved. | **No** |
| `types.py` | `:251`, `:629` | `ConsensusResult` / `Episode` fields | `dict[str, float]` unchanged. | **No** |
| `ui/src/store/types.ts` | `:349` | `Record<string, number>` | Unchanged. | **No** |

### 5.2 Tests — including the private names a public-name grep cannot see

| Test file | Reaches | Change |
|---|---|---|
| **`tests/test_performance_p0.py:176-190`** | **`_exact_shapley` / `_approximate_shapley` DIRECTLY** | **MUST BE AMENDED — mandatory, not optional.** It builds `vote_by_id = {v.agent_id: v}` and passes it positionally. The signature becomes `dict[str, list[Vote]]`. Amend to `{v.agent_id: [v] for v in votes}`; assertions unchanged. |
| `tests/test_performance_p0.py:135-168` | public, 3 / 15 / 20 voters | None. |
| `tests/test_shapley.py` (24 call sites) | public, distinct ids, ≤7 voters | None. Parity across 42 distinct-id configurations was measured for revision 1 and re-holds. |
| `tests/test_ad1130_outcome_only_room_trust.py:884, 977-980` | monkeypatches `crew_trust.compute_shapley_values`; 2, 11, 12 votes | None — 2 stays exact, 11/12 stay `_all_approved_shapley`. |
| `tests/test_bf783_verifier_not_paid_for_accepting.py:157` | trust *records*, not values | None. Its docstring says the two votes "merge" — false at HEAD, **true after this AD**. |
| `tests/test_ad861_crew_synth.py`, `tests/test_ad860_crew_verifier.py` | crew path, all-approving | None. |
| `tests/test_layer_boundaries.py:104` | import-graph assertion | None. |

> **Revision 1's acceptance criterion #2 said "0 existing tests amended … if any needs
> amending, stop." That was false** — its own patch amended `test_performance_p0.py`. A
> builder obeying the criterion would have hard-stopped; a builder obeying the patch would
> have violated the criterion. Revision 2 states the amendment as **required**, names the
> exact edit, and requires the explanatory comment to say *why a grep for the public name
> did not find this call site*.

### 5.3 The spend path, stated exactly — how many times, by whom, keyed by what

```
WHO:      runtime.py::_process_with_consensus -> _verify_one
HOW MANY: len([r for r in results if r.success]) x len(self.red_team_agents)
KEYED BY: result.agent_id           (an AGENT id from the result list)
VALUE:    max(consensus.shapley_values.get(result.agent_id, 0.0), 0.1)
```

Three consequences the builder must hold simultaneously:

1. **The write count is owned by the result list, not by the player set.** Nothing in
   `shapley.py` can change it. This is why D1 keeps the key set identical: any model that
   changed the keys would change *which* value each of those pre-existing writes picks up.
2. **Total spent ≠ total available at HEAD** (measured 2.00 vs 1.00). This AD does not fix
   that and must not claim to. **BF-851.**
3. **Post-fix spend is byte-identical to HEAD in every all-approving case**, and differs only
   where the Shapley value itself legitimately moves (mixed-verdict duplicate rounds).
   That is the property to test — see §7.2.

---

## 6. Implementation

All in `src/probos/consensus/shapley.py` except §6.4.

### 6.1 Imports and the bound

```
===SEARCH===
import itertools
import random
from typing import TYPE_CHECKING
===REPLACE===
import itertools
import logging
import random
from typing import TYPE_CHECKING
===END REPLACE===
```

```
===SEARCH===
MAX_EXACT_SHAPLEY = 10
===REPLACE===
logger = logging.getLogger(__name__)

# AD-1263/BF-850: bounds the POST-SPLIT PLAYER count, never the ballot count.
# Exact enumeration is n! permutations x n coalition evaluations; measured
# 8 -> 0.246s, 9 -> 2.08s, 10 -> 31.9s. quorum.py:114 runs this synchronously
# and unguarded on the destructive-op path, so the budget is < 0.5s wall clock.
MAX_EXACT_SHAPLEY = 8
===END REPLACE===
```

### 6.2 `compute_shapley_values` — player map, derived `n`, honest docstring

```
===SEARCH===
    Returns {agent_id: shapley_value} normalized to [0, 1].
    """
    if not votes:
        return {}

    n = len(votes)
    if n == 1:
        return {votes[0].agent_id: 1.0}

    # Map agent_id -> Vote for quick lookup
    vote_by_id: dict[str, Vote] = {v.agent_id: v for v in votes}
    agent_ids = list(vote_by_id.keys())

    if n <= MAX_EXACT_SHAPLEY:
        raw_values = _exact_shapley(agent_ids, vote_by_id, approval_threshold, use_confidence_weights)
    else:
        raw_values = _approximate_shapley(agent_ids, vote_by_id, approval_threshold, use_confidence_weights)
===REPLACE===
    ``Vote.agent_id`` is an opaque PARTICIPANT KEY, not necessarily an agent
    identity — ``crew_trust`` passes ``child:<work_item_id>`` and
    ``facilitator:<session_id>``. A key appearing more than once is ONE player
    who cast more than one ballot (AD-1263): that player contributes ALL of
    their ballots to any coalition they join, so both sides of the approval
    ratio see every ballot and no ``confidence`` is discarded. Before AD-1263
    the map was ``{v.agent_id: v}`` and the last ballot silently replaced the
    others.

    Attribution here is PER PARTICIPANT KEY. It is not per role, and it is not
    a count of trust writes: ``runtime`` spends this value once per successful
    ``IntentResult``, so a key appearing in two results is written twice from
    one entry. That multiplicity belongs to the result list, not to this
    function (BF-851).

    Returns ``{participant_key: value}`` where every value is in ``[0.0, 1.0]``
    and the values sum to at most 1.0. They sum to exactly 1.0 when no player
    has a negative raw marginal — which includes the degenerate case where no
    player has any marginal effect and the mass is split equally. They sum to
    less than 1.0 exactly when some player's presence broke otherwise-passing
    coalitions: ``max(0.0, v)`` clamps their share to zero while ``abs(v)``
    keeps its magnitude in the denominator, and the shortfall is that clamped
    mass. That asymmetry is deliberate and unchanged by AD-1263; altering it
    would move every rejected-outcome trust weight in ``runtime``.
    """
    if not votes:
        return {}

    # Participant key -> every ballot that key cast, in submission order.
    votes_by_id: dict[str, list[Vote]] = {}
    for v in votes:
        votes_by_id.setdefault(v.agent_id, []).append(v)
    agent_ids = list(votes_by_id.keys())

    if len(agent_ids) != len(votes):
        logger.debug(
            "AD-1263: %d ballots from %d participants; multi-ballot keys: %s",
            len(votes),
            len(agent_ids),
            {k: len(vs) for k, vs in votes_by_id.items() if len(vs) > 1},
        )

    # n is the PLAYER count, never the ballot count. It selects the enumeration
    # strategy and denominates the equal-split fallback, and both are per-player.
    # MAX_EXACT_SHAPLEY is calibrated against THIS quantity (BF-850).
    n = len(agent_ids)
    if n == 1:
        return {agent_ids[0]: 1.0}

    if n <= MAX_EXACT_SHAPLEY:
        raw_values = _exact_shapley(agent_ids, votes_by_id, approval_threshold, use_confidence_weights)
    else:
        raw_values = _approximate_shapley(agent_ids, votes_by_id, approval_threshold, use_confidence_weights)
===END REPLACE===
```

Also update the stale line in the same docstring:

```
===SEARCH===
    For coalitions larger than MAX_EXACT_SHAPLEY, switches to Monte Carlo
    approximation to avoid factorial explosion.
===REPLACE===
    For coalitions of more than MAX_EXACT_SHAPLEY PLAYERS (not ballots),
    switches to Monte Carlo approximation to avoid factorial explosion.
===END REPLACE===
```

### 6.3 `_exact_shapley` and `_approximate_shapley` take ballots per player

Four edits, two per function — identical in shape.

```
===SEARCH===
def _exact_shapley(
    agent_ids: list[str],
    vote_by_id: dict[str, Vote],
===REPLACE===
def _exact_shapley(
    agent_ids: list[str],
    votes_by_id: dict[str, list[Vote]],
===END REPLACE===
```

```
===SEARCH===
            coalition.append(vote_by_id[aid])
            v_with = _evaluate_coalition(
                coalition, approval_threshold, use_confidence_weights,
            )
            marginal_sums[aid] += float(v_with) - float(v_without)

    return {aid: marginal_sums[aid] / num_perms for aid in agent_ids}
===REPLACE===
            coalition.extend(votes_by_id[aid])
            v_with = _evaluate_coalition(
                coalition, approval_threshold, use_confidence_weights,
            )
            marginal_sums[aid] += float(v_with) - float(v_without)

    return {aid: marginal_sums[aid] / num_perms for aid in agent_ids}
===END REPLACE===
```

```
===SEARCH===
def _approximate_shapley(
    agent_ids: list[str],
    vote_by_id: dict[str, Vote],
===REPLACE===
def _approximate_shapley(
    agent_ids: list[str],
    votes_by_id: dict[str, list[Vote]],
===END REPLACE===
```

```
===SEARCH===
            coalition.append(vote_by_id[aid])
            v_with = _evaluate_coalition(
                coalition, approval_threshold, use_confidence_weights,
            )
            marginal_sums[aid] += float(v_with) - float(v_without)

    return {aid: marginal_sums[aid] / samples for aid in agent_ids}
===REPLACE===
            coalition.extend(votes_by_id[aid])
            v_with = _evaluate_coalition(
                coalition, approval_threshold, use_confidence_weights,
            )
            marginal_sums[aid] += float(v_with) - float(v_without)

    return {aid: marginal_sums[aid] / samples for aid in agent_ids}
===END REPLACE===
```

**Do not change `_evaluate_coalition`.** It already takes a flat `list[Vote]` and sums
weights across it — that *is* the multi-ballot semantics.

### 6.4 Retire the docstring that asserts the defect as the contract

`src/probos/cognitive/crew_synth.py`, `_build_votes` (`:484`):

```
===SEARCH===
        Skips the honest-degrade ``unverified`` case (empty ``verifier_agent_id``
        — producer Vote only). Shapley keys by ``agent_id``: an agent that is both
        a producer and a verifier in the same set yields two Votes, and
        ``compute_shapley_values`` builds ``{v.agent_id: v}`` — so the LAST one
        wins outright rather than being combined. Filed separately; it does not
        reach trust today because ``_record_trust`` writes a flat success rather
        than a Shapley-weighted one."""
===REPLACE===
        Skips the honest-degrade ``unverified`` case (empty ``verifier_agent_id``
        — producer Vote only). An agent that is both a producer and a verifier in
        the same set yields two Votes under one key; since AD-1263 that is one
        player casting two ballots and both are weighed, where previously the last
        silently replaced the first. Every Vote built here is approving (this
        method only sees accepted outcomes), so the attributed values are an equal
        split across distinct keys either way — what AD-1263 recovered here is the
        discarded ``confidence`` and ``reason``, not a different number. The folded
        value mixes both roles, so it must not become a producer-only trust weight
        without re-deriving per role: ``_record_trust`` writes a flat success
        rather than a Shapley-weighted one, which is what keeps BF-783 closed."""
===END REPLACE===
```

### 6.5 The mandatory test amendment

`tests/test_performance_p0.py`, `test_approximate_values_reasonable` (`:176-190`):

```
===SEARCH===
        vote_by_id = {v.agent_id: v for v in votes}
        agent_ids = list(vote_by_id.keys())

        exact = _exact_shapley(agent_ids, vote_by_id, 0.5, True)
        approx = _approximate_shapley(agent_ids, vote_by_id, 0.5, True, samples=5000)
===REPLACE===
        # This test reaches the PRIVATE helpers directly, which is why a grep for
        # the public compute_shapley_values name does not surface it. AD-1263
        # changed their input to dict[str, list[Vote]] so one participant key can
        # carry several ballots; the convergence assertions below are unchanged.
        votes_by_id = {v.agent_id: [v] for v in votes}
        agent_ids = list(votes_by_id.keys())

        exact = _exact_shapley(agent_ids, votes_by_id, 0.5, True)
        approx = _approximate_shapley(agent_ids, votes_by_id, 0.5, True, samples=5000)
===END REPLACE===
```

---

## 7. Tests

One new file: `tests/test_ad1263_one_player_per_participant_key.py`. Every test drives the
**real** `compute_shapley_values` — no reimplementation of the mapping, no mirror of the fix.
`Vote` is from `probos.types`; the field is `approved`, not `approve`.

### 7.1 Groups A–D — the attribution model (12)

**A — the discarded ballot (4)**

1. `test_a_second_ballot_under_one_key_is_not_discarded` — `[A ok .9, A no .5, B no 1.0]`, thr 0.6, weighted → `{"A": 0.5, "B": 0.0}`. Pin the pre-fix `{"A": 1/3, "B": 1/3}` in the docstring so the regression is legible.
2. `test_both_ballots_reach_the_approval_ratio` — same input; assert `A > 0.0`, proving A's *approving* ballot carried a coalition the surviving rejecting ballot alone could not.
3. `test_disagreeing_ballots_need_no_tiebreak` — one key with `approve` and `reject` ballots returns a finite value in `[0, 1]` and does not raise.
4. `test_confidence_of_the_extra_ballot_changes_the_result` — two ballots under one key differing only in `confidence`; assert the result differs from the same input with the first ballot removed. Proves the ballot is *weighed*, not merely *counted*.

**B — the all-zero fallback (4)**

5. `test_all_zero_fallback_sums_to_one_with_duplicate_keys` — `[a no, a no, b no]` → `{"a": .5, "b": .5}`, `sum == approx(1.0)`. Pre-fix `0.6667`.
6. `test_all_zero_fallback_sums_to_one_with_two_ballots_each` — `[a, a, b, b]` all rejecting → `{"a": .5, "b": .5}`, `sum == 1.0`. Pre-fix `0.5000`.
7. `test_all_zero_fallback_unchanged_for_distinct_keys` — `[a, b, c]` rejecting → `1/3` each. Guards over-correction.
8. `test_single_player_with_two_ballots_takes_the_whole_mass` — `[A no .5, A no .5]` → `{"A": 1.0}`. Pre-fix `{"A": 0.5}`. Pins the `n == 1` reordering.

**C — the normalisation contract as stated (4)**

9. `test_every_value_is_within_zero_and_one` — over a small duplicate-bearing matrix.
10. `test_values_never_exceed_one_in_total` — `sum <= 1.0 + 1e-9`.
11. `test_sum_is_exactly_one_when_no_marginal_is_negative` — all-approving input containing a duplicate key.
12. `test_shortfall_equals_the_clamped_mass` — negative-marginal input; `sum < 1.0` **and** the clamped player's value is exactly `0.0`.

### 7.2 Group E — the spend path (3) — **replaces the Captain's conservation test**

> **Correction to the brief, with measurement.** The requested test — *"total attribution
> spent equals total available"* — **cannot pass, and must not be written.** At HEAD,
> `A x3 + B` spends **2.00 against 1.00 available**, because `runtime.py:4092-4095` writes
> once per *(successful result × red-team agent)*. This AD does not change that loop, so a
> literal conservation assertion would fail on HEAD *and* on the fix and would be pinning a
> property the system has never had. It is filed as **BF-851**.
>
> The correct property — and the one that would have caught revision 1's blocker A — is
> **spend neutrality**: the fix must not move what `runtime` spends, except where the
> Shapley value itself legitimately moves.

13. `test_attribution_is_conserved_within_the_function` — the property this AD *does* own: for a duplicate-bearing all-approving input, `sum(compute_shapley_values(...)) == approx(1.0)`, and for every input in the matrix `sum <= 1.0`. Attribution conservation is a property of the returned dict.
14. `test_spend_is_neutral_against_head_for_all_approving_rounds` — reimplement **only the spend loop** (`for r in results if r.success: for _ in red_team: total[r.agent_id] += max(sv.get(r.agent_id, 0.0), 0.1)`) as a local helper — never import the fix into it. Drive it with `[A ok, A ok, B ok]` and `[A ok, A ok, A ok, B ok]`. Assert the per-agent spend equals the literals measured at HEAD: `{A: 1.0, B: 0.5}` and `{A: 1.5, B: 0.5}`. **This is the executable form of §5.3.**
15. `test_the_only_spend_delta_is_the_recovered_ballot` — `[A ok .9, A no .5, B no 1.0]`; assert post-fix spend `{A: 0.5}` against the HEAD literal `{A: 0.3333}`, and that the delta is confined to `A`. Pins that the movement is intended and bounded.

### 7.3 Group F — the exact/approximate bound (3)

16. `test_the_bound_is_measured_in_players_not_ballots` — 11 ballots collapsing to 8 keys. Monkeypatch `probos.consensus.shapley._approximate_shapley` to raise; assert it is **not** called — the exact path was chosen on 8 players, not Monte Carlo on 11 ballots. Then 11 ballots collapsing to **9** keys: monkeypatch `_exact_shapley` to raise; assert it is **not** called. Both directions, or the guard is half-built.
17. `test_exact_path_holds_its_latency_budget` — **hard number.** `MAX_EXACT_SHAPLEY` distinct approving voters must complete in **< 0.5 s**:
    ```python
    votes = [Vote(agent_id=f"a{i}", approved=True, confidence=0.8, reason="") for i in range(MAX_EXACT_SHAPLEY)]
    t = time.perf_counter(); compute_shapley_values(votes, approval_threshold=0.6); elapsed = time.perf_counter() - t
    assert elapsed < 0.5, f"exact Shapley took {elapsed:.3f}s at n={MAX_EXACT_SHAPLEY} (budget 0.5s)"
    ```
    Import the constant — do not hardcode `8` — so raising it later reddens this test instead of silently reintroducing BF-850. Measured headroom at `n=8`: 0.246 s.
18. `test_a_ten_player_coalition_no_longer_stalls` — 10 distinct approving voters complete in **< 1.0 s** (HEAD: **34.65 s**). This is the BF-850 regression test and it fails on HEAD by ~35×.

### 7.4 Group G — no collateral movement (2)

19. `test_distinct_keys_are_unchanged` — parametrised over thresholds `(0.5, 0.6, 0.9)` × `use_confidence_weights` `(True, False)` × coalition sizes 1–7, all distinct ids, against literal expected dicts captured from HEAD. Sizes stop at 7 so the parametrisation stays inside the exact path on both sides of the change.
20. `test_empty_and_single_ballot_are_unchanged` — `[]` → `{}`; one ballot → `{id: 1.0}`.
21. `test_result_survives_the_episodic_json_round_trip` — `json.loads(json.dumps(result)) == result` on a duplicate-bearing result. Executable form of D1; fails instantly if anyone reintroduces a tuple key, and it is the seam `episodic.py:3436` actually uses.

*(21 named tests across 7 groups; "18 new" in the header counts the required minimum — groups may merge parametrised cases.)*

### Gate

```
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1263_one_player_per_participant_key.py \
  tests/test_shapley.py tests/test_performance_p0.py \
  tests/test_bf783_verifier_not_paid_for_accepting.py \
  tests/test_ad1130_outcome_only_room_trust.py \
  tests/test_ad861_crew_synth.py tests/test_ad860_crew_verifier.py \
  tests/test_ad1126_verified_finalization.py -q -n 0
```

then the full parallel gate: `pytest tests/ -q -n 4 --dist=loadfile`.

---

## 8. Stop rule — hand back, do not patch

> **If a review round lands a finding INSIDE machinery this AD introduces — the player map,
> the derived `n`, the lowered bound, or the spend-neutrality helper — STOP. Revert, preserve
> the patch, and hand back to the Architect. Do not open another round.**

This is round 2 already. The measured pattern in this repo (BF-840, BF-841, AD-1262) is that
three or more findings clustered at *one seam you invented* means an unanswered design
question, not a buggy implementation — and each additional patch adds surface at the same
seam. Revision 1 was reverted for exactly this reason: both blockers sat on the boundary
between "what the function computes" and "what the runtime spends", which revision 1 had not
named as a boundary at all.

**The stop rule also fires on these specific signals:**

| Signal | Meaning | Action |
|---|---|---|
| A consumer in §5.1 marked "No" needs a code change | D1's shape guarantee is wrong | Stop. Hand back. |
| A test in §5.2 marked "None" needs amending | The distinct-id parity claim is wrong | Stop. Hand back — do **not** amend the test. |
| Test 17 or 18 fails | The bound is still mis-calibrated for this machine | Stop. Report the measured curve; the Architect re-derives `MAX_EXACT_SHAPLEY`. Do **not** raise the budget. |
| Test 14 fails | The fix moved the spend — blocker A has recurred | Stop immediately. Hand back. |
| A `?raw` / source-scan test asserts a line being changed | It pins the defect as contract | Update it **and record why inline**; never delete it. |

---

## 9. What this does NOT change — do not build

- **Do not fix BF-851.** The `runtime` spend loop at `:4092-4095` writes once per
  *(successful result × red-team agent)*. It over-spends at HEAD (measured 2.00 vs 1.00).
  **Leave it exactly as it is.** Test 14 pins that this AD does not move it. Fixing it means
  deciding whether N results from one agent are N observations or one — a trust-semantics
  question with its own blast radius across `trust.py`, `TrustObservation.weight`, and every
  Beta parameter already written. Its own AD.
- **Do not add `role` (or any field) to `Vote`.** D1.
- **Do not change the return type or any key.** `dict[str, float]`, keyed by the participant
  key exactly as supplied.
- **Do not make the values always sum to 1.0.** Removing the `abs()`/`max()` asymmetry moves
  every rejected-outcome trust weight at `runtime.py:4026`. Separate AD.
- **Do not make `MAX_EXACT_SHAPLEY` configurable.** No config field, no YAML, no env var. It
  is a hardware-calibrated safety bound, not a preference; a config surface invites raising it
  back over the cliff. If it must move, it moves with a new measurement in a new AD.
- **Do not touch `crew_synth._build_votes`' behaviour.** Docstring only.
- **Do not touch `crew_trust.py`.** Its pre-check inherits the new bound correctly; its keys
  are distinct by construction.
- **Do not touch `qa_pool.py`.** Guarded, and unreached at pool size 3.
- **Do not add `try/except` around `quorum.py:114`.** The model cannot raise; a guard there
  would defend nothing and hide a future real error.
- **Do not fix BF-833 (#1298) or BF-834 (#1299).** Cited only to establish that duplicate
  `agent_id`s in `quorum` results are reachable.
- **Do not touch the HXI, `api.py`, `panels.py`, `runtime.py`, `episodic.py`, or `types.py`.**
  If a change here forces one of them, D1 was violated — stop and surface it.
- **No config, no schema, no new dependency, no feature flag.**

---

## 10. Tracking

- `PROGRESS.md` — AD-1263 entry on ship. Record honestly: crew-synthesis attribution values
  are **unchanged**; the live value impact is on the quorum path; the **latency** impact is
  34.65 s → ~0.01 s for 10-voter rounds.
- `docs/development/roadmap.md` Bug Tracker — BF-837 (#1303) → CLOSED; **BF-850** → CLOSED;
  **BF-851** → OPEN with the measured 2.00-vs-1.00 line.
- `DECISIONS.md` — one entry recording **D1** (participant key, not agent id; per-agent not
  per-role; shape frozen by `episodic.py:3436`, `ui/src/store/types.ts:349`, and the
  `runtime.py:4026` floor), **D2** (the bound is measured in post-split players, lowered
  10 → 8 against a < 0.5 s budget), and **D3** (attribution and the spending of attribution
  are different layers; the fold happens in `shapley.py`, the multiplicity stays in `runtime`).
- Issue #1303 — close on push, quoting the measurements and stating plainly that the crew
  case is unchanged.
- File **BF-850** and **BF-851** as GitHub issues before building, so the commit can
  reference them.

---

## 11. Acceptance criteria

1. All new tests pass, driving the real `compute_shapley_values`.
2. **Test 14 (`test_spend_is_neutral_against_head_for_all_approving_rounds`) passes**, proving
   the fix does not move what `runtime` spends. If it fails, blocker A has recurred — stop.
3. **Test 17 passes with `elapsed < 0.5 s`** at `n == MAX_EXACT_SHAPLEY`, importing the
   constant rather than hardcoding it.
4. **Test 18 passes with `elapsed < 1.0 s`** for 10 distinct voters (HEAD: 34.65 s).
5. `tests/test_shapley.py`, `tests/test_bf783_verifier_not_paid_for_accepting.py`,
   `tests/test_ad1130_outcome_only_room_trust.py`, `tests/test_ad861_crew_synth.py` and
   `tests/test_ad860_crew_verifier.py` pass **unamended**. If any needs amending, stop — the
   parity claim is wrong and the design must be re-reviewed, not the test.
6. `tests/test_performance_p0.py` passes **with exactly the §6.5 amendment and no other**.
7. The full parallel gate passes with no new failures and no new warnings on changed paths.
8. `grep -rn "vote_by_id" src/ tests/` returns nothing.
9. `grep -rn "LAST one wins" src/` returns nothing.
10. `grep -n "MAX_EXACT_SHAPLEY" src/probos/consensus/shapley.py` shows `= 8` with the
    measured-budget comment intact.
11. `compute_shapley_values` still returns `dict[str, float]`; `Vote` has exactly its five
    existing fields.
12. Public functions carry full type annotations; the `debug` log names both counts and the
    offending keys.
13. Run the `Diff Reviewer` subagent on the staged diff with a different model before commit,
    telling it the spend path is the seam that broke revision 1. **Apply the stop rule to its
    findings** — a finding inside this AD's machinery means hand back, not patch.
14. **Verify all changes comply with the Engineering Principles in
    `.github/copilot-instructions.md`.**

---

## 12. Verified Against Codebase (2026-08-24)

Executed, not read. Every absence claim shows the enumeration that proves it.

### Latency — the exact-Shapley curve, real `_exact_shapley`

```
players | permutations | exact elapsed
   2    |            2 |    0.0000s
   3    |            6 |    0.0000s
   4    |           24 |    0.0001s
   5    |          120 |    0.0004s
   6    |          720 |    0.0034s
   7    |        5,040 |    0.0261s
   8    |       40,320 |    0.2456s   <- new bound, 0.246s
   9    |      362,880 |    2.0807s
  10    |    3,628,800 |   31.8825s
```

### The cliff is live at HEAD — BF-850

```
HEAD,  9 DISTINCT agents (n=9,  exact)        :  2.0751 s
HEAD, 10 DISTINCT agents (n=10, exact)        : 34.6517 s   <-- no fix needed to reach this
HEAD, 11 DISTINCT agents (n=11, monte carlo)  :  0.0127 s
HEAD, 11 ballots / 10 players (n=11 -> MC)    :  0.0081 s
FIX,  11 ballots / 10 players (n=10 -> EXACT) :  10! = 3,628,800 perms   <-- revision 1's cliff
git log -S "MAX_EXACT_SHAPLEY = 10" -- src/probos/consensus/shapley.py
  e33431f4 Optimize P0 performance bottlenecks: intent bus, Shapley, registry (AD-289)
```

### The spend path — BF-851, and blocker A re-attributed

```
src/probos/runtime.py:4092-4095
  verify_tasks = [ _verify_one(rt_agent, result)
                   for result in results if result.success
                   for rt_agent in self.red_team_agents ]
src/probos/runtime.py:4025-4026
  shapley_weight = max(consensus.shapley_values.get(result.agent_id, 0.0), 0.1)

scenario                        HEAD shapley (sum)   HEAD spent (total)   FIX spent (total)
dual-role A approves twice      {A:.5,B:.5}   1.0000 {A:1.0,B:.5}  1.5000 identical   1.5000
A x3 + B                        {A:.5,B:.5}   1.0000 {A:1.5,B:.5}  2.0000 identical   2.0000
3 distinct all approve          {each .3333}  1.0000 {each .3333}  1.0000 identical   1.0000
dual-role A, split verdicts     {A:.33,B:.33} 0.6667 {A:.3333}     0.3333 {A:.5}      0.5000
```

CLAIM: the doubling pre-exists at HEAD and revision 1 did not cause it.
HOLDS: yes — `A x3 + B` spends 2.00 against 1.00 available **at HEAD**, and the fix leaves
every all-approving spend byte-identical. The only delta is `+0.1667` on `A` in the
mixed-verdict case, which is the recovered ballot.

### Threshold blast radius

```
CLAIM: no test constructs a 9- or 10-player Shapley coalition, so lowering 10 -> 8
       changes no test's expected values.
RUN:   scanned every tests/*.py containing "Vote(" or "shapley" for range(9|10),
       _make_votes(9|10), and per-test-function literal Vote( counts of 9 or 10.
FOUND: test_ad1126_verified_finalization.py:4096  range(9)  -> 9 ROUNDS in ONE child
                                                    (asserts ValidationError), not players
       test_anchor_indexed_recall.py:442          range(10) -> 10 episodes, no Shapley
HOLDS: yes. Sizes actually exercised: 2, 3, 7, 11, 12, 15, 20.
       2/3/7 stay exact; 11/12/15/20 stay approximate. Nothing crosses the new bound.
       test_ad1130:970 test_small_vote_set_delegates_to_live_exact_shapley asserts calls == [2].
       test_ad1130:859/928/947 use 11-12 votes -> _all_approved_shapley, above 10 AND 8.
```

### Consumers — public and private names

```
rg -n 'compute_shapley_values|_exact_shapley|_approximate_shapley' src/
  consensus/quorum.py:15,114                    -> unguarded, synchronous
  consensus/shapley.py:12,37,50,66,67,69,82,108
  cognitive/crew_synth.py:26,50,491,513
  cognitive/crew_trust.py:15,267,268
  cognitive/crew_verifier.py:24,1323            -> docstrings only, does NOT call
rg -n 'compute_shapley_values|_exact_shapley|_approximate_shapley' tests/
  test_performance_p0.py:176,177,189,190        -> PRIVATE NAMES, positional dict[str, Vote]
  test_performance_p0.py:135-168                -> public, 3/15/20 voters
  test_shapley.py                               -> public, 24 call sites, distinct ids, <=7
  test_ad1130_outcome_only_room_trust.py:28,884,977,980
  test_layer_boundaries.py:104                  -> import-graph assertion only
rg -n 'shapley_values' src/ | grep -v consensus/shapley.py
  runtime.py:3990 (HXI payload) · runtime.py:4026 (trust weight) · runtime.py:490 (_last_)
  episodic.py:1041,3436 (json.dumps) · panels.py:228,267 · types.py:251,629
  memory_security.py:390 · dream_adapter.py:117 · events.py:741
ui/src/store/types.ts:349  shapley: Record<string, number>;
```

CLAIM: `test_performance_p0.py` is the ONLY test reaching the private helpers, and it MUST
be amended.
HOLDS: yes — `rg '_exact_shapley|_approximate_shapley' tests/` returns hits in that file
only (`:176,:177,:189,:190`). It passes `dict[str, Vote]` positionally; the signature becomes
`dict[str, list[Vote]]`. Revision 1's patch amended it while revision 1's acceptance
criterion #2 forbade amending any existing test — a direct contradiction, now resolved.

### D1 shape constraints

```
tuple key JSON: TypeError -> keys must be str, int, float, bool or None, not tuple
episodic.py:3436   json.dumps(ep.shapley_values)
panels.py:267      shapley_values.get(agent.id)
runtime.py:4026    max(consensus.shapley_values.get(result.agent_id, 0.0), 0.1)  <- floors to 0.1 under per-role keys
crew_trust.py:252  vote_keys = [f"child:{child.work_item_id}" for child in children]
crew_trust.py:253  facilitator_vote_key = f"facilitator:{session_id}"
```

### Revision-1 artefacts reused

```
.git/AD1263_ATTEMPT.patch  23,033 bytes  -- shapley.py hunks reused verbatim in 6.2/6.3;
                                            crew_synth docstring reused in 6.4;
                                            test_performance_p0 amendment reused in 6.5
.git/AD1263_tests.py       14,753 bytes  -- Groups A-D and G reusable; Groups E and F are NEW
```
