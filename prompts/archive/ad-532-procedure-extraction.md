# AD-532: Procedure Extraction (Dream Consolidation — CAPTURED Type)

**Context:** AD-531 (CLOSED) produces `EpisodeCluster` objects during dream cycles. Success-dominant clusters (>80% success rate, ≥3 episodes) represent repeated patterns where agents reliably solved a class of problem. The "how" — the actual steps — is currently lost. AD-532 extracts deterministic procedures from these success clusters using an LLM during the dream cycle. This is the first LLM call in the dreaming pipeline.

**Problem:** Dream consolidation identifies *that* agent X succeeded at task Y (via Hebbian weights), but not *how*. The crew re-invokes the LLM for every repeat task. AD-534 (Replay-First Dispatch) needs procedures to replay — this AD produces them.

**Scope (slim):** This AD covers only:
- **Trigger 1: Dream consolidation (reflective)** — extract from success clusters during `dream_cycle()`.
- **Evolution type: CAPTURED only** — extract novel patterns. No FIX/DERIVED yet.
- **In-memory storage** — `DreamingEngine._last_procedures`. AD-533 adds persistence.
- **Log-and-degrade** — LLM failure does not break dream cycles.

**Deferred (tracked as separate ADs):**
- AD-532b: FIX/DERIVED evolution types (requires AD-533 persistent store)
- AD-532c: Negative procedure extraction from failure clusters
- AD-532d: Multi-agent compound procedures
- AD-532e: Reactive & proactive extraction triggers + LLM confirmation gates

**Principles:** SOLID (new module, single responsibility), DRY (reuse EpisodeCluster fields), Law of Demeter (access episodes through cluster, not episodic_memory directly), Fail Fast (log-and-degrade — extraction failure does not break dreams), AD-541b (READ-ONLY episode framing for LLM calls).

---

## Part 0: Wire `llm_client` into DreamingEngine

The DreamingEngine currently has no LLM client. AD-532 introduces the first LLM call in the dream pipeline. Thread `llm_client` through the construction chain.

### File: `src/probos/cognitive/dreaming.py`

**Add `llm_client` parameter to `__init__()`** (currently line 31):

Before:
```python
def __init__(
    self,
    router: HebbianRouter,
    trust_network: TrustNetwork,
    episodic_memory: Any,
    config: DreamingConfig,
    idle_scale_down_fn: Any = None,
    gap_prediction_fn: Any = None,
    contradiction_resolve_fn: Any = None,  # AD-403
) -> None:
```

After:
```python
def __init__(
    self,
    router: HebbianRouter,
    trust_network: TrustNetwork,
    episodic_memory: Any,
    config: DreamingConfig,
    idle_scale_down_fn: Any = None,
    gap_prediction_fn: Any = None,
    contradiction_resolve_fn: Any = None,  # AD-403
    llm_client: Any = None,  # AD-532: procedure extraction
) -> None:
```

Store it:
```python
self._llm_client = llm_client  # AD-532: for procedure extraction
self._last_procedures: list[Any] = []  # AD-532: most recent extracted procedures
self._extracted_cluster_ids: set[str] = set()  # AD-532: already-processed clusters
```

Add a property (after `last_clusters` property):
```python
@property
def last_procedures(self) -> list[Any]:
    """Most recent procedures extracted from the last dream cycle (AD-532)."""
    return self._last_procedures
```

### File: `src/probos/startup/dreaming.py`

**Add `llm_client` parameter to `init_dreaming()`** (currently line 28):

Add to the keyword-only parameters (after `emit_event_fn`):
```python
llm_client: Any = None,  # AD-532: procedure extraction
```

**Pass to DreamingEngine constructor** (currently line 60-72):

Add to the `DreamingEngine(...)` call:
```python
llm_client=llm_client,
```

### File: `src/probos/runtime.py`

Find the `init_dreaming(...)` call and add the `llm_client` argument:
```python
llm_client=self.llm_client,
```

