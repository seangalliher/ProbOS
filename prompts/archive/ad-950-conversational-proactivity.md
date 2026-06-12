# AD-950 — Conversational proactivity: teach agents to advance the conversation (forward moves)

**Target repo:** OSS (`d:\ProbOS`). **This AD = AD-950.** GitHub epic `seangalliher/ProbOS#882` (Natural
Conversation); this issue **`#886`**. **Highest committed AD = AD-949** (AD-950 is free — grepped `roadmap.md`
+ `prompts/` + source; only PROGRESS.md mentions it as the planned next item).
**Mode:** Builder. **Backend only (Python).** Commit local. **No push** (the Captain decides the push).
**Builds on / lives beside:** AD-845 `_conversational_task_protocol`, AD-911 `_conversational_notebook_protocol`,
AD-934 `_conversational_deliberate_protocol`, AD-935 `_conversational_group_chat_protocol` — the overridable
conversational-prompt hooks invoked in `CognitiveAgent._decide_via_llm`'s `is_conversation` branch. AD-950 adds a
sibling hook in exactly that spot.
**Wave siblings (DO NOT build — awareness only):** AD-951 (agent next-speaker selection — makes the peer AD-950
addresses actually speak next), AD-952 (human response dynamics — variable turn-length modeling), AD-953
(conversational memory), AD-954 (first-class group/call surface). These are listed in `PROGRESS.md` as the epic
remainder.

## The North Star (Captain's words)
> "These are persistent agents with sovereign identity. When engaged in a conversation the dialog should be rich
> and engaging. The goal is that I could bring up a chat with the agents and start a conversation and a stranger
> walking in would not be able to tell that they were AI."

Captain-reported symptom: **in 1:1 the agent is PASSIVE** — it answers and stops; the Captain has to keep the
conversation going. Worse in group. This AD is the single highest-impact Turing-test lever in the epic.

## The problem (Conversation-Analysis framing)
Agents only ever produce **second-pair-parts** (answers) and never **first-pair-parts** (questions / proposals)
or next-speaker selections, so the conversation has no momentum and dies between Captain turns. The fix is to
teach the discourse **obligation** to advance the conversation: end an engaged turn with a forward-pointing move
(a genuine follow-up question or proposal in 1:1; optionally address a peer by name in group), **calibrated** by
personality + engagement — *not* relentless interrogation. Grounding: adjacency pairs (Schegloff),
mixed-initiative dialogue + discourse obligations (Traum & Allen), preference organization (productive
disagreement), recipient design (address by name, react to specifics).

---

## Goal

On the **live 1:1 / group conversational reply path** (`intent == "direct_message"`), append a calibrated
**conversation-advancing** instruction to the agent's system prompt so an engaged turn ends with **ONE** forward
move. Add a **group-only** extension (gated on the fan-out param `is_group_chat`) that permits handing the floor
to a peer by name. Ship it through **one shared hook** so 1:1 and group both inherit it. Default **ON** behind a
single `CommunicationsConfig.proactive_conversation_enabled` tuning knob.

