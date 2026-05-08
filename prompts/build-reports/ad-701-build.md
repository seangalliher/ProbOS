# AD-701 build report — Visiting Officer registry

**Prompt:** `prompts/ad-701-visiting-officers-v1.md`
**Builder:** Wave 130 builder (continuous mode)
**Date:** 2026-05-08
**Status:** SHIPPED
**Issue closed:** #477
**Wave:** 130 (2 of 10)

## Files Changed

- `src/probos/visiting_officers.py` — new module: `VisitingOfficerSession` (frozen dataclass) + `VisitingOfficerRegistry` (in-memory store + sweep loop).
- `src/probos/config.py` — new `VisitingOfficersConfig` model + wiring on `SystemConfig`.
- `src/probos/startup/finalize.py` — wire `VisitingOfficerRegistry` after MCPBridge; sources `instance_id` / `vessel_name` / `baseline_version` from `runtime.ontology.get_vessel_identity()` (corrected from prompt's `runtime.instance_id` references — see verify-first).
- `src/probos/startup/shutdown.py` — symmetric `await runtime.visiting_officers.stop()` before identity registry stops.
- `tests/test_ad701_visiting_officers.py` — 11 new tests.
- `DECISIONS.md` — AD-701 entry appended.

## Sections Implemented

- **D1.** `VisitingOfficerRegistry` module — done (frozen dataclass session, lock-protected dict, async sweep loop with cancellation handling, log-and-degrade emit_event).
- **D2.** `VisitingOfficersConfig` Pydantic model — done; wired alongside `WardRoomConfig` on `SystemConfig`. Default `enabled=False` (convention #14).
- **D3.** Runtime wiring in `finalize.py` — done; placed after MCPBridge per prompt.
- **D4.** Ward Room post attribution — no code change required; `WardRoomPost.author_id` is already `str`. Documented in `VisitingOfficerRegistry.register` docstring that consumers SHOULD `has_capability(did, "ward_room.post")` before relaying.
- **D5.** Tests — 11 cases (8 required + start/stop + config + emit-failure log-and-degrade).

## Post-Build Section Audit

All five `D*` sections from the prompt have corresponding code changes. No omissions.

## Verify-First Findings

- ✅ `AgentIdentityRegistry.issue_birth_certificate` signature matches at `identity.py:707`.
- ✅ `WardRoomPost.author_id` is `str` (`ward_room/models.py:46–58`).
- ✅ `runtime.identity_registry` public attribute (`runtime.py:532, 1352`).
- ✅ `runtime.emit_event` public method (`runtime.py:924`).
- ⚠️ **`runtime.instance_id` / `vessel_name` / `baseline_version` do NOT exist as direct runtime attributes.** Prompt's D3 code would have raised `AttributeError`. Builder corrected by sourcing from `runtime.ontology.get_vessel_identity()` which returns a `VesselIdentity(name, version, instance_id)` (`ontology/service.py:86`, `ontology/models.py:56`). Falls back to `config.system.version` if ontology is missing. Documented inline.
- ✅ `MCPBridge` wiring at `finalize.py:2528` provides the insertion-point template (the AD-701 wiring placed immediately after).

## Test Results

```
.\.venv\Scripts\pytest.exe tests/test_ad701_visiting_officers.py -v -n 0
11 passed in 0.33s
```

Full gate:
```
.\.venv\Scripts\pytest.exe tests/ -q -n 8 --dist=loadfile
12793 passed, 16 skipped, 175 warnings in 479.74s
```

Pre-AD-701: 12782 → +11 = 12793. Test count non-decreasing.

## Hard Constraints Honored

- ✅ No new `events.py` enum value — uses string event names through `emit_event` callback (matches `MCPBridge` pattern).
- ✅ No mutation of `WardRoomService` — registry is the enforcement seam.
- ✅ No SQLite persistence in v1 (forward marker AD-701b).
- ✅ No new `agent_tier` enum — `agent_type="visiting"` on existing certificate.
- ✅ No inbound MCP transport logic.
- ✅ Default `enabled=False` (convention #14).

## Pre-Commit Deletion Check

Top-5 staged files by line count — no file shows >200 deletions. Clean.

## Engineering Principles Compliance

- ✅ SOLID: Registry has single responsibility (session lifecycle); identity issuance is delegated. Open/Closed: capabilities are strings, not enums.
- ✅ Dependency Inversion: registry accepts `identity_registry` and `clock` as constructor params (testability).
- ✅ Type annotations on all public methods (incl. `Callable[[str, Any], None]` for emit_event).
- ✅ Async hygiene: `_sweep_task` reference held; `asyncio.CancelledError` caught and re-raised cleanly in `stop()`. `start()` is idempotent.
- ✅ Log-and-degrade on `emit_event` exceptions (regression-tested).
- ✅ Boundary tests: empty callsign, empty caps, zero TTL, expired session, unknown DID, out-of-scope cap, sweep deregistration.
- ✅ Defense in depth: capabilities checked at every `has_capability` call (also re-validates expiry).
