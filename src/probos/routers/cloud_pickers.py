"""AD-720c: cloud file picker REST endpoints.

Four endpoints:

* ``POST /api/cloud-pickers/{provider}/start`` — mint CSRF state + return auth URL.
* ``GET  /api/cloud-pickers/{provider}/callback`` — consume state, exchange code,
  store :class:`OAuthTokenBundle` in the AD-706f credential vault.
* ``GET  /api/cloud-pickers/{provider}/files`` — list provider files (paged).
* ``POST /api/cloud-pickers/{provider}/attach`` — server-side download → AD-731
  ``AttachmentStore`` SHA-256 ref. Browser receives only the ref.

Honest-degrade per the matrix in ``prompts/ad-720c-cloud-file-picker.md``
(Section 8). Vault precondition: ``cfg.credential_vault.enabled=True`` AND
``auth.crew_scope_token`` set — otherwise 503 ``credential_vault_unavailable``.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from probos.cloud_pickers.dropbox import DropboxProvider
from probos.cloud_pickers.google_drive import GoogleDriveProvider
from probos.cloud_pickers.onedrive import OneDriveProvider
from probos.cloud_pickers.provider import (
    ProviderError,
    ReauthorizationRequired,
)
from probos.cloud_pickers.tokens import CsrfStateStore, OAuthTokenBundle
from probos.routers.deps import get_runtime
from probos.tools.browser.credentials import CredentialScope

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/cloud-pickers", tags=["cloud-pickers"])


_PROVIDER_CLASSES = {
    "google_drive": GoogleDriveProvider,
    "onedrive": OneDriveProvider,
    "dropbox": DropboxProvider,
}


# Per-runtime CSRF state stores keyed by id(runtime). Tests reset via
# ``_clear_state_stores()`` exposed for test-only use.
_STATE_STORES: dict[int, CsrfStateStore] = {}


def _clear_state_stores() -> None:
    """Test-only: drop all per-runtime CSRF stores."""
    _STATE_STORES.clear()


def _get_state_store(runtime: Any) -> CsrfStateStore:
    key = id(runtime)
    store = _STATE_STORES.get(key)
    if store is None:
        ttl = int(runtime.config.cloud_pickers.state_ttl_seconds)
        store = CsrfStateStore(ttl_seconds=ttl)
        _STATE_STORES[key] = store
    return store


def _feature_check(runtime: Any) -> None:
    cfg = runtime.config.cloud_pickers
    if not cfg.enabled:
        raise HTTPException(status_code=503, detail="feature_disabled")


def _provider_config(runtime: Any, provider: str) -> Any:
    if provider not in _PROVIDER_CLASSES:
        raise HTTPException(status_code=404, detail="unknown_provider")
    cfg = runtime.config.cloud_pickers
    pcfg = getattr(cfg, provider, None)
    if pcfg is None:
        raise HTTPException(status_code=404, detail="unknown_provider")
    if not pcfg.enabled:
        raise HTTPException(status_code=503, detail="provider_disabled")
    if not pcfg.client_id or not pcfg.client_secret:
        raise HTTPException(status_code=503, detail="provider_not_configured")
    return pcfg


def _build_provider(runtime: Any, provider: str) -> Any:
    pcfg = _provider_config(runtime, provider)
    cls = _PROVIDER_CLASSES[provider]
    return cls(
        client_id=pcfg.client_id,
        client_secret=pcfg.client_secret,
        redirect_uri=pcfg.redirect_uri,
    )


def _vault_or_503(runtime: Any) -> Any:
    vault = getattr(runtime, "credential_vault", None)
    if vault is None:
        raise HTTPException(status_code=503, detail="credential_vault_unavailable")
    return vault


def _captain_id(runtime: Any) -> str:
    # AD-720c: scope token storage to the Captain identity. The runtime's
    # operator/identity is a single-Captain abstraction in OSS ProbOS; tokens
    # are captain-scoped and not exfiltratable by any agent (CredentialScope()
    # empty frozenset = captain-only access per credentials.py:40-58).
    return "captain"


def _vault_ref(provider: str, captain_id: str) -> str:
    return f"cloud_provider:{provider}:{captain_id}"


def _bundle_from_vault_value(value: str) -> OAuthTokenBundle | None:
    try:
        return OAuthTokenBundle.model_validate_json(value)
    except (ValueError, TypeError):
        # AD-720c: legacy/garbled value — surface as no-token so the caller
        # honest-degrades to ``oauth_not_authorized`` (operator can
        # reauthorize). Log at warning so corruption is visible.
        logger.warning(
            "AD-720c: vault value for cloud_provider ref is not a valid "
            "OAuthTokenBundle JSON; treating as missing (forcing reauth)"
        )
        return None


async def _read_bundle(runtime: Any, provider: str) -> OAuthTokenBundle:
    vault = _vault_or_503(runtime)
    ref = _vault_ref(provider, _captain_id(runtime))
    raw = await vault.read(ref=ref, requesting_agent_id=_captain_id(runtime))
    if raw is None:
        raise HTTPException(status_code=401, detail="oauth_not_authorized")
    bundle = _bundle_from_vault_value(raw)
    if bundle is None:
        raise HTTPException(status_code=401, detail="oauth_not_authorized")
    return bundle


async def _write_bundle(runtime: Any, provider: str, bundle: OAuthTokenBundle) -> None:
    vault = _vault_or_503(runtime)
    ref = _vault_ref(provider, _captain_id(runtime))
    # AD-706f: CredentialScope() empty frozenset = captain-only access per
    # credentials.py:40-58. Cloud-provider tokens are Captain-scoped — no
    # agent should be able to read them by impersonating a scope match.
    await vault.store(
        ref=ref,
        value=bundle.model_dump_json(),
        scope=CredentialScope(),
    )


async def _delete_bundle(runtime: Any, provider: str) -> None:
    vault = getattr(runtime, "credential_vault", None)
    if vault is None:
        return
    ref = _vault_ref(provider, _captain_id(runtime))
    await vault.delete(ref=ref)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/{provider}/start")
async def start_oauth(
    provider: str,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Mint CSRF state, build provider auth URL, return both to the caller.

    The caller (HXI) opens ``auth_url`` in a popup; the provider's callback
    redirects back to ``GET /api/cloud-pickers/{provider}/callback``.
    """
    _feature_check(runtime)
    _vault_or_503(runtime)  # fail fast if vault unavailable
    prov = _build_provider(runtime, provider)
    state = _get_state_store(runtime).mint(provider)
    auth_url = prov.start_authorization(state=state)
    return {"auth_url": auth_url, "state": state}


