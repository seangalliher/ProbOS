# AD-1282 / BF-782 (#1246) — The path that already sees the correction

**Status:** Ready to build
**Dependencies:** none (BF-778 already shipped; this closes its open question)
**Estimated tests:** 6–8 new, 10 removed/replaced
**Closes:** #1246 (BF-782: design a verification outcome signal that is not farmable)

---

## Summary

`SubtaskVerifier.record_verification_outcome` is dead code reserved for a capability
that **already exists on the live path**, implemented better. Delete the seam, correct
four comments that assert the opposite, and add the full-chain test that proves the live
path credits a refusal once a correction resolves it.

**Do NOT wire `converge()`.** See the decision below.

---

## The decision (answers the two questions on #1246)

### Q1 — Should the legacy orchestrator path use `converge()`?

**No. It is deliberately single-shot and terminal, and it stays that way.**

### Q2 — Where should the resolution signal come from?

**It already comes from the session path, and no new emission is required.**

### The enumeration that decides it

The question is which path can *observe a refusal being resolved by a correction*. That
requires three things at once: seeing the refusal, re-running the producer, and retaining
the round history long enough to attribute the outcome.

| Path | Sees refusal | Re-runs producer | Re-verifies | Retains round history | Live? | Can attribute resolution |
|---|---|---|---|---|---|---|
| `crew_orchestrator._verify()` → `verify()` (`crew_orchestrator.py:1373`) | yes | **no** — builds `ConvergenceOutcome(..., rounds=0)` | no | no | **yes** | **no** |
| `SubtaskVerifier.converge()` (`crew_verifier.py:1203`) | yes | yes | yes | local vars only, discarded on return | **no — zero production callers** | in principle |
| `converge_for_session()` (`crew_verifier.py:1418`), called from `crew_finalizer.py:1315, 2092` | yes | yes | yes | **yes — `history: list[SessionVerificationRound]`** | **yes** | **yes, and already does** |

Only the third row both observes resolution *and* runs in production. It already credits it:

```python
# src/probos/cognitive/crew_trust.py:298-301  (derive_completed_crew_trust_effects)
correct_judgment = verdict["status"] == "accepted" or (
    verdict["status"] == "refuted" and index + 1 < len(child.rounds)
)
```

"A refusal with a later round after it" **is** "a refusal a correction resolved." That
effect is emitted with `role="child_verifier"`, `success=True`,
`intent_type="crew_session_child_verification"`.

**The chain is live end to end** (verified, not recalled):

```
crew_finalizer._completed_trust_effects   (crew_finalizer.py:697)
  → crew_trust.derive_completed_crew_trust_effects   (crew_trust.py:206, credit at :298)
  → durable outbox (evidence_sha256 + outcome_id, idempotent)
  → crew_finalizer.drain_pending_trust   (crew_finalizer.py:664; called at :798, :829, :886, :1114, :3124, :3158)
  → CrewSessionTrustRecorder.drain_pending   (crew_trust.py:511)
  → TrustNetwork.record_outcome_once
```

with the recorder constructed at `startup/finalize.py:2075`. The two failure terminals
credit resolved refusals as well — `derive_convergence_exhausted_effects` (`crew_trust.py:350`)
and `derive_final_refutation_effects` (`crew_trust.py:412`). All three terminal outcomes
are covered.

### Consequences

1. **Wiring `converge()` is wrong.** It has no production caller, and giving it one means
   giving the legacy orchestrator a re-run loop — a change to *admission*, which BF-778
   explicitly scoped out. The repo has already recorded this boundary twice, unprompted:
   `crew_executor.py:199` ("READ THIS BEFORE ADDING A THIRD OUTER LOOP. **One already
   exists.**") and `config.py:7231` (`converge_for_session` "is a separate LIVE outer loop
   driven by an LLM judge on the finalizer path").

2. **The option offered on the issue would double-credit.** #1246 proposes "emit the
   resolution from the session path too." The session path is already the emitter. Adding a
   second write there credits the same verifier twice for one judgement, and the second
   write would bypass the outbox's idempotency (which keys on `outcome_id` derived from
   `evidence_sha256` + revision), so it would not even be deduplicated.

