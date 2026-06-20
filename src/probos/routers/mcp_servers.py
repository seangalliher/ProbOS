"""AD-1015: CRUD management API for runtime-mutable MCP server registrations.

Prefix ``/api/mcp/servers``. Gated on ``config.mcp.management_enabled`` (new,
default-OFF): every endpoint 404s with ``feature_disabled`` when off, so the
router can be included unconditionally (matching api.py's flat include loop)
without changing any existing path. Reads ``runtime.mcp_server_store`` (the
AD-1015 store) and ``runtime.mcp_bridge`` (AD-449/AD-1014) via ``getattr`` ->
honest-degrade 503 when absent.

Bridge key rule (single source of truth, §4): ``key = url if type=='http' else
name`` — the value ``MCPBridge._clients`` is keyed by. Await discipline: the http
register path is **sync** (``register_server``); the stdio register/unregister
paths are **async** (``register_stdio_server`` / ``unregister_server``).

Credentials (``auth_kind``/``credential_ref``) are inert stored strings this AD
(AD-1016 resolves them). No secret value is ever persisted or returned — the
``validate_record`` denylist + ``McpServerRecord.to_public_dict`` are the guards.
"""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from probos.cloud_pickers.tokens import CsrfStateStore, OAuthTokenBundle
from probos.integrations.mcp_bridge.access import (
    mcp_server_tool_id,
    mcp_tool_tool_id,
    resolve_mcp_access,
)
from probos.integrations.mcp_bridge.client import MCPClient
from probos.integrations.mcp_bridge.mcp_oauth import McpOAuthError, McpOAuthProvider
from probos.integrations.mcp_bridge.risk import McpToolRisk, resolve_tool_risk
from probos.integrations.mcp_bridge.session import MCPSession
from probos.integrations.mcp_bridge.store import (
    McpServerRecord,
    McpServerValidationError,
    validate_record,
)
from probos.integrations.mcp_bridge.transport import StdioTransport
from probos.routers.deps import get_runtime
from probos.tools.browser.credentials import CredentialScope
from probos.tools.protocol import ToolPermission

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mcp/servers", tags=["mcp-servers"])

# AD-1017: the Captain identity that may read captain-only vault credentials
# (``CredentialScope()`` empty allowed-set = captain-only).
_CAPTAIN_ID = "captain"

# AD-1019e: legal per-tool risk override strings — derived from the enum so a
# future 4th tier is covered automatically (single source of truth).
_RISK_VALUES: frozenset[str] = frozenset(r.value for r in McpToolRisk)

# AD-1017: OAuth CSRF state TTL (seconds). MCPConfig carries no OAuth-state field
# (config.py is out of scope this AD); the in-memory store's own default is also
# 300s. Mirrors cloud_pickers' per-runtime lazy state store.
_OAUTH_STATE_TTL_SECONDS = 300

# Per-runtime CSRF state stores keyed by id(runtime); mirrors
# routers/cloud_pickers.py:59. Tests reset via ``_clear_state_stores()``.
_STATE_STORES: dict[int, CsrfStateStore] = {}


def _clear_state_stores() -> None:
    """Test-only: drop all per-runtime CSRF stores."""
    _STATE_STORES.clear()


def _get_state_store(runtime: Any) -> CsrfStateStore:
    """Lazily build (once per runtime) the OAuth CSRF state store."""
    key = id(runtime)
    store = _STATE_STORES.get(key)
    if store is None:
        store = CsrfStateStore(ttl_seconds=_OAUTH_STATE_TTL_SECONDS)
        _STATE_STORES[key] = store
    return store


def _vault_or_503(runtime: Any) -> Any:
    """Honest-degrade 503 when the credential vault was not constructed."""
    vault = getattr(runtime, "credential_vault", None)
    if vault is None:
        raise HTTPException(status_code=503, detail="credential_vault_unavailable")
    return vault


def _static_ref(server_id: str) -> str:
    return f"mcp:{server_id}"


def _oauth_ref(server_id: str) -> str:
    return f"mcp:{server_id}:oauth"


def _oauth_secret_ref(server_id: str) -> str:
    return f"mcp:{server_id}:oauth_secret"


def _bundle_or_none(value: str) -> OAuthTokenBundle | None:
    """Parse a vault-stored OAuth bundle JSON; warn + None on corruption."""
    try:
        return OAuthTokenBundle.model_validate_json(value)
    except (ValueError, TypeError):
        logger.warning(
            "AD-1017: MCP OAuth bundle in vault is not valid OAuthTokenBundle "
            "JSON; treating as missing (no secret logged)"
        )
        return None

