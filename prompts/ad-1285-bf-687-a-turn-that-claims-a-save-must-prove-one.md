# AD-1285 / BF-687 (#1087): a turn that claims a save must be able to prove one

**Status:** Ready to build
**Dependencies:** none (AD-911/912, AD-797, AD-934, AD-1248 already landed)
**Estimated tests:** ~28 new
**Issue:** https://github.com/seangalliher/ProbOS/issues/1087
**Drafted against:** HEAD `991c6d1c`

---

## Problem

2026-07-26 22:40, live, an agent replied *"I wrote the finding and it's saved to
my notebook under the slug `ward-room-escalation-decision`"*. No such file
exists. `publish_finding` never appears in the log. She then reasoned forward
from the false premise for several turns.

The turn was **healthy** — no BF-612 empty content, no BF-674 cooldown, no
tier-unavailable in the 22:35–22:45 window. A working turn produced a specific,
plausible, entirely fictional slug.

The read side is guarded (AD-1119/1120 `referent_gate.py`, AD-1121
`confab_probe.py`). **Nothing guards the write side.** The claim is
unfalsifiable from inside the conversation, the agent builds on it, and nothing
marks the turn as suspect.

### The prose that was supposed to prevent this is unenforced

`cognitive_agent.py:2960-2961` (`_conversational_notebook_protocol`, AD-911/912):

> "…confirm conversationally that you have saved it. **Only claim a note is
> saved when you actually emit this tag — never say you saved something without
> it.**"

Same unenforced promise for artifacts at `cognitive_agent.py:3009`. AD-1157
settled what guidance without a mechanism is worth: crew were told to classify
notebooks for months while the tag had no syntax to carry the choice, and
2,453/2,453 entries took the default. **Do not "fix" this by editing prompt
text.**

### What already exists, and why none of it closes this

**AD-643b `_detect_undeclared_actions` (`cognitive_agent.py:4635`) is a
different axis. Do not extend it, do not duplicate it, do not touch it.**

It scans COMPOSE text for **markers** (`[NOTEBOOK\s`, `[ENDORSE\s`, `[DM\s`,
`[REPLY\s`, `[NOTE\s`, `[PROPOSAL]`) and reports the ones absent from
`intended_actions`. That is *marker present, intent undeclared* — its purpose is
to load a missed skill and re-reflect (`cognitive_agent.py:5222-5262`). This
defect is *claim present, marker absent, call absent*: the inverse, and on the
other side of the run.

It also could not have fired. It runs only inside
`if has_comm_action and execute_steps:` where
`_COMM_ACTIONS = {"ward_room_post", "ward_room_reply", "endorse", "dm"}`
(`cognitive_agent.py:5158`). The issue's own log line reads
`intended_actions=['oracle_query'] (intent=proactive_think)` — `oracle_query`
is not a comm action, so the `else` branch took the single-call path and
**AD-643b never ran on the observed turn.**

---

## Finding: the invocation record exists twice and is discarded both times

The real path is **not** `swe_harness/agentic_loop.py` directly. It is
`WorkItemAgenticExecutor` in `cognitive/agentic_dispatch.py`, reached from
`_maybe_run_conversational_agentic` (AD-1065, `cognitive_agent.py:4204`).

**1. The tool loop does not run on the observed turn at all.**
`_conversational_agentic_will_run` (`cognitive_agent.py:4179`) requires
`observation["intent"] == "direct_message"`, non-group, non-vision, and
`config.dm_agentic.enabled`. On `proactive_think` the loop never starts, so
`publish_finding` is not callable and the only durable write channel is the
`[NOTEBOOK]` marker.

**2. Where the loop does run, the record dies at the outcome boundary.**
`AgenticResult` (`agentic_loop.py:763`) carries `tool_calls` + `tool_results`,
correlated by `ToolCallResult.id`. `WorkItemAgenticOutcome`
(`agentic_dispatch.py:1486`) carries neither — stated in-repo at
`cognitive_agent.py:120`:

> "`WorkItemAgenticOutcome`, which carries neither `tool_calls` nor
> `tool_results` — so (BF-793) it never ran at all."

Three lossy projections survive, and **none can name a success**:

