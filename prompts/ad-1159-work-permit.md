# AD-1159 — The Work Permit: a durable, session-scoped authorization to act on a workstation

**Status:** Ready for Builder.
**Depends on:** AD-1124 (CrewSessionContract), AD-1154 (ActionApprovalStore pattern), AD-706 (classify_action tiers), BF-690 (single source of truth for advertised capability).
**Unblocks:** AD-1160 (wire the permit to the browser/workstation), AD-1161 (permit reissue between agents), AD-1162 (Tools launcher UI).

---

## 1. What this AD builds, in one sentence

A durable store of **work permits** — each a single-holder authorization for one agent to act on one workstation within one crew session, up to a bounded hazard tier — plus its invariants. **Nothing consumes it in this AD.**

## 2. Why nothing consumes it

AD-1154 set this precedent explicitly and it is repeated here because it is the single most likely thing to be "improved" away:

> *"Shipping the gate and the actions it gates in one change would mean the gate's first exercise is in production."*

The permit store lands with tests and no callers. AD-1160 wires it. If you find yourself editing `BrowserTool`, `DispatchToolExecutor`, or any UI file, you have left this AD's scope.

## 3. The naval model being absorbed (and the parts deliberately not)

Permit to Work (PTW) is the maritime/naval system for authorizing hazardous work in a space. Four properties transfer:

1. **Issuing Authority ≠ Performing Authority.** The officer who authorizes never performs. `surgeon.md:9` ("Every operation must have CMO authorization or Captain approval") and `yeoman.md:16` ("you do not issue orders on your own authority") already state this in the crew's standing orders — as prose, unenforced.
2. **The permit names a space, a work class, a holder, and a duration** — a structured record, not a boolean.
3. **Explicit closure returns the space to normal.** A permit is *closed*, not merely expired. Closure is where an outcome is recorded.
4. **Hazard classes** (cold work / hot work / confined space) — escalating tiers, each needing a higher authority. This maps onto the existing `classify_action` tier ladder.

**Not absorbed in this AD** (named so they are not half-built): watch-turnover revalidation, SIMOPS conflict reconciliation, suspension on general alarm, lockout/tagout multi-holder locks.

## 4. Verified ground truth

Every reference below was read from the live tree. Where a line number is given it was verified directly; where only a symbol is given, **locate it by symbol — do not trust a remembered line number.**

- **The store pattern to mirror:** `src/probos/tools/action_approvals.py` — `ActionApprovalStore`. This is the fourth instance of one shape (`ToolPermissionStore`, `IntentGrantStore`, `ActionApprovalStore`); yours is the fifth. Mirror it rather than inventing: WAL + `busy_timeout=5000` + `synchronous=NORMAL`, `ConnectionFactory` injection, in-memory cache loaded in `start()`, **zero-I/O sync reads**, soft-revoke for audit.
- **`ConnectionFactory` Protocol:** `src/probos/protocols.py`. Default SQLite impl: `src/probos/storage/sqlite_factory.py`. **Required** — the Cloud-Ready Storage rule in `.github/copilot-instructions.md` forbids direct `aiosqlite.connect()` in new modules.
- **Tier ladder:** `classify_action` in `src/probos/tools/browser/actions.py` returns int 1 | 2 | 3.
  - Tier 1 (silent observation): `state, screenshot, wait, extract_text, scroll, back, forward, verify, mouse_move`
  - Tier 2 (logged, ungated): `goto` unconditionally; `click/type/drag/mouse_button` on ordinary domains
  - Tier 3 (Captain ACK): `compute_use_click`, `upload_file`, `eval_js`, `fill_credential` always; plus click/type on checkout/payment/transfer paths or tier-3 domains
- **`CrewSessionContract`** in `src/probos/cognitive/crew_session.py`: `frozen=True, strict=True, extra="forbid"`, carries `revision`, `owner_ids: tuple[str, ...]`, `facilitator_id`, `thread_id`, `task_id`, and `CrewSessionState` ∈ {discussing, executing, verifying, blocked_needs_captain, done, failed}. Terminal: `done`, `failed`.
- **`_BROWSER_LOOP_ACTIONS`** (`src/probos/cognitive/agentic_dispatch.py:105`) = `{goto, state, extract_text, back, forward, wait}`.

### 4a. A discrepancy you must NOT silently resolve

`_BROWSER_LOOP_ACTIONS` is **not** a tier. Tier 1 includes `scroll`, `screenshot` and `verify`, which the loop set excludes for unrelated reasons (`scroll` mutates viewport state while returning no observation). A permit's tier ceiling and the loop allowlist are **different axes**. Do not unify them, do not redefine one in terms of the other, and do not widen `_BROWSER_LOOP_ACTIONS`. Assert it byte-identical at the end of this AD.

## 5. Deliverable

### 5.1 New module: `src/probos/tools/work_permits.py`

A `WorkPermit` dataclass and a `WorkPermitStore` mirroring `ActionApprovalStore`.

**Schema** — table `work_permits`:

| column | type | note |
|---|---|---|
| `id` | TEXT PRIMARY KEY | |
| `session_id` | TEXT NOT NULL | the crew session (the "space") |
| `workstation_id` | TEXT NOT NULL | e.g. `browser`, `monaco`, `mcp-app` |
| `holder_id` | TEXT NOT NULL | performing authority |
| `issued_by` | TEXT NOT NULL | issuing authority |
| `max_tier` | INTEGER NOT NULL | hazard ceiling, 1–3 |
| `reason` | TEXT NOT NULL DEFAULT '' | |
| `issued_at` | REAL NOT NULL | |
| `expires_at` | REAL NOT NULL | **NOT NULL — see 5.4** |
| `closed` | INTEGER NOT NULL DEFAULT 0 | |
| `closed_at` | REAL | |
| `close_reason` | TEXT NOT NULL DEFAULT '' | |
| `closed_by` | TEXT NOT NULL DEFAULT '' | |

