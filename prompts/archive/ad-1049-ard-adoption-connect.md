# AD-1049 — Adoption + connect (discovery-before-design)

**Epic:** ARD Integration (`docs/development/ard-integration.md`) · **Phase 3, Step 4**
**Issue:** #999 · **Epic:** #989 · **Target repo:** OSS (`d:\ProbOS`)
**Depends on:** AD-1046 (client), AD-1047 (trust), AD-1048 (permission) · **Blocks:** nothing (completes the client arc)
**Verification status:** ⚠ DRAFT — re-verify file refs against HEAD at build time. Connects through **existing** mechanisms — confirm `MCPBridge.register_server`/`register_stdio_server` (AD-449/1014), the A2A client ([federation/a2a/client.py](src/probos/federation/a2a/client.py)), the pack loader (AD-1013), and the **capability-gap** path in the self-mod pipeline at build time.

## Objective

Make a discovered → trust-cleared → **permitted** ARD resource actually usable by the crew agent: connect over its **native** mechanism and register it so the agent can invoke it next turn. Then wire **discovery-before-design**: try adopt-from-ARD *before* designing a new agent on a capability gap.

## Why

ARD is discovery, not execution (interoperability page). Connection uses the resource's own protocol. ProbOS already has every connector: MCP via `MCPBridge`, A2A via the federation client, skills via the pack loader. This AD is the *router* from an ARD `CatalogEntry.type` to the right existing connector — plus the strategic payoff: a capability gap first asks "can I discover this?" before "should I build this?"

## Build

1. **New `federation/ard/adopter.py`** — `async adopt(entry, *, agent_id) -> AdoptResult`:
   - **Permission gate first:** `resolve_ard_access(...)` (AD-1048) for `(agent_id, catalog, resource)` → if not enabled, refuse with `reason="not_permitted"` (no connection attempted).
   - **Trust gate:** `verify_entry(entry)` (AD-1047) → reject on domain mismatch; register the probationary prior.
   - **Connect by `entry.type`:**
     - `application/mcp-server-card+json` → `MCPBridge.register_server` (http) / `register_stdio_server` (stdio, allowlist+consent gated, AD-1014). The discovered tools become invocable to the permitted agent via the existing `_McpTool`/workbench path (AD-1019b/c).
     - `application/a2a-agent-card+json` → register an outbound A2A peer (federation client) so the agent can delegate via A2A.
     - `application/ai-skill` → load via the pack/skill loader (AD-1013) if the artifact is a fetchable skill bundle; else surface as a remote skill reference.
     - `application/ai-catalog+json` (bundle) → recurse: adopt the nested entries (each re-gated).
   - Idempotent; honest-degrade per type; never partially-adopt without reporting.
2. **Discovery-before-design wiring:** at the capability-gap decision point in the self-mod pipeline (confirm the exact hook — `cognitive/self_mod.py` / the gap handler), add a **prior step**: query `ArdClient.search(gap_description)`; if a permitted+trusted match exists, `adopt` it and retry the intent **before** invoking `AgentDesigner`. Gated on `federation.ard.enabled` (OFF ⇒ the gap path is byte-identical — design-from-scratch as today).
3. **Observability:** emit an episode for each adoption (preserve the learning loop — Principle #8).

## Acceptance criteria

- A permitted + trusted MCP entry → `adopt` registers the server; the permitted agent can invoke its tools next turn.
- A **non-permitted** entry → refused, **no connection attempted** (the "if permitted" guarantee).
- A domain-mismatch entry → rejected before connect.
- Bundle entry → nested entries adopted, each independently gated.
- Capability gap with a permitted ARD match → adopt+retry succeeds **without** designing a new agent; with no match → falls through to `AgentDesigner` (unchanged).
- With `federation.ard.enabled=False` → the gap path is byte-identical to pre-epic (design-from-scratch); `adopt` is never reached.
- Tests `tests/test_ad1049_ard_adoption.py` (BF-287: real adopter + real `ToolPermissionStore` + fake bridge/client/loader at the edges): permitted vs not, trust reject, each type routes to the right connector, bundle recursion, gap discover-before-design on/off, episode emitted.
- Verify compliance with `.github/copilot-instructions.md`.

## Do NOT build

- No new execution protocols — route to **existing** MCP/A2A/skill connectors only.
- No bypass of consensus for adopted destructive capabilities (they still flow through quorum — Safety Budget).
- No change to the design-from-scratch path when ARD is OFF or no match (byte-identical fallback).
- No central-registry logic (AD-1051 / commercial).
