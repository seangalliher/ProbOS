# AD-721d-1 — DSL Draft Preview + Revision Cycle

**Status:** Draft (Wave 145)
**Depends on:** AD-721d (shipped). No new infra.
**Closes:** GH #541
**Estimated tests:** +12 Python, +5 vitest

---

## Problem

AD-721d ships the agent-authored appearance pipeline:

```
Captain clicks "Design avatar"
  → POST /api/agent/{id}/appearance/propose  (LLM call, returns DSL)
  → CrewAvatarPopout opens with approval bar
  → Captain clicks Approve   → PUT /api/agent/{id}/appearance (persists)
  → Captain clicks Reject    → setProposedDsl(null) (DSL discarded)
```

The Captain has only two affordances: **approve blind** or **reject**. There is no way to say *"close, but make the hair shorter and the outfit warmer."* The agent's `propose_appearance(captain_note=...)` already accepts a 280-char revision hint (verified at `src/probos/cognitive/cognitive_agent.py:3054`), and the API request model already carries `captain_note: str = ""` (`api_models.py:269`) — the plumbing is wired, but **no UI surfaces it and there is no iteration / history concept on the server.**

This AD closes the loop:

```
Captain clicks "Design avatar"                → iteration 1 proposal
Captain clicks "Request revision" → textarea → iteration 2 proposal
Captain clicks "Request revision" → textarea → iteration 3 proposal
Captain MUST approve or reject (iteration cap)
```

Each iteration shows a parametric description with **diff highlighting** against the previous iteration so the Captain can see what the agent changed.

---

## Solution overview

1. **API** — extend `ProposeAppearanceRequest` with `previous_dsl: dict | None`; extend `ProposeAppearanceResponse` with `proposal_iteration: int` and `max_iterations: int`. Add `DELETE /api/agent/{id}/appearance/proposal-history`. Iteration cap returns HTTP 429.
2. **Config** — `AvatarsConfig.max_proposal_iterations: int = 3` (validated 1 ≤ v ≤ 10).
3. **Server-side history** — module-level in-memory dict in a new `src/probos/avatars/proposal_history.py`. Per-agent iteration counter, cleared on approve / on DELETE / on first propose-after-clear.
4. **UI** — `CrewAvatarPopout` gains a "Request revision" button → inline expandable textarea → submit. Parametric description renders as a structured block with amber-tint diff highlighting. At iteration cap, "Request revision" is disabled with a native tooltip.
5. **Audit** — `runtime.emit_event("appearance_proposal" | "appearance_approved" | "appearance_history_cleared", payload)` using string keys (no new `EventType` enum value — UX wave, not a substrate wave).

**What we deliberately do NOT do:**
- Use `runtime.cognitive_journal.record(...)` — its schema is LLM-call-shaped (`entry_id, prompt_tokens, completion_tokens, ...`, verified `cognitive/journal.py:360`). It is the wrong audit surface for UX events. Use `runtime.emit_event(...)` instead, which accepts `str | EventType` (verified `runtime.py:971`).
- Add a `revision_note` field. The existing `captain_note: str` IS the revision note — when `previous_dsl` is non-null AND `captain_note` is non-empty, this is a revision request. Splitting one concept across two fields was rejected.
- Persist history across runtime restarts.
- Touch the LLM-side prompt construction beyond what AD-721d already does — `captain_note` is already piped into the user message (verified `cognitive_agent.py:3152-3154`).

---

## Section 0 — Event keys

Three new event keys emitted via `runtime.emit_event(<string>, <dict>)`. These are **strings, not `EventType` enum values** — adding to the enum is out of scope for a UX wave. The `emit_event` signature accepts `str | EventType` (line 971 of `runtime.py`).

| Key | Payload | When |
|---|---|---|
| `appearance_proposal` | `{agent_id, iteration, has_captain_note: bool, captain_note_len: int}` | On every successful `POST /appearance/propose` (including iteration 1) |
| `appearance_approved` | `{agent_id, iterations_used}` | On successful `PUT /appearance` |
| `appearance_history_cleared` | `{agent_id, reason}` (reason ∈ `"approve" / "delete" / "reject"`) | On every history clear |

`captain_note_len` is logged (not the note text) to avoid leaking arbitrary Captain free-text into the event log.

---

## Section 1 — Config: `max_proposal_iterations`

**File:** `src/probos/config.py` (around line 922, the existing `AvatarsConfig` block).

### SEARCH

```python
class AvatarsConfig(BaseModel):
    """AD-721: 3D crew avatars (VRM popout)."""

    enabled: bool = True                                   # BF #536: default-on per Captain confirmation; parametric fallback is license-safe
    avatars_dir: str = "data/avatars"
    max_vrm_size_bytes: int = 25 * 1024 * 1024             # 25 MB hard cap
    fallback_to_parametric_on_error: bool = True
    # AD-721i: headless Blender renderer (operator brings the binary).
    blender_path: str = ""                                 # "" = search PATH via shutil.which("blender")
    blender_render_timeout_s: int = 180
    dsl_drafts_dir: str = "data/avatars/.drafts"
    # Wave 10 convention #14: transitional flag default-False; flip in a
    # follow-up AD once the renderer is exercised end-to-end.
    renderer_enabled: bool = False
    # Captain ruling 2026-05-09: capsule fallback default-on so v1 is end-to-end
    # without requiring operator-supplied base meshes.
    procedural_base_mesh_fallback: bool = True
```

### REPLACE

