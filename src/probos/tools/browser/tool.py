"""AD-706: BrowserTool — agent-driven Chromium browser via Playwright.

Plugs into the AD-423a Tool Layer. One ``BrowserTool`` instance is registered
in the ``ToolRegistry``; it owns a pool of ``BrowserSession`` instances keyed
by ``session_id``. Actions are dispatched through ``invoke(params, context)``.

Safety guidelines (verbatim from anthropics/claude-quickstarts/computer-use-demo, MIT):

1. Use a dedicated virtual machine or container with minimal privileges to
   prevent direct system attacks or accidents.
2. Avoid giving the model access to sensitive data, such as account login
   information, to prevent information theft.
3. Limit internet access to an allowlist of domains to reduce exposure to
   malicious content.
4. Ask a human to confirm decisions that may result in meaningful real-world
   consequences as well as any tasks requiring affirmative consent, such as
   accepting cookies, executing financial transactions, or agreeing to terms
   of service.

Source: anthropics/claude-quickstarts/computer-use-demo, MIT-licensed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from probos.events import EventType
from probos.tools.browser.actions import action_verify, classify_action, dispatch_action
from probos.tools.browser.loop_host import shutdown_playwright_host
from probos.tools.browser.session import BrowserSession
from probos.tools.protocol import ToolResult, ToolType

if TYPE_CHECKING:
    from probos.config import BrowserToolConfig
    from probos.security.audit import AuditLog

logger = logging.getLogger(__name__)


# Strict allowlist of keys permitted in the audit row's ``detail`` JSON (D5).
# Defense-in-depth against credential leakage. Any new key requires an explicit
# AD revision before being added here.
_AUDIT_DETAIL_ALLOWLIST: frozenset[str] = frozenset({
    "session_id",
    "action",
    "agent_id",
    "success",
    "error",
    "tier",
    "url_sanitized",
})

# BF-701: the agent-facing action vocabulary, declared ONCE.
#
# This used to be written out three times — in ``description``, in
# ``input_schema``'s enum, and again as a set literal inside ``invoke()``. AD-1160
# added ``key_type`` to the first two and missed the third, so the tool spent its
# entire life advertising an action it then refused: the description promised a
# "12-action vocabulary", the schema enum listed twelve, and the gate admitted
# eleven. An agent that read the documentation and called ``key_type`` was told
# ``unknown browser action: 'key_type'``.
#
# That is exactly what happened on the reference vessel. The trace shows the
# agent do the right thing in three calls — ``state``, ``click`` the document
# surface, then ``key_type`` — get refused, and spend the remaining seventeen
# steps guessing at CSS selectors and canvas coordinates before a ``goto``
# reloaded the page and discarded the work.
#
# Ordered because the schema enum and the description read better in a stable
# order; the gate uses the frozenset below. Deriving both from one tuple is the
# point: the gate can no longer disagree with what the agent was told.
#
# This tuple is the AGENT-facing surface only. ``actions._HANDLERS`` also
# registers privileged verbs (``eval_js``, ``fill_credential``, ``upload_file``,
# ``download``, ``drag``, ``key_combo``, ``mouse_move``, ``mouse_button``,
# ``compute_use_click``) which are deliberately NOT offered here and reach the
# tool through their own entry points. Adding a verb to this tuple exposes it to
# every agent — confirm ``classify_action`` assigns it a tier first.
_AGENT_ACTIONS: tuple[str, ...] = (
    "goto", "state", "click", "type", "key_type", "scroll",
    "screenshot", "wait", "back", "forward", "extract_text", "verify",
)
_AGENT_ACTION_SET: frozenset[str] = frozenset(_AGENT_ACTIONS)


class BrowserTool:
    """AD-706 Tool implementation. Tool Protocol structural subtype."""

    def __init__(
        self,
        *,
        config: BrowserToolConfig,
        audit_log: AuditLog | None = None,
        emit_event: Any | None = None,
        runtime: Any | None = None,
    ) -> None:
        self._config = config
        self._audit_log = audit_log
        self._emit_event = emit_event
        self._runtime = runtime  # AD-706c-1: for vision-LLM verify action
        self._sessions: dict[str, BrowserSession] = {}
        # Token -> {token, session_id, action, params, created_at}
        self._pending_confirmations: dict[str, dict[str, Any]] = {}
        # Lazily-started reaper task; reference held per Async Discipline.
        self._reaper_task: asyncio.Task[Any] | None = None
        self._reaper_stop = asyncio.Event()
        # Allow tests to substitute a session factory.
        self._session_factory: Any = BrowserSession
        # AD-706a: Captain-watch streaming viewer accounting. Public API
        # (acquire_viewer_slot / release_viewer_slot / active_viewers) so the
        # streaming router doesn't reach across module boundaries - Demeter.
        self._active_viewers: int = 0
        self._viewer_lock = asyncio.Lock()
        # AD-1052c: session_ids that have had >=1 forwarded input (the "drive
        # episode" latch). session_ids are uuid4 (never reused) so this set
        # never needs cleanup. Emits BROWSER_INPUT_FORWARDED once per session.
        self._driven_sessions: set[str] = set()

    # ------------------------------------------------------------------
    # Tool Protocol surface
    # ------------------------------------------------------------------

    @property
    def tool_id(self) -> str:
        return "browser"

    @property
    def name(self) -> str:
        return "Browser"

    @property
    def tool_type(self) -> ToolType:
        return ToolType.BROWSER

    @property
    def description(self) -> str:
        return (
            f"Drive a Chromium browser. {len(_AGENT_ACTIONS)}-action vocabulary: "
            + ", ".join(_AGENT_ACTIONS)
            + ". Use state() to get an indexed list of clickable elements, then "
            "click by index. To enter text into an editing surface that is not a "
            "form field — a document body, a canvas editor — click it first, then "
            "use key_type, which types into whatever now has focus."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["action"],
            "properties": {
                "action": {
                    "type": "string",
                    "enum": list(_AGENT_ACTIONS),
                },
                "session_id": {"type": "string", "description": "Reuse an existing session, or omit to create a fresh one."},
                "url": {"type": "string"},
                "index": {"type": "integer"},
                "selector": {"type": "string"},
                "text": {"type": "string"},
                "delay_ms": {"type": "integer", "description": "AD-1160: 'key_type' action — milliseconds between keystrokes (0-250). Omit for none. Canvas apps such as Word Online drop text typed at full speed."},
                "direction": {"type": "string", "enum": ["up", "down", "left", "right"]},
                "amount": {"type": "integer"},
                "milliseconds": {"type": "integer"},
                "seconds": {"type": "number"},
                "timeout_ms": {"type": "integer"},
                "confirmation_token": {"type": "string", "description": "Captain-issued token for tier-3 actions."},
                "expectation": {"type": "string", "description": "AD-706c-1: 'verify' action — natural-language statement to verify against the current screenshot."},
            },
        }

    @property
    def output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "url": {"type": "string"},
                "page_title": {"type": "string"},
                "screenshot_b64": {"type": "string"},
                "elements": {"type": "array"},
                "text": {"type": "string"},
                "intervention_required": {"type": "boolean"},
                "tier": {"type": "integer"},
            },
        }

    # ------------------------------------------------------------------
    # Public lifecycle
    # ------------------------------------------------------------------

    async def stop(self) -> None:
        """Stop the reaper task and close all live sessions."""
        if self._reaper_task is not None:
            self._reaper_stop.set()
            try:
                self._reaper_task.cancel()
            except Exception:
                logger.debug("AD-706: reaper task cancel failed", exc_info=True)
            try:
                await self._reaper_task
            except (asyncio.CancelledError, Exception):
                pass
            self._reaper_task = None
        for sid in list(self._sessions.keys()):
            session = self._sessions.pop(sid, None)
            if session is not None:
                try:
                    await session.stop()
                except Exception:
                    logger.debug("AD-706: session %s stop failed", sid, exc_info=True)
        # BF-695: every session is closed, so the Playwright host thread (if one
        # was ever needed) has no owner left. Closing it here pairs the lazy
        # start in ``BrowserSession.start``. The host is process-wide and
        # restartable, so a later session simply builds a fresh thread.
        await shutdown_playwright_host()

    async def reap_expired(self) -> int:
        """One-shot expiry sweep — closes any expired sessions. Returns count.

        Public so tests can drive the reaper deterministically without
        starting the background task.
        """
        closed = 0
        for sid in list(self._sessions.keys()):
            session = self._sessions.get(sid)
            if session is not None and session.is_expired():
                try:
                    await session.stop()
                except Exception:
                    logger.debug("AD-706: session %s stop failed", sid, exc_info=True)
                self._sessions.pop(sid, None)
                self._safe_emit(
                    EventType.BROWSER_SESSION_CLOSED,
                    {"session_id": sid, "reason": "expired"},
                )
                closed += 1
        # Opportunistically prune expired confirmation tokens (D6 #5).
        now = time.time()
        ttl = float(self._config.confirmation_timeout_seconds)
        for token in list(self._pending_confirmations.keys()):
            entry = self._pending_confirmations.get(token)
            if entry and (now - float(entry.get("created_at", 0.0))) >= ttl:
                self._pending_confirmations.pop(token, None)
        return closed

    # ------------------------------------------------------------------
    # invoke() — the main dispatch
    # ------------------------------------------------------------------

    async def invoke(
        self,
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        t0 = time.monotonic()
        action = params.get("action")
        agent_id = (context or {}).get("agent_id", "")
        session_id_param = params.get("session_id")

        # AD-1158: a workstation-bound invocation targets the session the
        # Captain is already watching. The binding lives in ``context`` (which
        # the runtime owns) rather than in the agent's prompt, because a
        # prompt-supplied id is guidance: the agent may use it, ignore it, or
        # invent one, and any of those silently opens a session the Captain
        # cannot see. AD-1157 and BF-688 were both this same defect — a
        # mechanism that existed but was never wired to the caller.
        #
        # An explicit ``session_id`` in ``params`` still wins: the agent may be
        # working several sessions and naming one is a deliberate act. The
        # binding only supplies the default the agent would otherwise leave
        # empty, which is exactly the case that creates a fresh hidden session.
        if not session_id_param:
            bound = (context or {}).get("browser_session_id")
            if isinstance(bound, str) and bound:
                session_id_param = bound
                logger.debug(
                    "AD-1158: binding browser call to workstation session %s "
                    "for agent %s", bound[:12], agent_id or "<unknown>",
                )

        if action not in _AGENT_ACTION_SET:
            elapsed_ms = (time.monotonic() - t0) * 1000.0
            self._audit(
                action=str(action or ""),
                agent_id=agent_id,
                session_id="",
                success=False,
                tier=0,
                error=f"unknown action: {action!r}",
                url=None,
            )
            return ToolResult(
                error=f"unknown browser action: {action!r}",
                duration_ms=elapsed_ms,
            )

        # 1. Resolve or create session.
        session = await self._get_or_create_session(session_id_param, agent_id)

        # 2. Domain allow/denylist check (only meaningful for navigation).
        if action == "goto":
            url = params.get("url") or ""
            deny_reason = self._check_domain(url)
            if deny_reason:
                elapsed_ms = (time.monotonic() - t0) * 1000.0
                self._audit(
                    action=action,
                    agent_id=agent_id,
                    session_id=session.session_id,
                    success=False,
                    tier=2,
                    error=f"Domain policy denied: {deny_reason}",
                    url=url,
                )
                return ToolResult(
                    error=f"Domain policy denied: {deny_reason}",
                    duration_ms=elapsed_ms,
                    metadata={"session_id": session.session_id, "tier": 2},
                )

        # 3. Tier classification.
        tier = classify_action(session, action, params)

        # 4. Tier-3 confirmation gate.
        if (
            tier == 3
            and self._config.require_confirmation_for_tier_3
            and not self._consume_confirmation_token(params, session.session_id, action)
        ):
            token = self._generate_confirmation_token(session.session_id, action, params)
            # BF-682 (closed by AD-1154): emit a NON-REDEEMABLE correlator, not the
            # bearer token. ``_consume_confirmation_token`` matches the full key, so
            # an 8-hex prefix identifies the pending confirmation in a log line or an
            # event stream without being spendable. This mattered little while no
            # unattended path could reach tier 3 (AD-1153 offers a read-only set);
            # AD-1154 makes the gate routinely reachable, so the raw token stops
            # being theoretically exposed and starts being routinely emitted.
            self._safe_emit(
                EventType.TOOL_INTERVENTION_REQUIRED,
                {
                    "session_id": session.session_id,
                    "action": action,
                    "tier": 3,
                    "agent_id": agent_id,
                    "confirmation_id": token[:8],
                },
            )
            elapsed_ms = (time.monotonic() - t0) * 1000.0
            self._audit(
                action=action,
                agent_id=agent_id,
                session_id=session.session_id,
                success=False,
                tier=3,
                error="intervention_required",
                url=params.get("url"),
            )
            # NOTE: token deliberately not surfaced in ToolResult.output —
            # human-in-loop reissue path only (D6 #2).
            return ToolResult(
                output={
                    "intervention_required": True,
                    "tier": 3,
                    "session_id": session.session_id,
                },
                duration_ms=elapsed_ms,
                metadata={"session_id": session.session_id, "tier": 3},
            )

        # 5. Per-domain rate limiting (best-effort; only meaningful when we
        # have a host to rate-limit against).
        rate_host = self._rate_limit_host(action, params, session)
        if rate_host:
            try:
                await session.wait_for_rate_limit(rate_host)
            except Exception:
                logger.debug("AD-706: rate limit wait failed", exc_info=True)

        # 6. Dispatch the action.
        try:
            if action == "verify":
                # AD-706c-1: special-cased dispatch — needs runtime context
                # for vision-LLM call + AttachmentStore. Falls back to
                # honest-degrade if runtime is None (e.g., test fixture).
                output = await action_verify(
                    session,
                    params,
                    runtime=self._runtime,
                    emit_event=self._emit_event,
                )
            elif action == "compute_use_click":
                # AD-706c-2: same special-cased dispatch signature as verify.
                from probos.tools.browser.compute_use import action_compute_use_click
                output = await action_compute_use_click(
                    session,
                    params,
                    runtime=self._runtime,
                    emit_event=self._emit_event,
                )
            elif action == "fill_credential":
                # AD-706f: same special-cased dispatch — vault read + page.fill.
                from probos.tools.browser.credentials import action_fill_credential
                merged_params = dict(params)
                merged_params.setdefault("agent_id", agent_id)
                output = await action_fill_credential(
                    session,
                    merged_params,
                    runtime=self._runtime,
                    emit_event=self._emit_event,
                )
            else:
                output = await dispatch_action(session, action, params)
                # AD-706e: per-action event types for the three highest-risk
                # vocabulary-v2 verbs. BROWSER_ACTION_EXECUTED still fires
                # below as the global per-action telemetry channel.
                if action == "upload_file" and isinstance(output, dict):
                    self._safe_emit(
                        EventType.BROWSER_FILE_UPLOAD_REQUESTED,
                        {
                            "session_id": session.session_id,
                            "agent_id": agent_id,
                            "selector": output.get("selector"),
                            "used_credential": output.get("used_credential", False),
                        },
                    )
                elif action == "download" and isinstance(output, dict):
                    self._safe_emit(
                        EventType.BROWSER_DOWNLOAD_REQUESTED,
                        {
                            "session_id": session.session_id,
                            "agent_id": agent_id,
                            "target": output.get("target"),
                            "suggested_filename": output.get("suggested_filename"),
                        },
                    )
                elif action == "eval_js" and isinstance(output, dict):
                    self._safe_emit(
                        EventType.BROWSER_EVAL_JS_EXECUTED,
                        {
                            "session_id": session.session_id,
                            "agent_id": agent_id,
                            "script_preview": output.get("script_preview", ""),
                        },
                    )
        except Exception as exc:
            elapsed_ms = (time.monotonic() - t0) * 1000.0
            self._audit(
                action=action,
                agent_id=agent_id,
                session_id=session.session_id,
                success=False,
                tier=tier,
                error=str(exc),
                url=params.get("url"),
            )
            return ToolResult(
                error=str(exc),
                duration_ms=elapsed_ms,
                metadata={"session_id": session.session_id, "tier": tier},
            )

        elapsed_ms = (time.monotonic() - t0) * 1000.0
        self._audit(
            action=action,
            agent_id=agent_id,
            session_id=session.session_id,
            success=True,
            tier=tier,
            error=None,
            url=output.get("url") if isinstance(output, dict) else None,
        )
        self._safe_emit(
            EventType.BROWSER_ACTION_EXECUTED,
            {
                "session_id": session.session_id,
                "agent_id": agent_id,
                "action": action,
                "tier": tier,
                "success": True,
            },
        )
        return ToolResult(
            output=output,
            duration_ms=elapsed_ms,
            metadata={"session_id": session.session_id, "tier": tier},
        )

    # ------------------------------------------------------------------
    # Session bookkeeping
    # ------------------------------------------------------------------

    async def _get_or_create_session(
        self,
        session_id: str | None,
        agent_id: str,
    ) -> BrowserSession:
        if session_id and session_id in self._sessions:
            existing = self._sessions[session_id]
            if not existing.is_expired():
                return existing
            # Expired: close + drop, fall through to create fresh.
            try:
                await existing.stop()
            except Exception:
                logger.debug("AD-706: stop expired session failed", exc_info=True)
            self._sessions.pop(session_id, None)
            self._safe_emit(
                EventType.BROWSER_SESSION_CLOSED,
                {"session_id": session_id, "reason": "expired"},
            )

        new_id = session_id or uuid.uuid4().hex
        session = self._session_factory(
            session_id=new_id,
            config=self._config,
            agent_id=agent_id,
            emit_event=self._emit_event,
        )
        await session.start()
        self._sessions[new_id] = session
        self._safe_emit(
            EventType.BROWSER_SESSION_OPENED,
            {"session_id": new_id, "agent_id": agent_id},
        )
        return session

    def _validate_cdp_endpoint(self, endpoint: str) -> str:
        """AD-1052b: return the host if allowed, else "" (refused).

        Accepts http/https/ws/wss CDP endpoints; the HOST must be in
        bridge_allowed_hosts (case-insensitive). Defense-in-depth against SSRF.
        """
        if not endpoint or not isinstance(endpoint, str):
            return ""
        try:
            parsed = urlparse(endpoint)
        except Exception:
            return ""
        if parsed.scheme.lower() not in ("http", "https", "ws", "wss"):
            return ""
        host = (parsed.hostname or "").lower()
        if not host:
            return ""
        # AD-1052b: urlparse strips the surrounding brackets from an IPv6 literal
        # (``http://[::1]:9222`` -> hostname ``::1``), but the allowlist stores the
        # bracketed form ``[::1]`` (the URL convention). Normalize BOTH sides so the
        # IPv6 loopback the default allowlist advertises actually matches, while the
        # exact-host SSRF guard (rejecting ``127.0.0.1.evil.com``) is preserved.
        def _strip_brackets(h: str) -> str:
            return h[1:-1] if len(h) >= 2 and h.startswith("[") and h.endswith("]") else h

        norm_host = _strip_brackets(host)
        allow = [_strip_brackets(h.lower()) for h in (self._config.bridge_allowed_hosts or [])]
        return host if norm_host in allow else ""

    async def connect_bridge_session(
        self, endpoint: str, *, agent_id: str, confirm: bool,
    ) -> dict[str, Any]:
        """AD-1052b: consent-gated, allowlist-validated CDP bridge connect.

        Honest-degrade (returns {"connected": False, "reason": ...}) when bridge
        is disabled, consent is not given, the endpoint host is not allowed, or
        the connect fails. On success stores the session and returns
        {"connected": True, "session_id", "streaming_url"}.
        """
        if not getattr(self._config, "bridge_enabled", False):
            self._safe_emit(EventType.BROWSER_BRIDGE_REFUSED, {"reason": "disabled"})
            return {"connected": False, "reason": "Bridge mode is disabled."}
        if confirm is not True:
            self._safe_emit(EventType.BROWSER_BRIDGE_REFUSED, {"reason": "consent"})
            return {"connected": False, "reason": "Connection consent is required."}
        host = self._validate_cdp_endpoint(endpoint)
        if not host:
            self._safe_emit(EventType.BROWSER_BRIDGE_REFUSED, {"reason": "endpoint_not_allowed"})
            return {"connected": False, "reason": "Endpoint not allowed."}

        new_id = uuid.uuid4().hex
        session = self._session_factory(
            session_id=new_id, config=self._config, agent_id=agent_id, emit_event=self._emit_event,
        )
        try:
            await session.connect(endpoint)
        except Exception:
            logger.warning("AD-1052b: bridge connect to %s failed", endpoint, exc_info=True)
            self._safe_emit(EventType.BROWSER_BRIDGE_REFUSED, {"reason": "unreachable", "host": host})
            return {"connected": False, "reason": f"Could not connect to {endpoint}"}

        self._sessions[new_id] = session
        self._safe_emit(
            EventType.BROWSER_BRIDGE_CONNECTED,
            {"session_id": new_id, "agent_id": agent_id, "host": host},
        )
        return {
            "connected": True,
            "session_id": new_id,
            "streaming_url": session.get_streaming_url(),
        }

    async def _discard_session(self, session_id: str, *, reason: str) -> None:
        """AD-1161: close and forget one session (no-op when already gone).

        Used when a session was created before the work it was created FOR was
        refused. Mirrors ``reap_expired``'s close-then-pop-then-emit ordering so
        a discarded session is indistinguishable from an expired one to any
        BROWSER_SESSION_CLOSED consumer.
        """
        session = self._sessions.get(session_id)
        if session is None:
            return
        try:
            await session.stop()
        except Exception:
            logger.debug(
                "AD-1161: stop of discarded session %s failed; dropping it anyway",
                session_id,
                exc_info=True,
            )
        self._sessions.pop(session_id, None)
        self._safe_emit(
            EventType.BROWSER_SESSION_CLOSED,
            {"session_id": session_id, "reason": reason},
        )

    @property
    def captain_session(self) -> dict[str, Any] | None:
        """AD-1163: the Captain's live session row, or ``None``.

        Carries ``url`` and ``page_title`` as well as the id, because an agent
        needs to be *told* the session exists before it will use it. AD-1158/1162
        made the binding work invisibly through the call context — deliberately,
        so no UUID has to survive a model copying it — but invisible to the
        plumbing turned out to mean invisible to the agent too: offered the
        browser and asked to type into "the document I have open", the agent
        made ZERO tool calls and answered that it could not control the
        Captain's screen. Correct reasoning from what it knew. This is what it
        needs to know.
        """
        captain_rows = [
            row for row in self.list_sessions()
            if row.get("agent_id") == "captain"
        ]
        if not captain_rows:
            return None
        if len(captain_rows) > 1:
            logger.warning(
                "AD-1162: the Captain has %d live browser sessions; binding the "
                "agent to the most recent (%s). Close the older ones to remove "
                "the ambiguity — the agent acts on one browser, not all of them.",
                len(captain_rows),
                str(captain_rows[-1].get("session_id"))[:12],
            )
        row = captain_rows[-1]
        session_id = row.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            return None
        return row

    @property
    def captain_session_id(self) -> str | None:
        """AD-1162: the live session the Captain opened, for ambient binding.

        ``agent_id == "captain"`` is set by :meth:`open_captain_session`
        (AD-1161); agent-opened sessions carry the agent's own id and are
        deliberately NOT bindable this way — an agent should not silently
        inherit another agent's browser.

        Returns ``None`` when the Captain has no live session, which is the
        honest answer: the agent then creates its own, exactly as before.
        """
        row = self.captain_session
        if row is None:
            return None
        session_id = row.get("session_id")
        return session_id if isinstance(session_id, str) and session_id else None

    async def open_captain_session(
        self, url: str, *, agent_id: str = "captain",
    ) -> dict[str, Any]:
        """AD-1161: open a fresh browser session at ``url`` for the Captain.

        ``GET /api/browser/sessions`` lists sessions but nothing CREATED one —
        a session only came into existence when an agent called ``goto``. This
        is the Captain-initiated counterpart: open the page first, sign in by
        hand, and only then hand the session to an agent.

        Navigation goes through ``invoke({"action": "goto"})`` rather than a
        private path, so ``domain_allowlist`` / ``domain_denylist``, the tier
        classification and the AD-706 audit row all bind here exactly as they
        do for an agent. Nothing about this entry point is exempt from browser
        policy; only the *initiator* differs.

        There is deliberately NO ``confirm`` parameter. ``connect_bridge_session``
        needs one because it attaches to an already-authenticated browser the
        Captain did not open for this purpose, so the consent is about handing
        over existing credentials. Opening a fresh session is the Captain acting
        on their own surface with nothing yet in it — a confirmation there is
        friction with no matching risk. Do not add one by analogy to the bridge.

        Honest-degrade: returns ``{"opened": False, "reason": ...}`` and never
        raises. A refused navigation leaves NO live session behind — the session
        ``invoke`` created before the refusal is discarded before returning.
        """
        if not getattr(self._config, "enabled", False):
            return {"opened": False, "reason": "Browser tool is disabled."}
        target = url.strip() if isinstance(url, str) else ""
        if not target:
            return {"opened": False, "reason": "A URL is required."}

        # ``invoke`` creates the session BEFORE its own try block, so a failure
        # to launch Chromium (missing binary, sandbox refusal) propagates out of
        # it. Contain it here: this method's whole contract is that the Captain
        # gets a reason back, never an exception through the router.
        try:
            result = await self.invoke(
                {"action": "goto", "url": target}, {"agent_id": agent_id},
            )
        except Exception as exc:  # noqa: BLE001 - Tier-2 log-and-degrade
            logger.warning(
                "AD-1161: opening a Captain session for %s failed before "
                "navigation: %s; no session was registered",
                self._sanitize_url(target), exc, exc_info=True,
            )
            return {"opened": False, "reason": f"Could not open a browser: {exc}"}
        session_id = str((result.metadata or {}).get("session_id") or "")

        if result.error is not None:
            await self._discard_session(session_id, reason="open_failed")
            return {"opened": False, "reason": result.error}

        output = result.output if isinstance(result.output, dict) else {}
        # ``goto`` classifies as tier 2 today, so the confirmation gate cannot
        # fire here. Handle it anyway: ``invoke`` documents this shape as a
        # non-error, non-navigated return, and reporting opened=True for a page
        # that was never loaded would be a false success claim if the tier ever
        # changes. The gate is NOT auto-satisfied — the Captain is told why.
        if output.get("intervention_required"):
            await self._discard_session(session_id, reason="open_refused")
            return {"opened": False, "reason": "Navigation requires confirmation."}

        session = self._sessions.get(session_id)
        return {
            "opened": True,
            "session_id": session_id,
            "streaming_url": session.get_streaming_url() if session is not None else None,
            "url": str(output.get("url") or target),
            "page_title": str(output.get("page_title") or ""),
        }

    async def forward_input(
        self, session_id: str, event: dict[str, Any], *, agent_id: str,
    ) -> dict[str, Any]:
        """AD-1052c: gate -> dispatch -> audit a human-forwarded input event.

        Honest-degrade {"forwarded": False, "reason": ...} when forwarding is
        disabled, the session is gone, or the session's page rejects the event.
        Emits BROWSER_INPUT_REFUSED on every refusal; BROWSER_INPUT_FORWARDED
        once per drive-episode per session (NOT per keystroke).
        """
        if not getattr(self._config, "input_forwarding_enabled", False):
            self._safe_emit(EventType.BROWSER_INPUT_REFUSED, {"reason": "disabled", "session_id": session_id})
            return {"forwarded": False, "reason": "Input forwarding is disabled."}
        session = self._sessions.get(session_id)
        if session is None:
            self._safe_emit(EventType.BROWSER_INPUT_REFUSED, {"reason": "session_not_found", "session_id": session_id})
            return {"forwarded": False, "reason": "Session not found."}
        result = await session.forward_input(event)
        if not result.get("forwarded"):
            self._safe_emit(
                EventType.BROWSER_INPUT_REFUSED,
                {"reason": result.get("reason", "rejected"), "session_id": session_id},
            )
            return result
        if session_id not in self._driven_sessions:
            self._driven_sessions.add(session_id)
            self._safe_emit(
                EventType.BROWSER_INPUT_FORWARDED,
                {"session_id": session_id, "agent_id": agent_id},
            )
        return result

    def get_session(self, session_id: str) -> BrowserSession | None:
        """Look up an active session (test/diagnostic helper)."""
        return self._sessions.get(session_id)

    def list_sessions(self) -> list[dict[str, Any]]:
        """AD-1052a: snapshot of active sessions for the Captain-watch picker.

        Each entry is built from the session's PUBLIC surface (session_id,
        agent_id, get_streaming_url(), last_url). streaming_url is None when
        BrowserToolConfig.streaming_enabled is False -> the HXI honest-degrades
        to BrowserStreamPanel's "Streaming not enabled" state.
        """
        return [
            {
                "session_id": s.session_id,
                "agent_id": s.agent_id,
                "streaming_url": s.get_streaming_url(),
                "last_url": s.last_url,
            }
            for s in self._sessions.values()
        ]

    @property
    def session_count(self) -> int:
        return len(self._sessions)

    @property
    def input_forwarding_enabled(self) -> bool:
        """AD-1052c: whether human input may be forwarded to a live page."""
        return bool(getattr(self._config, "input_forwarding_enabled", False))

    # ------------------------------------------------------------------
    # AD-706a viewer accounting (public API for streaming router)
    # ------------------------------------------------------------------

    @property
    def active_viewers(self) -> int:
        """AD-706a: count of open Captain-watch streaming viewers."""
        return self._active_viewers

    async def acquire_viewer_slot(self) -> bool:
        """AD-706a: try to reserve a streaming viewer slot.

        Returns True on success; False when the configured
        ``streaming_max_concurrent_viewers`` cap is exhausted. Callers MUST
        pair every successful acquire with ``release_viewer_slot()`` in
        ``finally``.
        """
        async with self._viewer_lock:
            cap = int(getattr(self._config, "streaming_max_concurrent_viewers", 0) or 0)
            if cap > 0 and self._active_viewers >= cap:
                return False
            self._active_viewers += 1
            return True

    async def release_viewer_slot(self) -> None:
        """AD-706a: release a viewer slot previously acquired."""
        async with self._viewer_lock:
            if self._active_viewers > 0:
                self._active_viewers -= 1

    # ------------------------------------------------------------------
    # Domain policy
    # ------------------------------------------------------------------

    def _check_domain(self, url: str) -> str:
        """Return a deny reason, or empty string if allowed."""
        if not url:
            return ""
        try:
            host = (urlparse(url).hostname or "").lower()
        except Exception:
            return ""
        if not host:
            return ""

        denylist = self._config.domain_denylist or []
        for pat in denylist:
            if isinstance(pat, str) and pat and self._suffix_match(host, pat.lower()):
                return "in denylist"

        allowlist = self._config.domain_allowlist
        if allowlist is not None:
            allowed = False
            for pat in allowlist:
                if isinstance(pat, str) and pat and self._suffix_match(host, pat.lower()):
                    allowed = True
                    break
            if not allowed:
                return "not in allowlist"
        return ""

    @staticmethod
    def _suffix_match(host: str, pattern: str) -> bool:
        """Suffix match — pattern matches host or any subdomain of pattern."""
        if not host or not pattern:
            return False
        if host == pattern:
            return True
        return host.endswith("." + pattern)

    def _rate_limit_host(
        self,
        action: str,
        params: dict[str, Any],
        session: BrowserSession,
    ) -> str:
        if action == "goto":
            url = params.get("url") or ""
        else:
            url = session.last_url or ""
        try:
            return (urlparse(url).hostname or "").lower()
        except Exception:
            return ""

    # ------------------------------------------------------------------
    # Confirmation token flow (D6)
    # ------------------------------------------------------------------

    def _generate_confirmation_token(
        self,
        session_id: str,
        action: str,
        params: dict[str, Any],
    ) -> str:
        token = uuid.uuid4().hex
        self._pending_confirmations[token] = {
            "token": token,
            "session_id": session_id,
            "action": action,
            "params": dict(params),  # snapshot
            "created_at": time.time(),
        }
        return token

    def _consume_confirmation_token(
        self,
        params: dict[str, Any],
        session_id: str,
        action: str,
    ) -> bool:
        token = params.get("confirmation_token")
        if not token or not isinstance(token, str):
            return False
        entry = self._pending_confirmations.pop(token, None)
        if entry is None:
            return False
        # Validate session + action match the original gate.
        if entry.get("session_id") != session_id or entry.get("action") != action:
            return False
        # Expiry check.
        ttl = float(self._config.confirmation_timeout_seconds)
        if (time.time() - float(entry.get("created_at", 0.0))) >= ttl:
            return False
        return True

    def seed_confirmation_token(
        self,
        *,
        token: str,
        session_id: str,
        action: str,
        params: dict[str, Any] | None = None,
    ) -> None:
        """Test/diagnostic helper to pre-seed a confirmation token."""
        self._pending_confirmations[token] = {
            "token": token,
            "session_id": session_id,
            "action": action,
            "params": dict(params or {}),
            "created_at": time.time(),
        }

    # ------------------------------------------------------------------
    # Audit + event emission
    # ------------------------------------------------------------------

    def _audit(
        self,
        *,
        action: str,
        agent_id: str,
        session_id: str,
        success: bool,
        tier: int,
        error: str | None,
        url: str | None,
    ) -> None:
        if self._audit_log is None:
            return
        detail: dict[str, Any] = {
            "session_id": session_id,
            "action": action,
            "agent_id": agent_id,
            "success": success,
            "tier": tier,
        }
        if error is not None:
            detail["error"] = error[:200]
        if url:
            detail["url_sanitized"] = self._sanitize_url(url)
        # Defense-in-depth: enforce the strict allowlist (D5).
        for key in list(detail.keys()):
            if key not in _AUDIT_DETAIL_ALLOWLIST:
                detail.pop(key, None)
        try:
            self._audit_log.append(
                category="browser_tool",
                detail=json.dumps(detail, sort_keys=True),
            )
        except Exception:
            logger.warning(
                "AD-706: audit append failed (action=%s, session=%s)",
                action, session_id, exc_info=True,
            )

    @staticmethod
    def _sanitize_url(url: str) -> str:
        """Drop query + fragment from a URL to avoid leaking tokens (D5)."""
        try:
            parsed = urlparse(url)
            return parsed._replace(query="", fragment="").geturl()
        except Exception:
            return ""

    def _safe_emit(self, event_type: EventType, data: dict[str, Any]) -> None:
        if self._emit_event is None:
            return
        try:
            self._emit_event(event_type, data)
        except Exception:
            logger.debug("AD-706: emit_event failed for %s", event_type, exc_info=True)
