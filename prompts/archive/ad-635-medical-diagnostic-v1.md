# AD-635 v1 — Medical Diagnostic Data Access: Clinical Telemetry Query Facade

**Status:** Ready for build
**Issue:** #231
**Parent:** AD-588 (introspective telemetry — self-query); AD-620/621/622 (clearance model)
**Depends on:** AD-588 (shipped), AD-620/621/622 (shipped), AD-658 chain traces (shipped)
**Estimated tests:** 8

---

## v1 Scope (NARROW)

This AD ships a **clearance-gated read-only query facade** for clinical agents (Diagnostician/Chapel, Counselor/Echo) to perform cross-agent telemetry queries. v1 covers **2 of the 4 data domains** identified in #231:

1. **Dream cycle history** — `EmergentDetector._dream_history` ring buffer surfaced via a new public `recent_dreams(limit)` accessor on EmergentDetector.
2. **Cross-agent cognitive journal chain traces** — `CognitiveJournal.get_recent_chain_traces(*, agent_id=...)` already supports cross-agent queries when the caller passes a target `agent_id`; we just gate it.

The remaining two domains (consolidation anomaly audit trail, circuit breaker state history) plus REST endpoints, shell command, and proactive injection are explicitly deferred to AD-635b–f.

This v1 is greenfield with respect to AD-635 — the codebase has zero `ClinicalTelemetry*` symbols today.

---

## Verified Anchors (HEAD `7f9bff6`)

```
grep -n "_dream_history" src/probos/cognitive/emergent_detector.py
  196:        self._dream_history: collections.deque[dict] = collections.deque(maxlen=max_history)
  249:    def clear_dream_history(self) -> None:
  973:        self._dream_history.append(report_data)

grep -n "class EmergentDetector" src/probos/cognitive/emergent_detector.py
  91: class EmergentDetector:

grep -n "self._emergent_detector" src/probos/runtime.py
  1496:        self._emergent_detector = dream_result.emergent_detector
  (private — no public runtime.emergent_detector property; consumers reach via getattr)

grep -n "async def get_recent_chain_traces" src/probos/cognitive/journal.py
  335:    async def get_recent_chain_traces(
        self, *, limit: int = 50, agent_id: str | None = None, since: float | None = None,
    ) -> list[dict[str, Any]]:

grep -n "runtime.cognitive_journal" src/probos/startup/shutdown.py
  233:    if runtime.cognitive_journal:
  235:        runtime.cognitive_journal = None
  (public attribute, settable)

grep -n "runtime.clearance_grant_store" src/probos/startup/shutdown.py
  238:    if hasattr(runtime, 'clearance_grant_store') and runtime.clearance_grant_store:
  (public attribute)

grep -n "class RecallTier" src/probos/earned_agency.py
  55: class RecallTier(str, Enum):
  56:     BASIC = "basic"
  57:     ENHANCED = "enhanced"
  58:     FULL = "full"
  59:     ORACLE = "oracle"

grep -n "def effective_recall_tier\|def resolve_billet_clearance\|def resolve_active_grants" src/probos/earned_agency.py
  99:  def effective_recall_tier(rank, billet_clearance, grants) -> RecallTier
  131: def resolve_billet_clearance(agent_type, ontology) -> str
  149: def resolve_active_grants(agent_id, grant_store) -> list[ClearanceGrant]

grep -n "def get_post_for_agent" src/probos/ontology/service.py
  165:    def get_post_for_agent(self, agent_type: str) -> Post | None:

grep -n "clearance:" src/probos/ontology/models.py
  40:    clearance: str = ""  # AD-620: RecallTier name (BASIC/ENHANCED/FULL/ORACLE)

grep -n "agent_type: counselor\|agent_type: diagnostician" config/ontology/organization.yaml
  334:  - agent_type: counselor       (post: counselor,       clearance: ORACLE)
  350:  - agent_type: diagnostician   (post: chief_medical,   clearance: FULL)

grep -n "def _wire_diagnostic_context\|def _wire_chain_optimizer" src/probos/startup/finalize.py
  214: def _wire_chain_optimizer(*, runtime, config) -> bool
  263: def _wire_diagnostic_context(*, runtime, config) -> bool

grep -n "diagnostic_context: DiagnosticContextConfig" src/probos/config.py
  2071:    diagnostic_context: DiagnosticContextConfig = Field(default_factory=DiagnosticContextConfig)

grep -rn "ClinicalTelemetry\|clinical_telemetry" src/probos/
  (zero hits — greenfield)
```

