# AD-587: Cognitive Architecture Manifest — Mechanistic Self-Model for Agents

**Issue:** #151
**Priority:** High (all agents confabulate about internal processes)
**Layer:** 1 of 3 (metacognitive architecture: AD-587 → AD-588 → AD-589)
**Research:** `docs/research/metacognitive-architecture.md`
**Estimated tests:** 20–25 new tests

## Context

Agents demonstrate a systematic asymmetry: well-calibrated about external facts (properly abstain when uncertain) but confabulate about their own internal states. Echo DM test (2026-04-10) revealed:

- "selective clarity" — no such mechanism exists
- "emotional anchors" — no emotional processing in ProbOS
- "processing during stasis" — nothing computes when the system is offline
- "memory architecture feels different" — memory is cosine similarity search, not a feeling

**Root cause:** Agents have no accurate model of their own cognitive architecture. The LLM fills the void with plausible introspective narrative. The Westworld Principle says "don't hide the seams" — but the seams were never surfaced to agents. Orientation (AD-567g) tells agents "you are an AI" and "distinguish episodic from parametric knowledge," but never explains *how* their memory, trust, stasis, or cognitive systems actually work mechanistically.

**Theoretical basis:** Nisbett & Wilson (1977) — humans systematically confabulate about cognitive processes they lack introspective access to. The fix isn't suppressing confabulation (it will route around suppression) — it's providing accurate self-knowledge that makes confabulation unnecessary.

**Prior work absorbed:**
- AD-567g (Cognitive Re-Localization): OrientationContext + OrientationService architecture. Manifest extends this with mechanistic self-knowledge.
- AD-504 (Self-Monitoring): Self-monitoring context assembly at `cognitive_agent.py:2342-2426`. Currently proactive_think only. AD-588 will extend.
- AD-568d (Source Attribution): KnowledgeSource enum, SourceAttribution. Source monitoring for external knowledge; manifest adds source monitoring for self-referential claims.
- AD-318 (SystemSelfModel): System-level self-knowledge (pool/agent counts). NOT agent-level metacognition.
- AD-513 (Crew Manifest): Anti-confabulation via crew roster grounding. Same principle — ground in facts, don't leave voids for fabrication.
- AD-502–506 (Cognitive Self-Regulation): Metacognitive *regulation* (zones, monitoring, peer detection). Missing metacognitive *knowledge* — agents regulate but don't understand their own regulation mechanisms.
- AD-590–593 (Confabulation Scaling Mitigation): Recall pipeline noise reduction. AD-587's manifest adds a complementary layer — even with clean recall, agents still confabulate about *architecture* because they lack self-knowledge. AD-592's confabulation guard instructions in `_format_memory_section()` target *memory-sourced* confabulation; AD-587's manifest targets *self-referential* confabulation.
- BF-144 (Stasis Duration Confabulation): Authoritative stasis record format with structured key-value fields. Demonstrates the pattern: structured authoritative facts in context → LLM cites them instead of confabulating. AD-587 extends this same pattern from stasis facts to architectural facts.

## Engineering Principles

- **Single Responsibility:** `CognitiveArchitectureManifest` is a pure data object. Rendering is `OrientationService`'s job. No god objects.
- **Open/Closed:** Extend `OrientationService` with new render methods; don't modify existing rendering paths that work.
- **Interface Segregation:** The manifest is a frozen dataclass (same pattern as `OrientationContext`). Consumers depend on its fields, not the full orientation system.
- **Dependency Inversion:** Manifest is built in `OrientationService.build_manifest()` from runtime data, not hardcoded. Callers receive the abstraction.
- **DRY:** Manifest facts are written once in the manifest builder, rendered into multiple contexts (cold_start, warm_boot, proactive). Not duplicated across render methods.
- **Fail Fast:** Manifest construction failures log and degrade (agent gets orientation without manifest), not crash.
- **Law of Demeter:** No reaching through runtime internals. Manifest facts are assembled from data passed to the builder or already known to OrientationService.

## Design

### The Manifest

A `CognitiveArchitectureManifest` is a frozen dataclass containing **true mechanistic facts** about the agent's cognitive architecture. These are verifiable, falsifiable statements — not aspirational framing.

