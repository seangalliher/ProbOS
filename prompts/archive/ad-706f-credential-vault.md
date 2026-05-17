# AD-706f — Browser Tool credential vault integration

**Status:** Draft v1.
**Closes:** #521.
**Dependencies:** AD-722b-1 (Wave 161, shipped — `AuthConfig.crew_scope_token` + `hmac.compare_digest` substrate). AD-706 BrowserTool. AD-706e `upload_file.credential_ref` hook.
**Estimated tests:** +12 pytest. **1 new pip dep (`cryptography>=42` — Apache 2.0/BSD dual-licensed).**

---

## Problem

Anthropic safety guideline #2 ("Avoid giving the model access to sensitive data") is honored in AD-706 v1 by **not** storing credentials at all. The agent cannot perform authenticated browser flows (login forms, OAuth consent screens, API-key entry, SFTP password prompts) without crossing this line.

AD-706f is the deliberate decision to add scoped credential storage with full audit trail, so agents can authenticate while preserving:

- Encrypted-at-rest storage with a KEK derived from the AD-722b-1 crew-scope substrate.
- Per-credential **capability scope** (which agent can read which credential).
- Auto-fill via Playwright `page.fill()` — **never** clipboard exposure.
- AuditLog row per read (the credential value never crosses an LLM prompt).

## Solution

New module `src/probos/tools/browser/credentials.py` exports a `CredentialVault` Protocol + a v1 `EncryptedFileCredentialVault` implementation backed by JSON sidecar + Fernet symmetric encryption.

### Section 0 — Event Types

Add to `event_log.py` EventType enum after `BROWSER_EVAL_JS_EXECUTED`:

- `CREDENTIAL_STORED` — vault write.
- `CREDENTIAL_READ` — vault read by an agent (audit row).
- `CREDENTIAL_READ_DENIED` — capability scope mismatch.
- `CREDENTIAL_DELETED` — vault delete.
- `CREDENTIAL_FILL_REQUESTED` — Playwright `page.fill` invocation requested by Browser Tool.

### Section 1 — Protocol and v1 implementation

`src/probos/tools/browser/credentials.py`:

```python
class CredentialVault(Protocol):
    async def store(self, *, ref: str, value: str, scope: CredentialScope) -> None: ...
    async def read(self, *, ref: str, requesting_agent_id: str) -> str | None: ...
    async def materialize_to_temp(self, *, ref: str, requesting_agent_id: str) -> Path | None: ...
    async def delete(self, *, ref: str) -> None: ...
    async def list_refs(self) -> list[CredentialMetadata]: ...
```

`CredentialScope` is a frozen dataclass:
- `allowed_agent_ids: frozenset[str]` — agent ids permitted to read. Empty set = Captain-only.
- `allowed_domains: frozenset[str]` — Browser session must have last_url matching one of these patterns for fill operations (`fnmatch.fnmatchcase` against lowered host).
- `expires_at: float | None` — Unix timestamp; None = no expiry.

`CredentialMetadata` (returned by `list_refs`): `ref`, `scope`, `created_at`, `last_read_at`, `read_count`. NO value field.

`EncryptedFileCredentialVault`:
- Constructor takes `path: Path`, `kek: bytes` (32-byte key).
- KEK derived from `AuthConfig.crew_scope_token` via `hashlib.scrypt(token.encode(), salt=b"probos-credential-vault-v1", n=2**14, r=8, p=1, dklen=32)`. Helper `_derive_kek(token: str) -> bytes` at module level.
- Value stored as Fernet ciphertext (`cryptography.fernet.Fernet` — Apache 2.0/BSD).
- On-disk format: `{"refs": {ref: {"ciphertext": "...", "scope": {...}, "created_at": ..., "last_read_at": ..., "read_count": ...}}}`.
- Atomic write via tmp+rename (AD-720d-2.1 / AD-721d-4 pattern).
- RLock for concurrent access.

`materialize_to_temp` decrypts, writes to `tempfile.NamedTemporaryFile(delete=False)`, returns path. **Caller is responsible for `unlink` in `finally`** — the contract is documented; the vault does not own the temp file lifecycle.