The clearance helper trio is the canonical pattern at `cognitive_agent.py:4958` and `proactive.py:1254`. Reuse exactly.

---

## Section 0 — Naming & Convention Reminders

1. **Property-collision trap (Wave 32 retrospective).** `CognitiveAgent.cognitive_journal` is a `@property` at `cognitive_agent.py:265` proxying to `runtime.cognitive_journal`. **`ClinicalTelemetryService` does NOT subclass CognitiveAgent**, so the trap does not apply here. Documented for future consumers (AD-635b/c may add a CognitiveAgent-side hook).
2. **Default-False per Wave 10 transitional-flag convention.** `ClinicalTelemetryConfig.enabled: bool = False` — service is invisible at runtime until Captain opts in via YAML.
3. **Demeter on `runtime._emergent_detector`.** The runtime stores the detector privately. v1 reads it via `getattr(runtime, "_emergent_detector", None)` in the wirer (mirrors `dream_adapter.py:65` precedent). A public `runtime.emergent_detector` property is OUT OF SCOPE — track as a follow-up nit.
4. **Public accessor on the OWNER, not the consumer.** Add `EmergentDetector.recent_dreams(limit=20)` rather than reaching into `_dream_history` from ClinicalTelemetryService. Open/Closed.

---

## Section 1 — New module `src/probos/cognitive/clinical_telemetry.py`

Create a new module. Full file content:

