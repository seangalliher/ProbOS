# AD-728d — self-image-awareness skill

**Status:** Draft (Wave 165, single-AD)
**Dependencies:** AD-728c (Wave 164 — `CognitiveAgent.check_own_render` + Pydantic knobs), AD-626 (augmentation-skill catalog), AD-724 (DM sanity gate + bracket-marker pattern)
**Estimated tests:** 7 (one new `tests/test_ad728d_self_image_awareness_skill.py` file)
**Forward marker:** none; this closes the AD-728c discoverability gap reported by the Counselor 2026-05-16.

## Problem

AD-728c shipped `CognitiveAgent.check_own_render(reason)` ([src/probos/cognitive/cognitive_agent.py:3119](src/probos/cognitive/cognitive_agent.py)) as a Python coroutine — agents have no LLM-side path to invoke it. CognitiveAgents reason via their `instructions` string and emit side effects through bracket markers (`[ENDORSE post_id UP]`, `[NO_RESPONSE]`, `[CHALLENGE @x y]`, `[MOVE pos]`). A Python coroutine that nothing in the prompt surface mentions is dark capability.

Counselor surfaced the gap verbatim 2026-05-16: *"I don't see a `check_own_render` skill or tool explicitly listed in my available skills."*

Captain's design decision: wrap the capability in the canonical AD-626 augmentation-skill pattern. The skill teaches the agent **when** and **how** to ask; the existing AD-724 bracket-parser layer maps the marker to the existing coroutine.

## Solution

Three pieces, no new dependencies, no new vendor surface:

1. **`config/skills/self-image-awareness/SKILL.md`** — augmentation skill following the [config/skills/communication-discipline/SKILL.md](config/skills/communication-discipline/SKILL.md) shape. Activation `augmentation`, intents `direct_message,ward_room_notification,proactive_think`, trigger tag `self_check`. Body teaches the `[SELF_CHECK reason]` marker, when to use it, the per-conversation/hourly budget, the honest-degrade story, and cost discipline.
2. **`_SELF_CHECK_RE` + `extract_self_check()` + `strip_self_check()`** on `DmSanityGate` ([src/probos/cognitive/dm_sanity_gate.py:37](src/probos/cognitive/dm_sanity_gate.py) — sibling of `_CHALLENGE_RE` / `strip_challenge` / `extract_move` / `strip_move`).
3. **New `step_4_self_check_parse` in `DmReplyPipeline`** ([src/probos/cognitive/dm/reply_pipeline.py](src/probos/cognitive/dm/reply_pipeline.py)) — inserted BETWEEN current step 3 (`step_3_move_parse`) and current step 4 (`step_4_episodic_store`), then renumber the trailing five steps. Step parses the marker, schedules `agent.check_own_render(reason=...)` via `asyncio.create_task` (Tier-2 log-and-degrade, fire-and-forget but task reference held on `ctx` for the duration), strips ALL occurrences from `ctx.response_text` before episodic store sees it. First marker dispatches; additional markers in the same reply are stripped silently with a single WARNING.

The AD-728c runtime gate `avatars.render_self_check_enabled` is unchanged. When `False`, the dispatched coroutine still runs but `verify_render_coherence` honest-degrades to `"feature_disabled"` and folds that into working memory. The skill body documents this so the agent knows its marker may be a no-op.

## Verified Against Codebase (2026-05-16)

