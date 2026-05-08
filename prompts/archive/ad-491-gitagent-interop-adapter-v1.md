# AD-491 v1 — gitagent interop adapter (publish/install boundary only)

**Issue:** [#491](https://github.com/seangalliher/ProbOS/issues/491)
**Type:** Architecture Decision (interop boundary — pure OSS plumbing)
**Depends on:** AD-441 (sovereign DID identity, AgentIdentityRegistry, birth certificates).
**Wave:** 129

## Goal

Other agent ecosystems (notably the emerging "gitagent" YAML format) describe agents as flat YAML manifests for publish/install distribution. ProbOS's authoritative identity model is the AD-441 sovereign DID + birth certificate (`did:probos:{ship_id}:{agent_uuid}`). AD-491 ships a **boundary adapter** — `export_agent_to_gitagent_yaml()` and `import_gitagent_yaml()` — that lets the OSS runtime publish a ProbOS agent in gitagent shape and consume a third-party gitagent YAML at install time, **without changing any internal representation**. The sovereign DID stays authoritative; the gitagent format is a serialization at the publish/install seam only.

## Verified Against Codebase (2026-05-08)

- ✅ `src/probos/substrate/agent.py:18` defines `class BaseAgent(ABC)` — agent identity surface for the export adapter.
- ✅ `src/probos/types.py:26-32` defines `class CapabilityDescriptor` with field `can: str` (plus `detail: str = ""`, `formats: list[str] = []`, `confidence: float = 1.0`). `[c.can for c in agent.default_capabilities]` is the correct read shape — verified at HEAD.
- ✅ AD-441 substrate is shipped: `decisions-era-4-evolution.md:1003` confirms `AgentIdentityRegistry` with three SQLite tables (`birth_certificates`, `identity_ledger`, `slot_mappings`) and `agent.sovereign_id` / `agent.did` attributes assigned during `_wire_agent()` at runtime startup.
- ✅ `decisions-era-4-evolution.md:1005` confirms 18 tests in `test_agent_identity.py` — Builder reads it before drafting D4 to confirm the public read surface (e.g. `identity_registry.get_certificate(sovereign_id)`).
- ✅ No existing `interop/` package at HEAD: `grep -n "gitagent" -r src/` returns 0 hits — collision-free greenfield.
- ✅ Pyproject already pulls in `pyyaml` for config parsing — verified via existing `from yaml import safe_load` import in `src/probos/config.py` (Builder confirms — if not present, add `pyyaml` to dependencies).
- ✅ The dispatch's "interop boundary only, not internal representation" guardrail aligns with the AD-441 design principle: sovereign DID is the steel thread; serialization formats orbit it.

## Scope

A new `interop/gitagent.py` module with two pure functions: one export, one import. No runtime wiring, no agent mutation, no commercial integration. The OSS sovereign DID identity remains authoritative — gitagent YAML is a translation layer at the publish/install seam.

## Deliverables

### D1. New package `src/probos/interop/__init__.py`

Empty (or single-line module docstring). The package exists to host future interop adapters (gitagent today, others later).

```python
"""ProbOS interop boundary adapters.

Each module in this package translates between the authoritative ProbOS
internal representation and an external ecosystem's wire format. Adapters
are publish/install-time only -- they do not run in the request path.
"""
```

### D2. New module `src/probos/interop/gitagent.py`

Module docstring at top:

```python
"""AD-491: gitagent YAML interop adapter.

The OSS sovereign DID + birth certificate is the authoritative identity.
This module is a pure boundary adapter for publishing a ProbOS agent in
gitagent YAML format and consuming a third-party gitagent YAML at
install time. No internal data model changes here.

Public API:
    export_agent_to_gitagent_yaml(agent) -> str
    import_gitagent_yaml(path) -> dict
"""
```

Imports: `from __future__ import annotations`, `from pathlib import Path`, `import yaml`, plus typing.

#### D2a. `export_agent_to_gitagent_yaml(agent)`

Signature:

```python
def export_agent_to_gitagent_yaml(agent: "BaseAgent") -> str:
    """Render a ProbOS agent in gitagent YAML format.

    The returned YAML carries the gitagent-canonical fields (name,
    version, runtime, capabilities, instructions) plus a ``probos``
    sub-section that preserves the sovereign DID and birth certificate
    hash so a round-trip back to ProbOS can re-assert authoritative
    identity. Round-tripping is by hash reference, not by re-issuing
    the sovereign DID -- the original ship's birth certificate remains
    the source of truth.
    """
```

Field mapping (all fields read from the agent via existing public attributes — Builder verifies each on `BaseAgent`):

| gitagent YAML key | Source on agent (verify at HEAD) |
|---|---|
| `name` | `agent.callsign` (fallback `agent.agent_type`) |
| `version` | `"1"` literal in v1 (no agent.version field exists; defer per-agent versioning) |
| `runtime` | `"probos"` literal |
| `agent_type` | `agent.agent_type` |
| `tier` | `agent.tier` |
| `capabilities` | `[c.can for c in agent.default_capabilities]` |
| `intents` | `[i.name for i in agent.intent_descriptors]` |
| `instructions` | `agent.instructions or ""` (CognitiveAgent attr) |
| `probos.sovereign_id` | `getattr(agent, "sovereign_id", "")` |
| `probos.did` | `getattr(agent, "did", "")` |
| `probos.pool` | `agent.pool` |

Use `yaml.safe_dump(..., sort_keys=False, default_flow_style=False)`. Return the rendered string.

If `agent.sovereign_id` is missing (cold start before AD-441 wiring), still produce valid YAML with `probos.sovereign_id: ""` — do NOT raise.

#### D2b. `import_gitagent_yaml(path)`

Signature:

```python
def import_gitagent_yaml(path: str | Path) -> dict[str, Any]:
    """Parse a gitagent YAML file into a ProbOS-friendly dict.

    Returns a dict with normalized keys ready for an installer to
    construct or register an agent. Does NOT instantiate a BaseAgent
    -- the caller (typically a future commercial-overlay installer)
    decides what to do with the parsed manifest.

    Raises ValueError on invalid YAML or missing required gitagent
    keys (``name``, ``runtime``). Other parse-time errors propagate.
    """
```

Required keys (raise `ValueError` if any missing): `name`, `runtime`.
Optional keys (default to empty/[]/"" in the returned dict): `version`, `agent_type`, `tier`, `capabilities`, `intents`, `instructions`, `probos`.

Returned dict shape:

```python
{
    "name": str,
    "version": str,            # "" if absent
    "runtime": str,
    "agent_type": str,
    "tier": str,
    "capabilities": list[str],
    "intents": list[str],
    "instructions": str,
    "probos": {
        "sovereign_id": str,   # "" if absent or non-probos source
        "did": str,
        "pool": str,
    },
}
```

If the source `runtime` is not `"probos"`, set `probos.sovereign_id` and `probos.did` to `""` regardless of what the file says — sovereign identity must be re-issued by the installer through the AD-441 registry, not trusted from foreign YAML. **This is the security boundary.**

### D3. Tests in `tests/test_ad491_gitagent_interop.py`

Minimum 8 tests using `tmp_path`:

1. `test_export_minimal_agent_produces_valid_yaml` — fake BaseAgent with `callsign="bones"`, `agent_type="diagnostician"`, etc -> `yaml.safe_load(export(...))` succeeds.
2. `test_export_includes_probos_sovereign_id` — agent with `sovereign_id="abc123"` -> parsed YAML has `probos.sovereign_id == "abc123"`.
3. `test_export_handles_missing_sovereign_id_gracefully` — agent without `sovereign_id` attr -> `probos.sovereign_id == ""` in output, no exception.
4. `test_export_capabilities_and_intents_serialize_as_lists` — agent with three CapabilityDescriptors and two IntentDescriptors -> YAML has `capabilities: [...]` (3 entries) and `intents: [...]` (2 entries).
5. `test_import_round_trip_probos_runtime` — export a ProbOS agent, write to tmp file, import -> returned dict has the same `probos.sovereign_id` value (round-trip-by-reference, not re-issuance).
6. `test_import_foreign_runtime_clears_sovereign_id` — write a YAML with `runtime: gitagent` and `probos.sovereign_id: forged-id` -> imported dict has `probos.sovereign_id == ""` (security boundary).
7. `test_import_missing_required_key_raises_valueerror` — write YAML lacking `name` -> `pytest.raises(ValueError, match="name")`.
8. `test_import_invalid_yaml_raises` — write a malformed YAML file -> `pytest.raises((yaml.YAMLError, ValueError))`.

All tests use a small `_FakeAgent` namespace stub — no real `BaseAgent` instantiation required. Reads must be attribute-based (not method calls) to match `getattr(agent, "sovereign_id", "")` shape.

## Non-Goals

- Do NOT instantiate or register an agent from imported YAML — that's a separate AD with its own clearance flow.
- Do NOT trust foreign-runtime sovereign IDs — the boundary always clears them on import.
- Do NOT add a `/install` slash command, HXI surface, or runtime wiring — pure publish/install adapter only.
- Do NOT add federation publishing — interop is local-disk in v1.
- Do NOT write to the AgentIdentityRegistry from the import path. Identity issuance is the registry's job, not the adapter's.
- Do NOT change `BaseAgent`, `IntentMessage`, `RuntimeProtocol`, or any AD-441 substrate.
- Do NOT add a "gitagent" tier or pool — interop happens at the YAML edge only.

## Acceptance

- Focused: `pytest tests/test_ad491_gitagent_interop.py -v -n 0` — 8/8 pass.
- Full gate: `pytest tests/ -q -n 16 --dist=loadfile` — green or only environmental flakes.
- `git diff` shows changes only in: `src/probos/interop/__init__.py` (new), `src/probos/interop/gitagent.py` (new), the new test file. No edits to `runtime.py`, `config.py`, `BaseAgent`, or any registered agent.
- Comply with engineering principles in `.github/copilot-instructions.md`.

## Tracking

- Closes [#491](https://github.com/seangalliher/ProbOS/issues/491).
- DECISIONS.md entry stub: AD-491 — gitagent interop adapter at the publish/install boundary; sovereign DID identity remains authoritative; foreign runtimes clear sovereign IDs on import.

## Revision (2026-05-08)

- **Recommended #1 applied**: Confirmed `CapabilityDescriptor.can` field name against `src/probos/types.py:26-32`. Field is `can: str` (not `name`); the existing `[c.can for c in agent.default_capabilities]` shape in D2a is correct. Added a verified-line entry citing the exact location.
