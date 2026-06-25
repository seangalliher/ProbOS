# AD-1041 — Own-catalog projection (Ship's Locker → ARD entries)

**Epic:** ARD Integration (`docs/development/ard-integration.md`) · **Phase 1, Step 2**
**Issue:** #991 · **Epic:** #989 · **Target repo:** OSS (`d:\ProbOS`)
**Depends on:** AD-1040 (envelope types) · **Blocks:** AD-1042, AD-1044
**Verification status:** ✅ verified against HEAD (the inventory source exists today)

## Objective

A **pure projection function** that turns the existing Ship's Locker inventory into an ARD `AiCatalog` (`entries[]`). No HTTP yet (AD-1042 serves it). Deterministic, reuses `_tool_origin`, default-OFF behind `federation.ard.enabled` at the *caller* (this function is pure).

## Why

The Ship's Locker (`GET /api/tools/catalog`, [routers/tools.py](src/probos/routers/tools.py) `list_capability_catalog`) already inventories all four capability axes — tools, skills, mesh-intents, MCP servers. ARD adoption is *reshaping that inventory into the standard envelope*, not recomputing it.

## Build

1. **New `src/probos/federation/ard/catalog_projector.py`** with one public function:
   ```python
   def project_catalog(
       inventory: dict,        # the dict shape returned by list_capability_catalog
       *,
       publisher_domain: str,  # FQDN anchor for URNs (from config or ship identity)
       host: HostInfo,
   ) -> AiCatalog: ...
   ```
   - For each **tool** entry: `CatalogEntry(identifier=build_urn(publisher_domain, axis_namespace, tool_id), display_name=name, type=PROBOS_AXIS_TO_MEDIA_TYPE[origin], data={...} | url=..., capabilities=[tool_id], description=..., tags=[domain/department])`. Map `origin` (`built_in`/`mcp`/`extension`) → media type via the AD-1040 map.
   - **skills** → `type=MT_AI_SKILL`, namespace `skill`, `capabilities=intents`.
   - **mesh_intents** → represented by a single `application/a2a-agent-card+json` entry referencing the ship's own card (`url=<base>/.well-known/agent.json`) — the ship-as-agent. (Do **not** emit one entry per mesh intent; they are the ship's A2A skills, already in the AgentCard.)
   - **mcp_servers** → `type=MT_MCP_SERVER`, namespace `mcp`, `url=<server url>`.
   - Deterministic order: sort entries by `identifier`.
2. **Refactor `list_capability_catalog`** (if needed) so the inventory assembly is reusable by the projector without an HTTP round-trip — extract the body into a `build_capability_inventory(runtime) -> dict` helper in [routers/tools.py](src/probos/routers/tools.py) (or a small `cognitive/`/`federation/` helper). The existing endpoint calls the helper (byte-identical response). The projector calls the same helper. **DRY** — one inventory source.
3. **`representative_queries` left empty here** — AD-1043 populates them. The projector emits `[]`.

## Acceptance criteria

- `project_catalog(inventory, publisher_domain="ship.local", host=...)` returns an `AiCatalog` whose `to_dict()` is spec-shaped (camelCase, value-or-reference satisfied for every entry).
- Tool origins map correctly: a `built_in` tool → `application/probos-tool+json`; an `mcp` tool → `application/mcp-server-card+json`; an `extension` tool → its mapped type.
- Mesh-intents collapse to exactly one `application/a2a-agent-card+json` ship entry (not N).
- Entries sorted by `identifier`; projection is deterministic across calls.
- `build_capability_inventory` extraction leaves `GET /api/tools/catalog` byte-identical (assert the endpoint response unchanged).
- Tests `tests/test_ad1041_catalog_projection.py` (BF-287: real inventory dict, real `HostInfo`): each axis projects to the right type; value-or-reference holds; empty inventory → empty `entries`; determinism.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Do NOT build

- No HTTP route (AD-1042). No `representativeQueries` mining (AD-1043). No search/filter (AD-1044).
- Do **not** emit one entry per mesh intent — the ship's A2A card already enumerates them.
- Do **not** change the JSON shape of `GET /api/tools/catalog` (only extract a reusable helper).
- Do **not** add trust manifests yet (signing is AD-C-027; the field stays `None`).