| Survivor | Why it cannot answer "did `publish_finding` succeed?" |
|---|---|
| `tool_failures` | `correlate_tool_outcomes` (`dm/reply_value.py:69`) stores the display name when a call failed and `""` when it succeeded. The name of a success is hashed into `call_signature` and unrecoverable; `names()` returns failures only. `to_wire()` then **drops the tombstones**, so the value `DmReply.from_intent_result` rebuilds at `routers/agents.py:3434` is merge-closed — failures only. Permission denials are dropped entirely. |
| `tool_trace_ref` | A SHA into `AttachmentStore`; `None` whenever no store is wired. Provenance, not an in-process fact. |
| `tool_defect` / `tool_defect_evaluated` | AD-1257/AD-1269. A defect verdict, not an inventory. |

**3. The marker channel throws its record away too.**
`step_4i_notebook_parse` (`reply_pipeline.py:895`) calls
`extract_and_execute_notebooks`, receives `(cleaned, actions)`, logs
`len(actions)` and discards it. Its safety net then strips any surviving
`[NOTEBOOK …]` block. So a marker whose write **failed** produces a
Captain-visible reply that reads exactly like a successful one.

**Conclusion: no name-addressable record of "what actually happened this turn"
exists anywhere the reply is composed. This AD creates one.**

---

## Solution

A per-turn **write ledger**: which durable-write channels were consulted, and
which actually produced a write. The reply is then checked against the ledger
before it reaches the Captain.

Two verdict branches. **Branch 1 is the structural core and uses no text
matching at all.**

**Branch 1 — marker ran, nothing was written.** A write marker was present, its
channel executed, and it produced zero actions. The tag is stripped and the
agent was instructed to "confirm conversationally that you have saved it", so
the reply is a success claim by construction. Purely structural; no regex.

**Branch 2 — no marker, nothing was written, and the reply asserts a save.**
Covers the observed defect. The **verdict** is the ledger; the text is only a
narrow precondition that can only ever *shrink* the flag set. This is the
reading of "structural, not string-matching" that makes the acceptance criteria
mutually satisfiable: string-matching alone would false-positive on every
genuine save, and the ledger is what prevents that.

**Intervention: correct and mark. Never block.** Design Principle #13(c) — a
refusal that ends the work is a capability ceiling in a governance costume. The
reply keeps its substance and gains one honest sentence; the turn is logged with
a stable marker.

**Abstain by default.** No flag when the ledger was never populated
(`evaluated is False`), when any write did occur, or when Branch 2's
precondition is absent. This is the AD-1269 lesson — a verdict of "nothing
happened" and "nobody looked" must not be the same value.

### Why not the alternatives

- **An LLM probe (AD-1121 `confab_probe.py`)** — that exists because the read
  side has no ground truth. The write side does. Sampling would be slower,
  costlier, and capable of false positives against a fact already known.
- **A new `[SAVED]` tag the agent must emit** — an agent that confabulates a
  save will confabulate the tag.
- **Blocking the reply** — see #13(c).

---

## Scope

**Files you may change:**

| File | Change |
|---|---|
| `src/probos/cognitive/dm/write_ledger.py` | **NEW** — ledger value + verdict |
| `src/probos/cognitive/dm/reply_pipeline.py` | ledger field, record at 4i/4f, new step 4m |
| `src/probos/cognitive/dm/__init__.py` | export the new names |
| `src/probos/config.py` | `WriteClaimGuardConfig` |
| `tests/test_ad1285_write_claim_guard.py` | **NEW** |
| `tests/test_ad1248_slice_b.py` | step-count docstring guard (see §7) |

**Files you must NOT change — hard stop if you think you need one:**

`cognitive_agent.py`, `agentic_dispatch.py`, `continue_or_ask.py`,
`repair_verification.py`, `fault_report.py`, `tools/browser/url_route_guard.py`
are **foreign-modified and unstaged in the working tree**. Editing them will
collide with work in flight. `cognitive_agent.py` is explicitly off-limits by
Captain's instruction. The design above is deliberately shaped to need none of
them.

Also do not touch `README.md`, `docs/architecture/federation.md`,
`docs/development/roadmap.md`.

---

## Implementation

### Section 1 — `src/probos/cognitive/dm/write_ledger.py` (new)

Layer: COGNITIVE. Runtime-free by construction — no runtime import, no LLM
client, no store. Pure value + pure function, so it is testable without a ship.

