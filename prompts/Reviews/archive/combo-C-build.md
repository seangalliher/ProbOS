# Combo C Build Report (Wave 13)

**Date:** 2026-05-03
**Builder:** GitHub Copilot (Builder mode)
**Prompt:** `prompts/combo-C-trivial-extensions.md` (revised at commit `72c1e7e`)
**Pass-2 review:** ✅ Approved (`prompts/Reviews/README-wave-13-pass-2.md`, commit `8ce4823`)

## Summary

Combo C shipped 5 children in a single commit, mirroring Wave 8 Combo A precedent. AD-572d and AD-573e were wholesale-deferred during the pass-1 → revision pass-2 architect review and were NOT built.

| AD | Type | File(s) | Tests |
|---|---|---|---|
| AD-526d | New file | `src/probos/recreation/preferences.py` (NEW) + `runtime.py` wiring | 4 |
| AD-572c | Extend | `src/probos/cognitive/captain_engagement.py` + `proactive.py` (`_gather_context`) | 3 |
| AD-573c | New action tag | `cognitive_agent.py` markers + `proactive.py` extractor | 4 |
| AD-573f | Lifecycle helpers | `src/probos/cognitive/working_memory.py` + `runtime.py` callback wiring | 5 |
| AD-575c | Flag | `src/probos/proactive.py` (`_check_unread_dms`) | 3 |
| **Total** | | | **19** |

## Per-child Notes

### AD-526d — GamePreferenceTracker
- New file at `src/probos/recreation/preferences.py` (~85 lines). Extends `recreation/` package (sibling to AD-526c `metadata.py`).
- Public attribute: `runtime.recreation_preference_tracker` (Wave 5 convention #1).
- Late-bind via `set_event_callback(self.emit_event)` in `runtime.__init__` mirroring `BilletRegistry`.
- Empty `agent_id`/`game_type` are no-ops (boundary test included).

### AD-572c — Ward Room Activity Summary
- Added async helper `wardroom_activity_summary()` to `CaptainEngagementProvider`. `snapshot()` left untouched (sync) — async helper called separately from already-async `_gather_context`.
- Aggregates per-channel via `list_threads(channel_id, limit=10)`; per-channel `try/except` so one failed channel doesn't kill the whole summary.
- Merged into `context["captain_engagement"]["wardroom_activity_summary"]` after the existing snapshot call.

### AD-573c — `[NOTE]` Action Tag
- Markers dict edit at `cognitive_agent.py:1747` matched the spec's SEARCH/REPLACE block exactly.
- Extractor uses `r'\[NOTE\s+([\w-]+)\](.*?)\[/NOTE\]'` (mirror notebook_pattern shape).
- Calls `runtime.working_memory.add_scratchpad(body)` and emits `WORKING_MEMORY_NOTE_RECORDED` with `{agent_id, tag, text_len}`.
- Strips `[NOTE …]` blocks from text after dispatch (mirrors notebook strip).

### AD-573f — Commitment Lifecycle
- Confirmed dict-of-`{id, summary, due?, status}` shape matches Combo A's actual ship (NOT a `Commitment` dataclass — Convention #20 reality-check honored).
- Manager-scoped (NO `agent_id` parameter — no per-agent partition exists).
- `set_event_callback` setter added to `WorkingMemoryManager`; runtime wires it immediately after construction.
- `add_commitment` extended to emit `COMMITMENT_RECORDED action="record"` after successful add.
- `mark_commitment_complete` clean no-op on unknown id (Wave-5 tier-2).

### AD-575c — DM Self-Reference Flag
- Read-only check on `dm["body"]`. Case-insensitive `@<callsign>` substring search.
- Added at the existing `event_data` construction site — minimal patch.

## What Was NOT Built

- **AD-572d** wholesale-deferred to AD-572d-i. Verified absence of `asyncio.Event`/`wait_for` patterns in `proactive.py` (only bare `asyncio.sleep` at lines 475/482/584/782). Did not touch `_think_loop` per the dispatch hard-stop.
- **AD-573e** wholesale-deferred to AD-573e-i. Verified absence of `cognitive_journal.recent_for_agent`. Did not invent the API.

## Test Counts

| Phase | Passing | Skipped | Delta |
|---|---|---|---|
| Pre-flight (post-Wave-12) | 10658 | 15 | baseline |
| AD-526d focused (`-n 0`) | 4 | 0 | +4 |
| AD-572c focused (`-n 0`) | 3 | 0 | +3 |
| AD-573c focused (`-n 0`) | 4 | 0 | +4 |
| AD-573f focused (`-n 0`) | 5 | 0 | +5 |
| AD-575c focused (`-n 0`) | 3 | 0 | +3 |
| **Combo C total focused** | **19** | **0** | **+19** |
| Full suite (`-n 8 --dist=loadfile`) | **10677** | **15** | **+19** |

## Hard-Stops Triggered

**None.** All 7 hard-stop conditions evaluated clean:

1. ✅ No phantom APIs introduced (`recreation_preference_tracker` documented FP per Wave-5 #1).
2. ✅ No architectural changes — all edits are additive at known extension points.
3. ✅ No persistent serial test failure on unchanged files.
4. ✅ No existing test breaks — full suite +19, zero regressions.
5. ✅ Zero quarantines introduced.
6. ✅ Inter-child SEARCH/REPLACE conflicts verified absent — sequencing (572c → 575c on `proactive.py`; 573c → 573f on `working_memory.py`) prevented overlap.
7. ✅ AD-573f shape matched live `working_memory.py` (Convention #20 honored).

## Flakes Observed

None. Full suite ran clean at `-n 8 --dist=loadfile` in ~7m24s.

## Files Changed

```
src/probos/events.py                          (+5)
src/probos/recreation/preferences.py          (NEW, ~85 lines)
src/probos/runtime.py                         (+10)
src/probos/cognitive/captain_engagement.py    (+45)
src/probos/proactive.py                       (+50)
src/probos/cognitive/cognitive_agent.py       (+1)
src/probos/cognitive/working_memory.py        (+70)
tests/test_combo_c_ad526d_preferences.py      (NEW, 4 tests)
tests/test_combo_c_ad572c_wardroom.py         (NEW, 3 tests)
tests/test_combo_c_ad573c_note.py             (NEW, 4 tests)
tests/test_combo_c_ad573f_commitments.py      (NEW, 5 tests)
tests/test_combo_c_ad575c_dm_self_ref.py      (NEW, 3 tests)
PROGRESS.md                                   (Combo C entry prepended)
DECISIONS.md                                  (Combo C entry under Era V)
docs/development/roadmap.md                   (5 status flags + 2 deferral notes)
```

## Compliance with Engineering Principles

Verified per `.github/copilot-instructions.md`:

- SOLID: SRP / OCP honored — additive surfaces, no private-attr reach across modules.
- Async discipline: New async helper uses standard pattern; no `ensure_future`; no fire-and-forget tasks.
- Logging: All new log sites include context (what failed, why it matters).
- Type annotations: All new public methods fully typed.
- Defense in depth: Every external API call wrapped in try/except with log-and-degrade fallback.
- Layer discipline: No upward imports introduced.
