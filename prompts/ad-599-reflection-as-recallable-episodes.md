# AD-599: Reflection as Recallable Episodes — Dream Insight Promotion

**Issue:** #173 (AD-599)
**Status:** Ready for builder
**Priority:** Medium
**Depends:** AD-551 (Notebook Consolidation — complete), AD-567d (Anchor-Preserving Dream Consolidation — complete)
**Files:** `src/probos/cognitive/dreaming.py` (EDIT), `src/probos/types.py` (EDIT — DreamReport + MemorySource), `src/probos/config.py` (EDIT — DreamingConfig), `tests/test_ad599_reflection_episodes.py` (NEW)

## Problem

Dream consolidation (Steps 7–14) produces high-value analytical insights — notebook consolidation patterns, convergence reports, emergence metrics snapshots, behavioral analysis, activation lifecycle summaries. These insights are written to CognitiveJournal and Ship's Records but never enter the episodic recall pipeline. An agent that dreamed about a trust pattern last night cannot recall that insight when facing a similar situation today. The dream's value is locked in write-only storage.

AD-599 promotes dream consolidation insights into standalone `[Reflection]` episodes in EpisodicMemory, making them recallable via `recall_for_agent()` and `recall_weighted()` during future cognitive cycles.

**Cognitive science basis:** Park et al. (2023) Generative Agents — periodic reflections become first-class retrievable memories, enabling higher-level reasoning across time.

**What this does NOT include:**
- Modifying any existing dream step behavior (Steps 0–14 are unchanged)
- LLM-based summarization or synthesis (reflections use existing data, no LLM calls)
- Custom retrieval logic for reflection episodes (ChromaDB semantic search handles it naturally)
- Reflection-specific decay policy (subject to same AD-567d activation lifecycle as all episodes)

---

## Section 1: MemorySource Extension

**File:** `src/probos/types.py` (EDIT)

Add a new `REFLECTION` variant to the `MemorySource` enum. This distinguishes reflection episodes from experiential ones without requiring a separate type system.

Find the `MemorySource` enum (currently at line ~342) and add after the `BRIEFING` entry:

```python
class MemorySource(str, Enum):
    """Classification of how an episode entered an agent's memory (AD-541)."""
    DIRECT = "direct"            # Agent personally experienced this
    SECONDHAND = "secondhand"    # Heard about it in Ward Room / DM from another agent
    SHIP_RECORDS = "ship_records"  # Read from Ship's Records (AD-434, future)
    BRIEFING = "briefing"        # Received during onboarding (AD-486, future)
    REFLECTION = "reflection"    # AD-599: Synthesized from dream consolidation insights
```

---

## Section 2: DreamReport Extension

**File:** `src/probos/types.py` (EDIT)

Add reflection tracking fields to `DreamReport`. Find the `DreamReport` dataclass (currently at line ~464) and add after the `unfaithful_episodes` field (currently the last field):

```python
    # AD-599: Reflection episodes promoted from dream insights
    reflections_created: int = 0
```

---

## Section 3: DreamingConfig Extension

**File:** `src/probos/config.py` (EDIT)

Add configuration fields to `DreamingConfig`. Find the `DreamingConfig` class and add after the existing `prune_min_age_hours` field (or at the end of the dream config fields):

```python
    # AD-599: Reflection episode promotion
    reflection_enabled: bool = True
    reflection_max_per_cycle: int = 3        # Cap reflections per dream cycle to prevent flooding
    reflection_min_importance: int = 8       # Importance score for reflection episodes (1-10 scale)
```

---

## Section 4: Dream Step 15 — Reflection Episode Promotion

**File:** `src/probos/cognitive/dreaming.py` (EDIT)

**Current step sequence:** Steps 0–14 (Step 14 is Source Attribution Consolidation). The new step is **Step 15**.

### 4a: Update the `dream_cycle` docstring

Find the `dream_cycle` method docstring (starts around line 199) and add Step 15:

```python
    async def dream_cycle(self) -> DreamReport:
        """Execute one full dream pass.

        Steps:
        0. Flush un-consolidated episodes via micro_dream (composable)
        1. (removed — micro_dream owns incremental consolidation)
        2. Prune — decay all weights and remove below-threshold connections
        3. Trust consolidation — boost/penalize agents based on track records
        4. Pre-warm — identify temporal intent sequences for faster routing
        5. Idle scale-down
        6. Episode clustering (AD-531)
        7. Procedure extraction from success clusters (AD-532)
        8. Gap prediction
        9. Emergence metrics (AD-557)
        15. Reflection episode promotion (AD-599)
        """
```

**Note:** Do NOT renumber existing steps 10–14. Just add step 15 at the end of the docstring list.

### 4b: Add the Step 15 block

Insert **after** the Step 14 block (after line ~1187 `logger.debug("AD-568d: Dream step 14 (source attribution) failed")`) and **before** the `duration_ms = (time.monotonic() - t_start) * 1000` line:

```python
        # Step 15: Reflection Episode Promotion (AD-599)
        reflections_created = 0
        try:
            if self.config.reflection_enabled and self.episodic_memory:
                reflections_created = await self._step_15_reflection_promotion(
                    episodes=episodes,
                    clusters=clusters,
                    convergence_reports=convergence_reports,
                    emergence_capacity=emergence_capacity,
                    coordination_balance=coordination_balance,
                    notebook_consolidations=notebook_consolidations,
                    behavioral_quality_score=behavioral_quality_score,
                )
                if reflections_created:
                    logger.info(
                        "AD-599 Step 15: Created %d reflection episodes",
                        reflections_created,
                    )
        except Exception:
            logger.debug("AD-599 Step 15: Reflection promotion failed", exc_info=True)
```

### 4c: Add `reflections_created` to the DreamReport construction

Find the `report = DreamReport(` block (starts around line 1191) and add after the `unfaithful_episodes` line:

```python
            # AD-599: Reflection episodes
            reflections_created=reflections_created,
```

### 4d: Add the `_step_15_reflection_promotion` method

Add this method to the `DreamingEngine` class, after the existing `_step_14_source_attribution` method (which ends around line 2100–2130 area — find the end of that method).