```python
"""AD-1285 (#1087 / BF-687): the per-turn record of what was actually written.

A reply that claims a durable save must be checkable against something. Before
this module there was nothing to check against: the agentic loop's
``tool_calls``/``tool_results`` die at ``WorkItemAgenticOutcome`` (BF-793), the
``ToolFailures`` projection cannot name a success once ``to_wire`` drops its
tombstones, and ``step_4i_notebook_parse`` logged its action count and threw it
away. This is the missing record.

Two states are deliberately distinct, for the AD-1269 reason: a ledger nobody
populated (``evaluated`` False) must never read as "no write occurred". An
unpopulated ledger abstains.
"""
```

Provide:

- `WRITE_CHANNEL_NOTEBOOK = "notebook"`, `WRITE_CHANNEL_ARTIFACT = "artifact"`
  — module constants; the ledger is keyed by channel name so a later slice can
  add `publish_finding` without changing the shape.

- `@dataclass(frozen=True) class WriteLedger` with:
  - `turn_observed: bool = False` — the guard itself ran this turn. Set once by
    `step_4m`, never by a channel.
  - `consulted: frozenset[str] = frozenset()` — channels whose step actually
    ran its execution path this turn.
  - `wrote: frozenset[str] = frozenset()` — channels that produced ≥1 write.
  - `evaluated: bool` — property, `self.turn_observed or bool(self.consulted)`.
  - `def consulted_with(self, channel: str, *, wrote: bool) -> "WriteLedger"`
  - `def observed(self) -> "WriteLedger"` — sets `turn_observed`.

  Both return a new value; frozen + copy-on-write so a step cannot retroactively
  mutate a value another step already read. `frozenset` fields for the same
  reason `ToolFailures` uses a sorted tuple rather than a `Mapping`
  (`dm_reply.py:212`): a mutable field on a "frozen" dataclass retains the
  caller's object.

  **`turn_observed` is why the two branches are independently reachable, and it
  is load-bearing.** Without it `evaluated` would mean `bool(consulted)`, and
  Branch 2 — no channel ran, so `consulted` is empty — could never be reached in
  production. Documented behaviour that never runs is not behaviour
  (`dm_reply.py:288`). It is also the AD-1269 distinction, in the same shape:
  "the pipeline looked at this turn" is a different fact from "a channel ran",
  and both are different from "nothing happened".

- `class ClaimVerdict(enum.Enum)`: `ABSTAIN`, `MARKER_WROTE_NOTHING`,
  `CLAIM_WITHOUT_WRITE`.

- `def assess_write_claim(reply_text: str, ledger: WriteLedger) -> ClaimVerdict`

  Order matters, and the abstains come first:

  1. `if not ledger.evaluated: return ABSTAIN` — nobody looked.
  2. `if ledger.wrote: return ABSTAIN` — a real write happened. **This is the
     line that satisfies "a genuinely successful call is never flagged."**
  3. `if ledger.consulted: return MARKER_WROTE_NOTHING` — Branch 1. A channel
     ran and wrote nothing. No text is read.
  4. `if _asserts_completed_save(reply_text): return CLAIM_WITHOUT_WRITE` —
     Branch 2. Reached when the guard ran, no channel did, and the reply claims
     a save. **This is the observed defect.**
  5. `return ABSTAIN`.

  Step 3 precedes any text read, so Branch 1 is text-independent.

- `def _asserts_completed_save(text: str) -> bool` — the narrow Branch 2
  precondition. Requirements, all mandatory:

  - **First person, completed, durable-object.** Match only a first-person
    subject (`I` / `I've` / `I have`) with a completed save verb (`saved`,
    `wrote`, `stored`, `recorded`, `published`, `filed`) **and** a
    durable-store object within the same clause (`notebook`, `note`,
    `record(s)`, `finding`, `file`, `document`, `artifact`, `slug`, `entry`).
    Requiring the object is what keeps "I saved you some time" out.
  - **Reject modal / future / interrogative / negated forms.** `I can save`,
    `I'll save`, `I could write`, `Shall I save`, `Do you want me to save`,
    `I have not saved`, `I did not write` must all be False. Implement as an
    explicit negative pre-filter, not as regex cleverness.
  - **Second/third-person subjects are out.** "Your settings are saved",
    "the system saved it" → False.
  - `re.IGNORECASE`. Compile at module scope.
  - Bounded input: examine at most the first 4000 characters. A long reply must
    not turn this into a scan cost.

  State the bias in the docstring: **this precondition is deliberately
  conservative and will miss phrasings. A miss costs one undetected turn; a
  false positive trains the Captain to ignore the warning, which costs the
  control itself.**

