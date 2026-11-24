"""BF-745: one way to put an ``McpServerRecord`` on the bridge.

Registering a record was implemented twice. The HXI enable/create path resolved
the record's credentials out of the vault before registering; the boot seed loop
did not, and passed ``dict(rec.headers)`` verbatim. So an authenticated server
worked when you enabled it and stopped working after a restart.

Nothing caught it because ``register_server`` stores the headers it is given and
resolves nothing itself -- registration SUCCEEDS, carrying no credentials. The
failure surfaces later as a remote auth error, or as a tool that quietly returns
nothing, far from the cause. The secret is deliberately absent from the record
(AD-1017 keeps it in the vault behind ``credential_ref``), which is exactly why
reading the record could not reveal the omission.

The auth helpers moved here from ``routers/mcp_servers.py`` because the boot
path needs them and must not import a router. AD-1236 adds a third caller (the
capability-ladder install fulfiller); adding it while two paths disagreed would
have repeated BF-744, where two routes to one outcome drifted apart.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any, Literal, overload

if TYPE_CHECKING:
    from probos.integrations.mcp_bridge.store import McpServerRecord

logger = logging.getLogger(__name__)

_CAPTAIN_ID = "captain"


def _bundle_or_none(value: str) -> Any | None:
    """Parse a vault-stored OAuth bundle JSON; warn + None on corruption."""
    from probos.cloud_pickers.tokens import OAuthTokenBundle

    try:
        return OAuthTokenBundle.model_validate_json(value)
    except (ValueError, TypeError):
        logger.warning(
            "AD-1017: MCP OAuth bundle in vault is not valid OAuthTokenBundle "
            "JSON; treating as missing (no secret logged)"
        )
        return None


async def resolve_secret_value(
    record: "McpServerRecord", runtime: Any
) -> str | None:
    """Resolve the raw secret for a record from the credential vault.

    ``static`` -> the stored token; ``oauth`` -> the bundle's ``access_token``.
    Returns ``None`` (honest-degrade, warning, **no secret logged**) when there
    is no vault, no ``credential_ref``, a vault miss, or a corrupt bundle -- the
    legacy registrar then registers unauthenticated; strict installation refuses.
    """
    vault = getattr(runtime, "credential_vault", None)
    if vault is None or not record.credential_ref:
        return None
    try:
        raw = await vault.read(
            ref=record.credential_ref, requesting_agent_id=_CAPTAIN_ID
        )
    except Exception:
        # This code was safe in the router, where a raise became an HTTP 500.
        # It is NOT safe here: the boot seed loop has no guard above it, so a
        # vault that raises (the encrypted-file backend can surface filesystem
        # errors while updating read metadata) would stop the ship from
        # starting because ONE authenticated server exists. Degrade exactly as
        # a vault miss does. Never log the exception payload -- it can carry
        # the secret.
        logger.warning(
            "AD-1017: credential vault read FAILED for MCP server %s "
            "(auth_kind=%s); credentials unavailable to the registrar "
            "(no secret logged)",
            record.name,
            record.auth_kind,
        )
        return None
    if raw is None:
        logger.warning(
            "AD-1017: credential vault miss for MCP server %s (auth_kind=%s, ref "
            "present, value absent); credentials unavailable to the registrar "
            "(no secret logged)",
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


def _registered_secret(
    runtime: Any, bridge: Any, record: McpServerRecord, key: str, value: str | None
) -> tuple[Any, Any]:
    """AD-1337 S4: register the credential this registration hands the server, as ``mcp:<name>``, and note the
    client already under ``key``. ``(None, None)`` when nothing is registered (no value, or no real registry)."""
    from probos.security.secret_masking import register_run_secret

    handle = register_run_secret(runtime, "mcp", record.name, value)
    if handle is None:
        return None, None
    try:
        return handle, bridge.get_client(key)
    except BaseException:
        handle.release()
        raise


def _settle_secret(runtime: Any, bridge: Any, key: str, before: Any, handle: Any, published: bool) -> None:
    """AD-1337 S4: the client this registration published keeps ``handle`` until it is closed; otherwise it is released.

    Only a real ``MCPClient`` that is new under ``key`` can own it, and only when the bridge answered ``True`` to this
    registration's own call: a client that another registration published under ``key`` while this one waited (a stdio
    spawn awaits, so it can be overtaken) is not this one's, whether this one then answered False, raised or was
    cancelled. A duplicate or reused key keeps its old client (which holds its own registration, if it holds one), and
    a failed or cancelled registration published nothing. The owner masks its own replies with the runtime's masker,
    read at each reply because the boot loop registers before finalize builds it (D9).
    """
    if handle is None:
        return
    from probos.integrations.mcp_bridge.client import MCPClient
    from probos.security.secret_masking import secret_masker_of

    client = bridge.get_client(key)
    if published and isinstance(client, MCPClient) and client is not before:
        client.hold_secret(handle, lambda: secret_masker_of(runtime))
    else:
        handle.release()


async def resolve_auth_headers(
    record: "McpServerRecord", runtime: Any
) -> dict[str, str]:
    """Build the http auth header(s) for a record. ``{}`` for none/miss.

    ``auth_kind=="none"`` -> ``{}`` (register byte-identical to AD-1015).
    ``static`` -> ``{header_name: f"{scheme} {value}".strip()}`` (bare ``value``
    when ``scheme`` is empty). ``oauth`` -> ``{"Authorization": "Bearer <access>"}``.
    """
    if record.auth_kind == "none":
        return {}
    value = await resolve_secret_value(record, runtime)
    return _auth_headers(record, value)


def _auth_headers(record: McpServerRecord, value: str | None) -> dict[str, str]:
    if value is None:
        return {}
    if record.auth_kind == "oauth":
        return {"Authorization": f"Bearer {value}"}
    name = record.auth_header_name or "Authorization"
    scheme = record.auth_scheme
    return {name: f"{scheme} {value}".strip() if scheme else value}


async def resolve_auth_env(
    record: "McpServerRecord", runtime: Any
) -> dict[str, str]:
    """Build the stdio auth env var for a record. ``{}`` unless ``auth_env_var`` set.

    The operator names the env var their server expects (e.g. ``API_KEY``); when
    unset, stdio registers unauthenticated (http is the primary auth path).
    """
    if record.auth_kind == "none" or not record.auth_env_var:
        return {}
    value = await resolve_secret_value(record, runtime)
    return _auth_env(record, value)


def _auth_env(record: McpServerRecord, value: str | None) -> dict[str, str]:
    if value is None:
        return {}
    return {record.auth_env_var: value}


@overload
async def register_record(
    runtime: Any, record: McpServerRecord, *, require_ready: Literal[True]
) -> bool: ...


@overload
async def register_record(
    runtime: Any, record: McpServerRecord, *, require_ready: Literal[False] = False
) -> None: ...


@overload
async def register_record(
    runtime: Any, record: McpServerRecord, *, require_ready: bool
) -> bool | None: ...


async def register_record(
    runtime: Any, record: McpServerRecord, *, require_ready: bool = False
) -> bool | None:
    """Put *record* on the bridge with its credentials resolved.

    Every path that registers a stored record goes through here, so an
    authenticated server behaves the same on boot as it does when enabled from
    the HXI. ``auth_kind=="none"`` resolves to ``{}``, making the merged
    ``headers``/``env`` byte-identical to the AD-1015 behaviour. Legacy callers
    return None and retain duplicate precedence and credential-miss degradation.
    Strict callers require configured credentials and exact configuration reuse
    or a newly registered client; stdio also requires positive process liveness.
    Mismatches and unknown liveness leave existing clients untouched.
    HTTP success proves local client configuration, not a remote handshake or
    acceptance of credentials. The bridge alone owns candidate cleanup.
    """
    bridge = getattr(runtime, "mcp_bridge", None)
    if bridge is None:
        if require_ready:
            logger.warning(
                "AD-1236: MCP bridge unavailable; strict registration failed, "
                "leaving the install request retryable"
            )
            return False
        return None
    if require_ready:
        try:
            if record.type not in ("http", "stdio") or record.auth_kind not in (
                "none", "static", "oauth"
            ):
                raise ValueError("unsupported MCP registration configuration")
            secret = None
            if record.auth_kind != "none":
                secret = await resolve_secret_value(record, runtime)
                if not isinstance(secret, str) or not secret.strip() or any(
                    character in secret for character in ("\r", "\n", "\x00")
                ):
                    raise ValueError("required MCP credential unavailable")
                if record.type == "stdio":
                    if not record.auth_env_var.strip() or any(
                        character in record.auth_env_var
                        for character in ("=", "\x00")
                    ):
                        raise ValueError("unusable MCP auth environment variable")
                elif record.auth_kind == "static" and (not re.fullmatch(
                    r"[!#$%&'*+.^_`|~0-9A-Za-z-]+",
                    record.auth_header_name or "Authorization",
                ) or any(
                    character in record.auth_scheme
                    for character in ("\r", "\n", "\x00")
                )):
                    raise ValueError("unusable MCP auth header")
            auth_headers = _auth_headers(record, secret)
            auth_env = _auth_env(record, secret)
            key = record.url if record.type == "http" else record.name
            handle, before = _registered_secret(runtime, bridge, record, key, secret)
            registered: bool | None = None
            try:
                if record.type == "http":
                    registered = bridge.register_server(
                        record.url, headers={**record.headers, **auth_headers},
                        reuse_if_matching=True,
                    )
                else:
                    registered = await bridge.register_stdio_server(
                        name=record.name,
                        command=record.command,
                        args=list(record.args),
                        env={**record.env, **auth_env},
                        cwd=record.cwd,
                        timeout=record.timeout_seconds,
                        reuse_if_matching=True,
                    )
            finally:
                _settle_secret(runtime, bridge, key, before, handle, registered is True)
            if registered is True:
                client = bridge.get_client(key)
                if client is not None and (record.type == "http" or client.is_alive is True):
                    return True
        except Exception:
            logger.warning(
                "AD-1236: strict MCP registration failed; configured credentials "
                "or client readiness unavailable, leaving the request retryable "
                "(no exception payload logged)"
            )
            return False
        logger.warning(
            "AD-1236: MCP bridge rejected registration or exposed no ready client; "
            "leaving the install request retryable"
        )
        return False
    # AD-1337 S4: the value is read here, not through resolve_auth_headers or resolve_auth_env, so it can be
    # registered; the same records read the vault exactly as before (none, or stdio without auth_env_var: no read).
    value = None
    if record.auth_kind != "none" and (record.type == "http" or record.auth_env_var):
        value = await resolve_secret_value(record, runtime)
    key = record.url if record.type == "http" else record.name
    handle, before = _registered_secret(runtime, bridge, record, key, value)
    published: bool | None = None
    try:
        if record.type == "http":
            published = bridge.register_server(
                record.url, headers={**record.headers, **_auth_headers(record, value)}
            )
            return
        published = await bridge.register_stdio_server(
            name=record.name,
            command=record.command,
            args=list(record.args),
            env={**record.env, **_auth_env(record, value)},
            cwd=record.cwd,
            timeout=record.timeout_seconds,
        )
    finally:
        _settle_secret(runtime, bridge, key, before, handle, published is True)
