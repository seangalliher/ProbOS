"""AD-805: thin Bot Framework client for outbound Teams activity.

Bot Framework outbound flow:
    1. Bot Service POSTs an inbound ``Activity`` to our webhook.
    2. We extract ``serviceUrl`` + ``conversation.id`` from the activity.
    3. We POST a reply Activity to
       ``{serviceUrl}/v3/conversations/{conversation_id}/activities``
       with a Bearer token obtained from the Azure AD token endpoint
       (``https://login.microsoftonline.com/botframework.com/oauth2/v2.0/token``).

v1 substrate keeps the token-fetch + send-activity in pure httpx (no
botframework-connector SDK) following the AD-803a/804/806 thin-client
pattern. Token caching is in-memory with a 5-minute safety margin
before the AAD-reported expiry.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

_TOKEN_ENDPOINT = (
    "https://login.microsoftonline.com/botframework.com/oauth2/v2.0/token"
)
_TOKEN_SCOPE = "https://api.botframework.com/.default"
_TOKEN_SAFETY_MARGIN_S = 300.0  # refresh 5 min before stated expiry


class TeamsAPIError(RuntimeError):
    """Raised for non-2xx HTTP responses from Bot Framework."""


@dataclass
class _CachedToken:
    value: str
    expires_at: float


class TeamsClient:
    """Bot Framework outbound client (token + send_activity)."""

    def __init__(
        self,
        *,
        app_id: str,
        app_password: str,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._app_id = app_id
        self._app_password = app_password
        self._http = http or httpx.AsyncClient(timeout=30.0)
        self._token: _CachedToken | None = None
        self._owns_client = http is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    async def _get_token(self, *, now: float | None = None) -> str:
        now = now if now is not None else time.time()
        if self._token and self._token.expires_at - _TOKEN_SAFETY_MARGIN_S > now:
            return self._token.value
        if not self._app_id or not self._app_password:
            raise TeamsAPIError("Teams app_id / app_password not configured")
        resp = await self._http.post(
            _TOKEN_ENDPOINT,
            data={
                "grant_type": "client_credentials",
                "client_id": self._app_id,
                "client_secret": self._app_password,
                "scope": _TOKEN_SCOPE,
            },
        )
        if resp.status_code != 200:
            raise TeamsAPIError(
                f"Bot Framework token endpoint returned {resp.status_code}: {resp.text}"
            )
        body = resp.json()
        token = body.get("access_token")
        expires_in = float(body.get("expires_in", 3599))
        if not token:
            raise TeamsAPIError("Bot Framework token response missing access_token")
        self._token = _CachedToken(value=token, expires_at=now + expires_in)
        return token

    async def send_activity(
        self,
        *,
        service_url: str,
        conversation_id: str,
        text: str,
        reply_to_id: str | None = None,
    ) -> dict:
        """POST a reply activity to a Teams conversation."""
        token = await self._get_token()
        url = (
            f"{service_url.rstrip('/')}/v3/conversations/{conversation_id}/activities"
        )
        body: dict = {
            "type": "message",
            "text": text,
        }
        if reply_to_id:
            body["replyToId"] = reply_to_id
        resp = await self._http.post(
            url,
            json=body,
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp.status_code not in (200, 201, 202):
            raise TeamsAPIError(
                f"Teams send_activity returned {resp.status_code}: {resp.text}"
            )
        try:
            return resp.json()
        except Exception:
            return {}
