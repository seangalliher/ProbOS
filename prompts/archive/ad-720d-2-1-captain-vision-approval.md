# AD-720d-2.1 — Captain approval flow for `vision_capable` enablement (propose-and-approve)

**Wave:** 162
**Closes:** #645
**Status:** ready to build
**Dependencies:** AD-720d-2 (Wave 154 — static-default `vision_capable` field shipped); AD-718a (voice-profile proposal flow pattern shipped); AD-721d-1 (DSL approval flow pattern shipped Wave 145).
**Estimated tests:** +8 pytest.
**Scope tag:** Server-only. No new pip/npm deps. Apache 2.0. UI follow-up filed as forward marker AD-720d-2.1a.

---

## Problem

AD-720d-2 (Wave 154, #564) shipped a static-default `vision_capable: bool = False` field on [src/probos/crew_profile.py](src/probos/crew_profile.py#L296) `CrewProfile`. Counselor + Architect seed-defaulted to `True` via `config/standing_orders/crew_profiles/*.yaml`. v1 is config-driven: an agent is either born vision-capable (yaml says so) or it isn't (no runtime path to flip the bit).

This AD adds the **Captain-mediated propose-and-approve** flow, mirroring the AD-718a / AD-721d-1 pattern: the agent requests vision capability at runtime, the Captain approves or denies, and on approval the `CrewProfile.vision_capable` flips to `True` for that agent.

---

## Solution overview

1. New API model `VisionCapabilityProposal` (rationale string, ≤280 chars) + `VisionCapabilityApproval` (approve/deny + optional reason).
2. New endpoints under `routers/agents.py`:
   - `POST /agents/{agent_id}/vision-capability/propose` — agent emits a request.
   - `POST /agents/{agent_id}/vision-capability/approve` — Captain approves; flips `vision_capable=True` in the registry.
   - `POST /agents/{agent_id}/vision-capability/deny` — Captain denies; records the denial in the proposal-history sidecar.
3. Persist `vision_capable` changes to the runtime registry via `CallsignRegistry.set_vision_capable(agent_id, value, reason)` (new public method on the registry).
4. Optional `vision-capability-history` endpoint to surface prior proposals (mirrors AD-721d-1 `appearance/proposal-history`).
5. The existing `routers/agents.py:agent_chat` gate at the `if image_ids:` block (line 1346) ALREADY consults `vision_capable` per AD-720d-2 — no change needed at the chat gate.

### What this does NOT change

- The `CrewProfile.vision_capable` schema (still `bool`, default `False`).
- The static-yaml seed path (operators can still pre-seed at boot).
- The chat-time vision routing in `routers/agents.py:agent_chat` — the gate is already there and reads from the registry.
- The vision tier itself (AD-732).
- AD-731 attachment-ref invariant (image bytes still flow through `AttachmentStore` SHA-256 refs).

---

## Section 1 — API models (`src/probos/api_models.py`)

Add after the existing AD-721d-1 `RequestAppearanceRevision` block:

```python
# ── Vision-capability proposal models (AD-720d-2.1) ──────────────
class ProposeVisionCapability(BaseModel):
    """AD-720d-2.1: agent requests vision capability.

    Rationale must be non-empty and ≤280 chars — matches AD-718a / AD-721d-1
    Captain-note budget. Pattern: 'I have started receiving image-bearing DMs
    from the Captain; vision capability would let me reason over them.'
    """
    rationale: str = Field(..., min_length=1, max_length=280)


class VisionCapabilityProposalResponse(BaseModel):
    """AD-720d-2.1: response to a propose call."""
    agent_id: str
    rationale: str
    proposal_id: str  # uuid, stored for later approve/deny correlation
    proposed_at: float  # unix epoch


class ApproveVisionCapability(BaseModel):
    """AD-720d-2.1: Captain approve/deny payload."""
    approve: bool
    reason: str = Field(default="", max_length=280)
```

Pydantic v2 mutable defaults: `Field(default="", max_length=280)` is safe (str is immutable).

---

## Section 2 — `CallsignRegistry.set_vision_capable`

In `src/probos/crew_profile.py`, add a public method on `CallsignRegistry` (the class that owns the `_type_to_profile` map at line 534):

```python
def set_vision_capable(
    self,
    agent_id: str,
    value: bool,
    *,
    reason: str = "",
) -> bool:
    """AD-720d-2.1: flip `vision_capable` for a specific agent_id.

    Returns True if the registry entry was updated, False if the agent_id
    is unknown. Idempotent — setting to the same value returns True with
    no side effect.

    Reason is logged at INFO level for audit; does not flow into trust or
    Hebbian (this is an authorization grant, not a behavior observation).
    """
    profile_dict = self._lookup_by_agent_id(agent_id)  # use existing private lookup
    if profile_dict is None:
        return False
    prior = bool(profile_dict.get("vision_capable", False))
    profile_dict["vision_capable"] = bool(value)
    logger.info(
        "AD-720d-2.1: vision_capable flipped for agent_id=%s prior=%s new=%s reason=%r",
        agent_id, prior, bool(value), reason,
    )
    return True
```

Builder: verify the exact name of the private "lookup by agent_id" path on `CallsignRegistry` before writing — `_lookup_by_agent_id` is illustrative. Read lines 534-580 to find the real signature. The method MUST use an existing public/private accessor; do NOT introduce a new private-attr reach-through (Demeter principle).

---

## Section 3 — Persistence sidecar

Mirror the AD-721d-1 `proposal_history.py` pattern. Add `src/probos/avatars/vision_proposal_history.py` (NEW FILE):

```python
"""AD-720d-2.1: in-memory + on-disk vision-capability proposal history."""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VisionProposalEntry:
    proposal_id: str
    agent_id: str
    rationale: str
    proposed_at: float
    resolved_at: float | None = None
    resolution: str | None = None  # "approved" | "denied"
    resolution_reason: str = ""


# Module-level state — matches AD-721d-1 proposal_history.py shape.
_entries: list[VisionProposalEntry] = []
_lock = RLock()
_path: Path | None = None


def configure(path: Path | None) -> None:
    """Bind on-disk sidecar (called once at startup from runtime.py)."""
    global _path
    with _lock:
        _path = path
        if path is not None and path.exists():
            _load_from_disk()


def append(entry: VisionProposalEntry) -> None:
    with _lock:
        _entries.append(entry)
        _persist()


def resolve(proposal_id: str, resolution: str, reason: str) -> VisionProposalEntry | None:
    with _lock:
        for idx, e in enumerate(_entries):
            if e.proposal_id == proposal_id and e.resolved_at is None:
                resolved = VisionProposalEntry(
                    proposal_id=e.proposal_id,
                    agent_id=e.agent_id,
                    rationale=e.rationale,
                    proposed_at=e.proposed_at,
                    resolved_at=time.time(),
                    resolution=resolution,
                    resolution_reason=reason,
                )
                _entries[idx] = resolved
                _persist()
                return resolved
        return None


def list_for_agent(agent_id: str) -> list[VisionProposalEntry]:
    with _lock:
        return [e for e in _entries if e.agent_id == agent_id]


def _persist() -> None:
    """Atomic write — matches AD-721d-4 sidecar persistence pattern."""
    if _path is None:
        return
    tmp = _path.with_suffix(_path.suffix + ".tmp")
    payload = [{k: getattr(e, k) for k in e.__dataclass_fields__} for e in _entries]
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(_path)


def _load_from_disk() -> None:
    global _entries
    try:
        raw = json.loads(_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        logger.warning(
            "AD-720d-2.1: failed to load vision proposal history from %s",
            _path, exc_info=True,
        )
        _entries = []
        return
    _entries = [VisionProposalEntry(**row) for row in raw]
```

Add `import logging` at the top.

---

## Section 4 — Config entry (`AvatarsConfig` or `AttachmentsConfig`?)

Add to `AvatarsConfig` (already hosts `proposal_history_path` per AD-721d-4):

```python
# AD-720d-2.1: on-disk sidecar for vision-capability proposal history.
vision_proposal_history_path: Path | None = None
```

Default-OFF (path None means in-memory only; runtime.py wires the real path).

---

## Section 5 — Wire from `runtime.py`

After the AD-721d-4 `proposal_history.configure(...)` call, add:

```python
from probos.avatars import vision_proposal_history

_vis_path = self.config.avatars.vision_proposal_history_path
if _vis_path is None:
    _vis_path = self.data_dir / "vision_proposal_history.json"
vision_proposal_history.configure(_vis_path)
```

Builder: verify the exact insertion point matches the AD-721d-4 wiring location in `runtime.py`. Read the AD-721d-4 commit hash from the roadmap and grep `runtime.py` for "proposal_history.configure" — insert immediately after.

---

## Section 6 — Three new endpoints in `routers/agents.py`

Pattern: mirror the AD-721d-1 `/appearance/propose` shape exactly. Three handlers:

```python
@router.post(
    "/{agent_id}/vision-capability/propose",
    response_model=VisionCapabilityProposalResponse,
)
async def propose_vision_capability(
    agent_id: str,
    req: ProposeVisionCapability,
    runtime: Any = Depends(get_runtime),
) -> VisionCapabilityProposalResponse:
    entry = VisionProposalEntry(
        proposal_id=str(uuid.uuid4()),
        agent_id=agent_id,
        rationale=req.rationale,
        proposed_at=time.time(),
    )
    vision_proposal_history.append(entry)
    # Emit event for HXI awareness (mirrors AD-721d-1 event emit).
    # AD-680: `runtime.emit_event` is a stable public method
    # (`runtime.py:1050`) — call directly, no hasattr guard.
    runtime.emit_event(
        EventType.VISION_CAPABILITY_PROPOSED,
        {"agent_id": agent_id, "proposal_id": entry.proposal_id,
         "rationale": req.rationale},
    )
    return VisionCapabilityProposalResponse(
        agent_id=agent_id,
        rationale=req.rationale,
        proposal_id=entry.proposal_id,
        proposed_at=entry.proposed_at,
    )


@router.post("/{agent_id}/vision-capability/approve")
async def approve_vision_capability(
    agent_id: str,
    proposal_id: str,
    req: ApproveVisionCapability,
    runtime: Any = Depends(get_runtime),
):
    resolution = "approved" if req.approve else "denied"
    resolved = vision_proposal_history.resolve(
        proposal_id, resolution, req.reason
    )
    if resolved is None:
        raise HTTPException(404, "proposal_id not found or already resolved")
    if req.approve:
        ok = runtime.callsign_registry.set_vision_capable(
            agent_id, True, reason=req.reason,
        )
        if not ok:
            raise HTTPException(404, "agent_id unknown")
    runtime.emit_event(
        EventType.VISION_CAPABILITY_RESOLVED,
        {"agent_id": agent_id, "proposal_id": proposal_id,
         "approved": req.approve, "reason": req.reason},
    )
    return {"ok": True, "resolution": resolution}
```

A separate `deny` endpoint is NOT needed — `approve` with `approve=False` covers it (matches AD-721d-1 single-endpoint shape with approve/deny in the body).

Add two new `EventType` enum values: `VISION_CAPABILITY_PROPOSED`, `VISION_CAPABILITY_RESOLVED` in `src/probos/events.py`. (This AD introduces them — do NOT flag as missing in pre-review.)

---

## Tests

`tests/test_ad720d_2_1_vision_approval.py` — 8 tests, all using real `SystemConfig()` per AD-722b-1a (no MagicMock):

1. `test_propose_creates_entry` — POST propose returns proposal_id, history sidecar grows by 1.
2. `test_approve_flips_registry` — propose then approve; `registry.get_profile(agent_id)["vision_capable"]` is True.
3. `test_deny_leaves_registry` — propose then approve(approve=False); registry still False.
4. `test_approve_unknown_proposal_404`.
5. `test_approve_already_resolved_404` — double-approve returns 404.
6. `test_history_persists_across_configure` — write entries, re-configure with same path, entries load.
7. `test_rationale_length_validation` — 281-char rationale → 422.
8. `test_chat_gate_respects_runtime_flip` — agent receives image attachment, gate respects the live registry state, not the boot-time yaml.

---

## Tracking

- `PROGRESS.md` — Wave 162 bullet.
- `docs/development/roadmap.md` — flip AD-720d-2.1 row to SHIPPED Wave 162; file forward markers AD-720d-2.1a (HXI UI surface for Captain pending-approval list) + AD-720d-2.1b (auto-deny TTL when Captain unresponsive for >N hours — technical trigger: when ProbOS adopts an autonomous-Captain mode).
- `DECISIONS.md` — append entry.

---

## Acceptance criteria

- Three new endpoints land in `routers/agents.py`.
- `CallsignRegistry.set_vision_capable` public method exists; no private-attr reach-through.
- `vision_proposal_history.py` mirrors AD-721d-4 sidecar pattern (atomic write, RLock, configure-at-startup).
- Two new `EventType` enum values registered.
- 8 new pytest tests green at `-n 0` and `-n 4 --dist=loadfile`.
- AD-731 invariant preserved — no image bytes touch this AD's code path.
- No new pip/npm deps.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-15)

- `src/probos/crew_profile.py:296` — `vision_capable: bool = False` field confirmed.
- `src/probos/crew_profile.py:534` — `CallsignRegistry._type_to_profile` dict confirmed.
- `src/probos/crew_profile.py:567-570` — AD-720d-2 surface-on-registry path confirmed.
- `src/probos/routers/agents.py:1346` — `if image_ids:` gate confirmed (the existing chat-time consumer; this AD does not touch the gate, only the data the gate reads).
- `src/probos/api_models.py:269-294` — AD-721d / AD-721d-1 proposal shapes confirmed (pattern reference).
- `src/probos/avatars/proposal_history.py` — AD-721d-1 + AD-721d-4 sidecar persistence pattern confirmed (pattern reference for new vision_proposal_history.py).
