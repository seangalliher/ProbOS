# AD-1270 (#1324): Night Orders escalation, wired: the hook never costs an event its dispatch, a match pages the Captain through the real bridge-alert path, and only triggers with a producer are mapped

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-27

**Status:** build-ready on `a2390998` (the AD-1341 S6 candidate). The orchestrator re-anchors on S6's merge. No new AD or BF number: this is the Night Orders checklist item on #1324 (comment 6230904043, from the BF-897 review F1). **Captain:** no condition met (D8). Overrulable: D2 (`red_alert`/`security_alert` are reported as inert rather than given producers) and D3 (trust pages on the crossing, not while below the floor).

**Re-anchored and reformatted by the orchestrator (2026-10-27).** (1) **Base:** `origin/main` `71ff4785834902c5985ae57344761d23a42245d7`, the merge of AD-1341 S6 (PR #1689). Its tree, `628f874a7b04a5e34878d84f6479e98b314a6cc1`, is the tree the Architect drafted on (`a2390998`), so every SEARCH below applies unchanged. (2) **Pair format:** the Architect wrote each pair as `Pair N:` with bare `SEARCH` and `REPLACE` lines inside one fence, and the 7.6 and section 8 pairs with no label at all; the apply tool reads `SEARCH:` and `REPLACE:` labels with a fence each, so the orchestrator converted all 14 pairs by tool (a round trip proved every body byte for byte; the 7.6 and section 8 labels now name their file). (3) **DECISIONS.md pair (section 8):** moved from the top of the Era V section to after AD-1341 S6's entry, where the file's recent entries are appended in date order; it also carries the just-culture entry the Captain asked to have recorded (#1569 comment 1; follow-up #1690, entry (d)), text by the Architect's 2026-10-27 consult. (4) **M3 also regenerates the AD ledger:** `python scripts/gen_ad_ledger.py`, then stage the two files it rewrites (`docs/development/open-ads-report.md`, `docs/development/ad-ledger-snapshot.json`); without it `gen_ad_ledger.py --check` and `tests/test_ad1184_ad_ledger.py` fail (measured on the orchestrator's oracle: 3 failures, then 33 passed). (5) **Dates:** every `2026-10-2X` in section 8 becomes the date of M3's commit.

**Amendment A1 (`claude-architect`, 2026-10-27, after the orchestrator's census of `427546b8`: 24 killed, 2 survived).** (1) **R-7 closed:** D2 now drives a second crossing of the same agent inside the 300 s cooldown. It asserts that the hook reached the service (the conn manager was called twice) and that no delivery was scheduled. It also asserts that the update that stays below the floor matched nothing. D2's body changes; the case count does not. (2) **R-9 recorded as equivalent:** an inactive manager's `check_escalation` is already False. Its §10 row names no test. (3) **§10 made census-ready:** every Killed-by cell names full function names, with `[id]` for a single case. W-2 and B-1 name their measured killers (T3b, D7) plus D2, which A1's assertions are predicted to make a second killer of both. (4) **§6 corrected:** the triggers file holds 32 cases. M2's file fails on 10 of 11 cases on its base: D3 passes there, as a negative case, and mutation R-2 kills it. (5) **Not changed:** §7.1 to §7.4 and §8. Rerun after A1: the baseline, then W-2, B-1, R-4, R-7, R-8.

**Milestones and tiers:**
- **M1, the trigger truth** (`watch_rotation.py`, the console command, tests). **STANDARD**: Captain-facing Night Orders behaviour and status.
- **M2, delivery and isolation** (`runtime.py` hook, `bridge_alerts.py`, tests). **HIGH**: `ProbOSRuntime._emit_event` is the shared event-emission contract (AD-1195 durable offer, NATS, listeners).
- **M3, trackers.**

Each milestone is one Builder delegation and one local commit, built in order and staged by explicit path, never `git add -A`. M2 gets a cross-family review (`gpt-6.1-sol`). The broad gate is the orchestrator's single canonical run after M3: `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label ad1270-night-orders --receipt logs/gates/ad1270-night-orders.receipt.json`. One mutation campaign runs on the assembled tree (§10).

**Tests:**
- New: `tests/test_ad1270_night_orders_triggers.py` (M1), `tests/test_ad1270_night_orders_delivery.py` (M2).
- Updated, with an inline reason: `tests/test_autonomous_operations.py` (M1). Two tests re-implemented the old inline rule on a `new_trust` field no producer sends, so they pinned the defect.
- No test touches a live system or a real data directory.

**Line endings:** the working copies are CRLF (`core.autocrlf=true`). The SEARCH blocks are LF; match and write with the file's own endings. New files are written LF.

---

## 0. Premise: what is present on this tree

| Clause | State | Evidence |
|---|---|---|
| `_emit_event` calls the hook first, unguarded, before durable offer and dispatch | present | `runtime.py:1946-1957` |
| The hook calls `self.bridge_alerts.add_alert(...)`, which does not exist | present | `runtime.py:2179-2185`; Absence AV1 |
| Its map keys `trust_change`, `alert_condition_change`, `build_failure`, `security_alert`, and the trust rule reads `new_trust` | present | `runtime.py:2150-2167` |
| Only `build_failure` has producers | present | `routers/build.py:85,366,410,482,489`; Absence AV2 |
| The trust producer emits `trust_update` with `old_score`, `new_score` | present | `consensus/trust.py:492-499`, `:534-541`, `:659-678` |
| Nothing changes the alert condition; AD-455's monitor reports nothing in v1 | present | `ontology/service.py:105`; `security/trust_integrity.py:64-75`; Absence AV3 |
| Night Orders is built in production when the proactive loop is on | present | `startup/finalize.py:4211-4216`; `runtime.py:3594` |
| The bridge-alert pattern: `BridgeAlertService.check_*` builds, deduplicates (`_should_emit`, AD-580 suppression) and records; the caller delivers via `WardRoomRouter.deliver_bridge_alert` | present | `bridge_alerts.py:92-113`, `:310-347`; `runtime.py:4790-4796`; `ward_room_router.py:1181-1227` |
| The service docstring names `_deliver_bridge_alert()`, which the runtime no longer has | present | `bridge_alerts.py:50-51`; Absence AV1 |
| Per-event tasks are held in `_event_listener_tasks` (BF-639), not `_background_tasks` | present | `runtime.py:1435-1438`, `:1984-1989`, `:3901-3904` |
| Borrowed-method hosts (BF-708) bind the hook with partial collaborators | present | `tests/test_bf897_build_pipeline_scale_and_checkout.py:898-919`; `tests/test_ad1195_durable_event_seam.py:66-82` |
| BF-897's tests pin "an unmarked build_failure still escalates (conn called)" and "a refusal does not" | present | `tests/test_bf897_build_pipeline_scale_and_checkout.py:929-966` |
| `BridgeAlertService` is frozen srp-size debt (no magnitudes stored) | present | `docs/development/architecture-baseline.yaml:331-339` |

## 1. Problem

When Night Orders list `build_failure` (the `maintenance` template, `watch_rotation.py:187`) and a real build fails, `_check_night_order_escalation` raises `AttributeError`. The exception comes out of `_emit_event` before the durable offer, the NATS publish and the local dispatch, so the HXI, the durable log and the stream all lose the event, and the Captain is not paged.

The other three triggers can never fire: their event names are never emitted. `trust_drop` is mapped from `trust_change`, but the producer emits `trust_update`.

## 2. Solution overview

- **M1:** the trigger rule moves beside the templates as `watch_rotation.night_order_trigger(event_type, details, *, trust_floor)`. It maps `build_failure` → `build_failure` (keeping BF-897's `not_executed is True` skip) and `trust_update` → `trust_drop`, raised once as the score crosses below the conn floor. `red_alert` and `security_alert` stay valid names but are unmapped. `get_status()` gains `inert_triggers`, `set_night_orders` logs a warning for them, and `/night-orders` prints them.
- **M2:** the hook becomes log-and-degrade. `BridgeAlertService.check_night_orders_escalation` builds the alert (ALERT severity, deduplicated per trigger and subject, suppressible by the Captain under AD-580). The hook delivers it with `WardRoomRouter.deliver_bridge_alert` on a task held in `_event_listener_tasks`.

## 3. Decisions

- **D1. The rule lives in `watch_rotation.py`**, the owner of the trigger vocabulary. It takes `trust_floor` as an argument, so `watch_rotation` imports nothing from `config`. The runtime passes `TRUST_FLOOR_CONN`, which it already imports (`runtime.py:111`).
- **D2. Inert, not invented.** Giving `red_alert` or `security_alert` a producer would be new capability, which is paused. The templates keep both names, because they become live the day a producer lands. Status, the console and a log line say they never fire. A guard test (T2) fails when a producer appears.
- **D3. Trust pages on the crossing** (`old >= floor > new`). An update that stays below the floor never pages again. The bridge-alert cooldown (300 s) applies per agent on top.
- **D4. Build in the service, deliver from the caller**, as all ten-plus other alert kinds do. The cost is one cohesive method on frozen srp debt; the baseline row is unchanged (R3).
- **D5. Fetch the loop before the alert is built.** Outside a running loop the alert is never built, so an undeliverable alert never uses up its cooldown.
- **D6. Keep `getattr` for collaborators.** BF-708 borrowed-method hosts lack them, which is the same reason `_emit_event` reads `durable_events` that way (`runtime.py:1951-1955`).
- **D7. The hook stays where it is in `_emit_event`.** AD-471's ordering intent (escalate even if dispatch fails) holds; only its failure is contained.
- **D8. Captain conditions:** none. Nothing destructive. No control is weakened: the hook used to raise and kill the event, and now it logs. There is no schema, route or config change, no spending, and no change across the OSS boundary.

## 4. Milestones

Write each milestone's new test file first and run it on the milestone's base: M1's must fail at collection, and M2's must fail on every case except D3, a negative case that passes on the old hook too (§6). If a test outside §7 fails, stop and report it; never delete or loosen a test. Run each focused gate with `d:/ProbOS/.venv/Scripts/pytest.exe -n 0`.

| Milestone | Tier | Files (§7) | Focused gate |
|---|---|---|---|
| **M1** trigger truth | STANDARD | 7.1 `src/probos/watch_rotation.py`; 7.2 `src/probos/experience/commands/commands_autonomous.py`; 7.3 new `tests/test_ad1270_night_orders_triggers.py`; 7.4 `tests/test_autonomous_operations.py` | `tests/test_ad1270_night_orders_triggers.py tests/test_autonomous_operations.py tests/test_commands_autonomous.py tests/test_bf897_build_pipeline_scale_and_checkout.py tests/test_ad1251_watch_orders_removed.py tests/test_workforce.py` |
| **M2** delivery and isolation | HIGH | 7.5 `src/probos/bridge_alerts.py`; 7.6 `src/probos/runtime.py`; 7.7 new `tests/test_ad1270_night_orders_delivery.py` | `tests/test_ad1270_night_orders_delivery.py tests/test_ad1270_night_orders_triggers.py tests/test_bridge_alerts.py tests/test_bf897_build_pipeline_scale_and_checkout.py tests/test_ad1195_durable_event_seam.py tests/test_ad637d_system_events_nats.py tests/test_ad680_public_runtime_api.py tests/test_bf708_capability_notice.py tests/test_ad1274_report_off_loop.py tests/test_autonomous_operations.py tests/test_layer_boundaries.py tests/test_ad1270b_architecture_fitness.py`; then `d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_architecture_principles.py --check` |
| **M3** trackers | docs | §8 | `tests/test_ad1184_ad_ledger.py`; `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py --check` |

## 5. Consumers of every value this changes

| Value | Consumers | Effect |
|---|---|---|
| `night_order_trigger`, `NIGHT_ORDER_TRIGGER_EVENTS`, `WIRED_NIGHT_ORDER_TRIGGERS` | `runtime._check_night_order_escalation` (M2), tests | new |
| `get_status()["inert_triggers"]` | `cmd_night_orders`; `GET` in `routers/system.py:429-431` (JSON, additive); no HXI reader (Grep `escalation_triggers\|night.orders` in `ui/src`: none) | additive key |
| `check_night_orders_escalation` | the hook only | new |
| `_check_night_order_escalation` behaviour | `_emit_event` (every producer); BF-708 hosts in `test_bf897_*`, `test_ad1195_*`, `test_ad637d_*` (own copy), `test_ad680_*` (stubbed) | never raises; same signature |
| `trust_update` now matched | trust producer `consensus/trust.py:661,678` → the hook | pages on a crossing under Night Orders |

## 6. Tests

On each milestone's base, the new file fails as follows (measured by the orchestrator, 2026-10-27):
- M1: collection fails, so every case fails: `ImportError: cannot import name 'NIGHT_ORDER_TRIGGER_EVENTS' from 'probos.watch_rotation'` (1 error during collection).
- M2 (on the M1 stage): 10 of the 11 cases fail. D4 ×3 and D7 ×2 raise `AttributeError` (no `check_night_orders_escalation`). D1, D5 and D6 `[router]` raise `AttributeError: 'BridgeAlertService' object has no attribute 'add_alert'`. D6 `[bridge_alerts]` finds no gap logged. D2 fails because the old map keys `trust_change`, so a `trust_update` matches nothing (after A1, its first failing assertion is `call_count == 1`, which sees 0). **D3 passes on the base**, as a negative case must: the old hook also declines a refused build and a trigger the order does not list. It still bites: on the assembled tree, mutation R-2 (the `mgr.check_escalation` test dropped) fails it.

| ID | File | Case | Proves |
|---|---|---|---|
| T1 | triggers | `test_every_mapped_event_has_a_production_producer` | the map names producers (source premise) |
| T2 | triggers | `test_the_inert_triggers_still_have_no_producer` | guard: fails when a producer lands |
| T2b | triggers | `test_every_template_trigger_is_wired_or_known_inert` | template vocabulary |
| T3 | triggers | `test_build_failure_raises_unless_the_request_ran_nothing` ×6 | BF-897 parity |
| T3b | triggers | `test_trust_update_raises_trust_drop_once_as_it_crosses_the_floor` ×11 | crossing, bounds, bool/inf/NaN/str/None |
| T3c | triggers | `test_events_the_old_map_keyed_raise_nothing` ×4 | the old keys are gone |
| T4 | triggers | `test_status_names_the_triggers_that_can_never_fire` ×3; `test_a_custom_trigger_with_no_producer_is_reported_and_logged`; `test_wired_triggers_report_nothing_inert_and_log_nothing`; `test_inactive_status_is_unchanged` | disclosure |
| T5 | triggers | `test_the_console_says_which_triggers_never_fire`; `test_a_fully_wired_order_prints_no_inert_line` | operator surface |
| D1 | delivery | `test_a_build_failure_under_night_orders_pages_the_captain_and_is_still_dispatched` | **the crossing test:** real emit → real Night Orders → real service → real router → Ward Room thread and an `action_required` notification, with the listener and durable offer intact |
| D2 | delivery | `test_a_trust_crossing_pages_once` | the trust chain end to end. An update that stays below the floor matches nothing (D3). A second crossing inside the 300 s cooldown reaches the service, which declines it, so no delivery is scheduled and no second thread is created (R-7, R6) |
| D3 | delivery | `test_a_refused_build_or_an_unlisted_trigger_pages_nobody` | negative chain |
| D4 | delivery | `test_an_escalation_that_raises_never_costs_the_event_its_dispatch` ×3 | isolation |
| D5 | delivery | `test_outside_an_event_loop_nothing_is_paged_and_the_cooldown_is_not_spent` | D5 |
| D6 | delivery | `test_without_a_bridge_alert_path_the_event_is_dispatched_and_the_gap_is_logged` ×2 | partial hosts |
| D7 | delivery | `test_the_alert_is_deduplicated_per_subject_and_suppressible`; `test_a_trust_drop_alert_names_the_agent_and_its_scores` | service contract |

Expected new cases: triggers 32, delivery 11 (measured on the orchestrator's oracle `427546b8`; the table above sums to 32). Measured there before A1: M1's focused list 333 passed, M2's 736 passed, and the §10 census baseline over its seven files 627 passed. A1 changes D2's body, not the number of cases, so the expected counts stay delivery 11, M2 736 and census 627. The orchestrator re-measures.

## 7. The contract

### 7.1 `src/probos/watch_rotation.py` (M1)

**Pair 1.** SEARCH:
```
import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
```
REPLACE:
```
import asyncio
import logging
import math
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Any
```

**Pair 2.** SEARCH:
```
        "alert_boundary": "green",  # Don't even change to Yellow
    },
}


@dataclass
class NightOrders:
```
REPLACE:
```
        "alert_boundary": "green",  # Don't even change to Yellow
    },
}

# AD-1270 (#1324): emitted event type -> the Night Orders trigger it raises.
# Every key has a production producer: ``build_failure`` (``routers/build.py``)
# and ``trust_update`` (``consensus/trust.py``, which carries ``old_score`` and
# ``new_score``). The AD-471 map keyed ``trust_change``, ``alert_condition_change``
# and ``security_alert``, which nothing emits, and read a ``new_trust`` field
# nothing sends. ``red_alert`` and ``security_alert`` stay valid trigger names
# but have no producer on this build (nothing calls
# ``OntologyService.set_alert_condition``; nothing emits ``security_alert``),
# so status reports them as inert instead of promising a page that never comes.
NIGHT_ORDER_TRIGGER_EVENTS: Mapping[str, str] = MappingProxyType({
    "build_failure": "build_failure",
    "trust_update": "trust_drop",
})
WIRED_NIGHT_ORDER_TRIGGERS: frozenset[str] = frozenset(NIGHT_ORDER_TRIGGER_EVENTS.values())


def night_order_trigger(
    event_type: str,
    details: Mapping[str, Any] | None,
    *,
    trust_floor: float,
) -> str | None:
    """The Night Orders trigger an emitted event raises, or ``None`` (AD-471, AD-1270 #1324).

    ``build_failure`` raises ``build_failure`` unless the request ran nothing
    (BF-897's ``not_executed`` marker, exactly ``True``). ``trust_update`` raises
    ``trust_drop`` once, as the score crosses below ``trust_floor``
    (``old >= floor > new``); an update that stays below the floor, or that
    carries no finite numeric scores, raises nothing.
    """
    trigger = NIGHT_ORDER_TRIGGER_EVENTS.get(event_type)
    if trigger is None:
        return None
    data = details or {}
    if trigger == "build_failure" and data.get("not_executed") is True:
        return None  # BF-897: a refused request ran nothing, so there is no failure to escalate
    if trigger == "trust_drop":
        old, new = data.get("old_score"), data.get("new_score")
        if not (_is_score(old) and _is_score(new)):
            return None
        if not (old >= trust_floor > new):  # once, as the score crosses below the floor
            return None
    return trigger


def _is_score(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


@dataclass
class NightOrders:
```

**Pair 3.** SEARCH:
```
        logger.info(
            "Night Orders set (template=%s, ttl=%.1fh, triggers=%s)",
            template or "custom", ttl_hours, escalation_triggers or [],
        )
        return self._orders
```
REPLACE:
```
        logger.info(
            "Night Orders set (template=%s, ttl=%.1fh, triggers=%s)",
            template or "custom", ttl_hours, escalation_triggers or [],
        )
        inert = sorted(set(self._orders.escalation_triggers) - WIRED_NIGHT_ORDER_TRIGGERS)
        if inert:
            logger.warning(
                "AD-1270: Night Orders triggers %s have no producer on this build and will never page the Captain",
                inert,
            )
        return self._orders
```

**Pair 4.** SEARCH:
```
            "escalation_triggers": self._orders.escalation_triggers,
        }
```
REPLACE:
```
            "escalation_triggers": self._orders.escalation_triggers,
            "inert_triggers": sorted(set(self._orders.escalation_triggers) - WIRED_NIGHT_ORDER_TRIGGERS),
        }
```

### 7.2 `src/probos/experience/commands/commands_autonomous.py` (M1)

**Pair 1.** SEARCH:
```
            console.print(f"  Alert boundary: {status['alert_boundary']}")
```
REPLACE:
```
            console.print(f"  Alert boundary: {status['alert_boundary']}")
            triggers = status["escalation_triggers"]
            console.print(f"  Escalates on: {', '.join(triggers) if triggers else 'nothing'}")
            if status["inert_triggers"]:
                console.print(f"  [yellow]Never fires on this build: {', '.join(status['inert_triggers'])}[/yellow]")
```

**Pair 2.** SEARCH:
```
        console.print(f"  TTL: {ttl}h")
```
REPLACE:
```
        console.print(f"  TTL: {ttl}h")
        inert = rt._night_orders_mgr.get_status()["inert_triggers"]
        if inert:
            console.print(f"  [yellow]Never fires on this build: {', '.join(inert)}[/yellow]")
```

### 7.3 New file: `tests/test_ad1270_night_orders_triggers.py` (M1)

```python
"""AD-1270 (#1324): Night Orders triggers name only events something emits (M1).

The trigger rule (``watch_rotation.night_order_trigger``), the inert-trigger
disclosure in Night Orders status, and the console's report of it.
"""
from __future__ import annotations

import logging
import math
import re
from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from rich.console import Console

import probos
from probos.config import TRUST_FLOOR_CONN
from probos.events import EventType
from probos.experience.commands import commands_autonomous
from probos.runtime import ProbOSRuntime
from probos.watch_rotation import (
    NIGHT_ORDER_TEMPLATES,
    NIGHT_ORDER_TRIGGER_EVENTS,
    WIRED_NIGHT_ORDER_TRIGGERS,
    NightOrdersManager,
    night_order_trigger,
)

_SRC = Path(probos.__file__).resolve().parent
_F = TRUST_FLOOR_CONN
_INERT = {"red_alert", "security_alert"}
_LOGGER = "probos.watch_rotation"


def _trigger(event_type: str, details: dict[str, Any] | None) -> str | None:
    return night_order_trigger(event_type, details, trust_floor=_F)


def _source(*parts: str) -> str:
    return _SRC.joinpath(*parts).read_text(encoding="utf-8")


# --- T1, T2: the map names producers, and only producers ---------------------


def test_every_mapped_event_has_a_production_producer() -> None:
    assert set(NIGHT_ORDER_TRIGGER_EVENTS) == {"build_failure", "trust_update"}
    assert EventType("build_failure") is EventType.BUILD_FAILURE
    assert EventType("trust_update") is EventType.TRUST_UPDATE
    assert "emit_event(EventType.BUILD_FAILURE, {" in _source("routers", "build.py")
    trust = _source("consensus", "trust.py")
    assert 'emissions.append(("trust_update", {' in trust
    assert '"new_score": new_score,' in trust


def test_the_inert_triggers_still_have_no_producer() -> None:
    """If this fails, a producer exists now: map it in NIGHT_ORDER_TRIGGER_EVENTS."""
    values = {m.value for m in EventType}
    assert values.isdisjoint({"trust_change", "alert_condition_change", "security_alert", "red_alert"})
    texts = {p.relative_to(_SRC).as_posix(): p.read_text(encoding="utf-8") for p in _SRC.rglob("*.py")}
    assert [p for p, t in texts.items() if re.search(r"\.set_alert_condition\(", t)] == []
    assert [p for p, t in texts.items() if re.search(r"""emit_event\w*\(\s*["']security_alert""", t)] == []


def test_every_template_trigger_is_wired_or_known_inert() -> None:
    names = {t for tpl in NIGHT_ORDER_TEMPLATES.values() for t in tpl["escalation_triggers"]}
    assert WIRED_NIGHT_ORDER_TRIGGERS == {"build_failure", "trust_drop"}
    assert names - WIRED_NIGHT_ORDER_TRIGGERS == _INERT


# --- T3: the rule --------------------------------------------------------------


@pytest.mark.parametrize(
    ("details", "expected"),
    [
        (None, "build_failure"),
        ({}, "build_failure"),
        ({"not_executed": True}, None),
        ({"not_executed": False}, "build_failure"),
        ({"not_executed": "true"}, "build_failure"),
        ({"not_executed": 1}, "build_failure"),
    ],
    ids=["none", "absent", "refused", "false", "string-true", "int-one"],
)
def test_build_failure_raises_unless_the_request_ran_nothing(details: Any, expected: str | None) -> None:
    assert _trigger("build_failure", details) == expected


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        (_F + 0.1, _F - 0.1, "trust_drop"),
        (_F, _F - 0.01, "trust_drop"),
        (_F - 0.01, _F - 0.1, None),
        (_F + 0.1, _F, None),
        (_F - 0.1, _F + 0.1, None),
        (_F - 0.1, _F - 0.1, None),
        (math.inf, _F - 0.1, None),
        (_F + 0.1, math.nan, None),
        (True, False, None),
        ("0.7", "0.5", None),
        (None, _F - 0.1, None),
    ],
    ids=["crosses", "from-floor", "already-below", "lands-on-floor", "rises", "floor-hit",
         "inf", "nan", "bool", "str", "missing"],
)
def test_trust_update_raises_trust_drop_once_as_it_crosses_the_floor(old: Any, new: Any, expected: str | None) -> None:
    assert _trigger("trust_update", {"agent_id": "a1", "old_score": old, "new_score": new}) == expected


@pytest.mark.parametrize("event_type", ["trust_change", "alert_condition_change", "security_alert", "bridge_alert"])
def test_events_the_old_map_keyed_raise_nothing(event_type: str) -> None:
    assert _trigger(event_type, {"new_trust": 0.0, "new_level": "red", "old_score": 0.9, "new_score": 0.1}) is None


# --- T4: status ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("template", "inert"),
    [("maintenance", ["security_alert"]), ("build", ["security_alert"]), ("quiet", ["red_alert", "security_alert"])],
)
def test_status_names_the_triggers_that_can_never_fire(template: str, inert: list[str]) -> None:
    mgr = NightOrdersManager()
    mgr.set_night_orders(instructions=[], template=template)
    assert mgr.get_status()["inert_triggers"] == inert


def test_a_custom_trigger_with_no_producer_is_reported_and_logged(caplog: pytest.LogCaptureFixture) -> None:
    mgr = NightOrdersManager()
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        mgr.set_night_orders(instructions=[], escalation_triggers=["build_failure", "trust_drop", "typo"])
    status = mgr.get_status()
    assert status["escalation_triggers"] == ["build_failure", "trust_drop", "typo"]
    assert status["inert_triggers"] == ["typo"]
    assert any("never page the Captain" in r.getMessage() and "typo" in r.getMessage() for r in caplog.records)


def test_wired_triggers_report_nothing_inert_and_log_nothing(caplog: pytest.LogCaptureFixture) -> None:
    mgr = NightOrdersManager()
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        mgr.set_night_orders(instructions=[], escalation_triggers=["build_failure", "trust_drop"])
    assert mgr.get_status()["inert_triggers"] == []
    assert not [r for r in caplog.records if "never page the Captain" in r.getMessage()]


def test_inactive_status_is_unchanged() -> None:
    assert NightOrdersManager().get_status() == {"active": False}


# --- T5: the console ---------------------------------------------------------------


def _console() -> Console:
    return Console(file=StringIO(), force_terminal=False, width=200)


def _out(console: Console) -> str:
    console.file.seek(0)
    return console.file.read()


def _runtime() -> Any:
    rt = MagicMock(spec=ProbOSRuntime)
    rt.conn_manager = None
    rt._night_orders_mgr = NightOrdersManager()
    return rt


@pytest.mark.asyncio
async def test_the_console_says_which_triggers_never_fire() -> None:
    rt = _runtime()
    set_console = _console()
    await commands_autonomous.cmd_night_orders(rt, set_console, "quiet")
    assert "Never fires on this build: red_alert, security_alert" in _out(set_console)
    status_console = _console()
    await commands_autonomous.cmd_night_orders(rt, status_console, "status")
    text = _out(status_console)
    assert "Escalates on: red_alert, security_alert" in text
    assert "Never fires on this build: red_alert, security_alert" in text


@pytest.mark.asyncio
async def test_a_fully_wired_order_prints_no_inert_line() -> None:
    rt = _runtime()
    rt._night_orders_mgr.set_night_orders([], escalation_triggers=["build_failure"])
    console = _console()
    await commands_autonomous.cmd_night_orders(rt, console, "status")
    text = _out(console)
    assert "Escalates on: build_failure" in text
    assert "Never fires" not in text
```

### 7.4 `tests/test_autonomous_operations.py` (M1)

**Pair 1.** SEARCH:
```
from probos.watch_rotation import (
    NightOrders,
    NightOrdersManager,
    WatchManager,
    WatchType,
    NIGHT_ORDER_TEMPLATES,
)
```
REPLACE:
```
from probos.config import TRUST_FLOOR_CONN
from probos.watch_rotation import (
    NightOrders,
    NightOrdersManager,
    WatchManager,
    WatchType,
    NIGHT_ORDER_TEMPLATES,
    night_order_trigger,
)
```

**Pair 2.** SEARCH:
```
    def test_night_orders_escalation_trust_drop(self):
        """Set Night Orders with trust_drop escalation. Verify bridge alert on low trust."""
        rt = MagicMock(spec=ProbOSRuntime)
        night_mgr = NightOrdersManager()
        night_mgr.set_night_orders(
            instructions=[],
            escalation_triggers=["trust_drop"],
        )
        rt._night_orders_mgr = night_mgr
        rt.conn_manager = ConnManager()

        # Mock bridge alerts
        rt.bridge_alerts = MagicMock(spec=BridgeAlertService)

        # Simulate the escalation check
        # Test the escalation logic directly on the manager
        assert night_mgr.check_escalation("trust_drop") is True

    def test_night_orders_escalation_ignored_above_floor(self):
        """Trust above floor (0.8) does not escalate."""
        night_mgr = NightOrdersManager()
        night_mgr.set_night_orders(
            instructions=[],
            escalation_triggers=["trust_drop"],
        )

        # Simulate the runtime check logic inline
        details = {"new_trust": 0.8}
        trigger = "trust_drop"

        # The runtime's _check_night_order_escalation would return early
        # because new_trust >= 0.6. Let's verify the logic:
        new_trust = details.get("new_trust", 1.0)
        should_skip = new_trust >= 0.6
        assert should_skip is True  # Would not reach check_escalation
```
REPLACE:
```
    def test_night_orders_escalation_trust_drop(self):
        """A trust_update that crosses below the conn floor raises trust_drop under Night Orders."""
        # AD-1270 (#1324): this test checked only check_escalation and named a
        # bridge alert it never exercised; it now calls the production rule with
        # the producer's own fields (consensus/trust.py). The chain is
        # tests/test_ad1270_night_orders_delivery.py.
        night_mgr = NightOrdersManager()
        night_mgr.set_night_orders(instructions=[], escalation_triggers=["trust_drop"])
        trigger = night_order_trigger(
            "trust_update", {"old_score": 0.7, "new_score": 0.5}, trust_floor=TRUST_FLOOR_CONN,
        )
        assert trigger == "trust_drop"
        assert night_mgr.check_escalation(trigger) is True

    def test_night_orders_escalation_ignored_above_floor(self):
        """A trust_update that stays above the conn floor raises nothing."""
        # AD-1270 (#1324): this test re-implemented the old inline rule on a
        # ``new_trust`` field no producer sends, so it pinned the defect; it now
        # calls the production rule.
        assert night_order_trigger(
            "trust_update", {"old_score": 0.9, "new_score": 0.8}, trust_floor=TRUST_FLOOR_CONN,
        ) is None
```

(After this pair `MagicMock`, `ConnManager`, `BridgeAlertService` and `ProbOSRuntime` are still used elsewhere in the file, at lines 8, 16, 17 and 337-417. Leave the imports alone.)

### 7.5 `src/probos/bridge_alerts.py` (M2)

**Pair 1.** SEARCH:
```
logger = logging.getLogger(__name__)


class AlertSeverity(str, Enum):
```
REPLACE:
```
logger = logging.getLogger(__name__)

# AD-1270 (#1324): what of an event's payload a Night Orders alert may carry.
_NIGHT_ORDERS_SUBJECT_MAX = 64
_NIGHT_ORDERS_DETAIL_MAX = 500


def _score_text(value: Any) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:.2f}"
    return "?"


class AlertSeverity(str, Enum):
```

**Pair 2.** SEARCH:
```
    The service itself does NOT post to the Ward Room — it returns BridgeAlert
    objects that the runtime delivers via _deliver_bridge_alert().
```
REPLACE:
```
    The service itself does NOT post to the Ward Room — it returns BridgeAlert
    objects that the caller delivers via ``WardRoomRouter.deliver_bridge_alert``.
```

**Pair 3.** SEARCH:
```
        self._record(a)
        return a

    def check_emergent_patterns(self, patterns: list) -> list[BridgeAlert]:
```
REPLACE:
```
        self._record(a)
        return a

    def check_night_orders_escalation(
        self, trigger: str, details: dict[str, Any],
    ) -> BridgeAlert | None:
        """AD-471 / AD-1270 (#1324): the alert that pages the Captain under Night Orders.

        ALERT severity, so delivery posts to the ship channel and raises an
        ``action_required`` notification. Deduplicated per trigger and subject
        (the build id or the agent id) and suppressible like every alert (AD-580).
        Only the subject, the scores and a bounded message reach the text.
        """
        subject = str(details.get("build_id") or details.get("agent_id") or "")[:_NIGHT_ORDERS_SUBJECT_MAX]
        key = f"night_orders:{trigger}:{subject}" if subject else f"night_orders:{trigger}"
        if not self._should_emit(key):  # AD-580: cooldown, dismiss, resolve and mute apply
            return None
        if trigger == "trust_drop":
            detail = (
                f"Agent {subject or 'unknown'} fell below the conn trust floor "
                f"({_score_text(details.get('old_score'))} \u2192 {_score_text(details.get('new_score'))}) "
                "while Night Orders were set."
            )
        else:
            message = str(details.get("message") or details.get("error") or "no detail")[:_NIGHT_ORDERS_DETAIL_MAX]
            detail = f"Night Orders escalation ({trigger}): {message}"
        a = BridgeAlert(
            id=str(uuid.uuid4()), severity=AlertSeverity.ALERT, source="night_orders",
            alert_type=f"night_orders_{trigger}",
            title=f"Night Orders escalation: {trigger}",
            detail=detail, department=None, dedup_key=key,
            related_agent_id=(subject or None) if trigger == "trust_drop" else None,
        )
        self._record(a)
        return a

    def check_emergent_patterns(self, patterns: list) -> list[BridgeAlert]:
```

### 7.6 `src/probos/runtime.py` (M2)

**Pair U1 (`src/probos/runtime.py`).** SEARCH:
```
    def _check_night_order_escalation(self, event_type: str, details: dict[str, Any] | None = None) -> None:
        """Check if a runtime event should trigger Night Orders escalation.

        Called from event emission points (trust changes, alert changes,
        build results). If the event matches a Night Orders escalation trigger,
        fires a bridge alert to wake the Captain.
        """
        if not hasattr(self, '_night_orders_mgr') or not self._night_orders_mgr:
            return
        if not self._night_orders_mgr.active:
            return

        # Map runtime events to Night Orders trigger names
        trigger_map = {
            "trust_change": "trust_drop",
            "alert_condition_change": "red_alert",
            "build_failure": "build_failure",
            "security_alert": "security_alert",
        }
        trigger = trigger_map.get(event_type)
        if not trigger:
            return

        # Additional condition checks
        if trigger == "build_failure" and details and details.get("not_executed") is True:
            return  # BF-897: a refused request ran nothing, so there is no failure to escalate
        if trigger == "trust_drop" and details:
            # Only escalate if trust dropped below floor
            new_trust = details.get("new_trust", 1.0)
            if new_trust >= TRUST_FLOOR_CONN:  # Not below floor
                return
        if trigger == "red_alert" and details:
            new_level = details.get("new_level", "")
            if new_level.lower() != "red":
                return

        # Check against Night Orders escalation triggers
        if self._night_orders_mgr.check_escalation(trigger):
            # Also notify conn manager
            if self.conn_manager:
                self.conn_manager.check_escalation(trigger, details)
            # Fire bridge alert
            if hasattr(self, 'bridge_alerts') and self.bridge_alerts:
                self.bridge_alerts.add_alert(
                    severity="critical",
                    title=f"Night Orders escalation: {trigger}",
                    source="night_orders",
                    details=details or {},
                )
            logger.warning("Night Orders escalation triggered: %s", trigger)
```
REPLACE:
```
    def _check_night_order_escalation(self, event_type: str, details: dict[str, Any] | None = None) -> None:
        """Page the Captain when an emitted event matches an active Night Orders trigger (AD-471).

        AD-1270 (#1324): ``_emit_event`` calls this before durable offer and
        dispatch, so it never raises: a failure is logged and the event still
        reaches its durable row, its NATS publish and its listeners. The trigger
        rule lives beside the templates (``watch_rotation.night_order_trigger``);
        ``BridgeAlertService.check_night_orders_escalation`` builds the alert
        (deduplicated, and suppressible by the Captain, AD-580) and
        ``WardRoomRouter.deliver_bridge_alert`` delivers it, as every other bridge
        alert is delivered. A borrowed-method host (BF-708) may lack any
        collaborator, so each is read with ``getattr``.
        """
        try:
            mgr = getattr(self, "_night_orders_mgr", None)
            if not mgr or not mgr.active:
                return
            from probos.watch_rotation import night_order_trigger

            trigger = night_order_trigger(event_type, details, trust_floor=TRUST_FLOOR_CONN)
            if trigger is None or not mgr.check_escalation(trigger):
                return
            logger.warning("Night Orders escalation triggered: %s", trigger)
            conn = getattr(self, "conn_manager", None)
            if conn:
                conn.check_escalation(trigger, details)
            alerts = getattr(self, "bridge_alerts", None)
            router = getattr(self, "ward_room_router", None)
            if not alerts or not router:
                logger.warning(
                    "AD-1270: Night Orders escalation %s has no bridge-alert path; the Captain is not paged",
                    trigger,
                )
                return
            loop = asyncio.get_running_loop()  # before the alert is built, so an undeliverable alert never spends its cooldown
            tasks = self._event_listener_tasks
            alert = alerts.check_night_orders_escalation(trigger, details or {})
            if alert is None:
                return  # inside the cooldown, or suppressed by the Captain (AD-580)
            task = loop.create_task(router.deliver_bridge_alert(alert), name="night-orders-escalation")
            tasks.add(task)
            task.add_done_callback(tasks.discard)
        except Exception:  # AD-1270 (#1324): log and degrade; the event still reaches durable offer and dispatch
            logger.warning(
                "AD-1270: Night Orders escalation failed for event %s; the event is still dispatched",
                event_type,
                exc_info=True,
            )
```

(Leave the `_emit_event` comment at `runtime.py:1946-1948` as it is. It is still true, and D7 keeps the hook where it is.)

### 7.7 New file: `tests/test_ad1270_night_orders_delivery.py` (M2)

```python
"""AD-1270 (#1324): a Night Orders escalation pages the Captain through the real
bridge-alert path, and never costs the event its dispatch (M2).

Hosts are the BF-708 shape: the unmodified runtime emission methods on a
minimal object, with a real NightOrdersManager, BridgeAlertService and
WardRoomRouter (its Ward Room is an AsyncMock).
"""
from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.bridge_alerts import AlertSeverity, BridgeAlertService
from probos.config import TRUST_FLOOR_CONN, SystemConfig
from probos.events import EventType
from probos.runtime import ProbOSRuntime
from probos.ward_room_router import WardRoomRouter
from probos.watch_rotation import NightOrdersManager

_LOGGER = "probos.runtime"
_F = TRUST_FLOOR_CONN
_REAL = object()


class _Host:
    add_event_listener = ProbOSRuntime.add_event_listener
    emit_event = ProbOSRuntime.emit_event
    _emit_event = ProbOSRuntime._emit_event
    _emit_event_local = ProbOSRuntime._emit_event_local
    _check_night_order_escalation = ProbOSRuntime._check_night_order_escalation

    def __init__(self, *, template: str = "maintenance", bridge_alerts: Any = _REAL, router: Any = _REAL) -> None:
        self._event_listeners: list[Any] = []
        self._live_event_listeners: list[Any] = []
        self._event_listener_tasks: set[asyncio.Task[Any]] = set()
        self._nats_publish_tasks: set[asyncio.Task[Any]] = set()
        self._nats_events_wired = False
        self.nats_bus = None
        self.offers: list[dict[str, Any]] = []
        self.durable_events = SimpleNamespace(offer=self.offers.append)
        self.conn_manager = MagicMock()
        self._night_orders_mgr = NightOrdersManager()
        self._night_orders_mgr.set_night_orders([], template=template)
        self.bridge_alerts = BridgeAlertService() if bridge_alerts is _REAL else bridge_alerts
        self.wr = AsyncMock()
        self.wr.get_channel_by_type.return_value = SimpleNamespace(id="ch-ship")
        self.notify = MagicMock()
        self.ward_room_router = (
            WardRoomRouter(
                ward_room=self.wr, registry=MagicMock(), intent_bus=AsyncMock(),
                trust_network=MagicMock(), ontology=None, callsign_registry=MagicMock(),
                episodic_memory=None, event_emitter=MagicMock(), event_log=AsyncMock(),
                config=SystemConfig(), notify_fn=self.notify,
            )
            if router is _REAL else router
        )
        self.events: list[dict[str, Any]] = []
        self.add_event_listener(self.events.append)

    async def settle(self) -> None:
        pending = list(self._event_listener_tasks)
        if pending:
            await asyncio.gather(*pending)


def _messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records]


@pytest.mark.asyncio
async def test_a_build_failure_under_night_orders_pages_the_captain_and_is_still_dispatched() -> None:
    host = _Host()
    host.emit_event(EventType.BUILD_FAILURE, {"build_id": "b9", "message": "Build failed: boom", "error": "boom"})
    assert len(host._event_listener_tasks) == 1  # the delivery is held, not fire-and-forget
    await host.settle()
    assert [e["type"] for e in host.events] == ["build_failure"]
    assert [e["type"] for e in host.offers] == ["build_failure"]
    host.conn_manager.check_escalation.assert_called_once()
    host.wr.create_thread.assert_awaited_once()
    kwargs = host.wr.create_thread.await_args.kwargs
    assert kwargs["channel_id"] == "ch-ship"
    assert kwargs["title"] == "[ALERT] Night Orders escalation: build_failure"
    assert "Build failed: boom" in kwargs["body"]
    host.notify.assert_called_once()
    assert host.notify.call_args.kwargs["notification_type"] == "action_required"


@pytest.mark.asyncio
async def test_a_trust_crossing_pages_once() -> None:
    host = _Host()
    host.emit_event(EventType.TRUST_UPDATE, {"agent_id": "a1", "old_score": _F + 0.1, "new_score": _F - 0.1})
    await host.settle()
    host.emit_event(EventType.TRUST_UPDATE, {"agent_id": "a1", "old_score": _F - 0.1, "new_score": _F - 0.2})
    await host.settle()
    assert host.conn_manager.check_escalation.call_count == 1  # staying below the floor is no crossing (D3)
    # A second crossing inside the 300 s cooldown matches; the service declines it (R6, AD-580).
    host.emit_event(EventType.TRUST_UPDATE, {"agent_id": "a1", "old_score": _F + 0.05, "new_score": _F - 0.05})
    assert host.conn_manager.check_escalation.call_count == 2
    assert [t for t in host._event_listener_tasks if not t.done()] == []  # a declined alert is never delivered
    await host.settle()
    assert len(host.events) == 3 and len(host.offers) == 3
    host.wr.create_thread.assert_awaited_once()
    assert host.wr.create_thread.await_args.kwargs["title"] == "[ALERT] Night Orders escalation: trust_drop"


@pytest.mark.asyncio
async def test_a_refused_build_or_an_unlisted_trigger_pages_nobody() -> None:
    refused = _Host()
    refused.emit_event(EventType.BUILD_FAILURE, {"build_id": "b1", "not_executed": True})
    unlisted = _Host(template="build")  # security_alert and trust_drop only
    unlisted.emit_event(EventType.BUILD_FAILURE, {"build_id": "b2", "message": "m"})
    for host in (refused, unlisted):
        await host.settle()
        assert len(host.events) == 1 and len(host.offers) == 1
        host.conn_manager.check_escalation.assert_not_called()
        host.wr.create_thread.assert_not_awaited()


@pytest.mark.parametrize("raiser", ["alerts", "orders", "conn"])
@pytest.mark.asyncio
async def test_an_escalation_that_raises_never_costs_the_event_its_dispatch(
    raiser: str, caplog: pytest.LogCaptureFixture,
) -> None:
    alerts = MagicMock(spec=BridgeAlertService)
    alerts.check_night_orders_escalation.side_effect = RuntimeError("boom")
    host = _Host(bridge_alerts=alerts if raiser == "alerts" else _REAL)
    if raiser == "orders":
        host._night_orders_mgr = MagicMock()
        host._night_orders_mgr.active = True
        host._night_orders_mgr.check_escalation.side_effect = RuntimeError("boom")
    if raiser == "conn":
        host.conn_manager.check_escalation.side_effect = RuntimeError("boom")
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        host.emit_event(EventType.BUILD_FAILURE, {"build_id": "b3", "message": "m"})
    await host.settle()
    assert len(host.events) == 1
    assert len(host.offers) == 1
    assert any("Night Orders escalation failed for event build_failure" in m for m in _messages(caplog))
    host.wr.create_thread.assert_not_awaited()


def test_outside_an_event_loop_nothing_is_paged_and_the_cooldown_is_not_spent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    host = _Host()
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        host.emit_event(EventType.BUILD_FAILURE, {"build_id": "b4", "message": "m"})
    assert len(host.events) == 1 and len(host.offers) == 1
    assert host._event_listener_tasks == set()
    assert any("Night Orders escalation failed for event build_failure" in m for m in _messages(caplog))
    assert host.bridge_alerts.check_night_orders_escalation("build_failure", {"build_id": "b4"}) is not None


@pytest.mark.parametrize("missing", ["bridge_alerts", "router"])
def test_without_a_bridge_alert_path_the_event_is_dispatched_and_the_gap_is_logged(
    missing: str, caplog: pytest.LogCaptureFixture,
) -> None:
    host = _Host(**{missing: None})
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        host.emit_event(EventType.BUILD_FAILURE, {"build_id": "b5", "message": "m"})
    assert len(host.events) == 1 and len(host.offers) == 1
    host.conn_manager.check_escalation.assert_called_once()
    assert any("has no bridge-alert path; the Captain is not paged" in m for m in _messages(caplog))


def test_the_alert_is_deduplicated_per_subject_and_suppressible() -> None:
    svc = BridgeAlertService()
    first = svc.check_night_orders_escalation("build_failure", {"build_id": "b1", "message": "x" * 900})
    assert first is not None
    assert first.severity is AlertSeverity.ALERT
    assert first.source == "night_orders"
    assert first.alert_type == "night_orders_build_failure"
    assert first.dedup_key == "night_orders:build_failure:b1"
    assert first.detail == "Night Orders escalation (build_failure): " + "x" * 500
    assert first.related_agent_id is None
    assert svc.check_night_orders_escalation("build_failure", {"build_id": "b1"}) is None
    assert svc.check_night_orders_escalation("build_failure", {"build_id": "b2"}) is not None
    svc.mute_alert("night_orders:build_failure:b3")
    assert svc.check_night_orders_escalation("build_failure", {"build_id": "b3"}) is None


def test_a_trust_drop_alert_names_the_agent_and_its_scores() -> None:
    svc = BridgeAlertService()
    a = svc.check_night_orders_escalation("trust_drop", {"agent_id": "a1", "old_score": 0.7, "new_score": 0.5})
    assert a is not None
    assert a.related_agent_id == "a1"
    assert a.dedup_key == "night_orders:trust_drop:a1"
    assert "(0.70 \u2192 0.50)" in a.detail
    b = svc.check_night_orders_escalation("build_failure", {})
    assert b is not None and b.dedup_key == "night_orders:build_failure"
```

## 8. Tracking (M3's commit)

`PROGRESS.md`. Re-anchor on S6's merge; the paragraph goes first.
**Pair U2 (`PROGRESS.md`).** SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**AD-1270 (2026-10-2X), #1324 Night Orders item -- Night Orders escalation, wired.** A runtime event matching an active Night Orders trigger now pages the Captain: an ALERT bridge alert posted to the ship channel with an `action_required` notification, built by `BridgeAlertService.check_night_orders_escalation` (deduplicated per trigger and build or agent; the Captain can dismiss or mute it, AD-580) and delivered by `WardRoomRouter.deliver_bridge_alert`. The hook used to call a `BridgeAlertService.add_alert` that does not exist, so a real build failure under Night Orders raised out of `_emit_event` before durable offer and dispatch and the event was lost (found by BF-897's review, #1559); the hook is now log-and-degrade and the event always reaches its durable row, its NATS publish and its listeners. Triggers are mapped only where something emits: `build_failure` (a refused request still escalates nothing, BF-897) and `trust_drop`, from `trust_update`, once as an agent's score crosses below the conn floor (the old `trust_change` key had no producer). `red_alert` and `security_alert` have no producer on this build; Night Orders status, `/night-orders` and a log line say so (`inert_triggers`). No schema, config field, event type or route. New: `tests/test_ad1270_night_orders_triggers.py`, `tests/test_ad1270_night_orders_delivery.py`. The contract is `prompts/ad-1270-night-orders-escalation.md`.

```

`DECISIONS.md`. Re-anchored by the orchestrator (2026-10-27): the file's recent entries are appended in date order after the latest one (AD-1341 S6) and ahead of the older newest-first block, so this entry goes there, before the heading of the entry that follows S6's, and not at the top of the Era V section as the Architect's draft had it.

**Pair U3 (`DECISIONS.md`).** SEARCH:
```
### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```
REPLACE:
```
### AD-1270 (#1324) -- Night Orders triggers are mapped only where a producer exists; the rest are reported as inert (2026-10-2X)

**Decision.** `watch_rotation.NIGHT_ORDER_TRIGGER_EVENTS` maps `build_failure` and `trust_update` (to `trust_drop`, on the crossing below the conn floor) only. `red_alert` (nothing calls `OntologyService.set_alert_condition`) and `security_alert` (no emitter; AD-455's monitor reports nothing in v1) remain valid names in the templates and are reported in `NightOrdersManager.get_status()["inert_triggers"]`. **Why.** A trigger with no producer is a promise to wake the Captain that cannot be kept; inventing producers is new capability under the pause. A guard test fails when a producer lands, so mapping it is one line. **Rejected.** Dropping the names from the templates (it loses the Captain's stated intent, and the names become live once a producer exists). Paging on every trust update below the floor (it would page repeatedly).

### Just culture for trust scoring: a design note for the next owner of earned agency (2026-10-17, recorded 2026-10-2X; #1569 comment 1)

- *Scope.* A design note; nothing under `src/` changes. Recorded at the Captain's request ("record this for whoever next touches earned agency or trust scoring") from the lessons-learned amendment to AD-1341 (#1569, first comment, 2026-10-17); follow-up #1690, entry (d).
- *The note (Captain).* Naval safety investigations are deliberately non-punitive and privileged, so that people report honestly. For ProbOS, an agent's self-reported error should cost little trust, or earn credit for candour; an error discovered after concealment should cost much more. Otherwise the trust model trains agents to hide mistakes, the Darwin Gödel Machine failure mode (`docs/research/darwin-godel-machine-absorption.md`).
- *Constraints for the owner (Architect).* Trust stays raw `(alpha, beta)`. Whether a report was made before discovery must come from a service record (who reported first, and when), never from the agent's own claim; otherwise candour credit becomes a new reward to game.
- *Not decided.* The weights, and whether a self-report is neutral or a credit.

### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```

Parent checklist (the orchestrator, on #1324): tick the Night Orders item with the commit and receipt.

## 9. What this does NOT change

- No producer for `red_alert` or `security_alert`, and no alert-condition writer (R1).
- The `ConnManager` escalation list (`conn.py:54-56`, `:192-202`) and the work-item templates' `escalation_triggers` metadata (`workforce.py:804,822,840`), which do not use this map (R2).
- `deliver_bridge_alert`, the Ward Room, notifications, AD-580 suppression semantics.
- `_emit_event`'s order (the hook still comes first), durable routing (AD-1195), NATS.
- `TrustUpdateEvent` (still never built; the producer emits the string form).
- No config field, event type, route, HXI view or schema.

## 10. Mutation rows (26 rows; one campaign on the assembled tree after an unmutated baseline of both new files passes)

| # | M | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|---|
| W-1 | M1 | `watch_rotation.py` | `if trigger == "build_failure" and data.get("not_executed") is True:` | `if trigger == "build_failure" and data.get("not_executed"):` | `test_build_failure_raises_unless_the_request_ran_nothing[string-true]`, `test_build_failure_raises_unless_the_request_ran_nothing[int-one]` |
| W-2 | M1 | `watch_rotation.py` | `if not (old >= trust_floor > new):  # once, as the score crosses below the floor` | `if not (new < trust_floor):` | `test_trust_update_raises_trust_drop_once_as_it_crosses_the_floor[already-below]`, `test_trust_update_raises_trust_drop_once_as_it_crosses_the_floor[floor-hit]`, `test_a_trust_crossing_pages_once` (A1: the stay-below update now matches, so `call_count == 1` sees 2) |
| W-3 | M1 | `watch_rotation.py` | `if not (old >= trust_floor > new):  # once, as the score crosses below the floor` | `if not (old > trust_floor > new):` | `test_trust_update_raises_trust_drop_once_as_it_crosses_the_floor[from-floor]` |
| W-4 | M1 | `watch_rotation.py` | `if not (old >= trust_floor > new):  # once, as the score crosses below the floor` | `if not (old >= trust_floor >= new):` | `test_trust_update_raises_trust_drop_once_as_it_crosses_the_floor[lands-on-floor]` |
| W-5 | M1 | `watch_rotation.py` | `return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)` | `return isinstance(value, (int, float)) and math.isfinite(value)` | `test_trust_update_raises_trust_drop_once_as_it_crosses_the_floor[bool]` |
| W-6 | M1 | `watch_rotation.py` | `return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)` | `return isinstance(value, (int, float)) and not isinstance(value, bool)` | `test_trust_update_raises_trust_drop_once_as_it_crosses_the_floor[inf]` |
| W-7 | M1 | `watch_rotation.py` | `"trust_update": "trust_drop",` | `"trust_change": "trust_drop",` | `test_every_mapped_event_has_a_production_producer`, `test_trust_update_raises_trust_drop_once_as_it_crosses_the_floor[crosses]` |
| W-8 | M1 | `watch_rotation.py` | `"inert_triggers": sorted(set(self._orders.escalation_triggers) - WIRED_NIGHT_ORDER_TRIGGERS),` | `"inert_triggers": [],` | `test_status_names_the_triggers_that_can_never_fire` |
| W-9 | M1 | `watch_rotation.py` | `if inert:` | `if False:` | `test_a_custom_trigger_with_no_producer_is_reported_and_logged` |
| W-10 | M1 | `watch_rotation.py` | `if not (_is_score(old) and _is_score(new)):` | `if False:` | `test_trust_update_raises_trust_drop_once_as_it_crosses_the_floor[str]`, `test_trust_update_raises_trust_drop_once_as_it_crosses_the_floor[missing]`, `test_trust_update_raises_trust_drop_once_as_it_crosses_the_floor[bool]`, `test_trust_update_raises_trust_drop_once_as_it_crosses_the_floor[inf]` |
| C-1 | M1 | `commands_autonomous.py` | `if status["inert_triggers"]:` | `if False:` | `test_the_console_says_which_triggers_never_fire` |
| C-2 | M1 | `commands_autonomous.py` | `inert = rt._night_orders_mgr.get_status()["inert_triggers"]` | `inert = []` | `test_the_console_says_which_triggers_never_fire` |
| B-1 | M2 | `bridge_alerts.py` | `if not self._should_emit(key):  # AD-580: cooldown, dismiss, resolve and mute apply` | `if False:` | `test_the_alert_is_deduplicated_per_subject_and_suppressible`, `test_a_trust_crossing_pages_once` (A1: the second crossing inside the cooldown is no longer declined, so a delivery is scheduled) |
| B-2 | M2 | `bridge_alerts.py` | `key = f"night_orders:{trigger}:{subject}" if subject else f"night_orders:{trigger}"` | `key = f"night_orders:{trigger}"` | `test_the_alert_is_deduplicated_per_subject_and_suppressible` |
| B-3 | M2 | `bridge_alerts.py` | `id=str(uuid.uuid4()), severity=AlertSeverity.ALERT, source="night_orders",` | `id=str(uuid.uuid4()), severity=AlertSeverity.ADVISORY, source="night_orders",` | `test_a_build_failure_under_night_orders_pages_the_captain_and_is_still_dispatched`, `test_the_alert_is_deduplicated_per_subject_and_suppressible` |
| B-4 | M2 | `bridge_alerts.py` | `message = str(details.get("message") or details.get("error") or "no detail")[:_NIGHT_ORDERS_DETAIL_MAX]` | `message = str(details.get("message") or details.get("error") or "no detail")` | `test_the_alert_is_deduplicated_per_subject_and_suppressible` |
| B-5 | M2 | `bridge_alerts.py` | `related_agent_id=(subject or None) if trigger == "trust_drop" else None,` | `related_agent_id=None,` | `test_a_trust_drop_alert_names_the_agent_and_its_scores` |
| R-1 | M2 | `runtime.py` | `except Exception:  # AD-1270 (#1324): log and degrade; the event still reaches durable offer and dispatch` | `except ZeroDivisionError:  # AD-1270 (#1324): log and degrade; the event still reaches durable offer and dispatch` | `test_an_escalation_that_raises_never_costs_the_event_its_dispatch`, `test_outside_an_event_loop_nothing_is_paged_and_the_cooldown_is_not_spent` |
| R-2 | M2 | `runtime.py` | `if trigger is None or not mgr.check_escalation(trigger):` | `if trigger is None:` | `test_a_refused_build_or_an_unlisted_trigger_pages_nobody` |
| R-3 | M2 | `runtime.py` | `loop = asyncio.get_running_loop()  # before the alert is built, so an undeliverable alert never spends its cooldown` | `loop = None` | `test_outside_an_event_loop_nothing_is_paged_and_the_cooldown_is_not_spent`, `test_a_build_failure_under_night_orders_pages_the_captain_and_is_still_dispatched` |
| R-4 | M2 | `runtime.py` | `tasks.add(task)` | `pass` | `test_a_build_failure_under_night_orders_pages_the_captain_and_is_still_dispatched`, `test_a_trust_crossing_pages_once` |
| R-5 | M2 | `runtime.py` | `if not alerts or not router:` | `if not alerts:` | `test_without_a_bridge_alert_path_the_event_is_dispatched_and_the_gap_is_logged[router]` |
| R-6 | M2 | `runtime.py` | `conn.check_escalation(trigger, details)` | `pass` | `test_a_build_failure_under_night_orders_pages_the_captain_and_is_still_dispatched`, `test_an_unmarked_build_failure_still_escalates` (BF-897's file) |
| R-7 | M2 | `runtime.py` | `if alert is None:` | `if False:` | `test_a_trust_crossing_pages_once` (A1: the second crossing inside the cooldown reaches this line with `None`; under the mutant a `deliver_bridge_alert(None)` task is scheduled, so the unfinished-task assertion fails) |
| R-8 | M2 | `runtime.py` | `trigger = night_order_trigger(event_type, details, trust_floor=TRUST_FLOOR_CONN)` | `trigger = night_order_trigger(event_type, details, trust_floor=0.0)` | `test_a_trust_crossing_pages_once` |
| R-9 | M2 | `runtime.py` | `if not mgr or not mgr.active:` | `if not mgr:` | none: **equivalent mutant**. An inactive `NightOrdersManager` already returns False from `check_escalation` (`watch_rotation.py:419-423`, re-reading the idempotent `active` property, `:308-314`), so the mutant only adds a call to the pure `night_order_trigger`. It is observable only with a manager whose `active` is false while `check_escalation` is true, which the production class cannot be. The census runs it on all files and reports it survived; record it as equivalent, with no test |

Each line occurs once in its file after §7. Lines with no row, and why: the docstrings; `_score_text`'s `"?"` branch (display only); the `"nothing"` arm of `Escalates on` (display only).

Killed-by cells are census-ready. They name full pytest function names in code spans, with a single parametrised case written `name[id]`. A cell names no function only for R-9, the equivalent mutant. Census of record: orchestrator, 2026-10-27, on `427546b8`: 24 killed, 2 survived (R-7, R-9), baseline 627 passed. A1 changes only D2, so after A1 rerun the unmutated baseline and the rows that claim D2: W-2, B-1, R-4, R-7, R-8. Expected: 25 killed, R-9 survived and recorded as equivalent.

## 11. Verified Against Codebase (2026-10-27, on `a2390998`)

```
Grep "_check_night_order_escalation|add_alert|deliver_bridge_alert" src
  runtime.py:1949 (call), :2137 (def), :2180 (add_alert, its only occurrence)
  ward_room_router.py:1181  async def deliver_bridge_alert(self, alert: Any) -> None:
  bridge_alerts.py:51       objects that the runtime delivers via _deliver_bridge_alert().
Read runtime.py:1930-1975, 1977-2016, 2029-2069, 2137-2186, 3886-3944, 1432-1438, 1512-1532
Grep "^logger = " runtime.py -> :229; watch_rotation.py:22; bridge_alerts.py:21
Grep "TRUST_FLOOR_CONN" runtime.py -> :111 import; config.py:220 TRUST_FLOOR_CONN = 0.6
Grep '"trust_update"' src -> consensus/trust.py:492, :534; payload Read :480-541, :655-678
Grep "BUILD_FAILURE" src -> routers/build.py:85,366,410,482,489; events.py:37
Read bridge_alerts.py:1-120 (AlertSeverity, BridgeAlert fields, _should_emit, _record), :310-349 (check_trust_change), :159 mute_alert
Read ward_room_router.py:43-93 (constructor: config.ward_room read at :79), :1181-1227
Read watch_rotation.py:14-20, :178-366
Read commands_autonomous.py:118-184
Read tests/test_autonomous_operations.py:18-24, :405-439, :468-483
Read tests/test_bf897_build_pipeline_scale_and_checkout.py:898-966
Read tests/test_ad1195_durable_event_seam.py:66-82; Grep tests/test_ad637d_system_events_nats.py:25,39,344; tests/test_ad680_public_runtime_api.py:76
Read tests/test_commands_autonomous.py:1-34 (mocks return {"active": False} only)
Read docs/development/architecture-baseline.yaml:331-339; scripts/check_architecture_principles.py:80-113, :187-188, :930-944
Read startup/finalize.py:4210-4224
```

## Absence Verified (2026-10-27)

| ID | Claim | Run | Found | Holds |
|---|---|---|---|---|
| AV1 | No `add_alert` method; no `_deliver_bridge_alert` on the runtime | Grep `add_alert\|deliver_bridge_alert` in `src` | only the call at `runtime.py:2180`; `deliver_bridge_alert` methods are only on `WardRoomRouter`; `_deliver_bridge_alert_fn` in `dream_adapter.py` is a parameter | yes |
| AV2 | No producer for `trust_change`, `alert_condition_change`, `security_alert` | Grep `"(trust_change\|alert_condition_change\|security_alert\|build_failure)"` in `src` | the map, lists and scorers only; emitters only for `build_failure` | yes |
| AV3 | Nothing changes the alert condition; no security_alert EventType | Grep `set_alert_condition\(` in `src`; Grep `^    [A-Z_]*(ALERT\|TRUST\|SECURITY\|CONDITION)[A-Z_]* = ` in `events.py` | the def only; members `TRUST_UPDATE, EXOGENOUS_ALERT, BRIDGE_ALERT, TRUST_CASCADE_WARNING, TRUST_INTEGRITY_VIOLATION, SECURITY_INPUT_REJECTED, TIERED_TRUST_INITIALIZED` | yes |
| AV4 | No test source-scans the replaced lines | Grep `trigger_map\|Night Orders escalation\|_deliver_bridge_alert\(\)\|inert_triggers\|night_order_trigger` in `tests` | only comments/docstrings in `test_ad637d_system_events_nats.py:38,233` | yes |
| AV5 | No HXI consumer of Night Orders status keys | Grep `escalation_triggers\|night.orders` in `ui/src` | none | yes |
| AV6 | Night Orders is not a P0 seam | Grep `(?i)night\|bridge_alert\|_emit_event\|escalation` in `docs/development/seams/p0-manifest.yaml` | none | yes |

## Not verified (the orchestrator verifies by running)

1. `SystemConfig()` constructs with no arguments in the test (the zero-config standing rule; not run).
2. `MagicMock(spec=BridgeAlertService)` exposes `check_night_orders_escalation` after 7.5 (true for `spec=` of a class; not run).
3. The focused lists' measured counts.

## 12. Deterministic gate checks, resolved up front

- `check_architecture_principles.py --check`: the new `create_task` result is stored, not a bare expression, so no `unowned-task` row. `BridgeAlertService`'s srp-size row stores triggers, not magnitudes, so it is unchanged. `watch_rotation` is unranked. No new top-level module.
- No config field, so neither `check_config_readers.py` nor `config-reference.md` changes.

## 13. Prior Art and Blind Spots

- **External prior art:** skipped. This is ProbOS-specific plumbing; observer isolation in event dispatch is the repo's own BF-639 pattern, reused here. `docs/research/reference-projects.md` was not consulted, because no external search was made.
- **Internal:** BF-639 (listener isolation), BF-708 (borrowed-method hosts), BF-897 (`not_executed`), AD-580 (suppression), AD-1195 (durable offer). All absorbed.
- **Blind spots found and handled:** the real trust event name (`trust_update`, `old_score`/`new_score`); repeated pages below the floor (D3); undeliverable alerts using up their cooldown (D5); custom typo triggers (reported as inert); a dedup key built from unbounded payload (capped at 64 and 500 characters).
- **Blind spots recorded, not fixed:** R1 to R6.

## 14. Diff Reviewer: properties to verify

**M1:**
1. `night_order_trigger` returns `build_failure` for `build_failure` unless `not_executed is True`, and `trust_drop` for `trust_update` only when finite non-bool numeric scores satisfy `old >= floor > new`. Everything else returns `None`.
2. Every key of the map has a production producer; no template name is missing from wired ∪ {`red_alert`, `security_alert`}.
3. `get_status()` of an active order includes `inert_triggers` = the sorted active triggers minus the wired set; an inactive order is still exactly `{"active": False}`.
4. The two rewritten tests in `test_autonomous_operations.py` call production code and carry their inline reason.

**M2:**
5. `_check_night_order_escalation` raises nothing for any exception from Night Orders, `ConnManager`, the service, the loop lookup or task creation; `_emit_event` still offers the event to `durable_events` and dispatches it.
6. A match under an active order with a service, a router and a running loop schedules exactly one `deliver_bridge_alert` task, held in `_event_listener_tasks` until done. A match the service declines (inside the cooldown, or suppressed under AD-580) schedules none: `deliver_bridge_alert` is never handed `None`.
7. Outside a running loop, the service is not called, so the cooldown is unspent.
8. The alert is ALERT severity, keyed `night_orders:{trigger}[:{subject}]`, subject ≤ 64 characters, message ≤ 500, and passes `_should_emit` (cooldown and AD-580 suppression).
9. BF-897's tests pass unchanged: the refusal is not escalated; an unmarked failure calls `conn_manager.check_escalation` once.
10. No other `_emit_event` behaviour, order or signature changed.

## 15. Acceptance criteria

- [ ] M1 to M3 built in order, one delegation and one local commit each, staged by explicit path.
- [ ] Each new test file failed on its milestone's base as §6 states (M1 at collection; M2 on every case but D3, the negative case) before the code was written.
- [ ] Each focused gate (§4) passes with `-n 0`; `check_architecture_principles.py --check` passes after M2.
- [ ] M2 has a cross-family review (`gpt-6.1-sol`) against §14, with its findings repaired.
- [ ] The §10 campaign runs once on the assembled tree; every row is killed, or recorded as equivalent (R-9), or returned to the Architect.
- [ ] `tests/test_bf897_build_pipeline_scale_and_checkout.py` passes unloosened.
- [ ] `gen_ad_ledger.py --check` and `tests/test_ad1184_ad_ledger.py` pass after M3.
- [ ] The orchestrator's single broad gate passes with its receipt.
- [ ] #1324's Night Orders checklist item is ticked with the commit and receipt; the register rows are posted on #1324.
- [ ] Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## For the register (#1324)

- **R1.** `red_alert` and `security_alert` never fire: nothing writes the alert condition, nothing emits `security_alert`, and AD-455's `TrustIntegrityMonitor.analyze` reports nothing in v1. Owner: whichever slice wires an alert-condition writer or AD-455b. The guard test T2 names the one-line map change.
- **R2.** `ConnManager`'s own escalation list and the work-item templates' `escalation_triggers` metadata still list `red_alert` and `security_alert`. Not read through this map; not checked whether anything reads the work-item metadata.
- **R3.** `BridgeAlertService` (frozen srp debt, owner AD-1270h) gains one cohesive `check_*` method; the baseline row is unchanged.
- **R4.** A delivery task that raises outside `deliver_bridge_alert`'s own guard (in `get_channel_by_type` or `event_log.log`) surfaces as asyncio's "Task exception was never retrieved", as every bridge-alert delivery already does.
- **R5.** Delivery tasks in `_event_listener_tasks` are not drained at shutdown; a page raised during shutdown may be lost. Same as BF-639 listener tasks.
- **R6.** A trust score oscillating across the floor pages once per crossing, beyond the 300 s per-agent cooldown.
- **R7.** No AD-1270a exercise receipt: steps 2 and 3 have no producer yet (`platform-maturity-program.md:755-758`). D1 is the crossing evidence until then.
- **R8.** Mutation census (orchestrator, 2026-10-27, on `427546b8`): 24 of 26 killed. Mutation R-7 (`if alert is None:`) survived because D2's second update was not a crossing and never reached the service. Amendment A1 gives D2 a second crossing inside the cooldown and asserts that no delivery is scheduled; R-7 closes when the rerun kills it. Mutation R-9 is equivalent (an inactive manager's `check_escalation` is already False). W-2 and B-1 were killed, but by T3b and D7, not by D2 as first claimed; A1's D2 assertions are predicted to make D2 a second killer of both.