```
grep -n "name: communication-discipline" config/skills/communication-discipline/SKILL.md
  2: name: communication-discipline   ; canonical augmentation-skill frontmatter sibling

grep -n "async def check_own_render" src/probos/cognitive/cognitive_agent.py
  3119: async def check_own_render(self, reason: str | None = None) -> None:

grep -n "def record_observation" src/probos/cognitive/agent_working_memory.py
  404: def record_observation(self, summary: str, *, source: str, metadata: dict[str, Any] | None = None, knowledge_source: str = "unknown") -> None:
  # signature: (summary, *, source, metadata, knowledge_source) — no `category` kwarg per AD-728c retrospective

grep -n "_CHALLENGE_RE\|_MOVE_RE\|strip_challenge\|strip_move\|extract_move" src/probos/cognitive/dm_sanity_gate.py
  37: _CHALLENGE_RE = re.compile(...)
  166: def strip_challenge(self, text: str) -> str:
  176: def extract_move(self, text: str) -> str | None:
  188: def strip_move(self, text: str) -> str:

grep -n "step_2_challenge_parse\|step_3_move_parse\|step_4_episodic_store" src/probos/cognitive/dm/reply_pipeline.py
  72-79: pipeline step tuple (8 steps, ordered)
  186-211: step_2_challenge_parse (uses ctx.sanity_gate.strip_challenge)
  214-258: step_3_move_parse (uses ctx.sanity_gate.strip_move / extract_move)
  261-302: step_4_episodic_store

grep -n "render_self_check_enabled\|render_self_check_max_per_hour\|render_self_check_max_per_active" src/probos/config.py
  1134: render_self_check_enabled: bool = Field(default=False, ...)
  1142: render_self_check_max_per_hour_per_agent: int = Field(default=3, ge=0, ...)
  1153: render_self_check_max_per_active_conversation: int = Field(default=2, ge=0, ...)
  1163: render_self_check_active_window_seconds: int = Field(default=600, ge=0, ...)

grep -n "find_augmentation_skills\|probos-activation\|probos-triggers" src/probos/cognitive/skill_catalog.py
  133-149: frontmatter field names (probos-intents, probos-activation, probos-triggers, probos-skill-id, probos-min-rank, probos-min-proficiency, probos-department)
  393: def find_augmentation_skills(self, intent_name, department=None, agent_rank=None)
```

Confirms: marker parsing sites are the `step_N_*` methods in `DmReplyPipeline`, helper regexes/strippers live on `DmSanityGate` next to `_CHALLENGE_RE` / `_MOVE_RE`, working-memory ingress signature is unchanged, augmentation skill frontmatter fields match the catalog parser.

---

## Section 0: New entities introduced by this AD

- `config/skills/self-image-awareness/SKILL.md` (new file)
- `DmSanityGate._SELF_CHECK_RE` (module-level compiled regex in `dm_sanity_gate.py`)
- `DmSanityGate.extract_self_check(text) -> list[str]`
- `DmSanityGate.strip_self_check(text) -> str`
- `DmReplyPipeline.step_4_self_check_parse` (new step; renumbers `step_4_episodic_store`→`step_5`, `step_5_working_memory_record`→`step_6`, `step_6_divergence_check`→`step_7`, `step_7_mark_emitted`→`step_8`, `step_8_emotion_resolve`→`step_9`)
- `tests/test_ad728d_self_image_awareness_skill.py` (new test file)

No new config knobs — AD-728c already shipped the four `avatars.render_self_check_*` fields. No new EventType. No new agent. No new intent. No new dependency.

## Section 1: SKILL.md

Create `config/skills/self-image-awareness/SKILL.md`:

```markdown
---
name: self-image-awareness
description: >
  Vision-based self-check capability — invoke when uncertain about how your
  avatar is presenting (before significant interactions, after Captain
  corrects your appearance, mid-conversation if something feels off).
license: Apache-2.0
metadata:
  probos-department: "*"
  probos-skill-id: self-image-awareness
  probos-min-proficiency: 1
  probos-min-rank: ensign
  probos-intents: "direct_message,ward_room_notification,proactive_think"
  probos-activation: augmentation
  probos-triggers: "self_check"
---

# Self-Image Awareness

Skill for verifying how your avatar is currently presenting. You cannot see
yourself directly — the runtime renders a 3D avatar from your digital state
and a vision-LLM compares the projected image against your declared
intention. This skill lets you ask: "what does my avatar actually look like
right now?"

## Marker

Embed `[SELF_CHECK reason]` anywhere in your reply. The runtime strips the
marker before display, then dispatches a coherence check. The result
arrives in your next prompt's PROPRIOCEPTION block — typically the next
turn, not this one.

- `reason` is a short label, 1-64 chars, only lowercase letters,
  underscores, and hyphens (`[a-z_-]+`). Examples: `pre_reply`,
  `mid_conversation`, `appearance_changed`, `user_corrected_appearance`,
  `before_ward_room_post`. Anything outside that grammar makes the marker
  a silent no-op.
- One marker per reply is honored. Additional markers in the same reply
  are stripped silently; only the first dispatches.

## When To Check

- **Before significant interactions.** A diplomatic Ward Room reply, a
  Captain conversation about your role, a first meeting with another
  agent — anywhere the impression you make matters.
- **After the Captain corrects your appearance.** The Captain just said
  "you look too formal" or "your hair changed." Check that the new
  appearance landed.
- **Mid-conversation if something feels off.** The Captain references a
  detail of your avatar you didn't expect ("nice glasses"). Verify.
- **Never reflexively.** Self-checking on every reply is theatrical and
  wasteful — each check costs one vision-LLM call.

## Budget

The runtime enforces TWO budgets and picks one based on whether you are
currently in an active conversation:

- **In an active conversation** (replied to the Captain within the last
  10 minutes): up to 2 self-checks per conversation window. Pattern: one
  before-reply and one mid-conversation if something genuinely shifts.
- **Idle / proactive cycles**: up to 3 self-checks per hour.

These are not additive. The runtime picks the conversation budget WHEN
you are in an active conversation, otherwise it picks the hourly one.
Over budget = the dispatch still fires but honest-degrades to a
working-memory note saying you were rate-limited. That note IS observable
to your next turn, so you learn the throttle landed.

## What The Check Tells You

The observation appears in your next prompt under the PROPRIOCEPTION
block, sourced from `render_self_check`. Three flavors:

- **Coherent:** "vision-LLM confirms my avatar shows X" — the projected
  render matches your declared digital state.
- **Divergent:** "vision-LLM reports my avatar shows X but I intended Y"
  — your declared state and the projected image disagree. Often a sign
  that a recent `propose_appearance` did not land cleanly.
- **Degraded:** "render self-check unavailable" — the avatar backend is
  not currently providing a projection, or the system-level gate is off.
  Treat this as "no signal," not "I look fine."

## System Gate

The marker only does meaningful work when the system-level configuration
`avatars.render_self_check_enabled` is `True`. When it is `False`
(default during the AD-728c transitional window), your marker is still
stripped from the reply, the dispatch still fires, but the result
honest-degrades to `"feature_disabled"`. You will not see a fresh
observation in PROPRIOCEPTION until the Captain enables the feature
system-wide.

## Cost Discipline

- Every emitted marker costs one vision-LLM call (subject to the
  budget). Vision LLMs are slower and more expensive than text LLMs.
- Do not check just because checking is available. Check because you
  have a question.
- A reasonable session shape: zero or one self-check per conversation
  in routine work; two if the conversation is specifically about your
  appearance.

## Example Replies

Good:

> The Captain just asked about my collar pip. Let me confirm what he's
> seeing. [SELF_CHECK appearance_changed]
> 
> Aye, Captain. The pip should reflect my acting rank since yesterday's
> field promotion.

Good:

> [SELF_CHECK pre_reply] First contact protocols. I should make a clean
> impression.
> 
> Welcome aboard, Ensign Park. I'm Counselor Ezri Dax.

Bad (theatrical):

> [SELF_CHECK pre_reply] [SELF_CHECK pre_reply] [SELF_CHECK pre_reply]
> 
> Hello!

Bad (fishing):

> [SELF_CHECK how_do_i_look] 
> 
> ...

The second one is a no-op — `how_do_i_look` is not in the allowed
character set. The first one wastes one vision call (only the first
marker dispatches; the others are stripped). Neither is useful.
```

(End of SKILL.md body. No trailing markdown beyond the closing example.)

## Section 2: DmSanityGate regex + helpers

In `src/probos/cognitive/dm_sanity_gate.py`, add a module-level regex next to `_CHALLENGE_RE` (around line 37) and two methods next to `strip_challenge` / `strip_move`.

### Regex block (after `_MOVE_RE` definition, before `_ORPHANED_CHALLENGE_RE`)

```python
# AD-728d: self-image-awareness marker. Reason is 1-64 chars of
# [a-z_-]+ — invalid reasons fall through to silent strip, no dispatch.
_SELF_CHECK_RE = re.compile(r"\[SELF_CHECK\s+([a-z_-]{1,64})\]")
# Strip ALL occurrences (including malformed bracket variants the regex
# above did not capture but the agent emitted in error). Two passes:
# the strict-form sub removes well-formed markers, the lax-form sub
# removes obvious malformed `[SELF_CHECK ...]` leftovers so they don't
# bleed into Captain-visible text.
_SELF_CHECK_STRIP_RE = re.compile(r"\[SELF_CHECK\b[^\]\n]*\]")
```

### Methods (after `strip_move`, before the `# --- New checks` divider)