```python
    async def _step_15_reflection_promotion(
        self,
        *,
        episodes: list,
        clusters: list,
        convergence_reports: list[dict],
        emergence_capacity: float | None,
        coordination_balance: float | None,
        notebook_consolidations: int,
        behavioral_quality_score: float | None,
    ) -> int:
        """AD-599: Promote dream consolidation insights into recallable episodes.

        Scans this dream cycle's outputs for high-value analytical insights and
        creates [Reflection] episodes in EpisodicMemory. These synthetic episodes
        are semantically rich and naturally score well on pattern/trend queries
        without custom retrieval logic.

        Returns the number of reflection episodes created.

        Rate limiting: max ``config.reflection_max_per_cycle`` per dream cycle.
        Deduplication: content-hash check against existing episodes (write-once
        guard in EpisodicMemory.store() handles collisions).
        """
        import hashlib
        import uuid

        from probos.types import AnchorFrame, Episode, MemorySource

        max_reflections = self.config.reflection_max_per_cycle
        importance = self.config.reflection_min_importance
        created = 0

        # Collect candidate reflection texts from this cycle's outputs.
        # Each candidate is (content_text, agent_ids_list).
        candidates: list[tuple[str, list[str]]] = []

        # Source 1: Convergence reports (Step 7g) — cross-agent analytical findings
        for conv in convergence_reports:
            agents = conv.get("agents", [])
            topic = conv.get("topic", "unknown")
            coherence = conv.get("coherence", 0.0)
            depts = conv.get("departments", [])
            text = (
                f"[Reflection] Convergence detected across {len(agents)} agents "
                f"in {len(depts)} departments on topic '{topic}' "
                f"(coherence={coherence:.3f}). "
                f"Agents: {', '.join(agents)}. "
                f"Departments: {', '.join(depts)}."
            )
            independence = conv.get("independence", "")
            if independence:
                text += f" Independence: {independence}."
            candidates.append((text, agents))

        # Source 2: Emergence metrics snapshot (Step 9)
        if emergence_capacity is not None:
            parts = [
                f"[Reflection] Dream cycle emergence snapshot: "
                f"capacity={emergence_capacity:.3f}",
            ]
            if coordination_balance is not None:
                parts.append(f"coordination_balance={coordination_balance:.3f}")
            if behavioral_quality_score is not None:
                parts.append(f"behavioral_quality={behavioral_quality_score:.3f}")
            text = ", ".join(parts) + "."
            # System-level insight — no specific agent
            candidates.append((text, []))

        # Source 3: Notebook consolidation summary (Step 7g)
        if notebook_consolidations > 0:
            text = (
                f"[Reflection] Dream consolidation merged {notebook_consolidations} "
                f"redundant notebook clusters. Knowledge base compacted."
            )
            candidates.append((text, []))

        # Source 4: Cluster-level patterns (Step 6) — only dominant clusters
        for cluster in clusters:
            if not hasattr(cluster, "episode_ids") or len(getattr(cluster, "episode_ids", [])) < 5:
                continue  # Only reflect on substantial clusters
            is_success = getattr(cluster, "is_success_dominant", False)
            is_failure = getattr(cluster, "is_failure_dominant", False)
            if not (is_success or is_failure):
                continue
            ep_count = len(cluster.episode_ids)
            label = "success" if is_success else "failure"
            # Extract agent participation from cluster episodes
            cluster_agents: list[str] = []
            for ep in episodes:
                if ep.id in cluster.episode_ids:
                    cluster_agents.extend(ep.agent_ids)
            cluster_agents = sorted(set(cluster_agents))
            text = (
                f"[Reflection] Identified {label}-dominant pattern cluster "
                f"with {ep_count} episodes. "
                f"Agents involved: {', '.join(cluster_agents[:5])}."
            )
            anchor_summary = getattr(cluster, "anchor_summary", None)
            if anchor_summary:
                text += f" Anchor context: {str(anchor_summary)[:200]}."
            candidates.append((text, cluster_agents[:5]))

        # Apply rate limit — take the first N candidates (convergence > emergence > notebook > clusters)
        candidates = candidates[:max_reflections]

        now = time.time()

        for content_text, agent_ids in candidates:
            # Deterministic ID from content hash — prevents duplicates across cycles
            content_hash = hashlib.sha256(content_text.encode()).hexdigest()[:16]
            episode_id = f"reflection-{content_hash}"

            # Build AnchorFrame with dream provenance
            anchors = AnchorFrame(
                trigger_type="dream_consolidation",
            )

            episode = Episode(
                id=episode_id,
                timestamp=now,
                user_input=content_text,
                dag_summary={"type": "reflection", "source": "dream_consolidation"},
                outcomes=[],
                reflection=content_text,
                agent_ids=agent_ids,
                duration_ms=0.0,
                source=MemorySource.REFLECTION,
                anchors=anchors,
                importance=importance,
            )

            try:
                await self.episodic_memory.store(episode)
                created += 1
            except Exception:
                logger.debug(
                    "AD-599: Failed to store reflection episode %s",
                    episode_id[:12],
                    exc_info=True,
                )

        return created
```

**Design notes:**

- **Deterministic IDs:** `reflection-{content_hash}` ensures that identical insights across dream cycles produce the same ID. The write-once guard in `EpisodicMemory.store()` silently skips duplicates. This is the dedup mechanism — no separate hash table needed.
- **Priority ordering:** Convergence reports first (cross-agent, highest analytical value), then emergence snapshots, then consolidation summaries, then cluster patterns. The `max_per_cycle` cap (default 3) prevents flooding.
- **`user_input` field:** Set to the reflection text because ChromaDB indexes this for semantic search via `_prepare_document()`. This is what makes reflections recallable by query.
- **`reflection` field:** Also set to the content text. This matches the Episode schema contract where `reflection` contains analytical summary.
- **No LLM calls:** All content is composed from structured data already computed by earlier steps. Zero additional latency or cost.
- **`MemorySource.REFLECTION`:** Enables downstream filtering (e.g., exclude reflections from certain analyses) without breaking existing recall paths.

