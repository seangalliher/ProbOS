# AD-1285 / BF-687 (#1087): a turn that claims a save must be able to prove one

**Status:** Rev 2 — ready to build. Rev 1 was implemented and is **staged,
uncommitted**. Do not commit the staged tree as-is; apply the deltas below.
**Dependencies:** none (AD-911/912, AD-797, AD-934, AD-1248 already landed)
**Estimated tests:** ~19 (rev 1 wrote 537 lines; roughly a third is deleted)
**Issue:** https://github.com/seangalliher/ProbOS/issues/1087 — **partially**
closed by this AD. See *What remains open* below.
**Drafted against:** HEAD `31cdc691` + the staged rev-1 tree
**AD ceiling at revision time:** **AD-1290** (see *AD numbering* below)

---

## Revision note — the two review findings, answered

Rev 1 shipped two verdict branches. Review found a defect in each. One finding
holds and one does not, and both answers changed the design.

### Finding 2 — HOLDS. Branch 2 is deleted.

`config/system.yaml:631` sets `publish_finding_enabled: true` and
`config/system.yaml:460` sets `dm_agentic.enabled: true`. On the live vessel a
1:1 DM turn therefore runs the AD-1065 tool loop, and `publish_finding` — which
calls `records_store.write_notebook` (`tools/publish_finding_tool.py:715`) — is
callable inside it. `publish_finding` is a **tool**, not a `[NOTEBOOK]` marker,
so it never touches the ledger. A genuine, successful publish would reach
`step_4m` as `consulted=∅ wrote=∅`, and rev-1's Branch 2 would have appended
*"treat the save described above as unconfirmed"* to a **truthful** reply.

That violates the issue's own acceptance criterion and is worse than the defect
it was built for, because it teaches the Captain to discount the warning.

The pipeline also cannot learn that the loop ran. Every candidate signal was
checked and each fails:

| Candidate | Why it does not discriminate |
|---|---|
| `ctx.params` | carries `dm_turn_id` / `thread_id` / `session_id`; no intent, no loop flag |
| `DmReply.tool_failures` | `ToolFailures.merge_open` defaults `False` (`dm_reply.py:235`) and `from_intent_result` rebuilds from wire, which is merge-closed. False whether or not a loop ran. |
| `result.metadata["tool_trace_ref"]` | AD-1203. Present ⇒ loop ran, but **absent ⇏ loop did not run** — it is `""` whenever no `AttachmentStore` is wired. Wrong polarity for a safety gate. |
| Recomputing the gate in `routers/agents.py` | `_conversational_agentic_will_run` (`cognitive_agent.py:4179`) documents itself as the *single source of truth* for "is the loop active for this turn?". A second copy in the router is drift waiting to happen. |
| Gating Branch 2 on `dm_agentic.enabled is False` | Sound, and **inert**: the live ship sets it `true`, so Branch 2 would abstain on every real turn. A branch that never runs is not a control (`dm_reply.py:288`). |

None of these is acceptable, so **Branch 2 is removed entirely** — with it
`CLAIM_WITHOUT_WRITE`, `_asserts_completed_save`, all three regexes,
`_CLAIM_SCAN_MAX_CHARS`, `turn_observed`, and `observed()`.

The module now reads **no reply text at all**. That is not a retreat; it is the
issue's stated criterion — *"Detection is structural (invocation record), not
string-matching the reply"* — met exactly, and it deletes the entire
false-positive class in one move.

### Finding 1 — DOES NOT HOLD. `step_4m` stays where it is.

Finding 1 argued that `step_4m` is unreachable from the path that produced
#1087, because the defect turn was `intent=proactive_think` and a proactive turn
never enters `_full_steps()`. The second half of that is true. The first half is
false, and **rev 1 is the source of the error** — it asserted that the issue's
quoted log line described the defect turn.

The issue quotes:

```
22:40:09 INFO probos.cognitive.cognitive_agent
  AD-643a: Agent surgeon intended_actions=['oracle_query'] (intent=proactive_think)
```

That is a **different agent**. From the live vessel's `identity.db`:

```
counselor -> callsign "Ezri"
surgeon   -> callsign "Meridian"
```

The issue's narrative names Ezri: *"2026-07-26 22:40, live, **in a 1:1 DM**. The
Captain asked Ezri to write a finding and publish it."* The quoted line is
Meridian's concurrent proactive turn, offered to show *where AD-643a runs* — one
line above in the **log**, not in the same turn. Rev 1 read it as the defect
turn's own line and built an inference on it; the review inherited that premise.

The defect turn was then located directly in the live store:

```
chat_threads.db / chat_thread_messages
  id         b4a3461fb2114475bfed7197d6c09b79
  thread_id  e879c64b78d24d6382e28555c9fec943   title "Hello Ezri"
             participants ["counselor_counselor_0_67c601cb"]   <- 1:1
  author_id  counselor_counselor_0_67c601cb     <- Ezri
  role       'agent'
  metadata   {"intent_id":"6f269465c00f45ac8acb0ceff2b86a4a"}
  created_at 1785127235.96  ->  local 2026-07-26 22:40:35
  body       "...So here's the honest report: I wrote the finding and it's
              saved to my notebook under the slug `ward-room-escalation-decision`..."
```

A `role='agent'` row on a chat thread carrying `metadata.intent_id` has exactly
one producer: `routers/agents.py:3472`, which appends
`_build_reply_metadata(intent.id, ...)` **immediately after**
`await pipeline.run()` on the pipeline built at `routers/agents.py:3425`. That
is `_full_steps()`.

**The defect turn is on Path A. `step_4m` is on the path that produced #1087.**
No relocation is required, and none is made.

Rev 1's related claim that "AD-643b never ran on the observed turn" rested on
the same conflation and is **withdrawn** — it is unproven either way. The
substantive point survives untouched and does not depend on it: AD-643b reports
*marker present, intent undeclared*; this defect is *claim present, marker
absent, call absent*. Different axis.

### What the proactive path is, since it was asked for

Enumerated for the record, and then **left alone**:

- Sink: `proactive.py:1368` `await self._post_to_ward_room(agent, response_text)`.
- Channels: `_extract_and_execute_actions` (`proactive.py:2868`) dispatches six —
  endorse, reply, DM, group chat, artifact, status — and returns
  `(cleaned_text, actions_executed)`. `proactive.py:1340` binds that list as
  `actions_taken` and **never reads it again** — the same discard that motivated
  this AD on the DM side.
- `extract_and_execute_notebooks` is **not** among those six. Its only
  production caller anywhere is `reply_pipeline.py:945`.
- No tool loop reaches a proactive turn: `_conversational_agentic_will_run`
  requires `intent == "direct_message"`, and the only other
  `WorkItemAgenticExecutor` entry on an agent is `_run_agentic_dispatch`, whose
  sole caller is `_handle_work_item_dispatch` (`cognitive_agent.py:2014`).

So the proactive path is the one place where the write-channel set is **closed**
and a claim-versus-ledger verdict would be sound. It is still **out of scope**:
it is not the path that produced #1087, `proactive.py` is a second file and a
second sink, and the ward-room post is itself a durable write that the guard
would run *before*. Record it as a forward marker; do not build it here.

---

## Problem

2026-07-26 22:40, live, in a 1:1 DM, Ezri replied *"I wrote the finding and it's
saved to my notebook under the slug `ward-room-escalation-decision`"*. No such
entry exists — verified below. `publish_finding` never appears in the log. She
then reasoned forward from the false premise for several turns.

The turn was **healthy** — no BF-612 empty content, no BF-674 cooldown, no
tier-unavailable in the 22:35–22:45 window. A working turn produced a specific,
plausible, entirely fictional slug.

The read side is guarded (AD-1119/1120 `referent_gate.py`, AD-1121
`confab_probe.py`). **Nothing guards the write side.**

### The adjacent defect this AD actually closes

`step_4i_notebook_parse` (`reply_pipeline.py:918`) calls
`extract_and_execute_notebooks`, receives `(cleaned, actions)`, logs
`len(actions)` and discards it. Its trailing safety net then **unwraps** any
surviving `[NOTEBOOK …]` block (`reply_pipeline.py:1004`), keeping the inner
text and dropping the markers.

So when the write does not happen, the Captain sees the note's content inline,
followed by whatever the agent said about saving it — a reply
**indistinguishable from a successful one**. The agent is instructed at
`cognitive_agent.py:2960-2961` to "confirm conversationally that you have saved
it", so a success claim is the expected shape.

`extract_and_execute_notebooks` returns `actions=[]` on four reachable paths:
records store unwired (`proactive.py:4093`), empty block body (`:4102`), the
write raising (`:4185`), and a marker `_NOTEBOOK_PATTERN` does not match.

This is measured, not hypothetical. Two agent replies in the Captain's own
transcript carry an **unexecuted** `[NOTEBOOK]` block and an explicit
completed-save claim, and neither entry exists in the store:

| When | Agent | Reply says | Slug in `ship-records/notebooks/` |
|---|---|---|---|
| 2026-06-07 01:12:57 | yeoman | "Done — that's saved to my notebook under `spacex-ipo-trade-setup`." | **absent** |
| 2026-06-07 12:25:53 | counselor | "I've got it filed." | **absent** |

