# Build AD-882 — Federation node-scope guard (no-op single-node)

**Repo:** OSS (`d:\ProbOS`). **Issue: #847.** **Epic:** AD-877→884 Quartermaster hardening.
**Highest committed AD: AD-876** (Wave 232). This is **AD-882**. One AD = one commit.
**Depends on:** AD-877 (acts before `clear_and_reroute`). **Ship as a default-safe no-op guard with a forward seam.**

---

## Problem

Liveness is checked against the **local** `AgentRegistry`. In a multi-node mesh, an item assigned to an agent
on **another node** looks "not live" locally and would be wrongly reclaimed by this node's sweep.

## Verify-first finding (drives the scope)

- **There is no per-agent or per-work-item node marker today.** Node ownership exists only at config /
  federation-peer granularity: `FederationConfig` (config.py:~2680) has `enabled: bool = False` and
  `node_id: str = "node-1"`. `WorkItem.assigned_to` is a bare agent id with **no** node qualifier, and the
  registry has no node field on agents.
- → AD-882 cannot *determine* remote ownership from existing data. It must be a **default-safe no-op** that
  installs the forward seam: an optional `metadata['owner_node']` convention that future federation code can
  populate. Absent marker → treat as local (current single-node reality).

## Build (guard only)

### Sweep — before acting on a `clear_and_reroute` decision (`QuartermasterAgent.reconcile()` / `_process_item`)

Inject the local node id and federation-enabled flag onto the agent (see wiring), then:

- If `self._federation_enabled` is True **and** `wi["metadata"].get("owner_node")` is set **and**
  `wi["metadata"]["owner_node"] != self._local_node_id`: skip with `reason="remote_owner"`,
  `counts["remote_owner_skipped"] += 1`, continue (do **not** unassign / re-dispatch).
- In **all** other cases (federation disabled, marker absent, or marker == local node): proceed as today.
  → On a single-node deployment (`federation.enabled=False`, default) this branch is never taken: pure no-op.
- Initialize `counts["remote_owner_skipped"] = 0` at the top of the sweep.

Precedence: place this skip alongside the AD-877 quarantine/backoff checks, **before** the attempt counter is
incremented (a remote-owned item must not accrue local reconcile attempts).

### Wiring — `_wire_board_reconciler` (startup/finalize.py:1866) + constructor

- Inject `agent._local_node_id = config.federation.node_id` and
  `agent._federation_enabled = config.federation.enabled` (verify-first the exact `config.federation` access
  path in finalize — reuse how other code reads `config.federation`).
- Add constructor kwargs `local_node_id: str = "node-1"`, `federation_enabled: bool = False` storing the same
  private attrs, so tests construct directly without finalize.

## Tests (≥5) — `tests/test_ad882_federation_node_guard.py`

**BF-287:** real `WorkItemStore`.

1. `federation_enabled=False` (default): item with `metadata['owner_node']='node-2'` is still reclaimed
   (guard is a no-op when federation off).
2. `federation_enabled=True` + `owner_node='node-2'` + `local_node_id='node-1'` → skipped, reason
   `remote_owner`, `remote_owner_skipped` incremented, NOT unassigned.
3. `federation_enabled=True` + `owner_node='node-1'` (== local) → reclaimed normally.
4. `federation_enabled=True` + no `owner_node` marker → treated as local, reclaimed normally.
5. A `remote_owner` skip does NOT increment `reconcile_attempts` (interaction with AD-877).

## Do not

- Build federation routing, peer lookup, or cross-node dispatch. This is a defensive **skip** only.
- Add a node field to `WorkItem`/`AgentRegistry` (use the optional `metadata['owner_node']` convention).

## Tracking

- PROGRESS.md banner → next free Wave. DECISIONS.md AD-882 newest-first under `## Era V — Civilization`
  (record: default-safe no-op; forward seam via `metadata['owner_node']`; no per-agent node marker exists yet).

## Acceptance

- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad882_federation_node_guard.py -q -n 0 -p no:cacheprovider` green.
- Corruption pre-check. Verify compliance with `.github/copilot-instructions.md`.

## Verified against codebase (2026-06-05)

- config.py:~2680 `FederationConfig` — `enabled: bool = False`, `node_id: str = "node-1"`. No per-agent/per-work-item node marker.
- workforce.py:581 `WorkItem` — `assigned_to` bare id; `metadata: dict` free-form (mutable).
