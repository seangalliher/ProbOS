# AD-609: Multi-Faceted Distillation — Failure & Comparative Analysis

**Status:** Ready for builder
**Scope:** New file + integration edits (~250 lines new, ~40 lines edits)
**Depends on:** AD-531 (episode clustering), AD-532c (negative procedures)

**Acceptance Criteria:**
- All 10 tests pass
- No new lint errors
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`

## Summary

Dream consolidation (AD-532) extracts procedures from success-dominant clusters and negative procedures from failure-dominant clusters (AD-532c). However, the failure analysis is shallow — it extracts a negative procedure but does not analyze _why_ the failure pattern occurs. There is also no comparative analysis between success and failure clusters on the same intent type.

This AD adds a `FailureDistiller` that:
1. Extracts structured failure signals from failure-dominant clusters (common departments, low-trust agents, trigger types).
2. Compares success and failure clusters sharing the same intent_type to identify differentiating factors.
3. Records results in DreamReport for observability.

No LLM dependency — analysis is purely structural (metadata from cluster fields).

## Architecture

```
DreamingEngine Step 7 (after procedure extraction)
    │
    ├── Success clusters → procedure extraction (existing AD-532)
    ├── Failure clusters → negative procedure extraction (existing AD-532c)
    │
    ▼
FailureDistiller.distill_failure_patterns(failure_clusters)
    ├── For each failure-dominant cluster:
    │   ├── Extract common departments from anchor_summary
    │   ├── Extract common intent_types
    │   ├── Extract participating_agents
    │   └── Build Procedure with is_negative=True, enriched description
    │
    ▼
FailureDistiller.distill_comparative(success_clusters, failure_clusters)
    ├── Group clusters by intent_type
    ├── For each intent_type with both success and failure clusters:
    │   ├── Compare agent counts, success_rates, variances
    │   └── Identify differentiating factors
    │
    ▼
DreamReport: failure_patterns_extracted, comparative_insights
```

---

## File Changes

| File | Change |
|------|--------|
| `src/probos/cognitive/failure_distiller.py` | **NEW** — FailureDistiller, ComparativeInsight |
| `src/probos/config.py` | Add DistillationConfig + wire into SystemConfig |
| `src/probos/types.py` | Add `failure_patterns_extracted` and `comparative_insights` to DreamReport |
| `src/probos/cognitive/dreaming.py` | After Step 7c, run failure distillation and comparative analysis |
| `tests/test_ad609_distillation.py` | **NEW** — 10 tests |

---

## Implementation

### Section 1: DistillationConfig

**File:** `src/probos/config.py`

Add a new Pydantic config model. Place it after `ThoughtStoreConfig` (or after the last cognitive config):

```python
class DistillationConfig(BaseModel):
    """AD-609: Multi-faceted distillation configuration."""

    enabled: bool = True
    min_failure_cluster_size: int = 3
    comparative_enabled: bool = True
```

Wire into `SystemConfig`:

```python
    distillation: DistillationConfig = DistillationConfig()  # AD-609
```

### Section 2: DreamReport Fields

**File:** `src/probos/types.py`

Add two new fields to the `DreamReport` dataclass. Find the end of the existing fields (search for the last field before the class ends or before methods begin) and add:

```python
    # AD-609: Multi-faceted distillation
    failure_patterns_extracted: int = 0
    comparative_insights: int = 0