Search for `init_dreaming(` to find the exact call site. It should be in the startup sequence that builds `DreamingResult`.

### Tests

Add a test that verifies `DreamingEngine.__init__` accepts and stores `llm_client`:
```python
def test_dreaming_engine_accepts_llm_client():
    """AD-532: DreamingEngine stores llm_client for procedure extraction."""
    from probos.cognitive.dreaming import DreamingEngine
    # ... create with llm_client=mock_client
    # assert engine._llm_client is mock_client
```

---

## Part 1: Procedure & ProcedureStep Schema

### New file: `src/probos/cognitive/procedures.py`

Create the procedure data model. This is the canonical schema consumed by AD-533 (store) and AD-534 (replay).

```python
"""AD-532: Procedure data model — deterministic step sequences extracted from experience.

A Procedure is the "how" — the specific ordered steps an agent used to solve
a class of problem successfully. Extracted from success-dominant EpisodeClusters
during dream consolidation (AD-531 → AD-532).

Consumed by:
- AD-533: Procedure Store (persistence)
- AD-534: Replay-First Dispatch (execution)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProcedureStep:
    """A single step in a deterministic procedure.

    Each step represents one action the agent took, with pre/postconditions
    that must hold for safe execution.
    """

    step_number: int  # 1-based ordinal
    action: str  # what to do (natural language description)
    expected_input: str = ""  # what state should look like before this step
    expected_output: str = ""  # what state should look like after this step
    fallback_action: str = ""  # what to do if this step fails
    invariants: list[str] = field(default_factory=list)  # must remain true during step

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_number": self.step_number,
            "action": self.action,
            "expected_input": self.expected_input,
            "expected_output": self.expected_output,
            "fallback_action": self.fallback_action,
            "invariants": self.invariants,
        }


@dataclass
class Procedure:
    """A deterministic procedure extracted from a success-dominant episode cluster.

    Represents the "compiled" solution to a recurring task type. Can be
    replayed without LLM involvement once validated (AD-534).
    """

    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    name: str = ""  # human-readable label (e.g., "Handle code review request")
    description: str = ""  # what this procedure accomplishes
    steps: list[ProcedureStep] = field(default_factory=list)
    preconditions: list[str] = field(default_factory=list)  # must be true before execution
    postconditions: list[str] = field(default_factory=list)  # must be true after execution
    intent_types: list[str] = field(default_factory=list)  # intent types this handles
    origin_cluster_id: str = ""  # EpisodeCluster.cluster_id that spawned this
    origin_agent_ids: list[str] = field(default_factory=list)  # agents in the cluster
    provenance: list[str] = field(default_factory=list)  # episode IDs this was derived from
    extraction_date: float = 0.0  # timestamp of extraction
    evolution_type: str = "CAPTURED"  # CAPTURED | FIX | DERIVED (only CAPTURED in AD-532)
    compilation_level: int = 1  # Dreyfus level (AD-535): 1=Novice
    success_count: int = 0  # incremented by AD-534 replay
    failure_count: int = 0  # incremented by AD-534 replay failure

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "steps": [s.to_dict() for s in self.steps],
            "preconditions": self.preconditions,
            "postconditions": self.postconditions,
            "intent_types": self.intent_types,
            "origin_cluster_id": self.origin_cluster_id,
            "origin_agent_ids": self.origin_agent_ids,
            "provenance": self.provenance,
            "extraction_date": self.extraction_date,
            "evolution_type": self.evolution_type,
            "compilation_level": self.compilation_level,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
        }
```

### Tests (~8 tests)

- `test_procedure_step_creation` — create ProcedureStep, verify fields
- `test_procedure_step_to_dict` — roundtrip serialization
- `test_procedure_creation` — create Procedure with defaults
- `test_procedure_with_steps` — create with populated steps list
- `test_procedure_to_dict` — full serialization including nested steps
- `test_procedure_to_dict_includes_all_fields` — no field lost
- `test_procedure_default_evolution_type` — verify "CAPTURED" default
- `test_procedure_default_compilation_level` — verify 1 (Novice)