Both are dated the day AD-911/912 landed, so they may predate `step_4i` on that
vessel; they are cited as evidence of the **shape**, not of current-code
frequency. The four `actions=[]` paths above are the current-code proof.

### Do not fix this with prompt text

AD-1157 settled what guidance without a mechanism is worth: crew were told to
classify notebooks for months while the tag had no syntax to carry the choice,
and 2,453/2,453 entries took the default. The prose at
`cognitive_agent.py:2960-2961` and `:3009` is already correct and already
unenforced. **Do not edit it.**

---

## Solution

A per-turn **write ledger**: which durable-write channels ran this turn, and
which of them actually produced a write. One verdict, decided entirely from that
record.

**`MARKER_WROTE_NOTHING` — a write channel ran and produced nothing.** A write
marker was present, its channel executed, and it wrote zero entries. The marker
is then stripped or unwrapped, so the reply is a success claim by construction.
The check is `consulted - wrote`, **per channel**, so a turn that wrote an
artifact cannot mask a notebook channel that wrote nothing.

**Intervention: correct and mark. Never block.** Design Principle #13(c) — a
refusal that ends the work is a capability ceiling in a governance costume. The
reply keeps its substance and gains one honest sentence; the turn is logged with
a stable marker.

**Abstain by default.** No verdict when no channel ran (`evaluated` False) and
none when every channel that ran also wrote. A turn with no write marker is
byte-identical.

**No reply text is read, anywhere in this AD.** `assess_write_claim` does not
take the reply as a parameter. That is the property to preserve under later
refactoring, and there is a test that asserts the signature.

---

## Scope

**Starting point: the staged rev-1 tree.** Do not `git reset` it; apply the
deltas below on top and re-stage.

| File | Change |
|---|---|
| `src/probos/cognitive/dm/write_ledger.py` | **§1** — delete the Branch-2 half; per-channel Branch 1 |
| `src/probos/cognitive/dm/reply_pipeline.py` | **§2** — drop the `observed()` call, log the pending set |
| `src/probos/cognitive/dm/__init__.py` | unchanged from staged |
| `src/probos/config.py` | **§3** — add `Field(description=...)` |
| `docs/development/config-reference.md` | regenerate after §3 |
| `tests/test_ad1285_write_claim_guard.py` | **§4** — rewrite |
| `tests/test_ad811a_a2ui_choice.py`, `tests/test_ad934_deliberate.py` | unchanged from staged |

The module stays at `cognitive/dm/write_ledger.py`. Rev 1's placement was right:
only the DM pipeline consumes it, so it does not move up a level.

**Files you must NOT change — hard stop if you think you need one:**
`cognitive_agent.py` (foreign-modified **and** off-limits by Captain's
instruction), `agentic_dispatch.py`, `continue_or_ask.py`,
`repair_verification.py`, `fault_report.py`, `tools/browser/url_route_guard.py`,
`proactive.py`, `routers/agents.py`, `README.md`,
`docs/architecture/federation.md`, `docs/development/roadmap.md`.

---

## Implementation

### §1 — `src/probos/cognitive/dm/write_ledger.py`

**Delete:**

- the `turn_observed` field and the `observed()` method;
- `ClaimVerdict.CLAIM_WITHOUT_WRITE`;
- `_asserts_completed_save`, `_COMPLETED_SAVE_RE`,
  `_NEGATED_OR_HYPOTHETICAL_RE`, `_CLAUSE_SPLIT_RE`, `_CLAIM_SCAN_MAX_CHARS`;
- the now-unused `import re`, the `CLAIM_WITHOUT_WRITE` entry in
  `_DISCLOSURES`, and both dropped names from `__all__`.

**Change:**

```python
    @property
    def evaluated(self) -> bool:
        """Whether any durable-write channel ran on this turn."""
        return bool(self.consulted)

    def consulted_with(self, channel: str, *, wrote: bool) -> "WriteLedger":
        """Record that ``channel`` ran, and whether it wrote."""
        return WriteLedger(
            consulted=self.consulted | {channel},
            wrote=(self.wrote | {channel}) if wrote else self.wrote,
        )

    @property
    def wrote_nothing(self) -> frozenset[str]:
        """Channels that ran and produced no write.

        Per channel, deliberately. A turn that persisted an artifact and ran a
        notebook channel that wrote nothing still confabulates the notebook,
        and a ledger-wide ``if self.wrote`` would mask it.
        """
        return self.consulted - self.wrote
```

