# Review: AD-701 — Visiting Officers
**Verdict:** ✅ Approved
**Tight, well-scoped registry; verify-first claims hold; minor convention gaps only.**

## Required (must fix before building)
_None._

## Recommended
1. Add the working-tree integrity reminder (Wave 129 convention #20). Builder should run `git diff --numstat | sort -k2nr | head -5` before reading source — required by dispatch but not echoed in the prompt body.
2. D3 wiring code reads `runtime.emit_event` and `runtime.identity_registry` directly. Verify both are public attributes (not `_emit_event_fn` callable / `_identity_registry`). The pattern in D2 uses `emit_event=Callable[[str, Any], None]` so the runtime side must expose a real method matching that signature; flag a Builder pre-check.

## Nits
- D5 lists 8 required + 1 recommended test — section header says "≥ 8" but the numbering goes to 9. Acceptance criteria says "8+ tests pass". Consistent, but tighten the wording.
- Sweep-loop naming `ad701-sweep` is fine; consider `visiting-officer-sweep` for grep-friendliness across waves.
- Frozen dataclass `VisitingOfficerSession` has all defaulted fields after non-defaulted — ordering is correct.

## Verified
- `src/probos/identity.py:403` `class AgentIdentityRegistry` — confirmed.
- `src/probos/identity.py:707` `async def issue_birth_certificate(...)` — confirmed; `agent_type` is a free-form `str`, no schema change needed.
- `src/probos/ward_room/service.py:29` `class WardRoomService(EventEmitterMixin)` — confirmed.
- `src/probos/__main__.py:598` `_cmd_init` (prompt cites `:599`, drift = 1, fine).
- `enabled: bool = False` default — convention #14 honored.
- D4 explicitly leaves `WardRoomService` unchanged — boundary discipline correct.
- Hard-constraint list calls out Wave 10 convention #14 explicitly.

## Pass 2 Review (2026-05-08)

**Verdict:** ✅ Approved
**Pass-1 had 0 Required; pass-2 confirms cross-cutting items landed.**

### Required
None.

### Recommended
None new.

### Nits
None new.

### Verified Improvements (pass-2)
- ✅ Working-tree integrity reminder present in Acceptance section (verified `git diff --numstat` reference).
- ✅ Build Ordering Note present (config.py serialization slot: claude-bootstrap → AD-701 → AD-707 → Memvid-QP).
- ✅ All cited symbols (`AgentIdentityRegistry` `identity.py:403`, `WardRoomService` `ward_room/service.py:29`, `issue_birth_certificate` `identity.py:707`) still match HEAD.
- ✅ No phantom-API regressions introduced.

### Pass-2 outcome
Held at ✅. Cleared for Builder dispatch.
