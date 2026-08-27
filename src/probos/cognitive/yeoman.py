"""YeomanAgent — Captain's personal assistant on the Bridge (AD-766).

Bridge-level CognitiveAgent. Acts in the Captain's name for administrative
matters: schedule, correspondence triage, daily briefings, crew delegation,
standing-order relay. The Yeoman is always near the Captain — presence
matters as much as task throughput.

Persona is anchored to the Captain Card (AD-739). Yeo consumes the card's
``to_system_context()`` output as the identity preamble; persona changes
require a runtime restart in v1 (forward marker AD-766a covers live
hot-reload).

Proactive-scan results emitted by ``ProactiveScanAgent`` (probos.proactive)
are aggregated into a single Captain digest within
``yeoman_digest_window_seconds`` so the Bridge isn't flooded one DM per
finding. Quiet-hours and out-of-work-hours scans are queued and skipped
per the existing ``DutySchedule`` policy.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.types import (
    HandlerLatencyClass,
    IntentDescriptor,
    IntentMessage,
    IntentResult,
)

if TYPE_CHECKING:
    from probos.captain_card.card import CaptainCard
    from probos.duty_schedule import DutySchedule

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Default persona — used when no Captain Card is wired (test bootstrap).
# Production runs read the live CaptainCard via initialize().
# ---------------------------------------------------------------------------

_DEFAULT_PERSONA = (
    "You are Yeo, the Captain's personal assistant.\n"
    "Working hours: 08:00-18:00 UTC\n"
    "Voice: Ship's Computer\n"
)


_ROLE_RULES = (
    "\n--- Yeoman role (AD-766) ---\n"
    "- Act in the Captain's name for administrative matters; never make "
    "tactical, financial, or destructive decisions without explicit "
    "Captain approval.\n"
    "- Triage proactive scan results into a single Captain DM digest; "
    "do not flood the bridge.\n"
    "- Delegate specialist work to the right crew member (@-mention) "
    "rather than answering outside your lane.\n"
    "- Maintain the Captain's standing orders and surface conflicts "
    "before they become problems.\n"
)


_YEOMAN_INTENT_DESCRIPTORS = [
    IntentDescriptor(
        name="daily_briefing",
        params={},
        description=(
            "Assemble overnight inbox/calendar/Teams highlights into a "
            "Captain DM"
        ),
        tier="domain",
    ),
    IntentDescriptor(
        name="schedule_lookup",
        params={"window": "today | this_week | YYYY-MM-DD"},
        description="Answer Captain calendar questions (today/this week)",
        tier="domain",
    ),
    IntentDescriptor(
        name="triage_inbox",
        params={"max_items": "max items to surface (default 3)"},
        description=(
            "Summarize unread mail and flag the 1-3 items requiring "
            "Captain attention"
        ),
        tier="domain",
    ),
    IntentDescriptor(
        name="delegate_to_crew",
        params={
            "request": "the work to delegate",
            "specialist_hint": "optional callsign hint",
        },
        description=(
            "Identify the right specialist for a request and @-mention "
            "them in a thread"
        ),
        tier="domain",
    ),
    IntentDescriptor(
        name="relay_standing_order",
        params={
            "department": "target department head",
            "order_text": "the Captain's order to relay",
        },
        description=(
            "Broadcast a Captain order to the named department head"
        ),
        tier="domain",
    ),
]


# Intent names that are pure reads — Yeoman publishes them as
# ``autoApproveReadOnly`` so AD-753/AD-765 unattended modes do not gate them
# behind quorum on every proactive run.
_YEOMAN_READ_ONLY_INTENTS: frozenset[str] = frozenset(
    {"daily_briefing", "schedule_lookup", "triage_inbox"}
)


class YeomanAgent(CognitiveAgent):
    """Captain's personal assistant — Bridge crew, singleton."""

    agent_type = "yeoman"
    tier = "domain"
    department = "Bridge"  # ontology is the source of truth; this is documentation
    callsign = "Yeo"

    _handled_intents = {
        "daily_briefing",
        "schedule_lookup",
        "triage_inbox",
        "delegate_to_crew",
        "relay_standing_order",
    }

    intent_descriptors = list(_YEOMAN_INTENT_DESCRIPTORS)
    read_only_intents: frozenset[str] = _YEOMAN_READ_ONLY_INTENTS

    instructions = _DEFAULT_PERSONA + _ROLE_RULES

    # Class-level singleton counter — Captain has exactly one Yeoman.
    _live_instance_count: int = 0

    def __init__(self, **kwargs: Any) -> None:
        # Singleton guard at the class level. Runtime registration MUST
        # spawn this agent exactly once; constructing a second instance
        # is a hard error so test bugs are caught at boot, not at use.
        if YeomanAgent._live_instance_count >= 1:
            raise RuntimeError(
                "YeomanAgent is a singleton; one instance is already live. "
                "Spawn the existing instance from runtime.registry instead "
                "of constructing a new one (AD-766)."
            )

        kwargs.setdefault("pool", "yeoman")
        super().__init__(**kwargs)
        YeomanAgent._live_instance_count += 1

        # Wired by initialize() once runtime infrastructure is available.
        self._captain_card: CaptainCard | None = None
        self._duty_schedule: DutySchedule | None = None
        self._proactive_sub_id: str = ""
        self._digest_window_seconds: float = 60.0

        # Aggregation buffer for proactive_scan results.
        self._scan_buffer: list[dict[str, Any]] = []
        self._buffer_lock = asyncio.Lock()
        self._flush_task: asyncio.Task[None] | None = None
        # Outbound DM dispatch tasks — kept to avoid fire-and-forget.
        self._pending_dispatch_tasks: set[asyncio.Task[None]] = set()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def stop(self) -> None:
        """Cancel flush task + dispatch tasks before the agent unwires."""
        if self._flush_task is not None and not self._flush_task.done():
            self._flush_task.cancel()
            try:
                await self._flush_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        for task in list(self._pending_dispatch_tasks):
            if not task.done():
                task.cancel()
        await super().stop()
        YeomanAgent._live_instance_count = max(
            0, YeomanAgent._live_instance_count - 1,
        )

    async def initialize(
        self,
        *,
        captain_card: "CaptainCard | None" = None,
        duty_schedule: "DutySchedule | None" = None,
        digest_window_seconds: float | None = None,
    ) -> None:
        """Wire runtime references and subscribe to proactive scans.

        Called by ``startup/agent_fleet.py`` after the runtime has loaded
        the Captain Card and built the duty schedule.
        """
        self._captain_card = captain_card
        self._duty_schedule = duty_schedule
        if digest_window_seconds is not None:
            self._digest_window_seconds = max(0.0, float(digest_window_seconds))

        # Adopt Captain Card persona — drop the bootstrap default.
        if captain_card is not None:
            try:
                persona = captain_card.to_system_context()
                self.instructions = persona + _ROLE_RULES
                logger.info(
                    "AD-766: YeomanAgent adopted Captain Card persona for %s",
                    captain_card.name,
                )
            except Exception:
                logger.warning(
                    "AD-766: Captain Card to_system_context() failed; "
                    "YeomanAgent retains default persona until next restart",
                    exc_info=True,
                )

        # Subscribe to the proactive_scan bus intent so we can aggregate.
        # The architect review (OQ#5) verified that the bus emits a single
        # ``proactive_scan`` intent today with ``scan_types`` in params —
        # there are no per-type ``proactive_scan_inbox`` events. We dispatch
        # by scan_type inside the handler.
        runtime = self._runtime
        if runtime is None or not hasattr(runtime, "intent_bus"):
            logger.warning(
                "AD-766: YeomanAgent has no runtime/intent_bus reference; "
                "proactive-scan aggregation disabled until restart",
            )
            return

        self._proactive_sub_id = f"yeoman-proactive-{self.id[:8]}"
        try:
            runtime.intent_bus.subscribe(
                self._proactive_sub_id,
                self._handle_proactive_scan,
                intent_names=["proactive_scan"],
                latency_class=HandlerLatencyClass.DETERMINISTIC,
            )
            logger.info(
                "AD-766: YeomanAgent subscribed to proactive_scan (subscriber=%s)",
                self._proactive_sub_id,
            )
        except Exception:
            logger.warning(
                "AD-766: YeomanAgent failed to subscribe to proactive_scan; "
                "Captain digests will not fire until next restart",
                exc_info=True,
            )

    # ------------------------------------------------------------------
    # Conversational capability grounding (BF-599)
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # AD-983a: live-capability grounding (the [MESH] do-and-report affordance)
    # was generalized to the base CognitiveAgent._conversational_capability_block
    # — it now renders the usage_hint of every reachable capability for ALL crew,
    # so the Yeoman-specific override (BF-599/BF-601) and the
    # _available_mesh_read_intents helper are retired. Yeo keeps only its
    # role-specific delegation JUDGMENT (the [CREATE_TASK] threshold below).
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Conversational task-creation protocol (AD-845)
    # ------------------------------------------------------------------

    def _conversational_task_protocol(self, observation: dict) -> str:
        """Teach Yeo its role-specific delegation JUDGMENT from a 1:1 chat reply.

        The four-tier threshold, minus the parts now carried elsewhere:
        Tier 1 (Answer): reply directly, no tag. Tier 2 (Do-and-report,
        AD-869): the ``[MESH ...]`` do-and-report affordance is now taught to
        ALL crew by the base ``_conversational_capability_block`` (AD-983a) — it
        is no longer Yeo-specific, so it is not repeated here. Tier 3
        (Write-it-down, AD-845): substantial work or anything that changes state
        — emit ``[CREATE_TASK title=... | instructions=... |
        specialist=@Callsign]`` to open a dispatchable tracked task. The
        specialist callsign is Tier 4 (Get-help). This task-creation judgment IS
        the genuinely role-specific piece Yeo keeps.

        Yeo's static ``instructions``/``_ROLE_RULES`` never reach the
        conversational prompt (composed with ``hardcoded_instructions=""``),
        so this protocol is injected here.

        Honest-degrade: the ``[CREATE_TASK]`` guidance is taught only when a
        work-item store is wired — Yeo is never told it can open tasks it
        cannot back. Returns "" when no store is available. All tag text is
        gap-regex-safe (BF-599 lesson).
        """
        runtime = self._runtime
        if runtime is None:
            return ""
        has_store = getattr(runtime, "work_item_store", None) is not None
        if not has_store:
            return ""

        parts: list[str] = [
            "\n\nDelegation threshold — choose the lightest action that fits "
            "the request:",
            "\n- If you already know the answer, just reply. No tag.",
            "\n- For a quick read-only lookup you can finish this turn, use the "
            "ship-capability tags listed above — the result is fetched and "
            "shown to the Captain inline.",
            "\n- If it is substantial work, would take longer than a "
            "quick reply, or would change something, open a tracked task "
            "instead of answering inline: emit [CREATE_TASK title=<short "
            "title> | instructions=<what to do> | specialist=@Callsign] "
            "anywhere in your reply, and confirm conversationally that "
            "you have opened the task and will report back when it is "
            "done. Choose the specialist by department (@Number One for "
            "Science research). The task runs on the mesh and appears on "
            "the Captain's board automatically.",
            "\nRule of thumb: if you can get the answer in the time it takes "
            "to reply and it changes nothing, just do it; otherwise write it "
            "down as a task.",
        ]
        return "".join(parts)

    # ------------------------------------------------------------------
    # Conversational notebook-save protocol: AD-912 generalized it to the
    # base CognitiveAgent hook (any crew agent can save a note from a 1:1
    # chat), so Yeo no longer needs a Yeoman-specific override.
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Proactive-scan aggregation
    # ------------------------------------------------------------------

    async def _handle_proactive_scan(
        self, intent: IntentMessage,
    ) -> IntentResult | None:
        """Buffer a proactive_scan event; schedule digest emission.

        Returns None (silent accept) — proactive_scan is fire-and-forget.
        Quiet-hours and out-of-work-hours emissions are dropped before
        buffering so the digest stays inside the policy window.
        """
        params = intent.params or {}
        scan_types = list(params.get("scan_types") or [])
        suppressed = dict(params.get("suppressed_reasons") or {})

        # Quiet-hours gate — if every scan_type is suppressed by the duty
        # schedule with a quiet/work-hours reason, this is a heartbeat that
        # the Captain explicitly does not want surfaced now. Queue is OK
        # but emission is not.
        if self._duty_schedule is not None and not scan_types:
            # Nothing allowed by policy right now. Treat as queued — buffer
            # but do not schedule a flush. Next allowed scan will trigger
            # one digest covering the queued results.
            async with self._buffer_lock:
                self._scan_buffer.append({
                    "ts": time.time(),
                    "scan_types": [],
                    "suppressed_reasons": suppressed,
                    "queued": True,
                })
            logger.debug(
                "AD-766: YeomanAgent queued suppressed scan (reasons=%s); "
                "no digest scheduled until policy allows",
                suppressed,
            )
            return None

        async with self._buffer_lock:
            self._scan_buffer.append({
                "ts": time.time(),
                "scan_types": scan_types,
                "suppressed_reasons": suppressed,
                "queued": False,
            })

        self._schedule_flush()
        return None

    def _schedule_flush(self) -> None:
        """Start a digest-flush timer if one is not already running."""
        if self._flush_task is not None and not self._flush_task.done():
            return  # An aggregation window is already in progress.
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop — likely a unit-test synchronous path. The
            # caller can drain via flush_now() instead.
            return
        self._flush_task = loop.create_task(
            self._flush_after_window(),
            name=f"yeoman-digest-flush-{self.id[:8]}",
        )

    async def _flush_after_window(self) -> None:
        """Wait the digest window, then emit a single Captain DM."""
        try:
            if self._digest_window_seconds > 0:
                await asyncio.sleep(self._digest_window_seconds)
            await self.flush_now()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "AD-766: YeomanAgent digest flush failed; buffer retained "
                "for the next scan-triggered flush",
                exc_info=True,
            )

    async def flush_now(self) -> dict[str, Any] | None:
        """Drain the buffer and emit one Captain digest. Returns the digest dict."""
        async with self._buffer_lock:
            if not self._scan_buffer:
                return None
            entries = list(self._scan_buffer)
            self._scan_buffer.clear()

        digest = self._build_digest(entries)
        await self._emit_digest(digest)
        return digest

    def _build_digest(self, entries: list[dict[str, Any]]) -> dict[str, Any]:
        """Roll N scan buffer entries into one structured Captain brief."""
        all_types: list[str] = []
        all_suppressed: dict[str, str] = {}
        queued_count = 0
        first_ts = entries[0]["ts"]
        last_ts = entries[-1]["ts"]
        for entry in entries:
            if entry.get("queued"):
                queued_count += 1
            for scan_type in entry.get("scan_types") or []:
                if scan_type not in all_types:
                    all_types.append(scan_type)
            for k, v in (entry.get("suppressed_reasons") or {}).items():
                # Last-write-wins is OK — reasons are stable strings.
                all_suppressed[k] = v
        return {
            "source": "yeoman",
            "window_start": first_ts,
            "window_end": last_ts,
            "scan_count": len(entries),
            "scan_types": all_types,
            "suppressed_reasons": all_suppressed,
            "queued_count": queued_count,
        }

    async def _emit_digest(self, digest: dict[str, Any]) -> None:
        """Broadcast a single Captain direct_message with the digest payload."""
        runtime = self._runtime
        if runtime is None or not hasattr(runtime, "intent_bus"):
            logger.warning(
                "AD-766: YeomanAgent has no intent_bus to emit digest; "
                "scan_count=%d dropped",
                digest.get("scan_count", 0),
            )
            return
        dm = IntentMessage(
            intent="direct_message",
            params={
                "text": _render_digest_text(digest),
                "from": "yeoman",
                "to": "captain",
                "kind": "yeoman_digest",
                "digest": digest,
            },
        )
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            await runtime.intent_bus.broadcast(dm)
            return
        task = loop.create_task(
            runtime.intent_bus.broadcast(dm),
            name=f"yeoman-digest-emit-{self.id[:8]}",
        )
        self._pending_dispatch_tasks.add(task)
        task.add_done_callback(self._pending_dispatch_tasks.discard)
        task.add_done_callback(self._report_digest_task_failure)

    def _report_digest_task_failure(self, task: asyncio.Task) -> None:
        """AD-1276: retrieve the digest broadcast's exception rather than lose it.

        ``discard`` was the only done-callback, so nothing ever called
        ``task.exception()`` and ANY failure of this broadcast vanished --
        surfacing at best as an "exception was never retrieved" warning at
        garbage-collection time, detached from the code that caused it.

        Not the cause #1253 states. A policy denial is NOT one of these
        exceptions: ``broadcast``'s default denial shape is ``[]``, and this
        call does not opt into ``raise_on_denial``. The real defect is broader
        and simpler -- every exception from this task was silent.
        """
        if task.cancelled():
            return  # cancellation is lifecycle control, not a fault
        exc = task.exception()
        if exc is None:
            return
        logger.error(
            "AD-1276: the Yeoman digest broadcast failed with %s; the Captain "
            "will not receive this digest",
            type(exc).__name__,
            exc_info=exc,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Department callsigns Yeo delegates to. Pure data so tests can inspect.
DELEGATION_MAP: dict[str, str] = {
    "medical": "Bones",
    "engineering": "LaForge",
    "science": "Number One",
    "security": "Worf",
    "operations": "O'Brien",
    "counseling": "Troi",
}


def resolve_delegate(request: str) -> str | None:
    """Return the crew callsign best suited for ``request``, or None.

    Pure keyword routing — the LLM still does the heavy lifting at runtime
    through ``instructions``. This helper exists for the structured
    ``delegate_to_crew`` test path and as a safe fallback when the LLM
    declines to pick a specialist.
    """
    text = (request or "").lower()
    keyword_map = {
        "medical": ("medical", "health", "patient", "diagnos", "treatment"),
        "engineering": ("engineering", "system", "power", "warp", "hardware"),
        "science": ("research", "analyze", "study", "sensor", "experiment"),
        "security": ("security", "tactical", "threat", "weapon", "defense"),
        "operations": ("logistics", "supply", "schedule", "coordinate", "ops"),
        "counseling": ("morale", "wellness", "stress", "counsel", "burnout"),
    }
    for department, keywords in keyword_map.items():
        if any(kw in text for kw in keywords):
            return DELEGATION_MAP.get(department)
    return None


def _render_digest_text(digest: dict[str, Any]) -> str:
    """Render a Captain-facing digest summary string."""
    lines = [
        f"Yeo digest — {digest.get('scan_count', 0)} scan(s) in window.",
    ]
    scan_types = digest.get("scan_types") or []
    if scan_types:
        lines.append("  Active: " + ", ".join(scan_types))
    suppressed = digest.get("suppressed_reasons") or {}
    if suppressed:
        lines.append(
            "  Suppressed: "
            + ", ".join(f"{k}={v}" for k, v in suppressed.items())
        )
    queued = digest.get("queued_count") or 0
    if queued:
        lines.append(f"  Queued (policy): {queued}")
    return "\n".join(lines)
