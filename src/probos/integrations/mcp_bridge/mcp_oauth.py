"""AD-1017: ``McpOAuthProvider`` — per-server OAuth authorization-code provider.

Modeled on AD-720c ``cloud_pickers.provider.CloudPickerProvider`` /
``google_drive.GoogleDriveProvider`` but **parameterized by the record's
``oauth_json``** (a per-server, non-secret OAuth client config) plus the
vault-stored ``client_secret``. The cloud-picker code is reused by IMPORT only
(``OAuthTokenBundle``) — none of it is modified.

Three operations, all over the resident ``httpx`` dep (no new pip deps):

* ``start_authorization(*, state) -> str`` — build the consent URL.
* ``async handle_callback(*, code) -> OAuthTokenBundle`` — POST
  ``grant_type=authorization_code`` to ``token_url``.
* ``async refresh(*, refresh_token) -> OAuthTokenBundle`` — POST
  ``grant_type=refresh_token`` to ``token_url``.

**Security:** token *values* are never logged. Failures log only the HTTP
status code / exception type, never the response body (which on success carries
the token).
"""

from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import urlencode

import httpx

from probos.cloud_pickers.tokens import OAuthTokenBundle

logger = logging.getLogger(__name__)


class McpOAuthError(Exception):
    """AD-1017: MCP OAuth token-exchange failure.

    ``detail`` is a stable machine-readable string the router surfaces in
    ``HTTPException.detail``. Self-contained (not coupled to the cloud-picker
    ``ProviderError`` taxonomy) so the MCP provider does not import private
    cloud-picker error types.
    """

    def __init__(self, detail: str, *, status: int = 502) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status = status


