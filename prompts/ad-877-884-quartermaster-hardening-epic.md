# Epic AD-877 → AD-884 — Quartermaster hardening (the "what we have not considered" follow-on)

**Repo:** OSS (`d:\ProbOS`). **GitHub issue: #847.** **Highest committed AD: AD-876** (Wave 232, work-board
reconciliation epic / Quartermaster shipped and enabled). This epic reserves **AD-877 → AD-884**.

**Why:** AD-874→876 shipped the *polling backstop* of work-board reconciliation: a deterministic
Utility-tier `QuartermasterAgent` that sweeps the board every `interval_seconds` and re-dispatches
items whose assignee is no longer live. The post-ship review surfaced eight gaps. This epic closes
them. Each AD is a single testable change; one AD = one commit.

> **Architect:** your job for this epic is (1) a verify-first review of every claim below against the
> live codebase, (2) drafting the per-AD build prompts `prompts/build-ad877.md` … `prompts/build-ad884.md`,
> and (3) recommending a build order + flagging which ADs are build-ready now vs. which should ship as a
> minimal, config-gated, default-off first cut. Every numeric claim, method name, and line number below
> is a candidate defect — grep before quoting. State the verified highest AD in your review.

---

## Shipped surface this epic builds on (verified APIs — re-verify before drafting)

- `src/probos/agents/quartermaster.py` — `QuartermasterAgent(BaseAgent)`, `tier="utility"`, no LLM.
  `reconcile()` is the sweep: pulls `status="open"` + `status="in_progress"` (each `limit=self._scan_limit`),
  merges by id, calls `self._reconciler.classify(wi, is_dispatchable=...)`, acts on the decision via
  `self._router` + `self._store`, emits `EventType.WORK_ITEM_RECONCILED` with a counts dict, stores an
  episode. Honest-degrade per item (continue sweep on exception).
- `src/probos/cognitive/work_reconciler.py` — `WorkItemReconciler` (pure, no mutation):
  `resolve_live_agent(assigned_to) -> str | None` and `classify(wi, *, is_dispatchable) -> ReconcileDecision`.
  `ReconcileDecision` is a frozen dataclass `(work_item_id, action, assignee, resolved_agent_id, reason)`;
  `action ∈ {"live_redispatch","clear_and_reroute","skip"}`. `_TERMINAL = {"done","failed","cancelled"}`.
- `src/probos/mesh/work_item_router.py` — `is_dispatchable(wi) -> bool` (l.59), `async dispatch_work_item(wi)`
  (l.68, the AD-874 reusable route), `async on_work_item_created(event)` (l.159, the create-listener that
  now delegates to `dispatch_work_item`).
- `src/probos/mesh/board_reconciler_ticker.py` — `BoardReconcilerTicker(*, agent, interval_seconds,
  warm_boot, startup_delay=10.0)`; idempotent `start()`/`stop()`, holds its `asyncio.create_task` ref,
  `_safe_reconcile()` Tier-2 degrade, re-raises `CancelledError`.
- `src/probos/config.py:4543` — `WorkBoardReconcilerConfig` (`enabled=False` default; **now `enabled: true`
  in `config/system.yaml`**). Fields: `interval_seconds` `[30,3600]`, `warm_boot`, `scan_limit` `[1,2000]`.
  Sibling of `hybrid_dispatch` on `SystemConfig` (config.py:5266). Hard-depends on `hybrid_dispatch.enabled`
  (the reconciler needs `runtime.work_item_router`).
- `src/probos/startup/finalize.py` — `_wire_board_reconciler(*, runtime, config) -> bool` builds the
  `WorkItemReconciler`, resolves the live quartermaster (`registry.get_by_pool("quartermaster")`), injects
  collaborators by exact private attrs (`agent._reconciler/_store/_router/_emit/_episodic/_scan_limit`),
  starts the ticker, parks it on `runtime.board_reconciler_ticker`.
- `src/probos/workforce.py:581` — `WorkItem` dataclass. Relevant fields: `status`, `assigned_to`,
  `created_at`, `updated_at`, `priority`, and a free-form `metadata: dict[str, Any]` (persisted as the
  `metadata TEXT` JSON column, l.844). `_IMMUTABLE_FIELDS = {"id","created_at","created_by"}` — so
  `metadata`, `status`, `assigned_to`, `updated_at` are mutable via `update_work_item`.
- `src/probos/events.py` — `WORK_ITEM_RECONCILED` (l.101, AD-875), `WORK_ITEM_QUARANTINED` (l.304, AD-528b).
  **Verify-first:** confirm whether a store-side quarantine mechanism (a `quarantined` status value and/or a
  `quarantine_work_item` method) actually exists, or whether AD-528b only defined the event. AD-877 depends
  on the answer.

---

## The eight ADs

