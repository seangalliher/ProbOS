"""HTTP fetch agent — fetches URLs via HTTP."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, ClassVar

import httpx

from probos.substrate.agent import BaseAgent
from probos.types import CapabilityDescriptor, IntentDescriptor, IntentMessage, IntentResult

logger = logging.getLogger(__name__)


@dataclass
class DomainRateState:
    """Per-domain rate-limit tracking (AD-270)."""

    last_request_time: float = 0.0
    min_interval_seconds: float = 2.0
    retry_after: float | None = None
    remaining: int | None = None
    reset_time: float | None = None
    consecutive_429s: int = 0


class HttpFetchAgent(BaseAgent):
    """Concrete agent that fetches URLs via HTTP.

    Read-only: GET requests are non-destructive and don't require
    consensus.  URL safety is enforced by red team verification.

    Capabilities: http_fetch.
    """

    agent_type: str = "http_fetch"
    tier = "core"
    default_capabilities = [
        CapabilityDescriptor(
            can="http_fetch",
            detail="Fetch a URL via HTTP and return the response",
        ),
    ]
    initial_confidence: float = 0.8
    intent_descriptors = [
        IntentDescriptor(name="http_fetch", params={"url": "<url>", "method": "GET"}, description="Fetch a URL", requires_consensus=False),
    ]

    _handled_intents = {"http_fetch"}

    # Security constants
    # Must be less than the DAG executor broadcast timeout (10s) so httpx
    # either completes or raises TimeoutException before asyncio.wait()
    # cancels the task.
    DEFAULT_TIMEOUT: float = 8.0
    MAX_BODY_BYTES: int = 1024 * 1024  # 1MB cap
    USER_AGENT: str = "ProbOS/0.1.0 (https://github.com/seangalliher/ProbOS)"

    # Only expose safe response headers
    _SAFE_HEADERS = frozenset({
        "content-type",
        "content-length",
        "server",
        "date",
        "last-modified",
        "retry-after",
        "x-ratelimit-remaining",
        "x-ratelimit-reset",
        "x-ratelimit-limit",
    })

    # Class-level shared state — all pool members share rate limit knowledge (AD-270)
    _domain_state: ClassVar[dict[str, DomainRateState]] = {}

    _KNOWN_RATE_LIMITS: ClassVar[dict[str, float]] = {
        "api.coingecko.com": 3.0,
        "wttr.in": 2.0,
        "feeds.reuters.com": 1.0,
        "feeds.bbci.co.uk": 1.0,
        "feeds.npr.org": 1.0,
        "html.duckduckgo.com": 2.0,
    }

    async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
        """Full lifecycle: perceive -> decide -> act -> report."""
        observation = await self.perceive(intent.__dict__)
        if observation is None:
            return None

        plan = await self.decide(observation)
        if plan is None:
            return None

        result = await self.act(plan)
        report = await self.report(result)

        success = report.get("success", False)
        self.update_confidence(success)

        return IntentResult(
            intent_id=intent.id,
            agent_id=self.id,
            success=success,
            result=report.get("data"),
            error=report.get("error"),
            confidence=self.confidence,
        )

    async def perceive(self, intent: dict[str, Any]) -> Any:
        """Check if this intent is something we handle."""
        intent_name = intent.get("intent", "")
        if intent_name not in self._handled_intents:
            return None
        return {
            "intent": intent_name,
            "params": intent.get("params", {}),
        }

    async def decide(self, observation: Any) -> Any:
        """Plan what to do based on the perceived intent."""
        params = observation["params"]
        url = params.get("url", "")
        method = params.get("method", "GET")

        if not url:
            return {"action": "error", "error": "No URL specified"}

        return {"action": "fetch", "url": url, "method": method}

    async def act(self, plan: Any) -> Any:
        """Execute the planned operation."""
        action = plan.get("action")

        if action == "error":
            return {"success": False, "error": plan["error"]}

        if action == "fetch":
            return await self._fetch_url(plan["url"], plan["method"])

        return {"success": False, "error": f"Unknown action: {action}"}

    async def report(self, result: Any) -> dict[str, Any]:
        """Package the result for the mesh."""
        return result

    # Blocked metadata hostnames
    _BLOCKED_HOSTS = frozenset({"metadata.google.internal"})

    def _validate_url(self, url: str) -> str | None:
        """Validate URL is safe to fetch. Returns error message or None if safe."""
        parsed = urllib.parse.urlparse(url)

        # Scheme check
        if parsed.scheme not in ("http", "https"):
            return f"Blocked scheme: {parsed.scheme}"

        # Extract hostname
        hostname = parsed.hostname
        if not hostname:
            return "No hostname in URL"

        # Cloud metadata hostnames
        if hostname.lower() in self._BLOCKED_HOSTS:
            return f"Blocked metadata endpoint: {hostname}"

        # Resolve DNS to catch rebinding attacks
        try:
            addrinfo = socket.getaddrinfo(hostname, None)
        except socket.gaierror:
            return f"Cannot resolve hostname: {hostname}"

        for family, _, _, _, sockaddr in addrinfo:
            ip = ipaddress.ip_address(sockaddr[0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return f"Blocked private/reserved IP: {ip}"

        return None

    async def _fetch_url(self, url: str, method: str) -> dict[str, Any]:
        """Fetch a URL with timeout, body capping, and per-domain rate limiting."""
        error = self._validate_url(url)
        if error:
            return {"success": False, "error": f"SSRF protection: {error}"}

        domain, state = self._get_domain_state(url)
        delay = await self._wait_for_rate_limit(domain, state)

        try:
            async with httpx.AsyncClient(
                timeout=self.DEFAULT_TIMEOUT,
                headers={"User-Agent": self.USER_AGENT},
                follow_redirects=True,
            ) as client:
                response = await client.request(method, url)

                self._update_rate_state(state, response)

                # Auto-retry once on 429 (AD-270)
                if response.status_code == 429:
                    retry_delay = await self._wait_for_rate_limit(domain, state)
                    state.last_request_time = time.monotonic()
                    response = await client.request(method, url)
                    self._update_rate_state(state, response)
                    delay += retry_delay

                body = response.content[:self.MAX_BODY_BYTES].decode(
                    "utf-8", errors="replace"
                )

                safe_headers = {
                    k: v
                    for k, v in response.headers.items()
                    if k.lower() in self._SAFE_HEADERS
                }

                return {
                    "success": True,
                    "data": {
                        "url": str(response.url),
                        "status_code": response.status_code,
                        "headers": safe_headers,
                        "body": body,
                        "body_length": len(body),
                        "rate_limit_delay": round(delay, 2),
                    },
                }
        except httpx.ConnectError as e:
            return {"success": False, "error": f"Connection error: {e}"}
        except httpx.TimeoutException:
            return {
                "success": False,
                "error": f"Request timed out after {self.DEFAULT_TIMEOUT}s",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _get_domain_state(self, url: str) -> tuple[str, DomainRateState]:
        """Look up or create rate-limit state for the URL's domain."""
        domain = urllib.parse.urlparse(url).netloc
        if domain not in self._domain_state:
            interval = self._KNOWN_RATE_LIMITS.get(domain, 2.0)
            self._domain_state[domain] = DomainRateState(min_interval_seconds=interval)
        return domain, self._domain_state[domain]

    async def _wait_for_rate_limit(self, domain: str, state: DomainRateState) -> float:
        """Sleep if the domain was requested too recently. Returns delay in seconds."""
        now = time.monotonic()

        # Respect Retry-After if set
        wait = 0.0
        if state.retry_after is not None and state.retry_after > now:
            wait = state.retry_after - now
            state.retry_after = None
        elif state.last_request_time > 0:
            elapsed = now - state.last_request_time
            if elapsed < state.min_interval_seconds:
                wait = state.min_interval_seconds - elapsed

        if wait > 0:
            wait = min(wait, 10.0)  # Never wait more than 10s — fail fast
            logger.debug("Rate limit courtesy delay: %.1fs for %s", wait, domain)
            await asyncio.sleep(wait)

        state.last_request_time = time.monotonic()
        return wait

    def _update_rate_state(self, state: DomainRateState, response: httpx.Response) -> None:
        """Update domain rate state from response status and headers."""
        if response.status_code == 429:
            state.consecutive_429s = min(state.consecutive_429s + 1, 3)
            # Retry-After header (seconds or HTTP-date — we only handle seconds)
            retry_after = response.headers.get("retry-after")
            if retry_after:
                try:
                    state.retry_after = time.monotonic() + float(retry_after)
                except (ValueError, TypeError):
                    pass
            # Exponential backoff capped at 60s
            state.min_interval_seconds = min(2 ** state.consecutive_429s, 60)
        else:
            state.consecutive_429s = 0

        # X-RateLimit-Remaining: pre-emptively slow down when near limit
        remaining = response.headers.get("x-ratelimit-remaining")
        if remaining is not None:
            try:
                state.remaining = int(remaining)
                if state.remaining <= 2:
                    state.min_interval_seconds = max(state.min_interval_seconds, state.min_interval_seconds * 2)
            except (ValueError, TypeError):
                pass

        # X-RateLimit-Reset: Unix timestamp
        reset_hdr = response.headers.get("x-ratelimit-reset")
        if reset_hdr is not None:
            try:
                reset_unix = float(reset_hdr)
                now_unix = time.time()
                if reset_unix > now_unix:
                    state.reset_time = time.monotonic() + (reset_unix - now_unix)
            except (ValueError, TypeError):
                pass
