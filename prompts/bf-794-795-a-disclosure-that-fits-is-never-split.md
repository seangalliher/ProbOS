# BF-794 + BF-795: a disclosure that fits is never split, and the episode keeps the facts

**Status:** Ready to build
**Issues:** #1258 (BF-794), #1259 (BF-795)
**Dependencies:** AD-1248 (`DmReply`), BF-802 (`split_for_wire`), AD-1293 (`self_contradicted_channels` precedent) — all landed at `90616db2`
**New AD number consumed:** none. These are bug fixes against shipped ADs; the BF numbers are already allocated by the issue titles. (AD ceiling at time of writing: **AD-1295**, next free **AD-1296**.)
**Estimated tests:** ~14 new
**Commits:** TWO. Slice 1 and Slice 2 touch different layers and must be independently revertible.

---

## Summary

Two AD-1248 follow-ups. Both filed issues state a real problem and propose a fix that does
not work. This prompt builds the fixes that do.

| | Filed as | Actually |
|---|---|---|
| **BF-794** | Telegram naively slices; use `render(max_chars=)`; needs a 7-adapter seam change | Telegram already routes through the lossless `split_for_wire`. The cut-inside-the-disclosure defect is **real and measured**, but the fix is a boundary rule **inside `split_for_wire`** — no seam change, and it fixes Discord (the worse case) for free |
| **BF-795** | Episode misses the disclosure because composition runs after `step_5` | True, but composing earlier **would not fix it**: `step_5` stores `response_text[:500]` and the disclosure is a *tail*. Store the structured facts instead |

---

## Slice 1 — BF-794: a disclosure that fits in one message is never split

### Problem

