"""AD-804: minimal Slack Web API client built on httpx.

Same approach as AD-803a Telegram — thin client over the public HTTP
Web API instead of taking the ``slack-bolt`` dep (which drags
``aiohttp`` and a large adapter framework). The Slack Web API is a
stable HTTP-JSON endpoint set at ``https://slack.com/api/<method>``.

Public surface:
    - ``SlackClient(bot_token, *, http=None, timeout=30.0, base="https://slack.com/api")``
    - ``await auth_test() -> dict``
    - ``await conversations_list(types="public_channel,private_channel", limit=200) -> list[dict]``
    - ``await conversations_history(channel, oldest=None, limit=20) -> list[dict]``
    - ``await chat_post_message(channel, text, thread_ts=None) -> dict``
    - ``await close() -> None``

AD-804b will extend this with Events API webhook + Socket Mode.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class SlackAPIError(Exception):
    """Slack API returned ``ok: false`` or an HTTP non-2xx status."""

    def __init__(self, message: str, *, status_code: int | None = None, payload: dict | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class SlackClient:
    """Minimal Slack Web API client.

    The client is async-safe to share across the polling loop and the
    outbound ``chat_post_message`` path. Pass a pre-built ``http`` to
    inject a ``MockTransport`` in tests.

    All methods POST to the Web API; Slack accepts both form-encoded
    and JSON; we use JSON via ``Authorization: Bearer <token>`` per the
    current Slack API docs.
    """

    def __init__(
        self,
        bot_token: str,
        *,
        http: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
        base: str = "https://slack.com/api",
    ) -> None:
        if not bot_token:
            raise ValueError("SlackClient requires a non-empty bot_token")
        self._token = bot_token
        self._base = base.rstrip("/")
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(timeout=timeout)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json; charset=utf-8",
        }

    async def _call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self._base}/{method}"
        try:
            response = await self._http.post(url, json=params or {}, headers=self._headers())
        except httpx.TimeoutException as exc:
            raise SlackAPIError(f"{method} timed out", status_code=None) from exc
        except httpx.RequestError as exc:
            raise SlackAPIError(f"{method} transport error: {exc}", status_code=None) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise SlackAPIError(
                f"{method} returned non-JSON body (status={response.status_code})",
                status_code=response.status_code,
            ) from exc

        if not response.is_success or not payload.get("ok"):
            error = payload.get("error") or response.text or "(no error)"
            raise SlackAPIError(
                f"{method} failed: {error}",
                status_code=response.status_code,
                payload=payload,
            )
        return payload

    # ---------- API methods ----------

    async def auth_test(self) -> dict:
        """Validate the token and return the bot's identity.

        Used by ``probos channel slack setup`` and the doctor check.
        Returns the full Slack auth.test payload (user, team, url, etc.).
        """
        return await self._call("auth.test")

    async def conversations_list(
        self,
        *,
        types: str = "public_channel,private_channel,im",
        limit: int = 200,
    ) -> list[dict]:
        """List channels the bot can see. Used when the operator hasn't
        explicitly enumerated channels in config.channels — we poll
        every channel the bot is a member of.
        """
        result = await self._call("conversations.list", {"types": types, "limit": limit})
        channels = result.get("channels", [])
        return channels if isinstance(channels, list) else []

    async def conversations_history(
        self,
        channel: str,
        *,
        oldest: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Fetch recent messages in a channel.

        ``oldest`` is a Slack timestamp (``"1234567890.123456"``) — the
        adapter's polling loop tracks the highest ``ts`` seen per
        channel and passes it back here on the next call.
        """
        params: dict[str, Any] = {"channel": channel, "limit": limit}
        if oldest is not None:
            params["oldest"] = oldest
        result = await self._call("conversations.history", params)
        messages = result.get("messages", [])
        return messages if isinstance(messages, list) else []

    async def chat_post_message(
        self,
        channel: str,
        text: str,
        *,
        thread_ts: str | None = None,
    ) -> dict:
        """Send a text reply. ``thread_ts`` (parent's ``ts``) threads the
        reply; omit to post at top level.
        """
        params: dict[str, Any] = {"channel": channel, "text": text}
        if thread_ts is not None:
            params["thread_ts"] = thread_ts
        return await self._call("chat.postMessage", params)

    # ---------- lifecycle ----------

    async def close(self) -> None:
        if self._owns_http:
            try:
                await self._http.aclose()
            except Exception:
                logger.warning("AD-804: SlackClient http.aclose raised", exc_info=True)