```python
def assess_write_claim(ledger: WriteLedger) -> ClaimVerdict:
    """Compare what this turn ran against what it wrote.

    Takes no reply text. The verdict is entirely structural, which is the
    #1087 criterion -- "detection is structural (invocation record), not
    string-matching the reply" -- and is what makes a false positive against a
    truthful reply unreachable rather than merely unlikely.

    Abstains when no channel ran, so a turn with no write marker is
    byte-identical.
    """
    if not ledger.evaluated:
        return ClaimVerdict.ABSTAIN
    if ledger.wrote_nothing:
        return ClaimVerdict.MARKER_WROTE_NOTHING
    return ClaimVerdict.ABSTAIN
```

**Rewrite the module docstring's second paragraph.** It currently explains the
`evaluated` distinction in terms of a Branch 2 that no longer exists. Replace it
with the fact that still holds, plus the constraint that produced this revision:

> An unpopulated ledger abstains. "No channel ran" and "a channel ran and wrote
> nothing" are deliberately different values, for the AD-1269 reason — a verdict
> of *nothing happened* must never be reachable from a field nobody set.
>
> This ledger sees the **marker** channels only. The AD-1065 tool loop runs
> upstream of the pipeline and writes without telling it, so a `wrote` set that
> is empty means "no marker channel wrote", never "this turn wrote nothing". No
> verdict here may assume otherwise. Closing that half needs a name-addressable
> tool-success set carried out of `WorkItemAgenticOutcome`; see #1087.

**Change the `MARKER_WROTE_NOTHING` disclosure** so it is true even when the
reply made no prose claim — the verdict does not read the text, so it cannot
know one was made:

```python
    ClaimVerdict.MARKER_WROTE_NOTHING: (
        "\n\n[A durable write was attempted on this turn and did not "
        "complete — nothing was saved.]"
    ),
```

Verify it against `_CAPABILITY_GAP_RE` (`decomposer.py:50`) in a test, as rev 1
does. The regex's `no` branch requires
`no (built-in |native )?(capability|ability|support|way|mechanism|tool)`, so
`nothing was saved` does not match; its `not` branch requires
`not (available|supported|possible)`, so `did not complete` does not match.

### §2 — `step_4m_write_claim_guard`

Keep the method, its placement, its config gate, its Tier-2 `except`, and the
empty-`response_text` early return. Three edits:

1. **Delete** the `self.ctx.write_ledger = self.ctx.write_ledger.observed()`
   line and its comment.
2. `verdict = assess_write_claim(self.ctx.write_ledger)` — one argument.
3. Log the pending set, which is the actionable fact:

```python
            logger.warning(
                "AD-1285: write-claim guard verdict=%s agent=%s thread=%s "
                "ran_without_writing=%s wrote=%s",
                verdict.value,
                self.ctx.agent_id,
                self.ctx.chat_thread_id,
                sorted(self.ctx.write_ledger.wrote_nothing),
                sorted(self.ctx.write_ledger.wrote),
            )
```

Update the method docstring: it says it "compares the reply against
`WriteLedger`". It compares **the ledger against itself**; the reply is only the
surface the disclosure is appended to.

**Keep the two `consulted_with` calls in `step_4i` exactly as staged**, including
the rule that the channel is **not** marked when `proactive_loop` is absent or
lacks the method. That is a genuinely different fact — no channel exists — and
conflating it with "a channel ran and wrote nothing" is the error the module's
own docstring warns about. It is also what keeps every `SimpleNamespace()`
runtime in the suite byte-identical. Record the residual instead: on a ship where
the notebook capability is advertised in the prompt but `proactive_loop` is
unwired, every marker is a phantom save and nothing flags it. That is a
deployment defect and belongs to a startup check, not a per-reply disclosure.

**Keep the artifact channel exactly as staged** — `wrote=True` only, never
`wrote=False`, with the builder's inline rationale. Under `consulted - wrote` the
artifact channel can therefore never appear in `wrote_nothing`, which is the
intended result: `extract_artifacts` lifts unmarked fenced blocks the agent never
claimed to save, so a `wrote=False` there would flag a reply that described no
save at all.

### §3 — config

`WriteClaimGuardConfig.enabled` currently has no `Field`, so the generated
`config-reference.md` row has an empty Description cell. Give it one:

```python
    enabled: bool = Field(
        default=True,
        description=(
            "AD-1285 (#1087): check a 1:1 reply against the turn's write "
            "ledger and append one honest sentence when a durable-write "
            "channel ran and wrote nothing. Reads no reply text. Default ON "
            "because this is a safety control rather than a capability, and a "
            "default-OFF control defends nothing (#13(a)) -- which is the "
            "AD-1157 failure mode #1087 names. Safe on: the verdict abstains "
            "unless a channel actually ran, so a turn with no write marker is "
            "byte-identical."
        ),
    )
```

Regenerate `docs/development/config-reference.md` and confirm the row is filled.

### §4 — tests

