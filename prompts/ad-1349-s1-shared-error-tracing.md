# AD-1349 S1: shared-error tracing — crew who repeat the same distinctive detail across Ward Room threads are one witness, and a contradicted shared detail names its origin

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-22

**Status:** Filed as #1634, 2026-10-22 (PAUSED under the new-capability pause). Related defects: BF-920 (#1633).
**Dependencies:** none unbuilt. Builds on AD-567f (`cognitive/social_verification.py`), AD-583f (`cognitive/observable_state.py`), AD-583g (`ward_room/thread_echo.py`), AD-1119 (`cognitive/referent_gate.extract_referents`).
**Estimated tests:** about 24 new functions in `tests/test_ad1349_shared_error.py`, plus three pinned-snapshot updates (config facade baseline, knowledge-model dump, config reference).
**Tier:** MEDIUM (detection only; default alerting OFF; no write path, no governance change).

---

## Problem

The Captain's 2026-04-08 case study (Chapel fabricated a "stuck" tic-tac-toe game after losing; four Medical officers amplified it into a "game state desynchronization" diagnosis) is the canonical cascade. It survives in the archive `C:\Users\seang\AppData\Local\ProbOS\data\archives\ward_room_2026-04-16_010400.db`. A read-only replay of today's shipped code over the Medical channel, 2026-04-08 16:00 to 20:12 local (241 threads and posts: Cortez 118, Chapel 47, Keiko 44, Sinclair 32), shows that **every shipped detector is blind to it**:

| Detector | Gate | Result on the cascade |
|---|---|---|
| AD-506b peer similarity → AD-567f `check_cascade_risk` | Jaccard of whole word sets >= 0.5 within 600 s, same channel (`ward_room/threads.py:23-81`) | **0 matches in 241 items**, so `check_cascade_risk` never ran (`ward_room/_helpers.py:31`) |
| AD-583g `ThreadEchoAnalyzer` | Jaccard to the thread source >= 0.4 (`ward_room/thread_echo.py:113-121`) | 22 threads with >= 3 authors; the highest similarity to source was 0.33; **echo_detected False on all 22** |
| AD-567f `compute_anchor_independence` (had it run) | different thread_id, same channel, no duty_cycle_id, > 60 s apart (`cognitive/social_verification.py:192`) | **1.0 (fully independent)** for the production-shaped anchors (`ward_room/messages.py:345-357`) |

LLM crew paraphrase; they do not copy. Bag-of-words similarity cannot see a paraphrased cascade, and anchor metadata calls posts in different threads of the same channel independent. AD-583's own premise ("`compute_anchor_independence()` would have scored ~0.0", issue #115) is false on this data: it scores 1.0.

What *does* link them is the method of textual criticism (stemmatics): **agreement in a distinctive, unlikely-to-recur reading proves shared descent**. The same replay finds the Medical officers sharing details absent from the 44,641 earlier Ward Room items: `52-minute game` (Chapel, Cortez, Sinclair), `display-logic desynchronization` (Chapel, Keiko, Sinclair), `phantom dose` (Chapel, Keiko), `game stall`. The 52 minutes is Chapel's invention (thread `7d37b882-56be-4a48-8fe2-1f1f6bf81b8c`, 19:57:19: "stuck for 52 minutes"); Sinclair restates it at 19:57:23 (post `096dfcfc-19f6-466b-a078-013ef50c6d62`) and it spreads to a second thread.

**But dependence is the normal state of a channel, not a cascade.** Measured over the same archive (2026-04-05 to 04-11), posts sharing two or more baseline-novel details with another author's post in the same channel within 600 s are 12-25% of all posts every day; on the live `ward_room.db` (2026-10-18 and 10-22) 33-52%. Stemmatics says the same thing: shared readings prove descent, not error. So content dependence must never raise an alarm on its own. It is the **trigger** for the error check that already exists (AD-583f `ObservableStateVerifier`), and the alarm condition is the stemmatic one: **a conjunctive error — a shared reading that ship state contradicts, held by two or more witnesses**.

The exact trigger specified below, replayed on 2026-04-08: 244 triggers in 4,562 posts (5.3%; Science 160, Medical 84). It fires on the evening cascade (20:08:32, Chapel, Cortez and Sinclair across two threads, shared `52 minute`) and reconstructs the origin as **Chapel at 19:57:19**. (The shipped `CascadeRiskResult.source_agent` would have named the latest poster; see Follow-ups.) Requiring two shared details instead of one drops it to 3 triggers and misses the cascade, which fixes `min_shared = 1`.

## Solution