---

## Part 2: `extract_procedure_from_cluster()` — LLM-Assisted Extraction

### File: `src/probos/cognitive/procedures.py` (append)

Add the extraction function after the dataclasses.

```python
import json
import logging
import time

logger = logging.getLogger(__name__)


async def extract_procedure_from_cluster(
    cluster: Any,  # EpisodeCluster
    episodes: list[Any],  # Episode objects in this cluster
    llm_client: Any,  # BaseLLMClient
) -> Procedure | None:
    """Extract a deterministic procedure from a success-dominant episode cluster.

    Uses AD-541b READ-ONLY episode framing to prevent the LLM from
    modifying or fabricating episode content.

    Returns None if extraction fails (log-and-degrade).
    """
```

**Build the extraction prompt.** Important: use AD-541b `=== READ-ONLY EPISODE ===` framing.

The system prompt should instruct the LLM:
```
You are a procedure extraction engine. You analyze successful execution episodes
and extract the common deterministic procedure — the specific steps that were
taken, in order, to achieve the outcome.

Output ONLY valid JSON matching this schema:
{
  "name": "short human-readable label",
  "description": "what this procedure accomplishes",
  "steps": [
    {
      "step_number": 1,
      "action": "what to do",
      "expected_input": "state before this step",
      "expected_output": "state after this step",
      "fallback_action": "what to do if this step fails",
      "invariants": ["what must remain true"]
    }
  ],
  "preconditions": ["what must be true before starting"],
  "postconditions": ["what must be true when done"]
}

Rules:
- Reference episode IDs, do not reconstruct narratives
- Extract the COMMON pattern across episodes, not any single episode's exact steps
- Steps should be deterministic and replayable without LLM assistance
- If no common procedure can be extracted, return {"error": "no_common_pattern"}
```

The user prompt wraps each episode in AD-541b boundaries:
```
Extract the common procedure from these {len(episodes)} successful episodes
(cluster {cluster.cluster_id}, {cluster.success_rate:.0%} success rate,
intent types: {cluster.intent_types}).

{for each episode in episodes:}
=== READ-ONLY EPISODE (do not modify, summarize, or reinterpret) ===
Episode ID: {ep.id}
User Input: {ep.user_input}
Outcomes: {json.dumps(ep.outcomes, default=str)}
DAG Summary: {json.dumps(ep.dag_summary, default=str)}
Reflection: {ep.reflection or "none"}
Agents: {ep.agent_ids}
=== END READ-ONLY EPISODE ===
{end for}

Analyze the PATTERN across these episodes. Do not alter, embellish,
or reinterpret individual episodes. Your output should reference
episode IDs, not reconstructed narratives.
```

**Call the LLM at standard tier:**
```python
from probos.types import LLMRequest

request = LLMRequest(
    prompt=user_prompt,
    system_prompt=system_prompt,
    tier="standard",
    temperature=0.0,
    max_tokens=2048,
)
response = await llm_client.complete(request)
```

**Parse the JSON response.** Strip markdown fences if present (````json ... ````). Parse with `json.loads()`. If the response contains `"error"`, return `None`. Build and return a `Procedure`:

```python
procedure = Procedure(
    name=data.get("name", ""),
    description=data.get("description", ""),
    steps=[ProcedureStep(**s) for s in data.get("steps", [])],
    preconditions=data.get("preconditions", []),
    postconditions=data.get("postconditions", []),
    intent_types=cluster.intent_types,
    origin_cluster_id=cluster.cluster_id,
    origin_agent_ids=cluster.participating_agents,
    provenance=cluster.episode_ids,
    extraction_date=time.time(),
    evolution_type="CAPTURED",
    compilation_level=1,
)
return procedure
```