---

## Section 5: Tests

**File:** `tests/test_ad599_reflection_episodes.py` (NEW)

### Test infrastructure

Create a minimal stub for `DreamingEngine` dependencies:

```python
"""AD-599: Reflection as Recallable Episodes — Dream Insight Promotion tests."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.config import DreamingConfig
from probos.types import DreamReport, Episode, MemorySource
```

For the `DreamingEngine`, construct with minimal required params:
- `router` = `MagicMock()` (HebbianRouter stub)
- `trust_network` = `MagicMock()` (TrustNetwork stub)
- `episodic_memory` = `AsyncMock()` with `store = AsyncMock()`, `recent = AsyncMock(return_value=[])`, `get_embeddings = AsyncMock(return_value={})`
- `config` = `DreamingConfig()` (defaults)

For cluster objects, use a simple `types.SimpleNamespace` with `episode_ids`, `is_success_dominant`, `is_failure_dominant`, `anchor_summary` attributes.

### Test categories (18 tests):

**MemorySource enum (1 test):**
1. `test_memory_source_reflection_exists` — `MemorySource.REFLECTION` exists and equals `"reflection"`.

**DreamReport field (1 test):**
2. `test_dream_report_reflections_created_default` — `DreamReport().reflections_created == 0`.

**Config fields (2 tests):**
3. `test_config_reflection_enabled_default` — `DreamingConfig().reflection_enabled is True`.
4. `test_config_reflection_max_per_cycle_default` — `DreamingConfig().reflection_max_per_cycle == 3`.

**Step 15 — convergence reflections (3 tests):**
5. `test_step15_convergence_report_creates_reflection` — Pass one convergence report `{"agents": ["a1", "a2"], "departments": ["science", "engineering"], "topic": "latency", "coherence": 0.85}` → `episodic_memory.store` called once. Verify the stored Episode has `source == MemorySource.REFLECTION`, `importance == 8`, `user_input` starts with `"[Reflection]"`, `agent_ids == ["a1", "a2"]`.
6. `test_step15_convergence_with_independence` — Convergence report with `"independence": "low"` → stored episode content contains `"Independence: low"`.
7. `test_step15_multiple_convergence_reports` — 2 convergence reports → 2 store calls (within default max of 3).

**Step 15 — emergence reflections (2 tests):**
8. `test_step15_emergence_snapshot_creates_reflection` — Pass `emergence_capacity=0.75, coordination_balance=0.60` with no convergence reports → store called once. Content contains `"capacity=0.750"` and `"coordination_balance=0.600"`.
9. `test_step15_emergence_with_behavioral` — Pass emergence + `behavioral_quality_score=0.82` → content contains `"behavioral_quality=0.820"`.

**Step 15 — notebook consolidation reflections (1 test):**
10. `test_step15_notebook_consolidation_creates_reflection` — Pass `notebook_consolidations=5` → content contains `"merged 5 redundant notebook clusters"`.

**Step 15 — cluster pattern reflections (2 tests):**
11. `test_step15_success_cluster_creates_reflection` — Pass a cluster with `is_success_dominant=True`, 6 `episode_ids`, and matching episodes in the `episodes` list → content contains `"success-dominant pattern cluster"` and `"6 episodes"`.
12. `test_step15_small_cluster_skipped` — Cluster with only 3 `episode_ids` → no reflection created for it (below the 5-episode threshold).

**Step 15 — rate limiting (2 tests):**
13. `test_step15_respects_max_per_cycle` — Set `config.reflection_max_per_cycle = 2`, pass 4 convergence reports → only 2 store calls.
14. `test_step15_disabled_creates_none` — Set `config.reflection_enabled = False` → step returns 0, no store calls.