class McpOAuthProvider:
    """AD-1017: per-server OAuth authorization-code provider for MCP servers.

    Parameterized by the non-secret OAuth client config (from the record's
    ``oauth_json``) + the vault-stored ``client_secret``. ``http_client_factory``
    is a zero-arg callable returning an ``httpx.AsyncClient`` (tests inject a
    ``MockTransport``-backed client; default constructs a vanilla one per call,
    closed via ``async with``).
    """

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        authorize_url: str,
        token_url: str,
        scopes: list[str] | None = None,
        redirect_uri: str = "",
        device_authorization_url: str = "",
        http_client_factory: Any = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._authorize_url = authorize_url
        self._token_url = token_url
        self._scopes = list(scopes or [])
        self._redirect_uri = redirect_uri
        self._device_authorization_url = device_authorization_url
        self._http_factory = http_client_factory or (
            lambda: httpx.AsyncClient(timeout=30.0)
        )

    # -- 1. Authorization URL --------------------------------------------

    def start_authorization(self, *, state: str) -> str:
        """Return the provider's OAuth consent URL (caller stores ``state``)."""
        params = {
            "client_id": self._client_id,
            "redirect_uri": self._redirect_uri,
            "response_type": "code",
            "scope": " ".join(self._scopes),
            "state": state,
        }
        return f"{self._authorize_url}?{urlencode(params)}"

    # -- 2. Callback (code -> bundle) ------------------------------------

    async def handle_callback(self, *, code: str) -> OAuthTokenBundle:
        """Exchange the authorization ``code`` for an :class:`OAuthTokenBundle`."""
        body = {
            "code": code,
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "redirect_uri": self._redirect_uri,
            "grant_type": "authorization_code",
        }
        return await self._token_post(body, prior_refresh_token=None)

    # -- 3. Refresh (refresh_token -> bundle) ----------------------------

    async def refresh(self, *, refresh_token: str) -> OAuthTokenBundle:
        """Exchange a ``refresh_token`` for a fresh :class:`OAuthTokenBundle`."""
        body = {
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        return await self._token_post(body, prior_refresh_token=refresh_token)

    # -- 4. Device authorization (RFC 8628) ------------------------------

    async def start_device_authorization(self) -> dict[str, Any]:
        """AD-1017a: begin an RFC 8628 device-code grant.

        POST ``client_id``/``scope`` (+ ``client_secret`` only when set) to the
        device-authorization endpoint; return the provider payload (carrying the
        ``device_code`` poll secret, ``user_code``, and ``verification_uri``).
        The caller holds ``device_code`` server-side — it is never returned to a
        browser. Raises :class:`McpOAuthError` on transport error, a non-200, or
        a payload missing any of the three required fields. Never logs the body.
        """
        data: dict[str, str] = {
            "client_id": self._client_id,
            "scope": " ".join(self._scopes),
        }
        if self._client_secret:
            data["client_secret"] = self._client_secret
        async with self._http_factory() as client:
            try:
                r = await client.post(self._device_authorization_url, data=data)
            except httpx.HTTPError as exc:
                logger.warning(
                    "AD-1017a: MCP device-authorization transport error: %s; "
                    "surfacing device_authorization_failed (no body logged)",
                    type(exc).__name__,
                )
                raise McpOAuthError("device_authorization_failed") from exc
        if r.status_code != 200:
            logger.warning(
                "AD-1017a: MCP device-authorization failed status=%d "
                "(response body not logged)",
                r.status_code,
            )
            raise McpOAuthError("device_authorization_failed")
        payload = r.json()
        if not isinstance(payload, dict) or not (
            payload.get("device_code")
            and payload.get("user_code")
            and payload.get("verification_uri")
        ):
            raise McpOAuthError("device_authorization_invalid")
        return payload

    async def poll_device_token(
        self, *, device_code: str
    ) -> OAuthTokenBundle | None:
        """AD-1017a: poll the token endpoint for an RFC 8628 device-code grant.

        Returns an :class:`OAuthTokenBundle` on success, or ``None`` while the
        grant is still pending (``authorization_pending``/``slow_down`` — RFC
        8628 returns HTTP 400 for these *non-terminal* signals, so this MUST NOT
        reuse ``_token_post``, which raises on every non-200). Raises
        :class:`McpOAuthError` (``status=400``) only on a terminal error
        (``access_denied``/``expired_token``/``invalid_grant``/transport, or an
        unparsable error body). Never logs the body.
        """
        data: dict[str, str] = {
            "client_id": self._client_id,
            "device_code": device_code,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        }
        if self._client_secret:
            data["client_secret"] = self._client_secret
        async with self._http_factory() as client:
            try:
                r = await client.post(self._token_url, data=data)
            except httpx.HTTPError as exc:
                logger.warning(
                    "AD-1017a: MCP device-token poll transport error: %s; "
                    "surfacing device_token_failed (no body logged)",
                    type(exc).__name__,
                )
                raise McpOAuthError("device_token_failed") from exc
        if r.status_code == 200:
            return _bundle_from_payload(r.json(), prior_refresh_token=None)
        try:
            parsed = r.json()
            err = parsed.get("error", "") if isinstance(parsed, dict) else ""
        except (ValueError, TypeError):
            err = ""  # unparsable error body -> treat as terminal
        if err in {"authorization_pending", "slow_down"}:
            return None
        logger.warning(
            "AD-1017a: MCP device-token poll terminal error status=%d "
            "(response body not logged)",
            r.status_code,
        )
        raise McpOAuthError(err or "device_token_failed", status=400)

    # -- token POST ------------------------------------------------------

    async def _token_post(
        self, body: dict[str, str], *, prior_refresh_token: str | None
    ) -> OAuthTokenBundle:
        """POST ``body`` to ``token_url`` and parse the bundle.

        Never logs the response body or any token value — only the status code
        / exception type. Raises :class:`McpOAuthError` on transport error or a
        non-200 response.
        """
        async with self._http_factory() as client:
            try:
                r = await client.post(self._token_url, data=body)
            except httpx.HTTPError as exc:
                logger.warning(
                    "AD-1017: MCP OAuth token exchange transport error: %s; "
                    "surfacing oauth_exchange_failed (no secret logged)",
                    type(exc).__name__,
                )
                raise McpOAuthError("oauth_exchange_failed") from exc
        if r.status_code != 200:
            logger.warning(
                "AD-1017: MCP OAuth token exchange failed status=%d "
                "(response body not logged — may carry a token)",
                r.status_code,
            )
            raise McpOAuthError("oauth_exchange_failed")
        return _bundle_from_payload(r.json(), prior_refresh_token=prior_refresh_token)


def _bundle_from_payload(
    payload: dict[str, Any], *, prior_refresh_token: str | None
) -> OAuthTokenBundle:
    """Build an :class:`OAuthTokenBundle` from a token-endpoint JSON payload.

    Preserves ``prior_refresh_token`` when the refresh response omits one (many
    providers do not rotate the refresh_token on a refresh exchange).
    """
    access = payload.get("access_token")
    if not isinstance(access, str) or not access:
        raise McpOAuthError("oauth_no_access_token")
    refresh = payload.get("refresh_token") or prior_refresh_token
    expires_in = payload.get("expires_in")
    expires_at = (
        time.time() + float(expires_in)
        if isinstance(expires_in, (int, float))
        else 0.0
    )
    return OAuthTokenBundle(
        access_token=access,
        refresh_token=refresh if isinstance(refresh, str) and refresh else None,
        expires_at=expires_at,
        token_type=str(payload.get("token_type", "Bearer")),
    )


__all__ = ["McpOAuthProvider", "McpOAuthError"]
