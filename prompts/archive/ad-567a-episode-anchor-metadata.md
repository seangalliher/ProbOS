# AD-567a: Episode Anchor Metadata — Rich Contextual Storage

## Priority: High | Scope: Medium | Type: Foundation AD (all AD-567 sub-ADs depend on this)

## Context

ProbOS agents contend with two overlapping knowledge sources (LLM parametric knowledge and episodic memory) in a single perceptual frame. Without explicit grounding, the boundaries blur and confabulation becomes indistinguishable from genuine recall. Evidence:

- **OBS-014:** Vega caught her own confabulation by checking anchors — metacognitive skill works
- **OBS-015:** Horizon+Atlas cascade confabulation — neither agent verified anchors, social propagation amplified fiction

Standing orders (federation.md Memory Anchoring Protocol) instruct agents to ground memories in ship reality. AD-567a provides the **architectural support** — enriching episode storage with contextual anchors that make grounding computable, not just behavioral.

### Intellectual Lineage

- **Johnson SMF (1993):** The 6 anchor dimensions ARE Johnson's "qualitative characteristics" computationally formalized. Direct SMF implementation for AI agents.
- **SEEM (Lu 2026):** Structure anchor metadata as a typed `AnchorFrame` dataclass (SEEM's Episodic Event Frame pattern) — richer provenance than flat key-value metadata.
- **Video-EM (Wang 2025):** When/where/what/entities framework validates that explicit dimensional tagging improves downstream reasoning.

## Design

### New Data Structure: `AnchorFrame`

Add to `src/probos/types.py` as a frozen dataclass alongside `Episode`:

```python
@dataclass(frozen=True)
class AnchorFrame:
    """Contextual anchors grounding an episode in ship reality (AD-567a).

    Inspired by Johnson's Source Monitoring Framework — the qualitative
    characteristics that distinguish genuine memory from confabulation.
    SEEM's Episodic Event Frame pattern — typed structure, not flat metadata.
    """
    # TEMPORAL — when did this happen?
    # (Episode.timestamp covers the primary "when"; these add context)
    duty_cycle_id: str = ""          # Links to DutyAssignment.duty_id if from duty cycle
    watch_section: str = ""          # e.g., "morning", "evening" — temporal context

    # SPATIAL — where in the ship did this happen?
    channel: str = ""                # "ward_room", "dm", "duty_report", "dag", "feedback", "smoke_test"
    channel_id: str = ""             # Specific Ward Room channel or thread ID
    department: str = ""             # Agent's department at time of episode

    # SOCIAL — who was involved?
    participants: list[str] = field(default_factory=list)  # Callsigns present/involved
    trigger_agent: str = ""          # Callsign of agent/entity that triggered this episode

    # CAUSAL — why did this happen?
    trigger_type: str = ""           # "duty_cycle", "proactive_think", "direct_message",
                                     # "captain_request", "event_response", "ward_room_post",
                                     # "ward_room_reply", "feedback", "smoke_test", "dag_execution"

    # EVIDENTIAL — what corroborates this?
    thread_id: str = ""              # Ward Room thread ID for cross-reference
    event_log_window: float = 0.0    # Timestamp range for EventLog cross-verification
```

### Episode Dataclass Update

Add a single field to `Episode` in `src/probos/types.py`:

```python
@dataclass(frozen=True)
class Episode:
    # ... existing fields ...
    source: str = "direct"
    # AD-567a: Contextual anchors grounding this episode in ship reality
    anchors: AnchorFrame | None = None
```

Default to `None` for backwards compatibility with existing episodes.

### MemorySource Fix

While touching episode creation paths, also fix the `MemorySource` wiring gap. Ward Room episodes currently all use `source="direct"` even when the agent is reading/hearing another agent's post. The Ward Room creation paths (sites #7-#10) create episodes for the **authoring** agent, so `DIRECT` is actually correct there — the author directly experienced posting. The `SECONDHAND` source will become relevant when agents create episodes from *reading* others' posts (future, not this AD). Do NOT change existing `source` values in this AD.

## Changes Required

### 1. Data structures (`src/probos/types.py`)

Add `AnchorFrame` dataclass before `Episode`. Add `anchors: AnchorFrame | None = None` field to `Episode` (after `source`).

### 2. Serialization (`src/probos/cognitive/episodic.py`)

**`_episode_to_metadata()` (~line 808):** Add anchor serialization to the metadata dict:

```python
"anchors_json": json.dumps(dataclasses.asdict(ep.anchors)) if ep.anchors else "",
```

**IMPORTANT:** The `anchors` field must NOT be included in the `compute_episode_hash()` computation. Content hash covers the episode's *content* (user_input, outcomes, etc.), not its *metadata framing*. Anchors are metadata about the episode, not the episode content itself. The `normalized` Episode used for hashing at line 829 should strip `anchors` to `None`:

```python
normalized = replace(ep, timestamp=ts, duration_ms=dur, source=ep.source or "direct", anchors=None)
```

This ensures existing content hashes remain valid and anchor addition/modification doesn't break integrity checks.

**`_metadata_to_episode()` (~line 847):** Add anchor deserialization:

```python
anchors_raw = metadata.get("anchors_json", "")
anchors = AnchorFrame(**json.loads(anchors_raw)) if anchors_raw else None
```

Pass `anchors=anchors` to the Episode constructor.

### 3. KnowledgeStore deserialization (`src/probos/knowledge/store.py`)

In `load_episodes()` (~line 104), add deserialization of anchors from the JSON episode representation. If `anchors` key exists in the dict, construct `AnchorFrame(**ep_dict["anchors"])`, otherwise `None`.

### 4. Episode creation sites — Anchor capture

Each episode creation site needs to construct an `AnchorFrame` with the context available at that point. **Capture what you know at creation time — recorded facts, not reconstructed inferences.**

#### Site 1: Dream Adapter (`src/probos/dream_adapter.py` ~line 343)

`build_episode()` — DAG execution pipeline (richest path).

```python
AnchorFrame(
    channel="dag",
    trigger_type="dag_execution",
    participants=[callsign for agent involved in DAG nodes],  # derive from execution_result
)
```

Context: extract agent callsigns from DAG node results. Department not directly available here — skip it (the agent's department is their own concern, not the DAG's).

#### Site 2-3: Runtime/Renderer fallback (`src/probos/runtime.py` ~line 2185, `src/probos/experience/renderer.py` ~line 414)

Bare fallback episodes. Minimal anchors:

```python
AnchorFrame(channel="dag", trigger_type="dag_execution")
```

#### Site 4: Cognitive Agent (`src/probos/cognitive/cognitive_agent.py` ~line 2167)

`_store_action_episode()` — agent action safety net.

Context available: `self.agent_type`, intent name, intent params (including "from" source), `self._runtime.ontology`.

```python
AnchorFrame(
    channel="action",
    department=self._resolve_department(),  # helper to get dept from ontology
    trigger_type=intent.name,  # e.g., "analyze_data", "security_scan"
    trigger_agent=observation.get("params", {}).get("from", ""),
)
```

Add a helper `_resolve_department(self) -> str` that safely gets the agent's department from runtime ontology. Pattern: `self._runtime.ontology.get_department(self.agent_type)` — grep the codebase for how other code resolves department and match that pattern.

#### Site 5-6: Proactive Loop (`src/probos/proactive.py` ~lines 486, 639)

Duty cycle episodes. Rich context available.

```python
AnchorFrame(
    channel="duty_report",
    duty_cycle_id=duty.duty_id if duty else "",
    watch_section=duty.watch_section if duty and hasattr(duty, "watch_section") else "",
    department=_resolve_department_for_agent(agent, rt),  # helper
    trigger_type="duty_cycle" if duty else "proactive_think",
)
```

Add a module-level helper `_resolve_department_for_agent(agent, runtime) -> str` that resolves department from the ontology. Keep it safe — return `""` on any error.

#### Site 7: Ward Room Thread Creation (`src/probos/ward_room/threads.py` ~line 356)

```python
AnchorFrame(
    channel="ward_room",
    channel_id=channel_id,
    thread_id=thread.id,
    trigger_type="ward_room_post",
    participants=[author_callsign or author_id],
    trigger_agent=author_callsign or author_id,
)
```

#### Site 8: Ward Room Thread Peer Repetition (`src/probos/ward_room/threads.py` ~line 385)

```python
AnchorFrame(
    channel="ward_room",
    channel_id=channel_id,
    thread_id=thread.id if thread else "",
    trigger_type="peer_repetition",
    trigger_agent=top_match["author_callsign"],
)
```

#### Site 9: Ward Room Reply (`src/probos/ward_room/messages.py` ~line 157)

```python
AnchorFrame(
    channel="ward_room",
    channel_id=channel_name,  # or the actual channel_id if available
    thread_id=thread_id,
    trigger_type="ward_room_reply",
    participants=[author_callsign or author_id],
    trigger_agent=author_callsign or author_id,
)
```

#### Site 10: Ward Room Reply Peer Repetition (`src/probos/ward_room/messages.py` ~line 185)

Same pattern as Site 8.

#### Site 11: Shell 1:1 Session (`src/probos/experience/commands/session.py` ~line 143)

```python
AnchorFrame(
    channel="dm",
    department=self.department,  # already available on AgentSession!
    trigger_type="direct_message",
    trigger_agent="captain",
    participants=["captain", self.callsign],
)
```

#### Site 12: HXI API 1:1 (`src/probos/routers/agents.py` ~line 205)

```python
AnchorFrame(
    channel="dm",
    trigger_type="direct_message",
    trigger_agent="captain",
    participants=["captain", callsign],
)
```

Department: resolve from `agent.agent_type` via ontology if runtime is accessible. Otherwise skip.

#### Site 13-14: Feedback (`src/probos/cognitive/feedback.py` ~lines 216, 368)

```python
AnchorFrame(
    channel="feedback",
    trigger_type="human_correction" or "human_feedback",
    trigger_agent="captain",
)
```

#### Site 15: SystemQA Smoke Test (`src/probos/runtime.py` ~line 2922)

```python
AnchorFrame(
    channel="smoke_test",
    trigger_type="smoke_test",
)
```

### 5. Import updates

Every file that creates an `Episode` with anchors needs `from probos.types import AnchorFrame`. Add the import alongside existing `Episode` imports.

Files requiring new import:
- `src/probos/dream_adapter.py`
- `src/probos/runtime.py`
- `src/probos/experience/renderer.py`
- `src/probos/cognitive/cognitive_agent.py`
- `src/probos/proactive.py`
- `src/probos/ward_room/threads.py`
- `src/probos/ward_room/messages.py`
- `src/probos/experience/commands/session.py`
- `src/probos/routers/agents.py`
- `src/probos/cognitive/feedback.py`

## Do NOT Change

- **Retrieval behavior** — this AD only enriches storage. Recall methods remain untouched (AD-567b will add anchor-aware formatting).
- **Dream consolidation** — do not modify dream steps (AD-567d handles anchor preservation).
- **Content hash computation** — anchors must be EXCLUDED from content hash. See Section 2 above.
- **`MemorySource` values** — do not change which source value is assigned at any creation site. The current `source="direct"` assignments are correct for authoring-agent episodes.
- **`should_store()` gate** — do not modify the selective encoding gate.
- **Existing episode recall/display** — `_format_memory_section()` in cognitive_agent.py should not be modified (that's AD-567b).

## Verification Before Implementation

1. **Grep `Episode(` across the codebase** to confirm you have ALL creation sites. The 15 sites listed above were identified from research — verify no new ones have been added.
2. **Grep for department resolution patterns** — find how other code resolves an agent's department from the ontology. Match that pattern for the helper functions.
3. **Check `DutyAssignment`** — verify it has `duty_id` and `watch_section` attributes. Grep for the class definition.
4. **Check `compute_episode_hash`** — confirm the hash function uses the Episode dataclass and that excluding `anchors=None` in the normalized copy won't break it (it should work fine since `None` is the default).

## Tests

### Unit tests for AnchorFrame

- Test `AnchorFrame()` default construction (all empty strings/lists)
- Test `AnchorFrame` with full fields
- Test `AnchorFrame` serialization round-trip: `asdict()` → JSON → `AnchorFrame(**loaded)`
- Test `AnchorFrame` is frozen (immutable)

### Serialization round-trip

- Test `_episode_to_metadata()` with anchored Episode → metadata includes `anchors_json`
- Test `_episode_to_metadata()` with `anchors=None` → metadata has empty `anchors_json`
- Test `_metadata_to_episode()` with `anchors_json` → Episode has populated anchors
- Test `_metadata_to_episode()` without `anchors_json` key → Episode has `anchors=None` (backwards compat)
- Test content hash is identical with and without anchors (anchors excluded from hash)

### Per-site anchor capture

For each of the 15 creation sites, at minimum test:
- Episode is created with `anchors` not None
- `anchors.channel` is set to the expected value
- `anchors.trigger_type` is set to the expected value

Focus test effort on the 5 most important paths:
1. Dream adapter (`channel="dag"`)
2. Proactive duty cycle (`channel="duty_report"`, `duty_cycle_id` populated)
3. Ward Room thread (`channel="ward_room"`, `thread_id` populated)
4. Shell 1:1 (`channel="dm"`, `participants` includes "captain")
5. Cognitive agent action (`trigger_type` matches intent name)

### Backwards compatibility

- Test that existing episodes without `anchors_json` in metadata deserialize correctly (`anchors=None`)
- Test that `KnowledgeStore.load_episodes()` handles episodes with and without anchors
- Test that `should_store()` gate still works with anchored episodes
- Test that content hash verification still passes for anchored episodes

## Acceptance Criteria

- `AnchorFrame` dataclass in `types.py` with 10 fields (temporal, spatial, social, causal, evidential)
- `Episode.anchors` field added (optional, default None)
- All 15 episode creation sites populate `AnchorFrame` with available context
- Serialization/deserialization round-trip works through ChromaDB metadata
- Content hash is NOT affected by anchor metadata
- All existing tests pass (no regressions)
- New tests cover AnchorFrame construction, serialization, and per-site capture
