# Build Prompt — Group-Memory Enrichment Wave (AD-986a + AD-987)

**Architect:** verify-first complete (2026-06-13). All file:line references below were
read against the live codebase. **Builder:** implement exactly; do not expand scope.

Two coupled ADs that edit the SAME group-episode write block in
`src/probos/routers/thread_fanout.py` (the AD-933a write, ~lines 665–720) and the
SAME `AnchorFrame` dataclass (`src/probos/types.py:368`). Ship together (one write site).

Both are **default-OFF** (convention #14): byte-identical episodes until the config
flags are enabled.

---

## Background (from the live 2026-06-12/13 investigation + Counselor feedback)

The group-episode write stores:
- `episode_input = f"[group chat] {trigger_body[:200]}"` — **no speaker label** on the
  round-0 Captain trigger (cascade-round triggers already embed `callsign: text` labels).
- `reflection = f"{callsign} said in group chat: {reply['text'][:240]}"` — the agent's
  own contribution is **truncated at 240 chars**, so a substantive multi-paragraph reply's
  payload is never indexed.
- `anchors = AnchorFrame(channel="chat", trigger_type="group_fanout", participants=…,
  chat_thread_id=…)` — the SOCIAL slot **`trigger_agent` is never set** (it exists at
  `types.py:227`/`:391` and is already extracted to `anchor_trigger_agent` metadata at
  `episodic.py:516,524`).
- The frame the agent SAW at capture lives separately in its `VisionWorkingMemory` ring
  (`VisionObservation.attachment_ref` + `.description`, `working_memory.py:23-27`), bound to
  nothing — so recall yields "what was said" and "what I saw" as two disconnected streams.

`_prepare_document` (`episodic.py:2966`) indexes `user_input` + `reflection` into the
embedding (FTS5 already indexes both). `anchors_json` is written via
`json.dumps(dataclasses.asdict(ep.anchors))` (`episodic.py:2934`) and read via
`AnchorFrame(**json.loads(...))` (`episodic.py:767`) — so **new AnchorFrame fields with
defaults serialize automatically and round-trip backward-compatibly.**

---

## AD-986a (#929 — contained slice): speaker attribution + reflection fidelity

> Note: the eviction-weighted retention half of #929 is **deferred** (it touches the
> retention substrate — design-gated, watch-then-calibrate). This wave ships the
> contained, testable reflection-fidelity + attribution slice.

### Config — `src/probos/config.py` `MemoryConfig`
- `group_episode_enrichment_enabled: bool = False`
- `group_reflection_max_chars: int = 600`

### `src/probos/routers/thread_fanout.py`
1. Add a `trigger_speaker: str = ""` parameter to `_fan_one_round` (after `trigger_body`).
2. Round-0 caller (~line 802): pass `trigger_speaker="Captain"`.
3. Cascade caller (~line 899): pass `trigger_speaker=""` (the joined trigger already carries
   per-line `callsign: text` labels — do not double-label).
4. In the AD-933a episode write, read the gate once:
   `_enrich = bool(getattr(mem_cfg, "group_episode_enrichment_enabled", False))`.
   - When `_enrich`:
     - `episode_input = f"[group chat] {trigger_speaker}: {trigger_body[:200]}"` if
       `trigger_speaker` else `f"[group chat] {trigger_body[:200]}"`.
     - reflection cap = `getattr(mem_cfg, "group_reflection_max_chars", 600)`.
     - set `anchors.trigger_agent = trigger_speaker` (only when non-empty).
   - When not `_enrich`: byte-identical to today (no prefix, `[:240]`, `trigger_agent=""`).

### Acceptance
- Enrichment ON: round-0 episode `user_input` starts `"[group chat] Captain: "`; the agent's
  reflection includes content past char 240; `anchors.trigger_agent == "Captain"`.
- Enrichment OFF: episode is byte-identical to the pre-change write.
- BF-287 tests on a real `EpisodicMemory` + real `ChatThreadStore`.

---

## AD-987 (new issue): visual↔conversational binding at capture

### Config — `src/probos/config.py` `MemoryConfig`
- `episode_visual_binding_enabled: bool = False`

### `src/probos/types.py` `AnchorFrame` (EVIDENTIAL section, after `event_log_window`)
- `visual_attachment_ref: str = ""`  # SHA-256 of the frame the agent saw (AttachmentStore, durable)
- `visual_description: str = ""`      # vision-LLM description at capture

### `src/probos/routers/thread_fanout.py` (same episode write)
When `getattr(mem_cfg, "episode_visual_binding_enabled", False)`:
- `from probos.perception.consumer import get_or_create_working_memory`
- `_obs = get_or_create_working_memory(reply["agent_id"]).latest()`
- if `_obs is not None and _obs.attachment_ref`: set `anchors.visual_attachment_ref =
  _obs.attachment_ref` and `anchors.visual_description = _obs.description`.
- Tier-2: wrap in try/except (binding failure must never block the episode write).

### `src/probos/cognitive/episodic.py` `_prepare_document` (~line 2992, after reflection)
- When `episode.anchors and episode.anchors.visual_description`: append
  `f"[saw: {episode.anchors.visual_description}]"` to `parts` — so "what was I seeing when
  X" becomes recall-searchable (ties the two streams at the embedding level). This is
  implicitly gated (the field is only populated when binding is enabled) → byte-identical off.

### Acceptance
- Binding ON + a live frame in the agent's ring: the stored episode's
  `anchors.visual_attachment_ref` == the ring's latest `attachment_ref`;
  `_prepare_document` output contains `[saw: …]`.
- Binding OFF: `AnchorFrame.visual_* == ""`; `_prepare_document` unchanged; episode
  byte-identical.
- New `AnchorFrame` fields round-trip through `asdict` → `AnchorFrame(**json.loads(...))`.
- BF-287 tests on a real store.

---

## Do NOT change
- The 1:1 episode path (`_store_action_episode`), the cascade trigger labeling, the
  facilitator, the sovereign-shard recall filter, or any existing AnchorFrame field.
- Eviction/retention logic (the deferred #929 half).
- Both flags default False; enable in `config/system.yaml` only after gates pass.

## Verify compliance with `.github/copilot-instructions.md` Engineering Principles.
