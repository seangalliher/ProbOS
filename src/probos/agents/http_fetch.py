"""HTTP fetch agent — fetches URLs via HTTP."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from probos.substrate.agent import BaseAgent
from probos.types import CapabilityDescriptor, IntentDescriptor, IntentMessage, IntentResult

logger = logging.getLogger(__name__)


class HttpFetchAgent(BaseAgent):
    """Concrete agent that fetches URLs via HTTP.

    Read-only: GET requests are non-destructive and don't require
    consensus.  URL safety is enforced by red team verification.

    Capabilities: http_fetch.
    """

    agent_type: str = "http_fetch"
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
    })

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

    async def _fetch_url(self, url: str, method: str) -> dict[str, Any]:
        """Fetch a URL with timeout and body capping."""
        try:
            async with httpx.AsyncClient(
                timeout=self.DEFAULT_TIMEOUT,
                headers={"User-Agent": self.USER_AGENT},
                follow_redirects=True,
            ) as client:
                response = await client.request(method, url)

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