```python
"""AD-635 v1 — Clinical Telemetry Query Facade.

Clearance-gated read-only query service enabling Medical (Chapel,
chief_medical/FULL) and Counselor (Echo, counselor/ORACLE) to perform
cross-agent clinical diagnostics over substrate telemetry.

v1 surfaces TWO data domains:
  - Dream cycle history (via EmergentDetector.recent_dreams)
  - Cross-agent cognitive journal chain traces (via CognitiveJournal.get_recent_chain_traces)

Anomaly audit trail and circuit breaker state history are deferred to AD-635b/c.
REST endpoints, shell command, and proactive injection are deferred to AD-635d/e/f.

Authorization model (AD-620/622): caller must hold a clearance tier of FULL
or ORACLE (resolved via effective_recall_tier from rank + billet + active
grants) AND have a clinical agent_type. Denied queries return [] and log
a warning — they never raise. Every query is logged to a bounded in-memory
audit ring. Persistence of the audit log is deferred to AD-635b.
"""

from __future__ import annotations

import collections
import logging
import time
from typing import Any

from probos.earned_agency import (
    RecallTier,
    effective_recall_tier,
    resolve_active_grants,
    resolve_billet_clearance,
)

logger = logging.getLogger(__name__)


# Clinical agent_types authorized (in addition to clearance gate).
CLINICAL_ROLES: frozenset[str] = frozenset({"diagnostician", "counselor"})

# Tier floor — caller must hold FULL or ORACLE.
QUALIFYING_TIERS: frozenset[RecallTier] = frozenset(
    {RecallTier.FULL, RecallTier.ORACLE}
)


class ClinicalTelemetryService:
    """AD-635 v1: Read-only clearance-gated cross-agent clinical query facade."""

    def __init__(self, runtime: Any, *, audit_max_entries: int = 1000) -> None:
        self._runtime = runtime
        self._audit: collections.deque[dict[str, Any]] = collections.deque(
            maxlen=max(1, int(audit_max_entries))
        )

    # ---- Public API ------------------------------------------------------

    async def query_dream_history(
        self,
        *,
        requester_agent_id: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Return up to `limit` recent dream reports, most recent first.

        Returns [] (not raises) if requester lacks clearance or if the
        EmergentDetector is unavailable. Every call is logged to the audit ring.
        """
        granted = self._authorize_clinical_query(requester_agent_id)
        if not granted:
            self._record_audit(
                requester_agent_id, "dream_history", granted=False, result_count=0
            )
            logger.warning(
                "AD-635: dream_history denied for %s (clearance/role gate)",
                requester_agent_id,
            )
            return []

        detector = getattr(self._runtime, "_emergent_detector", None)
        if detector is None or not hasattr(detector, "recent_dreams"):
            self._record_audit(
                requester_agent_id, "dream_history", granted=True, result_count=0
            )
            return []

        try:
            rows = detector.recent_dreams(limit=max(0, int(limit)))
        except Exception:
            logger.warning(
                "AD-635: dream_history accessor failed for %s", requester_agent_id,
                exc_info=True,
            )
            self._record_audit(
                requester_agent_id, "dream_history", granted=True, result_count=0
            )
            return []

        self._record_audit(
            requester_agent_id, "dream_history", granted=True, result_count=len(rows)
        )
        return rows

    async def query_agent_chain_traces(
        self,
        *,
        requester_agent_id: str,
        target_agent_id: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Return up to `limit` recent chain traces for `target_agent_id`.

        Returns [] (not raises) if requester lacks clearance, if the journal
        is unavailable, or on any underlying failure.
        """
        granted = self._authorize_clinical_query(requester_agent_id)
        if not granted:
            self._record_audit(
                requester_agent_id,
                "chain_traces",
                granted=False,
                result_count=0,
                target_agent_id=target_agent_id,
            )
            logger.warning(
                "AD-635: chain_traces denied for %s (clearance/role gate)",
                requester_agent_id,
            )
            return []

        journal = getattr(self._runtime, "cognitive_journal", None)
        if journal is None or not hasattr(journal, "get_recent_chain_traces"):
            self._record_audit(
                requester_agent_id,
                "chain_traces",
                granted=True,
                result_count=0,
                target_agent_id=target_agent_id,
            )
            return []

        try:
            rows = await journal.get_recent_chain_traces(
                limit=max(0, int(limit)),
                agent_id=target_agent_id,
            )
        except Exception:
            logger.warning(
                "AD-635: chain_traces query failed for %s -> %s",
                requester_agent_id, target_agent_id,
                exc_info=True,
            )
            self._record_audit(
                requester_agent_id,
                "chain_traces",
                granted=True,
                result_count=0,
                target_agent_id=target_agent_id,
            )
            return []

        self._record_audit(
            requester_agent_id,
            "chain_traces",
            granted=True,
            result_count=len(rows),
            target_agent_id=target_agent_id,
        )
        return rows

    @property
    def audit_log(self) -> list[dict[str, Any]]:
        """Snapshot of the audit ring (most recent last). Returns a copy."""
        return list(self._audit)

    # ---- Internals -------------------------------------------------------

    def _authorize_clinical_query(self, agent_id: str) -> bool:
        """Resolve effective clearance tier + clinical role for `agent_id`."""
        agent_type = self._resolve_agent_type(agent_id)
        if not agent_type or agent_type not in CLINICAL_ROLES:
            return False

        billet_clearance = ""
        ontology = getattr(self._runtime, "ontology", None)
        try:
            billet_clearance = resolve_billet_clearance(agent_type, ontology)
        except Exception:
            logger.debug("AD-635: billet clearance lookup failed", exc_info=True)

        grants: list[Any] = []
        try:
            grants = resolve_active_grants(
                agent_id,
                getattr(self._runtime, "clearance_grant_store", None),
            )
        except Exception:
            logger.debug("AD-635: grant lookup failed", exc_info=True)

        rank = self._resolve_rank(agent_id)

        try:
            tier = effective_recall_tier(rank, billet_clearance, grants)
        except Exception:
            logger.debug("AD-635: tier resolution failed", exc_info=True)
            return False

        return tier in QUALIFYING_TIERS

    def _resolve_agent_type(self, agent_id: str) -> str:
        registry = getattr(self._runtime, "registry", None)
        if registry is None:
            return ""
        try:
            agent = registry.get(agent_id)
        except Exception:
            return ""
        if agent is None:
            return ""
        return getattr(agent, "agent_type", "") or ""

    def _resolve_rank(self, agent_id: str) -> Any:
        acm = getattr(self._runtime, "acm", None)
        if acm is None:
            return None
        try:
            profile = acm.get(agent_id)
        except Exception:
            return None
        if profile is None:
            return None
        return getattr(profile, "rank", None)

    def _record_audit(
        self,
        requester_agent_id: str,
        query_type: str,
        *,
        granted: bool,
        result_count: int,
        target_agent_id: str | None = None,
    ) -> None:
        entry: dict[str, Any] = {
            "ts": time.time(),
            "requester_agent_id": requester_agent_id,
            "query_type": query_type,
            "granted": bool(granted),
            "result_count": int(result_count),
        }
        if target_agent_id is not None:
            entry["target_agent_id"] = target_agent_id
        self._audit.append(entry)
```

