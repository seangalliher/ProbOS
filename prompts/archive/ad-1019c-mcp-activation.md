# AD-1019c — MCP activation: lazy adapters, find_mcp_tool, warm workbench + TTL, tier enforcement (backend)

**Epic #955 · issue #963 · depends on AD-1019b (shipped: authorization + tier classification).**
**Repo: OSS (`d:\ProbOS`). AD ceiling at drafting: AD-1020 (AD-1019c/d/e are named sub-ADs; no new top-level number).**

Makes MCP tools actually agent-callable. **Backend only — no HXI (AD-1019d).**

---

## Architect design pass — pinned decisions (read first)

These five were settled against the live code. Verify line numbers at build; do not re-litigate the consensus model — it is aligned with the AD-1019b tier approach.

### DD-1 — CONSENSUS tier reuses the existing quorum via the proven propose→vote→commit template (era-4-safe)

The tier→gate mapping the Captain aligned on:

| Tier | Keys | Backend behavior |
|------|------|------------------|
| `OPEN` | 0 | direct `MCPBridge.invoke(server_url, tool, args)` |
| `CONFIRM` | 1 | **block unless** the call carries an explicit operator confirmation token; absent → return a `requires_confirmation` outcome, **no invoke**. (The HXI affordance that supplies the token is AD-1019d.) |
| `CONSENSUS` | 2 | route through the **existing** quorum, then invoke **only on approval** |