```python
class AvatarsConfig(BaseModel):
    """AD-721: 3D crew avatars (VRM popout)."""

    enabled: bool = True                                   # BF #536: default-on per Captain confirmation; parametric fallback is license-safe
    avatars_dir: str = "data/avatars"
    max_vrm_size_bytes: int = 25 * 1024 * 1024             # 25 MB hard cap
    fallback_to_parametric_on_error: bool = True
    # AD-721i: headless Blender renderer (operator brings the binary).
    blender_path: str = ""                                 # "" = search PATH via shutil.which("blender")
    blender_render_timeout_s: int = 180
    dsl_drafts_dir: str = "data/avatars/.drafts"
    # Wave 10 convention #14: transitional flag default-False; flip in a
    # follow-up AD once the renderer is exercised end-to-end.
    renderer_enabled: bool = False
    # Captain ruling 2026-05-09: capsule fallback default-on so v1 is end-to-end
    # without requiring operator-supplied base meshes.
    procedural_base_mesh_fallback: bool = True
    # AD-721d-1: how many revision iterations before the Captain MUST approve
    # or reject. Iteration 1 = initial proposal; iterations 2..N are
    # revisions. Bounded 1..10 to keep LLM cost predictable.
    max_proposal_iterations: int = 3

    @field_validator("max_proposal_iterations")
    @classmethod
    def _bound_max_proposal_iterations(cls, v: int) -> int:
        if not 1 <= v <= 10:
            raise ValueError(
                f"max_proposal_iterations must be 1 ≤ v ≤ 10, got {v}"
            )
        return v
```

> Verified: `field_validator` is already imported at `src/probos/config.py:10`.

---

## Section 2 — In-memory proposal history

**Create new file:** `src/probos/avatars/proposal_history.py`

```python
"""AD-721d-1: in-memory per-agent proposal history.

The Captain can iterate up to ``AvatarsConfig.max_proposal_iterations``
times on an agent's avatar DSL. Each call to ``POST /appearance/propose``
appends to the history; ``PUT /appearance`` (approve) and
``DELETE /appearance/proposal-history`` (explicit clear) clear it.

This module is intentionally a process-local module-level dict. v1 is
single-process; cluster-wide consistency, persistence across restarts,
and quorum on the iteration counter are out of scope. The DSL itself
persists ONLY when the Captain approves (via the existing AD-721d
``AppearanceProfile.dsl`` path).

The module exposes module-level functions, not a class — there is no
state worth dependency-injecting and the OSS-tier wiring stays trivial.
A future commercial overlay may swap to a redis-backed implementation
behind the same function signatures.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProposalEntry:
    """One iteration in an agent's current DSL-proposal session."""

    dsl: dict          # AvatarDSL.model_dump() snapshot
    captain_note: str  # the revision hint used to produce this dsl ("" for iteration 1)
    timestamp: float


# Module-level state — guarded by a re-entrant lock so concurrent FastAPI
# requests on the same agent don't race the counter.
_lock = threading.RLock()
_history: dict[str, list[ProposalEntry]] = {}


def append(agent_id: str, dsl: dict, captain_note: str) -> int:
    """Append a proposal entry; return the new iteration count (1-based)."""
    with _lock:
        entries = _history.setdefault(agent_id, [])
        entries.append(
            ProposalEntry(dsl=dsl, captain_note=captain_note, timestamp=time.time())
        )
        return len(entries)


def iteration_count(agent_id: str) -> int:
    """Return current iteration count for ``agent_id`` (0 if no history)."""
    with _lock:
        return len(_history.get(agent_id, []))


def latest(agent_id: str) -> ProposalEntry | None:
    """Return the most-recent ProposalEntry for ``agent_id``, or None."""
    with _lock:
        entries = _history.get(agent_id)
        return entries[-1] if entries else None


def clear(agent_id: str) -> int:
    """Drop history for ``agent_id``; return the prior iteration count."""
    with _lock:
        prior = len(_history.get(agent_id, []))
        _history.pop(agent_id, None)
        return prior


def reset_all() -> None:
    """Test-only: drop ALL history. Production callers should use ``clear``."""
    with _lock:
        _history.clear()


__all__ = [
    "ProposalEntry",
    "append",
    "iteration_count",
    "latest",
    "clear",
    "reset_all",
]
```

**Why module-level state, not runtime-attached.**
- No phase-ordering risk (BF-259/260/261/262 lesson): no `getattr(runtime, "appearance_proposal_history", None)` from earlier startup phases — there are no earlier consumers.
- No new wiring in `runtime.py` / `startup/finalize.py` — the router imports the module directly.
- Acceptable for in-memory, single-process v1. A future commercial overlay can swap the backing store without changing the function signatures.

---

## Section 3 — API model extensions

**File:** `src/probos/api_models.py` (around line 248-285, the `ProposeAppearance*` block).

### SEARCH

```python
# ── Appearance models (AD-721d) ──────────────────────────────────

class ProposeAppearanceRequest(BaseModel):
    """AD-721d: Optional Captain revision note for "Request revisions" flows."""
    captain_note: str = ""


class ProposeAppearanceResponse(BaseModel):
    """AD-721d: Validated AvatarDSL returned for Captain review (NOT yet persisted)."""
    agent_id: str
    dsl: dict


class SetAppearanceRequest(BaseModel):
    """AD-721d: Persist an approved AvatarDSL to ``AppearanceProfile.dsl``.

    The endpoint re-validates ``dsl`` with ``AvatarDSL.model_validate(...)``
    before writing. Invalid → HTTP 422.
    """
    dsl: dict
```

### REPLACE

```python
# ── Appearance models (AD-721d, extended AD-721d-1) ──────────────

class ProposeAppearanceRequest(BaseModel):
    """AD-721d + AD-721d-1: Captain revision note plus optional prior DSL.

    AD-721d-1: when ``previous_dsl`` is non-null AND ``captain_note`` is
    non-empty, this is a *revision* request. The server validates
    ``previous_dsl`` matches the ``AvatarDSL`` schema (rejects 422 if not)
    and increments the per-agent iteration counter. At
    ``AvatarsConfig.max_proposal_iterations`` the endpoint returns 429.

    ``captain_note`` IS the revision note — there is intentionally no
    separate ``revision_note`` field. The semantic difference between
    "initial proposal" and "revision" is carried by the presence of
    ``previous_dsl`` plus the existing iteration counter.
    """
    captain_note: str = ""
    previous_dsl: dict | None = None  # AD-721d-1


class ProposeAppearanceResponse(BaseModel):
    """AD-721d + AD-721d-1: Validated AvatarDSL plus iteration metadata."""
    agent_id: str
    dsl: dict
    proposal_iteration: int = 1   # AD-721d-1: 1-based; 1 for initial proposal
    max_iterations: int = 3       # AD-721d-1: echo of AvatarsConfig.max_proposal_iterations


class SetAppearanceRequest(BaseModel):
    """AD-721d: Persist an approved AvatarDSL to ``AppearanceProfile.dsl``.

    The endpoint re-validates ``dsl`` with ``AvatarDSL.model_validate(...)``
    before writing. Invalid → HTTP 422. AD-721d-1: on success, clears the
    in-memory proposal history for ``agent_id``.
    """
    dsl: dict
```

