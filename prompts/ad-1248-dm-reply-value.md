# AD-1248 — `DmReply`: a reply is a value, not a string

**Status:** **APPROVED for build** — v7, after seven adversarial review rounds.
Round 7 verdict: *"(a) The design is correct enough to build. DD-12 closes the
round-6 design blocker… Any remaining problems are implementation gates for
Slice A, not evidence that the next slice would establish the wrong boundary."*
**Supersedes:** the `DmReply` half of AD-726c (forward marker, filed Wave 160, never built)
**Unblocks:** BF-773 (#1230), which cannot be built correctly without it
**Related, NOT retired here:** BF-702's emotion-tag class. This AD lands the
shape; migrating `<intent emotion=…>` onto it is a follow-up, so the existing
promotion-side strip must stay and the AD-1230 deferred leak needs its own
owner. An earlier draft claimed this AD retired that class — it does not.

---

## Problem

A DM reply is an untyped `str` that does double duty as **both the payload and
the metadata channel**. Any fact *about* the reply has nowhere to live, so it is
either smuggled *inside* the text and parsed back out, or routed *around* the
text through a side channel that only some delivery paths carry.

Measured on HEAD (`4daf5c07`):

| Measure | Count |
|---|---|
| Markers encoded into the reply text and parsed back out | **14** (`[MESH`, `[TODOS`, `[ACTION`, `<artifact`, `<intent emotion=…>`, …) |
| `strip_*` helpers that exist to remove them again | **10** |
| `_full_steps()` stages / lines that assign `ctx.response_text` | **20 / 34** |
| Delivery paths that render agentic text to the Captain | **6** |
| …of those, paths that read the BF-773 provenance field | **2** |
| Side-channel hops needed to move one fact agent → router | **4** (`observation` → `decision` → `act()` → `IntentResult.metadata`) |

### The defect class, three instances

1. **BF-702** — a promoted run returned the loop's text directly, bypassing
   `step_7_divergence_check`, and `<intent emotion=warm>` leaked into the
   Captain's transcript. Fixed *at that one bypass*.
2. **This session (unfiled)** — adversarial review found the **AD-1230 deferred
   replay** path still leaks the same tag. Same defect, different bypass,
   different year, because the fix was applied to a path rather than to the
   shape.
3. **BF-773** — a failed tool call must reach the text the Captain reads. Four
   review rounds, fourteen blockers, and the count never converged: each round
   found either a new delivery path or a new prose form the ownership parser
   mis-handled (blockquote → indented code → `- ` → `1. ` → `Note: `).

BF-773 is not hard because disclosure is hard. It is the first feature that
needed **one fact to survive every path**, and no mechanism for that exists.

### The baseline: the staged BF-773 diff is DISCARDED

Review round 4 read `cognitive_agent.py:4227-4237` as "the producer today" and
built a blocker on it. That code is the **staged, four-times-rejected BF-773
attempt**, not HEAD. Enumerated:

```
git grep -n "tool_failures" HEAD -- src/     → no matches (exit 1)
git grep -n "tool_failures"      -- src/     → 12+ matches, all in staged edits
git status --porcelain                       → M cognitive_agent.py, M agents.py,
                                               A tool_failure_disclosure.py, …
```

**There is no legacy `metadata["tool_failures"]` producer or consumer at HEAD.**
So AD-1248 builds from clean HEAD: `git restore --staged --worktree` the eleven
BF-773 files first. There is no dual authority to migrate, no rendered sentence
in the body to re-render, and no compatibility window — the concealment risk
round 4 identified in promotion and deferred replay is an artifact of the staged
diff and vanishes with it.

**Salvaged as KNOWLEDGE, not as code.** The staged diff is discarded outright —
no branch, no patch. Three considerations made preservation the wrong call:

1. **The code does not survive the redesign anyway.** `correlate_tool_outcomes`
   must emit scoped `{root}.{scope}:{signature}` keys and carry the merge-open
   lifecycle bit; `collapse_to_names` becomes `ToolFailures.names()`. Only
   `_signature()` (name + canonical-JSON args → 16 hex) survives intact, and it
   is fourteen lines.
2. **One of its docstrings now contradicts this AD.** `collapse_to_names`
   documents that the signature map *"must NOT"* cross a process boundary.
   DD-5 decided the opposite — ≤64 failing entries ride the wire deliberately,
   because merge needs them. Preserving that beside plausible-looking reference
   code preserves a superseded conclusion.
3. **Everything of value is now written down here** — the tombstone rationale
   (DD-1), the offered-name and denial rules (DD-1a), the payload measurements
   (DD-1), and the `offered_names` post-dedup capture point (DD-1a). That is the
   whole of what four reviews left unfaulted.

**Deleted with it:** `_owned_tail_span`, `_DISCLOSURE_TAIL_RE`,
`ensure_tool_failure_disclosure`, `recanonicalise_disclosure`,
`_reads_as_a_capability_gap`, and `step_7a_tool_failure_disclosure` — the
prose-parsing machinery this AD exists to make unnecessary. Also reverted: the
four repointed guards in `test_ad811a_a2ui_choice.py`, `test_ad934_deliberate.py`,
`test_bf680_token_usage_fallback.py` and `test_bf754_mcp_callable_definitions.py`,
which were repointed *at* that machinery.

### The fix was already diagnosed and never built

`reply_pipeline.py:86`:

> *"NOT frozen by design… AD-726c will introduce a frozen `DmReply` final shape
> once AD-726a + AD-726b land and the full contract stabilizes."*

`docs/development/roadmap.md:721` files AD-726c as *"Frozen cross-phase shapes
(`DmObservation`, `DmReply`)"*, gated on AD-726a + AD-726b.

**Enumerated: `class DmReply`, `class DmObservation`, `class DmContextPrep` and
`class DmPromptAssembler` — zero of the four exist in `src/`.** The reply-side
shape was gated behind two *prompt-side* extractions it does not depend on, and
so never landed. Every DM feature since Wave 160 has paid that interest.

---

## Decision

Introduce **`DmReply`** — a frozen value carrying the reply body plus the facts
that must survive a rewrite of that body (DD-8). It is produced once at the
agent boundary, carried across every component boundary as a value, and
**composed into display text exactly once, at each egress surface.**

The load-bearing property: **no component ever re-parses display text to
recover a fact.** That deletes the ownership question rather than answering it.

### DD-1 — The type: pinned scope tokens, tagged precise/summary state

```python
@dataclass(frozen=True)
class ToolFailures:
    """Two states, exactly one authoritative in each.

    PRECISE : ``entries`` = sorted ((scope:signature), display_name) pairs.
              ``names()`` is DERIVED. Full algebra available.
    SUMMARY : ``entries`` empty, ``summary_names`` + ``unresolved_count`` set.
              Disclosure intact, merge precision lost. See DD-2.

    ``entries`` is a sorted tuple of pairs, not a Mapping: a ``Mapping`` field on
    a frozen dataclass retains the CALLER'S dict, and mutating it after
    construction mutates the "frozen" value \u2014 proved by execution in round 3.
    """
    entries: tuple[tuple[str, str], ...] = ()      # PRECISE state
    summary_names: tuple[str, ...] = ()            # SUMMARY state
    unresolved_count: int = 0                      # SUMMARY state

    @property
    def is_summary(self) -> bool: ...
    def names(self) -> tuple[str, ...]: ...        # derived when precise
    def superseded_by(self, other) -> "ToolFailures": ...  # same scope; see DD-2
    def combined_with(self, other) -> "ToolFailures": ...  # disjoint scopes
```

**Only FAILING calls are SERIALIZED — but success tombstones survive in
memory.** v5 dropped successes from the type entirely, and round 5 killed it by
execution: without a tombstone, "pass 2 never retried this call" and "pass 2
retried it and it succeeded" serialize to the identical empty state, and
`superseded_by` must produce *retain* for the first and *clear* for the second.

```
pass2_no_retry_serialized      {}
pass2_retried_success_serialized {}
states_equal                   True
required_results               {'no_retry': 'retain', 'retried_success': 'clear'}
```

So the value has two lifecycle states, and the distinction is load-bearing:

| State | Contains | `superseded_by` |
|---|---|---|
| **merge-open** — built in process by `correlate_tool_outcomes` | failures **and** `""` success tombstones | full LWW algebra |
| **merge-closed** — reconstructed from the wire or a durable record | failures only | **raises** `ToolFailuresMergeClosed` |

The lifecycle bit is **orthogonal** to PRECISE/SUMMARY — a value can be
merge-open and summarised, or merge-closed and precise — so it is a separate
field, not a fourth enum member. And `superseded_by` rejects **either operand**
being merge-closed, not only the receiver: superseding *with* a reconstructed
value is equally unable to prove a success, and round 6 caught v6 specifying
only the receiver.

The staged BF-773 code already used `""` as a success tombstone; that part was
right and v5 discarded it by accident. Tombstones are dropped **at
serialization**, which is safe only because no supersession crosses a
serialization boundary today — and making the reconstructed value *raise* is
what turns that from an assumption into an enforced precondition. Round 5
verified the precondition holds at HEAD: AD-1164 reinvokes a local `_run_pass`
(`continue_or_ask.py:680`), AD-1155 assigns a local executor outcome
(`crew_executor.py:1768`, `:1890`), and crew reconstruction is followed by
`combined_with`, which is a union and needs no tombstones. If that ever changes,
the raise finds it on the first run rather than in a transcript.

The 64-entry bound therefore bounds distinct *failing* calls on the wire, which
is pathological rather than routine — round 4's 65-entry counter-example was 64
successes and one failure. The bound is not arbitrary: the discarded BF-773
build measured the unbounded map at **~176 KB for 2,000 signature entries and
~880 KB for 10,000**, against **~4.5 KB for 64 collapsed names** — the NATS 1 MB
ceiling is reachable by a long run, which is why PRECISE has a cap and SUMMARY
exists at all.

### DD-1a — The display name must come from the OFFER, not the registry

A salvaged finding from the discarded build, and the only place it is recorded.
`correlate_tool_outcomes` takes the set of **provider-facing names actually
offered this run**, and renders `UNKNOWN_TOOL_LABEL` for anything else. Two
reasons, both measured during the BF-773 attempts:

- **A registry id is not what the model receives.** AD-1019c ids shaped
  `mcp:{server}:{tool}` are rewritten to `mcp_<server>_<tool>_<16hex>` before
  they reach the provider (BF-754/BF-757, `swe_harness/tool_call.py:26`).
  Keying disclosure off the registry id names a tool the Captain never saw the
  agent offered.
- **The offered set can refresh mid-run**, so it must be captured from the
  actual offer rather than recomputed later. Capture it in `_build_tools`
  **after** `dedupe_llm_definitions`, not before — a pre-dedup capture names
  tools that were never offered.

**Permission denials are dropped, not disclosed.** Also salvaged, also recorded
nowhere else. AD-855's capability-gap driver already surfaces a denial to the
Captain as a tracked request naming the exact tool, which is strictly better
than a sentence reading "an unrecognised tool returned an error". Disclosing
both reports one event twice, in the worse wording. The build must reconcile
denial identifiers against the **offered** name, not the registry id — round 4
found the staged attempt failed in both directions, hiding a real failure when
the gap driver was degraded and duplicating it when the MCP alias did not match
(`denied_tools=['mcp:docs:search']` vs `call.name='mcp_docs_search_38c53abe80026e47'`).

**A `tuple[str, ...]` of names is the wrong attachment type**, and v2 had it
wrong. Supersession is per *call*, not per tool: `web_search(query=A)` failing
and `web_search(query=B)` succeeding are two searches, not a retry.

**But the signature alone is also wrong**, and v3 had *that* wrong. Round 3
proved by execution that two *independent* runs of `web_search(query="same")` —
one failed, one successful — produce the identical 16-hex signature, and
last-write-wins then erases the real failure:

```
failed_run              {'1f68624e831165e5': 'web_search'}
successful_independent  {'1f68624e831165e5': ''}
last_write_wins_merge   {'1f68624e831165e5': ''}
rendered_failure_names  []
```

Correct for an AD-1164 continuation; wrong for crew fan-in and delegation.

**Scope identity, pinned here rather than deferred.** v4 left this to the build
with a stated risk; round 4 was right that this is load-bearing enough to
specify now, and that `IntentMessage.id` does not fit (32 + 1 + 16 = 49 chars,
over the 48-char cap v4 proposed).

**The key carries LINEAGE, not just a scope.** Round 5 found the algebra was not
closed under delegation: a prior pass with scopes `{parent, child-A}` and a
fresh pass with `{parent, child-B}` is neither same-scope (so `superseded_by`
cannot apply) nor disjoint (so `combined_with` cannot). The key therefore names
the root execution and the producing scope separately:

| Property | Value |
|---|---|
| Token | **12 lowercase hex characters** |
| Key | `f"{root}.{scope}:{signature}"` — 12 + 1 + 12 + 1 + 16 = **42 chars**, cap **48** |
| Character class | `^[0-9a-f]{12}\.[0-9a-f]{12}:[0-9a-f]{16}$` — validated on the wire |
| Derivation | `sha256(source_id.encode()).hexdigest()[:12]`, except where the source is already 12 hex |
| Root | the execution that owns the turn; for an execution's own calls `scope == root` |

| Execution | Source id | Minting point |
|---|---|---|
| DM turn (all passes) | the cognitive `correlation_id` — `uuid4().hex[:12]`, minted once in `perceive()` (`cognitive_agent.py:2432`) | exists |
| **Work-item dispatch** | hashed `work_item_id` | **`_run_agentic_dispatch` never calls `perceive()`** (`cognitive_agent.py:1761` → `:1931`), so it has no cognitive `correlation_id` |
| Crew child | hashed `_crew_work_item_id` (`crew_executor.py:1735`) | child ids may be 128 chars (`crew_executor.py:64`) |
| AD-1155 outer-loop passes | **the child's scope, reused** | so pass 2 supersedes pass 1 |
| Delegated sub-agent | **freshly minted** `uuid4().hex[:12]`, root inherited from the parent | none exists today (`delegate_task_tool.py:179` carries only depth) |
| Convergence correction | **freshly minted**, new root | the corrected run replaces, so collision with the discarded run must be impossible |

**Promotion must read the scope from the observation, not the instance.**
`self._current_correlation_id` is cleared at `cognitive_agent.py:6347` while a
promoted background task may still be running, so promotion captures
`observation["correlation_id"]` at hand-off. Reading the instance field is a
use-after-clear that would silently mint a different scope for the same turn.

Distinct scopes collide only with probability ~2⁻⁴⁸ (12 hex = 48 bits), so fan-in
effectively cannot cancel a failure; identical scopes collide by design, so a
retry supersedes. "Cannot collide" would be an overstatement and v5 made it.


```python
@dataclass(frozen=True)
class DmReply:
    body: str                                   # the agent's prose. Never re-parsed.
    tool_failures: ToolFailures = ToolFailures()

    def render(self, *, max_chars: int | None = None) -> str: ...   # see DD-11
    def __str__(self) -> str: ...               # == render()
    def with_body(self, body: str) -> "DmReply": ...
    def superseded_by(self, other: "DmReply") -> "DmReply": ...
    def replaced_by(self, other: "DmReply") -> "DmReply": ...
    def combined_with(self, other: "DmReply") -> "DmReply": ...
```

### DD-2 — Four operations, and what each does in the SUMMARY state

Round 1 established transform ≠ replacement. Round 2 established that
replacement is itself two things, because AD-1164's continuation prompt says
*"build on the previous output, do not start over"* — a pass-1 failure that pass
2 never retried must NOT vanish. Round 3 established that fan-in is a fourth
thing. Round 4 established that the **summary state needs its own algebra**,
because two different histories serialize to the identical summary and no
implementation can recover both answers from it.

| Operation | Body | Attachments (PRECISE) | Attachments (SUMMARY) | Used by |
|---|---|---|---|---|
| `with_body(text)` | replaced | preserved | preserved | AD-934 deep re-roll |
| `superseded_by(other)` | replaced | LWW on **`other`'s own scope**; every other scope **retained** | **retained, not cleared**, and logs | AD-1164 continuation; AD-1155 outer loop |
| `replaced_by(other)` | replaced | replaced | replaced | AD-724-1 retry; convergence correction |
| `combined_with(other)` | caller's | unioned, **scopes** asserted disjoint | names unioned, counts summed | crew fan-in; delegation |

**Supersession is scoped, not wholesale**, and that is what closes round 5's
delegation gap. Pass 2 supersedes only the keys it could have retried — its own
scope. A failure recorded under `child-A` in pass 1 is retained, because pass 2
did not run child-A; if pass 2 delegated again, its failures arrive under
`child-B` and both are disclosed.

**Recorded over-disclosure.** If pass 2 *successfully* redid what child-A failed
at, child-A's failure still renders. Resolving that needs delegation identity
stable across passes, which does not exist — `DelegateTaskTool` carries only
depth (`delegate_task_tool.py:179`). The root field in the key makes lineage
*representable* so a later AD can refine this; until then it is a bounded error
in the over-disclosing direction, which this AD has already chosen as the
survivable one.

**Supersession of a SUMMARY value retains the disclosure.** It cannot be
cleared, because the keys needed to prove a later success are gone. Same trade,
same direction. Reachable only after 64 distinct *failing* calls in one
execution, which is already a broken run. **Supersession of a merge-closed value
raises** (DD-1) rather than guessing.


`superseded_by` and `combined_with` are deliberately *not* the same function
with a different name. Union is only safe when scopes are disjoint; LWW is only
correct when they are identical. Each asserts its precondition rather than
inferring it, so a mis-wired call site fails loudly instead of silently deleting
a disclosure.

**Replacement and supersession apply only when the fresh run yields a valid
result.** The empty and error branches at each site retain the previous reply
today, and must continue to — otherwise a failed retry erases a good disclosure.

| Site | Operation |
|---|---|
| AD-724-1 sanity retry (`reply_pipeline.py:279` → `:293`) | `replaced_by` |
| AD-1164 continuation / reinvoke (`continue_or_ask.py:610`) | `superseded_by` |
| **AD-1155 crew outer loop (`crew_executor.py:1901`)** — multiple runs, only the final outcome returned | `superseded_by` |
| Convergence correction (`crew_verifier.py:1588`, legacy `:1240`) | `replaced_by` |
| Crew synthesis fold (`crew_synth.py:240`, `:364`) | `combined_with` |
| `DelegateTaskTool` child → parent (`delegate_task_tool.py:190`) | `combined_with` |

The AD-1155 row is new in v5: round 4 found the outer loop discards all but the
final outcome, so without it a pass-1 failure never retried in pass 2 disappears
— the exact defect `superseded_by` exists to prevent, one level up.

DD-6's "the mutation sites are untouched" therefore holds for **transforms
only**. Each site above needs a crossing test in both directions: an old failure
cleared, and a new one disclosed. Fan-in needs one more: **sibling A fails and
sibling B succeeds with byte-identical tool arguments**, and A's failure must
still render.



### DD-3 — `__str__` renders

A careless `str(reply)` or `f"{reply}"` yields the **correct** display text, not
the bare body. A renderer that forgets to call `render()` still tells the truth.
Fail-safe by construction, because "someone forgets this path" is precisely how
this defect class reproduces.

### DD-4 — Zero attachments renders byte-identically

`DmReply(body=x).render() == x`, exactly. The migration is behaviour-preserving
at every site until a fact is actually attached, which makes the diff auditable
and lets the suite prove it.

### DD-5 — The bus carries the BODY; rendering happens only at egress

v2 put the rendered text in `result` and duplicated the body into `metadata`.
Round 2 killed that on two counts, both measured:

- **The equality check could not establish authority.** DD-4 requires
  `render(body, ∅) == body`, so rendering is not injective: a stale
  `(body=b, attachments=a)` and a current rendered-only `(body=render(b,a), ∅)`
  both satisfy `candidate.render() == result.result`. A later `with_body()` then
  resurrects stale attachments.
- **Duplication doubles the payload.** A 600,000-byte body measured 600,150
  bytes in the NATS envelope and **1,200,209** once duplicated into
  `metadata["dm_reply"]["body"]`. `NATSMessage.respond` JSON-encodes the whole
  object with no cap, so one large reply fails the entire request.

The corrected design removes the pair rather than policing it:

- **`IntentResult.result = reply.body`** — the prose, un-rendered. No duplication.
- **`metadata["dm_reply"]`** — attachments only, bounded (schema below).
- **`render()` is called exactly once per route, at an EGRESS sink** — the
  registered points where the reply leaves ProbOS for a human (DD-11). Never on
  the internal bus, and **not** at a transport hop that reconstructs an
  `IntentResult` on the far side.

There is no rendered/body pair, therefore no staleness to detect and no
consistency guard to get wrong. `from_intent_result()` remains the single
reconstruction helper, but its only job is schema validation.

**Wire schema — two MUTUALLY EXCLUSIVE states, never both.** v4 put `names` and
`entries` in the same object and bounded each field independently. Round 4 broke
that by execution: a payload with `names=['read_file']` and
`entries=[['…','web_search']]` satisfied every stated bound while being flatly
self-contradictory. Two representations of one fact, unchecked against each
other, is the round-2 duplication trap wearing different clothes.

So the payload is a **tagged union**. Exactly one state is present; a payload
carrying keys from both is *malformed*, not reconciled:

```jsonc
// PRECISE — the normal case
{"v": 1, "entries": [["<12hex>.<12hex>:<16hex>", "web_search"]]}

// SUMMARY — only when PRECISE would exceed its bound
{"v": 1, "truncated": true, "names": ["web_search"], "unresolved_count": 65}
```

| State | Key | Bound |
|---|---|---|
| PRECISE | `entries` | ≤ 64 pairs of **failing** calls; key matches `^[0-9a-f]{12}\.[0-9a-f]{12}:[0-9a-f]{16}$` (42 chars, cap 48); value matches the name grammar below |
| SUMMARY | `truncated` | must be `true` |
| SUMMARY | `names` | ≤ 32 items, **same grammar** as an entry value — they are the same strings |
| SUMMARY | `unresolved_count` | `int`, ≥ `len(names)`, ≤ 10⁴ |

**Names use the real producer grammar**, not an arbitrary byte cap. v5 allowed
128 UTF-8 bytes, which admits control characters that no tool name can contain.
The provider-facing name is already constrained to OpenAI's function-name
grammar by BF-754/BF-757 (`swe_harness/tool_call.py:26`, `fullmatch`, not
`match` — `$` also matches before a trailing newline):

```
^[A-Za-z0-9_-]{1,64}$
```

That is the wire bound. 32 names × 64 chars is 2,048 characters of names, which
matters for the budget in DD-11.

`names` is **derived** from `entries` in the precise state and never
serialized there, so there is no pair to disagree. In the summary state
`entries` is absent and `names` is authoritative — again one authority.
Successes are never serialized in either state (DD-1).

Two degradation rules, deliberately different because they mean different
things:

- **Malformed / unknown `v` / both states present / bad key shape / a name that
  fails the grammar** — the metadata is not trustworthy. Degrade to
  `DmReply(body=result.result)` with **no** attachments, and log.
- **Valid but would exceed the PRECISE bound** — the metadata is trustworthy and
  merely large. Serialize the SUMMARY state. Merge precision degrades per DD-2;
  **disclosure does not degrade at all**.

Two enforceable invariants, replacing v3's single one:

1. A **malformed** reconstruction never carries non-empty attachments.
2. A **valid** reconstruction with at least one failure always renders a
   non-empty disclosure — count-only in the worst case, never empty.

This mirrors the precedent already in the tree: `crew_executor.py:1036` drops
artifact refs and warns rather than discarding the record.


**The trade this makes, stated plainly.** A consumer that ignores `metadata` now
receives the body *without* the disclosure, where v2's rendered-`result` would
have carried it. That is only acceptable because the egress sinks are
**enumerated and finite** (DD-11) and every one renders. The risk is future code
adding a sink that does not — which is exactly the failure this AD exists to
remove, so it is called out in Risks rather than waved away.


**Known metadata-loss boundaries.** `metadata` survives NATS (BF-742) but is
dropped by `federation/bridge.py::_serialize_directed_result` and omitted by
`cognitive/checkpoint.py::_serialize_result`.

**Directed federation is a TRANSPORT HOP, not an egress**, and v3 had it
mis-classified. The remote bridge does not deliver to a human: the origin
reconstructs another internal `IntentResult` from the serialised payload
(`federation/bridge.py:1271`) and *that* result then flows to a local sink.
Rendering remotely would flatten the structure before the consumer that needs
it. So the fix is the opposite of v3's: **carry the bounded `dm_reply` metadata
across `_serialize_directed_result` / `_finalize_directed_result_for_origin`**
and render at the real origin sink. There is also no in-repo production caller
to prove otherwise — enumerated:

```
Select-String -Path src\**\*.py -Pattern 'forward_direct_message'
src/probos/federation/bridge.py:1146:    async def forward_direct_message(
```

The definition and nothing else. If the build cannot identify a production
origin sink, it records that enumeration rather than inventing a render point.

**Checkpoint/resume** splits into two answers, and v3 deferred both:

- The **generic DAG checkpoint** is *not* on any Captain DM route. Its writers
  are confined to `DAGExecutor` (`decomposer.py:746`). Recorded here as a
  determined result, not a build-time question.
- The **crew synthesis recovery checkpoint** *is* on a Captain-visible route and
  does lose the facts. That is DD-9's problem and is specified there.

**Contract amendment required.** `types.py:88` reads *"Not for payload: results
belong in `result`."* This AD keeps that true — the payload stays in `result`;
only *facts about* the payload ride in `metadata`. The docstring is extended to
say so explicitly in the same commit.

### DD-6 — `DmReply` is canonical in the context; `response_text` is a view

`DmReplyContext` holds `reply: DmReply`. `response_text` becomes a **property**
backed by `reply.body`: reading returns the body, assigning performs
`self.reply = self.reply.with_body(value)`.

Deliberately not "a second field beside the text" — two independently mutable
body fields would drift, and drift is the defect this AD exists to remove. One
canonical value, one view onto it.

The payoff: the **34 existing `ctx.response_text` assignment lines change not at
all**, and every one now preserves attachments for free. `build_response()` is
an egress sink and composes once, via `ctx.reply.render()`.

**Viability confirmed, and the objection to it is wrong.** A property cannot be
added *beside* a same-named field — but that is not the design. The field
`response_text: str` (`reply_pipeline.py:96`) is **replaced** by `reply: DmReply`
in the same non-default position, and `response_text` becomes a property over
`reply.body`. Round 3 AST-enumerated `DmReplyContext` for anything a property
would break — `dataclasses.replace`, `asdict`, `vars`, field reflection,
serialization — and found none. Enumerated again before build: **every one of
the 27 construction sites uses keyword arguments**, none positional, so the
migration is mechanical.

**But the constructors DO change, and v2 hid that.** `DmReplyContext` has **27**
construction sites (2 production — `routers/agents.py:3381`,
`routers/thread_fanout.py:660` — and 25 test) that pass `response_text=`, which a
property cannot accept. Those 27 migrate to `reply=DmReply(body=...)`. Do **not**
hide the change behind a custom 15-field `__init__` — that buys a smaller diff by
obscuring the contract, which is the trade this AD exists to reverse.

**Counts are clean-HEAD, and earlier drafts got this wrong.** v5/v6 recorded
"21 stages / 35 assignments, returning to 20/34 once `step_7a` is deleted" — that
measured the *staged* BF-773 tree. At clean HEAD `_full_steps()` already returns
**20** entries and there are **34** assignments, because `step_7a` never existed
here. Criterion 9 is therefore a **regression guard** (this AD must not add
stages or assignment sites), not a restoration target.

(Unrelated pre-existing defect, found while measuring: the `_full_steps()`
docstring at `reply_pipeline.py:146` claims "18 steps" while the tuple returns
20. File it; do not fix it here.)

Consequently `step_7a_tool_failure_disclosure` — added in the BF-773 attempt —
is **deleted**, along with `_owned_tail_span`, `_DISCLOSURE_TAIL_RE` and
`recanonicalise_disclosure`. Roughly 120 lines of prose-parsing machinery go
away, and with them every ownership edge case.

### DD-7 — The entry points return `DmReply`; `llm_output` stays a `str`

Each entry point has exactly **one** caller (AST-enumerated on HEAD:
`_maybe_run_conversational_agentic` def 3988 / call 3820; `_run_agentic_dispatch`
def 1897 / call 1830). But the return is **not substitutable at that caller**: it
goes into `decision["llm_output"]`, which downstream code slices and calls
`.split()`, `.lower()` and `.strip()` on. Several of those failures are
swallowed — silently disabling faithfulness and learning — and the `.strip()`
would trigger a fallback to a second single-pass reply.

So the value travels **beside** the string, never as it:

- `decision["llm_output"] = reply.body` — every existing string consumer is
  untouched;
- `decision["_dm_reply"] = reply` — the canonical value, threaded through
  `act()`;
- `metadata["dm_reply"]` is constructed **only** at the `IntentResult` boundary
  (the body already travels in `result`, per DD-5).

| Symbol | New shape |
|---|---|
| `_maybe_run_conversational_agentic` | returns `DmReply \| None` |
| `_run_agentic_dispatch` | returns `DmReply \| None` |
| `_agentic_turn` (task awaited by promotion) | returns `DmReply` |
| `continue_or_ask.resolve_exhausted_turn` | takes and returns `DmReply` |
| `WorkItemAgenticOutcome` | see DD-9 — **one** body field, not two |

**The polymorphic boundary must not be assumed.** `act()` is overridden by
subclasses (`counselor.py:2946`) and by generated agents
(`agent_designer.py:129`), and those overrides copy only `llm_output`. The AD
therefore does **not** rely on every override forwarding `_dm_reply`: the pair is
reconciled at the **single** `IntentResult` construction site
(`cognitive_agent.py:6353`), which reads `_dm_reply` from the decision if present
and otherwise synthesises `DmReply(body=result)`. One place, no override
contract.

**Decision caching must be specified, and the exclusion is broader than
`_dm_reply`.** Decisions are cached wholesale (`cognitive_agent.py:3216` →
`:3342`). A cached decision carrying a `_dm_reply` from a previous turn would
replay stale attachments — but round 3 showed the same is already true of
`_tool_trace_ref`, which is forwarded and persisted with the next thread reply
(`cognitive_agent.py:5130`, `agents.py:3412`). So the cached projection excludes
**all per-run provenance**, `_dm_reply` and `_tool_trace_ref` together; a cache
hit reconstructs `DmReply(body=llm_output)` with no attachments. A replayed
answer asserts nothing about this turn's tools. The pre-existing
`_tool_trace_ref` half is a latent defect this AD closes as a side effect; it is
filed separately so it is not silently absorbed.

### DD-9 — One body field, and the crew facts must survive SYNTHESIS

`WorkItemAgenticOutcome` has **53** construction sites (1 production, 52 test).
Adding an independent `reply` beside `final_text` would recreate exactly the
drift DD-6 rejects. So: keep `final_text` and the structured run facts, and
expose **`to_dm_reply()`** as a projection. One body, one source of truth.

Rendering at the crew room post (`crew_executor.py:2094` → `:2534`) is necessary
and **not sufficient**. `SubtaskResult` (`crew_executor.py:1053`) carries only
text; both synthesizers then feed that text to an LLM and accept fresh output
(durable `crew_synth.py:240`, legacy `crew_synth.py:364`), and the result is
published as a Captain-visible artifact (`crew_finalizer.py:2969`). Hoping the
synthesiser repeats a sentence is the same trust DD-10 rejects.

Therefore the structured facts must travel through `SubtaskResult`, through the
convergence and recovery records, and through synthesis — and be **composed
after** synthesis, onto the synthesised body, via `combined_with` (DD-2), not
`superseded_by`: the children are disjoint scopes.

**"Through the records" is not a design, so here are the exact eleven.** Round 3
established that a restart after synthesis has nowhere to recover attachments
from; round 4 found that **convergence correction** loses them a step earlier and
in both directions; round 5 found **three more exact-key consumers** of the same
`crew_execution` record. Each structure gains a `tool_failures` field carrying
the DD-5 payload, and each versioned one bumps its version and accepts both
shapes:

| # | Structure | Site | Note |
|---|---|---|---|
| 1 | `SubtaskResult` | `crew_executor.py:1053` | in-memory; text-only today |
| 2 | `crew_execution` record | `crew_executor.py:1019` | `"version": 1` → `2`; subject to the 32 KiB `_MAX_EVIDENCE_BYTES` cap, so it uses the DD-5 SUMMARY state, not a raise |
| 3 | terminal-result reconstruction | `crew_executor.py:1410` | **exact key-set** |
| 4 | crew session projection | `crew_session.py:1317` | **exact key-set**, reached from `_row_semantic_projection` |
| 5 | finalizer live validation + resume reconstruction | `crew_finalizer.py:1174` | **exact key-set** |
| 6 | finalizer live child-result validation | `crew_finalizer.py:2431` | **exact key-set** |
| 7 | `_normalize_correction_outcome` | `crew_verifier.py:1508` | carries no failures today, so a corrected run's new failures are lost |
| 8 | session correction `replace(current, …)` | `crew_verifier.py:1588` | would **preserve the initial run's field** — must apply true `replaced_by` |
| 9 | legacy convergence | `crew_verifier.py:1240` | mutates only `result.output` |
| 10 | convergence checkpoint writer / reader | `crew_finalizer.py:1828` → `:1915` | **exact key-set** |
| 11 | `SessionSynthesisDraft` + synthesis recovery checkpoint | `crew_synth.py:99`, `crew_finalizer.py:1424` | **exact key-set** (`expected_keys`) |

Round 5 executed the v2 key set against the real consumers:

```
crew_session_accepts_v2_keys=    False
crew_finalizer_accepts_v2_keys=  False
new_key=                         ['tool_failures']
```

Without #7–#10 the observable result — round 4's words, verified by reading — is
that *corrected prose can retain old failures, lose new failures, and lose them
again after restart*. Correction is a `replaced_by` (DD-2), and `replace()` on a
dataclass is the opposite of that: it silently keeps what it is not told to
change.

**Six structures compare loaded key sets for EXACT equality** (#3, #4, #5, #6,
#10, #11). Adding a field to the writer without every reader is not a soft
degradation — it raises on the next projection or resume. Writers and *all*
readers of one record must land in one commit, with a test that loads a v1
record and a v2 record. v5 said three; that undercount is itself the hazard.

**Two required restart crossing tests**, not one: restart **after convergence,
before synthesis**, and restart **after synthesis, before publication**. A tool
failed in a child, the process died, the session resumed — and the published
artifact still discloses. Nothing shallower proves the durable design.



### DD-10 — Nested delegation propagates structurally, not textually

Putting a rendered child disclosure into the parent's tool output does **not**
guarantee the parent repeats it. The interception point is the raw-result hook
at `agentic_dispatch.py:1588`, before `swe_harness/tool_call.py:529` discards
tool metadata. `DelegateTaskTool` runs a separate executor
(`delegate_task_tool.py:190`), so the child is a **disjoint scope**: carry the
child's normalised facts — not a duplicated full child reply — and fold them in
with `combined_with`.

### DD-11 — The register lists SINKS; scenarios are listed separately

v3 listed routes and called it a register. v4 mixed sinks with semantic
scenarios and still missed sinks. Round 4 found four more by reading, so the
rule is now explicit:

> **A sink is one concrete write of reply text to something a human later
> reads.** An HTTP response body. A thread-store append. A channel send. A shell
> print. A published artifact. A persisted summary. Nothing else goes in the
> register — operations (`combined_with`) and test scenarios (restart-after-
> synthesis) are listed in the acceptance matrix, not here.

One route routinely holds two sinks, and a test on the wrong one passes while
the other conceals. Round 4's finds, all verified by reading:

| Route | Sink A | Sink B |
|---|---|---|
| Agent DM endpoint | thread append `agents.py:3428` | HTTP response `agents.py:3445` |
| HXI inline callsign | thread append `chat.py:513` | HTTP response `chat.py:502` |
| HXI multi-mention | per-reply append `chat.py:271` | `per_agent_replies` `chat.py:360` |
| Crew durable publication | artifact `crew_finalizer.py:2969` | **persisted summary** `:1123` / `:3103` |
| **Promoted completion** | thread append `turn_promotion.py:304` | **full human-readable artifact** `turn_promotion.py:175` |

Round 5 found four more sinks that v5 missed entirely: the promoted-completion
pair above, the work-item dispatch thread append (`cognitive_agent.py:1841`) and
the deferred replay thread append (`startup/finalize.py:2691`). **This is the
fifth consecutive round in which sinks were missed, and the reviewer explicitly
declined to claim the new count is final.** Treat the list as evidence that the
list is the wrong safeguard — the structural test is.

**The structural test cannot be constructor-based.** v4 and v5 specified
"classify the 14 literal DM `IntentMessage` constructors", and round 5 showed
that cannot see promotion at all: the promoted sink consumes a **background
task**, not a new `IntentMessage`.

**Nor can it be a provenance assertion over `str`**, and that was v6's error.
Round 6 named it precisely: *"a requirement dressed as a test."* Asking static
analysis whether a given `str` is "agent-produced reply text" that "passed
through the render helper" needs whole-program polymorphic dataflow, which this
repo's structural tests — local AST and source assertions — cannot do. The
channel path proves it: at `discord_adapter.py:247` the analyzer sees only
`chunk`.

### DD-12 — `RenderedDmText`: the boundary is NOMINAL, so the test can be static

The completeness safeguard is a **type**, not an inspection.

```python
class RenderedDmText(str):
    """The composed, Captain-visible form of a DmReply. Produced ONLY by
    ``DmReply.render()``. Every registered human egress accepts this and not
    a bare ``str``."""
```

Three layers, each cheap, none relying on dataflow analysis:

1. **Nominal** — `DmReply.render()` returns `RenderedDmText`; every registered
   egress helper is annotated to take `RenderedDmText`. A type checker rejects a
   bare `str` at the boundary. A `str` subclass, so every existing consumer of
   the value keeps working unchanged.
2. **Runtime** — each egress helper asserts `isinstance(text, RenderedDmText)`
   and raises. Defence in depth: the annotation is advisory at runtime, the
   assertion is not.
3. **Static** — an AST test enumerates the **sink primitives** (thread-store
   `append_message`, adapter sends, artifact publish, summary persist, DM route
   response construction) and fails if one is called outside a registered egress
   helper. This is a finite, syntactic call grammar, with an explicit audited
   exemption list — not a semantic claim about a string's history.

A new adapter that publishes `IntentResult.result` directly now fails layer 3 on
the sink primitive, and layers 1–2 if it routes through a helper. That is the
enforceable version of the promise DD-5 depends on.

#### DD-12 build contract — four conditions, from round 7's approval

Round 7 measured the marker's behaviour on Python 3.12.13 / Pydantic 2.12.5.
**Every transformation erodes it**: `str()`, f-strings, `.format()`, `.join()`,
slicing, `+`, `*`, `.strip()`, `.replace()`, JSON round-trip and a `str`-annotated
Pydantic field all return a plain `str`. That erosion is **fail-closed** if and
only if the guard runs on the direct result of `render()`, before anything
touches it. Approval is conditional on all four:

1. **Construction is sealed.** `RenderedDmText("plain")` currently succeeds
   (`direct_constructor|str|'plain'|RenderedDmText|True`). Construct it only as
   the final operation inside `render()` — private sentinel, or layer 3 rejects
   every `RenderedDmText(...)` outside `render()`. **Never "repair" an eroded
   value by re-wrapping it**; that converts the token into a rubber stamp.
2. **The guard raises, it does not assert.** `assert isinstance(...)` is removed
   by `python -O` — round 7 reached an egress body with a bare string that way.
   Use `if not isinstance(text, RenderedDmText): raise TypeError(...)`. No `-O`
   launch exists today, but the contract must not depend on that.
3. **The guard runs first**, before `str()`, f-strings, slicing, joins, Pydantic
   construction, JSON, or Discord chunking. Assert on entry, then transform
   freely inside the helper.
4. **Shared writers are not exempted.** `send_response` carries ordinary text
   too; route that through `DmReply(body=text).render()` as a zero-attachment
   reply, or give DM replies a genuinely separate typed primitive. Exempting the
   shared callsite would exempt the DM path with it.

**Do not annotate Pydantic response fields with the subclass.** Pydantic rejects
the model at class creation, and `arbitrary_types_allowed=True` still cannot
generate JSON Schema. `api_models.py:39` stays `str`; the typed helper runs
*before* model construction.

**Layer 1 is not independently enforceable here**, and the AD should not pretend
otherwise. Enumerated:

```
python type-check config / CI gate enumeration → NO MATCHES
(.github/workflows/ci.yml:37 runs pytest; no type checker)
```

The annotation helps Pylance and any future gate. **The guarantee comes from
layers 2 and 3 and the crossing tests.**

**Layer 3 is implementable in this repo's existing style**, verified by
prototype against the live tree — parent-map/owner assertions already exist at
`tests/test_ad1124_crew_session_contract.py:2000` and whole-tree AST enumeration
at `tests/test_layer_boundaries.py:149`:

```
append_message:           20 direct call nodes
add_version:               6 direct + 1 passed through asyncio.to_thread
publish_verified_result:   2
ChannelAdapter overrides:  7
HEAD/worktree AST delta:   0 for all three primitive sets
```

Two consequences for the scanner: it must inspect **callable references**, not
only `ast.Call` (crew publication passes `self._artifacts.add_version` to
`asyncio.to_thread`); and **exemptions must be exact call-node fingerprints**,
never file- or function-level. `routers/chat.py::chat` contains Captain, system,
ordinary-agent and DM-reply appends in one function, so a function-level
exemption would silence the DM path by accident. Exact normalized fingerprints
plus mutation tests make additions fail closed.

**Row 8 was a pseudo-sink.** `channels/base.py:204` sends an internal intent and
returns a string; the concrete human writes are the adapters downstream. Round 6
found four; round 7's AST enumeration found **seven** concrete `send_response`
overrides — Discord, Gmail, Matrix, Slack, Teams, Telegram, Webhook — of which
OSS startup instantiates Discord, Slack and webhook. So the register is **24**,
not 18, and layer 3 must enumerate **every `ChannelAdapter` subclass** and
classify each override as typed egress, no-op, or exact audited exemption —
rather than trusting a hand-written list that has been wrong seven times.

**The persisted-summary sink needs its own mechanism.** Both durable branches
store `draft.final_text[:4096]`, which crosses the projection and is read
directly by the HXI (`ui/src/components/chats/ChatsPanel.tsx:310`,
`ui/src/components/crew/CrewCollaborationPanel.tsx:382`). Round 4 executed the
exact truncation against a 5,000-character body:

```
disclosure_in_full=True
disclosure_in_persisted_summary=False
```

Blind slicing cuts the disclosure off. The fix must not reparse rendered text,
so `render()` takes an optional budget — and round 5 corrected two things about
it:

- **The budget is CHARACTERS, not bytes.** The real validator uses
  `len(normalized)` (`crew_session.py:622`), so 4,096 `é` characters are
  accepted at 8,192 UTF-8 bytes. The parameter is `max_chars=4096`, matching the
  consumer. Using bytes would be a silent stricter regression.
- **"Reserve the attachment" is not always satisfiable**, so there is a ladder,
  not a rule. 32 names at the 64-char grammar bound is 2,048 characters plus
  separators — under 4,096, but a smaller budget or a PRECISE disclosure can
  exceed it:

  | Budget vs. attachment | Behaviour |
  |---|---|
  | attachment fits, body does not | truncate the **body**, codepoint-safe, keep the whole attachment |
  | attachment does not fit | fall back to the **count-only** form (`"N tool calls failed"`) |
  | count-only does not fit | **raise** — a budget below the minimum is a caller error, not a disclosure to drop |

  Truncation cuts on **code-point** boundaries. It does not promise grapheme
  clusters: round 6 showed `"e\u0301x"[:1]` yields `"e"` and orphans the
  combining accent. Guaranteeing graphemes needs a segmentation dependency this
  AD does not add; the cut is never inside a surrogate pair, and that is the
  whole claim.


Remaining rules:

- **Render once per route per VARIANT**, and reuse across that route's sinks.
  v6 said "once per route", which round 6 showed is wrong for crew: the full
  artifact and the bounded summary are different variants of the same reply
  (`crew_finalizer.py:1010` → `:1123`). One helper returns both; neither sink
  re-renders from scratch and no sink reparses the other's output.
- The register lives beside `DmReply`; the acceptance matrix has one row per
  sink.

A sink added later that does not render is how this AD fails. **DD-12**, not
this table, is what makes that a review failure rather than a transcript
failure.



### DD-8 — Scope line: what `DmReply` carries

**It carries facts that must survive a BODY REWRITE.** It does not absorb
markers whose effect is a write into another store.

- IN: `tool_failures` (BF-773). Forward: the AD-722a emotion self-tag.
- OUT: `[TODOS]`, `<artifact>`, `[A2UI]`, `[CREATE_TASK]`, `[GEN_IMAGE]`,
  `[NOTEBOOK]`, `[ACTION]` — extraction side effects with their own stores.
- OUT: **permission denials** — AD-855's capability-gap driver already surfaces
  them by exact name (DD-1a). A denial is not a tool failure and must not be
  disclosed as one.

**Correction, and it matters.** The v1 draft justified the OUT list with "they
are not lost across paths". That is **false on HEAD**, proved by execution: the
A2UI protocol is taught to the agentic prompt (`cognitive_agent.py:3673`) while
extraction exists **only** in the reply pipeline (`reply_pipeline.py:1261`), so
the promotion and deferred bypasses both hand the Captain a raw marker and
create no widget:

```
promotion: Choose one. [A2UI]{"kind":"choice",...}[/A2UI]
deferred:  Answering your message... Choose one. [A2UI]{"kind":"choice",...}[/A2UI]
```

**Second correction:** "these markers drive side effects into their own stores"
is false for `[MESH]`, which performs a READ and folds its result back into the
reply — it is a body transform, not a side effect. So the OUT list is not a
single coherent category, and this AD should stop pretending it is. The honest
line is narrower: **`DmReply` carries facts that must survive a body rewrite.**
`[MESH]` output becomes part of the body and is carried by that; the
store-backed markers are extraction side effects whose folding into a value type
is a larger redesign than this AD should hold.

Their bypass leakage is a **real, separate defect** — file it, do not silence it.
The proportionate near-term mitigation is to gate marker *teaching* on paths
whose extraction will not run; note that promotion is decided **after** prompt
assembly, so that gate needs designing rather than asserting.

---

## Do NOT build

Named explicitly, because each is tempting and each would reproduce BF-773's
divergence at larger scale:

- **Do not** absorb the 14 in-pipeline markers into `DmReply`.
- **Do not** build AD-726a (`DmContextPrep`) or AD-726b (`DmPromptAssembler`).
  They are prompt-side and this AD does not depend on them — that false
  dependency is why the reply shape never shipped.
- **Do not** change the type of `IntentResult.result`. It stays `str`.
- **Do not** touch the group fan-out path; the conversational agentic loop does
  not run there (`_maybe_run_conversational_agentic` returns `None` for
  `is_group_chat`).
- **Do not** migrate the emotion self-tag in this AD. Land the shape first;
  move `<intent emotion=…>` onto it as a follow-up so the two changes are
  separately reviewable.
- **Do not** fix the AD-1230 deferred self-tag leak here. File it.
- **Do not** absorb the pre-existing `_tool_trace_ref` cache-staleness defect
  (DD-7) as an unremarked side effect. It is fixed by the same exclusion, and it
  is filed separately so the fix is attributable.

---

## Acceptance criteria

1. `DmReply(body=x).render() == x` for arbitrary `x`, property-tested.
2. `with_body()` preserves attachments; a transformer chain that rewrites the
   body three times still renders every attachment exactly once.
3. **Two degradation invariants**, not one (DD-5): a *malformed* reconstruction
   never carries non-empty attachments and logs; a *valid but oversize* one
   still renders a non-empty disclosure — count-only in the worst case.
   Both directions tested, because v3 had only the first and it deleted a real
   failure at 65 entries.
4. **A crossing test per SINK** (DD-11), each asserting a failed tool reaches
   the Captain-visible text. Sinks, not routes and not operations — rounds 3 and
   4 proved one route holds two sinks in four separate places:

   | # | Sink | Site |
   |---|---|---|
   | 1 | Inline DM — thread append | `agents.py:3428` |
   | 2 | Agent DM endpoint — HTTP response | `agents.py:3445` |
   | 3 | HXI chat — HTTP response | `routers/chat.py:216` |
   | 4 | HXI inline callsign — HTTP response | `routers/chat.py:502` |
   | 5 | HXI inline callsign — thread append | `routers/chat.py:513` |
   | 6 | HXI multi-mention — per-reply append | `routers/chat.py:271` |
   | 7 | HXI multi-mention — `per_agent_replies` | `routers/chat.py:360` |
   | 8 | Channel adapter — **Discord** send | `channels/discord_adapter.py:247` |
   | 9 | Channel adapter — **Slack** send | `channels/slack_adapter.py:156` |
   | 10 | Channel adapter — **Matrix** send | `channels/matrix_adapter.py:96` |
   | 11 | Channel adapter — **Telegram** send | `channels/telegram_adapter.py:97` |
   | 12 | Channel adapter — **Gmail** send | `ChannelAdapter` override |
   | 13 | Channel adapter — **Teams** send | `ChannelAdapter` override |
   | 14 | Channel adapter — **Webhook** send | `ChannelAdapter` override |
   | 15 | Shell session print | `experience/commands/session.py:110` |
   | 16 | Crew room post | `crew_executor.py:2534` |
   | 17 | Crew synthesis — durable **live** artifact | `crew_finalizer.py:2969` |
   | 18 | Crew synthesis — durable **resume** artifact | `crew_finalizer.py:942` → `:1075` |
   | 19 | Crew — persisted **bounded summary**, live | `crew_finalizer.py:3103` |
   | 20 | Crew — persisted **bounded summary**, resume | `crew_finalizer.py:1123` |
   | 21 | Work-item dispatch — thread append | `cognitive_agent.py:1841` |
   | 22 | Promoted completion — thread append | `turn_promotion.py:304` |
   | 23 | Promoted completion — full artifact | `turn_promotion.py:175` |
   | 24 | Deferred replay — thread append | `startup/finalize.py:2691` |

   **24 is not asserted to be final.** Sinks were missed in every one of seven
   review rounds — `channels/base.py:211` was itself a pseudo-sink until round 6
   traced past it to four adapters, and round 7 then found seven. The
   completeness guarantee is criterion 7 (DD-12), not this table.

   **Legacy synthesis is NOT a sink.** v4's row 20 was wrong: its owner callback
   discards `task.result()` (`crew_orchestrator.py:323-333`), so there is no
   in-tree Captain sink. Round 4's AST enumeration:

   ```
   maybe_dispatch_crew:        defs=1, calls=0
   run_crew_task:              defs=1, calls=1 (internal owner call)
   CrewSynthesizer.synthesize: calls=1
   CrewSynthesizer.resume:     defs=0, calls=0
   forward_direct_message:     defs=1, calls=0
   ```

   Legacy must still *carry* the facts (it feeds structures DD-9 lists), but it
   gets no sink row until it has a real publication path.

   **Directed federation is not a sink either** (DD-5): the origin reconstructs
   an `IntentResult` (`federation/bridge.py:1271`) and a *local* sink displays
   it. It is a metadata-carriage requirement, tested by criterion 5.

5. **A crossing test per SEMANTIC SCENARIO** — these are behaviours, not sinks,
   and v4 wrongly mixed them into the register:

   | # | Scenario | Semantics |
   |---|---|---|
   | S1 | AD-724-1 sanity retry | `replaced_by` |
   | S2 | AD-934 deliberate re-roll | `with_body` |
   | S3 | AD-1164 continuation / reinvoke | `superseded_by` |
   | S4 | **AD-1155 crew outer loop**, pass 1 fails, pass 2 does not retry | `superseded_by` |
   | S5 | AD-1165 promotion — fast branch | carriage |
   | S6 | AD-1165 promotion — promoted branch | carriage |
   | S7 | AD-1230 deferred replay | carriage |
   | S8 | Work-item dispatch | carriage |
   | S9 | `DelegateTaskTool` nested | `combined_with`, disjoint scopes |
   | S10 | Convergence correction — session | `replaced_by`, both directions |
   | S11 | Convergence correction — legacy | `replaced_by` |
   | S12 | Restart **after convergence, before synthesis** | durability |
   | S13 | Restart **after synthesis, before publication** | durability |
   | S14 | Sibling A fails, B succeeds, **identical tool arguments** | scope isolation |
   | S15 | SUMMARY-state value then superseded | disclosure retained, logged |
   | S16 | Bounded-summary render at 4096 **chars** | attachment survives, body truncates |
   | S17 | Attachment alone exceeds the budget | count-only fallback |
   | S18 | Budget below the count-only minimum | raises |
   | S19 | Pass 1 delegates to child-A and fails; pass 2 supersedes | child-A retained, own scope cleared |
   | S20 | `superseded_by` on a **merge-closed** value | raises `ToolFailuresMergeClosed` |
   | S21 | An **MCP-aliased** tool fails | the offered alias renders, never the registry id (DD-1a) |
   | S22 | A tool name absent from the offered set fails | `UNKNOWN_TOOL_LABEL`, not a fabricated name |
   | S23 | A **permission denial**, gap driver healthy | not disclosed as a tool failure |
   | S24 | A **permission denial**, gap driver degraded | still not disclosed — one event, one report |

   **Deliberately excluded**, from the 14-constructor enumeration: qualification
   probes, pacing follow-ups, the Yeoman digest broadcast, proactive vision, and
   group fan-out — their results are internal or discarded, or the agentic path
   is gated off. Recorded here so the exclusion is a decision, not an omission.

   **The generic DAG checkpoint is not on any DM route** — writers confined to
   `DAGExecutor` (`decomposer.py:746`). Determined, not deferred.
6. `IntentResult` round-trips a `DmReply` through `_serialize_result` /
   `_deserialize_result` with attachments intact, and across
   `_serialize_directed_result` → `_finalize_directed_result_for_origin`.
7. **DD-12's three layers, all present**: `DmReply.render()` returns
   `RenderedDmText`; every registered egress helper is annotated to take it and
   asserts `isinstance` at runtime; and an AST test enumerates the **sink
   primitives** and fails if one is called outside a registered helper, with an
   explicit audited exemption list. A semantic "this string passed through the
   renderer" assertion is **not** acceptable — round 6 showed it is not statically
   decidable, since at `discord_adapter.py:247` the analyzer sees only `chunk`.
   Import aliases must resolve (`_IntentMessage`).
8. `ToolFailures` is genuinely immutable: mutating the mapping passed to the
   constructor does not change the value. (Round 3 broke the v3 shape this way.)
   A payload carrying **both** wire states is rejected as malformed, not
   reconciled. (Round 4 broke the v4 shape this way.) And a merge-closed value
   raises on `superseded_by` rather than silently retaining. (Round 5 broke the
   v5 shape this way.)
9. `_owned_tail_span`, `_DISCLOSURE_TAIL_RE`, `recanonicalise_disclosure`,
   `ensure_tool_failure_disclosure`, `_reads_as_a_capability_gap` and
   `step_7a_tool_failure_disclosure` do not exist in the tree, and
   `_full_steps()` is **20** entries / **34** assignments — both unchanged from
   clean HEAD. A **regression guard**: this AD adds no pipeline stage and no
   assignment site.
10. Mutation matrix over every new guard, all killed, tree restored
    byte-identical. Every survivor is a missing crossing test, not an accepted gap.
11. Full gate green and reconciled exactly against the prior baseline.
12. Verify all changes comply with the Engineering Principles in
    `.github/copilot-instructions.md`.

---

## Build in three SEQUENTIAL slices

One architectural decision, three landings. These are **sequential dependencies,
not independently revertible in arbitrary order** — v2 claimed otherwise and was
wrong. And **BF-773 closes at the end of C**, not B: until crew synthesis and
delegation carry the facts, a failed tool is still concealed on those surfaces.

**Slice A must contain a real producer AND every path that would otherwise
conceal.** Round 4 built a blocker on `cognitive_agent.py:4227` "rendering
disclosure into the body today" — that is the staged BF-773 diff, which this AD
discards (see *The baseline*), and round 5 confirmed the correction by
enumeration. At clean HEAD there is no legacy producer, no legacy consumer, and
no rendered sentence to migrate.

**Slice A also owns DD-12's boundary type**, because it decides the signature of
every egress helper. Deferring it would let slice B register helpers taking bare
`str` and then re-sign them in C — the wrong boundary, established early, which
is round 6's reason for holding the design.

**A second `IntentResult` boundary exists in A's scope.** Work-item dispatch
constructs its own envelope after either `_run_agentic_dispatch` or the fallback
`handle_intent()` (`cognitive_agent.py:1830`–`:1895`), so A must reconstruct the
fallback reply before metadata is flattened and serialize that outer envelope
too. "The single `IntentResult` site" is true of the conversational path only.

| Slice | Content | Gate to advance |
|-------|---------|-----------------|
| **A — value, wire, boundary type, producer, and the paths that would conceal** | `DmReply`, `ToolFailures` (lineage keys, merge-open/closed as an orthogonal bit, tagged wire union, defensive copy), the four DD-2 operations incl. scoped supersession and summary algebra, the DD-5 schema + degradation rules, `render(max_chars=)` ladder, **`RenderedDmText` + DD-12 layers 1–3 + its four-condition build contract**, `types.py` amendment, DD-6 context migration (27 constructors), DD-7 threading + **both** `IntentResult` boundaries + cache exclusion, the real producer, `_agentic_turn` + promotion + deferred replay, sinks 1–2 and 21–24 | Zero-attachment byte-identity; sinks 1–2, 21–24; scenarios S5–S8, S15–S18, S20–S24, and a **synthetic** S19 algebra test; sealed construction and `-O`-proof guard proved by mutation; full gate reconciled |
| **B — the remaining DM sinks and the turn algebra** | DD-2 sites S1–S3, sinks 3–15, the DD-11 register, layer-3 classification of **all seven** `ChannelAdapter` overrides | Sinks 3–15; S1–S3; `_full_steps()` still 20 entries / 34 assignments |
| **C — work-item, crew, delegation, synthesis** | DD-9's eleven durable structures (six exact-key-set readers), DD-10 nested propagation, sinks 16–20, scenarios S4, S9–S14, and the **real** S19 crossing test | Sinks 16–20; S4, S9–S14, S19, including both restart tests and the identical-arguments sibling |

S19 is deliberately split: the *algebra* (scoped supersession retains a
disjoint child scope) is provable in A against a synthetic value, but the real
pass → delegate → supersede crossing test needs DD-10, which lands in C. v6
gated A on the crossing test and could not have passed.

Slice A carries vertical sinks deliberately: a value type with no producer and
no consumer is dead production code, and this repo has enough of that.

---

## Risks

- **The sink register has been incomplete in all seven review rounds.** v3 had
  19 routes, v4 22 mixed rows, v5 14 sinks, v6 18, v7 21 then 24 — and one of the
  "sinks" was a pseudo-sink hiding seven real ones. The list has never been
  right, which is precisely why DD-12 makes the safeguard a **type** rather than
  a list. Read the table as evidence of the hazard, not coverage of it.
- **DD-12 is the load-bearing safeguard, and layer 1 does not enforce itself.**
  There is no Python type checker in CI (`.github/workflows/ci.yml:37`), and
  every string transformation erodes the marker. The guarantee is layers 2 and 3
  plus the crossing tests. If the guard becomes an `assert`, or construction is
  unsealed, or an eroded value is ever re-wrapped, the token becomes a rubber
  stamp and the whole design degrades to the convention it replaced.
- **The exemption list is the other way DD-12 fails.** Exemptions must be exact
  call-node fingerprints; `routers/chat.py::chat` alone holds four different
  kinds of append, so one function-level exemption would silence the DM path by
  accident.
- **Three deliberate over-disclosures.** A SUMMARY value cannot be cleared; a
  merge-closed value raises rather than guesses; and a delegated child's failure
  is retained across a pass that may have redone it successfully (delegation
  identity is not stable across passes — `delegate_task_tool.py:179` carries only
  depth). All three err toward telling the Captain too much. That is the chosen
  direction, but it is a real cost and a later AD may want the lineage field the
  key now carries.
- **DD-1's "no merge crosses the wire" is enforced, not assumed** — a
  merge-closed value raises on either operand. Round 5 verified the precondition
  holds at HEAD, and round 6 verified it specifically across a durable crew
  resume: reconstructed children flow to finalizer resume
  (`crew_orchestrator.py:455`), never back into the AD-1155 outer loop.
- **Six durable readers compare key sets for exact equality.** A writer/reader
  split across commits raises on the next projection or resume. Slice C is the
  highest-risk landing in this AD, and v5's undercount of three is exactly the
  shape of the failure.
- **The DD-8 boundary has moved twice under review** — first the "not lost"
  justification, then the `[MESH]` mis-classification. Least settled part of the
  design; re-derive it before slice C.
- **24 sinks + 24 scenarios + 11 durable structures is the real cost**, not the
  type. That is deliberate: this defect class is *defined* by paths nobody
  tested, so the tests are the deliverable and the type is the enabler.
- **A new fact could still be added as a marker** rather than a field. Nothing
  structurally prevents it; the honest mitigation is that once the parsing
  machinery is gone, the field is the path of least resistance.
- **Slice A is a shared-contract change**, not a refactor: `types.py:88`, 27
  context constructors, DD-7 threading, DD-12's egress signatures, and six
  delivery paths. Review it as a contract change.