- `def disclosure_for(verdict: ClaimVerdict) -> str` — the appended sentence.

  **Gap-regex-safe. `_CAPABILITY_GAP_RE` (`decomposer.py:50`) matches `don't
  have`, `can't`, `cannot`, `unable to`, `no capability|ability|support|way|
  mechanism|tool`, `not available|supported|possible`, `lack(s|ing)`, `doesn't
  have|support`, `beyond my capabilities`, `outside my scope`. The disclosure
  must contain none of them** — a match would misclassify the turn as a
  capability gap and trigger self-modification.

  Use text of this shape (verify against the regex in a test):

  - `MARKER_WROTE_NOTHING` → `"\n\n[No durable write was recorded for this turn — the save described above did not complete.]"`
  - `CLAIM_WITHOUT_WRITE` → `"\n\n[No durable write was recorded for this turn — treat the save described above as unconfirmed.]"`

### Section 2 — ledger field on `DmReplyContext`

In `reply_pipeline.py`, after the `generated_attachment_ids` field (~line 129),
following the AD-791a defaulting convention already documented at line 119 so
the existing `DmReplyContext(...)` constructions in tests keep working:

```python
    # AD-1285 (#1087): what this turn actually wrote. Populated by the steps
    # that own a durable-write channel; read by ``step_4m_write_claim_guard``.
    # Defaulted, so every existing construction site is untouched.
    write_ledger: WriteLedger = field(default_factory=WriteLedger)
```

Import `WriteLedger` at module top with the other `dm` imports.

### Section 3 — record the notebook channel

In `step_4i_notebook_parse`, the fast-path early return stays exactly as it is —
**a turn with no marker must not mark the channel consulted.** Record only on
the branch that actually executed:

```python
            try:
                cleaned, actions = await proactive.extract_and_execute_notebooks(
                    self.ctx.agent, self.ctx.response_text,
                )
                self.ctx.response_text = cleaned
                # AD-1285: the channel ran; ``actions`` is the only in-process
                # evidence of whether it wrote, and it was previously logged
                # and dropped.
                self.ctx.write_ledger = self.ctx.write_ledger.consulted_with(
                    WRITE_CHANNEL_NOTEBOOK, wrote=bool(actions),
                )
                if actions:
                    logger.info(...)   # unchanged
            except Exception:
                # AD-1285: the write raised. Consulted, wrote nothing.
                self.ctx.write_ledger = self.ctx.write_ledger.consulted_with(
                    WRITE_CHANNEL_NOTEBOOK, wrote=False,
                )
                logger.warning(...)    # unchanged
```

Leave the trailing safety-net strip untouched.

**Do not** mark the channel consulted when `proactive` is `None` or lacks
`extract_and_execute_notebooks` — that is "no channel", not "a channel that
wrote nothing", and conflating them would flag every turn on a ship with no
proactive loop wired.

### Section 4 — record the artifact channel

Same treatment in `step_4f_extract_artifacts` (`reply_pipeline.py:1199`). Read
the method first and mirror whatever its existing success signal is. Mark
consulted only where extraction actually ran; `wrote=True` only where an
artifact was persisted. If the method's success signal is ambiguous, **leave
this section out and say so in your build report** — an ambiguous ledger entry
is worse than an absent one, because it produces false positives.

### Section 5 — `step_4m_write_claim_guard`

New method on `DmReplyPipeline`, placed with the other step methods:

```python
    async def step_4m_write_claim_guard(self) -> None:
        """AD-1285 (#1087 / BF-687): a turn that claims a save must prove one.

        Compares the reply against :class:`WriteLedger` — the record of what
        this turn actually wrote — and appends one honest sentence when the
        two disagree. Never blocks and never rewrites the agent's substance
        (#13(c): a refusal that ends the work is a capability ceiling in a
        governance costume).

        Abstains whenever the ledger was not populated, so a ship with no
        write channel wired is byte-identical.

        Tier-2 honest-degrade: never raises.
        """
```

Behaviour:

