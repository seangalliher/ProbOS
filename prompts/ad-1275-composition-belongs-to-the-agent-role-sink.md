# AD-1275 / BF-806: composition belongs to the agent-role sink

**Issue:** #1270 (OPEN) · **Repo:** OSS `d:\ProbOS`, branch `main`
**AD:** AD-1275 — newly minted. **Ceiling was AD-1274**, from `prompts/ad-*.md` filenames and the
`git log --all --format='%s'` subject `AD-1273, AD-1274: build prompts for the two recycle/delivery
redesigns`. GitHub issue titles across all states top out lower (AD-1270, issue #1324).
**Not** taken from `docs/development/open-ads-report.md`.
**BF:** BF-806 — already allocated by the issue. (Highest BF in `git log`: BF-854.)
**Status:** ready to build · **Estimated tests:** 18–24 across two slices
**Slice A alone does NOT close #1270.** See *Closure* at the foot of this file.

---

## The defect, verified at HEAD (2026-08-26)

`DmReplyPipeline` removes two markers on its way out. Eleven modules write Captain-visible rows
without it. BF-792 wired the shared composer into two of them:

```
src/probos/cognitive/dm/bypass_egress.py:58   _MARKER_PROBE = re.compile(r"\[A2UI\]|<intent\s+emotion", re.IGNORECASE)
                                       :118   def compose_bypass_reply(text: str) -> str:
src/probos/cognitive/turn_promotion.py:882    body = compose_bypass_reply(text) or _REPORT_EMPTY
src/probos/cognitive/deferred_turns.py:298    reply = compose_bypass_reply(reply)
```

Everything else reaches the store raw. The confirmed-by-execution leak:

```
src/probos/cognitive/cognitive_agent.py:2044   _body = str(_composed.render())     # DmReply.render() -- strips NEITHER marker
                                        :2046  thread_store.append_message(
                                        :2049      role="agent",
                                        :2050      body=_body,
                                        :2053  except Exception: logger.warning(...)   # swallowed
```

Reachable directly from `CognitiveAgent.handle_intent` via `:6685 → _handle_work_item_dispatch (:1944)`.

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

Verified sole-INSERT: `grep "INTO chat_thread_messages" src/` returns `threads/__init__.py:1356`
only. `crew_executor.py:2522` calls `append_message_once` directly — the chokepoint must be
`append_message_once`, not `append_message`.

---

## Is `role="agent"` a sound discriminator? — measured, not assumed

Every `append_message*` call site in `src/`, with the role it passes:

| Site | role | body provenance | sink composes? |
|---|---|---|---|
| `cognitive/cognitive_agent.py:2049` | `agent` | LLM ack (**confirmed leaking**) | **yes** |
| `cognitive/crew_executor.py:2526` | `agent` | crew child output | **yes** |
| `cognitive/turn_promotion.py:626` | `agent` | already composed at `:882` → no-op | yes (idempotent) |
| `proactive.py:4566` | `agent` | AD-928 status | **yes** |
| `routers/agents.py:3467` | `agent` | `DmReplyPipeline` output → no-op | yes (idempotent) |
| `routers/chat.py:286` | `agent` | multi-mention reply | **yes** |
| `routers/chat.py:534` | `agent` | inline-callsign reply | **yes** |
| `routers/chat.py:680` | `agent` | vision reply | **yes** |
| `routers/thread_fanout.py:742` | `agent` | emotion stripped at `:715`, A2UI raw | **yes** |
| `startup/finalize.py:2704` | `agent` | already composed by `deferred_turns:298` | yes (idempotent) |
| `threads/agent_group_chat.py:230` | `agent` | agent-created group opening | **yes** |
| `cognitive/cognitive_agent.py:1983` | `captain` | `task_text` (`:1970`) — **model-reachable** | **no → Slice B** |
| `routers/agents.py:2772`, `:2832` | `captain` | `req.message` — Captain HTTP | no |
| `routers/chat.py:177`, `:439`, `:497`, `:668` | `captain` | Captain HTTP | no |
| `routers/agents.py:2779`, `routers/chat.py:446` | `system` | `personality_command.py:44/56/66/76` — hardcoded literals | no |
| `routers/threads.py:582` | `body.role` | REST API (`AppendMessageRequest`, `threads.py:156`) | role-dependent |

**Verdict: yes, with one measured hole.** The corruption the issue worries about is a *Captain-typed*
body being rewritten. Captain keystrokes arrive as `role="captain"` and are never touched. The
`role="system"` rows are hardcoded literals. So no Captain-typed text is composed.

The hole is the mirror image: **`cognitive_agent.py:1983` posts a model-reachable body as
`role="captain"`.** `task_text` (`:1970`) is built from `params["title"]` / `params["description"]`,
which `mesh/work_item_router.py:115-117` copies verbatim from the work-item dict — and work items are
created by agents. The sink cannot distinguish that row from a real Captain message (same role, same
`author_id="captain"`). Only the producer can. That is Slice B, and it is why Slice A does not close
the issue.

### The REST row

`routers/threads.py:582` forwards a client-supplied role. Enumerated: the only shipped clients are
`ui/src/components/profile/ProfileChatTab.tsx:1387` (`role: 'captain'`) and
`ui/src/components/profile/GroupChatHeader.tsx:112` (`role: 'system'`). No shipped client posts
`role: 'agent'` to that endpoint. Classify it as **covered by the sink** — an API caller that asserts
`role="agent"` is asserting the row is model-authored, and composition is idempotent, so replaying an
already-clean transcript is byte-identical.

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

**2. There is no import cycle.** Measured in a fresh interpreter:

```
> import probos.cognitive.dm.bypass_egress
probos.* modules loaded = 11
probos.threads in closure -> []
```

`probos.threads` is absent from the closure, so `threads/__init__.py` importing the composer cannot
cycle.

---

## Slice A — the sink composes (build this first)

### A1. `src/probos/threads/__init__.py` — compose inside `append_message_once`

Insert **after** the validation block (`:1292-1307`, so `type(body) is not str` still rejects
non-`str` and subclasses first) and **before** `metadata_json` is built at `:1310`. It must be
before the idempotency comparison at `:1341` (`current.body == body`) so both sides of that
comparison are composed and `crew_executor`'s re-offer stays exact.

Use a **function-scope import**, matching the existing in-tree idiom at `threads/__init__.py:896`
(`from probos.threads.naming import suggest_title`). Do not add a module-scope import: the closure is
cycle-free but a module-scope edge would make a persistence module import a cognitive one, and would
pull `reply_pipeline` + `artifacts` into every process that touches the thread store.

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
before reaching the store (`turn_promotion.py:882` `or _REPORT_EMPTY`; `deferred_turns.py:298` +
its falsiness branch), so a producer that has an opinion still wins — the constant only covers
producers that do not.

Do **not** apply this substitution when the incoming body was *already* empty; that is the caller's
own choice and must stay byte-identical.

### A3. Keep the guard test working — re-purpose, do not weaken

`tests/test_bf791_bf792_bypass_egress.py:322` (`test_the_set_of_thread_writers_is_the_one_that_was_enumerated`)
pins the measured file set in both directions. **Keep the scan and both directions exactly as they
are.** Change only what the two sets *mean*:

- `_COMPOSED_SINKS` (`:295`) — currently `{"probos/cognitive/turn_promotion.py"}`. Becomes the set of
  modules that compose *at the producer* because their row is model-authored but not `role="agent"`.
  Empty after Slice A; gains `probos/cognitive/cognitive_agent.py` in Slice B.
- `_OTHER_SINKS` (`:308`) — becomes "writers whose rows the sink covers, or which are classified
  exempt". Membership still has to be earned.

`test_the_composed_sinks_actually_import_the_composition` (`:355`) stays and keeps its meaning.
`test_both_bypass_modules_share_one_composition` (`:272`) stays — it asserts function identity via
`turn_promotion.compose_bypass_reply is compose_bypass_reply`, which A1 does not touch.

Update the module docstring (`:1-8`) and the `_OTHER_SINKS` comment block above `:308` so the file no
longer claims the two-path framing.

### A4. `src/probos/cognitive/dm/bypass_egress.py` — correct the docstring

Lines `:17-24` state that nine model-authored sinks are unwired and that "the rest are tracked
separately". After A1 that is false. A docstring asserting a property the code does not have is the
BF-754 failure class; rewrite it to describe the sink-side boundary and name the one producer-side
exemption. Do not delete the BF-702/791/792 history — it is why the shape is what it is.

---

## Slice B — the one producer-side obligation (this is what closes #1270)

### B1. `src/probos/cognitive/cognitive_agent.py:1980-1989`

Compose `task_text` (`:1970`) before it is appended as `role="captain"`. It is the only measured
model-reachable body wearing a non-agent role. Import `compose_bypass_reply` the same way
`turn_promotion.py:63` does.

Keep the surrounding `try/except` (`:1990`) exactly as it is — a thread-store outage on the dispatch
path is genuinely log-and-degrade, and this is not the egress-contract case that
`routers/agents.py:3451` deliberately hoisted out of its catch.

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
| T13 | Existing `tests/test_bf791_bf792_bypass_egress.py` | Whole file green after the A3 re-purpose, including both directions of the enumeration scan. |

Focused gate:

```
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1275_sink_side_composition.py \
  tests/test_bf791_bf792_bypass_egress.py tests/test_ad839_work_item_dispatch.py \
  tests/test_ad1165_turn_promotion.py tests/test_ad811a_a2ui_choice.py \
  tests/test_ad811c_group_a2ui.py tests/test_ad948_group_intent_tag_strip.py \
  tests/test_ad1248_dm_reply_value.py -q -p no:randomly
```

Blast radius to expect: `tests/` constructs `ChatThreadStore` **151 times**. Any existing test that
stores a marker-bearing `role="agent"` body and asserts the raw text comes back will now fail — that
is the fix working. Update the assertion and record why inline; **never delete such a test**
(BF-707/710/717/720).

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
  (`runtime.py:620`) versus 151 in tests; a `None` default would mean tests exercise the
  non-composing path, which is precisely the gap being closed.
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
  producer-side exemption with its reason. This is the "recorded decision" #1270 asks for.
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
   directions.
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

## Verified against codebase (2026-08-26)

```
git log --all --format='%s' | Select-String 'AD-1(2[5-9][0-9]|3[0-9][0-9])'
  AD-1273, AD-1274: build prompts for the two recycle/delivery redesigns      <- ceiling
Get-ChildItem prompts -Filter 'ad-*.md' -> highest numeric = 1274
GitHub issue titles (state=all) -> highest AD in a title = AD-1270 (#1324)
git log --all --format='%s' | Select-String 'BF-8\d\d' -> highest = BF-854

grep -n "INTO chat_thread_messages" src/
  src/probos/threads/__init__.py:1356      (sole INSERT)

src/probos/threads/__init__.py
  1262  def append_message(self, thread_id, *, author_id, role, body, metadata=None)
  1271      return self.append_message_once(...)
  1281  def append_message_once(self, thread_id, *, message_id, author_id, role, body, created_at, metadata=None)
  1299      or role not in {"captain", "agent", "system"}
  1300      or type(body) is not str
  1307  timestamp = float(created_at)
  1310  metadata_json = json.dumps(
  1341  and current.body == body                     (idempotency comparison)
  1356  "INSERT INTO chat_thread_messages "
  1376  inserted = True
  1390  self._notify_message_committed(message)
   896  from probos.threads.naming import suggest_title      (function-scope import idiom)

src/probos/cognitive/dm/bypass_egress.py
    53  UNRENDERABLE_NOTE = (
    58  _MARKER_PROBE = re.compile(r"\[A2UI\]|<intent\s+emotion", re.IGNORECASE)
   118  def compose_bypass_reply(text: str) -> str:
   137      if not _MARKER_PROBE.search(raw):

src/probos/cognitive/turn_promotion.py:63    from probos.cognitive.dm.bypass_egress import compose_bypass_reply
                                      :126   _REPORT_EMPTY: str = "That background task is finished."
                                      :626   role="agent",
                                      :882   body = compose_bypass_reply(text) or _REPORT_EMPTY
src/probos/cognitive/deferred_turns.py:60    from probos.cognitive.dm.bypass_egress import compose_bypass_reply
                                      :298   reply = compose_bypass_reply(reply)

src/probos/cognitive/cognitive_agent.py
  1944  async def _handle_work_item_dispatch(self, intent: IntentMessage) -> IntentResult:
  1970  task_text = "\n".join(task_lines)
  1983      role="captain",                 body=task_text        <- model-reachable, Slice B
  2044  _body = str(_composed.render())
  2049      role="agent",                   body=_body            <- confirmed leaking
  6685  return await self._handle_work_item_dispatch(intent)

src/probos/mesh/work_item_router.py:115-117   "work_type"/"tags"/"metadata" copied verbatim from wi
src/probos/cognitive/crew_executor.py:2522    thread_store.append_message_once(   ... :2526 role="agent"
                                      :2536   if message is None:
                                      :2537       raise ValueError("crew_execution_message_thread_missing")
src/probos/proactive.py:4566                  role="agent",
src/probos/routers/chat.py:286,534,680        role="agent",
src/probos/routers/chat.py:177,439,497,668    role="captain",
src/probos/routers/chat.py:446                role="system",   body=_personality_result["system_reply"]
src/probos/routers/agents.py:3467             role="agent",     :3451 _rendered = require_rendered(...)
src/probos/routers/agents.py:2772,2832        role="captain",
src/probos/routers/agents.py:2779             role="system",
src/probos/routers/thread_fanout.py:715       reply_text = strip_intent_self_tag(reply_text)
                                      :742    role="agent",       (no A2UI handling on this path)
src/probos/routers/threads.py:156             role: str = Field(..., pattern="^(captain|agent|system)$")
                              :582            role=body.role,
src/probos/startup/finalize.py:2704           role="agent",
src/probos/threads/agent_group_chat.py:230    role="agent",
src/probos/cognitive/commands/personality_command.py:44,56,66,76   "system_reply": <literal>
src/probos/dm_reply.py:63-72                  DD-12: "a hand-written sink list is not [enforceable]"
                      :105                    def require_rendered(text, *, sink) -> RenderedDmText
src/probos/runtime.py:620                     self.chat_thread_store = ChatThreadStore(   (sole production construction)
src/probos/cognitive/dm/a2ui_extractor.py:77  def build_a2ui_stub(name, version, kind="choice")
                                          :93 async def replace_a2ui_with_stubs(

ui/src/components/profile/ProfileChatTab.tsx:1387   role: 'captain'   (POST /api/threads/{id}/messages)
ui/src/components/profile/GroupChatHeader.tsx:112   role: 'system'    (appendMessage)
ui/src -> no shipped client posts role:'agent' to that endpoint

tests/test_bf791_bf792_bypass_egress.py:272   def test_both_bypass_modules_share_one_composition
                                       :295   _COMPOSED_SINKS = {...}
                                       :308   _OTHER_SINKS = {...}
                                       :322   def test_the_set_of_thread_writers_is_the_one_that_was_enumerated
                                       :355   def test_the_composed_sinks_actually_import_the_composition
grep -c 'ChatThreadStore(' tests/*.py -> 151
```

### Absence verified (2026-08-26)

```
CLAIM: no INSERT into chat_thread_messages exists outside append_message_once
RUN:   grep "INTO chat_thread_messages" (workspace)
FOUND: src/probos/threads/__init__.py:1356 only (plus one prose hit in prompts/archive/)
HOLDS: yes

CLAIM: importing the composer from threads/ cannot cycle
RUN:   python -c "import sys; import probos.cognitive.dm.bypass_egress; print([m for m in sys.modules if m.startswith('probos.threads')])"
FOUND: []   (11 probos modules loaded; probos.threads absent)
PREMISE CHECK: the probe asserts hasattr(be,'compose_bypass_reply') first, so an import that
               silently no-opped would fail loudly rather than print an empty list
HOLDS: yes

CLAIM: no shipped UI client POSTs role:'agent' to /api/threads/{id}/messages
RUN:   grep "role:\s*['\"]agent['\"]" ui/src/**  +  grep "appendMessage(" ui/src/**
FOUND: 63 hits, all local display state or test fixtures; the two real callers pass
       'captain' (ProfileChatTab.tsx:1387) and 'system' (GroupChatHeader.tsx:112)
HOLDS: yes

CLAIM: role="system" bodies are never model-authored
RUN:   grep '"system_reply"' src/
FOUND: personality_command.py:44,56,66,76 -- four hardcoded literals; agents.py:2792 and
       chat.py:459 are hardcoded failure fallbacks
HOLDS: yes
```
