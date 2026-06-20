# AD-1019b — MCP authorization: department lockers + 3-tier resolver + tool risk classification

**Track:** GitHub #962 (epic #955). **Highest AD = AD-1019a (confirmed via DECISIONS.md grep 2026-06-16) → this is AD-1019b.** **Backend authorization + classification ONLY — no invocation (AD-1019c), no HXI (AD-1019d).** All references ✅ verified against the live codebase — see §7.

> Architect: verify every reference against the live codebase before approving. Re-grep the AD ceiling. This is the first slice of the "toolbox" design — the converged design is on epic #955.

## 1. Context (verified 2026-06-16)
AD-1019 made MCP per-agent/per-tool grants real via `ToolPermissionStore` + a 2-source `resolve_mcp_access`. This AD adds the **department tier** (the "logical hammer in many lockers") and the **risk classification** (OPEN/CONFIRM/CONSENSUS — the "keys" model). Pure/store layer only; AD-1019c does invocation + enforcement.

Read first:
- `ToolPermissionStore` — [permissions.py](src/probos/tools/permissions.py): `_SCHEMA` `tool_access_grants(id, agent_id, tool_id, permission, is_restriction, reason, issued_by, issued_at, expires_at, revoked, revoked_at)`; `issue_grant(agent_id, tool_id, permission, *, is_restriction, reason, …)`; `revoke_grant(grant_id)`; `get_active_grants_sync(agent_id, tool_id?)`. **This is the exact shape to mirror.**
- `resolve_mcp_access(grants, server_name, tool_name) -> (enabled, source)` — [access.py](src/probos/integrations/mcp_bridge/access.py): pure; folds a flat grant list; precedence tool>server, restriction>grant, default opt-in-off; `source ∈ {tool,server,default}`. `mcp_server_tool_id` / `mcp_tool_tool_id` composite ids.
- `McpServerStore` / `McpServerRecord` — [store.py](src/probos/integrations/mcp_bridge/store.py): AD-1015 store; AD-1017 added 4 columns via a migration-safe `_migrate_ad1017` (`ALTER TABLE ADD COLUMN`, `OperationalError` swallowed) — **mirror that migration pattern** for the new risk column.
- `ToolAccessGrant` — [protocol.py](src/probos/tools/protocol.py): the grant dataclass `resolve_mcp_access` consumes.

## 2. Build

### 2a. `DepartmentToolGrantStore` (new) — `src/probos/integrations/mcp_bridge/department_grants.py`
Mirror `ToolPermissionStore` **exactly** (ConnectionFactory, `PRAGMA journal_mode=WAL`/`busy_timeout=5000`/`synchronous=NORMAL`, in-memory `_cache`, `db_path=""` cache-only, soft-revoke). The grant key is **`department`** in place of `agent_id`.

**DECISION — reuse `ToolAccessGrant` (PINNED).** Do NOT define a new `DepartmentToolGrant`. `resolve_mcp_access` only ever reads `.tool_id` and `.is_restriction` (verified — it NEVER reads `.agent_id`), so a department grant is a `ToolAccessGrant` whose `agent_id` field carries the department string. This lets the 3-source resolver fold `list[ToolAccessGrant]` for BOTH tiers with zero type churn (strongest back-compat with AD-1019a's exact param type). Document the `agent_id = department` convention in the store + module docstring so the field-name smell is contained. (A `Protocol`/new-type split is over-engineering for a backend slice; revisit only if AD-1019d's serializer needs it.)

Schema `department_tool_grants(id TEXT PRIMARY KEY, department TEXT NOT NULL, tool_id TEXT NOT NULL, permission TEXT NOT NULL, is_restriction INTEGER NOT NULL DEFAULT 0, reason TEXT NOT NULL DEFAULT '', issued_by TEXT NOT NULL DEFAULT 'captain', issued_at REAL NOT NULL, expires_at REAL, revoked INTEGER NOT NULL DEFAULT 0, revoked_at REAL)` + indexes on `department`, `tool_id`, `(revoked, expires_at)`. `_row_to_grant` maps `ToolAccessGrant(id=row[0], agent_id=row[1]  # =department, tool_id=row[2], permission=ToolPermission(row[3]), …)`.