`split_for_wire` ([dm_reply.py](../src/probos/dm_reply.py#L731)) is exactly lossless —
`"".join(split_for_wire(t, n)) == t`. Nothing is destroyed. The defect is **fragmentation
at the worst possible place**: the boundary lands *inside* the composed disclosure, so
message 1 ends mid-sentence and message 2 carries a 6-character orphan.

The mechanism is the `cut < limit // 2` guard at
[dm_reply.py](../src/probos/dm_reply.py#L770). The disclosure is preceded by
`_DISCLOSURE_PREFIX = "\n\n"` ([dm_reply.py](../src/probos/dm_reply.py#L707)) and contains
no newline, so that `\n\n` is the last newline in the whole text and is exactly the right
boundary. When the body is short and the disclosure is long, that boundary falls below
`limit // 2`, the guard **rejects it**, control falls through to the space search — and the
disclosure is full of `", "` separators, so the cut lands inside it.

Measured at `90616db2`, sweeping name-count × name-length × body-length:

```
discord  (limit 2000)  FIXABLE cuts = 7055   UNFIXABLE = 3600
telegram (limit 4096)  FIXABLE cuts =   91   UNFIXABLE =    0

discord : 15 names x 64 -> rendered=2002 body=948 disc=1052 parts=[1996,    6]
telegram: 31 names x 64 -> rendered=4098 body=1988 disc=2108 parts=[4092,   6]
```

*FIXABLE* = the disclosure fits within one message and is split anyway. *UNFIXABLE* = the
disclosure alone exceeds the wire limit (`_MAX_NAMES = 32` × 64-char names = 2,174 chars >
Discord's 2,000); no boundary placement can fit it and no chunking strategy can.

**Reachability.** The cut requires `len(disclosure) > limit / 2`. Discord needs a
>1,000-character disclosure (≈15 distinct 64-char names, or ≈25 × 38); AD-1019c rewrites MCP
ids to `mcp_{server}_{tool}_{16hex}`, which genuinely approaches the 64-char `_NAME_RE`
ceiling, so an MCP server outage failing 15+ distinct tools in one turn reaches it. Telegram
needs >2,048 characters — essentially the maximum disclosure the system can emit. **Discord
is the reachable channel; the issue is titled Telegram.** One splitter serves both.

### Why the filed fix is rejected

`render(max_chars=)`'s three-tier ladder **truncates the body** to keep the disclosure whole.
That is the right trade for a sink that can send only one message and must choose. It is the
wrong trade here: chunking delivers every part, so the body text the ladder would discard was
going to arrive in the next message anyway. Applying it at a chunk boundary destroys the
agent's words to protect a note that was not at risk. **Do not use it.**

The seam change (`send_response` accepting `DmReply | str` across seven adapters) is also
unnecessary. It was proposed on the premise that placement needs to know where the disclosure
is. It does not: the disclosure's own `\n\n` already marks the boundary, and the splitter was
merely declining to use it.

### The fix

Accept an early newline boundary when it is the **last newline in the text** and everything
after it fits in one piece. That is precisely the structural-tail case.

Two formulations were measured. Both eliminate every fixable cut; the narrow one perturbs
ordinary prose 12× less, so build the narrow one:

```
BROAD  (remainder fits)                    fixable=0  prose changed=12/12000
NARROW (remainder fits AND last newline)   fixable=0  prose changed= 1/12000   <-- build this
```

`split_for_wire` stays disclosure-agnostic — it must not import or mention `DmReply`,
`_DISCLOSURE_PREFIX`, or tool failures. This is a boundary-quality improvement that happens to
guarantee the property.

### Section 1.1 — `src/probos/dm_reply.py`

```
===SEARCH===
        # +1 keeps the delimiter with the piece being emitted, so nothing is
        # dropped and the FOLLOWING piece does not start with the boundary.
        cut = text.rfind("\n", 0, limit)
        cut = cut + 1 if cut != -1 else -1
        if cut <= 0 or cut < limit // 2:
            space = text.rfind(" ", 0, limit)
            cut = space + 1 if space != -1 else -1
        if cut <= 0 or cut < limit // 2:
            cut = limit  # hard cut; >= 1, so progress is guaranteed
===REPLACE===
        # +1 keeps the delimiter with the piece being emitted, so nothing is
        # dropped and the FOLLOWING piece does not start with the boundary.
        newline = text.rfind("\n", 0, limit)
        cut = newline + 1 if newline != -1 else -1
        # BF-794 (#1258): an early newline is still the right boundary when it
        # is the LAST one and what follows fits in a single piece. Rejecting it
        # for being early sent a short-body/long-tail reply to the space search,
        # which cuts inside the tail because the tail is full of separators --
        # 7,055 such cuts at Discord's 2,000 limit.
        tail_fits = newline != -1 and newline == text.rfind("\n") and len(text) - cut <= limit
        if cut <= 0 or (cut < limit // 2 and not tail_fits):
            space = text.rfind(" ", 0, limit)
            cut = space + 1 if space != -1 else -1
        if cut <= 0 or cut < limit // 2:
            cut = limit  # hard cut; >= 1, so progress is guaranteed
===END REPLACE===
```

Then extend the docstring's adversarial-review bullet list with a third bullet in the same
voice, recording the BF-794 defect and that losslessness and termination are unchanged.

### Slice 1 tests — `tests/test_bf794_disclosure_survives_the_wire_split.py` (new)

1. `test_disclosure_that_fits_within_the_limit_is_never_split` — the load-bearing one.
   Sweep `nnames` 1..32 × `nlen` in (8, 16, 32, 48, 64) × body 0..limit+400 step 2, for
   limits 2000 and 4096. Build via `DmReply(body=..., tool_failures=...).render()`, locate the
   tail by `len(text) - len(disclosure)`, assert no cumulative piece offset falls strictly
   inside it **whenever `len(disclosure) + 2 <= limit`**.
   **The test must assert its own premise:** first run the same check against the pre-fix
   boundary rule (inline a local copy) and assert it finds >0 cuts. A sweep that cannot
   detect the defect proves nothing — this is exactly how the first analysis of this issue
   reached the wrong answer with 36,240 green cases.
2. `test_a_disclosure_larger_than_the_limit_is_still_split_losslessly` — pins the UNFIXABLE
   case as accepted behaviour, not a latent bug: 32 × 64 names on Discord, assert the join is
   exact and no piece exceeds the limit.
3. `test_split_is_lossless_and_terminates_for_random_text` — extend/mirror the existing
   round-trip property from [test_bf802_adapter_egress.py](../tests/test_bf802_adapter_egress.py#L149).
4. `test_ordinary_prose_boundary_choice_is_effectively_unchanged` — random prose corpus;
   assert ≥99% of `(text, limit)` pairs split identically to the pre-fix rule, and that every
   result is lossless and within limit. Documents the 1/12000 perturbation as intended.
5. `test_telegram_and_discord_share_one_splitter` — assert
   `discord_adapter._chunk_message(body) == split_for_wire(body, 2000)` and that
   [telegram_adapter.py](../src/probos/channels/telegram_adapter.py#L124) calls
   `split_for_wire`, so the fix provably reaches both sinks.

---

## Slice 2 — BF-795: the episode carries the facts, not a rendering

### Problem

[reply_pipeline.py](../src/probos/cognitive/dm/reply_pipeline.py#L1931) stores:

```python
"response": self.ctx.response_text[:500],
```

`ctx.response_text` is a property over `ctx.reply.body`
([reply_pipeline.py](../src/probos/cognitive/dm/reply_pipeline.py#L127)), and the AD-1248
disclosure is composed later at
[reply_pipeline.py](../src/probos/cognitive/dm/reply_pipeline.py#L2067)
(`self.ctx.reply.render()`). So the episode records the bare body. The issue is right.

**But the implied fix does not work.** `[:500]` truncates from the *front*; the disclosure is
a *tail*. Composing before `step_5` would still drop it for every reply longer than 500
characters — which is most of them. Verify this before building anything else.

Two further reasons not to store the rendered text: the disclosure is composed *per route per
variant* (the HTTP route renders at `:2067`; the channel route renders separately and prefixes
a callsign at [base.py](../src/probos/channels/base.py#L231)), so there is no single rendering
an episode could store; and `outcomes[0]["response"]` is consumed as *what the agent said* by
[procedures.py](../src/probos/cognitive/procedures.py#L1404),
[importance_scorer.py](../src/probos/cognitive/importance_scorer.py#L87) and
[episodic.py](../src/probos/cognitive/episodic.py#L1652).

The concern behind the issue is nonetheless real and is the AD-1248 failure mode one layer
deeper: `procedures.py` synthesises procedures from stored responses, so a reply that reads
"I fetched the versions" after a failed fetch teaches the mesh a falsehood about its own
capability.

### The fix

Store the **structured facts the disclosure was composed from**, so the episode and the reply
agree by construction without pinning a channel-specific rendering. `ctx.reply.tool_failures`
is already on the context at `step_5` — no seam change.

This is exactly the AD-1293 shape: `self_contradicted_channels`
([types.py](../src/probos/types.py#L655)) is a first-class `Episode` field carrying what the
turn's own record says it did not accomplish, stamped at encode time and deliberately outside
`compute_episode_hash` ([episodic.py](../src/probos/cognitive/episodic.py#L1038) — note
`outcomes` *is* hashed; the integrity fields are not). Follow it.

**Two fields, not one.** `failed_call_count` is not derivable from `names()`: two failed
`web_search` calls are two failures and one name, which is documented on the property itself
and was the original AD-1248 count bug. Storing only names would re-introduce it.

### Section 2.1 — `src/probos/types.py`, after `self_contradicted_channels` (L655)

Add to `Episode`:

```python
    # BF-795 (#1259): the facts the AD-1248 egress disclosure is composed from,
    # stamped at encode time. NOT the rendered tail -- that is composed per
    # route per variant, so no single rendering is the episode's to keep, and
    # ``outcomes[0]["response"]`` is front-truncated at 500 chars while the
    # disclosure is a tail. Empty = "this turn disclosed no tool failure",
    # which is what the Captain-visible reply also said.
    failed_tool_names: list[str] = field(default_factory=list)
    # Not derivable from the names above: two failed calls to one tool are two
    # failures and one name (``ToolFailures.failed_call_count``).
    failed_tool_call_count: int = 0
```

Both stay **out of** `compute_episode_hash` — adding them would invalidate every stored
episode's hash and trigger a mass auto-heal, the reason given for `correlation_id` at
[episodic.py](../src/probos/cognitive/episodic.py#L3560-L3565).

### Section 2.2 — `src/probos/cognitive/episodic.py` encode (after L3578)

Add beside `self_contradicted_json`, same JSON-string convention:

```python
            # BF-795 (#1259): AD-1248 disclosure facts, scalar metadata only.
            "failed_tool_names_json": json.dumps(ep.failed_tool_names or []),
            "failed_tool_call_count": int(ep.failed_tool_call_count),
```

### Section 2.3 — `src/probos/cognitive/episodic.py` decode (after the `self_contradicted` block, L3710-3718)

Mirror that block exactly — parse defensively, non-list and malformed JSON both degrade to
`[]` / `0`, pre-BF-795 episodes lack the keys and default cleanly. Then pass both to the
`Episode(...)` construction beside `self_contradicted_channels=self_contradicted` (L3756).

### Section 2.4 — `src/probos/cognitive/dm/reply_pipeline.py`, `step_5_episodic_store` (L1898)

Read the facts off `ctx.reply` next to the existing AD-1293 ledger read, and pass both to
`Episode(...)` beside `self_contradicted_channels`. Tier-2: this step is already inside a
broad `try/except` that logs and drops — do not add a second one, and do not let a missing
`tool_failures` raise.

**Leave `"response": self.ctx.response_text[:500]` exactly as it is.**

### Slice 2 tests — `tests/test_bf795_episode_carries_the_tool_facts.py` (new)

Model on [test_ad1293_turn_record_reaches_episode.py](../tests/test_ad1293_turn_record_reaches_episode.py),
which already has the recording-`episodic_memory` fixture and drives
`step_5_episodic_store()` directly.

1. `test_a_failed_tool_reaches_the_episode_as_facts` — ctx whose `reply.tool_failures` names
   `web_search`; assert the stored `Episode.failed_tool_names == ["web_search"]` and
   `failed_tool_call_count == 1`.
2. `test_two_failures_of_one_tool_are_two_calls_and_one_name` — the count/name distinction.
3. `test_a_clean_turn_stores_empty_facts` — no failures ⇒ `[]` and `0`, never `None`.
4. `test_the_rendered_disclosure_is_not_stored_in_the_response` — assert the stored
   `outcomes[0]["response"]` does **not** contain `"could not complete this using"`. Pins the
   decision: the episode keeps facts, not a rendering.
5. `test_facts_survive_the_metadata_round_trip` — **the half-chain test, mandatory.**
   `_episode_to_metadata` → `_metadata_to_episode` and assert both fields come back equal.
   A field that encodes but does not decode is inert and indistinguishable from working.
6. `test_pre_bf795_metadata_rehydrates_with_empty_facts` — metadata dict with neither key.
7. `test_malformed_facts_metadata_degrades_to_empty` — `"not json"`, `'{"a":1}'`, `None`.
8. `test_episode_hash_is_unchanged_by_the_new_fields` — same `compute_episode_hash` with and
   without them populated. Guards the mass auto-heal.
9. `test_step_5_still_stores_when_tool_failures_is_absent` — a ctx whose reply lacks the
   attribute must not raise and must still store the episode.

---

## What this does NOT change — do not build

- **Do not change `ChannelAdapter.send_response`.** It stays `(channel_id: str, response: str, **kwargs)`
  across all seven implementors ([base.py](../src/probos/channels/base.py#L70)). No
  `DmReply | str` union, no seam change, no return-type change to
  `_handle_callsign_resolved`. Slice 1 makes it unnecessary.
- **Do not write `DmReply.render_chunks()`.** It was written and deleted during BF-802 for
  having no production caller; it never entered any ref. Slice 1 removes the need.
- **Do not use `render(max_chars=)` in any adapter.** Rejected above with reasons.
- **Do not touch the five non-chunking adapters** (slack, teams, gmail, matrix, webhook).
  They do not call `split_for_wire` and have no wire limit wired. Whether they need one is a
  separate question and is not this fix.
- **Do not attempt to fix the UNFIXABLE case** (disclosure alone exceeds the wire limit). It
  is unfixable by chunking; the split stays lossless, so every name still reaches the Captain
  across two messages. Bounding `_MAX_NAMES` per channel is a separate decision.
- **Do not compose the AD-1248 disclosure earlier in the pipeline**, and do not move
  `build_response()`'s render. The single-composition-point property is AD-1248's core
  invariant.
- **Do not change `"response": self.ctx.response_text[:500]`** — neither the slice nor the
  bound.
- **Do not harmonise the two disclosure mechanisms.** AD-1285's write-claim disclosure *does*
  reach the episode body, because `step_4m` mutates `response_text`
  ([reply_pipeline.py](../src/probos/cognitive/dm/reply_pipeline.py#L1887-L1889)) before `step_5`,
  while AD-1248's does not. That asymmetry is real and deliberate — AD-1285 rewrites the
  reply, AD-1248 composes at egress. Note it; do not unify it here.
- **Do not add `split_for_wire` knowledge of `DmReply`.** It stays a generic string splitter.
- **Do not touch group-chat or federation episode paths.**

---

## Tracking

- `PROGRESS.md` — CLOSED entries for BF-794 and BF-795, one line each.
- `docs/development/roadmap.md` — Bug Tracker rows for both.
- `DECISIONS.md` — **one** entry recording the two design decisions and the rejected
  alternatives: (a) the wire split is fixed at the boundary rule, not the egress contract, and
  `render(max_chars=)` is explicitly wrong for a lossless sink; (b) the episode stores AD-1248
  facts, not a rendering, because composition is per-route-per-variant and `response` is
  front-truncated.

---

## Acceptance criteria

1. The measured sweep reports **0 fixable mid-disclosure cuts** at limits 2000 and 4096, down
   from 7,055 and 91.
2. `split_for_wire` remains exactly lossless and terminating for every input; no piece exceeds
   `limit`; `limit <= 0` still raises.
3. The premise-assertion in Slice 1 test 1 fails loudly if the pre-fix rule is substituted.
4. `split_for_wire` contains no reference to `DmReply`, `_DISCLOSURE_PREFIX`, or tool failures.
5. `Episode.failed_tool_names` / `failed_tool_call_count` survive a
   `_episode_to_metadata` → `_metadata_to_episode` round trip.
6. `compute_episode_hash` output is unchanged by the two new fields.
7. Pre-BF-795 metadata and malformed values rehydrate to `[]` / `0` without raising.
8. `outcomes[0]["response"]` still contains no rendered disclosure.
9. `step_5_episodic_store` still stores an episode when `tool_failures` is absent or raises.
10. Two commits, in order: Slice 1 (`BF-794 (#1258)`), then Slice 2 (`BF-795 (#1259)`). Each
    passes its focused tests alone. One broad gate covers the pair.
11. Adversarial review (`Diff Reviewer`, different model than the author) runs on each staged
    diff, and its findings are addressed before commit.
12. Full gate via the canonical wrapper:
    `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label bf794-bf795`
13. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Verified Against Codebase (2026-08-31, HEAD `90616db2`)

```
src/probos/dm_reply.py
   132: _NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
   150: _MAX_NAMES = 32
   707: _DISCLOSURE_PREFIX = "\n\n"
   731: def split_for_wire(text: str, limit: int) -> list[str]:
   768:         cut = text.rfind("\n", 0, limit)
   770:         if cut <= 0 or cut < limit // 2:
   771:             space = text.rfind(" ", 0, limit)
   773:         if cut <= 0 or cut < limit // 2:
   774:             cut = limit  # hard cut; >= 1, so progress is guaranteed
   798:     def render(self, *, max_chars: int | None = None) -> RenderedDmText:

src/probos/types.py
   617: class Episode:
   655:     self_contradicted_channels: list[str] = field(default_factory=list)

src/probos/cognitive/episodic.py
  1038:         "outcomes": episode.outcomes,          # outcomes IS hashed
  3565:             "correlation_id": ep.correlation_id or "",   # the not-in-hash precedent
  3578:             "self_contradicted_json": json.dumps(ep.self_contradicted_channels or [])
  3710:         self_contradicted_raw = metadata.get("self_contradicted_json", "")
  3756:             self_contradicted_channels=self_contradicted,  # AD-1293 (#1200)

src/probos/cognitive/dm/reply_pipeline.py
   127:     reply: DmReply
   171:     tool_invocations: ToolInvocations | None = None
  1887:             self.ctx.response_text = (          # AD-1285 mutates the body
  1888:                 self.ctx.response_text + disclosure_for(verdict)
  1898:     async def step_5_episodic_store(self) -> None:
  1919:                     self_contradicted_channels=self_contradicted,  # AD-1293 (#1200)
  1931:                         "response": self.ctx.response_text[:500],
  2067:             "response": self.ctx.reply.render(),

src/probos/channels/base.py
    70:     async def send_response(
    71:         self, channel_id: str, response: str, **kwargs: Any
   231:         rendered = DmReply.from_intent_result(result).render()

src/probos/channels/telegram_adapter.py
   124:         parts = split_for_wire(response, _MAX_MESSAGE_LENGTH)   # 4096

src/probos/channels/discord_adapter.py
    23: _MAX_MESSAGE_LENGTH = 2000
    37:     return split_for_wire(text, limit)
```

**Absence verified (2026-08-31).**

```
CLAIM: no adapter other than discord/telegram chunks outbound text
RUN:   grep -rn "split_for_wire" src/probos/channels/
FOUND: discord_adapter.py:19,32,37 ; telegram_adapter.py:28,124  -- only these two
HOLDS: yes

CLAIM: a tool name cannot carry a newline, so the disclosure has no internal newline
RUN:   read offered_display_name (cognitive/dm/reply_value.py:58) and
       ToolFailures.from_wire (dm_reply.py:487,492,530)
FOUND: local path collapses any name not in the offered set to UNKNOWN_TOOL_LABEL
       ("an unrecognised tool"); the wire path applies _NAME_RE = ^[A-Za-z0-9_-]{1,64}$
HOLDS: yes -- both entry paths block it, which is why the "\n\n" prefix is always the
       LAST newline and the narrow rule is exact
```

**Measurement provenance.** Both sweeps in this prompt were run against `90616db2` with
`d:/ProbOS/.venv/Scripts/python.exe`. Each asserted its own premise before trusting a
negative: the Slice 1 sweep first reproduced the reported Discord headline case
(`32 names x 64, body="" -> rendered 2176, parts [1948, 228]`) and refused to run otherwise.
An earlier 36,240-case sweep of this same question returned **0 cuts and was wrong** — it
never exercised the many-names regime where the defect lives. Re-derive with the full name
space, or do not re-derive.
