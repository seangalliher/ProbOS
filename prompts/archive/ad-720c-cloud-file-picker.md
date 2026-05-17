# AD-720c — Cloud File Picker (OAuth-bound Source)

**Status:** Medium-large. **Closes:** #551. **Tests:** +14 pytest, +6 vitest. **Wave:** 168. **UI gate required.**

## Problem

Issue #551 (AD-720c) — Captain wants to attach files to chat from Google Drive / OneDrive / Dropbox via OAuth. Today the only attachment paths are:

- `POST /api/chat/attachments` (base64 JSON body, AD-720).
- `POST /api/chat/attachments/multipart` (UploadFile multipart, AD-720a, `chat.py:763`).
- Image paste (AD-720d).

Both terminate in `_validate_and_store_attachment` → `AttachmentStore.write(sha, blob, mime)` per AD-731.

This AD adds a third source: **cloud-hosted files**. The Captain authorizes ProbOS to read from their cloud provider once (OAuth handshake), the token is stored encrypted in the AD-706f credential vault, and subsequent file picks fetch metadata + bytes through the provider's API.

**OSS scope (per issue body):** protocol + extension-point only. Commercial-overlay concerns (managed accounts, billing) live in the private repo. We ship the OAuth plumbing + one provider stub; additional providers are forward markers.

## Solution

Five layers:

1. **OAuth provider interface** (`Protocol`) — `start_authorization()`, `handle_callback()`, `list_files()`, `download_file()`.
2. **Three OAuth provider stubs** — Google Drive, OneDrive, Dropbox. v1 ships ONE working provider (Captain ruling — recommend Google Drive as most operator-common); the other two are scaffolded interfaces with `NotImplementedError` + forward markers.
3. **Token storage** in AD-706f credential vault (Fernet-encrypted; scope-bound to "cloud_provider:{provider_id}").
4. **API endpoints**: `POST /api/cloud-pickers/{provider}/start`, `GET /api/cloud-pickers/{provider}/callback`, `GET /api/cloud-pickers/{provider}/files`, `POST /api/cloud-pickers/{provider}/attach`.
5. **HXI cloud-picker UI** — modal launched from chat compose; lists files; on select, downloads bytes server-side and returns the `attachment_id` SHA via the AD-731 path (NO bytes through the browser).

**Critical invariants:**
- All file bytes flow through `AttachmentStore.write(sha, blob, mime)` per AD-731 — browser never sees the raw bytes, only the SHA ref.
- OAuth tokens stored ONLY in `CredentialVault` (AD-706f). Never logged. Never in plaintext on disk.
- Vault precondition: `credential_vault.enabled=True` AND `auth.crew_scope_token` set. Honest-degrade 503 with structured detail when prerequisites missing.
- No new pip deps: `httpx` (already resident) handles HTTP; `cryptography` (Wave 166) handles encryption; `secrets` (stdlib) handles state-token generation.
- Operator-provided OAuth client credentials via config (BYOC — bring your own client). Default: feature disabled. Operator registers their own OAuth app with Google/Microsoft/Dropbox and enters client_id + client_secret in config.

## Implementation

### Section 1: Config

Add to `src/probos/config.py`:

```python
class CloudPickerProviderConfig(BaseModel):
    """AD-720c: per-provider OAuth client credentials. Operator-supplied."""
    enabled: bool = Field(default=False, description="AD-720c: enable this provider.")
    client_id: str = Field(default="", description="Operator-supplied OAuth client ID.")
    client_secret: str = Field(default="", description="Operator-supplied OAuth client secret.")
    redirect_uri: str = Field(
        default="http://127.0.0.1:8081/api/cloud-pickers/{provider}/callback",
        description="OAuth redirect URI; must match the registration at the provider.",
    )


class CloudPickersConfig(BaseModel):
    """AD-720c: cloud file picker config (OAuth-bound). Default OFF."""
    enabled: bool = Field(default=False, description="AD-720c master switch.")
    max_file_size_bytes: int = Field(default=50_000_000, ge=1)
    google_drive: CloudPickerProviderConfig = Field(default_factory=CloudPickerProviderConfig)
    onedrive: CloudPickerProviderConfig = Field(default_factory=CloudPickerProviderConfig)
    dropbox: CloudPickerProviderConfig = Field(default_factory=CloudPickerProviderConfig)


# Add to ProbOSConfig:
cloud_pickers: CloudPickersConfig = Field(default_factory=CloudPickersConfig)
```

