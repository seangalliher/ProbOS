# AD-573d v1: Dream-to-Working-Memory Pipeline

**Status:** READY (Wave 67 — single-AD reframe of #8 combo; see WAVE-67-DISPATCH.md)
**Closes (partial):** GH issue #8 (final remaining buildable child of AD-573b–f combo)
**Dependencies:** AD-573 v1 (complete), AD-573b (complete via Wave 8 Combo A), AD-515 DreamAdapter (complete)
**HEAD at draft:** `fa6d83d` (post-Wave-66, working tree clean)
**Baseline test count:** 11401 → expected **11411** (+10 net), window **[+8, +12]**

## Problem

Dream cycles consolidate ship cognition once per ~10 minutes (full) and ~10 seconds (micro). They produce rich `DreamReport` artifacts (`types.py:474`) — clusters found, procedures extracted, contradictions resolved, convergence reports generated, behavioral metrics. None of this is surfaced into `WorkingMemoryManager.scratchpad` (the LLM context narrowing surface AD-573b/c built). Every cognitive pathway therefore wakes from a dream amnesic of what just consolidated.

The deferral note at `prompts/archive/combo-C-trivial-extensions.md:282` reads:

> *"AD-573d (dream-to-WM pipeline) — deferred; depends on `runtime.dream_scheduler` exposing summaries (same blocker as AD-477g)."*

Verified at HEAD `fa6d83d`:

```
src/probos/cognitive/dreaming.py:2807    @property
src/probos/cognitive/dreaming.py:2809        def last_dream_report(self) -> DreamReport | None:
src/probos/types.py:474                    @dataclass class DreamReport:
src/probos/types.py:478                        episodes_replayed: int = 0
src/probos/types.py:483                        clusters_found: int = 0
src/probos/types.py:485                        procedures_extracted: int = 0
src/probos/types.py:497                        contradictions_found: int = 0
src/probos/types.py:517                        notebook_consolidations: int = 0
src/probos/types.py:519                        convergence_reports_generated: int = 0
src/probos/cognitive/working_memory.py:155   def add_scratchpad(self, text: str) -> None:
src/probos/cognitive/working_memory.py:33     scratchpad: list[str] = field(default_factory=list)
src/probos/dream_adapter.py:39                class DreamAdapter:
src/probos/dream_adapter.py:108               def on_post_dream(self, dream_report: Any) -> None:
src/probos/runtime.py:348                     self.working_memory = WorkingMemoryManager(...)
src/probos/startup/finalize.py:2414           dream_adapter = DreamAdapter(...)
```

The forcing function is satisfied. `DreamScheduler.last_dream_report` is a stable public property; `DreamAdapter.on_post_dream(dream_report)` already receives the report. `WorkingMemoryManager.add_scratchpad` is a stable Combo A surface. Wiring is mechanical.

## Solution

Single producer-side branch in `DreamAdapter`, late-bound `WorkingMemoryManager` reference via ctor kwarg + finalize-side wiring. No service-side change to `WorkingMemoryManager`. No new public attribute on runtime. No new EventType. No new Pydantic config. No change to `DreamReport`. No change to `WorkingMemorySnapshot.to_text()` rendering — that gap (scratchpad not rendered) is documented but out of scope for this AD.

### Section 1 — `DreamAdapter` ctor accepts `working_memory`

`src/probos/dream_adapter.py` — add ctor kwarg + field assignment.

```
===MODIFY: src/probos/dream_adapter.py===
===SEARCH===
        behavioral_monitor: BehavioralMonitor | None = None,
        deliver_bridge_alert_fn: Callable | None = None,
        llm_client: Any = None,  # BF-069: LLM client for health monitoring
        identity_registry: Any = None,  # BF-103: for sovereign ID resolution
    ) -> None:
        self._dream_scheduler = dream_scheduler
===REPLACE===
        behavioral_monitor: BehavioralMonitor | None = None,
        deliver_bridge_alert_fn: Callable | None = None,
        llm_client: Any = None,  # BF-069: LLM client for health monitoring
        identity_registry: Any = None,  # BF-103: for sovereign ID resolution
        working_memory: Any = None,  # AD-573d: dream-to-WM pipeline
    ) -> None:
        self._dream_scheduler = dream_scheduler
===END REPLACE===
===SEARCH===
        self._llm_client = llm_client
        self._identity_registry = identity_registry

        # Runtime state references (set by runtime after creation)
        self._cold_start: bool = False
        self._last_shapley_values: dict[str, float] | None = None
===REPLACE===
        self._llm_client = llm_client
        self._identity_registry = identity_registry
        self._working_memory = working_memory  # AD-573d

        # Runtime state references (set by runtime after creation)
        self._cold_start: bool = False
        self._last_shapley_values: dict[str, float] | None = None
===END REPLACE===
```

### Section 2 — Static helper `_summarize_dream_report`

Add a module-level pure function above the `DreamAdapter` class (just below `logger = logging.getLogger(__name__)` line 37). Pure, no I/O, deterministic.

```
===MODIFY: src/probos/dream_adapter.py===
===SEARCH===
logger = logging.getLogger(__name__)


class DreamAdapter:
===REPLACE===
logger = logging.getLogger(__name__)


# AD-573d: Dream report fields surfaced into WorkingMemory scratchpad.
# Empty/zero reports are suppressed (caller checks for None return).
_DREAM_SUMMARY_FIELDS: tuple[tuple[str, str], ...] = (
    ("clusters_found", "clusters"),
    ("procedures_extracted", "procedures"),
    ("contradictions_found", "contradictions"),
    ("convergence_reports_generated", "convergences"),
    ("notebook_consolidations", "notebooks"),
)


def _summarize_dream_report(report: Any) -> str | None:
    """Build a one-line summary string from a DreamReport.

    Returns ``None`` when ``report`` is falsy or every tracked field is zero.
    Pure function — no I/O, no logging, no exceptions raised on missing
    attributes (uses ``getattr(..., 0)``).
    """
    if not report:
        return None
    parts: list[str] = []
    for attr, label in _DREAM_SUMMARY_FIELDS:
        value = getattr(report, attr, 0) or 0
        if value:
            parts.append(f"{value} {label}")
    if not parts:
        return None
    return f"Dream consolidation: {', '.join(parts)}"


class DreamAdapter:
===END REPLACE===
```

### Section 3 — Hook into `on_post_dream`

Insert the working-memory write immediately after the AD-557 emergence-metrics block (so summary lands even if `_emergent_detector` is None or `analyze()` raises). Best-effort — never raises into the dream-cycle caller.

```
===MODIFY: src/probos/dream_adapter.py===
===SEARCH===
            if dream_report.fragmentation_risk:
                self._event_emitter(EventType.FRAGMENTATION_WARNING, {
                    "synergy_ratio": getattr(dream_report, "synergy_ratio", 0.0),
                    "pairs_analyzed": getattr(dream_report, "pairs_analyzed", 0),
                })

        if not self._emergent_detector:
            return
===REPLACE===
            if dream_report.fragmentation_risk:
                self._event_emitter(EventType.FRAGMENTATION_WARNING, {
                    "synergy_ratio": getattr(dream_report, "synergy_ratio", 0.0),
                    "pairs_analyzed": getattr(dream_report, "pairs_analyzed", 0),
                })

        # AD-573d: surface dream summary into WorkingMemory scratchpad ring.
        if self._working_memory is not None:
            try:
                summary = _summarize_dream_report(dream_report)
                if summary:
                    self._working_memory.add_scratchpad(summary)
            except Exception:
                logger.warning(
                    "AD-573d: dream summary scratchpad write failed",
                    exc_info=True,
                )

        if not self._emergent_detector:
            return
===END REPLACE===
```

### Section 4 — Finalize-side wiring

Pass `runtime.working_memory` to the `DreamAdapter` ctor in `startup/finalize.py:2414`. Existing kwargs are alphabetically clustered by purpose; place the new kwarg adjacent to `identity_registry`.

```
===MODIFY: src/probos/startup/finalize.py===
===SEARCH===
        llm_client=getattr(runtime, 'llm_client', None),  # BF-069
        identity_registry=runtime.identity_registry,  # BF-103
    )
    dream_adapter._cold_start = runtime._cold_start
===REPLACE===
        llm_client=getattr(runtime, 'llm_client', None),  # BF-069
        identity_registry=runtime.identity_registry,  # BF-103
        working_memory=getattr(runtime, "working_memory", None),  # AD-573d
    )
    dream_adapter._cold_start = runtime._cold_start
===END REPLACE===
```

### Section 5 — Tests

**New file:** `tests/test_ad573d_dream_to_working_memory.py`

10 focused tests. Use `MagicMock` for `WorkingMemoryManager` (per Wave 13 / Wave 66 fixture precedent — full runtime fixtures explode wave-gate budget).

| # | Test | Asserts |
|---|---|---|
| 1 | `test_summarize_full_report_renders_all_fields` | `_summarize_dream_report(report)` includes "3 clusters, 2 procedures, 1 contradictions, 4 convergences, 5 notebooks" given a `DreamReport(clusters_found=3, procedures_extracted=2, contradictions_found=1, convergence_reports_generated=4, notebook_consolidations=5)` |
| 2 | `test_summarize_partial_report_omits_zeros` | `DreamReport(clusters_found=2)` → `"Dream consolidation: 2 clusters"` (zero fields suppressed) |
| 3 | `test_summarize_empty_report_returns_none` | `DreamReport()` (all zero defaults) → `None` |
| 4 | `test_summarize_none_report_returns_none` | `_summarize_dream_report(None) is None` |
| 5 | `test_summarize_uses_getattr_default_on_missing_attr` | `SimpleNamespace(clusters_found=2)` (missing other tracked attrs) → `"Dream consolidation: 2 clusters"`, no AttributeError |
| 6 | `test_on_post_dream_writes_scratchpad_when_wm_present` | `DreamAdapter` constructed with `working_memory=MagicMock()`. Call `on_post_dream(report)` with a non-empty report. Assert `working_memory.add_scratchpad` called once with the expected summary string. |
| 7 | `test_on_post_dream_skips_scratchpad_when_summary_empty` | Adapter with `working_memory=MagicMock()`. Call with empty `DreamReport()`. Assert `add_scratchpad` NOT called. |
| 8 | `test_on_post_dream_tolerates_working_memory_none` | Adapter constructed without `working_memory` kwarg (defaults None). Call `on_post_dream(report)` with non-empty report. No exception, no `add_scratchpad` call (cannot — it's None). |
| 9 | `test_on_post_dream_log_and_degrades_on_scratchpad_failure` | `working_memory=MagicMock()` with `add_scratchpad.side_effect = RuntimeError("disk full")`. Call `on_post_dream(report)`. Assert no exception propagated. Assert WARNING captured via `caplog` with `"AD-573d"` prefix. |
| 10 | `test_on_post_dream_runs_summary_before_emergent_analyze` | Adapter with `working_memory=MagicMock()` and `emergent_detector=MagicMock()` whose `.analyze.side_effect = RuntimeError("boom")`. Call `on_post_dream(report)`. Assert `add_scratchpad` was called (summary path completed BEFORE the emergent failure short-circuited the rest). |

Constructor helper for tests (use a thin factory; do NOT call into real runtime):

```python
def _build_adapter(*, working_memory=None, emergent_detector=None):
    return DreamAdapter(
        dream_scheduler=None,
        emergent_detector=emergent_detector,
        episodic_memory=None,
        knowledge_store=None,
        hebbian_router=MagicMock(),
        trust_network=MagicMock(),
        event_emitter=lambda et, data: None,
        self_mod_pipeline=None,
        bridge_alerts=None,
        ward_room=None,
        registry=MagicMock(),
        event_log=None,
        config=MagicMock(),
        pools={},
        working_memory=working_memory,
    )
```

## What this AD does NOT change

- `WorkingMemoryManager` source (zero edits — Combo A's `add_scratchpad` is the consumed surface).
- `WorkingMemorySnapshot.to_text()` rendering of scratchpad — this gap (scratchpad fields exist on the snapshot at `working_memory.py:33` but `to_text()` does not render them) is documented and remains. Separate AD if/when LLM-side surfacing is needed.
- `DreamReport` schema (`types.py:474`) — pure consumer. No new fields.
- No new EventType. The scratchpad already emits no event; AD-573f only emits on `add_commitment`/`mark_commitment_complete`. AD-573d does not break that asymmetry.
- No new Pydantic config. Per-pathway opt-out is unnecessary; if `runtime.working_memory` is None (synthetic test runtime), the adapter no-ops.
- `DreamScheduler` (zero edits — `last_dream_report` is read-only consumer surface, but in fact this AD doesn't even consume that property; it consumes the report passed by argument to `on_post_dream`).
- Per-agent `AgentWorkingMemory` (`cognitive/agent_working_memory.py`, AD-573 unified WM). That surface is already wired into dreaming via `_agent_wm` (AD-671); AD-573d targets the system-level `WorkingMemoryManager` (the LLM context narrowing surface) only. No conflict.
- `runtime.dream_scheduler` callback wiring at `finalize.py:2440-2444` (no change — `on_post_dream` is already the wired callback).
- `proactive.py` AD-573c notebook/scratchpad extractor at line 2806 (untouched — orthogonal write path).

## Acceptance Criteria

1. Full gate (`pytest tests/ -q -n 4 --dist=loadfile`) lands at **11411 ± 2** (window [11409, 11413]).
2. All existing AD-573, AD-573b, AD-573c, AD-573f, AD-515 (DreamAdapter), AD-557 (emergence metrics), AD-237 (post-dream emergent detection) tests pass without modification.
3. `_summarize_dream_report` is a pure function — no `import time`, no logger calls, no I/O. Tested in isolation.
4. `on_post_dream` never raises on `add_scratchpad` failure (tier-2 log-and-degrade per Wave-5 convention).
5. The new helper `_summarize_dream_report` is module-level (not a method) — kept testable without instantiating `DreamAdapter`.
6. `working_memory` is the LAST positional/keyword in the ctor (per Open/Closed — appended, not interleaved into existing positional cluster).
7. Tier ordering preserved: AD-557 emergence metrics emit FIRST, AD-573d scratchpad write SECOND, AD-237 emergent analysis THIRD. Test #10 locks this.
8. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

## Verified Against Codebase (2026-05-05, HEAD `fa6d83d`)

```
grep -n "class DreamAdapter|def on_post_dream|def __init__" src/probos/dream_adapter.py
  39:  class DreamAdapter:
  42:      def __init__(
  108:     def on_post_dream(self, dream_report: Any) -> None:

grep -n "_summarize_dream_report|_DREAM_SUMMARY_FIELDS" src/probos/dream_adapter.py
  (no hits — both symbols are intra-prompt-introduction; not phantoms)

grep -n "add_scratchpad|scratchpad" src/probos/cognitive/working_memory.py
  33:      scratchpad: list[str] = field(default_factory=list)
  104:     # AD-573b: relational links / scratchpad / commitments (bounded rings)
  155:     def add_scratchpad(self, text: str) -> None:
  159:         self._scratchpad.append(text)

grep -n "class DreamReport|clusters_found|procedures_extracted|contradictions_found|convergence_reports_generated|notebook_consolidations" src/probos/types.py
  474:  class DreamReport:
  483:      clusters_found: int = 0  # AD-531
  485:      procedures_extracted: int = 0  # AD-532
  497:      contradictions_found: int = 0  # AD-403
  517:      notebook_consolidations: int = 0  # AD-551
  519:      convergence_reports_generated: int = 0

grep -n "DreamAdapter(" src/probos/startup/finalize.py
  2414: dream_adapter = DreamAdapter(

grep -n "self.working_memory = WorkingMemoryManager" src/probos/runtime.py
  348:  self.working_memory = WorkingMemoryManager(

grep -n "_post_dream_fn = dream_adapter.on_post_dream" src/probos/startup/finalize.py
  2443: runtime.dream_scheduler._post_dream_fn = dream_adapter.on_post_dream
```

Every concrete claim in the prompt body maps to a grep hit above. Net-new symbols (`_DREAM_SUMMARY_FIELDS`, `_summarize_dream_report`, `working_memory` ctor kwarg) are intra-prompt-introductions per the same FP class as Waves 27–66 phantom-API pre-check semantics.