```

**Builder:** Place these after the existing `negative_procedures_extracted` field or at the end of the dataclass fields. Follow the existing style of field comments.

### Section 3: FailureDistiller

**File:** `src/probos/cognitive/failure_distiller.py` (NEW)

```python
"""AD-609: Multi-Faceted Distillation — Failure & Comparative Analysis.

Structural analysis of failure-dominant clusters and comparison against
success clusters on the same intent types. No LLM dependency — all
analysis is derived from cluster metadata fields.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ComparativeInsight:
    """Result of comparing success and failure clusters on the same intent."""

    intent_type: str
    success_pattern: str
    failure_pattern: str
    differentiating_factor: str
    confidence: float


class FailureDistiller:
    """Extracts structured failure patterns and comparative insights.

    Parameters
    ----------
    config : DistillationConfig-like or None
        Configuration. If None, uses hardcoded defaults.
    procedure_store : ProcedureStore or None
        For persisting failure-derived procedures.
    """

    def __init__(
        self,
        config: Any = None,
        procedure_store: Any = None,
    ) -> None:
        if config is not None:
            self._min_cluster_size: int = config.min_failure_cluster_size
            self._comparative_enabled: bool = config.comparative_enabled
        else:
            self._min_cluster_size = 3
            self._comparative_enabled = True

        self._procedure_store = procedure_store

    def distill_failure_patterns(
        self,
        clusters: list[Any],
    ) -> list[Any]:
        """Extract structured failure patterns from failure-dominant clusters.

        For each failure-dominant cluster with sufficient size, extracts
        common failure signals (departments, intent types, agents) and
        builds a negative Procedure with enriched description.

        Parameters
        ----------
        clusters : list[EpisodeCluster]
            All clusters from the dream cycle (filtered internally).

        Returns
        -------
        list[Procedure]
            Negative procedures with enriched failure descriptions.
        """
        from probos.cognitive.procedures import Procedure, ProcedureStep

        results: list[Any] = []
        for cluster in clusters:
            if not getattr(cluster, 'is_failure_dominant', False):
                continue
            if getattr(cluster, 'episode_count', 0) < self._min_cluster_size:
                continue

            signals = self._extract_failure_signals(cluster)
            intent_types = getattr(cluster, 'intent_types', [])
            if not intent_types:
                continue

            # Build enriched description from failure signals
            description_parts = [
                f"Failure pattern on intent(s): {', '.join(intent_types)}.",
            ]
            if signals.get("departments"):
                description_parts.append(
                    f"Commonly involves department(s): {', '.join(signals['departments'])}."
                )
            if signals.get("agent_count", 0) > 0:
                description_parts.append(
                    f"Involves {signals['agent_count']} participating agent(s)."
                )
            if signals.get("trigger_types"):
                description_parts.append(
                    f"Common trigger type(s): {', '.join(signals['trigger_types'])}."
                )
            description_parts.append(
                f"Failure rate: {(1 - getattr(cluster, 'success_rate', 0.5)):.0%} "
                f"across {getattr(cluster, 'episode_count', 0)} episodes."
            )

            procedure = Procedure(
                id=uuid.uuid4().hex,
                name=f"Failure: {intent_types[0]}" if intent_types else "Failure pattern",
                description=" ".join(description_parts),
                intent_types=list(intent_types),
                origin_cluster_id=getattr(cluster, 'cluster_id', ''),
                origin_agent_ids=list(getattr(cluster, 'participating_agents', [])),
                extraction_date=time.time(),
                is_negative=True,
                steps=[ProcedureStep(
                    action=f"Avoid: {intent_types[0] if intent_types else 'unknown'}",
                    description=" ".join(description_parts),
                )],
            )
            results.append(procedure)

            logger.debug(
                "AD-609: Extracted failure pattern from cluster %s — %s",
                getattr(cluster, 'cluster_id', '')[:8],
                procedure.name,
            )

        return results

    def distill_comparative(
        self,
        success_clusters: list[Any],
        failure_clusters: list[Any],
    ) -> list[ComparativeInsight]:
        """Compare success and failure clusters on the same intent types.

        Groups clusters by intent_type, then compares metadata between
        success-dominant and failure-dominant groups to identify what
        differentiates success from failure.

        Parameters
        ----------
        success_clusters : list[EpisodeCluster]
            Success-dominant clusters.
        failure_clusters : list[EpisodeCluster]
            Failure-dominant clusters.

        Returns
        -------
        list[ComparativeInsight]
            Insights about what differs between success and failure.
        """
        if not self._comparative_enabled:
            return []

        if not success_clusters or not failure_clusters:
            return []

        # Group by intent type
        success_by_intent: dict[str, list[Any]] = {}
        for cluster in success_clusters:
            for intent in getattr(cluster, 'intent_types', []):
                success_by_intent.setdefault(intent, []).append(cluster)

        failure_by_intent: dict[str, list[Any]] = {}
        for cluster in failure_clusters:
            for intent in getattr(cluster, 'intent_types', []):
                failure_by_intent.setdefault(intent, []).append(cluster)

        # Find overlapping intents
        shared_intents = set(success_by_intent.keys()) & set(failure_by_intent.keys())

        insights: list[ComparativeInsight] = []
        for intent in shared_intents:
            s_clusters = success_by_intent[intent]
            f_clusters = failure_by_intent[intent]

            # Compare metrics
            s_signals = self._aggregate_signals(s_clusters)
            f_signals = self._aggregate_signals(f_clusters)

            # Identify differentiating factors
            differentiators: list[str] = []

            # Agent count difference
            if s_signals["avg_agent_count"] != f_signals["avg_agent_count"]:
                if s_signals["avg_agent_count"] > f_signals["avg_agent_count"]:
                    differentiators.append(
                        f"Success involves more agents ({s_signals['avg_agent_count']:.1f} vs {f_signals['avg_agent_count']:.1f})"
                    )
                else:
                    differentiators.append(
                        f"Failure involves more agents ({f_signals['avg_agent_count']:.1f} vs {s_signals['avg_agent_count']:.1f})"
                    )

            # Department difference
            s_depts = set(s_signals.get("departments", []))
            f_depts = set(f_signals.get("departments", []))
            unique_to_failure = f_depts - s_depts
            if unique_to_failure:
                differentiators.append(
                    f"Failure-specific departments: {', '.join(unique_to_failure)}"
                )

            # Cluster variance (tightness)
            if s_signals["avg_variance"] < f_signals["avg_variance"]:
                differentiators.append(
                    f"Success clusters are tighter (variance {s_signals['avg_variance']:.3f} vs {f_signals['avg_variance']:.3f})"
                )

            if not differentiators:
                differentiators.append("No clear structural differentiator found")

            # Success pattern summary
            s_ep_count = sum(getattr(c, 'episode_count', 0) for c in s_clusters)
            f_ep_count = sum(getattr(c, 'episode_count', 0) for c in f_clusters)

            insight = ComparativeInsight(
                intent_type=intent,
                success_pattern=f"{len(s_clusters)} success cluster(s), {s_ep_count} episodes",
                failure_pattern=f"{len(f_clusters)} failure cluster(s), {f_ep_count} episodes",
                differentiating_factor="; ".join(differentiators),
                confidence=min(s_ep_count, f_ep_count) / max(s_ep_count + f_ep_count, 1),
            )
            insights.append(insight)

            logger.debug(
                "AD-609: Comparative insight for '%s' — %s",
                intent, insight.differentiating_factor[:80],
            )

        return insights

    def _extract_failure_signals(self, cluster: Any) -> dict[str, Any]:
        """Extract common failure indicators from a cluster.

        Parameters
        ----------
        cluster : EpisodeCluster
            A failure-dominant cluster.

        Returns
        -------
        dict
            Extracted signals: departments, agent_count, trigger_types.
        """
        anchor_summary = getattr(cluster, 'anchor_summary', {}) or {}
        return {
            "departments": anchor_summary.get("departments", []),
            "trigger_types": anchor_summary.get("trigger_types", []),
            "agent_count": len(getattr(cluster, 'participating_agents', [])),
            "episode_count": getattr(cluster, 'episode_count', 0),
            "success_rate": getattr(cluster, 'success_rate', 0.0),
        }

    def _aggregate_signals(self, clusters: list[Any]) -> dict[str, Any]:
        """Aggregate signals across multiple clusters.

        Parameters
        ----------
        clusters : list[EpisodeCluster]
            Clusters to aggregate.

        Returns
        -------
        dict
            Aggregated signals.
        """
        all_departments: list[str] = []
        total_agents = 0
        total_variance = 0.0
        for cluster in clusters:
            summary = getattr(cluster, 'anchor_summary', {}) or {}
            all_departments.extend(summary.get("departments", []))
            total_agents += len(getattr(cluster, 'participating_agents', []))
            total_variance += getattr(cluster, 'variance', 0.0)

        n = max(len(clusters), 1)
        return {
            "departments": list(set(all_departments)),
            "avg_agent_count": total_agents / n,
            "avg_variance": total_variance / n,
        }
```

### Section 4: DreamingEngine Integration

**File:** `src/probos/cognitive/dreaming.py`

#### 4a: Constructor parameter

Add an optional `failure_distiller` parameter to `DreamingEngine.__init__()`:

```python
        failure_distiller: Any = None,  # AD-609: failure & comparative analysis
```

Store it:

```python
        self._failure_distiller = failure_distiller
```

#### 4b: Dream cycle integration

After Step 7c (negative procedure extraction, around line 534) and before Step 7d, add:

```python
        # Step 7c-2: Failure distillation & comparative analysis (AD-609)
        failure_patterns_extracted = 0
        comparative_insights_count = 0
        if self._failure_distiller and clusters:
            try:
                # Separate success and failure clusters
                success_clusters = [c for c in clusters if c.is_success_dominant]
                failure_clusters_list = [c for c in clusters if c.is_failure_dominant]

                # Distill failure patterns
                failure_procedures = self._failure_distiller.distill_failure_patterns(
                    failure_clusters_list
                )
                failure_patterns_extracted = len(failure_procedures)
                if failure_procedures:
                    procedures.extend(failure_procedures)
                    # Persist if store available
                    if self._procedure_store:
                        for fp in failure_procedures:
                            try:
                                await self._procedure_store.save(fp)
                            except Exception:
                                logger.debug("AD-609: Failed to persist failure procedure", exc_info=True)

                # Comparative analysis
                comparative_results = self._failure_distiller.distill_comparative(
                    success_clusters, failure_clusters_list
                )
                comparative_insights_count = len(comparative_results)

                if failure_patterns_extracted or comparative_insights_count:
                    logger.debug(
                        "Step 7c-2: Distilled %d failure patterns, %d comparative insights",
                        failure_patterns_extracted, comparative_insights_count,
                    )
            except Exception:
                logger.debug("Step 7c-2 failure distillation failed (non-critical)", exc_info=True)
```

#### 4c: DreamReport update

In the DreamReport construction (around line 1270), add the new fields:

```python
            failure_patterns_extracted=failure_patterns_extracted,  # AD-609
            comparative_insights=comparative_insights_count,  # AD-609
```

### Section 5: Startup Wiring

**File:** `src/probos/startup/dreaming.py`

#### 5a: Create FailureDistiller and pass to DreamingEngine

Before the `DreamingEngine` constructor call, add:

```python
    # AD-609: Failure distiller
    failure_distiller = None
    if config.distillation.enabled:
        try:
            from probos.cognitive.failure_distiller import FailureDistiller as _FailureDistiller
            failure_distiller = _FailureDistiller(
                config=config.distillation,
                procedure_store=procedure_store,
            )
            logger.info("AD-609: FailureDistiller initialized")
        except Exception as e:
            logger.warning("AD-609: FailureDistiller failed to start: %s — continuing without", e)
```

Update the `DreamingEngine` constructor call to include:

```python
            failure_distiller=failure_distiller,  # AD-609
```

---

## Tests

**File:** `tests/test_ad609_distillation.py` (NEW)

### Test List

| # | Test Name | What It Verifies |
|---|-----------|------------------|
| 1 | `test_distill_failure_patterns` | Extracts negative procedures from failure-dominant clusters |
| 2 | `test_extract_failure_signals` | _extract_failure_signals returns correct departments, agents, triggers |
| 3 | `test_negative_procedure_fields` | Output procedures have is_negative=True, correct intent_types |
| 4 | `test_comparative_insight_same_intent` | Compares success/failure clusters sharing an intent |
| 5 | `test_comparative_differentiating_factor` | Identifies agent count or department differences |
| 6 | `test_min_cluster_size_filter` | Clusters below min_failure_cluster_size are skipped |
| 7 | `test_config_disabled` | When enabled=False, distiller is not created |
| 8 | `test_dream_report_fields` | DreamReport has failure_patterns_extracted and comparative_insights fields |
| 9 | `test_no_failure_clusters` | Empty failure cluster list returns empty results |
| 10 | `test_comparative_no_shared_intents` | No shared intents between success/failure returns empty insights |

### Test Stubs

```python
import pytest
from dataclasses import dataclass, field

from probos.cognitive.failure_distiller import FailureDistiller, ComparativeInsight
from probos.types import DreamReport


@dataclass
class _FakeCluster:
    cluster_id: str = "c1"
    intent_types: list[str] = field(default_factory=lambda: ["code_review"])
    success_rate: float = 0.2
    episode_count: int = 5
    is_success_dominant: bool = False
    is_failure_dominant: bool = True
    participating_agents: list[str] = field(default_factory=lambda: ["agent-1", "agent-2"])
    variance: float = 0.3
    anchor_summary: dict = field(default_factory=lambda: {
        "departments": ["engineering"],
        "trigger_types": ["ward_room_notification"],
    })


@dataclass
class _FakeSuccessCluster:
    cluster_id: str = "s1"
    intent_types: list[str] = field(default_factory=lambda: ["code_review"])
    success_rate: float = 0.9
    episode_count: int = 8
    is_success_dominant: bool = True
    is_failure_dominant: bool = False
    participating_agents: list[str] = field(default_factory=lambda: ["agent-1", "agent-2", "agent-3"])
    variance: float = 0.1
    anchor_summary: dict = field(default_factory=lambda: {
        "departments": ["engineering", "science"],
        "trigger_types": ["direct_message"],
    })


@pytest.fixture
def distiller():
    return FailureDistiller()
```

---

## Targeted Test Commands

After Section 1-2 (Config + DreamReport):
```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad609_distillation.py -v -k "config or dream_report"
```

After Section 3 (FailureDistiller):
```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad609_distillation.py -v
```

After Section 4-5 (DreamingEngine + Startup):
```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad609_distillation.py -v
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_dreaming.py -v -x
```

Full suite (after all sections complete):
```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q
```

---

## Tracking

After all tests pass:

- **PROGRESS.md:** Add line `AD-609 Multi-Faceted Distillation — CLOSED`
- **docs/development/roadmap.md:** Update the AD-609 row status to `Complete`
- **DECISIONS.md:** Add entry:
  ```
  AD-609: Multi-Faceted Distillation. FailureDistiller extracts structured
  failure signals (departments, agents, triggers) from failure-dominant
  clusters and builds enriched negative procedures. Comparative analysis
  identifies differentiating factors between success and failure clusters
  on shared intents. No LLM dependency — purely structural metadata analysis.
  Results tracked in DreamReport.
  ```

---

## Scope Boundaries

**DO:**
- Create `failure_distiller.py` with FailureDistiller, ComparativeInsight.
- Add DistillationConfig to config.py and wire into SystemConfig.
- Add `failure_patterns_extracted` and `comparative_insights` to DreamReport.
- Wire into DreamingEngine after Step 7c.
- Wire into startup/dreaming.py.
- Write all 10 tests.

**DO NOT:**
- Use LLM-based failure analysis (structural metadata only).
- Determine root causes (that requires deeper causal reasoning).
- Generate automated remediation suggestions.
- Modify existing negative procedure extraction (Step 7c stays as-is).
- Change the procedure extraction flow for success clusters.
- Modify existing tests.
- Add API endpoints or HXI dashboard panels.
- Add numpy, scipy, or other heavy dependencies.