### Section 2 — Config

`src/probos/config.py` — new `CredentialVaultConfig` model nested under `BrowserToolConfig`:

```python
class CredentialVaultConfig(BaseModel):
    enabled: bool = False  # default-OFF transitional gate
    backend: Literal["file"] = "file"  # v1 only
    file_path: str = "data/credential_vault.json"
    max_credentials: int = 100  # ge=1, le=10000
    require_https_for_fill: bool = True
```

Wire into `BrowserToolConfig`:
```
credential_vault: CredentialVaultConfig = Field(default_factory=CredentialVaultConfig)
```

Hard precondition for `enabled=True`: `auth.crew_scope_token` must be non-empty (KEK derivation needs a secret). Pydantic root validator on `CredentialVaultConfig` cannot see sibling sections; enforce via a **runtime check at vault construction time** that raises `RuntimeError` with a clear message if `kek` is `_derive_kek("")`. The runtime startup wires the vault only when both `enabled=True` AND `auth.crew_scope_token` is non-empty; otherwise sets `runtime.credential_vault = None`.

### Section 3 — Runtime wiring

`src/probos/startup/finalize.py` (or the equivalent startup step that constructs the BrowserTool — verify location via `grep -n "BrowserTool" src/probos/startup/*.py` before writing the SEARCH/REPLACE):

Two-phase wiring (mirrors AD-722d):
1. Attribute declared `None` next to BrowserTool construction.
2. After auth_cfg is resolved, if `cfg.tools.browser.credential_vault.enabled and cfg.auth.crew_scope_token`, construct the vault and set `runtime.credential_vault = vault`. Log at INFO: "AD-706f credential vault enabled (n credentials loaded)".

### Section 4 — Browser Tool fill action

New action verb `fill_credential` registered in `_HANDLERS`:

```
async def _action_fill_credential(session, params, *, runtime):
    selector = params["selector"]
    credential_ref = params["credential_ref"]
    agent_id = params.get("agent_id", "")  # set by tool dispatcher from session.agent_id
```

