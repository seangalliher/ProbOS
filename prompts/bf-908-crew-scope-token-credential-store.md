# BF-908 (#1605): the crew-scope token resolves through the credential store, OS keyring first, behind one accessor; the config files join the BF-758 floor

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-20
**Status:** build-ready contract, two slices in one batch (C1a, C1b). Not yet dry-run.
**Base:** `origin/main` `2b97ca115c8295381c4907a9fb5ad5a4aef84cf8` (AD-1343 batch A and BF-909 merged). Every SEARCH block below was written against this tree.
**Tier:** HIGH, confirmed, not raised (credentials; a gate on every Captain route; a shared contract: one accessor behind eleven reads in six modules). Exempt from the new-capability pause (a defect).
**Issue:** closes #1605; references #1595 (a prerequisite for closing it), does not close it.
**Number:** BF-908 only (issue #1605 title). No AD number. AD ceiling `AD-1346` (`scripts/ad_ceiling.py`, 2026-10-20: git subjects and issue titles), next AD-1347, unused.
**Dependencies:** none outside this tree. `keyring>=25.0` is already a core dependency (`pyproject.toml:62`).
**Estimated tests:** about 70 new (C1a about 50, C1b about 20), no deleted tests, no edited existing tests.

**Process (unchanged from the consult of 2026-10-20 05:07Z, #1595 comment 6283928462):** each slice gets its own Builder milestones, one consolidated focused check, a cross-family Diff Reviewer pass (`gpt-6.1-sol`) and its own local commit; then ONE receipted broad gate for the batch and one PR. A mutation campaign is required (HIGH): table in section 9.

---

## 1. Problem

The Captain's crew-scope token (`auth.crew_scope_token`) is the only credential between a caller and every Captain-only route, and it keys the browser's file credential vault. It lives only in the config file, in plain text, which any process running as the Captain's OS user can read, an agent's shell command included; and the BF-758 file-read floor does not cover that file.

| Fact | Evidence (this tree) |
|---|---|
| The setting is a plain pydantic field, read from YAML only | `src/probos/config.py:2926-2939` (`AuthConfig`), `:4103-4113` (`load_config`) |
| Eleven direct reads in six modules, plus the dependency's own read | `routers/auth.py:38` (`_configured_token`); `routers/agent_stop.py:54`; `routers/identity.py:163`, `:306`; `routers/security.py:223`, `:302`; `routers/federation_attachments.py:101`, `:110`, `:158` (`getattr`); `startup/finalize.py:423`, `:468` (passed to the vault at `:501`) |
| An empty token makes `require_crew_scope` a pass-through | `routers/auth.py:57-59` |
| The vessel loads `--config`, else `~/.probos/config.yaml`, else the checkout's `config/system.yaml`, and records it | `__main__.py:486-503`; `__main__.py:639` (`runtime.config_path`) |
| The floor is the data directory plus two leaf names | `security/file_access.py:61-64` (`PROTECTED_LEAF_NAMES`), `:136`, `:185-202` (`protected_read_roots`) |
| A content search checks only its ROOT against the floor, then returns matching lines of every file under it | `agents/code_search.py:142-156` (root), `:165-222` (rg), `:228-271` (Python) |
| `CredentialStore` resolves config, env, a plaintext JSON store, then a CLI; `get()` skips the department check when `department` is None and the tier check unless enforcement is on | `credential_store.py:331-369`, `:189` (JSON write), `:279`, `:291` |
| `CredentialEncryptor.retrieve` turns every keyring failure into `None` | `security/credential_encryption.py:25-37` |
| AD-1196 already has a fail-closed, secure-backend-only keyring rule | `identity_key_store.py:84-92`, `:151-167` |
| `trusted_command_env()` hands the whole runtime environment to 17 modules, an operator-approved MCP server among them | `execution/command_env.py:134-149`; consumers listed in section 11 |
| The Settings save rewrites the loaded config file from the in-memory config | `routers/config.py:246`, `:262-267` |

## 2. Solution overview

1. **One accessor** (`probos/credential_store.py`): `crew_scope_token(runtime)` and `crew_scope_locked(runtime)`. Every one of the eleven reads, and `routers/auth.py`, call it. A structural test fails if any module other than the owner reads the setting.
2. **A keyring step** (`probos/security/crew_scope.py`, composed into `CredentialStore` as the public attribute `crew_scope`): one dedicated entry (`probos.crew_scope` / `crew_scope_token`), read once at startup (Phase 1a, right after the stop record opens), through AD-1196's secure-backend rule. Not a `CredentialSpec`, never in the JSON store, so no `get()` caller can reach it.
3. **Fail closed:** a secure keyring that fails, does not answer or holds a malformed entry is *unavailable*; with no token in the config file either, every crew-scope route refuses every caller (403 `crew_scope_token_unavailable`) instead of passing everyone through. A host with *no* secure backend has no keyring step and behaves exactly as today.
4. **The config file keeps working, with a warning:** a token found only in the config file is still enforced; startup and `probos doctor` warn, naming the file and the setting, never the value, and say how to move it. Nothing writes, moves or deletes it.
5. **The Captain's CLI:** `probos crew-token set | rotate | clear | status`. The token comes from a no-echo prompt (twice) or one line of standard input, never the command line. No route, crew tool, federation surface or MCP server imports the code that writes the entry.
6. **The floor:** the loaded config file, the checkout's `config/system.yaml` and `~/.probos/config.yaml` join `protected_read_roots`; content search drops every match in a file the floor refuses.
7. **Real child-process tests** show what an agent's command, shell agent, `run_python` and the env builders can and cannot obtain, and pin what they still can (section 10).

## 3. Decisions (D1..D18)

| # | Decision | Rejected alternatives, and why |
|---|---|---|
| D1 | **Tier HIGH, confirmed.** | Lowering it: the change gates every Captain route and keys a vault. |
| D2 | **The accessor lives in `probos/credential_store.py`** (`crew_scope_token(runtime)`, `crew_scope_locked(runtime)`), the lowest module that knows `CredentialStore`; routers and startup import it. The keyring I/O and the one read of the config setting (`configured_crew_scope_token`) live in `probos/security/crew_scope.py`. The accessor reads `runtime.config` **live**: a runtime with a real `CredentialStore` gets the keyring's token if it holds one, else its current config's; any other runtime (a `SimpleNamespace` or `MagicMock` test double, `ui/e2e/fixtures/ad1192_backend.py:1371`) reads its config only. So the 95 test sites that set or replace `runtime.config.auth.crew_scope_token` (37 test files) and the UI helper `tests/fixtures/consulted_evidence_bridge.py:457` keep working unchanged. | (a) Copying the keyring's token into `config.auth.crew_scope_token` at startup: `POST /api/config` dumps `runtime.config` into the loaded file (`routers/config.py:246`, `:267`), so the first Settings save would write the keyring token into `system.yaml`, breaking requirement 2; it also keeps eleven reads. (b) New methods on `CredentialStore`: it has exactly 15 direct methods and the AD-1270b gate fires on a 16th (`scripts/check_architecture_principles.py:188`, `:568`); hence the composed `crew_scope` attribute and module functions. (c) The store reading `self._config`: tests replace `runtime.config` after construction (`tests/test_ad1196_identity_keys_api.py:108`), so the store's copy goes stale. |
| D3 | **The keyring step uses AD-1196's rule** (`secure_keyring_backend`, extracted from `KeyringKeyStore._resolve_backend`, behaviour unchanged): a recommended backend only, a `ChainerBackend` replaced by its first recommended member, every failure fail-closed. | Through `CredentialEncryptor` (AD-754), as the consult first said: `retrieve()` maps every failure to `None` (`credential_encryption.py:29-37`), so a locked keychain would read as "no token" and open every route; and it calls whatever default backend answers, insecure ones included. Duplicating the 15-line rule: DRY. |
| D4 | **The entry is unreachable through `get()`:** it is not a `CredentialSpec`, so `get(name)` answers `None` ("unknown credential", `credential_store.py:273-276`) before the department bypass at `:279` or the tier check at `:291` is reached. Every caller of the store: `cognitive/repair_issue.py:144` (`get("github")`), `experience/commands/commands_status.py:195` (`list_credentials()` -> `available()` -> `get()`); the store reaches the first through `startup/finalize.py:3142`. `rotate()` writes any name to the JSON store (`:182-190`) but the accessor never reads that store. | A spec with `allowed_departments=[]` and `min_tier`: the department check is skipped when `department` is None (`:279`) and the tier check is off by default (`:291`), so a spec would be reachable. |
| D5 | **A third state, fail closed.** Unavailable (a secure backend errors, does not answer within 10 s, or holds a malformed entry) with no token in the config: `require_crew_scope` answers 403 `crew_scope_token_unavailable`, `verify_ws_token` closes 1008, the Captain-only 403 routes refuse (their token is `""`), the file vault stays disabled. With a token in the config: that token is enforced, with the warning. No secure backend at all (headless Linux, CI, the test suite): no keyring step, behaviour exactly as today. | Treating "unavailable" as "absent": a locked keychain would open every route. Refusing to start: a keyring hiccup would stop the vessel of a Captain who never used the keyring. A durable "the token is in the keyring" marker to catch a backend that vanished between boots: any same-user process can delete it and read the keyring anyway (D17); the 403 routes stay closed regardless. Recorded as residual R4. |
| D6 | **No environment-variable source** (Q4). `trusted_command_env()` returns all of `os.environ` (`command_env.py:149`) to 17 modules, an operator-approved MCP server (`integrations/mcp_bridge/transport.py:274`) and the build pipeline's git (`execution/authority.py:781`) among them; a token there would reach third-party code. Test K3 pins this. | An env var excluded from agent paths only: it is excluded from `build_command_env` (the `PROBOS_` prefix, `command_env.py:91-92`) but not from the trusted launches. |
| D7 | **A token found only in the config file keeps working, with a warning** (Q5): startup WARNING and `probos doctor` WARN, naming the file and `auth.crew_scope_token`, never the value, and saying how to move it. A token in both: the keyring's is used and the file's is named as unused. | "Refused": as the orchestrator noted, refusing can only mean refusing to start (treating it as unset is a pass-through). That is the Captain's call and would break every existing deployment at upgrade. |
| D8 | **Read once at start** (Q6), in Phase 1a after the stop record opens and before NATS, any agent or `finalize_startup`. A change (set, rotate, clear) takes effect when the vessel restarts; the CLI says so and that the running vessel keeps the token it started with. The Captain restarts. | Per request: a keyring IPC call on every API request, a keyring hiccup flipping routes per request, and the vault's key is fixed at startup anyway (`finalize.py:497-502`). |
| D9 | **Rotation and the file vault** (Q3): `set` and `rotate` refuse a token that differs from the one in use while the browser file vault (enabled, `backend: file`) holds entries or cannot be read; entering the token in use (moving it from the file) is allowed; `clear` is never refused (an emergency action) and says the vault's entries stay encrypted under the cleared token. | Re-encrypting: the CLI runs beside a vessel that holds the vault in memory and saves it on every write (`tools/browser/credentials.py:184`), so an offline re-encryption would be overwritten; and it needs vault-format code outside AD-706f. |
| D10 | **The floor names files, not leaf names** (Q7): `protected_config_files(runtime)` adds the file the vessel loaded (`runtime.config_path`), the checkout's `config/system.yaml` and `~/.probos/config.yaml`, whichever was loaded (each can hold the token). A reader with no runtime still gets the two defaults. Content search re-checks every match against the floor. | A leaf name: `config.yaml` is too common to refuse everywhere, and an explicit `--config` file has any name. Floor-checking the root only: it returned the token's line from `system.yaml` under an admitted checkout root, and the vault's lines under a root above the data directory (a pre-BF-908 gap this closes too). |
| D11 | **No keyring available** (Q8): the stop routes answer 403 `agent_stop_requires_crew_scope_token`; the other routes behave as today with an empty token (pass-through). Tests D1 and D5. | |
| D12 | **Each child-process test claims only what it proves** (Q9): section 10. One test pins the residual: a shell command can still read a token left in the config file. | A test that claims "agents cannot read the token": false for any same-user process. |
| D13 | **CLI only, no HXI panel** (Q10). `probos crew-token` in `__main__.py`, implemented in `probos/crew_token_cli.py`. Token from `getpass` twice or `--stdin`; no argument takes it. | An HXI panel or any route that sets the token: while no token is set the API is a pass-through, so an agent's shell `curl` to loopback could set a token and lock the Captain out. `POST /api/config` already refuses secret fields (`routers/config.py:232-244`). Considered, deferred. |
| D14 | **`probos doctor` check `crew_scope_token`** (Q11), `doctor/checks/crew_scope_check.py`, registered after `security_check`: OK (keyring, or not set), WARN (a token in the config file, alone or beside the keyring's; no secure keyring with a file token), FAIL (unavailable with no file token). The remediation names `probos crew-token set` and says a panel that sends no token answers 401 while any token is set, as today. | |
| D15 | **Test safety** (mandatory): `tests/conftest.py` forces `PYTHON_KEYRING_BACKEND=keyring.backends.fail.Keyring` at import, before any `probos` import, for this process and every child that inherits `os.environ`; every test that needs a keyring injects an in-memory duck (`tests/fixtures/crew_scope_keyring.py`); test A1 fails if the real backend is reached. A child started through `build_command_env` does NOT inherit the variable (the name holds `KEY`, so it is credential-shaped, `command_env.py:51-55`), so no such child script may import `keyring` (test K5). | `setdefault`: a shell that names a real backend would reach it. `keyring.set_keyring(...)`: AD-1196 tests forbid it (`tests/test_ad1196_identity_keys_api.py:57`). |
| D16 | **No value is ever printed or logged.** Errors carry an exception type name, a backend's class name or a rule name; `KeyringRead.token` is `repr=False`; the CLI reads the config through AD-1137's redacting `describe_load_failure`. | |
| D17 | **The residual is recorded** in `DECISIONS.md` (BF-908), in `security/crew_scope.py`'s and `routers/agent_stop.py`'s docstrings, in the doctor and startup text (which say who can read the file), and the orchestrator posts it on #1605 and #1595. | |
| D18 | **No config-model or golden change.** `AuthConfig` is untouched (its description still says "Set via config/system.yaml"; changing it moves the AD-1270e1 facade digest and the generated config reference: considered, deferred). `ReadFileTool.description` is untouched (pinned by `tests/fixtures/ad1179_tool_definition_golden.json` and `ad1152_agentic_off_golden.json`; it stays true). | |

**Residuals (recorded, D17):** R1 any process running as the vessel's OS user (an agent's shell command, `run_python`, which runs the venv interpreter that has `keyring`) can read and write the keyring entry and could run `probos crew-token` itself. R2 while the token is still in a config file, a shell command or `run_python` can read that file (test K4 pins it). R3 a copy or hard link of the config file under another path is not on the floor, nor is any reader that does not call the floor. R4 a secure backend absent at a boot (for example a Linux session without its secret service) reads as "no keyring": the 403 routes stay closed, the other routes pass through as on any vessel without a token. R5 a change takes effect only at restart, `clear` included.

## 4. Milestones

Build in order. Each milestone is bounded to about 50 tool calls; each slice to about 150.

| Slice | Milestone | Sections | Focused check at the end |
|---|---|---|---|
| C1a | M1 keyring core | 5.1-5.5 | `tests/test_bf908_crew_scope_token.py -k "suite or keyring_step or accessor or reachable"` plus the keyring files in 8.1 |
| C1a | M2 wiring | 5.6-5.12 | the D/E/I tests, and the route files in 8.1 |
| C1a | M3 doctor and CLI | 5.13-5.17 | the F/G/H tests, the doctor files and the four scripts in 8.1; then the slice's consolidated check, Diff Reviewer, commit |
| C1b | M4 floor and search | 6.1-6.2 | J tests and the floor files in 8.2 |
| C1b | M5 children and trackers | 6.3-6.5 | K tests; the slice's consolidated check, Diff Reviewer, commit |

Then the orchestrator: mutation campaign (section 9), one receipted broad gate, PR.

**Staging:** explicit paths only, never `git add -A`. `tests/conftest.py` and `config/system.yaml` may hold unrelated Captain work in an operator checkout: stage `tests/conftest.py` by hunk; this contract never edits `config/system.yaml`.

---

## 5. Slice C1a

### 5.1 New file: `src/probos/security/crew_scope.py`

```python
"""BF-908 (#1605): the crew-scope token's entry in the OS keyring.

The crew-scope token guards every Captain route (``require_crew_scope``) and keys
the browser's file credential vault. Until BF-908 it lived only in the config
file, which any process running as the vessel's user can read, agents' shell
commands included. This module owns its keyring entry: the one place that reads,
stores or clears it, and the one read of ``auth.crew_scope_token`` from a config
(:func:`configured_crew_scope_token`).

* :class:`CrewScopeKeyring` is ``CredentialStore``'s keyring step. Startup reads
  the entry once (:meth:`CrewScopeKeyring.load`); a change takes effect at the next
  start, because the browser vault's key is fixed then.
* :func:`store_keyring_token` and :func:`clear_keyring_token` are the Captain's:
  only ``probos crew-token`` (``probos/crew_token_cli.py``) calls them. No route,
  crew tool, federation surface or MCP server imports this module
  (``tests/test_bf908_crew_scope_token.py`` pins both).

The keyring is used through a recommended (secure) backend only, by the AD-1196
rule (:func:`probos.identity_key_store.secure_keyring_backend`). A host with no
secure backend has no keyring step, and the token can come only from the config
file. A secure backend that fails or does not answer is UNAVAILABLE, never "no
token": with no token in the config file either, every route that needs the
token refuses every caller instead of letting every caller through.

What this does not defend: any process running as the vessel's OS user can read
and write this entry with the ``keyring`` package, agents' shell commands and
``run_python`` included. Moving the token here takes it out of files and out of
every child's environment; it does not separate one user's processes.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

#: The keyring entry. Distinct from the browser vault's ``probos.credentials`` and
#: the identity keys' ``probos.identity:<kid>``.
CREW_SCOPE_KEYRING_SERVICE = "probos.crew_scope"
CREW_SCOPE_KEYRING_USERNAME = "crew_scope_token"
#: A keyring that has not answered by then is unavailable (a locked keychain can prompt).
CREW_SCOPE_READ_TIMEOUT_SECONDS = 10.0
#: The shortest token ``probos crew-token`` stores.
MIN_TOKEN_CHARS = 16
#: What every crew-scope route answers while the keyring is unreadable and no token is configured.
CREW_SCOPE_UNAVAILABLE = "crew_scope_token_unavailable"
_NO_SECURE_BACKEND = "no recommended (secure) keyring backend"


class CrewScopeSource(Enum):
    """What the keyring step found."""

    UNREAD = "unread"  # startup has not read it yet
    KEYRING = "keyring"  # a secure keyring holds the token
    ABSENT = "absent"  # a secure keyring holds no token
    NO_SECURE_BACKEND = "no_secure_backend"  # this host has no recommended keyring backend
    UNAVAILABLE = "unavailable"  # a secure keyring failed, did not answer, or holds a malformed entry


@dataclass(frozen=True)
class KeyringRead:
    """One read of the entry. ``token`` is never in the repr; ``reason`` never holds a value."""

    source: CrewScopeSource
    token: str = field(default="", repr=False)
    backend: str = ""
    reason: str = ""


@dataclass(frozen=True)
class CrewScopePosture:
    """Where the token comes from, said without its value. ``severity``: ok, warning or error."""

    severity: str
    message: str
    remediation: str = ""


class CrewScopeKeyringError(Exception):
    """A store or clear the keyring refused. The message never holds the token."""


def configured_crew_scope_token(config: Any) -> str:
    """``auth.crew_scope_token`` from ``config``; ``""`` when the config or its auth section is absent.

    The only read of that setting in ``src/probos`` (pinned by the BF-908 guard test).
    """
    auth = getattr(config, "auth", None) if config is not None else None
    if auth is None:
        return ""
    return auth.crew_scope_token


def token_refusal(value: object) -> str | None:
    """Why ``value`` may not be stored as the token, or ``None`` when it may."""
    if not isinstance(value, str):
        return "not text"
    if len(value) < MIN_TOKEN_CHARS:
        return f"shorter than {MIN_TOKEN_CHARS} characters"
    if any(not ("!" <= char <= "~") for char in value):
        return "not printable ASCII without spaces"
    return None


def _backend_name(backend: Any) -> str:
    kind = type(backend)
    return f"{kind.__module__}.{kind.__qualname__}"


def _secure_backend(backend: Any | None) -> Any:
    """The recommended backend to call, by the AD-1196 rule; raises ``KeyStoreUnavailable``."""
    from probos.identity_key_store import secure_keyring_backend

    return secure_keyring_backend(backend)


def read_keyring_token(backend: Any | None = None) -> KeyringRead:
    """Read the entry once, synchronously. Never raises and never logs the value."""
    from probos.identity_keys import KeyStoreUnavailable

    try:
        chosen = _secure_backend(backend)
    except KeyStoreUnavailable:
        return KeyringRead(CrewScopeSource.NO_SECURE_BACKEND, reason=_NO_SECURE_BACKEND)
    except Exception as exc:  # noqa: BLE001 -- fail closed: an unresolvable keyring is unavailable
        return KeyringRead(CrewScopeSource.UNAVAILABLE, reason=f"the keyring failed ({type(exc).__name__})")
    name = _backend_name(chosen)
    try:
        value = chosen.get_password(CREW_SCOPE_KEYRING_SERVICE, CREW_SCOPE_KEYRING_USERNAME)
    except Exception as exc:  # noqa: BLE001 -- fail closed: a failing read is never "no token"
        return KeyringRead(CrewScopeSource.UNAVAILABLE, backend=name, reason=f"the keyring failed ({type(exc).__name__})")
    if value is None:
        return KeyringRead(CrewScopeSource.ABSENT, backend=name)
    refusal = token_refusal(value)
    if refusal is not None:
        return KeyringRead(CrewScopeSource.UNAVAILABLE, backend=name, reason=f"the keyring entry is malformed ({refusal})")
    return KeyringRead(CrewScopeSource.KEYRING, token=value, backend=name)


async def read_keyring_token_bounded(
    backend: Any | None = None, *, timeout_seconds: float = CREW_SCOPE_READ_TIMEOUT_SECONDS,
) -> KeyringRead:
    """:func:`read_keyring_token` off the event loop, bounded in time. Raises only ``CancelledError``."""
    try:
        return await asyncio.wait_for(asyncio.to_thread(read_keyring_token, backend), timeout=timeout_seconds)
    except TimeoutError:
        return KeyringRead(
            CrewScopeSource.UNAVAILABLE, reason=f"the keyring did not answer within {timeout_seconds:g} s",
        )
    except Exception as exc:  # noqa: BLE001 -- the worker could not run: unavailable, fail closed
        return KeyringRead(CrewScopeSource.UNAVAILABLE, reason=f"the keyring read did not run ({type(exc).__name__})")


def store_keyring_token(value: str, *, backend: Any | None = None) -> str:
    """Store ``value`` as the entry and read it back; return the backend's name.

    The Captain's action only (``probos crew-token``). Raises :class:`CrewScopeKeyringError`.
    """
    from probos.identity_keys import KeyStoreUnavailable

    if token_refusal(value) is not None:
        raise CrewScopeKeyringError("the token does not meet the stored-token rule")
    try:
        chosen = _secure_backend(backend)
    except KeyStoreUnavailable:
        raise CrewScopeKeyringError(f"this host has {_NO_SECURE_BACKEND}") from None
    name = _backend_name(chosen)
    try:
        chosen.set_password(CREW_SCOPE_KEYRING_SERVICE, CREW_SCOPE_KEYRING_USERNAME, value)
        stored = chosen.get_password(CREW_SCOPE_KEYRING_SERVICE, CREW_SCOPE_KEYRING_USERNAME)
    except Exception as exc:  # noqa: BLE001 -- the type only: a backend's text could quote the value
        raise CrewScopeKeyringError(f"the keyring {name} refused the token ({type(exc).__name__})") from None
    if not isinstance(stored, str) or not hmac.compare_digest(stored.encode("utf-8"), value.encode("utf-8")):
        raise CrewScopeKeyringError(f"the keyring {name} did not keep the token")
    return name


def clear_keyring_token(*, backend: Any | None = None) -> bool:
    """Delete the entry: ``True`` when one was removed, ``False`` when there was none. The Captain's action only."""
    import keyring.errors

    from probos.identity_keys import KeyStoreUnavailable

    try:
        chosen = _secure_backend(backend)
    except KeyStoreUnavailable:
        raise CrewScopeKeyringError(f"this host has {_NO_SECURE_BACKEND}") from None
    name = _backend_name(chosen)
    try:
        chosen.delete_password(CREW_SCOPE_KEYRING_SERVICE, CREW_SCOPE_KEYRING_USERNAME)
    except keyring.errors.PasswordDeleteError:
        return False
    except Exception as exc:  # noqa: BLE001 -- the type only
        raise CrewScopeKeyringError(f"the keyring {name} refused to clear the token ({type(exc).__name__})") from None
    return True


def crew_scope_posture(read: KeyringRead, *, config_holds_token: bool, config_file: str) -> CrewScopePosture:
    """Where the token comes from, for the startup log, ``probos doctor`` and ``probos crew-token status``."""
    source = read.source
    if source is CrewScopeSource.KEYRING and config_holds_token:
        return CrewScopePosture(
            "warning",
            f"BF-908: auth.crew_scope_token in {config_file} is not used: the OS keyring holds the crew-scope "
            "token. Delete that line; any process running as this user can read the file.",
            f"Delete auth.crew_scope_token from {config_file}. ProbOS never edits the file.",
        )
    if source is CrewScopeSource.KEYRING:
        return CrewScopePosture("ok", f"crew-scope token: held in the OS keyring ({read.backend})")
    if not config_holds_token and source is CrewScopeSource.UNAVAILABLE:
        return CrewScopePosture(
            "error",
            f"BF-908: the OS keyring could not be read ({read.reason}) and {config_file} sets no crew-scope token, "
            f"so every route that needs the token refuses every caller (403 {CREW_SCOPE_UNAVAILABLE}) until the "
            "vessel restarts with the keyring readable.",
            "Unlock or repair the OS keyring, then restart the vessel; `probos crew-token status` shows what it answers.",
        )
    if not config_holds_token:
        return CrewScopePosture(
            "ok", "crew-scope token: not set; the Captain-only routes answer 403 and the other API routes take no token",
        )
    exposed = (
        f"BF-908: the crew-scope token is read from auth.crew_scope_token in {config_file}, which any process "
        "running as this user can read, agents' shell commands included."
    )
    if source is CrewScopeSource.NO_SECURE_BACKEND:
        return CrewScopePosture(
            "warning", f"{exposed} This host has no secure OS keyring to move it to.",
            "Keep the file readable by your user only; `probos crew-token set` needs a secure OS keyring.",
        )
    if source is CrewScopeSource.UNAVAILABLE:
        exposed = f"{exposed} The OS keyring could not be read ({read.reason})."
    return CrewScopePosture(
        "warning", exposed,
        "Run `probos crew-token set` and enter the same token, so HXI and the browser vault keep working, then "
        f"delete auth.crew_scope_token from {config_file} and restart. ProbOS never edits the file. While any "
        "token is set, an HXI panel that sends none answers 401, as it does now.",
    )


class CrewScopeKeyring:
    """BF-908: ``CredentialStore``'s keyring step for the crew-scope token, read once at startup."""

    def __init__(
        self, *, backend: Any | None = None, timeout_seconds: float = CREW_SCOPE_READ_TIMEOUT_SECONDS,
    ) -> None:
        self._backend = backend
        self._timeout_seconds = timeout_seconds
        self._read = KeyringRead(CrewScopeSource.UNREAD)

    @property
    def source(self) -> CrewScopeSource:
        """What the last read found (``UNREAD`` before startup reads it)."""
        return self._read.source

    async def load(self, *, config: Any = None, config_path: str | None = None) -> KeyringRead:
        """Read the entry (bounded; raises only ``CancelledError``) and log where the token comes from."""
        read = await read_keyring_token_bounded(self._backend, timeout_seconds=self._timeout_seconds)
        self._read = read
        posture = crew_scope_posture(
            read, config_holds_token=bool(configured_crew_scope_token(config)),
            config_file=config_path or "the loaded configuration",
        )
        if posture.severity == "ok":
            logger.info("%s", posture.message)
        elif posture.severity == "warning":
            logger.warning("%s", posture.message)
        else:
            logger.error("%s", posture.message)
        return read

    def token(self, config: Any) -> str:
        """The token to enforce: the keyring's when it holds one, else ``config``'s (``""`` when neither)."""
        if self._read.source is CrewScopeSource.KEYRING:
            return self._read.token
        return configured_crew_scope_token(config)

    def locked(self, config: Any) -> bool:
        """True when a secure keyring could not be read and ``config`` holds no token: refuse every caller."""
        return self._read.source is CrewScopeSource.UNAVAILABLE and not configured_crew_scope_token(config)
```

Notes for the Builder: no `logger.log(...)` and no `event_log.log(...)` call (the AD-1195 census scans `.log(` calls, `tests/test_ad1195_eventlog_pair_freeze.py:121-130`); no `asyncio.create_task` (AD-1270b `unowned-task`).

### 5.2 `src/probos/identity_key_store.py`: extract the secure-backend rule (behaviour unchanged)

SEARCH:
```python
def _require_recommended(backend: Any) -> Any:
    import keyring.core

    if not keyring.core.recommended(backend):
        raise KeyStoreUnavailable(
            f"keyring backend {_qualified_name(backend)} (priority {_priority(backend)}) is not a "
            "recommended secure backend; identity keys are never stored on it"
        )
    return backend


class KeyringKeyStore:
```
REPLACE:
```python
def _require_recommended(backend: Any) -> Any:
    import keyring.core

    if not keyring.core.recommended(backend):
        raise KeyStoreUnavailable(
            f"keyring backend {_qualified_name(backend)} (priority {_priority(backend)}) is not a "
            "recommended secure backend; identity keys are never stored on it"
        )
    return backend


def secure_keyring_backend(backend: Any | None = None) -> Any:
    """The recommended (secure) keyring backend to call: ``backend``, else the process default.

    A ``ChainerBackend`` is replaced by its first recommended member and never called
    through, because a chained miss falls through to whatever insecure backend answers.
    Raises :class:`KeyStoreUnavailable` when no secure backend is available. AD-1196's
    rule, shared with BF-908's crew-scope token (``probos/security/crew_scope.py``).
    """
    import keyring
    import keyring.core
    from keyring.backends.chainer import ChainerBackend

    chosen = backend if backend is not None else keyring.get_keyring()
    if not isinstance(chosen, ChainerBackend):
        return _require_recommended(chosen)
    candidates = [b for b in chosen.backends if keyring.core.recommended(b)]
    if not candidates:
        raise KeyStoreUnavailable(
            "no chained keyring backend is recommended (secure): "
            + ", ".join(f"{_qualified_name(b)} (priority {_priority(b)})" for b in chosen.backends)
        )
    return _require_recommended(candidates[0])


class KeyringKeyStore:
```

SEARCH:
```python
    def _resolve_backend(self) -> Any:
        """The secure backend for this call (runs in the worker thread)."""
        import keyring
        import keyring.core
        from keyring.backends.chainer import ChainerBackend

        backend = self._backend if self._backend is not None else keyring.get_keyring()
        if not isinstance(backend, ChainerBackend):
            return _require_recommended(backend)
        candidates = [b for b in backend.backends if keyring.core.recommended(b)]
        if not candidates:
            raise KeyStoreUnavailable(
                "no chained keyring backend is recommended (secure): "
                + ", ".join(f"{_qualified_name(b)} (priority {_priority(b)})" for b in backend.backends)
            )
        backend = candidates[0]
        return _require_recommended(backend)
```
REPLACE:
```python
    def _resolve_backend(self) -> Any:
        """The secure backend for this call (runs in the worker thread)."""
        return secure_keyring_backend(self._backend)
```

### 5.3 `src/probos/credential_store.py`: compose the keyring step; the accessor

SEARCH:
```python
"""CredentialStore -- Ship's Computer credential resolution service (AD-395).

Centralizes credential lookup across ProbOS agents and adapters.
Resolution chain: explicit config -> environment variable -> CLI tool -> None.
"""
```
REPLACE:
```python
"""CredentialStore -- Ship's Computer credential resolution service (AD-395).

Centralizes credential lookup across ProbOS agents and adapters.
Resolution chain: explicit config -> environment variable -> CLI tool -> None.

BF-908: the crew-scope token is not a CredentialSpec. ``crew_scope_token(runtime)``
below is its one reader: the OS keyring's entry (``CredentialStore.crew_scope``,
read once at startup), else ``auth.crew_scope_token`` from the runtime's config.
"""
```

SEARCH:
```python
from probos.execution.command_env import trusted_command_env

logger = logging.getLogger(__name__)
```
REPLACE:
```python
from probos.execution.command_env import trusted_command_env
from probos.security.crew_scope import (  # noqa: F401 -- CREW_SCOPE_UNAVAILABLE is re-exported for routers/auth.py
    CREW_SCOPE_UNAVAILABLE,
    CrewScopeKeyring,
    configured_crew_scope_token,
)

logger = logging.getLogger(__name__)
```

SEARCH:
```python
        # AD-456c: per-tier credential lookup gate. Default False preserves
        # AD-456 v1 ungated-lookup behavior; finalize flips to True when
        # ``config.security_infra.credential_tier_enforcement`` is set.
        self._tier_enforcement: bool = False
        self._register_builtins()
```
REPLACE:
```python
        # AD-456c: per-tier credential lookup gate. Default False preserves
        # AD-456 v1 ungated-lookup behavior; finalize flips to True when
        # ``config.security_infra.credential_tier_enforcement`` is set.
        self._tier_enforcement: bool = False
        # BF-908: the crew-scope token's keyring step. Not a CredentialSpec and never in
        # the JSON store, so get(), available(), list_credentials() and rotate() never
        # reach it; crew_scope_token(runtime) at the end of this module is its one reader.
        self.crew_scope = CrewScopeKeyring()
        self._register_builtins()
```

SEARCH:
```python
    def list_credentials(self) -> list[dict[str, str | bool]]:
        """List registered credential names and status. Never returns values."""
        results = []
        for spec in self._specs.values():
            results.append({
                "name": spec.name,
                "available": self.available(spec.name),
                "description": spec.description,
            })
        return results
```
REPLACE:
```python
    def list_credentials(self) -> list[dict[str, str | bool]]:
        """List registered credential names and status. Never returns values."""
        results = []
        for spec in self._specs.values():
            results.append({
                "name": spec.name,
                "available": self.available(spec.name),
                "description": spec.description,
            })
        return results


def crew_scope_token(runtime: Any) -> str:
    """BF-908 (#1605): the crew-scope token to enforce; the one read every route and startup use.

    The OS keyring's entry (read once at startup through ``runtime.credential_store``),
    else ``auth.crew_scope_token`` from the runtime's current config, else ``""``. A
    runtime without a ``CredentialStore`` (a test double) reads its config only.
    """
    config = getattr(runtime, "config", None)
    store = getattr(runtime, "credential_store", None)
    if isinstance(store, CredentialStore):
        return store.crew_scope.token(config)
    return configured_crew_scope_token(config)


def crew_scope_locked(runtime: Any) -> bool:
    """BF-908: True when a secure keyring could not be read and no token is configured; refuse every caller."""
    store = getattr(runtime, "credential_store", None)
    return isinstance(store, CredentialStore) and store.crew_scope.locked(getattr(runtime, "config", None))
```

### 5.4 `tests/conftest.py`: no test reaches the real keyring

SEARCH:
```python
os.environ.setdefault("PROBOS_DISABLE_OVERLAY", "1")

# Windows: closing an asyncio loop must not pin an ephemeral TCP port in TIME_WAIT. Module level, so it is in
```
REPLACE:
```python
os.environ.setdefault("PROBOS_DISABLE_OVERLAY", "1")

# BF-908 (#1605): no test reaches the Captain's real OS keyring (the Windows credential store on
# the Captain's machine). Forced, not setdefault: a shell that names a real backend must not reach
# it either. keyring reads this when it first picks a backend, in this process and in every child
# that inherits os.environ. A child started through execution/command_env.build_command_env does
# NOT inherit it (the name is credential-shaped), so no such child in a test may import keyring.
# tests/test_bf908_crew_scope_token.py fails if the real backend is reached.
os.environ["PYTHON_KEYRING_BACKEND"] = "keyring.backends.fail.Keyring"

# Windows: closing an asyncio loop must not pin an ephemeral TCP port in TIME_WAIT. Module level, so it is in
```

### 5.5 New file: `tests/fixtures/crew_scope_keyring.py`

```python
"""BF-908: keyring ducks for the crew-scope token tests. Never the OS keyring (tests/conftest.py)."""

from __future__ import annotations

import threading
from typing import Any

import keyring.errors

from probos.credential_store import CredentialStore
from probos.security.crew_scope import (
    CREW_SCOPE_KEYRING_SERVICE,
    CREW_SCOPE_KEYRING_USERNAME,
    CrewScopeKeyring,
)

#: Synthetic tokens (16+ printable ASCII characters). No real token is in this tree.
KEYRING_TOKEN = "bf908-synthetic-keyring-token-7d3"
FILE_TOKEN = "bf908-synthetic-file-token-a41"
ROTATED_TOKEN = "bf908-synthetic-rotated-token-5e2"
ENTRY = (CREW_SCOPE_KEYRING_SERVICE, CREW_SCOPE_KEYRING_USERNAME)


class MemoryKeyring:
    """A recommended (priority 5) in-memory backend, duck-typed as AD-1196's tests do."""

    def __init__(self, priority: float = 5, *, token: str | None = None) -> None:
        self.priority = priority
        self.entries: dict[tuple[str, str], str] = {}
        if token is not None:
            self.entries[ENTRY] = token

    def get_password(self, service: str, username: str) -> str | None:
        return self.entries.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.entries[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        if self.entries.pop((service, username), None) is None:
            raise keyring.errors.PasswordDeleteError("no such entry")


class InsecureKeyring(MemoryKeyring):
    """Priority 0: never recommended, so the host has no secure backend."""

    def __init__(self, *, token: str | None = None) -> None:
        super().__init__(priority=0, token=token)


class FailingKeyring(MemoryKeyring):
    """A recommended backend whose every call raises, as a locked or broken keychain does."""

    def get_password(self, service: str, username: str) -> str | None:
        raise RuntimeError("keychain locked")

    def set_password(self, service: str, username: str, password: str) -> None:
        raise RuntimeError("keychain locked")

    def delete_password(self, service: str, username: str) -> None:
        raise RuntimeError("keychain locked")


class ForgetfulKeyring(MemoryKeyring):
    """A recommended backend that accepts a write and keeps nothing."""

    def set_password(self, service: str, username: str, password: str) -> None:
        return None


class SilentKeyring(MemoryKeyring):
    """A recommended backend whose read blocks until released (a keychain prompt nobody answers)."""

    def __init__(self) -> None:
        super().__init__()
        self.release = threading.Event()

    def get_password(self, service: str, username: str) -> str | None:
        self.release.wait(5)
        return None


async def loaded_store(config: Any, backend: Any, *, config_path: str | None = None) -> CredentialStore:
    """A real CredentialStore whose keyring step reads ``backend`` once, as startup does."""
    store = CredentialStore(config=config)
    store.crew_scope = CrewScopeKeyring(backend=backend)
    await store.crew_scope.load(config=config, config_path=config_path)
    return store
```

### 5.6 `src/probos/routers/auth.py`

SEARCH:
```python
from fastapi import Depends, Header, HTTPException, Request, WebSocket

from probos.routers.deps import get_runtime
from probos.tools.browser.lifecycle import BrowserActor, BrowserAuthorityBasis

logger = logging.getLogger(__name__)


def _configured_token(runtime: Any) -> str:
    """Pull ``auth.crew_scope_token`` from runtime config; empty when unset."""
    cfg = getattr(runtime, "config", None)
    if cfg is None:
        return ""
    auth_cfg = getattr(cfg, "auth", None)
    if auth_cfg is None:
        return ""
    return auth_cfg.crew_scope_token
```
REPLACE:
```python
from fastapi import Depends, Header, HTTPException, Request, WebSocket

from probos.credential_store import CREW_SCOPE_UNAVAILABLE, crew_scope_locked, crew_scope_token
from probos.routers.deps import get_runtime
from probos.tools.browser.lifecycle import BrowserActor, BrowserAuthorityBasis

logger = logging.getLogger(__name__)
```

SEARCH:
```python
    When ``auth.crew_scope_token`` is empty, this dependency is a pass-through -
    backward-compatible with single-operator HXI installs. When configured,
    missing / malformed / wrong tokens raise HTTP 401.
    """
    expected = _configured_token(runtime)
    if not expected:
        return  # auth disabled
```
REPLACE:
```python
    When no token resolves, this dependency is a pass-through -
    backward-compatible with single-operator HXI installs. When configured,
    missing / malformed / wrong tokens raise HTTP 401.

    BF-908: the token is ``crew_scope_token(runtime)``, the OS keyring's before
    ``auth.crew_scope_token``. While a secure keyring cannot be read and no token
    is configured, every caller is refused (403 ``crew_scope_token_unavailable``):
    an unreadable keyring is never an open gate.
    """
    if crew_scope_locked(runtime):  # BF-908: fail closed, never pass-through
        raise HTTPException(status_code=403, detail=CREW_SCOPE_UNAVAILABLE)
    expected = crew_scope_token(runtime)
    if not expected:
        return  # auth disabled
```

SEARCH:
```python
    basis = (
        BrowserAuthorityBasis.SHARED_CREW_SCOPE
        if _configured_token(runtime)
        else BrowserAuthorityBasis.SINGLE_OPERATOR_COMPATIBILITY
    )
```
REPLACE:
```python
    basis = (
        BrowserAuthorityBasis.SHARED_CREW_SCOPE
        if crew_scope_token(runtime)
        else BrowserAuthorityBasis.SINGLE_OPERATOR_COMPATIBILITY
    )
```

SEARCH:
```python
    expected = _configured_token(runtime)
    if not expected:
        return True
    presented = websocket.query_params.get("token", "") or ""
```
REPLACE:
```python
    expected = crew_scope_token(runtime)
    locked = crew_scope_locked(runtime)  # BF-908: an unreadable keyring refuses every socket
    if not expected and not locked:
        return True
    presented = websocket.query_params.get("token", "") or ""
```
(While locked, `expected` is `""`, so the unchanged next line refuses every presented value: an empty one by `not presented`, any other by `compare_digest`.)

### 5.7 `src/probos/routers/agent_stop.py`

SEARCH:
```python
Authority is the existing Captain authority on the API. ``require_crew_scope`` answers 401
to a missing or wrong bearer token once ``auth.crew_scope_token`` is set; because it lets
every caller through while no token is set, these routes answer 403 until one is (the
AD-1196 / AD-1340 rule: no Captain order through an open gate). Agent tools do not reach
them: ``security/url_guard.py`` refuses loopback to ``http_fetch`` and to every browser
context ProbOS creates. The residual is stated in the AD-1343 contract (C1): a shell or
sandbox run that could read ``config/system.yaml`` could present the token.
```
REPLACE:
```python
Authority is the existing Captain authority on the API. ``require_crew_scope`` answers 401
to a missing or wrong bearer token once a crew-scope token is set; because it lets
every caller through while no token is set, these routes answer 403 until one is (the
AD-1196 / AD-1340 rule: no Captain order through an open gate). Agent tools do not reach
them: ``security/url_guard.py`` refuses loopback to ``http_fetch`` and to every browser
context ProbOS creates. BF-908: the token is ``credential_store.crew_scope_token(runtime)``,
the OS keyring's before ``auth.crew_scope_token``. The residual (DECISIONS.md, BF-908): any
process running as the vessel's user can read the keyring entry, and the config file while
the token is still there.
```

SEARCH:
```python
from probos.agent_stop import LIFT_NOTE, S1_SCOPE, AgentStopService, StopNotFound
from probos.crew_utils import is_crew_agent
from probos.routers.auth import require_crew_scope
```
REPLACE:
```python
from probos.agent_stop import LIFT_NOTE, S1_SCOPE, AgentStopService, StopNotFound
from probos.credential_store import crew_scope_token
from probos.crew_utils import is_crew_agent
from probos.routers.auth import require_crew_scope
```

SEARCH:
```python
    if not isinstance(stops, AgentStopService):
        raise HTTPException(status_code=503, detail=_UNAVAILABLE)
    if not runtime.config.auth.crew_scope_token:  # AD-1343: never a Captain order through an open gate
        raise HTTPException(status_code=403, detail=_TOKEN_REQUIRED)
```
REPLACE:
```python
    if not isinstance(stops, AgentStopService):
        raise HTTPException(status_code=503, detail=_UNAVAILABLE)
    if not crew_scope_token(runtime):  # AD-1343: never a Captain order through an open gate (BF-908: one accessor)
        raise HTTPException(status_code=403, detail=_TOKEN_REQUIRED)
```

### 5.8 `src/probos/routers/identity.py`

SEARCH:
```python
    RecoveryAuthorizationInvalid,
)
from probos.routers.auth import require_crew_scope
from probos.routers.deps import get_runtime
```
REPLACE:
```python
    RecoveryAuthorizationInvalid,
)
from probos.credential_store import crew_scope_token
from probos.routers.auth import require_crew_scope
from probos.routers.deps import get_runtime
```

SEARCH:
```python
    binding = _binding(runtime)
    if not runtime.config.auth.crew_scope_token:
        raise HTTPException(status_code=403, detail=_TOKEN_REQUIRED)
    return binding
```
REPLACE:
```python
    binding = _binding(runtime)
    if not crew_scope_token(runtime):
        raise HTTPException(status_code=403, detail=_TOKEN_REQUIRED)
    return binding
```

SEARCH:
```python
        raise HTTPException(status_code=503, detail=_PEERS_NOT_ARMED)
    if not runtime.config.auth.crew_scope_token:  # AD-1198 slice 2c the AD-1196 A-0 rule: no reset through an open gate
        raise HTTPException(status_code=403, detail=_TOKEN_REQUIRED)
```
REPLACE:
```python
        raise HTTPException(status_code=503, detail=_PEERS_NOT_ARMED)
    if not crew_scope_token(runtime):  # AD-1198 slice 2c the AD-1196 A-0 rule: no reset through an open gate
        raise HTTPException(status_code=403, detail=_TOKEN_REQUIRED)
```

### 5.9 `src/probos/routers/security.py`

SEARCH:
```python
from probos.knowledge.erasure import ErasureManager
from probos.routers.auth import require_crew_scope
from probos.routers.deps import get_runtime
```
REPLACE:
```python
from probos.credential_store import crew_scope_token
from probos.knowledge.erasure import ErasureManager
from probos.routers.auth import require_crew_scope
from probos.routers.deps import get_runtime
```

SEARCH:
```python
    if not runtime.config.auth.crew_scope_token:  # AD-1340 S2a: never serve archived episodes through an open gate
        raise HTTPException(status_code=403, detail=_ARCHIVE_LOOKUP_TOKEN_REQUIRED)
    memory = getattr(runtime, "episodic_memory", None)
```
REPLACE:
```python
    if not crew_scope_token(runtime):  # AD-1340 S2a: never serve archived episodes through an open gate
        raise HTTPException(status_code=403, detail=_ARCHIVE_LOOKUP_TOKEN_REQUIRED)
    memory = getattr(runtime, "episodic_memory", None)
```

SEARCH:
```python
    if not runtime.config.auth.crew_scope_token:  # AD-1340 S2b: never restore through an open gate
        raise HTTPException(status_code=403, detail=_ARCHIVE_RESTORE_TOKEN_REQUIRED)
    memory = getattr(runtime, "episodic_memory", None)
```
REPLACE:
```python
    if not crew_scope_token(runtime):  # AD-1340 S2b: never restore through an open gate
        raise HTTPException(status_code=403, detail=_ARCHIVE_RESTORE_TOKEN_REQUIRED)
    memory = getattr(runtime, "episodic_memory", None)
```

### 5.10 `src/probos/routers/federation_attachments.py`

SEARCH:
```python
from probos.federation.mcp_server import bearer_token_matches, is_json_media_type, read_bounded_body
from probos.federation.peer_requests import ATTACHMENT_REQUEST, MAX_PEER_REQUEST_BYTES
from probos.routers.auth import require_crew_scope
```
REPLACE:
```python
from probos.credential_store import crew_scope_token
from probos.federation.mcp_server import bearer_token_matches, is_json_media_type, read_bounded_body
from probos.federation.peer_requests import ATTACHMENT_REQUEST, MAX_PEER_REQUEST_BYTES
from probos.routers.auth import require_crew_scope
```

SEARCH:
```python
    if peer_requests_armed(runtime.config):  # AD-1198 armed: peers use signed requests, never a bearer token
        if runtime.config.auth.crew_scope_token:
            logger.error(
```
REPLACE:
```python
    if peer_requests_armed(runtime.config):  # AD-1198 armed: peers use signed requests, never a bearer token
        if crew_scope_token(runtime):
            logger.error(
```

SEARCH:
```python
    # 2. Fail-closed token hardening — never serve through a pass-through gate.
    if not runtime.config.auth.crew_scope_token:
        raise HTTPException(
```
REPLACE:
```python
    # 2. Fail-closed token hardening — never serve through a pass-through gate.
    if not crew_scope_token(runtime):
        raise HTTPException(
```

SEARCH:
```python
    if authorization is not None:  # AD-1198 a peer request carries no bearer credential
        crew = getattr(getattr(runtime.config, "auth", None), "crew_scope_token", "") or ""
        if crew and bearer_token_matches(authorization, crew):
```
REPLACE:
```python
    if authorization is not None:  # AD-1198 a peer request carries no bearer credential
        crew = crew_scope_token(runtime) or ""
        if crew and bearer_token_matches(authorization, crew):
```

### 5.11 `src/probos/startup/finalize.py` and `src/probos/tools/browser/credentials.py`

SEARCH:
```python
from probos.utils import format_duration
from probos.crew_utils import is_crew_agent

if TYPE_CHECKING:
```
REPLACE:
```python
from probos.utils import format_duration
from probos.crew_utils import is_crew_agent
from probos.credential_store import crew_scope_token

if TYPE_CHECKING:
```

SEARCH:
```python
        authority_basis=(
            BrowserAuthorityBasis.SHARED_CREW_SCOPE if config.auth.crew_scope_token
            else BrowserAuthorityBasis.SINGLE_OPERATOR_COMPATIBILITY
        ),
```
REPLACE:
```python
        authority_basis=(
            BrowserAuthorityBasis.SHARED_CREW_SCOPE if crew_scope_token(runtime)
            else BrowserAuthorityBasis.SINGLE_OPERATOR_COMPATIBILITY
        ),
```

SEARCH:
```python
    vault_cfg = getattr(cfg, "credential_vault", None)
    auth_cfg = getattr(config, "auth", None)
    crew_token = getattr(auth_cfg, "crew_scope_token", "") if auth_cfg else ""
    backend = getattr(vault_cfg, "backend", "file") if vault_cfg is not None else "file"
```
REPLACE:
```python
    vault_cfg = getattr(cfg, "credential_vault", None)
    crew_token = crew_scope_token(runtime)  # BF-908: the keyring's token, else the config's
    backend = getattr(vault_cfg, "backend", "file") if vault_cfg is not None else "file"
```

SEARCH:
```python
        logger.warning(
            "AD-706f: credential_vault.enabled=True but auth.crew_scope_token "
            "is empty; vault disabled. Set auth.crew_scope_token in "
            "config/system.yaml to enable."
        )
```
REPLACE:
```python
        logger.warning(
            "AD-706f: credential_vault.enabled=True but no crew-scope token "
            "is set; vault disabled. Set one with `probos crew-token set` "
            "(BF-908) and restart to enable."
        )
```

In `src/probos/tools/browser/credentials.py`, SEARCH:
```python
                "AD-706f credential vault requires a non-empty "
                "auth.crew_scope_token. The KEK derivation needs a real "
                "operator secret. Set auth.crew_scope_token in config/system.yaml "
                "and restart, or set credential_vault.enabled=False to disable."
```
REPLACE:
```python
                "AD-706f credential vault requires a non-empty "
                "crew_scope_token. The KEK derivation needs a real "
                "operator secret. Set one with `probos crew-token set` (BF-908) "
                "and restart, or set credential_vault.enabled=False to disable."
```
(`tests/test_ad706f_credential_vault.py:72` matches `crew_scope_token`; the word stays.)

### 5.12 `src/probos/runtime.py`: read the keyring once, in Phase 1a

SEARCH:
```python
        self.agent_stops = AgentStopService(data_dir=self._data_dir, event_log=self.event_log)
        await self.agent_stops.start()
        # AD-1195: Phase 1 opened the EventLog; durable rows are written on this loop.
```
REPLACE:
```python
        self.agent_stops = AgentStopService(data_dir=self._data_dir, event_log=self.event_log)
        await self.agent_stops.start()
        # BF-908 (Phase 1a): the crew-scope token's keyring step, read once, before any route,
        # the browser vault or an agent reads the token. It never raises: a secure keyring that
        # cannot be read is held as "unavailable", and the routes that need the token fail closed.
        await self.credential_store.crew_scope.load(config=self.config, config_path=self.config_path)
        # AD-1195: Phase 1 opened the EventLog; durable rows are written on this loop.
```

### 5.13 New file: `src/probos/doctor/checks/crew_scope_check.py`

```python
"""BF-908 (#1605): where the crew-scope token comes from, and whether a config file still holds it.

Names the file and the setting, never the value. WARN while ``auth.crew_scope_token``
is set in the config file (any process running as the Captain's user can read it);
FAIL when a secure OS keyring cannot be read and the file sets no token, because the
vessel would then refuse every caller on every route that needs the token.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from probos.doctor.protocol import CheckOutcome, CheckResult, DoctorContext
from probos.doctor.registry import register_check
from probos.security.crew_scope import (
    configured_crew_scope_token,
    crew_scope_posture,
    read_keyring_token_bounded,
)

_OUTCOMES = {"ok": CheckOutcome.OK, "warning": CheckOutcome.WARN, "error": CheckOutcome.FAIL}


@dataclass(frozen=True)
class _CrewScopeCheck:
    name: str = "crew_scope_token"
    backend: Any = None  # BF-908: tests inject an in-memory keyring; None reads the OS keyring

    async def run(self, ctx: DoctorContext) -> CheckResult:
        if ctx.config is None:
            return CheckResult(outcome=CheckOutcome.WARN, message="crew-scope token: skipped (config unavailable)")
        read = await read_keyring_token_bounded(self.backend)
        where = ctx.config_path if ctx.config_path is not None else ctx.config_target
        posture = crew_scope_posture(
            read, config_holds_token=bool(configured_crew_scope_token(ctx.config)),
            config_file=str(where) if where is not None else "the config file",
        )
        return CheckResult(outcome=_OUTCOMES[posture.severity], message=posture.message, remediation=posture.remediation)


register_check(_CrewScopeCheck())
```

In `src/probos/doctor/checks/__init__.py`, SEARCH:
```python
    crew_enrollment_check,
    security_check,
    disk_check,
```
REPLACE:
```python
    crew_enrollment_check,
    security_check,
    crew_scope_check,
    disk_check,
```

### 5.14 New file: `src/probos/crew_token_cli.py`

```python
"""BF-908 (#1605): ``probos crew-token`` -- the Captain sets, rotates, clears or inspects the crew-scope token.

The token is read from a no-echo prompt (twice) or, with ``--stdin``, from one line
of standard input; never from the command line, so it reaches neither shell history
nor the process list. It is stored in the OS keyring through
``probos.security.crew_scope``; nothing here writes a config file. A change takes
effect when the vessel next starts.

This is the Captain's action. No route, crew tool or MCP server reaches it: only
``probos/__main__.py`` imports this module (pinned by
``tests/test_bf908_crew_scope_token.py``). An agent's shell command runs as the same
user and could run this command, or call ``keyring`` directly; that residual is
recorded in DECISIONS.md, BF-908.
"""

from __future__ import annotations

import getpass
import hmac
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO

from rich.console import Console
from rich.markup import escape

from probos.security.crew_scope import (
    MIN_TOKEN_CHARS,
    CrewScopeKeyringError,
    CrewScopeSource,
    KeyringRead,
    clear_keyring_token,
    configured_crew_scope_token,
    crew_scope_posture,
    read_keyring_token,
    store_keyring_token,
    token_refusal,
)

_RESTART = "Restart the vessel for this to take effect; until then it keeps the token it started with."


def file_vault_entries(config: Any) -> tuple[Path, int] | None:
    """The browser file vault's path and entry count when it is enabled (-1: unreadable), else None.

    Resolved as the vessel resolves it: relative to the current directory.
    """
    vault = config.browser_tool.credential_vault
    if not vault.enabled or vault.backend != "file":
        return None
    path = Path(vault.file_path).resolve()
    if not path.exists():
        return path, 0
    try:
        refs = json.loads(path.read_text(encoding="utf-8")).get("refs", {})
    except (OSError, ValueError, AttributeError):
        return path, -1
    return (path, len(refs)) if isinstance(refs, dict) else (path, -1)


def _vault_note(count: int) -> str:
    return "cannot be read" if count < 0 else f"holds {count} entr{'y' if count == 1 else 'ies'}"


def _load(config_path: Path, console: Console) -> Any | None:
    from probos.config import load_config
    from probos.doctor.runner import describe_load_failure

    try:
        return load_config(config_path)
    except Exception as exc:  # noqa: BLE001 -- reported without any value from the file (AD-1137)
        console.print(escape(f"Config {config_path} does not load: {describe_load_failure(exc, config_path)}"), style="red")
        return None


def _read_new_token(
    *, use_stdin: bool, stdin: TextIO, stdin_is_tty: Callable[[], bool],
    read_secret: Callable[[str], str], console: Console,
) -> tuple[str | None, int]:
    if use_stdin:
        return stdin.readline().rstrip("\r\n"), 0
    if not stdin_is_tty():
        console.print("Standard input is not a terminal: pass --stdin to read the token from it.", style="red")
        return None, 2
    first = read_secret("New crew-scope token (not shown): ")
    second = read_secret("The same token again: ")
    if not hmac.compare_digest(first.encode("utf-8"), second.encode("utf-8")):
        console.print("The two entries differ; nothing was stored.", style="red")
        return None, 1
    return first, 0


def _status(current: KeyringRead, config: Any, config_path: Path, console: Console) -> int:
    posture = crew_scope_posture(
        current, config_holds_token=bool(configured_crew_scope_token(config)), config_file=str(config_path),
    )
    console.print(escape(posture.message))
    if posture.remediation:
        console.print(escape(posture.remediation), style="dim")
    vault = file_vault_entries(config)
    if vault is not None:
        console.print(escape(f"Browser file vault {vault[0]} {_vault_note(vault[1])}."))
    return 0


def _set(
    command: str, current: KeyringRead, config: Any, config_path: Path, console: Console, backend: Any, *,
    use_stdin: bool, stdin: TextIO, stdin_is_tty: Callable[[], bool], read_secret: Callable[[str], str],
) -> int:
    if current.source is CrewScopeSource.NO_SECURE_BACKEND:
        console.print("This host has no secure OS keyring, so the token cannot be stored there; nothing was stored.", style="red")
        return 1
    if current.source is CrewScopeSource.UNAVAILABLE:
        console.print(escape(f"The OS keyring could not be read ({current.reason}); nothing was stored."), style="red")
        return 1
    if command == "set" and current.source is CrewScopeSource.KEYRING:
        console.print("The OS keyring already holds a crew-scope token: use `probos crew-token rotate` to replace it.", style="red")
        return 1
    if command == "rotate" and current.source is not CrewScopeSource.KEYRING:
        console.print("The OS keyring holds no crew-scope token to rotate: use `probos crew-token set`.", style="red")
        return 1
    value, code = _read_new_token(
        use_stdin=use_stdin, stdin=stdin, stdin_is_tty=stdin_is_tty, read_secret=read_secret, console=console,
    )
    if value is None:
        return code
    refusal = token_refusal(value)
    if refusal is not None:
        console.print(
            escape(f"Not stored: the token is {refusal}; use at least {MIN_TOKEN_CHARS} printable ASCII characters and no spaces."),
            style="red",
        )
        return 1
    in_use = current.token if current.source is CrewScopeSource.KEYRING else configured_crew_scope_token(config)
    changes_key = not hmac.compare_digest(value.encode("utf-8"), in_use.encode("utf-8"))
    vault = file_vault_entries(config)
    if changes_key and vault is not None and vault[1] != 0:
        console.print(
            escape(
                f"Not stored: the browser file vault {vault[0]} {_vault_note(vault[1])}, encrypted under the token in "
                "use; a different token would leave them unreadable. Remove them first, or enter the token in use."
            ),
            style="red",
        )
        return 1
    try:
        name = store_keyring_token(value, backend=backend)
    except CrewScopeKeyringError as exc:
        console.print(escape(f"Not stored: {exc}."), style="red")
        return 1
    console.print(escape(f"Stored the crew-scope token in the OS keyring ({name}). {_RESTART}"))
    if configured_crew_scope_token(config):
        console.print(escape(
            f"auth.crew_scope_token is still set in {config_path}: delete that line (ProbOS never edits the file). "
            "While the keyring holds a token, the file's is not used."
        ))
    console.print("HXI panels must send this token: while any token is set, a panel that sends none answers 401.")
    return 0


def _clear(current: KeyringRead, config: Any, config_path: Path, console: Console, backend: Any) -> int:
    if current.source is CrewScopeSource.NO_SECURE_BACKEND:
        console.print("This host has no secure OS keyring, so no keyring token exists to clear.")
        return 0
    try:
        removed = clear_keyring_token(backend=backend)
    except CrewScopeKeyringError as exc:
        console.print(escape(f"Not cleared: {exc}."), style="red")
        return 1
    if not removed:
        console.print("The OS keyring held no crew-scope token; nothing was cleared.")
        return 0
    if configured_crew_scope_token(config):
        after = f"the vessel reads auth.crew_scope_token from {config_path}"
    else:
        after = "the Captain-only routes answer 403 and the other API routes take no token, until a token is set again"
    console.print(escape(f"Cleared the crew-scope token from the OS keyring. {_RESTART} After the restart, {after}."))
    vault = file_vault_entries(config)
    if vault is not None and vault[1] != 0:
        console.print(escape(
            f"The browser file vault {vault[0]} {_vault_note(vault[1])}, encrypted under the cleared token; "
            "set that token again to read them."
        ))
    return 0


def run(
    command: str,
    *,
    config_path: Path,
    console: Console,
    use_stdin: bool = False,
    read_secret: Callable[[str], str] = getpass.getpass,
    stdin: TextIO | None = None,
    stdin_is_tty: Callable[[], bool] | None = None,
    backend: Any | None = None,
) -> int:
    """``probos crew-token <command>``: 0 done, 1 refused, 2 usage or an unreadable config."""
    config = _load(config_path, console)
    if config is None:
        return 2
    current = read_keyring_token(backend)
    if command == "status":
        return _status(current, config, config_path, console)
    if command == "clear":
        return _clear(current, config, config_path, console, backend)
    if command not in ("set", "rotate"):
        console.print(escape(f"Unknown crew-token command: {command}"), style="red")
        return 2
    source = sys.stdin if stdin is None else stdin
    is_tty = source.isatty if stdin_is_tty is None else stdin_is_tty
    return _set(
        command, current, config, config_path, console, backend,
        use_stdin=use_stdin, stdin=source, stdin_is_tty=is_tty, read_secret=read_secret,
    )
```

### 5.15 `src/probos/__main__.py`: the subcommand

SEARCH:
```python
    # soft_wrap: a path or URL is never hard-wrapped mid-string, as in setup (AD-1135 B4).
    return asyncio.run(run_doctor(args, Console(soft_wrap=True), ctx=ctx))


def _cmd_pairing(args: argparse.Namespace) -> int:
```
REPLACE:
```python
    # soft_wrap: a path or URL is never hard-wrapped mid-string, as in setup (AD-1135 B4).
    return asyncio.run(run_doctor(args, Console(soft_wrap=True), ctx=ctx))


def _cmd_crew_token(args: argparse.Namespace) -> int:
    """BF-908: ``probos crew-token set|rotate|clear|status``, the Captain's keyring action.

    Reads the config ``probos`` and ``probos serve`` would load (``--config`` before or
    after ``crew-token``, else ``_resolve_config_path``), as ``probos doctor`` does. The
    work is in ``probos/crew_token_cli.py``; only this module imports it.
    """
    from probos import crew_token_cli

    return crew_token_cli.run(
        args.crew_token_cmd,
        config_path=_resolve_config_path(getattr(args, "config", None)),
        use_stdin=bool(getattr(args, "stdin", False)),
        console=Console(soft_wrap=True),
    )


def _cmd_pairing(args: argparse.Namespace) -> int:
```

SEARCH:
```python
    channel_mx_setup.add_argument(
        "--password",
        type=str,
        default=None,
        help="Password (skips interactive prompt; prefer the prompt to avoid shell history)",
    )

    # --- probos migrate (AD-808) ---
```
REPLACE:
```python
    channel_mx_setup.add_argument(
        "--password",
        type=str,
        default=None,
        help="Password (skips interactive prompt; prefer the prompt to avoid shell history)",
    )

    # --- probos crew-token (BF-908) ---
    crew_token_parser = subparsers.add_parser(
        "crew-token",
        help="Set, rotate, clear or show the crew-scope token in the OS keyring (BF-908; the Captain's action)",
    )
    # SUPPRESS as for doctor: a --config given before `crew-token` (the root parser's) is kept.
    crew_token_parser.add_argument(
        "--config", "-c", type=Path, metavar="PATH", default=argparse.SUPPRESS,
        help="The config file the vessel loads (default: the one probos loads)",
    )
    crew_token_sub = crew_token_parser.add_subparsers(dest="crew_token_cmd", required=True)
    for _verb, _verb_help in (
        ("set", "Store a token in the OS keyring (prompted twice, never shown)"),
        ("rotate", "Replace the token the OS keyring holds"),
    ):
        _verb_parser = crew_token_sub.add_parser(_verb, help=_verb_help)
        _verb_parser.add_argument(
            "--stdin", action="store_true",
            help="Read the token from one line of standard input; it is never taken from the command line",
        )
    crew_token_sub.add_parser("clear", help="Delete the token from the OS keyring (never refused)")
    crew_token_sub.add_parser("status", help="Say where the token comes from, never its value")

    # --- probos migrate (AD-808) ---
```

SEARCH:
```python
    if args.command == "doctor":
        # AD-484: doctor returns non-zero exit code on failure
        import sys
        sys.exit(_cmd_doctor(args))
```
REPLACE:
```python
    if args.command == "doctor":
        # AD-484: doctor returns non-zero exit code on failure
        import sys
        sys.exit(_cmd_doctor(args))

    if args.command == "crew-token":  # BF-908
        import sys
        sys.exit(_cmd_crew_token(args))
```

### 5.16 New file: `tests/test_bf908_crew_scope_token.py` (C1a tests)

Module docstring: what each section proves and does not (section 10). Imports from `tests.fixtures.crew_scope_keyring`. Every test that needs a keyring passes a duck; none touches the OS keyring. `asyncio_mode = "auto"` (`pyproject.toml:181`): plain `async def test_...`. Never assert on a token's absence by printing it: assert `TOKEN not in text`.

| ID | Test | Asserts |
|---|---|---|
| A1 | `test_the_suite_never_reaches_the_real_os_keyring` | `os.environ["PYTHON_KEYRING_BACKEND"] == "keyring.backends.fail.Keyring"`; `type(keyring.get_keyring()).__module__ == "keyring.backends.fail"`; `read_keyring_token().source is CrewScopeSource.NO_SECURE_BACKEND`; a child `subprocess.run([sys.executable, "-c", "import keyring; print(type(keyring.get_keyring()).__module__)"], env=dict(os.environ), capture_output=True, text=True, timeout=120)` prints `keyring.backends.fail` |
| B1 | `test_keyring_step_reads_a_stored_token` | `MemoryKeyring(token=KEYRING_TOKEN)` -> `KEYRING`, `.token == KEYRING_TOKEN`, `KEYRING_TOKEN not in repr(read)` |
| B2 | `test_keyring_step_an_empty_secure_keyring_is_absent` | `ABSENT`, `token == ""` |
| B3 | `test_keyring_step_a_host_without_a_secure_backend_has_none` | `InsecureKeyring(token=KEYRING_TOKEN)` -> `NO_SECURE_BACKEND` (the insecure backend is never read: token not returned) |
| B3b | `test_keyring_step_a_chain_uses_its_first_secure_member` | `ChainerBackend` whose `backends` property is patched (or a duck chainer subclass) to `[InsecureKeyring(token=FILE_TOKEN), MemoryKeyring(token=KEYRING_TOKEN)]` -> `KEYRING` and `KEYRING_TOKEN`; a chain of insecure members only -> `NO_SECURE_BACKEND`. Follow `tests/test_ad1196_did_key_binding.py:660-690` for building a chainer |
| B4 | `test_keyring_step_a_failing_secure_keyring_is_unavailable_never_absent` | `FailingKeyring()` -> `UNAVAILABLE`; `"RuntimeError" in read.reason`; `"keychain locked" not in read.reason` |
| B5 | `test_keyring_step_a_malformed_entry_is_unavailable` | `MemoryKeyring(token="short")` -> `UNAVAILABLE`, `token == ""` |
| B6 | `test_keyring_step_a_keyring_that_does_not_answer_is_unavailable` | `SilentKeyring()`, `await read_keyring_token_bounded(k, timeout_seconds=0.05)` -> `UNAVAILABLE`, "did not answer" in reason; `k.release.set()` in `finally` |
| B7 | `test_keyring_step_token_rule` (parametrized) | 15 chars refused, 16 accepted, a space refused, a tab refused, `"é"*16` refused, `None` refused |
| C1 | `test_accessor_prefers_the_keyring_then_the_config` | runtime `SimpleNamespace(config=SystemConfig(auth=AuthConfig(crew_scope_token=FILE_TOKEN)), credential_store=store)`; before `load`: `crew_scope_token(rt) == FILE_TOKEN`; after `load` with `MemoryKeyring(token=KEYRING_TOKEN)`: `KEYRING_TOKEN`; reloaded over an empty keyring: `FILE_TOKEN` |
| C2 | `test_accessor_a_test_double_reads_its_config_only` | no `credential_store` attribute -> config token; `credential_store=MagicMock()` -> config token; `runtime=None` -> `""`; config without `auth` -> `""` |
| C3 | `test_accessor_reads_the_runtime_s_current_config` | replace `runtime.config` with a new `SystemConfig` holding `ROTATED_TOKEN` after the store was built -> `ROTATED_TOKEN` |
| C4 | `test_accessor_a_locked_keyring_refuses_while_no_token_is_configured` | `FailingKeyring`, empty config -> `crew_scope_locked` True, token `""`; config with `FILE_TOKEN` -> locked False, token `FILE_TOKEN`; `NO_SECURE_BACKEND` with empty config -> locked False |
| C5 | `test_the_keyring_token_is_never_reachable_through_get_or_the_json_store` | store with `store_path=tmp_path/"secrets.json"`, loaded `KEYRING_TOKEN`; for every name in `[s["name"] for s in store.list_credentials()] + ["crew_scope", "crew_scope_token", "auth.crew_scope_token", CREW_SCOPE_KEYRING_SERVICE]`, departments `None` and `"engineering"`, tier enforcement off and on: `store.get(name, department=d) != KEYRING_TOKEN`; no listed name is a crew-scope name; `store.rotate("crew_scope_token", ROTATED_TOKEN)` leaves `store.crew_scope.token(cfg) == KEYRING_TOKEN`; the JSON file, if written, does not contain `KEYRING_TOKEN`; `KEYRING_TOKEN not in os.environ.values()` |
| D1 | `test_the_stop_routes_accept_the_keyring_token_and_refuse_without_it` | real `AgentStopService(data_dir=tmp_path/"stops")` started/stopped; app = `FastAPI()` + `agent_stop.router`, `app.state.runtime = SimpleNamespace(agent_stops=service, config=SystemConfig(), credential_store=store)` (pattern `tests/test_ad1343_agent_stop.py:200-207`, `httpx.ASGITransport`); keyring holds `KEYRING_TOKEN`: `GET /api/stops` Bearer `KEYRING_TOKEN` 200, wrong token 401, none 401, `FILE_TOKEN` 401. Empty keyring and empty config: 403 `agent_stop_requires_crew_scope_token`. `FailingKeyring` and empty config: 403 `crew_scope_token_unavailable` |
| D2 | `test_every_captain_only_gate_reads_the_one_accessor` | `identity._key_action_binding(runtime)` and `identity._peer_reset_exchange(runtime)` return the sentinel when the keyring holds the token and the config is empty, raise 403 otherwise (sentinels on `identity_key_binding` / `federation_identity_exchange`); `GET /api/federation/attachments/nothex` on `federation_attachments.router` with `SystemConfig(attachments=AttachmentsConfig(serve_remote_enabled=True))`: Bearer `KEYRING_TOKEN` -> 400 `invalid_content_hash` (past the token gate); empty keyring and config -> 403 `remote_serving_requires_token` |
| D3 | `test_websockets_refuse_every_caller_while_locked` | duck socket (`query_params` dict, `async close(code, reason)` records): locked -> `verify_ws_token` False and closed with 1008, for no token and for any token; keyring token presented -> True; nothing configured, keyring absent -> True (unchanged default) |
| D4 | `test_a_settings_save_never_writes_the_keyring_token_into_the_config_file` | `routers.config.router` app over `SimpleNamespace(config=SystemConfig(), config_path=str(tmp_path/"system.yaml"), credential_store=store, _start_time=0.0)` (file written as `yaml.safe_dump({})`); GET `/api/config` Bearer `KEYRING_TOKEN` -> csrf; POST `{"patch": {"system": {"log_level": "DEBUG"}}}` with Bearer and `X-Probos-CSRF` -> 200 (pattern `tests/test_ad741_config_api.py:84-102`); `KEYRING_TOKEN not in` the file text; `yaml.safe_load(file)["auth"]["crew_scope_token"] == ""` |
| D5 | `test_an_ordinary_crew_scope_route_refuses_while_locked` | `await require_crew_scope(Request({"type": "http", "query_string": b"", "headers": []}), authorization=None, runtime=rt)`: locked -> `HTTPException` 403 `crew_scope_token_unavailable`; keyring token as `authorization="Bearer ..."` -> returns None; nothing configured -> returns None (today's pass-through, unchanged) |
| D6 | `test_the_browser_actor_basis_follows_the_keyring_token` | `await require_browser_actor(runtime=rt, crew_scope=None)`: keyring token -> `actor.authority_basis is BrowserAuthorityBasis.SHARED_CREW_SCOPE`; nothing -> `SINGLE_OPERATOR_COMPATIBILITY` |
| E1 | `test_a_token_only_in_the_config_file_keeps_working_with_the_warning` (golden) | `tmp_path/"system.yaml"` = `yaml.safe_dump({"auth": {"crew_scope_token": FILE_TOKEN}})`; `cfg = load_config(path)`; snapshot the bytes; `loaded_store(cfg, MemoryKeyring(), config_path=str(path))` under `caplog` WARNING (logger `probos.security.crew_scope`): exactly one WARNING, containing `str(path)`, `auth.crew_scope_token` and `probos crew-token set`; `FILE_TOKEN not in caplog.text`; the stop list route answers 200 to Bearer `FILE_TOKEN`; the file's bytes are unchanged |
| E2 | `test_a_token_in_both_uses_the_keyring_s_and_names_the_file_s_as_unused` | WARNING contains "is not used"; accessor -> `KEYRING_TOKEN`; Bearer `FILE_TOKEN` -> 401; neither value in `caplog.text` |
| E3 | `test_a_locked_keyring_is_logged_as_an_error_without_a_value` | `FailingKeyring`, empty config: one ERROR containing `crew_scope_token_unavailable`; "keychain locked" not in `caplog.text` |
| E4 | `test_startup_reads_the_keyring_once_before_anything_reads_the_token` | `src = inspect.getsource(ProbOSRuntime.start)`; `src.count("crew_scope.load(") == 1`; `src.index("await self.agent_stops.start()") < src.index("await self.credential_store.crew_scope.load(config=self.config, config_path=self.config_path)") < src.index("await init_nats(") < src.index("finalize_startup(")` |
| F1 | `test_doctor_says_where_the_token_comes_from` (parametrized) | `_CrewScopeCheck(backend=...)` over `DoctorContext(config=load_config(path), home_dir=tmp_path, data_dir=tmp_path, config_path=path)`: keyring only -> OK; file only -> WARN, message has `str(path)` and `auth.crew_scope_token`, remediation has `probos crew-token set` and `401`; both -> WARN "is not used"; neither -> OK "not set"; `FailingKeyring` + no file token -> FAIL; `InsecureKeyring` + file token -> WARN "no secure OS keyring". No token value in any message or remediation |
| F2 | `test_doctor_check_is_registered_once` | `from probos.doctor import checks`; `[c.name for c in iter_checks()].count("crew_scope_token") == 1` |
| F3 | `test_doctor_check_skips_without_a_config` | `config=None` -> WARN "skipped" |
| G1 | `test_cli_set_stores_a_prompted_token_and_never_prints_it` | `crew_token_cli.run("set", config_path=path, console=Console(file=io.StringIO(), width=300, color_system=None), read_secret=lambda _: KEYRING_TOKEN, stdin_is_tty=lambda: True, backend=mem)` -> 0; `mem.entries[ENTRY] == KEYRING_TOKEN`; output lacks the token and contains "Restart the vessel" and "401" |
| G2 | `test_cli_set_refuses` (parametrized) | entries differ -> 1; 15-character token -> 1; keyring already holds one (`set`) -> 1 and says `rotate`; `InsecureKeyring` -> 1; `FailingKeyring` -> 1. Each: `mem.entries` unchanged, no token in output |
| G3 | `test_cli_reads_standard_input_only_with_the_flag` | `stdin_is_tty=lambda: False` without `use_stdin` -> 2 and a `read_secret` that raises `AssertionError` is never called; `use_stdin=True, stdin=io.StringIO(KEYRING_TOKEN + "\n")` -> 0 and stored |
| G4 | `test_cli_refuses_a_new_token_while_the_file_vault_holds_entries` | config with `browser_tool.credential_vault` `enabled: true`, `backend: file`, `file_path: <tmp>/vault.json` holding `{"refs": {"r1": {}}}`; keyring holds `KEYRING_TOKEN`: `rotate` to `ROTATED_TOKEN` -> 1, entry still `KEYRING_TOKEN`; `rotate` to `KEYRING_TOKEN` -> 0. Keyring empty, file token `FILE_TOKEN`: `set` `FILE_TOKEN` (moving it) -> 0; unreadable vault file (`"{"`) and a different token -> 1 |
| G5 | `test_cli_clear_removes_the_entry_and_is_never_refused_for_the_vault` | vault with entries, keyring holds the token -> 0, entry gone, output names the vault; again -> 0 "held no"; `InsecureKeyring` -> 0 |
| G6 | `test_cli_status_never_prints_the_token` | keyring and file tokens set -> 0; neither value in output; "is not used" in output |
| G7 | `test_a_keyring_that_does_not_keep_the_token_is_reported` | `ForgetfulKeyring` -> `set` 1, output "did not keep" |
| G8 | `test_the_cli_takes_no_token_on_the_command_line` (real child) | `env = {**os.environ, "PYTHONPATH": str(src_dir)}` (pattern `tests/test_bf906_doctor_check.py:336-344`), `cwd=tmp_path`, `--config` a tmp file always (never the Captain's config): `[sys.executable, "-m", "probos", "--config", str(cfg), "crew-token", "set", KEYRING_TOKEN]` -> returncode 2 (argparse refuses the extra argument); `[..., "crew-token", "set", "--stdin"]` with `input=KEYRING_TOKEN + "\n"` -> returncode 1 and "no secure OS keyring" in stdout (the fail backend is inherited), token not in stdout or stderr |
| H1 | `test_no_module_reads_the_token_setting_directly` | AST scan of every `src/probos/**/*.py`: any `ast.Attribute` with `attr == "crew_scope_token"` or `ast.Constant` equal to `"crew_scope_token"` outside `probos/security/crew_scope.py` fails, naming file and line; in the owner exactly one such `ast.Attribute` (the read in `configured_crew_scope_token`); the scan visited more than 500 files |
| H2 | `test_only_the_captain_s_cli_writes_the_keyring_entry` | AST: the set of modules calling `store_keyring_token` or `clear_keyring_token` (as `Name` or `Attribute`), other than the defining module, `== {"probos.crew_token_cli"}`; modules importing `probos.crew_token_cli` (`import probos.crew_token_cli`, `from probos import crew_token_cli`, `from probos.crew_token_cli import ...`) `== {"probos.__main__"}`; modules importing `probos.security.crew_scope` `== {"probos.credential_store", "probos.crew_token_cli", "probos.doctor.checks.crew_scope_check"}` (exact, so a router, tool, federation or MCP importer fails) |
| I1 | `test_the_file_vault_is_keyed_from_the_keyring_token` | `pytest.importorskip("playwright.async_api")`; `cfg = SystemConfig()`, `browser_tool.enabled = True`, `credential_vault.enabled = True`, `file_path = str(tmp_path/"vault.json")`; premise `cfg.auth.crew_scope_token == ""`; runtime `SimpleNamespace(tool_registry=ToolRegistry(), audit_log=None, emit_event=None, config=cfg, credential_store=<loaded KEYRING_TOKEN>)` (pattern `tests/test_bf753_browser_wiring_keeps_the_workbench.py:55-64`); `_wire_browser_tool(runtime=runtime, config=cfg)`; `isinstance(runtime.credential_vault, EncryptedFileCredentialVault)` |

### 5.17 Guard-test helper code (H1, H2), to copy

```python
_SRC = Path(probos.__file__).resolve().parent


def _modules() -> Iterator[tuple[str, ast.Module]]:
    for path in sorted(_SRC.rglob("*.py")):
        rel = path.relative_to(_SRC.parent).with_suffix("")
        name = ".".join(rel.parts)
        yield name, ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imports(tree: ast.Module) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return found
```

---

## 6. Slice C1b

### 6.1 `src/probos/security/file_access.py`: the config files join the floor

SEARCH:
```python
# Mirrors ``ExecutionConfig.workspace_root``. A literal, not an import, so this
# guard works for a reader that has no runtime and no config at all.
_DEFAULT_WORKSPACE_ROOT = "data/execution/workspaces"
```
REPLACE:
```python
# Mirrors ``ExecutionConfig.workspace_root``. A literal, not an import, so this
# guard works for a reader that has no runtime and no config at all.
_DEFAULT_WORKSPACE_ROOT = "data/execution/workspaces"

# BF-908: the checkout's config file, mirroring ``__main__._repo_default_config_path``
# (``src/probos/security/file_access.py`` -> ``parents[3]`` is the checkout). A literal
# for the same reason: a reader with no runtime must still refuse it.
_REPO_DEFAULT_CONFIG = Path(__file__).resolve().parents[3] / "config" / "system.yaml"
```

SEARCH:
```python
        if exempt is None or _depth(exempt) <= _depth(protect):
            raise FileAccessDenied(
                raw, "path is inside the runtime's protected data directory"
            )
```
REPLACE:
```python
        if exempt is None or _depth(exempt) <= _depth(protect):
            raise FileAccessDenied(
                raw, "path is protected: the runtime's data directory or a config file"
            )
```

SEARCH:
```python
def protected_read_roots(runtime: Any) -> list[Path]:
    """The floor: the runtime data directory (vault, governance databases).

    Falls back to the platform data dir for the same reason as above -- the
    readers that need this most have no runtime.
    """
    data_dir = getattr(runtime, "data_dir", None)
```
REPLACE:
```python
def protected_read_roots(runtime: Any) -> list[Path]:
    """The floor: the runtime data directory (vault, governance databases) and the config files.

    Falls back to the platform data dir for the same reason as above -- the
    readers that need this most have no runtime.

    BF-908: plus every config file that can hold ``auth.crew_scope_token``
    (:func:`protected_config_files`). A file root matches that file only.
    """
    return _protected_data_dir(runtime) + protected_config_files(runtime)


def protected_config_files(runtime: Any) -> list[Path]:
    """BF-908: the config files the floor refuses, resolved, whether or not they exist.

    The file the vessel loaded (``runtime.config_path``: ``--config``,
    ``~/.probos/config.yaml`` or the checkout's ``config/system.yaml``) and both
    defaults, since either can hold ``auth.crew_scope_token`` whichever was loaded.
    Paths, not leaf names: ``config.yaml`` is too common a name to refuse everywhere.
    Not covered: a copy or hard link of the file under another path, and every
    reader that does not call this floor (a shell command, ``run_python``).
    """
    candidates: list[object] = [getattr(runtime, "config_path", None), _REPO_DEFAULT_CONFIG]
    try:
        candidates.append(Path.home() / ".probos" / "config.yaml")
    except (RuntimeError, OSError):
        pass
    files: list[Path] = []
    for candidate in candidates:
        if not isinstance(candidate, (str, Path)) or not str(candidate):
            continue
        try:
            files.append(Path(candidate).resolve())
        except (OSError, RuntimeError, ValueError):
            continue
    return files


def _protected_data_dir(runtime: Any) -> list[Path]:
    data_dir = getattr(runtime, "data_dir", None)
```
(The rest of the old body, from `if data_dir is None:` to `return []`, stays unchanged as `_protected_data_dir`'s body.)

### 6.2 `src/probos/agents/code_search.py`: every match is re-checked against the floor

SEARCH:
```python
        # Prefer the operator's ripgrep binary; fall back to pure Python.
        rg = _resolve_rg_binary()
        if rg is not None:
            rg_result = await self._search_rg(rg, plan, root)
            if rg_result is not None:
                return rg_result
            # Tier-2: rg failed -> fall through to the Python engine.
        return self._search_python(plan, root)
```
REPLACE:
```python
        # Prefer the operator's ripgrep binary; fall back to pure Python.
        rg = _resolve_rg_binary()
        if rg is not None:
            rg_result = await self._search_rg(rg, plan, root)
            if rg_result is not None:
                return _within_floor(rg_result, getattr(self, "_runtime", None))
            # Tier-2: rg failed -> fall through to the Python engine.
        return _within_floor(self._search_python(plan, root), getattr(self, "_runtime", None))
```

SEARCH:
```python
        return {
            "success": True,
            "data": matches,
            "count": len(matches),
            "engine": "python",
            "truncated": truncated,
        }


def _install_root() -> Path:
```
REPLACE:
```python
        return {
            "success": True,
            "data": matches,
            "count": len(matches),
            "engine": "python",
            "truncated": truncated,
        }


def _within_floor(result: dict, runtime: Any) -> dict:
    """BF-908: drop every match in a file the read floor refuses.

    The root check in ``act`` admits a directory; both engines then read every file
    under it, so a root holding a protected file (the checkout holding
    ``config/system.yaml``, or a folder above the data directory) returned that
    file's matching lines. Each match is re-checked against the same floor.
    """
    from probos.security.file_access import FileAccessDenied, resolve_for_runtime

    matches = result.get("data")
    if not result.get("success") or not isinstance(matches, list):
        return result
    kept: list[Any] = []
    for match in matches:
        try:
            resolve_for_runtime(str(match.get("path", "")) if isinstance(match, dict) else "", runtime)
        except FileAccessDenied:
            continue
        kept.append(match)
    if len(kept) == len(matches):
        return result
    logger.info("BF-908: content search dropped %d match(es) in files the read floor refuses", len(matches) - len(kept))
    return {**result, "data": kept, "count": len(kept)}


def _install_root() -> Path:
```

### 6.3 New file: `tests/test_bf908_floor_and_children.py` (C1b tests)

Module docstring states, per test, what it proves and what it does not (section 10). Child commands and scripts are module constants in `_CHILD_COMMANDS`; none mentions `keyring` (K5).

| ID | Test | Asserts |
|---|---|---|
| J1 | `test_the_loaded_config_file_is_on_the_floor` | runtime `SimpleNamespace(data_dir=tmp_path/"data", config_path=str(cfg), config=SimpleNamespace(execution=SimpleNamespace(workspace_root=str(tmp_path/"data"/"execution"/"workspaces")), security_infra=SimpleNamespace(read_roots=[])))`; `resolve_for_runtime(str(cfg), rt)` raises `FileAccessDenied`; a sibling `notes.txt` in the same directory resolves; `cfg.resolve() in protected_config_files(rt)` |
| J2 | `test_both_default_config_files_are_on_the_floor_without_a_runtime` | `file_access._REPO_DEFAULT_CONFIG == probos.__main__._repo_default_config_path()` (unpatched); `protected_config_files(None)` contains `_REPO_DEFAULT_CONFIG.resolve()` and `(Path.home()/".probos"/"config.yaml").resolve()`; `protected_read_roots(None)` still starts with the platform data dir |
| J3 | `test_a_mock_runtime_adds_no_config_file` | `protected_config_files(MagicMock())` does not raise and holds only the two defaults |
| J4 | `test_every_floor_reader_refuses_the_config_file` | `await FileReaderAgent(agent_id="fr-1", runtime=rt)._read_file(str(cfg))` -> `success` False and `FILE_TOKEN not in str(result)`; `ReadFileTool(rt).resolve_source_path(str(cfg))` and `CodebaseReadSourceTool(rt).resolve_source_path(str(cfg))` raise `FileAccessDenied`; listing the directory (`DirectoryListAgent._list_directory`) still succeeds (names only) |
| J5 | `test_content_search_drops_matches_in_a_protected_file` (parametrized `python`, `rg`) | `python`: `monkeypatch.setattr(code_search, "_resolve_rg_binary", lambda: None)`; `rg`: skip when `code_search._resolve_rg_binary()` is None. Directory holds `system.yaml` (registered as `rt.config_path`, containing `FILE_TOKEN`) and `notes.txt` (containing `FILE_TOKEN`); `plan = await agent.decide({"params": {"path": str(d), "pattern": FILE_TOKEN}})`; `result = await agent.act(plan)`: success, the matched paths are exactly `[notes.txt]`, `count == 1` |
| J6 | `test_a_search_above_the_data_directory_drops_the_vault` | root `tmp_path` (above `tmp_path/"data"`), `data/credential_vault.json` and `notes.txt` hold a pattern: only `notes.txt` is returned, Python engine |
| J7 | `test_a_search_that_drops_nothing_returns_the_engine_s_result_unchanged` | no protected file under the root: `result` equals the engine's dict, `count` unchanged |
| K1 | `test_no_agent_command_child_sees_the_token` (variants `windows`, `posix` with the skipifs of `tests/test_bf890_command_env.py:494-512`) | store loaded with `MemoryKeyring(token=KEYRING_TOKEN)`; premise `KEYRING_TOKEN not in os.environ.values()`; `monkeypatch.setenv("PROBOS_CREW_SCOPE_TOKEN", ENV_PROBE)`; premise: an inheriting child (`subprocess.run("set"` on Windows / `"env"` on POSIX`, shell=True, capture_output=True)`) sees `ENV_PROBE`; `RunCommandTool(_FakeRuntime()).invoke({"command": "set"|"env", "timeout": 30})` and `ShellCommandAgent().handle_intent(IntentMessage(intent="run_command", params={"command": <PowerShell env dump>|"env"}))`: exit 0, and neither `ENV_PROBE` nor `KEYRING_TOKEN` in stdout. PowerShell dump: `Get-ChildItem Env: \| ForEach-Object { $_.Name + '=' + $_.Value }` |
| K2 | `test_a_run_python_child_sees_no_token_in_its_environment` | `SubprocessSandbox(scratch_root=str(tmp_path/"scratch")).run(ExecutionRequest(code="import json, os\nprint(json.dumps(sorted(os.environ.items())))"))` -> success; `PATH` among the names (premise: it printed its environment); neither `ENV_PROBE` nor `KEYRING_TOKEN` in stdout |
| K3 | `test_an_environment_variable_would_reach_every_trusted_launch` (D6's evidence) | with `ENV_PROBE` planted: `ENV_PROBE in trusted_command_env().values()` (why no env-var source exists); `ENV_PROBE not in build_command_env().values()` and `not in {**build_command_env(), "PYTHONPATH": "x"}.values()` (the builder's pytest env shape, `cognitive/builder.py:2827`); with the store loaded, `KEYRING_TOKEN` in neither |
| K4 | `test_a_shell_command_can_still_read_a_token_left_in_the_config_file` (residual R2, pinned) | `cfg` holds `FILE_TOKEN`; `RunCommandTool(_FakeRuntime()).invoke({"command": f'type "{cfg}"'` (Windows) / `f"cat '{cfg}'"` (POSIX)`, ...})` -> `FILE_TOKEN in stdout`. Docstring: this pins a limitation, as `tests/test_bf758_file_read_confinement.py:433-450` does; it fails only when OS-level isolation (AD-995) closes it, and then the docstring goes with it |
| K5 | `test_no_child_script_here_imports_keyring` | `all("keyring" not in command for command in _CHILD_COMMANDS)` |

Synthetic values (add to the fixture module or this file): `ENV_PROBE = "bf908-env-probe-value-c19"`. `_FakeRuntime` as `tests/test_bf890_command_env.py:83-84`.

### 6.4 `DECISIONS.md`

SEARCH:
```markdown
- *Reversal.* Revert the BF-909 commit. Nothing persisted is touched.

### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```
REPLACE:
```markdown
- *Reversal.* Revert the BF-909 commit. Nothing persisted is touched.

### BF-908 -- The crew-scope token resolves through the credential store, OS keyring first, behind one accessor; the config files join the read floor (2026-10-20, #1605)

The Captain's crew-scope token sat in plain text in the config file, outside the BF-758 floor, and eleven reads in six modules took it from the config directly. The Captain's decision (#1595, comment 6281405184) set five requirements; the contract is `prompts/bf-908-crew-scope-token-credential-store.md`.

- *D1 (one accessor).* `credential_store.crew_scope_token(runtime)` and `crew_scope_locked(runtime)` are the only reads; `probos/security/crew_scope.py` holds the keyring step and the one read of the setting. A structural test fails on any other read. The accessor reads `runtime.config` live, so test doubles and the HXI test helper that set the setting keep working.
- *D2 (the keyring step).* One entry, `probos.crew_scope` / `crew_scope_token`, read once at startup (Phase 1a) through AD-1196's secure-backend rule (`identity_key_store.secure_keyring_backend`), not `CredentialEncryptor`, whose `retrieve` turns a failure into "no credential". Not a `CredentialSpec` and never in the JSON store, so no `get()` caller reaches it.
- *D3 (fail closed).* A secure keyring that fails, does not answer within 10 s or holds a malformed entry, with no token in the config, makes every crew-scope route answer 403 `crew_scope_token_unavailable`. A host with no secure backend has no keyring step and behaves as before.
- *D4 (no environment variable).* `trusted_command_env()` passes the whole environment to 17 modules, an operator-approved MCP server among them.
- *D5 (the config file).* A token found only there keeps working; startup and `probos doctor` warn, naming the file and the setting, never the value. Nothing writes, moves or deletes it.
- *D6 (when it takes effect).* At the next start. `probos crew-token set|rotate|clear|status` is the Captain's CLI; the token comes from a no-echo prompt or `--stdin`, never the command line. No HXI panel: while no token is set the API is open, so a route that sets one could be used by an agent's shell to lock the Captain out. A change is refused while the browser file vault holds entries under the token in use; `clear` never is.
- *D7 (the floor).* The loaded config file, `config/system.yaml` and `~/.probos/config.yaml` are on `protected_read_roots`; content search re-checks every match, which also closes a search rooted above the data directory.
- *Residual, accepted.* Any process running as the vessel's user, agents' shell commands and `run_python` included, can read and write the keyring entry and could run `probos crew-token`; while the token is still in a config file, a shell command can read that file (pinned by a test). A copy of the file elsewhere is not on the floor. A secure keyring missing at a boot reads as "no keyring": the Captain-only routes stay closed, the others are open as on any vessel without a token. A change takes effect only at a restart.
- *Tests.* No test reaches the real keyring: `tests/conftest.py` forces `PYTHON_KEYRING_BACKEND=keyring.backends.fail.Keyring`; tests inject in-memory backends.
- *Reversal.* Revert the BF-908 commits. A token stored in the keyring stays there and is ignored; put it back in the config file before reverting, or HXI and the stop routes lose it.

### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```

### 6.5 `PROGRESS.md`

SEARCH:
```markdown
# ProbOS Progress

**BF-909 (2026-10-20), #1607 -- 
```
REPLACE:
```markdown
# ProbOS Progress

**BF-908 (2026-10-20), #1605 -- the Captain's crew-scope token now resolves through the credential store, from the OS keyring first, behind one accessor, and the config files are on the file-read floor, so a crew agent's file tools can no longer read the token and a token moved to the keyring is in no file and no child's environment.** Eleven reads in six modules took `auth.crew_scope_token` from the config, which any process running as the Captain's user can read. `credential_store.crew_scope_token(runtime)` is now the only read (a structural test pins it): the keyring's entry, read once at startup through AD-1196's secure-backend rule, else the config's. A keyring that cannot be read refuses every caller instead of opening the routes. A token still in the config file keeps working, and startup and `probos doctor` warn, naming the file and the setting, never the value. `probos crew-token set|rotate|clear|status` is the Captain's own action; no route, crew tool or MCP server reaches it. Content search now drops matches in files the floor refuses. Residual (DECISIONS.md, BF-908): any same-user process can still read the keyring entry, and the file while the token stays there.

**BF-909 (2026-10-20), #1607 -- 
```

No `docs/development/roadmap.md` row (the Bug Tracker lists only bugs deliberately not fixed; DECISIONS.md BF-906 D12). The AD/BF ledger is derived from the commit subjects, which start `BF-908:`.

---

## 7. What this does NOT change

- `config/system.yaml`, `~/.probos/config.yaml` or any config file: never written, moved or rewritten by this change. `POST /api/config` keeps rewriting the loaded file from the in-memory config, as before; the in-memory config never holds the keyring's token (test D4).
- `AuthConfig`, every config model, `docs/development/config-facade-baseline.yaml`, the generated config reference.
- `require_crew_scope`'s behaviour with a token or with none (401 for a missing or wrong token; pass-through with none); only the new unavailable state is added.
- HXI: no panel; the UI sends the token as today.
- The browser vault's format and KEK derivation (`tools/browser/credentials.py:107-122`); the keychain backend (AD-1016).
- `CredentialStore.get`, `rotate`, `available`, `list_credentials`, the JSON store, the built-in specs.
- `ReadFileTool.description` and its two goldens.
- The MCP inbound token (`federation/mcp_server.py`, BF-875/876): a separate credential.
- `run_python`, the shell agent, `run_command` and their env builders (`execution/command_env.py`, `execution/isolation.py`).
- Federation: peers never hold this token (AD-1198), unchanged.

## 8. Focused checks (per slice; the broad gate runs once, by the orchestrator)

Interpreter: `d:/ProbOS/.venv/Scripts/pytest.exe`, `-n 0` for each focused check.

### 8.1 C1a

- `tests/test_bf908_crew_scope_token.py`
- Keyring users, because of the conftest change: `tests/test_ad1016_keyring_backend.py tests/test_credential_encryptor.py tests/test_m365_token_manager.py tests/test_m365_security_baseline.py tests/test_ad1196_identity_keys_api.py tests/test_ad1196_did_key_binding.py tests/test_ad1197_envelope_wiring.py tests/test_ad1197_signed_envelopes.py tests/test_ad1198_a2a_peer_gate.py tests/test_ad1198_a2a_peer_identity.py tests/test_ad1198_admission_wiring.py tests/test_ad1198_cluster_gate.py tests/test_ad1198_fork_recovery_gate.py tests/test_ad1198_fork_resolution.py tests/test_ad1198_identity_gate.py tests/test_ad1198_identity_continuity.py tests/test_ad1198_peer_admission.py tests/test_ad1198_peer_http_routes.py tests/test_ad1198_peer_http_gate.py tests/test_ad1198_peer_requests.py tests/test_ad1198_peer_reset.py tests/test_ad1198_peer_reset_gate.py tests/test_ad1198_transfer_recheck.py tests/test_bf885_identity_db_units.py`
- Token readers and route owners: `tests/test_ad722b_1_crew_scope_auth.py tests/test_ad1343_agent_stop.py tests/test_ad1343_stop_crossing.py tests/test_ad1343_stop_seam_inventory.py tests/test_ad1340_s2a_lookup_route.py tests/test_ad1340_s2b_restore_route.py tests/test_ad731a_remote_attachment.py tests/test_ad706a_browser_streaming.py tests/test_ad706f_credential_vault.py tests/test_ad1052a_browser_sessions.py tests/test_ad1052b_browser_bridge.py tests/test_ad1052c_browser_input_forward.py tests/test_ad1161_captain_session.py tests/test_ad1207_fault_visibility.py tests/test_ad1128_crew_session_ingress_dedup.py tests/test_ad1133_live_crew_session_refresh.py tests/test_hxi_chat_integration.py tests/test_distribution.py tests/test_browser_session_lifecycle.py tests/test_bf753_browser_wiring_keeps_the_workbench.py tests/test_ad741_config_api.py tests/test_ad741_secret_redaction.py tests/test_commands_status.py tests/test_bf890_command_env.py tests/test_bf892_spawn_env_guard.py`
- Startup and doctor: `tests/test_issue1419_failed_start_rollback.py tests/test_ad1195_eventlog_pair_freeze.py tests/test_ad801_doctor.py tests/test_ad1137_doctor.py tests/test_bf906_doctor_check.py tests/test_ad1328_s2a_startup_and_doctor.py tests/test_ad484_ux_adoption.py tests/test_standing_orders_layout.py`
- Scripts, each `--check`: `scripts/check_architecture_principles.py`, `scripts/check_seam_contracts.py`, `scripts/check_store_registry.py`, `scripts/check_config_facade.py`.

### 8.2 C1b

- `tests/test_bf908_floor_and_children.py tests/test_bf908_crew_scope_token.py`
- Floor and search: `tests/test_bf758_file_read_confinement.py tests/test_ad989_code_search.py tests/test_bf895_rg_line_parse.py tests/test_ad1200_repository_instructions.py tests/test_ad1200_instruction_file_access.py tests/test_ad1240_workspace_results.py tests/test_ad1240_workspace_result_lifecycle.py tests/test_ad1240_tool_result_delivery.py tests/test_bf890_command_env.py tests/test_bf892_spawn_env_guard.py tests/test_standing_orders_layout.py`
- `scripts/check_architecture_principles.py --check`.

Broad gate (orchestrator, once): `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label bf-908 --receipt logs/gates/bf-908.receipt.json`.

## 9. Mutation table (HIGH; WHOLE stripped lines, each unique in its file)

| # | File | Line (stripped, exact) | Mutate to | Killed by |
|---|---|---|---|---|
| 1 | `src/probos/security/crew_scope.py` | `if self._read.source is CrewScopeSource.KEYRING:` | `if False:` | C1, D1 |
| 2 | same | `return self._read.token` | `return configured_crew_scope_token(config)` | C1, D1, E2 |
| 3 | same | `return self._read.source is CrewScopeSource.UNAVAILABLE and not configured_crew_scope_token(config)` | `return False` | C4, D1, D3, D5 |
| 4 | same | `return KeyringRead(CrewScopeSource.UNAVAILABLE, backend=name, reason=f"the keyring failed ({type(exc).__name__})")` | `return KeyringRead(CrewScopeSource.ABSENT, backend=name)` | B4, C4 |
| 5 | same | `if refusal is not None:` | `if False:` | B5 |
| 6 | same | `return await asyncio.wait_for(asyncio.to_thread(read_keyring_token, backend), timeout=timeout_seconds)` | `return read_keyring_token(backend)` | B6 |
| 7 | same | `if any(not ("!" <= char <= "~") for char in value):` | `if False:` | B7 |
| 8 | same | `if not isinstance(stored, str) or not hmac.compare_digest(stored.encode("utf-8"), value.encode("utf-8")):` | `if False:` | G7 |
| 9 | same | `if source is CrewScopeSource.KEYRING and config_holds_token:` | `if False:` | E2, F1 (both) |
| 10 | same | `if not config_holds_token and source is CrewScopeSource.UNAVAILABLE:` | `if False:` | E3, F1 (FAIL) |
| 11 | `src/probos/identity_key_store.py` | `return _require_recommended(chosen)` | `return chosen` | B3 |
| 12 | same | `candidates = [b for b in chosen.backends if keyring.core.recommended(b)]` | `candidates = list(chosen.backends)` | B3b |
| 13 | `src/probos/credential_store.py` | `return store.crew_scope.token(config)` | `return configured_crew_scope_token(config)` | C1, D1 |
| 14 | same | `return isinstance(store, CredentialStore) and store.crew_scope.locked(getattr(runtime, "config", None))` | `return False` | C4, D5 |
| 15 | `src/probos/routers/auth.py` | `if crew_scope_locked(runtime):  # BF-908: fail closed, never pass-through` | `if False:` | D1 (detail), D5 |
| 16 | same | `if not expected and not locked:` | `if not expected:` | D3 |
| 17 | same | `if crew_scope_token(runtime)` | `if False` | D6 |
| 18 | `src/probos/routers/agent_stop.py` | `if not crew_scope_token(runtime):  # AD-1343: never a Captain order through an open gate (BF-908: one accessor)` | `if False:` | D1 (empty case) |
| 19 | `src/probos/routers/identity.py` | `if not crew_scope_token(runtime):` | `if False:` | D2 |
| 20 | `src/probos/routers/federation_attachments.py` | `if not crew_scope_token(runtime):` | `if False:` | D2 |
| 21 | `src/probos/startup/finalize.py` | `crew_token = crew_scope_token(runtime)  # BF-908: the keyring's token, else the config's` | `crew_token = ""` | I1 |
| 22 | `src/probos/runtime.py` | `await self.credential_store.crew_scope.load(config=self.config, config_path=self.config_path)` | delete the line | E4 |
| 23 | `src/probos/crew_token_cli.py` | `changes_key = not hmac.compare_digest(value.encode("utf-8"), in_use.encode("utf-8"))` | `changes_key = False` | G4 |
| 24 | same | `if changes_key and vault is not None and vault[1] != 0:` | `if False:` | G4 |
| 25 | same | `if not stdin_is_tty():` | `if False:` | G3 |
| 26 | same | `if command == "set" and current.source is CrewScopeSource.KEYRING:` | `if False:` | G2 (existing) |
| 27 | `src/probos/doctor/checks/crew_scope_check.py` | `return CheckResult(outcome=_OUTCOMES[posture.severity], message=posture.message, remediation=posture.remediation)` | `return CheckResult(outcome=CheckOutcome.OK, message=posture.message)` | F1 |
| 28 | `src/probos/security/file_access.py` | `return _protected_data_dir(runtime) + protected_config_files(runtime)` | `return _protected_data_dir(runtime)` | J1, J4 |
| 29 | same | `candidates: list[object] = [getattr(runtime, "config_path", None), _REPO_DEFAULT_CONFIG]` | `candidates: list[object] = [_REPO_DEFAULT_CONFIG]` | J1 |
| 30 | same | `if not isinstance(candidate, (str, Path)) or not str(candidate):` | `if not str(candidate):` | J3 |
| 31 | `src/probos/agents/code_search.py` | `return _within_floor(self._search_python(plan, root), getattr(self, "_runtime", None))` | `return self._search_python(plan, root)` | J5[python], J6 |
| 32 | same | `return _within_floor(rg_result, getattr(self, "_runtime", None))` | `return rg_result` | J5[rg] (skipped when no `rg`: record it as not run) |
| 33 | same | `kept.append(match)` | delete the line | J5, J7 |
| 34 | same | `if len(kept) == len(matches):` | `if True:` | J5 |

Equivalent mutants deliberately not listed: adding `locked or` to the socket refusal line (already refused by `not presented` / `compare_digest` with `expected == ""`); `return _require_recommended(candidates[0])` -> `return candidates[0]` (every candidate is already recommended). The campaign of record names the base tree and each file's sha256 (standing order: one campaign per candidate).

## 10. What each test proves, and what it does not (Q9)

| Test | Proves | Does not prove |
|---|---|---|
| A1 | This suite, and any child that inherits its environment, uses the fail backend; the keyring step finds no secure backend here. | Anything about a child built with `build_command_env` (it does not inherit the variable; K5 keeps such children away from `keyring`). |
| C5 | No name, department or tier makes `get()` return the token; `rotate()` cannot replace it; it is not in the JSON store or `os.environ`. | That in-process ProbOS code cannot call `runtime.credential_store.crew_scope.token(...)`; it can, as it can read any attribute. |
| D1-D6 | The routes and the socket check accept the keyring's token, refuse others, and fail closed while the keyring is unreadable. | Live HXI behaviour. |
| D4 | A Settings save writes the in-memory config, which never holds the keyring's token. | That a token already in the file is removed (it is not; requirement 2). |
| E1 | An existing deployment with the token in the file keeps working, with one warning naming the file, never the value, and the file is untouched. | Anything about other config files. |
| G8 | The CLI's real entry takes no token as an argument and reaches the keyring layer end to end (refused here by the fail backend). | Interactive `getpass` on a real terminal. |
| H1, H2 | No module but the owner reads the setting; only the CLI calls the writers; only three modules import the keyring module, and none is a router, tool, federation or MCP module. | That a same-user process cannot call `keyring` itself (residual R1). |
| J1-J7 | Every floor reader refuses the config files; content search drops their lines, and the vault's under an ancestor root. | Readers that do not call the floor: shell, `run_python` (residual R2/R3). |
| K1, K2 | The children `run_command`, the shell agent and `run_python` start see neither the keyring's token nor a token-shaped variable set in the vessel's environment. | That they cannot read the keyring or a file: they run as the same user (R1, R2). |
| K3 | A variable in the vessel's environment would reach every trusted launch (why D6 rejects one) and no agent-command env; the keyring's token is in neither. | |
| K4 | Pins residual R2: a shell command reads a token left in the config file. | |

## 11. Verified Against Codebase (2026-10-20, tree `2b97ca11`)

```
grep -n "crew_scope_token" src/probos (attribute reads, all)
  routers/auth.py:38:        return auth_cfg.crew_scope_token
  routers/agent_stop.py:54:  if not runtime.config.auth.crew_scope_token:  # AD-1343: never a Captain order through an open gate
  routers/identity.py:163:   if not runtime.config.auth.crew_scope_token:
  routers/identity.py:306:   if not runtime.config.auth.crew_scope_token:  # AD-1198 slice 2c the AD-1196 A-0 rule: no reset through an open gate
  routers/security.py:223:   if not runtime.config.auth.crew_scope_token:  # AD-1340 S2a: never serve archived episodes through an open gate
  routers/security.py:302:   if not runtime.config.auth.crew_scope_token:  # AD-1340 S2b: never restore through an open gate
  routers/federation_attachments.py:101:  if runtime.config.auth.crew_scope_token:
  routers/federation_attachments.py:110:  if not runtime.config.auth.crew_scope_token:
  routers/federation_attachments.py:158:  crew = getattr(getattr(runtime.config, "auth", None), "crew_scope_token", "") or ""
  startup/finalize.py:423:   BrowserAuthorityBasis.SHARED_CREW_SCOPE if config.auth.crew_scope_token
  startup/finalize.py:468:   crew_token = getattr(auth_cfg, "crew_scope_token", "") if auth_cfg else ""
  startup/finalize.py:501:   crew_scope_token=crew_token,
grep -n "class AuthConfig|crew_scope_token: str" src/probos/config.py
  2926: class AuthConfig(BaseModel):    2933: crew_scope_token: str = Field(
grep -n "def load_config" src/probos/config.py
  4103: def load_config(path: str | Path) -> SystemConfig:
grep -n "_repo_default_config_path|_resolve_config_path|config_path =" src/probos/__main__.py
  486: def _repo_default_config_path() -> Path:   492: def _resolve_config_path(config_path: Path | None) -> Path:
  639: runtime.config_path = str(resolved_path) if resolved_path else None
grep -n "self.config_path" src/probos/runtime.py
  1279: self.config_path: str | None = None
grep -n "agent_stops.start|init_nats|finalize_startup(" src/probos/runtime.py
  2770-2771: self.agent_stops = AgentStopService(...) / await self.agent_stops.start()
  2778: self.nats_bus = await init_nats(self.config)    3473: fin = await finalize_startup(runtime=self, config=self.config)
grep -n "credential_store" src/probos
  runtime.py:709 (constructed), finalize.py:3142 (repair dispatcher), finalize.py:4443-4468 (AD-456),
  experience/commands/commands_status.py:191-195 (list_credentials), cognitive/repair_issue.py:134-144 (get("github"))
grep -n "^    def " src/probos/credential_store.py   -> 15
grep -n "SRP_MAX_DIRECT_METHODS" scripts/check_architecture_principles.py
  188: SRP_MAX_DIRECT_METHODS = 15    568: if methods > SRP_MAX_DIRECT_METHODS:
grep -n "def retrieve|except Exception|return None" src/probos/security/credential_encryption.py
  25: def retrieve(...)   31: except Exception:   37: return None
grep -n "def _require_recommended|def _resolve_backend" src/probos/identity_key_store.py
  84: def _require_recommended(backend: Any) -> Any:   151: def _resolve_backend(self) -> Any:
grep -n "class KeyStoreUnavailable" src/probos/identity_keys.py
  99: class KeyStoreUnavailable(IdentityKeyUnavailable):
grep -n "def recommended|load_env|PYTHON_KEYRING_BACKEND" d:/ProbOS/.venv/Lib/site-packages/keyring/core.py
  85-86: def recommended(backend) -> bool: return backend.priority >= 1
  150-153: def load_env(): ... os.environ['PYTHON_KEYRING_BACKEND']   106-107: _detect_backend: load_env() or load_config() or ...
grep -n "priority" d:/ProbOS/.venv/Lib/site-packages/keyring/backends/fail.py
  18-19: def priority(cls) -> float: return 0
grep -n "PYTHON_KEYRING_BACKEND" tests/fixtures/federation_cluster.py
  159: PYTHON_KEYRING_BACKEND="keyring.backends.fail.Keyring",
grep -n "set_keyring" tests/test_ad1196_identity_keys_api.py
  57: monkeypatch.setattr(keyring, "set_keyring", _forbidden)
grep -n "def trusted_command_env|return dict(os.environ)|RUNTIME_NAME_PREFIX|CREDENTIAL_NAME_WORDS" src/probos/execution/command_env.py
  51-54: CREDENTIAL_NAME_WORDS = ("KEY", ...)   61: RUNTIME_NAME_PREFIX: str = "PROBOS_"   134: def trusted_command_env()   149: return dict(os.environ)
grep -n "trusted_command_env()" src/probos  (17 modules)
  agents/code_search.py:183, audio/tts/piper_backend.py:239, avatars/rhubarb_backend.py:179/255/392, avatars/blender_renderer.py:188,
  credential_store.py:361, episodic_health.py:399, execution/authority.py:781, doctor/checks/sandbox_check.py:25,
  cognitive/dm/artifact_extractor.py:202, __main__.py:254/463/3013/3019, worktree_manager.py:64,
  integrations/mcp_bridge/transport.py:274, knowledge/records_store.py:1243, knowledge/store.py:1233,
  security/container_sandbox.py:260, cognitive/referent_gate.py:471, cognitive/scout.py:412
grep -n "build_command_env(" src/probos  (agent-run paths)
  agents/shell_command.py:227/290, agents/red_team.py:324/423, cognitive/builder.py:1613/2827/2903/2978,
  cognitive/dependency_resolver.py:220, security/container_sandbox.py:171, cognitive/swe_harness/tools.py:1173/1241
grep -n "_ENV_PASSTHROUGH|def _build_env" src/probos/execution/isolation.py
  645: _ENV_PASSTHROUGH = SANDBOX_ENV_PASSTHROUGH   1042-1074: _build_env (allowlist + blackhole proxy)
grep -n "PROTECTED_LEAF_NAMES|def protected_read_roots|def resolve_for_runtime|protected data directory" src/probos/security/file_access.py
  61: PROTECTED_LEAF_NAMES = frozenset({   136: if resolved.name in PROTECTED_LEAF_NAMES:
  145: raw, "path is inside the runtime's protected data directory"   185: def protected_read_roots   218: def resolve_for_runtime
grep -n "resolve_for_runtime|protected_read_roots|read_verified_file|read_bounded_utf8" src/probos (the floor's readers)
  agents/code_search.py:143, agents/file_reader.py:108, agents/file_search.py:131, agents/directory_list.py:110,
  repository_instructions.py:62/262, cognitive/swe_harness/tools.py:328-332/439/745
grep -n "model_dump|_write_yaml_atomic(cfg_path|is_secret_field_id" src/probos/routers/config.py
  234: blocked = [p for p in patch_paths if is_secret_field_id(p)]   246: current = runtime.config.model_dump(mode="python")
  267: _write_yaml_atomic(cfg_path, new_cfg.model_dump(mode="json"))
grep -n "credential_vault|file_path" src/probos/config_models/integrations.py ; src/probos/config.py
  integrations.py:79 class CredentialVaultConfig, :91 backend "file", :100-101 file_path "data/credential_vault.json"
  config.py:3961: browser_tool: BrowserToolConfig   config.py:1530: credential_vault: CredentialVaultConfig
grep -n "def _derive_kek|def _save|crew_scope_token in config/system.yaml" src/probos/tools/browser/credentials.py
  107: def _derive_kek   152: "operator secret. Set auth.crew_scope_token in config/system.yaml "   184: def _save
grep -n "register_check|security_check|crew_enrollment_check" src/probos/doctor
  checks/__init__.py:18-19: crew_enrollment_check, security_check,   registry.py:21: def register_check
grep -n "class DoctorContext|config_path|config_target" src/probos/doctor/protocol.py
  37: class DoctorContext:   52: config_path: Path | None   53: config_target: Path | None = None
grep -n "def describe_load_failure" src/probos/doctor/runner.py
  87: def describe_load_failure(exc: Exception, path: Path) -> str:
grep -n "add_parser(\"doctor\"|args.command == \"doctor\"|def _cmd_doctor|# --- probos migrate" src/probos/__main__.py
  1853: def _cmd_doctor   3116: doctor_parser = subparsers.add_parser("doctor", ...)   3210: # --- probos migrate (AD-808) ---   3365: if args.command == "doctor":
grep -n "asyncio_mode|addopts" pyproject.toml
  181: asyncio_mode = "auto"   196: addopts = "-n 16 --dist=loadfile"
grep -n "keyring|playwright|requires-python" pyproject.toml
  9: requires-python = ">=3.12"   62: "keyring>=25.0"   119: "playwright>=1.50"
grep -n "data directory\" in description|data directory is not readable" tests/test_bf758_file_read_confinement.py tests/fixtures
  test_bf758...:428: assert "data directory" in description   fixtures/ad1179_tool_definition_golden.json, fixtures/ad1152_agentic_off_golden.json
grep -n "_DYNAMIC_SITES|CredentialStore._log_access" tests/test_ad1195_eventlog_pair_freeze.py
  121: _DYNAMIC_SITES   125: ('src/probos/credential_store.py', 'CredentialStore._log_access', "'credential'", "f'access:{name}'")
grep -n "inspect.getsource(ProbOSRuntime.start)|_startup_complete = True" tests/test_issue1419_failed_start_rollback.py
  161: source = inspect.getsource(ProbOSRuntime.start)   164: assert "self._startup_complete = True" in source
grep -n "extras.*verifier_independence" tests/test_bf906_doctor_check.py
  350: assert names[names.index("extras") + 1] == "verifier_independence"
grep -n "runtime = SimpleNamespace" ui/e2e/fixtures/ad1192_backend.py
  1371: runtime = SimpleNamespace(   1655: state.runtime.config.auth.crew_scope_token = token
```

### Absence Verified (2026-10-20)

```
CLAIM: no module, CLI verb, keyring service or doctor check named for this exists yet
RUN:   Grep "probos\.crew_scope|crew-token|crew_scope\.py|security\.crew_scope" over src, tests, scripts
FOUND: four test constants only ("ad1017-test-crew-token", "ad1017a-...", "wave168-test-crew-token", "bf745-test-crew-token")
HOLDS: yes

CLAIM: no seam, store or architecture baseline row names a symbol this removes (routers.auth._configured_token, KeyringKeyStore._resolve_backend's body)
RUN:   Grep "_configured_token|require_crew_scope|crew_scope|file_access|code_search|identity_key_store|_resolve_backend" docs/development/seams
FOUND: none; architecture-baseline.yaml names credential_store only at CredentialStore._log_access (unowned-task), untouched
HOLDS: yes

CLAIM: no test imports routers.auth._configured_token
RUN:   Grep "_configured_token" outside prompts/
FOUND: src/probos/routers/auth.py; test NAMES containing "configured_token" in six test files; docs/PROGRESS/DECISIONS prose
HOLDS: yes (no import)

CLAIM: no test pins the floor's refusal text, the vault-disabled warning or the vault RuntimeError text beyond "crew_scope_token"
RUN:   Grep "protected data directory|holds credentials and is not readable|vault disabled|is empty; vault|Set auth.crew_scope_token" tests/
FOUND: none (test_ad706f_credential_vault.py:72 matches "crew_scope_token", kept)
HOLDS: yes

CLAIM: no test or src calls keyring.set_keyring globally
RUN:   Grep "set_keyring" over src and tests
FOUND: only monkeypatches that FORBID it (test_ad1196_identity_keys_api.py:57, test_ad1196_did_key_binding.py:140)
HOLDS: yes

CLAIM: nothing in src writes the in-memory config to the loaded file except POST /api/config
RUN:   Grep "yaml\.(safe_)?dump\(|write_text\(.*yaml" src/probos
FOUND: routers/config.py:149/213 (the Settings writer and the scrubbed GET), __main__.py:2431/2503/2587 (channel setup writing its own payload), and unrelated stores
HOLDS: yes; none receives the keyring token (it never enters the config)
```

## 12. Prior Art and Blind Spots (review date 2026-10-20)

Internal: no study under `docs/research/` covers credential storage (Grep "keyring|bearer token|secret storage|credential storage", none). Prior decisions used: AD-1196 (`identity_key_store.py`, the secure-backend, fail-closed keyring rule, adopted as D3), AD-1137 (doctor names settings, never values; `describe_load_failure`, reused), BF-758 (the floor and its recorded limitations, extended), BF-890/892 (child environments, the evidence for D6).

External (three searches):
- GitHub CLI stores its token in the system credential store and, when none is found or it fails, falls back to a plain-text file, reported by `gh auth status` ([gh auth login manual](https://manpages.opensuse.org/Leap-15.6/gh/gh-auth-login.1.en.html); [Flox on the silent Linux fallback](https://flox.dev/blog/get-secure-github-cli-auth-you-can-take-with-you-anywhere); [glab adopting the same default](https://gitlab.com/gitlab-org/cli/-/merge_requests/3528)). **Adapted:** a status command that says where the token is (`probos crew-token status`). **Rejected:** the silent fallback; a failing keyring here is "unavailable" and fails closed, and nothing is ever written to a file.
- The `keyring` library selects a backend from `PYTHON_KEYRING_BACKEND` first, and documents a null backend for disabling it ([keyring docs](https://keyring.readthedocs.io/); [PyPI](https://pypi.org/project/keyring)). **Adopted** for test safety, with the fail backend the repo's federation cluster already uses.
- OS credential stores do not separate one user's processes: on Windows any process of the user can read and write that user's credentials ([Microsoft Q&A](https://learn.microsoft.com/en-us/answers/questions/881226/windows-credential-manager-permission-management)); an unlocked Secret Service is readable by other applications of the session ([java-keyring issue on CVE-2018-19358](https://github.com/HubSpot/java-keyring)). **Recorded** as residual R1; nothing here claims more.

Reference projects (`docs/research/reference-projects.md`, judged on 2026-10-20): none examined; credential storage is not the subject of any listed project. Considered, deferred: SWE-agent (last 2026-03-20, overdue), Cursor (2026-06-13, overdue). No row updates.

Blind spots found and settled: the Settings writer would persist an injected token (D2); `CredentialEncryptor` reads a failure as absence (D3); the AD-1270b method ceiling (D2); content search bypassed the floor below an admitted root, for the vault too (D10); children built by `build_command_env` drop `PYTHON_KEYRING_BACKEND`, so a test child must never import `keyring` (D15). Considered, deferred (one line each): `GET /api/config`'s `secret_present` reports the file only, so HXI Settings shows the token as unset once it lives in the keyring; the HXI's `?token=` query parameter (AD-706a) can appear in access logs; an operator command-policy rule forbidding `probos crew-token` in agent shells (AD-1328); `AuthConfig`'s description still points at the config file (D18).

## 13. Acceptance criteria

1. All eleven reads go through `crew_scope_token(runtime)`; H1 passes; no direct read remains in `src/`.
2. With the token only in the keyring: the stop routes answer 200 to it, 401 to any other, and 403 `agent_stop_requires_crew_scope_token` when nothing resolves (D1); the file vault is keyed from it (I1); no child the agent paths start sees it (K1, K2); the config file never gains it (D4).
3. With the token only in the config file: everything works as today, with one startup WARNING and a doctor WARN naming the file and `auth.crew_scope_token`, never the value; the file is unchanged (E1, F1).
4. A secure keyring that cannot be read, with no file token: every crew-scope route answers 403 `crew_scope_token_unavailable`, sockets close 1008, startup logs an ERROR, doctor FAILs (C4, D1, D3, D5, E3, F1).
5. No test touches the real OS keyring or the Captain's config or data directory (A1; every config in a test is under `tmp_path`, and G8 passes `--config`).
6. `probos crew-token` takes no token from the command line and is reachable only from `__main__` (G8, H2).
7. The config files are on the floor and content search honours it (J1-J7); the residuals are pinned or recorded (K4, DECISIONS.md).
8. The four scripts in 8.1 pass `--check`; every focused file in section 8 passes.
9. Mutation campaign: every row in section 9 killed (row 32 recorded as not run if `rg` is absent).
10. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 14. Premises to re-verify before the dry run

1. `keyring.core.get_keyring()` in a pytest worker returns `keyring.backends.fail.Keyring` once the conftest line is in (no plugin initialises keyring earlier). A1 checks it.
2. No existing test relies on the real default keyring backend: run the 24 keyring files in 8.1 after M1. A failure there means a test was reaching the real keyring; report it, do not weaken A1.
3. FastAPI resolves a route's `dependencies=[...]` before its parameter dependencies, so a locked stop route answers `crew_scope_token_unavailable` (D1 asserts the detail; if the order differs, the status is still 403 and D1's locked-case detail assertion is the one to settle with the Architect).
4. `POST /api/config` runs over a `SimpleNamespace` runtime (D4); if it reads another runtime attribute, add it to the test runtime, never change the route.
5. `ChainerBackend.backends` can be stood in by a duck or a patched property for B3b (as `tests/test_ad1196_did_key_binding.py:660-690` does).
6. No test that boots a real runtime asserts "no WARNING at boot" while its config sets a token (the new posture WARNING): `tests/test_ad1343_stop_crossing.py`, `tests/test_issue1419_failed_start_rollback.py`, `tests/test_distribution.py`.
7. `rg` availability on the campaign host (row 32).
8. `python -m probos --config <tmp> crew-token set --stdin` exits 1 within 120 s from `cwd=tmp_path` with `PYTHONPATH=src` (G8); `load_dotenv()` (`__main__.py:3071-3075`) does not set `PYTHON_KEYRING_BACKEND`.
9. `tests/test_ad989_code_search.py` never searches a root that holds the checkout's `config/system.yaml` expecting its lines.
10. Every line in section 9 is unique in its file after the build (grep each before mutating).

## 15. Captain

Nothing in this contract needs the Captain: the Captain's decision of 2026-10-20 delegated the config-file question (D7) to the Architect, every other choice is inside the envelope, and no control is weakened (D5 adds a fail-closed state; D10 widens the floor). The Captain's own actions after merge, not decisions: run `probos crew-token set` with the token in use, delete `auth.crew_scope_token` from the config file, restart the vessel.