### Section 2: Provider Protocol + base helpers

New file `src/probos/cloud_pickers/provider.py`:

```python
from typing import Protocol


class CloudPickerProvider(Protocol):
    """AD-720c: OAuth-bound file source for chat attachments."""

    provider_id: str  # 'google_drive' / 'onedrive' / 'dropbox'

    def start_authorization(self, *, state: str) -> str:
        """Return the provider's OAuth consent URL. Caller stores `state`
        in a session-scoped CSRF guard."""
        ...

    async def handle_callback(self, *, code: str, state: str) -> str:
        """Exchange `code` for an access token; return the token string."""
        ...

    async def list_files(
        self, *, access_token: str, query: str | None = None, page_token: str | None = None
    ) -> dict:
        """Return {'files': [{'id', 'name', 'mime', 'size_bytes', 'modified_at'}],
        'next_page_token': str | None}."""
        ...

    async def download_file(
        self, *, access_token: str, file_id: str
    ) -> tuple[bytes, str, str]:
        """Return (blob, declared_mime, declared_filename). Size MUST be
        validated against cfg.cloud_pickers.max_file_size_bytes by the caller."""
        ...
```

### Section 3: Google Drive provider (v1)

`src/probos/cloud_pickers/google_drive.py`:

- `start_authorization`: builds `https://accounts.google.com/o/oauth2/v2/auth?...` URL with scope `https://www.googleapis.com/auth/drive.file` (least-privilege: app-created files only).
- `handle_callback`: POST `https://oauth2.googleapis.com/token` with `code`, `client_id`, `client_secret`, `redirect_uri`, `grant_type=authorization_code`.
- `list_files`: GET `https://www.googleapis.com/drive/v3/files?q=...&pageSize=50`.
- `download_file`: GET `https://www.googleapis.com/drive/v3/files/{id}?alt=media`.

All HTTP via `httpx.AsyncClient` (no new deps).

### Section 4: OneDrive + Dropbox stubs

`src/probos/cloud_pickers/onedrive.py` and `dropbox.py`:

```python
class OneDriveProvider:
    provider_id = "onedrive"
    def start_authorization(self, *, state: str) -> str:
        raise NotImplementedError(
            "AD-720c-1 forward marker: OneDrive provider stub. "
            "Trigger to implement: operator demand."
        )
    # ... same for other methods
```

File forward-marker issues post-merge:
- AD-720c-1 (OneDrive provider implementation).
- AD-720c-2 (Dropbox provider implementation).

### Section 5: API endpoints

New file `src/probos/routers/cloud_pickers.py`:

```python
@router.post("/cloud-pickers/{provider}/start")
async def start_oauth(provider: str, runtime: Any = Depends(get_runtime)) -> dict:
    """Returns {'auth_url': str, 'state': str}. Caller (HXI) opens auth_url
    in a popup; the callback redirects back to this server."""
    _cloud_pickers_feature_check(runtime)
    _provider_enabled_check(runtime, provider)
    state = secrets.token_urlsafe(32)
    # Store state in a 5-min TTL in-memory set keyed by state→provider for callback CSRF guard.
    _state_store.add(state, provider)
    auth_url = _get_provider(runtime, provider).start_authorization(state=state)
    return {"auth_url": auth_url, "state": state}


@router.get("/cloud-pickers/{provider}/callback")
async def oauth_callback(
    provider: str, code: str, state: str, runtime: Any = Depends(get_runtime)
) -> HTMLResponse:
    """Exchanges code for token; stores token in vault; returns a small
    HTML page that posts a message to the opener window and closes."""
    if not _state_store.consume(state, provider):
        raise HTTPException(status_code=403, detail="invalid_state_token")
    access_token = await _get_provider(runtime, provider).handle_callback(code=code, state=state)
    vault = runtime.credential_vault
    if vault is None:
        raise HTTPException(status_code=503, detail="credential_vault_unavailable")
    # AD-706f: CredentialScope() with empty frozenset defaults = captain-only
    # access per credentials.py:40-58. Cloud-provider tokens are captain-scoped
    # (the Captain authorized the OAuth grant; no agent should be able to
    # exfiltrate the token by impersonating a scope match).
    scope = CredentialScope()
    await vault.store(ref=f"cloud_provider:{provider}", value=access_token, scope=scope)
    return HTMLResponse("<html><body><script>window.opener.postMessage({type:'oauth_complete',provider:'" + provider + "'},'*');window.close();</script></body></html>")


@router.get("/cloud-pickers/{provider}/files")
async def list_files(
    provider: str, q: str | None = None, page_token: str | None = None,
    runtime: Any = Depends(get_runtime),
) -> dict:
    """List files for the authorized provider. 401 if token missing/expired."""
    ...


@router.post("/cloud-pickers/{provider}/attach")
async def attach_file(
    provider: str, file_id: str, runtime: Any = Depends(get_runtime),
) -> dict:
    """Download the file server-side; store via AttachmentStore; return
    {'attachment_id': sha, 'mime': str, 'size_bytes': int, 'filename': str}.
    AD-731: bytes NEVER returned to the browser."""
    _cloud_pickers_feature_check(runtime)
    _provider_enabled_check(runtime, provider)
    vault = runtime.credential_vault
    if vault is None:
        raise HTTPException(status_code=503, detail="credential_vault_unavailable")
    access_token = await vault.read(ref=f"cloud_provider:{provider}", requesting_agent_id="captain")
    if access_token is None:
        raise HTTPException(status_code=401, detail="oauth_not_authorized")
    blob, mime, filename = await _get_provider(runtime, provider).download_file(
        access_token=access_token, file_id=file_id
    )
    max_bytes = runtime.config.cloud_pickers.max_file_size_bytes
    if len(blob) > max_bytes:
        raise HTTPException(status_code=413, detail={"reason": "file_too_large", "limit": max_bytes})
    ok, result = await _validate_and_store_attachment(
        runtime, blob, mime, declared_filename=filename, declared_hash_or_None=None,
    )
    if not ok:
        return JSONResponse(status_code=result["status_code"], content=result["body"])
    return result
```

Register the router in the app startup file (verify path in pre-flight).

### Section 5b: OAuth refresh-token handling

**Store the full token bundle, not just the access token.** Replace the `access_token: str` value stored under `cloud_provider:{provider}` with a structured Pydantic model:

```python
class OAuthTokenBundle(BaseModel):
    """AD-720c: OAuth token bundle persisted in the credential vault.
    Stored as JSON-serialized model under ref `cloud_provider:{provider}`."""
    access_token: str
    refresh_token: str | None = None  # None when provider didn't issue one
    expires_at: float = Field(
        default=0.0,
        description="Unix timestamp (seconds). 0.0 = no expiry known; treat access_token as opaque.",
    )
```

`handle_callback()` updated signature: returns `OAuthTokenBundle` (not bare `str`). Vault `store()` writes `bundle.model_dump_json()`.

**Refresh exchange on 401.** When `list_files` / `download_file` receives an HTTP 401 from the provider:

1. Read the bundle from the vault.
2. If `refresh_token is None` → surface `reauthorization_required` (the current happy path stays for providers that don't issue refresh tokens).
3. Otherwise, POST the provider's token endpoint with `grant_type=refresh_token`, `refresh_token=bundle.refresh_token`, `client_id`, `client_secret`. On success → write the new bundle to the vault (preserving the original refresh_token if the response doesn't include a new one — Google rotates rarely, Dropbox doesn't rotate) and RETRY the original request once. On refresh failure (4xx) → delete the vault entry, surface `reauthorization_required`.
4. On retry success → return as normal. On retry 401 again → surface `reauthorization_required` (avoid loops).

**Google Drive consent requirement.** To receive a `refresh_token` from Google on the FIRST authorization, the consent URL MUST include `access_type=offline&prompt=consent`. Without `prompt=consent`, Google omits the refresh_token on subsequent authorizations for the same user/scope (a common production trap). Document in the Google provider's `start_authorization()`:

```python
# AD-720c: access_type=offline → request refresh_token issuance.
# prompt=consent → force consent screen even on re-authorization so
# refresh_token is re-issued (Google's documented behavior — without
# this, only the FIRST ever authorization for a (user, client_id, scope)
# tuple receives a refresh_token).
params = {
    "client_id": cfg.client_id,
    "redirect_uri": cfg.redirect_uri.format(provider="google_drive"),
    "response_type": "code",
    "scope": "https://www.googleapis.com/auth/drive.file",
    "access_type": "offline",
    "prompt": "consent",
    "state": state,
}
```

OneDrive and Dropbox use different parameter names (`offline_access` scope for OneDrive; default behavior for Dropbox). Stubs document the requirement per-provider when implemented under AD-720c-1 / AD-720c-2.

**PKCE skipped (intentional).** ProbOS is a confidential client (server-stored `client_secret` per `CloudPickerProviderConfig`). Per OAuth 2.1 §1.5, PKCE is REQUIRED for public clients and OPTIONAL for confidential clients that hold a client_secret. We rely on the client_secret + the in-memory state-token CSRF guard. If a future provider issues only a public-client app type (no client_secret), PKCE would become required and surfaces as a forward marker.

### Section 6: State store (CSRF guard)

`src/probos/cloud_pickers/state_store.py`: in-memory TTL set, 5-minute expiry. Stdlib only. Threadsafe. Cleared on runtime shutdown.

### Section 7: HXI cloud picker UI

`ui/src/components/CloudPicker.tsx`: modal with:
- Provider selector (only those enabled per `/api/system/status`).
- "Authorize" button → POST `/cloud-pickers/{provider}/start` → open `auth_url` in popup → listen for `oauth_complete` postMessage.
- Once authorized: file list with search/pagination.
- File click → POST `/cloud-pickers/{provider}/attach` → returns `attachment_id` → editor inserts it into the existing chat compose `attachment_ids: string[]` (per AD-720b chat shape).

Mount from chat compose alongside the existing paste/upload triggers.

### Section 8: Honest-degrade matrix

| Condition | Behavior |
|---|---|
| `cloud_pickers.enabled=False` | All endpoints 503 with `feature_disabled`. |
| `credential_vault.enabled=False` | Endpoints 503 with `credential_vault_unavailable`. |
| Provider config incomplete (no client_id) | Endpoints 503 with `provider_not_configured`. |
| Token expired (provider returns 401) | If `refresh_token` present in bundle → attempt refresh exchange + retry once (Section 5b). If refresh fails or no refresh_token → vault entry deleted; endpoint returns 401 with `reauthorization_required`. |
| File > max_file_size_bytes | 413 with `file_too_large`. |
| AttachmentStore disabled | 503 (existing AD-720 honest-degrade). |

## Tests

`tests/test_ad720c_provider_protocol.py` (+3): protocol shape, error contracts.

`tests/test_ad720c_google_drive.py` (+5): mock httpx responses for token exchange / list / download; assert URL params, auth header shape, scope.

`tests/test_ad720c_state_store.py` (+2): TTL expiry, single-consume guarantee.

`tests/test_ad720c_endpoints.py` (+4): each endpoint honest-degrade matrix; vault interaction; AD-731 invariant (browser response NEVER contains raw bytes); CSRF state validation.

`ui/src/components/__tests__/CloudPicker.test.tsx` (+6 vitest): provider selector renders only enabled providers; authorize triggers popup + postMessage flow; file list pagination; file click attaches via API + closes modal with attachment_id; honest-degrade banner on 503; error toast on 401.

**Use real Pydantic config and real registry fixtures (BF-287). No MagicMock at substrate boundaries.**

## What this does NOT change

- `_validate_and_store_attachment` (AD-720a) — reused as-is. AD-731 invariant preserved.
- `CredentialVault` Protocol surface — reused as-is.
- `httpx` / `cryptography` versions — no bumps, no new deps.
- Browser chat compose `attachment_ids: string[]` shape — extended, not redesigned.
- Existing paste / upload paths — untouched.

## Tracking

- `DECISIONS.md` — append AD-720c shipped entry.
- `PROGRESS.md` — bump highest-AD line if needed.
- `docs/development/roadmap.md` — mark AD-720c shipped; add AD-720c-1 (OneDrive), AD-720c-2 (Dropbox) forward markers.
- File 2 forward-marker issues post-merge.
- `gh issue close 551 --comment "Shipped Wave 168 (AD-720c). Google Drive provider v1; OneDrive + Dropbox forward markers (AD-720c-1, AD-720c-2) filed. OAuth tokens via AD-706f vault; bytes via AD-731 AttachmentStore. See DECISIONS.md."`

## Acceptance Criteria

1. New module: `src/probos/cloud_pickers/` (provider.py, google_drive.py, onedrive.py, dropbox.py, state_store.py).
2. New router: `src/probos/routers/cloud_pickers.py` with 4 endpoints.
3. Config: `CloudPickersConfig` + nested per-provider config; default-OFF.
4. New UI component: `ui/src/components/CloudPicker.tsx`.
5. Tokens stored in `CredentialVault` (AD-706f), Fernet-encrypted, scope-bound.
6. AD-731 invariant: file bytes flow through `AttachmentStore.write(sha, blob, mime)`; HTTP responses to the browser carry refs, not bytes.
7. CSRF: 32-byte state token, single-consume, 5-min TTL.
8. OneDrive + Dropbox endpoints honest-degrade with `NotImplementedError` → 503 `provider_not_implemented`.
9. 14 pytest + 6 vitest pass.
10. `cd ui; npm run build` succeeds (AD-738b gate).
11. `cd ui; npx vitest run` green.
12. `pytest tests/ -q -n 4 --dist=loadfile` green.
13. Zero new pip / npm deps. `httpx` + `cryptography` reused.
14. No production code path uses `asyncio.create_subprocess_*` (BF-280 standing rule — `httpx` is fine, not subprocess).
15. Forward-marker GitHub issues filed for AD-720c-1 and AD-720c-2.
16. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Verified Against Codebase (2026-05-17)

```
grep "AttachmentStore" src/probos/attachments/store.py
  line 14: class AttachmentStore(Protocol):

grep "_validate_and_store_attachment" src/probos/routers/chat.py
  line 719: @router.post("/chat/attachments")
  line 763: @router.post("/chat/attachments/multipart")  # AD-720a (Wave 139)

grep "EncryptedFileCredentialVault" src/probos/tools/browser/credentials.py
  line 130: class EncryptedFileCredentialVault:

grep "async def store" src/probos/tools/browser/credentials.py
  line 86: async def store(self, *, ref: str, value: str, scope: CredentialScope) -> None: ...
  line 193: async def store(self, *, ref: str, value: str, scope: CredentialScope) -> None:

grep "AD-706f credential vault" src/probos/startup/finalize.py
  line 175-208: opt-in via cfg.credential_vault.enabled AND auth.crew_scope_token

grep "AD-731" src/probos/api_models.py
  line 312: rendered bytes through ``AttachmentStore`` (SHA-256 ref per AD-731)

ls src/probos/attachments/
  filesystem_store.py  (FilesystemAttachmentStore — concrete impl)
  store.py             (Protocol)
```