---

## Section 2 — Public dream-history accessor on `EmergentDetector`

Add a small public accessor right after the existing `clear_dream_history` method (around line 256 in `src/probos/cognitive/emergent_detector.py`). Open/Closed: extend the owner; do not let consumers reach into the private deque.

### SEARCH

```python
    def clear_dream_history(self) -> None:
        """Clear stale dream report history.

        BF-178: After stasis recovery, pre-stasis dream baselines cause
        false consolidation anomalies. Clearing forces dream_min_history
        gate to re-apply, requiring fresh baseline accumulation.
        """
        self._dream_history.clear()
```

### REPLACE

```python
    def clear_dream_history(self) -> None:
        """Clear stale dream report history.

        BF-178: After stasis recovery, pre-stasis dream baselines cause
        false consolidation anomalies. Clearing forces dream_min_history
        gate to re-apply, requiring fresh baseline accumulation.
        """
        self._dream_history.clear()

    def recent_dreams(self, limit: int = 20) -> list[dict]:
        """AD-635: Public read accessor over the dream-report ring buffer.

        Returns up to `limit` most-recent dream reports as a list of dicts.
        Most recent last (FIFO order matches deque iteration). Returns a
        new list each call — callers may mutate without affecting state.
        """
        if limit <= 0:
            return []
        if limit >= len(self._dream_history):
            return list(self._dream_history)
        return list(self._dream_history)[-limit:]
```

---

## Section 3 — Pydantic config

Add a new `ClinicalTelemetryConfig` immediately before `class CommunicationsConfig` (after `CognitiveJournalConfig` at `config.py:1739`).

### SEARCH

```python
class CognitiveJournalConfig(BaseModel):
    """Cognitive Journal — append-only LLM reasoning trace store (AD-431)."""
    enabled: bool = True
    retention_days: int = 14         # Keep journal entries for N days (0 = keep forever)
    max_rows: int = 500_000          # Hard cap on total rows (0 = no cap)
    prune_interval_seconds: float = 3600.0


class CommunicationsConfig(BaseModel):
```

### REPLACE