**Error handling:** Wrap the entire function body in try/except. On ANY exception (JSON parse error, LLM error, network error), log at debug level and return `None`. This is critical — extraction failure must not break dream cycles.

### Tests (~8 tests)

- `test_extract_procedure_from_cluster_success` — mock LLM returns valid JSON, verify Procedure created
- `test_extract_procedure_from_cluster_llm_error` — mock LLM returns error response, verify None returned
- `test_extract_procedure_from_cluster_invalid_json` — mock LLM returns garbage, verify None returned
- `test_extract_procedure_from_cluster_no_common_pattern` — mock LLM returns `{"error": "no_common_pattern"}`, verify None
- `test_extract_procedure_prompt_contains_read_only_framing` — verify AD-541b markers in prompt
- `test_extract_procedure_uses_standard_tier` — verify LLMRequest.tier == "standard"
- `test_extract_procedure_provenance_from_cluster` — verify episode_ids transferred to procedure.provenance
- `test_extract_procedure_strips_markdown_fences` — mock LLM wraps output in ```json ... ```, verify parsed correctly

---

## Part 3: Dream Cycle Integration — Step 7 (Procedure Extraction)

### File: `src/probos/cognitive/dreaming.py`

**Add import** (at top, after `episode_clustering` import):
```python
from probos.cognitive.procedures import extract_procedure_from_cluster
```

**Insert Step 7 between Step 6 (clustering) and Step 7 (gap prediction).** The current Step 7 (gap prediction, line 170) becomes Step 8.

After the Step 6 block (after line 168), insert:

```python
        # Step 7: Procedure extraction from success clusters (AD-532)
        procedures_extracted = 0
        procedures: list = []
        if self._llm_client and clusters:
            for cluster in clusters:
                # Only extract from success-dominant clusters
                if not cluster.is_success_dominant:
                    continue
                # Skip clusters we've already processed
                if cluster.cluster_id in self._extracted_cluster_ids:
                    continue
                try:
                    # Get the actual Episode objects for this cluster
                    cluster_episodes = [
                        ep for ep in episodes
                        if ep.id in cluster.episode_ids
                    ]
                    if not cluster_episodes:
                        continue
                    procedure = await extract_procedure_from_cluster(
                        cluster=cluster,
                        episodes=cluster_episodes,
                        llm_client=self._llm_client,
                    )
                    if procedure:
                        procedures.append(procedure)
                        procedures_extracted += 1
                        self._extracted_cluster_ids.add(cluster.cluster_id)
                        logger.info(
                            "Procedure extracted from cluster %s: '%s' (%d steps)",
                            cluster.cluster_id[:8],
                            procedure.name,
                            len(procedure.steps),
                        )
                except Exception as e:
                    logger.debug(
                        "Procedure extraction failed for cluster %s (non-critical): %s",
                        cluster.cluster_id[:8], e,
                    )
            self._last_procedures = procedures
```

**Rename current Step 7 comment** (line 170):
```python
        # Step 8: Capability gap prediction (AD-385)
```

**Update DreamReport construction** (line 181) — add procedure fields:

The `DreamReport` dataclass in `src/probos/types.py` needs two new fields:
```python
procedures_extracted: int = 0  # AD-532
procedures: list[Any] = field(default_factory=list)  # AD-532: Procedure objects
```

Add to the DreamReport constructor in dream_cycle():
```python
procedures_extracted=procedures_extracted,
procedures=procedures,
```

**Update the log line** (line 194) — add procedures count:
```python
logger.info(
    "dream-cycle: flushed=%d strengthened=%d pruned=%d trust_adjusted=%d "
    "clusters=%d procedures=%d gaps=%d contradictions=%d",
    report.episodes_replayed,
    report.weights_strengthened,
    report.weights_pruned,
    report.trust_adjustments,
    report.clusters_found,
    procedures_extracted,
    report.gaps_predicted,
    report.contradictions_found,
)
```

