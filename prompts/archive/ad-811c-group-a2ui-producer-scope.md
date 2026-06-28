# AD-811c — Group-chat A2UI producer (#735): VERIFY-FIRST scope + BuildSpec

**Author:** Architect · **HEAD:** `858380b9` · **Date:** 2026-06-25
**Verdict:** ✅ **GO — but RE-SCOPED to BACKEND-ONLY (~1 line).** Not a backend+UI split.
**Headline:** The group fan-out ALREADY runs the reply-pipeline escalation subset and the group
transcript ALREADY renders through the same `ProfileChatTab` path as 1:1 — so there is **no
group-specific renderer to build**. The single real gap is that `step_4k_extract_a2ui` was
deliberately excluded from `_escalation_steps()` ("1:1 only, v1 scope"). Adding it brings the group
path to full A2UI parity with 1:1. **One STOP-FLAG** (a shared, non-group-specific inline-card
render gate) needs Captain confirmation but does **not** block AD-811c.

---

## 1. The decisive finding (the question the task hinged on)

> *Does the group fan-out run the DM `reply_pipeline` (extraction for free) or a separate path?*

**It runs the reply-pipeline escalation subset.** AD-933 wired `thread_fanout._send_one` to build a
`DmReplyPipeline` and call `run_escalation_only()`. Verified real code
([thread_fanout.py](../src/probos/routers/thread_fanout.py#L620-L638)):

```python
if result and result.result and agent is not None:
    try:
        pipeline = DmReplyPipeline(DmReplyContext(
            runtime=runtime, agent=agent, agent_id=agent_id, callsign=callsign,
            req_message=trigger_body,
            response_text=reply_text,          # :627  <- step_4k reads/mutates this
            has_image_attachment=bool(vision_messages), per_attachment=[],
            sanity_gate=sanity_gate, params=params, message_text=trigger_body,
            sampling_state=None, avatar_event_bus=None,
            chat_thread_id=thread_id,          # :635  <- step_4k anchors extraction here
        ))
        await pipeline.run_escalation_only()    # :637
        reply_text = pipeline.ctx.response_text or reply_text   # :638  <- adopts the stub
```

But `run_escalation_only()` runs `_escalation_steps()`, and **`step_4k_extract_a2ui` is in
`_full_steps()` (the 1:1 chain) but NOT `_escalation_steps()`** — by design, deferred to AD-811c.
Verified [reply_pipeline.py](../src/probos/cognitive/dm/reply_pipeline.py#L201-L209):

```python
def _escalation_steps(self) -> tuple[Callable, ...]:
    ...
    return (
        self.step_4c_image_gen_parse,   # AD-933b
        self.step_4e_action_dispatch,
        self.step_4i_notebook_parse,
        self.step_4h_mesh_read_parse,
        self.step_4f_extract_artifacts,
        self.step_4g_create_task_parse,
        self.step_4j_deliberate_parse,  # AD-934
    )   # <- step_4k_extract_a2ui is ABSENT
```

And `step_4k`'s own docstring states the deferral
([reply_pipeline.py](../src/probos/cognitive/dm/reply_pipeline.py#L1240-L1243)):
> *"1:1 only — registered in `_full_steps` but NOT `_escalation_steps` (v1 scope)."*

**So a group agent's `[A2UI]{json}[/A2UI]` tag is never extracted on the group path today.** When
`a2ui_enabled=True`, a group agent (already taught the tag — see §3) would emit the raw tag and it
would leak verbatim into the group transcript (a "this is AI" tell, the BF-616 / divergence-leak
class). AD-811c closes this by running `step_4k` on the group path.

**This makes the AD-811c backend a genuine ~1-line addition.** The seam is fully wired; `step_4k`
reads `ctx.response_text` / `ctx.chat_thread_id` / `runtime.config.communications.a2ui_enabled` /
`artifact_store` / `attachment_store` / `agent_id` — every one set by `_send_one` — and mutates
`ctx.response_text`, which `_send_one:638` adopts and then `store.append_message`'s.

---

## 2. Verified-against-codebase (every premise, real signatures + line numbers)

| # | Premise to verify | Finding (HEAD `858380b9`) |
|---|---|---|
| 1 | 1:1 A2UI extraction step | `DmReplyPipeline.step_4k_extract_a2ui` ([reply_pipeline.py:1233](../src/probos/cognitive/dm/reply_pipeline.py#L1233)); registered in `_full_steps()` after `step_4f_extract_artifacts` ([:167](../src/probos/cognitive/dm/reply_pipeline.py#L167)). Calls `extract_a2ui(text, max_options)` + `replace_a2ui_with_stubs(...)` ([:1273-1287](../src/probos/cognitive/dm/reply_pipeline.py#L1273)); mutates `self.ctx.response_text`. Gated on `comms.a2ui_enabled` (early-return when off → byte-identical). |
| 1 | Extractor + artifact write | `cognitive/dm/a2ui_extractor.py` — `extract_a2ui` ([:37](../src/probos/cognitive/dm/a2ui_extractor.py#L37)), `replace_a2ui_with_stubs` ([:93](../src/probos/cognitive/dm/a2ui_extractor.py#L93)) (AD-797 two-call write: `attachment_store.write` + `artifact_store.add_version`). Kind-generic via `spec.kind`. **No change needed.** |
| 1 | 1:1 UI stub→card→response | `ProfileChatTab.renderMessageBodyWithArtifacts(text, threadId, onA2UIChoice?)` ([:114](../ui/src/components/profile/ProfileChatTab.tsx#L114)); `parseA2UIStub(line)` BEFORE `parseArtifactStub` ([:127/:159](../ui/src/components/profile/ProfileChatTab.tsx#L127)); dispatches `choice→A2UIChoiceCard / multiselect→A2UIMultiSelectCard / form→A2UIFormCard` ([:128-156](../ui/src/components/profile/ProfileChatTab.tsx#L128)); `onChoice={onA2UIChoice}` → `(opt)=>sendText(opt)` at the call site ([:1194](../ui/src/components/profile/ProfileChatTab.tsx#L1194)). |
| 2 | **Group fan-out path** | `thread_fanout._send_one` runs `DmReplyPipeline.run_escalation_only()` ([:621-638](../src/probos/routers/thread_fanout.py#L621)) — **it DOES run the reply pipeline (escalation subset)**, with `chat_thread_id=thread_id` set and `ctx.response_text` adopted. `step_4k` is the only missing step. |
| 2 | Group persistence/delivery | `_send_one` → `store.append_message(...)` (the stub survives like any reply). UI loads via `threadApi.listMessages(threadId)` → `GET /api/threads/{id}/messages` ([routers/threads.py:302](../src/probos/routers/threads.py#L302)); shape `{id, thread_id, author_id, role, body, created_at, metadata}`. A stub in `body` flows to the client identically to 1:1. |
| 3 | **Group chat UI component** | **It IS `ProfileChatTab`** (premise "NOT ProfileChatTab" is WRONG). `AgentProfilePanel` derives the host id from the active group thread and mounts `<ProfileChatTab agentId={agentId} />` ([AgentProfilePanel.tsx:542](../ui/src/components/profile/AgentProfilePanel.tsx#L542)); `selectTranscriptMessages(activeThreadId, threadMsgs, conv)` ([profileTranscript.ts:35](../ui/src/components/profile/profileTranscript.ts#L35)) feeds the GROUP thread's messages into the **same** `renderMessageBodyWithArtifacts(... )` call ([:1194](../ui/src/components/profile/ProfileChatTab.tsx#L1194)). `GroupChatHeader` + `MeetingView` mount alongside. **The group transcript already shares the 1:1 A2UI dispatch.** |
| 4 | **Response semantics** | `sendText` ([:652](../ui/src/components/profile/ProfileChatTab.tsx#L652)) routes to `POST /api/threads/{id}/messages` with `role:"captain"` when the active thread has ≥2 crew ([:694-710](../ui/src/components/profile/ProfileChatTab.tsx#L694)) → AD-914 fan-out; else `/api/agent/{id}/chat` (1:1). So `onChoice={(opt)=>sendText(opt)}` **auto-routes** a group card click to the group thread as a normal Captain message. **Option (a), already supported, zero new code.** |
| 5 | Default-OFF + reuse | `comms.a2ui_enabled` default **False** ([config.py:5210](../src/probos/config.py#L5210)). Reuses schema (`a2ui/__init__.py`), extractor, all three cards. No new kind, endpoint, or config. |
| 6 | AD numbering | Highest top-level heading = **`### AD-1052`** ([DECISIONS.md:603](../DECISIONS.md#L603)) with sub-ADs `AD-1052a/b/c`. `AD-811c` is a pre-reserved #735 sub-number; grep `AD-811c` shows only the forward-marker deferrals (DECISIONS.md:17/27/39) — **not taken** by anything unrelated. No new top-level AD. |

### Teaching block fires on the GROUP path (§3 support)
`_conversational_a2ui_block` ([cognitive_agent.py:2231](../src/probos/cognitive/cognitive_agent.py#L2231))
is appended inside the **shared** `_decide_via_llm` `is_conversation` branch
([:2993](../src/probos/cognitive/cognitive_agent.py#L2993)), beside `_conversational_capability_block`
— **not 1:1-scoped**. The group `direct_message` dispatch hits the same branch (cf. AD-955
`_conversational_room_awareness_protocol` "renders on the GROUP `direct_message` path"). So group
agents are **already taught** the `[A2UI]` tag when `a2ui_enabled=True`. The producer wiring
(`step_4k`) is the only thing between that and a rendered card.

---

## 3. STOP-FLAG (non-blocking for AD-811c; NOT group-specific) — needs Captain confirmation

The shared inline-card render call passes the **prop** `threadId`, but the only live mount passes
**no** `threadId`:

- `AgentProfilePanel.tsx:542` → `<ProfileChatTab agentId={agentId} />` (no `threadId`). It is the
  **only** live `<ProfileChatTab>` mount (grep: rest are archived prompts + the voiceE2E test).
- `ProfileChatTab({ agentId, threadId }: Props)` ([:182](../ui/src/components/profile/ProfileChatTab.tsx#L182))
  → `threadId === undefined` at runtime. There is **no** `const threadId = activeThreadId` reassignment.
- Render call ([:1194](../ui/src/components/profile/ProfileChatTab.tsx#L1194)) passes that undefined
  `threadId`; the card gates are `if (a2ui && threadId …)` ([:128](../ui/src/components/profile/ProfileChatTab.tsx#L128))
  and `if (stub && threadId)` ([:160](../ui/src/components/profile/ProfileChatTab.tsx#L160)).

**Prediction from static analysis:** with `threadId` undefined, inline **A2UI _and_ artifact** cards
gate off and the stub lines fall through to **plain text** in the live HXI — for **both** 1:1 and
group. `artifactsByThread` *is* hydrated for `activeThreadId` (`ArtifactDrawer.tsx:82`), so the fix is
the one-token change `threadId` → `activeThreadId` at line 1194.

**Why this was never caught:** `ProfileChatTab.a2ui.test.tsx` only `?raw` **source-scans** the call
string (`'renderMessageBodyWithArtifacts(msg.text, threadId, (opt) => sendText(opt))'`) and renders
the cards **in isolation** — it never renders `ProfileChatTab` end-to-end ("too heavy under jsdom").
BF-287-class masking: the test encodes a source contract production doesn't satisfy at runtime.

**Architect call:** this is a **separate BF** (it changes AD-797 *artifact* behavior and is **not**
group-specific), NOT part of AD-811c. Bundling it would violate one-AD-one-concern and the "1:1
byte-identical" constraint. **Two things for the Captain:**
1. **Live-verify:** with `a2ui_enabled` on, in a 1:1 today, does an agent's `[A2UI]`/artifact tag
   render as a **card** or as raw stub text? If raw text → confirms the gate; file the render-gate BF
   (`threadId`→`activeThreadId`, lights up cards for **both** 1:1 and group; grep the BF ceiling for
   the next free number).
2. **Sequencing:** ship AD-811c (backend parity) independent of the BF. The visible group card
   appears once the shared render-gate BF lands — same moment 1:1 cards do.

> Net: AD-811c achieves **backend A2UI parity** for group. The *visible card* depends on a shared,
> pre-existing render gate that is identical for 1:1 and group — so AD-811c does not regress anything
> and is correct to ship on its own.

---

## 4. Group-response-semantics recommendation (for confirmation)

**Recommend Option (a): the widget is addressed to the channel; the Captain's pick posts as a normal
Captain group message.** This is exactly what the existing `sendText` group-branch already does
(≥2-crew thread → `POST /api/threads/{id}/messages` as `role:"captain"` → AD-914 fan-out). The same
`onChoice={(opt)=>sendText(opt)}` callback the 1:1 path uses auto-routes correctly because `sendText`
branches on the active thread — **zero new addressing code**.

- Option (b) (widget addressed to a specific participant, correlated reply) requires a new
  addressing/correlation system — that is **AD-811f** (response correlation; "the comma-join's
  label-with-comma ambiguity is resolved there via a structured echo" — DECISIONS.md:27). **Out of
  scope.** Do not invent it here.

---

## 5. Decomposition verdict

**ONE small AD. BACKEND-ONLY. No split.**

- The "group UI renderer" the task anticipated **does not exist as separable work** — the group
  transcript shares the 1:1 `ProfileChatTab` render path, and the response route is the existing
  `sendText` group-branch. There is nothing group-specific to build in the UI.
- The cross-language footprint that would normally force a split (Python wiring + a React renderer +
  dual pytest/vitest) collapses to **Python-only**: a tuple addition + two docstring updates + a new
  pytest file.
- The threadId render-gate is **not** AD-811c work (separate BF, not group-specific — §3).

> **Re-scope vs the task framing:** the task framed AD-811c as "backend group producer + group UI
> renderer." Verified reality: backend producer = ~1 line; group UI renderer = **already shared, no
> work**. So AD-811c ships as a backend-only AD that reaches 1:1↔group parity.

---

## 6. BuildSpec (Builder-ready) — AD-811c

**Scope:** add `step_4k_extract_a2ui` to the group-chat escalation subset so a group agent's `[A2UI]`
tag is extracted into an artifact + inline stub (already persisted + rendered through the shared
path). Default-OFF byte-identical. No UI change. No config. No new kind/endpoint/correlation.

### Backend change 1 — `_escalation_steps()` tuple
[reply_pipeline.py](../src/probos/cognitive/dm/reply_pipeline.py#L201-L209). Insert `step_4k` **after**
`step_4f_extract_artifacts` (preserve `_full_steps` relative order 4f → 4k → 4g):

```python
# SEARCH
            self.step_4f_extract_artifacts,
            self.step_4g_create_task_parse,
            self.step_4j_deliberate_parse,  # AD-934
        )
# REPLACE
            self.step_4f_extract_artifacts,
            self.step_4k_extract_a2ui,      # AD-811c (group A2UI producer; #735)
            self.step_4g_create_task_parse,
            self.step_4j_deliberate_parse,  # AD-934
        )
```

### Backend change 2 — `_escalation_steps()` docstring
Same method's docstring (lines ~175-200). Move `step_4k` from the **Excluded** list to **Included**,
update the order note `4c -> 4e -> 4i -> 4h -> 4f -> 4g -> 4j` → `… 4f -> 4k -> 4g -> 4j`, and add a
one-line AD-811c rationale: *"`step_4k_extract_a2ui` (AD-811a/c) — extracts `[A2UI]` widget tags into
artifacts + inline stubs; channel-agnostic (reads `chat_thread_id`, `a2ui_enabled`), AD-811c activates
it on the group path."* Remove `step_4k` from any "Excluded" enumeration.

### Backend change 3 — `step_4k_extract_a2ui` method docstring
[reply_pipeline.py:1240-1243](../src/probos/cognitive/dm/reply_pipeline.py#L1240). Replace the
*"1:1 only — registered in `_full_steps` but NOT `_escalation_steps` (v1 scope)"* line with: *"AD-811c
registers this in BOTH `_full_steps` (1:1) and `_escalation_steps` (group fan-out); it is
channel-agnostic — `chat_thread_id` and `a2ui_enabled` are set on both paths."*

### No other production change
- `_send_one` / `thread_fanout.py` — **untouched** (already builds `DmReplyContext(chat_thread_id=
  thread_id, response_text=reply_text)` + adopts `ctx.response_text`).
- `a2ui_extractor.py`, `a2ui/__init__.py`, `cognitive_agent.py`, `config.py`,
  `config/system.yaml` — **untouched** (extractor/cards/teaching-block/flag already kind-generic +
  channel-agnostic).
- **UI — untouched** (shared render path; see §3 for the separate render-gate BF).

### Tests — NEW `tests/test_ad811c_group_a2ui.py` (BF-287: real `DmReplyPipeline` + real
`DmReplyContext` + real `ArtifactStore` + real filesystem `AttachmentStore` on `tmp_path` + a
config-shaped runtime with a real `CommunicationsConfig`; fakes only at the registry/intent-bus edges)
~8–12 cases:

1. **Tuple membership + order:** `step_4k_extract_a2ui` ∈ `_escalation_steps()`, positioned **after**
   `step_4f_extract_artifacts` and **before** `step_4g_create_task_parse`.
2. **1:1 unchanged:** `step_4k` still ∈ `_full_steps()`; `_full_steps()` order byte-identical.
3. **Group extract (choice), flag ON:** ctx with `response_text` containing `[A2UI]{choice}[/A2UI]`,
   `a2ui_enabled=True`, `chat_thread_id="t1"` → `run_escalation_only()` → `ctx.response_text` carries
   `[A2UI: a2ui-choice-1.json v1 - choice]` (stub, **not** the raw tag); artifact persisted
   (`artifact_store` has the version, `attachment_store` has the JSON blob).
4. **Flag OFF inert:** same input, `a2ui_enabled=False` → `run_escalation_only()` leaves
   `response_text` **unchanged** (step_4k early-returns); no artifact written.
5. **Kind-genericity:** a `multiselect` (and/or `form`) tag also extracts on the group path via the
   shared `parse_a2ui_spec` (proves no kind coupling).
6. **Honest-degrade:** malformed `[A2UI]{bad json}[/A2UI]` → `response_text` intact, no raise (Tier-2).
7. **End-to-end through `group_chat_fanout`** (real `ChatThreadStore` on `tmp_path` + real
   `IntentBus(SignalManager)` + a scripted `direct_message` handler returning the A2UI tag, flag ON):
   the persisted group message (`store.list_messages`) `body` carries the **stub**, proving it
   survives to persistence (mirror the AD-958c/AD-978 e2e harness).
8. **OFF e2e byte-identical:** same harness, flag OFF → persisted body has no A2UI artifact/stub.

### Gates
- Focused: `pytest tests/test_ad811c_group_a2ui.py -q -n 0`.
- **Load-bearing parity guard (must stay green/UNCHANGED):**
  `pytest tests/test_ad811a_a2ui_choice.py tests/test_ad811b_a2ui_multiselect.py tests/test_ad811b_1_a2ui_form.py -q -n 0` (1:1 path byte-identical).
- Blast-radius: `pytest tests/test_ad914_group_chat_fanout.py tests/test_ad933*.py tests/test_ad956_scale_aware_facilitation.py tests/test_ad978_group_perception.py tests/test_ad958c_peer_correction.py -q -n 0` (fan-out / escalation suites — 0 regressions).
- Full gate per repo convention (isolated `PROBOS_DATA_DIR`): `pytest tests/ -q -n auto`.

---

## 7. What this does NOT change (scope fence)

- **No UI change.** (The inline-card render-gate is a separate, non-group-specific BF — §3.)
- **No response correlation / addressing** — that is **AD-811f**.
- **No new widget kind** (choice/multiselect/form already shipped; AD-811b-1a typed fields deferred).
- **No new endpoint** (reuses `POST /api/threads/{id}/messages` via `sendText`).
- **No new config** (reuses `communications.a2ui_enabled`; **no `config/system.yaml` edit**).
- **No `_send_one` / `DmReplyContext` / facilitator / `IntentMessage` / per-channel adapter (AD-811d) /
  DecisionQueue (AD-811e) change.**
- **No `_full_steps()` reorder** — `step_4k` already lives there; 1:1 stays byte-identical.

---

## 8. Acceptance criteria

- `step_4k_extract_a2ui` runs on the group fan-out path (in `_escalation_steps()`), extracting a group
  agent's `[A2UI]` tag into an artifact + inline stub when `a2ui_enabled=True`.
- `a2ui_enabled=False` → the group path is byte-identical (step inert; no agent emits the tag anyway).
- 1:1 path (AD-811a/b/b-1 suites) stays **green and UNCHANGED** (the load-bearing parity guard).
- New `tests/test_ad811c_group_a2ui.py` green; blast-radius suites 0 regressions.
- **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## 9. Open items for Captain before the Builder runs

1. **Confirm group-response-semantics = Option (a)** (channel-addressed; pick posts as a normal Captain
   group message via the existing `sendText` route). [Recommended; already supported.]
2. **Live-verify the render-gate** (§3): in a 1:1 with `a2ui_enabled` on, does an A2UI/artifact tag
   render as a **card** or raw stub text? If raw → authorize a separate render-gate BF
   (`threadId`→`activeThreadId` at `ProfileChatTab.tsx:1194`) that lights up cards for **both** 1:1 and
   group. AD-811c ships independently either way.

---

## Verified Against Codebase (2026-06-25, HEAD 858380b9)

```
grep step_4k_extract_a2ui reply_pipeline.py
  :167  self.step_4k_extract_a2ui,  # AD-811a (default-OFF; 1:1 only)   [in _full_steps]
  :1233 async def step_4k_extract_a2ui(self) -> None:
  :1242 "1:1 only — registered in _full_steps but NOT _escalation_steps (v1 scope)."
_escalation_steps() return tuple reply_pipeline.py:201-209  -> step_4k ABSENT (4c,4e,4i,4h,4f,4g,4j)

thread_fanout.py:620-638
  :621 pipeline = DmReplyPipeline(DmReplyContext(
  :627   response_text=reply_text,
  :635   chat_thread_id=thread_id,
  :637 await pipeline.run_escalation_only()
  :638 reply_text = pipeline.ctx.response_text or reply_text

cognitive_agent.py
  :2231 def _conversational_a2ui_block(self, observation: dict) -> str:
  :2993 _a2ui_block = self._conversational_a2ui_block(observation)   [shared is_conversation branch]

ProfileChatTab.tsx
  :114  function renderMessageBodyWithArtifacts(text, threadId, onA2UIChoice?)
  :128  if (a2ui && threadId && (kind in choice|multiselect|form))
  :160  if (stub && threadId)
  :182  export function ProfileChatTab({ agentId, threadId }: Props)
  :652  const sendText = useCallback(async (textArg) => {
  :694-710  group branch -> POST /api/threads/${groupThreadId}/messages role:"captain"
  :1194 body={renderMessageBodyWithArtifacts(msg.text, threadId, (opt) => sendText(opt))}
AgentProfilePanel.tsx:542  <ProfileChatTab agentId={agentId} />        [ONLY live mount; NO threadId]
profileTranscript.ts:35  selectTranscriptMessages(activeThreadId, threadMsgs, conv)  [feeds group msgs]
ArtifactDrawer.tsx:82  hydrateArtifacts(activeThreadId, list)          [artifactsByThread IS hydrated]

config.py:5210  a2ui_enabled: bool = Field(... default False ...)
DECISIONS.md:603  ### AD-1052  (sub a/b/c) = highest top-level; AD-811f = response correlation (:17/27/39)
tests: test_ad811a_a2ui_choice.py / test_ad811b_a2ui_multiselect.py / test_ad811b_1_a2ui_form.py
       (no test_ad811c yet)
```