3. **`record_verification_outcome` cannot be reached from anywhere correct.** From the
   session path it double-credits; from the legacy path there is no resolution signal to
   give it. It is a seam with no callable position, and it has already caused harm — it is
   the reason a false claim ("`record_verification_outcome` is called from the convergence
   path") is sitting in shipped source today.

### Is this a decision or a patch?

It was **correctly routed as a decision** — the issue poses a real either/or and recommends
the option that turns out to be wrong. But once enumerated, it **resolves to a bounded
corrective change**, because the capability already exists. There is no new mechanism to
design. Build it as written.

### Correction to the issue's premise (carry this into the commit message)

#1246 states: *"BF-778 moved verifier trust attribution out of `verify()` … and into
`converge()`, which credits a refusal once a correction resolves it."*

**That is not what the code does.** `converge()` credits nothing. BF-778 *removed* the
`verify()` write and deliberately did **not** add one to `converge()`; the comment block at
`crew_verifier.py:1219-1232` records that an earlier revision tried exactly that and it was
rejected as farmable by a whitespace edit. The dormant thing is
`record_verification_outcome`, which `converge()` does not call.

---

## Corrected anchors

The issue's line numbers are ~11 days old. Three of five moved (all by −14).

| Anchor | Issue said | **Actual (verified 2026-08-27)** |
|---|---|---|
| `crew_orchestrator.py` → `verify()` | 1373 | **1373** — unchanged |
| `crew_finalizer.py` → `converge_for_session()` | 1329, 2106 | **1315, 2092** |
| `crew_finalizer.py` → `verify_for_session()` | 1558, 2292 | **1544, 2278** |
| `converge()` — tests only | (stated) | **confirmed** — `crew_verifier.py:1203`; callers only in `test_ad860_crew_verifier.py` and `test_bf777_bf778_verifier_trust.py` |
| `record_verification_outcome` | (stated dormant) | **confirmed** — `crew_verifier.py:1149`; zero production callers repo-wide |

Additional anchors this prompt uses:

| Symbol | Location |
|---|---|
| `class SubtaskVerifier` | `crew_verifier.py:1051` |
| `verify()` | `crew_verifier.py:1086` |
| `verify_for_session()` | `crew_verifier.py:1332` |
| `converge_for_session()` | `crew_verifier.py:1418` |
| `derive_completed_crew_trust_effects` | `crew_trust.py:206` (credit predicate at `:298`) |
| `CrewSessionTrustRecorder.drain_pending` | `crew_trust.py:511` |
| `_completed_trust_effects` | `crew_finalizer.py:686-709` |

**Stale citation found in passing (optional nit, Section 6):** `crew_executor.py:199` cites
`converge_for_session` as `crew_verifier.py:1301`. It is at **1418**.

---

## Implementation

### Section 1 — Delete the dead seam

`src/probos/cognitive/crew_verifier.py` — delete the entire method (currently `:1149-1200`).

SEARCH:
```python
    def record_verification_outcome(
        self,
        verifier_agent_id: str,
        producer_agent_id: str,
        *,
        refusal_was_upheld: bool,
    ) -> None:
        """Record a RESOLVED verification outcome against the verifier (BF-778).

        ``refusal_was_upheld`` is the judgement's correctness, NOT its
        direction: an upheld refusal and a sound acceptance are both successes.

        NOTE: nothing calls this yet, deliberately. ``verify()`` used to score
        the verifier with ``success=verdict.accepted``, which paid it to accept;
        that write is gone and its removal is the live half of BF-778. The
        replacement requires knowing whether a judgement was CORRECT, which
        needs real adjudication -- a grounded acceptance criterion or a
        downstream outcome. A text-diff proxy was tried and rejected: it is
        farmable by a whitespace edit and makes refusing weakly dominate
        accepting, which is BF-778 mirrored rather than fixed.

        This method is the seam that adjudication will call. BF-782 (#1246)
        owns designing it; BF-783 (#1247) owns the acceptance incentive AD-861
        still applies through ``crew_synth``.
        """
        if type(refusal_was_upheld) is not bool:
            # Validated BEFORE the empty-id no-op: TrustNetwork branches on
            # truthiness, so a string "false" would record a SUCCESS, and a
            # bypass here would make the guard depend on an unrelated argument.
            raise TypeError(
                "refusal_was_upheld must be a bool, got "
                f"{type(refusal_was_upheld).__name__}"
            )
        if not verifier_agent_id:
            return
        try:
            self._trust.record_outcome(
                verifier_agent_id,
                success=refusal_was_upheld,
                intent_type="crew_verification",
                verifier_id=producer_agent_id,
                source="crew_verification",
            )
        except RuntimeError as exc:
            if str(exc) != "trust_write_in_progress":
                raise
            logger.warning(
                "AD-1130: resolved verifier trust observation skipped for "
                "verifier=%s target=%s because a durable trust write is in "
                "progress; the resolved outcome is lost for this cycle",
                verifier_agent_id,
                producer_agent_id,
            )

    async def converge(
```

REPLACE:
```python
    async def converge(
```

**Do not** substitute a stub, a deprecation shim, or a `NotImplementedError`. A named seam
invites a caller; that is how this defect happened.

`self._trust` remains a constructor dependency — it is still injected and is part of the
class's declared collaborators. Leave the constructor untouched.

### Section 2 — Correct the module docstring

`src/probos/cognitive/crew_verifier.py:29-36`.

SEARCH:
```
BF-778: no path in this module writes verifier trust today. ``verify()`` used to
record each verdict against the :class:`TrustNetwork` at judgement time with
``success=verdict.accepted`` -- which paid a verifier to accept and penalised
every refusal, inverting the point of an adversarial layer. Whether a judgement
was CORRECT is not knowable when it is made, and no proxy available here
establishes it later, so the ledger stays neutral. ``record_verification_outcome``
is the seam a future adjudicator will call and is the only thing here that CAN
write; nothing calls it. See BF-782 (#1246) and BF-783 (#1247).
```

REPLACE:
```
BF-778: no path in this module writes verifier trust, and none should. ``verify()``
used to record each verdict against the :class:`TrustNetwork` at judgement time with
``success=verdict.accepted`` -- which paid a verifier to accept and penalised every
refusal, inverting the point of an adversarial layer. Whether a judgement was CORRECT
is not knowable when it is made; it becomes knowable only once a correction either
closes the gap the refusal named or fails to.

AD-1282 (BF-782, #1246): that resolution is observed and attributed OUTSIDE this
module, on the session path, because that is the only path that retains the round
history needed to see it. ``converge_for_session`` accumulates the rounds;
``crew_trust.derive_completed_crew_trust_effects`` credits a refusal that a later
round resolved; delivery is durable and idempotent through the crew trust outbox.
This module supplies the judgements and nothing else -- deliberately, so that a
verdict cannot be paid for at the moment it is made. See BF-783 (#1247) for the
remaining acceptance-incentive question.
```

### Section 3 — Correct the `verify()` comment (this one is false today)

`src/probos/cognitive/crew_verifier.py:1139-1147`.

SEARCH:
```python
        # BF-778: no trust write here. This used to record the VERIFIER with
        # success=verdict.accepted, which paid it to accept and penalised every
        # refusal -- exactly inverting what an adversarial layer is for. The
        # correctness of a judgement is not knowable at the moment it is made;
        # it becomes knowable when a correction either closes the gap the
        # refusal named or contradicts it. `record_verification_outcome` is
        # called from the convergence path once that resolves, and
        # `verify_for_session` has always had this shape.
        return verdict
```

REPLACE:
```python
        # BF-778: no trust write here. This used to record the VERIFIER with
        # success=verdict.accepted, which paid it to accept and penalised every
        # refusal -- exactly inverting what an adversarial layer is for. The
        # correctness of a judgement is not knowable at the moment it is made;
        # it becomes knowable when a correction either closes the gap the
        # refusal named or contradicts it. AD-1282: that resolution is attributed
        # on the session path, which is the only path that keeps the round
        # history -- `crew_trust.derive_completed_crew_trust_effects` credits a
        # refusal followed by a later round. `verify_for_session` has always had
        # this shape.
        return verdict
```

### Section 4 — Update the `converge()` rationale block

`src/probos/cognitive/crew_verifier.py` — inside `converge()`, in the `if verdict.accepted:`
branch of the loop (currently `:1228-1232`).

SEARCH:
```python
                # Judging correctness needs real adjudication (a grounded
                # acceptance criterion, or a downstream outcome), which does not
                # exist yet. BF-782 (#1246) owns designing it. Until then the
                # ledger stays neutral, which is the one position that cannot
                # teach the mesh the wrong lesson.
```

REPLACE:
```python
                # Judging correctness needs real adjudication. AD-1282 (BF-782,
                # #1246) resolved where that lives: the SESSION path, which keeps
                # the round history and attributes through the crew trust outbox.
                # This legacy path is single-shot by design and has no production
                # caller, so it stays neutral -- crediting here would be a second
                # write for a judgement the session path already pays.
```

### Section 5 — Correct the `crew_synth` note

`src/probos/cognitive/crew_synth.py:535-538`.

SEARCH:
```
        Verifier trust is therefore left NEUTRAL here, and no other live path
        moves it: `record_verification_outcome` has no production caller
        pending BF-782. This is a deliberate absence, not a delegation -- a
        verifier earns trust only in another role until that lands.
```

REPLACE:
```
        Verifier trust is therefore left NEUTRAL here. AD-1282 (BF-782): the live
        path that DOES move it is the crew session finalizer, which credits a
        refusal once a later round resolves it
        (`crew_trust.derive_completed_crew_trust_effects`). Synthesis is the wrong
        layer for that judgement and must not duplicate it -- a verifier earns
        trust here only in another role.
```

### Section 6 — Optional nit

`src/probos/cognitive/crew_executor.py:199` cites `converge_for_session` as
`crew_verifier.py:1301`; it is at **1418**. Fix the number only. Do not touch the
surrounding warning text.

---

## Tests

### Delete (they cover a method that no longer exists)

- `tests/test_bf777_bf778_verifier_trust.py:481-570` — the five
  `test_record_verification_outcome_*` tests.
- `tests/test_ad860_crew_verifier.py:199` and `:217` — both call the method. Read them
  first: `:186-201` asserts the busy-store swallow, `:204-219` asserts a non-busy trust
  error propagates. Both are *about the deleted method*, not about `verify()`, despite
  their names.
  - **Before deleting, confirm the equivalent handling exists on the live path** —
    `CrewSessionTrustRecorder.drain_pending` (`crew_trust.py:511+`) has its own
    exception policy and leaves the outbox row pending on failure. Verify this by
    reading it; if the equivalent coverage is missing there, say so and stop rather
    than dropping the assertions.

### Add — `tests/test_ad1282_verifier_credit_full_chain.py`

**1. The full chain (this is acceptance criterion 2 — it must cross every seam).**

`test_a_refusal_resolved_by_a_correction_credits_the_verifier_end_to_end`

Drive the **production entry point**, not the derive function:

1. Build a real `SubtaskVerifier` with a fake LLM scripted `refute → accept` and a fake
   agentic executor returning corrected text.
2. `await verifier.converge_for_session(...)` — the real entry point. Assert the outcome
   carries **two** rounds: `refuted` then `accepted`.
3. Take the child verification evidence **the way the finalizer takes it** — through
   `CrewSessionFinalizer._completed_trust_effects`, not by hand-building the payload.
   Read `crew_finalizer.py:686-709` and the `_ChildPublication.verification` construction
   to get the real shape.
4. Enqueue the effects, then `await CrewSessionTrustRecorder(...).drain_pending()`.
5. Assert on a **real `TrustNetwork`** that the verifier's `alpha` rose — the verifier was
   paid for the refusal that the correction resolved.

**The premise must be asserted before the conclusion.** Capture `alpha` before the drain
and assert it changed; a test that only reads the final value passes against a fixture
that was already at that value. Assert the effect's `role == "child_verifier"` and
`result_revision` points at the **refuted** round, not the accepted one — that is the
distinction the whole decision rests on, and an assertion that merely finds *a* credit
would pass even if the code credited the acceptance instead.

**2. Guard: the seam does not come back.**

`test_there_is_no_record_verification_outcome_seam`

```python
assert not hasattr(SubtaskVerifier, "record_verification_outcome")
```

Docstring must state *why*: reintroducing it would double-credit against the session
path's outbox write, and it silently rotted into a false comment the last time it existed.

**3. Negative control.**

`test_a_refusal_that_was_never_resolved_does_not_credit_the_verifier` — a single refuted
round with no later round produces **no** `child_verifier` success effect on the completed
path. Without this, test 1 passes against code that credits every verifier unconditionally.

### Run

```
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1282_verifier_credit_full_chain.py tests/test_bf777_bf778_verifier_trust.py tests/test_ad860_crew_verifier.py tests/test_ad1130_outcome_only_room_trust.py -q -p no:randomly
```

Then the full gate once the change is frozen:
```
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q
```

---

## What this does NOT change — do not build these

1. **Do not give `converge()` a production caller.** Deleting the dead seam does not mean
   activating the dead method. `converge()` stays test-only.
2. **Do not add a convergence/re-run loop to `crew_orchestrator`.** That changes admission
   on the legacy path — a behaviour change with its own risk surface that BF-778 scoped out
   and that `crew_executor.py:199` explicitly warns against.
3. **Do not emit a second resolution signal from the session path.** It already emits one.
   A second write double-credits and bypasses outbox idempotency.
4. **Do not touch the `verdict["status"] == "accepted"` half of the `correct_judgment`
   predicate** (`crew_trust.py:298`). Whether a plain acceptance should pay is the
   acceptance-incentive question, and it belongs to **BF-783 (#1247)**. It is adjacent,
   tempting, and out of scope. If you believe it is farmable, say so in the build report —
   do not change it here.
5. **Do not refactor the `derive_*` functions or the outbox.** They are correct.
6. **Do not remove `trust_network` from `SubtaskVerifier.__init__`.** Still injected, still
   part of the declared contract.
7. **Do not touch** `README.md`, `docs/architecture/federation.md`, or
   `docs/development/roadmap.md` — they carry another session's uncommitted edits.
8. **Do not run a mutation campaign.** Targeted only, per convention, and nothing here
   demands it.

---

## Tracking

- `PROGRESS.md` — CLOSED entry for BF-782 (#1246), one line: resolution attribution already
  lived on the session path; dead seam removed, false comments corrected, full-chain test added.
- `DECISIONS.md` — **AD-1282**: verification outcome attribution belongs to the crew session
  path, which is the only path retaining round history; the legacy orchestrator path is
  deliberately single-shot and terminal.
- `docs/development/roadmap.md` Bug Tracker — **skip this edit**; the file is dirty from
  another session. Note in the build report that the row is owed.

---

## Acceptance criteria

1. Either `converge()` has a production caller, or `record_verification_outcome` is called
   from whichever path actually observes a refusal resolving. — **Satisfied by
   enumeration:** the observing path is the session path, it already performs the write via
   `crew_trust`, and the redundant seam is removed. The prompt must show this, not assert it.
2. A test spans the FULL chain: production entry point → refusal → correction → acceptance →
   verifier credited. Half-chain evidence does not satisfy this.
3. The dormancy note in `record_verification_outcome`'s docstring is removed — by deleting
   the method — and the three other comments that assert a caller exists are corrected
   (Sections 2, 3, 4, 5).
4. `grep -rn "record_verification_outcome" src/ tests/` returns **only** the guard test.
5. No production behaviour changes. Trust writes before and after are identical; this
   removes unreachable code and corrects false documentation.
6. Verify all changes comply with the Engineering Principles in
   `.github/copilot-instructions.md`.
7. Run the `Diff Reviewer` subagent on the staged diff before committing, with a different
   model than the one that wrote the change. Point it at the claim that no production
   behaviour changed, and at the deleted tests.

---

## Verified against codebase (2026-08-27)

```
grep -n "class SubtaskVerifier|def verify|def converge|record_verification_outcome" src/probos/cognitive/crew_verifier.py
  1051: class SubtaskVerifier:
  1086:     async def verify(self, result: "SubtaskResult") -> VerificationVerdict:
  1149:     def record_verification_outcome(
  1203:     async def converge(
  1332:     async def verify_for_session(
  1418:     async def converge_for_session(

grep -n "converge_for_session|verify_for_session|_verifier.verify(" src/probos/cognitive/crew_finalizer.py src/probos/cognitive/crew_orchestrator.py
  crew_finalizer.py:1315:   outcome = await self._verifier.converge_for_session(
  crew_finalizer.py:2092:   outcome = await self._verifier.converge_for_session(
  crew_finalizer.py:1544:   verdict = await self._verifier.verify_for_session(
  crew_finalizer.py:2278:   final_verdict = await self._verifier.verify_for_session(
  crew_orchestrator.py:1373: verdict = await self._verifier.verify(result)

# ABSENCE VERIFIED — converge() has no production caller
rg -n '\.converge\(' src/            -> (no matches)
rg -n '\.converge\(' tests/          -> test_ad860_crew_verifier.py:293,309,332
                                        test_bf777_bf778_verifier_trust.py:219,235,264,306,338,356,397,443,460,473

# ABSENCE VERIFIED — record_verification_outcome has no production caller
rg -n 'record_verification_outcome' src/    -> (no matches)
rg -n 'record_verification_outcome' docs/ config/ prompts/  -> (no matches)
rg -n 'record_verification_outcome' tests/  -> test_ad860_crew_verifier.py:199,217
                                               test_bf777_bf778_verifier_trust.py:481-568

# The live credit for a resolved refusal
grep -n "correct_judgment" src/probos/cognitive/crew_trust.py
  298:  correct_judgment = verdict["status"] == "accepted" or (
  299:      verdict["status"] == "refuted" and index + 1 < len(child.rounds)
  301:  if not correct_judgment:

# The chain is wired
grep -n "derive_completed_crew_trust_effects|drain_pending" src/probos/cognitive/crew_finalizer.py
  23:   derive_completed_crew_trust_effects,
  664:  async def drain_pending_trust(
  697:  return derive_completed_crew_trust_effects(
  798, 829, 886, 1114, 3124, 3158:  await self.drain_pending_trust()
grep -n "CrewSessionTrustRecorder" src/probos/startup/finalize.py
  2075: trust_recorder = CrewSessionTrustRecorder(

# Existing coverage is derive-level only (half-chain) — hand-built round history
grep -n "child_verifier" tests/test_ad1130_outcome_only_room_trust.py
  837:  assert by_role.count(("child_verifier", True, 1)) == 1
  838:  assert by_role.count(("child_verifier", True, 2)) == 1
  # built from: history = (_round(0, status="refuted"), _round(1, status="accepted"))
  # i.e. never passes through converge_for_session — the seam this AD must cross

# The repo's own recorded boundary
grep -n "THIRD OUTER LOOP" src/probos/cognitive/crew_executor.py
  198: # READ THIS BEFORE ADDING A THIRD OUTER LOOP. **One already exists.**
grep -n "separate LIVE" src/probos/config.py
  7231: "SubtaskVerifier.converge_for_session, which is a separate LIVE "
```

**AD ceiling enumerated 2026-08-27:** `git log --all --format='%s'` → **1281**;
`prompts/*` filenames → **1281**; GitHub issue titles (all states, 1330 issues) → 1276.
Ceiling **AD-1281** from git log + prompts. This is **AD-1282**.

**BF ceiling:** git log → 859; GitHub (all states) → 859; working tree → **BF-860**
(`tests/test_bf860_consensus_floor.py` staged, uncommitted). Next free BF is 861 — **not
used**; this closes the existing BF-782 (#1246) under an AD number, matching the
`ad-NNNN-bf-NNN-*.md` convention.
