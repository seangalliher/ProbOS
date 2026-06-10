# AD-934 — In-chat `[THINK]` / `[DELIBERATE]` deep reasoning (DESIGN — needs a Captain decision before build)

**Target repo:** OSS (`d:\ProbOS`). **This AD = AD-934.** Highest committed: AD-933 (`a7004781`).
**Status: DESIGN, not yet buildable as a single clean wiring.** Verified against HEAD; two architectural
problems below make a blind Builder dispatch a hard-stop. This file captures the design so the work is not
lost; the Captain picks an option, then it becomes a build prompt.

## Goal
Let an agent, mid-conversation, judge that a turn needs deeper reasoning than the one-shot reply and run the
**AD-632 sub-task chain** (Q→A→C→E→R) for that turn — agent-judged, per-turn, **never** a global pipeline
switch. The original "let the chain act like a one-shot" idea, in its safest form. **Behind a config flag
default-OFF** (convention #14: transitional behavioral flags default False, flip in a later AD).

## Why it is NOT a clean wiring (verified vs HEAD — the two hard problems)
1. **The dormant hatch is pre-LLM; a `[THINK]` marker is post-LLM.** `_pending_sub_task_chain` is consumed at
   the TOP of `decide()` (`cognitive_agent.py:1989`, Priority-1) — *before* the LLM call — and is **set by
   nothing today** (only `__init__:532` to `None` and the `:1991` consume). So a `[THINK]` emitted in the
   agent's reply (post-LLM) cannot make *that* turn a chain. Acting on it requires either a **two-turn
   re-dispatch** (turn 1 emits `[THINK]` → set pending chain → re-dispatch turn 2 runs the chain) or a
   **pre-LLM trigger** on the inbound message. No re-dispatch trigger exists in the codebase.
2. **`direct_message` has no chain template.** `_build_chain_for_intent` (`cognitive_agent.py:2727`) builds a
   chain only for `ward_room_notification` and `proactive_think`; it `return None` for everything else. Each
   chain's COMPOSE step uses a registered `prompt_template` name (`"ward_room_response"`,
   `"proactive_observation"`). A DM "deliberate" chain needs its own COMPOSE template registered — there is
   none today.

`SubTaskChain` shape (verified, `cognitive/sub_task.py:71`): `steps: list[SubTaskSpec]`, `chain_timeout_ms`,
`fallback`, `source`. `SubTaskSpec`: `sub_task_type` (`SubTaskType`), `name`, `prompt_template` (template
NAME), `context_keys`, `tier`, `timeout_ms`, `required`, `depends_on`. Marker parse/strip pattern to mirror:
`DmSanityGate.extract_create_task`/`strip_create_task` (`cognitive/dm_sanity_gate.py:257/279`, regex-based).

## Design options (Captain picks one)
**Option A — pre-LLM inbound trigger + DM compose template (truest to the marker's intent).**
- New config flag `group_chat.in_chat_deliberate_enabled: bool = False`.
- New `DmSanityGate.extract_think/strip_think` for a `[THINK]`/`[DELIBERATE]` marker.
- New `_build_chain_for_intent` branch for `direct_message` (a DM-shaped Q→A→C→E→R) + a registered
  `"dm_deliberate_*"` COMPOSE/ANALYZE/REFLECT prompt template set.
- Trigger: a lightweight pre-decide pass (or a Captain-supplied `params["deliberate"]`) sets
  `_pending_sub_task_chain` before `decide()`. Agent-judged variant needs the two-turn re-dispatch (Option B).
- Largest surface; most faithful; multiple new templates + a trigger path.

**Option B — two-turn post-reply re-dispatch (agent-judged).**
- Agent emits `[THINK]` in its one-shot reply; a new post-LLM step (mirror `step_4g`) sets
  `agent._pending_sub_task_chain = <DM chain>` and **re-dispatches** the same `direct_message` intent once.
- Requires building the re-dispatch loop (with a re-entrancy guard so a chain reply can't re-trigger) AND the
  DM chain template (shares Option A's template work). Cleanest "agent decides" semantics; new control flow on
  a hot path.

**Option C — redefine `[THINK]` as a post-LLM deep-tier re-roll (does NOT use the chain).**
- `[THINK]` → a single deep-tier LLM pass that reconsiders the agent's own draft reply and replaces it.
- Buildable purely as a new escalation step (no chain, no template, no re-dispatch, no two-turn).
- **But this is a different feature** than "expose the AD-632 chain" — it must be an explicit Captain choice
  to redefine the marker, not a silent substitution.

## Recommendation (Architect)
The **agentic loop** (AD-545) already serves "deep work" better than the fixed 5-stage chain (it is
tool-capable and open-ended), and AD-933 just gave group chat the `[CREATE_TASK]` → agentic-loop path. So
genuine deep work is already covered. `[THINK]`-via-chain only adds value for **tool-free single-agent
deliberation inline**, a narrow slice. **Recommendation: keep this captured (this file) and build only if a
concrete case appears.** If the Captain wants it now, **Option C** (flag-gated deep-tier re-roll) is the
smallest, lowest-risk increment that delivers "noticeably more careful reply on demand" without touching
`decide()` / the chain machinery — at the cost of not literally using the AD-632 chain.

## Hard-stop for any Builder dispatch
Options A and B require changes to `decide()` control flow and/or new registered prompt templates — an
**architectural change**, which is a Builder hard-stop. Do NOT dispatch a Builder on A or B without an
explicit, fully-specified template + trigger design in this file first. Option C is dispatchable as a
flag-gated post-LLM step.

## Scope fence (whatever option)
Flag default-OFF. No change to the existing `ward_room_notification`/`proactive_think` chains, the
one-shot default for live turns, `_CHAIN_ELIGIBLE_INTENTS`, the AD-933 group escalation subset, or the
Ward Room. Never a global pipeline switch — strictly per-turn, agent- or Captain-judged, flag-gated.