Indexes: `(session_id, workstation_id, closed)` for the holder lookup; `(closed, expires_at)` for cache load. Mirror `ActionApprovalStore`'s index naming.

### 5.2 Public API

```python
async def start(db_path: str, connection_factory: ConnectionFactory | None = None) -> None
async def stop() -> None

async def issue_permit(
    *, session_id: str, workstation_id: str, holder_id: str,
    issued_by: str, max_tier: int, ttl_seconds: float, reason: str = "",
) -> WorkPermit                      # raises PermitConflict / ValueError per 5.3

async def close_permit(
    permit_id: str, *, closed_by: str, close_reason: str = "",
) -> bool

async def revoke_permit(permit_id: str, *, revoked_by: str) -> bool
    # Captain-side unconditional close. Implemented as close with a
    # close_reason of "revoked"; a separate column is NOT required.

def holder_sync(session_id: str, workstation_id: str) -> str | None
def permitted_tier_sync(agent_id: str, session_id: str, workstation_id: str) -> int
    # 0 = no permit. Zero I/O — dispatch path.
def get_sync(permit_id: str) -> WorkPermit | None
def list_open_sync(session_id: str = "") -> list[WorkPermit]
```

### 5.3 Invariants — the substance of this AD

Each must be individually tested.

1. **Single holder.** At most **one** open, unexpired permit per `(session_id, workstation_id)`. A second `issue_permit` for an occupied space raises rather than silently superseding — a permit that vanishes because someone else asked is the failure PTW exists to prevent.
2. **Issuing ≠ performing.** `issued_by == holder_id` is rejected. Self-issue is the whole point of the separation.
3. **Tier bounds.** `max_tier` ∉ {1, 2, 3} is rejected. Reject `bool` explicitly — `isinstance(True, int)` is `True` in Python, and `max_tier=True` would otherwise silently mean tier 1.
4. **`expires_at` is NOT NULL.** Follows AD-1154's reasoning verbatim: a permit with no expiry is a permanent authority nobody remembers granting. `ttl_seconds` is a required parameter; there is no `expires_at: float | None` overload.
5. **Expiry is lazy, on read.** `permitted_tier_sync` and `holder_sync` return as if closed once `expires_at` has passed. **No background reaper** — matches all four existing stores.
6. **Closure is terminal.** A closed permit never reopens. `close_permit` on an already-closed permit returns `False`, does not raise.
7. **No wildcards.** `session_id`/`workstation_id`/`holder_id` match exactly. An empty string matches only an empty string. AD-1154 rejected wildcard scope for the same reason.
8. **`permitted_tier_sync` is agent-scoped.** An agent that is not the holder gets `0`, even when a permit is open for that space.

### 5.4 Config

Add to `config.py`, on the existing Pydantic models, with defaults that leave the system byte-identical:

```python
work_permits_enabled: bool = False       # default-OFF
work_permit_default_ttl_seconds: float = 3600.0
work_permit_max_tier_ceiling: int = 2    # tier 3 needs explicit Captain issue
```

Place these on the config model that most closely matches existing tool-governance settings — **locate it, do not assume `AgenticToolsConfig`.** Every field needs a description string.

## 6. Do NOT build

Named explicitly because each is tempting and each belongs to a later AD:

- **Any caller.** No wiring into `BrowserTool`, `DispatchToolExecutor`, `agentic_dispatch.py`, `finalize.py`, or the runtime. The store is constructed by tests only.
- **No UI.** No files under `ui/`.
- **No API routes.** No `src/probos/routers/` changes.
- **No agent→agent transfer.** That is AD-1161. There is no `transfer_permit` method in this AD.
- **No watch-turnover revalidation.** `WatchManager` is in-memory scaffolding gated behind `proactive_cognitive.enabled`; building on it now would couple permits to an unrelated flag.
- **No changes to `_BROWSER_LOOP_ACTIONS`** — assert it byte-identical.
- **No changes to `classify_action`** — this AD reads its tier vocabulary, it does not alter it.
- **No new `CrewSessionContract` field.** The permit references `session_id`; the contract is untouched. Extending a frozen Pydantic contract with CAS semantics is AD-1160's problem, not this one.

## 7. Acceptance criteria

- New file `src/probos/tools/work_permits.py`; new tests `tests/test_ad1159_work_permits.py`.
- Every invariant in 5.3 has its own test, plus boundary coverage per the Testing Standards: happy path, error case, and empty/None input for every public method.
- A test asserts `_BROWSER_LOOP_ACTIONS` is unchanged.
- A test asserts the store uses `ConnectionFactory` (construct with a custom factory and assert it was used) — the Cloud-Ready Storage rule.
- A test asserts `max_tier=True` and `max_tier=False` are rejected.
- Config defaults leave every existing code path byte-identical; a test asserts the flag defaults to `False`.
- Full type annotations on every public method (parameters + return).
- Log messages carry context — what failed, why it matters, what happens next. No bare `logger.warning("error")`.
- **Run the full suite**, not a filtered subset: `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/ -q --timeout=600` with `$env:PROBOS_DATA_DIR` set to a fresh temp dir and `$env:PROBOS_EMBEDDINGS='local'`. Baseline before your change is **21,711 passed, 34 skipped**. Report the new count.
- **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

## 8. Commit

One commit. Message via `git commit -F <file>` — never inline `-m`, PowerShell eats `$`.
**Do not `git add config/system.yaml`** — it is skip-worktree (`S`). Verify with `git ls-files -v config/system.yaml` before staging.