# Connection-affecting fields — a change to any of these on an enabled row forces
# a bridge re-register (PUT). ``enabled`` is handled by the enable/disable axis.
_CONNECTION_FIELDS = frozenset(
    {"type", "url", "headers", "command", "args", "env", "cwd", "timeout_seconds"}
)


class McpServerBody(BaseModel):
    """Create body for ``POST /api/mcp/servers``."""

    name: str
    type: str = "http"
    url: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str = ""
    timeout_seconds: float | None = None
    enabled: bool = True
    auth_kind: str = "none"
    credential_ref: str = ""


class McpServerUpdateBody(BaseModel):
    """Partial-update body for ``PUT /api/mcp/servers/{id}`` (all optional)."""

    name: str | None = None
    type: str | None = None
    url: str | None = None
    headers: dict[str, str] | None = None
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    cwd: str | None = None
    timeout_seconds: float | None = None
    enabled: bool | None = None
    auth_kind: str | None = None
    credential_ref: str | None = None
    # AD-1019e (DD-2): server-level default risk tier (open|confirm|consensus).
    # The existing model_dump→replace→validate_record merge applies it
    # generically; validate_record's _VALID_RISK_TIERS guard rejects bad values.
    default_risk: str | None = None


class CredentialBody(BaseModel):
    """Body for ``POST /api/mcp/servers/{id}/credential`` (static token).

    The token ``value`` is stored in the credential vault by ref — never on the
    record, never echoed back. ``header_name``/``scheme`` (http) or ``env_var``
    (stdio) are the non-secret resolution metadata persisted on the record.
    """

    value: str
    header_name: str = "Authorization"
    scheme: str = "Bearer"
    env_var: str = ""


class OAuthStartBody(BaseModel):
    """Body for ``POST /api/mcp/servers/{id}/auth/start``.

    The non-secret OAuth client config is persisted to ``record.oauth_json``;
    ``client_secret`` (if supplied) is stashed in the vault under
    ``mcp:{id}:oauth_secret`` — never in ``oauth_json`` or any response.
    """

    client_id: str = ""
    client_secret: str = ""
    authorize_url: str = ""
    token_url: str = ""
    scopes: list[str] = Field(default_factory=list)
    redirect_uri: str = ""


class McpAgentAccessBody(BaseModel):
    """Body for ``POST /api/mcp/servers/{id}/agents/{agent_id}`` (AD-1019).

    ``enabled`` flips between a grant (``True``) and a restriction (``False``);
    ``tool`` (when present) scopes the decision to a single tool, otherwise the
    grant applies server-wide (all tools).
    """

    enabled: bool
    tool: str | None = None


class RiskBody(BaseModel):
    """Body for ``PUT /api/mcp/servers/{id}/tools/{tool}/risk`` (AD-1019e)."""

    risk: str


def _require_enabled(runtime: Any) -> None:
    """404 ``feature_disabled`` unless ``config.mcp.management_enabled`` is True."""
    cfg = getattr(getattr(runtime, "config", None), "mcp", None)
    if cfg is None or not getattr(cfg, "management_enabled", False):
        raise HTTPException(status_code=404, detail="feature_disabled")


