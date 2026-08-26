# AD-1263 — a participant who votes twice is one player, not the last ballot

> ## SUPERSEDED — DO NOT BUILD
>
> **This is revision 1. It was BUILT and REVERTED.** Build
> `prompts/ad-1263-one-player-per-participant-key.md` instead.
>
> Two measured blockers, both on the boundary between *what the function computes* and
> *what the runtime spends* — a boundary this revision never names:
>
> 1. **The bound was left in the old units.** D3 correctly makes `n` the player count, but
>    `MAX_EXACT_SHAPLEY = 10` stays calibrated for the ballot count. 11 ballots collapsing
>    to 10 players flips from Monte Carlo (0.0081 s) to exact (10! = 3,628,800 perms).
>    Measured 10-player exact: **31.9 s**. Test 14 below *asserts this cliff as desired
>    behaviour*.
> 2. **The trust spend path is absent.** `runtime.py:4092-4095` writes once per
>    *(successful result × red-team agent)*, keyed `.get(result.agent_id)`. The consumer
>    table never mentions the multiplicity. (Re-measured: the over-spend pre-exists at HEAD
>    and this change does not move it — now filed as BF-851 — but the spec had no basis for
>    saying so either way.)
>
> Also incorrect here: the header claims **0 existing tests amended** and acceptance
> criterion #2 says to stop if any needs amending — yet `test_performance_p0.py:189-190`
> reaches the **private** `_exact_shapley`/`_approximate_shapley` and *must* be amended.
> Revision 1's own patch amended it, contradicting its own criterion.
>
> Retained for the reasoning in D1/D2/D4 and the rejected-alternatives table, which
> revision 2 reuses.

