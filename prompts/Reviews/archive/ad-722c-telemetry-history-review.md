# Review: AD-722c — Avatar telemetry history (JSONL)

**Verdict:** ✅ Approved
**JSONL-per-agent + lazy retention query + best-effort writer hook lands cleanly. All verify-first claims hold.**

## Required (must fix before building)
_None._

## Recommended
1. **Docstring reference in `TelemetryHistoryWriter.append`** says the executor pattern "mirrors records_store async-with-blocking-write usage." `RecordsStore.write_entry` (records_store.py:90) is `async def` and does its own subprocess management; it's not a sync-via-executor pattern. Soften the comment to just "synchronous file write inside a thread executor — avoids needing aiofiles."

## Nits
1. `query()` reads the whole file then sorts + slices to `limit`. Fine for v1 (~400 B rows × retention_days × frame rate stays well under 100 MB for normal operators), but worth mentioning in the AD-722c-1 forward marker — rotation + tail-first read is the natural pair.
2. `_sanitize_agent_id` rejects empty strings and non-`[A-Za-z0-9_.\-]` — verify the existing crew agent IDs all match this regex (they do per current registry, but worth a one-line assertion comment).

## Verified
- `AvatarTelemetryConfig` at `src/probos/config.py:1025` — confirmed; existing fields `divergence_aggregate_window: int = 50` (1062) is the correct anchor for new fields.
- `AvatarTelemetrySnapshot` frozen dataclass at `src/probos/avatars/telemetry.py:345`; `to_dict()` at line 378-389 returns 10-key flat-ish dict.
- `runtime.avatar_event_bus = AvatarEventBus()` at `src/probos/runtime.py:430`.
- WS publish loop: `agent._last_self_avatar_snap = initial` at `routers/agents.py:708`; `agent._last_self_avatar_snap = snap` at line 737. Both anchor lines for the Tier-2 hook exist exactly as the prompt asserts.
- `agent_avatar_telemetry` GET at line 609; WS handler `agent_avatar_telemetry_stream` at line 635 — endpoint insertion seam is correct.
- Tier-2 log-and-degrade pattern: writer methods all wrap I/O in `try/except` with WARNING log and silent return. Tier-2 per `.github/copilot-instructions.md` — correct.
- Test plan: 6 tests cover happy + error + edge (malformed line, malicious agent_id, disk failure, retention window). Boundary coverage required by review-criteria §7 — met.
- License: stdlib only. AD-731 invariant N/A here (no attachments).
- Phase ordering (§10): writer is constructed at runtime.py:430 alongside `AvatarEventBus()` — both in the same early phase. No cross-phase consumer. Clean.
- No UI changes — AD-738b UI gate not triggered. Correctly omitted from verification commands.

---

**Re-review:** _(pending Builder dispatch)_

### Re-review (pass-2): unchanged, verdict re-affirmed ✅