Rewrite `tests/test_ad1285_write_claim_guard.py`. Delete the Branch-2 negative
corpus, the Branch-2 positive cases, and every `observed()` / `turn_observed`
assertion. Keep `_Fake*` stubs and real `WriteLedger` values — **no
`MagicMock(spec=...)`** for the pipeline or the ledger (AD-1284: a spec'd double
auto-mocks any new public name, so an assertion passes for the wrong reason).

**Ledger value (6)**

1. `WriteLedger()` → `evaluated is False`, both sets empty, `wrote_nothing`
   empty.
2. `consulted_with("notebook", wrote=True)` → in both sets; `wrote_nothing`
   empty.
3. `consulted_with("notebook", wrote=False)` → `consulted` only;
   `wrote_nothing == {"notebook"}`.
4. Copy-on-write: the original value is unchanged after `consulted_with`.
5. Two channels accumulate independently.
6. Idempotence: `consulted_with("notebook", wrote=False)` twice leaves both set
   sizes unchanged.

**Verdict (5)**

7. Unpopulated ledger → `ABSTAIN`. *The false-positive floor; name it in the
   test docstring.*
8. `consulted={"notebook"} wrote={"notebook"}` → `ABSTAIN`. **A genuinely
   successful write is never flagged** — the acceptance criterion, asserted
   directly.
9. `consulted={"notebook"} wrote=∅` → `MARKER_WROTE_NOTHING`.
10. **Masking regression:** `consulted={"notebook","artifact"}
    wrote={"artifact"}` → `MARKER_WROTE_NOTHING`, and
    `wrote_nothing == {"notebook"}`. A ledger-wide `if self.wrote` returns
    `ABSTAIN` here; this test is what forbids that shape.
11. **Signature guard:** `inspect.signature(assess_write_claim)` has exactly one
    parameter, named `ledger`. Assert it, with a docstring saying the verdict
    must never become text-dependent. This is the property the whole revision
    turns on.

**Disclosure (3)**

12. `disclosure_for(MARKER_WROTE_NOTHING)` asserted against the real compiled
    `decomposer._CAPABILITY_GAP_RE` —
    `assert not _CAPABILITY_GAP_RE.search(text)`. Import it; do not restate it.
13. `disclosure_for(ABSTAIN) == ""`.
14. The disclosure is non-empty and starts with a blank-line separator.

**Pipeline integration (4)** — the seam, not the halves

15. End-to-end: a `DmReplyContext` whose fake proactive loop returns
    `(cleaned, [])` for a reply containing `[NOTEBOOK slug]…[/NOTEBOOK]`; run the
    **full pipeline**; assert the final `ctx.response_text` carries the
    disclosure and no longer carries the marker. This is the one test that
    crosses 4i → ledger → 4m.
16. Same fixture, fake returns one action → **no** disclosure, body otherwise
    unchanged.
17. Runtime with **no** `proactive_loop`, reply containing a marker → **no**
    disclosure (the unwired ship stays byte-identical), and the safety net still
    unwrapped the marker.
18. `config.write_claim_guard.enabled = False` → byte-identical output.

**Ordering (1)**

19. `step_4m_write_claim_guard` is in `_full_steps()` strictly after
    `step_4j_deliberate_parse` and strictly before `step_5_episodic_store`, and
    **absent** from `_escalation_steps()`.

---

## What this does NOT change

- `publish_finding` — verified working 23:46 the same night. Untouched.
- BF-612 / BF-674 empty-response behaviour — #1086.
- Read-side confabulation — AD-1119/1120/1121. Untouched.
- AD-643a / AD-643b — different axis, and both in an off-limits file.
- The `[NOTEBOOK]` / artifact protocol prose — the point is to enforce it.
- The proactive ward-room path — enumerated above, forward marker only.
- The group fan-out path — forward marker already in the staged
  `_escalation_steps` docstring.
- `routers/agents.py` — rev 1 needed nothing there and rev 2 needs less.

## What remains open on #1087 — **the issue does not close**

This AD closes the *marker* half: a `[NOTEBOOK]` write that ran and failed can no
longer reach the Captain looking like a success. It does **not** close the
observed 22:40 turn, which carried no marker at all — `consulted` is empty there,
so the guard abstains by design.

Closing the observed turn requires knowing which **tools** succeeded, and that
record does not exist:

- `AgenticResult` (`swe_harness/agentic_loop.py:763`) holds `tool_calls` +
  `tool_results`, correlated by `ToolCallResult.id`.
- `WorkItemAgenticOutcome` (`agentic_dispatch.py:1486`) carries **neither** —
  stated in-repo at `cognitive_agent.py:120`: *"…which carries neither
  `tool_calls` nor `tool_results` — so (BF-793) it never ran at all."*
