# Wave 43 Dispatch — AD-695 v1 Ship Health Oracle Tier + Threshold Bridge Alerts

**Single-AD continuous-build wave.** FULL v1 (Captain "no trivial deferral").

## Inputs

- `prompts/ad-695-ship-health-oracle-v1.md` — the prompt.
- `.github/copilot-instructions.md` — engineering principles.

## Standing rules

- Test gate: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile`.
- Hard-stop conditions:
  1. Any new `_publish_once` body references `create_post()` or `_format_post()` for posting — re-disable per BF-258.
  2. Phantom API surfaces (anchor mismatch, missing method on real class).
  3. ThresholdAlertConfig defaults change to `enabled=True` — Wave-10 transitional-flag convention violation.
- Anti-patterns to flag:
  - `runtime.threshold_alerts` accessed without `None` guard (the config defaults to disabled).
  - `_query_health` reaching into `runtime` directly instead of via `self._health_provider`.
  - New EventType added (none required for v1).
  - `BridgeAlert.dedup_key` left blank (must be `threshold_id`).

## Wave-specific reminders

1. **AD-641a `_publish_once` already neutered (BF-258).** The "spam loop removal" task is a NO-OP at HEAD — what's left is to wire the threshold call into the existing dormant body. Do NOT re-disable a non-existent `create_post`.
2. **Default-False on ThresholdAlertConfig** is intentional — opt-in to ward-room noise. Default-True deviation is **NOT** acceptable here (unlike AD-687/AD-689/AD-692 where pass-through made it safe). ThresholdAlerts actually DO post things on enable; they need explicit operator opt-in.
3. **`_query_health` parameter shape is `(query_text, *, k)`** — no `requester_agent_id`, no `tiers`, no `types`. Mirrors `_query_records`/`_query_archive` minimal shape, NOT `_query_graph`.
4. **`runtime` IS the health_provider** — `runtime.spawner.pools` / `runtime.attention` / `runtime.degradation_manager` / `runtime.observability_bridge` all already exist as public-ish attributes. No new accessor surface. Tests use `SimpleNamespace` to mimic the same shape.
5. **`StressLevel` ordering hardcoded** in `_check_degradation`: `{normal:0, elevated:1, degraded:2, critical:3}`. Verified at `src/probos/degradation/policy.py:10` (StressLevel(str, Enum)). If actual enum members differ at HEAD, builder must match — but spec assumes standard four-tier ladder.
6. **BridgeAlert constructor** at `bridge_alerts.py:30` expects `(id, severity, source, alert_type, title, detail, department, dedup_key, ...)` — `id` non-default first. Use `str(uuid.uuid4())` (matches existing pattern at `bridge_alerts.py:14`). `related_pool` defaults to None.
7. **Attention `queue_size` is a property** at `attention.py:193` — read with `int(getattr(attn, "queue_size", 0) or 0)`.
8. **Phantom-API pre-check expectations**: 0 NEW phantoms. Likely FPs: `runtime.threshold_alerts` (introduced by prompt), `ThresholdAlertConfig` (introduced by prompt), `OracleService.attach_health_provider` (introduced by prompt), `OracleService._query_health` (introduced by prompt). Same intro-not-yet-in-index FP class as Waves 27/28/29/31/32/33/41/42.

## Build groups

Single ordered build group:

1. Section 1 — write `src/probos/cognitive/threshold_alerts.py` (~250 lines).
2. Section 2 — `multi_replace` two SEARCH/REPLACE blocks in `config.py` (1298 + 2161).
3. Section 3 — single SEARCH/REPLACE in `finalize.py` after AD-641a block.
4. Section 4 — single SEARCH/REPLACE in `observability/bridge.py` (`_publish_once` body).
5. Section 5 — `multi_replace` in `oracle_service.py` (3 blocks: tier list, dispatch slot, ctor; plus 1 sequential `replace_string_in_file` for `attach_health_provider`; append `_query_health` after `_expand_via_graph`).
6. Section 6 — single SEARCH/REPLACE in `finalize.py` (extend the block from Section 3).
7. Section 7 — write `tests/test_ad695_ship_health_oracle.py` (~360 lines, 13 tests).

## Per-commit quality gates

- After Section 7 lands: run targeted test file `pytest tests/test_ad695_ship_health_oracle.py -v -n 0`. All 13 must pass before invoking the full gate.
- Full gate must show `+13` from Wave 42 baseline (11064 → 11077).

## Trackers (single-commit-bundled)

- `PROGRESS.md` — prepend Era V entry.
- `docs/development/roadmap.md` — status flip Scoped → Complete.
- `DECISIONS.md` — prepend Era V entry.

## Post-build

- Single commit: `Wave 43 build: AD-695 v1 Ship Health Oracle Tier + Threshold Bridge Alerts (#389)`.
- Push to `origin/main`.
- Issue #389 close BLOCKED by EMU 403 — user closes manually.
- Move prompt + dispatch to `prompts/archive/`.
- Wave plan id="43" status: pending → done (orchestrator advances).