1. **Pure module `cognitive/stemma.py`** (no I/O, no LLM): `extract_distinctive_details(text)` returns normalized distinctive readings: number+unit (`52 minutes`, `52-minute` → `52 minute`), coined hyphenated compounds (>= 8 characters), and hex identifiers (via the shipped AD-1119 `extract_referents`, kind `hex`). `reconstruct_stemma(witnesses, common_readings, min_shared)` links witnesses of *different* agents that share at least `min_shared` readings not in `common_readings` (the polygenesis guard: readings already present in the channel's baseline are the "archetype", not evidence), joins them with union-find, and returns components with a deterministic origin: the earliest witness, ties broken by id.
2. **Ward Room tracer `ward_room/shared_error.py`** (`SharedErrorTracer`, constructor-injected like `ThreadEchoAnalyzer`): for each new thread or post, reads the channel window (last `window_seconds`, at most 50 items) and the baseline (the 200 items before the window) through a narrow protocol, reconstructs the stemma, and **triggers** when the new item's component has >= `min_agents` distinct agents across >= 2 threads (same-thread echo stays AD-583g's job). On a trigger it verifies the component's claims, origin first, with the existing `ObservableStateVerifier`, and reports a **conjunctive error** when claims from >= 2 distinct agents fail. Alerting is a separate, default-OFF policy with per-origin dedup.
3. **Wiring**: one new helper in `ward_room/_helpers.py`; `ThreadManager` and `MessageStore` call it after the existing echo trace; `finalize.py` builds the tracer beside `ThreadEchoAnalyzer`. A triggered trace always logs one INFO line of counts (the measurement this slice exists to collect). When alerting is enabled and a conjunctive error is due, it emits the existing `OBSERVABLE_STATE_MISMATCH` with `agents_involved` origin-first (so the Counselor's three DMs reach the origin before the copyists, `cognitive/counselor.py:2018`) and delivers the bridge alert.

**Why alerting defaults OFF.** The error half is only as precise as the AD-583f providers, and they are keyword-coarse: `TrustStateProvider` marks any claim containing the word "anomaly" false when no trust score is 2 sigma out (`cognitive/observable_state.py:226-240`); `RecreationStateProvider` marks "stuck" false whenever the game is active (`:156-165`). At about 5% of posts triggering, enabling Counselor DMs before measuring that precision risks a DM storm. This follows the AD-1119 → AD-1120 precedent in the same problem area: ship observe-only, read the logs, then flip. The tracing itself is ON by default, so the slice is not inert: it produces the measurement on the live ship from the first boot.

**Privacy (AD-567f principle).** The tracer reads Ward Room bodies inside the Ward Room service (channel content its members already see). Nothing it logs, emits or alerts carries post content: counts, callsigns, ids and the verifier's ship-state summary only.

### Section 0: Event Types

**None added.** The alert reuses `EventType.OBSERVABLE_STATE_MISMATCH` (`events.py:229`), already grandfathered in the AD-1195 persistence contract (`event_persistence.py:318`) and already consumed by the Counselor (`counselor.py:1048-1049`). A new member would move six pinned AD-1195 counts (`tests/test_ad1195_durable_event_seam.py:326-330`, `tests/test_ad1195_event_persistence_contract.py:505-509`, `tests/test_ad1195_durable_producers.py:162,172`) for no consumer gain. The payload gains a discriminator key `"trigger": "shared_error"`.

---

## Implementation

### Section 1: `src/probos/cognitive/stemma.py` (new)

Full file. Cognitive layer, stdlib plus `probos.cognitive.referent_gate` only.

```python
"""AD-1349: shared-error (stemmatic) dependence between crew witnesses.

Textual criticism's common-error method (Lachmann, Maas): witnesses that share a
distinctive reading unlikely to arise independently ("Leitfehler") descend from a
common source; agreement in an ordinary reading proves nothing. Here a witness is
one Ward Room thread or post, a reading is a normalized distinctive detail, and
readings already present in the channel's baseline are treated as the common
archetype (the polygenesis guard), so they never link anyone.

Union-find over shared readings is deliberately conservative under contamination
(a witness that drew on two sources joins both branches into one). The origin of a
component is its earliest extant witness: a hypothesis about the archetype, not a
proof, because the true source may lie outside the observed window.

Deterministic and LLM-free. No I/O.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from probos.cognitive.referent_gate import extract_referents

_CODE_SPANS = re.compile(r"`{3}.*?`{3}|`[^`\n]*`", re.DOTALL)  # fenced blocks, then inline spans
_NUMERIC_DETAIL = re.compile(
    r"(?<![\w.])(\d+(?:\.\d+)?)[\s-]?"
    r"(minutes?|mins?|seconds?|secs?|hours?|hrs?|days?|%|percent|ms|cycles?)(?!\w)"
)
_UNIT_CANON: dict[str, str] = {
    "minute": "minute", "minutes": "minute", "min": "minute", "mins": "minute",
    "second": "second", "seconds": "second", "sec": "second", "secs": "second",
    "hour": "hour", "hours": "hour", "hr": "hour", "hrs": "hour",
    "day": "day", "days": "day", "%": "%", "percent": "%", "ms": "ms",
    "cycle": "cycle", "cycles": "cycle",
}
_COINED_COMPOUND = re.compile(r"\b[a-z]{3,}(?:-[a-z]{3,})+\b")
_MIN_COMPOUND_LEN = 8


def extract_distinctive_details(text: str) -> frozenset[str]:
    """Return the normalized distinctive readings in ``text``.

    Three kinds, each prefixed so kinds never collide: ``n:`` number+unit
    (``"52 minutes"`` and ``"52-minute"`` both become ``"n:52 minute"``), ``h:``
    coined hyphenated compound of at least eight characters, ``x:`` hex identifier
    as AD-1119 extracts it. Code spans are ignored. Empty or None-like text gives
    an empty set.
    """
    if not text:
        return frozenset()
    prose = _CODE_SPANS.sub(" ", text)
    lowered = prose.lower()
    details: set[str] = {
        f"n:{number} {_UNIT_CANON[unit]}" for number, unit in _NUMERIC_DETAIL.findall(lowered)
    }
    details.update(
        f"h:{compound}"
        for compound in _COINED_COMPOUND.findall(lowered)
        if len(compound) >= _MIN_COMPOUND_LEN
    )
    details.update(
        f"x:{referent.token.lower()}"
        for referent in extract_referents(text)
        if referent.kind == "hex"
    )
    return frozenset(details)


@dataclass(frozen=True)
class Witness:
    """One observed text: a Ward Room thread or post."""

    witness_id: str
    agent_id: str
    unit_id: str  # the thread the witness belongs to
    timestamp: float
    details: frozenset[str]


@dataclass(frozen=True)
class StemmaComponent:
    """Witnesses joined by shared distinctive readings."""

    witness_ids: tuple[str, ...]  # chronological (timestamp, witness_id)
    agent_ids: tuple[str, ...]  # sorted, unique
    unit_ids: tuple[str, ...]  # sorted, unique
    origin_witness_id: str
    origin_agent_id: str
    shared_reading_count: int  # readings held by >= 2 distinct agents in the component


def reconstruct_stemma(
    witnesses: Sequence[Witness],
    *,
    common_readings: frozenset[str] = frozenset(),
    min_shared: int = 1,
) -> tuple[StemmaComponent, ...]:
    """Group witnesses into components of shared descent.

    Two witnesses are linked when their agents differ and they share at least
    ``min_shared`` readings outside ``common_readings``. Linking is transitive.
    Every witness is in exactly one component (singletons included). Components
    are returned ordered by their origin (timestamp, witness_id). Raises
    ``ValueError`` when ``min_shared < 1``.
    """
    if min_shared < 1:
        raise ValueError("min_shared must be >= 1")
    ordered = sorted(witnesses, key=lambda w: (w.timestamp, w.witness_id))
    readings = [w.details - common_readings for w in ordered]
    parent = list(range(len(ordered)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for i in range(len(ordered)):
        for j in range(i + 1, len(ordered)):
            if ordered[i].agent_id == ordered[j].agent_id:
                continue
            if len(readings[i] & readings[j]) >= min_shared:
                parent[find(i)] = find(j)

    groups: dict[int, list[int]] = {}
    for index in range(len(ordered)):
        groups.setdefault(find(index), []).append(index)

    keyed: list[tuple[int, StemmaComponent]] = []
    for members in groups.values():
        members.sort()  # indices into the chronological list, so members[0] is the origin
        holders: dict[str, set[str]] = {}
        for index in members:
            for reading in readings[index]:
                holders.setdefault(reading, set()).add(ordered[index].agent_id)
        origin = ordered[members[0]]
        keyed.append((members[0], StemmaComponent(
            witness_ids=tuple(ordered[i].witness_id for i in members),
            agent_ids=tuple(sorted({ordered[i].agent_id for i in members})),
            unit_ids=tuple(sorted({ordered[i].unit_id for i in members})),
            origin_witness_id=origin.witness_id,
            origin_agent_id=origin.agent_id,
            shared_reading_count=sum(1 for agents in holders.values() if len(agents) >= 2),
        )))
    keyed.sort(key=lambda pair: pair[0])
    return tuple(component for _, component in keyed)
```

Builder notes: (a) `_CODE_SPANS` duplicates the intent of AD-1119's private `_strip_code_spans` (`referent_gate.py:182`); do not import the private name across modules. (b) If two witnesses share a `witness_id`, that is a caller bug; do not add handling for it.

### Section 2: `src/probos/ward_room/shared_error.py` (new)

Full file.

```python
"""AD-1349: Ward Room shared-error tracing (stemmatic conjunctive-error detection).

AD-583g traces echo inside one thread by word overlap. LLM crew paraphrase, and a
cascade crosses threads, so neither gate saw the 2026-04-08 Medical cascade. This
tracer links posts by shared distinctive readings (cognitive/stemma.py) across the
threads of one channel, and asks the existing ObservableStateVerifier whether the
shared claims contradict ship state. Dependence alone is normal channel behaviour
and never alerts; a conjunctive error (claims of >= 2 linked agents contradicted)
may, when alerting is enabled.

Privacy (AD-567f): bodies are read here, inside the Ward Room; the result carries
counts, ids, callsigns and the verifier's ship-state summary only.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Protocol

from probos.cognitive.stemma import Witness, extract_distinctive_details, reconstruct_stemma

logger = logging.getLogger(__name__)

_CLAIM_CHARS = 500
_ALERT_MEMORY = 256


class ChannelWindowProtocol(Protocol):
    """Narrow read access to a channel's recent threads and posts (ISP)."""

    async def get_channel_window(
        self, channel_id: str, *, since: float, until: float, limit: int,
    ) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class SharedErrorResult:
    """Outcome of one trace. ``triggered`` False means nothing below it applies."""

    triggered: bool
    channel_id: str
    conjunctive_error: bool = False
    alert_due: bool = False
    origin_item_id: str = ""
    origin_thread_id: str = ""
    origin_callsign: str = ""
    witness_callsigns: tuple[str, ...] = ()  # origin first, then first appearance
    witness_count: int = 0  # distinct agents in the component
    thread_count: int = 0
    shared_detail_count: int = 0
    claims_checked: int = 0
    claims_failed: int = 0
    failed_agent_count: int = 0
    ground_truth_summary: str = ""


class SharedErrorTracer:
    """Trace shared distinctive readings across a channel's threads (DIP: injected)."""

    def __init__(
        self,
        channel_window: ChannelWindowProtocol,
        observable_state_verifier: Any,
        *,
        window_seconds: float = 3600.0,
        min_agents: int = 3,
        alerts_enabled: bool = False,
        window_limit: int = 50,
        baseline_limit: int = 200,
        min_threads: int = 2,
        max_claims: int = 10,
    ) -> None:
        self._window = channel_window
        self._verifier = observable_state_verifier
        self._window_seconds = window_seconds
        self._min_agents = min_agents
        self._alerts_enabled = alerts_enabled
        self._window_limit = window_limit
        self._baseline_limit = baseline_limit
        self._min_threads = min_threads
        self._max_claims = max_claims
        self._alerted: OrderedDict[str, float] = OrderedDict()

    async def trace(
        self,
        *,
        channel_id: str,
        item_id: str,
        thread_id: str,
        author_id: str,
        author_callsign: str,
        body: str,
        created_at: float,
    ) -> SharedErrorResult:
        """Trace one new thread or post. Never raises for a verifier failure."""
        own = extract_distinctive_details(body)
        if not own:
            return SharedErrorResult(triggered=False, channel_id=channel_id)

        window_start = created_at - self._window_seconds
        baseline_rows = await self._window.get_channel_window(
            channel_id, since=0.0, until=window_start, limit=self._baseline_limit,
        )
        common: set[str] = set()
        for row in baseline_rows:
            common |= extract_distinctive_details(row.get("body", ""))
        if not (own - common):
            return SharedErrorResult(triggered=False, channel_id=channel_id)

        window_rows = [
            row for row in await self._window.get_channel_window(
                channel_id, since=window_start, until=created_at, limit=self._window_limit,
            )
            if row.get("id") != item_id
        ]
        rows = window_rows + [{
            "id": item_id, "thread_id": thread_id, "author_id": author_id,
            "author_callsign": author_callsign, "body": body, "created_at": created_at,
        }]
        by_id = {row["id"]: row for row in rows}
        witnesses = [
            Witness(
                witness_id=row["id"],
                agent_id=row.get("author_id", ""),
                unit_id=row.get("thread_id", ""),
                timestamp=float(row.get("created_at", 0.0)),
                details=own if row["id"] == item_id else extract_distinctive_details(row.get("body", "")),
            )
            for row in rows
        ]
        components = reconstruct_stemma(witnesses, common_readings=frozenset(common))
        component = next(c for c in components if item_id in c.witness_ids)
        if len(component.agent_ids) < self._min_agents or len(component.unit_ids) < self._min_threads:
            return SharedErrorResult(triggered=False, channel_id=channel_id)

        def callsign(row: dict[str, Any]) -> str:
            return row.get("author_callsign") or row.get("author_id", "")[:8]

        ordered_rows = [by_id[wid] for wid in component.witness_ids]  # chronological, origin first
        callsigns: list[str] = []
        for row in ordered_rows:
            if callsign(row) not in callsigns:
                callsigns.append(callsign(row))
        origin = by_id[component.origin_witness_id]

        claims: list[str] = []
        claim_authors: dict[str, set[str]] = {}
        for row in ordered_rows:
            text = (row.get("body") or "")[:_CLAIM_CHARS]
            if not text:
                continue
            if text not in claim_authors:
                claims.append(text)
            claim_authors.setdefault(text, set()).add(row.get("author_id", ""))
        claims = claims[: self._max_claims]

        checked = failed = 0
        failed_agents: set[str] = set()
        summaries: list[str] = []
        if self._verifier is not None and claims:
            try:
                results = await self._verifier.verify_claims(claims, context={"agents": callsigns})
            except Exception:
                logger.warning(
                    "AD-1349: shared-error verification failed for channel=%s origin=%s; "
                    "reporting the trigger without a verdict", channel_id, origin["id"], exc_info=True,
                )
                results = []
            checked = len(results)
            for result in results:
                if result.verified is False:
                    failed += 1
                    failed_agents |= claim_authors.get(result.claim_text, set())
                    if result.ground_truth_summary and result.ground_truth_summary not in summaries:
                        summaries.append(result.ground_truth_summary)

        conjunctive = len(failed_agents) >= 2
        alert_due = False
        if conjunctive and self._alerts_enabled:
            alert_due = self._claim_alert(origin["id"], created_at)

        return SharedErrorResult(
            triggered=True,
            channel_id=channel_id,
            conjunctive_error=conjunctive,
            alert_due=alert_due,
            origin_item_id=origin["id"],
            origin_thread_id=origin.get("thread_id", ""),
            origin_callsign=callsign(origin),
            witness_callsigns=tuple(callsigns),
            witness_count=len(component.agent_ids),
            thread_count=len(component.unit_ids),
            shared_detail_count=component.shared_reading_count,
            claims_checked=checked,
            claims_failed=failed,
            failed_agent_count=len(failed_agents),
            ground_truth_summary="; ".join(summaries[:3]),
        )

    def _claim_alert(self, origin_id: str, now: float) -> bool:
        """True once per origin within ``window_seconds`` (in-memory, bounded)."""
        last = self._alerted.get(origin_id)
        if last is not None and now - last < self._window_seconds:
            return False
        self._alerted[origin_id] = now
        self._alerted.move_to_end(origin_id)
        while len(self._alerted) > _ALERT_MEMORY:
            self._alerted.popitem(last=False)
        return True
```

Exception tiers: the verifier call is **log-and-degrade** (a broken provider must not block a post; the trigger is still reported). A failure of `get_channel_window` propagates out of `trace` to the helper, which logs it (Section 4). Dedup memory is lost on restart; the bridge alert's own dedup (`bridge_alerts.py:615-617`) still holds within a run.

### Section 3: `ThreadManager.get_channel_window` and its `WardRoomService` delegate

**3a.** In `src/probos/ward_room/threads.py`, add a public method directly **before** `get_thread_posts_temporal` (`threads.py:759`):

SEARCH:
```python
    async def get_thread_posts_temporal(self, thread_id: str) -> list[dict[str, Any]]:
        """Return all posts in a thread, flat and ordered by created_at.
```
REPLACE:
```python
    async def get_channel_window(
        self, channel_id: str, *, since: float, until: float, limit: int,
    ) -> list[dict[str, Any]]:
        """AD-1349: the ``limit`` most recent threads and live posts of a channel.

        Rows with ``since <= created_at < until``, returned oldest first, each
        ``{id, thread_id, author_id, author_callsign, body, created_at}``. A thread
        row's ``thread_id`` is its own id. Deleted posts are excluded.
        """
        if not self._db or limit <= 0:
            return []
        rows: list[dict[str, Any]] = []
        async with self._db.execute(
            "SELECT id, thread_id, author_id, author_callsign, body, created_at FROM ("
            " SELECT id, id AS thread_id, author_id, author_callsign, body, created_at"
            " FROM threads WHERE channel_id = ? AND created_at >= ? AND created_at < ?"
            " UNION ALL"
            " SELECT p.id, p.thread_id, p.author_id, p.author_callsign, p.body, p.created_at"
            " FROM posts p JOIN threads t ON p.thread_id = t.id"
            " WHERE t.channel_id = ? AND p.deleted = 0 AND p.created_at >= ? AND p.created_at < ?"
            ") ORDER BY created_at DESC, id DESC LIMIT ?",
            (channel_id, since, until, channel_id, since, until, limit),
        ) as cursor:
            async for row in cursor:
                rows.append({
                    "id": row[0], "thread_id": row[1], "author_id": row[2],
                    "author_callsign": row[3] or "", "body": row[4] or "",
                    "created_at": row[5],
                })
        rows.reverse()
        return rows

    async def get_thread_posts_temporal(self, thread_id: str) -> list[dict[str, Any]]:
        """Return all posts in a thread, flat and ordered by created_at.
```

**3b.** In `src/probos/ward_room/service.py`, add the delegate after `count_threads` (`service.py:348-350`), following the existing delegate pattern:

SEARCH:
```python
    async def count_threads(self, channel_id: str) -> int:
        """AD-613: Return thread count for a channel without fetching rows."""
        return await self._threads.count_threads(channel_id)
```
REPLACE:
```python
    async def count_threads(self, channel_id: str) -> int:
        """AD-613: Return thread count for a channel without fetching rows."""
        return await self._threads.count_threads(channel_id)

    async def get_channel_window(
        self, channel_id: str, *, since: float, until: float, limit: int,
    ) -> list[dict[str, Any]]:
        """AD-1349: delegate to ``ThreadManager.get_channel_window``."""
        if not self._threads:
            return []
        return await self._threads.get_channel_window(
            channel_id, since=since, until=until, limit=limit,
        )
```
(Confirm `Any` is imported in `service.py`; add it to the existing `typing` import only if absent.)

### Section 4: helper and call sites

**4a.** Append to `src/probos/ward_room/_helpers.py` (after `check_and_trace_echo`, which ends at `_helpers.py:147`):

```python
async def check_and_trace_shared_error(
    shared_error_tracer: Any,
    emit_fn: Callable | None,
    bridge_alerts: Any,
    ward_room_router: Any,
    *,
    channel_id: str,
    item_id: str,
    thread_id: str,
    author_id: str,
    author_callsign: str,
    body: str,
    created_at: float,
) -> None:
    """AD-1349: trace shared distinctive readings across a channel's threads.

    Logs every trigger (counts only). Emits OBSERVABLE_STATE_MISMATCH and delivers
    its bridge alert only when the tracer reports ``alert_due``.
    """
    if not shared_error_tracer:
        return
    try:
        result = await shared_error_tracer.trace(
            channel_id=channel_id, item_id=item_id, thread_id=thread_id,
            author_id=author_id, author_callsign=author_callsign,
            body=body, created_at=created_at,
        )
        if not result.triggered:
            return
        logger.info(
            "AD-1349 shared-error trace: channel=%s origin=%s/%s agents=%d threads=%d "
            "shared=%d checked=%d failed=%d failed_agents=%d conjunctive=%s alert_due=%s",
            channel_id, result.origin_callsign, result.origin_item_id, result.witness_count,
            result.thread_count, result.shared_detail_count, result.claims_checked,
            result.claims_failed, result.failed_agent_count, result.conjunctive_error,
            result.alert_due,
        )
        if not result.alert_due:
            return
        if emit_fn:
            from probos.events import EventType as _ET
            emit_fn(_ET.OBSERVABLE_STATE_MISMATCH, {
                "thread_id": result.origin_thread_id,
                "channel_id": channel_id,
                "claims_checked": result.claims_checked,
                "claims_failed": result.claims_failed,
                "ground_truth_summary": result.ground_truth_summary,
                "agents_involved": list(result.witness_callsigns),
                "trigger": "shared_error",
                "origin_callsign": result.origin_callsign,
                "witness_count": result.witness_count,
                "thread_count": result.thread_count,
                "shared_detail_count": result.shared_detail_count,
            })
        if bridge_alerts:
            alerts = bridge_alerts.check_observable_mismatch({
                "thread_id": f"shared-error:{result.origin_item_id}",
                "claims_failed": result.claims_failed,
                "ground_truth_summary": result.ground_truth_summary,
            })
            if alerts and ward_room_router:
                for alert in alerts:
                    try:
                        await ward_room_router.deliver_bridge_alert(alert)
                    except Exception:
                        logger.debug("AD-1349: bridge alert delivery failed", exc_info=True)
    except Exception:
        logger.warning("AD-1349: shared-error trace failed for channel=%s", channel_id, exc_info=True)
```

Tier: log-and-degrade at WARNING (not DEBUG): a broken trace is a visible loss of a safety detector, unlike the DEBUG-level pattern in the older helpers.

**4b.** `set_echo_services` gains one keyword in all three places. In `ward_room/threads.py:180-191` and `ward_room/messages.py:57-65`, add the parameter `shared_error_tracer: Any = None` after `ward_room_router` and store it as `self._shared_error_tracer = shared_error_tracer`. Also initialise `self._shared_error_tracer: Any = None` in each class's `__init__` beside `self._social_verification` (`threads.py:162`, `messages.py:39`), so the call sites below read the attribute directly (no `getattr` default). In `ward_room/service.py:187-208`, add the same parameter and pass `shared_error_tracer=shared_error_tracer` to both sub-service calls.

**4c.** Add a delegating method to both `ThreadManager` and `MessageStore`, beside `_check_echo_trace`:

```python
    async def _check_shared_error(
        self, *, channel_id: str, item_id: str, thread_id: str, author_id: str,
        author_callsign: str, body: str, created_at: float,
    ) -> None:
        """AD-1349: Delegate to helper for shared-error tracing."""
        from probos.ward_room._helpers import check_and_trace_shared_error
        await check_and_trace_shared_error(
            self._shared_error_tracer,
            self._emit,
            getattr(self, '_bridge_alerts', None),
            getattr(self, '_ward_room_router', None),
            channel_id=channel_id, item_id=item_id, thread_id=thread_id,
            author_id=author_id, author_callsign=author_callsign,
            body=body, created_at=created_at,
        )
```
(The two `getattr` reads mirror `_check_echo_trace` exactly: `_bridge_alerts` and `_ward_room_router` are only set by `set_echo_services`. Do not widen this slice to fix that pre-existing pattern.)

**4d.** Call sites. In `ward_room/threads.py`, after `threads.py:562`:

SEARCH:
```python
        # AD-583f/583g: Echo chain tracing when peer similarity detected
        await self._check_echo_trace(peer_matches, thread.id, channel_id)
```
REPLACE:
```python
        # AD-583f/583g: Echo chain tracing when peer similarity detected
        await self._check_echo_trace(peer_matches, thread.id, channel_id)

        # AD-1349: shared-error tracing across the channel's threads (not gated on peer_matches)
        await self._check_shared_error(
            channel_id=channel_id, item_id=thread.id, thread_id=thread.id,
            author_id=author_id, author_callsign=author_callsign,
            body=body, created_at=thread.created_at,
        )
```

In `ward_room/messages.py`, after `messages.py:310`:

SEARCH:
```python
        # AD-583f/583g: Echo chain tracing when peer similarity detected
        await self._check_echo_trace(peer_matches, thread_id, thread_channel_id)
```
REPLACE:
```python
        # AD-583f/583g: Echo chain tracing when peer similarity detected
        await self._check_echo_trace(peer_matches, thread_id, thread_channel_id)

        # AD-1349: shared-error tracing across the channel's threads (not gated on peer_matches)
        await self._check_shared_error(
            channel_id=thread_channel_id, item_id=post.id, thread_id=thread_id,
            author_id=author_id, author_callsign=author_callsign,
            body=body, created_at=post.created_at,
        )
```

### Section 5: configuration

In `src/probos/config_models/knowledge.py`, extend `SourceTracingConfig` (`knowledge.py:399-404`):

SEARCH:
```python
class SourceTracingConfig(BaseModel):
    """AD-583g: Ward Room echo detection and source tracing."""

    echo_min_chain_length: int = 3
    echo_similarity_threshold: float = 0.4
    echo_analysis_enabled: bool = True
```
REPLACE:
```python
class SourceTracingConfig(BaseModel):
    """AD-583g: Ward Room echo detection and source tracing."""

    echo_min_chain_length: int = 3
    echo_similarity_threshold: float = 0.4
    echo_analysis_enabled: bool = True
    # AD-1349: shared-error (stemmatic) tracing across a channel's threads.
    shared_error_tracing_enabled: bool = True  # trace and log every trigger (counts only)
    shared_error_alerts_enabled: bool = False  # emit OBSERVABLE_STATE_MISMATCH + bridge alert on a conjunctive error
    shared_error_window_seconds: float = 3600.0  # channel look-back for linked witnesses
    shared_error_min_agents: int = 3  # distinct agents in one component before verifying

    @field_validator("shared_error_window_seconds")
    @classmethod
    def _positive_window(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("shared_error_window_seconds must be > 0")
        return value

    @field_validator("shared_error_min_agents")
    @classmethod
    def _at_least_two_agents(cls, value: int) -> int:
        if value < 2:
            raise ValueError("shared_error_min_agents must be >= 2")
        return value
```

Validators, not `Field(gt=...)`: a `Field` bound would also move the pinned `EXPECTED_BOUND_COUNTS` table (`tests/test_ad1270e2f_knowledge_models.py:456-535`).

Pinned snapshots this changes, each updated in the same commit with an inline `# AD-1349 (...)` reason, never deleted:
1. `tests/test_ad1270e2f_knowledge_models.py:265-267`: add the four new keys and defaults to `EXPECTED_DUMPS["SourceTracingConfig"]`.
2. `docs/development/config-facade-baseline.yaml`: regenerate with `d:/ProbOS/.venv/Scripts/python.exe scripts/check_config_facade.py --update-baseline`; review the diff (only `SourceTracingConfig` fields and the field count may move).
3. `tests/test_ad1270e1_config_facade.py:1525-1553`: append `# AD-1349 adds four source_tracing.shared_error_* fields (1869 -> 1873).` and bump `field_definitions`. Use the number the checker writes, not this arithmetic, if they differ.
4. `docs/development/config-reference.md`: regenerate with `d:/ProbOS/.venv/Scripts/python.exe scripts/gen_config_reference.py`; then `--check` must pass.

**Do not edit `config/system.yaml`.** It carries the Captain's uncommitted local changes, and the defaults above need no YAML.

### Section 6: startup wiring

In `src/probos/startup/finalize.py`, inside the AD-583f/583g block (`finalize.py:5849-5893`):

SEARCH:
```python
        # Late-bind to Ward Room via public set_echo_services (Law of Demeter)
        if runtime.ward_room and (thread_echo or observable_verifier):
            runtime.ward_room.set_echo_services(
                thread_echo_analyzer=thread_echo,
                observable_state_verifier=observable_verifier,
                bridge_alerts=getattr(runtime, 'bridge_alerts', None),
                ward_room_router=ward_room_router,
            )
```
REPLACE:
```python
        # AD-1349: shared-error tracing needs the verifier for its error half
        shared_error_tracer = None
        if src_cfg.shared_error_tracing_enabled and runtime.ward_room and observable_verifier:
            from probos.ward_room.shared_error import SharedErrorTracer
            shared_error_tracer = SharedErrorTracer(
                runtime.ward_room,
                observable_verifier,
                window_seconds=src_cfg.shared_error_window_seconds,
                min_agents=src_cfg.shared_error_min_agents,
                alerts_enabled=src_cfg.shared_error_alerts_enabled,
            )

        # Late-bind to Ward Room via public set_echo_services (Law of Demeter)
        if runtime.ward_room and (thread_echo or observable_verifier):
            runtime.ward_room.set_echo_services(
                thread_echo_analyzer=thread_echo,
                observable_state_verifier=observable_verifier,
                bridge_alerts=getattr(runtime, 'bridge_alerts', None),
                ward_room_router=ward_room_router,
                shared_error_tracer=shared_error_tracer,
            )
```

The tracer receives the public `runtime.ward_room` service (which now carries `get_channel_window`), not `runtime.ward_room._threads`.

---

## Tests

New file `tests/test_ad1349_shared_error.py`. No live data, no network; synthetic texts modeled on the 2026-04-08 archive.

**Pure module (`stemma`)**
1. `test_number_and_unit_normalize_across_spellings`: `"stuck for 52 minutes"` and `"a 52-minute game stall"` both yield `n:52 minute`.
2. `test_short_hyphenation_is_not_distinctive`: `"re-run"` yields nothing; `"display-logic"` yields `h:display-logic`.
3. `test_hex_identifier_comes_from_referent_extraction`: `"node e77acec7 failed"` yields `x:e77acec7`; plain decimals do not.
4. `test_code_spans_are_ignored`.
5. `test_empty_text_has_no_details` (empty string and whitespace).
6. `test_same_agent_never_links_to_itself`.
7. `test_common_readings_never_link` (polygenesis guard): two agents sharing only a baseline reading stay separate components.
8. `test_linking_is_transitive`: A-B share x, B-C share y → one component of three agents.
9. `test_origin_is_the_earliest_witness_with_deterministic_tie_break` (equal timestamps → lower id).
10. `test_shared_reading_count_counts_readings_held_by_two_agents`.
11. `test_min_shared_below_one_is_rejected` (ValueError).
12. `test_empty_witness_list_gives_no_components`.

**Tracer (fake `ChannelWindowProtocol`, fake verifier)**
13. `test_no_distinctive_detail_reads_nothing`: fake records zero `get_channel_window` calls.
14. `test_detail_already_in_baseline_does_not_trigger`.
15. `test_april_eighth_shape_triggers_with_chapel_as_origin`: Chapel thread T1 "stuck for 52 minutes", Sinclair post in T1 "52-minute game state desynchronization", Cortez post in T2 "the 52-minute stall" → `triggered`, `origin_callsign == "Chapel"`, `witness_callsigns[0] == "Chapel"`, `thread_count == 2`, `witness_count == 3`.
16. `test_single_thread_chain_does_not_trigger` (left to AD-583g).
17. `test_two_agents_do_not_trigger` (min_agents 3).
18. `test_conjunctive_error_needs_two_failed_agents`: verifier fails only Chapel's claim → `conjunctive_error False`; fails Chapel's and Cortez's → True, `failed_agent_count == 2`.
19. `test_verifier_failure_degrades_to_a_trigger_without_verdict`: verifier raises → `triggered True`, `claims_checked == 0`, no exception, WARNING logged.
20. `test_alerts_disabled_never_due` (default).
21. `test_alert_is_due_once_per_origin_within_window` and due again after `window_seconds`.

**Seam (crosses the chain: real `WardRoomService` on a temp DB → helper → emit)**
22. `test_real_ward_room_posts_reach_the_mismatch_event_origin_first`: real `WardRoomService(db_path=tmp_path/"wr.db", emit_event=recorder)`, started; construct it the way `tests/test_ad1229_message_receipts_e2e.py:63` does. Wire `set_echo_services(observable_state_verifier=fake, shared_error_tracer=SharedErrorTracer(service, fake, alerts_enabled=True))`. Create the three-agent, two-thread sequence of test 15 through `create_thread`/`create_post`. Assert the recorder received exactly one `OBSERVABLE_STATE_MISMATCH` with `trigger == "shared_error"` and `agents_involved[0] == "Chapel"`, and that a fourth linked post does **not** emit a second one (dedup).
23. `test_real_ward_room_with_alerts_off_emits_nothing_but_logs`: same sequence, `alerts_enabled=False`: no `OBSERVABLE_STATE_MISMATCH`; `caplog` holds an `AD-1349 shared-error trace` INFO line that contains no post text (assert none of `"stuck"`, `"minute"`, `"stall"`, `"desynchronization"` appears in it; do not assert on digits, because ids may contain them).
24. `test_get_channel_window_orders_limits_and_excludes_deleted`: real DB; `limit` keeps the most recent rows and returns them oldest first; a deleted post is absent; `until` is exclusive.

**Config**
25. `test_source_tracing_defaults_and_validators`: defaults as Section 5; window 0 and min_agents 1 rejected.

Focused coding gate (Builder, per section):
```
d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_ad1349_shared_error.py -q -n 0
d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_ad583g_source_tracing.py tests/test_ad583f_observable_state.py tests/test_social_verification.py tests/test_ad1270e2f_knowledge_models.py tests/test_ad1270e1_config_facade.py tests/test_config_reference_current.py -q -n 0
d:/ProbOS/.venv/Scripts/python.exe scripts/check_config_facade.py --check
d:/ProbOS/.venv/Scripts/python.exe scripts/gen_config_reference.py --check
```
Plus every test file that constructs `ThreadManager`, `MessageStore` or `WardRoomService` and calls `set_echo_services` (grep `set_echo_services` under `tests/` before running; today none does). Broad gate: once, by the main session, per the orchestrator's procedure; never `pytest tests/` directly.

## What This Does NOT Change

- `check_peer_similarity`, `check_cascade_risk`, `compute_anchor_independence`, `ThreadEchoAnalyzer`: untouched. Their defects are Follow-ups below, not this AD.
- `check_corroboration` / `corroboration_score` (the "effective witness count" idea): no production caller exists, so a branch count there would be inert. Deferred until a consumer exists.
- Cross-channel and cross-medium descent (DMs, dream consolidation, Oracle, group-chat rooms): slice 1 is one channel. The archive shows the "desync" reading in Science on 2026-04-07 (thread `23b28d8c-b6e2-4396-bff7-26a327a77433`, DM `5a789fa5-2624-43e7-888f-02aa22abf79a`) a day before Medical; slice 1 cannot link it.
- Counselor, bridge-alert and AD-583f provider logic: unchanged; the tracer only feeds them.
- No new EventType, no new store, no LLM call, no `config/system.yaml` edit.

## Follow-ups found during verification (filed as BF-920, #1633; not this AD)

| # | Defect | Evidence |
|---|---|---|
| F1 | The same-thread veto is bypassed by time: `compute_anchor_independence` counts a same-thread pair > 60 s apart as independent, so AD-583g's echo independence is 1.0 for any chain spanning a minute, and its bridge alert (`bridge_alerts.py:578-580`, `< 0.3`) cannot fire. | `social_verification.py:192` and `:381` (`... or _time_separated(...)`); replay: same thread at 0/120/240 s → 1.0; at 0/20/40 s → 0.0. The tests use 5 s gaps (`tests/test_social_verification.py:154-155, 356-358`), hiding it. |
| F2 | `CascadeRiskResult.source_agent` is always the current author: `check_peer_similarity` returns no `timestamp`, so `match.get("timestamp", inf)` never beats `inf`. | `threads.py:50-56, 69-75` (keys: author_id, author_callsign, body_preview, similarity, post_id); `social_verification.py:509-537`; the test feeds fabricated timestamps (`tests/test_social_verification.py:339-342`) — a half-chain test. |
| F3 | `CASCADE_CONFABULATION_DETECTED` is emitted twice per detection (service and helper), so the Counselor handles it twice. | `social_verification.py:609-618`; `_helpers.py:41-48`. |
| F4 | The AD-583f observable-mismatch bridge alert is built and dropped. | `_helpers.py:139-144` discards the list `check_observable_mismatch` returns (`bridge_alerts.py:608-631`). |
| F5 | Inert AD-567f surface: `check_corroboration`, `get_verification_context` and `BridgeAlertService.check_cascade_risk` have no production caller; `SystemHealthProvider` is imported but never registered. | Absence enumeration below; `finalize.py:5856, 5863-5867`. |

## Tracking

- `PROGRESS.md`: AD-1349 S1 entry with the replay numbers and the default-OFF alerting decision.
- `DECISIONS.md`: AD-1349 — "dependence by shared distinctive reading is a trigger, never an alarm; the alarm is a conjunctive error (shared reading contradicted by ship state, >= 2 witnesses); alerting ships OFF pending measured provider precision".
- `docs/development/roadmap.md`: the AD row; the Follow-ups BF row when it is filed.

## Acceptance Criteria

1. The 2026-04-08-shaped sequence (test 15 and seam test 22) triggers with Chapel as origin, and the alert reaches `OBSERVABLE_STATE_MISMATCH` once, origin first.
2. Dependence without a contradicted claim never emits (tests 18, 20, 23).
3. A trace never blocks or fails a post (test 19; helper catches and logs at WARNING).
4. No log line, event or alert carries post content (test 23).
5. All four pinned snapshots updated with inline reasons; `check_config_facade.py --check` and `gen_config_reference.py --check` pass; `config/system.yaml` untouched.
6. After merge, the Captain reviews the `AD-1349 shared-error trace` INFO lines from the live ship for at least seven days (trigger count, `conjunctive=True` count, a hand check of each conjunctive verdict) before `shared_error_alerts_enabled` is flipped; that flip is S2.
7. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Prior Art and Blind Spots

| Source | Decision |
|---|---|
| Common-errors method / Leitfehler (Maas; [Parvum Lexicon Stemmatologicum: Common errors method](https://wiki.helsinki.fi/xwiki/bin/view/stemmatology/Common%20errors%20method/), [Error, indicative or significant](https://wiki.helsinki.fi/xwiki/bin/view/stemmatology/Error,%20indicative%20or%20significant/)) | **Absorbed.** Only significant (conjunctive) shared readings link witnesses; shared ordinary readings prove nothing. Implemented as distinctive-detail extraction plus the alarm-only-on-contradicted-reading rule. |
| Polygenesis ([Parvum Lexicon: Polygenesis](https://wiki.helsinki.fi/xwiki/bin/view/stemmatology/Polygenesis/)) | **Adapted.** A reading present in the channel baseline is the archetype, excluded from linking. Blind spot kept open: crew on one model family may coin the same compound independently ("shared imagination", [summary](https://www.promptlayer.com/research-papers/shared-imagination-llms-hallucinate-alike)); the baseline absorbs a model's habitual coinages over time, but a first-time shared coinage can still be polygenetic. That is why the alarm also needs the verifier's contradiction. |
| Maximum-parsimony / phylogenetic stemma reconstruction | **Rejected for S1.** Connected components answer "one branch or several" without a tree; contamination makes trees unreliable and union-find is conservative under it. |
| MemeTracker (Leskovec, Backstrom, Kleinberg, KDD 2009; [inference follow-up](https://arxiv.org/pdf/1006.0234)) | **Adapted.** Track short distinctive phrase variants, clustered by normalization (our `52 minutes` = `52-minute`; without it the origin moves from Chapel to Sinclair, measured). Their noted limit, that phrase data shows when a source used a phrase but not where it got it, is why our origin is "earliest extant witness", documented as a hypothesis. |
| AWS Well-Architected agentic lens ([AGENTSEC01-BP03](https://docs.aws.amazon.com/wellarchitected/latest/agentic-ai-lens/agentsec01-bp03.html)): flag fabrications at memory entry and propagate to readers | **Considered, deferred.** Memory-write gating is a larger design and would widen this AD. |
| Internal: AD-567f (circular reporting), AD-583/583f/583g, AD-1119 referents, case study 2026-04-08 | Reused: verifier, Counselor path, bridge alerts, `extract_referents`. AD-583's "~0.0" premise is refuted by replay (Problem). |

`docs/research/reference-projects.md` (date used: 2026-10-22): no listed project addresses cross-agent claim provenance; none examined, no rows updated. AG-UI (never reviewed) considered, deferred as irrelevant here.

Other blind spots: (a) restarts lose the alert-dedup memory (bridge-alert dedup still applies); (b) a high-traffic channel can exceed the 50-item window, so long cascades are traced piecewise; (c) the baseline is per channel, so a reading common ship-wide but new to a channel can link (acceptable: it still needs a contradicted claim to alarm).

---

## Verified Against Codebase (2026-10-22)

```
grep -n "def _are_independently_anchored\|def _time_separated\|elif _are_independently_anchored\|if _are_independently_anchored(a, b) or _time_separated" src/probos/cognitive/social_verification.py
  72: def _are_independently_anchored(anchors_a: Any, anchors_b: Any) -> bool:
  109: def _time_separated(ep_a: Any, ep_b: Any, threshold: float = 60.0) -> bool:
  192: elif _are_independently_anchored(a, b) or _time_separated(episodes[i], episodes[j]):
  381: if _are_independently_anchored(a, b) or _time_separated(ep, other):
grep -n "match_ts = match.get\|source_agent = match_callsign\|EventType.CASCADE_CONFABULATION_DETECTED.value" src/probos/cognitive/social_verification.py
  514: match_ts = match.get("timestamp", float("inf"))
  537: source_agent = match_callsign
  614: EventType.CASCADE_CONFABULATION_DETECTED.value,
grep -n "async def check_peer_similarity\|\"post_id\": row\[0\]\|def set_echo_services\|async def _check_echo_trace\|await self._check_echo_trace\|async def get_thread_posts_temporal\|self._social_verification: Any = None" src/probos/ward_room/threads.py
  23: async def check_peer_similarity(
  55/74: "post_id": row[0],
  162: self._social_verification: Any = None  # AD-567f: late-bound
  180: def set_echo_services(
  206: async def _check_echo_trace(
  562: await self._check_echo_trace(peer_matches, thread.id, channel_id)
  759: async def get_thread_posts_temporal(self, thread_id: str) -> list[dict[str, Any]]:
grep -n "self._social_verification: Any = None\|def set_echo_services\|async def _check_echo_trace\|peer_matches = await check_peer_similarity\|await self._check_echo_trace\|source_timestamp=post.created_at\|channel_id=channel_name" src/probos/ward_room/messages.py
  39: self._social_verification: Any = None  # AD-567f: late-bound
  57: def set_echo_services(
  127: async def _check_echo_trace(
  206: peer_matches = await check_peer_similarity(
  310: await self._check_echo_trace(peer_matches, thread_id, thread_channel_id)
  347: channel_id=channel_name,
  353: source_timestamp=post.created_at,  # AD-577
grep -n "async def check_and_emit_cascade_risk\|_ET.CASCADE_CONFABULATION_DETECTED\|async def check_and_trace_echo\|bridge_alerts.check_observable_mismatch\|_thread_manager.get_thread_posts_temporal" src/probos/ward_room/_helpers.py
  20: async def check_and_emit_cascade_risk(
  46: _ET.CASCADE_CONFABULATION_DETECTED,
  53: async def check_and_trace_echo(
  107: posts = await thread_echo_analyzer._thread_manager.get_thread_posts_temporal(
  140: bridge_alerts.check_observable_mismatch({
grep -n "similarity_threshold: float = 0.4\|if sim >= self._similarity_threshold\|independence = compute_anchor_independence(episodes)" src/probos/ward_room/thread_echo.py
  67: similarity_threshold: float = 0.4,
  115: if sim >= self._similarity_threshold:
  151: independence = compute_anchor_independence(episodes)
grep -n "self._threads = ThreadManager\|def set_echo_services\|async def count_threads\|async def create_thread\|async def create_post" src/probos/ward_room/service.py
  145: self._threads = ThreadManager(
  187: def set_echo_services(
  348: async def count_threads(self, channel_id: str) -> int:
  411: async def create_thread(
  455: async def create_post(
grep -n "AD-583f/583g: Observable State\|providers.append(RecreationStateProvider\|providers.append(TrustStateProvider\|SystemHealthProvider,\|runtime.ward_room.set_echo_services(" src/probos/startup/finalize.py
  5849: # --- AD-583f/583g: Observable State Verification + Source Tracing ---
  5856: SystemHealthProvider,
  5865: providers.append(RecreationStateProvider(runtime.recreation_service))
  5867: providers.append(TrustStateProvider(runtime.trust_network))
  5885: runtime.ward_room.set_echo_services(
grep -n "async def verify_claims\|if \"stuck\" in claim_lower\|if \"anomaly\" in claim_lower\|class SystemHealthProvider" src/probos/cognitive/observable_state.py
  63: async def verify_claims(
  156: if "stuck" in claim_lower or "stale" in claim_lower:
  226: if "anomaly" in claim_lower:
  266: class SystemHealthProvider:
grep -n "OBSERVABLE_STATE_MISMATCH\|CASCADE_CONFABULATION_DETECTED =" src/probos/events.py src/probos/event_persistence.py
  events.py:217: CASCADE_CONFABULATION_DETECTED = "cascade_confabulation_detected"  # AD-567f
  events.py:229: OBSERVABLE_STATE_MISMATCH = "observable_state_mismatch"  # AD-583f
  event_persistence.py:318: "OBSERVABLE_STATE_MISMATCH",   (GRANDFATHERED)
grep -n "OBSERVABLE_STATE_MISMATCH.value\|async def _on_observable_mismatch\|for callsign in agents\[:3\]" src/probos/cognitive/counselor.py
  1048: elif event_type == EventType.OBSERVABLE_STATE_MISMATCH.value:
  2004: async def _on_observable_mismatch(self, data: dict[str, Any]) -> None:
  2018: for callsign in agents[:3]:  # Limit DMs
grep -n "def check_observable_mismatch\|dedup_key = f\"state_mismatch" src/probos/bridge_alerts.py
  608: def check_observable_mismatch(self, verification_result: dict) -> list[BridgeAlert]:
  615: dedup_key = f"state_mismatch:{thread_id}"
grep -n "async def deliver_bridge_alert" src/probos/ward_room_router.py
  1181: async def deliver_bridge_alert(self, alert: Any) -> None:
grep -n "class SourceTracingConfig\|echo_analysis_enabled: bool = True\|^from pydantic import" src/probos/config_models/knowledge.py
  10: from pydantic import BaseModel, Field, field_validator, model_validator
  399: class SourceTracingConfig(BaseModel):
  404: echo_analysis_enabled: bool = True
grep -n "'SourceTracingConfig': {\|\"SourceTracingConfig\": 0" tests/test_ad1270e2f_knowledge_models.py
  265: 'SourceTracingConfig': {   'echo_min_chain_length': 3,
  476: "SourceTracingConfig": 0,
grep -n "field_definitions\"\] == \|_SCRIPT = " tests/test_ad1270e1_config_facade.py
  46: _SCRIPT = _REPO_ROOT / "scripts" / "check_config_facade.py"
  1553: assert counts["field_definitions"] == 1869
grep -n "\"--update-baseline\"\|\"--check\"" scripts/check_config_facade.py scripts/gen_config_reference.py
  check_config_facade.py:1711/1716; gen_config_reference.py:191
grep -n "^class Referent\|^def extract_referents\|^def _strip_code_spans" src/probos/cognitive/referent_gate.py
  145: class Referent:   (token, kind, raw, claim_confidence)
  182: def _strip_code_spans(text: str) -> str:
  219: def extract_referents(text: str) -> list[Referent]:
grep -n "jaccard_similarity\|def text_to_words" src/probos/cognitive/similarity.py
  4: def jaccard_similarity(a: set[str], b: set[str]) -> float:
  17: def text_to_words(text: str) -> set[str]:
```

## Absence Verified (2026-10-22)

```
CLAIM: nothing in src/ calls check_corroboration or get_verification_context except the service itself
RUN:   Grep "verification_context|check_corroboration" over the repo (prompts/archive excluded)
FOUND: src/probos/cognitive/social_verification.py (definitions + self-call at :633), tests/test_social_verification.py, two docs
HOLDS: yes

CLAIM: BridgeAlertService.check_cascade_risk has no caller
RUN:   Grep "check_cascade_risk|check_ward_room_echo" src/ (excluding social_verification.py)
FOUND: bridge_alerts.py:806 (definition only); the other hits are the ward-room wrappers of SocialVerificationService.check_cascade_risk
HOLDS: yes

CLAIM: check_peer_similarity matches carry no timestamp
RUN:   Read src/probos/ward_room/threads.py:23-81
FOUND: match dict keys author_id, author_callsign, body_preview, similarity, post_id (both queries)
HOLDS: yes

CLAIM: no content-based (shared-reading / stemmatic) dependence exists in the codebase
RUN:   Grep "(?i)stemma|stemmatic|shared error|shared-error|witness count|effective witness|phylogen|idiosyncratic|content-based dependence|lexical fingerprint|distinctive detail" over the repo
FOUND: one hit, docs/development/roadmap-era-5-completed.md:3871 ("idiosyncratic", unrelated)
HOLDS: yes; the nearest existing mechanisms are Jaccard similarity (AD-506b, AD-583g, AD-554) and AD-1119 referent grounding (group-chat seeds only)

CLAIM: no test calls set_echo_services
RUN:   Grep "set_echo_services|ThreadEchoAnalyzer" tests/
FOUND: tests/test_ad583g_source_tracing.py constructs ThreadEchoAnalyzer only; no set_echo_services
HOLDS: yes
```

## Live-data evidence (read-only, 2026-10-22)

Replays ran with `mode=ro` SQLite URIs against the shipped functions imported from `src/` (scripts kept outside the repository). Nothing was written; the vessel was not started or stopped.

| Measurement | Source | Result |
|---|---|---|
| Canonical cascade survives | `archives/ward_room_2026-04-16_010400.db` (62,486 posts, 16,256 threads) | Medical 2026-04-08: Chapel threads `cbf565ea-6d58-46fc-b3af-d9a6d7e40c67` (19:21:58), `7d37b882-56be-4a48-8fe2-1f1f6bf81b8c` (19:57:19); Sinclair, Keiko, Cortez replies through 20:13; Captain's correction 20:12 |
| AD-506b trigger on the cascade | same, 16:00-20:12 | 0 of 241 items |
| AD-583g echo on the cascade | same | 0 of 22 threads (max similarity 0.33) |
| Anchor independence (production-shaped) | replay of `compute_anchor_independence` | 1.0 |
| Shared-reading fire rate (dependence) | archive 04-05..04-11; live `ward_room.db` 10-18, 10-22 | 12-25% / 33-52% of posts |
| This slice's trigger | archive 2026-04-08 | 244 of 4,562 posts (5.3%); fires on the cascade at 20:08:32, origin Chapel 19:57:19, shared `n:52 minute` |
| `events.db` history | live `events.db` | 888 rows, 2026-10-18 to 10-22 only; no cascade or echo event in range (retention, not evidence of absence in April) |