```python
class CognitiveJournalConfig(BaseModel):
    """Cognitive Journal — append-only LLM reasoning trace store (AD-431)."""
    enabled: bool = True
    retention_days: int = 14         # Keep journal entries for N days (0 = keep forever)
    max_rows: int = 500_000          # Hard cap on total rows (0 = no cap)
    prune_interval_seconds: float = 3600.0


class ClinicalTelemetryConfig(BaseModel):
    """AD-635 v1: Clearance-gated clinical query facade (Medical / Counselor).

    Disabled by default — Captain opts in via YAML. v1 is read-only, has no
    automatic invocation, and surfaces nothing at runtime until a clinical
    agent invokes a query method on `runtime.clinical_telemetry`.
    """
    enabled: bool = False
    audit_max_entries: int = 1000


class CommunicationsConfig(BaseModel):
```

Then add the SystemConfig field. Insert immediately after the `diagnostic_context` Field:

### SEARCH

```python
    diagnostic_context: DiagnosticContextConfig = Field(
        default_factory=DiagnosticContextConfig
    )  # AD-661
    knowledge_loading: KnowledgeLoadingConfig = KnowledgeLoadingConfig()  # AD-585
```

### REPLACE

```python
    diagnostic_context: DiagnosticContextConfig = Field(
        default_factory=DiagnosticContextConfig
    )  # AD-661
    clinical_telemetry: ClinicalTelemetryConfig = Field(
        default_factory=ClinicalTelemetryConfig
    )  # AD-635
    knowledge_loading: KnowledgeLoadingConfig = KnowledgeLoadingConfig()  # AD-585
```

---

## Section 4 — Wirer in `startup/finalize.py`

Append a new wirer after `_wire_diagnostic_context`. Use `getattr(runtime, "_emergent_detector", None)` since the runtime stores it privately (documented Demeter exception — see Section 0).

### SEARCH

```python
def _wire_diagnostic_context(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-661 v1: Wire DiagnosticContextService pull-based assembly service."""
    cfg = getattr(config, "diagnostic_context", None)
    if not cfg or not cfg.enabled:
        return False

    from probos.cognitive.diagnostic_context import DiagnosticContextService

    runtime.diagnostic_context_service = DiagnosticContextService(
        runtime,
        default_budget_tokens=cfg.default_budget_tokens,
        chain_trace_ratio=cfg.chain_trace_ratio,
        procedure_ratio=cfg.procedure_ratio,
        episode_ratio=cfg.episode_ratio,
        chars_per_token=cfg.chars_per_token,
    )
    logger.info(
        "AD-661: DiagnosticContextService v1 initialized "
        "(pull-based, keyword-only, budget=%d)",
        cfg.default_budget_tokens,
    )
    return True
```

### REPLACE

```python
def _wire_diagnostic_context(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-661 v1: Wire DiagnosticContextService pull-based assembly service."""
    cfg = getattr(config, "diagnostic_context", None)
    if not cfg or not cfg.enabled:
        return False

    from probos.cognitive.diagnostic_context import DiagnosticContextService

    runtime.diagnostic_context_service = DiagnosticContextService(
        runtime,
        default_budget_tokens=cfg.default_budget_tokens,
        chain_trace_ratio=cfg.chain_trace_ratio,
        procedure_ratio=cfg.procedure_ratio,
        episode_ratio=cfg.episode_ratio,
        chars_per_token=cfg.chars_per_token,
    )
    logger.info(
        "AD-661: DiagnosticContextService v1 initialized "
        "(pull-based, keyword-only, budget=%d)",
        cfg.default_budget_tokens,
    )
    return True


def _wire_clinical_telemetry(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-635 v1: Wire ClinicalTelemetryService clearance-gated query facade."""
    cfg = getattr(config, "clinical_telemetry", None)
    if not cfg or not cfg.enabled:
        return False

    from probos.cognitive.clinical_telemetry import ClinicalTelemetryService

    runtime.clinical_telemetry = ClinicalTelemetryService(
        runtime,
        audit_max_entries=cfg.audit_max_entries,
    )
    logger.info(
        "AD-635: ClinicalTelemetryService v1 initialized "
        "(2 domains: dream_history + chain_traces; clearance gate FULL+)"
    )
    return True
```

