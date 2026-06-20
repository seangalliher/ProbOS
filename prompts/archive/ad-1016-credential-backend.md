# AD-1016 — Credential backend abstraction: vault + OS keychain

**Track:** GitHub #957 (epic #955). **Highest AD at authoring: AD-1015 → this is AD-1016.**
**Repo:** OSS (`d:\ProbOS`). Backend + config + startup only — no MCP auth wiring (AD-1017), no HXI, no per-agent grants.

> **Architect:** verify every reference; re-grep the ceiling; confirm the `CredentialVault` Protocol method set + signatures exactly so the keychain backend is structurally substitutable. Resolve the crew-token-gating question for the keychain backend (§2). Confirm the fake-keyring test approach (`keyrings.alt` memory backend vs `keyring.set_keyring`).

---

## 1. Goal

Make the credential layer pluggable so secrets live in either the existing **encrypted file vault** or the **OS keychain** (Windows DPAPI / macOS Keychain / Linux libsecret), operator-selectable via `CredentialVaultConfig.backend`. AD-1015's `McpServerStore.credential_ref`/`auth_kind` resolve here (AD-1017 wires them). Consumers are already backend-agnostic (they use only the `CredentialVault` Protocol).

Read first:
- `CredentialVault` Protocol + `EncryptedFileCredentialVault` — [credentials.py](src/probos/tools/browser/credentials.py): `store(*, ref, value, scope)`, `read(*, ref, requesting_agent_id) -> str|None`, `materialize_to_temp(*, ref, requesting_agent_id) -> Path|None`, `delete(*, ref)`, `list_refs() -> list[CredentialMetadata]`. `CredentialScope` (frozen: allowed_agent_ids/domains/expires_at + `permits_agent`/`is_expired`/`to_dict`/`from_dict`); `CredentialMetadata` (ref/scope/created_at/last_read_at/read_count — NO value).
- `CredentialEncryptor` — [credential_encryption.py](src/probos/security/credential_encryption.py) (AD-754): `store(key, value)`/`retrieve(key)->str|None`/`delete(key)` over `keyring` (get/set/delete_password, honest-degrade on failure).
- `CredentialVaultConfig` — [config.py](src/probos/config.py#L1289): `enabled=False`, **`backend: str = "file"`** (the selector seam — extend, don't add), `file_path`, `max_credentials`, `require_https_for_fill`.
- Startup — [finalize.py](src/probos/startup/finalize.py#L224): builds `EncryptedFileCredentialVault` when `enabled` + `crew_scope_token`; `runtime.credential_vault = vault`; honest-degrade to None.
- Consumers (Protocol-only, do not touch): `vault.read(...)` [cloud_pickers.py](src/probos/routers/cloud_pickers.py#L135), `vault.materialize_to_temp(...)` [actions.py](src/probos/tools/browser/actions.py#L463).

## 2. `KeyringCredentialBackend` (new) — `src/probos/security/keyring_backend.py`

Implements the **`CredentialVault` Protocol** exactly (same method names + keyword-only signatures + return types — structurally substitutable for `EncryptedFileCredentialVault`). **VERIFIED: all five Protocol methods are `async`** (`async def store/read/materialize_to_temp/delete/list_refs`). `keyring` is synchronous; wrap each keyring call in `await asyncio.to_thread(...)` so the async signatures are honored without a blocking-call-in-async smell.

**The enumeration problem.** The OS keychain is a `service+username→value` KV store with **no list** and **no metadata**. So the backend keeps a **non-secret metadata sidecar** (JSON at a config path, e.g. `data/credential_keyring_index.json`): `{"refs": {ref: {"scope": {...}, "created_at": float, "last_read_at": float|None, "read_count": int}}}` — **values NEVER in the sidecar**; values live only in the OS keychain. Atomic tmp+rename write (match the file-vault pattern). A threading lock like the file vault.

- `__init__(*, service_name: str, index_path: Path, encryptor: CredentialEncryptor | None = None)` — default a `CredentialEncryptor(app_name=service_name)`; load the sidecar.
- `store(*, ref, value, scope)` → `encryptor.store(ref, value)` (keyring) + sidecar metadata (scope.to_dict, created_at=now, last_read_at=None, read_count=0); enforce `max_credentials` if wired.
- `read(*, ref, requesting_agent_id)` → sidecar lookup → `scope.is_expired()`→None, `not scope.permits_agent(agent)`→None → `encryptor.retrieve(ref)`; on hit bump last_read_at/read_count + persist sidecar. Missing ref or keyring miss → None.
- `materialize_to_temp(*, ref, requesting_agent_id)` → `read(...)` then write to a 0600 temp file (reuse the file-vault helper if it can be lifted to a shared function WITHOUT changing the file vault's behavior; else replicate minimally). Returns Path|None.
- `delete(*, ref)` → `encryptor.delete(ref)` + drop sidecar entry + persist.
- `list_refs()` → `[CredentialMetadata(...)]` from the sidecar (metadata only).
- **Availability/honest-degrade:** wrap keyring calls; if the keyring raises `NoKeyringError`/any backend error, log a structured warning and degrade (read/list return None/[]; store raises a clear error so the caller knows it didn't persist). The backend must never crash the runtime.

**Crew-token gating decision (RESOLVED):** the file vault uses `crew_scope_token` to derive the Fernet KEK. The keychain backend's secrecy is the **OS keychain itself** (already encrypted at rest by the OS), so it does NOT need the KEK to encrypt values. **Decision: the keychain backend requires `enabled=True` but does NOT require `crew_scope_token`** (the sidecar holds no secrets). Startup gates each backend accordingly (file → needs token; keychain → token optional). Document in the module + finalize.py comment.

## 3. Config + startup

- `config.py` `CredentialVaultConfig.backend`: update the description to `"file" (default) | "keychain"`; add a `@field_validator("backend")` that rejects anything else. Add `keyring_index_path: str = "data/credential_keyring_index.json"` and `keyring_service_name: str = "probos.credentials"`.
- `finalize.py` (the AD-706f block ~L224): switch on `vault_cfg.backend`:
  - `"file"` (or unset) → today's `EncryptedFileCredentialVault` path **unchanged** (still requires `enabled` + `crew_scope_token`).
  - `"keychain"` → build `KeyringCredentialBackend(service_name=vault_cfg.keyring_service_name, index_path=Path(vault_cfg.keyring_index_path))` when `enabled` (token optional per §2); assign `runtime.credential_vault`. Honest-degrade to None on construction failure with a structured warning.
- No change to consumers, the Protocol, or the file-vault wire format.

## 4. Tests — `tests/test_ad1016_keyring_backend.py`

BF-287 (VERIFIED approach): `keyrings.alt` is **NOT installed**. Mirror the established pattern in [test_credential_encryptor.py](tests/test_credential_encryptor.py) — `monkeypatch.setattr("keyring.set_password"/"keyring.get_password"/"keyring.delete_password", <real dict-backed functions>)` so storage semantics are REAL (a module-level dict), not MagicMock. Sidecar on `tmp_path`.
- Protocol conformance: assert `KeyringCredentialBackend` has the 5 Protocol methods with matching signatures (e.g. `inspect.signature` vs `EncryptedFileCredentialVault`, or a `isinstance`-style structural check).
- store→read returns value; wrong-agent scope → None; expired scope → None; delete removes value AND sidecar entry; list_refs → metadata only; read bumps read_count + last_read_at.
- **Secret never in sidecar:** after store, assert the on-disk index JSON does not contain the secret value.
- materialize_to_temp writes a file containing the value; file mode is restrictive (best-effort on Windows).
- Honest-degrade: a keyring that raises on get → read returns None (no crash); list_refs still works from the sidecar.
- Config: `backend="keychain"` accepted; `backend="bogus"` rejected by the validator; `backend="file"` default unchanged.
- Run the existing credential-vault suite unchanged: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -k "credential or vault or 706f or 754 or config" -q -n 0 -p no:cacheprovider`.

## 5. Do NOT change
- ❌ The `CredentialVault` Protocol surface, `EncryptedFileCredentialVault` behavior/wire format, or consumers (`cloud_pickers`, `actions`). ❌ MCP auth/OAuth (AD-1017). ❌ HXI. ❌ per-agent grants. Default `backend="file"` ⇒ byte-identical.

## 6. Acceptance
All §4 green; file-vault suite unchanged; `KeyringCredentialBackend` structurally substitutable; no secret value in the sidecar; both startup branches honest-degrade; full type annotations; Pydantic v2 validator; async hygiene; **verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

## 7. Files the Builder will touch
**Create:** `src/probos/security/keyring_backend.py`, `tests/test_ad1016_keyring_backend.py`.
**Modify:** `src/probos/config.py` (`CredentialVaultConfig`: backend description + validator + `keyring_index_path`/`keyring_service_name`), `src/probos/startup/finalize.py` (backend switch in the AD-706f block), `DECISIONS.md` + `PROGRESS.md` (AD-1016 entry).
**Do NOT touch:** `tools/browser/credentials.py` (Protocol + file vault), `security/credential_encryption.py`, `routers/cloud_pickers.py`, `tools/browser/actions.py`.

## 8. Verified-against-codebase (2026-06-16)
- `CredentialVault` Protocol: 5 async methods, keyword-only, exact signatures (credentials.py:86–92). ✅
- `CredentialEncryptor.store/retrieve/delete` (credential_encryption.py, AD-754) honest-degrades on keyring failure. ✅
- `CredentialVaultConfig.backend: str = "file"` exists (config.py:1301) — extend, don't add. ✅
- finalize.py AD-706f block at L224 builds the file vault + assigns `runtime.credential_vault`; honest-degrade to None. ✅
- Consumers use only the Protocol (cloud_pickers.py:135 `read`, actions.py:463 `materialize_to_temp`). ✅
- `keyrings.alt` NOT installed → tests monkeypatch `keyring.*_password` with real dict-backed fns (test_credential_encryptor.py pattern). ✅