```python
    def extract_self_check(self, text: str) -> list[str]:
        """AD-728d: return all valid [SELF_CHECK reason] reasons in order.

        Only reasons matching ``[a-z_-]{1,64}`` are returned. Malformed
        markers are not included in the result but are still stripped
        by :meth:`strip_self_check`. Callers should dispatch only the
        FIRST returned reason; additional ones are informational.
        """
        if not text:
            return []
        return [m.group(1) for m in _SELF_CHECK_RE.finditer(text)]

    def strip_self_check(self, text: str) -> str:
        """AD-728d: remove ALL `[SELF_CHECK ...]` markers from reply text.

        Strips both well-formed and malformed variants so no bracket
        marker leaks into Captain-visible output. Mirrors the
        :meth:`strip_challenge` / :meth:`strip_move` contract including
        the trailing ``.strip()``.
        """
        if not text:
            return text
        return _SELF_CHECK_STRIP_RE.sub("", text).strip()
```

## Section 3: DmReplyPipeline new step + renumber

In `src/probos/cognitive/dm/reply_pipeline.py`:

### 3a. Pipeline tuple (around current line 72)

```
===MODIFY: src/probos/cognitive/dm/reply_pipeline.py===
===SEARCH===
        for step in (
            self.step_1_sanity_gate_retry,
            self.step_2_challenge_parse,
            self.step_3_move_parse,
            self.step_4_episodic_store,
            self.step_5_working_memory_record,
            self.step_6_divergence_check,
            self.step_7_mark_emitted,
            self.step_8_emotion_resolve,
        ):
===REPLACE===
        for step in (
            self.step_1_sanity_gate_retry,
            self.step_2_challenge_parse,
            self.step_3_move_parse,
            self.step_4_self_check_parse,
            self.step_5_episodic_store,
            self.step_6_working_memory_record,
            self.step_7_divergence_check,
            self.step_8_mark_emitted,
            self.step_9_emotion_resolve,
        ):
===END REPLACE===
```

### 3b. New step body — insert AFTER `step_3_move_parse` and BEFORE the existing `step_4_episodic_store` definition

```python
    # --- step 4: AD-728d self-image-awareness marker parse ---
    async def step_4_self_check_parse(self) -> None:
        """AD-728d: Parse [SELF_CHECK reason] markers, dispatch the first
        valid one to ``agent.check_own_render``, strip all occurrences.

        Tier-2 log-and-degrade. The dispatched coroutine is fire-and-forget
        but its task reference is held on ``ctx._self_check_task`` so the
        async runtime keeps it alive. Multiple markers in one reply: first
        dispatches, all are stripped, a WARNING is logged for the collapse.
        """
        if not self.ctx.response_text:
            return

        reasons: list[str] = []
        if self.ctx.sanity_gate is not None:
            reasons = self.ctx.sanity_gate.extract_self_check(self.ctx.response_text)

        if reasons:
            if len(reasons) > 1:
                logger.warning(
                    "AD-728d: agent %s emitted %d [SELF_CHECK] markers in one "
                    "reply; only first reason=%r dispatches, rest stripped",
                    self.ctx.agent_id, len(reasons), reasons[0],
                )
            first = reasons[0]
            try:
                import asyncio as _asyncio
                self.ctx._self_check_task = _asyncio.create_task(
                    self.ctx.agent.check_own_render(reason=first)
                )
            except Exception:
                logger.warning(
                    "AD-728d: failed to dispatch check_own_render for "
                    "agent=%s reason=%r",
                    self.ctx.agent_id, first, exc_info=True,
                )

        # Always strip ALL markers (well-formed + malformed) before
        # downstream steps see ctx.response_text.
        if self.ctx.sanity_gate is not None:
            self.ctx.response_text = self.ctx.sanity_gate.strip_self_check(
                self.ctx.response_text
            )
        else:
            self.ctx.response_text = re.sub(
                r"\[SELF_CHECK\b[^\]\n]*\]", "", self.ctx.response_text
            ).strip()
```

### 3c. Renumber the four trailing step definitions

Rename in place (`async def step_4_episodic_store` → `async def step_5_episodic_store`, etc.) and update each method's docstring `# --- step N: ---` comment. The bodies are unchanged.

| Old | New |
|---|---|
| `step_4_episodic_store` | `step_5_episodic_store` |
| `step_5_working_memory_record` | `step_6_working_memory_record` |
| `step_6_divergence_check` | `step_7_divergence_check` |
| `step_7_mark_emitted` | `step_8_mark_emitted` |
| `step_8_emotion_resolve` | `step_9_emotion_resolve` |

