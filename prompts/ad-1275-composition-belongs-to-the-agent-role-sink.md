# AD-1275 / BF-806: composition belongs to the agent-role sink

**Issue:** #1270 (OPEN) · **Repo:** OSS `d:\ProbOS`, branch `main`
**BF:** BF-806 — already allocated by the issue.
**Status:** rev 2, ready to build · **Estimated tests:** 18–24 across two slices
**Slice A alone does NOT close #1270.** See *Closure* at the foot of this file.

## Numbering — why this is not AD-1283

The ceiling moved since rev 1. Enumerated 2026-08-28, from the three sources the standing rule
names — **not** from `docs/development/open-ads-report.md` or `ad-ledger-snapshot.json`:

| Source | Highest |
|---|---|
| `git log --all --format='%s'` subjects | **AD-1282** (`7edf309e`); AD-1278 is `d5d644ec` |
| `prompts/ad-*.md` filenames | **AD-1282** |
| GitHub issue titles, `--state all` (1331 issues scanned) | AD-1276 (#1330) |

**Ceiling = AD-1282. Next free = AD-1283. It stays free.**

AD-1275 was already allocated to *this* issue and never built:

```
git log --all --format='%h %s' | Select-String 'AD-1275'
  37dd7a95  AD-1275: build prompt for BF-806, composition at the agent-role sink   <- the ONLY hit
grep -r 'AD-1275|BF-806' src/ tests/
  NONE                                                                             <- never built
```

A single "build prompt for" commit plus zero markers in `src/` and `tests/` is the
allocated-but-unbuilt signature. "Never reuse" forbids one number for two *different* changes; the
same issue at the same scope is a **revision**. Minting AD-1283 here would leave AD-1275 dangling
forever — allocated, prompted, never built, never explained. Same call as AD-1278 rev 2/3.

## What rev 2 changes

No change to the decision. Rev 1 was written 2026-08-26; AD-1278 and AD-1282 have landed since and
**every claim was re-verified at HEAD** (2026-08-28). The file set did not drift — the scan still
finds the same 11 modules and `tests/test_bf791_bf792_bypass_egress.py` is green (26 passed). Line
anchors drifted badly and are corrected throughout:

| Anchor | rev 1 | HEAD |
|---|---|---|
| `turn_promotion.py` compose call | `:882` | **`:1533`** |
| `turn_promotion.py` import / `_REPORT_EMPTY` / `role="agent"` | `:63` / `:126` / `:626` | **`:65` / `:128` / `:1213`** |
| `cognitive_agent.py` `_body = str(...)` / dispatch entry / `task_text` | `:2044` / `:6685` / `:1970` | **`:2042` / `:6704` / `:1971`** |
| `threads/__init__.py` validation end / `metadata_json` / idempotency | `:1307` / `:1310` / `:1341` | **`:1308` / `:1311` / `:1343`** |
| guard test `_COMPOSED_SINKS` / `_OTHER_SINKS` / scan / import-check | `:295` / `:308` / `:322` / `:355` | **`:305` / `:318` / `:332` / `:365`** |
| `routers/chat.py` agent rows | `:286,534,680` | **`:307,560,706`** |
| `startup/finalize.py` agent row | `:2704` | **`:2751`** |
| `ChatThreadStore(` in `tests/` | 151 | **166** |

One rev-1 statement is now **wrong and is corrected below**: the UI citation
`ProfileChatTab.tsx:1387` no longer exists. The POST is at `:1496` with `role: 'captain'` at `:1501`.
The *conclusion* it supported still holds and was re-measured.

---

## The defect, re-verified at HEAD (2026-08-28)

`DmReplyPipeline` removes two markers on its way out. Eleven modules write Captain-visible rows
without it. BF-792 wired the shared composer into two of them — and `compose_bypass_reply` still has
exactly four references outside its own definition, measured:

```
src/probos/cognitive/dm/bypass_egress.py:58    _MARKER_PROBE = re.compile(r"\[A2UI\]|<intent\s+emotion", re.IGNORECASE)
                                       :118    def compose_bypass_reply(text: str) -> str:
src/probos/cognitive/turn_promotion.py:65      from probos.cognitive.dm.bypass_egress import compose_bypass_reply
                                      :1533     body = compose_bypass_reply(text) or _REPORT_EMPTY
src/probos/cognitive/deferred_turns.py:60      from probos.cognitive.dm.bypass_egress import compose_bypass_reply
                                       :298     reply = compose_bypass_reply(reply)
```

Note `deferred_turns.py` composes but is **not** a thread writer — it never calls `append_message*`,
which is why `_COMPOSED_SINKS` holds only `turn_promotion.py`.

Everything else reaches the store raw. The confirmed-by-execution leak:

```
src/probos/cognitive/cognitive_agent.py:2042   _body = str(_composed.render())     # DmReply.render() -- strips NEITHER marker
                                        :2046  thread_store.append_message(
                                        :2049      role="agent",
                                        :2050      body=_body,
                                        :2053  except Exception: logger.warning(...)   # swallowed
```

Reachable directly from `CognitiveAgent.handle_intent` via `:6704 → _handle_work_item_dispatch (:1944)`.

---

## The decision

> **Composition happens once, at the sink, for `role == "agent"` rows — inside
> `ChatThreadStore.append_message_once`. A model-authored row that wears a non-agent role is a
> producer-side obligation, and there is exactly one of them.**

### Why the producer-side answer loses

Per-producer composition is what has already been tried three times (BF-702 fixed one marker on one
path, BF-791 and BF-792 found the other three cells). It requires an author of a *future* writer to
know the obligation exists. The enumeration test makes them *notice*, but noticing is not doing —
and the test cannot tell a correct classification from a lazy one.

The DM egress reached the same conclusion for the same reason, and it is written into the tree:

```
src/probos/dm_reply.py:63-72
    "DD-5 puts the un-rendered body on the bus and composes only at egress, which is only sound if
     'which surfaces render' is enforceable. Six review rounds proved a hand-written sink list is
     not: it was wrong every round, and the last one found a pseudo-sink hiding seven real ones."
```

BF-806 is that same finding, one layer down. The eleven-module scan in #1270 is the hand-written
list, and it was wrong on first draft (the test found three modules the review's own enumeration had
missed).

### Why the sink can be trusted here

`append_message_once` is the **only** INSERT:

```
src/probos/threads/__init__.py:1262   def append_message(...)              -> delegates to append_message_once (:1271)
                               :1281  def append_message_once(...)          -- the only other entry point
                               :1299      or role not in {"captain", "agent", "system"}   -- role is a validated enum
                               :1300      or type(body) is not str
                               :1356      "INSERT INTO chat_thread_messages "             -- sole INSERT in the tree
                               :1390      self._notify_message_committed(message)         -- live-refresh reads the same object
```

The load-bearing fact is the third line: **`role` is a required, closed-set, sink-validated
parameter.** A sink-side rule keyed on author role is not an inference the store has to make — the
discriminator is already an argument it rejects rows for getting wrong.

Verified sole-INSERT: `grep "INTO chat_thread_messages" src/` returns `threads/__init__.py:1356`
only. `crew_executor.py:2522` calls `append_message_once` directly — the chokepoint must be
`append_message_once`, not `append_message`.

---

## Is `role="agent"` a sound discriminator? — measured, not assumed

Every `append_message*` call site in `src/`, with the role it passes:

Produced by AST — every `Call` whose `func.attr` is `append_message`/`append_message_once`, with its
`role=`, `author_id=` and `body=` keyword unparsed. **22 call sites across 11 modules.** Line numbers
are the *call* line.

| Site (call line) | role | author_id | body provenance | role known **at the sink**? | sink composes? |
|---|---|---|---|---|---|
| `cognitive/cognitive_agent.py:2046` | `agent` | `self.id` | LLM ack (**confirmed leaking**) | yes — literal | **yes** |
| `cognitive/crew_executor.py:2522` | `agent` | `author_id` | crew child output | yes — literal | **yes** |
| `cognitive/turn_promotion.py:1209` | `agent` | `agent_id` | already composed at `:1533` → no-op | yes — literal | yes (idempotent) |
| `proactive.py:4563` | `agent` | `agent.id` | AD-928 status | yes — literal | **yes** |
| `routers/agents.py:3472` | `agent` | `agent_id` | `require_rendered` (`:3458`) → no-op | yes — literal | yes (idempotent) |
| `routers/chat.py:307` | `agent` | `_reply.agent_id` | multi-mention reply | yes — literal | **yes** |
| `routers/chat.py:560` | `agent` | `resolved['agent_id']` | inline-callsign reply | yes — literal | **yes** |
| `routers/chat.py:706` | `agent` | `'ships-computer'` | vision / Computer reply | yes — literal | **yes** |
| `routers/thread_fanout.py:741` | `agent` | `agent_id` | emotion stripped upstream, **A2UI raw** | yes — literal | **yes** |
| `startup/finalize.py:2751` | `agent` | `agent_id` | already composed by `deferred_turns:298` | yes — literal | yes (idempotent) |
| `threads/agent_group_chat.py:227` | `agent` | `creator_id` | agent-created group opening | yes — literal | **yes** |
| `cognitive/cognitive_agent.py:1980` | `captain` | `'captain'` | `task_text` (`:1971`) — **model-reachable** | yes, but the role **lies** | **no → Slice B** |
| `routers/agents.py:2769`, `:2829` | `captain` | `'captain'` | `req.message` — Captain HTTP | yes — literal | no |
| `routers/chat.py:176`, `:460`, `:518`, `:694` | `captain` | `'captain'` | Captain HTTP | yes — literal | no |
| `routers/agents.py:2776`, `routers/chat.py:467` | `system` | `'system'` | `personality_command.py:44/56/66/76` — hardcoded literals | yes — literal | no |
| `routers/threads.py:579` | `body.role` | `body.author_id` | REST API (`AppendMessageRequest`, `threads.py:156`) | yes — **client-asserted** | role-dependent |
| `threads/__init__.py:1271` | `role` | `author_id` | *internal delegation only* — not a producer | n/a | n/a (covered by the callee) |

The fifth column is the one that decides whether a sink-side rule is even possible, and it is **yes
for every row**: 20 of the 22 sites pass a *literal* role, one is the internal delegation, and one is
client-asserted through a `pattern="^(captain|agent|system)$"` field. There is no site where the sink
must guess.

**Verdict: yes, with one measured hole.**

### (b) What happens to the genuinely ambiguous rows

The issue's stated risk is a *Captain-typed* body being rewritten. That risk is closed by the role
gate, not by heuristics:

- **`role="captain"` → never composed, byte-identical, no exceptions.** If the Captain literally types
  `[A2UI]{"kind":"choice"}[/A2UI]` or `<intent emotion=warm>`, it is stored verbatim. The sink does
  **not** sniff the body; it reads the role. A marker-shaped string is not evidence of provenance and
  must never be treated as such — that is what makes this rule safe rather than clever. **T2 pins it.**
- **`role="system"` → never composed.** Measured: every system body is a hardcoded literal
  (`personality_command.py:44/56/66/76`), so there is nothing to strip; and leaving them alone keeps
  the rule "exactly one role is composed" rather than "two roles, for different reasons". **T3 pins it.**
- **`role="agent"` → always composed.** Including rows that are already clean: `compose_bypass_reply`
  early-returns byte-identically when `_MARKER_PROBE` does not match, so the five already-composed or
  already-rendered producers are unaffected.

The genuinely ambiguous rows are exactly two, and neither is resolved by taste:

**1. The model-authored body wearing a Captain role — the one real hole.**
**`cognitive_agent.py:1980` posts a model-reachable body as `role="captain"`.** `task_text` (`:1971`)
is built from `params["title"]` / `params["description"]`, which `mesh/work_item_router.py:115-117`
copies verbatim from the work-item dict — and work items are created by agents. The sink cannot
distinguish that row from a real Captain message: same role, same `author_id="captain"`, same shape.
No sink-side rule can fix this without also rewriting real Captain text, which is the corruption we
refuse. **So it is a producer-side obligation, and it is the only one.** That is Slice B, and it is
why Slice A does not close the issue.

**2. The REST row — `routers/threads.py:579` forwards a client-supplied role.**
Re-enumerated at HEAD across production UI (`.test.` files excluded — rev 1's grep counted fixtures):

```
ui/src/components/profile/ProfileChatTab.tsx:1496  POST /api/threads/${groupThreadId}/messages
                                            :1501    role: 'captain'
ui/src/components/sidebar/threadApi.ts:617         export async function appendMessage(threadId, body)
                                       :622          POST /api/threads/${threadId}/messages
ui/src/components/profile/GroupChatHeader.tsx:112  await appendMessage(threadId, {
                                              :114    role: 'system',        <- its ONLY caller
```

The other production `role: 'agent'` hits (`ProfileChatTab.tsx:969, 1544, 1698, 1714, 1845`) are
`useStore.getState().appendThreadMessage(...)` / `addAgentMessage(...)` — **client-side display state,
not POST bodies.** Verified by reading `:1490-1560`. So no shipped client posts `role: 'agent'` to
that endpoint.

Classify it as **covered by the sink**: an API caller that asserts `role="agent"` is asserting the row
is model-authored, and asking for the model-authored egress contract is the correct response to that
assertion. Composition is idempotent, so replaying an already-clean transcript is byte-identical.

---

## The two facts that de-risk this, both measured

**1. The shipped A2UI widget is NOT damaged.** `replace_a2ui_with_stubs`
(`cognitive/dm/a2ui_extractor.py:93-155`) rewrites the raw block into a stub
(`build_a2ui_stub`, `:77`) that the HXI renders as an interactive widget. The stub is
`[A2UI: name vN - kind]`; `_MARKER_PROBE` requires the literal `[A2UI]`. Measured:

```
STUB              : '[A2UI: a2ui-choice-1.json v1 - choice]'
STUB byte-identical: True
RAW  transformed   : True (premise check)
RAW  out           : 'Ready. Pick?\n1. a\n2. b'
```

The premise check is load-bearing — a probe where *both* came back unchanged would prove nothing.
**Reproduce this assertion as a test (§Tests T7).**

**2. There is no import cycle.** Re-measured in a fresh interpreter at HEAD (2026-08-28):

```
> import probos.cognitive.dm.bypass_egress
probos.* modules loaded = 10
probos.threads in closure -> []
```

`probos.threads` is absent from the closure, so `threads/__init__.py` importing the composer cannot
cycle. (Rev 1 measured 11 modules; the closure shrank, which does not weaken the conclusion.)

**3. The layering objection, and why the function-scope import answers it.** `threads/__init__.py`
imports **stdlib only** at module scope (`json, logging, math, re, sqlite3, time, uuid, dataclasses,
pathlib, typing`). A module-scope `from probos.cognitive...` edge would make a persistence module
depend on a cognitive one — a layer violation under `.github/copilot-instructions.md`, and it would
pull `a2ui` + `artifacts` into every process that touches the thread store. A **function-scope**
import inside `append_message_once` keeps the module's declared dependency surface stdlib-only and
matches the idiom already in this exact file at `:896`
(`from probos.threads.naming import suggest_title`). This is the deliberate trade and it must be
stated in the code comment, not left for a reviewer to rediscover.

---

## Slice A — the sink composes (build this first)

### A1. `src/probos/threads/__init__.py` — compose inside `append_message_once`

Insert **after** the validation block (which ends at `:1308`, `timestamp = float(created_at)`, so
`type(body) is not str` at `:1300` still rejects non-`str` and subclasses first) and **before**
`metadata_json` is built at `:1311`. It must be before the idempotency comparison at `:1343`
(`current.body == body`) so both sides of that comparison are composed and `crew_executor`'s re-offer
stays exact.

Use a **function-scope import**, matching the existing in-tree idiom at `threads/__init__.py:896`
(`from probos.threads.naming import suggest_title`). Do not add a module-scope import: the closure is
cycle-free but a module-scope edge would make a persistence module import a cognitive one, and would
pull `a2ui` + `artifacts` into every process that touches the thread store.

**No `try/except` around the import or the call.** A failure here is a programming error; degrading
to "store it raw" reinstates the exact defect being closed, and every producer's own
`except Exception: logger.warning` would swallow the evidence.

### A2. The empty-after-composition policy — decided here

`compose_bypass_reply` returns `""` when the body was nothing but markers. The store must not insert
a blank bubble, and must not return `None` — `crew_executor.py:2536-2537` raises
`crew_execution_message_thread_missing` on `None`, which would report a false thread-missing error.

**Decision:** when a non-empty `role="agent"` body composes to empty, substitute a single named
constant in `bypass_egress.py` alongside `UNRENDERABLE_NOTE` (`:53`) and log at `warning` with the
author and thread. Rationale: the two already-wired callers each supply their own empty-reply wording
before reaching the store (`turn_promotion.py:1533` `or _REPORT_EMPTY`; `deferred_turns.py:298` +
its falsiness branch), so a producer that has an opinion still wins — the constant only covers
producers that do not.

Do **not** apply this substitution when the incoming body was *already* empty; that is the caller's
own choice and must stay byte-identical.

### A3. Keep the guard test working — re-purpose, do not weaken

`tests/test_bf791_bf792_bypass_egress.py:332` (`test_the_set_of_thread_writers_is_the_one_that_was_enumerated`)
pins the measured file set in both directions. It is **green at HEAD** (whole file: 26 passed) and
its scan is the authority — note it uses `src.rglob("*.py")` with the pattern
`\.append_message(?:_once)?\s*\(`, i.e. a *leading dot*, so `def append_message` at
`routers/threads.py:502` and `threads/__init__.py:1262/1281` are correctly not counted as writers.
**Keep the scan, the regex and both directions exactly as they are.** Change only what the two sets
*mean*:

- `_COMPOSED_SINKS` (`:305`) — currently `{"probos/cognitive/turn_promotion.py"}`. Becomes the set of
  modules that compose *at the producer* because their row is model-authored but not `role="agent"`.
  Empty after Slice A; gains `probos/cognitive/cognitive_agent.py` in Slice B.
- `_OTHER_SINKS` (`:318`) — becomes "writers whose rows the sink covers, or which are classified
  exempt". Membership still has to be earned.

**The guard must not become trivially satisfiable.** After Slice A, `_COMPOSED_SINKS` is empty and
`test_the_composed_sinks_actually_import_the_composition` (`:365`) would vacuously pass over an empty
set. Add one assertion so the split keeps teeth: **the sink module itself
(`probos/threads/__init__.py`) must reference `compose_bypass_reply`.** That is what makes
"`_OTHER_SINKS` is covered by the sink" a checked claim rather than a comment. Without it, deleting
the A1 edit would leave the whole guard file green — which is the failure mode this AD exists to
prevent.

`test_the_composed_sinks_actually_import_the_composition` (`:365`) stays and keeps its meaning.
`test_both_bypass_modules_share_one_composition` (`:282`) stays — it asserts function identity via
`turn_promotion.compose_bypass_reply is compose_bypass_reply`, which A1 does not touch.

Update the module docstring (`:1-8`) and the `_OTHER_SINKS` comment block above `:318` so the file no
longer claims the two-path framing.

### A4. `src/probos/cognitive/dm/bypass_egress.py` — correct the docstring

Lines `:17-24` state that nine model-authored sinks are unwired and that "the rest are tracked
separately". After A1 that is false. A docstring asserting a property the code does not have is the
BF-754 failure class; rewrite it to describe the sink-side boundary and name the one producer-side
exemption. Do not delete the BF-702/791/792 history — it is why the shape is what it is.

---

## Slice B — the one producer-side obligation (this is what closes #1270)

### B1. `src/probos/cognitive/cognitive_agent.py:1980-1989`

Compose `task_text` (`:1971`) before it is appended as `role="captain"`. It is the only measured
model-reachable body wearing a non-agent role. Import `compose_bypass_reply` the same way
`turn_promotion.py:65` does.

Keep the surrounding `try/except` (`:1990`) exactly as it is — a thread-store outage on the dispatch
path is genuinely log-and-degrade, and this is not the egress-contract case that
`routers/agents.py:3458` deliberately hoisted out of its catch.

### B2. Record the classification

Add `probos/cognitive/cognitive_agent.py` to `_COMPOSED_SINKS` so
`test_the_composed_sinks_actually_import_the_composition` proves the import is present.

---

## Tests

New file `tests/test_ad1275_sink_side_composition.py` unless noted.

| # | Test | Asserts |
|---|---|---|
| T1 | `test_the_work_item_acknowledgement_reaches_the_store_clean` | Drive the **real** `CognitiveAgent._handle_work_item_dispatch` through a **real** `ChatThreadStore` (tmp_path), body carrying both markers. Read the row back with `list_messages`. Neither marker present, prose survives. **This is #1270's stated acceptance criterion — do not substitute a fake store.** |
| T2 | `test_a_captain_row_is_stored_byte_identical` | A `role="captain"` body containing `[A2UI]{...}[/A2UI]` and `<intent emotion=warm>` round-trips **byte-identically**. The corruption guard. |
| T3 | `test_a_system_row_is_stored_byte_identical` | Same for `role="system"`. |
| T4 | `test_an_agent_row_is_composed` | Direct `append_message(role="agent", ...)`, both markers gone, prose kept. |
| T5 | `test_an_agent_row_of_only_markers_gets_the_note_not_a_blank` | A2 policy: stored body is the constant, not `""`, and a `warning` was logged. |
| T6 | `test_an_already_empty_agent_body_is_not_substituted` | A2 carve-out: `body=""` stays `""`. Pins the boundary the previous row could otherwise absorb. |
| T7 | `test_the_a2ui_stub_survives_the_sink_byte_identical` | `build_a2ui_stub(...)` inside an agent body is byte-identical after storage, **and** a raw block in the same test is transformed. Both assertions required — the premise check is what makes the first one mean something. |
| T8 | `test_append_message_once_stays_idempotent_under_composition` | Same `message_id`, same marker-bearing body, twice → second call returns the existing row and does **not** raise `chat_thread_message_conflict`. Pins the A1 ordering constraint. |
| T9 | `test_the_crew_child_result_row_is_composed` | Drive `crew_executor._append_crew_session_child_result` against a real store; the `append_message_once` entry point composes too. |
| T10 | `test_the_live_refresh_callback_sees_the_composed_body` | `set_message_committed_callback` receives the composed body, not the raw one (`:1390`). |
| T11 | `test_a_non_str_body_still_raises_before_composition` | `body=b"x"` → `ValueError("chat_thread_message_invalid")`. Proves composition did not move ahead of validation. |
| T12 (Slice B) | `test_the_dispatch_task_message_is_composed_at_the_producer` | Real dispatch, real store; the `role="captain"` task row is clean **and** was cleaned by the producer (assert the sink left `role="captain"` alone via T2 still passing). |
| T13 | Existing `tests/test_bf791_bf792_bypass_egress.py` | Whole file green after the A3 re-purpose, including both directions of the enumeration scan **and** the new sink-module assertion. Baseline at HEAD is 26 passed. |

**T1 is the acceptance criterion and it must cross the seam.** Producer → stored body, real
`CognitiveAgent._handle_work_item_dispatch`, real `ChatThreadStore` on `tmp_path`, read back with
`list_messages`. A test that asserts the producer called the composer, plus a separate test that the
composer strips markers, is **half-chain evidence and does not satisfy this** — that pairing is this
repo's most common defect shape (every link correct, the chain dead). Do not substitute a fake store,
a `MagicMock`, or an assertion on the argument passed to `append_message`.

**T1 must also assert its own premise.** Before the strip assertion, assert the *unfixed* shape would
have failed — i.e. assert the raw `_body` the producer built still contained both markers (or that
`compose_bypass_reply(raw) != raw` for that exact fixture). A fixture whose body happens to carry no
marker would pass the strip assertion while proving nothing.

Focused gate:

```
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1275_sink_side_composition.py \
  tests/test_bf791_bf792_bypass_egress.py tests/test_ad839_work_item_dispatch.py \
  tests/test_ad1165_turn_promotion.py tests/test_ad811a_a2ui_choice.py \
  tests/test_ad811c_group_a2ui.py tests/test_ad948_group_intent_tag_strip.py \
  tests/test_ad1248_dm_reply_value.py -q -p no:randomly
```

Blast radius to expect: `tests/` constructs `ChatThreadStore` **166 times** (re-counted at HEAD; rev 1
said 151). Any existing test that stores a marker-bearing `role="agent"` body and asserts the raw
text comes back will now fail — that is the fix working. Update the assertion and record why inline;
**never delete such a test** (BF-707/710/717/720).

Broad gate once the wave is frozen: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q`.

---

## What this does NOT change — do not build

- **Do not add composition to any of the eight `role="agent"` producers.** The sink covers them. A
  producer-side call would be a second application (harmless — composition is idempotent) but it
  re-creates the per-path pattern this AD exists to retire.
- **Do not touch `DmReplyPipeline`, its step list, or `step_4k_extract_a2ui`.** The A2UI widget
  feature is unaffected (proved above). Do not "fix" the disabled-feature path inside the pipeline.
- **Do not convert `RenderedDmText` / `require_rendered` into a thread-store admission token.** A
  hard raise at the store would be swallowed by the seven producer `except Exception` blocks and turn
  a visible marker into a silently dropped reply — strictly worse for the Captain. Transform; do not
  refuse.
- **Do not add constructor injection for the composer.** One production construction site
  (`runtime.py:620` — the only `ChatThreadStore(` in all of `src/`) versus 166 in tests; a `None`
  default would mean tests exercise the non-composing path, which is precisely the gap being closed.
  The `set_message_committed_callback` / `_clock` / `_id_factory` injection precedent in this class is
  real but does not apply: those are *optional observers and seams*, whereas this is a **contract the
  store must always honour**. An injectable egress rule is an egress rule you can forget to wire.
- **Do not relocate `compose_bypass_reply` to a new leaf module.** The lazy import makes it
  unnecessary. Record the relocation as a deferred seam if you think it is worth doing.
- **Do not weaken, split, or delete `test_the_set_of_thread_writers_is_the_one_that_was_enumerated`.**
  Re-purpose the set semantics only. The scan and both failure directions stay.
- **Do not change `routers/threads.py`, its `AppendMessageRequest` role pattern, or the UI.**
- **Do not touch `proactive.py`, `crew_executor.py`, `thread_fanout.py`, `chat.py`,
  `agent_group_chat.py`, `agents.py` or `finalize.py` production code at all** — they are covered by
  the sink without edits. Their only appearance in this build is in the test table and the
  classification sets.

---

## Tracking

- `PROGRESS.md` — AD-1275 / BF-806 entry with the test delta.
- `DECISIONS.md` — the decision statement, the `role="agent"` discriminator evidence, and the one
  producer-side exemption with its reason. This is the "recorded decision" #1270 asks for. Note in
  the entry that AD-1275 was allocated 2026-08-26 and built on a rev-2 prompt, so the number is not
  mistaken for a gap.
- `docs/development/roadmap.md` Bug Tracker — BF-806 row.

---

## Acceptance criteria

1. `append_message_once` composes `role == "agent"` bodies, before the idempotency comparison and the
   INSERT, after the type validation.
2. `role="captain"` and `role="system"` rows are byte-identical through the store — proved by T2/T3.
3. The AD-811a/b/c widget stub survives byte-identically, with the raw-block premise check in the
   same test — T7.
4. T1 crosses producer → stored body against a real `ChatThreadStore`, per #1270's acceptance.
5. `tests/test_bf791_bf792_bypass_egress.py` is green with its enumeration scan intact in both
   directions, **and** the guard is still meaningful: an added assertion proves
   `probos/threads/__init__.py` references `compose_bypass_reply`, so deleting the A1 edit turns the
   guard file red rather than leaving it vacuously green over an empty `_COMPOSED_SINKS`.
6. Slice B composes `cognitive_agent.py:1980`'s `role="captain"` task row at the producer and records
   it in `_COMPOSED_SINKS`.
7. `bypass_egress.py`'s module docstring no longer asserts a property the code does not have.
8. Full repository suite green once the wave is frozen.
9. Run the `Diff Reviewer` subagent on the staged diff, on a different model than the author, and
   address its findings before committing.
10. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Closure

**Slice A alone does not close #1270.** It satisfies two of the issue's three acceptance bullets (the
recorded decision, and the cross-seam test for the `cognitive_agent` acknowledgement) and covers all
eleven `role="agent"` writers permanently. It leaves the third bullet — *every* model-authored sink
composed or explicitly exempt — open, because `cognitive_agent.py:1983` writes a model-reachable body
as `role="captain"` and the sink cannot see that. Ship Slice A on its own if the wave is cut short,
and say in the commit that the issue stays open pending Slice B.

---

## Verified against codebase (re-run 2026-08-28, at `d5d644ec`)

```
-- AD ceiling, three sources, none of them open-ads-report.md --
git log --all --format='%s' | extract AD-(\d+) | max   -> 1282   (AD-1282 = 7edf309e, AD-1278 = d5d644ec)
Get-ChildItem prompts -Filter 'ad-*.md'      | max     -> 1282
gh issue list --state all --limit 4000 (1331 issues) | max in a title -> 1276 (#1330)
   => ceiling 1282, next free 1283, NOT consumed (AD-1275 is allocated-but-unbuilt for this issue)

grep "INTO chat_thread_messages" src/
  src/probos/threads/__init__.py:1356      (sole INSERT)

src/probos/threads/__init__.py
   237  def __init__(self, db_path, *, clock=time.time, id_factory=...)   (injection precedent)
  1262  def append_message(self, thread_id, *, author_id, role, body, metadata=None)
  1271      return self.append_message_once(...)
  1281  def append_message_once(self, thread_id, *, message_id, author_id, role, body, created_at, metadata=None)
  1299      or role not in {"captain", "agent", "system"}
  1300      or type(body) is not str
  1308  timestamp = float(created_at)                (end of validation)
  1311  metadata_json = json.dumps(
  1343  and current.body == body                     (idempotency comparison)
  1356  "INSERT INTO chat_thread_messages "
  1390  self._notify_message_committed(message)
   896  from probos.threads.naming import suggest_title      (function-scope import idiom)
  module-scope imports: stdlib ONLY (json, logging, math, re, sqlite3, time, uuid, dataclasses, pathlib, typing)

src/probos/cognitive/dm/bypass_egress.py
    53  UNRENDERABLE_NOTE = (
    58  _MARKER_PROBE = re.compile(r"\[A2UI\]|<intent\s+emotion", re.IGNORECASE)
   118  def compose_bypass_reply(text: str) -> str:
   137      if not _MARKER_PROBE.search(raw):

src/probos/cognitive/turn_promotion.py:65     from probos.cognitive.dm.bypass_egress import compose_bypass_reply
                                      :128    _REPORT_EMPTY: str = "That background task is finished."
                                      :1209   thread_store.append_message(   ... :1213 role="agent"
                                      :1533   body = compose_bypass_reply(text) or _REPORT_EMPTY
src/probos/cognitive/deferred_turns.py:60     from probos.cognitive.dm.bypass_egress import compose_bypass_reply
                                      :298    reply = compose_bypass_reply(reply)
   (deferred_turns.py calls NO append_message* -- composes, but is not a thread writer)

src/probos/cognitive/cognitive_agent.py
  1944  async def _handle_work_item_dispatch(self, intent: IntentMessage) -> IntentResult:
  1971  task_text = "\n".join(task_lines)
  1980  thread_store.append_message( ... :1983 role="captain", body=task_text   <- model-reachable, Slice B
  2042  _body = str(_composed.render())
  2046  thread_store.append_message( ... :2049 role="agent",  body=_body        <- confirmed leaking
  6704  return await self._handle_work_item_dispatch(intent)

AST enumeration of every .append_message / .append_message_once Call in src/probos:
  22 call sites, 11 modules -- identical file set to the guard test's _COMPOSED_SINKS | _OTHER_SINKS
  cognitive/cognitive_agent.py:1980 captain | :2046 agent
  cognitive/crew_executor.py:2522 agent   (append_message_once)
  cognitive/turn_promotion.py:1209 agent
  proactive.py:4563 agent
  routers/agents.py:2769 captain | :2776 system | :2829 captain | :3472 agent
  routers/chat.py:176 captain | :307 agent | :460 captain | :467 system | :518 captain
                 :560 agent | :694 captain | :706 agent
  routers/thread_fanout.py:741 agent
  routers/threads.py:579 role=body.role
  startup/finalize.py:2751 agent
  threads/__init__.py:1271 role=role      (internal delegation, not a producer)
  threads/agent_group_chat.py:227 agent

src/probos/routers/agents.py:3424  from probos.dm_reply import DmReply, require_rendered  # AD-1248
                            :3458  _rendered = require_rendered(
src/probos/routers/threads.py:156  role: str = Field(..., pattern="^(captain|agent|system)$")
src/probos/mesh/work_item_router.py:115-117   work-item fields copied verbatim from wi
src/probos/cognitive/crew_executor.py:2536    if message is None:
                                      :2537       raise ValueError("crew_execution_message_thread_missing")
src/probos/runtime.py:620          self.chat_thread_store = ChatThreadStore(    (SOLE construction in src/, count=1)
                      :1304        self.chat_thread_store.set_message_committed_callback(...)
src/probos/cognitive/dm/a2ui_extractor.py:77  def build_a2ui_stub(name: str, version: int, kind: str = "choice") -> str

ui/ (production only -- '.test.' excluded; rev 1's grep counted fixtures and cited a dead line)
  components/profile/ProfileChatTab.tsx:1496  POST /api/threads/${groupThreadId}/messages
                                       :1501    role: 'captain'
  components/sidebar/threadApi.ts:617         export async function appendMessage(...)  :622 POST
  components/profile/GroupChatHeader.tsx:112  await appendMessage(threadId, { :114 role: 'system' })  <- only caller
  ProfileChatTab.tsx:969,1544,1698,1714,1845  role:'agent' -> appendThreadMessage/addAgentMessage (client state, NOT POST)

tests/test_bf791_bf792_bypass_egress.py:282   def test_both_bypass_modules_share_one_composition
                                       :305   _COMPOSED_SINKS = {"probos/cognitive/turn_promotion.py"}
                                       :318   _OTHER_SINKS = {...10 modules...}
                                       :332   def test_the_set_of_thread_writers_is_the_one_that_was_enumerated
                                       :365   def test_the_composed_sinks_actually_import_the_composition
  pytest tests/test_bf791_bf792_bypass_egress.py -q -p no:randomly -> 26 passed   (green baseline)
grep -c 'ChatThreadStore(' tests/ -> 166
```

### Measured, with premise checks (2026-08-28)

```
CLAIM: the AD-811a/b/c widget stub survives the sink byte-identically
RUN:   build_a2ui_stub('a2ui-choice-1.json', 1, 'choice') inside an agent body -> compose_bypass_reply
STUB               : 'Ready. [A2UI: a2ui-choice-1.json v1 - choice]'
STUB byte-identical: True
RAW  transformed   : True   <- PREMISE CHECK. Without this, a probe where BOTH came back
                              unchanged (e.g. a no-op composer) would read as a pass.
RAW  out           : 'Ready. Pick?\n1. a\n2. b'
HOLDS: yes -- _MARKER_PROBE requires the literal '[A2UI]'; the stub is '[A2UI: '
```

### Absence verified (2026-08-28)

Claims of absence are the dangerous half — a failed recall and a completed search are
indistinguishable from the inside — so each one below shows the command that was actually run.

```
CLAIM: no INSERT into chat_thread_messages exists outside append_message_once
RUN:   Get-ChildItem src\probos -Recurse -Filter *.py | Select-String "INTO chat_thread_messages"
FOUND: src/probos/threads/__init__.py:1356 only
HOLDS: yes

CLAIM: importing the composer from threads/ cannot cycle
RUN:   python -c "import probos.cognitive.dm.bypass_egress; print([m for m in sys.modules if m.startswith('probos.threads')])"
FOUND: []   (10 probos modules loaded; probos.threads absent)
HOLDS: yes

CLAIM: no shipped PRODUCTION UI client POSTs role:'agent' to /api/threads/{id}/messages
RUN:   ui/src **/*.tsx,*.ts, excluding '.test.', for /messages POSTs and for role:'agent'
       then READ ProfileChatTab.tsx:1490-1560 to classify each role:'agent' hit
FOUND: 2 POST callers -- 'captain' (ProfileChatTab.tsx:1501), 'system' (GroupChatHeader.tsx:114).
       All 5 production role:'agent' hits are appendThreadMessage/addAgentMessage client state.
HOLDS: yes  (rev 1 reached the same conclusion from a grep that included .test. fixtures and a
             now-dead line number; re-derived here from production files and a read)

CLAIM: role="system" bodies are never model-authored
RUN:   grep '"system_reply"' src/
FOUND: personality_command.py:44,56,66,76 -- four hardcoded literals
HOLDS: yes

CLAIM: AD-1275 was never built
RUN:   git log --all --format='%h %s' | Select-String 'AD-1275'   ->  37dd7a95 only (a "build prompt" commit)
       scan src/ and tests/ for 'AD-1275' | 'BF-806' | 'ad1275' | 'bf806'   ->  NONE
HOLDS: yes -- allocated-but-unbuilt, so this is a revision, not a re-mint

CLAIM: the guard test's file set did NOT drift since the issue was filed (2026-08-19)
RUN:   AST scan of src/probos for .append_message* calls -> 11 modules;
       compare with _COMPOSED_SINKS | _OTHER_SINKS -> 11 modules; pytest -> 26 passed
HOLDS: yes -- the file set is unchanged. Only line numbers moved.
```

### A caution for the builder

Every line number above was measured on 2026-08-28 and **rev 1's were wrong within two days**. If
this prompt sits unbuilt, re-run the anchors before editing rather than trusting them — and re-read
the *"What this does NOT change"* list hardest, because an intervening AD is most likely to have
falsified one of those claims rather than a line number.