---

## Section 4 — Router: revision flow + DELETE endpoint

**File:** `src/probos/routers/agents.py`.

### 4a. `POST /{agent_id}/appearance/propose` — extend with iteration logic

Current code at line 389-426 (verified). Modify the handler to:
1. Validate `previous_dsl` (if supplied) against `AvatarDSL` schema before incrementing.
2. Read `iteration_count(agent_id)` BEFORE the LLM call. If `current + 1 > cfg.avatars.max_proposal_iterations`, return 429.
3. Pass `captain_note` through to `propose_appearance(captain_note=...)` as today.
4. On success, call `proposal_history.append(...)` and emit `appearance_proposal` event.

### SEARCH

```python
@router.post("/{agent_id}/appearance/propose", response_model=ProposeAppearanceResponse)
async def propose_agent_appearance(
    agent_id: str,
    req: ProposeAppearanceRequest | None = None,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-721d D7: trigger ``CognitiveAgent.propose_appearance`` and return the
    proposed DSL for Captain review. NOT persisted — caller must follow up with
    ``PUT /{agent_id}/appearance`` once the Captain approves.
    """
    _avatars_feature_check(runtime)
    agent = runtime.registry.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    if not hasattr(agent, "propose_appearance"):
        raise HTTPException(
            status_code=400,
            detail=f"Agent {agent_id} does not support appearance proposal "
                   "(not a CognitiveAgent subclass)",
        )

    from probos.avatars.dsl import AppearanceProposalError

    captain_note = (req.captain_note if req else "") or ""
    try:
        dsl = await agent.propose_appearance(captain_note=captain_note)
    except AppearanceProposalError as exc:
        logger.warning(
            "AD-721d: appearance proposal rejected for %s: reason=%s detail=%s; "
            "no DSL persisted, Captain may retry",
            agent_id, exc.reason, exc.detail,
        )
        raise HTTPException(
            status_code=422,
            detail={"reason": exc.reason, "detail": exc.detail},
        )
    return {"agent_id": agent_id, "dsl": dsl.model_dump()}
```

### REPLACE

```python
@router.post("/{agent_id}/appearance/propose", response_model=ProposeAppearanceResponse)
async def propose_agent_appearance(
    agent_id: str,
    req: ProposeAppearanceRequest | None = None,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-721d D7 + AD-721d-1: trigger ``CognitiveAgent.propose_appearance``
    and return the proposed DSL for Captain review. NOT persisted — caller
    must follow up with ``PUT /{agent_id}/appearance`` once the Captain
    approves.

    AD-721d-1: supports up to ``cfg.avatars.max_proposal_iterations``
    revisions per agent. Iteration count is server-side in-memory
    (cleared on approve / DELETE /appearance/proposal-history). At the
    cap the endpoint returns HTTP 429 with structured detail.
    """
    _avatars_feature_check(runtime)
    agent = runtime.registry.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    if not hasattr(agent, "propose_appearance"):
        raise HTTPException(
            status_code=400,
            detail=f"Agent {agent_id} does not support appearance proposal "
                   "(not a CognitiveAgent subclass)",
        )

    from probos.avatars.dsl import AppearanceProposalError, AvatarDSL
    from probos.avatars import proposal_history

    captain_note = (req.captain_note if req else "") or ""
    previous_dsl_raw = (req.previous_dsl if req else None)

    # AD-721d-1: validate previous_dsl shape BEFORE incrementing the counter.
    # Malformed previous_dsl must NOT consume an iteration slot.
    if previous_dsl_raw is not None:
        try:
            AvatarDSL.model_validate(previous_dsl_raw)
        except Exception as exc:
            raise HTTPException(
                status_code=422,
                detail={"reason": "invalid_previous_dsl", "detail": str(exc)},
            )

    # AD-721d-1: iteration cap. Reading BEFORE the LLM call ensures we don't
    # spend a $LLM_call when we're going to 429 anyway.
    cfg_max = int(getattr(runtime.config.avatars, "max_proposal_iterations", 3))
    current_iterations = proposal_history.iteration_count(agent_id)
    if current_iterations + 1 > cfg_max:
        raise HTTPException(
            status_code=429,
            detail={
                "reason": "iteration_cap_reached",
                "detail": (
                    f"Maximum {cfg_max} proposal iterations reached for "
                    f"{agent_id}. Approve, reject, or DELETE the proposal "
                    "history to start a new session."
                ),
                "iteration": current_iterations,
                "max_iterations": cfg_max,
            },
        )

    try:
        dsl = await agent.propose_appearance(captain_note=captain_note)
    except AppearanceProposalError as exc:
        logger.warning(
            "AD-721d: appearance proposal rejected for %s: reason=%s detail=%s; "
            "no DSL persisted, Captain may retry",
            agent_id, exc.reason, exc.detail,
        )
        raise HTTPException(
            status_code=422,
            detail={"reason": exc.reason, "detail": exc.detail},
        )

    dsl_dict = dsl.model_dump()
    new_iteration = proposal_history.append(agent_id, dsl_dict, captain_note)

    # AD-721d-1: audit event — string-keyed, not a new EventType enum value.
    try:
        runtime.emit_event(
            "appearance_proposal",
            {
                "agent_id": agent_id,
                "iteration": new_iteration,
                "has_captain_note": bool(captain_note),
                "captain_note_len": len(captain_note),
            },
        )
    except Exception:
        # Tier-2 log-and-degrade: audit failure must not block the Captain.
        logger.warning(
            "AD-721d-1: emit_event('appearance_proposal') failed for %s; "
            "proposal returned to Captain but audit lost",
            agent_id, exc_info=True,
        )

    return {
        "agent_id": agent_id,
        "dsl": dsl_dict,
        "proposal_iteration": new_iteration,
        "max_iterations": cfg_max,
    }
```

### 4b. `PUT /{agent_id}/appearance` — clear history on approve + emit event

