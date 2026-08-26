# AD-1263 / BF-837 — the game is played over agents, not over ballots

**Status:** ready to build
**Closes:** BF-837 ([#1303](https://github.com/seangalliher/ProbOS/issues/1303))
**Branch / base:** `main` @ `c4820d75`
**Supersedes:** `prompts/ad-1263-shapley-duplicate-participant-key.md` (rev 1 — built, reverted) and `prompts/ad-1263-one-player-per-participant-key.md` (rev 2 — only its `MAX_EXACT_SHAPLEY` half shipped, as BF-850 in `4f667ea7`)
**Dependencies:** AD-223/AD-224 (`compute_shapley_values`), BF-850 (`MAX_EXACT_SHAPLEY = 8`, shipped), AD-1272 (`combine_verdicts`, shipped at `c4820d75`)
**Estimated tests:** 18 new in one new file · **2 existing tests amended** (both mandatory, both named in §7) · 1 docstring corrected

---

## 1. Numbering

| Question | Answer |
|---|---|
| Did anything ship under AD-1263? | **No.** `git log -S "vote_by_id" -- src/probos/consensus/shapley.py` returns only `340207ac` and `e33431f4`, both pre-dating AD-1263. |
| Is a new number needed? | **No.** AD-1263 is allocated to #1303 and unconsumed. |
| New BF minted here? | **None.** Backlog Burn-Down Mode; this closes one issue. |

---

## 2. Problem — measured by execution against HEAD, not recalled

`src/probos/consensus/shapley.py:68` builds one entry per *distinct* `agent_id`:

```python
n = len(votes)                                            # :63  — ballots
...
vote_by_id: dict[str, Vote] = {v.agent_id: v for v in votes}   # :68  — players
agent_ids = list(vote_by_id.keys())                       # :69
```

`n` counts **ballots that arrived**; `agent_ids` counts **players in the game**. The two are
spent interchangeably. Every finding below is that one confusion.

### 2.1 The five shapes, reproduced

```
MAX_EXACT_SHAPLEY = 8   (threshold 0.6 unless noted)

F1  A(T,.9) A(F,.2) B(T,.8) C(T,.8)  -> {'A': 0.0, 'B': 0.5, 'C': 0.5}   SUM=1.000000
    A's approving ballot is discarded; A is credited as a pure dissenter.

F2  A(T,.9) A(F,.2) B(T,.8)          -> {'A': 0.0,   'B': 1.0}
    A(F,.2) A(T,.9) B(T,.8)          -> {'A': 0.5,   'B': 0.5}
    Same ballots, different arrival order, different attribution. Last write wins.

F3  A(T,0.0) A(T,0.0) B(T,0.0)       -> {'A': 0.3333, 'B': 0.3333}  SUM=0.666667
    The all-zero fallback is `1.0 / n` over `agent_ids`: n=3 ballots, 2 players.

F3b A(F,.5) A(F,.5)                  -> {'A': 0.5}                  SUM=0.500000
    NOT IN THE ISSUE. n=2 skips the `n == 1` short circuit at :64, the single
    surviving rejecting ballot clamps to zero, and one player is handed half a game.

F4  A x5 + B x5 (10 ballots)         -> {'A': 0.523, 'B': 0.477}   SUM=1.000000
    n=10 > 8 selects Monte Carlo for a TWO-player game. Exact 0.5/0.5 was free.
    Sampling noise for nothing.

CTRL 3 distinct, all approve         -> 0.3333 x3                  SUM=1.000000
CTRL 1 ballot                        -> {'A': 1.0}                 SUM=1.000000
```

`F3b` is a sixth defect of the same root cause and is in scope. **F3 and F4 are in scope**:
they are not separate bugs, they are the other two places `n` is spent.

### 2.2 The sharpest statement: HEAD solves a different game than the one that was voted

`QuorumEngine.evaluate` (`quorum.py:72-90`) tallies **every** result, then hands the same
votes to Shapley, which throws most of them away. Measured on `A ok · A ok · A ok · B fail`:

```
engine outcome = approved      (weighted 2.7 / 3.6 = 0.75 >= 0.6)
v(N) over ALL 4 ballots        = True     <-- the vote that was actually held
v(N) over HEAD's 2 survivors   = False    <-- the grand coalition HEAD enumerates
HEAD shapley = {'A': 0.5, 'B': 0.0}       SUM=0.500000
```

**The characteristic function reports that the grand coalition fails a vote the engine
passed.** Attribution is not merely lossy — it is computed over a coalition game whose
outcome contradicts the consensus it is attributing. That is the defect; the discarded
ballot is a symptom.

### 2.3 Production reachability — established

`quorum.py:73` builds one `Vote` per `IntentResult`, so an agent returning N successful
results casts N ballots. `runtime.py:4060-4062` produces exactly that shape. This is not
hypothetical and it is not confined to `crew_synth`.

---

## 3. Decision D1 — one player per `agent_id`, carrying every ballot it cast

> **A participant that voted more than once is ONE player holding ALL of its ballots. When
> that player joins a coalition, all of its ballots join with it, and they combine by
> confidence-weighted approval: `Σapproval / Σweight >= approval_threshold`.**

### Why this rule and not another

This is the Captain's option (a) — the rule AD-1272 established in
`consensus/verification.py::combine_verdicts` for combining a set of weighted booleans.
**It requires no extraction and no casting**, because that rule did not originate in
`verification.py`. Its own module docstring (`verification.py:7-9`) says so:

> "The rule mirrors ``_evaluate_coalition`` in ``shapley.py``: the system already decided
> that a weighted set of booleans agrees when its confidence-weighted approval clears
> ``policy.approval_threshold``."

`_evaluate_coalition` (`shapley.py:20-39`) is the original. Letting a player's ballots enter
a coalition together **is** that rule, applied by the function that already owns it.
Verified by execution:

```
_evaluate_coalition([A approve@0.9, A reject@0.2], 0.6, True) -> True     (0.9/1.1 = 0.818)
combine_verdicts     on the same two weights, same threshold -> True      (identical arithmetic)
```

The Captain's caveat about `VerificationResult`-typed reuse is therefore moot: nothing is
constructed, nothing is cast, and no arithmetic is duplicated.

### Rejected alternatives — decided by enumerating consumers, not by taste

| Consumer | Anchor | What it does with the returned dict |
|---|---|---|
| **AD-1272 trust spend** | `runtime.py:4121` | `consensus.shapley_values.get(target_agent_id)` where `target_agent_id ∈ {r.agent_id for r in results if r.success}` (`:4090`) — **a bare agent id**; `None` → `continue` (`:4123-4134`) |
| HXI consensus event | `runtime.py:3992` | `"shapley": consensus.shapley_values or {}` → JSON to the UI |
| HXI store type | `ui/src/store/types.ts:349` | `shapley: Record<string, number>` |
| Episodic persistence | `episodic.py:3436` | `json.dumps(ep.shapley_values)` — **str keys only** |
| Episodic read-back | `episodic.py:3611` | `json.loads(...)` |
| Agents panel | `panels.py:267` | `shapley_values.get(agent.id)` — **a bare agent id** |
| `crew_synth` attribution | `crew_synth.py:507-517` | keys become `SynthesisResult.shapley_values`; `test_ad861_crew_synth.py:213` asserts the exact key set |
| `crew_trust` | `crew_trust.py:267-272` | `len(votes) <= MAX_EXACT_SHAPLEY` pre-check, then calls |
| QA pool | `qa_pool.py:59` | injected `shapley_fn`, pool default 3 |
| Introspection | `runtime.py:3997` | `_last_shapley_values` |

**(b) one player per ballot (`A#1`, `A#2`) is unavailable, not merely awkward.** Under
per-ballot keys no `result.agent_id` matches any key, so `runtime.py:4122` takes
`attributed is None` → `continue` for **every agent in every consensus round**. Trust would
stop accruing entirely, silently but for a warning. It also breaks the two bare-id lookups
and changes the `test_ad861` key set. Five consumers need bare agent ids; none needs
per-ballot identity. The table decides it.

**(c) deterministic last-write-wins still discards a ballot.** F2 shows the discard is
material (A gets 0.0 or 0.5 depending on which ballot survives), and it leaves §2.2
untouched — the grand coalition would still contradict the engine. It also fixes neither
F3 nor F4.

### D1 implementation shape — and why it is not the naive one

A player's ballots reduce to **two floats**, because the rule is linear:
`(Σ weight over approving ballots, Σ weight over all ballots)`. The naive form — flattening
ballots into `_evaluate_coalition` — is arithmetically identical but makes coalition
evaluation `O(total_ballots)` instead of `O(players)`. **Measured at 8 players, the
BF-850 bound:**

| ballots/player | total ballots | naive flatten | player summary |
|---:|---:|---:|---:|
| 1 | 8 | 0.178 s | 0.059 s |
| 3 | 24 | 0.392 s | 0.065 s |
| **5** | **40** | **0.627 s — busts the 0.5 s BF-850 budget** | 0.061 s |
| 10 | 80 | 1.198 s — busts it | 0.060 s |
| 25 | 200 | 3.231 s — busts it | 0.061 s |

**The naive form re-breaks BF-850 at five ballots per player.** The player summary is flat in
ballot count and ~3× faster than HEAD. Build the summary form. Test 12 pins the budget.

---

## 4. Decision D2 — the game size is the player count, at every site

> **`n` means "players in the game" everywhere. Any quantity that measures how big the game
> is must count the same set that gets enumerated.**

Three sites inside the function, enumerated exhaustively:

| Site | Anchor | HEAD | After |
|---|---|---|---|
| Short circuit | `:63-65` `n = len(votes)`, `if n == 1` | ballots | players — fixes **F3b** |
| Tier selection | `:71` `if n <= MAX_EXACT_SHAPLEY` | ballots | players — fixes **F4** |
| Equal split | `:82` `{aid: 1.0 / n ...}` | ballots | players — fixes **F3** |

**A fourth site lives outside the function and must NOT change.** `crew_trust.py:267` runs
its own `if len(votes) <= MAX_EXACT_SHAPLEY` pre-check. Verified distinct-by-construction:
`crew_trust.py:238-241` raises `crew_trust_evidence_invalid` when
`len({child.work_item_id for child in children}) != len(children)`, and the keys are
`child:<work_item_id>` plus one `facilitator:<session_id>` (`:252-253`). There
`len(votes) == n players` already, so the pre-check stays correct in the new units with no
edit. Leave it alone.

**`MAX_EXACT_SHAPLEY` does not change.** It is already 8 (BF-850, `4f667ea7`) and the
player summary keeps the exact path inside its budget regardless of ballot multiplicity.

---

## 5. Decision D3 — the conservation invariant, corrected

The brief asks whether the dict "still sums to 1.0 in every shape." **It does not, and it
must not.** Negative marginals are clamped at `:80` (`max(0.0, v) / total`), which
legitimately drops mass in mixed-verdict rounds. Measured, HEAD **and** after:

```
3 distinct, all approve        -> {A:.333, B:.333, C:.333}  SUM=1.000000
2 approve + 1 dissenter        -> {A:.400, B:.400, C:.000}  SUM=0.800000   <-- correct, not a bug
```

Two existing tests already depend on the weaker property, and they are right:

- `test_shapley.py:143-151` — `test_values_sum_to_at_most_one` asserts `<= 1.0 + 1e-9`.
- `test_ad1272_...py:348` — `_assert_spend_conserved` computes `available` **from the round**,
  with the comment "a mixed-verdict round has an attributable total below 1.0."

> **The invariant is: `sum(values) <= 1.0` always; `== 1.0` whenever no marginal is clamped;
> and the all-zero equal-split branch `== 1.0` exactly.** F3 and F3b violate the third
> clause today. Do not write a test asserting `== 1.0` unconditionally — it would fail on
> correct dissenter rounds and would pin the wrong contract.

---

## 6. What this does to AD-1272 — one test moves, and it is a premise, not the conservation

AD-1272's spend loop already keys on **bare agent ids, once per distinct agent**
(`runtime.py:4090`, `:4119-4121`). Keys and cardinality are unchanged by this AD.
Measured, HEAD vs the proposed rule:

```
A,A,A + B  (all succeed)   HEAD {A:.5,  B:.5 } SUM=1.0000  ->  {A:.5,  B:.5 } SUM=1.0000   IDENTICAL
A,A,A + B  (B fails)       HEAD {A:.5,  B:.0 } SUM=0.5000  ->  {A:1.0, B:.0 } SUM=1.0000   MOVES
3 distinct                 HEAD {.333 x3}      SUM=1.0000  ->  identical                    IDENTICAL
dissenter                  HEAD {.4,.4,.0}     SUM=0.8000  ->  identical                    IDENTICAL
```

Test-by-test, all 35 in `tests/test_ad1272_trust_accrues_per_unit_of_work.py`:

| Test | Fixture | Effect |
|---|---|---|
| all 22 `TestCombineVerdicts` | `verification.py` only | **untouched** — this AD does not import or modify it |
| `test_duplicate_agent_one_verifier_spends_once_per_agent` `:378` | `[A,A,A,B]` all succeed | **no movement** — attribution identical |
| `test_duplicate_agent_two_verifiers_spends_once_per_agent` `:387` | same | **no movement** |
| `test_three_distinct_agents_two_verifiers_spend_three_times` `:398` | distinct | **no movement** (parity, §8) |
| **`test_mixed_verdict_denominator_is_below_one` `:399`** | `[A,A,A,B(fail)]` | **MOVES — must be amended.** `available` becomes 1.0, so `assert available < 1.0` (`:406`) fails, and `:411` `== {"A"}` no longer holds |
| `test_nine_agents_monte_carlo_spend_is_conserved` `:414` | 9 distinct | **no movement** — 9 players > 8 both ways |
| `test_sub_floor_shapley_value_is_spent_as_computed` `:428` | `consensus_override` | **no movement** — bypasses Shapley |
| `test_empty_shapley_keeps_the_unit_weight_branch` `:447` | INSUFFICIENT | **no movement** — no attribution computed |
| remaining `TestSpendConservation` / verifier-integrity tests | distinct or override | **no movement** |

**The conservation assertion itself (`spent == available`, `len(calls) == len(verified)`,
`{keys} == verified`) is preserved in every case, including the one that moves.** Only the
*premise guard* that the denominator is below 1.0 moves, because this AD makes A's three
ballots count and A therefore earns the whole attributable game.

---

## 7. Implementation

### 7.1 `src/probos/consensus/shapley.py`

**(a) Add the shared rule and the player summary.** Insert after `MAX_EXACT_SHAPLEY` (`:17`).

```
===SEARCH===
MAX_EXACT_SHAPLEY = 8


def _evaluate_coalition(
    coalition_votes: list[Vote],
    approval_threshold: float,
    use_confidence_weights: bool,
) -> bool:
    """Check if a coalition of votes achieves quorum approval."""
    if not coalition_votes:
        return False

    weighted_approval = 0.0
    total_weight = 0.0
    for v in coalition_votes:
        weight = v.confidence if use_confidence_weights else 1.0
        total_weight += weight
        if v.approved:
            weighted_approval += weight

    if total_weight == 0:
        return False
    return (weighted_approval / total_weight) >= approval_threshold
===REPLACE===
MAX_EXACT_SHAPLEY = 8


class _PlayerWeight(NamedTuple):
    """One participant's whole ballot set, reduced to the two sums the rule needs.

    BF-837: a participant that voted more than once is one player holding all of
    its ballots, and the coalition rule is linear in them, so the ballots reduce
    to a pair once instead of being re-summed inside every coalition. Measured at
    the ``MAX_EXACT_SHAPLEY`` bound with 25 ballots per player: 0.061 s here
    against 3.23 s for the equivalent form that carries the ballot lists, which
    would have re-broken BF-850's 0.5 s synchronous budget.
    """

    approval: float
    total: float


def _clears_threshold(
    weighted_approval: float, total_weight: float, approval_threshold: float,
) -> bool:
    """The consensus rule, in the one place it is allowed to live.

    ``verification.combine_verdicts`` (AD-1272) documents itself as mirroring
    this arithmetic; it is the same rule at a different scale, so it stays one
    expression.
    """
    if total_weight == 0:
        return False
    return (weighted_approval / total_weight) >= approval_threshold


def _summarise_players(
    votes: list[Vote], use_confidence_weights: bool,
) -> dict[str, _PlayerWeight]:
    """Collapse ballots to one entry per ``agent_id``, first-appearance ordered."""
    players: dict[str, _PlayerWeight] = {}
    for v in votes:
        weight = v.confidence if use_confidence_weights else 1.0
        prior = players.get(v.agent_id)
        approval = (prior.approval if prior is not None else 0.0)
        total = (prior.total if prior is not None else 0.0)
        players[v.agent_id] = _PlayerWeight(
            approval + (weight if v.approved else 0.0), total + weight,
        )
    return players


def _evaluate_coalition(
    coalition_votes: list[Vote],
    approval_threshold: float,
    use_confidence_weights: bool,
) -> bool:
    """Check if a coalition of votes achieves quorum approval."""
    if not coalition_votes:
        return False

    weighted_approval = 0.0
    total_weight = 0.0
    for v in coalition_votes:
        weight = v.confidence if use_confidence_weights else 1.0
        total_weight += weight
        if v.approved:
            weighted_approval += weight

    return _clears_threshold(weighted_approval, total_weight, approval_threshold)
===END REPLACE===
```

Add `NamedTuple` to the `typing` import at `:7` (`from typing import TYPE_CHECKING, NamedTuple`).

> `_evaluate_coalition` keeps its signature and its behaviour. It is imported by
> `tests/test_performance_p0.py:178` and named in `verification.py`'s docstring; both stay
> true. It is not called from the Shapley loops after this change — that is intended, and it
> is not dead: it is the list-shaped adapter for the same rule.

**(b) Players, not ballots, in `compute_shapley_values`.**

```
===SEARCH===
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
    # BF-837: one player per agent_id, carrying every ballot it cast. A
    # participant that voted twice used to have its earlier ballot replaced
    # outright, which left the grand coalition failing votes the quorum engine
    # had passed.
    players = _summarise_players(votes, use_confidence_weights)
    agent_ids = list(players.keys())

    # The game is played over players. ``n`` measures the set that actually gets
    # enumerated -- the short circuit, the tier selection and the equal split
    # below all read it, and all three were previously counting ballots.
    n = len(agent_ids)
    if n == 1:
        return {agent_ids[0]: 1.0}

    if n <= MAX_EXACT_SHAPLEY:
        raw_values = _exact_shapley(agent_ids, players, approval_threshold)
    else:
        raw_values = _approximate_shapley(agent_ids, players, approval_threshold)
===END REPLACE===
```

**(c) The two enumerators accumulate player pairs.** Replace the bodies of `_exact_shapley`
(`:87-110`) and `_approximate_shapley` (`:113-140`) so each takes
`players: dict[str, _PlayerWeight]`, drops the now-unused `use_confidence_weights`
parameter (weighting is applied during summarisation, so it can no longer drift), and
accumulates `approval` / `total` across the permutation:

```python
        for aid in perm:
            v_without = _clears_threshold(approval, total, approval_threshold)
            player = players[aid]
            approval += player.approval
            total += player.total
            v_with = _clears_threshold(approval, total, approval_threshold)
            marginal_sums[aid] += float(v_with) - float(v_without)
```

`_approximate_shapley` keeps its `samples: int = 1000` keyword. Update both docstrings and
`compute_shapley_values`' docstring (`:52-58`) to say the players are agents and the value is
per agent.

### 7.2 `src/probos/cognitive/crew_synth.py:488-494` — a docstring that asserts the defect

The `_build_votes` docstring currently states the bug as the contract:

> "``compute_shapley_values`` builds ``{v.agent_id: v}`` — so the LAST one wins outright
> rather than being combined. Filed separately; it does not reach trust today…"

Replace with a statement of the new rule: a dual-role agent yields two Votes and they now
combine into one player by confidence-weighted approval. **No code change in this file.**

### 7.3 `tests/test_performance_p0.py:186-190` — mandatory amendment

This test reaches the private enumerators directly, so the signature change breaks it:

```python
        vote_by_id = {v.agent_id: v for v in votes}      # :186
        agent_ids = list(vote_by_id.keys())              # :187
        exact = _exact_shapley(agent_ids, vote_by_id, 0.5, True)              # :189
        approx = _approximate_shapley(agent_ids, vote_by_id, 0.5, True, samples=5000)  # :190
```

Amend to build the summary via `_summarise_players(votes, True)` and drop the trailing
`True`. **Do not weaken the assertion** (`abs(exact[aid] - approx[aid]) < 0.1`) and do not
change the three distinct votes it uses. Rev 1 of this AD claimed "0 existing tests amended"
while its own patch amended this file; state the amendment in the commit message.

### 7.4 `tests/test_ad1272_trust_accrues_per_unit_of_work.py:399-411` — mandatory amendment

Change the fixture so the round still clamps. Simulated against the proposed rule (the
Builder must re-measure against the built code and use the observed figures):

```python
        results = [_result("A"), _result("A"), _result("B"), _result("C", success=False)]
        # proposed rule -> {A: 0.625, B: 0.25, C: 0.0}; available over {A, B} = 0.875
```

Then `:411` becomes `== {"A", "B"}`. **Keep** `assert available < 1.0` and its comment —
that premise guard is the reason the test exists, and the new fixture must satisfy it
honestly rather than by relaxing the assertion. **Do not touch** `_assert_spend_conserved`.

---

## 8. Tests — `tests/test_ad1263_shapley_players_not_ballots.py`

Assert on returned values and conservation. **Never assert a Monte Carlo figure** — above
8 players the values are sampled and vary run to run. Where the approximate path is
exercised, assert only which path ran, key sets, and `sum <= 1.0`.

**`TestPlayersNotBallots`**
1. `test_a_duplicate_ballot_no_longer_replaces_its_predecessor` — F1 input → all three keys present, `sv["A"] == pytest.approx(1/3)`, sum `== approx(1.0)`.
2. `test_ballot_arrival_order_does_not_change_attribution` — F2 both orders → equal dicts; assert `{"A": 0.5, "B": 0.5}`.
3. `test_a_players_ballots_combine_by_confidence_weighted_approval` — unit-test `_clears_threshold(0.9, 1.1, 0.6) is True` and `_clears_threshold(0.2, 1.1, 0.6) is False`; plus `_summarise_players` returns `_PlayerWeight(0.9, 1.1)` for `[A(T,.9), A(F,.2)]`.
4. `test_a_single_player_with_many_ballots_takes_the_whole_game` — F3b → `{"A": 1.0}`.
5. `test_keys_are_bare_agent_ids` — duplicates present → keys `== {"A","B"}`, every key `isinstance(str)`.

**`TestConservation`**
6. `test_all_zero_confidence_with_duplicates_splits_the_whole_game` — F3 → `{"A": 0.5, "B": 0.5}`, sum `== approx(1.0)`.
7. `test_values_never_exceed_one` — parametrised over ≥6 shapes incl. duplicates → `sum <= 1.0 + 1e-9`, all values `>= 0.0`.
8. `test_a_clamped_round_legitimately_sums_below_one` — `[A(T,1), B(T,1), C(F,1)]` unweighted → `C == 0.0`, sum `== approx(0.8)`. **Pins D3; guards against anyone "fixing" conservation to an unconditional 1.0.**
9. `test_equal_split_fallback_sums_to_exactly_one` — all-zero-confidence with duplicates and without.

**`TestGameSizeIsThePlayerCount`** — monkeypatch spies on `shapley._exact_shapley` / `shapley._approximate_shapley` (pattern at `test_performance_p0.py:215-241`).
10. `test_ballot_count_above_the_bound_still_takes_the_exact_path` — F4 (10 ballots, 2 players) → exact spy called, approximate not; values `{"A": 0.5, "B": 0.5}` exactly.
11. `test_player_count_above_the_bound_takes_the_approximate_path` — `MAX_EXACT_SHAPLEY + 1` distinct → approximate spy called. No value assertions.
12. `test_the_exact_path_stays_inside_the_bf850_budget_under_ballot_multiplicity` — `MAX_EXACT_SHAPLEY` players × 25 ballots each → exact path, `elapsed < 0.5`. **Mandatory: the rejected flatten design measures 3.23 s here.**

**`TestGrandCoalitionAgreesWithTheVote`** — the seam.
13. `test_the_grand_coalition_matches_the_quorum_engines_own_verdict` — drive the real `QuorumEngine.evaluate` on `[A ok, A ok, A ok, B fail]`; premise-assert `consensus.outcome is ConsensusOutcome.APPROVED`, then assert the summarised grand coalition clears via `_clears_threshold`. **Fails at HEAD.**

**`TestDistinctIdParity`**
14. `test_distinct_ids_are_unaffected` — re-pin what `test_shapley.py` relies on: 3 unanimous → `1/3` each; dissenter → `0.0`; single ballot → `{"a1": 1.0}`; empty → `{}`.
15. `test_composite_participant_keys_are_unaffected` — `child:w1`, `child:w2`, `facilitator:s1` (the AD-1130 shape) → 3 players, sum `== approx(1.0)`.

**`TestConsumerContracts`**
16. `test_result_survives_the_episodic_json_round_trip` — `json.loads(json.dumps(sv)) == sv` with duplicates in the input (`episodic.py:3436`/`:3611`).
17. `test_a_bare_agent_id_lookup_resolves` — `sv.get("A") is not None` for the `panels.py:267` / `runtime.py:4121` access shape.

**`TestSpendSeam`** — crosses quorum → verify → combine → trust in one test.
18. `test_one_spend_per_distinct_agent_survives_the_merge` — a real round over `[A, A, A, B]` with a fake verifier: `len(calls) == 2`, `{c["agent_id"] for c in calls} == {"A","B"}`, `sum(weights) == approx(sum of shapley over verified)`. Reuse the `_run_round` fixture shape from `test_ad1272_...py:262-315`; do not import it across files — copy the minimal form.

---

## 9. What this does NOT change — do not build

- **Do not change `MAX_EXACT_SHAPLEY`.** BF-850 set it to 8 at `4f667ea7`; the player summary keeps the exact path inside its budget.
- **Do not modify `src/probos/runtime.py`.** AD-1272 shipped at `c4820d75`; the spend loop already keys on bare ids, once per distinct agent, and needs no edit.
- **Do not modify `consensus/verification.py` or `combine_verdicts`.** Reuse here is by shared arithmetic, not by import.
- **Do not modify `crew_trust.py:267`.** Its pre-check is correct in the new units (§4).
- **Do not change `QuorumEngine.evaluate`'s outcome arithmetic** (`quorum.py:72-96`). It already counts every ballot; this AD makes Shapley agree with it, not the reverse.
- **Do not re-key to per-role, composite or tuple keys.** Five consumers require bare `str` agent ids (§3).
- **Do not reintroduce a weight floor.** AD-1272 removed `max(value, 0.1)` deliberately.
- **Do not harden `Vote.confidence` validation** (negative / NaN / `None`). That is `combine_verdicts`' concern and is out of scope.
- **Do not touch #1304 or #1313**, and do not open adjacent issues. Backlog Burn-Down Mode: one issue, bounded fix.
- **Do not weaken `tests/test_consensus_integration.py`** — it must pass unmodified. Distinct-id parity (§10) is what protects it.
- **Do not delete or relax any assertion in `test_shapley.py`.** If one fails, the parity property is broken and the design is wrong — stop and surface it.

---

## 10. Acceptance criteria

1. All five measured shapes are corrected: F1 credits A, F2 is order-independent, F3 sums to exactly 1.0, F3b returns `{"A": 1.0}`, F4 takes the exact path.
2. **Distinct-id parity is bit-exact.** Verified before drafting by executing HEAD against the proposed rule over **18,000 configurations** (2–7 distinct agents × weighted/unweighted × thresholds 0.5/0.6/0.75): **0 differences under `==` with no tolerance.** If any existing test in `test_shapley.py`, `test_consensus_integration.py`, `test_ad861_crew_synth.py` or `test_ad1130_outcome_only_room_trust.py` moves, the implementation diverges from this spec — stop and surface it.
3. `sum(values) <= 1.0` in every shape; `== 1.0` where no marginal is clamped; the equal-split branch `== 1.0` exactly (§5).
4. Exactly **two** existing tests are amended — `test_performance_p0.py:186-190` and `test_ad1272_...py:399-411` — and both amendments are named in the commit message with their reason.
5. AD-1272's conservation assertions are unchanged and passing; `tests/test_ad1272_trust_accrues_per_unit_of_work.py` is green at 35 tests.
6. The exact path completes in **< 0.5 s** at `MAX_EXACT_SHAPLEY` players regardless of ballot multiplicity (test 12).
7. No Monte Carlo figure is asserted anywhere in the new file.
8. Focused gate green: `pytest tests/test_ad1263_shapley_players_not_ballots.py tests/test_shapley.py tests/test_performance_p0.py tests/test_consensus_integration.py tests/test_ad1272_trust_accrues_per_unit_of_work.py tests/test_ad861_crew_synth.py tests/test_ad1130_outcome_only_room_trust.py -q -p no:randomly`
9. Adversarial review on the staged diff with a different model, findings repaired, **then** one full-repository gate on the frozen tree.
10. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**
11. Update `PROGRESS.md` and the `docs/development/roadmap.md` Bug Tracker row for BF-837; close #1303 with the measured before/after for all five shapes.

---

## 11. Verified Against Codebase (2026-08-26, `main` @ `c4820d75`)

```
git log --oneline -1
  c4820d75 fix(bf-851): trust accrues per unit of work, and verdicts combine before it is spent

git log --oneline -S "vote_by_id" -- src/probos/consensus/shapley.py
  e33431f4, 340207ac          # no AD-1263 code has ever landed

git log --oneline -3 -- src/probos/consensus/shapley.py
  4f667ea7 BF-850: bound exact Shapley at 8, below the factorial cliff

src/probos/consensus/shapley.py
    17: MAX_EXACT_SHAPLEY = 8
    20: def _evaluate_coalition(
    26:     if not coalition_votes:
    42: def compute_shapley_values(
    60:     if not votes:
    63:     n = len(votes)
    64:     if n == 1:
    65:         return {votes[0].agent_id: 1.0}
    68:     vote_by_id: dict[str, Vote] = {v.agent_id: v for v in votes}
    69:     agent_ids = list(vote_by_id.keys())
    71:     if n <= MAX_EXACT_SHAPLEY:
    72:         raw_values = _exact_shapley(agent_ids, vote_by_id, approval_threshold, use_confidence_weights)
    74:         raw_values = _approximate_shapley(agent_ids, vote_by_id, approval_threshold, use_confidence_weights)
    82:         normalized = {aid: 1.0 / n for aid in agent_ids}
    87: def _exact_shapley(          89:     vote_by_id: dict[str, Vote],
   113: def _approximate_shapley(   115:     vote_by_id: dict[str, Vote],

src/probos/consensus/quorum.py:73        Vote(agent_id=r.agent_id, ...) per IntentResult
src/probos/consensus/verification.py:7   "The rule mirrors ``_evaluate_coalition`` in ``shapley.py``"
src/probos/consensus/verification.py:114 (weighted_approval / total_weight) >= approval_threshold
src/probos/runtime.py:3992               "shapley": consensus.shapley_values or {}
src/probos/runtime.py:4090               contributed = {result.agent_id for result in results if result.success}
src/probos/runtime.py:4121               attributed = consensus.shapley_values.get(target_agent_id)
src/probos/cognitive/crew_synth.py:484   def _build_votes(...)      :491-492  "the LAST one wins outright"
src/probos/cognitive/crew_trust.py:239   len({child.work_item_id ...}) != len(children) -> raises
src/probos/cognitive/crew_trust.py:267   if len(votes) <= MAX_EXACT_SHAPLEY
src/probos/cognitive/episodic.py:3436    "shapley_values_json": json.dumps(ep.shapley_values)
src/probos/experience/panels.py:267      sv = shapley_values.get(agent.id)
ui/src/store/types.ts:349                shapley: Record<string, number>;
tests/test_performance_p0.py:186-190     private-enumerator call site (amended)
tests/test_ad1272_...py:399/406/411      mixed-verdict premise (amended)
```

**Absence verified:**

```
CLAIM: _evaluate_coalition has no production caller outside shapley.py
RUN:   Get-ChildItem -Recurse -Include *.py -Path src,tests | Select-String "_evaluate_coalition"
FOUND: shapley.py:20,101,105,128,132  ·  verification.py:7,64 (docstring prose, not calls)
       test_ad1272_...py:131 (comment)  ·  test_performance_p0.py:178 (import, never called)
HOLDS: yes — changing the Shapley loops to stop calling it strands no production consumer.

CLAIM: no existing test constructs a duplicate-agent_id Shapley coalition
RUN:   scanned every tests/*.py matching "Vote(" or "compute_shapley_values" for repeated agent_id
FOUND: none. test_shapley.py uses a1..a5; test_performance_p0.py uses f"agent_{i}";
       crew_trust fixtures use child:<unique>; test_ad861 asserts 4 distinct keys.
HOLDS: yes — which is why distinct-id parity is sufficient to protect the existing suite.
```