@router.get("/{provider}/callback")
async def oauth_callback(
    provider: str,
    code: str,
    state: str,
    runtime: Any = Depends(get_runtime),
) -> HTMLResponse:
    """Consume state, exchange ``code`` for token bundle, persist via vault."""
    _feature_check(runtime)
    store = _get_state_store(runtime)
    if not store.consume(state, provider):
        raise HTTPException(status_code=403, detail="invalid_state_token")
    prov = _build_provider(runtime, provider)
    try:
        bundle = await prov.handle_callback(code=code)
    except ProviderError as e:
        raise HTTPException(status_code=e.status, detail=e.detail) from e
    await _write_bundle(runtime, provider, bundle)
    # Small HTML that posts a message to the opener window and closes. No
    # token data crosses the iframe boundary — only the provider id.
    safe_provider = provider.replace("'", "")
    html = (
        "<html><body><script>"
        "try{window.opener.postMessage("
        f"{{type:'oauth_complete',provider:'{safe_provider}'}}"
        ",'*');}catch(e){};"
        "window.close();"
        "</script></body></html>"
    )
    return HTMLResponse(html)


@router.get("/{provider}/files")
async def list_files(
    provider: str,
    q: str | None = None,
    page_token: str | None = None,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """List files for the authorized provider."""
    _feature_check(runtime)
    prov = _build_provider(runtime, provider)
    bundle = await _read_bundle(runtime, provider)
    try:
        files, next_token, refreshed = await prov.list_files(
            bundle=bundle, query=q, page_token=page_token
        )
    except ReauthorizationRequired as e:
        await _delete_bundle(runtime, provider)
        raise HTTPException(status_code=401, detail=e.detail) from e
    except ProviderError as e:
        raise HTTPException(status_code=e.status, detail=e.detail) from e
    if refreshed is not None:
        await _write_bundle(runtime, provider, refreshed)
    return {"files": list(files), "next_page_token": next_token}


@router.post("/{provider}/attach")
async def attach_file(
    provider: str,
    req: Request,
    runtime: Any = Depends(get_runtime),
) -> Any:
    """Download a file server-side; store via AttachmentStore; return SHA ref.

    AD-731 invariant: bytes flow through ``AttachmentStore.write(sha, blob,
    mime)``; the HTTP response carries only the SHA-256 ref + metadata.
    """
    _feature_check(runtime)
    try:
        payload = await req.json()
    except (ValueError, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail="invalid_body")
    file_id = payload.get("file_id")
    if not isinstance(file_id, str) or not file_id:
        raise HTTPException(status_code=400, detail="missing_file_id")

    prov = _build_provider(runtime, provider)
    bundle = await _read_bundle(runtime, provider)
    try:
        blob, mime, filename, refreshed = await prov.download_file(
            bundle=bundle, file_id=file_id
        )
    except ReauthorizationRequired as e:
        await _delete_bundle(runtime, provider)
        raise HTTPException(status_code=401, detail=e.detail) from e
    except ProviderError as e:
        raise HTTPException(status_code=e.status, detail=e.detail) from e
    if refreshed is not None:
        await _write_bundle(runtime, provider, refreshed)

    max_bytes = int(runtime.config.cloud_pickers.max_file_size_bytes)
    if len(blob) > max_bytes:
        return JSONResponse(
            status_code=413,
            content={"error": "file_too_large", "limit": max_bytes, "size": len(blob)},
        )

    # AD-731: route bytes through the shared AD-720a validator → AttachmentStore.
    # Import lazily to avoid a circular import at module load time (chat.py
    # imports from probos.routers, which would otherwise pull cloud_pickers
    # back through the package).
    from probos.routers.chat import _validate_and_store_attachment

    ok, result = await _validate_and_store_attachment(
        runtime,
        blob,
        mime,
        declared_filename=filename,
        declared_hash_or_None=None,
    )
    if not ok:
        return JSONResponse(
            status_code=result["status_code"],
            content=result["body"],
            headers=result.get("headers"),
        )
    return result