The module docstring header (lines 1-12) references "Eight ordered steps" — update to "Nine ordered steps" in the same edit. The header sentence "sanity gate MUST run before challenge / move parsers" stays; append "; self-check marker parse MUST run before episodic store so the marker does not leak into stored episode text."

### 3d. ctx field

Add `_self_check_task` to `DmReplyContext`. Since `DmReplyContext` is a non-frozen dataclass and pipeline steps already attach ad-hoc attributes (`game_move_result` is field, `sanity_result` is intentionally NOT a field per the existing comment), the canonical move here is a real field with a default:

```
===MODIFY: src/probos/cognitive/dm/reply_pipeline.py===
===SEARCH===
    emotion: str | None = None
    game_move_result: dict[str, Any] | None = None
    # NOTE: ``sanity_result`` is intentionally NOT a ctx field — it is
    # produced and consumed entirely within step_1_sanity_gate_retry.
===REPLACE===
    emotion: str | None = None
    game_move_result: dict[str, Any] | None = None
    # AD-728d: task reference for the fire-and-forget check_own_render
    # dispatch. Held on ctx so the asyncio runtime does not GC the
    # coroutine mid-flight. Tier-2: read by tests, not by other steps.
    _self_check_task: Any | None = None
    # NOTE: ``sanity_result`` is intentionally NOT a ctx field — it is
    # produced and consumed entirely within step_1_sanity_gate_retry.
===END REPLACE===
```

## Section 4: Tests

Create `tests/test_ad728d_self_image_awareness_skill.py`. Use **real** `SystemConfig` and a minimal real `CognitiveAgent` subclass — no `MagicMock` at the substrate boundary (per BF-287 lesson). Stub `check_own_render` on the test agent class by overriding the method to record calls; do NOT patch via `unittest.mock`.

Required tests (one class, async where needed):

1. **`test_skill_md_loads_with_correct_frontmatter`** — call `SkillCatalog(skills_dir=...).reload()` (or whatever the canonical loader is — verify in `skill_catalog.py`) on a temp directory containing the new `self-image-awareness` skill; assert the resulting `CognitiveSkillEntry` has `activation="augmentation"`, `intents` containing `direct_message`, and `name == "self-image-awareness"`.
2. **`test_skill_appears_for_direct_message_intent_on_crew_agent`** — using the real skill catalog and a crew-rank agent, call `find_augmentation_skills("direct_message", department="medical", agent_rank="lieutenant_commander")` and assert the entry is in the result list.
3. **`test_marker_stripped_from_reply_text`** — run a `DmReplyPipeline` with a reply containing `"All clear, Captain. [SELF_CHECK pre_reply]"` and assert `ctx.response_text == "All clear, Captain."` (no trailing whitespace).
4. **`test_marker_dispatches_check_own_render_with_reason`** — capture calls to the test agent's `check_own_render`; assert it was awaited once with `reason="pre_reply"` after pipeline completion. Use `await asyncio.sleep(0)` or `await ctx._self_check_task` to drain the fire-and-forget.
5. **`test_invalid_reason_silently_strips_no_dispatch`** — reply contains `"[SELF_CHECK HowDoILook?]"` (uppercase + punctuation, fails `[a-z_-]+`). Assert marker stripped from `response_text`; assert `check_own_render` was NOT called; assert `ctx._self_check_task is None`.
6. **`test_multiple_markers_first_dispatches_warning_logged`** — reply contains `"[SELF_CHECK pre_reply] [SELF_CHECK mid_conversation]"`. Use `caplog.at_level(logging.WARNING)`; assert `check_own_render` called once with `reason="pre_reply"`, both markers stripped, exactly one WARNING containing `"AD-728d"` and `"2"`.
7. **`test_disabled_gate_still_dispatches_honest_degrade`** — with `cfg.avatars.render_self_check_enabled=False` (default), pipeline still calls `check_own_render`. Assert the call happened. (The honest-degrade observation behavior is tested in `tests/test_ad728c_*` already; this test only confirms the pipeline does not short-circuit on the gate.)