Then register the wirer in `finalize_startup`. Insert immediately after the `_wire_diagnostic_context` invocation block at `finalize.py:569`.

### SEARCH

```python
    if _wire_diagnostic_context(runtime=runtime, config=config):
        logger.info("AD-661: DiagnosticContextService v1 wired during finalization")

    if _wire_workspace_ontology(runtime=runtime, config=config):
        logger.info("AD-478: WorkspaceOntologyRegistry v1 wired during finalization")
```

### REPLACE

```python
    if _wire_diagnostic_context(runtime=runtime, config=config):
        logger.info("AD-661: DiagnosticContextService v1 wired during finalization")

    if _wire_clinical_telemetry(runtime=runtime, config=config):
        logger.info("AD-635: ClinicalTelemetryService v1 wired during finalization")

    if _wire_workspace_ontology(runtime=runtime, config=config):
        logger.info("AD-478: WorkspaceOntologyRegistry v1 wired during finalization")
```

---

## Section 5 — Tests `tests/test_ad635_clinical_telemetry.py`

Create a new test file. 8 focused tests (over the 7 floor by 1).

```python
"""AD-635 v1: Clinical Telemetry Query Facade — clearance-gated read-only access."""

from __future__ import annotations

import collections
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.clinical_telemetry import (
    CLINICAL_ROLES,
    QUALIFYING_TIERS,
    ClinicalTelemetryService,
)
from probos.cognitive.emergent_detector import EmergentDetector
from probos.config import ClinicalTelemetryConfig, SystemConfig
from probos.earned_agency import RecallTier
from probos.startup.finalize import _wire_clinical_telemetry


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _make_runtime(
    *,
    agents: dict[str, str] | None = None,    # agent_id -> agent_type
    journal_traces: list[dict] | None = None,
    journal_raises: bool = False,
    detector_dreams: list[dict] | None = None,
    has_detector: bool = True,
):
    """Build a minimal runtime stub for the service tests."""
    agents = agents or {}

    class _Reg:
        def get(self, aid):  # noqa: D401
            atype = agents.get(aid)
            if atype is None:
                return None
            return SimpleNamespace(agent_type=atype)

    class _Ont:
        # Map agent_type -> Post.clearance via the live mapping.
        _MAP = {"diagnostician": "FULL", "counselor": "ORACLE"}

        def get_post_for_agent(self, agent_type):
            cl = self._MAP.get(agent_type)
            if cl is None:
                return None
            return SimpleNamespace(clearance=cl)

    journal = AsyncMock()
    if journal_raises:
        journal.get_recent_chain_traces = AsyncMock(side_effect=RuntimeError("boom"))
    else:
        journal.get_recent_chain_traces = AsyncMock(
            return_value=list(journal_traces or [])
        )

    runtime = SimpleNamespace(
        registry=_Reg(),
        ontology=_Ont(),
        cognitive_journal=journal,
        clearance_grant_store=None,
        acm=None,
    )
    if has_detector:
        det = SimpleNamespace(
            recent_dreams=lambda limit=20: list(detector_dreams or [])[-limit:],
        )
        runtime._emergent_detector = det
    return runtime


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------

def test_service_shape_and_module_constants():
    """Service exposes the two query methods + audit_log; constants are correct."""
    rt = _make_runtime()
    svc = ClinicalTelemetryService(rt, audit_max_entries=5)
    assert hasattr(svc, "query_dream_history")
    assert hasattr(svc, "query_agent_chain_traces")
    assert svc.audit_log == []
    # Audit ring is bounded.
    assert isinstance(svc._audit, collections.deque)
    assert svc._audit.maxlen == 5
    assert CLINICAL_ROLES == frozenset({"diagnostician", "counselor"})
    assert QUALIFYING_TIERS == frozenset({RecallTier.FULL, RecallTier.ORACLE})


@pytest.mark.asyncio
async def test_authorized_dream_query_returns_results():
    """Counselor (ORACLE) is authorized; query returns dream rows; audit granted=True."""
    dreams = [{"id": "d1"}, {"id": "d2"}, {"id": "d3"}]
    rt = _make_runtime(
        agents={"echo-1": "counselor"},
        detector_dreams=dreams,
    )
    svc = ClinicalTelemetryService(rt)
    out = await svc.query_dream_history(requester_agent_id="echo-1", limit=20)
    assert out == dreams
    assert svc.audit_log[-1]["granted"] is True
    assert svc.audit_log[-1]["query_type"] == "dream_history"
    assert svc.audit_log[-1]["result_count"] == 3


@pytest.mark.asyncio
async def test_unauthorized_dream_query_returns_empty(caplog):
    """Non-clinical agent_type: returns []; logs warning; audit granted=False."""
    rt = _make_runtime(agents={"sci-1": "scientist"})
    svc = ClinicalTelemetryService(rt)
    with caplog.at_level("WARNING"):
        out = await svc.query_dream_history(requester_agent_id="sci-1")
    assert out == []
    assert svc.audit_log[-1]["granted"] is False
    assert any("AD-635" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_authorized_chain_traces_passes_target_agent_id():
    """Diagnostician (FULL) querying another agent passes target agent_id to journal."""
    traces = [{"chain_id": "c1", "agent_id": "engineer-7"}]
    rt = _make_runtime(
        agents={"chapel-1": "diagnostician"},
        journal_traces=traces,
    )
    svc = ClinicalTelemetryService(rt)
    out = await svc.query_agent_chain_traces(
        requester_agent_id="chapel-1",
        target_agent_id="engineer-7",
        limit=10,
    )
    assert out == traces
    rt.cognitive_journal.get_recent_chain_traces.assert_awaited_once_with(
        limit=10, agent_id="engineer-7"
    )
    last = svc.audit_log[-1]
    assert last["granted"] is True
    assert last["target_agent_id"] == "engineer-7"
    assert last["result_count"] == 1


@pytest.mark.asyncio
async def test_unauthorized_chain_traces_returns_empty():
    """Unknown agent (no registry entry): returns []; audit granted=False."""
    rt = _make_runtime(agents={})  # registry returns None
    svc = ClinicalTelemetryService(rt)
    out = await svc.query_agent_chain_traces(
        requester_agent_id="ghost",
        target_agent_id="engineer-7",
    )
    assert out == []
    assert svc.audit_log[-1]["granted"] is False
    # Journal is never called when authorization fails.
    rt.cognitive_journal.get_recent_chain_traces.assert_not_awaited()


@pytest.mark.asyncio
async def test_chain_traces_journal_failure_log_and_degrade(caplog):
    """Journal raises: returns []; warning logged; audit granted=True (gate passed)."""
    rt = _make_runtime(
        agents={"chapel-1": "diagnostician"},
        journal_raises=True,
    )
    svc = ClinicalTelemetryService(rt)
    with caplog.at_level("WARNING"):
        out = await svc.query_agent_chain_traces(
            requester_agent_id="chapel-1",
            target_agent_id="engineer-7",
        )
    assert out == []
    assert any("AD-635" in r.message for r in caplog.records)
    last = svc.audit_log[-1]
    assert last["granted"] is True
    assert last["result_count"] == 0


@pytest.mark.asyncio
async def test_audit_ring_is_bounded():
    """audit_max_entries caps the ring; oldest entries are evicted."""
    rt = _make_runtime(agents={"echo-1": "counselor"})
    svc = ClinicalTelemetryService(rt, audit_max_entries=3)
    for _ in range(5):
        await svc.query_dream_history(requester_agent_id="echo-1", limit=1)
    assert len(svc.audit_log) == 3


def test_emergent_detector_recent_dreams_accessor():
    """EmergentDetector.recent_dreams returns most-recent N (FIFO order)."""
    det = EmergentDetector(max_history=10)
    for i in range(5):
        det._dream_history.append({"id": f"d{i}"})
    out = det.recent_dreams(limit=3)
    assert [d["id"] for d in out] == ["d2", "d3", "d4"]
    # limit larger than history returns full snapshot.
    assert det.recent_dreams(limit=99) == list(det._dream_history)
    # limit <= 0 returns [].
    assert det.recent_dreams(limit=0) == []
    # Returned list is a copy (mutation isolation).
    snap = det.recent_dreams(limit=10)
    snap.append({"id": "x"})
    assert "x" not in [d["id"] for d in det._dream_history]


def test_wirer_creates_runtime_attribute_when_enabled_and_no_op_when_disabled():
    """Wirer is a no-op when disabled; constructs runtime.clinical_telemetry when enabled."""
    rt_disabled = SimpleNamespace()
    cfg_disabled = SystemConfig()
    assert cfg_disabled.clinical_telemetry.enabled is False
    assert _wire_clinical_telemetry(runtime=rt_disabled, config=cfg_disabled) is False
    assert not hasattr(rt_disabled, "clinical_telemetry")

    rt_enabled = SimpleNamespace()
    cfg_enabled = SystemConfig(
        clinical_telemetry=ClinicalTelemetryConfig(
            enabled=True, audit_max_entries=42
        ),
    )
    assert _wire_clinical_telemetry(runtime=rt_enabled, config=cfg_enabled) is True
    assert isinstance(rt_enabled.clinical_telemetry, ClinicalTelemetryService)
    assert rt_enabled.clinical_telemetry._audit.maxlen == 42
```

