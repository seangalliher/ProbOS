"""AD-803a: minimal Telegram Bot API client built on httpx.

Avoids the LGPL-3.0 ``python-telegram-bot`` dependency per the BUILDER
standing-rule license policy. We re-implement the small slice of the
Bot API we actually need (``getMe``, ``getUpdates``, ``sendMessage``)
on top of ``httpx`` (already a runtime dep). The Bot API is a stable
HTTP-JSON endpoint set at ``https://api.telegram.org/bot<token>/<method>``.

Public surface:
    - ``TelegramClient(token, *, http=None, timeout=30.0, base="https://api.telegram.org")``
    - ``await get_me() -> dict``
    - ``await get_updates(offset=None, timeout=25, allowed_updates=None) -> list[dict]``
    - ``await send_message(chat_id, text, parse_mode=None, reply_to_message_id=None) -> dict``
    - ``await close() -> None``

AD-803b will extend this with ``getFile`` (for attachment downloads),
``setWebhook`` (for webhook mode), and ``sendPhoto`` / ``sendDocument``
for outbound artifacts.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class TelegramAPIError(Exception):
    """Bot API returned ``ok: false`` or an HTTP non-2xx status."""

    def __init__(self, message: str, *, status_code: int | None = None, payload: dict | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class TelegramClient:
    """Minimal Telegram Bot API client.

    The client is async-safe to share across the polling loop and the
    outbound ``send_message`` path (httpx supports concurrent requests
    on a single ``AsyncClient``). Pass a pre-built ``http`` to inject a
    ``MockTransport`` in tests.
    """

    def __init__(
        self,
        token: str,
        *,
        http: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
        base: str = "https://api.telegram.org",
    ) -> None:
        if not token:
            raise ValueError("TelegramClient requires a non-empty token")
        self._token = token
        self._base = base.rstrip("/")
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(timeout=timeout)

    def _url(self, method: str) -> str:
        return f"{self._base}/bot{self._token}/{method}"

    async def _call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        """POST against the Bot API; raise ``TelegramAPIError`` on failure.

        The Bot API uses POST for everything; longer-polling ``getUpdates``
        requests use a per-request timeout slightly higher than the
        long-poll timeout so the HTTP layer doesn't fire before the API.
        """
        url = self._url(method)
        try:
            response = await self._http.post(url, json=params or {})
        except httpx.TimeoutException as exc:
            raise TelegramAPIError(f"{method} timed out", status_code=None) from exc
        except httpx.RequestError as exc:
            raise TelegramAPIError(f"{method} transport error: {exc}", status_code=None) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise TelegramAPIError(
                f"{method} returned non-JSON body (status={response.status_code})",
                status_code=response.status_code,
            ) from exc

        if not response.is_success or not payload.get("ok"):
            description = payload.get("description") or response.text or "(no description)"
            raise TelegramAPIError(
                f"{method} failed: {description}",
                status_code=response.status_code,
                payload=payload,
            )
        return payload.get("result")

    # ---------- API methods ----------

    async def get_me(self) -> dict:
        """Returns the bot's own identity. Used by ``probos channel telegram setup``
        to validate the token and by the doctor health check.
        """
        return await self._call("getMe")

    async def get_updates(
        self,
        *,
        offset: int | None = None,
        timeout: int = 25,
        allowed_updates: list[str] | None = None,
    ) -> list[dict]:
        """Long-poll for inbound updates.

        ``offset`` is one greater than the last seen ``update_id`` — the
        adapter's polling loop tracks this and passes it in.
        ``allowed_updates=["message"]`` restricts to text DMs only in v1;
        AD-803b widens it to ``"callback_query"``, ``"edited_message"``,
        etc. for richer interactions.
        """
        params: dict[str, Any] = {"timeout": timeout}
        if offset is not None:
            params["offset"] = offset
        if allowed_updates is not None:
            params["allowed_updates"] = allowed_updates
        result = await self._call("getUpdates", params)
        if not isinstance(result, list):
            return []
        return result

    async def send_message(
        self,
        chat_id: int | str,
        text: str,
        *,
        parse_mode: str | None = None,
        reply_to_message_id: int | None = None,
    ) -> dict:
        """Send a text reply. ``parse_mode`` accepts ``"Markdown"`` or
        ``"MarkdownV2"`` or ``"HTML"`` per the Bot API.
        """
        params: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if parse_mode is not None:
            params["parse_mode"] = parse_mode
        if reply_to_message_id is not None:
            params["reply_to_message_id"] = reply_to_message_id
        return await self._call("sendMessage", params)

    # ---------- lifecycle ----------

    async def close(self) -> None:
        """Close the underlying httpx client if we own it. No-op if the
        client was injected (caller manages lifecycle).
        """
        if self._owns_http:
            try:
                await self._http.aclose()
            except Exception:
                logger.warning("AD-803a: TelegramClient http.aclose raised", exc_info=True)