1. Honest-degrade if `runtime.credential_vault is None`.
2. Check `cfg.tools.browser.credential_vault.require_https_for_fill` against `session.last_url` (raise ValueError on http://).
3. Check the credential's `scope.allowed_domains` against the current page host.
4. Call `vault.read(ref=credential_ref, requesting_agent_id=agent_id)`. None return → emit `CREDENTIAL_READ_DENIED`, honest-degrade.
5. `await session.page.fill(selector, value)`.
6. Emit `CREDENTIAL_FILL_REQUESTED`.

`fill_credential` is **tier-3 always** (Captain ACK required for every credential read). Add to `classify_action` always-tier-3 set alongside `upload_file`, `eval_js`, `compute_use_click`.

### Section 5 — `upload_file.credential_ref` hook (AD-706e wire-up)

Update AD-706e's `upload_file` handler:

- If `params.get("credential_ref")`:
  - If `runtime.credential_vault is None` → honest-degrade.
  - Call `vault.materialize_to_temp(ref=ref, requesting_agent_id=agent_id)`.
  - `try`: `page.set_input_files(selector, temp_path)`. `finally`: `temp_path.unlink(missing_ok=True)`.

The vault never exposes raw bytes via this path — temp file is the contract.

### Section 6 — Admin API (Captain only)

New routes under `src/probos/routers/credentials.py`:

- `POST /api/credentials` — create. Body: `{ref, value, scope: {allowed_agent_ids, allowed_domains, expires_at}}`.
- `GET /api/credentials` — list refs (no values).
- `DELETE /api/credentials/{ref}` — remove.

All three behind `Depends(require_crew_scope)` (AD-722b-1). When `auth.crew_scope_token` is empty, the routes return 503 with body `{"error": "credential_vault_requires_auth"}` — the safety floor.

### Tests (`tests/test_ad706f_credential_vault.py`)

1. `test_vault_disabled_by_default` — `cfg.tools.browser.credential_vault.enabled == False`.
2. `test_vault_requires_crew_scope_token_for_construction` — empty token raises `RuntimeError`.
3. `test_vault_store_and_read_roundtrip` — Fernet roundtrip via real `EncryptedFileCredentialVault` (Captain-readable).
4. `test_vault_scope_denies_unauthorized_agent` — agent not in `allowed_agent_ids` gets None + `CREDENTIAL_READ_DENIED` event.
5. `test_vault_expires_at_enforced` — expired credential returns None.
6. `test_vault_persists_across_restart` — write, recreate vault, read.
7. `test_vault_materialize_to_temp_returns_path_caller_unlinks` — file exists; assert vault does not auto-delete.
8. `test_action_fill_credential_honest_degrades_when_vault_none`.
9. `test_action_fill_credential_blocks_http_when_require_https_true`.
10. `test_action_fill_credential_blocks_domain_mismatch`.
11. `test_action_fill_credential_always_tier_3` — `classify_action(session, "fill_credential", {})` == 3.
12. `test_credentials_router_returns_503_without_crew_scope_token`.
13. `test_upload_file_credential_ref_materializes_and_cleans_up` — assert temp path unlinked in finally.
14. `test_vault_kek_derivation_deterministic` — same token → same KEK; different token → different KEK.

All tests use real `SystemConfig()` + real `EncryptedFileCredentialVault` against `tmp_path` (BF-287). No MagicMock at substrate boundary. KEK derivation uses a test-only short token to keep scrypt fast.

## What This Does NOT Change

- AD-722b-1 auth substrate unchanged — vault REUSES `AuthConfig.crew_scope_token` (no new shared secret).
- The vault never crosses an LLM prompt — values are read by the Browser Tool handler and passed directly to Playwright.
- AD-706e `upload_file.credential_ref` is a forward-compatible hook; AD-706e's literal-path mode unchanged when vault is absent.
- `EncryptedFileCredentialVault` is the v1 backend. Protocol allows future OS-keychain absorption (AD-706f-1).

## Tracking

- `PROGRESS.md` — Wave 166 entry.
- `docs/development/roadmap.md` — close #521.
- `DECISIONS.md` — append AD-706f. Note the `cryptography` dep addition explicitly (Apache 2.0/BSD dual; verified at install time).

Forward markers (TECHNICAL triggers):
- AD-706f-1 — OS-keychain backend (Windows Credential Manager, macOS Keychain, Linux Secret Service). Trigger: operator-requested cross-machine credential sync OR commercial-overlay.
- AD-706f-2 — Per-credential audit log query API. Trigger: ≥3 audit-trail GET requests in production.
- AD-706f-3 — Credential rotation API. Trigger: any credential reaches `expires_at` in production.
- AD-706f-4 — Multi-Captain per-crew vault (pairs with AD-722b-1a). Trigger: AD-722b-1a lands.

## Acceptance Criteria

- 14 tests green under serial + parallel gates.
- Full pytest gate: previous +N → ≥+14.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
- `pip show cryptography` succeeds post-install (CI install step gate).
- No new npm deps.
- License posture: `cryptography` is dual-licensed Apache 2.0 / BSD — verified clean for OSS absorption per `.github/copilot-instructions.md`.

## Verified Against Codebase (2026-05-16)

```
grep -n "AuthConfig" src/probos/config.py
  2561: class AuthConfig(BaseModel):

grep -n "crew_scope_token" src/probos/routers/auth.py
  4: - Single shared secret (Pydantic ``AuthConfig.crew_scope_token``).
  30:     """Pull ``auth.crew_scope_token`` from runtime config; empty when unset."""
  37:     return auth_cfg.crew_scope_token

grep -n "hmac.compare_digest" src/probos/routers/auth.py
  8: - Constant-time compare via ``hmac.compare_digest``.
  59:     if not hmac.compare_digest(presented, expected):
  74:     if not presented or not hmac.compare_digest(presented, expected):

grep -n "class BrowserToolConfig" src/probos/config.py
  936: class BrowserToolConfig(BaseModel):
```

`cryptography` package is Apache 2.0 / BSD dual-licensed (verified on PyPI). KEK derivation via stdlib `hashlib.scrypt` — no extra dep for derivation. Fernet authenticated encryption is `cryptography.fernet`.
