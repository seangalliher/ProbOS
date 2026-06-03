# AD-853..857 — Crew Self-Unblock: unified CapabilityRequest, acquire-vs-build triage, block→resume loop

**Status:** Draft for review (Architect-authored, verify-first against HEAD)
**Mode:** Architect spec. Builder executes ONE AD = ONE commit with a gate between each. Do NOT build the whole epic in one pass.
**Northstar:** Crew agents function like a ship's crew — commanded by conversation or formal assignment, all work tracked on the kanban board through its lifecycle, agents get work done with their knowledge/skills/tools, and when blocked they **request approval to acquire a tool/skill or to have a new capability built** rather than silently failing.
**Numbering:** Highest committed AD = **AD-839**. This epic = **AD-853–857** (845–852 reserved for Yeo workflow + web-research depth; 840–844 for Desktop Console). Reconciled in `docs/development/roadmap.md` (Crew Autonomy table).

---

## Why this epic (the gap)

Every individual primitive already exists, but as **four disconnected approval mechanisms** with no shared model, queue, or auto-resume:

| Existing primitive | Location (verified HEAD) | Limitation |
|---|---|---|
| Vision-capability proposal (agent→Captain approve/deny) | `propose_vision_capability` [routers/agents.py:847](../src/probos/routers/agents.py); `ProposeVisionCapability` [api_models.py:345](../src/probos/api_models.py); `VisionProposalEntry` sidecar | Vision only |
| In-chat tool grant | `ChatToolGrantRequest` [api_models.py:328](../src/probos/api_models.py); `chat_tool_grant` [routers/chat.py:1020](../src/probos/routers/chat.py); `ToolPermissionStore.issue_grant` (VERIFY signature — sibling of `ClearanceGrantStore.issue_grant` [clearance_grants.py:105](../src/probos/clearance_grants.py)) | Captain-initiated, not agent-requested |
| Self-mod build approval | `require_user_approval` + `_user_approval_fn` + `_import_approval_fn` [self_mod.py:129-214](../src/probos/cognitive/self_mod.py) | Bare callback, jumps straight to "build new agent" |
| Extension install approval | `PENDING_APPROVAL` → `approve_extension` [extensions/registry.py:55-97](../src/probos/extensions/registry.py) | Separate state machine |
| Work-item BLOCKED state | `WorkItemStatus.BLOCKED` + transitions `in_progress↔blocked` [workforce.py:51,165-218](../src/probos/workforce.py) | Nothing DRIVES it; no resume |

**Net:** an agent that hits a wall today just fails. There is no single "I need capability X, here's why, here's the task it unblocks" request, no cheap-first triage (grant before build), and no driver that sets the WorkItem `BLOCKED`, files the request, and resumes on approval. That spine is this epic.

---

## AD-853 — Unified `CapabilityRequest` model + single approval queue