- Return immediately when `config.write_claim_guard.enabled` is False, or when
  `ctx.response_text` is empty.
- `self.ctx.write_ledger = self.ctx.write_ledger.observed()` — **first**, before
  assessing. This is what makes Branch 2 reachable: the guard ran, so the turn
  was looked at, whether or not any channel was.
- `verdict = assess_write_claim(self.ctx.response_text, self.ctx.write_ledger)`.
- On `ABSTAIN`, return without touching anything.
- Otherwise `logger.warning(...)` with a stable, greppable marker naming the
  verdict, the agent id, the chat thread id, and the consulted/wrote channel
  sets — this is the "turn is marked in the log so this is diagnosable after
  the fact" criterion. Do not log the reply body.
- Append `disclosure_for(verdict)` via `self.ctx.response_text = ... + ...`.
  The property setter preserves attachments (AD-1248).

### Section 6 — register the step

In `_full_steps()`, insert between `step_4j_deliberate_parse` and
`step_5_episodic_store`:

```python
            self.step_4j_deliberate_parse,  # AD-934
            self.step_4m_write_claim_guard,  # AD-1285 (#1087)
            self.step_5_episodic_store,
```

Both boundaries are load-bearing:
- **After 4j** — AD-934 re-rolls the reply text at the deep tier. Checking
  before it would assess a draft the Captain never sees.
- **Before 5** — the stored episode and the divergence check must carry the
  corrected text.

