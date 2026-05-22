"""AD-806: minimal Matrix client-server API client built on httpx.

Same approach as AD-803a Telegram and AD-804 Slack — thin client over
the public HTTP API instead of taking the ``matrix-nio`` dep. The
Matrix client-server API is a stable HTTP-JSON endpoint set at
``{homeserver}/_matrix/client/v3/<method>``.

v1 covers what the adapter substrate needs:
    - ``await login_password(user, password) -> access_token``
    - ``await whoami() -> user_id``
    - ``await sync(since=None, timeout_ms=25000) -> dict``
    - ``await join_room(room_id_or_alias) -> room_id``
    - ``await send_message(room_id, body, msgtype="m.text") -> event_id``
    - ``await close() -> None``

E2EE rooms are deferred to AD-806b (needs libolm). Plaintext rooms work
without it.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class MatrixAPIError(Exception):
    """Matrix server returned an HTTP non-2xx or an errcode payload."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        errcode: str | None = None,
        payload: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.errcode = errcode
        self.payload = payload


class MatrixClient:
    """Minimal Matrix client-server API client."""

    def __init__(
        self,
        homeserver: str,
        *,
        access_token: str | None = None,
        http: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
    ) -> None:
        if not homeserver:
            raise ValueError("MatrixClient requires a homeserver URL")
        self._homeserver = homeserver.rstrip("/")
        self._access_token = access_token
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(timeout=timeout)

    @property
    def access_token(self) -> str | None:
        return self._access_token

    def _url(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return f"{self._homeserver}/_matrix/client/v3{path}"

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self._access_token:
            h["Authorization"] = f"Bearer {self._access_token}"
        return h

    async def _call(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
    ) -> Any:
        url = self._url(path)
        try:
            response = await self._http.request(
                method, url, params=params, json=json_body, headers=self._headers(),
            )
        except httpx.TimeoutException as exc:
            raise MatrixAPIError(f"{method} {path} timed out", status_code=None) from exc
        except httpx.RequestError as exc:
            raise MatrixAPIError(f"{method} {path} transport error: {exc}", status_code=None) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise MatrixAPIError(
                f"{method} {path} returned non-JSON (status={response.status_code})",
                status_code=response.status_code,
            ) from exc

        if not response.is_success:
            errcode = payload.get("errcode") if isinstance(payload, dict) else None
            error_msg = payload.get("error") if isinstance(payload, dict) else None
            raise MatrixAPIError(
                f"{method} {path} failed: {errcode or response.status_code}: {error_msg or response.text}",
                status_code=response.status_code,
                errcode=errcode,
                payload=payload if isinstance(payload, dict) else None,
            )
        return payload

    # ---------- auth ----------

    async def login_password(self, user_id: str, password: str) -> str:
        """Login with user_id + password; returns the access token.

        The adapter saves the token in its config so subsequent boots
        don't need the password.
        """
        body = {
            "type": "m.login.password",
            "identifier": {"type": "m.id.user", "user": user_id},
            "password": password,
        }
        result = await self._call("POST", "/login", json_body=body)
        token = result.get("access_token") if isinstance(result, dict) else None
        if not isinstance(token, str):
            raise MatrixAPIError("login response did not include access_token", payload=result)
        self._access_token = token
        return token

    async def whoami(self) -> str:
        """Return the canonical user_id for the active access token."""
        result = await self._call("GET", "/account/whoami")
        user_id = result.get("user_id") if isinstance(result, dict) else None
        if not isinstance(user_id, str):
            raise MatrixAPIError("whoami did not return user_id", payload=result)
        return user_id

    # ---------- room ops ----------

    async def join_room(self, room_id_or_alias: str) -> str:
        """Join a room (or accept an invite). Returns the canonical room_id."""
        # URL-quote the alias/id — handled by httpx via params? No, this
        # goes in the path. We rely on httpx to encode unsafe characters.
        from urllib.parse import quote
        result = await self._call(
            "POST", f"/join/{quote(room_id_or_alias, safe='!#')}",
        )
        room_id = result.get("room_id") if isinstance(result, dict) else None
        return room_id if isinstance(room_id, str) else room_id_or_alias

    # ---------- sync / send ----------

    async def sync(
        self,
        *,
        since: str | None = None,
        timeout_ms: int = 25000,
        full_state: bool = False,
    ) -> dict:
        """Long-poll for inbound events. Returns the full sync payload
        (with ``next_batch`` to feed back as ``since`` on the next call).
        """
        params: dict[str, Any] = {"timeout": timeout_ms}
        if since is not None:
            params["since"] = since
        if full_state:
            params["full_state"] = "true"
        result = await self._call("GET", "/sync", params=params)
        return result if isinstance(result, dict) else {}

    async def send_message(
        self,
        room_id: str,
        body: str,
        *,
        msgtype: str = "m.text",
    ) -> str:
        """Send a text message to a room. Returns the new event_id."""
        txn_id = uuid.uuid4().hex
        from urllib.parse import quote
        result = await self._call(
            "PUT",
            f"/rooms/{quote(room_id, safe='!')}/send/m.room.message/{txn_id}",
            json_body={"msgtype": msgtype, "body": body},
        )
        event_id = result.get("event_id") if isinstance(result, dict) else None
        return event_id if isinstance(event_id, str) else ""

    # ---------- lifecycle ----------

    async def close(self) -> None:
        if self._owns_http:
            try:
                await self._http.aclose()
            except Exception:
                logger.warning("AD-806: MatrixClient http.aclose raised", exc_info=True)