### AD-877 — Reconcile-attempt tracking + dead-letter quarantine (thrash guard) — **highest priority**
**Problem:** if a `clear_and_reroute` item's *next* assignee is also not live (genuinely no agent of that
type, or a real capability gap), the sweep clears-and-reroutes it **every cycle forever**. No counter,
no backoff, no terminal state.
**Build:**
- Track attempts in `WorkItem.metadata["reconcile_attempts"]` (int) and `metadata["last_reconcile_at"]`
  (float epoch). Increment on each `clear_and_reroute` for that item.
- Add config to `WorkBoardReconcilerConfig`: `max_reconcile_attempts: int = Field(default=3, ge=1, le=20)`,
  `reconcile_backoff_seconds: int = Field(default=600, ge=0, le=86400)`.
- When `reconcile_attempts >= max_reconcile_attempts`: **stop re-routing**; move the item to the existing
  quarantine path (emit `WORK_ITEM_QUARANTINED` + set the quarantined status if that mechanism exists —
  Architect verifies AD-528b's surface; if no status exists, the minimal cut is "skip + emit
  `WORK_ITEM_QUARANTINED` + mark `metadata['quarantined']=True`" and the reconciler treats quarantined
  items as `skip`).
- Backoff: skip any item whose `last_reconcile_at` is within `reconcile_backoff_seconds` of now.
**Tests (≥10):** attempt increments; quarantine at threshold; quarantined item skipped on next sweep;
backoff skip; counts dict gains `quarantined`/`backoff_skipped`. Real `WorkItemStore` (BF-287).
**Do not:** add a new DB column; use `metadata`.

### AD-878 — Boot-race grace period + dispatch idempotency guard
**Problem:** the warm-boot sweep fires `startup_delay` (~10s) after boot. A freshly-created item that is
mid-first-dispatch could look stranded and be double-dispatched.
**Build:**
- Add `min_item_age_seconds: int = Field(default=30, ge=0, le=600)` to `WorkBoardReconcilerConfig`.
- In the sweep, **skip** any item whose `created_at` is younger than `now - min_item_age_seconds`
  (reason `too_fresh`); add `counts["too_fresh"]`.
- Verify-first: confirm `dispatch_work_item` is safe to re-run on an already-dispatched item (it should be,
  since `on_work_item_created` and the reconciler both call it). If it is not idempotent, the Architect
  scopes the minimal guard; **do not** rework the dispatch path beyond what's needed.
**Tests (≥6):** fresh item skipped; aged item processed; boundary at exactly `min_item_age_seconds`.

### AD-879 — Deterministic oldest-first scan ordering + starvation guard
**Problem:** `scan_limit` caps the sweep at 200 items per status. With a backlog >200, nothing guarantees
the *oldest* stranded items are seen first — they can starve.
**Build:**
- Ensure the sweep processes oldest-first (sort merged items by `(priority, created_at)` or confirm
  `list_work_items` already returns a deterministic oldest-first order — verify-first).
- When the merged count reaches `scan_limit`, set `counts["truncated"]=True` and log a Tier-2 warning so a
  growing backlog is visible.
**Tests (≥5):** ordering deterministic + oldest-first; truncation flag set when backlog exceeds limit.
**Do not:** raise the default `scan_limit`.

### AD-880 — Reactive reclaim on agent removal (event-driven; sweep becomes the safety net)
**Problem:** reclaim is poll-only — up to `interval_seconds` (5 min) latency. Mature schedulers pair the
sweep with a reactive reclaim triggered when an agent dies/deregisters.
**Build (minimal, config-gated):**
- Emit a bus event when an agent is removed. Verify-first: today `runtime.py:4411` logs an `event_log`
  `"agent_removed"` (event-log category, **not** an `EventType`); `registry.unregister` and
  `pool.remove_agent` are the removal seams. The minimal cut adds an `AGENT_REMOVED` `EventType` emitted at
  the canonical removal point.
- Quartermaster subscribes (when enabled) and runs a **scoped** reconcile of just that agent's items
  (a new `reconcile_for_agent(agent_id)` that reuses the same classify→act path).
- Gate behind a new `reactive_reclaim: bool = False` on `WorkBoardReconcilerConfig` (default off — it adds a
  bus subscription).
**Tests (≥8):** event emitted on unregister; subscriber reclaims only the dead agent's items; disabled = no
subscription. Real registry + store.
**Do not:** change the sweep's semantics; reactive is additive.