### File: `src/probos/types.py`

Add to `DreamReport` (after `clusters` field, line 375):
```python
procedures_extracted: int = 0  # AD-532
procedures: list[Any] = field(default_factory=list)  # AD-532: Procedure objects
```

### Tests (~9 tests)

- `test_dream_cycle_extracts_procedures_from_success_clusters` — mock LLM, verify procedures in DreamReport
- `test_dream_cycle_skips_failure_clusters` — only success-dominant clusters processed
- `test_dream_cycle_skips_already_extracted_clusters` — `_extracted_cluster_ids` dedup works
- `test_dream_cycle_procedure_extraction_log_and_degrade` — LLM fails, dream cycle still completes, procedures_extracted=0
- `test_dream_cycle_no_procedures_without_llm_client` — no llm_client wired, verify 0 procedures
- `test_dream_cycle_no_procedures_without_clusters` — no clusters found, verify 0 procedures
- `test_dream_report_includes_procedures` — DreamReport.procedures populated
- `test_dream_report_procedures_extracted_count` — DreamReport.procedures_extracted matches list length
- `test_dream_cycle_gap_prediction_still_works` — gap prediction (Step 8) still runs after extraction

---

## Validation Checklist

After building, verify:

1. **Part 0 — LLM client wiring:**
   - [ ] `DreamingEngine.__init__` accepts `llm_client` kwarg
   - [ ] `DreamingEngine._llm_client` is stored
   - [ ] `DreamingEngine._last_procedures` initializes to empty list
   - [ ] `DreamingEngine._extracted_cluster_ids` initializes to empty set
   - [ ] `DreamingEngine.last_procedures` property works
   - [ ] `init_dreaming()` accepts `llm_client` kwarg
   - [ ] `init_dreaming()` passes `llm_client` to `DreamingEngine`
   - [ ] `runtime.py` passes `self.llm_client` to `init_dreaming()`

2. **Part 1 — Schema:**
   - [ ] `ProcedureStep` dataclass with all fields
   - [ ] `ProcedureStep.to_dict()` serializes correctly
   - [ ] `Procedure` dataclass with all fields
   - [ ] `Procedure.to_dict()` serializes including nested steps
   - [ ] `Procedure.evolution_type` defaults to "CAPTURED"
   - [ ] `Procedure.compilation_level` defaults to 1

3. **Part 2 — Extraction:**
   - [ ] `extract_procedure_from_cluster()` exists and is async
   - [ ] Uses standard tier LLM (`tier="standard"`)
   - [ ] Prompt contains `=== READ-ONLY EPISODE ===` framing (AD-541b)
   - [ ] Prompt contains `=== END READ-ONLY EPISODE ===` closing
   - [ ] Prompt instructs "reference episode IDs, not reconstructed narratives"
   - [ ] JSON parsing handles markdown fences
   - [ ] `{"error": ...}` response returns None
   - [ ] LLM error returns None (doesn't raise)
   - [ ] Invalid JSON returns None (doesn't raise)
   - [ ] Procedure.provenance = cluster.episode_ids

4. **Part 3 — Dream cycle integration:**
   - [ ] Step 7 inserted between clustering (Step 6) and gap prediction (now Step 8)
   - [ ] Only processes `is_success_dominant` clusters
   - [ ] Skips clusters in `_extracted_cluster_ids`
   - [ ] Stores extracted procedures in `_last_procedures`
   - [ ] Adds cluster_id to `_extracted_cluster_ids` after successful extraction
   - [ ] DreamReport has `procedures_extracted` and `procedures` fields
   - [ ] Log line includes procedures count
   - [ ] Gap prediction renumbered to Step 8
   - [ ] Dream cycle completes normally even if all extractions fail

5. **Cross-cutting:**
   - [ ] No import cycles
   - [ ] All existing tests still pass
   - [ ] ~25 new tests total
   - [ ] Pre-commit hook passes (no commercial content)