- The three survivors cannot name a success. `tool_failures` stores `""` as a
  success tombstone and `to_wire()` drops tombstones (`dm_reply.py:400`);
  `tool_trace_ref` is `None` on an unwired store; `tool_defect` is a verdict, not
  an inventory.
- The only carrier from the loop onto `IntentResult.metadata` is
  `_build_result_metadata` at **`cognitive_agent.py:193`**.

So the remaining work needs `agentic_dispatch.py:2343` — produce a
name-addressable success set beside `tool_failures` and `tool_defect`, following
the AD-1248 / AD-1257 / AD-1269 precedent written inline there — **and**
`cognitive_agent.py:193` to carry it. Both files are foreign-modified; the second
is off-limits by instruction. It cannot be built in this wave.

The ledger is keyed by **channel name** precisely so that work adds a key rather
than reshaping the value. `WriteLedger` is the half that can be built now.

**Report this to the Captain as a partial closure and let them file the
remainder. Do not close #1087.**

---

## Tracking

- `PROGRESS.md` — AD-1285 entry, stating partial closure of #1087.
- `docs/development/roadmap.md` Bug Tracker — **do not edit** (off-limits this
  wave). Note the pending row in your build report instead.
- `DECISIONS.md` — not required.

---

## Acceptance criteria

- [ ] A turn whose write channel ran and wrote nothing is detected **without
      reading the reply at all** — enforced by `assess_write_claim` taking no
      text parameter, asserted by test 11.
- [ ] A genuinely successful write is never flagged — asserted directly (test 8).
- [ ] A channel that wrote nothing is not masked by a sibling channel that did
      (test 10).
- [ ] A ledger no channel populated abstains (test 7).
- [ ] A turn carrying no write marker is byte-identical, including on a runtime
      with no `proactive_loop` (test 17).
- [ ] The turn is logged with a stable, greppable marker naming the channels that
      ran without writing. The reply body is never logged.
- [ ] The reply is never blocked, refused, or substantively rewritten.
- [ ] An agent accurately reporting a real failure is unaffected — the guard
      reads the ledger only and never penalises.
- [ ] Disclosure text does not match `_CAPABILITY_GAP_RE`.
- [ ] `_full_steps` docstring says 21 and the BF-796 guard passes unmodified.
- [ ] `ClaimVerdict` has exactly two members and `write_ledger.py` imports no
      `re`.
- [ ] No change to `cognitive_agent.py`, `agentic_dispatch.py`,
      `continue_or_ask.py`, `repair_verification.py`, `fault_report.py`,
      `tools/browser/url_route_guard.py`, `proactive.py`, `routers/agents.py`,
      `README.md`, `docs/architecture/federation.md`,
      `docs/development/roadmap.md`.
- [ ] The build report states plainly that #1087 is **partially** closed and
      names what remains.
- [ ] Verify all changes comply with the Engineering Principles in
      `.github/copilot-instructions.md`.

---

## Gating

The working tree carries unrelated uncommitted work that removes
`RedirectEscalation` while `browser/session.py` still imports it — roughly 423
tests fail for that reason alone. **Do not stash it.** Gate in a linked worktree:

```
git worktree add <wt> 31cdc691
git apply <staged patch>          # your own changes only
$env:PYTHONPATH = "<wt>/src"      # shadow the editable install
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q
```

Known artefact: three `test_phantom_api_precheck_*` tests fail in a linked
worktree and pass in the main one — they shell out to repo-relative scripts.
Verify, then count them as passes.

Focused gate:

```
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1285_write_claim_guard.py \
  tests/test_ad1248_slice_b.py tests/test_ad934_deliberate.py \
  tests/test_ad811a_a2ui_choice.py tests/test_ad811c_group_a2ui.py \
  tests/test_ad911_yeoman_notebook.py tests/test_ad912_crew_notebook_generalization.py \
  tests/test_ad550_notebook_dedup.py tests/test_ad1157_notebook_classification.py \
  tests/test_ad724_dm_hardening.py tests/test_ad933_group_chat_escalation.py \
  tests/test_bf296_dm_outbound_in_reply.py -q -p no:randomly
```

`test_ad911_*`, `test_ad912_*`, `test_ad550_*`, `test_ad1157_*` and
`test_ad724_*` are in the focused gate because they push `[NOTEBOOK` text through
this exact step — they are the blast radius of any change to the consulted rule.

Run the adversarial `Diff Reviewer` on the staged diff before committing, with a
different model than the one that wrote the code. Tell it: **the verdict is
structural and no reply text is read anywhere** — a finding that the guard can be
reached by text is a Critical; the consumer that must accept the change is
`DmReplyPipeline.run()`; the highest-risk property is that a genuine save is
never flagged; and the AD-1065 tool loop writes outside this ledger, so any
reasoning that treats an empty `wrote` set as "this turn wrote nothing" is wrong.