def _require_store(runtime: Any) -> Any:
    """Honest-degrade 503 when the store was not constructed."""
    store = getattr(runtime, "mcp_server_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="mcp_server_store_unavailable")
    return store


def _command_allowlist(runtime: Any) -> list[str]:
    cfg = getattr(getattr(runtime, "config", None), "mcp", None)
    return list(getattr(cfg, "command_allowlist", []) or [])


def _bridge_key(record: McpServerRecord) -> str:
    """The value ``MCPBridge._clients`` is keyed by: url (http) / name (stdio)."""
    return record.url if record.type == "http" else record.name


def _request_timeout(runtime: Any, record: McpServerRecord) -> float:
    if record.timeout_seconds is not None:
        return record.timeout_seconds
    cfg = getattr(getattr(runtime, "config", None), "mcp", None)
    return float(getattr(cfg, "request_timeout_seconds", 30.0) or 30.0)


async def _resolve_secret_value(record: McpServerRecord, runtime: Any) -> str | None:
    """Resolve the raw secret value for a record from the credential vault.

    ``static`` → the stored token; ``oauth`` → the bundle's ``access_token``.
    Returns ``None`` (honest-degrade, warning, **no secret logged**) when there
    is no vault, no ``credential_ref``, a vault miss, or a corrupt bundle — the
    server then registers unauthenticated.
    """
    vault = getattr(runtime, "credential_vault", None)
    if vault is None or not record.credential_ref:
        return None
    raw = await vault.read(
        ref=record.credential_ref, requesting_agent_id=_CAPTAIN_ID
    )
    if raw is None:
        logger.warning(
            "AD-1017: credential vault miss for MCP server %s (auth_kind=%s, ref "
            "present, value absent); registering unauthenticated (no secret logged)",
            record.name,
            record.auth_kind,
        )
        return None
    if record.auth_kind == "oauth":
        bundle = _bundle_or_none(raw)
        if bundle is None:
            return None
        return bundle.access_token
    return raw


async def _resolve_auth_headers(
    record: McpServerRecord, runtime: Any
) -> dict[str, str]:
    """Build the http auth header(s) for a record. ``{}`` for none/miss.

    ``auth_kind=="none"`` → ``{}`` (register byte-identical to AD-1015).
    ``static`` → ``{header_name: f"{scheme} {value}".strip()}`` (bare ``value``
    when ``scheme`` is empty). ``oauth`` → ``{"Authorization": "Bearer <access>"}``.
    """
    if record.auth_kind == "none":
        return {}
    value = await _resolve_secret_value(record, runtime)
    if value is None:
        return {}
    if record.auth_kind == "oauth":
        return {"Authorization": f"Bearer {value}"}
    name = record.auth_header_name or "Authorization"
    scheme = record.auth_scheme
    return {name: f"{scheme} {value}".strip() if scheme else value}


async def _resolve_auth_env(record: McpServerRecord, runtime: Any) -> dict[str, str]:
    """Build the stdio auth env var for a record. ``{}`` unless ``auth_env_var`` set.

    The operator names the env var their server expects (e.g. ``API_KEY``); when
    unset, stdio registers unauthenticated (http is the primary auth path).
    """
    if record.auth_kind == "none" or not record.auth_env_var:
        return {}
    value = await _resolve_secret_value(record, runtime)
    if value is None:
        return {}
    return {record.auth_env_var: value}


async def _register(runtime: Any, record: McpServerRecord) -> None:
    """Live-register via the §4 key rule, merging resolved auth — http sync, stdio await.

    ``auth_kind=="none"`` resolves to ``{}`` so the merged ``headers``/``env``
    are byte-identical to the AD-1015 ``dict(record.headers)`` / ``dict(record.env)``.
    """
    bridge = getattr(runtime, "mcp_bridge", None)
    if bridge is None:
        return
    if record.type == "http":
        auth_headers = await _resolve_auth_headers(record, runtime)
        bridge.register_server(
            record.url, headers={**record.headers, **auth_headers}
        )
    else:
        auth_env = await _resolve_auth_env(record, runtime)
        await bridge.register_stdio_server(
            name=record.name,
            command=record.command,
            args=list(record.args),
            env={**record.env, **auth_env},
            cwd=record.cwd,
            timeout=record.timeout_seconds,
        )


async def _unregister(bridge: Any, key: str) -> None:
    """Best-effort bridge teardown (ignores an unknown key)."""
    if bridge is None:
        return
    await bridge.unregister_server(key)


async def _reregister(runtime: Any, record: McpServerRecord) -> None:
    """Unregister-then-register an enabled row so new auth reaches the wire.

    ``register_server``/``register_stdio_server`` no-op on a duplicate key, so a
    credential/token change on an already-registered server must drop the old
    client first. No-op when the row is disabled.
    """
    if not record.enabled:
        return
    bridge = getattr(runtime, "mcp_bridge", None)
    await _unregister(bridge, _bridge_key(record))
    await _register(runtime, record)


@router.get("")
async def list_servers(runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    _require_enabled(runtime)
    store = _require_store(runtime)
    records = await store.list()
    return {"servers": [r.to_public_dict() for r in records], "count": len(records)}


@router.post("", status_code=201)
async def create_server(
    body: McpServerBody, runtime: Any = Depends(get_runtime)
) -> dict[str, Any]:
    _require_enabled(runtime)
    store = _require_store(runtime)
    record = McpServerRecord(
        name=body.name,
        type=body.type,
        url=body.url,
        headers=dict(body.headers),
        command=body.command,
        args=list(body.args),
        env=dict(body.env),
        cwd=body.cwd,
        timeout_seconds=body.timeout_seconds,
        enabled=body.enabled,
        auth_kind=body.auth_kind,
        credential_ref=body.credential_ref,
    )
    try:
        validate_record(record, command_allowlist=_command_allowlist(runtime))
    except McpServerValidationError as exc:
        raise HTTPException(
            status_code=400, detail={"error": exc.code, "message": str(exc)}
        )
    try:
        created = await store.create(record)
    except ValueError as exc:
        raise HTTPException(
            status_code=409, detail={"error": "duplicate_name", "message": str(exc)}
        )
    if created.enabled:
        await _register(runtime, created)
    return created.to_public_dict()


@router.get("/{server_id}")
async def get_server(
    server_id: str, runtime: Any = Depends(get_runtime)
) -> dict[str, Any]:
    _require_enabled(runtime)
    store = _require_store(runtime)
    record = await store.get(server_id)
    if record is None:
        raise HTTPException(status_code=404, detail="not_found")
    return record.to_public_dict()


@router.put("/{server_id}")
async def update_server(
    server_id: str,
    body: McpServerUpdateBody,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    _require_enabled(runtime)
    store = _require_store(runtime)
    existing = await store.get(server_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="not_found")

    fields = body.model_dump(exclude_unset=True)
    # The update body carries only valid McpServerRecord fields, so the merge is
    # a direct replace — used solely to validate the prospective record before
    # it is persisted.
    merged = replace(existing, **fields)
    try:
        validate_record(merged, command_allowlist=_command_allowlist(runtime))
    except McpServerValidationError as exc:
        raise HTTPException(
            status_code=400, detail={"error": exc.code, "message": str(exc)}
        )

    old_key = _bridge_key(existing)
    try:
        updated = await store.update(server_id, **fields)
    except ValueError as exc:
        raise HTTPException(
            status_code=409, detail={"error": "duplicate_name", "message": str(exc)}
        )
    if updated is None:  # pragma: no cover - existing was just fetched
        raise HTTPException(status_code=404, detail="not_found")

    # Re-register on a connection-affecting change when the row is enabled.
    if _CONNECTION_FIELDS & set(fields) and updated.enabled:
        bridge = getattr(runtime, "mcp_bridge", None)
        await _unregister(bridge, old_key)
        await _register(runtime, updated)
    return updated.to_public_dict()


@router.delete("/{server_id}")
async def delete_server(
    server_id: str, runtime: Any = Depends(get_runtime)
) -> dict[str, Any]:
    _require_enabled(runtime)
    store = _require_store(runtime)
    existing = await store.get(server_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="not_found")
    await _unregister(getattr(runtime, "mcp_bridge", None), _bridge_key(existing))
    # AD-1016: credential cleanup via credential_ref is a later seam — secret
    # deletion is not implemented here (credential_ref is an inert string today).
    await store.delete(server_id)
    return {"deleted": True, "id": server_id}


@router.post("/{server_id}/enable")
async def enable_server(
    server_id: str, runtime: Any = Depends(get_runtime)
) -> dict[str, Any]:
    _require_enabled(runtime)
    store = _require_store(runtime)
    record = await store.set_enabled(server_id, True)
    if record is None:
        raise HTTPException(status_code=404, detail="not_found")
    await _register(runtime, record)
    return record.to_public_dict()


@router.post("/{server_id}/disable")
async def disable_server(
    server_id: str, runtime: Any = Depends(get_runtime)
) -> dict[str, Any]:
    _require_enabled(runtime)
    store = _require_store(runtime)
    record = await store.set_enabled(server_id, False)
    if record is None:
        raise HTTPException(status_code=404, detail="not_found")
    await _unregister(getattr(runtime, "mcp_bridge", None), _bridge_key(record))
    return record.to_public_dict()


@router.post("/{server_id}/test")
async def test_server(
    server_id: str, runtime: Any = Depends(get_runtime)
) -> dict[str, Any]:
    """Transient connection test — never persisted, never touches ``_clients``.

    Builds a throwaway client, runs ``initialize()`` + ``list_tools()``, and
    **closes it in a ``finally``** (no leaked subprocess). Returns
    ``{ok, tool_count}`` or ``{ok: false, error}`` at HTTP 200 (honest-degrade —
    a connection/server failure is a result, not a 500).
    """
    _require_enabled(runtime)
    store = _require_store(runtime)
    record = await store.get(server_id)
    if record is None:
        raise HTTPException(status_code=404, detail="not_found")

    timeout = _request_timeout(runtime, record)
    try:
        if record.type == "http":
            client = MCPClient(
                session=MCPSession(
                    server_url=record.url, headers=dict(record.headers)
                ),
                timeout=timeout,
            )
            try:
                await client.initialize()
                tools = await client.list_tools()
                return {"ok": True, "tool_count": len(tools)}
            finally:
                await client.close()
        else:
            transport = StdioTransport(
                command=record.command,
                args=list(record.args),
                env=dict(record.env),
                cwd=record.cwd,
                timeout=timeout,
                name=record.name,
            )
            client = MCPClient(
                session=MCPSession(server_url=f"stdio:{record.name}"),
                transport=transport,
                timeout=timeout,
            )
            try:
                await transport.start()
                await client.initialize()
                tools = await client.list_tools()
                return {"ok": True, "tool_count": len(tools)}
            finally:
                await client.close()
    except Exception as exc:  # honest-degrade: never 500 for a connection failure
        logger.warning(
            "AD-1015: MCP test-connection failed for %s: %s",
            record.name,
            exc,
            exc_info=True,
        )
        return {"ok": False, "error": str(exc)[:300]}


# --------------------------------------------------------------------------- #
# AD-1017: credential + OAuth endpoints (secrets only in the vault, by ref)
# --------------------------------------------------------------------------- #


def _load_oauth_json(record: McpServerRecord) -> dict[str, Any]:
    """Parse ``record.oauth_json`` (non-secret OAuth client config). ``{}`` on miss."""
    if not record.oauth_json:
        return {}
    try:
        data = json.loads(record.oauth_json)
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _merge_oauth_config(
    record: McpServerRecord, body: OAuthStartBody
) -> dict[str, Any]:
    """Merge the start body's non-secret OAuth config over the record's stored one.

    The ``client_secret`` is intentionally excluded — it lives only in the vault.
    """
    existing = _load_oauth_json(record)
    return {
        "client_id": body.client_id or existing.get("client_id", ""),
        "authorize_url": body.authorize_url or existing.get("authorize_url", ""),
        "token_url": body.token_url or existing.get("token_url", ""),
        "scopes": list(body.scopes) or list(existing.get("scopes", []) or []),
        "redirect_uri": body.redirect_uri or existing.get("redirect_uri", ""),
    }


async def _build_oauth_provider(
    record: McpServerRecord, runtime: Any
) -> McpOAuthProvider:
    """Build the per-server provider from ``oauth_json`` + the vault client_secret."""
    vault = _vault_or_503(runtime)
    cfg = _load_oauth_json(record)
    secret = (
        await vault.read(
            ref=_oauth_secret_ref(record.id), requesting_agent_id=_CAPTAIN_ID
        )
        or ""
    )
    return McpOAuthProvider(
        client_id=str(cfg.get("client_id", "")),
        client_secret=secret,
        authorize_url=str(cfg.get("authorize_url", "")),
        token_url=str(cfg.get("token_url", "")),
        scopes=list(cfg.get("scopes", []) or []),
        redirect_uri=str(cfg.get("redirect_uri", "")),
    )


def _popup_close_html(server_id: str) -> str:
    """The same popup-close HTML shape as the cloud-pickers callback.

    No token data crosses the iframe boundary — only the (sanitized) server id.
    """
    safe = server_id.replace("'", "")
    return (
        "<html><body><script>"
        "try{window.opener.postMessage("
        f"{{type:'oauth_complete',provider:'mcp',server_id:'{safe}'}}"
        ",'*');}catch(e){};"
        "window.close();"
        "</script></body></html>"
    )


@router.post("/{server_id}/credential")
async def set_credential(
    server_id: str,
    body: CredentialBody,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Store a static token in the vault by ref; flip the record to ``static``.

    The token ``value`` never touches the store row or the response — only the
    non-secret ``credential_ref``/``auth_header_name``/``auth_scheme``/
    ``auth_env_var`` are persisted. 503 when no vault.
    """
    _require_enabled(runtime)
    store = _require_store(runtime)
    record = await store.get(server_id)
    if record is None:
        raise HTTPException(status_code=404, detail="not_found")
    vault = _vault_or_503(runtime)
    ref = _static_ref(server_id)
    await vault.store(ref=ref, value=body.value, scope=CredentialScope())
    updated = await store.update(
        server_id,
        auth_kind="static",
        credential_ref=ref,
        auth_header_name=body.header_name,
        auth_scheme=body.scheme,
        auth_env_var=body.env_var,
    )
    if updated is None:  # pragma: no cover - record was just fetched
        raise HTTPException(status_code=404, detail="not_found")
    await _reregister(runtime, updated)
    return updated.to_public_dict()


@router.delete("/{server_id}/credential")
async def delete_credential(
    server_id: str, runtime: Any = Depends(get_runtime)
) -> dict[str, Any]:
    """Delete the stored credential and flip the record back to ``none``."""
    _require_enabled(runtime)
    store = _require_store(runtime)
    record = await store.get(server_id)
    if record is None:
        raise HTTPException(status_code=404, detail="not_found")
    vault = getattr(runtime, "credential_vault", None)
    if vault is not None and record.credential_ref:
        await vault.delete(ref=record.credential_ref)
    updated = await store.update(server_id, auth_kind="none", credential_ref="")
    if updated is None:  # pragma: no cover - record was just fetched
        raise HTTPException(status_code=404, detail="not_found")
    await _reregister(runtime, updated)
    return updated.to_public_dict()


@router.post("/{server_id}/auth/start")
async def oauth_start(
    server_id: str,
    body: OAuthStartBody,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Persist the non-secret OAuth config + vault the client_secret; return the consent URL."""
    _require_enabled(runtime)
    store = _require_store(runtime)
    record = await store.get(server_id)
    if record is None:
        raise HTTPException(status_code=404, detail="not_found")
    vault = _vault_or_503(runtime)
    if body.client_secret:
        await vault.store(
            ref=_oauth_secret_ref(server_id),
            value=body.client_secret,
            scope=CredentialScope(),
        )
    updated = await store.update(
        server_id, oauth_json=json.dumps(_merge_oauth_config(record, body))
    )
    if updated is None:  # pragma: no cover - record was just fetched
        raise HTTPException(status_code=404, detail="not_found")
    provider = await _build_oauth_provider(updated, runtime)
    state = _get_state_store(runtime).mint(server_id)
    auth_url = provider.start_authorization(state=state)
    return {"auth_url": auth_url, "state": state}


@router.get("/{server_id}/auth/callback")
async def oauth_callback(
    server_id: str,
    code: str,
    state: str,
    runtime: Any = Depends(get_runtime),
) -> HTMLResponse:
    """Consume the CSRF state, exchange ``code`` for a bundle, persist it via vault."""
    _require_enabled(runtime)
    store = _require_store(runtime)
    if not _get_state_store(runtime).consume(state, server_id):
        raise HTTPException(status_code=403, detail="invalid_state_token")
    record = await store.get(server_id)
    if record is None:
        raise HTTPException(status_code=404, detail="not_found")
    vault = _vault_or_503(runtime)
    provider = await _build_oauth_provider(record, runtime)
    try:
        bundle = await provider.handle_callback(code=code)
    except McpOAuthError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail) from exc
    ref = _oauth_ref(server_id)
    await vault.store(ref=ref, value=bundle.model_dump_json(), scope=CredentialScope())
    updated = await store.update(server_id, auth_kind="oauth", credential_ref=ref)
    if updated is not None:
        await _reregister(runtime, updated)
    return HTMLResponse(_popup_close_html(server_id))


@router.post("/{server_id}/auth/refresh")
async def oauth_refresh(
    server_id: str, runtime: Any = Depends(get_runtime)
) -> dict[str, Any]:
    """Reactive refresh: re-exchange the stored refresh_token, re-store, re-register."""
    _require_enabled(runtime)
    store = _require_store(runtime)
    record = await store.get(server_id)
    if record is None:
        raise HTTPException(status_code=404, detail="not_found")
    vault = _vault_or_503(runtime)
    raw = await vault.read(ref=_oauth_ref(server_id), requesting_agent_id=_CAPTAIN_ID)
    bundle = _bundle_or_none(raw) if raw else None
    if bundle is None or not bundle.refresh_token:
        raise HTTPException(status_code=400, detail="no_refresh_token")
    provider = await _build_oauth_provider(record, runtime)
    try:
        new_bundle = await provider.refresh(refresh_token=bundle.refresh_token)
    except McpOAuthError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail) from exc
    ref = _oauth_ref(server_id)
    await vault.store(
        ref=ref, value=new_bundle.model_dump_json(), scope=CredentialScope()
    )
    updated = await store.update(server_id, auth_kind="oauth", credential_ref=ref)
    if updated is not None:
        await _reregister(runtime, updated)
    return {"refreshed": True}


# --------------------------------------------------------------------------- #
# AD-1019: per-agent + per-tool MCP enablement (reuse ToolPermissionStore via
# composite ids ``mcp:{name}`` / ``mcp:{name}:{tool}``). Authorization +
# enumeration substrate only — MCP-tool invocation wiring is AD-1019b.
# --------------------------------------------------------------------------- #


def _perm_store_or_503(runtime: Any) -> Any:
    """Honest-degrade 503 when the ToolPermissionStore was not constructed."""
    perms = getattr(runtime, "tool_permission_store", None)
    if perms is None:
        raise HTTPException(
            status_code=503, detail="tool_permission_store_unavailable"
        )
    return perms


def _risk_store_or_503(runtime: Any) -> Any:
    """Honest-degrade 503 when the McpToolRiskStore was not constructed (AD-1019e)."""
    risk_store = getattr(runtime, "mcp_tool_risk_store", None)
    if risk_store is None:
        raise HTTPException(
            status_code=503, detail="mcp_tool_risk_store_unavailable"
        )
    return risk_store


async def _enumerate_tools(
    runtime: Any, record: McpServerRecord
) -> tuple[list[dict[str, Any]], str | None]:
    """Enumerate a server's tools via the live bridge client. Never raises.

    Honest-degrade on every axis to ``([], reason)`` so the caller can emit
    ``{tools: [], count: 0, error}`` at HTTP 200: no bridge, an unregistered /
    disabled row (``get_client`` miss), or a connection/protocol failure during
    ``list_tools()``. On success returns ``([{name, description}, ...], None)``.
    """
    bridge = getattr(runtime, "mcp_bridge", None)
    if bridge is None:
        return [], "mcp_bridge_unavailable"
    client = bridge.get_client(_bridge_key(record))
    if client is None:
        return [], "not_registered"
    try:
        raw = await client.list_tools()
    except Exception as exc:  # honest-degrade: a connection failure is a result
        logger.warning(
            "AD-1019: list_tools failed for MCP server %s; returning empty + "
            "error (never 500): %s",
            record.name,
            exc,
            exc_info=True,
        )
        return [], str(exc)[:300]
    tools = [
        {"name": t.get("name", ""), "description": t.get("description", "")}
        for t in raw
        if isinstance(t, dict)
    ]
    return tools, None


@router.get("/{server_id}/tools")
async def list_server_tools(
    server_id: str, runtime: Any = Depends(get_runtime)
) -> dict[str, Any]:
    """Enumerate the tools an MCP server exposes (honest-degrade, never 500).

    AD-1019e: each tool also carries its effective ``risk`` tier + ``risk_source``
    (``override``|``default``) when the risk store is present. The risk store
    keys on the server RECORD id (the same key the AD-1019c dispatch reads —
    DD-1), and ``server_id`` here IS that record id, so the read is consistent.
    Honest-degrade: with no risk store the risk fields are OMITTED (the existing
    response shape is byte-identical).
    """
    _require_enabled(runtime)
    store = _require_store(runtime)
    record = await store.get(server_id)
    if record is None:
        raise HTTPException(status_code=404, detail="not_found")
    tools, error = await _enumerate_tools(runtime, record)
    risk_store = getattr(runtime, "mcp_tool_risk_store", None)
    if risk_store is not None:
        server_default = McpToolRisk(record.default_risk)
        for tool in tools:
            name = tool.get("name", "")
            override = risk_store.get_risk_sync(server_id, name)
            tool["risk"] = resolve_tool_risk(server_default, override).value
            tool["risk_source"] = "override" if override is not None else "default"
    result: dict[str, Any] = {"tools": tools, "count": len(tools)}
    if error:
        result["error"] = error
    return result


def _agent_department(runtime: Any, agent_id: str) -> str:
    """Resolve the agent's canonical crew/governance department (AD-1019b).

    Uses the public ontology accessor — NOT the private pool-group
    ``runtime._get_agent_department`` (that is a notification-display concept).
    Returns ``""`` when unavailable (honest-degrade → no dept grants fold).
    """
    reg = getattr(runtime, "registry", None)
    ont = getattr(runtime, "ontology", None)
    agent = reg.get(agent_id) if reg is not None else None
    if agent is None or ont is None:
        return ""
    return ont.get_agent_department(getattr(agent, "agent_type", "")) or ""


@router.get("/{server_id}/agents/{agent_id}/access")
async def get_agent_access(
    server_id: str, agent_id: str, runtime: Any = Depends(get_runtime)
) -> dict[str, Any]:
    """The agent's per-tool enablement for a server (resolved over grants)."""
    _require_enabled(runtime)
    store = _require_store(runtime)
    record = await store.get(server_id)
    if record is None:
        raise HTTPException(status_code=404, detail="not_found")
    tools, error = await _enumerate_tools(runtime, record)
    perms = getattr(runtime, "tool_permission_store", None)
    grants = perms.get_active_grants_sync(agent_id) if perms is not None else []
    # AD-1019b: department tier grants (3-source resolver).
    dept = _agent_department(runtime, agent_id)
    dept_store = getattr(runtime, "department_tool_grant_store", None)
    dept_grants = (
        dept_store.get_active_grants_sync(dept)
        if dept_store is not None and dept
        else []
    )
    # Server scope: an empty tool name folds to the server/default branches only.
    server_enabled, _ = resolve_mcp_access(grants, record.name, "", department_grants=dept_grants)
    tool_access: list[dict[str, Any]] = []
    for tool in tools:
        name = tool.get("name", "")
        enabled, source = resolve_mcp_access(grants, record.name, name, department_grants=dept_grants)
        tool_access.append({"name": name, "enabled": enabled, "source": source})
    result: dict[str, Any] = {
        "server_enabled": server_enabled,
        "tools": tool_access,
    }
    if error:
        result["error"] = error
    return result


@router.post("/{server_id}/agents/{agent_id}")
async def set_agent_access(
    server_id: str,
    agent_id: str,
    body: McpAgentAccessBody,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Enable/disable an MCP server (or one tool) for an agent (AD-1019).

    Records an auditable ``ToolAccessGrant`` over the reused ``ToolPermissionStore``:
    a grant (``enabled=True`` → ``WRITE``) or a restriction (``enabled=False`` →
    ``NONE`` + ``is_restriction``). ``tool`` scopes it to one tool, else server-wide.
    """
    _require_enabled(runtime)
    store = _require_store(runtime)
    record = await store.get(server_id)
    if record is None:
        raise HTTPException(status_code=404, detail="not_found")
    perms = _perm_store_or_503(runtime)
    tool_id = (
        mcp_tool_tool_id(record.name, body.tool)
        if body.tool
        else mcp_server_tool_id(record.name)
    )
    grant = await perms.issue_grant(
        agent_id,
        tool_id,
        permission=ToolPermission.WRITE if body.enabled else ToolPermission.NONE,
        is_restriction=not body.enabled,
        reason="mcp enablement",
    )
    return {
        "grant_id": grant.id,
        "agent_id": agent_id,
        "tool_id": grant.tool_id,
        "enabled": body.enabled,
        "is_restriction": grant.is_restriction,
    }


@router.delete("/{server_id}/agents/{agent_id}")
async def clear_agent_access(
    server_id: str,
    agent_id: str,
    tool: str | None = None,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Revoke the agent's grant(s) for a server/tool, reverting to default."""
    _require_enabled(runtime)
    store = _require_store(runtime)
    record = await store.get(server_id)
    if record is None:
        raise HTTPException(status_code=404, detail="not_found")
    perms = _perm_store_or_503(runtime)
    tool_id = (
        mcp_tool_tool_id(record.name, tool)
        if tool
        else mcp_server_tool_id(record.name)
    )
    revoked = 0
    for grant in perms.get_active_grants_sync(agent_id, tool_id):
        if await perms.revoke_grant(grant.id):
            revoked += 1
    return {"revoked": revoked}


# --------------------------------------------------------------------------- #
# AD-1019e: per-tool risk-tier authoring (the "keys" governance model). Writes
# the SAME ``(server_id, tool_name)`` key the AD-1019c dispatch reads (DD-1:
# server_id is the record id, NOT the name). Gated + honest-degrade like the
# per-agent grant endpoints above.
# --------------------------------------------------------------------------- #


@router.put("/{server_id}/tools/{tool}/risk")
async def set_tool_risk(
    server_id: str,
    tool: str,
    body: RiskBody,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Set the per-tool risk override for a tool on a server (AD-1019e).

    Keyed on the server RECORD id (``server_id`` path param) so the override the
    AD-1019c dispatch resolves at invoke time is the one written here (DD-1).
    """
    _require_enabled(runtime)
    store = _require_store(runtime)
    record = await store.get(server_id)
    if record is None:
        raise HTTPException(status_code=404, detail="not_found")
    if body.risk not in _RISK_VALUES:
        raise HTTPException(status_code=400, detail="invalid_risk")
    risk_store = _risk_store_or_503(runtime)
    await risk_store.set_risk(server_id, tool, McpToolRisk(body.risk))
    return {"server_id": server_id, "tool": tool, "risk": body.risk}


@router.delete("/{server_id}/tools/{tool}/risk")
async def clear_tool_risk(
    server_id: str,
    tool: str,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Clear the per-tool risk override, reverting to the server default (AD-1019e)."""
    _require_enabled(runtime)
    risk_store = _risk_store_or_503(runtime)
    cleared = await risk_store.clear_risk(server_id, tool)
    return {"cleared": cleared}