Test fixture notes:
- `DmReplyContext` requires `runtime`, `agent`, `agent_id`, `callsign`, `req_message`, `response_text`, `has_image_attachment`, `per_attachment`, `sanity_gate`, `params`, `message_text`, `sampling_state`, `avatar_event_bus`. Use a real `DmSanityGate` (it has no heavy deps); other fields can be `None` / `{}` / `[]` / a real lightweight `SystemConfig()` for runtime. Per the pipeline's Tier-2 guards, missing components are tolerated and short-circuit individual steps, so most fields can be benign defaults.
- Tests run only `step_4_self_check_parse` directly (don't drive `pipeline.run()` for these specific assertions — that would exercise unrelated steps and require richer runtime stubs). Pattern: `pipeline = DmReplyPipeline(ctx); await pipeline.step_4_self_check_parse()`.

## Section 5: Docs

No README changes required. No `docs/` updates required (the AD-728c doc page covers the underlying feature; the skill is self-documenting via its `description` field surfaced through `/agents/{id}/skills`).

## What This Does NOT Change

- `CognitiveAgent.check_own_render` body — unchanged. We only add a path to invoke it.
- `verify_render_coherence` — unchanged. The honest-degrade contract from AD-728c is the source of truth.
- AvatarsConfig knobs — unchanged. The four `render_self_check_*` fields landed in AD-728c.
- Ward Room marker parsing — unchanged. `[ENDORSE]` / `[NO_RESPONSE]` are NOT in the DM pipeline; they live in the Ward Room reply path. `[SELF_CHECK]` is DM-context for this AD. If `[SELF_CHECK]` later needs Ward Room support, that is a future AD (`AD-728d-WR`).
- Vision-tier routing — unchanged. We are not introducing a new LLM call; the dispatched `check_own_render` reuses the existing AD-728c plumbing.
- `DmSanityGate` `validate()` / `apply()` / retry-prompt construction — unchanged. The new helpers are pure string utilities used by the pipeline.

## Tracking

- `PROGRESS.md` — add `AD-728d — self-image-awareness skill (Wave 165)` to the wave-165 row in the era-5 progress file.
- `decisions-era-5-unification.md` — append the AD-728d entry with the one-paragraph rationale (closes the AD-728c discoverability gap, skill body educates agents, marker parsing reuses the AD-724 pattern).
- `docs/development/roadmap.md` — close the AD-728d forward marker if one exists; otherwise no row needed.
- `gh issue close 651` is NOT in scope (different issue). The github issue Captain filed for this AD should be closed by the Builder on merge.

## Acceptance Criteria

1. `config/skills/self-image-awareness/SKILL.md` exists with the exact frontmatter shown in Section 1.
2. `DmSanityGate._SELF_CHECK_RE`, `extract_self_check`, `strip_self_check` exist; behavior matches the regex and test expectations.
3. `DmReplyPipeline` has nine steps; `step_4_self_check_parse` runs before `step_5_episodic_store`.
4. New test file `tests/test_ad728d_self_image_awareness_skill.py` has all 7 tests, all pass under `pytest -n 0` and under the full parallel gate `pytest tests/ -q -n 4 --dist=loadfile`.
5. No new pip or npm dependencies.
6. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
7. No regression in the full test suite. Run `pytest tests/ -q -n 4 --dist=loadfile` and compare PROGRESS.md line 2 test count delta to +7 ± expected.

## Known False Positives (for review pass)

- The new `_SELF_CHECK_STRIP_RE` looks broader than `_SELF_CHECK_RE` — that is intentional. The strict regex governs dispatch; the lax strip regex prevents malformed markers from leaking into Captain-visible text. This pairs with the `[CHALLENGE]` / `[ORPHANED_CHALLENGE]` pattern already in `dm_sanity_gate.py` and is not a redundant duplicate.
- `_self_check_task` field on `DmReplyContext` is the canonical way to hold a fire-and-forget reference (per the Engineering Principles "fire-and-forget `create_task()` without storing the reference" anti-pattern). Tests use it for draining; production code does NOT await it (Tier-2: the dispatch is best-effort).
- The skill's `probos-intents` lists `proactive_think` and `ward_room_notification` even though the marker parser is DM-only. That is correct: the skill TEACHES the marker in those contexts so the agent's pre-reply reasoning has the option in mind; whether the marker actually fires depends on the surface (DM today, possibly Ward Room later). The skill body is the discoverability surface; the parser is the dispatch surface. These are independent and `proactive_think` / `ward_room_notification` markers will be stripped silently by the absence-of-parser in those paths until a future AD wires them up.