---

## What This Does NOT Change

| Out | Where it lives next |
|---|---|
| Consolidation anomaly audit trail (no shipped substrate today) | AD-635b |
| Circuit breaker state history (only current state at `/api/system/circuit-breakers`; no trip history persisted) | AD-635c |
| REST endpoints (`/api/clinical/*`) | AD-635d |
| Shell command (`/clinical` or `/medbay`) | AD-635e |
| Proactive context injection for clinical agents (parallels AD-630 subordinate stats) | AD-635f |
| Audit log persistence (currently in-memory only) | AD-635b |
| Public `runtime.emergent_detector` property (Demeter follow-up) | AD-635-cleanup |
| New EventType emission on query | future |
| Counselor / Diagnostician agent-side auto-invocation hooks | AD-635f |
| HXI surface for clinical telemetry | future |

---

## Tracking Updates

- **PROGRESS.md** — flip `AD-635 SCOPED ...` to `AD-635 v1 CLOSED ...` at line 329 with the closure summary.
- **`docs/development/roadmap.md`** — flip the AD-635 status line at 5880 from SCOPED to v1 CLOSED.
- **DECISIONS.md** — append a v1 closure note under the existing AD-635 entry (do not rewrite).

---

## Acceptance Criteria

1. Full parallel gate green at `pytest tests/ -q -n 8 --dist=loadfile`.
2. Test-count delta exactly +8 vs Wave 34 baseline 10957 → **expected 10965**.
3. New file `src/probos/cognitive/clinical_telemetry.py` (~280 lines).
4. New public method `EmergentDetector.recent_dreams(limit=20)` — only addition to that class.
5. New `ClinicalTelemetryConfig` and `SystemConfig.clinical_telemetry` field (default-False; v1 invisible at runtime out-of-box).
6. New wirer `_wire_clinical_telemetry` registered in `finalize_startup` immediately after `_wire_diagnostic_context`.
7. New test file `tests/test_ad635_clinical_telemetry.py` with 8 passing tests.
8. No changes to AD-588 IntrospectiveTelemetryService, AD-661 DiagnosticContextService, or any other shipped surface.
9. Issue #231 closes on merge.
10. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
