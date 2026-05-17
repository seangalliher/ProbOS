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
            "Drive a Chromium browser. 10-action vocabulary: "
            "goto, state, click, type, scroll, screenshot, wait, back, forward, extract_text. "
            "Use state() to get an indexed list of clickable elements, then click/type by index."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["action"],
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "goto", "state", "click", "type", "scroll",
                        "screenshot", "wait", "back", "forward", "extract_text",
                        "verify",
                    ],
                },
                "session_id": {"type": "string", "description": "Reuse an existing session, or omit to create a fresh one."},
                "url": {"type": "string"},
                "index": {"type": "integer"},
                "selector": {"type": "string"},
                "text": {"type": "string"},
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

        if action not in {
            "goto", "state", "click", "type", "scroll",
            "screenshot", "wait", "back", "forward", "extract_text",
            "verify",
        }:
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
            self._safe_emit(
                EventType.TOOL_INTERVENTION_REQUIRED,
                {
                    "session_id": session.session_id,
                    "action": action,
                    "tier": 3,
                    "agent_id": agent_id,
                    "confirmation_token": token,
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
        )
        await session.start()
        self._sessions[new_id] = session
        self._safe_emit(
            EventType.BROWSER_SESSION_OPENED,
            {"session_id": new_id, "agent_id": agent_id},
        )
        return session

    def get_session(self, session_id: str) -> BrowserSession | None:
        """Look up an active session (test/diagnostic helper)."""
        return self._sessions.get(session_id)

    @property
    def session_count(self) -> int:
        return len(self._sessions)

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