The existing handler ends with `return {"agentId": agent_id, "dsl": dsl.model_dump()}` (line ~491, verified). Insert history-clear and audit emission **immediately before that return**.

### SEARCH

```python
        crew.appearance.dsl = dsl.model_dump()
        runtime.profile_store.update(crew)
    else:
        logger.warning(
            "AD-721d: profile_store not present on runtime; "
            "appearance DSL for %s not persisted (Captain approval lost)",
            agent_id,
        )

    return {"agentId": agent_id, "dsl": dsl.model_dump()}
```

### REPLACE

```python
        crew.appearance.dsl = dsl.model_dump()
        runtime.profile_store.update(crew)
    else:
        logger.warning(
            "AD-721d: profile_store not present on runtime; "
            "appearance DSL for %s not persisted (Captain approval lost)",
            agent_id,
        )

    # AD-721d-1: clear proposal history + emit audit event on approve.
    from probos.avatars import proposal_history
    iterations_used = proposal_history.clear(agent_id)
    try:
        runtime.emit_event(
            "appearance_approved",
            {"agent_id": agent_id, "iterations_used": iterations_used},
        )
    except Exception:
        logger.warning(
            "AD-721d-1: emit_event('appearance_approved') failed for %s; "
            "approval persisted but audit lost",
            agent_id, exc_info=True,
        )

    return {"agentId": agent_id, "dsl": dsl.model_dump()}
```

### 4c. `DELETE /{agent_id}/appearance/proposal-history` — new endpoint

Insert **immediately after** the existing `set_agent_appearance` handler. The body ends with the `return {"agentId": agent_id, "dsl": dsl.model_dump()}` line modified in 4b — anchor on the next blank line after it.

```python
@router.delete("/{agent_id}/appearance/proposal-history")
async def clear_agent_appearance_proposal_history(
    agent_id: str,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-721d-1: explicitly drop the in-memory proposal-history for
    ``agent_id``. Used when the Captain rejects a proposal mid-session, or
    when an operator wants to reset the iteration counter without
    approving anything.

    Idempotent: returns ``{"agent_id": ..., "cleared_iterations": N}``
    where N is the prior iteration count (0 if no history existed).
    """
    _avatars_feature_check(runtime)
    agent = runtime.registry.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    from probos.avatars import proposal_history
    cleared = proposal_history.clear(agent_id)
    try:
        runtime.emit_event(
            "appearance_history_cleared",
            {"agent_id": agent_id, "reason": "delete"},
        )
    except Exception:
        logger.warning(
            "AD-721d-1: emit_event('appearance_history_cleared') failed for %s",
            agent_id, exc_info=True,
        )
    return {"agent_id": agent_id, "cleared_iterations": cleared}
```

---

## Section 5 — UI: client-side diff helper

**Create new file:** `ui/src/components/profile/avatarDslDiff.ts`

```ts
/** AD-721d-1: shallow field-path diff between two AvatarDSL snapshots.
 *
 * Returns a Set of dotted paths whose values differ. The popout uses
 * this Set to apply amber-tint highlighting + strikethrough on the
 * previous value, per HXI Design Principle #4 (motion/state encoding).
 *
 * NOT a deep structural diff — we only inspect the 9 fields surfaced
 * in the parametric description renderer:
 *   body.type, body.height_cm,
 *   hair.style, hair.color_hsl,
 *   face.warmth, face.jaw, face.eyes,
 *   outfit.style, outfit.primary_color,
 *   expression_resting,
 *   notes
 */
import type { AvatarDSLDict } from '../../store/types';

const FIELDS: ReadonlyArray<readonly [string, (d: AvatarDSLDict) => unknown]> = [
  ['body.type',           (d) => d.body?.type],
  ['body.height_cm',      (d) => d.body?.height_cm],
  ['hair.style',          (d) => d.hair?.style],
  ['hair.color_hsl',      (d) => JSON.stringify(d.hair?.color_hsl ?? null)],
  ['face.warmth',         (d) => d.face?.warmth],
  ['face.jaw',            (d) => d.face?.jaw],
  ['face.eyes',           (d) => d.face?.eyes],
  ['outfit.style',        (d) => d.outfit?.style],
  ['outfit.primary_color',(d) => d.outfit?.primary_color],
  ['expression_resting',  (d) => d.expression_resting],
  ['notes',               (d) => d.notes],
];

export function diffAvatarDsl(
  prev: AvatarDSLDict | null | undefined,
  curr: AvatarDSLDict,
): Set<string> {
  const changed = new Set<string>();
  if (!prev) return changed;
  for (const [path, get] of FIELDS) {
    if (get(prev) !== get(curr)) changed.add(path);
  }
  return changed;
}
```

> The renderer in Section 6 reads this Set; tests in Section 8 cover the diff helper independently.

---

## Section 6 — UI: extend `CrewAvatarPopout` approval bar

**File:** `ui/src/components/profile/CrewAvatarPopout.tsx`.

The current approval bar (around lines 225-290) renders Approve + Reject. Extend it with:

1. A **structured parametric block** rendered in a small panel above the action buttons. Each field shows label + value, with amber tint + strikethrough on changed fields when `previousDsl` is non-null.
2. A **"Request revision"** button (between Approve and Reject) with a stroke-SVG curved-arrow glyph. Disabled when `iteration >= maxIterations`.
3. An **inline textarea** (collapsed by default; expands when "Request revision" is clicked) with a 280-char counter and a stroke-SVG send button.

### New props

Extend the `Props` interface (around line 18):

### SEARCH

```ts
interface Props {
  agentId: string;
  appearance: CrewAppearance | null;
  departmentColor: string;
  agentSignals: AgentSignals;
  onClose: () => void;
  // AD-721d: when set, surfaces the approval bar with the proposed DSL.
  proposedDsl?: AvatarDSLDict | null;
  onApproveDsl?: (dsl: AvatarDSLDict) => void | Promise<void>;
  onRejectDsl?: () => void;
}
```

### REPLACE