**Step 15 — deduplication (1 test):**
15. `test_step15_deterministic_ids` — Call step twice with identical convergence report → both store calls use the same episode ID (starts with `"reflection-"`). The write-once guard in `EpisodicMemory.store` would handle the dedup; this test only verifies the ID is deterministic.

**Step 15 — error handling (2 tests):**
16. `test_step15_store_failure_degrades` — Patch `episodic_memory.store` to raise `Exception` → method returns 0 (not propagated), no crash.
17. `test_step15_empty_inputs_returns_zero` — Call with empty clusters, empty convergence_reports, `emergence_capacity=None` → returns 0, no store calls.

**Integration — DreamReport wiring (1 test):**
18. `test_dream_cycle_includes_reflections_created` — Run a full `dream_cycle()` with `episodic_memory.recent` returning at least 1 episode. Verify the returned `DreamReport` has `reflections_created` field (may be 0 if no insights were generated, but field must exist and be an int).

**Important test patterns:**
- All tests that call `_step_15_reflection_promotion` directly should create a `DreamingEngine` with a `DreamingConfig(reflection_enabled=True)` and a mock `episodic_memory` with `store = AsyncMock()`.
- Verify episode properties by inspecting `episodic_memory.store.call_args_list` — each call's first positional arg is the `Episode` object.
- For the full `dream_cycle` test (test 18): mock `episodic_memory.recent` to return a minimal episode list, mock `get_embeddings` to return `{}`, mock `trust_network.raw_scores()` to return `{}`. The dream cycle should complete without errors. Check `report.reflections_created` is an `int`.

---

## Engineering Principles Compliance

- **SOLID/S** — Step 15 is a pure side-effect step. It reads from earlier steps' outputs and writes to episodic memory. It does not modify any prior step's behavior or output.
- **SOLID/O** — New MemorySource variant extends the enum without modifying existing values. New DreamReport field has a default (0) so existing consumers are unaffected.
- **Fail Fast** — Step 15 is wrapped in `try/except` at the call site (log-and-degrade). Individual episode store failures are caught inside the loop. Dream cycle never fails because of reflection promotion.
- **DRY** — Reuses existing `EpisodicMemory.store()` with its write-once guard, importance scoring, and eviction. No custom dedup logic — deterministic IDs + write-once = dedup for free.
- **Law of Demeter** — Step 15 receives all inputs as method parameters (clusters, convergence_reports, emergence metrics). It does not reach into other steps' internal state or private attributes.

---

## Tracker Updates

After all tests pass:

1. **PROGRESS.md** — Add entry:
   ```
   | AD-599 | Reflection as Recallable Episodes | Dream Step 15 promotes consolidation insights to [Reflection] episodes in EpisodicMemory. MemorySource.REFLECTION. Rate-limited, deduped via deterministic IDs. 18 tests. | CLOSED |
   ```

2. **docs/development/roadmap.md** — Update the AD-599 entry status from `planned` to `complete`.

3. **DECISIONS.md** — Add entry:
   ```
   ## AD-599: Reflection as Recallable Episodes — Dream Insight Promotion

   **Decision:** Dream Step 15 promotes consolidation insights (convergence reports, emergence snapshots, notebook consolidations, dominant cluster patterns) into [Reflection] episodes stored in EpisodicMemory. Episodes use MemorySource.REFLECTION source tag and importance 8 (distilled wisdom). Deterministic content-hash IDs prevent cross-cycle duplication via existing write-once guard.

   **Rationale:** Dream consolidation produces high-value analytical insights locked in write-only storage (CognitiveJournal, Ship's Records). Promoting them to episodic memory makes them recallable during future cognitive cycles. No LLM calls — reflections are composed from structured data already computed by Steps 7–14. Rate-limited to 3 per cycle to prevent episodic memory flooding.

   **Alternative considered:** LLM-synthesized reflections (richer language, more nuanced). Rejected — adds latency, cost, and non-determinism to a side-effect step. Structured composition is sufficient because ChromaDB semantic search handles fuzzy matching.
   ```