API (mirror `ToolPermissionStore` signatures — **`permission` is required**, since `ToolAccessGrant.permission` has no default; AD-1019d will pass `WRITE`/`NONE` exactly as `set_agent_access` does):
- `async issue_grant(department, tool_id, permission: ToolPermission, *, is_restriction=False, reason="", issued_by="captain", expires_at=None) -> ToolAccessGrant`
- `async revoke_grant(grant_id) -> bool` (soft-revoke)
- `get_active_grants_sync(department, tool_id=None) -> list[ToolAccessGrant]` (filters `g.agent_id != department`; lazy-expiry like the source)
- `async list_grants(*, active_only=True) -> list[ToolAccessGrant]`

Many-to-many is inherent (no uniqueness on department×tool — the same `tool_id` may be granted to many departments, and one department may hold many tools). Wire `runtime.department_tool_grant_store` in `startup/finalize.py` next to the `mcp_server_store` block (gate `config.mcp.management_enabled`; `db_path=str(runtime.data_dir / "department_tool_grants.db")`; `= None` in the `else`), and stop+None it in `startup/shutdown.py` mirroring the `mcp_server_store` teardown (~L691).

### 2b. Extend `resolve_mcp_access` to 3-source (`src/probos/integrations/mcp_bridge/access.py`)
**Do NOT rename or reorder the existing positional params** (AD-1019a's `resolve_mcp_access(grants, server_name, tool_name)` is consumed by `mcp_servers.py`). ADD one keyword-only param with an immutable default:
```python
from collections.abc import Sequence
def resolve_mcp_access(
    grants: list[ToolAccessGrant],
    server_name: str,
    tool_name: str,
    *,
    department_grants: Sequence[ToolAccessGrant] = (),
) -> tuple[bool, str]:
```
Fold the agent `grants` first, then `department_grants`, into the SAME four buckets but tracked per origin (agent vs dept).

**PINNED precedence ladder** — a total, deterministic lexicographic order over `(scope-specificity, origin-specificity, restriction-first)`. First match wins:

| # | Winning grant | Result |
|---|---|---|
| 1 | agent tool-scope **restriction** | `(False, "tool")` |
| 2 | agent tool-scope **grant** | `(True,  "tool")` |
| 3 | dept  tool-scope **restriction** | `(False, "department")` |
| 4 | dept  tool-scope **grant** | `(True,  "department")` |
| 5 | agent server-scope **restriction** | `(False, "server")` |
| 6 | agent server-scope **grant** | `(True,  "server")` |
| 7 | dept  server-scope **restriction** | `(False, "department")` |
| 8 | dept  server-scope **grant** | `(True,  "department")` |
| 9 | (nothing) | `(False, "default")` |

Rationale: tool-scope (finer) outranks server-scope (broader); within a scope, agent (specific) outranks department (broad); within scope+origin, restriction beats grant. Consequence: a department's tool-scope restriction CAN override an agent's broad server-scope grant — the correct most-specific-match-wins ACL semantic.

**PINNED `source`-label rule:** `source == "tool"`/`"server"` iff an **agent** grant decided (at tool/server scope); `source == "department"` iff a **department** grant decided (at EITHER scope); `source == "default"` iff nothing decided. Back-compat guarantee: with `department_grants=()` rows 3/4/7/8 are unreachable, so the resolver can only return `{tool, server, default}` — **byte-identical to AD-1019a**. `"department"` is a NEW value; the existing three are never renamed. (A single token is sufficient for AD-1019d; do NOT introduce compound `department:tool` strings here.)

**Caller** (`mcp_servers.py` `get_agent_access`) — the ONLY production call site. Resolve the agent's department via the **canonical public ontology accessor** (verified): `runtime.ontology.get_agent_department(agent.agent_type)` where `agent = runtime.registry.get(agent_id)`. An agent has exactly ONE department (`str | None`); honest-degrade to `""` when registry/ontology/agent is absent (→ no dept grants → identical to AD-1019a). Do NOT use the private pool-group `runtime._get_agent_department` — that is a notification-display concept, not the crew/governance department the lockers key on. Add a small router helper:
```python
def _agent_department(runtime: Any, agent_id: str) -> str:
    reg = getattr(runtime, "registry", None)
    ont = getattr(runtime, "ontology", None)
    agent = reg.get(agent_id) if reg is not None else None
    if agent is None or ont is None:
        return ""
    return ont.get_agent_department(agent.agent_type) or ""
```
Then fetch `dept_grants = dept_store.get_active_grants_sync(dept)` (when `runtime.department_tool_grant_store` is present and `dept` is non-empty, else `[]`) and pass `department_grants=dept_grants` into BOTH `resolve_mcp_access` calls (server-scope `""` and per-tool). Forward-wiring note: until AD-1019d adds the issue-dept-grant API, no dept grants exist in prod, so this fold is dormant (correct); tests exercise it by issuing grants through the store directly.

### 2c. Tool risk classification — `src/probos/integrations/mcp_bridge/risk.py` (new)
- `McpToolRisk(str, Enum)` = `OPEN="open"` | `CONFIRM="confirm"` | `CONSENSUS="consensus"` (default `OPEN`). Put it + `resolve_tool_risk` + `McpToolRiskStore` in a NEW `risk.py` (parallels `access.py`; keeps risk a distinct concern from access).
- Pure `resolve_tool_risk(server_default: McpToolRisk, tool_override: McpToolRisk | None) -> McpToolRisk`: `return tool_override if tool_override is not None else server_default`. (Explicit `is not None`, NOT `or` — avoids any falsy-enum trap.) No I/O.

**Server-level default — column on `mcp_servers` (PINNED; ALTER is migration-safe).** `McpServerStore._row_to_record` is **positional** (`row[0]..row[18]`) and AD-1017's `ADD COLUMN` appends to the END, so the new column is safe **iff it is appended at the END everywhere**. Full edit set (all must land together or positional order breaks):
  1. `_SCHEMA`: append `default_risk TEXT NOT NULL DEFAULT 'open'` as the LAST column (after `oauth_json`).
  2. Add `_AD1019B_MIGRATIONS = ("ALTER TABLE mcp_servers ADD COLUMN default_risk TEXT NOT NULL DEFAULT 'open'",)` and a `_migrate_ad1019b()` (same `sqlite3.OperationalError`-swallow pattern as `_migrate_ad1017`), called in `start()` immediately AFTER `await self._migrate_ad1017()`.
  3. `McpServerRecord`: add `default_risk: str = "open"` (defaulted field — after the non-defaulted `name`/`type`).
  4. `_row_to_record`: add `default_risk=row[19]`.
  5. `_record_to_params`: append `rec.default_risk` (→ 20 values).
  6. INSERT: add `default_risk` to the column list + one more `?` (20 cols / 20 placeholders).
  7. UPDATE: add `default_risk = ?` + the param (before the trailing `updated_at = ?`/`WHERE id = ?`).
  8. `to_public_dict`: add `"default_risk": self.default_risk` (NON-secret config). Safe — `test_to_public_dict_shape` (AD-1015) asserts individual keys, NOT the exact key set (verified), so the added key does not break it.

**Per-tool override — dedicated `McpToolRiskStore` (PINNED; lightest correct).** A small store in `risk.py` mirroring the lifecycle pattern (ConnectionFactory, WAL PRAGMAs, `_cache`, `db_path=""` cache-only). Override is config (set/clear/upsert), NOT audit — so NO soft-revoke. Table `mcp_tool_risk(id TEXT PRIMARY KEY, server_id TEXT NOT NULL, tool_name TEXT NOT NULL, risk TEXT NOT NULL, updated_at REAL NOT NULL)` + `UNIQUE(server_id, tool_name)` + index on `server_id`. API: `async set_risk(server_id, tool_name, risk: McpToolRisk) -> None` (upsert — replace any existing row for that `(server_id, tool_name)`), `get_risk_sync(server_id, tool_name) -> McpToolRisk | None` (cache read, `None` when unset), `async clear_risk(server_id, tool_name) -> bool` (hard delete), `list_sync() -> list[...]` (for AD-1019d). Wire `runtime.mcp_tool_risk_store` alongside the dept store (same `management_enabled` gate; `db_path=str(runtime.data_dir / "mcp_tool_risk.db")`; teardown in shutdown.py).

*(Rejected: overloading grants; a JSON column; collapsing the server default into the risk table with a `tool_name=""` sentinel — the last would drop the `to_public_dict` surfacing AD-1019d needs.)*

This AD only **stores + resolves** risk. No invoke-path/quorum wiring (AD-1019c). No SET-risk / issue-dept-grant API endpoints (AD-1019d authoring).

## 3. Tests — `tests/test_ad1019b_*.py` (BF-287: real stores, `db_path=""` — no MagicMock at the store boundary)
- **`DepartmentToolGrantStore`**: issue/revoke/`get_active_grants_sync(department, tool_id?)`; many-to-many (same `tool_id` in 2 departments; one department holding many tools); soft-revoke removes from active; lazy-expiry; `db_path=""` cache-only path. Assert the returned record is a `ToolAccessGrant` with `.agent_id == department`.
- **3-source `resolve_mcp_access` matrix** (issue grants through the real stores): ship-default-only → `(False,"default")`; dept grant + agent in that dept → `(True,"department")`, agent NOT in dept → `(False,"default")`; agent grant → `"tool"`/`"server"`; **agent restriction beats dept grant at the same scope**; **dept tool-scope restriction beats agent server-scope grant** (most-specific-wins); every row of the §2b ladder; `source`-label correctness across all of `{tool,server,department,default}`. Single-department note: an agent has exactly ONE department, so the "multi-department" case is a union over a 1-element set — assert one agent's dept grants apply and a different department's do not.
- **Back-compat (HARD)**: `resolve_mcp_access(grants, server, tool)` 3-arg and `department_grants=()` are byte-identical to AD-1019a. Re-run the existing AD-1019/1019a access tests UNCHANGED (they must stay green under the new signature).
- **`resolve_tool_risk`**: default `OPEN`; server default returned when no override; per-tool override wins; `None` override → server default.
- **`McpToolRiskStore`**: set/`get_risk_sync`/`clear_risk`; upsert replaces; `None` when unset.
- **Migration (positional-order guarantee)**: create a record over a real DB, reload via `start()`, and assert `_row_to_record` still reads every prior field correctly AND `default_risk == "open"` (proves the END-appended column did not shift `row[0..18]`). Also assert a fresh DB migrates cleanly (the duplicate-column `OperationalError` is a swallowed no-op).
- **Gate**: `management_enabled=False` ⇒ both new stores are `None`, `get_agent_access` byte-identical; `pytest -k "mcp or ad1015 or ad1017 or ad1019"` all green.

## 4. Do NOT
❌ Invocation / adapters / `find_mcp_tool` / workbench / TTL (AD-1019c). ❌ Consensus/confirm ENFORCEMENT — this AD only CLASSIFIES (stores+resolves the tier); AD-1019c wires it to the quorum/invoke path. ❌ Touch the invoke path or `quorum`. ❌ HXI (AD-1019d). ❌ NEW API endpoints (issue-dept-grant, set-risk) — those are AD-1019d authoring; this AD only updates the existing `get_agent_access` read path. ❌ Rename/reorder existing `source` values or the `resolve_mcp_access` positional params. ❌ Insert `default_risk` anywhere but the END of `mcp_servers` (would shift the positional `_row_to_record`). ❌ Change AD-1019a behavior when `department_grants` is empty.

## 5. Acceptance
All §3 green; back-compat PROVEN (AD-1019/1019a access tests run UNCHANGED + `-k "mcp or ad1015 or ad1017 or ad1019"` green); 3-source `resolve_mcp_access` + `resolve_tool_risk` pure + exhaustively unit-tested; `DepartmentToolGrantStore`/`McpToolRiskStore` mirror the audited `ToolPermissionStore`/`McpServerStore` lifecycle; `default_risk` migration preserves positional column order; default-OFF (`management_enabled=False`) byte-identical; full type annotations on all new public methods; Pydantic v2 / async hygiene (no fire-and-forget tasks; `()` not `[]` defaults); **verify compliance with `.github/copilot-instructions.md`.**

## 6. Files the Builder will touch
**Create:**
- `src/probos/integrations/mcp_bridge/department_grants.py` — `DepartmentToolGrantStore` (reuses `ToolAccessGrant`).
- `src/probos/integrations/mcp_bridge/risk.py` — `McpToolRisk` enum, pure `resolve_tool_risk`, `McpToolRiskStore`.
- `tests/test_ad1019b_department_grants.py`, `tests/test_ad1019b_resolver_3source.py`, `tests/test_ad1019b_tool_risk.py`.

**Modify:**
- `src/probos/integrations/mcp_bridge/access.py` — add keyword-only `department_grants` + 3-source fold (§2b ladder). No positional-param change.
- `src/probos/integrations/mcp_bridge/store.py` — append `default_risk` column (8-site edit set, §2c); add `_AD1019B_MIGRATIONS` + `_migrate_ad1019b()`.
- `src/probos/routers/mcp_servers.py` — `get_agent_access`: `_agent_department` helper + fold `department_grants` into both `resolve_mcp_access` calls.
- `src/probos/startup/finalize.py` — wire `runtime.department_tool_grant_store` + `runtime.mcp_tool_risk_store` (gate `config.mcp.management_enabled`; `else: None`), next to the `mcp_server_store` block (~L3338).
- `src/probos/startup/shutdown.py` — stop + `None` both new stores, mirroring the `mcp_server_store` teardown (~L691).

## 7. Verified against codebase (2026-06-16)
| Claim | Evidence |
|---|---|
| Highest AD = AD-1019a; AD-1019b free | `git grep "### AD-1…" DECISIONS.md` → tail = `AD-1019, AD-1019a` |
| `ToolPermissionStore` shape (schema, `issue_grant`/`revoke_grant`/`get_active_grants_sync`) | permissions.py L19-37 `_SCHEMA`, L110 `issue_grant`, L161 `revoke_grant`, L177 `get_active_grants_sync` |
| `resolve_mcp_access` is 2-source, reads only `.tool_id`/`.is_restriction`, `source ∈ {tool,server,default}` | access.py L34-89 (NO `.agent_id` read → reuse of `ToolAccessGrant` is type-safe) |
| `mcp_server_tool_id`/`mcp_tool_tool_id` composite ids | access.py L24-31 |
| `ToolAccessGrant` fields (`agent_id`, `tool_id`, required `permission`, `is_restriction`, …) | protocol.py L211-230 |
| `McpServerStore` positional `_row_to_record` (`row[0..18]`); `_AD1017_MIGRATIONS` append-at-end; `_migrate_ad1017` `OperationalError`-swallow | store.py L65-72, L297 `_migrate_ad1017`, L324-345 `_row_to_record` |
| `to_public_dict` is the serialization seam; AD-1015 shape test asserts individual keys (adding `default_risk` is safe) | store.py L160-184; tests/test_ad1015_mcp_server_store.py L160-167 |
| Department accessor = `runtime.ontology.get_agent_department(agent_type) -> str \| None` (public, crew dept), via `runtime.registry.get(agent_id).agent_type` | ontology/service.py L159; usages in agent_onboarding / ward_room_router / capability_triage / department_dispatcher |
| `get_agent_access` is the only `resolve_mcp_access` prod caller; issues grants with `WRITE`/`NONE` | mcp_servers.py L829-855 (calls), L858-892 (`set_agent_access`) |
| `mcp_server_store` startup wiring (gate `management_enabled`, `runtime.data_dir`, `else None`) + teardown | finalize.py L3338-3370; shutdown.py L691-693 |
| `config.mcp.management_enabled: bool = False` | config.py L3593 |
