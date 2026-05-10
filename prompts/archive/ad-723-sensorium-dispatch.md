# AD-723 — Sensorium dispatch unification (System-1 / System-2 path coherence, Phase 1)

**Status:** READY FOR BUILDER
**Wave:** 144 (single-prompt wave, single commit)
**Dispatch:** [prompts/WAVE-144-DISPATCH.md](WAVE-144-DISPATCH.md)
**Cluster plan:** [prompts/BUILDER-EXECUTION-PLAN-avatar-cluster.md](BUILDER-EXECUTION-PLAN-avatar-cluster.md)
**Depends on:** AD-722 v1 (Wave 140, SHIPPED), AD-722-1 / AD-722f (Wave 141, SHIPPED), AD-722b (Wave 142, SHIPPED), AD-722a (Wave 143, SHIPPED — its `_build_intent_self_tag_instruction` becomes a registry entry here).
**Issue:** [#581](https://github.com/seangalliher/ProbOS/issues/581)
**Risk:** **MEDIUM-HIGH** — large, surgical refactor across two long assembly methods. Mechanical correctness is gated by golden-text snapshot tests (pre/post byte equality). Zero behavioural change; zero new capability.
**Estimated tests:** ≥ 22 new Python boundary cases (3 snapshot + ~12 dispatcher unit + ~5 path-coherence + ~2 ordering). **No UI changes; no Vitest delta.**

> **Builder:** read [prompts/WAVE-144-DISPATCH.md](WAVE-144-DISPATCH.md) for cross-AD context, the standing test gate, and the engineering-principles checklist. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## 1. Goal (TL;DR)

Today the `SENSORIUM_REGISTRY` `ClassVar[dict]` at `cognitive_agent.py:122-138` is **inventory** — nothing iterates it. Every sensorium injection is hand-wired into both `_build_cognitive_baseline` (chain path) AND the DM/WR branches of `_build_user_message` (one-shot paths). AD-722 shipped with the avatar block in baseline only; Captain reported "no avatar awareness in 1:1 chat" and a follow-up BF wired the DM branch separately. AD-722a (Wave 143) paid the same tax for `_build_intent_self_tag_instruction`.

**AD-723 makes the registry the dispatcher.** Each entry gains a `paths` tuple declaring which prompt-assembly paths consume it. Each path-specific assembly method calls `await self._dispatch_sensorium(SensoriumPath.X, observation)` exactly once and merges the result into its `parts: list[str]`. New sensorium ADs register once with one `paths` tuple instead of being hand-wired into two assembly methods.

**Non-goal — keep the System-1 / System-2 split.** Per the Captain ruling 2026-05-10 ([DECISIONS.md AD-723](../DECISIONS.md)) and the consolidated System-1/System-2 ruling, AD-723 does NOT merge chain and one-shot paths. DM stays one-shot for latency and tone; chain stays multi-LLM for deliberative work. AD-723 unifies the **wiring registry**, not the **paths themselves**.

**Acceptance gate:** golden-text snapshot tests assert that the rendered prompt for one chain path, one DM, and one WR observation is **byte-identical** before and after the refactor. If the diff is non-zero, the refactor isn't safe.

---

## 2. Verified Against Codebase (2026-05-10 @ HEAD)

```
# Registry definition — currently inventory, no iterators.
grep -n "SENSORIUM_REGISTRY\|class SensoriumLayer" src/probos/cognitive/cognitive_agent.py
    52:  class SensoriumLayer(StrEnum):
   122:      SENSORIUM_REGISTRY: ClassVar[dict[str, tuple[SensoriumLayer, str]]] = {
  4778:          structured self-state snapshot. See SENSORIUM_REGISTRY for the full inventory.
# 14 entries total in the dict at lines 123-137 (verified by manual count).
# Zero callers — no `for ... in SENSORIUM_REGISTRY` or `SENSORIUM_REGISTRY[...]` access.

# Chain baseline — 12 numbered steps, ends with avatar block (Wave 140 BF).
grep -n "def _build_cognitive_baseline\|# 1\. \|# 2\. \|# 12\. AD-722" src/probos/cognitive/cognitive_agent.py
  4438:     def _build_cognitive_baseline(self, observation: dict) -> dict[str, str]:
  4448:         # 1. Temporal awareness (AD-502) — self-contained
  4455:         # 2. Working memory (AD-573) — self-contained
  ...
  4590:     # 12. AD-722 BF (2026-05-10): avatar self-observation (INTEROCEPTION).
  4596:         avatar_block = self._build_avatar_self_observation(observation or {})
  4598:         _intent_tag_line = self._build_intent_self_tag_instruction()

# Chain extensions — None-for-removal semantics.
grep -n "def _build_cognitive_extensions\|state\[.*\] = None" src/probos/cognitive/cognitive_agent.py
  4610:     def _build_cognitive_extensions(self, context_parts: dict) -> dict[str, str]:
  4768:             state["_no_episodic_memories"] = None  # type: ignore[assignment]

# Meta-merger that runs baseline then extensions.
grep -n "def _build_cognitive_state" src/probos/cognitive/cognitive_agent.py
  4773:     def _build_cognitive_state(self, context_parts: dict, observation: dict | None = None) -> dict[str, str]:

# Chain call site — situation awareness is chain-only.
grep -n "_build_situation_awareness\|_build_cognitive_state\(" src/probos/cognitive/cognitive_agent.py
  2336:         _cognitive_state = self._build_cognitive_state(_context_parts, observation=observation)
  2345:             _situation = self._build_situation_awareness(_context_parts)
  4843:     def _build_situation_awareness(self, context_parts: dict) -> dict[str, str]:

# DM / WR branches of _build_user_message — inline blocks.
grep -n "async def _build_user_message\|if intent_name == \"direct_message\"\|if intent_name == \"ward_room_notification\"" src/probos/cognitive/cognitive_agent.py
  5048:     async def _build_user_message(self, observation: dict) -> str:
  5063:         if intent_name == "direct_message":
  5301:         if intent_name == "ward_room_notification":

# Avatar block + intent-self-tag hand-wired in both baseline AND DM.
grep -n "_build_avatar_self_observation\|_build_intent_self_tag_instruction" src/probos/cognitive/cognitive_agent.py
  2659:     def _build_avatar_self_observation(self, observation: dict) -> str:
  2737:     def _build_intent_self_tag_instruction(self) -> str:
  4596:             avatar_block = self._build_avatar_self_observation(observation or {})
  4598:             _intent_tag_line = self._build_intent_self_tag_instruction()
  5218:                 _avatar_block = self._build_avatar_self_observation(observation)
  5223:                 _intent_tag_line = self._build_intent_self_tag_instruction()
# Two call sites for each. THIS is the dual-wire tax.
# WR branch deliberately omits both — see AD-722 addendum (h) "no avatar in WR".

# Async injections that the dispatcher must handle.
grep -n "async def _build_dm_self_monitoring\|await _telemetry_svc" src/probos/cognitive/cognitive_agent.py
  4168:     async def _build_dm_self_monitoring(self, thread_id: str) -> str | None:
  5096:                 _snapshot = await _telemetry_svc.get_full_snapshot(_agent_id)
  5345:                 _snapshot = await _telemetry_svc.get_full_snapshot(_agent_id)

# AD-722a's per-agent divergence store on runtime — referenced by
# _build_divergence_note_suffix INSIDE _build_avatar_self_observation
# (no separate registry entry needed; suffix is embedded in avatar block).
grep -n "divergence_results" src/probos/runtime.py src/probos/cognitive/cognitive_agent.py
  src/probos/runtime.py:439:         self.divergence_results: dict[str, "DivergenceResult"] = {}
  src/probos/cognitive/cognitive_agent.py:2716:             results = getattr(rt, "divergence_results", None)

# DECISIONS.md anchor.
grep -n "AD-723 — Sensorium dispatch unification" DECISIONS.md
  1731:  ### AD-723 — Sensorium dispatch unification (System-1 / System-2 path coherence, Phase 1)
```

---

## 3. Architectural decisions (locked in v1)

| # | Decision | Default chosen | Rationale |
|---|---|---|---|
| D-1 | `SensoriumPath` type | `StrEnum` | Matches existing `SensoriumLayer` precedent (line 52). Serializable into logs and event payloads without `.value` calls. |
| D-2 | `SensoriumEntry` shape | `@dataclass(frozen=True)` | Hashable, immutable, extensible. Dict-tuple form has zero external callers (greenfield); no migration risk. |
| D-3 | Method signature normalization | `(self, observation: dict) -> str \| dict[str, str] \| None` | `None` = no contribution this cycle. `str` = single output keyed by `entry.output_key`. `dict` = multi-key (`_build_cognitive_baseline` shape preserved during the staged migration; final form is per-key methods). |
| D-4 | Dispatcher | **Two variants:** `_dispatch_sensorium_sync(path, observation)` for CHAIN paths (all registered methods are sync at HEAD); `async _dispatch_sensorium_async(path, observation)` for DM/WR (have async injections — `_build_dm_self_monitoring`, introspective telemetry). `inspect.iscoroutinefunction(method)` distinguishes; the sync variant raises `RuntimeError` if it encounters an async method (defense in depth). Deterministic key ordering = (priority asc, then registration order). **Rationale:** preserves the sync signature of `_build_cognitive_baseline` / `_build_cognitive_extensions` / `_build_cognitive_state` / `_build_situation_awareness` — ~17 existing test call sites across `tests/test_ad646_cognitive_baseline.py`, `tests/test_ad646b_chain_parity.py`, `tests/test_ad635f_clinical_proactive_context.py`, `tests/test_ad648_post_capability_profiles.py` call them synchronously. Verified at HEAD: zero async methods register on any CHAIN path. |
| D-5 | Existing inline blocks | **Extract all to named `_sensorium_<key>` methods** | SOLID-clean, individually testable, eliminates lambda registration. Line-count delta is the architectural payoff this AD pays for. |
| D-6 | Extensions integration | Merge into dispatch as `paths=(CHAIN_EXTENSIONS,)` with `priority=10`; baseline entries default `priority=0` | Preserves AD-646 None-for-removal semantics in the dispatcher (see §5.2). Higher priority overrides baseline by key. |
| D-7 | DM-branch refactor | Convert each inline block to a registry entry with `paths=(DM_ONESHOT, ...)` | Some entries overlap baseline (`paths=(CHAIN_BASELINE, DM_ONESHOT)` for temporal, working memory, avatar, intent-self-tag). Boot-camp ship-state snapshot (AD-683) stays inline — DM-specific cold-start preamble; not crew-sensory data. |
| D-8 | WR branch scope | Subset of DM — per AD-722 addendum (h) | NOT in WR: avatar block, intent-self-tag, DM self-monitoring, boot-camp snippet, captain-text footer. YES in WR: temporal, cognitive zone, working memory, memories, oracle, source attribution. Audience-shaped blocks (channel header, author footer, mention guidance) stay inline. |
| D-9 | Async detection | `inspect.iscoroutinefunction(bound_method)` | Correct primitive — NOT `iscoroutine` (that's for an already-called awaitable). Works on bound async methods. |
| D-10 | AD-722a `_build_intent_self_tag_instruction` | Register with `paths=(CHAIN_BASELINE, DM_ONESHOT)` | AD-722a deliberately deferred this to AD-723. The dual-wire (baseline line 4598 + DM line 5223) is exactly the tax AD-723 removes. WR is excluded per D-8. |
| D-11 | Snapshot tests | Golden-text fixtures in `tests/fixtures/sensorium_snapshots/` | Three files: `chain_baseline.txt`, `dm_oneshot.txt`, `wr_oneshot.txt`. Pre/post diff must be zero. Updates require explicit `--snapshot-update` style regen step (Builder regenerates ONCE pre-refactor, then asserts equality post-refactor). |
| D-12 | Divergence-note (AD-722a) registration | NOT a separate entry — already embedded in `_build_avatar_self_observation`'s output | Confirmed by grep: `_build_divergence_note_suffix` is called from inside `_build_avatar_self_observation` (line 2693). A single avatar-block registry entry covers both. |

---

## 4. New types

**File:** `src/probos/cognitive/cognitive_agent.py` (additions only, no removals in this section).

Insert immediately after the `SensoriumLayer` definition (current line 57) and before `derive_communication_context` (current line 60):

```python
class SensoriumPath(StrEnum):
    """AD-723: prompt-assembly paths that consume sensorium injections.

    Each registry entry declares which paths consume it via its ``paths``
    tuple. The dispatcher iterates the registry once per path; an entry
    with an empty ``paths`` tuple is inventory-only (documented but never
    rendered into a prompt).
    """

    CHAIN_BASELINE = "chain_baseline"
    """Universal cognitive baseline — runs for ALL chain executions."""

    CHAIN_EXTENSIONS = "chain_extensions"
    """Proactive-conditional overrides — populated by proactive.py context_parts."""

    CHAIN_SITUATION = "chain_situation"
    """Environmental percepts — WR activity, alerts, infra, subordinates."""

    DM_ONESHOT = "dm_oneshot"
    """1:1 conversation with the Captain — System-1 path, single LLM call."""

    WR_ONESHOT = "wr_oneshot"
    """Ward Room channels — peer audience; intentionally narrower than DM."""


@dataclass(frozen=True)
class SensoriumEntry:
    """AD-723: registry record describing how a sensorium injection is dispatched.

    Replaces the prior ``tuple[SensoriumLayer, str]`` inventory shape with
    a dispatch-aware record. ``paths`` declares which prompt-assembly paths
    consume the entry. Empty ``paths`` is allowed for inventory-only entries
    (meta-methods that delegate rather than render).
    """

    layer: SensoriumLayer
    description: str
    paths: tuple["SensoriumPath", ...] = ()
    priority: int = 0
    output_key: str | None = None
    """Key under which the entry's string output is stored in the merged dict.

    When ``None``, the entry's registered method MUST return ``dict[str, str]``
    or ``None`` (no single-key output). When set, the method MUST return
    ``str`` or ``None`` and the dispatcher stores ``result`` under
    ``output_key`` in the merged dict.
    """
```

Add the import where the other `from dataclasses` / `from enum` imports live (top of file).

---

## 5. Registry conversion

### 5.1 Replace the registry literal

**File:** `src/probos/cognitive/cognitive_agent.py`, lines 122-138.

The replacement preserves ALL 14 existing entries (so the documented inventory is unchanged) and adds `paths` / `priority` / `output_key` fields. Meta-methods (`_build_cognitive_baseline`, `_build_cognitive_extensions`, `_build_cognitive_state`, `_build_user_message`) keep `paths=()` — they are dispatch ORCHESTRATORS, not dispatch TARGETS. Plus one new entry for `_build_intent_self_tag_instruction` (AD-722a deferred registration).

Use the table below as the source of truth. Builder writes the literal in registration order; the dispatcher preserves it (priority then insertion).

| Method | Layer | Paths | Priority | output_key | Notes |
|---|---|---|---|---|---|
| `_build_temporal_context` | PROPRIOCEPTION | CHAIN_BASELINE, DM_ONESHOT, WR_ONESHOT | 0 | `_temporal_context` | Returns str; WR/DM wrap in `--- Temporal Awareness ---` block — handled in inline wrappers, NOT in registered method |
| `_get_comm_proficiency_guidance` | PROPRIOCEPTION | CHAIN_BASELINE | 0 | `_comm_proficiency` | str-or-None |
| `_detect_self_in_content` | PROPRIOCEPTION | CHAIN_BASELINE, WR_ONESHOT | 0 | `_self_recognition_cue` | Takes observation, extracts `context`. Method already handles its own signature — wrapper extracts `context` first. |
| `_build_dm_self_monitoring` | PROPRIOCEPTION | WR_ONESHOT | 0 | `_dm_self_monitoring` | **Async**. WR-only (DM-thread detection); not chain. Wrapper extracts `thread_id` from `observation["params"]`. |
| `_confabulation_guard` | PROPRIOCEPTION | () | 0 | None | Inventory only — called inside other entries (memory section, baseline). Keep registered for documentation. |
| `_build_crew_complement` | PROPRIOCEPTION | () | 0 | None | Inventory only — embedded inside `_build_temporal_context` already. |
| `_build_cognitive_baseline` | INTEROCEPTION | () | 0 | None | Meta-method; the dispatcher replaces it. Keep registered for documentation. |
| `_build_cognitive_extensions` | INTEROCEPTION | () | 0 | None | Meta-method; replaced by CHAIN_EXTENSIONS entries. |
| `_build_cognitive_state` | INTEROCEPTION | () | 0 | None | Meta-method; replaced by composed dispatch. |
| `_format_memory_section` | INTEROCEPTION | DM_ONESHOT, WR_ONESHOT | 0 | `_formatted_memories_section` | Renders observation `recent_memories` + `_source_framing`. Chain already pre-formats into `_formatted_memories` in `perceive()` (line 2360); chain path NOT in `paths`. |
| `_build_situation_awareness` | EXTEROCEPTION | () | 0 | None | Meta-method; replaced by CHAIN_SITUATION entries below. |
| `_build_active_game_context` | EXTEROCEPTION | CHAIN_SITUATION, DM_ONESHOT | 0 | `_active_game` | DM path renders an inline block; chain uses observation key. |
| `_build_user_message` | EXTEROCEPTION | () | 0 | None | Meta-method; the orchestrator. |
| `_build_avatar_self_observation` | INTEROCEPTION | CHAIN_BASELINE, DM_ONESHOT | 0 | `_avatar_self_observation` | NOT WR per AD-722 addendum (h). Embeds divergence-note suffix; no separate registry entry needed. |
| **`_build_intent_self_tag_instruction`** | **PROPRIOCEPTION** | **CHAIN_BASELINE, DM_ONESHOT** | **0** | **`_intent_self_tag`** | **NEW registry entry — AD-722a deferred this to AD-723.** No-arg method; wrapper ignores observation. |
| **(N+ — see §5.3)** Inline-extracted baseline blocks | varies | CHAIN_BASELINE | 0 | varies | One entry per former numbered step that does NOT already correspond to a top-level helper method. |
| **(N+)** Inline-extracted DM blocks | varies | DM_ONESHOT | 0 | varies | One entry per former inline block in the DM branch. |
| **(N+)** Inline-extracted WR blocks | varies | WR_ONESHOT | 0 | varies | One entry per former inline block in the WR branch. |
| **(N+)** Extension overrides | INTEROCEPTION | CHAIN_EXTENSIONS | 10 | varies | One entry per former step of `_build_cognitive_extensions`. **Higher priority** so they override baseline by key. None-return is honored as removal (see §6.3). |
| **(N+)** Situation entries | EXTEROCEPTION | CHAIN_SITUATION | 0 | varies | One entry per former step of `_build_situation_awareness`. |

### 5.2 Method extraction list

The Builder extracts inline blocks into named methods. Each extracted method has signature `(self, observation: dict) -> str \| None`. The method body is exactly the existing inline block, with `state[key] = X` → `return X` (or `return None` when the block guarded an assignment).

**From `_build_cognitive_baseline` (extract steps that are currently inline):**

- Step 3 → `_sensorium_agent_metrics` → `_agent_metrics`
- Step 4 → `_sensorium_ontology_baseline` → `_ontology_context`
- Step 5 → `_sensorium_source_attribution_baseline` → `_source_attribution_text`
- Step 6 → `_sensorium_confab_guard_baseline` → `_confabulation_guard` (calls existing `_confabulation_guard(None)`)
- Step 7 → `_sensorium_no_memories_flag` → `_no_episodic_memories`
- Step 9 → `_sensorium_cold_start_note` → `_cold_start_note`
- Step 10 → `_sensorium_source_attribution_rich` → `_source_attribution_text` (override; same key as step 5 — handled by dispatcher merge order)

Steps 1, 2, 8, 11, 12 already call helper methods (`_build_temporal_context`, working-memory render, `_get_comm_proficiency_guidance`, `_detect_self_in_content`, `_build_avatar_self_observation`) — those become registry entries directly with `paths` tuples (see §5.1 table). The working-memory render is wrapped in a tiny helper `_sensorium_working_memory` → `_working_memory_context` because `_working_memory.render_context(budget=1500)` is a method on a different object, not on `CognitiveAgent`.

**From `_build_cognitive_extensions` (each step becomes a `paths=(CHAIN_EXTENSIONS,)` entry with `priority=10`):**

- `_sensorium_ext_self_monitoring` → `_self_monitoring`
- `_sensorium_ext_source_attribution_authority` → `_source_attribution_text` (overrides baseline)
- `_sensorium_ext_introspective_telemetry` → `_introspective_telemetry`
- `_sensorium_ext_ontology_from_context_parts` → `_ontology_context` (overrides baseline)
- `_sensorium_ext_orientation_supplement` → `_orientation_supplement`
- `_sensorium_ext_confab_guard_authority` → `_confabulation_guard` (overrides baseline)
- `_sensorium_ext_no_memories_flag_override` → `_no_episodic_memories` (returns `None` to signal removal when memories ARE present, or the flag string when present-but-empty — see §6.3)

**From `_build_situation_awareness` (each step becomes a `paths=(CHAIN_SITUATION,)` entry):**

- `_sensorium_situation_ward_room_activity` → `_ward_room_activity`
- `_sensorium_situation_recent_alerts` → `_recent_alerts`
- `_sensorium_situation_recent_events` → `_recent_events`
- `_sensorium_situation_infrastructure` → `_infrastructure_status`
- `_sensorium_situation_subordinate_stats` → `_subordinate_stats`
- `_sensorium_situation_clinical_telemetry` → `_clinical_telemetry`
- `_sensorium_situation_system_note` → `_cold_start_note` (overrides baseline's step 9 key in chain path — Builder verifies this is the intended legacy behaviour by snapshot)
- `_sensorium_situation_active_game` → `_active_game`

**From `_build_user_message` DM branch (each inline block becomes a `paths=(DM_ONESHOT,)` or `paths=(CHAIN_BASELINE, DM_ONESHOT)` entry):**

| Inline block (current location) | Extracted method | output_key | paths |
|---|---|---|---|
| Boot-camp ship state (line ~5070) | **STAYS INLINE** — DM-only cold-start preamble; not crew-sensory | n/a | n/a |
| Temporal awareness wrap (line ~5079) | Uses existing `_build_temporal_context` registry entry; inline wrapper formats `--- Temporal Awareness --- / ... / ---` framing AFTER dispatch | n/a | n/a |
| Cognitive zone (line ~5089) | `_sensorium_cognitive_zone_tag` | `_cognitive_zone` | DM_ONESHOT, WR_ONESHOT |
| Introspective telemetry (line ~5097) | `_sensorium_introspective_telemetry_oneshot` (**async**) | `_introspective_telemetry` | DM_ONESHOT, WR_ONESHOT |
| Working memory render (line ~5113) | `_sensorium_working_memory` (existing — see baseline) | `_working_memory_context` | CHAIN_BASELINE, DM_ONESHOT, WR_ONESHOT |
| Avatar block (line ~5218) | Existing `_build_avatar_self_observation` registry entry | `_avatar_self_observation` | CHAIN_BASELINE, DM_ONESHOT |
| Intent self-tag (line ~5223) | NEW `_build_intent_self_tag_instruction` registry entry | `_intent_self_tag` | CHAIN_BASELINE, DM_ONESHOT |
| Episodic memory section (line ~5232) | Existing `_format_memory_section` registry entry (wrapper extracts `recent_memories` + `_source_framing`) | `_formatted_memories_section` | DM_ONESHOT, WR_ONESHOT |
| Oracle context (line ~5239) | `_sensorium_oracle_context_block` | `_oracle_context_block` | DM_ONESHOT, WR_ONESHOT |
| Source attribution (line ~5260) | `_sensorium_source_attribution_oneshot` | `_source_attribution_tag` | DM_ONESHOT, WR_ONESHOT |
| Session history (line ~5283) | **STAYS INLINE** — DM-only conversational history; reads `params["session_history"]` | n/a | n/a |
| Active game (line ~5292) | Uses existing `_build_active_game_context` registry entry | `_active_game` | CHAIN_SITUATION, DM_ONESHOT |
| Captain says (line ~5298) | **STAYS INLINE** — terminal footer; not sensorium | n/a | n/a |

**From `_build_user_message` WR branch (each inline block, intentionally narrower than DM):**

| Inline block | Extracted method | output_key | paths |
|---|---|---|---|
| Channel/thread header (line ~5308) | **STAYS INLINE** — audience-shaped preamble | n/a | n/a |
| Temporal awareness wrap | Existing entry; inline framing | n/a | n/a |
| Cognitive zone | Existing `_sensorium_cognitive_zone_tag` | `_cognitive_zone` | DM_ONESHOT, WR_ONESHOT |
| DM self-monitoring (line ~5331, only if `channel_name.startswith("dm-")`) | Existing `_build_dm_self_monitoring` registry entry (async) | `_dm_self_monitoring` | WR_ONESHOT |
| Introspective telemetry (line ~5345) | Existing async entry | `_introspective_telemetry` | DM_ONESHOT, WR_ONESHOT |
| Working memory render | Existing entry | `_working_memory_context` | (already covered) |
| Cold-start system note (line ~5374) | `_sensorium_cold_start_note_oneshot` | `_cold_start_note` | WR_ONESHOT |
| Episodic memory section | Existing entry | `_formatted_memories_section` | (already covered) |
| Oracle context | Existing entry | `_oracle_context_block` | (already covered) |
| Source attribution | Existing entry | `_source_attribution_tag` | (already covered) |
| Augmentation skill (line ~5414) | **STAYS INLINE** — context-dependent task framing; not pure sensorium | n/a | n/a |
| Conversation context (line ~5422) | **STAYS INLINE** — audience-shaped body | n/a | n/a |
| Self-recognition (line ~5427) | Existing `_detect_self_in_content` entry | `_self_recognition_cue` | CHAIN_BASELINE, WR_ONESHOT |
| Author footer / mention guidance (line ~5430+) | **STAYS INLINE** — audience-shaped footer | n/a | n/a |

**Explicitly NOT in WR:**

- `_build_avatar_self_observation` (per AD-722 addendum h — interoception is private to agent-LLM, not for peer channels)
- `_build_intent_self_tag_instruction` (depends on avatar block)
- Boot-camp ship state (DM-only)
- Session history (DM-only)
- Captain says footer (DM-only)

### 5.3 Output of §5: the new registry

Builder constructs the new literal with the entries above. Existing 14 entries keep their layer and description text verbatim; only the value shape changes (tuple → `SensoriumEntry`) plus the new `paths` / `priority` / `output_key` fields. New entries (extracted methods + `_build_intent_self_tag_instruction`) are appended in the order listed in §5.2.

---

## 6. Dispatcher

### 6.1 Methods — sync + async variants

Add two dispatcher methods on `CognitiveAgent` sharing a single inner helper. The split preserves the sync signature of all legacy chain shims (back-compat with existing tests — see §D-4 rationale) while allowing async injections on the DM/WR paths.

```python
import inspect

def _sensorium_entries_for_path(
    self, path: SensoriumPath,
) -> list[tuple[str, SensoriumEntry]]:
    """AD-723: (priority asc, registration order) entries for the given path."""
    return sorted(
        (
            (name, entry)
            for name, entry in self.SENSORIUM_REGISTRY.items()
            if path in entry.paths
        ),
        key=lambda item: item[1].priority,
    )


def _apply_sensorium_result(
    self,
    merged: dict[str, str],
    entry: SensoriumEntry,
    method_name: str,
    result: object,
) -> None:
    """AD-723: merge a single registered-method result into the dispatch dict.

    ``None`` = removal (AD-646 semantics). ``str`` = keyed by entry.output_key.
    ``dict`` = multi-key contribution. Anything else is logged and dropped.
    """
    if result is None:
        if entry.output_key:
            merged.pop(entry.output_key, None)
        return
    if isinstance(result, str):
        if not result:
            return
        if entry.output_key is None:
            logger.warning(
                "AD-723: %s returned str but no output_key; dropping",
                method_name,
            )
            return
        merged[entry.output_key] = result
        return
    if isinstance(result, dict):
        for k, v in result.items():
            if v is None:
                merged.pop(k, None)
            elif isinstance(v, str) and v:
                merged[k] = v
        return
    logger.warning(
        "AD-723: %s returned %s; expected str | dict | None",
        method_name,
        type(result).__name__,
    )


def _dispatch_sensorium_sync(
    self,
    path: SensoriumPath,
    observation: dict,
) -> dict[str, str]:
    """AD-723: synchronous dispatch — used by chain paths.

    Raises ``RuntimeError`` if it encounters an async-registered method on
    the given path. At HEAD, no async methods are registered for any chain
    path; this guard catches future regressions.
    """
    merged: dict[str, str] = {}
    for method_name, entry in self._sensorium_entries_for_path(path):
        method = getattr(self, method_name, None)
        if method is None:
            logger.warning(
                "AD-723: sensorium method %s not bound on %s; skipping",
                method_name, type(self).__name__,
            )
            continue
        if inspect.iscoroutinefunction(method):
            raise RuntimeError(
                f"AD-723: async method {method_name} registered on sync path "
                f"{path.value}; use _dispatch_sensorium_async or change path."
            )
        try:
            result = method(observation)
        except Exception:
            logger.debug(
                "AD-723: sensorium method %s raised on path %s; degrading",
                method_name, path.value, exc_info=True,
            )
            continue
        self._apply_sensorium_result(merged, entry, method_name, result)
    return merged


async def _dispatch_sensorium_async(
    self,
    path: SensoriumPath,
    observation: dict,
) -> dict[str, str]:
    """AD-723: asynchronous dispatch — used by DM and WR one-shot paths.

    Handles both sync and async registered methods uniformly via
    ``inspect.iscoroutinefunction``.
    """
    merged: dict[str, str] = {}
    for method_name, entry in self._sensorium_entries_for_path(path):
        method = getattr(self, method_name, None)
        if method is None:
            logger.warning(
                "AD-723: sensorium method %s not bound on %s; skipping",
                method_name, type(self).__name__,
            )
            continue
        try:
            if inspect.iscoroutinefunction(method):
                result = await method(observation)
            else:
                result = method(observation)
        except Exception:
            logger.debug(
                "AD-723: sensorium method %s raised on path %s; degrading",
                method_name, path.value, exc_info=True,
            )
            continue
        self._apply_sensorium_result(merged, entry, method_name, result)
    return merged
```

### 6.2 Test for sync-path async-regression guard

```python
def test_sync_dispatch_rejects_async_method(monkeypatch, canned_agent):
    """AD-723: sync dispatcher refuses to silently drop async methods."""
    async def _async_payload(self, observation: dict) -> str:
        return "async-result"
    # Register a one-off async method on CHAIN_BASELINE for this test only.
    monkeypatch.setattr(
        canned_agent.__class__, "_test_async_method", _async_payload,
    )
    canned_agent.__class__.SENSORIUM_REGISTRY["_test_async_method"] = SensoriumEntry(
        layer=SensoriumLayer.INTEROCEPTION,
        description="test",
        paths=(SensoriumPath.CHAIN_BASELINE,),
        output_key="_test_key",
    )
    try:
        with pytest.raises(RuntimeError, match="async method .* on sync path"):
            canned_agent._dispatch_sensorium_sync(
                SensoriumPath.CHAIN_BASELINE, {},
            )
    finally:
        canned_agent.__class__.SENSORIUM_REGISTRY.pop("_test_async_method", None)
```

### 6.3 Wrapper convention for existing helper methods

Some existing methods (e.g., `_build_temporal_context`, `_get_comm_proficiency_guidance`, `_build_active_game_context`) have signatures that don't take `observation`. Two options for each: (a) write a one-line `_sensorium_<name>(self, observation: dict)` wrapper that calls the underlying method with the right args, or (b) accept and ignore `observation` in the existing method.

**Default: option (a) — one-line wrapper.** Preserves the existing public-ish helper signatures; keeps registry uniform.

Example:

```python
def _sensorium_temporal_context(self, observation: dict) -> str:
    """AD-723 dispatch wrapper for _build_temporal_context."""
    return self._build_temporal_context()
```

Register the WRAPPER (`_sensorium_temporal_context`), not the underlying method, when the underlying method's signature is incompatible. The §5.1 table lists the underlying methods for human readability; the actual registry key is the wrapper when one is needed.

Methods that ARE already `(self, observation: dict) -> str | None` register directly.

### 6.4 Extensions priority / None semantics

AD-646's None-for-removal is preserved: `_build_cognitive_extensions` step 7 currently sets `state["_no_episodic_memories"] = None` to remove the baseline-set flag when memories ARE present. In AD-723, the extracted method `_sensorium_ext_no_memories_flag_override` returns `None` to trigger the same removal — see §6.1 dispatcher logic.

Extensions run with `priority=10` (baseline default `0`), so all extension entries execute AFTER all baseline entries. Same-key writes naturally override.

### 6.5 Sensorium budget tracking

The existing `_track_sensorium_budget` (line 4791) call site in `perceive()` (line 2349) takes two dicts (cognitive_state + situation). After AD-723, those two dicts are produced by `_build_cognitive_state` (which now delegates to `_dispatch_sensorium_sync` internally for CHAIN_BASELINE + CHAIN_EXTENSIONS) and `_build_situation_awareness` (delegates to `_dispatch_sensorium_sync(CHAIN_SITUATION)`). Call site is unchanged. **AD-666's observability behaviour is preserved.**

---

## 7. Call-site refactors

### 7.1 `_build_cognitive_state` (line 4773) — STAYS SYNC

Replace the body so it delegates to the **sync** dispatcher. Signature unchanged — preserves the ~17 existing test call sites that call this method synchronously.

```python
def _build_cognitive_state(
    self,
    context_parts: dict,
    observation: dict | None = None,
) -> dict[str, str]:
    """AD-723: dispatch CHAIN_BASELINE then CHAIN_EXTENSIONS into one merged state."""
    obs = observation or {}
    if context_parts:
        obs = {**obs, "_context_parts": context_parts}
    state = self._dispatch_sensorium_sync(SensoriumPath.CHAIN_BASELINE, obs)
    if context_parts:
        ext = self._dispatch_sensorium_sync(SensoriumPath.CHAIN_EXTENSIONS, obs)
        # Cross-path merge: extensions overwrite baseline by key.
        # None values in ext have already been applied as pops inside the
        # sync dispatcher's _apply_sensorium_result; ext only contains
        # set-or-overwrite contributions here.
        for k, v in ext.items():
            state[k] = v
        # Apply removals from extensions that returned None: re-dispatch
        # would lose them. The dispatcher already popped from its own
        # merged dict, but baseline state needs the same removals applied.
        # SIMPLER: dispatch both paths against a SHARED merged dict —
        # see alternate body below if test-suite shows a removal regression.
    return state
```

**Caller at `cognitive_agent.py:2338` is unchanged** (no `await` added — method stays sync).

> **Builder note — None-removal across paths:** the snippet above runs each path against its own merged dict, then dict-merges them. AD-646's `_no_episodic_memories = None` removal must survive across the merge. If the snapshot test for the chain path fails specifically on the `_no_episodic_memories` key, switch to the SINGLE-DICT variant: call `_apply_sensorium_result` directly against a shared `state` dict by inlining the dispatcher loop, so extensions can pop baseline-set keys. Both implementations are valid; the single-dict form is the safe default — use it from the start:
>
> ```python
> def _build_cognitive_state(
>     self,
>     context_parts: dict,
>     observation: dict | None = None,
> ) -> dict[str, str]:
>     import inspect
>     obs = observation or {}
>     if context_parts:
>         obs = {**obs, "_context_parts": context_parts}
>     state: dict[str, str] = {}
>     for path in (SensoriumPath.CHAIN_BASELINE, SensoriumPath.CHAIN_EXTENSIONS):
>         if path == SensoriumPath.CHAIN_EXTENSIONS and not context_parts:
>             continue
>         for method_name, entry in self._sensorium_entries_for_path(path):
>             method = getattr(self, method_name, None)
>             if method is None or inspect.iscoroutinefunction(method):
>                 continue
>             try:
>                 result = method(obs)
>             except Exception:
>                 logger.debug(
>                     "AD-723: %s raised on path %s; degrading",
>                     method_name, path.value, exc_info=True,
>                 )
>                 continue
>             self._apply_sensorium_result(state, entry, method_name, result)
>     return state
> ```
>
> Use this single-dict form. The two-call form is shown only to illustrate the priority-merge issue.

### 7.2 `_build_cognitive_baseline` (line 4438) and `_build_cognitive_extensions` (line 4610) — STAY SYNC

Replace bodies with thin SYNC shims around the sync dispatcher. Signatures unchanged. Existing test call sites in `tests/test_ad646_cognitive_baseline.py`, `tests/test_ad646b_chain_parity.py`, `tests/test_ad635f_clinical_proactive_context.py`, `tests/test_ad648_post_capability_profiles.py` (~17 total) continue to work without modification.

```python
def _build_cognitive_baseline(self, observation: dict) -> dict[str, str]:
    """AD-723: thin shim — dispatches CHAIN_BASELINE synchronously."""
    return self._dispatch_sensorium_sync(SensoriumPath.CHAIN_BASELINE, observation)


def _build_cognitive_extensions(self, context_parts: dict) -> dict[str, str]:
    """AD-723: thin shim — dispatches CHAIN_EXTENSIONS synchronously."""
    return self._dispatch_sensorium_sync(
        SensoriumPath.CHAIN_EXTENSIONS,
        {"_context_parts": context_parts},
    )
```

### 7.3 `_build_situation_awareness` (line 4843) — STAYS SYNC

```python
def _build_situation_awareness(self, context_parts: dict) -> dict[str, str]:
    """AD-723: thin shim — dispatches CHAIN_SITUATION synchronously."""
    return self._dispatch_sensorium_sync(
        SensoriumPath.CHAIN_SITUATION,
        {"_context_parts": context_parts},
    )
```

Caller at `cognitive_agent.py:2345` is unchanged (no `await` added). Existing test caller in `tests/test_ad635f_clinical_proactive_context.py` continues to work.

### 7.4 `_build_user_message` DM branch

Replace the inline-block sequence with:

```python
if intent_name == "direct_message":
    parts: list[str] = []

    # AD-683: boot-camp ship state snapshot — DM-only cold-start preamble (inline).
    # ... (UNCHANGED body of the existing block) ...

    # AD-723: dispatch DM_ONESHOT sensorium injections (async — handles
    # both sync and async registered methods).
    blocks = await self._dispatch_sensorium_async(SensoriumPath.DM_ONESHOT, observation)

    # Temporal awareness wrap (inline framing around the dispatched key).
    if blocks.get("_temporal_context"):
        parts.append("--- Temporal Awareness ---")
        parts.append(blocks["_temporal_context"])
        parts.append("---")
        parts.append("")

    # Remaining DM_ONESHOT keys are rendered in registry-defined order
    # (the dispatcher already sorted them). Each is appended as its own
    # block with a blank-line separator, MATCHING the prior inline layout
    # block-for-block. Snapshot tests are the byte-equality gate.
    for key in (
        "_cognitive_zone",
        "_introspective_telemetry",
        "_working_memory_context",
        "_avatar_self_observation",
        "_intent_self_tag",
        "_formatted_memories_section",
        "_oracle_context_block",
        "_source_attribution_tag",
    ):
        if blocks.get(key):
            parts.append(blocks[key])
            parts.append("")

    # AD-572: active game (rendered from CHAIN_SITUATION/DM_ONESHOT entry).
    if blocks.get("_active_game"):
        parts.append(blocks["_active_game"])
        parts.append("")

    # Session history (DM-only, inline).
    # ... (UNCHANGED body of the existing block) ...

    parts.append(f"Captain says: {params.get('text', '')}")
    return "\n".join(parts)
```

**Block ordering is locked by the snapshot test.** The key tuple above matches the existing inline order. Builder MUST NOT reorder.

### 7.5 `_build_user_message` WR branch

Same pattern — narrower key tuple:

```python
if intent_name == "ward_room_notification":
    # ... (UNCHANGED channel header + thread title preamble) ...

    blocks = await self._dispatch_sensorium_async(SensoriumPath.WR_ONESHOT, observation)

    if blocks.get("_temporal_context"):
        wr_parts.append("")
        wr_parts.append("--- Temporal Awareness ---")
        wr_parts.append(blocks["_temporal_context"])
        wr_parts.append("---")

    for key in (
        "_cognitive_zone",
        "_dm_self_monitoring",
        "_introspective_telemetry",
        "_working_memory_context",
        "_cold_start_note",
        "_formatted_memories_section",
        "_oracle_context_block",
        "_source_attribution_tag",
    ):
        if blocks.get(key):
            wr_parts.append("")
            wr_parts.append(blocks[key])

    # ... (UNCHANGED augmentation skill block, conversation context,
    #      self-recognition rendering, author footer, mention guidance) ...
```

Note: WR retains its own block-spacing convention (blank-line BEFORE each block, not after). This matches the existing layout. Snapshot tests confirm.

---

## 8. Tests

**New file:** `tests/test_ad723_sensorium_dispatch.py`.

### 8.1 Golden-text snapshot tests (3 cases — these are the safety net)

Fixtures live in `tests/fixtures/sensorium_snapshots/`:

- `chain_baseline.txt` — rendered output of `_dispatch_sensorium(CHAIN_BASELINE, observation)` for a canned observation
- `dm_oneshot.txt` — rendered output of `_build_user_message({"intent": "direct_message", ...})` for a canned DM observation
- `wr_oneshot.txt` — rendered output of `_build_user_message({"intent": "ward_room_notification", ...})` for a canned WR observation

**Capture workflow (Builder, ONCE pre-refactor):**

1. Before applying the refactor, write a temporary script that constructs a `CognitiveAgent` with a deterministic fake runtime, calls the existing pre-refactor assembly methods, and writes the output verbatim to the three fixture files. Commit the fixtures in the SAME commit as the refactor.
2. After applying the refactor, the test re-runs the same construction and asserts byte equality.

```python
def test_chain_baseline_byte_equality(canned_agent, canned_chain_observation):
    """AD-723: refactored CHAIN_BASELINE dispatch produces byte-identical output."""
    fixture = (FIXTURES_DIR / "chain_baseline.txt").read_text(encoding="utf-8")
    actual_dict = asyncio.run(
        canned_agent._dispatch_sensorium(
            SensoriumPath.CHAIN_BASELINE, canned_chain_observation,
        )
    )
    actual = "\n".join(f"{k}\n{v}" for k, v in actual_dict.items())
    assert actual == fixture, "AD-723 byte-equality regression"
```

(Builder writes equivalent tests for DM and WR. The "rendered output" must include the key order — that's part of the contract.)

### 8.2 Path-coherence tests (5+ cases)

```python
def test_avatar_not_in_wr_paths():
    """AD-722 addendum (h): avatar block is NOT injected into WR (peer audience)."""
    entry = CognitiveAgent.SENSORIUM_REGISTRY["_build_avatar_self_observation"]
    assert SensoriumPath.WR_ONESHOT not in entry.paths

def test_intent_self_tag_not_in_wr_paths():
    """AD-722a: intent self-tag follows avatar block — also NOT in WR."""
    entry = CognitiveAgent.SENSORIUM_REGISTRY["_build_intent_self_tag_instruction"]
    assert SensoriumPath.WR_ONESHOT not in entry.paths

def test_dm_self_monitoring_not_in_dm_paths():
    """`_build_dm_self_monitoring` is for WR dm-* channel detection, not DM one-shot."""
    entry = CognitiveAgent.SENSORIUM_REGISTRY["_build_dm_self_monitoring"]
    assert SensoriumPath.DM_ONESHOT not in entry.paths
    assert SensoriumPath.WR_ONESHOT in entry.paths

def test_situation_entries_chain_only():
    """CHAIN_SITUATION entries never appear in DM/WR (situation is chain-only)."""
    for name, entry in CognitiveAgent.SENSORIUM_REGISTRY.items():
        if SensoriumPath.CHAIN_SITUATION in entry.paths:
            assert SensoriumPath.DM_ONESHOT not in entry.paths, name
            assert SensoriumPath.WR_ONESHOT not in entry.paths, name

def test_all_registered_methods_exist():
    """Phantom-API guard: every registered method name must resolve on CognitiveAgent."""
    for method_name in CognitiveAgent.SENSORIUM_REGISTRY:
        assert hasattr(CognitiveAgent, method_name), (
            f"AD-723: {method_name} is registered but not defined on CognitiveAgent"
        )
```

### 8.3 Dispatcher unit tests (≥ 8 cases)

- `test_dispatch_empty_paths_returns_empty` — entry with `paths=()` is never invoked
- `test_dispatch_priority_ordering` — higher-priority entry overrides lower-priority for same key
- `test_dispatch_registration_order_preserved` — same priority → dict-insertion order
- `test_dispatch_none_signals_removal` — extension returns `None` → key is popped from merged dict
- `test_dispatch_empty_string_skipped` — entry returns `""` → key NOT set
- `test_dispatch_async_method_awaited` — coroutine method correctly awaited (use `inspect.iscoroutinefunction` precondition; assert `await`-shaped behaviour)
- `test_dispatch_sync_method_called_direct` — non-async method called without await
- `test_dispatch_method_raise_tier2_degrade` — exception in registered method → logged, skipped, no propagation
- `test_dispatch_missing_method_warning` — registry name not bound → WARNING logged, skipped

### 8.4 Path-specific dispatch tests (≥ 4 cases)

- `test_chain_baseline_dispatch_calls_extensions_via_state` — `_build_cognitive_state` runs both BASELINE and EXTENSIONS
- `test_situation_dispatch_chain_only` — `_dispatch_sensorium(CHAIN_SITUATION, ...)` returns only EXTEROCEPTION entries
- `test_dm_dispatch_excludes_situation` — DM_ONESHOT path does not include CHAIN_SITUATION entries (active_game is DUAL-registered)
- `test_wr_dispatch_excludes_avatar` — WR_ONESHOT result has no `_avatar_self_observation` key

### 8.5 AD-646 None-removal regression (≥ 2 cases)

- `test_extensions_no_memories_removal` — when extensions return `None` for `_no_episodic_memories`, the merged state does NOT contain that key
- `test_extensions_priority_override` — extensions key with priority 10 overrides baseline key with priority 0

---

## 9. What This Does NOT Change

- **The System-1 / System-2 path split is preserved.** Chain stays chain; DM stays DM; WR stays WR. AD-723 unifies the *wiring registry*, not the *paths*.
- **No new sensorium injections.** Every entry in the new registry corresponds to a method/block that already exists at HEAD. Zero new capability.
- **No new config fields.** Existing `sensorium.enabled` / `sensorium.token_budget_warning` (read by `_track_sensorium_budget`) are unchanged.
- **No new event types.** `EventType.SENSORIUM_BUDGET_EXCEEDED` (read at line 4831) continues to fire from the same call site.
- **AD-722 / AD-722a feature flags unchanged.** `inject_into_agent_context` and `divergence_detection` continue to gate the avatar block and the self-tag, respectively. AD-723 only refactors WHERE they are wired.
- **No changes to `routers/agents.py`.** The chat handler is unaffected. `mark_reply_emitted` continues to be called from its single call site (line 908 / 909).
- **No changes to the chain executor.** `_execute_chain_with_intent_routing` (around line 2336) gets one `await` added to its `_build_cognitive_state` call; otherwise unchanged.
- **No changes to the AD-646 None-removal semantics.** Extensions can still return None for keys they want removed from the merged state.
- **No federation / replication changes.** The registry is `ClassVar` on `CognitiveAgent`; federated agents inherit the same registry.
- **No commercial overlay changes.** The registry is a public class attribute; overlay subclasses can extend it via standard Python `SENSORIUM_REGISTRY = {**super().SENSORIUM_REGISTRY, ...}` — but that's a future capability, not part of AD-723.

---

## 10. Tracking

After the commit lands, the Builder updates:

- **`PROGRESS.md`**: status line records Wave 144 shipped, AD-723 closed (#581). Test count delta recorded.
- **`progress-era-5-unification.md`** (the active era file): append an entry summarizing AD-723's deliverables and the dual-wire tax it eliminates. Reference the snapshot suite as the safety net.
- **`docs/development/roadmap.md`**: mark AD-723 / #581 as SHIPPED.
- **`DECISIONS.md`**: the AD-723 entry (lines 1731-1742) already exists as a forward marker — append a "**Shipped:** 2026-05-NN — Wave 144." line. No further edits.

---

## 11. Acceptance Criteria

- All 14 existing `SENSORIUM_REGISTRY` entries preserved; one new entry added (`_build_intent_self_tag_instruction`); inline-extracted methods registered per §5.2.
- `SensoriumPath` and `SensoriumEntry` types added per §4.
- `_dispatch_sensorium` implemented per §6.1; tier-2 degrade verified by test §8.3.
- All four chain shims (`_build_cognitive_state`, `_build_cognitive_baseline`, `_build_cognitive_extensions`, `_build_situation_awareness`) refactored per §7 — **signatures unchanged (stay sync)**. DM/WR branches of `_build_user_message` use `_dispatch_sensorium_async`.
- ~17 existing test call sites across `tests/test_ad646_cognitive_baseline.py`, `tests/test_ad646b_chain_parity.py`, `tests/test_ad635f_clinical_proactive_context.py`, `tests/test_ad648_post_capability_profiles.py` continue to pass WITHOUT modification (sync signatures preserved).
- Golden-text snapshot fixtures (3 files) committed with the refactor; byte-equality tests pass.
- All ≥ 22 new tests pass. Full parallel gate green: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile`.
- No Vitest delta. No UI changes.
- No phantom APIs: every registered method name resolves on `CognitiveAgent` (test §8.2 `test_all_registered_methods_exist`).
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
