# AD-572e Build Report

**Wave:** 18 (single-prompt)  
**Date:** 2026-05-03  
**Mode:** Single commit. Final AD-572 child.

## Summary

Shipped `CaptainEngagementProvider.task_awareness(agent_id)` async helper + proactive-loop injection. Mirrors Combo C (`wardroom_activity_summary`) pattern exactly.

## Changes

| File | +/- | Notes |
|---|---|---|
| `src/probos/cognitive/captain_engagement.py` | +52 | New async helper at line 163 |
| `src/probos/proactive.py` | +10 | Sibling block after Combo C injection (lines 1197-1206) |
| `tests/test_ad572e_task_awareness.py` | +166 | 12 new tests |
| `PROGRESS.md` | +1 prepended entry | |
| `DECISIONS.md` | +9 | Era V entry |
| `docs/development/roadmap.md` | line 4572 updated | 572e flipped to complete; 572d-i still deferred |

## Test Counts

- Focused: 12/12 pass at `pytest tests/test_ad572e_task_awareness.py -v -n 0` in 0.26s.
- Full gate: **10755 passed, 15 skipped** in 401.85s (delta **+13** vs Wave 17 baseline 10742 — 12 new + 1 previously-flaky `test_model_tier_query` now passing on its own; pre-existing local-overlay flake unrelated to this AD).

## Confirmations

- ✅ Helper is **async** (`async def task_awareness`).
- ✅ Helper is **defensive** — returns `{}` on runtime None / agent_id falsy / store missing / query exception (mirrors Combo C log-and-degrade tier).
- ✅ Helper returns **structured dict** `{"open_count": int, "tasks": [{"id", "title", "type"}]}` mirroring Combo C shape.
- ✅ Proactive injection at `proactive.py:1196-1206` **reuses** the existing `engagement_provider` local from line 1181 (no re-fetch).
- ✅ Uses `isinstance(context.get("captain_engagement"), dict)` injection guard (NOT `setdefault`).
- ✅ Uses `hasattr(engagement_provider, "task_awareness")` forward-compat guard.
- ✅ AD-572d-i was **NOT** touched — no interruptible-wait pattern, no `asyncio.Event`, no `wait_for` added.
- ✅ No new EventTypes. No new public attributes. No new Pydantic config.

## Hard-Stops Triggered

**0.**

## Flakes Observed

`test_model_tier_query` was failing in baseline (1 fail before my change), now passing in the post-build full-gate run. Pre-existing local-overlay artifact from stashed unrelated mods (`config/ontology/resources.yaml`, `llm_client.py`, `model_registry.py`, `config.py`, `test_ad463_model_routing.py`, `test_ontology_ops_comms_resources.py` — stashed pre-flight under `wave-18-preflight-stash`). Not related to AD-572e.

No xdist crash; no flake in the new test file.

## Section Audit

| Section in prompt | Implementation |
|---|---|
| Section 0 — EventTypes | Confirmed no new EventTypes (verbatim). |
| Section 1 — `task_awareness()` helper | `captain_engagement.py:163` |
| Section 2 — Proactive injection | `proactive.py:1196-1206` |
| Section 3 — Pydantic config | Confirmed no new config (verbatim). |

All `###` sections from the prompt mapped to code or explicit no-op verification.