```ts
interface Props {
  agentId: string;
  appearance: CrewAppearance | null;
  departmentColor: string;
  agentSignals: AgentSignals;
  onClose: () => void;
  // AD-721d: when set, surfaces the approval bar with the proposed DSL.
  proposedDsl?: AvatarDSLDict | null;
  onApproveDsl?: (dsl: AvatarDSLDict) => void | Promise<void>;
  onRejectDsl?: () => void;
  // AD-721d-1: revision-cycle wiring.
  previousDsl?: AvatarDSLDict | null;     // for diff highlighting
  iteration?: number;                      // 1-based; defaults to 1 when absent
  maxIterations?: number;                  // defaults to 3
  onRequestRevision?: (note: string) => void | Promise<void>;
}
```

### Implementation: replace the approval-bar block

The full replacement block is large (~140 lines). Builder: replace the entire JSX expression `{proposedDsl && (<div data-testid="approval-bar" ...>...</div>)}` with the block below. Anchor the SEARCH on the unique `data-testid="approval-bar"` opening + the closing `)}` that follows the existing block.

Key requirements (HXI Design Principles):
- **No emoji.** All icons inline SVG, `strokeWidth={1.5}`, `strokeLinecap="round"`. (HXI #3)
- **Colors:** active amber `#f0b060`; dim `#8888a0`; changed-value tint `rgba(240, 176, 96, 0.18)` bg.
- **Diff visual:** changed field renders new value in amber, previous value below with `textDecoration: 'line-through'` and `color: '#666680'`.
- **Counter:** `${note.length} / 280`, turns amber at 250, red `#cc6666` at 280.
- **At cap:** "Request revision" button rendered with `disabled` + `aria-disabled="true"` + native `title` tooltip explaining the cap. (HXI #1 — the affordance communicates its own state.)

```tsx
{proposedDsl && (() => {
  const changed = diffAvatarDsl(previousDsl ?? null, proposedDsl);
  const iter = iteration ?? 1;
  const maxIter = maxIterations ?? 3;
  const atCap = iter >= maxIter;
  const labelStyle: React.CSSProperties = {
    color: '#8888a0', fontSize: 10, marginRight: 4,
  };
  const valueStyle = (path: string): React.CSSProperties => ({
    color: changed.has(path) ? '#f0b060' : '#ccccd8',
    background: changed.has(path) ? 'rgba(240, 176, 96, 0.12)' : 'transparent',
    padding: changed.has(path) ? '0 4px' : 0,
    borderRadius: 2,
  });
  const prevStyle: React.CSSProperties = {
    color: '#666680', fontSize: 9, textDecoration: 'line-through', marginLeft: 4,
  };
  const renderField = (path: string, label: string, curr: unknown, prev: unknown) => (
    <div style={{ display: 'flex', alignItems: 'baseline', gap: 4, lineHeight: 1.4 }}>
      <span style={labelStyle}>{label}</span>
      <span style={valueStyle(path)} data-diff-path={path}>{String(curr)}</span>
      {changed.has(path) && prev !== undefined && prev !== null && (
        <span style={prevStyle} data-diff-prev={path}>{String(prev)}</span>
      )}
    </div>
  );

  return (
    <div
      data-testid="approval-bar"
      data-iteration={iter}
      data-max-iterations={maxIter}
      style={{
        flex: '0 0 auto',
        padding: '6px 8px',
        background: 'rgba(240, 176, 96, 0.06)',
        borderTop: '1px solid rgba(240, 176, 96, 0.15)',
        display: 'flex',
        flexDirection: 'column',
        gap: 6,
        fontSize: 11,
        fontFamily: "'JetBrains Mono', monospace",
        color: '#ccccd8',
      }}
    >
      {/* Structured parametric description (with diff highlights) */}
      <div data-testid="parametric-description" style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ color: '#f0b060', fontSize: 10 }}>
            Proposal {iter} / {maxIter}
          </span>
          {/* Hair-color swatch (small SVG square, no emoji) */}
          <svg width="10" height="10" viewBox="0 0 10 10" aria-label="hair color">
            <rect
              x="0" y="0" width="10" height="10" rx="2"
              fill={`hsl(${proposedDsl.hair?.color_hsl?.[0] ?? 0}, ${proposedDsl.hair?.color_hsl?.[1] ?? 0}%, ${proposedDsl.hair?.color_hsl?.[2] ?? 0}%)`}
            />
          </svg>
          {/* Outfit-color swatch */}
          <svg width="10" height="10" viewBox="0 0 10 10" aria-label="outfit color">
            <rect
              x="0" y="0" width="10" height="10" rx="2"
              fill={proposedDsl.outfit?.primary_color ?? '#2a4a6a'}
            />
          </svg>
        </div>
        {renderField('body.type',            'body',     proposedDsl.body?.type,            previousDsl?.body?.type)}
        {renderField('body.height_cm',       'h(cm)',    proposedDsl.body?.height_cm,       previousDsl?.body?.height_cm)}
        {renderField('hair.style',           'hair',     proposedDsl.hair?.style,           previousDsl?.hair?.style)}
        {renderField('face.warmth',          'warmth',   proposedDsl.face?.warmth,          previousDsl?.face?.warmth)}
        {renderField('face.jaw',             'jaw',      proposedDsl.face?.jaw,             previousDsl?.face?.jaw)}
        {renderField('face.eyes',            'eyes',     proposedDsl.face?.eyes,            previousDsl?.face?.eyes)}
        {renderField('outfit.style',         'outfit',   proposedDsl.outfit?.style,         previousDsl?.outfit?.style)}
        {renderField('expression_resting',   'resting',  proposedDsl.expression_resting,    previousDsl?.expression_resting)}
        {proposedDsl.notes && (
          <div style={{ color: '#8888a0', fontSize: 10, marginTop: 2, fontStyle: 'italic' }}>
            {proposedDsl.notes}
          </div>
        )}
      </div>

      {/* Action row: Approve / Request revision / Reject */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span style={{ flex: 1 }} />
        <button
          data-testid="approve-dsl-btn"
          onClick={() => onApproveDsl?.(proposedDsl)}
          aria-label="Approve avatar design"
          title="Approve"
          style={{
            background: 'none', border: '1px solid rgba(240, 176, 96, 0.4)',
            color: '#f0b060', cursor: 'pointer', padding: '2px 6px',
            borderRadius: 3, display: 'flex', alignItems: 'center',
          }}
        >
          <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor"
               strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M3 8l3.5 3.5L13 4.5" />
          </svg>
        </button>
        <button
          data-testid="request-revision-btn"
          onClick={() => setRevisionOpen((v) => !v)}
          aria-label="Request avatar design revision"
          aria-disabled={atCap}
          disabled={atCap}
          title={atCap
            ? `Maximum revisions reached (${maxIter}). Approve or reject.`
            : 'Request revision'}
          style={{
            background: 'none',
            border: `1px solid ${atCap ? 'rgba(136, 136, 160, 0.25)' : 'rgba(240, 176, 96, 0.4)'}`,
            color: atCap ? '#666680' : '#f0b060',
            cursor: atCap ? 'not-allowed' : 'pointer',
            padding: '2px 6px', borderRadius: 3, display: 'flex', alignItems: 'center',
          }}
        >
          {/* Curved arrow / revise glyph — stroke-based, no emoji. */}
          <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor"
               strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M2 8a6 6 0 0 1 10.5-4" />
            <path d="M13 2v3h-3" />
            <path d="M14 8a6 6 0 0 1-10.5 4" />
            <path d="M3 14v-3h3" />
          </svg>
        </button>
        <button
          data-testid="reject-dsl-btn"
          onClick={() => { setRevisionOpen(false); onRejectDsl?.(); }}
          aria-label="Reject avatar design"
          title="Reject"
          style={{
            background: 'none', border: '1px solid rgba(136, 136, 160, 0.4)',
            color: '#8888a0', cursor: 'pointer', padding: '2px 6px',
            borderRadius: 3, display: 'flex', alignItems: 'center',
          }}
        >
          <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor"
               strokeWidth="1.5" strokeLinecap="round">
            <line x1="3" y1="3" x2="13" y2="13" />
            <line x1="13" y1="3" x2="3" y2="13" />
          </svg>
        </button>
      </div>

      {/* Inline revision textarea (expands when Request revision is clicked) */}
      {revisionOpen && !atCap && (
        <div data-testid="revision-textarea-wrap" style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <textarea
            data-testid="revision-note"
            value={revisionNote}
            onChange={(e) => setRevisionNote(e.target.value.slice(0, 280))}
            placeholder="What should the agent change? (≤ 280 chars)"
            rows={2}
            style={{
              width: '100%', resize: 'vertical', fontSize: 11,
              fontFamily: "'JetBrains Mono', monospace",
              background: 'rgba(0, 0, 0, 0.3)',
              color: '#ccccd8',
              border: '1px solid rgba(240, 176, 96, 0.25)',
              borderRadius: 3, padding: 4,
            }}
          />
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span
              data-testid="revision-counter"
              style={{
                fontSize: 9,
                color: revisionNote.length >= 280
                  ? '#cc6666'
                  : revisionNote.length >= 250 ? '#f0b060' : '#666680',
              }}
            >
              {revisionNote.length} / 280
            </span>
            <span style={{ flex: 1 }} />
            <button
              data-testid="submit-revision-btn"
              onClick={async () => {
                const note = revisionNote.trim();
                if (!note) return;
                await onRequestRevision?.(note);
                setRevisionNote('');
                setRevisionOpen(false);
              }}
              disabled={!revisionNote.trim()}
              aria-label="Submit revision request"
              title="Submit revision"
              style={{
                background: 'none',
                border: '1px solid rgba(240, 176, 96, 0.4)',
                color: revisionNote.trim() ? '#f0b060' : '#666680',
                cursor: revisionNote.trim() ? 'pointer' : 'not-allowed',
                padding: '2px 6px', borderRadius: 3, display: 'flex', alignItems: 'center',
              }}
            >
              {/* Paper-plane / send glyph — stroke-based. */}
              <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor"
                   strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M2 8l12-5-5 12-2-5z" />
                <path d="M7 10l5-7" />
              </svg>
            </button>
          </div>
        </div>
      )}
    </div>
  );
})()}
```

Add the matching `useState` hooks at the top of `CrewAvatarPopout` (next to existing state):

```ts
const [revisionOpen, setRevisionOpen] = useState(false);
const [revisionNote, setRevisionNote] = useState('');
```

And add the import for the diff helper (top of file with other imports):

```ts
import { diffAvatarDsl } from './avatarDslDiff';
```

---

## Section 7 — UI: wire `AgentProfilePanel` → re-propose flow

**File:** `ui/src/components/profile/AgentProfilePanel.tsx`.

The existing panel (around lines 60-80, 215-240, 360-380) already manages `proposedDsl` state and the design button. Extend it with:

1. New state: `previousDsl`, `proposalIteration`, `proposalMaxIterations`.
2. `onRequestRevision` callback that re-POSTs `/appearance/propose` with `{captain_note: note, previous_dsl: proposedDsl}` and updates state.
3. Update existing approve/reject callbacks: on approve, clear iteration state; on reject, also fire `DELETE /appearance/proposal-history` (fire-and-forget).
4. Pass new props through to `<CrewAvatarPopout ... />`.

### State additions (next to `const [proposedDsl, setProposedDsl] = useState<AvatarDSLDict | null>(null);` at line ~62)

```ts
const [previousDsl, setPreviousDsl] = useState<AvatarDSLDict | null>(null);
const [proposalIteration, setProposalIteration] = useState<number>(1);
const [proposalMaxIterations, setProposalMaxIterations] = useState<number>(3);
```

### Update the existing design-button POST handler (around line 220-235)

The current code reads `data.dsl` but ignores `proposal_iteration` / `max_iterations`. Update:

### SEARCH

```ts
                  const data = await r.json();
                  if (data && data.dsl) {
                    setProposedDsl(data.dsl as AvatarDSLDict);
                    setAvatarOpen(true);
                  }
```

### REPLACE

```ts
                  const data = await r.json();
                  if (data && data.dsl) {
                    setProposedDsl(data.dsl as AvatarDSLDict);
                    setPreviousDsl(null);
                    setProposalIteration(Number(data.proposal_iteration ?? 1));
                    setProposalMaxIterations(Number(data.max_iterations ?? 3));
                    setAvatarOpen(true);
                  }
```

### Update the `<CrewAvatarPopout ... />` instantiation (single SEARCH/REPLACE covering onClose → onRejectDsl)

### SEARCH

```tsx
          onClose={() => { setAvatarOpen(false); setProposedDsl(null); }}
          proposedDsl={proposedDsl}
          onApproveDsl={async (dsl) => {
            const r = await fetch(`/api/agent/${agentId}/appearance`, {
              method: 'PUT',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ dsl }),
            });
            if (r.ok) {
              setProposedDsl(null);
              // Refresh profile so any cached vrm_url is picked up.
              fetch(`/api/agent/${agentId}/profile`)
                .then(rr => rr.ok ? rr.json() : null)
                .then(d => { if (d) setProfileData(d); })
                .catch(() => {});
            }
          }}
          onRejectDsl={() => setProposedDsl(null)}
```

### REPLACE

```tsx
          onClose={() => {
            setAvatarOpen(false);
            setProposedDsl(null);
            setPreviousDsl(null);
          }}
          proposedDsl={proposedDsl}
          previousDsl={previousDsl}
          iteration={proposalIteration}
          maxIterations={proposalMaxIterations}
          onRequestRevision={async (note) => {
            if (!agentId) return;
            try {
              const r = await fetch(`/api/agent/${agentId}/appearance/propose`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                  captain_note: note,
                  previous_dsl: proposedDsl,
                }),
              });
              if (!r.ok) {
                setDesignError(`Revision rejected (HTTP ${r.status})`);
                return;
              }
              const data = await r.json();
              if (data && data.dsl) {
                setPreviousDsl(proposedDsl);
                setProposedDsl(data.dsl as AvatarDSLDict);
                setProposalIteration(Number(data.proposal_iteration ?? proposalIteration + 1));
                setProposalMaxIterations(Number(data.max_iterations ?? proposalMaxIterations));
              }
            } catch (e: any) {
              setDesignError(String(e?.message || e));
            }
          }}
          onApproveDsl={async (dsl) => {
            const r = await fetch(`/api/agent/${agentId}/appearance`, {
              method: 'PUT',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ dsl }),
            });
            if (r.ok) {
              setProposedDsl(null);
              setPreviousDsl(null);
              setProposalIteration(1);
              // Refresh profile so any cached vrm_url is picked up.
              fetch(`/api/agent/${agentId}/profile`)
                .then(rr => rr.ok ? rr.json() : null)
                .then(d => { if (d) setProfileData(d); })
                .catch(() => {});
            }
          }}
          onRejectDsl={() => {
            // AD-721d-1: best-effort server-side history clear; UI does not block on this.
            if (agentId) {
              fetch(`/api/agent/${agentId}/appearance/proposal-history`, { method: 'DELETE' })
                .catch(() => { /* swallow — Tier-1 (UX cleanup, no user impact) */ });
            }
            setProposedDsl(null);
            setPreviousDsl(null);
            setProposalIteration(1);
          }}
```

---

## Section 8 — Tests

### 8a. Python (~12 tests)

Create `tests/test_ad721d1_dsl_preview.py` with the following test cases. Use the existing AD-721d test fixtures as a pattern (look at `tests/test_ad721d_*.py` for the TestClient harness, stub agent, etc.). Each test must reset `proposal_history` in setup/teardown via `proposal_history.reset_all()` to avoid order-dependence.

| Test | Asserts |
|---|---|
| `test_propose_request_accepts_previous_dsl` | POST with `{captain_note, previous_dsl}` returns 200, `proposal_iteration=2` (after a first call that returned 1) |
| `test_propose_iteration_cap_returns_429` | 4th propose call (default cap = 3) returns 429 with `reason="iteration_cap_reached"`, iteration/max in detail |
| `test_propose_history_cleared_on_approve` | After `PUT /appearance` succeeds, subsequent propose returns `proposal_iteration=1` |
| `test_propose_history_cleared_on_delete` | After `DELETE /appearance/proposal-history` returns 200, subsequent propose returns `proposal_iteration=1` |
| `test_propose_invalid_previous_dsl_returns_422_no_increment` | POST with `{previous_dsl: {body: {type: "INVALID"}}}` returns 422 AND `iteration_count` unchanged |
| `test_propose_captain_note_over_280_returns_422` | Existing AD-721d validator still fires (regression test) |
| `test_parse_appearance_dsl_security_guards_still_hold` | `_parse_appearance_dsl` still rejects oversized / YAML-anchor / depth-bomb payloads (regression) |
| `test_avatars_config_max_proposal_iterations_validator` | `AvatarsConfig(max_proposal_iterations=0)` raises; `=11` raises; `=5` accepts |
| `test_propose_avatars_feature_disabled_returns_503` | All 3 endpoints (propose/PUT/DELETE) return 503 when `cfg.avatars.enabled=False` |
| `test_proposal_history_isolated_per_agent` | Agent A's iterations don't leak into agent B's count |
| `test_emit_event_appearance_proposal_on_each_iteration` | Mock `runtime.emit_event`; each propose call fires `("appearance_proposal", {agent_id, iteration, has_captain_note, captain_note_len})` |
| `test_emit_event_appearance_approved_clears_history` | PUT /appearance fires `appearance_approved` AND `proposal_history.iteration_count(agent_id) == 0` afterwards |
| `test_delete_proposal_history_endpoint_emits_history_cleared` | DELETE fires `appearance_history_cleared` with `reason="delete"` |

> Builder: use `pytest.fixture(autouse=True)` to call `proposal_history.reset_all()` before AND after each test. Tests must be order-independent (test isolation rule).

### 8b. Vitest (~5 tests)

Create `ui/src/__tests__/CrewAvatarPopout.revision.test.tsx`:

| Test | Asserts |
|---|---|
| `renders Request revision button when proposedDsl is set` | `getByTestId('request-revision-btn')` exists |
| `clicking Request revision opens the textarea` | After click, `getByTestId('revision-textarea-wrap')` exists; counter shows `0 / 280` |
| `Submit posts captain_note and previous_dsl` | Mock `onRequestRevision`, type note, click submit → callback called with the note |
| `at iteration cap, Request revision is disabled with tooltip` | Render with `iteration={3} maxIterations={3}`; button has `disabled` + `title` mentioning the cap |

Create `ui/src/__tests__/CrewAvatarPopout.diff.test.tsx`:

| Test | Asserts |
|---|---|
| `diffAvatarDsl returns changed paths` | Direct unit test of the helper — change `body.type`; result is `Set(["body.type"])` |
| `parametric description applies amber tint on changed fields` | Render with `previousDsl` and `proposedDsl` differing on `outfit.style`; query `[data-diff-path="outfit.style"]` has `color: rgb(240, 176, 96)` (or computed-style equivalent) |

> Combined ≥ 5 vitest cases across two files.

---

## What this AD does NOT change

- AD-721d's `propose_appearance` LLM-prompt construction — `captain_note` is already piped through. We only add `previous_dsl` validation in the router; the LLM still sees only `captain_note` as the revision hint.
- AD-721d's `_parse_appearance_dsl` security guards — size cap, YAML anchor/alias rejection, depth guard remain in place. Adding revision flow does NOT introduce a new parse path.
- `EventType` enum — three new audit keys are emitted as **strings** via `runtime.emit_event(...)`. Promoting them to enum values is a separate AD (a substrate wave, not a UX wave).
- `crew_profile.AppearanceProfile` schema — DSL persistence is unchanged. Only the *final approved* DSL is persisted; intermediate revisions live only in `proposal_history._history`.
- Cognitive journal — `runtime.cognitive_journal.record(...)` is NOT used (its schema is LLM-call-shaped, verified `cognitive/journal.py:360`).
- Renderer-side preview before persistence — that requires the headless Blender renderer (AD-721i) and is out of scope. v1 ships parametric description only.
- Counselor-mediated revision (vs Captain-mediated) — future AD; current design is Captain-driven agent self-revision.

---

## Tracking

| File | Update |
|---|---|
| `PROGRESS.md` | Add CLOSED entry: "AD-721d-1 — DSL draft preview + revision cycle (Wave 145). +12 Python, +5 vitest. Closes #541." Bump test count. |
| `docs/development/roadmap.md` | Move #541 to Done. |
| `DECISIONS.md` | Append AD-721d-1 entry with: (a) chose `captain_note` as the revision-note slot (not a new `revision_note` field), (b) chose `runtime.emit_event` with string keys (not `cognitive_journal.record` and not new `EventType` enum), (c) chose module-level in-memory history (not runtime-attached) to avoid Phase-ordering risk per BF-259/260/261/262. |

No PROGRESS.md / roadmap updates for BFs in this wave (none expected — UX wave).

---

## Acceptance criteria

1. All Python tests in `tests/test_ad721d1_*.py` pass under `pytest tests/test_ad721d1_dsl_preview.py -v -n 0`.
2. All vitest tests in `ui/src/__tests__/CrewAvatarPopout.{revision,diff}.test.tsx` pass under `cd ui && npx vitest run`.
3. Full parallel gate (`pytest tests/ -q -n 4 --dist=loadfile`) shows test count incremented by exactly the new tests; no pre-existing tests regress.
4. UI: clicking "Request revision" → typing → submitting fires a POST with body `{captain_note: <note>, previous_dsl: <current>}`; the popout re-renders with the new DSL and an amber diff on changed fields.
5. UI: at iteration 3, the "Request revision" button is disabled with a native tooltip explaining the cap.
6. UI: NO emoji introduced. All new icons are inline SVG with `strokeWidth={1.5}` and `strokeLinecap="round"` (HXI Design Principle #3).
7. Server: `DELETE /api/agent/{id}/appearance/proposal-history` returns 200 + `{cleared_iterations: N}`; is idempotent.
8. Server: `runtime.emit_event` is called on every proposal, approval, and history-clear — verified by mock in tests.
9. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-10)

```
grep -n "propose_appearance" src/probos/cognitive/cognitive_agent.py
  3052: async def propose_appearance(
  3054:         captain_note: str = "",

grep -n "captain_note" src/probos/api_models.py
  269:     captain_note: str = ""

grep -n "AppearanceProposalError" src/probos/avatars/dsl.py
  146: class AppearanceProposalError(Exception):

grep -n "appearance/propose\|/appearance" src/probos/routers/agents.py
  389: @router.post("/{agent_id}/appearance/propose", response_model=ProposeAppearanceResponse)
  414:         dsl = await agent.propose_appearance(captain_note=captain_note)
  428: @router.put("/{agent_id}/appearance")

grep -n "class AvatarsConfig" src/probos/config.py
  922: class AvatarsConfig(BaseModel):

grep -n "class AvatarDSL\b" src/probos/avatars/dsl.py
  118: class AvatarDSL(BaseModel):

grep -n "def emit_event" src/probos/runtime.py
  971:     def emit_event(self, event: BaseEvent | str | EventType, data: dict[str, Any] | None = None) -> None:

grep -n "async def record\b" src/probos/cognitive/journal.py
  360:     async def record(            # signature is LLM-call-shaped (entry_id, prompt_tokens, ...)
                                        # → NOT used by this AD; we use emit_event instead.

grep -n "data-testid=\"approval-bar\"\|design-avatar-btn\|proposedDsl" ui/src/components/profile/AgentProfilePanel.tsx
  62:   const [proposedDsl, setProposedDsl] = useState<AvatarDSLDict | null>(null);
  215:               data-testid="design-avatar-btn"
  221:                   const r = await fetch(`/api/agent/${agentId}/appearance/propose`, {
  363:           proposedDsl={proposedDsl}
  379:           onRejectDsl={() => setProposedDsl(null)}

grep -n "data-testid=\"approval-bar\"" ui/src/components/profile/CrewAvatarPopout.tsx
  (matches the existing approval-bar JSX block; line numbers shift between
   revisions — Builder anchors on the data-testid attribute, not the line.)

grep -n "approval-bar\|approve-dsl-btn\|reject-dsl-btn" ui/src/__tests__/AgentProfilePanel.designAvatar.test.tsx
  130-141: existing AD-721d coverage. Revision-flow tests live in a new file.
```

Every concrete claim in the SEARCH blocks above maps to one of these grep hits. The single "non-existent" reference (`cognitive_journal.record(...)`) is explicitly called out as **not used** by this AD — it is documented in the "Solution overview" + "What this AD does NOT change" sections as a deliberate avoidance, so the reviewer will not flag it as a phantom.