---

## AD numbering

Rev 1 enumerated `git log --all --format='%s'` and `prompts/ad-*.md` and reported
ceiling AD-1284. It **did not enumerate GitHub issue titles**, which is the third
required source and the only place an allocated-but-unbuilt AD lives. Epic #1332
had allocated AD-1284..1288 fifty-five minutes earlier. The Captain resolved it
by renumbering the unbuilt epic — the shipped side keeps its numbers because
`DECISIONS.md` is append-only — so **AD-1284 and AD-1285 stand**.

Re-enumerated at revision time, all three sources:

```
git log --all --format='%s' | grep -o 'AD-1[0-9]\{3\}' | sort -u | tail
  ... AD-1283  AD-1284  AD-1285
ls prompts/ad-1*.md | tail -1
  ad-1285-bf-687-a-turn-that-claims-a-save-must-prove-one.md
GitHub issue titles (all states, newest first)
  #1337 AD-1290: Elastic Scatter/Gather and Team Trials     <- ceiling
  #1336 AD-1289: Typed Mission Blackboard
  #1335 AD-1288: Agent-Commissioned Team Lifecycle
  #1334 AD-1287: Evidence-Bound Skill Qualification
  #1333 AD-1286: Elastic Team Contract
```

**Ceiling AD-1290; next free AD-1291.** This document is a revision of AD-1285,
not a new allocation — same issue, same scope, already built.

---

## Verified Against Codebase (2026-08-29, HEAD `31cdc691` + staged tree)

```
config/system.yaml:460                 enabled: true            # dm_agentic
config/system.yaml:631                 publish_finding_enabled: true
src/probos/config.py:6657              publish_finding_enabled: bool = False  # AD-1140 default
src/probos/startup/communication.py:705  enabled=config.agentic_tools.publish_finding_enabled
src/probos/tools/publish_finding_tool.py:715  path = await self._records.write_notebook(

src/probos/cognitive/cognitive_agent.py:4179  _conversational_agentic_will_run
src/probos/cognitive/cognitive_agent.py:4195    if observation.get("intent") != "direct_message": return False
src/probos/cognitive/cognitive_agent.py:2014  reply_text = await self._run_agentic_dispatch(   # only caller
src/probos/cognitive/cognitive_agent.py:1944  async def _handle_work_item_dispatch(...)        # its enclosing intent
src/probos/cognitive/cognitive_agent.py:120   "carries neither ``tool_calls`` nor ``tool_results`` -- BF-793"
src/probos/cognitive/cognitive_agent.py:193   def _build_result_metadata(...)                  # only metadata carrier
src/probos/cognitive/cognitive_agent.py:220     metadata["tool_trace_ref"] = source["_tool_trace_ref"]
src/probos/cognitive/cognitive_agent.py:2960-2961  "never say you saved something without it"
src/probos/cognitive/agentic_dispatch.py:1486 class WorkItemAgenticOutcome
src/probos/cognitive/agentic_dispatch.py:2347   tool_trace_ref=tool_trace_ref,   # production site
src/probos/dm_reply.py:235             merge_open default False
src/probos/dm_reply.py:400             "Success tombstones are dropped here."   (to_wire)

src/probos/routers/agents.py:3425      pipeline = DmReplyPipeline(DmReplyContext(
src/probos/routers/agents.py:3443      await pipeline.run()
src/probos/routers/agents.py:3466      _reply_meta = _build_reply_metadata(intent.id, result, response)
src/probos/routers/agents.py:3472      _thread_store.append_message(... role="agent", metadata=_reply_meta)
src/probos/routers/agents.py:2624      def _build_reply_metadata(...) -> meta = {"intent_id": intent_id}
src/probos/routers/thread_fanout.py:675  second (group) construction site
src/probos/routers/thread_fanout.py:695  await pipeline.run_escalation_only()

src/probos/cognitive/dm/reply_pipeline.py:173   await self._run_steps(self._full_steps())
src/probos/cognitive/dm/reply_pipeline.py:918   step_4i docstring
src/probos/cognitive/dm/reply_pipeline.py:937     if "[NOTEBOOK" not in ...: return   # fast path
src/probos/cognitive/dm/reply_pipeline.py:945     cleaned, actions = await proactive.extract_and_execute_notebooks(
src/probos/cognitive/dm/reply_pipeline.py:1004    safety net: re.sub(...) UNWRAPS, keeping inner text
src/probos/cognitive/dm/reply_pipeline.py:1295    step_4f artifact record (staged)
src/probos/cognitive/dm/reply_pipeline.py:1696    step_4m_write_claim_guard (staged)

src/probos/proactive.py:1340   cleaned_text, actions_taken = await self._extract_and_execute_actions(
src/probos/proactive.py:1368   await self._post_to_ward_room(agent, response_text)   # proactive sink
src/probos/proactive.py:2868   async def _extract_and_execute_actions(...)           # six channels
src/probos/proactive.py:4070   async def extract_and_execute_notebooks(...)
src/probos/proactive.py:4093     if records_store is None: return text, actions
src/probos/proactive.py:4102     if not notebook_content: continue
src/probos/proactive.py:4185     except Exception: ... (no action appended)

src/probos/cognitive/decomposer.py:50  _CAPABILITY_GAP_RE = re.compile(
tests/test_ad1248_slice_b.py:483-487   docstring count guard -> 21
```

