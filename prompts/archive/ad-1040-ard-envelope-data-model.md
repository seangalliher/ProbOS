# AD-1040 — ARD envelope data model + media-type taxonomy + config scaffold

**Epic:** ARD Integration (`docs/development/ard-integration.md`) · **Phase 1, Step 1**
**Issue:** #990 · **Epic:** #989 · **Target repo:** OSS (`d:\ProbOS`)
**Depends on:** nothing · **Blocks:** AD-1041..AD-1051
**Verification status:** ✅ verified against HEAD (buildable now)

## Objective

Create the pure **data model + media-type taxonomy + config scaffold** for ARD. This AD ships *types and config only* — no projection, no HTTP, no client. Nothing in the runtime imports it yet. It is the foundation the rest of the epic builds on.

## Why

ARD is an *artifact-agnostic envelope* (spec §3.3). Before ProbOS can publish or consume catalogs, it needs the in-memory representation of an `ai-catalog.json` manifest and its `CatalogEntry` objects, plus a single source of truth for the IANA media types (the spec is **draft v0.9** — registrations pending — so the taxonomy must live in one constant).

## Build

1. **New package `src/probos/federation/ard/`** with `__init__.py` (export the public types) and `catalog.py`.

2. **`catalog.py` — pure dataclasses (frozen where natural), no I/O, no `probos` imports beyond `types` if needed:**
   - `HostInfo(display_name: str, identifier: str = "", documentation_url: str = "", logo_url: str = "")`.
   - `TrustManifest(identity: str, identity_type: str = "", attestations: list[Attestation] = [], provenance: list[ProvenanceLink] = [], signature: str = "")` + `Attestation(type: str, uri: str, digest: str = "")` + `ProvenanceLink(relation: str, source_id: str, source_digest: str = "")`. (Field names mirror spec §5; `default_factory=list` for the lists — never bare mutable defaults.)
   - `CatalogEntry(identifier: str, display_name: str, type: str, url: str | None = None, data: dict | None = None, description: str = "", tags: list[str] = [], capabilities: list[str] = [], representative_queries: list[str] = [], version: str = "", updated_at: str = "", metadata: dict = {}, trust_manifest: TrustManifest | None = None)`.
     - **Strict value-or-reference (spec §3.4):** exactly one of `url` / `data` must be set. Validate in `__post_init__` → raise `ValueError` if both or neither. A `to_dict()` that omits empty optionals and emits camelCase keys (`displayName`, `representativeQueries`, `trustManifest`, `updatedAt`) per the spec.
   - `AiCatalog(spec_version: str = "1.0", host: HostInfo | None = None, entries: list[CatalogEntry] = [])` + `to_dict()`.

3. **URN helpers in `catalog.py` (or a sibling `urn.py`):**
   - `build_urn(publisher: str, namespace: str, name: str) -> str` → `f"urn:air:{publisher}:{namespace}:{name}"`.
   - `parse_urn(urn: str) -> tuple[publisher, namespace, name] | None` (honest-degrade `None` on malformed).
   - `publisher_domain(urn: str) -> str` (extract the FQDN authority — used by AD-1047 trust verification).
   - Validate against the spec pattern `^urn:air:...`.

4. **Media-type constants (single source of truth)** in `media_types.py`:
   ```python
   MT_PROBOS_TOOL = "application/probos-tool+json"
   MT_MCP_SERVER = "application/mcp-server-card+json"
   MT_AI_SKILL = "application/ai-skill"
   MT_A2A_AGENT = "application/a2a-agent-card+json"
   MT_AI_CATALOG = "application/ai-catalog+json"
   MT_AI_REGISTRY = "application/ai-registry+json"
   ```
   Plus a `PROBOS_AXIS_TO_MEDIA_TYPE` map keyed on the `_tool_origin` taxonomy (`built_in`/`mcp`/`extension`) + the skill/mesh-intent/pack axes. Used by AD-1041.

5. **Config scaffold — `FederationArdConfig`** in [config.py](src/probos/config.py), mirroring `FederationA2AConfig` (L2826). Place the class next to it and nest it in `FederationConfig` (L2885) exactly like `a2a`:
   ```python
   class FederationArdConfig(BaseModel):
       """ARD (Agentic Resource Discovery) integration. Default-OFF."""
       enabled: bool = False
       well_known_path: str = "/.well-known/ai-catalog.json"
       # client: discovery endpoints registered with this ship (AD-1046)
       discovery_endpoints: list[str] = Field(default_factory=list)
       # publisher: external registry to register this ship's catalog with (AD-1051)
       registry_url: str = ""
       publisher_namespace_domain: str = ""  # FQDN anchor for URNs; "" = derive from ship identity
   ```
   Add to `FederationConfig`: `ard: FederationArdConfig = Field(default_factory=FederationArdConfig)`.

## Acceptance criteria

- `from probos.federation.ard import CatalogEntry, AiCatalog, HostInfo, TrustManifest, build_urn` works.
- `CatalogEntry` with both `url` and `data` → `ValueError`; with neither → `ValueError`; with exactly one → ok.
- `to_dict()` emits camelCase keys and omits empty optionals; round-trips a representative manifest matching the spec §4.1 example shape.
- `build_urn`/`parse_urn`/`publisher_domain` round-trip; malformed → `None`/`""`.
- `SystemConfig().federation.ard.enabled is False` (default-OFF); `config/system.yaml` **untouched**.
- New tests `tests/test_ad1040_ard_envelope.py` (BF-287: real dataclasses, no MagicMock): value-or-reference both branches, camelCase serialization, URN round-trip + malformed, config default.
- `import probos.runtime` smoke clean.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Do NOT build

- No projector (AD-1041), no HTTP route (AD-1042), no `representativeQueries` mining (AD-1043), no search (AD-1044), no client (AD-1046).
- Do **not** wire the package into `runtime.py` or any router — nothing imports it this AD.
- Do **not** touch `config/system.yaml` (default-OFF ships in `config.py`).
- Do **not** add signing/verification logic to `TrustManifest` — it is a data carrier only.
