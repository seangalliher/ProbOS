# AD-454 — EvidenceCollector (auto-classifier for Ward Room posts)

**Issue:** [#510](https://github.com/seangalliher/ProbOS/issues/510) — *closed by this commit (`Closes #510`).*
**Type:** Code AD (new infrastructure-tier agent + config + finalize wirer + tests)
**Depends on:** **`prompts/ad-454-emergence-taxonomy-v1.md`** (must be merged first — provides `src/probos/cognitive/emergence_taxonomy.py` and `docs/research/emergence-taxonomy.md`).
**Wave:** 131
**Mode:** main

## Goal

Build the OSS `EvidenceCollector` agent that subscribes to Ward Room post events, classifies each post against the AD-454 22-code taxonomy via a fast-tier LLM call, and writes structured YAML observations to disk for the AD-453 emergence-research pipeline. Default-disabled (research opt-in); zero impact on production runtime when off.

This is the consumer side of AD-454. The taxonomy module is already shipped by the prerequisite prompt; this prompt only imports it.

## Verified Against Codebase (2026-05-08)

```
grep -n "WARD_ROOM_POST_CREATED" src/probos/events.py
  68: WARD_ROOM_POST_CREATED = "ward_room_post_created"
  719: event_type: EventType = field(default=EventType.WARD_ROOM_POST_CREATED, init=False)

# Payload — verified at the emission site:
grep -n "WARD_ROOM_POST_CREATED" src/probos/ward_room/messages.py
  238: self._emit(EventType.WARD_ROOM_POST_CREATED, {
  Payload keys at lines 239–245: post_id, thread_id, author_id,
  parent_id, author_callsign, mentions.
  *Body is NOT in payload — collector must fetch via ward_room.get_post().*

# Listener registration pattern — verified live:
grep -n "runtime.add_event_listener" src/probos/startup/finalize.py
  2377: runtime.add_event_listener(
            feedback.on_event,
            event_types=[
                EventType.VERIFICATION_PASSED.value,
                EventType.VERIFICATION_FAILED.value,
            ],
         )
  Reference pattern: GroundTruthTrustFeedback finalize wirer
  (finalize.py ~line 2360–2400). Same shape applies here.

# Listener dispatch is fire-and-forget; sync OR async accepted:
grep -n "iscoroutinefunction" src/probos/runtime.py
  916: if asyncio.iscoroutinefunction(fn):
  917:     asyncio.create_task(fn(event))
  918: else:
  919:     fn(event)
  Confirms: handler may be `async def on_event(event: dict)`.

# LLM client + tier:
grep -n "tier" src/probos/types.py | head -3
  221: tier: str = "standard"  # LLMTier value
  Confirms: tier is a per-LLMRequest str field. AD-700c precedent —
  fast tier requested via `LLMRequest(... tier="fast")`.

grep -n "self.llm_client" src/probos/runtime.py | head -3
  408: llm_client=self.llm_client,
  Confirms: runtime.llm_client is the public attribute. Type:
  `BaseLLMClient | None` (runtime.py:332).

# BaseAgent tier values (class-level attribute on subclasses):
grep -nE 'tier\s*=\s*"(utility|core|domain)"' src/probos/agents/ src/probos/cognitive/
  agents/introspect.py:27:        tier = "utility"
  agents/system_qa.py:77:         tier = "utility"
  agents/federation_recall_agent.py:27: tier = "utility"
  agents/utility/nl_graph_query_agent.py:40: tier = "utility"
  cognitive/code_reviewer.py:36:  tier = "utility"
  *No class-level tier == "infrastructure" exists on any BaseAgent
  subclass.* The string "infrastructure" appears only in identity-tier
  asset tagging (agent_onboarding.py:395 + identity.py:653,689).
  Canonical tier for a system-level passive observer (no Ward Room
  participation, no trust, no Hebbian) is "utility" — see
  IntrospectionAgent / SystemQAAgent precedent.

# Finalize wirer pattern — verified shape:
grep -nE 'def _wire_[a-z_]+\(\*, runtime: Any, config: "SystemConfig"\)' src/probos/startup/finalize.py | head -5
  25, 80, 105, 122, 141, ...
  Standard signature confirmed: keyword-only, returns bool.

# Knowledge store availability (alternative output sink):
grep -n "self._knowledge_store" src/probos/runtime.py
  1453: self._knowledge_store = cog.knowledge_store
  Available, but the right home for ad-hoc research artifacts is the
  filesystem under data/research/ — KnowledgeStore is for cognitive
  recall, not append-only research logs. We use file storage.

# Public emit_event API:
grep -n "def emit_event" src/probos/runtime.py
  924: def emit_event(self, event: BaseEvent | str | EventType, ...) -> None:
  Confirmed stable.

# AD-numbering hard rule:
Select-String -Path PROGRESS.md,DECISIONS.md,docs\development\roadmap.md \
  -Pattern 'AD-\d+' -AllMatches | ... | Select-Object -Last 5
  AD-713, AD-714, AD-715, AD-716, AD-717.
  AD-454 is reused per the dispatch (issue #510 was originally filed
  as AD-454; the number was reserved when the issue was opened but the
  taxonomy prerequisite blocked it). Builder MUST verify before commit
  that no other tracker file has independently re-issued AD-454 since
  the dispatch was written. If a collision is found, surface and STOP.
```

### Verify-first findings (flag in build report)

1. **Dispatch terminology drift.** The dispatch uses "infrastructure-tier agent" / `tier="infrastructure"`. There is **no class-level `tier == "infrastructure"`** on any `BaseAgent` subclass in the live codebase. The closest matching precedent for a passive system observer with no Ward Room/trust/Hebbian participation is `tier = "utility"` (see `IntrospectionAgent`, `SystemQAAgent`, `FederationRecallAgent`). The dispatch's "infrastructure-tier" should be read as a *role description*; the **canonical class-level value is `"utility"`**, and that is what this prompt specs.
2. **Ward Room post payload does NOT include the body.** Collector must call `runtime.ward_room.get_post(post_id)` to retrieve `body`, and `runtime.ward_room.get_thread(thread_id, post_limit=...)` for thread context. The dispatch does not state this explicitly.
3. **AD-numbering reuse risk.** Highest live AD is AD-717. AD-454 is being deliberately reused per the dispatch's binding to issue #510. Builder must run the AD-numbering hard rule one more time at commit time to confirm AD-454 has not been independently re-issued.

## Scope

### In scope

- New module `src/probos/cognitive/evidence_collector.py` (the agent + its event handler).
- New config `EmergenceCollectorConfig` in `src/probos/config.py`, hung off `SystemConfig`.
- New finalize wirer `_wire_emergence_collector` in `src/probos/startup/finalize.py`.
- File-based output: `data/research/emergence-evidence/<trial-id>/OBS-NNNN.yaml`.
- Tests at `tests/test_ad454_evidence_collector.py`.

### Out of scope (HARD)

- The taxonomy itself (already shipped by the v1 prompt).
- Any change to the existing `EmergentDetector`. Orthogonal axis.
- Federation-tier sharing of evidence. OS-tier file storage only; not federation-synced.
- LLM-judge meta-evaluation of classifier accuracy. Separate AD.
- HXI surfaces, paper-generation tooling, dashboard. Separate ADs.
- Any modification of Ward Room behavior, dispatch, or pipeline. The collector is a passive observer that reads via the public `runtime.ward_room` API.
- Modification of `runtime.py` beyond what already exists. Wiring goes through `finalize.py` like every other peer subsystem.

## Deliverables

### D1. New module `src/probos/cognitive/evidence_collector.py`

Pure observer. Owns its own event handler, fetches post body + short thread context (via `await runtime.ward_room.get_post(post_id)` and `await runtime.ward_room.get_thread(thread_id, post_limit=...)` — both are async, see verify-first finding #2), calls `await runtime.llm_client.complete(LLMRequest(..., tier="fast"))` with the classifier prompt from `emergence_taxonomy.as_classifier_prompt()`, parses the JSON response, applies confidence + dedup filters, writes a YAML file. No trust effects, no Hebbian effects, no Ward Room posting, no consensus participation.

Required public API (subset — Builder fills in the rest along the same shape):

```python
"""AD-454: EvidenceCollector — auto-classifies Ward Room posts against the
emergence taxonomy. Pure observer. OSS-tier file output.

Default disabled. When enabled, subscribes to WARD_ROOM_POST_CREATED via
runtime.add_event_listener and writes one YAML file per accepted
classification under config.emergence_collector.output_dir.

Not federation-synced. Not consumed by trust, Hebbian, or consensus.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from probos.cognitive.emergence_taxonomy import (
    BehaviorCode,
    TAXONOMY,
    as_classifier_prompt,
)
from probos.types import LLMRequest

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EvidenceObservation:
    """One persisted classification."""

    obs_id: str                  # "OBS-0001" formatted
    timestamp: float             # epoch seconds
    trial_id: str                # config.emergence_collector.trial_id
    post_id: str
    thread_id: str
    author_id: str
    author_callsign: str
    behavior_codes: tuple[BehaviorCode, ...]
    confidence: float            # in [0,1], must be >= threshold to persist
    reasoning: str               # LLM's free-text justification, capped at N chars
    raw_response: str = ""       # the full LLM JSON string (debug aid)


class EvidenceCollector:
    """Passive Ward Room observer that classifies posts against the taxonomy."""

    tier: str = "utility"  # canonical class-level tier (see verify-first finding #1)

    def __init__(
        self,
        *,
        runtime: Any,
        confidence_threshold: float = 0.7,
        dedup_window_seconds: float = 600.0,
        output_dir: Path | str = "data/research/emergence-evidence",
        llm_tier: str = "fast",
        trial_id: str = "default",
        thread_context_limit: int = 5,
        max_reasoning_chars: int = 2000,
    ) -> None:
        ...

    async def on_ward_room_post(self, event: dict[str, Any]) -> None:
        """Listener entry point. Async — registered via add_event_listener."""
        ...

    async def classify_post(
        self,
        *,
        post_id: str,
        thread_id: str,
        author_id: str,
        author_callsign: str,
    ) -> EvidenceObservation | None:
        """Classify one post; return the observation or None if filtered."""
        ...

    def _parse_llm_response(self, raw: str) -> tuple[list[BehaviorCode], float, str]:
        """Strict JSON parsing with permissive code matching.

        - Extracts the first JSON object from raw (in case the LLM emits
          markdown fences or stray prose).
        - Maps free-text codes to BehaviorCode values; unknown codes drop.
        - Confidence clamped to [0.0, 1.0].
        - Reasoning truncated to max_reasoning_chars.
        """
        ...

    async def _persist(self, obs: EvidenceObservation) -> Path:
        """Write a single OBS-NNNN.yaml file. Concurrency-safe.

        Uses an asyncio.Lock to guarantee monotonic, gapless OBS numbering
        even under concurrent post events. The lock is per-collector
        instance; since there is exactly one collector per runtime, this
        is sufficient.
        """
        ...
```

Implementation constraints:

- **Listener registration is OWNED by the finalize wirer (D3), not the collector.** The collector exposes `on_ward_room_post(event)` and `classify_post(...)`; finalize calls `runtime.add_event_listener(collector.on_ward_room_post, event_types=[EventType.WARD_ROOM_POST_CREATED.value])` after construction.
- **Dedup window** is per-`(author_id, behavior_code)` tuple. If any code in a new observation matches a previously-persisted observation for the same author within `dedup_window_seconds`, the entire new observation is dropped (silent — debug-log only). Anti-pattern codes follow the same rule (a CASCADE-CONFAB is per-author too — multiple agents confabulating still produces one observation per author). **Note for the Builder:** a true cascade by definition produces one OBS file per agent in the cascade, each independently classifying the same anti-pattern code. That's the intended signal — it is the across-author count that detects the cascade. Do not "fix" this by collapsing per-author CASCADE-CONFAB observations into a single shared file.
- **Confidence < threshold ⇒ silent skip.** Debug-log only.
- **Failed LLM call** (timeout, non-200, malformed JSON) ⇒ `logger.warning(...)` with context (post_id, error) and skip. **Tier-2 log-and-degrade**, never propagate. The collector is research telemetry; a missing observation is acceptable, a thrown exception that crashes the listener is not.
- **OBS numbering.** Per-trial monotonic counter starting at 1, zero-padded to 4 digits (`OBS-0001`, `OBS-0002`, ...). On startup, the collector scans the trial directory and resumes from `max + 1` (so a restart inside a trial doesn't collide). Async lock guarantees no race on the counter when concurrent posts arrive.
- **YAML output schema** (literal):
  ```yaml
  obs_id: OBS-0042
  timestamp: 1746720000.123
  trial_id: trial-3
  post_id: <post_id>
  thread_id: <thread_id>
  author_id: <author_id>
  author_callsign: Vega
  behavior_codes:
    - SELF-AWARE
    - META-COG
  confidence: 0.83
  reasoning: |
    Agent independently distinguished episodic memory from context
    window data, self-corrected confabulation under interrogation.
  raw_response: |
    {"codes": ["SELF-AWARE","META-COG"], "confidence": 0.83, ...}
  ```
- **PyYAML dependency.** Verify it's already in `pyproject.toml`. If yes, use `yaml.safe_dump(..., sort_keys=False)`. If no, surface to the dispatcher (do NOT add a new dep in this AD without explicit approval — fall back to a hand-rolled writer that emits the same key order).
- **Public API typed in full.** Demeter respected — collector takes `runtime` for `runtime.llm_client`, `runtime.ward_room`, and that's it. Do NOT reach into `runtime._private_attr`.
- **Exception policy is uniform tier-2 (log-and-degrade) at every boundary inside the collector.** All exception paths inside `on_ward_room_post`, `classify_post`, `_parse_llm_response`, and `_persist` are tier-2. Use `logger.exception(...)` with full context (post_id, trial_id, behavior_code if known, error class) for unexpected errors; use `logger.warning(...)` with context for expected failures (LLM timeout, malformed JSON, OSError, missing trial dir). **Never `raise` out of these methods.** Rationale: `runtime.add_event_listener` dispatches async handlers via `asyncio.create_task(fn(event))` (verified `runtime.py:917`) without storing the task ref — any propagated exception becomes a fire-and-forget asyncio task error and is silently lost. The listener boundary owns the swallow. Filesystem corruption (e.g. trial dir doesn't exist after `mkdir(parents=True, exist_ok=True)`) thus surfaces as a `logger.exception(...)` line with full context, not a silent task death; the collector remains operational for the next post.
- **`runtime.evidence_collector` is a runtime-attribute set by finalize, not a class-level annotation.** This AD does NOT add a class-level annotation on `ProbOSRuntime`; the attribute is set by D3's finalize wirer (`runtime.evidence_collector = collector`) and read defensively via `getattr(runtime, 'evidence_collector', None)` everywhere except inside the collector instance itself. Consistent with several existing peer subsystems (Wave 5 convention #1). A future cleanup AD may promote peer-subsystem slots to class-level `Any | None = None` annotations on `ProbOSRuntime`; that is out of scope here.

### D2. Configuration in `src/probos/config.py`

```python
class EmergenceCollectorConfig(BaseModel):
    """AD-454: EvidenceCollector — research opt-in, default disabled."""

    enabled: bool = False
    confidence_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    dedup_window_seconds: float = Field(default=600.0, ge=0.0)
    output_dir: str = "data/research/emergence-evidence"
    llm_tier: str = "fast"
    trial_id: str = "default"
    thread_context_limit: int = Field(default=5, ge=0, le=50)
    max_reasoning_chars: int = Field(default=2000, ge=100, le=20000)
```

Hang it off `SystemConfig` as `emergence_collector: EmergenceCollectorConfig = Field(default_factory=EmergenceCollectorConfig)`. Default-False enabled — the system boots and runs unchanged with zero overhead unless an operator explicitly opts in for a research trial.

**No env-var override.** Trials are deliberate; the operator edits `config/system.yaml` for a trial, then reverts.

### D3. Finalize wirer in `src/probos/startup/finalize.py`

New function placed near other agent/observer wirers, signature consistent with the rest:

```python
def _wire_emergence_collector(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-454: Wire EvidenceCollector if enabled. Default off."""
    cfg = getattr(config, "emergence_collector", None)
    if not cfg or not cfg.enabled:
        return False

    if getattr(runtime, "llm_client", None) is None:
        logger.warning(
            "AD-454: EvidenceCollector wants llm_client but runtime.llm_client "
            "is None; collector NOT wired. Configure an LLM client to enable."
        )
        return False
    if getattr(runtime, "ward_room", None) is None:
        logger.warning(
            "AD-454: EvidenceCollector wants ward_room but runtime.ward_room "
            "is None; collector NOT wired."
        )
        return False

    from probos.cognitive.evidence_collector import EvidenceCollector
    from probos.events import EventType

    collector = EvidenceCollector(
        runtime=runtime,
        confidence_threshold=cfg.confidence_threshold,
        dedup_window_seconds=cfg.dedup_window_seconds,
        output_dir=cfg.output_dir,
        llm_tier=cfg.llm_tier,
        trial_id=cfg.trial_id,
        thread_context_limit=cfg.thread_context_limit,
        max_reasoning_chars=cfg.max_reasoning_chars,
    )
    runtime.evidence_collector = collector  # public attribute (Wave 5 convention #1)
    runtime.add_event_listener(
        collector.on_ward_room_post,
        event_types=[EventType.WARD_ROOM_POST_CREATED.value],
    )
    logger.info(
        "AD-454: EvidenceCollector wired (trial=%s, threshold=%.2f, "
        "dedup_window=%.0fs, output=%s)",
        cfg.trial_id, cfg.confidence_threshold,
        cfg.dedup_window_seconds, cfg.output_dir,
    )
    return True
```

Insert the call in the existing finalize sequence. Do **not** make it a hard dependency of any other wirer; it is purely additive. Place it after `_wire_birth_chamber` group and before federation/HXI wirers — anywhere in the existing additive block is fine so long as `runtime.llm_client` and `runtime.ward_room` are already set by the time it runs (they are; both are constructed in the cognitive/comm bring-up well before `finalize.py` runs).

### D4. Tests at `tests/test_ad454_evidence_collector.py`

Minimum 7 (the dispatch's six + one for graceful degrade):

1. `test_classify_post_happy_path_writes_obs_yaml` — fake LLM returns `{"codes":["MGT-DIR"], "confidence": 0.9, "reasoning":"..."}`; assert OBS-0001.yaml exists, schema correct, contains `MGT-DIR`.
2. `test_low_confidence_no_write` — LLM returns `confidence: 0.3`; assert no OBS file written; collector returns `None`.
3. `test_dedup_within_window_drops_second` — two posts by same author, both classified `MGT-DIR` within `dedup_window_seconds`; assert only OBS-0001 is written.
4. `test_dedup_across_authors_does_not_dedup` — two different authors, same code, same window; assert two OBS files.
5. `test_anti_pattern_cascade_confab_is_persisted_and_flagged` — LLM returns `["CASCADE-CONFAB"]`; assert OBS file written and `behavior_codes` contains the anti-pattern (no special-casing — anti-patterns persist exactly like positive codes).
6. `test_disabled_config_wirer_returns_false_and_no_listener_registered` — `cfg.enabled=False`; assert `_wire_emergence_collector` returns False, no listener added.
7. `test_concurrent_posts_obs_numbers_monotonic_and_unique` — fire `N=10` post events concurrently. **Invocation is direct on the collector, not via the runtime dispatcher**: `await asyncio.gather(*[collector.on_ward_room_post(evt) for evt in events])`. This isolates the `_persist` lock guarantee from the runtime's `add_event_listener` dispatch behavior. Assert OBS-0001..OBS-0010 exist with no gaps and no duplicates.
8. (recommended) `test_llm_failure_logged_and_does_not_propagate` — patch `runtime.llm_client.complete` to raise; assert no exception bubbles out of `on_ward_room_post`, no OBS file written, warning logged.
9. (recommended) `test_malformed_llm_json_is_logged_and_skipped` — LLM returns "not json at all" or `{"codes": ["NOT-A-CODE"]}`; assert no OBS file (unknown code with no recognized codes ⇒ effectively low-confidence; skip).

Use a `_FakeLLMClient` stub class (not MagicMock) per the project's testing convention. Use `tmp_path` for `output_dir`. Use a small fake runtime that exposes `llm_client`, `ward_room`, and `add_event_listener` — do NOT spin up the full runtime.

### D5. DECISIONS.md entry

Append to the appropriate era file:

```markdown
### AD-454 — EvidenceCollector (Ward Room post auto-classifier, AD-453 research)

OSS-tier passive observer. Subscribes to EventType.WARD_ROOM_POST_CREATED.
Classifies each post against the AD-454 taxonomy (22 codes incl.
CASCADE-CONFAB anti-pattern) via fast-tier LLM call. Writes
OBS-NNNN.yaml files under config.emergence_collector.output_dir.
Default disabled (research opt-in). No trust effects, no Hebbian
effects, no consensus participation, no federation sync. tier="utility"
(matches IntrospectionAgent / SystemQAAgent precedent).

Dedup: per-(author_id, behavior_code), default 600s window.
Confidence threshold default 0.7.
Closes #510 (joint with AD-454 taxonomy prerequisite).
```

## What this does NOT change

- `EmergentDetector` and its event surfaces — untouched.
- Ward Room dispatch, pipeline, router behavior — untouched (collector is a read-only listener).
- Trust, Hebbian, consensus, dreaming — untouched.
- Federation surface — untouched (collector output is OS-tier file storage only).
- Any existing test — only additions.
- `runtime.py` — untouched. All wiring through `finalize.py`.

## Acceptance criteria

- Pre-flight: working-tree integrity check before starting. `git diff --numstat`; any tracked-file deletion >200 lines that wasn't authored in this prompt's session = STOP and surface (Wave 129/130 retrospective convention #20).
- AD-numbering re-verification: confirm at commit time that AD-454 has not been independently re-issued elsewhere since the dispatch was written. If a collision is found, surface and STOP.
- Focused gate: `pytest tests/test_ad454_evidence_collector.py -v -n 0` green; minimum 7 tests.
- Full gate: `pytest tests/ -q -n 8 --dist=loadfile` non-decreasing.
- Disabled-by-default: with the default config, `pytest -k 'not ad454'` shows zero new wiring (collector is constructed only when `config.emergence_collector.enabled is True`).
- Type annotations: every public method on `EvidenceCollector` is fully typed.
- Logging: every fail path includes context (post_id + reason). No bare `logger.warning("error")`.
- Config: `EmergenceCollectorConfig` lives in `config.py`; defaults reasonable; `enabled=False` per Wave 10 convention #14 (transitional flag).
- Dependency: collector imports `from probos.cognitive.emergence_taxonomy import ...`; if that module is missing (i.e., AD-454 v1 prompt was not merged first), the build fails loudly — that's the correct dependency-ordering failure.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Revision (2026-05-08)

Pass-1 review (`prompts/Reviews/ad-454-evidence-collector-v1-review.md`) returned ⚠️ Conditional with 1 Required + 3 Recommended findings. All folded in; none rejected.

- **Required — Tier-2 listener-boundary exception policy.** D1 implementation-constraints bullet (the former "Tier-3 propagate ONLY for filesystem-broken" line) replaced with a uniform tier-2 (log-and-degrade) policy across `on_ward_room_post`, `classify_post`, `_parse_llm_response`, and `_persist`. Rationale embedded in the bullet: `runtime.add_event_listener` dispatches via `asyncio.create_task(fn(event))` (verified `runtime.py:917`) without storing the task ref, so a propagated exception becomes a silent fire-and-forget task error. The listener boundary owns the swallow. Filesystem corruption surfaces as `logger.exception(...)` with full context (post_id, trial_id, behavior_code, error class), not silent task death. Old wording fully removed from normative content.
- **Recommended #1 — Explicit `await` on async ward-room reads.** D1 narrative paragraph (Pure observer…) updated to spell out `await runtime.ward_room.get_post(post_id)` and `await runtime.ward_room.get_thread(thread_id, post_limit=...)` literally, with cross-reference to verify-first finding #2. Prevents Builder from emitting an unawaited-coroutine regression.
- **Recommended #2 — No class-level `evidence_collector` annotation.** D1 implementation-constraints bullet added: `runtime.evidence_collector` is set by D3's finalize wirer and read defensively via `getattr(runtime, 'evidence_collector', None)` everywhere except inside the collector. Explicitly out of scope: promoting peer-subsystem slots to class-level annotations on `ProbOSRuntime`.
- **Recommended #3 — Test #7 invokes the collector directly.** D4 test #7 (concurrency) reworded to make the invocation explicit: `await asyncio.gather(*[collector.on_ward_room_post(evt) for evt in events])`. The test now isolates the `_persist` lock guarantee from runtime dispatch behavior, eliminating brittle dependency on dispatcher ordering.

Nits (CASCADE-CONFAB per-author cadence note, `_parse_llm_response` list→tuple boundary, YAML literal-style verification) folded in where natural — the per-author cascade clarification was added inline to the dedup-window bullet in D1 (since it was a one-liner that prevents the Builder from "fixing" what isn't broken). The other two nits left as-is per review note that they need no code change.

## Tracking

- Builder updates `PROGRESS.md` with the AD-454 collector line and current test count delta.
- Builder appends the DECISIONS.md entry from D5.
- Final commit message includes `Closes #510`.

## Forward markers

- **AD-454-1.** LLM-judge meta-evaluation: a periodic batch job samples N OBS files, asks a deep-tier LLM to re-judge with the canonical prompt, computes inter-rater agreement. Validates classifier accuracy without humans-in-the-loop for each post.
- **AD-454-2.** Federation-tier sharing of evidence (currently OS-tier file storage only). Requires AD-479 federation maturity.
- **AD-454-3.** Auto-paper-generation: roll OBS files for a trial into a Markdown summary table per the AD-453 paper's evidence-section template.
- **AD-454-4.** PID/TDMI quantitative measurement layered on taxonomy-tagged windows (Riedl 2026 framework).