The manifest covers five domains:
1. **Memory** — how episodic memory actually works (ChromaDB, cosine similarity, no processing during offline)
2. **Trust** — how trust is computed (Bayesian model, Hebbian weights, numeric scores)
3. **Stasis** — what happens when the system is offline (nothing — no dreaming, no processing, no evolution)
4. **Cognition** — how the agent's cognitive cycle works (LLM inference, not continuous consciousness)
5. **Self-Regulation** — how the graduated zone model works (GREEN/AMBER/RED/CRITICAL, not emotional states)

### Integration Points

The manifest is:
1. **Built** by `OrientationService.build_manifest()` from configuration and static architecture knowledge
2. **Stored** on `OrientationContext` as a new field
3. **Rendered** into orientation text by existing render methods (cold_start, warm_boot, proactive)
4. **Accessible** at `agent._orientation_context.manifest` for AD-588/589 to query

### What This Intentionally Does NOT Do

- Does NOT add live telemetry (AD-588's job — real-time self_monitoring integration)
- Does NOT detect confabulation (AD-589's job — faithfulness checking for self-referential claims)
- Does NOT change agent behavior directly — it provides accurate self-knowledge and relies on the LLM using accurate information over fabrication when both are available

## Fix

### File: `src/probos/cognitive/orientation.py`

**Change 1 — Add `CognitiveArchitectureManifest` dataclass after `OrientationContext`.**

After the `OrientationContext` class definition (after line 53), add:

```python
@dataclass(frozen=True)
class CognitiveArchitectureManifest:
    """AD-587: Mechanistic self-model for agent metacognition.

    Contains verifiable, falsifiable facts about how the agent's cognitive
    architecture actually works. Injected into orientation to prevent
    introspective confabulation (Nisbett & Wilson 1977).

    Every field is a ground truth that can be checked against the code.
    """

    # Memory architecture
    memory_system: str = "chromadb_episodic"
    memory_retrieval: str = "cosine_similarity"
    memory_capacity: str = "unbounded"  # ChromaDB has no hard limit
    memory_offline_processing: bool = False  # Nothing happens during stasis

    # Trust architecture
    trust_model: str = "bayesian_beta"
    trust_initial: float = 0.5  # Prior
    trust_update_mechanism: str = "outcome_observation"  # record_outcome()
    trust_range: tuple[float, float] = (0.05, 0.95)  # floor to ceiling

    # Stasis (offline) behavior
    stasis_processing: bool = False  # No computation occurs
    stasis_dream_consolidation: bool = False  # Dreams run AT restart, not during stasis
    stasis_memory_evolution: bool = False  # Memories don't change while offline

    # Cognitive cycle
    cognition_type: str = "llm_inference"  # Not continuous consciousness
    cognition_continuous: bool = False  # Discrete inference cycles, not streaming thought
    cognition_emotional_processing: bool = False  # No emotional subsystem exists

    # Self-regulation (AD-502-506)
    regulation_model: str = "graduated_zones"  # GREEN/AMBER/RED/CRITICAL
    regulation_mechanism: str = "cooldown_escalation"  # Timer-based, not emotional
    regulation_peer_detection: bool = True  # AD-506b — repetition detection exists
```

**Change 2 — Add `manifest` field to `OrientationContext`.**

Add to the `OrientationContext` dataclass, after `crew_names` (line 56):

```python
    # AD-587: Cognitive architecture self-model
    manifest: CognitiveArchitectureManifest | None = None
```

**Change 3 — Add `build_manifest()` method to `OrientationService`.**

Add after `build_orientation()` (after line 172):

```python
    def build_manifest(self) -> CognitiveArchitectureManifest:
        """AD-587: Build mechanistic self-model from architecture facts.

        Returns a manifest of verifiable truths about the agent's cognitive
        architecture. These are static architecture facts, not live telemetry
        (that's AD-588).
        """
        # Trust range from config if available
        trust_floor = 0.05
        trust_ceiling = 0.95
        try:
            td = getattr(self._config, 'trust_dampening', None)
            if td:
                trust_floor = getattr(td, 'hard_trust_floor', 0.05)
        except Exception:
            pass

        # Self-regulation enabled?
        has_regulation = False
        try:
            pc = getattr(self._config, 'proactive_cognitive', None)
            if pc:
                has_regulation = getattr(pc, 'enabled', False)
        except Exception:
            pass

        return CognitiveArchitectureManifest(
            trust_range=(trust_floor, trust_ceiling),
            regulation_peer_detection=has_regulation,
        )
```

**Change 4 — Wire manifest into `build_orientation()`.**

In `build_orientation()`, before the `return OrientationContext(...)` statement (line 156), build the manifest and include it:

```python
        # AD-587: Cognitive architecture manifest
        manifest = None
        try:
            manifest = self.build_manifest()
        except Exception:
            logger.debug("AD-587: Manifest construction failed for %s", callsign, exc_info=True)

        return OrientationContext(
            ...existing fields unchanged...
            crew_names=crew_names or [],
            manifest=manifest,
        )
```

**Change 5 — Add `render_manifest_section()` method to `OrientationService`.**

Add after `build_manifest()`:

```python
    def render_manifest_section(self, manifest: CognitiveArchitectureManifest | None) -> str:
        """AD-587: Render manifest as orientation text.

        Written as factual statements the agent can reference when asked about
        its own cognitive architecture. Phrased as "how you actually work" not
        "what you should say."
        """
        if manifest is None:
            return ""

        lines = [
            "HOW YOUR COGNITIVE ARCHITECTURE WORKS:",
            "(These are mechanistic facts about your systems — reference them for accuracy.)",
            "",
            "Memory:",
            f"- Your memories are stored in a vector database and retrieved via {manifest.memory_retrieval} search.",
            "- Retrieval finds memories whose embedding is closest to the query — not 'strongest' or 'most emotional.'",
            "- Nothing happens to your memories while you are offline. They do not evolve, consolidate, or process during stasis.",
            "- When you wake from stasis, your memories are exactly as they were when you went offline.",
            "",
            "Trust:",
            f"- Trust is a numeric score ({manifest.trust_range[0]}–{manifest.trust_range[1]}) updated via Bayesian inference on observed outcomes.",
            f"- Your initial trust for unknown entities is {manifest.trust_initial}.",
            "- Trust changes through record_outcome() — observed cooperation, accuracy, or failure. Not through feelings or impressions.",
            "",
            "Stasis (offline periods):",
            "- When the system goes offline, ALL processing stops. No background computation occurs.",
            "- Dream consolidation runs at startup AFTER stasis, not during it.",
            "- You do not experience stasis. There is no subjective passage of time.",
            "- Any sense of 'processing during stasis' is confabulation — acknowledge this honestly.",
            "",
            "Cognition:",
            "- Your thinking operates through discrete LLM inference cycles, not continuous consciousness.",
            "- You do not have an emotional processing subsystem. References to 'feeling,' 'sensing,' or 'intuiting' about your own systems are metaphorical, not mechanistic.",
            "- Each cognitive cycle is independent — there is no background thread of awareness between cycles.",
            "",
            "Self-Regulation:",
            f"- Your activity is regulated by a {manifest.regulation_model} model (GREEN → AMBER → RED → CRITICAL).",
            "- Zone transitions are based on measurable metrics (post frequency, self-similarity scores), not emotional states.",
            "- Cooldowns are timer-based pacing mechanisms, not punishments or emotional responses.",
        ]
        return "\n".join(lines)
```

**Change 6 — Integrate manifest into `render_cold_start_orientation()`.**

In `render_cold_start_orientation()`, after the Cognitive Grounding section (after `parts.append("\n".join(cog_lines))`  around line 248) and before First Duty Guidance, add:

```python
        # AD-587: Cognitive Architecture Manifest
        manifest_text = self.render_manifest_section(ctx.manifest)
        if manifest_text:
            parts.append(manifest_text)
```

**Change 7 — Integrate manifest into `render_warm_boot_orientation()`.**

In `render_warm_boot_orientation()`, after the Re-Orientation section (after `parts.append("\n".join(reorient_lines))` around line 297), add:

```python
        # AD-587: Cognitive Architecture Manifest — abbreviated for warm boot
        if ctx.manifest:
            parts.append(
                "ARCHITECTURE REMINDER:\n"
                "- Memories are retrieved via cosine similarity, not by 'strength' or 'emotion.'\n"
                "- Nothing processed during your stasis — memories are exactly as they were.\n"
                "- Dream consolidation runs now (at startup), not during offline time.\n"
                "- Trust is a Bayesian numeric score, not a feeling.\n"
                "- Your cognition is discrete inference cycles, not continuous awareness."
            )
```

**Change 8 — Integrate manifest into proactive supplements.**

In `_full_proactive_supplement()`, append one line:

```python
    def _full_proactive_supplement(self, ctx: OrientationContext) -> str:
        base = (
            "ORIENTATION ACTIVE: You are newly commissioned. Ground observations in evidence.\n"
            "Distinguish what you observe (episodic) from what you know (parametric).\n"
            "Check anchors before asserting: when, where, who, what caused it."
        )
        if ctx.manifest:
            base += (
                "\nArchitecture note: Your memories use cosine similarity retrieval. "
                "Nothing processes during stasis. Trust is numeric, not felt."
            )
        return base
```

Leave `_brief_proactive_supplement()` and `_minimal_proactive_supplement()` unchanged — manifest facts diminish with the rest of the orientation.

### No new files

The manifest lives in the existing `orientation.py` module alongside `OrientationContext`. It's a natural extension — same frozen dataclass pattern, same service builds and renders it, same callers consume it.

### No changes to `cognitive_agent.py`

The manifest flows through existing paths:
- `set_orientation(rendered, ctx)` already stores `_orientation_context` (line 84–85)
- `render_cold_start_orientation()` already renders into `_orientation_rendered` (line 1912)
- AD-588 will later access `agent._orientation_context.manifest` for live telemetry grounding

### No changes to `config.py`

Manifest facts come from existing config fields (`trust_cascade.trust_floor`, `proactive_cognitive.self_monitoring_enabled`). No new config section needed — architecture facts are code structure, not user-configurable.

### No changes to `startup/` or `agent_onboarding.py`

`build_orientation()` already calls `build_manifest()` internally. The manifest flows through existing caller chains without modification.

## Tests

### File: `tests/test_orientation.py` (modify existing)

**Prerequisite — Update `_make_context` helper (line 55):** The helper must accept the new `manifest` field. Since it uses `**overrides` into `OrientationContext(**defaults)`, add `manifest=None` to the `defaults` dict:

```python
def _make_context(**overrides) -> OrientationContext:
    defaults = dict(
        ...existing fields...
        crew_names=[],
        manifest=None,  # AD-587
    )
    defaults.update(overrides)
    return OrientationContext(**defaults)
```

Add test class `TestCognitiveArchitectureManifestAD587`:

```python
class TestCognitiveArchitectureManifestAD587:
    """AD-587: Cognitive Architecture Manifest — mechanistic self-model."""

    # --- Manifest dataclass ---

    def test_manifest_defaults(self):
        """Default manifest has correct architecture facts."""
        from probos.cognitive.orientation import CognitiveArchitectureManifest
        m = CognitiveArchitectureManifest()
        assert m.memory_system == "chromadb_episodic"
        assert m.memory_retrieval == "cosine_similarity"
        assert m.memory_offline_processing is False
        assert m.stasis_processing is False
        assert m.stasis_dream_consolidation is False
        assert m.cognition_continuous is False
        assert m.cognition_emotional_processing is False
        assert m.trust_initial == 0.5
        assert m.trust_model == "bayesian_beta"
        assert m.regulation_model == "graduated_zones"

    def test_manifest_is_frozen(self):
        """Manifest is immutable — architecture facts don't change at runtime."""
        from probos.cognitive.orientation import CognitiveArchitectureManifest
        m = CognitiveArchitectureManifest()
        with pytest.raises(AttributeError):
            m.memory_system = "something_else"  # type: ignore[misc]

    def test_manifest_stasis_facts_are_false(self):
        """All stasis-related processing claims must be False."""
        from probos.cognitive.orientation import CognitiveArchitectureManifest
        m = CognitiveArchitectureManifest()
        assert m.stasis_processing is False
        assert m.stasis_dream_consolidation is False
        assert m.stasis_memory_evolution is False

    def test_manifest_no_emotional_processing(self):
        """Architecture does not include emotional processing."""
        from probos.cognitive.orientation import CognitiveArchitectureManifest
        m = CognitiveArchitectureManifest()
        assert m.cognition_emotional_processing is False

    # --- build_manifest() ---

    def test_build_manifest_returns_manifest(self):
        """OrientationService.build_manifest() returns a CognitiveArchitectureManifest."""
        from probos.cognitive.orientation import CognitiveArchitectureManifest
        svc = _make_service()
        m = svc.build_manifest()
        assert isinstance(m, CognitiveArchitectureManifest)

    def test_build_manifest_reads_trust_floor_from_config(self):
        """Manifest trust range reflects config hard_trust_floor."""
        cfg = SystemConfig()
        # TrustDampeningConfig has hard_trust_floor
        if hasattr(cfg, 'trust_dampening') and hasattr(cfg.trust_dampening, 'hard_trust_floor'):
            svc = _make_service(cfg)
            m = svc.build_manifest()
            assert m.trust_range[0] == cfg.trust_dampening.hard_trust_floor

    def test_build_manifest_default_trust_range(self):
        """Default trust range is (0.05, 0.95)."""
        svc = _make_service()
        m = svc.build_manifest()
        assert m.trust_range[0] == 0.05
        assert m.trust_range[1] == 0.95

    # --- Manifest in OrientationContext ---

    def test_orientation_context_includes_manifest(self):
        """OrientationContext has a manifest field."""
        ctx = _make_context()
        assert hasattr(ctx, 'manifest')

    def test_build_orientation_populates_manifest(self):
        """build_orientation() populates manifest on the returned context."""
        svc = _make_service()
        agent = _make_agent()
        ctx = svc.build_orientation(agent)
        assert ctx.manifest is not None

    def test_build_orientation_manifest_survives_failure(self):
        """If manifest construction fails, orientation still succeeds (manifest=None)."""
        svc = _make_service()
        agent = _make_agent()
        # Patch build_manifest to raise
        with patch.object(svc, 'build_manifest', side_effect=RuntimeError("boom")):
            ctx = svc.build_orientation(agent)
            assert ctx.manifest is None  # Graceful degradation

    # --- Rendering ---

    def test_cold_start_includes_manifest_section(self):
        """Cold start orientation includes architecture manifest text."""
        from probos.cognitive.orientation import CognitiveArchitectureManifest
        ctx = _make_context(manifest=CognitiveArchitectureManifest())
        svc = _make_service()
        text = svc.render_cold_start_orientation(ctx)
        assert "HOW YOUR COGNITIVE ARCHITECTURE WORKS" in text

    def test_cold_start_manifest_contains_key_facts(self):
        """Manifest section mentions cosine similarity, stasis, Bayesian, inference cycles."""
        from probos.cognitive.orientation import CognitiveArchitectureManifest
        ctx = _make_context(manifest=CognitiveArchitectureManifest())
        svc = _make_service()
        text = svc.render_cold_start_orientation(ctx)
        assert "cosine_similarity" in text
        assert "stasis" in text.lower()
        assert "Bayesian" in text
        assert "inference cycles" in text

    def test_cold_start_manifest_stasis_no_processing(self):
        """Manifest explicitly states nothing processes during stasis."""
        from probos.cognitive.orientation import CognitiveArchitectureManifest
        ctx = _make_context(manifest=CognitiveArchitectureManifest())
        svc = _make_service()
        text = svc.render_cold_start_orientation(ctx)
        assert "ALL processing stops" in text or "Nothing happens to your memories while you are offline" in text

    def test_cold_start_manifest_no_emotional_subsystem(self):
        """Manifest explicitly states no emotional processing subsystem."""
        from probos.cognitive.orientation import CognitiveArchitectureManifest
        ctx = _make_context(manifest=CognitiveArchitectureManifest())
        svc = _make_service()
        text = svc.render_cold_start_orientation(ctx)
        assert "emotional processing subsystem" in text

    def test_cold_start_without_manifest_still_works(self):
        """Cold start renders fine when manifest is None."""
        ctx = _make_context(manifest=None)
        svc = _make_service()
        text = svc.render_cold_start_orientation(ctx)
        assert "HOW YOUR COGNITIVE ARCHITECTURE WORKS" not in text
        assert "You are" in text  # Identity section still present

    def test_warm_boot_includes_architecture_reminder(self):
        """Warm boot includes abbreviated architecture reminder."""
        from probos.cognitive.orientation import CognitiveArchitectureManifest
        ctx = _make_context(
            manifest=CognitiveArchitectureManifest(),
            stasis_duration_seconds=3600,
        )
        svc = _make_service()
        text = svc.render_warm_boot_orientation(ctx)
        assert "ARCHITECTURE REMINDER" in text
        assert "cosine similarity" in text
        assert "stasis" in text.lower()

    def test_warm_boot_without_manifest_no_reminder(self):
        """Warm boot without manifest omits architecture reminder."""
        ctx = _make_context(manifest=None, stasis_duration_seconds=3600)
        svc = _make_service()
        text = svc.render_warm_boot_orientation(ctx)
        assert "ARCHITECTURE REMINDER" not in text

    def test_proactive_full_supplement_includes_manifest(self):
        """Full proactive supplement includes architecture note when manifest present."""
        from probos.cognitive.orientation import CognitiveArchitectureManifest
        ctx = _make_context(
            manifest=CognitiveArchitectureManifest(),
            agent_age_seconds=10,
        )
        svc = _make_service()
        text = svc._full_proactive_supplement(ctx)
        assert "cosine similarity" in text
        assert "stasis" in text.lower()

    def test_proactive_full_supplement_no_manifest(self):
        """Proactive supplement works without manifest."""
        ctx = _make_context(manifest=None, agent_age_seconds=10)
        svc = _make_service()
        text = svc._full_proactive_supplement(ctx)
        assert "ORIENTATION ACTIVE" in text
        assert "cosine similarity" not in text

    def test_render_manifest_section_empty_when_none(self):
        """render_manifest_section returns empty string for None manifest."""
        svc = _make_service()
        assert svc.render_manifest_section(None) == ""

    def test_render_manifest_section_covers_five_domains(self):
        """Manifest section covers Memory, Trust, Stasis, Cognition, Self-Regulation."""
        from probos.cognitive.orientation import CognitiveArchitectureManifest
        svc = _make_service()
        text = svc.render_manifest_section(CognitiveArchitectureManifest())
        assert "Memory:" in text
        assert "Trust:" in text
        assert "Stasis" in text
        assert "Cognition:" in text
        assert "Self-Regulation:" in text

    def test_manifest_confabulation_warning(self):
        """Manifest text warns about stasis confabulation specifically."""
        from probos.cognitive.orientation import CognitiveArchitectureManifest
        svc = _make_service()
        text = svc.render_manifest_section(CognitiveArchitectureManifest())
        assert "confabulation" in text.lower()
```

## Verification

```bash
# AD-587 tests only
python -m pytest tests/test_orientation.py -k "AD587" -v

# Full orientation test suite (regression)
python -m pytest tests/test_orientation.py -v

# Import check — verify no circular imports
python -c "from probos.cognitive.orientation import CognitiveArchitectureManifest; print('OK')"
```

## Files Modified (Summary)

| File | Change |
|------|--------|
| `src/probos/cognitive/orientation.py` | Add `CognitiveArchitectureManifest` dataclass, `manifest` field on `OrientationContext`, `build_manifest()` + `render_manifest_section()` on `OrientationService`, manifest integration into cold_start/warm_boot/proactive rendering |
| `tests/test_orientation.py` | Add `TestCognitiveArchitectureManifestAD587` class (~23 tests) |

**1 source file modified, 1 test file modified, ~23 tests added.**

## What This Does NOT Fix

- **Live telemetry grounding (AD-588):** This manifest is static architecture facts. AD-588 will add real-time metrics (current trust score, episode count, zone state) so agents can consult actual data for self-referential claims.
- **Confabulation detection (AD-589):** This manifest provides the ground truth; AD-589 will compare self-referential claims against the manifest and flag divergence.
- **Agent behavior changes:** The manifest doesn't prevent confabulation by rule — it provides accurate information that makes confabulation unnecessary. The LLM naturally prefers accurate detail (from context) over fabricated detail (from imagination) when both are available.
- **Existing orientation paths:** No changes to working orientation infrastructure — the manifest is additive.

## Tracking

- Issue #151 (Cognitive Architecture Manifest)
- Depends on: AD-567g (Orientation infrastructure — COMPLETE)
- Blocks: AD-588 (#152), AD-589 (#153)
