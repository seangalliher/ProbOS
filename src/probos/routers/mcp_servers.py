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

import logging
from dataclasses import replace
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from probos.integrations.mcp_bridge.client import MCPClient
from probos.integrations.mcp_bridge.session import MCPSession
from probos.integrations.mcp_bridge.store import (
    McpServerRecord,
    McpServerValidationError,
    validate_record,
)
from probos.integrations.mcp_bridge.transport import StdioTransport
from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mcp/servers", tags=["mcp-servers"])

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


async def _register(bridge: Any, record: McpServerRecord) -> None:
    """Live-register via the §4 key rule — http sync, stdio await."""
    if bridge is None:
        return
    if record.type == "http":
        bridge.register_server(record.url, headers=dict(record.headers))
    else:
        await bridge.register_stdio_server(
            name=record.name,
            command=record.command,
            args=list(record.args),
            env=dict(record.env),
            cwd=record.cwd,
            timeout=record.timeout_seconds,
        )


async def _unregister(bridge: Any, key: str) -> None:
    """Best-effort bridge teardown (ignores an unknown key)."""
    if bridge is None:
        return
    await bridge.unregister_server(key)


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
        await _register(getattr(runtime, "mcp_bridge", None), created)
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
        await _register(bridge, updated)
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
    await _register(getattr(runtime, "mcp_bridge", None), record)
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