**The CONSENSUS mechanism already exists** — mirror `runtime.submit_write_with_consensus` ([runtime.py](src/probos/runtime.py#L3129)) **exactly**. That method is the canonical, era-safe shape:

1. `result = await self.submit_intent_with_consensus(intent=..., params=...)` ([runtime.py](src/probos/runtime.py#L2939)) — broadcast + `QuorumEngine.evaluate` + red-team verification + trust/Hebbian update of the **voters**.
2. `if result["consensus"].outcome == ConsensusOutcome.APPROVED` **and** no failed verifications →
3. **only then** perform the side effect (`FileWriterAgent.commit_write` there; `MCPBridge.invoke` here).

> ⚠️ **The era-4 trap (AD-362, decisions-era-4):** broadcasting a `requires_consensus` intent and reading `IntentResult(success=True)` does **NOT** mean the action ran — that was only a *proposal*, and the file writes silently never committed. **Never call `MCPBridge.invoke` on the broadcast/vote.** Invoke is the *commit*, gated on `APPROVED`.

Add a thin `runtime.submit_mcp_invoke_with_consensus(server_url, tool, arguments, *, timeout=None, policy=None) -> dict` that mirrors `submit_write_with_consensus` and performs the `MCPBridge.invoke` commit on approval.

**One sub-question to resolve at build (flagged, not guessed):** `submit_intent_with_consensus` collects votes from agents that respond to the broadcast intent. There is **no MCP serving pool**, so a bare `mcp_invoke` broadcast may yield **zero voters → INSUFFICIENT → always blocked**. Resolve by ONE of (Builder picks, verify voter population first):
  - **(A, recommended)** a minimal `McpConsensusProposer` utility agent (one pool, `tier="utility"`) that responds to `mcp_invoke` with a **proposal only** (`requires_consensus=True`, validates auth+tier, **never executes**) — exact `FileWriterAgent` parity; the runtime commits via `MCPBridge.invoke`. Mirror [agents/file_writer.py](src/probos/agents/file_writer.py).
  - **(B)** reuse an existing governance voting population if one already answers generic gated intents (verify it exists before choosing this).

OPEN/CONFIRM never touch the bus — the adapter owns the commit (matches issue item #1).

### DD-2 — `find_mcp_tool` reuses the AD-979c RRF *primitives* (not `find_intents`)

⚠️ **Verify-first correction:** `CapabilityRetriever.find_intents` ([capability_retriever.py](src/probos/cognitive/capability_retriever.py#L119)) is **`IntentDescriptor`-bound** — it indexes a catalog of `IntentDescriptor`s and returns `list[IntentDescriptor]`. MCP tools are NOT `IntentDescriptor`s, so do **not** call `find_intents` (and do not force MCP tools into `IntentDescriptor` shape).

Instead reuse the **pure RRF primitives** that `CapabilityRetriever` itself is built on: `fts_or_query` + `reciprocal_rank_fusion` (both importable from `probos.cognitive.episodic`) + the `_tokenize` pattern. Run them over the agent's **AD-1019b-authorized** MCP tool `{name, description}` dicts (scope the candidate set by `resolve_mcp_access` first), fuse a name-token axis + a full-text axis, return the ranked top-k. Deterministic, per-call, per-agent-scoped — mirrors `find_intents`'s internals without its `IntentDescriptor` dependency.

### DD-3 — Workbench lifecycle mirrors `register_mesh_intent_tools` + `AttachmentReaper`

- A tool pulled onto the workbench registers a thin adapter in the `ToolRegistry`, mirroring `register_mesh_intent_tools` ([agentic_dispatch.py](src/probos/cognitive/agentic_dispatch.py#L179)) and the `_MeshIntentTool` adapter (L75). Per-agent scoped via AD-1019b `resolve_mcp_access`.
- `MCPBridge` already keeps clients warm (`self._clients` cache) — instant re-use within session.
- A 24h idle-TTL reaper mirrors `AttachmentReaper` ([attachments/reaper.py](src/probos/attachments/reaper.py#L38)) (`start()`/`stop()`/`sweep_once()`, no-op when disabled, started in `finalize.py`, stopped in `shutdown.py`) — unloads idle adapters back to the toolbox.

### DD-4 — str→enum guard on `default_risk` (carryover from the AD-1019b review)

Tier resolution reads `record.default_risk` (a free-form `str`; AD-1019b validates it only at the create/update boundary). At the invoke path, convert defensively: `McpToolRisk(record.default_risk)` wrapped so an unknown/legacy value **logs a warning and fails closed to `CONSENSUS`** (the most-gated tier — a risk classifier that cannot determine the risk assumes the maximum, per the Safety Budget axiom) — **never crash the invoke path**. Per-tool override (AD-1019b `McpToolRiskStore.get_risk_sync`) wins via the existing `resolve_tool_risk`.

### DD-5 — Episode on every invoke; NO trust/Hebbian scoring of the MCP tool

Every MCP invoke (all three tiers) stores an episode (episodic completeness). **No** trust/Hebbian write *for the MCP tool/server itself* (recorded-not-scored, per the design). The voter trust/Hebbian updates inside `submit_intent_with_consensus` are governance scoring of the **voters** — that is correct and stays.

### DD-6 — Activation is independently default-OFF

New `MCPConfig.agent_tools_enabled: bool = False` (convention #14 transitional flag, distinct from `management_enabled`). Off → no adapters registered, `find_mcp_tool` absent, reaper never starts → **byte-identical** to AD-1019b.

---

## Build

1. **Lazy MCP-tool adapters** — `_McpTool` adapter (mirror `_MeshIntentTool`) whose `invoke` reads the effective `McpToolRisk` (DD-4) then routes per DD-1. Register per-agent at dispatch for the agent's authorized MCP tools, scoped via AD-1019b `resolve_mcp_access` (mirror the AD-1007 per-agent restriction-filter pattern at [agentic_dispatch.py](src/probos/cognitive/agentic_dispatch.py#L292), but the MCP authorization source is `resolve_mcp_access`, not the mesh-intent `ToolPermissionStore` lens).
2. **`find_mcp_tool`** — the active-search tool (DD-2): `find_mcp_tool("create a github issue")` → ranked authorized matches → pulling one registers it warm on the workbench.
3. **Workbench + 24h idle-TTL reaper** (DD-3).
4. **Tier enforcement at invoke** (DD-1 + DD-4): OPEN direct; CONFIRM blocks without a confirmation token; CONSENSUS via `submit_mcp_invoke_with_consensus`.
5. **Episode on invoke** (DD-5).

## Acceptance
- Real `MCPBridge` + AD-1014 echo fixture: an authorized MCP tool is callable end-to-end; an unauthorized one is **absent** from the agent's toolset.
- `find_mcp_tool` returns ranked matches scoped to the agent's AD-1019b authorization; pulling one makes it invocable.
- **Tier gate:** OPEN invokes directly; CONFIRM returns `requires_confirmation` and does **not** invoke without a token; CONSENSUS routes through `submit_mcp_invoke_with_consensus` — assert the quorum path is hit AND that `MCPBridge.invoke` fires **only** on `APPROVED` (a rejected/INSUFFICIENT vote performs **no** invoke — the era-4 regression guard).
- Idle reaper unloads after TTL; warm re-use within session does not re-fetch (`_clients` hit).
- An episode is stored on invoke; **no** trust/Hebbian write attributable to the MCP tool/server.
- `agent_tools_enabled=False` ⇒ byte-identical (no adapters, no `find_mcp_tool`, reaper never starts).
- **Real-DB / real-substrate tests per BF-287** (no MagicMock at the bridge/registry/runtime boundary; the AD-1019b review lesson — cache-only/mock tests mask the real path). Reuse the AD-1014 echo fixture + a real `ToolRegistry`.
- Verify compliance with `.github/copilot-instructions.md` — esp. **async hygiene** (`create_task` references held; reaper cancellation re-raises) and the **IntentBus fan-out** note (the consensus vote broadcasts once; do not fan out N invokes).

## Do NOT build here
❌ HXI (AD-1019d) — including the CONFIRM operator affordance and tier/department **authoring** UI. ❌ Hebbian-biased MCP ranking (AD-1019e fast-follow). ❌ Trust/Hebbian scoring of MCP tools (DD-5). ❌ A new top-level AD number — this is AD-1019c. ❌ Change AD-1019b authorization behavior, the `resolve_mcp_access` precedence ladder, or `default_risk` boundary validation. ❌ Execute on the broadcast/vote (the era-4 trap).

## Files (verify each at build)
- `src/probos/cognitive/agentic_dispatch.py` — `_McpTool` adapter + per-agent registration (mirror `_MeshIntentTool` / `register_mesh_intent_tools`).
- `src/probos/cognitive/mcp_workbench.py` (NEW) — `find_mcp_tool` retrieval (DD-2) + workbench registration/lifecycle.
- `src/probos/integrations/mcp_bridge/reaper.py` (NEW) — idle-TTL adapter reaper (mirror `AttachmentReaper`).
- `src/probos/runtime.py` — `submit_mcp_invoke_with_consensus` (mirror `submit_write_with_consensus`).
- `src/probos/agents/mcp_consensus_proposer.py` (NEW, if DD-1 option A) — propose-only voter (mirror `file_writer.py`).
- `src/probos/config.py` — `MCPConfig.agent_tools_enabled=False`.
- `src/probos/startup/finalize.py` / `shutdown.py` — start/stop the reaper (gated).
- `tests/test_ad1019c_*.py` (NEW) — adapters, `find_mcp_tool` scope, the three tiers incl. the era-4 no-invoke-on-reject guard, reaper TTL, episode-on-invoke, default-OFF byte-identity.

## Done-when
All acceptance green; `-k "mcp or ad1014 or ad1015 or ad1017 or ad1019"` gate green (AD-1019b's 330 unchanged + new); default-OFF byte-identical; full type annotations on new public methods; async hygiene verified; **verify compliance with `.github/copilot-instructions.md`.**