**Live-vessel evidence** (`%LOCALAPPDATA%\ProbOS\data`, resolved from the running
process, *not* `d:\ProbOS\data`):

```
identity.db.birth_certificates
  ('counselor', 'Ezri')      ('surgeon', 'Meridian')
  -> the issue's quoted 22:40:09 "Agent surgeon ... proactive_think" line is a
     DIFFERENT agent from the Ezri turn the issue narrates.

chat_threads.db.chat_thread_messages
  id=b4a3461f... thread=e879c64b... ("Hello Ezri", participants=[counselor] -> 1:1)
  author=counselor_counselor_0_67c601cb  role='agent'
  metadata={"intent_id":"6f269465..."}   created_at -> local 2026-07-26 22:40:35
  body contains "...saved to my notebook under the slug `ward-room-escalation-decision`"
  -> role='agent' + metadata.intent_id is produced only at routers/agents.py:3472,
     immediately after pipeline.run(). Path A. _full_steps() DOES run on this turn.
```

**Absence verified**

```
CLAIM: only two sites construct DmReplyPipeline
RUN:   Select-String -Path src\**\*.py -Pattern 'DmReplyPipeline\('
FOUND: routers/agents.py:3425, routers/thread_fanout.py:675
HOLDS: yes

CLAIM: extract_and_execute_notebooks has exactly one production caller
RUN:   Select-String -Path src\**\*.py -Pattern 'extract_and_execute_notebooks'
FOUND: proactive.py:4070 (def), reply_pipeline.py:945 (call), plus 2 docstrings
HOLDS: yes -- the proactive path never calls it

CLAIM: proactive.py:1340 binds actions_taken and never reads it
RUN:   Select-String -Path src\probos\proactive.py -Pattern 'actions_taken'
FOUND: 1340 only
HOLDS: yes

CLAIM: no tool loop reaches a proactive_think turn
RUN:   Select-String -Path src\**\*.py -Pattern 'WorkItemAgenticExecutor\(|AgenticLoop\('
FOUND: cognitive_agent.py:2142 (_run_agentic_dispatch; sole caller :2014, inside
       _handle_work_item_dispatch), cognitive_agent.py:4238
       (_maybe_run_conversational_agentic, gated intent == direct_message),
       startup/finalize.py:1996, tools/delegate_task_tool.py:183 (in-loop tool),
       swe_harness/native_builder.py:100, agentic_dispatch.py:2215
HOLDS: yes -- none is reachable from proactive_think

CLAIM: the three claimed notebook slugs were never written
RUN:   walked %LOCALAPPDATA%\ProbOS\data\ship-records\notebooks (2,648 files,
       per-callsign dirs, filenames are "<slug>.md" -- Ezri alone has 272);
       matched each slug against BOTH filename and file content
CONTROL: the scan named a file it had actually read
       (github-validation-methodology.md), so a nil result is a real absence and
       not an unopened walk
FOUND: ward-room-escalation-decision  -> absent
       engineering-morale-watch       -> absent
       spacex-ipo-trade-setup         -> absent
HOLDS: yes

CLAIM: three persisted agent replies still carry a "[NOTEBOOK" string
RUN:   sqlite chat_thread_messages where role='agent' and body like '%[NOTEBOOK%'
       (1,069 agent messages total)
FOUND: 2026-07-26 22:45:26 counselor -- FALSE POSITIVE: prose mention of the
         "[NOTEBOOK] tag", no real block. The LIKE cannot tell them apart; both
         real instances were confirmed by reading the body.
       2026-06-07 12:25:53 counselor -- real unexecuted block + "I've got it filed."
       2026-06-07 01:12:57 yeoman    -- real unexecuted block + "Done -- that's saved"
NOTE:  AD-911 and AD-912 both landed 2026-06-07, so both real instances may
       predate step_4i on that vessel. Cited for shape, not for current-code rate.
```