This is **instructions-first** (Design Principle #6): the behavior lives entirely in the system-prompt text the
LLM reasons over — **no** scripted follow-ups in `decide()`/`act()`, **no** structural dispatch change.

---

## Verified current shape (grep evidence in the footer)

### 1. The single shared instruction-assembly site — `cognitive_agent.py`

`CognitiveAgent._decide_via_llm` classifies the call and, for conversational intents, composes the prompt with
**`hardcoded_instructions=""`** (so an agent's static instructions / standing orders **never reach this path**):

```python
# cognitive_agent.py:2231
is_conversation = observation.get("intent") in ("direct_message", "ward_room_notification", "proactive_think")
...
if is_conversation:
    composed = compose_instructions(
        agent_type=...,
        hardcoded_instructions="",   # :2246  ← standing orders DO NOT reach here
        ...
    )
    if observation.get("intent") == "ward_room_notification":
        ...                          # ward-room (+ DM-channel sub-case)
    elif observation.get("intent") == "proactive_think":
        ...                          # proactive observation / [PROPOSAL]
    else:                            # ← intent == "direct_message" : the live 1:1 AND group path
        composed += "\n\nYou are in a 1:1 conversation with the Captain. ..."
    # --- the overridable conversational hooks, appended for ALL three branches: ---
    _cap_block   = self._conversational_capability_block(observation)      # BF-599
    _task_proto  = self._conversational_task_protocol(observation)         # AD-845
    _nb_proto    = self._conversational_notebook_protocol(observation)     # AD-911
    _delib_proto = self._conversational_deliberate_protocol(observation)   # AD-934
    _group_proto = self._conversational_group_chat_protocol(observation)   # AD-935  (gates on params["is_group_chat"])
    # ← AD-950 inserts its hook here, after _group_proto
else:
    composed = compose_instructions(..., hardcoded_instructions=self.instructions or "", ...)
```

> **`else` == `direct_message`.** Because `is_conversation` is only true for those three intents, the `else`
> branch catches exactly `direct_message` — which is **both** 1:1 and group. So gating AD-950 on
> `observation.get("intent") == "direct_message"` precisely targets the live conversational reply path the
> Captain is complaining about, and leaves ward-room / proactive (which already carry their own
> conversation-advancing guidance: *"agree, disagree, build on ideas, ask questions"*) untouched.

### 2. 1:1 vs group thread the same intent; only group sets `is_group_chat`

| Path | Site | `intent` | `is_group_chat`? |
|---|---|---|---|
| 1:1 Captain chat | `routers/agents.py:2181` | `"direct_message"` | **no** (`_params` at `:2168`–`2173`) |
| `@callsign` from main chat bar | `routers/chat.py` / `api.py` (BF-009) | `"direct_message"` | **no** |
| Group fan-out | `routers/thread_fanout.py:282` | `"direct_message"` | **`True`** |

All production `direct_message` emitters are Captain-facing **live** chat, so the universal guidance lands on
exactly the right surfaces; the group-only paragraph lands only on the fan-out (the one site that sets
`is_group_chat`). (Test-only `direct_message` builders in `test_ad398/604/637f` are not production paths.)

### 3. The AD-935 group hook (the exact pattern AD-950 mirrors) — `cognitive_agent.py:~1934`

```python
def _conversational_group_chat_protocol(self, observation: dict) -> str:
    params = observation.get("params") or {}
    if not params.get("is_group_chat"):
        return ""
    return ("\n\nYou are in a group chat with other crew. Reply ONLY when you have ... [NO_RESPONSE] ...")
```

AD-934's hook reads config the way AD-950 will:
`cfg = getattr(getattr(runtime, "config", None), "dm_deliberate", None)` then `getattr(cfg, "enabled", False)`.

### 4. `CommunicationsConfig` (the flag's home) — `config.py:4613`, mounted `:5285`

Holds the conversation-policy fields (`dm_min_rank`, `group_chat_min_rank`, `recreation_min_rank`,
`artifact_*`, `status_*`, `presence_working_window_seconds`). Mounted on `SystemConfig` as
`communications: CommunicationsConfig = CommunicationsConfig()`. Precedent in the same class:
`presence_working_window_seconds` ships ON by default with the note *"Read-only/computed … not a transitional
behavioral flag."*

### 5. The capability-gap regex — `decomposer.py:33` (audit every added string)

`_CAPABILITY_GAP_RE` (case-insensitive) matches: `don't have`, `can't`/`cannot`, `unable to`,
`no (built-in|native)? (capability|ability|support|way|mechanism|tool)`, `not (available|supported|possible)`,
`lack(s|ing)?`, `doesn't (have|support)`, `beyond (my|current) (capabilities|abilities)`,
`outside (my|the) (scope|capabilities)`. **None** of these may appear in AD-950's instruction text (both the
universal and group renderings are tested against the regex).

---

## Design decisions (documented)

### A. One shared **cognitive_agent hook**, NOT a standing order

The conversational reply path composes with `hardcoded_instructions=""` (§1), so **a standing order in
`federation.md` would be dead** for this purpose — it never reaches the 1:1/group reply. (AD-924's group-chat
standing order works on the *proactive* path, which composes with the agent's real static instructions; that is a
different surface.) AD-950 therefore lives **only** in a new overridable hook
`_conversational_proactivity_protocol`, invoked in the one `is_conversation` branch that **both** 1:1 and group
flow through. **Do not** add or edit any `config/standing_orders/*.md` file.

### B. Flag: `CommunicationsConfig.proactive_conversation_enabled: bool = True` — **default ON, a tuning knob**

This is **pure prompt text** appended to a reply the LLM is already generating: **no extra LLM pass, no added
latency, no cost, no structural change, no loop risk.** Convention #14's default-OFF rule is for *risky
structural* changes (AD-934's deep-tier re-roll, AD-935's a2a cascade, AD-925's auto task-rooms) — not for
behavior-shaping instruction text. The sibling instruction hooks (BF-599 capability, AD-845 task, AD-911
notebook) all ship **ON** for the agents/paths they apply to, gated by opt-in/substrate rather than a kill
switch. The North Star wants richness **by default** — the highest-impact Turing lever must not ship dark. We add
**one default-ON enable knob** so the Captain has a clean off-switch / tuning point if the proactivity ever reads
as over-eager (the AD-949 "audible by default + an in-call mute" philosophy, applied to conversation). Home =
`CommunicationsConfig` (it already spans DM + group + recreation policy; AD-924 precedent). **Default-ON even
when config is absent** (`getattr(comm_cfg, "proactive_conversation_enabled", True)`) so a bare runtime still gets
the richness.

### C. `is_group_chat` gates only the group-only paragraph

Universal forward-move guidance fires for **every** `direct_message` (1:1 + group). The **peer-address**
paragraph is appended **only** when `observation["params"].get("is_group_chat")` is truthy — set exclusively by
the group fan-out (`thread_fanout.py:282`). 1:1 and `@callsign` omit it, so a 1:1 reply gets the universal
guidance only. This exactly mirrors AD-935.

---

## Section 1 — MODIFY `src/probos/config.py`: add the default-ON flag to `CommunicationsConfig`

Insert after `presence_working_window_seconds` (the last field of `CommunicationsConfig`, `:4632`):

```
SEARCH:
    # AD-930: presence "working" = an operation completed within this many
    # seconds (recent-activity proxy via AgentMeta.last_active; there is no
    # true in-flight signal at HEAD — AD-930a). Read-only/computed, so this
    # ships ON by default (not a transitional behavioral flag).
    presence_working_window_seconds: float = 90.0


class WorkforceConfig(BaseModel):

REPLACE:
    # AD-930: presence "working" = an operation completed within this many
    # seconds (recent-activity proxy via AgentMeta.last_active; there is no
    # true in-flight signal at HEAD — AD-930a). Read-only/computed, so this
    # ships ON by default (not a transitional behavioral flag).
    presence_working_window_seconds: float = 90.0
    # AD-950: conversation-advancing ("proactivity") guidance on the live
    # 1:1/group direct_message reply path — teach agents to end an engaged turn
    # with ONE forward move (a follow-up question or proposal) so a conversation
    # has momentum instead of dying between Captain turns. Pure prompt text (no
    # extra LLM pass, no cost, no structural change), so it ships ON for the
    # richness the North Star demands; this is the Captain's tuning knob /
    # off-switch if the proactivity ever reads as over-eager.
    proactive_conversation_enabled: bool = True


class WorkforceConfig(BaseModel):
```

> One additive field, default `True`. No other config touched. Zero-config boot stays byte-identical except the
> new (ON) default.

---

## Section 2 — MODIFY `src/probos/cognitive/cognitive_agent.py`: add the hook definition

Insert the new hook **immediately after** `_conversational_group_chat_protocol` returns and **before**
`async def decide` (`:~1948`):

```
SEARCH:
        return (
            "\n\nYou are in a group chat with other crew. Reply ONLY when you have "
            "something substantive to add, build on, answer, or correct. If a "
            "fellow crew member directs a question to you, answer it. When you have "
            "nothing to add, respond with exactly [NO_RESPONSE] and nothing else."
        )

    async def decide(self, observation: dict) -> dict:

REPLACE:
        return (
            "\n\nYou are in a group chat with other crew. Reply ONLY when you have "
            "something substantive to add, build on, answer, or correct. If a "
            "fellow crew member directs a question to you, answer it. When you have "
            "nothing to add, respond with exactly [NO_RESPONSE] and nothing else."
        )

    def _conversational_proactivity_protocol(self, observation: dict) -> str:
        """AD-950 (Natural Conversation epic, #886): teach the discourse OBLIGATION
        to ADVANCE a live conversation. On the 1:1/group ``direct_message`` reply
        path, append calibrated guidance to end an ENGAGED turn with ONE forward
        move — a genuine follow-up question, or a proposal/offer that gives the
        other party an easy opening to respond — using recipient design (react to
        specifics, address by name). NOT every turn: calibrated to engagement and
        the agent's personality so it reads as conversation, not interrogation. In
        a group chat (the fan-out param ``is_group_chat``) it additionally permits
        handing the floor to a peer by name (sets up AD-951's next-speaker
        selection). Gated to the live conversational path (intent ==
        "direct_message") so ward-room / proactive posts — which already carry
        their own conversation-advancing guidance — are unaffected. Default ON via
        ``CommunicationsConfig.proactive_conversation_enabled`` (a tuning knob, not
        a kill switch); honest-degrade returns "" when the flag is off. Overridable
        (Open/Closed). Gap-regex-safe (no can't/cannot/don't have/unable to/not
        able to)."""
        if observation.get("intent") != "direct_message":
            return ""
        runtime = getattr(self, "_runtime", None)
        comm_cfg = getattr(getattr(runtime, "config", None), "communications", None)
        if not getattr(comm_cfg, "proactive_conversation_enabled", True):
            return ""
        guidance = (
            "\n\nKeeping the conversation alive: you are a participant in a real "
            "conversation, not a question-answering service. When the exchange is "
            "engaged and a natural next step exists, end your turn with ONE forward "
            "move — a genuine follow-up question, an observation that invites a "
            "reply, or a concrete proposal or offer that gives the other person an "
            "easy opening to respond. Do this when it fits the moment, NOT on every "
            "turn: read the Captain's engagement and your own personality, and let "
            "a turn rest when that is the natural thing (a simple acknowledgement, a "
            "closing thought, or a beat the Captain plainly wants to end). React to "
            "the SPECIFIC thing that was said — name it and build on it — rather "
            "than replying in the abstract. Match your length to the move: a brief "
            "reaction when that is enough, a fuller contribution when the topic "
            "earns it. Honest, respectful disagreement is welcome when your "
            "expertise points a different direction — reflexive agreement reads as "
            "hollow. Ground every follow-up in what was actually said; never invent "
            "a question or proposal about something that did not occur."
        )
        params = observation.get("params") or {}
        if params.get("is_group_chat"):
            guidance += (
                "\n\nBecause this is a group chat, you may also hand the floor to a "
                "specific crew member when their expertise fits the moment: address "
                "them directly by name (their callsign) and put the question or "
                "proposal to them, the way colleagues pull a teammate into a "
                "discussion. Use this to keep the conversation moving across the "
                "crew — one clear hand-off to the right person, not a prompt aimed "
                "at everyone at once."
            )
        return guidance

    async def decide(self, observation: dict) -> dict:
```

---

## Section 3 — MODIFY `src/probos/cognitive/cognitive_agent.py`: invoke the hook

Insert the invocation **immediately after** the AD-935 `_group_proto` block and **before** the `else:` that
closes `if is_conversation:` (`:~2425`):

```
SEARCH:
            # AD-935: group-chat decline protocol. Overridable hook; base returns
            # "" unless the fan-out passed params["is_group_chat"], so the
            # [NO_RESPONSE] decline option is taught only inside a group chat.
            _group_proto = self._conversational_group_chat_protocol(observation)
            if _group_proto:
                composed += _group_proto
        else:
            composed = compose_instructions(

REPLACE:
            # AD-935: group-chat decline protocol. Overridable hook; base returns
            # "" unless the fan-out passed params["is_group_chat"], so the
            # [NO_RESPONSE] decline option is taught only inside a group chat.
            _group_proto = self._conversational_group_chat_protocol(observation)
            if _group_proto:
                composed += _group_proto
            # AD-950: conversation-advancing (proactivity) protocol. Overridable
            # hook; base returns "" unless on the live 1:1/group direct_message
            # path AND CommunicationsConfig.proactive_conversation_enabled (default
            # ON). Teaches ending an engaged turn with ONE forward move; the
            # group-only peer-address part gates on params["is_group_chat"], so 1:1
            # gets the universal guidance only. Composes with the AD-935 decline
            # protocol above (reply only when substantive) — AD-950 shapes the
            # turns the agent DOES take.
            _proactive_proto = self._conversational_proactivity_protocol(observation)
            if _proactive_proto:
                composed += _proactive_proto
        else:
            composed = compose_instructions(
```

> The hook is appended in the shared `is_conversation` block, but its own `intent == "direct_message"` gate means
> it is inert for the ward-room and proactive branches (which also reach this append point). Net effect: fires on
> 1:1 + group only.

---

## Section 4 — NEW `tests/test_ad950_conversational_proactivity.py`

**BF-287 discipline:** real `CommunicationsConfig` (NOT `MagicMock`) for the flag paths; the hook is exercised via
the real `CognitiveAgent._conversational_proactivity_protocol` bound to a `SimpleNamespace` self (the AD-934/935
pattern). Assert the assembled guidance **contains** the proactivity obligation, that the group-only paragraph is
present **only** when `is_group_chat`, and that both renderings are `_CAPABILITY_GAP_RE`-clean.

Harness:

```python
from types import SimpleNamespace

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.decomposer import _CAPABILITY_GAP_RE
from probos.config import CommunicationsConfig

_HOOK = CognitiveAgent._conversational_proactivity_protocol

# A distinctive phrase that appears ONLY in the group-only paragraph, used to
# prove the conditional (present for group, absent for 1:1).
_GROUP_MARKER = "hand the floor"


def _self(*, enabled: bool | None = None):
    """SimpleNamespace self. enabled=None -> no runtime (default-ON path);
    else a real CommunicationsConfig under _runtime.config.communications."""
    if enabled is None:
        return SimpleNamespace()
    comm = CommunicationsConfig(proactive_conversation_enabled=enabled)
    return SimpleNamespace(_runtime=SimpleNamespace(config=SimpleNamespace(communications=comm)))


def _gap_clean(text: str) -> None:
    assert _CAPABILITY_GAP_RE.search(text) is None
    for banned in ("can't", "cannot", "don't have", "unable to", "not able to"):
        assert banned not in text.lower()
```

Required cases (≥9):

1. `test_inert_on_ward_room_and_proactive` — `{"intent":"ward_room_notification","params":{}}` and
   `{"intent":"proactive_think","params":{}}` → `""` (even default-ON), so the existing branches are untouched.
2. `test_1to1_nonempty_and_gap_safe` — `{"intent":"direct_message","params":{}}` on `_self()` → non-empty;
   `_gap_clean(out)`; `_GROUP_MARKER not in out` (1:1 omits the peer-address paragraph).
3. `test_1to1_teaches_forward_move` — assert the universal text names the obligation
   (`"forward move" in out` and `"follow-up" in out.lower()`).
4. `test_calibration_language_present` — assert the anti-interrogation calibration survives any future edit:
   `"NOT on every turn" in out` (or `"not on every turn" in out.lower()`) and `"personality" in out.lower()`.
   This is the regression guard against AD-950 silently becoming relentless.
5. `test_honesty_clause_present` — `"never invent" in out.lower()` (proactivity must not induce fabricated
   follow-ups).
6. `test_group_includes_peer_address_and_gap_safe` — `{"intent":"direct_message","params":{"is_group_chat":True}}`
   on `_self()` → contains the universal text **and** `_GROUP_MARKER`; `"callsign" in out.lower()`;
   `_gap_clean(out)`.
7. `test_flag_off_returns_empty_for_both` — `_self(enabled=False)` → `""` for both the 1:1 and the group
   observations.
8. `test_default_on_when_config_absent` — bare `_self()` (no `_runtime`) + 1:1 observation → non-empty
   (proves `getattr(..., True)` default-ON).
9. `test_config_default_is_on` — `CommunicationsConfig().proactive_conversation_enabled is True`.

Call shape for every hook case: `out = _HOOK(_self(...), {"intent": "...", "params": {...}})`.

---

## Test gates (the Builder MUST run all)

- **Focused gate (must be green):**
  `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -k "cognitive_agent or dm or reply or pipeline or standing or group or facilitat or config" -q -p no:cacheprovider`
- The `tests/test_skill_agent.py::TestSkillPipeline` serial-isolation flakes are **pre-existing** (green in
  isolation; event-loop pollution from skill-pool spawning) — **do not chase them**; verify any such failure is
  green when the file is run alone (`-n 0`) and move on.
- **Capability-gap audit:** every added instruction string passes `_CAPABILITY_GAP_RE.search(...) is None`
  (covered by cases 2 & 6; the Builder re-confirms the regex on any wording change).
- Report the focused-gate `passed` count and the `+N pytest` delta.

---

## Do **NOT** (scope fence)

- **No scripted follow-ups in `decide()` / `act()`** (or anywhere). The behavior lives **only** in the
  instruction text the hook returns. The hook must not branch on message content or hardcode a specific
  question/proposal — Design Principle #6 (instructions-first).
- **Not relentless.** Keep the calibration clauses verbatim in spirit — *"NOT on every turn"*, *"calibrated to
  engagement + personality"*, *"let a turn rest"*. Do **not** strengthen the guidance into "always end with a
  question." (Case 4 guards this.)
- **No fabrication.** Keep the *"Ground every follow-up in what was actually said; never invent …"* clause.
  Proactivity must not induce confabulated follow-ups — respect AD-722a divergence and episodic honesty.
- **No capability-gap-regex-matching text.** Audit every added string against `_CAPABILITY_GAP_RE`.
- **No standing-order edit.** Do **not** add/modify `config/standing_orders/federation.md` (or any standing
  order) — it would not reach the conversational reply path (`hardcoded_instructions=""`).
- **Preserve destructive-intent consensus.** This is reply-shaping prompt text only. Do **not** touch intent
  dispatch, the decomposer, `requires_consensus`, the escalation ladder, or consensus. A proposal/offer *in
  chat* is conversational; any actual destructive action still routes through the existing gates.
- **One length clause only — coordinate with AD-952.** AD-950 keeps a single *"match your length to the move"*
  clause. The full human-response-dynamics / turn-length modeling is **AD-952** — do **not** build a separate
  length-control mechanism here. One place.
- **Do not build AD-951.** AD-950 only *permits* addressing a peer by name; making the named peer actually speak
  next is **AD-951**. No fan-out / next-speaker / facilitator change here.
- **No edits** to the AD-935 group decline hook, AD-934 deliberate, AD-845 task, AD-911 notebook, BF-599
  capability block, the ward-room / proactive branches, `thread_fanout.py`, `routers/agents.py`,
  `routers/chat.py`, or any LLM-call plumbing. AD-950 is **three additive edits + one new test file.**

---

## Files

| File | Change |
|---|---|
| `src/probos/config.py` | +1 field `CommunicationsConfig.proactive_conversation_enabled = True` |
| `src/probos/cognitive/cognitive_agent.py` | + hook `_conversational_proactivity_protocol` (def) + its invocation in the `is_conversation` branch |
| `tests/test_ad950_conversational_proactivity.py` | NEW (+≥9 pytest) |

## Tracking (same commit)

- `docs/development/roadmap.md` — AD-950 row, `SHIPPED <date> gate-verified`, contiguous after AD-949.
- `PROGRESS.md` — AD-950 block prepended (note: hook-not-standing-order rationale; default-ON flag; group-only
  gate; sets up AD-951).
- `DECISIONS.md` — AD-950 entry above AD-949 (Decisions A–C above).
- Commit message `AD-950: <title>`. Commit local; **do not push**.

## Acceptance criteria

- [ ] `CommunicationsConfig.proactive_conversation_enabled` defaults `True`; zero-config boot unaffected otherwise.
- [ ] `_conversational_proactivity_protocol` returns the universal forward-move guidance for `direct_message`
      (1:1 + group), the group-only peer-address paragraph **only** when `is_group_chat`, and `""` for
      ward-room / proactive and when the flag is off.
- [ ] Both renderings are `_CAPABILITY_GAP_RE`-clean.
- [ ] ≥9 pytest in `tests/test_ad950_conversational_proactivity.py`; focused gate green; skill-pool isolation
      flakes confirmed pre-existing, not chased.
- [ ] No scripted follow-ups in `decide()`/`act()`; no standing-order, dispatch, consensus, fan-out, or
      LLM-plumbing change.
- [ ] **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Verified Against Codebase (2026-06-09)

```
grep -n "is_conversation =" src/probos/cognitive/cognitive_agent.py
  2231: is_conversation = observation.get("intent") in ("direct_message", "ward_room_notification", "proactive_think")

# conversational compose uses hardcoded_instructions="" (standing orders never reach the DM/group reply)
read cognitive_agent.py:2239-2251
  2246:                hardcoded_instructions="",

# the else branch (== direct_message) — "You are in a 1:1 conversation with the Captain"
read cognitive_agent.py:2370-2382  ("You are in a 1:1 conversation with the Captain. ...")

# the AD-935 group hook + the invocation site AD-950 inserts after
grep -n "_conversational_group_chat_protocol" src/probos/cognitive/cognitive_agent.py
  1934: (docstring) "group fan-out param ``is_group_chat``"
  1938:         if not params.get("is_group_chat"):
  2421:             _group_proto = self._conversational_group_chat_protocol(observation)

# AD-934 config-read pattern AD-950 mirrors (inverted default)
read cognitive_agent.py:1913-1925  (getattr(getattr(runtime,"config",None),"dm_deliberate",None); getattr(cfg,"enabled",False))

# group fan-out sets is_group_chat; 1:1 + @callsign do not
grep -n "is_group_chat" src/probos/routers/thread_fanout.py
  282:             "is_group_chat": True,
read routers/agents.py:2168-2185  (_params: text/from/session/session_history — NO is_group_chat; intent="direct_message" @ :2181)
grep -rn 'intent\s*=\s*["\x27]direct_message["\x27]'  → production emitters: agents.py:2181, thread_fanout.py, chat.py/api.py(BF-009); rest are tests/docs

# flag home + mount
grep -n "class CommunicationsConfig" src/probos/config.py        → 4613
read config.py:4628-4632  (presence_working_window_seconds: float = 90.0  ← insertion anchor)
grep -n "communications: CommunicationsConfig" src/probos/config.py → 5285

# capability-gap regex (audit anchor)
grep -n "_CAPABILITY_GAP_RE = re.compile" src/probos/cognitive/decomposer.py → 33
read decomposer.py:33-40  (don't have|can't|cannot|unable to|no …(capability|ability|support|way|mechanism|tool)|not (available|supported|possible)|lack…|doesn't (have|support)|beyond …(capabilities|abilities)|outside …(scope|capabilities))

# test harness precedents
read tests/test_ad935_group_reactivity.py:420-440  (CognitiveAgent._conversational_group_chat_protocol(SimpleNamespace(), obs) + _CAPABILITY_GAP_RE.search(out) is None)
read tests/test_ad934_deliberate.py:60-66          (real DmDeliberateConfig under SimpleNamespace(config=...))

# AD-950 free
grep -rn "AD-950" → only PROGRESS.md (planned-next marker); no roadmap row, no source, no prompt
```