**Build.** A new module `src/probos/capability_request.py`:
- `@dataclass CapabilityRequest`: `id`, `agent_id`, `kind: Literal["grant","install","build"]`, `target` (tool_id / skill name / capability description), `rationale` (≤280, matches AD-718a budget), `work_item_id: str | None`, `status: Literal["pending","approved","denied","fulfilled","failed"]`, `created_at`, `decided_at`, `decided_by`, `decision_reason`.
- **Identity & attribution (required).** The request is attributable to the requesting agent's stable **`AgentID`** (`agent.id`, a `str` from [types.py:13](../src/probos/types.py); this is the trust-boundary key every store + `TrustNetwork` consumes — do NOT pull in the `identity.py` DID/birth-certificate ledger, that is a different concern) so the approval trail records *whose authority the capability was granted under* — and the outcome (approved/denied/fulfilled/failed) is recorded against that agent's **trust ledger** so capability requests feed the learning loop (a denied or failed request is a trust signal, an approved-and-fulfilled one is provenance). Record via the **verified-real** signature (sync, keyword args): `trust.record_outcome(agent_id=req.agent_id, success=approved, weight=1.0, intent_type="capability_request", source="capability_request")` — real def is `def record_outcome(self, agent_id, success, weight=1.0, intent_type="", episode_id="", verifier_id="", source="verification") -> float` ([trust.py:217](../src/probos/consensus/trust.py); it is **synchronous**, do NOT await it, and there is NO positional `source` — use keywords). Do NOT add a new identity system or a new attribution scheme — reuse the existing per-agent `AgentID` + `TrustNetwork`. The `decided_by` field captures the approver (Captain) for the dual-attribution audit trail.
- `class CapabilityRequestStore` following the verified `ClearanceGrantStore` DB+cache shape [clearance_grants.py:105-145](../src/probos/clearance_grants.py): `async def file_request(...) -> CapabilityRequest`, `async def decide(request_id, approve, reason, decided_by) -> CapabilityRequest`, `async def list_pending()`, `async def get(request_id)` (the read methods do DB I/O — they MUST be `async`, mirroring the sibling's async `list_grants`/`get_grant`; do NOT leave them sync). SQLite via the cloud-ready `ConnectionFactory` **Protocol** (`from probos.protocols import ConnectionFactory`, default `probos.storage.sqlite_factory.default_factory`; in `start()` do `self._db = await self._connection_factory.connect(self.db_path)` + WAL/busy_timeout PRAGMAs + `executescript(_SCHEMA)` + `commit()`) — NOT direct `aiosqlite.connect` (copilot-instructions storage rule; the sibling genuinely uses this Protocol, copy it verbatim).
- **Event emission (the sibling does NOT do this — AD-853's one legitimate divergence).** `ClearanceGrantStore`/`ToolPermissionStore` `issue_grant` emit **no events**; mirroring them "exactly" yields zero events and fails the acceptance test. Add emission via the existing `EventEmitterMixin` ([protocols.py:20](../src/probos/protocols.py)): accept an `emit_event` callback at construction, set `self._emit_event`, and call `self._emit(EventType.CAPABILITY_REQUEST_FILED, {...})` / `CAPABILITY_REQUEST_DECIDED` / `CAPABILITY_REQUEST_FULFILLED` at the right points. The callback is wired in `startup/communication.py` at construction.
- New events in [events.py](../src/probos/events.py) (the mechanism is the `class EventType(str, Enum)` at [events.py:21](../src/probos/events.py) — add members, e.g. `CAPABILITY_REQUEST_FILED = "capability_request_filed"`; verified-existing siblings `WORK_ITEM_CREATED`/`WORK_ITEM_STATUS_CHANGED` at [events.py:98-100](../src/probos/events.py); do NOT assume any others exist): `CAPABILITY_REQUEST_FILED`, `CAPABILITY_REQUEST_DECIDED`, `CAPABILITY_REQUEST_FULFILLED`.
- Wire the store in startup alongside the other stores: construct `CapabilityRequestStore(db_path=str(data_dir / "capability_requests.db"), connection_factory=..., emit_event=<runtime emit>)` immediately after the `ClearanceGrantStore` block at [startup/communication.py:291](../src/probos/startup/communication.py), `await ...start()`, no config gate; declare `runtime.capability_request_store: CapabilityRequestStore | None = None` alongside [runtime.py:702](../src/probos/runtime.py).

**Acceptance.** `tests/test_ad853_capability_request.py` (≥7, real store fixture copied verbatim from [tests/test_ad622_clearance_grants.py:113-122](../tests/test_ad622_clearance_grants.py), NO MagicMock at the storage boundary): file→pending; decide(approve)→approved + `CAPABILITY_REQUEST_DECIDED` event emitted; decide(deny)→denied; `list_pending` filters; persistence round-trip (two store instances on the same `db_path`, template at [test_ad622_clearance_grants.py:195-202](../tests/test_ad622_clearance_grants.py)); `work_item_id` carried through; decide records the outcome against a **real** `TrustNetwork` (assert the agent's score moves, so the trust-ledger wiring isn't silently dropped). Verify Engineering-Principles compliance.

**Do NOT build:** the triage router (854), the resume driver (855), any UI. Do not delete or rewrite the existing vision/tool/extension proposal paths — they keep working; 853 is additive and they migrate onto it in a later AD.

---

## AD-854 — Acquire-vs-build triage router (grant → install → build)

**Build.** `src/probos/cognitive/capability_triage.py` — a pure decision function (no I/O) + a thin async driver:
- `triage(gap: CapabilityGap, *, registry, tool_registry, extension_registry) -> CapabilityRequest`-kind decision, choosing the **cheapest reversible rung first**, mapped to the three governance axioms:
  1. **grant** an already-registered tool the agent lacks permission for → **Minimal Authority** (most reversible, no new code).
  2. **install** a known skill/extension from the registry → **Reversibility Preference** (sandboxed, revocable).
  3. **build** a new capability via the Architect/Builder self-mod pipeline → **Safety Budget** (most expensive/least reversible; always needs Captain approval).
- **Zero-ceremony fast path for the grant rung (low-latency case).** A `grant` request MAY be **auto-approved without a Captain prompt** when ALL hold: (a) the target is a **non-destructive** tool (its `IntentDescriptor` does not set `requires_consensus`), (b) an **in-department peer already holds** the grant (precedent exists), and (c) the requesting agent's trust is at or above a configurable floor. Otherwise the grant falls back to the normal approval queue. `install` and `build` ALWAYS require Captain approval — no fast path. This keeps the common case fast (seconds, no interruption) while the Captain is only interrupted for capability-envelope *expansion* that is destructive, novel, or unprecedented. The auto-approve decision and its three predicates are logged and recorded against the agent's trust ledger like any other decision. Make the floor + the whole fast path config-gated (Pydantic, default conservative — fast path OFF or trust-floor high until proven).
- The driver files the resulting `CapabilityRequest` (AD-853) and, on approval, routes to the existing fulfiller for that rung: grant→`ToolPermissionStore.issue_grant`; install→`approve_extension`; build→`self_mod_pipeline.handle_unhandled_intent` ([runtime.py:3438](../src/probos/runtime.py) pattern).
- Reuse the existing capability-gap detection (`is_capability_gap` [decomposer.py], `_last_capability_gap` [runtime.py]) — do NOT invent a new gap detector.

**Acceptance.** `tests/test_ad854_capability_triage.py` (≥7): missing-permission-on-registered-tool→grant; known-skill→install; novel-capability→build; build always sets needs-approval; **grant fast-path auto-approves only when non-destructive + peer-precedent + trust-floor all hold, else queues**; triage is pure/deterministic given inputs; unknown registries→honest-degrade to build with a logged reason. Verify Engineering-Principles compliance.

**Do NOT build:** the resume driver (855), new fulfillers (reuse existing), UI.

---

## AD-855 — BLOCKED → request → approve → resume work-item loop driver

**Build.** The driver that closes the lifecycle on the kanban board:
- When a dispatched work item's agent hits a capability gap mid-execution: set the WorkItem `status=BLOCKED` via `update_work_item(..., status="blocked", metadata={...blocked_reason, capability_request_id})` (transition `in_progress→blocked` already legal [workforce.py:169](../src/probos/workforce.py)), and file the triaged `CapabilityRequest` (854) carrying `work_item_id`.
- Subscribe to `CAPABILITY_REQUEST_DECIDED`: on **approved+fulfilled**, transition `blocked→in_progress` and **re-dispatch** the work item (reuse `WorkItemRouter` dispatch path [work_item_router.py:104](../src/probos/mesh/work_item_router.py)); on **denied**, transition to `failed`/`cancelled` with the reason recorded.
- Hold all task references (no fire-and-forget). Honest-degrade if stores are absent.

**Acceptance.** `tests/test_ad855_block_resume.py` (≥6, real WorkItemStore + CapabilityRequestStore): gap→BLOCKED + request filed with work_item_id; approve→back to in_progress + re-dispatch; deny→failed with reason; non-dispatchable items unaffected; double-decision idempotent; store-absent degrade. Verify Engineering-Principles compliance.

**Do NOT build:** UI, the AgenticLoop bridge (856).

---

## AD-856 — `AgenticLoop` as the executor for dispatchable work items (bridge)

**Build.** Today a dispatched work item runs the agent's single-shot `perceive→decide→act`, so it can fetch once and answer once but cannot iterate across tools. Wire the existing `AgenticLoop` (AD-545, [swe_harness/agentic_loop.py:47](../src/probos/cognitive/swe_harness/agentic_loop.py)) as the execution path for `metadata.dispatchable` work items:
- A `ToolExecutor` ([tools/executor.py:40](../src/probos/tools/executor.py)) populated with the agent's GRANTED tools + the mesh web intents (`web_search`/`read_page`/`http_fetch`) exposed as tools.
- `_handle_work_item_dispatch` [cognitive_agent.py:1082](../src/probos/cognitive/cognitive_agent.py) runs the loop (bounded `max_iterations`, token budget) instead of one `act()`. On a tool-permission denial inside the loop → emit a capability gap → AD-855 driver blocks+requests.
- This is the single change that makes "agents get work done using their skills and tools" real, and it is the same engine AD-852 (web-research loop) uses — one investment, two payoffs. Reuse, do NOT author a second loop (DRY).

**Acceptance.** `tests/test_ad856_agentic_dispatch.py` (≥5): dispatchable item runs the loop with ≥2 tool iterations (fake ToolExecutor); permission denial mid-loop→capability gap surfaced; respects max_iterations/token budget; non-dispatchable path unchanged (regression); granted-tool set scopes the executor. Verify Engineering-Principles compliance.

**Do NOT build:** new tools, UI, changes to AgenticLoop internals.

---

## AD-857 — Capability-request HXI/chat decision surface (alert-driven, dual-surface)

**Build (UI + thin API).** Per HXI Principle #9 (alert-driven layout reconfiguration), a pending `CapabilityRequest` must **rise to the top** of the HXI and also appear in the relevant 1:1/Ward Room chat, so the Captain can approve/deny from either surface — same dual-surface pattern as the Yeo completion DM (AD-846).
- `GET /api/capability-requests?status=pending`, `POST /api/capability-requests/{id}/decide` (approve/deny + reason) — thin wrappers over the AD-853 store.
- HXI: a pending-request card (department-colored per Principle #9) with Approve/Deny + the rationale and the linked work item. Vitest component test required (UI-test rule — the HXI has broken from untested UI changes before).

**Acceptance.** ≥3 API tests (happy/deny/validation) + ≥1 vitest component test. Verify Engineering-Principles compliance.

**Do NOT build:** new request kinds, changes to the triage/resume logic.

---

## Build order & gates

`AD-853 → 854 → 855 → 856 → 857`, each: focused tests green → full gate → commit → **stop, review**. AD-856 (touches the dispatch hot path) and AD-855 (touches runtime startup wiring) get a corruption pre-check (`git diff --numstat`, PowerShell sort) before commit per the working-tree-integrity memory.

**Test invocation (CWD hazard):** `Set-Location -LiteralPath d:\ProbOS` then
`d:/ProbOS/.venv/Scripts/pytest.exe d:/ProbOS/tests/test_ad853_capability_request.py --rootdir d:/ProbOS -q -n 0 -p no:cacheprovider`.

## Relationship to adjacent reserved ADs (do NOT duplicate)
- **AD-840** (HXI Skill Registry) / **AD-842** (per-agent tool grants in ACM profile) are the *Captain-manual* grant surfaces. This epic is the *agent-initiated request + auto-resume* spine. They compose: AD-842's grant mechanism is a fulfiller for AD-854's "grant" rung; AD-857's card is the agent-initiated counterpart to AD-840's manual surface. Keep the boundary clean in implementation.
- **AD-852** (web-research loop) and **AD-856** share `AgenticLoop` — build 856's bridge first if both are scheduled, so 852 plugs into a proven executor.

## Verify-first reminders for the Builder
- `ToolPermissionStore.issue_grant` signature is ASSUMED from the `ClearanceGrantStore` sibling — grep the real class before citing.
- Confirm the exact `runtime.py` startup module that constructs grant/tool stores before wiring `CapabilityRequestStore`.
- Only `WORK_ITEM_CREATED` + `WORK_ITEM_STATUS_CHANGED` are verified in events.py — add new event constants, don't assume others.
- Treat this spec as a lead, not ground truth: grep/read every cited API before editing (subagent/spec reports are leads — recurring memory lesson).
