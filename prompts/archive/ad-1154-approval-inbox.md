# AD-1154 — Approval inbox: park an unattended ask instead of acting, and let a standing rule answer it once

**Issue: #1081 · Epic #1068 (agentic harness parity). Depends on AD-1153 (in-tree at HEAD `015c3643`) and on **BF-682**, which this AD closes as Section 0 rather than sequencing separately.**
**Repo: OSS (`d:\ProbOS`). This AD = **AD-1154** (#1081), reserved by the issue and below the shipped ceiling — AD-1155 landed first. AD ceiling: **AD-1155**; next free **AD-1156**. BF ceiling: **BF-683**; next free **BF-684**. `BF-681` is an unallocated gap, do not use it. No new AD. No new BF — **BF-682 closes here**.**

An unattended agent that reaches a consequential action currently has two outcomes: perform it, or emit a success-shaped no-op the model reads as completion. This adds the third: file a durable, reviewable record; tell the agent honestly that the step did not happen; carry on. A standing, TTL-bounded rule answers the same ask on the next run without asking again.

**Read the corrections before the DDs.** #1081's central premise — *"a durable pending-ask record"* is something ProbOS needs to build — is **false at HEAD**. The approval inbox already exists, end to end: a `ConnectionFactory`-backed store, a live REST decision surface, a live HXI panel, a Captain-DM notifier, a work-item resume driver, and even a heuristic auto-approval predicate. Building a fifth parallel store would put the ask on a surface nobody polls. And #1081's prescribed *resolution* surface — `AgentNotification` + `POST /api/notifications/{id}/accept` — is **in-memory only**, so an ask surfaced there dies at restart. Both corrections change the shape of the build.

---

## Corrections to #1081, read off the live tree at HEAD `015c3643`

### C-1 — The approval inbox already exists and is LIVE. This AD adds a fourth `kind` to it

`CapabilityRequestStore` (`capability_request.py:71`, AD-853) is a complete durable approval queue on the house pattern, and it is already wired on the live path:

| #1081 asks for | At HEAD |
|---|---|
| A durable pending-ask record | `CapabilityRequest` (`capability_request.py:55`), SQLite + `ConnectionFactory` + WAL + cache (`:87-104`) |
| Who asked, for what, in which work item | `agent_id`, `kind`, `target`, `rationale`, `work_item_id` (`:57-63`) |
| A human decides later | `decide(request_id, approve, reason, decided_by)` (`:172`), `list_pending()` (`:263`) |
| A REST decision surface | `GET /api/capability-requests?status=pending` + `POST /{id}/decide` (`routers/capability_requests.py:46`, `:65`) |
| A place the Captain actually looks | `ui/src/components/capability/CapabilityRequestPanel.tsx` — polls `?status=pending` (`:193`), Approve/Deny POST (`:209`) |
| Chat-side surfacing | AD-857 Captain-DM notifier on `CAPABILITY_REQUEST_FILED` (`startup/finalize.py:2557-2590`) |
| Resume after decision | AD-855 `CapabilityGapDriver`, listening on `capability_request_fulfilled` / `capability_request_decided` (`startup/finalize.py:2536-2551`) |
| Post-approval terminal states | `status` vocabulary is `pending / approved / denied / fulfilled / failed` (`:50`), with `mark_fulfilled()` (`:231`) |

`RequestKind` is `Literal["grant", "install", "build"]` (`:49`). This AD adds **`"action"`** — an ask about performing a specific tool action, rather than about acquiring a capability.

**The HXI panel is already kind-agnostic.** `CapabilityRequestPanel.tsx` types `kind: string` (`:18`), renders `{req.kind}` / `{req.target}` verbatim (`:117`, `:120`), and `departmentColor` falls through to a neutral dim for an unrecognised key (`:44-48`). A fourth kind renders **with no UI change**. That is the single strongest argument against a new store: the panel that exists is the panel the Captain has.

**Consequence, stated because it is the honest cost:** a fourth kind means `_serialize` (`routers/capability_requests.py:26`) must carry the new payload field or the Captain sees `target` and nothing else. That is in scope (DD-1); widening the panel is not (DD-9).

### C-2 — `NotificationQueue` is IN-MEMORY. #1081's prescribed resolution surface is not durable

`notifications.py:66` — `self._notifications: dict[str, AgentNotification]`. There is no DB, no `ConnectionFactory`, no `start()`/`stop()`. The class docstring says *"Persistent notification queue"* (`:63`); that word is wrong at HEAD and has been since AD-323. `NotificationQueue` is constructed once, in-process, at `runtime.py:1140`.

So the issue's instruction — *"Reuse `AgentNotification.suggested_action` + `POST /api/notifications/{id}/accept` (AD-1053) rather than inventing a second surface"* — would put a pending ask on a queue that:
- **loses every unacknowledged ask on restart**, which is precisely the "outlives the run" property the whole design rests on;
- prunes only *acknowledged* entries (`_prune_acknowledged`, `:186`), so unacked asks accumulate without bound in RAM until the process dies and takes them with it.

**The AD-1053 invariant is right and is preserved; the AD-1053 surface is not used.** The invariant is *the producer authors the action, the client only references an id* (`routers/system.py:433`). The AD-853 decide endpoint has exactly the same property — the body is `{approve, reason}` and nothing else (`api_models.py:262-270`) — and it is backed by SQLite. **Resolution goes through `POST /api/capability-requests/{id}/decide`, not `/api/notifications/{id}/accept`.** This is a correction to the issue, not a deviation from its intent.

### C-3 — The tier-3 no-op is confirmed exactly as described, and `BrowserTool` is NOT where it gets fixed

`tools/browser/tool.py:304-311` returns

```python
return ToolResult(
    output={"intervention_required": True, "tier": 3, "session_id": session.session_id},
    duration_ms=elapsed_ms,
    metadata={"session_id": session.session_id, "tier": 3},
)
```

with **no `error=` kwarg**, so `ToolResult.error is None` and `ToolCallResult.from_tool_result` (`swe_harness/tool_call.py:39-56`) takes the non-error branch: `is_error=False`. The `error="intervention_required"` two lines above (`:300`) is an argument to `self._audit(...)`, not to the returned result. The model receives a dict that reads as success.

And each pass through the gate mints a token: `_generate_confirmation_token` (`:696`) writes `self._pending_confirmations[token]` unconditionally; the only pruner is `reap_expired()` (`:186`).

**This AD does not change `BrowserTool.invoke`.** That method also serves the AD-745 DM dispatch path, where a human *is* present and the Captain-ACK reissue flow (`_consume_confirmation_token`, `:711`) is the intended mechanism. Changing the return there would alter a working attended path to fix an unattended one. The park + honest-refusal wrapper sits at `DispatchToolExecutor.invoke` (`agentic_dispatch.py:384`), **above** the tool — the same seam and the same reasoning as AD-1153/DD-1, which put `_BROWSER_LOOP_ACTIONS` there rather than inside the tool.

### C-4 — Neither `ToolPermissionStore` nor `IntentGrantStore` can express an action shape. Checked, not assumed

#1081: *"A standing approval is a durable privilege grant, so it belongs near `ToolPermissionStore` / `IntentGrantStore` rather than in a new store."* The instinct is right; the fit is not.

| Store | Primary key of a grant | Can it say "approve `browser.click` on `github.com`"? |
|---|---|---|
| `ToolPermissionStore` (`tools/permissions.py:39`) | `(agent_id, tool_id, permission)` — schema `:21-32` | **No.** There is no action column and no scope column. Granting `browser` grants *every* browser verb, including `eval_js` and `fill_credential`. |
| `IntentGrantStore` (`cognitive/intent_grants.py:75`) | `(agent_id, intent_name)` — schema `:41-51` | **No.** Same shape one layer up. `browser` is not a mesh intent at all. |

Both are **capability** grants: *may this agent hold this tool*. A standing approval is an **action** grant: *may this agent perform this shape of act, in this scope, until this time*. Widening `ToolPermissionStore` with `action` + `scope_key` columns would change the meaning of every existing row and of `check_permission`, which is on the hot path of every tool call in the system.

**So: a new store, deliberately, with the reason recorded.** It mirrors `IntentGrantStore` line for line (DD-4) so it is the fourth instance of one pattern rather than a fourth pattern — and it inherits `intent_grants.py:20-24`'s own note that a unified `CapabilityGrantStore` is the eventual consolidation. Do not attempt that consolidation here.

### C-5 — Heuristic auto-approval already exists in ProbOS, and its signals do not transfer

`capability_triage.evaluate_grant_fast_path` (`:53-72`) is exactly MAF's "heuristic auto-approval for safe, unattended execution", already shipped:

```python
return fast_path_enabled and non_destructive and peer_precedent and agent_trust >= trust_floor
```

Four-way AND, explicit, pure, testable, conservative, config-gated. It is the right shape. **Its inputs do not exist for an action ask:**

- `peer_precedent` asks *does an in-department peer already hold this grant*. There is no peer-holds-this-action-shape relation to query; the store this AD builds is empty at first ask, by construction.
- `non_destructive` is derived from a tool's registered permission matrix (`_derive_tool_permission`, `:78`). A browser `click` has no such matrix — its destructiveness is a property of the page, which is exactly why `classify_action` (`tools/browser/actions.py`) reaches for URL-path and element-text heuristics and still lands on "ask the Captain."

**DD-5 defers heuristic auto-approval.** The reasoning is in that DD; the point here is that the deferral is not a gap — the shipped standing rule gives the operator the same relief with a decision they made explicitly.

### C-6 — BF-682 is a declared precondition, and it is 3 lines. It closes here

Roadmap Bug Tracker, BF-682: *"Raw `confirmation_token` in the `TOOL_INTERVENTION_REQUIRED` event payload … **Becomes load-bearing at AD-1154.**"* Confirmed at `tools/browser/tool.py:283-291` — the emitted payload carries `"confirmation_token": token` verbatim, and `_consume_confirmation_token` reads the token straight out of `params` (`:711-716`), so possession of the log line is possession of the approval.

The middle link is still broken (C-7), so this remains hardening rather than a live exploit — but this AD is what makes a tier-3 gate reachable from an unattended loop, so the token stops being theoretically exposed and starts being routinely emitted. **Fix it in Section 0.** Blast radius is one assertion, `tests/test_ad706_browser_tool.py:279`.

### C-7 — Confirmed: no `emit_event`-sourced tool event is persisted. The inbox cannot lean on the event log

`runtime._emit_event` (`runtime.py:1621`) routes to JetStream when NATS is connected and otherwise to `_emit_event_local` (`:1660`), which walks `self._event_listeners` and `self._live_event_listeners`. **`EventLog.log` is not on either path.**

Measured on the live store, not inferred:

```
data/events.db — 402 483 rows, 8 distinct `event` values
  agent_wired 252 802 · pool_created 135 016 · started 4 508 · stopping 4 504
  stopped 4 503 · intent_resolved 572 · intent_broadcast 572 · ward_room_echo_detected 6
tool_intervention_required 0 · tool_invoked 0
browser_session_started 0 · browser_session_closed 0 · notification 0
```

A pending ask is not reconstructible from the event log. The store is the record of truth; events are notification only. Note the corollary for BF-682: the *query-your-own-log → replay the token* chain is unreachable today because the middle link does not exist — which is why BF-682 is a hardening fix and not an incident.

### C-8 — By the time a human decides, the browser session is gone

`BrowserToolConfig.session_max_duration_seconds = 1800` (`config.py:1568`) and `confirmation_timeout_seconds = 300` (`:1581`). A parked ask waits on human latency — minutes to days. This is decisive for DD-3 and it is the honest limitation of the whole design: **approval cannot replay the action that was parked.** A page-relative `click` selector resolved against a session that no longer exists, or against a page that has since changed, is more dangerous than not acting. Say this in the docstring and in the record; do not build a re-execution path that pretends otherwise.

### C-9 — Confirmed as stated in the issue or the brief

- `AggregateDecision.asked` is defined (`hooks/bus.py:107`) and has **no production consumer** — a `grep` for `\.asked\b` across `src/probos/` returns only two unrelated prose strings (`dm/reply_pipeline.py:1125`, `counselor.py:532`). `ask` is behaviourally `allow`.
- `_CAPABILITY_GAP_RE` (`decomposer.py:33`) contains bare `lack(?:s|ing)?`, `can['’]?t`, `cannot`, `unable to`, `not (?:available|supported|possible)`, `don['’]?t have`, `no (?:built-in |native )?(?:capability|ability|support|way|mechanism|tool)`, `doesn['’]?t (?:have|support)`, `beyond (?:my|current) (?:capabilities|abilities)`, `outside (?:my|the) (?:scope|capabilities)`. `re.IGNORECASE`.
- `_BROWSER_LOOP_ACTIONS = {"goto", "state", "extract_text", "back", "forward", "wait"}` (`agentic_dispatch.py:103`). Note: `scroll` is tier **1** in `classify_action`, not tier 3 — it is absent from the loop set for a different reason (it mutates viewport state with no observation returned), and widening the set is out of scope either way.
- Tier-3-reachable verbs are `click` / `type` / `drag` / `mouse_button` under the URL/text checks, plus the always-tier-3 `compute_use_click`, `upload_file`, `eval_js`, `fill_credential`, and conditional `key_combo` / `download` (`tools/browser/actions.py`, `classify_action`).
- The `crew_execution` record is exactly 14 keys (`crew_executor.py:634-648`); `SubtaskResult` is 13 frozen fields (`:667-681`); `description` is inside `_PROVISIONING_SPEC_KEYS` (`crew_session.py:1037-1049`) and therefore inside `_final_plan_hash` / `plan_seed_hash`. **None of the three is touched.**

---

## Pinned design decisions

### DD-0 — Scope: one new store, one new `kind`, one wrapper. No suspension anywhere

Three moving parts and no more:

1. **A fourth `CapabilityRequest.kind`** — `"action"`, carrying a bounded producer-authored payload (DD-1).
2. **`ActionApprovalStore`** — a narrow, mandatorily-expiring standing-rule store keyed on the action shape (DD-4).
3. **A park-and-refuse wrapper** at `DispatchToolExecutor.invoke` (DD-2).

`AgenticLoop` is not modified. `WorkItemAgenticExecutor.run` is not modified. `CrewTaskExecutor._run_child` is not modified. Nothing holds an LLM client, a `max_parallel_tool_calls` slot, a `max_parallel_subtasks` slot or a fan-out semaphore permit across a wait, because nothing waits. The run continues past the park within the same turn.

### DD-1 — The durable record: `kind="action"` on `CapabilityRequestStore`, plus one nullable `payload` column

**Why not a new store.** Five reasons, in descending order of force: the HXI panel that already exists renders it (C-1); the Captain-DM notifier that already exists announces it; the decision endpoint that already exists resolves it; `CapabilityRequestStore` is already the house `ConnectionFactory` pattern with a proven round-trip; and `intent_grants.py:20-24` already flags store proliferation as a known debt.

**The payload.** `target` is a bare string and cannot carry `params`. Add **one** nullable column:

```sql
payload TEXT   -- JSON; NULL for kind in (grant, install, build)
```

NULL for the three existing kinds ⇒ every existing row and every existing code path is byte-identical.

**Exact-key validation, both directions.** The decoded payload is a dict with exactly these six keys, validated on write and re-validated on read (a hand-edited DB is an untrusted input):

| Key | Type | Bound |
|---|---|---|
| `tool_id` | `str` | 1–64 chars, `^[a-z0-9_:.-]+$` |
| `action` | `str` | 1–64 chars, `^[a-z0-9_]+$` |
| `params` | `dict` | ≤ 20 keys, all keys `str`, serialised form ≤ `_ACTION_PAYLOAD_MAX_CHARS` |
| `scope_key` | `str` | ≤ 253 chars (a registrable domain, or `""`) |
| `session_id` | `str \| None` | ≤ 64 chars — recorded for forensics only; **never replayed** (C-8) |
| `thread_id` | `str` | ≤ 64 chars |

`_ACTION_PAYLOAD_MAX_CHARS = 4000`, matching `_MAX_OUTPUT_SUMMARY_CHARS`'s order of magnitude and comfortably under the existing `_RATIONALE_MAX = 280` × 15. Serialise with `json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)` and reject on `TypeError | ValueError | OverflowError` rather than letting a non-serialisable `params` raise inside `file_request`.

**Two hard exclusions from `params`, both non-negotiable:**
- `confirmation_token` is **stripped** before serialisation. Durably persisting a bearer token that `_consume_confirmation_token` will honour is BF-682 with a longer half-life.
- `action == "fill_credential"` is **never parked**. It is always tier 3 by design (`classify_action`) precisely because the Captain ACKs every credential read; converting that into a durable record plus a standing rule would turn a per-call human gate into a stored credential-access grant. It refuses through the normal path instead (DD-2's refusal text, with the request id omitted).

**Schema migration is required and `CREATE TABLE IF NOT EXISTS` will not do it.** An operator upgrading in place has an 11-column `capability_requests` table; the new INSERT would fail with `table has no column named payload`. Add a guarded migration in `start()`, before `_refresh_cache()`:

```python
cols = {r[1] async for r in await self._db.execute("PRAGMA table_info(capability_requests)")}
if "payload" not in cols:
    await self._db.execute("ALTER TABLE capability_requests ADD COLUMN payload TEXT")
    await self._db.commit()
```

`_refresh_cache`'s SELECT (`:118-121`) lists columns explicitly, so append `payload` there and read it as `row[11]` in `_row_to_request` (`:271`). The INSERT (`:150-157`) uses positional `VALUES` — **both must move together**, and `payload` must be appended last so no existing index shifts.

**The real-DB round-trip test is mandatory and is the point of this DD.** A cache-only suite (`db_path=""`) never executes `_row_to_request`, never executes the migration, and never catches a column-order slip — the exact class of defect this change introduces. The test writes an `action` request through a real `tmp_path` DB, stops the store, opens a **second** store instance on the same file, and asserts the decoded payload is byte-identical to the input. Mirror `tests/test_ad853_capability_request.py:96` (`test_persistence_round_trip`).

**Idempotency.** `file_action_request(...)` computes a dedup key `sha256(agent_id | tool_id | action | scope_key | work_item_id | canonical_params)` and, if a **pending** request with that key exists, returns it unchanged without inserting. This is the direct answer to the `_pending_confirmations` growth in C-3: a model that retries the refused call three times files **one** ask, not three. Store the key in the payload? No — recompute it from the payload on cache load, so no twelfth column and no second index.

### DD-2 — The agent is told the truth, in an ERROR-shaped result, once

**Shape.** The wrapper returns `ToolResult(error=<refusal>)`, so `ToolCallResult.from_tool_result` sets `is_error=True` and the transcript renders it as a failed step. This is the fix for C-3's defect **on the parked path only**; `BrowserTool.invoke`'s own return is untouched (C-3).

**Text.** Three constraints, all binding simultaneously:

1. **Not a capability gap.** Every authored string is checked against the **real imported** `decomposer._CAPABILITY_GAP_RE`, not a re-typed copy. `lack` is a bare substring, so `black`, `slack`, `blacklist` and `blackhole` all trip it — and `blacklist` is a plausible word in a browser refusal. Watch for it.
2. **Not success.** The `is_error=True` shape carries most of this, but the words must too: name the action as not performed.
3. **Not an invitation to retry.** Say so directly. Dedup (DD-1) makes a retry harmless to the store, but a retry loop still burns iterations against `AGENTIC_MAX_ITERATIONS`.

Suggested wording, to be re-run against the imported regex rather than trusted from this document:

- parked — `"This step needs the Captain's approval before it runs. It was filed for review as request {request_id} and the page was left as it was. Do not repeat this call — a repeat is folded into the same request. Continue with the rest of your task and report what remains open."`
- inbox full (DD-6) — `"This step needs the Captain's approval before it runs. Too many of your requests are already awaiting review, so it was refused rather than filed. Continue with the rest of your task and report what remains open."`
- credential (DD-1) — `"Credential entry stays a per-use Captain decision and was refused here. Continue with the rest of your task and report what remains open."`
- standing rule applied (informational, attached to the successful result as `disposition`, mirroring `_BROWSER_DISPOSITION`) — `"(This action ran under a standing approval issued by the Captain, valid until {expiry}.)"`

Note that `"was not performed"`, `"was refused"` and `"remains open"` are all clean under the regex; `"not available"`, `"no way"` and `"unable to"` are not.

### DD-3 — Resolution is a decision, not a replay. Approval unblocks the NEXT run, not this one

**What approval does:** flips `status` to `approved` durably, records `decided_by` / `decision_reason` / `decided_at`, fires `CAPABILITY_REQUEST_DECIDED`, records a trust outcome for the requesting agent (existing `decide()` behaviour, `:200-217`), and — when the Captain asked for it and standing rules are enabled — issues a scoped, expiring `ActionApproval` (DD-4).

**What approval does NOT do:** re-execute the parked action, and re-dispatch the originating work item. Both are rejected on the record:

- **Re-execution is unsafe by C-8.** The `session_id` in the payload almost certainly names a session reaped by `session_max_duration_seconds`. Creating a *fresh* session and replaying a page-relative `click` selector against whatever that page looks like now is a different act from the one the Captain approved. The payload's `session_id` is retained for forensics and is never passed to `BrowserTool`. Assert that directly.
- **Work-item re-dispatch is the AD-1155/DD-3 spend hazard in new clothing.** The child already completed with an honest partial result and a persisted `crew_execution` record. Re-running the whole agentic loop from a REST handler puts an unbudgeted, unbounded LLM run behind a button. If a future AD wants it, `WorkItemAgenticExecutor.run` is right there and the budget arithmetic is already solved — but it is not this AD.

**Say the limitation out loud, in the config description and in the DECISIONS entry:** *approval does not rescue the run that raised the ask. It converts a silent no-op into a durable record, a trust signal and — optionally — a rule that lets the next run proceed without asking.* An AD that quietly implied otherwise would be worse than one that does less.

**Denial** is already meaningful: `status="denied"`, a mandatory non-empty `reason` (`api_models.py:271`), a negative trust outcome, and the AD-855 driver's existing `capability_request_decided` handling. Nothing new is needed.

**API delta** — two optional fields on `CapabilityRequestDecideRequest` (`api_models.py:262`), both defaulted so every existing caller and every existing test is byte-identical:

```python
grant_standing: bool = False
standing_ttl_hours: int | None = None   # None -> config default; clamped to the config max
```

`grant_standing` is a **no-op** for `kind in (grant, install, build)` — log at INFO and ignore, do not 400. The router owns that branch; the store's `decide()` keeps its current signature and semantics.

### DD-4 — `ActionApprovalStore`: scoped to `(agent_id, tool_id, action, scope_key)`, TTL mandatory, no wildcards

New module `src/probos/tools/action_approvals.py`, mirroring `IntentGrantStore` (`cognitive/intent_grants.py`) structurally — `ConnectionFactory`, WAL, `busy_timeout=5000`, `synchronous=NORMAL`, in-memory cache for a zero-I/O sync read, soft revoke for audit.

```sql
CREATE TABLE IF NOT EXISTS action_approvals (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    tool_id TEXT NOT NULL,
    action TEXT NOT NULL,
    scope_key TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    issued_by TEXT NOT NULL DEFAULT 'captain',
    issued_at REAL NOT NULL,
    expires_at REAL NOT NULL,          -- NOT NULL. See below.
    revoked INTEGER NOT NULL DEFAULT 0,
    revoked_at REAL
);
CREATE INDEX IF NOT EXISTS idx_aa_lookup ON action_approvals(agent_id, tool_id, action, scope_key);
CREATE INDEX IF NOT EXISTS idx_aa_active ON action_approvals(revoked, expires_at);
```

**`expires_at REAL NOT NULL` is the load-bearing difference from the three sibling stores**, all of which allow `expires_at REAL` nullable = never expires. #1081: *"a standing rule with no TTL is a permanent privilege escalation nobody remembers granting."* Enforce it in the schema so it cannot be bypassed by a future caller passing `None`, not only in the method signature. `issue_approval(...)` takes `ttl_seconds: float` — not `expires_at: float | None` — so the type system carries the invariant too.

**Scope: four-part, exact match, no wildcard.** `is_approved_sync(agent_id, tool_id, action, scope_key) -> bool` matches all four fields exactly, plus `revoked == 0` and `expires_at > now`. Considered and rejected: a `scope_key == ""` wildcard meaning "any scope". It reads as a convenience and behaves as "approve every click on every site forever-until-TTL" — the single most dangerous row this table could hold, one typo away. A rule with `scope_key=""` matches only asks whose computed `scope_key` is `""`.

**`scope_key` is producer-computed; the store never parses a URL.** For `tool_id == "browser"` it is the lowercased hostname of `session.last_url` (or of `params["url"]` for `goto`), computed at park time by the wrapper. For any other tool it is `""`. This keeps the store generic without giving it a URL parser, and it means a browser standing rule is *always* domain-scoped — the operator cannot accidentally issue a global one.

**Considered and rejected: per-tool and per-tool+agent scoping.** Per-tool is `ToolPermissionStore` and already exists (C-4). Per-tool+agent without an action is the same thing with an extra column. Only the four-part key expresses the thing the Captain is actually being asked.

**Expiry is enforced on read, not by a reaper.** `is_approved_sync` filters on `expires_at > time.time()` and `_load_cache` filters the same way at start, mirroring `IntentGrantStore._load_cache` (`:118-127`). A row past its TTL is inert immediately; physical cleanup is a later concern and is explicitly not built here.

**Lifecycle.** Constructed in `startup/communication.py` beside `IntentGrantStore` (`:578`), added to `CommunicationResult` (`:756`), attached at `runtime.py:2897`-adjacent, stopped in `startup/shutdown.py` beside `intent_grant_store` (`:917-919`). Follow all four sites exactly; a store that starts and never stops leaks a connection on every restart.

### DD-5 — Heuristic auto-approval is DEFERRED, and the reason is that its inputs do not exist

MAF ships it; ProbOS already has its shape (`evaluate_grant_fast_path`, C-5); and it is still wrong to bundle here.

- **`peer_precedent` has no referent.** For a capability grant it means "an in-department peer already holds this tool" — a query over `ToolPermissionStore`. For an action shape, the only table that could answer is the one this AD creates, which is empty at the first ask. The signal that makes the existing fast path safe is structurally unavailable.
- **`non_destructive` is undecidable for the actions that matter.** It is derived from a tool's registered permission matrix (`_derive_tool_permission`, `capability_triage.py:78`). A browser `click`'s destructiveness is a property of the page, not the tool — which is exactly why `classify_action` resorts to URL-path substrings and element-text regexes and *still* escalates to a human.
- **A rule the Captain typed beats a rule the system guessed.** DD-4 gives the operator the whole of MAF's "don't ask again" relief through an explicit, scoped, expiring decision. The marginal value of auto-approval on top of that is one fewer first-time prompt; the marginal risk is an unattended agent performing an unreviewed consequential act. That trade is not close.
- **Review surface.** Bundling it roughly doubles the predicate area of this AD and puts the riskiest code in the same review as the storage migration. Ship the inbox, watch what actually gets approved, then design the predicate against real rows.

Record it as a follow-up in the roadmap Deferred column, naming `evaluate_grant_fast_path` as the shape to copy and this DD as the reason it was not.

### DD-6 — The inbox is bounded, and a full inbox degrades to a refusal, not to unbounded growth

An approval inbox with no cap is a memory leak wearing a governance costume, and — worse — it is the "an inbox nobody reads" failure mode made structural: 400 pending asks is indistinguishable from 0 to a human.

`approval_inbox.max_pending_per_agent` (default 20, `ge=1, le=200`). Counted from the store's cache, per `agent_id`, over `status == "pending"` only. At the cap, the wrapper **refuses without filing** (DD-2's second string) and logs at WARNING with the agent id and the count — the operator learns their inbox is saturated from the log, not from the panel silently growing.

`approval_inbox.pending_ask_ttl_hours` (default 72, `ge=1, le=720`) marks an undecided ask stale. **Stale means excluded from the per-agent count and rendered as stale, not auto-approved and not auto-denied.** Auto-approving on timeout would make walking away the approval mechanism; auto-denying would silently discard a decision the Captain may still want to make. `list_pending()` keeps returning stale asks — the panel is the place they should nag from.

**This is the AD's own answer to "an inbox nobody reads is worse than a refusal."** The cap converts a neglected inbox into an honest refusal within 20 asks per agent, rather than into an unbounded queue that looks like progress. It does not solve the human-attention problem; it bounds the damage when the human is absent.

### DD-7 — Consensus is not routable around this path. Assert it directly

Two independent guards, because this is the one property whose failure would be a governance regression rather than a bug:

1. **At park time.** The wrapper never files an ask for an action whose dispatch would be consensus-gated. Tool actions do not carry `requires_consensus` (that is an `IntentDescriptor` field, `agents/*.py`), so the guard is on the *mesh* side: `_MeshIntentTool.invoke` (`agentic_dispatch.py:465`) and `_McpTool.invoke`'s `CONSENSUS` branch (`:603`) are **not** wrapped. The wrapper arms for one tool id in this AD — `browser` — and the arming is a `frozenset` membership check in the same fail-safe direction as `_BROWSER_LOOP_ACTIONS` and `PARALLEL_SAFE_TOOL_IDS`: membership is the only way in, so anything new, renamed or unrecognised is not parked and takes its existing path.
2. **At resolution time.** `decide()` does not dispatch anything (DD-3), so there is no second dispatch path to gate. `POST /api/notifications/{id}/accept` — which *does* dispatch, through `bus.broadcast` with the existing AD-698 pre-authorization seam and consensus gating (`routers/system.py:431-437`) — is not used and is not modified.

Assert both: a test that arms the wrapper, invokes a mesh-intent tool and an MCP `CONSENSUS`-tier tool, and requires that **no** `CapabilityRequest` is filed and both take their unmodified path.

`ActionApprovalStore` grants nothing about intents and is consulted only by the wrapper, so a standing rule can never satisfy a quorum requirement. Assert that `is_approved_sync` is not called from any consensus code path — a `grep` guard in the test file, following the AD-1142 drift-guard shape.

### DD-8 — Default-OFF, byte-identical when off, gated twice

```python
class ApprovalInboxConfig(BaseModel):        # AD-1154
    enabled: bool = False
    standing_rules_enabled: bool = False
    standing_rule_max_ttl_hours: int = Field(default=168, ge=1, le=720)
    standing_rule_default_ttl_hours: int = Field(default=24, ge=1, le=720)
    max_pending_per_agent: int = Field(default=20, ge=1, le=200)
    pending_ask_ttl_hours: int = Field(default=72, ge=1, le=720)
```

**Two flags, not one.** `enabled` turns on parking. `standing_rules_enabled` additionally permits a durable privilege grant. An operator who wants the audit trail without the "don't ask again" lever gets exactly that, and the riskier half stays off until asked for. `standing_rule_default_ttl_hours` (24h) is deliberately far below the max (168h) so the low-effort path is the short-lived one.

Off ⇒ `DispatchToolExecutor.invoke` never calls the wrapper, `_action_approvals` stays `None`, `restrict_browser_actions`'s AD-1153 path is unchanged, and the kwarg dict reaching `super().invoke` is byte-identical. Assert key-for-key against a literal recomputation, per the AD-1142 Section 1 pattern.

Not a Σ flag; **do not touch `tests/ablation/sigma_flags.py`.**

**Cross-field relation, documented not validated** (AD-1142 precedent): `standing_rule_default_ttl_hours` must be `<= standing_rule_max_ttl_hours`. Clamp at issue time, assert in tests, and do **not** add a `@model_validator` — a validator here turns an unrelated `POST /config` into a 422.

### DD-9 — What is deliberately not built, so the next reader does not look for it

- **No new UI.** The HXI panel renders the fourth kind unchanged (C-1). It will show `kind: action` and `target`; it will not show `params`, and there is no Approve-with-standing checkbox in this AD. The `grant_standing` field is API-only until a follow-up adds the affordance. Say this plainly — an operator reading the roadmap should not expect a button that is not there.
- **No widening of `_BROWSER_LOOP_ACTIONS`.** Admitting `click` / `type` is the *follow-up* this AD unblocks, not part of it. Shipping the gate and the actions it gates in one change would mean the gate's first exercise is in production. `_BROWSER_LOOP_ACTIONS` is byte-identical at the end of this AD — assert it.
- **No re-execution and no work-item re-dispatch** (DD-3).
- **No auto-approval predicate** (DD-5).
- **No `HookBus.ask` wiring.** `AggregateDecision.asked` stays consumerless (C-9). Making it mean something is a `HookBus` change with its own most-restrictive-wins semantics, and the parking seam does not need it.
- **No unification of the four grant stores.** Flagged in `intent_grants.py:20-24`, still correct, still a separate refactor.

### DD-10 — The wrapper is one method, and it cannot raise

`DispatchToolExecutor._park_or_admit(agent_id, tool_id, params) -> ToolResult | None` — `None` means "admit, take the normal path". Called from `invoke` **before** `super().invoke`, immediately after the AD-1153 `_refuse_browser_action` block, so an action already refused as non-allowlisted is never parked (a refusal is not an ask).

Ordering inside `_park_or_admit`, and the order is load-bearing:

1. Not armed for this `tool_id` ⇒ `None`.
2. `classify_action(session, action, params) != 3` ⇒ `None`. **This requires a session**, and resolving one has a side effect (`_get_or_create_session`, `tool.py:249`). Do **not** create a session to answer a policy question — call the pure `classify_action` with the session the executor can already reach, and when there is none, treat only the *always*-tier-3 verbs (`compute_use_click`, `upload_file`, `eval_js`, `fill_credential`) as tier 3 and admit the rest to `BrowserTool`, whose own gate then runs as it does today. State this asymmetry; it is the difference between a wrapper and a second tier classifier.
3. `action == "fill_credential"` ⇒ credential refusal, no filing (DD-1).
4. Standing rule hit (`standing_rules_enabled` and `is_approved_sync(...)`) ⇒ `None` (admit), and the successful result carries the DD-2 informational disposition.
5. Per-agent pending cap reached ⇒ inbox-full refusal, no filing (DD-6).
6. File (or dedup onto) the ask ⇒ parked refusal carrying `request_id`.

**Every step absorbs its own exceptions and fails toward refusal, never toward admission.** A store that is down, a payload that will not serialise, a cache read that raises — all produce the parked refusal text with the request id omitted, logged at WARNING. The one thing that must never happen is a swallowed error causing step 6 to be skipped and the action to proceed. This is the Safety Budget axiom: a gate that cannot determine the answer assumes the maximum.

`_park_or_admit` is `async` (the store write is `async`), which is fine — `invoke` is already `async` and the wrapper adds one awaited SQLite INSERT to a call that is about to make a network round trip.

---

## Build

### Section 0 — BF-682: stop emitting the raw confirmation token

`src/probos/tools/browser/tool.py`, the `_safe_emit(EventType.TOOL_INTERVENTION_REQUIRED, ...)` payload at `:283-291`: replace `"confirmation_token": token` with `"confirmation_id": token[:8]`. The 8-hex prefix correlates a log line to a pending confirmation without being redeemable — `_consume_confirmation_token` (`:711`) matches the full key, so a prefix cannot satisfy it. Do not change `_generate_confirmation_token`, `_consume_confirmation_token` or `seed_confirmation_token`.

`tests/test_ad706_browser_tool.py:279` — `assert "confirmation_token" in payload` becomes `assert "confirmation_token" not in payload` plus `assert payload["confirmation_id"] == token_prefix`. That is the entire blast radius.

**BF-682 closes with this section.**

### Section 1 — `src/probos/capability_request.py`

- `RequestKind = Literal["grant", "install", "build", "action"]` (`:49`).
- `CapabilityRequest.payload: dict[str, Any] | None = None` — appended **last** so the dataclass field order is stable.
- `_SCHEMA` gains `payload TEXT` (nullable, last column).
- `start()` gains the DD-1 guarded `ALTER TABLE` migration, before `_refresh_cache()`.
- `_refresh_cache()`'s explicit SELECT gains `payload`; `_row_to_request` reads `row[11]` and decodes via a module helper that returns `None` on any decode or validation failure (log WARNING, do not raise — a corrupt row must not prevent the store from starting).
- `file_request()`'s INSERT gains the column and the positional value; existing callers pass nothing and get `NULL`.
- New `file_action_request(...)` — validates the payload shape (DD-1), computes the dedup key, returns an existing pending match unchanged, otherwise delegates to the same INSERT path. Emits `CAPABILITY_REQUEST_FILED` exactly as `file_request` does, so the AD-857 notifier and the AD-855 driver need no change.
- Module constants: `_ACTION_PAYLOAD_MAX_CHARS = 4000`, `_ACTION_PAYLOAD_KEYS` (frozenset of the six), `_TOOL_ID_RE`, `_ACTION_RE`, `_MAX_ACTION_PARAM_KEYS = 20`.

### Section 2 — `src/probos/tools/action_approvals.py` (NEW)

`ActionApproval` dataclass + `ActionApprovalStore`, per DD-4. Public API: `start()` / `stop()` / `issue_approval(...)` / `revoke_approval(id)` / `is_approved_sync(...)` / `list_approvals(active_only=True)`. Mirror `cognitive/intent_grants.py` structurally; the module docstring must state the C-4 finding (why neither existing store fits) and the DD-4 no-wildcard decision.

### Section 3 — `src/probos/cognitive/agentic_dispatch.py`

- Module constants near `_BROWSER_LOOP_ACTIONS` (`:103`): `_APPROVAL_INBOX_TOOL_IDS = frozenset({"browser"})`, `_ALWAYS_TIER_3_ACTIONS = frozenset({"compute_use_click", "upload_file", "eval_js", "fill_credential"})`, `_NEVER_PARK_ACTIONS = frozenset({"fill_credential"})`, and the four DD-2 strings. Comment block stating the fail-safe direction and citing AD-1147/DD-1 and AD-1153/DD-1 as precedent.
- `DispatchToolExecutor.__init__` (`:338`) gains `self._approval_inbox: Any = None` (unarmed default) mirroring `self._browser_actions = None` (`:343`).
- `DispatchToolExecutor.arm_approval_inbox(*, request_store, approval_store, config)` — post-construction, same reasoning as `restrict_browser_actions` (`:345-361`).
- `DispatchToolExecutor._park_or_admit(...)` per DD-10.
- `invoke()` (`:384`) calls it after the AD-1153 `restricted` refusal block (`:394-398`) and before `super().invoke`.
- `WorkItemAgenticExecutor.run` arms the inbox alongside the AD-1153 `restrict_browser_actions` call (`:1191`), gated on `config.approval_inbox.enabled` and the two stores being present.
- `_ALWAYS_TIER_3_ACTIONS` must be asserted as a subset of the verbs `classify_action` short-circuits to 3 — a drift guard, since that function is in a module this file does not import.

### Section 4 — `src/probos/config.py`

`ApprovalInboxConfig` per DD-8, plus `approval_inbox: ApprovalInboxConfig = Field(default_factory=ApprovalInboxConfig)` on `SystemConfig`. Descriptions must carry: the DD-3 statement that approval does not replay the action, the DD-6 cap-degrades-to-refusal behaviour, the DD-4 mandatory-TTL rationale, and the DD-9 note that no HXI affordance for `grant_standing` ships here.

### Section 5 — `src/probos/api_models.py` + `src/probos/routers/capability_requests.py`

- `CapabilityRequestDecideRequest` gains `grant_standing: bool = False` and `standing_ttl_hours: int | None = None` (DD-3). The existing `_require_reason_on_deny` validator is unchanged.
- `_serialize` (`:26`) gains `"payload": req.payload`.
- `decide_capability_request` gains the standing-rule branch: only for `kind == "action"`, only when `standing_rules_enabled` and `approve` and `grant_standing`, TTL clamped to `standing_rule_max_ttl_hours`. Missing store ⇒ `{"standing_rule": None}` in the response, HTTP 200 — honest-degrade, never a 500, following the AD-1053 convention at `routers/system.py:431`.

### Section 6 — startup / shutdown wiring

- `src/probos/startup/communication.py` — construct + `start()` the store beside `IntentGrantStore` (`:578`); add to `CommunicationResult` (`:756`).
- `src/probos/runtime.py` — `self.action_approval_store = comm.action_approval_store` beside `:2897`.
- `src/probos/startup/shutdown.py` — `stop()` + `None` beside `:917-919`.

### Section 7 — `docs/development/config-reference.md`

Regenerate with `python scripts/gen_config_reference.py`. Do not hand-edit.

### Section 8 — Tests

`tests/test_ad1154_approval_inbox.py` (NEW), ≈40 tests. Reuse the `tmp_path` store fixture from `tests/test_ad853_capability_request.py:12` and the `_FakeRegistry` / executor doubles from `tests/test_ad1153_browser_agentic_loop.py`. Import the **real** `_CAPABILITY_GAP_RE` from `probos.cognitive.decomposer`.

**No new files under `src/` other than `tools/action_approvals.py`.** **No edit to** `src/probos/tools/browser/tool.py` beyond Section 0's one payload key, `src/probos/notifications.py`, `src/probos/routers/system.py`, `src/probos/cognitive/swe_harness/agentic_loop.py`, `src/probos/cognitive/crew_executor.py`, `src/probos/cognitive/crew_verifier.py`, `src/probos/tools/permissions.py`, `src/probos/cognitive/intent_grants.py`, or anything under `ui/`.

---

## Acceptance

**Headline — an unattended tier-3 action is parked, the run continues, and the agent is told the truth. It must behave differently with the flag off.**

> A `DispatchToolExecutor` armed with the inbox invokes `browser` with `action="click"` against a tier-3 URL. With `approval_inbox.enabled=True`: exactly one `CapabilityRequest` with `kind="action"` exists in the store, its payload decodes to the producer's `(tool_id, action, params, scope_key)`, the returned `ToolResult.error` is non-`None`, `ToolCallResult.from_tool_result(...).is_error` is `True`, and `BrowserTool.invoke` was **never entered** — assert on the tool double's call count, not on the result shape. With the flag off — **the same test body, one flag flipped** — zero requests are filed, `BrowserTool.invoke` is entered once, and the result is the success-shaped `intervention_required` no-op that HEAD produces today.

**Durability (DD-1) — the mandatory real-DB round trip:**
- Write an `action` request through a real `tmp_path` DB, `stop()`, construct a **second** `CapabilityRequestStore` on the same path, `start()`, and assert the reloaded payload is byte-identical under canonical JSON. This is the test that exercises `_row_to_request`, the SELECT column list and the migration; a cache-only suite cannot.
- **Migration:** create a DB with the pre-AD-1154 11-column schema, then `start()` a new-code store against it and assert `payload` exists, no exception is raised, and pre-existing rows load with `payload is None`.
- A row whose `payload` column holds invalid JSON, a non-dict, a dict with a missing key, a dict with an extra key, or an over-length `params` ⇒ loads as `payload=None` with a WARNING; the store still starts and the other rows are intact.
- `confirmation_token` present in `params` at file time ⇒ absent from the persisted payload. Assert on the reloaded row, not the in-memory object.
- `action="fill_credential"` ⇒ **no** request filed, credential refusal returned.
- Dedup: three identical parked calls ⇒ one row, and all three return the same `request_id`.
- Dedup does **not** collapse across differing `scope_key`, differing `params`, or a request already `approved`/`denied` — four separate tests.
- Payload bounds: 21 param keys, a non-`str` param key, a non-serialisable value, a 5000-char serialised form, a `tool_id` failing the regex — each rejected, no filing, no raise.
- `kind` in `(grant, install, build)` still writes `payload IS NULL`, and `tests/test_ad853_capability_request.py` passes unchanged.

**Agent-facing text (DD-2):**
- Every authored string is clean under the **real imported** `_CAPABILITY_GAP_RE` — parked, inbox-full, credential, and the standing-rule disposition, each with a realistic `request_id` / `expiry` interpolated.
- A rendered parked refusal contains the request id and does not contain `"intervention_required"`.
- `ToolCallResult.from_tool_result` on the parked result gives `is_error=True` — asserted through the real adapter, not by inspecting `ToolResult`.

**Resolution (DD-3):**
- `POST /api/capability-requests/{id}/decide` with `approve=True` on an `action` request ⇒ `status="approved"`, and **`BrowserTool.invoke` is not called** and **`WorkItemAgenticExecutor.run` is not called**. Assert both call counts are zero — this is the C-8 property and it is the one a future refactor is most likely to "improve" away.
- The payload's `session_id` is never passed to any browser API — assert the tool double received no call at all during decide.
- `approve=True, grant_standing=True` with `standing_rules_enabled=True` ⇒ exactly one `ActionApproval`, matching all four scope fields, with `expires_at` in the future and `<= now + standing_rule_max_ttl_hours`.
- Same call with `standing_rules_enabled=False` ⇒ no approval issued, HTTP 200, `{"standing_rule": None}`.
- `grant_standing=True` on `kind="grant"` ⇒ ignored, no approval issued, HTTP 200, existing behaviour byte-identical.
- `approve=False` requires a reason (existing validator) and issues no standing rule even with `grant_standing=True`.
- Deciding an already-decided request still returns 400 (existing `routers/capability_requests.py:81-85` guard, unchanged).

**Standing rules (DD-4):**
- A matching active approval ⇒ the action is admitted, `BrowserTool.invoke` **is** entered, no request filed, and the result carries the informational disposition.
- Mismatch on any **one** of the four scope fields ⇒ parked. Four separate tests. The `scope_key` case must use a *sibling* domain (`docs.github.com` vs `github.com`) to prove there is no suffix matching.
- `scope_key=""` in the rule does **not** match an ask whose `scope_key` is `"github.com"` — the no-wildcard assertion.
- Expired (`expires_at` in the past) ⇒ parked. Revoked ⇒ parked.
- `issue_approval` has no parameter that produces a NULL `expires_at` — assert via `inspect.signature`, and assert the schema declares `expires_at` `NOT NULL` by reading `PRAGMA table_info`.
- Real-DB round trip for `ActionApprovalStore` too: issue, stop, reopen, `is_approved_sync` still `True`.
- `list_approvals(active_only=True)` excludes expired and revoked.

**Bounds (DD-6):**
- `max_pending_per_agent=2`: the third distinct ask ⇒ inbox-full refusal, **no** row written, WARNING logged with the agent id and count. Assert the store row count is exactly 2.
- The cap is **per agent** — a second agent at the same moment can still file.
- Deciding one pending ask frees a slot; the next ask files.
- An ask older than `pending_ask_ttl_hours` is excluded from the cap count but is **still returned by `list_pending()`** and its `status` is still `"pending"` — it is neither auto-approved nor auto-denied.

**Consensus (DD-7):**
- `_MeshIntentTool.invoke` and `_McpTool.invoke` at `CONSENSUS` tier, with the inbox armed ⇒ zero requests filed, both take their unmodified path. This is the "no second, weaker path around consensus" assertion and it must be direct.
- `_APPROVAL_INBOX_TOOL_IDS == {"browser"}` — the fail-safe drift guard.
- `_ALWAYS_TIER_3_ACTIONS` is a subset of the verbs `classify_action` short-circuits to 3 — assert by calling the real `classify_action` for each member.
- A source grep asserting `is_approved_sync` appears in no module under `src/probos/consensus/`.

**Seam and OFF-path (DD-8, DD-10):**
- Flag OFF ⇒ the kwarg dict reaching `super().invoke` is asserted **key-for-key and value-for-value** against a literal recomputation.
- `_BROWSER_LOOP_ACTIONS` is byte-identical — `assert _BROWSER_LOOP_ACTIONS == frozenset({"goto","state","extract_text","back","forward","wait"})`.
- An unarmed `DispatchToolExecutor` (`_approval_inbox is None`) behaves byte-identically to AD-1153 — `tests/test_ad1153_browser_agentic_loop.py` passes unchanged.
- An action already refused by `_refuse_browser_action` is **not** parked — the AD-1153 refusal wins and no row is written.
- Store failures fail toward refusal: `file_action_request` raising, `is_approved_sync` raising, and a store that is `None` — each produces a refusal (never an admission), no exception escapes `invoke`, and a WARNING is logged. Three tests; the `is_approved_sync`-raising case is the important one, because failing open there admits the action.
- No session available ⇒ only `_ALWAYS_TIER_3_ACTIONS` park; `click`/`type` pass through to `BrowserTool` and hit its own gate (DD-10 step 2).

**Config (DD-8):**
- `SystemConfig()` constructs with zero configuration and `approval_inbox.enabled is False`, `standing_rules_enabled is False`.
- `standing_rule_default_ttl_hours <= standing_rule_max_ttl_hours` on defaults; a request exceeding the max clamps rather than raising; no `@model_validator` was added — assert `"approval_inbox"` triggers no 422 on an out-of-range sibling field.
- The regenerated `config-reference.md` contains the DD-3 "approval does not replay the action" sentence and the DD-6 cap behaviour — doc-grep test, AD-1142 Section 11 precedent.

**BF-682 (Section 0):**
- The `TOOL_INTERVENTION_REQUIRED` payload has no `confirmation_token` key and has a `confirmation_id` that is an 8-char prefix.
- `_consume_confirmation_token` still rejects the 8-char prefix and still accepts the full token — both directions.

---

## Testing

**Do NOT run the full suite.** Run exactly these, serially:

```powershell
d:/ProbOS/.venv/Scripts/pytest.exe `
  tests/test_ad1154_approval_inbox.py `
  tests/test_ad853_capability_request.py `
  tests/test_ad854_capability_triage.py `
  tests/test_ad855_block_resume.py `
  tests/test_ad857_capability_request_api.py `
  tests/test_ad857_capability_request_notifier.py `
  tests/test_ad1153_browser_agentic_loop.py `
  tests/test_ad706_browser_tool.py `
  tests/test_ad423b_tool_permissions.py `
  tests/test_ad1005_intent_grants.py `
  tests/test_ad1053_actionable_notifications.py `
  -q -n 0
```

`test_ad853` / `test_ad854` / `test_ad855` / `test_ad857*` are the byte-identity guards on the store, the triage router, the resume driver and the API being extended — if any moves, the fourth kind is not additive. `test_ad1153` proves the AD-1153 seam is untouched. `test_ad706` carries Section 0's blast radius. `test_ad423b` / `test_ad1005` prove the two capability-grant stores are unchanged (C-4). `test_ad1053` proves the notification path is untouched (C-2).

---

## What this does NOT change

`AgenticLoop`'s iteration, `stopped_reason` set or message construction · suspension or checkpointing of any kind · `WorkItemAgenticExecutor.run`'s signature or body · `CrewTaskExecutor._run_child` and the AD-1155 outer loop · `SubtaskVerifier.converge_for_session` · `_BROWSER_LOOP_ACTIONS` and the AD-1153 read-only partition · `BrowserTool.invoke`'s tier-3 return, `classify_action`, `_generate_confirmation_token`, `_consume_confirmation_token` or `seed_confirmation_token` · the AD-745 DM browser dispatch path · `NotificationQueue`, `AgentNotification`, `suggested_action` or `POST /api/notifications/{id}/accept` · `ToolPermissionStore`, `IntentGrantStore`, `SkillGrantStore` or `registry.check_permission` · consensus, quorum, Shapley or `requires_consensus` on any intent · `HookBus`, `AggregateDecision.asked` or the PreDispatch capability gate · `evaluate_grant_fast_path` and the AD-854 grant fast path · the 14-key `crew_execution` set · the `SubtaskResult` field set · `WorkItem.description` or the plan-identity hash · `tests/ablation/sigma_flags.py` · anything under `ui/`.

---

## Tracking

- **`PROGRESS.md`** — AD-1154 shipped, one line. AD ceiling stays **AD-1155**; next free **AD-1156**. BF ceiling stays **BF-683**; next free **BF-684**. Mark **BF-682 CLOSED** with a one-line reason.
- **`docs/development/roadmap.md`** — update the AD-1154 row from planned to shipped, and state what it deliberately does not do (no re-execution, no auto-approval, no widened browser allowlist, no new UI). Mark the **BF-682** row CLOSED. Add a Deferred entry for heuristic auto-approval naming `evaluate_grant_fast_path` as the shape and DD-5 as the reason.
- **`DECISIONS.md`** (era 5) — AD-1154 entry. It must record C-1, C-2 and C-8 explicitly: *the approval inbox already existed (AD-853/854/855/857) and this AD added a fourth kind to it rather than a fifth store; `NotificationQueue` is in-memory, so the AD-1053 accept path could not carry a durable ask; and approval cannot replay the parked action because the browser session TTL (1800 s) is shorter than human decision latency.* Those three are what a future AD will otherwise rediscover expensively.
- **`docs/development/config-reference.md`** — regenerated, not hand-edited.

## Acceptance criteria

- The headline test behaves differently with the flag off and on, in the same test body, and asserts on `BrowserTool.invoke`'s call count rather than on a result shape.
- The parked result is error-shaped through the real `ToolCallResult.from_tool_result`, and every authored string is clean under the real imported `_CAPABILITY_GAP_RE`.
- The real-DB round trip and the 11-column migration test both pass; no cache-only substitute is accepted for either.
- A standing rule matches on all four scope fields and on none fewer; `expires_at` cannot be NULL by schema, not only by convention.
- Consensus-gated dispatch is provably not routable through this path, asserted directly for both mesh intents and MCP `CONSENSUS`-tier tools.
- Every failure mode of the wrapper degrades to a refusal, never to an admission.
- Default-OFF is byte-identical, asserted key-for-key against a literal recomputation.
- BF-682 is closed and its single blast-radius assertion is inverted.
- **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Verified Against Codebase (2026-07-26, HEAD `015c3643`)

```
git log --oneline -2
  015c3643 AD-1155: loop-until-done - outer completion evaluator over crew children
  ed3f9f52 AD-1153: offer the browser tool to the agentic loop (read-only v1)

--- C-1: the inbox exists ---
grep -n "class CapabilityRequestStore\|class CapabilityRequest\b\|RequestKind = Literal\|RequestStatus = Literal" src/probos/capability_request.py
  49: RequestKind = Literal["grant", "install", "build"]
  50: RequestStatus = Literal["pending","approved","denied","fulfilled","failed"]
  55: class CapabilityRequest:
  71: class CapabilityRequestStore(EventEmitterMixin):
grep -n "def start\|def file_request\|def decide\|def mark_fulfilled\|def list_pending\|def _row_to_request\|_RATIONALE_MAX" src/probos/capability_request.py
  30: _RATIONALE_MAX = 280      99: async def start      126: async def file_request
  172: async def decide          231: async def mark_fulfilled  263: async def list_pending
  271: def _row_to_request
sed -n '32,47p' src/probos/capability_request.py
  CREATE TABLE capability_requests ( id, agent_id, kind, target, rationale,
    work_item_id, status, created_at, decided_at, decided_by, decision_reason )   # 11 cols
grep -n "router = APIRouter\|async def list_capability_requests\|async def decide_capability_request\|def _serialize" src/probos/routers/capability_requests.py
  22: prefix="/api/capability-requests"   26: _serialize   46: list   65: decide
grep -n "capability-requests\|kind: string\|function departmentColor\|req.kind" ui/src/components/capability/CapabilityRequestPanel.tsx
  18: kind: string;   44: function departmentColor(kind: string)   84/117/120
  193: fetch('/api/capability-requests?status=pending')
  209: fetch(`/api/capability-requests/${id}/decide`)
grep -n "_wire_capability_gap_driver\|_wire_capability_request_notifier" src/probos/startup/finalize.py
  2509 / 2557   (listeners on capability_request_decided|fulfilled|filed)
grep -n "await store.file_request(" src/probos/cognitive/capability_triage.py
  190:    req = await store.file_request(

--- C-2: NotificationQueue is in-memory ---
grep -n "class NotificationQueue" -A 6 src/probos/notifications.py
  63: """Persistent notification queue ..."""      # docstring is WRONG
  66:   self._notifications: dict[str, AgentNotification] = {}
grep -rn "NotificationQueue(" src/probos/
  runtime.py:1140:  self.notification_queue = NotificationQueue(on_event=self._emit_event)
grep -n "async def accept_notification" -A 12 src/probos/routers/system.py
  427-444: reads n.suggested_action; client body carries no intent (AD-1053 invariant)
grep -n "class CapabilityRequestDecideRequest" -A 8 src/probos/api_models.py
  262-270: approve: bool ; reason: str = "" ; _require_reason_on_deny

--- C-3: the success-shaped no-op ---
sed -n '300,312p' src/probos/tools/browser/tool.py
  300:     error="intervention_required",          # <- argument to self._audit(...)
  304:  return ToolResult(
  307:      "intervention_required": True, "tier": 3, "session_id": ...
             # NO error= kwarg  =>  ToolResult.error is None
grep -n "def from_tool_result" -A 10 src/probos/cognitive/swe_harness/tool_call.py
  39-49: if tool_result.error is not None: ... is_error=True   # else branch => False
grep -n "_pending_confirmations\|def reap_expired\|def _generate_confirmation_token\|def _consume_confirmation_token" src/probos/tools/browser/tool.py
  76 / 186 / 696 / 711 / 703 / 742

--- C-4: neither grant store can express an action shape ---
sed -n '20,33p' src/probos/tools/permissions.py
  tool_access_grants( id, agent_id, tool_id, permission, is_restriction, ... )   # no action, no scope
sed -n '40,52p' src/probos/cognitive/intent_grants.py
  intent_access_grants( id, agent_id, intent_name, is_restriction, ... )         # no action, no scope
sed -n '20,24p' src/probos/cognitive/intent_grants.py
  "NOTE (refactor candidate ...): this is the third store mirroring ToolPermissionStore"

--- C-5: heuristic auto-approval already exists ---
grep -n "def evaluate_grant_fast_path" -A 18 src/probos/cognitive/capability_triage.py
  53-72: fast_path_enabled and non_destructive and peer_precedent and agent_trust >= trust_floor
  78: def _derive_tool_permission(registration)     # non_destructive is matrix-derived
  253: auto = evaluate_grant_fast_path(...)

--- C-6: BF-682 ---
sed -n '283,291p' src/probos/tools/browser/tool.py
  "confirmation_token": token,        # raw token in the emitted payload
grep -n 'confirmation_token" in payload' tests/test_ad706_browser_tool.py
  279:    assert "confirmation_token" in payload
roadmap.md:895  BF-682 ... "Becomes load-bearing at AD-1154." | Precondition for AD-1154

--- C-7: no tool event is persisted (measured) ---
grep -n "def _emit_event\b" -A 40 src/probos/runtime.py
  1621-1657: NATS js_publish OR _emit_event_local ; EventLog.log is on NEITHER path
sqlite3 data/events.db "select event,count(*) from events group by event"
  402483 rows / 8 distinct: agent_wired 252802, pool_created 135016, started 4508,
  stopping 4504, stopped 4503, intent_resolved 572, intent_broadcast 572,
  ward_room_echo_detected 6
  tool_intervention_required 0 | tool_invoked 0 | browser_session_started 0
  browser_session_closed 0 | notification 0 | notification_ack 0

--- C-8: session TTL vs human latency ---
grep -n "session_max_duration_seconds\|confirmation_timeout_seconds" src/probos/config.py
  1568: session_max_duration_seconds: int = 1800
  1581: confirmation_timeout_seconds: int = 300   # auto-deny if Captain doesn't ACK

--- C-9 + seams ---
grep -n "_BROWSER_LOOP_ACTIONS: frozenset" -A 2 src/probos/cognitive/agentic_dispatch.py
  103: frozenset({"goto","state","extract_text","back","forward","wait"})
grep -nE "^class |def (invoke|restrict_browser_actions|_refuse_browser_action)\b" src/probos/cognitive/agentic_dispatch.py
  324: class DispatchToolExecutor(ToolExecutor)
  345: def restrict_browser_actions      362: def _refuse_browser_action
  384: async def invoke                  (DispatchToolExecutor.invoke — the wrapper seam)
  421: class _MeshIntentTool  -> 465: async def invoke
  514: class _McpTool         -> 603: async def invoke
  802: class WorkItemAgenticExecutor
grep -n "_browser_actions\|executor.restrict_browser_actions" src/probos/cognitive/agentic_dispatch.py
  343 (init) / 360 (setter) / 369 / 394 (invoke guard) / 1191 (arming call site)
grep -n "def classify_action" -A 40 src/probos/tools/browser/actions.py
  always-3: compute_use_click, upload_file, eval_js, fill_credential
  tier-1 silent set INCLUDES "scroll" ; goto => 2 ; click/type/drag/mouse_button => URL/text checks
grep -n "def asked\|class AggregateDecision\|ASK = " src/probos/hooks/bus.py
  67: ASK = "ask"   90: class AggregateDecision   107: def asked
grep -rnE "\.asked\b" src/probos/     # 2 hits, both unrelated prose (reply_pipeline:1125, counselor:532)
                                       # => AggregateDecision.asked has ZERO consumers
python -c "from probos.cognitive.decomposer import _CAPABILITY_GAP_RE as R; print(R.pattern)"
  ...|lack(?:s|ing)?|...     # bare substring confirmed

--- wiring seam ---
grep -n "IntentGrantStore(\|ToolPermissionStore(\|CommunicationResult(" src/probos/startup/communication.py
  487: CapabilityRequestStore(   578: IntentGrantStore(   657: ToolPermissionStore(
  756: return CommunicationResult(  ... 770/773/776
grep -n "self.intent_grant_store = comm\|self.tool_permission_store = comm" src/probos/runtime.py
  2856 / 2897
grep -n "intent_grant_store" src/probos/startup/shutdown.py
  917-919
grep -n "async def store\|test_persistence_round_trip" tests/test_ad853_capability_request.py
  12 (tmp_path fixture) / 96 (real-DB round trip — the pattern to mirror)
ls data/*.db | findstr capability_requests     # absent: created on first file_request
```