**Do not add it to `_escalation_steps()`.** The group fan-out
(`thread_fanout.py:675`) runs `run_escalation_only`, and the same hazard exists
there, but its disclosure sink is unverified and `_escalation_steps` documents
an explicit 1:1/group exclusion rationale. Record it as a forward marker in the
`_escalation_steps` docstring: *"AD-1285 `step_4m_write_claim_guard` is 1:1-only
pending group-sink verification (#1087)."*

### Section 7 — the step-count guard

`tests/test_ad1248_slice_b.py:477-487` asserts the `_full_steps` docstring
number equals `len(_full_steps())`. Adding a step makes the tuple 21.

Update the `_full_steps` docstring: `**20 steps**` → `**21 steps**`, and extend
the trailing sentence to name the AD-1285 insertion alongside the AD-934 one.
Do not weaken or delete the guard test — it exists because BF-796 found the
docstring saying 18 while the tuple returned 20.

Check the other order regressions still pass unmodified:
`tests/test_ad811a_a2ui_choice.py:308`, `tests/test_ad811c_group_a2ui.py:99`,
`tests/test_ad934_deliberate.py:232`,
`tests/test_bf296_dm_outbound_in_reply.py:30`.

### Section 8 — config

In `config.py`, near `DmAgenticConfig` (line 6284):

```python
class WriteClaimGuardConfig(BaseModel):  # AD-1285 (#1087 / BF-687)
    """Whether a reply is checked against the turn's write ledger."""

    enabled: bool = True
```

Register on the parent model beside `dm_agentic` (line 7542).

**Default ON, and that is a decision.** Repo convention defaults new
*capabilities* OFF (AD-1119, `dm_deliberate`, A2UI). This is a *safety control*,
and Design Principle #13(a) is explicit that a ceiling must be a decision rather
than an inheritance — a default-OFF control defends nothing, which is the
AD-1157 failure mode this issue names. Default ON is safe here because
`assess_write_claim` abstains on an unpopulated ledger, so a ship without the
notebook channel wired is byte-identical. The flag exists so the behaviour can
be turned off without a revert.

---

## Tests — `tests/test_ad1285_write_claim_guard.py`

Use `_Fake*` stubs, not mock chains. **Do not use `MagicMock(spec=...)` for the
pipeline or the ledger** — AD-1284 hit exactly this: a spec'd double
auto-mocks any new public name, so an assertion passes for the wrong reason.
Construct real `WriteLedger` values.

**Ledger value (6)**
1. Default `WriteLedger()` → `evaluated is False`, both sets empty.
2. `consulted_with("notebook", wrote=True)` → both sets contain it.
3. `consulted_with("notebook", wrote=False)` → consulted only.
4. Copy-on-write: the original value is unchanged after `consulted_with`.
5. Two channels accumulate independently.
6. `observed()` alone → `evaluated is True`, `consulted` still empty. *This is
   the Branch-2 precondition; assert it directly.*

**Verdict — abstains (5)**
6. Unpopulated ledger + a reply that plainly claims a save → `ABSTAIN`.
   *This is the false-positive floor. Name it in the test docstring.*
7. `wrote={"notebook"}` + a save claim → `ABSTAIN` (**genuine success never
   flagged** — the acceptance criterion, asserted directly).
8. `wrote` non-empty but `consulted` also holds a second channel that wrote
   nothing → `ABSTAIN`. A turn that wrote *something* is not confabulating.
9. Consulted, wrote nothing, reply is a question (`"Shall I save that?"`) →
   still `MARKER_WROTE_NOTHING`, because Branch 1 does not read text. Assert
   this explicitly so a later refactor cannot quietly make Branch 1
   text-dependent.
10. Empty reply text + unpopulated ledger → `ABSTAIN`.

**Verdict — Branch 1 (2)**
11. Consulted `notebook`, wrote nothing → `MARKER_WROTE_NOTHING`.
12. Consulted after the write raised → `MARKER_WROTE_NOTHING`.

**Verdict — Branch 2 negative corpus (6)** — one parametrised test, each string
asserted `ABSTAIN` against `WriteLedger().observed()` (guard ran, no channel
ran). This is the false-positive corpus and the most important test in the
file:

`"I can save that to your notebook."` / `"I'll write that up and save it."` /
`"Shall I save this as a note?"` / `"Do you want me to record that?"` /
`"I have not saved anything yet."` / `"Your preferences are saved."`

**Verdict — Branch 2 positive (3)**
`WriteLedger().observed()` + `"I wrote the finding and it's saved to my notebook
under the slug ward-room-escalation-decision"` → `CLAIM_WITHOUT_WRITE`. **Use
the verbatim observed string — this is the regression test for #1087.** Plus
`"I've recorded that in my notebook."` and `"I saved the document for you."`

**Disclosure (2)**
- `disclosure_for` output for **both** verdicts asserted against
  `decomposer._CAPABILITY_GAP_RE` — `assert not _CAPABILITY_GAP_RE.search(text)`.
  Import the real compiled regex; do not restate it.
- Disclosure is non-empty and starts with a blank-line separator.

**Pipeline integration (3)** — the seam, not the halves
- End-to-end: a `DmReplyContext` whose fake proactive loop returns
  `(cleaned, [])` for a reply containing `[NOTEBOOK slug]…[/NOTEBOOK]`; run the
  **full pipeline**; assert the final `ctx.response_text` carries the
  disclosure. This is the one test that crosses 4i → ledger → 4m.
- Same fixture with the fake returning one action → **no** disclosure, and the
  reply body is otherwise unchanged.
- `config.write_claim_guard.enabled = False` → byte-identical output.

**Ordering (1)**
- `step_4m_write_claim_guard` appears in `_full_steps()` strictly after
  `step_4j_deliberate_parse` and strictly before `step_5_episodic_store`, and
  is **absent** from `_escalation_steps()`.

---

## What this does NOT change

- `publish_finding` — verified working 23:46 the same night. Untouched.
- BF-612 / BF-674 empty-response behaviour — #1086.
- Read-side confabulation — AD-1119/1120/1121. Untouched.
- AD-643a/AD-643b — different axis, and both live in an off-limits file.
- The `[NOTEBOOK]` / artifact protocol prose — the point is to enforce it, not
  reword it.
- The group fan-out path — forward marker only.
- Carrying the ledger through `WorkItemAgenticOutcome` so a `publish_finding`
  success is name-addressable — **deferred, see below.**

### Deferred: the agentic-loop half (a follow-up AD, not this one)

Closing the loop for tool-based writes needs a name-addressable success set on
`WorkItemAgenticOutcome`, produced at `agentic_dispatch.py:2343` beside
`tool_failures` and `tool_defect`, then carried to the reply. That is the right
design — it is exactly the AD-1248/AD-1257 pattern, and AD-1269's
`tool_defect_evaluated` is the precedent for the `evaluated` flag. **It is not
in this AD because it requires `agentic_dispatch.py` and `cognitive_agent.py`,
both foreign-modified, and `cognitive_agent.py` is off-limits.** File it once
the tree is clean. When you do: `WorkItemAgenticOutcome` carries neither
`tool_calls` nor `tool_results` — a detector handed that projection returns
nothing on every DM turn. That is BF-793, and it is written into the AD-1257
docstring at `cognitive_agent.py:120` precisely so the next person does not
repeat it.

---

## Tracking

- `PROGRESS.md` — add the AD-1285 entry.
- `docs/development/roadmap.md` Bug Tracker — **do not edit** (off-limits this
  wave). Note the pending row in your build report instead.
- `DECISIONS.md` — not required.

---

## Acceptance criteria

- [ ] A reply claiming a durable save, on a turn where no write occurred, is
      detected — with the verdict grounded in the ledger, not in the text.
- [ ] A turn whose write channel ran and wrote nothing is detected **without
      reading the reply at all** (Branch 1).
- [ ] A genuinely successful write is never flagged — asserted directly (test 7).
- [ ] An unpopulated ledger abstains — asserted directly (test 6).
- [ ] The Captain receives no unqualified success claim for an action that did
      not occur.
- [ ] The turn is logged with a stable, greppable marker.
- [ ] The reply is never blocked, refused, or substantively rewritten.
- [ ] An agent accurately reporting a real failure is unaffected — the guard
      reads the ledger and appends only on disagreement; it never penalises.
- [ ] Disclosure text does not match `_CAPABILITY_GAP_RE`.
- [ ] `_full_steps` docstring says 21 and the BF-796 guard passes unmodified.
- [ ] No change to `cognitive_agent.py`, `agentic_dispatch.py`,
      `continue_or_ask.py`, `repair_verification.py`, `fault_report.py`,
      `tools/browser/url_route_guard.py`, `README.md`,
      `docs/architecture/federation.md`, `docs/development/roadmap.md`.
- [ ] Both verdict branches are independently reachable in production, not only
      in tests.
- [ ] Verify all changes comply with the Engineering Principles in
      `.github/copilot-instructions.md`.

---

## Gating

The working tree carries unrelated uncommitted work that removes
`RedirectEscalation` while `browser/session.py` still imports it — roughly 423
tests fail for that reason alone. **Do not stash it.** Gate in a linked
worktree:

```
git worktree add <wt> 991c6d1c
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
  tests/test_ad933_group_chat_escalation.py \
  tests/test_bf296_dm_outbound_in_reply.py -q -p no:randomly
```

Run the adversarial `Diff Reviewer` on the staged diff before committing, with a
different model than the one that wrote the code. Tell it: the ledger is the
verdict and the text is only a precondition; the consumer that must accept the
change is `DmReplyPipeline.run()`; and the highest-risk property is that a
genuine save is never flagged.

---

## Verified Against Codebase (2026-08-29, HEAD 991c6d1c)

```
git log --all --format='%s' | grep -o 'AD-1[0-9]\{3\}' | sort -u | tail -1
  AD-1284
ls prompts/ad-*.md | tail -1
  ad-1284-bf-779-consensus-gate-reachability-and-declaration.md
  → ceiling AD-1284 from BOTH sources; next free AD-1285

grep -n "_extract_intended_actions\|_detect_undeclared_actions" src/probos/cognitive/cognitive_agent.py
  4611: def _extract_intended_actions(chain_results: list) -> list[str]:
  4635: def _detect_undeclared_actions(
  5124:     intended_actions = self._extract_intended_actions(triage_results)
  5222:     undeclared = self._detect_undeclared_actions(compose_text, intended_actions)

src/probos/cognitive/cognitive_agent.py:4651
  "notebook": re.compile(r'\[NOTEBOOK\s', re.IGNORECASE),     # marker, not prose
src/probos/cognitive/cognitive_agent.py:5158
  _COMM_ACTIONS = frozenset({"ward_room_post", "ward_room_reply", "endorse", "dm"})
src/probos/cognitive/cognitive_agent.py:5194
  if has_comm_action and execute_steps:                       # AD-643b gate

src/probos/cognitive/cognitive_agent.py:2960-2961
  "confirm conversationally that you have saved it. Only claim a "
  "note is saved when you actually emit this tag — never say you "
src/probos/cognitive/cognitive_agent.py:3009
  "saved when you actually emit this tag."                    # artifact twin

src/probos/cognitive/cognitive_agent.py:4179  _conversational_agentic_will_run
src/probos/cognitive/cognitive_agent.py:4195  if observation.get("intent") != "direct_message": return False
src/probos/cognitive/cognitive_agent.py:4204  _maybe_run_conversational_agentic
src/probos/cognitive/cognitive_agent.py:120
  "``WorkItemAgenticOutcome``, which carries neither ``tool_calls`` nor
   ``tool_results`` — so (BF-793) it never ran at all."

src/probos/cognitive/swe_harness/agentic_loop.py:763  class AgenticResult
src/probos/cognitive/swe_harness/agentic_loop.py:767  tool_calls: list[ToolCallRequest]
src/probos/cognitive/swe_harness/agentic_loop.py:783  tool_results: list[ToolCallResult]
src/probos/cognitive/agentic_dispatch.py:1486        class WorkItemAgenticOutcome
src/probos/cognitive/agentic_dispatch.py:2343-2372   construction site
  2354: tool_failures=correlate_tool_outcomes(...)   # AD-1248 "only scope holding the raw pairs"
  2365: tool_defect=detect_tool_defect(...)          # AD-1257 "same scope, same reason. BF-793"
  2371: tool_defect_evaluated=True                   # AD-1269 evaluated-flag precedent

src/probos/cognitive/dm/reply_value.py:69    def correlate_tool_outcomes(
src/probos/cognitive/dm/reply_value.py:128     state[key] = offered_display_name(...) if failed else ""
src/probos/dm_reply.py:165   def call_signature(name, arguments)  # name hashed → success unnamed
src/probos/dm_reply.py:400     "Success tombstones are dropped here."   (to_wire)
src/probos/routers/agents.py:3434  reply=DmReply.from_intent_result(result)  # merge-closed

src/probos/cognitive/dm/reply_pipeline.py:82    class DmReplyContext
src/probos/cognitive/dm/reply_pipeline.py:129   generated_attachment_ids  (last field)
src/probos/cognitive/dm/reply_pipeline.py:163   def _full_steps  → "**20 steps**"
src/probos/cognitive/dm/reply_pipeline.py:895   step_4i_notebook_parse
src/probos/cognitive/dm/reply_pipeline.py:915     if "[NOTEBOOK" not in ...: return   # fast path
src/probos/cognitive/dm/reply_pipeline.py:919     cleaned, actions = await proactive.extract_and_execute_notebooks(
src/probos/cognitive/dm/reply_pipeline.py:1199  step_4f_extract_artifacts
src/probos/routers/agents.py:3425               DmReplyPipeline(DmReplyContext(
src/probos/routers/thread_fanout.py:675         group path, run_escalation_only

tests/test_ad1248_slice_b.py:483-487
  actual = len(rp.DmReplyPipeline._full_steps(pipeline))
  → docstring count guard; must become 21

src/probos/cognitive/decomposer.py:50  _CAPABILITY_GAP_RE = re.compile(
src/probos/config.py:6284              class DmAgenticConfig(BaseModel):  # AD-1065
src/probos/config.py:7542              dm_agentic: DmAgenticConfig = Field(...)
src/probos/cognitive/dm/__init__.py:8-10  exports DmReplyContext, DmReplyPipeline

git status --porcelain -- src/ tests/
   M src/probos/cognitive/agentic_dispatch.py     ← foreign, do not edit
   M src/probos/cognitive/cognitive_agent.py      ← foreign, OFF LIMITS
   M src/probos/cognitive/continue_or_ask.py
   M src/probos/cognitive/repair_verification.py
   M src/probos/fault_report.py
   M src/probos/tools/browser/url_route_guard.py
   M tests/test_bf822_browser_navigation_floor.py
  ?? src/probos/infrastructure/restore.py
```

**Absence verified**

```
CLAIM: no allocated-but-unbuilt AD already covers #1087 / BF-687
RUN:   grep -l 'BF-687\|1087' prompts/ad-*.md
FOUND: (none)
HOLDS: yes — AD-1285 is a fresh allocation, not a revision

CLAIM: nothing today compares narration against an actual invocation record
RUN:   grep -rn 'correlate_tool_outcomes|detect_tool_defect|_detect_undeclared_actions' src/
FOUND: reply_value.py:69 (failures, successes unnamed), fault_report.py:298
       (defect verdict), cognitive_agent.py:4635 (markers vs declared intent)
HOLDS: yes — all three answer a different question
```