**Status:** SUPERSEDED by `prompts/ad-1263-one-player-per-participant-key.md`
**Closes:** BF-837 (#1303)
**Dependencies:** AD-223/AD-224 (`compute_shapley_values`), AD-861 (`crew_synth` attribution), AD-1130 (`crew_trust` composite participant keys — the in-repo precedent this follows)
**Estimated tests:** 16 new in one new file; **0 existing tests amended** (distinct-id parity proven across 42 configurations, below)

---

## Numbering

| Authority | AD ceiling | BF ceiling |
|---|---|---|
| Ledger (`docs/development/open-ads-report.md`) | "next free **AD-1251**" — **STALE** | "next free **BF-837**" — **STALE** |
| GitHub, all states (authoritative) | **AD-1261** filed (#1311) | **BF-844** filed (#1314) |
| Untracked in-flight prompts | `prompts/ad-12{50..62}-*.md` | max `bf-833-*` |

The ledger's issue layer cannot see untracked prompts and its snapshot predates
#1302–#1314. `prompts/ad-1262-the-backup-that-never-ran.md:24` records "next free
AD after this one: **AD-1263**".

- **This work is AD-1263.** Next free AD after this one: **AD-1264**.
- **No new BF is minted.** This builds against the already-filed BF-837 (#1303).

### Why an AD and not just the BF

#1303 as filed is "stop overwriting a dict key". Verification below shows that the
key is not an agent identity — `crew_trust.py:252–267` already writes
`child:<work_item_id>` and `facilitator:<session_id>` into that same field — and
that the return value is JSON-serialised (`episodic.py:3436`) and typed in the HXI
store (`ui/src/store/types.ts:349`). So the re-key the issue proposes is not
available, the docstring's normalisation promise is measurably false on a second
path the issue does not mention, and the correct model has to be *chosen* rather
than restored. That is design. BF-837 closes as a consequence.

---

## Problem

`src/probos/consensus/shapley.py:63` builds

```python
vote_by_id: dict[str, Vote] = {v.agent_id: v for v in votes}
agent_ids = list(vote_by_id.keys())
```

so a second `Vote` carrying an `agent_id` already present **silently replaces the
first**. Three consequences, all measured by executing the real function.

### 1. A ballot is discarded outright

```
Vote fields: ['agent_id', 'approved', 'confidence', 'reason', 'timestamp']
D1 votes_in=3 agents_out=2 -> {'both': 0.5, 'solo': 0.5} sum=1.0000
```

`crew_synth._build_votes` (`crew_synth.py:484–505`) produces exactly this input: one
producer `Vote` per accepted outcome plus one verifier `Vote` per outcome with a
`verifier_agent_id`. An agent that both produced and verified in the same accepted
set contributes two ballots; only the last survives, taking its `confidence` and
its `reason` (which names the sub-task) with it.

### 2. `n` is taken from the ballot list but spent on the player set

`n = len(votes)` (`:58`) while `agent_ids` comes from the deduplicated map (`:64`).
`n` is then spent three ways — the `n == 1` early return (`:59`), the exact-vs-Monte-Carlo
selection `n <= MAX_EXACT_SHAPLEY` (`:66`), and the all-zero fallback
`{aid: 1.0 / n for aid in agent_ids}` (`:77`). The last one loses attribution mass:

```
D3 3 distinct reject     votes=3 agents=3 sum=1.0000
D3 3 votes / 2 agents    votes=3 agents=2 sum=0.6667   (short by 0.3333)
D3 4 votes / 2 agents    votes=4 agents=2 sum=0.5000   (short by 0.5000)
```

The docstring (`:53`) promises "normalized to [0, 1]". The unanimous-approval path
still sums to 1.0, which is why this stayed invisible. The exact-vs-MC selection has
the same root cause in the conservative direction: 11 ballots from 8 players
enumerates 8 players by Monte Carlo when exact was affordable.

### 3. The docstring on the producing caller asserts the defect as the contract

`crew_synth.py:488–494` currently reads:

> `compute_shapley_values` builds `{v.agent_id: v}` — so the LAST one wins outright
> rather than being combined. Filed separately; it does not reach trust today …

That becomes false when this ships and must move with the code.

### Where this is live today — and where it is not

**Not in the crew path's published values.** `_build_votes` iterates
`accepted = [oc for oc in outcomes if oc.verdict.accepted]` (`crew_synth.py:163`), sets
`approved=oc.verdict.accepted` (`:499`), and `SubtaskVerifier.verdict_to_vote`
(`crew_verifier.py:1325–1330`) sets `approved=verdict.accepted`. **Every ballot
crew_synth builds is therefore approving**, every non-empty coalition clears the
threshold, and the result is an equal split across distinct keys regardless of
confidence. Measured — the dual-role case is unchanged by this fix:

```
H4 crew_synth dual-role, all approve (thr .6)
   OLD {'both': 0.5, 'solo': 0.5} sum=1.0000
   NEW {'both': 0.5, 'solo': 0.5} sum=1.0000
```

State this plainly and do not claim otherwise in the commit: for crew synthesis
this AD corrects the *model* and the discarded `confidence`/`reason`, not the
numbers the Captain currently sees.

**Live in quorum.** `quorum.py:76–86` builds one `Vote` per `IntentResult` with
`agent_id=r.agent_id` and no dedup, and `quorum.py:114` calls
`compute_shapley_values` with **no `try/except`** on the destructive-op consensus
path. Duplicate `agent_id`s in `results` are reachable — that is the shape of
BF-833 (#1298, a straggler appending its result into a later broadcast that reused
the intent ID) and BF-834 (#1299). There the ballots genuinely mix approve and
reject, so both the discarded ballot and the short normalisation bite:

```
H1 dual-role decisive producer ballot (thr .6)
   OLD {'A': 0.3333, 'B': 0.3333} sum=0.6667
   NEW {'A': 0.5,    'B': 0.0}    sum=0.5000
```

`runtime.py:4024–4027` then spends that value as a trust weight
(`max(consensus.shapley_values.get(result.agent_id, 0.0), 0.1)`), so a
short-normalised value is a systematically **under-weighted** trust write today.

**Not a trust defect in crew_synth yet.** `_record_trust` (`crew_synth.py:519–571`)
writes a flat `success=True` with no `weight=`, so today the collapse distorts
attribution and provenance reporting (AD-861's purpose), not the ledger. It becomes
a trust defect the moment anyone makes that write Shapley-weighted. Preserve the
BF-783 note that says so.

---

## Solution

**A participant key that appears more than once is one player who cast more than
one ballot, and that player contributes all of their ballots to any coalition they
join.** `_evaluate_coalition` already sums weights over a flat `list[Vote]`, so the
model needs only the map to become `dict[str, list[Vote]]` and the coalition builder
to `extend` instead of `append`.

This is lossless, total (it cannot raise), leaves the return type and every key
unchanged, and makes defect 2 unreachable because `n` is then genuinely the player
count.

### Decisions and rationale

**D1 — Do NOT add `role` to `Vote`; do NOT change the return shape.**
`Vote.agent_id` is already an opaque **participant key** in production, not an agent
identity: `crew_trust.py:252–267` writes `f"child:{child.work_item_id}"` and
`f"facilitator:{session_id}"` into it. A `role` field cannot express those, so it
would serve exactly one caller. The `(agent_id, role)` tuple key the issue proposes
is unavailable for a harder reason — measured:

```
tuple key JSON: TypeError -> keys must be str, int, float, bool or None, not tuple
```

and `episodic.py:3436` does `json.dumps(ep.shapley_values)` on this exact value.
Three consumers additionally look up by bare agent id: `panels.py:267`
(`shapley_values.get(agent.id)`), `runtime.py:4026`, and `crew_synth._record_trust`
(`for agent_id in shapley`). `ConsensusResult.shapley_values` (`types.py:251`) reaches
the HXI through `runtime.py:3990` and is typed `Record<string, number>` at
`ui/src/store/types.ts:349`. **The shape stays `dict[str, float]`.**

**D2 — Do NOT reject or raise on a duplicate key.** `quorum.py:114` is unguarded on
the live consensus path for destructive intents; a raise there fails a consensus
round rather than an attribution. (`qa_pool.py:108–121` *is* guarded and would
degrade safely, but quorum is the binding constraint.) Nor is a duplicate always an
error: `crew_synth` produces them legitimately. Log at `debug` with the key and
ballot count — `debug` rather than `warning` precisely because the legitimate case
is a normal crew path and a warning there would be noise.

**D3 — Derive `n` from the player set.** Move the map construction above the `n == 1`
early return and set `n = len(agent_ids)`. This fixes the fallback, aligns the
exact-vs-MC selection with what is actually enumerated, and makes a single player
casting several ballots return `{A: 1.0}` rather than `{A: 1/len(votes)}`.

**D4 — State the normalisation contract honestly; do not change the arithmetic.**
The normaliser clamps the numerator with `max(0.0, v)` while keeping the full
magnitude in the denominator via `sum(abs(v))`, so a player whose presence broke
passing coalitions surrenders mass that is given to nobody. The true contract:

- every value is in `[0.0, 1.0]`;
- the values always sum to **≤ 1.0**;
- they sum to **exactly 1.0** when no player's raw marginal is negative — which
  includes the degenerate all-zero equal-split case;
- they sum to **< 1.0** exactly when some player's raw marginal is negative, and the
  shortfall is precisely that clamped mass.

Write that down. **Do not "fix" the asymmetry** — making it always sum to 1.0 changes
every rejected-outcome trust weight at `runtime.py:4026`. That is a separate decision
with its own blast radius, and it is out of scope here (see *Do not build*).

### Rejected alternatives

| Alternative | Why not |
|---|---|
| Key by `(agent_id, role)` (as #1303 proposes) | Not JSON-serialisable — `episodic.py:3436` raises `TypeError` (measured). Breaks three bare-id lookups and the HXI `Record<string, number>` type. |
| Add `role: str` to `Vote` | A type change at every construction site to serve one caller, and it cannot express `crew_trust`'s work-item keys, which are the existing precedent. |
| Raise `ValueError` on a duplicate | `quorum.py:114` is unguarded on the destructive-op consensus path; this converts an attribution defect into a failed consensus round. |
| Merge duplicates into one `Vote` (sum/average confidence) | Requires inventing a tiebreak for disagreeing `approved` values and discards `reason`. The multi-ballot model needs no tiebreak: each ballot is weighed on its own side of the ratio. |
| Deterministically disambiguate keys inside the function (`a`, `a#1`) | Returns keys no caller can look up; silently breaks `panels.py:267` and `runtime.py:4026`. |
| Change `crew_synth._build_votes` to emit composite keys | Would then need folding back to agent ids before `_record_trust`, `_store_episode`, the `CREW_TASK_COMPLETED` payload and `SynthesisResult.shapley_values` — four seams changed to fix a defect that belongs one level down. The multi-ballot model needs **zero** changes in `crew_synth`. |

---

## Implementation

Everything below is in `src/probos/consensus/shapley.py` except Section 4.

### Section 1 — `compute_shapley_values`: player map, derived `n`, honest docstring

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
    ``facilitator:<session_id>``. A key appearing more than once is one player
    who cast more than one ballot (AD-1263): that player contributes ALL of
    their ballots to any coalition they join, so both sides of the approval
    ratio see every ballot and no ``confidence`` is discarded. Before AD-1263
    the map was ``{v.agent_id: v}`` and the last ballot silently replaced the
    others.

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

    # n is the PLAYER count, never the ballot count: it selects the enumeration
    # strategy and denominates the equal-split fallback, and both are per-player.
    n = len(agent_ids)
    if n == 1:
        return {agent_ids[0]: 1.0}

    if n <= MAX_EXACT_SHAPLEY:
        raw_values = _exact_shapley(agent_ids, votes_by_id, approval_threshold, use_confidence_weights)
    else:
        raw_values = _approximate_shapley(agent_ids, votes_by_id, approval_threshold, use_confidence_weights)
===END REPLACE===
```

`logger` does not currently exist in this module. Add it with the imports, following
the convention used by `src/probos/consensus/quorum.py`:

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

and, immediately above `MAX_EXACT_SHAPLEY = 10`:

```
===SEARCH===
MAX_EXACT_SHAPLEY = 10
===REPLACE===
logger = logging.getLogger(__name__)

MAX_EXACT_SHAPLEY = 10
===END REPLACE===
```

### Section 2 — `_exact_shapley` takes ballots per player

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

### Section 3 — `_approximate_shapley` takes ballots per player

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

Do not change `_evaluate_coalition`. It already takes a flat `list[Vote]` and sums
weights across it, which is exactly the multi-ballot semantics.

### Section 4 — retire the docstring that asserts the defect

In `src/probos/cognitive/crew_synth.py`, `_build_votes` (`:484`):

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

---

## Tests

One new file: `tests/test_ad1263_shapley_duplicate_participants.py`. Every test drives
the **real** `compute_shapley_values` — no reimplementation of the mapping, no mirror
of the fix. Import `Vote` from `probos.types`; note the field is `approved`, not
`approve`.

Expected values below were produced by executing the proposed implementation against
the real `_evaluate_coalition`. Assert them exactly (`pytest.approx` where float).

**Group A — the discarded ballot (4)**

1. `test_a_second_ballot_under_one_key_is_not_discarded` — `[A approve 0.9, A reject 0.5, B reject 1.0]`, threshold 0.6, weighted. Expect `{"A": 0.5, "B": 0.0}`. Pin the pre-fix value in the docstring (`{"A": 1/3, "B": 1/3}`) so the regression is legible.
2. `test_both_ballots_reach_the_approval_ratio` — same input; additionally assert `A > 0.0`, proving A's *approving* ballot carried a coalition that the surviving rejecting ballot alone could not.
3. `test_disagreeing_ballots_need_no_tiebreak` — one key with `approve` and `reject` ballots resolves without error and returns a finite value in `[0, 1]`.
4. `test_reason_and_confidence_survive_into_the_weighting` — two ballots under one key differing only in `confidence`; assert the result differs from the same input with the first ballot removed. This is what proves the ballot is *weighed*, not merely *counted*.

**Group B — the all-zero fallback (4)**

5. `test_all_zero_fallback_sums_to_one_with_duplicate_keys` — `[a reject, a reject, b reject]`, threshold 0.6. Expect `{"a": 0.5, "b": 0.5}` and **`sum == pytest.approx(1.0)`** explicitly. Pre-fix: `0.6667`.
6. `test_all_zero_fallback_sums_to_one_with_two_ballots_each` — `[a, a, b, b]` all rejecting. Expect `{"a": 0.5, "b": 0.5}`, `sum == 1.0`. Pre-fix: `0.5000`.
7. `test_all_zero_fallback_unchanged_for_distinct_keys` — `[a, b, c]` all rejecting → `1/3` each, `sum == 1.0`. Guards against over-correction.
8. `test_single_player_with_two_ballots_takes_the_whole_mass` — `[A reject 0.5, A reject 0.5]`. Expect `{"A": 1.0}`. Pre-fix: `{"A": 0.5}`. This is the `n == 1` reordering.

**Group C — the contract as stated (4)**

9. `test_every_value_is_within_zero_and_one` — over a small matrix of duplicate-bearing inputs.
10. `test_values_never_exceed_one_in_total` — same matrix, `sum <= 1.0 + 1e-9`.
11. `test_sum_is_exactly_one_when_no_marginal_is_negative` — all-approving input containing a duplicate key; `sum == pytest.approx(1.0)`.
12. `test_shortfall_equals_the_clamped_mass` — an input with a negative raw marginal; assert `sum < 1.0` **and** that the deficit is accounted for rather than arbitrary, by asserting the clamped player's returned value is exactly `0.0`. This pins D4 as a contract instead of an accident.

**Group D — no collateral movement (4)**

13. `test_distinct_keys_are_unchanged` — parametrised over thresholds `(0.5, 0.6, 0.9)` × `use_confidence_weights` `(True, False)` × coalition sizes 1–7, all distinct ids. Assert against literal expected dicts captured from HEAD. (Parity across these 42 configurations was measured before drafting; this test is the durable guard.)
14. `test_player_count_selects_the_enumeration_strategy` — 11 ballots from 8 distinct-plus-duplicate keys. Monkeypatch `probos.consensus.shapley._approximate_shapley` to raise; assert it is **not** called, proving the exact path was selected on 8 players rather than the Monte Carlo path on 11 ballots.
15. `test_empty_and_single_ballot_are_unchanged` — `[]` → `{}`; one ballot → `{id: 1.0}`.
16. `test_result_survives_the_episodic_json_round_trip` — `json.loads(json.dumps(result)) == result` on a duplicate-bearing result. This is the executable form of D1: it fails immediately if anyone reintroduces a tuple key, and it is the seam `episodic.py:3436` actually uses.

### Gate

```
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1263_shapley_duplicate_participants.py \
  tests/test_shapley.py tests/test_performance_p0.py \
  tests/test_bf783_verifier_not_paid_for_accepting.py \
  tests/test_ad1130_outcome_only_room_trust.py \
  tests/test_ad860_crew_verifier.py -q -n 0
```

then the full parallel gate `pytest tests/ -q -n 4 --dist=loadfile`.

---

## What this does NOT change — do not build

- **Do not add `role` (or any field) to `Vote`.** D1.
- **Do not change the return type or any key.** It must stay `dict[str, float]` keyed
  by the participant key exactly as supplied.
- **Do not make the values always sum to 1.0.** Removing the `abs()`/`max()`
  asymmetry moves every rejected-outcome trust weight at `runtime.py:4026`. Out of
  scope; if the Captain wants it, it is its own AD.
- **Do not touch `crew_synth._build_votes`' behaviour.** Only its docstring changes.
  It needs no composite keys under this model — that is the point of choosing it.
- **Do not add a `try/except` around `quorum.py:114`.** The chosen model cannot
  raise, so a guard there would defend nothing and would hide a future real error.
- **Do not touch `crew_trust.py`.** Its keys are already distinct by construction;
  `_all_approved_shapley` and the `MAX_EXACT_SHAPLEY` pre-check stay exactly as they
  are.
- **Do not touch `qa_pool.py`.** Its existing `try/except` fallback is correct and is
  not reached by this change.
- **Do not fix BF-833 (#1298) or BF-834 (#1299).** They are cited here only to
  establish that duplicate `agent_id`s in `quorum` results are reachable. Straggler
  containment is their work, not this one's.
- **Do not touch the HXI, `api.py`, `panels.py`, `runtime.py`, `episodic.py`, or
  `types.py`.** The shape is deliberately preserved so none of them need to move; if
  a change here forces one of them, the design decision was violated — stop and
  surface it.
- **No config, no YAML, no schema, no new dependency, no feature flag.** This is a
  correctness fix to a pure function.

---

## Tracking

- `PROGRESS.md` — AD-1263 entry on ship; record honestly that crew-synthesis
  attribution values are **unchanged** and that the live value impact is on the
  quorum path.
- `docs/development/roadmap.md` — Bug Tracker row for BF-837 (#1303) → CLOSED by
  AD-1263.
- `DECISIONS.md` — one entry recording D1 (participant key, not agent id; shape
  frozen by `episodic.py:3436` and `ui/src/store/types.ts:349`), D2 (total, never
  raises, because `quorum.py:114` is unguarded), and D4 (the normalisation contract
  as actually implemented, and why the asymmetry was left alone).
- Issue #1303 — close on push, quoting the H1/H2/H3 measurements and stating plainly
  that H4 (the crew case) is unchanged.

---

## Acceptance criteria

1. All 16 new tests pass, driving the real `compute_shapley_values`.
2. `tests/test_shapley.py`, `tests/test_performance_p0.py`,
   `tests/test_bf783_verifier_not_paid_for_accepting.py`,
   `tests/test_ad1130_outcome_only_room_trust.py` and
   `tests/test_ad860_crew_verifier.py` pass **unamended**. If any needs amending,
   stop — it means the distinct-id parity claim is wrong and the design must be
   re-reviewed, not the test.
3. The full parallel gate passes with no new failures and no new warnings on changed
   paths.
4. `grep -n "vote_by_id" src/probos/consensus/shapley.py` returns nothing.
5. `grep -n "LAST one wins" src/` returns nothing.
6. `compute_shapley_values` still returns `dict[str, float]`; `Vote` has exactly its
   five existing fields.
7. Public functions carry full type annotations; the `debug` log names both counts
   and the offending keys.
8. **Verify all changes comply with the Engineering Principles in
   `.github/copilot-instructions.md`.**

---

## Verified Against Codebase (2026-08-24)

Executed, not read. Facts asserted as ABSENT were enumerated and the enumeration is shown.

```
python -c "<drive the real compute_shapley_values>"
  Vote fields: ['agent_id', 'approved', 'confidence', 'reason', 'timestamp']
  D1 votes_in=3 agents_out=2 -> {'both': 0.5, 'solo': 0.5} sum=1.0000
  D3 3 distinct reject     votes=3 agents=3 sum=1.0000
  D3 3 votes / 2 agents    votes=3 agents=2 sum=0.6667
  D3 4 votes / 2 agents    votes=4 agents=2 sum=0.5000
  tuple key JSON: TypeError -> keys must be str, int, float, bool or None, not tuple

<prototype of the proposed implementation vs HEAD>
  H1 [A ok .9, A no .5, B no 1.0] thr .6  OLD {'A':.3333,'B':.3333} sum .6667
                                          NEW {'A':.5,   'B':.0}    sum .5000
  H2 [a no, a no, b no]           thr .6  OLD sum .6667  NEW {'a':.5,'b':.5} sum 1.0000
  H3 [A no, A no]                 thr .6  OLD {'A':.5}   NEW {'A':1.0}
  H4 [both ok .9, both ok .5, solo ok .8] OLD {'both':.5,'solo':.5}  NEW identical
  Distinct-id parity across 42 configs: True
```

```
grep -n "n = len(votes)|vote_by_id|agent_ids = |n == 1|MAX_EXACT_SHAPLEY|1.0 / n|coalition.append" src/probos/consensus/shapley.py
   12: MAX_EXACT_SHAPLEY = 10
   58: n = len(votes)
   59: if n == 1:
   63: vote_by_id: dict[str, Vote] = {v.agent_id: v for v in votes}
   64: agent_ids = list(vote_by_id.keys())
   66: if n <= MAX_EXACT_SHAPLEY:
   77: normalized = {aid: 1.0 / n for aid in agent_ids}
   84: vote_by_id: dict[str, Vote],
   99: coalition.append(vote_by_id[aid])
  110: vote_by_id: dict[str, Vote],
  126: coalition.append(vote_by_id[aid])
```

```
grep -rn "compute_shapley_values|shapley_values" src/          # every consumer
  consensus/quorum.py:15,114                 -> result.shapley_values  (NO try/except)
  cognitive/crew_synth.py:50,491,513,617     -> _build_votes / _attribute
  cognitive/crew_trust.py:15,268,274         -> composite keys + MAX_EXACT pre-check
  cognitive/self_improvement/qa_pool.py:59   -> injected, guarded by try/except
  cognitive/episodic.py:3436                 -> json.dumps(ep.shapley_values)
  experience/panels.py:267                   -> shapley_values.get(agent.id)
  runtime.py:3990,4026                       -> HXI event payload; trust weight
  types.py:251,629                           -> ConsensusResult / Episode fields
```

```
grep -n "child:|facilitator:" src/probos/cognitive/crew_trust.py   # the precedent for D1
  252: vote_keys = [f"child:{child.work_item_id}" for child in children]
  253: facilitator_vote_key = f"facilitator:{session_id}"
```

```
grep -n "shapley" ui/src/store/types.ts
  349: shapley: Record<string, number>;
```

CLAIM: no existing test pins the collapse or the short normalisation as contract.
```
rg -n 'compute_shapley_values' tests/
  test_shapley.py (24 hits) · test_performance_p0.py:137,148,162 ·
  test_ad1130_outcome_only_room_trust.py:28,884,977,980 · test_layer_boundaries.py:104
rg -n '_build_votes|LAST one wins|verdict_to_vote' tests/
  test_ad860_crew_verifier.py:341,346 · test_bf783_…:4,157 · test_self_monitoring.py:704 (unrelated)
```
HOLDS: yes — every `compute_shapley_values` call in tests uses **distinct** ids
(`a1/a2/a3`, `agent_{i}`), so none exercises the collapsed path. The two nearest
assertions are `test_values_sum_to_at_most_one` (`<= 1.0`, still true) and
`test_values_sum_to_one_with_approvals` (`≈ 1.0` on an all-approving distinct-id
input, unchanged). `test_bf783_…:157` asserts trust *records*, not values, and its
docstring already says the two votes "merge" — false at HEAD, true after this AD.

CLAIM: `quorum.evaluate` can emit duplicate `agent_id`s, so a raise is unsafe.
```
sed -n '76,86p' src/probos/consensus/quorum.py
  for r in results:
      vote = Vote(agent_id=r.agent_id, approved=r.success, ...)
      votes.append(vote)        # no dedup, no uniqueness precondition
```
HOLDS: yes — one `Vote` per `IntentResult`, keyed straight off `r.agent_id`, and
#1298/#1299 are open defects in which one agent's result lands in another
broadcast's result list.

CLAIM: every `crew_synth` ballot is approving, so H4 is unchanged.
```
crew_synth.py:163     accepted = [oc for oc in outcomes if oc.verdict.accepted]
crew_synth.py:499     approved=oc.verdict.accepted        # True across `accepted`
crew_verifier.py:1327 approved=verdict.accepted           # same verdict object
```
HOLDS: yes — confirmed independently by the H4 measurement above.