### AD-881 — Liveness ≠ progress: detect live-but-stalled assignees
**Problem:** the reconciler reclaims only items whose assignee is **absent** from the registry. An assignee
that is live but silently stuck (no progress/heartbeat) is never reclaimed.
**Build (first cut, config-gated, default-off):**
- Add `stall_timeout_seconds: int = Field(default=0, ge=0, le=86400)` (0 = disabled) to the config.
- When >0, an `in_progress` item whose `updated_at` is older than `now - stall_timeout_seconds` AND whose
  owner is live is classified `clear_and_reroute` with reason `stalled` (subject to the AD-877 attempt
  guard so it can't thrash).
- Verify-first: confirm `updated_at` advances on real progress (claim/heartbeat) — if it doesn't, the
  Architect identifies the right staleness signal or scopes this to a documented no-op default.
**Tests (≥6):** disabled (0) never reclaims; stalled live item reclaimed when enabled; fresh `updated_at`
not reclaimed.
**Do not:** add new heartbeat plumbing; use existing timestamps/signals only.

### AD-882 — Federation node-scope guard
**Problem:** liveness is checked against the **local** registry. In a multi-node mesh, an item assigned to
an agent on another node looks "not live" locally and would be wrongly reclaimed.
**Build (guard only; no-op single-node):**
- Before `clear_and_reroute`, if the assignee resolves to a **remote-node** agent (verify-first: how does
  ProbOS mark node ownership — `federation/` peer/identity? a node_id on the agent/slot?), skip with reason
  `remote_owner`. On a single-node deployment this is a no-op.
**Tests (≥5):** remote-owned item skipped; local item still reclaimed; single-node unaffected.
**Do not:** build federation routing; this is a defensive skip only.

### AD-883 — Observability: reconciliation status surface
**Problem:** the sweep emits `WORK_ITEM_RECONCILED` counts, but the Captain can't *see* reconciliation
activity (HXI principle #6: the canvas is the information; #10 the Ship's Computer reports from sensors).
**Build:**
- Track last-sweep summary (counts + timestamp) on the agent or ticker.
- Surface it: a `/board` (or introspection `agent_info quartermaster`) status line — "last sweep: scanned N,
  redispatched N, cleared N, quarantined N, Xs ago". Verify-first the slash-command/panels seam
  (`experience/shell.py`, `experience/panels.py`) and the introspection delegation path (AD-320).
**Tests (≥5):** last-summary recorded; status line renders the recorded counts; empty/never-run state.
**Do not:** add a new HTTP endpoint unless the chosen surface requires it; prefer the existing introspection
path.

### AD-884 — Authority-scoping governance record (Minimal Authority axiom)
**Problem:** the Quartermaster can mutate any board item (unassign + re-dispatch) with no consensus gate.
That's defensible (housekeeping, reversible) but is currently *implicit*.
**Build (governance + guard test, minimal code):**
- Record the explicit decision in `DECISIONS.md` (AD-884): the Quartermaster's authority is scoped to
  reconcile-only operations (unassign / re-dispatch / quarantine), all reversible housekeeping, so no
  consensus gate is required; it must not perform destructive intents.
- Add a guard **test** asserting the agent's declared `intent_descriptors` / capabilities are reconcile-only
  and that it sets no `requires_consensus` destructive intent. If a tiny code assertion helps (e.g. an
  explicit allow-list constant), add it.
**Tests (≥3):** capability surface is reconcile-only; no destructive/consensus intent declared.
**Do not:** add a consensus gate; the decision is that none is needed — record the reasoning.

---

## Cross-cutting constraints (apply to every AD)
- **One AD = one commit.** Corruption pre-check (`git diff --numstat | sort -k2nr | head`) before each.
- **BF-287:** real `WorkItemStore` (`tmp_path`, `await store.start()`), real `AgentRegistry`/`AgentIdentityRegistry`;
  `_Fake*` only for the router/dispatch/LLM boundary. No MagicMock at the substrate/storage boundary.
- **Config:** all new fields on `WorkBoardReconcilerConfig`, Pydantic `Field(ge=, le=)` bounds, transitional
  flags default **False/0/off** (conv #14). Validation at parse time.
- **Events:** real `EventType` members, no raw-string fallback; `runtime.emit_event` is **sync** (don't await).
- **Async:** ticker/subscription tasks hold their reference, `asyncio.create_task` (never `ensure_future`),
  `get_running_loop()`, `CancelledError` re-raised, idempotent `stop()`.
- **Honest-degrade:** missing collaborator / config = INFO no-op, not an error. Per-item exception continues the sweep.
- **Per AD:** update PROGRESS.md top banner (next `Wave NNN`) + DECISIONS.md (newest-first, under
  `## Era V — Civilization`). No standalone markdown docs. Verify all changes comply with the Engineering
  Principles in `.github/copilot-instructions.md`.
- Focused **serial** gate green per AD: `d:/ProbOS/.venv/Scripts/pytest.exe <files> -q -n 0 -p no:cacheprovider`
  (xdist has known `KeyError:'ServicePackMajorVersion'` worker-crash noise on this box — re-run serially to confirm).

## Out of scope for this epic
- Reworking the AD-874 dispatch route beyond the minimal idempotency guard (AD-878).
- Real federation routing (AD-882 is a defensive skip only).
- New heartbeat plumbing (AD-881 uses existing timestamps).
- Raising `scan_limit` or changing sweep cadence defaults.

## Build-order recommendation (Architect to confirm/adjust)
877 (thrash guard — unblocks 881) → 879 (ordering) → 878 (grace period) → 884 (governance) →
883 (observability) → 880 (reactive) → 881 (stall) → 882 (federation guard).
Architect may flag 880/881/882 as "minimal first cut" or defer with justification.
