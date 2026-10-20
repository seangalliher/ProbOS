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

---

## Amendment A1 (2026-10-20, after the whole-contract dry run)

**Amended by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-20

**Trigger.** Dry run of 2026-10-20 13:00-13:30Z (orchestrator): the contract's 41 SEARCH/REPLACE pairs and five new files applied to `2b97ca11`; the whole existing suite gave 1 failed, 48,927 passed, 147 skipped. The failure: `tests/test_ad1137_doctor.py::test_the_doctor_package_is_imported_only_by_the_cli` (`:1415-1437`, `assert importers == {"__main__.py"}`), because section 5.14's `_load` imports `probos.doctor.runner.describe_load_failure`. A second defect of the same class turned up in the self-check below: H1 as written (section 5.16) fails on the contract's own doctor check (`name: str = "crew_scope_token"`, section 5.13). The dry run could not catch it because the test tables were not applied.

**Apply order.** Apply these blocks to the tree as it stands after the contract's own blocks (cumulative). Each SEARCH occurs exactly once in that tree.

**Supersedes:**
- D16's last clause, "the CLI reads the config through AD-1137's redacting `describe_load_failure`". Replaced by D19.
- Section 5.14: the `_load` function and the docstring sentence that starts "This is the Captain's action". Replaced by A1.1 and A1.2.
- Section 5.16: rows H1 and H2. Replaced by the rows below. New row G9.
- Section 5.17: the `_imports` helper. Replaced by A1.4.
- Section 10: the H1/H2 row. Added: a G9 row.
- Section 12, "AD-1137 (doctor names settings, never values; `describe_load_failure`, reused)". It now reads: "AD-1137's rule kept: the CLI does not import the doctor package and points to `probos doctor`."
- Section 13, criterion 6. Replaced below.
- Header "Estimated tests": about 71 (one new parametrized test, G9).
- Section 5.15 (`__main__.py`) is **unchanged**. A1 needs no `__main__` edit.

### D19 (new; amends D16)

| # | Decision | Rejected alternatives, and why |
|---|---|---|
| D19 | **`probos crew-token` imports nothing from `probos.doctor`.** If the config does not load, the CLI prints the config path and the exception's **type name** only, then points to `probos doctor --config <path>`, which names the setting at fault without its value (AD-1137). It exits 2 before the keyring is read. No value can leak, by construction: the exception's text is never formatted. The standing AD-1137 guard stays unedited. | (1) Inject the describer from `__main__` (a `describe_load_failure` keyword on `run`): the guard passes, but it adds a `Callable` parameter, a second code path (a `None` default that must print the type only anyway) and a `__main__` edit, all to repeat in the CLI what `probos doctor` already reports. A config that does not load also stops the vessel, so the Captain runs `probos doctor` either way. (3) Widen the AD-1137 test to allow `crew_token_cli.py`: it weakens a standing structural guard to fit new code. The guard keeps the doctor package, which reaches `provider_setup`, inside one entry point. That is not this contract's call, and nothing needs it. |

### A1.1 `src/probos/crew_token_cli.py`: the docstring states the rule

SEARCH:
```python
This is the Captain's action. No route, crew tool or MCP server reaches it: only
``probos/__main__.py`` imports this module (pinned by
``tests/test_bf908_crew_scope_token.py``). An agent's shell command runs as the same
```
REPLACE:
```python
This is the Captain's action. No route, crew tool or MCP server reaches it: only
``probos/__main__.py`` imports this module (pinned by
``tests/test_bf908_crew_scope_token.py``), and it imports nothing from
``probos.doctor`` (AD-1137: only ``__main__`` does, ``tests/test_ad1137_doctor.py``).
An agent's shell command runs as the same
```

### A1.2 `src/probos/crew_token_cli.py`: `_load` shows the type only

SEARCH:
```python
def _load(config_path: Path, console: Console) -> Any | None:
    from probos.config import load_config
    from probos.doctor.runner import describe_load_failure

    try:
        return load_config(config_path)
    except Exception as exc:  # noqa: BLE001 -- reported without any value from the file (AD-1137)
        console.print(escape(f"Config {config_path} does not load: {describe_load_failure(exc, config_path)}"), style="red")
        return None
```
REPLACE:
```python
def _load(config_path: Path, console: Console) -> Any | None:
    """The config at ``config_path``, or None after saying it does not load.

    BF-908 A1 (D19): only the exception's type is shown, because its text can quote a
    value from the file (Pydantic's input_value). ``probos doctor`` names the setting at
    fault without its value; only ``__main__`` imports the doctor package (AD-1137).
    """
    from probos.config import load_config

    try:
        return load_config(config_path)
    except Exception as exc:  # noqa: BLE001 -- BF-908 A1: the type name only, never the exception's text
        console.print(escape(f"Config {config_path} does not load ({type(exc).__name__}); `probos doctor --config {config_path}` names the setting at fault."), style="red")
        return None
```

### A1.3 Test rows (section 5.16): H1 and H2 replaced, G9 added

| ID | Test | Asserts |
|---|---|---|
| G9 | `test_cli_a_config_that_does_not_load_shows_its_type_never_its_text` (parametrized over `"status"`, `"set"`, `"clear"`) | `path = tmp_path/"config.yaml"` = `yaml.safe_dump({"cognitive": {"llm_timeout_seconds": FILE_TOKEN}})`. Premise, following `tests/test_ad1137_doctor.py:316-323`: `pytest.raises(ValidationError)` on `load_config(path)` and `FILE_TOKEN in str(exc_info.value)`. Then `crew_token_cli.run(cmd, config_path=path, console=Console(file=io.StringIO(), soft_wrap=True, color_system=None), read_secret=<raises AssertionError>, stdin_is_tty=lambda: True, backend=mem)` returns 2. The output contains `str(path)`, `"ValidationError"` and `"probos doctor --config"`; `FILE_TOKEN not in` the output; `mem.entries == {}`; `read_secret` is never called. |
| H1 | `test_no_module_reads_the_token_setting_directly` | AST scan of every `src/probos/**/*.py`, outside `probos/security/crew_scope.py`. A **read shape** fails, naming the file and line: (a) any `ast.Attribute` with `attr == "crew_scope_token"`; (b) an `ast.Constant` equal to `"crew_scope_token"` used as the second positional argument of a `getattr`, `hasattr` or `setattr` call, or as a `Subscript` slice. A constant in any other position is not a read and is allowed: the doctor check's `name: str = "crew_scope_token"` (section 5.13; the D14 check name, which F1/F2 pin). In the owner: exactly one such `ast.Attribute` (the read in `configured_crew_scope_token`). The scan visited more than 500 files. Detector premise: run the same detector on `ast.parse('getattr(a, "crew_scope_token", "")\nb["crew_scope_token"]\nc.auth.crew_scope_token\nname: str = "crew_scope_token"')` and it reports exactly lines 1, 2 and 3. |
| H2 | `test_only_the_captain_s_cli_writes_the_keyring_entry` | As before: the modules calling `store_keyring_token` or `clear_keyring_token` (as `Name` or `Attribute`), other than the defining module, are `== {"probos.crew_token_cli"}`; the modules importing `probos.crew_token_cli` are `== {"probos.__main__"}`; the modules importing `probos.security.crew_scope` are `== {"probos.credential_store", "probos.crew_token_cli", "probos.doctor.checks.crew_scope_check"}`. **Added:** no name in `_imports("probos.crew_token_cli", tree)` equals `probos.doctor` or starts with `probos.doctor.` (AD-1137's rule, with a BF-908 failure message). Imports are collected with A1.4's helper, which resolves relative imports, so `from ..security import crew_scope` counts. Detector premise: `_imports("probos.routers.x", ast.parse("from ..security import crew_scope"))` contains `"probos.security.crew_scope"`. |

Rows G1-G8 are unchanged: none of them reaches the load failure.

### A1.4 Section 5.17's `_imports` helper, replaced (relative imports resolved)

```python
def _imports(module: str, tree: ast.Module) -> set[str]:
    """Dotted names ``tree`` imports, anywhere in it; relative imports resolved against ``module``'s package.

    ``module`` is the dotted name ``_modules()`` yields (``probos.routers.auth``; a package's
    ``__init__`` yields ``probos.routers.__init__``, whose package is ``probos.routers``).
    """
    package = module.split(".")[:-1]
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                base = node.module or ""
            else:
                anchor = package[: len(package) - (node.level - 1)]
                base = ".".join([*anchor, *([node.module] if node.module else [])])
            found.add(base)
            found.update(f"{base}.{alias.name}" for alias in node.names)
    return found
```

(Pattern: `tests/test_ad1326_procedure_challenger.py:2322-2346`.) Callers pass the name `_modules()` yields. A package's `__init__` reports as `probos.x.__init__`, so H2 compares module names with any `.__init__` suffix stripped.

### A1.5 Section 10 rows

| Test | Proves | Does not prove |
|---|---|---|
| G9 | A config that does not load is refused (exit 2) before the keyring is read. The output names the file, the exception's type and `probos doctor`, never the exception's text, though that text quotes a value. | Which setting is at fault: that is `probos doctor`'s job (AD-1137 tests). |
| H1, H2 | No module but the owner reads the setting (attribute, `getattr` or subscript); only the CLI calls the writers; only three modules import the keyring module (relative imports included), and none is a router, tool, federation or MCP module; the CLI imports nothing from the doctor package. | That a same-user process cannot call `keyring` itself (residual R1). A read through a computed name (`getattr(a, "crew_" + "scope_token")`). |

### A1.6 Mutation table (section 9): one row added

| # | File | Line (stripped, exact) | Mutate to | Killed by |
|---|---|---|---|---|
| 35 | `src/probos/crew_token_cli.py` | `` console.print(escape(f"Config {config_path} does not load ({type(exc).__name__}); `probos doctor --config {config_path}` names the setting at fault."), style="red") `` | the same line with `({type(exc).__name__})` replaced by `({exc})` | G9 |

Rows 1-34 are unchanged. Rows 23-26 (`crew_token_cli.py`) are untouched by A1.1/A1.2 and still unique in their file.

### A1.7 Section 8.1 and section 13

- Section 8.1, "Startup and doctor": add `tests/test_ad1135_provider_setup.py` (its `provider_setup` importer set, `:703`). `tests/test_ad1137_doctor.py` is already listed. It must pass **unedited**.
- Section 13, criterion 6, replaced: "`probos crew-token` takes no token from the command line, is reachable only from `__main__`, and imports nothing from `probos.doctor` (G8, H2; `tests/test_ad1137_doctor.py::test_the_doctor_package_is_imported_only_by_the_cli` passes unedited). A config that does not load is reported by type only (G9)."

### A1.8 Premises to re-verify (section 14, items added)

11. With A1 applied, `tests/test_ad1137_doctor.py::test_the_doctor_package_is_imported_only_by_the_cli` passes **unedited** (the dry run's single failure). `tests/test_ad1135_provider_setup.py:703` still passes: the CLI never imported `provider_setup` directly, and now does not reach it through the doctor package either.
12. G9's premise holds: `str(ValidationError)` quotes `input_value` (no model sets `hide_input_in_errors`; Grep over `src/probos`: 0 hits). If it fails, report it; do not drop the `FILE_TOKEN not in output` assertion.
13. H1's narrowed detector, run on the built tree, reports nothing outside the owner. Expected allowed constants: `doctor/checks/crew_scope_check.py` (`name: str = "crew_scope_token"`) only. The owner's `CREW_SCOPE_KEYRING_USERNAME = "crew_scope_token"` is inside the owner.
14. Rerun the whole existing suite, or at least the files in 8.1, on the amended tree. Expected: 0 failed.

### A1.9 Self-check: other structural or inventory guards the new or edited modules could trip

The dry run applied every source file and the fixture, so each existing guard over `src/` ran against them and passed (the only failure is the one above). What the dry run did **not** exercise: guards that scan `tests/`, which will see the two new test files once the Builders write them, and the contract's own new guards (H1, H2, E4). Checked:

```
CLAIM: no other existing AST importer-set test is tripped by the new or edited modules
RUN:   Grep "importers == |== \{\"__main__" tests/
FOUND: test_ad1135_provider_setup.py:703 (provider_setup importers: the CLI never imports provider_setup; unaffected),
       test_ad1137_doctor.py:1437 (the failure; fixed by A1.2),
       test_ad1326_procedure_challenger.py:2366 (the procedure ledger module; not imported by any BF-908 module),
       test_bf877_unapproved_design_is_refused.py:457 (ProbOSShell construction sites; none added),
       test_codebase_index.py:396 (unrelated)
HOLDS: yes

CLAIM: no existing guard that scans tests/ would trip on the two new test files as specified
RUN:   Grep for rglob/glob over the tests directory in tests/ and scripts/
FOUND: test_ad1270e2g_crew_models.py:724 (flags reads of the literal "src/probos/config.py": the BF-908 tables have none);
       test_ad1270f_shutdown_grace.py:902, :1069 (only files that contain "fast_teardown": none planned);
       test_ad1248_slice_c_one_shape.py:251 (a set literal equal to the crew-execution key shape: none planned);
       scripts/check_architecture_principles.py:1035 (source-text-tests: E4's getsource and H1/H2's read_text are
         reported, never failed: REPORT_ONLY_CATEGORIES, :168);
       scripts/check_config_profiles.py:81 (reads tests/conftest.py: applied in the dry run, preflight green);
       tests/fixtures/file_durations.json (no inventory: an unknown file is weighed at the mean, test_ci_shards.py:498)
HOLDS: yes

CLAIM: the contract's own new guards hold against the contract's own code
RUN:   Grep "[\"']crew_scope_token[\"']|\.crew_scope_token\b" over src/probos and over this contract's code blocks
FOUND: base reads = the eleven sites, all replaced; contract code: security/crew_scope.py:136 (owner constant),
       :187 (the owner's one Attribute read), doctor/checks/crew_scope_check.py (section 5.13) `name: str = "crew_scope_token"`
       -> H1 as first written FAILS here; fixed by A1.3's narrowed H1 (a check name is not a read)
RUN:   Grep "probos\.security\.crew_scope|store_keyring_token|clear_keyring_token|probos\.crew_token_cli" in this contract
FOUND: importers credential_store (section 5.3), crew_token_cli (5.14), doctor/checks/crew_scope_check (5.13), and the
       tests/fixtures file (outside src, not scanned by H2); writers called only in crew_token_cli; crew_token_cli
       imported only by __main__ (5.15)
HOLDS: yes, H2 holds; E4 asserts only strings the contract's runtime.py block adds
```

Also checked, no defect found: the doctor ordering pin `tests/test_bf906_doctor_check.py:350` (`extras` -> `verifier_independence`), since `crew_scope_check` sits after `security_check`, not between those two; and the AD-1343 seam inventory, the store registry and the architecture baseline over `src/`, all green in the dry run. A subtlety the dry run could not show: section 5.17's `_imports` ignored relative imports, which would have let a router escape H2's import check silently. A1.4 closes it.

### A1.10 Verified Against Codebase (2026-10-20, tree `2b97ca11` plus the contract's blocks as the orchestrator reported them)

```
grep -n "def test_the_doctor_package_is_imported_only_by_the_cli|assert importers ==" tests/test_ad1137_doctor.py
  1415: def test_the_doctor_package_is_imported_only_by_the_cli() -> None:   1437: assert importers == {"__main__.py"}
grep -n "def describe_load_failure|from probos import provider_setup" src/probos/doctor/runner.py
  87: def describe_load_failure(exc: Exception, path: Path) -> str:   92: from probos import provider_setup
grep -n "from probos.doctor" src/probos/__main__.py
  1871: from probos.doctor import run_doctor   1872: from probos.doctor.runner import build_context
grep -n "doctor_parser.add_argument" src/probos/__main__.py
  3118-3120: "--config", "-c", ... help="Check this config file (default: the one probos loads)"
grep -n "raw = yaml.safe_load(f)" src/probos/config.py
  4109 (a file stream: a YAML error carries no snippet, so G9 uses the ValidationError case)
grep -n "assert secret in str(exc_info.value)" tests/test_ad1137_doctor.py
  323 (the G9 premise pattern)
grep -n "hide_input_in_errors" src/probos   -> 0 hits
grep -n "def _from_module|def _imported_modules" tests/test_ad1326_procedure_challenger.py
  2322, 2330 (A1.4's pattern)
grep -n "REPORT_ONLY_CATEGORIES|SOURCE_TEXT_MARKERS" scripts/check_architecture_principles.py
  168: ("private-access", "source-text-tests")   249: ("getsource", "read_text")
Contract text used as SEARCH (each once in its file after the contract's blocks): section 5.14 lines 1153-1155
  (docstring) and 1211-1219 (`_load`); "does not load" occurs once in crew_token_cli.py after A1.2 (mutation row 35).
```

### A1.11 Captain

Nothing here needs the Captain. D19 removes a dependency; it does not weaken a control. The AD-1137 guard stays unedited, and D16's "no value is ever printed" becomes stronger: nothing is redacted because nothing is formatted. H1's narrowing applies to a test this contract introduces, not to any standing guard, and it still catches every read shape the base tree has (attribute, `getattr`).

---

## Amendment A2 (2026-10-20, after review round 1 of slice C1a)

**Amended by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-20

**Trigger.** Review round 1 of the C1a candidate (`gpt-6.1-sol`; staged tree `f5cc60ea534d4f44b24b2e726e6eb2ea3a206233` on `19e04ab7`; full text `logs/review-c1a-r1.md`): NOT READY, four findings. Everything else the reviewer was asked to verify held (section 5.16's rows, G10, the eleven reads, the writer boundary).

**Apply order.** Every SEARCH below is written against the **candidate's files** (the C1a build, M1-M3), not the contract's original blocks, and occurs exactly once in its file. The two SEARCH/REPLACE pairs in A2.5 apply to the text of this contract's section 6.4 (the C1b Builder pastes that block into `DECISIONS.md`).

**Supersedes:**
- Section 5.1 (as built): `read_keyring_token_bounded`, `clear_keyring_token`, `CrewScopeKeyring.locked` and one module-docstring paragraph. Replaced by A2.2.
- Section 5.3 (as built): the `crew_scope_locked` docstring. Replaced by A2.2.
- Section 5.5 (as built): two ducks and one constant added. A2.3.
- Section 5.16: the test file's header paragraph and rows B6, E4, G5, G8 reworded; rows B8, B9, B10, B11, C6, E5 and G11 added. A2.3, A2.4.
- Section 9: rows 3 and 6 replaced; rows 14 and 22 gain killers; rows 36-43 added. A2.6.
- Sections 8.1, 10, 13 and 14: A2.7.
- Section 6.4's D3, D6 and "Residual, accepted" bullets. A2.5.
- Header "Estimated tests": about 78 (A1's 71 plus B8, B9, B10, B11, C6, E5, G11).
- Section 5.14 (`crew_token_cli.py`) and section 5.15 (`__main__.py`) are **unchanged**: the CLI already prints a `CrewScopeKeyringError` as "Not cleared: ..." with exit 1 (`crew_token_cli.py:176-178`).

### A2.1 Decisions D20-D25

| # | Decision | Rejected alternatives, and why |
|---|---|---|
| D20 | **Finding 1 (P1, ordinary reach): fix.** `read_keyring_token_bounded` runs the blocking read on its own **daemon** `threading.Thread` (named `CREW_SCOPE_READ_THREAD_NAME`) that hands the result to an `asyncio.Future` through `loop.call_soon_threadsafe`; the caller awaits it with `asyncio.wait_for`. A late answer is dropped without an exception: the hand-over skips a future that is already done (timed out or cancelled), and the thread returns quietly when the loop has closed (`RuntimeError` from `call_soon_threadsafe`). On timeout the result stays `UNAVAILABLE`, "did not answer within N s"; the function still raises only `CancelledError`. One thread per read: startup reads once, `probos doctor` once. The same lesson and remedy, measured, is AD-1137 A-3 (`doctor/checks/llm_check.py:143-175`, "a pool's workers are joined at interpreter exit"); its helper is not reused because `probos.security` may not import `probos.doctor` (AD-1137's importer guard, `tests/test_ad1137_doctor.py:1415-1437`) and it is synchronous. | (a) `asyncio.to_thread` / `loop.run_in_executor(None, ...)` (the candidate): a timed-out `wait_for` cannot stop the call, and the default executor's worker is joined by `asyncio.run` (`asyncio/runners.py:73`, `shutdown_default_executor(THREAD_JOIN_TIMEOUT)`, 300 s, `asyncio/constants.py:34`) and again, without a limit, at interpreter exit (`concurrent/futures/thread.py:23,37`, `_python_exit` registered by `threading._register_atexit`). Measured by the reviewer: `asyncio.run` returned only when the backend was released. (b) A dedicated `ThreadPoolExecutor` with `shutdown(wait=False)`: the same atexit join holds the interpreter. (c) A subprocess per read: it could be killed, but it costs an interpreter start and a `keyring` import per read (about 0.3-1 s), re-opens which environment the child gets (D15, K5) and needs a Windows-safe kill; the abandoned daemon thread costs one blocked thread until exit (R7). |
| D21 | **Finding 2 (P2, injected-only): fix with option (a).** `UNREAD` counts as locked when the config holds no token: `CrewScopeKeyring.locked` is true for `UNREAD` or `UNAVAILABLE` (`_LOCKED_SOURCES`) while `configured_crew_scope_token(config)` is empty; a file token is enforced in every state, as before. Executable proof that the read runs in the real boot order: E5 boots a real `ProbOSRuntime` (the BF-906 pattern); C6 asserts the before-load HTTP and WebSocket refusals. E4 stays (it pins the exact placement E5 cannot see). **Ranking:** (a) first: correctness and safety (a future change that skips or reorders the load becomes a loud 403 `crew_scope_token_unavailable`, not a silently open gate), no production behaviour changes (`probos serve` awaits `runtime.start()` at `__main__.py:650` before `create_app(runtime)` at `:812`; `tests/fixtures/federation_cluster_node.py:184` starts before it serves at `:192`), a one-line revert, and validation measured by the orchestrator: 2,274 passed in section 8.1's 59 files and 342 passed in the 10 other files that build a real runtime and drive the app or gates, 0 failed. The reach is only `require_crew_scope` and `verify_ws_token` (`crew_scope_locked`'s only callers, `routers/auth.py:52`, `:96`); `crew_scope_token` is unchanged, and a `MagicMock` or `SimpleNamespace` runtime is never locked (`credential_store.py:445`), so the remaining real-runtime files that do not drive those two cannot change. (b) second: keeps the unread-open posture and relies on a test to catch a skipped load; it fixes the test weakness but leaves the gate's default open. (c) last: records both and fixes neither. | (b), (c) as ranked. |
| D22 | **Finding 3 (P2, ordinary reach): fix.** After any deletion error, `clear_keyring_token` answers `False` ("none was there") **only** when the error is `keyring.errors.PasswordDeleteError` **and** a read-back through the same backend returns `None`. An entry still present, or a read-back that itself fails, raises `CrewScopeKeyringError("the keyring <backend> refused to clear the token (PasswordDeleteError)")`, the type only; the CLI prints "Not cleared: ..." and exits 1 (unchanged code, `crew_token_cli.py:176-178`). Verified in the installed `keyring`: macOS maps every `api.Error` from a deletion, `KeychainDenied` and `SecAuthFailure` included, to `PasswordDeleteError` (`keyring/backends/macOS/__init__.py:74-77`; `api.py:111,129,133,137`); Windows raises it only when neither target exists and re-raises any other `pywintypes.error` (`Windows.py:147-164`); SecretService raises it for "No such password!" (`SecretService.py:94-101`). The read-back is correct on all three. | Matching the exception's text ("not found"): backend- and locale-specific, and the text may quote what the backend held. Treating every `PasswordDeleteError` as a failure: the second `clear` on an empty keyring would exit 1 on Windows and SecretService, where it means "absent" (G5 pins exit 0). |
| D23 | **Finding 4 (P3, injected-only): record, not fix.** argparse's root parser echoes an unrecognized positional (`probos crew-token set <token>`) to standard error before exiting 2 (`__main__.py:3389`). The value was disclosed when it was typed: it is in the shell's history and in the process's command line, readable by any same-user process (the population of R1). The echo goes to the same terminal and adds no reader. D16 is read as "no value the CLI or ProbOS holds is printed or logged"; G8 now asserts the value is absent from the rejected child's stdout and leaves stderr unasserted, naming R8 (a test must not pin the echo as the contract). | Redacting: (1) `parse_known_args` in `main()` with a redacted error for `crew-token` only: about 8 lines in the shared root entry point for every command, plus a test; (2) a catch-all positional on the `crew-token` verb parsers: about 5 lines, but a value starting with `-` still reaches the root parser's "unrecognized arguments" error. Neither removes the disclosure that already happened; recorded as R8 with that price. |
| D24 | **Scope: only `security/crew_scope.py`'s read is fixed here.** The same defect class predates BF-908 in `identity_key_store.py:186` (AD-1196, `asyncio.wait_for(asyncio.to_thread(run), ...)`, `git blame`: `c4f367503`, 2026-10-01) and in `security/keyring_backend.py` (AD-1016: eight `asyncio.to_thread` keyring calls with no timeout at all, `:160`, `:167`, `:170`, `:178`, `:189`, `:220`, `:228`, `:231`). Recorded as one follow-up (R6), filed by the orchestrator. The follow-up should lift D20's helper into a shared module rather than copy it. | Fixing them in this batch: different features and contracts (the identity key store and the browser vault backend), each with its own tests and review surface; it widens a HIGH batch that is one round from converging. |
| D25 | **Three deviations of the candidate from the contract text, decided and kept (as built, A2.8).** | Reverting the code to the contract text: (a) loses D7's remediation in the log; (b) runs `gh auth token` against the GitHub CLI's real credential store; (c) removes tests that cross seams. |

**Who records what.** The orchestrator posts D20-D25 and R6-R8 on #1605 and pastes R6-R8 into the #1523 register; it opens **one** follow-up issue for R6 (suggested title: "keyring I/O on asyncio's default executor can hold the process at exit (AD-1196 `identity_key_store.py:186`, AD-1016 `security/keyring_backend.py`)"), referencing #1605. R7 and R8 need no issue: they are recorded in `DECISIONS.md` through A2.5.

### A2.2 Source changes (against the candidate)

#### A2.2.1 `src/probos/security/crew_scope.py`: the import

SEARCH:
```python
import hmac
import logging
from dataclasses import dataclass, field
```
REPLACE:
```python
import hmac
import logging
import threading
from dataclasses import dataclass, field
```

#### A2.2.2 `src/probos/security/crew_scope.py`: the module docstring

SEARCH:
```python
file. A secure backend that fails or does not answer is UNAVAILABLE, never "no
token": with no token in the config file either, every route that needs the
token refuses every caller instead of letting every caller through.
```
REPLACE:
```python
file. A secure backend that fails or does not answer is UNAVAILABLE, never "no
token": with no token in the config file either, every route that needs the
token refuses every caller instead of letting every caller through. So does a
keyring step startup has not read yet (UNREAD). The read runs on a daemon thread,
so a keyring that never answers cannot hold the vessel or ``probos doctor`` open
at exit.
```

#### A2.2.3 `src/probos/security/crew_scope.py`: the thread's name

SEARCH:
```python
CREW_SCOPE_UNAVAILABLE = "crew_scope_token_unavailable"
_NO_SECURE_BACKEND = "no recommended (secure) keyring backend"
```
REPLACE:
```python
CREW_SCOPE_UNAVAILABLE = "crew_scope_token_unavailable"
_NO_SECURE_BACKEND = "no recommended (secure) keyring backend"
#: The daemon thread a bounded read runs on (BF-908 A2, D20). Never joined, so it never holds up exit.
CREW_SCOPE_READ_THREAD_NAME = "probos-crew-scope-keyring-read"
```

#### A2.2.4 `src/probos/security/crew_scope.py`: the locked sources

SEARCH:
```python
    UNAVAILABLE = "unavailable"  # a secure keyring failed, did not answer, or holds a malformed entry


@dataclass(frozen=True)
class KeyringRead:
```
REPLACE:
```python
    UNAVAILABLE = "unavailable"  # a secure keyring failed, did not answer, or holds a malformed entry


#: BF-908 A2 (D21): with no token in the config, these refuse every caller. UNREAD is one of them, so a runtime
#: whose startup never read the keyring refuses loudly instead of opening every crew-scope route.
_LOCKED_SOURCES = frozenset({CrewScopeSource.UNREAD, CrewScopeSource.UNAVAILABLE})


@dataclass(frozen=True)
class KeyringRead:
```

#### A2.2.5 `src/probos/security/crew_scope.py`: the bounded read on a daemon thread

SEARCH:
```python
async def read_keyring_token_bounded(
    backend: Any | None = None, *, timeout_seconds: float = CREW_SCOPE_READ_TIMEOUT_SECONDS,
) -> KeyringRead:
    """:func:`read_keyring_token` off the event loop, bounded in time. Raises only ``CancelledError``."""
    try:
        return await asyncio.wait_for(asyncio.to_thread(read_keyring_token, backend), timeout=timeout_seconds)
    except TimeoutError:
```
REPLACE:
```python
def _hand_over(future: asyncio.Future[KeyringRead], read: KeyringRead) -> None:
    """On ``future``'s loop: deliver ``read`` unless the caller has stopped waiting for it."""
    if not future.done():  # timed out or cancelled: nobody waits for this read any more
        future.set_result(read)


def _read_on_daemon_thread(
    backend: Any | None, loop: asyncio.AbstractEventLoop, future: asyncio.Future[KeyringRead],
) -> None:
    """The worker: the blocking read (it never raises), handed to ``loop`` if that loop still runs."""
    read = read_keyring_token(backend)
    try:
        loop.call_soon_threadsafe(_hand_over, future, read)
    except RuntimeError:  # the loop closed after the caller gave up: nothing to deliver to
        return


async def read_keyring_token_bounded(
    backend: Any | None = None, *, timeout_seconds: float = CREW_SCOPE_READ_TIMEOUT_SECONDS,
) -> KeyringRead:
    """:func:`read_keyring_token` on a daemon thread, bounded in time. Raises only ``CancelledError``.

    BF-908 A2 (D20): not ``asyncio.to_thread``. A timed-out ``wait_for`` stops waiting but cannot stop the
    blocking call, and the default executor's worker is joined when ``asyncio.run`` closes its loop (up to
    300 s) and again, without a limit, at interpreter exit, so a keyring that never answers would hold the
    vessel or ``probos doctor`` open. A daemon thread is never joined; a late answer is dropped quietly.
    One thread per read: startup reads once, the doctor once (AD-1137 A-3 measured the same remedy).
    """
    loop = asyncio.get_running_loop()
    future: asyncio.Future[KeyringRead] = loop.create_future()
    try:
        worker = threading.Thread(
            target=_read_on_daemon_thread, args=(backend, loop, future), name=CREW_SCOPE_READ_THREAD_NAME, daemon=True,
        )
        worker.start()
        return await asyncio.wait_for(future, timeout=timeout_seconds)
    except TimeoutError:
```

(The two `except` arms that follow are unchanged: `TimeoutError` -> "did not answer within N s"; `Exception` -> "the keyring read did not run (<type>)", which now also covers a thread that cannot start.)

#### A2.2.6 `src/probos/security/crew_scope.py`: `clear_keyring_token` reports "none" only after a read-back

SEARCH:
```python
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
```
REPLACE:
```python
def _entry_absent(chosen: Any) -> bool:
    """True only when ``chosen`` answers that it holds no entry. A read-back that fails is not "absent"."""
    try:
        held = chosen.get_password(CREW_SCOPE_KEYRING_SERVICE, CREW_SCOPE_KEYRING_USERNAME)
    except Exception:  # noqa: BLE001 -- fail closed: never report "none was there" without an answer
        return False  # BF-908 A2: an entry that cannot be read back is not "absent"
    return held is None


def clear_keyring_token(*, backend: Any | None = None) -> bool:
    """Delete the entry: ``True`` when one was removed, ``False`` when a read-back shows there was none.

    The Captain's action only. ``PasswordDeleteError`` alone does not mean "none was there": keyring's macOS
    backend raises it for every refusal, a denied keychain included (BF-908 A2, D22). Raises
    :class:`CrewScopeKeyringError`, whose message names the exception's type only.
    """
    import keyring.errors

    from probos.identity_keys import KeyStoreUnavailable

    try:
        chosen = _secure_backend(backend)
    except KeyStoreUnavailable:
        raise CrewScopeKeyringError(f"this host has {_NO_SECURE_BACKEND}") from None
    name = _backend_name(chosen)
    try:
        chosen.delete_password(CREW_SCOPE_KEYRING_SERVICE, CREW_SCOPE_KEYRING_USERNAME)
    except Exception as exc:  # noqa: BLE001 -- the type only: a backend's text could quote the value
        if isinstance(exc, keyring.errors.PasswordDeleteError) and _entry_absent(chosen):
            return False
        raise CrewScopeKeyringError(f"the keyring {name} refused to clear the token ({type(exc).__name__})") from None
    return True
```

#### A2.2.7 `src/probos/security/crew_scope.py`: `locked`

SEARCH:
```python
    def locked(self, config: Any) -> bool:
        """True when a secure keyring could not be read and ``config`` holds no token: refuse every caller."""
        return self._read.source is CrewScopeSource.UNAVAILABLE and not configured_crew_scope_token(config)
```
REPLACE:
```python
    def locked(self, config: Any) -> bool:
        """True when ``config`` holds no token and the keyring is unreadable or not read yet: refuse every caller.

        BF-908 A2 (D21): ``UNREAD`` counts, so a runtime whose startup never read the keyring refuses instead of
        letting every caller through. A token in ``config`` is enforced in every state, as before.
        """
        return self._read.source in _LOCKED_SOURCES and not configured_crew_scope_token(config)
```

#### A2.2.8 `src/probos/credential_store.py`: the accessor's docstring

SEARCH:
```python
    """BF-908: True when a secure keyring could not be read and no token is configured; refuse every caller."""
```
REPLACE:
```python
    """BF-908: True when no token is configured and the keyring could not be read, or startup has not read it yet.

    Refuse every caller then (A2, D21). A runtime without a real ``CredentialStore`` (a test double) is never locked.
    """
```

### A2.3 Fixture changes: `tests/fixtures/crew_scope_keyring.py`

SEARCH:
```python
    def get_password(self, service: str, username: str) -> str | None:
        self.release.wait(5)
        return None
```
REPLACE:
```python
    def get_password(self, service: str, username: str) -> str | None:
        self.release.wait(5)
        return None


#: The text a refusing duck's deletion error carries; no message may contain it (the type only, D16).
DENIAL_DETAIL = "bf908-synthetic-denial-detail"


class RefusingDeleteKeyring(MemoryKeyring):
    """A recommended backend whose deletion is refused while the entry stays, as macOS reports a denied keychain.

    keyring's macOS backend raises ``PasswordDeleteError`` for every ``api.Error`` from a deletion,
    ``KeychainDenied`` included (``keyring/backends/macOS/__init__.py``), so that error alone does not mean
    "none was there" (BF-908 A2, D22). ``MemoryKeyring`` raises it only when the entry is absent.
    """

    def delete_password(self, service: str, username: str) -> None:
        raise keyring.errors.PasswordDeleteError(f"Can't delete password in keychain: {DENIAL_DETAIL}")


class LockedDeleteKeyring(RefusingDeleteKeyring):
    """A refused deletion whose read-back fails too (a keychain that locked between the calls)."""

    def get_password(self, service: str, username: str) -> str | None:
        raise keyring.errors.KeyringLocked(DENIAL_DETAIL)
```

### A2.4 Tests: `tests/test_bf908_crew_scope_token.py`

#### A2.4.1 Rows (section 5.16)

| ID | Test | Asserts |
|---|---|---|
| B6 (reworded only) | `test_keyring_step_a_keyring_that_does_not_answer_is_unavailable` (code unchanged) | As built. Its "Does not prove" adds: "that the process can exit while the read is blocked (B9)". |
| B8 | `test_keyring_step_a_refused_deletion_is_never_reported_as_absent` | **Detector premise (upstream contract):** `inspect.getsource(keyring.backends.macOS.Keyring.delete_password)` contains `"except api.Error"` and `"raise PasswordDeleteError("` (the module imports on Windows: `api` is imported under `try`). **Duck premise:** `RefusingDeleteKeyring(token=KEYRING_TOKEN).delete_password(*ENTRY)` raises `PasswordDeleteError` and the entry stays. Then `clear_keyring_token(backend=refusing)` raises `CrewScopeKeyringError` whose text contains `"PasswordDeleteError"` and not `DENIAL_DETAIL`; the entry is still `KEYRING_TOKEN`. `LockedDeleteKeyring(token=KEYRING_TOKEN)`: raises `CrewScopeKeyringError` containing `"PasswordDeleteError"`. `MemoryKeyring()`: returns `False`. `MemoryKeyring(token=KEYRING_TOKEN)`: returns `True` and the entry is gone. |
| B9 | `test_keyring_step_a_read_that_never_answers_does_not_hold_the_process_at_exit` | A real child: `subprocess.run([sys.executable, "-c", _NEVER_ANSWERS_CHILD], capture_output=True, text=True, timeout=60, check=False, cwd=tmp_path, env={**os.environ, "PYTHONPATH": <src dir>})`. Premise: the env holds `PYTHON_KEYRING_BACKEND=keyring.backends.fail.Keyring`. The script defines a recommended duck (`priority = 5`) whose `get_password` waits on an `Event` that is never set, runs `asyncio.run(main())` where `main` awaits `read_keyring_token_bounded(duck, timeout_seconds=0.2)` and prints `read.source.value` and `"did not answer" in read.reason`, then returns. `subprocess.TimeoutExpired` -> `pytest.fail` naming the cause. The child exits 0 and its stdout splits to `["unavailable", "True"]`. Against the candidate (`to_thread`) it fails after 60 s; that is the tests-first proof. |
| B10 | `test_keyring_step_a_late_answer_is_dropped_quietly` | `threading.excepthook` monkeypatched to a recorder; the running loop's exception handler replaced by a recorder (restored in `finally`). `before = frozenset(threading.enumerate())`; `read_keyring_token_bounded(SilentKeyring(), timeout_seconds=0.05)`. The new threads named `CREW_SCOPE_READ_THREAD_NAME` are exactly one, `daemon is True` and still alive (premise: the backend is blocked when the caller gives up). Release the duck, `join(5)`, assert not alive, `await asyncio.sleep(0.05)` so the late hand-over runs on this loop. `read.source is UNAVAILABLE`, `"did not answer" in read.reason`, both recorders empty. |
| B11 | `test_keyring_step_a_late_answer_after_the_loop_closed_is_dropped_quietly` | Synchronous. `threading.excepthook` recorder; `loop = asyncio.new_event_loop()`; `loop.run_until_complete(read_keyring_token_bounded(SilentKeyring(), timeout_seconds=0.05))`; `loop.close()`; then release the duck and `join(5)` the one new read thread. `read.source is UNAVAILABLE`; the recorder is empty (the thread's `call_soon_threadsafe` met a closed loop and returned). |
| C6 | `test_accessor_an_unread_keyring_refuses_while_no_token_is_configured` | A real `CredentialStore(config=SystemConfig())` that never loaded, in a `SimpleNamespace` runtime. Premise: `source is UNREAD`. `crew_scope_locked` is `True`, `crew_scope_token == ""`; `require_crew_scope(_http_request(), authorization=None, runtime=...)` raises 403 `crew_scope_token_unavailable`; `verify_ws_token` returns `False` and closes 1008 for no token and for `KEYRING_TOKEN`. With `AuthConfig(crew_scope_token=FILE_TOKEN)`, still unread: not locked, `crew_scope_token == FILE_TOKEN`, `require_crew_scope` accepts `Bearer FILE_TOKEN` (`None`) and answers 401 to none. |
| E4 (reworded only) | `test_startup_reads_the_keyring_once_before_anything_reads_the_token` (code unchanged) | "Does not prove" now reads: "that a real boot reaches it; E5 does. A source-order check passes with the call under `if False:`." |
| E5 | `test_a_real_boot_reads_the_keyring_after_the_stop_record_and_before_nats` | A real `ProbOSRuntime(config=<BF-906 boot config>, data_dir=tmp_path/"data", llm_client=MockLLMClient())`; `runtime.credential_store.crew_scope` replaced by `_RecordingKeyringStep(runtime, MemoryKeyring(token=KEYRING_TOKEN))`, a `CrewScopeKeyring` subclass whose `load` records `(runtime.agent_stops is not None, runtime.nats_bus is None)` and calls `super().load`. Before `start()`: `source is UNREAD`, `crew_scope_locked(runtime) is True`, `crew_scope_token(runtime) == ""`. `probos.startup.nats.init_nats` monkeypatched to record `crew_scope.source` and delegate to the real one. After `await runtime.start()`: `calls == [(True, True)]`, the recorded source at NATS `== [KEYRING]`, `crew_scope_token(runtime) == KEYRING_TOKEN`, not locked; `await runtime.stop()` in `finally`. |
| G5 (reworded only) | as built | "Proves" adds: "the second `clear` says the keyring held none only because the read-back found no entry (D22)". |
| G8 (one assertion added) | `test_the_cli_takes_no_token_on_the_command_line` | Adds `KEYRING_TOKEN not in as_argument.stdout`. The rejected child's stderr is **not** asserted: argparse echoes the mistyped value there (R8, D23); a test must not pin that echo as the contract. |
| G11 | `test_cli_clear_reports_a_refused_deletion_and_keeps_the_entry` | `crew_token_cli.run("clear", config_path=_config_file(tmp_path), console=<quiet>, backend=RefusingDeleteKeyring(token=KEYRING_TOKEN))` returns 1; the output contains `"Not cleared"` and `"PasswordDeleteError"`, not `"held no"`, not `DENIAL_DETAIL`, and no token (`_assert_prints_no_token`); the entry is still `KEYRING_TOKEN`. |

#### A2.4.2 Imports

SEARCH:
```python
import ast
import contextlib
```
REPLACE:
```python
import ast
import asyncio
import contextlib
```

SEARCH:
```python
import subprocess
import sys
from collections.abc import AsyncIterator, Callable, Iterator
```
REPLACE:
```python
import subprocess
import sys
import threading
from collections.abc import AsyncIterator, Callable, Iterator
```

SEARCH:
```python
import keyring
import pytest
```
REPLACE:
```python
import keyring
import keyring.errors
import pytest
```

SEARCH:
```python
from probos.agent_stop import AgentStopService
from probos.config import AttachmentsConfig, AuthConfig, SystemConfig, load_config
```
REPLACE:
```python
from probos.agent_stop import AgentStopService
from probos.cognitive.llm_client import MockLLMClient
from probos.config import AttachmentsConfig, AuthConfig, SystemConfig, load_config
```

SEARCH:
```python
from probos.security.crew_scope import (
    CREW_SCOPE_KEYRING_SERVICE,
    CrewScopeKeyring,
    CrewScopeSource,
    read_keyring_token,
    read_keyring_token_bounded,
    token_refusal,
)
```
REPLACE:
```python
from probos.security.crew_scope import (
    CREW_SCOPE_KEYRING_SERVICE,
    CREW_SCOPE_READ_THREAD_NAME,
    CrewScopeKeyring,
    CrewScopeKeyringError,
    CrewScopeSource,
    KeyringRead,
    clear_keyring_token,
    read_keyring_token,
    read_keyring_token_bounded,
    token_refusal,
)
```

SEARCH:
```python
from tests.fixtures.crew_scope_keyring import (
    ENTRY,
    FILE_TOKEN,
    KEYRING_TOKEN,
    ROTATED_TOKEN,
    FailingKeyring,
    ForgetfulKeyring,
    InsecureKeyring,
    MemoryKeyring,
    SilentKeyring,
    loaded_store,
)
```
REPLACE:
```python
from tests.fixtures.crew_scope_keyring import (
    DENIAL_DETAIL,
    ENTRY,
    FILE_TOKEN,
    KEYRING_TOKEN,
    ROTATED_TOKEN,
    FailingKeyring,
    ForgetfulKeyring,
    InsecureKeyring,
    LockedDeleteKeyring,
    MemoryKeyring,
    RefusingDeleteKeyring,
    SilentKeyring,
    loaded_store,
)
```

#### A2.4.3 Module docstring

SEARCH:
```python
test's own loop. None of them builds a real runtime, reads a real config file or calls ``CredentialStore.get``.
The CLI tests (G) call ``crew_token_cli.run`` with an in-memory keyring duck, an injected secret reader and a config
file under ``tmp_path``; only G8 starts a child, and it too passes ``--config <tmp file>`` and inherits the fail backend.
```
REPLACE:
```python
test's own loop. None of them builds a real runtime, reads a real config file or calls ``CredentialStore.get``.
E5 alone boots a real ``ProbOSRuntime`` (the BF-906 real-boot pattern), because a source-order check cannot show
that a real boot reaches the keyring read.
The CLI tests (G) call ``crew_token_cli.run`` with an in-memory keyring duck, an injected secret reader and a config
file under ``tmp_path``; only G8 starts a CLI child, and it too passes ``--config <tmp file>`` and inherits the fail
backend. A1 and B9 start a ``python -c`` child that inherits it as well; B9's child reads only a duck its own
script defines.
```

SEARCH:
```python
B6  a keyring that does not answer is UNAVAILABLE
    Proves: the bounded read gives up on a blocked backend and reports it unavailable.
    Does not prove: the 10 s production bound; the test passes a short one.
B7  the stored-token rule
    Proves: 15 characters, a space, a tab, non-ASCII text and a non-string are refused; 16 printable ASCII
    characters are accepted.
    Does not prove: the CLI's prompts (a later milestone).
```
REPLACE:
```python
B6  a keyring that does not answer is UNAVAILABLE
    Proves: the bounded read gives up on a blocked backend and reports it unavailable.
    Does not prove: the 10 s production bound; the test passes a short one. That the process can exit while
    the read is blocked (B9).
B7  the stored-token rule
    Proves: 15 characters, a space, a tab, non-ASCII text and a non-string are refused; 16 printable ASCII
    characters are accepted.
    Does not prove: the CLI's prompts (a later milestone).
B8  a refused deletion is never reported as absent
    Proves: a ``PasswordDeleteError`` that leaves the entry in place, or whose read-back fails, is a refusal naming
    the type only; "none was there" only when the read-back finds no entry. The premise pins keyring's macOS
    backend, which raises that error for a denied keychain too.
    Does not prove: a real keychain's answer; the backends are ducks shaped on keyring's source.
B9  a read that never answers does not hold the process at exit
    Proves: in a real child, ``asyncio.run`` returns and the interpreter exits while the keyring call is still
    blocked, with the read reported unavailable.
    Does not prove: what a real keychain prompt does; the child's backend is a duck that never returns.
B10 a late answer is dropped quietly
    Proves: the read runs on one daemon thread, and an answer that arrives after the caller gave up raises nothing
    on the loop or in the thread.
    Does not prove: B9's exit; this runs in the test's own process.
B11 a late answer after the loop closed is dropped quietly
    Proves: the worker meets a closed loop without an exception escaping the thread.
    Does not prove: anything about a loop that is still running (B10).
```

SEARCH:
```python
    it can, as it can read any attribute.
D1  the stop routes accept the keyring's token and refuse without it
```
REPLACE:
```python
    it can, as it can read any attribute.
C6  an unread keyring refuses while no token is configured
    Proves: a real ``CredentialStore`` that startup never loaded is locked with no configured token (403
    ``crew_scope_token_unavailable``; sockets close 1008), and a configured token is enforced in that state.
    Does not prove: that startup loads it (E5).
D1  the stop routes accept the keyring's token and refuse without it
```

SEARCH:
```python
    Does not prove: that a real boot reaches it (a source-order check, as the AD-1343 Phase 1a ones are).
```
REPLACE:
```python
    Does not prove: that a real boot reaches it; E5 does. A source-order check passes with the call under
    ``if False:``.
E5  a real boot reads the keyring after the stop record and before NATS
    Proves: ``ProbOSRuntime.start`` calls the keyring step's ``load`` exactly once, with the stop record already
    built and NATS not yet started; the read has finished when NATS starts; before the boot the runtime refuses
    (locked), after it the keyring's token is enforced.
    Does not prove: the exact line (E4); the OS keyring (a duck is injected).
```

SEARCH:
```python
    says the keyring held none; on a host with no secure backend it exits 0 and touches no backend.
```
REPLACE:
```python
    says the keyring held none, because the read-back found no entry (D22); on a host with no secure backend it
    exits 0 and touches no backend.
```

SEARCH:
```python
    Proves: the CLI's real entry takes no token as an argument and reaches the keyring layer end to end (refused here
    by the fail backend).
    Does not prove: interactive ``getpass`` on a real terminal.
```
REPLACE:
```python
    Proves: the CLI's real entry takes no token as an argument and reaches the keyring layer end to end (refused here
    by the fail backend); a rejected argument is not in the child's standard output.
    Does not prove: interactive ``getpass`` on a real terminal. Standard error: argparse echoes a mistyped value
    there (residual R8, D23), so it is not asserted.
```

SEARCH:
```python
    Does not prove: the same across two real processes; the keyring is a duck here.
H1, H2  one reader of the setting, one writer of the entry
```
REPLACE:
```python
    Does not prove: the same across two real processes; the keyring is a duck here.
G11 a refused deletion is reported, and the entry stays
    Proves: ``clear`` over a backend that refuses the deletion and keeps the entry exits 1 with "Not cleared" and
    the error's type, never "held no", the backend's text or a token.
    Does not prove: a real keychain (B8's premise pins keyring's macOS contract).
H1, H2  one reader of the setting, one writer of the entry
```

#### A2.4.4 B8-B11 (after B6)

SEARCH:
```python
    assert read.source is CrewScopeSource.UNAVAILABLE
    assert "did not answer" in read.reason


@pytest.mark.parametrize(
```
REPLACE:
```python
    assert read.source is CrewScopeSource.UNAVAILABLE
    assert "did not answer" in read.reason


def test_keyring_step_a_refused_deletion_is_never_reported_as_absent() -> None:
    import keyring.backends.macOS as macos_backend

    # Premise (keyring's own macOS backend): every api.Error from a deletion, a denied keychain included, is raised
    # as PasswordDeleteError, so that error alone does not mean "none was there". If keyring changes this, re-examine D22.
    deletion = inspect.getsource(macos_backend.Keyring.delete_password)
    assert "except api.Error" in deletion
    assert "raise PasswordDeleteError(" in deletion
    refusing = RefusingDeleteKeyring(token=KEYRING_TOKEN)
    with pytest.raises(keyring.errors.PasswordDeleteError):
        refusing.delete_password(*ENTRY)  # premise: the duck raises it and keeps the entry
    assert refusing.entries[ENTRY] == KEYRING_TOKEN

    with pytest.raises(CrewScopeKeyringError) as kept:
        clear_keyring_token(backend=refusing)
    assert "PasswordDeleteError" in str(kept.value)
    assert DENIAL_DETAIL not in str(kept.value)
    assert refusing.entries[ENTRY] == KEYRING_TOKEN

    with pytest.raises(CrewScopeKeyringError) as unreadable:  # the read-back fails too: not "absent"
        clear_keyring_token(backend=LockedDeleteKeyring(token=KEYRING_TOKEN))
    assert "PasswordDeleteError" in str(unreadable.value)
    assert DENIAL_DETAIL not in str(unreadable.value)

    assert clear_keyring_token(backend=MemoryKeyring()) is False  # truly absent
    held = MemoryKeyring(token=KEYRING_TOKEN)
    assert clear_keyring_token(backend=held) is True
    assert ENTRY not in held.entries


_NEVER_ANSWERS_CHILD = """
import asyncio
import threading

from probos.security.crew_scope import read_keyring_token_bounded


class NeverAnswers:
    priority = 5  # recommended, as a secure backend is

    def get_password(self, service, username):
        threading.Event().wait()  # never returns: a keychain prompt nobody answers


async def main():
    read = await read_keyring_token_bounded(NeverAnswers(), timeout_seconds=0.2)
    print(read.source.value, "did not answer" in read.reason, flush=True)


asyncio.run(main())
"""


def test_keyring_step_a_read_that_never_answers_does_not_hold_the_process_at_exit(tmp_path: Path) -> None:
    src_dir = Path(probos.__file__).resolve().parents[1]  # the tree this test runs against
    env = {**os.environ, "PYTHONPATH": str(src_dir)}
    assert env.get("PYTHON_KEYRING_BACKEND") == "keyring.backends.fail.Keyring"  # premise: no real keyring in the child
    try:
        child = subprocess.run(
            [sys.executable, "-c", _NEVER_ANSWERS_CHILD], capture_output=True, text=True, timeout=60,
            check=False, cwd=tmp_path, env=env,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("BF-908 A2: the child did not exit within 60 s; a keyring read that never answers held it open")

    assert child.returncode == 0, child.stderr
    assert child.stdout.split() == ["unavailable", "True"]


def _read_threads_since(before: frozenset[threading.Thread]) -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t not in before and t.name == CREW_SCOPE_READ_THREAD_NAME]


async def test_keyring_step_a_late_answer_is_dropped_quietly(monkeypatch: pytest.MonkeyPatch) -> None:
    thread_errors: list[object] = []
    monkeypatch.setattr(threading, "excepthook", lambda args: thread_errors.append(args.exc_type))
    loop = asyncio.get_running_loop()
    loop_errors: list[object] = []
    previous = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: loop_errors.append(context.get("exception") or context["message"]))
    silent = SilentKeyring()
    before = frozenset(threading.enumerate())
    try:
        try:
            read = await read_keyring_token_bounded(silent, timeout_seconds=0.05)
            workers = _read_threads_since(before)
            assert len(workers) == 1  # premise: the read ran on its own thread
            assert workers[0].daemon is True  # D20: a daemon thread never holds up exit
            assert workers[0].is_alive()  # premise: the backend was still blocked when the caller gave up
        finally:
            silent.release.set()
        workers[0].join(5)
        assert not workers[0].is_alive()
        await asyncio.sleep(0.05)  # the late answer's hand-over runs on this loop
    finally:
        loop.set_exception_handler(previous)

    assert read.source is CrewScopeSource.UNAVAILABLE
    assert "did not answer" in read.reason
    assert loop_errors == []
    assert thread_errors == []


def test_keyring_step_a_late_answer_after_the_loop_closed_is_dropped_quietly(monkeypatch: pytest.MonkeyPatch) -> None:
    thread_errors: list[object] = []
    monkeypatch.setattr(threading, "excepthook", lambda args: thread_errors.append(args.exc_type))
    silent = SilentKeyring()
    before = frozenset(threading.enumerate())
    loop = asyncio.new_event_loop()
    try:
        read = loop.run_until_complete(read_keyring_token_bounded(silent, timeout_seconds=0.05))
    finally:
        loop.close()
        workers = _read_threads_since(before)
        silent.release.set()

    assert len(workers) == 1  # premise: the read ran on its own thread
    workers[0].join(5)
    assert not workers[0].is_alive()
    assert read.source is CrewScopeSource.UNAVAILABLE
    assert thread_errors == []  # the worker met the closed loop and returned


@pytest.mark.parametrize(
```

#### A2.4.5 C6 (after C4)

SEARCH:
```python
    no_backend = SimpleNamespace(config=empty, credential_store=await loaded_store(empty, InsecureKeyring()))
    assert no_backend.credential_store.crew_scope.source is CrewScopeSource.NO_SECURE_BACKEND  # premise
    assert crew_scope_locked(no_backend) is False
```
REPLACE:
```python
    no_backend = SimpleNamespace(config=empty, credential_store=await loaded_store(empty, InsecureKeyring()))
    assert no_backend.credential_store.crew_scope.source is CrewScopeSource.NO_SECURE_BACKEND  # premise
    assert crew_scope_locked(no_backend) is False


async def test_accessor_an_unread_keyring_refuses_while_no_token_is_configured() -> None:
    empty = SystemConfig()
    unread = SimpleNamespace(config=empty, credential_store=CredentialStore(config=empty))
    assert unread.credential_store.crew_scope.source is CrewScopeSource.UNREAD  # premise: startup never read it
    assert crew_scope_locked(unread) is True  # D21: a skipped read refuses, never opens
    assert crew_scope_token(unread) == ""
    with pytest.raises(HTTPException) as refused:
        await require_crew_scope(_http_request(), authorization=None, runtime=unread)
    assert (refused.value.status_code, refused.value.detail) == (403, "crew_scope_token_unavailable")
    for presented in (None, KEYRING_TOKEN):
        socket = _DuckSocket(presented)
        assert await verify_ws_token(socket, unread) is False, presented
        assert [code for code, _reason in socket.closed] == [1008], presented

    configured = SystemConfig(auth=AuthConfig(crew_scope_token=FILE_TOKEN))
    with_file_token = SimpleNamespace(config=configured, credential_store=CredentialStore(config=configured))
    assert with_file_token.credential_store.crew_scope.source is CrewScopeSource.UNREAD  # premise
    assert crew_scope_locked(with_file_token) is False  # a configured token is enforced in every state
    assert crew_scope_token(with_file_token) == FILE_TOKEN
    assert await require_crew_scope(
        _http_request(), authorization=f"Bearer {FILE_TOKEN}", runtime=with_file_token,
    ) is None
    with pytest.raises(HTTPException) as unauthenticated:
        await require_crew_scope(_http_request(), authorization=None, runtime=with_file_token)
    assert unauthenticated.value.status_code == 401
```

#### A2.4.6 E5 (after E4)

SEARCH:
```python
    assert stop_record < keyring_read < source.index("await init_nats(") < source.index("finalize_startup(")
```
REPLACE:
```python
    assert stop_record < keyring_read < source.index("await init_nats(") < source.index("finalize_startup(")


class _RecordingKeyringStep(CrewScopeKeyring):
    """The real keyring step over a duck, recording what the runtime had started when startup called ``load``."""

    def __init__(self, runtime: ProbOSRuntime, backend: Any) -> None:
        super().__init__(backend=backend)
        self._runtime = runtime
        self.calls: list[tuple[bool, bool]] = []  # (the stop record exists, NATS not started yet)

    async def load(self, *, config: Any = None, config_path: str | None = None) -> KeyringRead:
        self.calls.append((self._runtime.agent_stops is not None, self._runtime.nats_bus is None))
        return await super().load(config=config, config_path=config_path)


def _boot_config() -> SystemConfig:
    # The BF-906 real-boot configuration (tests/test_bf906_crew_enrollment_boot.py, ``_config``).
    config = SystemConfig()
    config.onboarding.naming_ceremony = False
    config.proactive_cognitive.enabled = False
    config.qa.enabled = False
    return config


async def test_a_real_boot_reads_the_keyring_after_the_stop_record_and_before_nats(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from probos.startup import nats as startup_nats

    runtime = ProbOSRuntime(config=_boot_config(), data_dir=tmp_path / "data", llm_client=MockLLMClient())
    step = _RecordingKeyringStep(runtime, MemoryKeyring(token=KEYRING_TOKEN))
    runtime.credential_store.crew_scope = step
    assert step.source is CrewScopeSource.UNREAD  # premise
    assert crew_scope_locked(runtime) is True  # D21: before the read, no configured token -> refuse
    assert crew_scope_token(runtime) == ""

    real_init_nats = startup_nats.init_nats
    seen_at_nats: list[CrewScopeSource] = []

    async def recording_init_nats(config: SystemConfig) -> Any:
        seen_at_nats.append(runtime.credential_store.crew_scope.source)
        return await real_init_nats(config)

    monkeypatch.setattr(startup_nats, "init_nats", recording_init_nats)
    await runtime.start()
    try:
        assert step.calls == [(True, True)]  # once, after the stop record, before NATS
        assert seen_at_nats == [CrewScopeSource.KEYRING]  # the read had finished when NATS started
        assert crew_scope_token(runtime) == KEYRING_TOKEN
        assert crew_scope_locked(runtime) is False
    finally:
        await runtime.stop()
```

#### A2.4.7 G8's added assertion

SEARCH:
```python
    assert as_argument.returncode == 2, as_argument.stderr  # argparse refuses the extra argument
```
REPLACE:
```python
    assert as_argument.returncode == 2, as_argument.stderr  # argparse refuses the extra argument
    # BF-908 A2 (D23): stderr is deliberately not asserted. argparse echoes the mistyped value there (residual R8);
    # it was already in the shell's history. Pinning the echo as the contract would be wrong; so would asserting
    # its absence, which no test here can make true without redacting the root parser.
    assert KEYRING_TOKEN not in as_argument.stdout
```

#### A2.4.8 G11 (after G5)

SEARCH:
```python
    assert no_secure_backend == 0
    assert insecure.entries[ENTRY] == KEYRING_TOKEN  # a backend that is not secure is never touched
    _assert_prints_no_token(out.getvalue())
```
REPLACE:
```python
    assert no_secure_backend == 0
    assert insecure.entries[ENTRY] == KEYRING_TOKEN  # a backend that is not secure is never touched
    _assert_prints_no_token(out.getvalue())


def test_cli_clear_reports_a_refused_deletion_and_keeps_the_entry(tmp_path: Path) -> None:
    refusing = RefusingDeleteKeyring(token=KEYRING_TOKEN)
    console, out = _quiet_console()

    code = crew_token_cli.run("clear", config_path=_config_file(tmp_path), console=console, backend=refusing)

    text = out.getvalue()
    assert code == 1
    assert "Not cleared" in text
    assert "PasswordDeleteError" in text
    assert "held no" not in text  # D22: a refusal is never reported as "none was there"
    assert DENIAL_DETAIL not in text
    assert refusing.entries[ENTRY] == KEYRING_TOKEN
    _assert_prints_no_token(text)
```

### A2.5 Section 6.4 (`DECISIONS.md` block): SEARCH/REPLACE against this contract's own text

Apply to section 6.4's REPLACE block before the C1b Builder pastes it. Section 6.5 (`PROGRESS.md`) needs **no** change: "A keyring that cannot be read refuses every caller instead of opening the routes" stays true.

SEARCH:
```markdown
- *D3 (fail closed).* A secure keyring that fails, does not answer within 10 s or holds a malformed entry, with no token in the config, makes every crew-scope route answer 403 `crew_scope_token_unavailable`. A host with no secure backend has no keyring step and behaves as before.
```
REPLACE:
```markdown
- *D3 (fail closed).* A secure keyring that fails, does not answer within 10 s or holds a malformed entry, or a keyring step that startup has not read yet, with no token in the config, makes every crew-scope route answer 403 `crew_scope_token_unavailable`. A host with no secure backend has no keyring step and behaves as before. The read runs on a daemon thread, so a keyring that never answers cannot hold the vessel or `probos doctor` open at exit (`asyncio.to_thread`'s worker would be joined there).
```

SEARCH:
```markdown
A change is refused while the browser file vault holds entries under the token in use; `clear` never is.
```
REPLACE:
```markdown
A change is refused while the browser file vault holds entries under the token in use; `clear` never is, and it says the keyring held no token only when a read-back shows the entry absent (macOS reports a denied keychain with the same error as a missing entry).
```

SEARCH:
```markdown
A change takes effect only at a restart.
```
REPLACE:
```markdown
A change takes effect only at a restart. A keyring read that never answers is abandoned on its daemon thread, which holds that one blocked call until the process exits. A token typed as a command-line argument by mistake is refused, and argparse echoes it to the same terminal's standard error; it was already in the shell's history. The identity-key store's bounded read (AD-1196) and the browser vault's keychain calls (AD-1016) still run on asyncio's default executor, so a keyring that never answers can hold those processes at exit: a follow-up issue.
```

### A2.6 Mutation table (section 9): rows changed and added

| # | File | Line (stripped, exact) | Mutate to | Killed by |
|---|---|---|---|---|
| 3 (replaced) | `src/probos/security/crew_scope.py` | `return self._read.source in _LOCKED_SOURCES and not configured_crew_scope_token(config)` | `return False` | C4, C6, D1, D3, D5, E5 |
| 6 (replaced; the old anchor is gone) | same | `return await asyncio.wait_for(future, timeout=timeout_seconds)` | `return read_keyring_token(backend)` | B6 (the read blocks the loop ~5 s, then answers ABSENT) |
| 14 (killers widened; line unchanged) | `src/probos/credential_store.py` | `return isinstance(store, CredentialStore) and store.crew_scope.locked(getattr(runtime, "config", None))` | `return False` | C4, C6, D5, E5 |
| 22 (killers widened; line unchanged) | `src/probos/runtime.py` | `await self.credential_store.crew_scope.load(config=self.config, config_path=self.config_path)` | delete the line | E4, E5 |
| 36 | `src/probos/security/crew_scope.py` | `_LOCKED_SOURCES = frozenset({CrewScopeSource.UNREAD, CrewScopeSource.UNAVAILABLE})` | `_LOCKED_SOURCES = frozenset({CrewScopeSource.UNAVAILABLE})` | C6, E5 |
| 37 | same | `target=_read_on_daemon_thread, args=(backend, loop, future), name=CREW_SCOPE_READ_THREAD_NAME, daemon=True,` | the same line with `daemon=False` | B9, B10 |
| 38 | same | `if not future.done():  # timed out or cancelled: nobody waits for this read any more` | `if True:` | B10 (`InvalidStateError` reaches the loop's handler) |
| 39 | same | `except RuntimeError:  # the loop closed after the caller gave up: nothing to deliver to` | `except ValueError:` | B11 (the `RuntimeError` escapes the thread) |
| 40 | same | `if isinstance(exc, keyring.errors.PasswordDeleteError) and _entry_absent(chosen):` | `if isinstance(exc, keyring.errors.PasswordDeleteError):` | B8, G11 |
| 41 | same | `return held is None` | `return True` | B8, G11 |
| 42 | same | `return False  # BF-908 A2: an entry that cannot be read back is not "absent"` | `return True` | B8 (`LockedDeleteKeyring`) |
| 43 | `src/probos/runtime.py` | `await self.credential_store.crew_scope.load(config=self.config, config_path=self.config_path)` | the same line indented under a new `if False:` line (the reviewer's mutant) | E5 (E4 survives it, by design) |

Rows 1-2, 4-5, 7-13, 15-35 are unchanged; their lines are untouched by A2 and stay unique (row 4's `return KeyringRead(CrewScopeSource.UNAVAILABLE, backend=name, reason=f"the keyring failed ({type(exc).__name__})")` included; A2 adds no line of that text). Rows 37-42's lines each occur once in `crew_scope.py` after A2 (each is new text; `return False` and `return True` occur elsewhere, which is why rows 42 and 41 anchor on a comment or a unique expression, and why the absent branch's bare `return False` and `clear`'s `return True` are not rows).

**Equivalent or excluded mutants:** dropping `isinstance(exc, keyring.errors.PasswordDeleteError) and` from row 40's line (a non-`PasswordDeleteError` failure whose read-back finds no entry would then read "none was there", which is true; no false success, no disclosure); deleting `worker.start()` (every load then times out after 10 s; killed by C1 and the D rows at about 10 s each, too slow to list as a row); removing `_hand_over`'s `future.set_result(read)` (same: every read times out; killed by C1). Rows 37 and 43 need their own run of B9 and E5 respectively (each about 1-60 s and a real boot).

**Campaign of record:** the orchestrator runs the whole table on the repaired candidate, recording the base tree and each pinned file's sha256 (standing order); rows 37-43 and replaced rows 3 and 6 are new, the rest rerun only for files whose sha256 changed (`crew_scope.py`, `credential_store.py`; `runtime.py` is untouched by A2, so rows 21-22 need no rerun if its hash matches the candidate's, and row 22's new killer E5 is shown by row 43).

### A2.7 Sections 8.1, 10, 13 and 14

**Section 8.1, added files:**
- Real boot and leftovers: `tests/test_bf906_crew_enrollment_boot.py tests/test_issue1452_stop_leftovers.py` (E5 uses BF-906's pattern; the new daemon thread is excluded from leftover checks, `tests/fixtures/runtime_lifecycle.py:144-156`).
- Option (a)'s reach, as measured by the orchestrator: `tests/test_ad1194_unified_capability_triage.py tests/test_ad719_chat_fanout.py tests/test_ad719_episodic_writes.py tests/test_ad914_group_chat_fanout.py tests/test_ad916_chat_file_sharing.py tests/test_architect_api.py tests/test_bf756_agent_tools_without_management.py tests/test_builder_api.py tests/test_dispatch_wiring.py tests/test_selfmod_e2e.py`.
- Unchanged: the four scripts. Section 8.2 (C1b) is unchanged.

**Section 10, rows added or replaced:**

| Test | Proves | Does not prove |
|---|---|---|
| B8 | A refused deletion that keeps the entry, or whose read-back fails, is reported by type, never as "none was there". | A real keychain's answer (ducks shaped on keyring's macOS source, pinned as a premise). |
| B9 | A keyring read that never answers does not hold `asyncio.run` or the interpreter at exit. | A real keychain prompt. |
| B10, B11 | A late answer, on a running or a closed loop, raises nothing anywhere; the read runs on one daemon thread. | B9's exit. |
| C6 | An unread keyring step refuses every caller while no token is configured, and enforces a configured one. | That startup loads it (E5). |
| E4 | Exactly one `load` call, between the stop record and NATS, in `start`'s source. | That a real boot reaches it (E5); it passes under `if False:`. |
| E5 | A real boot calls `load` once, after the stop record and before NATS; refused before, the keyring's token enforced after. | The exact line (E4). |
| G8 | No token argument is accepted; it is not in the child's stdout. | Its stderr: argparse echoes a mistyped value there (R8). |
| G11 | The CLI reports a refused deletion as "Not cleared" with exit 1 and keeps the entry. | A real keychain. |

**Section 13, criteria:**
- Criterion 4 adds: "so does a keyring step that startup has not read yet (C6, E5)."
- New criterion 11: "A keyring read that never answers does not hold the vessel or `probos doctor` open at exit, and a late answer raises nothing (B9, B10, B11)."
- New criterion 12: "`probos crew-token clear` says the keyring held none only when a read-back shows the entry absent; a refused deletion exits 1 and keeps the entry (B8, G11)."
- Criterion 9 covers rows 1-43 (A2.6).

**Section 14, premises added:**
15. E5 boots under the conftest's fail backend exactly as `tests/test_bf906_crew_enrollment_boot.py:55-58` does. If the boot fails for a reason outside BF-908, report it; do not skip E5.
16. Tests first: against the unrepaired candidate, B8, B9 (after 60 s), B10, B11 (no thread of that name), C6, E5 (its before-boot premise) and G11 fail; G8's added assertion passes.
17. `import keyring.backends.macOS` succeeds on Windows (`api` is imported under `try`, `macOS/__init__.py:10-13`) and `inspect.getsource` unwraps `warn_keychain` (`functools.wraps`).

**Self-check: guards the new code could trip.**

```
CLAIM: no AST importer-set guard is tripped
RUN:   Grep "importers == " tests/ (A1.9's enumeration); A2 adds `import threading` to crew_scope.py only
FOUND: test_ad1137_doctor.py:1437 (doctor importers: crew_scope.py still imports nothing from probos.doctor;
       D20 deliberately does not reuse llm_check._bounded for this reason), test_ad1135_provider_setup.py:703,
       test_ad1326_procedure_challenger.py:2366, test_bf877:457, test_codebase_index.py:396: none affected
HOLDS: yes

CLAIM: H1 and H2 hold
RUN:   the new src lines read no `crew_scope_token` attribute; no new importer of probos.security.crew_scope;
       store/clear are still called only by crew_token_cli (B8 and G11 are in tests/, which H2 does not scan)
HOLDS: yes

CLAIM: K5 ("no child script imports keyring") does not apply to B9
RUN:   contract section 6.3 row K5: `all("keyring" not in command for command in _CHILD_COMMANDS)`, in C1b's file
FOUND: K5 is scoped to C1b's build_command_env children; B9's child inherits os.environ (the fail backend) and is
       in C1a's file
HOLDS: yes

CLAIM: no thread or leftover guard trips on the new daemon thread
RUN:   Grep "threading.enumerate(" tests/ src/; Grep "Thread|to_thread" scripts/check_seam_contracts.py
FOUND: tests/fixtures/runtime_lifecycle.py:144-156 counts non-daemon threads only; test_ad1137_doctor.py:819 counts
       "probos-doctor-probe" only; check_seam_contracts.py: no match; check_architecture_principles.py's gating
       categories are srp-size, layer-import (and report-only private-access, source-text-tests: :168, :573, :608,
       :632, :741), none about threads
HOLDS: yes

CLAIM: the "AD-734 hook" named in the request
RUN:   Grep "AD-734" over the repo outside prompts/
FOUND: tests/test_ad734_wire_shape_contract.py (the vision wire-shape test; scans no test files), DECISIONS.md:6937,
       PROGRESS.md, the AD ledger; no hook, and no .githooks/ or .pre-commit-config.yaml in this tree
HOLDS: nothing to trip; if the orchestrator means another hook, name it and I will check it
```

E5 does not use `started_runtime` or the text `fast_teardown`, so the AD-1270f scan of test files (`tests/test_ad1270f_shutdown_grace.py:902`, `:1069`) does not see it.

### A2.8 As built (D25): three deviations kept

(a) **The startup log carries the remediation.** `CrewScopeKeyring.load` logs `posture.message` followed by `posture.remediation`, when present, in one record at the posture's level (`security/crew_scope.py:272-280`). D7 and E1 require the command (`probos crew-token set`) in the startup log; section 5.1's sample logged the message only. E1 asserts exactly one record.

(b) **C5 stubs the GitHub CLI and clears four variables.** C5 replaces `probos.credential_store.subprocess` with a recorder that fails as an absent CLI does, and deletes `GH_TOKEN`, `GITHUB_TOKEN`, `PROBOS_DISCORD_TOKEN` and `LLM_API_KEY` from the environment (`tests/test_bf908_crew_scope_token.py:446-452`). Section 5.16's row as written would have run `gh auth token` against the GitHub CLI's real credential store (the built-in `github` spec ends in a CLI step, `credential_store.py:375`). **Standing rule for this batch:** any later test that calls `get()`, `available()` or `list_credentials()` on a real `CredentialStore` needs the same guard; C1b's children tests must honour it.

(c) **Tests beyond the rows.** G10 (`test_a_token_the_cli_stored_is_the_one_the_vessel_enforces`: CLI `set` -> keyring -> startup read -> accessor -> the stop route, 200 and 401) and a read counter in G9 (`_CountingKeyring`, `mem.reads == 0`: refused before the keyring is read). Both are kept as rows.

### A2.9 Residuals and follow-ups (R1-R5 stay)

Worded for the #1523 register and the DECISIONS entry:

- **R6 (follow-up issue; the orchestrator files it).** The identity-key store's bounded keyring read (`identity_key_store.py:186`, AD-1196) and the browser vault's keychain backend (`security/keyring_backend.py`, AD-1016: eight `asyncio.to_thread` calls with no timeout) run on asyncio's default executor. A keyring call that never returns holds `asyncio.run` at exit for up to 300 s and then the interpreter without a limit; the AD-1016 calls also hold their awaiting caller indefinitely. **Reach:** ordinary on a host whose keychain prompts and nobody answers, or whose secret service stalls. Predates BF-908. Fix: lift BF-908's daemon-thread read (D20) into a shared helper and use it for both.
- **R7 (recorded).** A keyring read that never answers is abandoned on a daemon thread, which holds that one blocked call until the process exits. One thread per bounded read; startup and `probos doctor` each read once, so it does not grow. **Reach:** the same hosts as R6.
- **R8 (recorded; P3).** `probos crew-token <verb> <token>` is refused (exit 2), and argparse echoes the mistyped value to the same terminal's standard error. The value was already in the shell's history and the process's command line. **Reach:** the Captain mistyping. Fix if wanted later: `parse_known_args` in `main()` with a redacted error for `crew-token` (about 8 lines in the shared entry point plus a test).

### A2.10 Repair milestone

**M3r (C1a repair), one Builder pass, tests first, about 35-45 tool calls.** (1) A2.3 fixture and A2.4 test blocks; run `tests/test_bf908_crew_scope_token.py -n 0` and confirm premise 16 (seven new tests red; B9 takes 60 s to fail). (2) A2.2 source blocks. (3) Rerun the file, then section 8.1 with A2.7's additions, `-n 0`. (4) Report every SEARCH that did not match exactly once; do not improvise. Then the orchestrator: one consolidated focused check, review round 2 on the **delta** (A2 touches no shared contract beyond `locked()`'s widened state, which C6/E5 pin and the measured 69 files cover), commit.

### A2.11 Prior art and blind spots

- **Internal.** AD-1137 A-3 measured the same exit hang for doctor probes and chose a daemon thread over an executor (`doctor/checks/llm_check.py:146-151`): adopted, not imported (D20). BF-906's real-boot tests (`tests/test_bf906_crew_enrollment_boot.py:55-58`): E5's pattern, adopted. The BF-906 lesson (a source-text test passes on dead code): why E5 accompanies E4.
- **External.** CPython [issue #96827](https://github.com/python/cpython/issues/96827): `asyncio.run`'s cleanup waits in `shutdown_default_executor` for a thread still running in the default executor. It confirms the finding; nothing in CPython stops `asyncio.run` waiting for such a thread, hence a thread outside the executor. ProbOS-specific plumbing otherwise; `docs/research/reference-projects.md` not consulted (a bug-fix amendment, not a design AD).
- **Blind spots checked.** A late answer on a cancelled future, or on a closed loop (B10, B11); a thread that cannot start (the existing `except Exception` arm, "did not run"); Windows and SecretService delete semantics (D22: the read-back is correct on both); a real runtime that is never started serving no-token routes (D21: no production path; the test suites are measured).

### A2.12 Verified Against Codebase (2026-10-20, candidate tree `f5cc60ea` in worktree `bf908-a2`)

```
grep -n "asyncio.to_thread(read_keyring_token" src/probos/security/crew_scope.py
  150: return await asyncio.wait_for(asyncio.to_thread(read_keyring_token, backend), timeout=timeout_seconds)
grep -n "except keyring.errors.PasswordDeleteError" src/probos/security/crew_scope.py      196
grep -n "return self._read.source is CrewScopeSource.UNAVAILABLE" src/probos/security/crew_scope.py   291
grep -n "self._read = KeyringRead(CrewScopeSource.UNREAD)" src/probos/security/crew_scope.py         254
grep -n "def crew_scope_locked|store.crew_scope.locked" src/probos/credential_store.py   442, 445
grep -n "crew_scope_locked" src/probos      routers/auth.py:24, :52, :96; credential_store.py:442, :445 (only)
grep -n "await self.agent_stops.start()|crew_scope.load(|await init_nats(" src/probos/runtime.py   2771, 2775, 2782
grep -n "self.agent_stops = None|self.nats_bus: NATSBus | None = None|self.config_path: str | None = None" src/probos/runtime.py
  704, 1657, 1279
grep -n "async def init_nats" src/probos/startup/nats.py     19 (one caller: runtime.py:2782)
grep -n "await runtime.start()|create_app(runtime" src/probos/__main__.py   650, 812
grep -n "await runtime.start()|_serve_api(runtime" tests/fixtures/federation_cluster_node.py   184, 192
grep -n "removed = clear_keyring_token|Not cleared|held no" src/probos/crew_token_cli.py   175, 177, 180
grep -n "args = parser.parse_args()" src/probos/__main__.py   3389
grep -n "def delete_password|except api.Error|raise PasswordDeleteError" .venv/.../keyring/backends/macOS/__init__.py   70, 76, 77
grep -n "^class (Error|NotFound|KeychainDenied|SecAuthFailure)" .venv/.../keyring/backends/macOS/api.py   111, 129, 133, 137
grep -n "def delete_password|raise PasswordDeleteError|winerror == 1168" .venv/.../keyring/backends/Windows.py   147, 156, 162
grep -n "def delete_password|No such password" .venv/.../keyring/backends/SecretService.py   94, 101
grep -n "shutdown_default_executor" <python 3.12.13>/Lib/asyncio/runners.py   73;  constants.py:34 THREAD_JOIN_TIMEOUT = 300
grep -n "def _python_exit|_register_atexit" <python 3.12.13>/Lib/concurrent/futures/thread.py   23, 37
grep -n "asyncio.wait_for(asyncio.to_thread(run)" src/probos/identity_key_store.py   186 (git blame c4f367503, 2026-10-01)
grep -n "asyncio.to_thread" src/probos/security/keyring_backend.py   160, 167, 170, 178, 189, 220, 228, 231
grep -n "worker = threading.Thread(target=run, name=\"probos-doctor-probe\", daemon=True)" src/probos/doctor/checks/llm_check.py   166
grep -n "def _quiet_console|soft_wrap=True" tests/test_bf908_crew_scope_token.py   873, 876
grep -n "def nondaemon_threads_since|not thread.daemon" tests/fixtures/runtime_lifecycle.py   144, 154
interpreter: d:/ProbOS/.venv (pyvenv.cfg version_info = 3.12.13)
```

**Absence verified (2026-10-20):**

```
CLAIM: no production path serves crew-scope routes from a runtime whose start() has not run (D21's "no behaviour change")
RUN:   Grep "create_app\(" src/probos  ->  api.py:111 (the definition); Grep "create_app\(runtime" src/probos -> __main__.py:812 only
FOUND: __main__.py:650 awaits runtime.start() before :812; tests/fixtures/federation_cluster_node.py starts (:184) before serving (:192)
HOLDS: yes

CLAIM: crew_scope_locked has no caller beyond the two gates
RUN:   Grep "crew_scope_locked|\.locked\(" src/probos
FOUND: routers/auth.py:52, :96; the definition; unrelated asyncio Lock.locked() calls (telemetry_relay, perception, crew_orchestrator)
HOLDS: yes

CLAIM: a MagicMock or SimpleNamespace runtime is never locked, so the other real-runtime-free app tests cannot change
RUN:   credential_store.py:445 `isinstance(store, CredentialStore) and ...`; e.g. tests/test_ad1270f_shutdown_grace.py:252 (MagicMock runtime)
HOLDS: yes
```

### A2.13 Captain

Nothing here needs the Captain. D20 and D22 repair defects without changing a control; D21 makes an unread keyring step fail closed (a control strengthened, no production behaviour changed); D23 records a P3 the convergence rule allows recording (injected-only, no repair introduced it) and narrows D16's wording to what holds; D24 files a pre-existing defect as a follow-up rather than widening this batch.

## Amendment A3 (2026-10-20, after review round 1 of slice C1b)

**Amended by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-20

**Trigger.** Review round 1 of the C1b candidate (`gpt-6.1-sol`; staged tree `655073e03bda9e02c71abcbc3caf2d390ab98f58` on `eca5a242`; full text `logs/review-c1b-r1.md`): NOT READY, four findings and one to record. Everything else held: the legitimate config consumers (the loader, `probos doctor`, the Settings JSON and YAML functions and their HXI callers) work with a protected config file; both engines reach the filter; keys and types are intact; J6's premise and K5 hold; the ledger check passes.

**Apply order.** Three groups, in this order: **tests first** (A3.2: apply, then run the file and confirm A3.6 premise 18: the listed tests are red on the unrepaired candidate), **source** (A3.3), **trackers** (A3.4). Every SEARCH is written against the **candidate's** files (tree `655073e0`) and occurs exactly once in its file. A3.4's SEARCH blocks are fragments of single long lines in `DECISIONS.md` and `PROGRESS.md`; replace the fragment in place.

**Supersedes:**
- Section 6.1 (as built): `protected_config_files` lists each file once. A3.3.3.
- Section 6.2 (as built): `_within_floor` takes the search's floor, and both engines ask the floor before they count a match. A3.3.1, A3.3.2.
- Section 6.3 (as built): the file's header paragraph; J4, K1, K2 and K4's assertions; rows J8-J16 added. A3.2.
- Section 6.4 and 6.5 as pasted into `DECISIONS.md` and `PROGRESS.md` by the C1b Builder: A3.4 edits those files directly (this contract's sections 6.4 and 6.5 stay as they are; the trackers are the record).
- Section 9: rows 31, 32 replaced; rows 28, 33, 34 change killers; rows 44-56 added. A3.5.
- Sections 8.2, 10, 13 and 14: A3.6.
- C1b's test count: 18 cases (17 passed, 1 POSIX skip on Windows) becomes 32 (J8 x2, J9 x2, J10 x2, J11 x2, J12, J13 x2, J14, J15, J16).

### A3.1 Decisions D26-D31

| # | Decision | Rejected alternatives, and why |
|---|---|---|
| D26 | **Finding 1 (P2, ordinary reach, new in C1b): fix with floor-aware engines.** `act` builds one `_ReadFloor` per search (the three root lists, computed once, and a cache of one decision per distinct path) and passes it to both engines. The Python engine asks it about each file **before opening it** (`fp.open`, `code_search.py:248`), so a protected file is never read and never counted. The rg engine asks it about each parsed line's path **before** appending and before the cap's `break` (`:205`); rg's `--max-count` is per file (`:172`), so a protected file emits at most `max_results` lines, all skipped. BF-895's "rg and the parser disagree" fallback (`:209`) now keys on lines that **parsed**, not on lines kept, so output whose every line the floor refused is an empty rg result, not a false fallback with a misleading warning. `_within_floor` stays as defence in depth, now taking the same floor (cache hits, no new resolution); J13 keeps it live by stubbing an engine that ignores the floor. Measured cost before: 200 matches, 200 floor constructions and 1,000 `Path.resolve()` calls (165 ms, the reviewer); after: one floor per search (plus the root check's own) and one resolution per distinct file (J14 pins `{"roots_built": 2, "decisions": 3}` for one public file with 30 matching lines). | (a) Over-collect, then truncate: the Python engine would read every file to its end and rg's whole output would be kept; `max_results` exists to bound that work. (b) rg `--glob '!<path>'` exclusions: globs are relative to the search root with `/` separators and match the spelled path, not the resolved one, so a `..` or symlinked spelling escapes; the data-directory rule (a root, with a deeper workspace exemption) has no exact glob; and the Python engine needs the per-file check anyway, so the rule would live twice. (c) Fixing `truncated` only: `handle_intent` discards it (`:99`); the reviewer measured `[]` reaching `DmReplyPipeline._render_mesh_read_result()` (`cognitive/dm/reply_pipeline.py:1539-1552`) with no notice. (d) A public `ReadFloor` in `security/file_access.py` with `resolve_for_runtime` rebuilt on it: DRY-better, but it rewrites the function six readers call, inside the module the AD-1200 and BF-758 suites drive, for a search-local need; the same three-call composition already exists twice (`repository_instructions.py:62-64`, `cognitive/swe_harness/tools.py:329-331`), and J16 pins `_ReadFloor` to `resolve_for_runtime`'s answers. Considered for the R10 follow-up, which touches that module anyway. (e) A mandatory `floor` argument on the engines: `tests/test_bf895_rg_line_parse.py:186-226` and J5-J7's controls call the raw engines positionally; `floor` is keyword-only, default `None` (the raw engine), and `act` always passes one (rows 45, 50, 56). |
| D27 | **`truncated` keeps its meaning: the cap of permitted matches was reached.** It is now counted over permitted matches only, so a protected file can neither set it (J10) nor hide a real cut (J11). It does not become "more permitted matches exist": rg's `--max-count` is per file, so a file with more matching lines than the cap is cut by rg itself and the engine cannot tell (R13; predates BF-908). | Redefining it as "a further permitted match was seen": rg cannot report it for a single file, so the two engines would disagree. |
| D28 | **The rg quota tests drive the real `_search_rg` with a fake child.** `_FakeRg` prints `path<NUL>1:text` records in a fixed order (the protected file first) and exits 0. Real rg searches in parallel, so the order of its output is not fixed: a protected-first test on real rg passes a broken engine whenever rg happens to print the public file first. The fake makes J9-J11[rg] and J15 deterministic and lets them run on a host with no `rg`; J5[rg] still runs the real binary. | `--sort path` in production to fix rg's order: makes every search single-threaded to serve a test. Real rg with many protected files (lowering the false-pass chance): still probabilistic, and skipped where `rg` is absent. |
| D29 | **Finding 2 (P2, injected-only, new in C1b): fix, test-only.** Every check on a child's output is derived into a local (labels, booleans, an exit code, gathered in one dict) and only that local is asserted. Pytest's assertion rewriting prints a call's arguments and the repr of an attribute's owner when an assertion fails, and `ToolResult`'s repr includes `output` (`tools/protocol.py:81-87`), so `assert tool_result.success is True` would also print the child's stdout. Applies to K1 (both children and the inheriting premise), K2 and K4; J4's two token-membership checks get the same treatment (synthetic values, but the same rule). Assertion messages no longer quote a result's `error`, except `RunCommandTool`'s, whose errors are refusal, timeout or exception texts, never child output (`cognitive/swe_harness/tools.py:1211-1275`); the shell agent's and the sandbox's errors may hold the child's stderr and are withheld. These changes cannot be red: they change only what a failure prints. | Leaving the passing assertions as they are: the module's own safety claim (`:11-12`) and D15 must hold when a test fails, which is when the output is printed. `pytest -p no:assertion`: global, and loses every other diagnostic. |
| D30 | **Finding 3 (P3, ordinary reach, new in C1b): fix.** `protected_config_files` keeps the first occurrence of each resolved `Path`, in candidate order (loaded, checkout default, home default); `Path` equality is case-insensitive on Windows. The data directory still leads `protected_read_roots`. J8 covers both loaded-equals-default cases, each spelled with a `..` hop. | De-duplicating in `protected_read_roots` instead: a data directory equal to a config file is not a real case, and `protected_config_files` is the public answer to "which config files". |
| D31 | **Finding 4 (P3, ordinary reach): fix the wording; the unfloored readers become one follow-up (R9), not part of this slice.** `PROGRESS.md` names the floor-aware readers, qualifies the fail-closed rule with "no token in the config", and separates "no route, crew tool or MCP server manages the token" from a same-user shell running the CLI. `DECISIONS.md`'s D7 and "Residual, accepted" bullets say the same and name the readers that do not call the floor. **Finding 5 (P3, injected-only, predates BF-908): record (R10).** Reading the standing-orders tool for R9 also found a separate pre-existing defect: its `department` parameter is joined into a path unchecked (`cognitive/swe_harness/tools.py:850-854`), so the tool reads any `.md` file the vessel user can read, the data directory included; the tool is registered for every rank from ensign (`:1322`, `read_perms`). Recorded as R11, its own follow-up issue. | Widening C1b to put every reader behind the floor: a different change, with each reader's own tests and review surface, in a HIGH batch one round from converging; and for the token, moving it to the keyring already closes every file reader. Fixing R11 here: not BF-908's defect (no token is a `.md` file) and its own contract. |

**Who records what.** The orchestrator posts D26-D31 and R9-R13 on #1605 and pastes R9-R13 into the #1523 register. It opens **two** follow-up issues, each referencing #1605: one for R9 and R10 together (suggested title: "readers that bypass the BF-758 floor, and a containment comparison that fails open (`security/file_access.py:85-95`)"), one for R11 (suggested title: "`standing_orders_lookup` joins `department` into a path unchecked: any `.md` file the vessel user can read"). R12 and R13 need no issue.

### A3.2 Tests first: `tests/test_bf908_floor_and_children.py`

Apply all of A3.2, run the file with `-n 0`, and confirm premise 18 before touching the source.

#### A3.2.1 The header: the safety rule, as it now holds

SEARCH:
```text
a message or a print: a test derives a list of LABELS or a boolean first and asserts on that.
```
REPLACE:
```text
a message or a print: a test derives LABELS, booleans or an exit code into a local first and asserts on that local alone. No
``assert`` calls a function on a child's output or names a result object that holds it: when an assertion fails, pytest's
rewriting prints a call's arguments and the repr of an attribute's owner (review round 1 of C1b found two such guards).
```

#### A3.2.2 The header: rows J8-J16

SEARCH:
```text
J7  a search that drops nothing returns the engine's result unchanged
    Proves: with no protected file under the root, ``act`` returns exactly what the Python engine returned: the same records
    and the same ``count``.
    Does not prove: the same for the rg engine.
K1  no agent command's child sees the token
```
REPLACE:
```text
J7  a search that drops nothing returns the engine's result unchanged
    Proves: with no protected file under the root, ``act`` returns exactly what the Python engine returned: the same records
    and the same ``count``.
    Does not prove: the same for the rg engine.
J8  a loaded config file that is a default is listed once
    Proves: when ``runtime.config_path`` names the checkout's or the home default (spelled with a ``..`` hop),
    ``protected_config_files`` lists each file once, loaded first, and the data directory still leads ``protected_read_roots``.
    Does not prove: anything about two different files that are hard links of one another (residual R3).
J9  a protected first match does not use up the quota (``python`` and ``rg``)
    Proves: with ``max_results=1`` and the loaded config file met first (the unfloored Python engine returns it; the fake rg
    prints it first), ``act`` returns the public match, from the engine named.
    Does not prove: real rg's order (D28: it is not fixed; J5 runs the real binary).
J10 a search that no public match was cut from is not truncated (``python`` and ``rg``)
    Proves: a protected match does not count toward the cap: one public match under a cap of two is ``truncated`` False.
    Does not prove: that ``truncated`` means "more matches exist" (D27, R13: it means "the cap was reached").
J11 a search the cap really cut is truncated (``python`` and ``rg``)
    Proves: three public matches under a cap of two return the first two, ``count`` 2, ``truncated`` True; the protected
    match ahead of them takes no slot.
    Does not prove: the same for matches inside one file under real rg (rg's per-file ``--max-count``).
J12 ``handle_intent`` returns the public match behind a protected one
    Proves: at the boundary the DM pipeline consumes, a search with ``max_results=1`` whose first match is protected returns
    the public match, not ``[]``.
    Does not prove: the DM pipeline's rendering (it renders the list it is given).
J13 ``act`` drops a protected match an engine returned (``python`` and ``rg``)
    Proves: defence in depth: with each engine replaced by one that ignores the floor, ``act`` still returns only the public
    match. Runs without an ``rg`` binary.
    Does not prove: that today's engines ever return one (J9-J11 show they do not).
J14 the floor decides each file once per search
    Proves: for one public file with thirty matching lines, a search builds the floor's roots twice (the root check, the
    search) and makes three decisions (the root, the config file, the public file), never one per line.
    Detector premise: ``_ReadFloor`` looks the floor's functions up on ``probos.security.file_access`` at call time (the
    module's lazy-import convention); if it bound them at import, the counts would fall and the test would fail, not pass.
    Does not prove: wall-clock cost.
J15 rg output whose every line the floor refused is an empty rg result
    Proves: lines that parsed and were refused are not BF-895's "rg and the parser disagree" case: the result is rg's, empty,
    not a fallback to the Python engine.
    Does not prove: BF-895's own fallback (its tests do).
J16 the search's floor decides as ``resolve_for_runtime`` does
    Proves: on a confined vessel (``read_roots`` set), for a public file, the loaded config, a data-directory file, a workspace
    file and a file outside every readable root, ``_ReadFloor.permits`` gives ``resolve_for_runtime``'s answers, which are
    True, False, False, True, False.
    Does not prove: a symlink's target (BF-758's tests cover resolution).
K1  no agent command's child sees the token
```

#### A3.2.3 J4: the two membership checks

SEARCH:
```python
    assert refused["success"] is False
    assert FILE_TOKEN not in str(refused)
    assert sibling["success"] is True  # control: the agent reads, so the refusal above is the floor's
```
REPLACE:
```python
    refusal_holds_token = FILE_TOKEN in str(refused)
    assert refused["success"] is False
    assert refusal_holds_token is False
    assert sibling["success"] is True  # control: the agent reads, so the refusal above is the floor's
```

SEARCH:
```python
    assert sorted(entry["name"] for entry in listing["data"]) == sorted([cfg.name, notes.name])
    assert FILE_TOKEN not in str(listing)
```
REPLACE:
```python
    listing_holds_token = FILE_TOKEN in str(listing)
    assert sorted(entry["name"] for entry in listing["data"]) == sorted([cfg.name, notes.name])
    assert listing_holds_token is False
```

#### A3.2.4 J8, after J3's no-home test

SEARCH:
```python
    assert protected_config_files(None) == [file_access._REPO_DEFAULT_CONFIG.resolve()]


async def test_every_floor_reader_refuses_the_config_file(tmp_path: Path) -> None:
```
REPLACE:
```python
    assert protected_config_files(None) == [file_access._REPO_DEFAULT_CONFIG.resolve()]


@pytest.mark.parametrize("loaded", ["checkout_default", "home_default"])
def test_a_loaded_default_config_file_is_listed_once(tmp_path: Path, loaded: str) -> None:
    checkout = file_access._REPO_DEFAULT_CONFIG.resolve()
    home = (Path.home() / ".probos" / "config.yaml").resolve()
    # Spelled with a ``..`` hop: the floor compares resolved paths, not spellings.
    spelled = {
        "checkout_default": file_access._REPO_DEFAULT_CONFIG.parent / ".." / "config" / "system.yaml",
        "home_default": Path.home() / ".probos" / ".." / ".probos" / "config.yaml",
    }[loaded]
    rt = _runtime(tmp_path, spelled)

    files = protected_config_files(rt)
    roots = protected_read_roots(rt)

    assert files == ([checkout, home] if loaded == "checkout_default" else [home, checkout])
    assert roots == [(tmp_path / "data").resolve(), *files]


async def test_every_floor_reader_refuses_the_config_file(tmp_path: Path) -> None:
```

#### A3.2.5 J9-J16, after J7

SEARCH:
```python
    assert result == engine_result
    assert result["count"] == engine_result["count"]
```
REPLACE:
```python
    assert result == engine_result
    assert result["count"] == engine_result["count"]


# --------------------------------------------------------------------------- #
# J9-J16 -- a protected file never uses up the result quota (amendment A3)
# --------------------------------------------------------------------------- #


def _quota_root(tmp_path: Path, public_matches: int) -> tuple[Path, SimpleNamespace, Path, list[Path]]:
    """A search root whose FIRST file in walk order is the loaded config (one match), then *public_matches* ordinary files.

    ``iter_files`` yields a directory's files sorted by name, so ``aa-vessel.yaml`` is read before ``note-0.txt``.
    """
    root = tmp_path / "project"
    root.mkdir()
    cfg = root / "aa-vessel.yaml"
    cfg.write_text(f"auth:\n  crew_scope_token: {FILE_TOKEN}\n", encoding="utf-8")
    public = [root / f"note-{index}.txt" for index in range(public_matches)]
    for path in public:
        path.write_text(f"{FILE_TOKEN}\n", encoding="utf-8")
    return root, _runtime(tmp_path, cfg), cfg, public


class _FakeRg:
    """An ``rg`` child that prints one ``path<NUL>1:text`` record per path, in the order given, and exits 0.

    Real rg searches in parallel, so its output order is not fixed (D28); this one prints the protected file first every time.
    """

    def __init__(self, paths: list[Path]) -> None:
        self.returncode = 0
        self._stdout = "".join(f"{path}\x001:{FILE_TOKEN}\n" for path in paths).encode("utf-8")

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._stdout, b""


def _use_engine(monkeypatch: pytest.MonkeyPatch, engine: str, rg_prints: list[Path]) -> None:
    """Pin the engine ``act`` takes: the Python engine (no rg), or the real rg engine reading ``_FakeRg``'s output."""
    if engine == "python":
        monkeypatch.setattr(code_search, "_resolve_rg_binary", lambda: None)
        return
    fake = _FakeRg(rg_prints)

    async def _spawn(*_args: object, **_kwargs: object) -> _FakeRg:
        return fake

    monkeypatch.setattr(code_search, "_resolve_rg_binary", lambda: "rg-stub")
    monkeypatch.setattr(code_search.asyncio, "create_subprocess_exec", _spawn)


async def _search(agent: CodeSearchAgent, root: Path, max_results: int) -> dict:
    plan = await agent.decide({"params": {"path": str(root), "pattern": FILE_TOKEN, "max_results": max_results}})
    return await agent.act(plan)


@pytest.mark.parametrize("engine", ["python", "rg"])
async def test_a_protected_first_match_does_not_use_up_the_quota(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, engine: str,
) -> None:
    root, rt, cfg, public = _quota_root(tmp_path, public_matches=1)
    _use_engine(monkeypatch, engine, [cfg, *public])
    agent = CodeSearchAgent(agent_id="cs-9", runtime=rt)
    if engine == "python":
        # Premise: the unfloored engine meets the protected file first, so it would fill a quota of one with it.
        plan = await agent.decide({"params": {"path": str(root), "pattern": FILE_TOKEN, "max_results": 1}})
        assert _paths(agent._search_python(plan, root.resolve())) == [cfg.resolve()]

    result = await _search(agent, root, max_results=1)

    assert result["success"] is True
    assert result["engine"] == engine
    assert _paths(result) == [public[0].resolve()]
    assert result["count"] == 1


@pytest.mark.parametrize("engine", ["python", "rg"])
async def test_a_search_no_public_match_was_cut_from_is_not_truncated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, engine: str,
) -> None:
    root, rt, cfg, public = _quota_root(tmp_path, public_matches=1)
    _use_engine(monkeypatch, engine, [cfg, *public])

    result = await _search(CodeSearchAgent(agent_id="cs-10", runtime=rt), root, max_results=2)

    assert result["engine"] == engine
    assert _paths(result) == [public[0].resolve()]
    assert result["count"] == 1
    assert result["truncated"] is False


@pytest.mark.parametrize("engine", ["python", "rg"])
async def test_a_search_the_cap_really_cut_is_truncated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, engine: str,
) -> None:
    root, rt, cfg, public = _quota_root(tmp_path, public_matches=3)
    _use_engine(monkeypatch, engine, [cfg, *public])

    result = await _search(CodeSearchAgent(agent_id="cs-11", runtime=rt), root, max_results=2)

    assert result["engine"] == engine
    assert _paths(result) == [public[0].resolve(), public[1].resolve()]
    assert result["count"] == 2
    assert result["truncated"] is True


async def test_handle_intent_returns_the_public_match_behind_a_protected_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, rt, _cfg, public = _quota_root(tmp_path, public_matches=1)
    _use_engine(monkeypatch, "python", [])

    result = await CodeSearchAgent(agent_id="cs-12", runtime=rt).handle_intent(
        IntentMessage(intent="search_content", params={"path": str(root), "pattern": FILE_TOKEN, "max_results": 1})
    )

    assert result is not None
    assert result.success is True
    assert [Path(match["path"]).resolve() for match in result.result] == [public[0].resolve()]


@pytest.mark.parametrize("engine", ["python", "rg"])
async def test_act_drops_a_protected_match_an_engine_returned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, engine: str,
) -> None:
    root, rt, cfg, public = _quota_root(tmp_path, public_matches=1)
    unfloored = {
        "success": True,
        "data": [
            {"path": str(cfg), "line": 2, "text": FILE_TOKEN},
            {"path": str(public[0]), "line": 1, "text": FILE_TOKEN},
        ],
        "count": 2,
        "engine": engine,
        "truncated": False,
    }

    def _python(self: CodeSearchAgent, plan: dict, _root: Path, *, floor: object = None) -> dict:
        return dict(unfloored)

    async def _rg(self: CodeSearchAgent, rg: str, plan: dict, _root: Path, *, floor: object = None) -> dict:
        return dict(unfloored)

    monkeypatch.setattr(code_search, "_resolve_rg_binary", (lambda: None) if engine == "python" else (lambda: "rg-stub"))
    monkeypatch.setattr(CodeSearchAgent, "_search_python", _python)
    monkeypatch.setattr(CodeSearchAgent, "_search_rg", _rg)

    result = await _search(CodeSearchAgent(agent_id="cs-13", runtime=rt), root, max_results=5)

    assert result["engine"] == engine
    assert _paths(result) == [public[0].resolve()]
    assert result["count"] == 1


async def test_the_floor_decides_each_file_once_per_search(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, rt, _cfg, public = _quota_root(tmp_path, public_matches=1)
    public[0].write_text("".join(f"{FILE_TOKEN} {index}\n" for index in range(30)), encoding="utf-8")
    _use_engine(monkeypatch, "python", [])
    calls = {"roots_built": 0, "decisions": 0}
    real_roots, real_resolve = file_access.protected_read_roots, file_access.resolve_read_path

    def _roots(runtime: object) -> list[Path]:
        calls["roots_built"] += 1
        return real_roots(runtime)

    def _resolve(raw: str, **kwargs: object) -> Path:
        calls["decisions"] += 1
        return real_resolve(raw, **kwargs)

    monkeypatch.setattr(file_access, "protected_read_roots", _roots)
    monkeypatch.setattr(file_access, "resolve_read_path", _resolve)

    result = await _search(CodeSearchAgent(agent_id="cs-14", runtime=rt), root, max_results=200)

    assert result["count"] == 30  # control: one public file, thirty matching lines
    # The root check builds the roots and decides once; the search builds them once more and decides once per FILE (the
    # config file and the public file), never once per matching line.
    assert calls == {"roots_built": 2, "decisions": 3}


async def test_rg_output_whose_every_line_the_floor_refused_is_an_empty_rg_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, rt, cfg, _public = _quota_root(tmp_path, public_matches=0)
    _use_engine(monkeypatch, "rg", [cfg])

    result = await _search(CodeSearchAgent(agent_id="cs-15", runtime=rt), root, max_results=5)

    # Not a fallback to the Python engine: rg's lines parsed; the floor refused them.
    assert result == {"success": True, "data": [], "count": 0, "engine": "rg", "truncated": False}


def test_the_search_floor_decides_as_resolve_for_runtime_does(tmp_path: Path) -> None:
    base = tmp_path.resolve()  # the workspace root is used as given, so compare canonical paths
    project, cfg, notes = _project(base)
    data = base / "data"
    paths = [
        notes,
        cfg,
        data / "ward_room_notes.txt",
        data / "execution" / "workspaces" / "agent-1" / "draft.txt",
        base / "outside" / "elsewhere.txt",
    ]
    rt = _runtime(base, cfg)
    rt.config.security_infra.read_roots = [str(project)]  # confined: the project and, always, the workspace

    def _admitted(path: Path) -> bool:
        try:
            resolve_for_runtime(str(path), rt)
        except FileAccessDenied:
            return False
        return True

    floor = code_search._ReadFloor(rt)
    decided = [floor.permits(str(path)) for path in paths]

    assert decided == [_admitted(path) for path in paths]
    assert decided == [True, False, False, True, False]
```

#### A3.2.6 K1: every check derived first

SEARCH:
```python
    inheriting = subprocess.run(
        tool_command, shell=True, stdin=subprocess.DEVNULL, capture_output=True, timeout=60,
    )
    assert _labels_seen_in(inheriting.stdout.decode("utf-8", errors="replace"), {"ENV_PROBE": ENV_PROBE}) == ["ENV_PROBE"]

    tool_result = await RunCommandTool(_FakeRuntime()).invoke({"command": tool_command, "timeout": 30})
    assert tool_result.success is True, f"run_command did not run: {tool_result.error}"
    assert tool_result.output["exit_code"] == 0
    assert _prints_an_environment(tool_result.output["stdout"]) is True
    assert _labels_seen_in(tool_result.output["stdout"], _PLANTS) == []

    agent_result = await ShellCommandAgent().handle_intent(
        IntentMessage(intent="run_command", params={"command": agent_command})
    )
    assert agent_result is not None
    assert agent_result.success is True, f"shell agent did not run: {agent_result.error}"
    assert agent_result.result["exit_code"] == 0
    assert _prints_an_environment(agent_result.result["stdout"]) is True
    assert _labels_seen_in(agent_result.result["stdout"], _PLANTS) == []
```
REPLACE:
```python
    inheriting = subprocess.run(
        tool_command, shell=True, stdin=subprocess.DEVNULL, capture_output=True, timeout=60,
    )
    inherited = _labels_seen_in(inheriting.stdout.decode("utf-8", errors="replace"), {"ENV_PROBE": ENV_PROBE})
    assert inherited == ["ENV_PROBE"]

    # Each check on a child's output is derived into a local first; only the locals are asserted (header: the safety rule).
    # RunCommandTool's ``error`` is a refusal, timeout or exception text, never child output, so it may be shown.
    tool_result = await RunCommandTool(_FakeRuntime()).invoke({"command": tool_command, "timeout": 30})
    tool_ran = tool_result.success is True
    tool_stdout = tool_result.output["stdout"] if tool_ran else ""
    tool_checks = {
        "ran": tool_ran,
        "error": tool_result.error,
        "exit_code": tool_result.output["exit_code"] if tool_ran else None,
        "prints_an_environment": _prints_an_environment(tool_stdout),
        "labels_seen": _labels_seen_in(tool_stdout, _PLANTS),
    }
    assert tool_checks == {"ran": True, "error": None, "exit_code": 0, "prints_an_environment": True, "labels_seen": []}

    agent_result = await ShellCommandAgent().handle_intent(
        IntentMessage(intent="run_command", params={"command": agent_command})
    )
    assert agent_result is not None
    # The shell agent's ``error`` may hold the child's stderr: withheld.
    agent_ran = agent_result.success is True
    agent_stdout = agent_result.result["stdout"] if agent_ran else ""
    agent_checks = {
        "ran": agent_ran,
        "exit_code": agent_result.result["exit_code"] if agent_ran else None,
        "prints_an_environment": _prints_an_environment(agent_stdout),
        "labels_seen": _labels_seen_in(agent_stdout, _PLANTS),
    }
    assert agent_checks == {"ran": True, "exit_code": 0, "prints_an_environment": True, "labels_seen": []}
```

#### A3.2.7 K2

SEARCH:
```python
    assert result.success is True, f"run_python did not run: {result.error}"
    names = [pair[0] for pair in json.loads(result.stdout)]
    assert "PATH" in names  # premise: the child printed its environment
    assert _labels_seen_in(result.stdout, _PLANTS) == []
```
REPLACE:
```python
    # The sandbox's ``error`` may hold the child's stderr: withheld. Only derived values are asserted.
    ran = result.success is True
    names = [pair[0] for pair in json.loads(result.stdout)] if ran else []
    checks = {
        "ran": ran,
        "prints_an_environment": "PATH" in names,  # premise: the child printed its environment
        "labels_seen": _labels_seen_in(result.stdout if ran else "", _PLANTS),
    }
    assert checks == {"ran": True, "prints_an_environment": True, "labels_seen": []}
```

#### A3.2.8 K4

SEARCH:
```python
    assert result.success is True, f"run_command did not run: {result.error}"
    assert result.output["exit_code"] == 0
    assert (FILE_TOKEN in result.output["stdout"]) is True
```
REPLACE:
```python
    ran = result.success is True
    checks = {
        "ran": ran,
        "error": result.error,  # RunCommandTool's: never child output
        "exit_code": result.output["exit_code"] if ran else None,
        "read_the_token": ran and FILE_TOKEN in result.output["stdout"],
    }
    assert checks == {"ran": True, "error": None, "exit_code": 0, "read_the_token": True}
```

### A3.3 Source

#### A3.3.1 `src/probos/agents/code_search.py`: `act`, the two engines

SEARCH:
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
REPLACE:
```python
        # BF-908 A3: one read floor per search. Both engines ask it about a file BEFORE they
        # count its matches, so a protected file never uses up max_results (a protected first
        # match made a legitimate search come back empty); _within_floor then re-checks what
        # an engine returned, from the same floor's cached decisions.
        floor = _ReadFloor(getattr(self, "_runtime", None))
        # Prefer the operator's ripgrep binary; fall back to pure Python.
        rg = _resolve_rg_binary()
        if rg is not None:
            rg_result = await self._search_rg(rg, plan, root, floor=floor)
            if rg_result is not None:
                return _within_floor(rg_result, floor)
            # Tier-2: rg failed -> fall through to the Python engine.
        return _within_floor(self._search_python(plan, root, floor=floor), floor)
```

SEARCH:
```python
    async def _search_rg(self, rg: str, plan: dict, root: Path) -> dict | None:
        """Run ``rg`` via subprocess (no shell -> no injection). Returns a result
        dict, or ``None`` to signal the caller to fall back to Python."""
```
REPLACE:
```python
    async def _search_rg(
        self, rg: str, plan: dict, root: Path, *, floor: _ReadFloor | None = None,
    ) -> dict | None:
        """Run ``rg`` via subprocess (no shell -> no injection). Returns a result
        dict, or ``None`` to signal the caller to fall back to Python.

        BF-908 A3: a line in a file *floor* refuses is skipped before it is counted.
        ``--max-count`` is per file, so rg itself still reads such a file; its lines
        never reach the result. ``floor=None`` is the raw engine (the tests' control);
        ``act`` always passes one.
        """
```

SEARCH:
```python
        matches: list[dict] = []
        # BF-895 (#1548): frame on LF only. str.splitlines() also splits at U+2028, U+2029,
        # U+0085, form feed and others, which a file name or a match can hold: it cut a path
        # short and minted a record from the tail of a match. One trailing CR (a CRLF file's
        # line) is part of the terminator, as splitlines() treated it.
        for line in stdout.decode("utf-8", errors="replace").split("\n"):
            parsed = _parse_rg_line(line.removesuffix("\r"))
            if parsed is not None:
                matches.append(parsed)
                if len(matches) >= plan["max_results"]:
                    break
        # BF-895 (#1548): exit 0 means rg found a match. If nothing parsed, the parser
        # and rg disagree: report nothing rather than a false zero, so act() falls back.
        if not matches and (proc.returncode == 0 or stdout):
```
REPLACE:
```python
        matches: list[dict] = []
        parsed_lines = 0
        # BF-895 (#1548): frame on LF only. str.splitlines() also splits at U+2028, U+2029,
        # U+0085, form feed and others, which a file name or a match can hold: it cut a path
        # short and minted a record from the tail of a match. One trailing CR (a CRLF file's
        # line) is part of the terminator, as splitlines() treated it.
        for line in stdout.decode("utf-8", errors="replace").split("\n"):
            parsed = _parse_rg_line(line.removesuffix("\r"))
            if parsed is None:
                continue
            parsed_lines += 1
            # BF-908 A3: skipped before it is counted, so it never uses up max_results.
            if floor is not None and not floor.permits(parsed["path"]):
                continue
            matches.append(parsed)
            if len(matches) >= plan["max_results"]:
                break
        # BF-895 (#1548): exit 0 means rg found a match. If nothing parsed, the parser
        # and rg disagree: report nothing rather than a false zero, so act() falls back.
        # BF-908 A3: lines that parsed and that the floor refused are not that case.
        if not parsed_lines and (proc.returncode == 0 or stdout):
```

SEARCH:
```python
    def _search_python(self, plan: dict, root: Path) -> dict:
        flags = re.IGNORECASE if plan["case_insensitive"] else 0
```
REPLACE:
```python
    def _search_python(self, plan: dict, root: Path, *, floor: _ReadFloor | None = None) -> dict:
        """BF-908 A3: a file *floor* refuses is skipped before it is opened, so it is never
        read and never counted. ``floor=None`` is the raw engine (the tests' control);
        ``act`` always passes one."""
        flags = re.IGNORECASE if plan["case_insensitive"] else 0
```

SEARCH:
```python
        for fp in files:
            if glob and not fp.match(glob):
                continue
            try:
```
REPLACE:
```python
        for fp in files:
            if glob and not fp.match(glob):
                continue
            if floor is not None and not floor.permits(str(fp)):
                continue
            try:
```

#### A3.3.2 `src/probos/agents/code_search.py`: `_ReadFloor`, and `_within_floor` on it

Keep both imports lazy, as the module does at `:140` (J14's detector premise).

SEARCH:
```python
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
```
REPLACE:
```python
class _ReadFloor:
    """BF-908 A3: the read floor for one search, built once, deciding each path once.

    The roots ``resolve_for_runtime`` uses, composed the way ``repository_instructions``
    and ``swe_harness/tools`` already do, so the per-file check costs one resolution,
    not a fresh floor (review round 1 of C1b measured 200 matches costing 200 floors
    and 1,000 ``Path.resolve()`` calls). Built per search, so the next search sees a
    changed runtime.
    """

    def __init__(self, runtime: Any) -> None:
        from probos.security.file_access import (
            permitted_read_roots,
            protected_read_roots,
            workspace_exempt_roots,
        )

        self._protected = protected_read_roots(runtime)
        self._exempt = workspace_exempt_roots(runtime)
        self._permitted = permitted_read_roots(runtime) or None
        self._decided: dict[str, bool] = {}

    def permits(self, path: str) -> bool:
        """True when a reader that calls the floor may open *path*."""
        if path not in self._decided:
            from probos.security.file_access import FileAccessDenied, resolve_read_path

            try:
                resolve_read_path(
                    path, protected_roots=self._protected, exempt_roots=self._exempt,
                    permitted_roots=self._permitted,
                )
            except FileAccessDenied:
                self._decided[path] = False
            else:
                self._decided[path] = True
        return self._decided[path]


def _within_floor(result: dict, floor: _ReadFloor) -> dict:
    """BF-908: drop every match in a file the read floor refuses (defence in depth).

    The root check in ``act`` admits a directory, and a root can hold a protected
    file (the checkout holding ``config/system.yaml``, or a folder above the data
    directory). Both engines skip such a file before counting its matches (A3); this
    re-checks what an engine returned, so an engine that forgets the floor still
    cannot return a protected file's lines. *floor* has decided each path once.
    """
    matches = result.get("data")
    if not result.get("success") or not isinstance(matches, list):
        return result
    kept: list[Any] = []
    for match in matches:
        if isinstance(match, dict) and floor.permits(str(match.get("path", ""))):
            kept.append(match)
```

(The rest of `_within_floor`, from `if len(kept) == len(matches):` to its `return`, is unchanged.)

#### A3.3.3 `src/probos/security/file_access.py`: each config file once

SEARCH:
```python
    Paths, not leaf names: ``config.yaml`` is too common a name to refuse everywhere.
    Not covered: a copy or hard link of the file under another path, and every
    reader that does not call this floor (a shell command, ``run_python``).
    """
```
REPLACE:
```python
    Paths, not leaf names: ``config.yaml`` is too common a name to refuse everywhere.
    Each file once, in that order: the loaded file is usually one of the defaults.
    Not covered: a copy or hard link of the file under another path, and every
    reader that does not call this floor (a shell command, ``run_python``).
    """
```

SEARCH:
```python
        try:
            files.append(Path(candidate).resolve())
        except (OSError, RuntimeError, ValueError):
            continue
    return files
```
REPLACE:
```python
        try:
            resolved = Path(candidate).resolve()
        except (OSError, RuntimeError, ValueError):
            continue
        if resolved not in files:  # BF-908 A3: the loaded file is often a default; list each file once
            files.append(resolved)
    return files
```

### A3.4 Trackers (after the source)

Each SEARCH is a fragment of one line; it occurs once in its file. Then regenerate the ledger (`python scripts/gen_ad_ledger.py`, no `--online`) and run `python scripts/gen_ad_ledger.py --check`; the two regenerated files belong to the candidate.

#### A3.4.1 `PROGRESS.md` line 3 (five fragments)

SEARCH:
```text
so a crew agent's file tools can no longer read the token and
```
REPLACE:
```text
so the file readers that call the floor (`read_file`, `codebase_read_source` and content search) can no longer read the token from a config file, and
```

SEARCH:
```text
A keyring that cannot be read refuses every caller instead of opening the routes.
```
REPLACE:
```text
A keyring that cannot be read, with no token in the config file, refuses every caller instead of opening the routes; a token in the file is still enforced.
```

SEARCH:
```text
is the Captain's own action; no route, crew tool or MCP server reaches it.
```
REPLACE:
```text
is the Captain's own action: no route, crew tool or MCP server manages the token, though a shell command running as the Captain's user could run the CLI (residual).
```

SEARCH:
```text
Content search now drops matches in files the floor refuses.
```
REPLACE:
```text
Content search asks the floor about each file before it counts a match, so a protected file neither shows a line nor uses up the result quota.
```

SEARCH:
```text
and the file while the token stays there.
```
REPLACE:
```text
and the file while the token stays there; readers that do not call the floor (the standing-orders lookup, the red-team verifier, the indexed source and document readers) are a follow-up.
```

#### A3.4.2 `DECISIONS.md`, BF-908 entry (three fragments)

D7 bullet. SEARCH:
```text
are on `protected_read_roots`; content search re-checks every match, which also closes a search rooted above the data directory.
```
REPLACE:
```text
are on `protected_read_roots`, each file once; content search asks the floor about each file before it counts a match, so a protected file neither shows a line nor uses up the result quota, and re-checks every match it returns. This also closes a search rooted above the data directory.
```

"Residual, accepted" bullet. SEARCH:
```text
still run on asyncio's default executor, so a keyring that never answers can hold those processes at exit: a follow-up issue.
```
REPLACE:
```text
still run on asyncio's default executor, so a keyring that never answers can hold those processes at exit: a follow-up issue. Readers that do not call the floor can still return a config file's content: the standing-orders lookup (`cognitive/swe_harness/tools.py:845-857`, which joins its `department` parameter into a path unchecked, so it reaches any `.md` file), the red-team verifier (`agents/red_team.py:154-164`, which puts the content of a file a refused `read_file` named into its result's `expected` field) and the indexed source and document readers. A token moved to the keyring is in no file for them to read; the readers themselves are a follow-up. A containment comparison that raises is skipped, so the floor admits a path the data-directory rule would refuse (`security/file_access.py:85-95`; predates BF-908; a follow-up).
```

"As built" bullet. SEARCH:
```text
J6 sets `include_ignored`: the Python engine's default walk prunes a directory named `data`, so without it the test could not fail.
```
REPLACE:
```text
J6 sets `include_ignored`: the Python engine's default walk prunes a directory named `data`, so without it the test could not fail. Review round 1 of slice C1b found that a protected file's matches used up the search's result quota, so a legitimate search could come back empty through `handle_intent`; both engines now ask the floor about a file before counting its matches, and decide each file once per search (amendment A3, D26-D31). The same round made the children tests derive every check on a child's output into a local before asserting it, so a failure cannot print that output, and listed each config file once.
```

### A3.5 Mutation table (section 9): rows changed and added

| # | File | Line (stripped, exact) | Mutate to | Killed by |
|---|---|---|---|---|
| 28 (killers widened; line unchanged) | `src/probos/security/file_access.py` | `return _protected_data_dir(runtime) + protected_config_files(runtime)` | `return _protected_data_dir(runtime)` | J1, J4, J8 |
| 31 (replaced; the old anchor is gone) | `src/probos/agents/code_search.py` | `return _within_floor(self._search_python(plan, root, floor=floor), floor)` | `return self._search_python(plan, root, floor=floor)` | J13[python] |
| 32 (replaced; the old anchor is gone) | same | `return _within_floor(rg_result, floor)` | `return rg_result` | J13[rg] (runs without an `rg` binary; no longer "not run") |
| 33 (killers changed; line unchanged) | same | `kept.append(match)` | delete the line | J5, J7, J13 |
| 34 (killers changed; line unchanged) | same | `if len(kept) == len(matches):` | `if True:` | J13 (J5 no longer: the engines drop first) |
| 44 | `src/probos/security/file_access.py` | `if resolved not in files:  # BF-908 A3: the loaded file is often a default; list each file once` | `if True:` | J8 (both) |
| 45 | `src/probos/agents/code_search.py` | `floor = _ReadFloor(getattr(self, "_runtime", None))` | `floor = _ReadFloor(None)` | J5, J9 |
| 46 | same | `if floor is not None and not floor.permits(str(fp)):` | `if False:` | J9[python], J10[python], J11[python] |
| 47 | same | `if floor is not None and not floor.permits(parsed["path"]):` | `if False:` | J9[rg], J10[rg], J11[rg] |
| 48 | same | `parsed_lines += 1` | delete the line | J9[rg], J10[rg], J11[rg] (every rg result falls back to the Python engine) |
| 49 | same | `if not parsed_lines and (proc.returncode == 0 or stdout):` | `if not matches and (proc.returncode == 0 or stdout):` | J15 |
| 50 | same | `rg_result = await self._search_rg(rg, plan, root, floor=floor)` | `rg_result = await self._search_rg(rg, plan, root)` | J9[rg], J10[rg], J11[rg] |
| 51 | same | `if path not in self._decided:` | `if True:` | J14 |
| 52 | same | `self._decided[path] = False` | `self._decided[path] = True` | J5, J6, J9, J16 |
| 53 | same | `self._permitted = permitted_read_roots(runtime) or None` | `self._permitted = None` | J16 |
| 54 | same | `self._exempt = workspace_exempt_roots(runtime)` | `self._exempt = []` | J16 |
| 55 | same | `if isinstance(match, dict) and floor.permits(str(match.get("path", ""))):` | `if isinstance(match, dict):` | J13 |
| 56 | same | `return _within_floor(self._search_python(plan, root, floor=floor), floor)` (row 31's line, a second mutant) | `return _within_floor(self._search_python(plan, root), floor)` | J9[python], J10[python], J11[python] |

Rows 29 and 30 are unchanged, line and killers (J1; J3). Every new line above is new text, unique in its file after A3 (`self._decided[path] = True` also occurs once, in the `else` arm, which is why row 52 anchors on the `False` line). Rows 1-27 and 35-43 are untouched by A3.

**Equivalent or excluded mutants:** dropping `floor is not None and` from rows 46-47 (only the raw-engine callers pass `None`, and they would then raise `AttributeError`: killed by J5-J7's controls and the BF-895 tests, not an equivalent but not worth a row); deleting `self._decided[path] = True` (every permitted path is then re-decided and the final lookup raises `KeyError`: killed by every search test); the `logger.info` line in `_within_floor` (log only).

**Campaign of record:** both pinned files change (`security/file_access.py`, `agents/code_search.py`), so rows 28-34 rerun with rows 44-56 on the repaired candidate, recording the base tree and each file's sha256. No other file in the table changes in A3.

### A3.6 Sections 8.2, 10, 13 and 14

**Section 8.2, added files:** `tests/test_ad869_mesh_read_inline.py` (the DM pipeline's mesh-read path, the finding's consumer), `tests/test_capability.py` and `tests/test_ad1260_wellness_domain.py` (each names `CodeSearchAgent` or `search_content`). Unchanged: the rest of 8.2 (`tests/test_bf895_rg_line_parse.py`, `tests/test_ad989_code_search.py`, `tests/test_bf892_spawn_env_guard.py` already cover the engines and the spawn guard), `scripts/check_architecture_principles.py --check`, and `python scripts/gen_ad_ledger.py --check` after A3.4.

**Section 10, rows added or replaced:**

| Test | Proves | Does not prove |
|---|---|---|
| J1-J7 (replaced) | Every floor reader refuses the config files; content search skips a protected file before it counts a match, and re-checks what an engine returns; the vault's lines are dropped under an ancestor root. | Readers that do not call the floor: shell, `run_python` (R2), and the readers in R9. |
| J8 | Each config file is listed once when the loaded file is a default, whatever its spelling; the data directory leads the roots. | Hard links (R3). |
| J9-J11 | A protected match takes no slot in the quota and does not set `truncated`; a real cut still does; on both engines. | Real rg's order (D28). |
| J12 | The boundary the DM pipeline consumes returns the public match. | The pipeline's rendering. |
| J13 | `act` drops a protected match whatever an engine returns. | That today's engines return one (they do not). |
| J14 | One floor per search, one decision per file. | Wall-clock cost. |
| J15 | rg output whose every line the floor refused is an empty rg result, not a fallback. | BF-895's own fallback. |
| J16 | `_ReadFloor` answers as `resolve_for_runtime` does, confinement and the workspace exemption included. | Symlink targets. |
| K1, K2, K4 (added clause) | ... and no assertion renders a child's output when it fails. | |

**Section 13, criteria:**
- Criterion 7 becomes: "The config files are on the floor, each once (J8); content search asks the floor about a file before it counts a match, so a protected file neither leaks a line nor shortens or empties a legitimate search (J9-J12, J15), `act` re-checks what an engine returns (J13), and each file is decided once per search, as `resolve_for_runtime` would (J14, J16); the residuals are pinned or recorded (K4, DECISIONS.md)."
- New criterion 13: "No assertion in `tests/test_bf908_floor_and_children.py` calls a function on a child's output or names a result object that holds it; each check is derived into a local first (K1, K2, K4, J4)."
- New criterion 14: "`PROGRESS.md` and `DECISIONS.md` claim only what the code provides: the floor-aware readers, the fail-closed rule's "no token in the config" condition, and the same-user shell's access to the CLI (D31)."
- Criterion 9 covers rows 1-56.

**Section 14, premises added:**
18. Tests first: against the unrepaired candidate, **red**: J8 (both), J9 (both), J10 (both), J11 (both), J12, J14 (counts 32 and 32) and J16 (`AttributeError`: no `_ReadFloor`). **Green, by design:** J13 (both; the candidate's `_within_floor` already drops), J15 (the candidate's rg result is rg's), and the J4, K1, K2 and K4 changes (they change only what a failure prints).
19. `iter_files` yields a directory's files, sorted, before its subdirectories (`substrate/file_walk.py:160-175`): J9's Python premise asserts it.
20. Monkeypatching `asyncio.create_subprocess_exec` for one test spawns nothing else in that test (the fake is restored at teardown); `tests/test_bf892_spawn_env_guard.py:86` still counts one spawn site in `CodeSearchAgent._search_rg` (A3 adds none).

### A3.7 Self-check: guards the new code could trip

```
CLAIM: the SRP size trigger is not tripped
RUN:   scripts/check_architecture_principles.py:187-188 (500 body lines, 15 direct methods per class)
FOUND: CodeSearchAgent keeps its 7 methods (code_search.py:84-271) and grows by about 25 lines; _ReadFloor has 2;
       file_access.py gains no class or method (A3.3.3 edits a function)
HOLDS: yes

CLAIM: no layer or importer guard is tripped
RUN:   Grep "from probos.security" src/probos/agents -> http_fetch.py:14 (top level), code_search.py:140, :282,
       file_reader.py:106, file_search.py:128, directory_list.py:107 (lazy); Grep "protected_read_roots|
       workspace_exempt_roots|permitted_read_roots" src -> repository_instructions.py:15-19, swe_harness/tools.py:50-54
FOUND: an agents -> security import is established; the new names come from a module code_search already imports;
       no test pins the importers of those three functions (Grep over tests/: only test_bf758 calls them, and
       test_bf908_floor_and_children imports two)
HOLDS: yes

CLAIM: the engines' existing callers keep working
RUN:   Grep "_search_rg|_search_python|_within_floor" tests/
FOUND: test_bf895_rg_line_parse.py:186-226 (positional 3- and 2-argument calls: floor is keyword-only, default None);
       test_bf892_spawn_env_guard.py:86 (qualname key, one spawn site: unchanged); this file's J5-J7 (raw-engine controls)
HOLDS: yes

CLAIM: the AD-1200 and BF-758 suites see no change
RUN:   A3 changes neither resolve_read_path nor resolve_for_runtime; protected_config_files changes only by dropping a
       repeated entry. test_ad1200_instruction_file_access.py:346-353 and test_ad1200_repository_instructions.py:193-201
       patch file_access.resolve_read_path for their own readers
HOLDS: yes (both suites are in 8.2)
```

### A3.8 Residuals and follow-ups (R1-R8 stay)

Worded for the #1523 register and the DECISIONS entry:

- **R9 (follow-up issue, with R10).** Readers that do not call the BF-758 floor can return a config file's content: `StandingOrdersLookupTool.invoke` (`cognitive/swe_harness/tools.py:857`, for a config file stored under a `.md` name, reached through R11), `RedTeamAgent`'s verification (`agents/red_team.py:154-164`: after a refused `read_file` of an existing file it puts the file's content in `VerificationResult.expected`; `rg '\.expected\b' src/probos` finds no reader of that attribute, so where it travels was not enumerated), and the indexed source and document readers (the reviewer's enumeration; not re-verified here). **Reach:** ordinary for the standing-orders tool (registered for every rank from ensign, `tools.py:1322`), not established for the others. For the token, moving it to the keyring closes all of them. Fix: route each through `resolve_for_runtime`, or the bounded reader.
- **R10 (follow-up issue, with R9; P3, injected-only, predates BF-908).** `_longest_match` (`security/file_access.py:85-95`) skips a root whose containment comparison raises `OSError` or `ValueError`, so the floor admits a path the data-directory rule would refuse. Path-resolution failures are refused correctly. Fix: deny the read when evaluating its protected-root containment fails (the permitted-roots use of the same helper already fails closed: no match means refused).
- **R11 (its own follow-up issue; predates BF-908).** `StandingOrdersLookupTool` joins its `department` parameter into `config/standing_orders/departments/{department}.md` unchecked (`tools.py:850-854`): a `..` path, or an absolute one (pathlib's `/` replaces the base), reads any `.md` file the vessel user can read, the data directory included, bypassing the floor. **Reach:** ordinary for any agent holding the SWE tool registry (`read_perms`, ensign and up). Verified by reading, not executed. Fix: validate `department` against the department directory's file names, or resolve and require containment under `config/standing_orders`.
- **R12 (recorded).** The rg engine's child still reads a protected file (rg is told the root, not the floor); its lines reach ProbOS's memory through the pipe and are discarded before any result. **Reach:** none to an agent.
- **R13 (recorded; predates BF-908).** `truncated` means "the cap was reached", not "more matches exist": rg's per-file `--max-count` can cut one file's matches without the engine knowing (D27).

### A3.9 Repair milestone

**M5r (C1b repair), one Builder pass, tests first, about 30-40 tool calls.** (1) A3.2's nine blocks; run `tests/test_bf908_floor_and_children.py -n 0` and confirm premise 18 (the red list fails, the green list passes). (2) A3.3's eight blocks. (3) Rerun the file; then section 8.2 with A3.6's additions, `-n 0`. (4) A3.4's eight fragments; regenerate the ledger and run its `--check`. (5) Report every SEARCH that did not match exactly once; do not improvise. Then the orchestrator: one consolidated focused check, the mutation campaign for rows 28-34 and 44-56, and review round 2 on the **delta** (A3 changes one shared function's output, `protected_config_files`, only by dropping repeats, which J8 pins; the engines' new keyword is private to `code_search.py`).

### A3.10 Prior art and blind spots

- **Internal.** The three-call floor composition is `repository_instructions.py:62-64` and `cognitive/swe_harness/tools.py:329-331`: adopted (D26), with J16 pinning equivalence. BF-895's fallback contract (`code_search.py:207-215`): kept, re-keyed on parsed lines (row 49).
- **External.** A bug-fix amendment with no outside design question: the rule applied is the general one that an authorization filter must run before a result limit, or pages come back short. No web search; `docs/research/reference-projects.md` not consulted.
- **Blind spots checked.** A protected file that is the search root itself (refused by the root check before any engine runs, `code_search.py:142-145`); a single-file root (`files = [root]`: decided once, admitted); rg output whose every line is refused (J15); a non-dict match (dropped, as before); the floor's cost on a large walk (one resolution per walked file, cheaper than the open and read it replaces for a protected file and small against the read of a public one; `iter_files` is bounded by `max_files`).

### A3.11 Verified Against Codebase (2026-10-20, candidate tree `655073e0` in worktree `bf908-a3`)

```
code_search.py   :99 result=report.get("data") (truncated discarded)  :140 lazy file_access import  :143 root check
                 :149-156 act's engine calls  :165 _search_rg signature  :171-172 --max-count per file  :196-209 parse loop,
                 cap :205, BF-895 fallback :209  :221 truncated  :228 _search_python  :244-264 walk loop, fp.open :248
                 :274-297 _within_floor (only caller: act)
file_access.py   :85-95 _longest_match skips OSError/ValueError  :98 resolve_read_path(raw, *, ...)  :190-199 protected_read_roots
                 :202-225 protected_config_files, files.append(Path(candidate).resolve()) :222  :256-266 resolve_for_runtime
file_walk.py     :160 os.walk  :164 sorted(dirnames)  :175 sorted(filenames)
workspace.py     :102-104 an absolute workspace root is returned as given (J16 resolves tmp_path first)
swe_harness/tools.py  :329-331 floor composition  :845-857 standing orders (department joined :850-854; read :857)
                 :1211-1275 RunCommandTool errors (refusal, timeout, exception)  :1322 StandingOrdersLookupTool, read_perms
tools/protocol.py :81-91 ToolResult(output, error, ...) repr includes output; success is a property (error is None)
repository_instructions.py :62-64 floor composition
red_team.py      :154-164 expected=content
tests/test_bf895_rg_line_parse.py :186-226 positional engine calls   tests/test_bf892_spawn_env_guard.py :86
pyproject.toml   :196 addopts = "-n 16 --dist=loadfile" (no --showlocals); scripts/: no showlocals or --tb
DECISIONS.md     :391 D7, :392 Residual, :394 As built (each SEARCH fragment once)   PROGRESS.md :3 (each fragment once)
```

**Absence verified (2026-10-20):**

```
CLAIM: nothing but act calls _within_floor or depends on the engines' old arity
RUN:   Grep "_search_rg|_search_python|_within_floor" tests/ ; Grep "_within_floor" src/
FOUND: tests: bf892:86 (qualname), bf895:186-226 (positional), bf908 J5-J7; src: code_search.py only
HOLDS: yes

CLAIM: no src reader of VerificationResult.expected (R9's "not enumerated" stands as stated)
RUN:   Grep "\.expected\b" src/probos
FOUND: execution/workspace_result_store.py:486-864 (self._identities.expected(), unrelated) only
HOLDS: yes; serialisation of the whole result was not enumerated

CLAIM: pytest runs here without --showlocals, so a local holding child output is not printed on failure
RUN:   Grep "addopts|showlocals|--tb" pyproject.toml ; Grep "showlocals|\"-l\"|--tb" scripts/
FOUND: pyproject.toml:196 only; scripts: no match
HOLDS: yes (a maintainer passing -l by hand would print locals; that is outside the suite's control)
```

### A3.12 Captain

Nothing here needs the Captain. D26-D30 repair defects without weakening a control (the floor is applied earlier, not narrowed); D31 corrects tracker wording to what holds and records three follow-ups (R9-R11) and two notes (R12, R13) rather than widening a HIGH batch; no authority, gate or approval rule changes.

## Amendment A4 (2026-10-20, after review round 2 of slice C1b)

**Amended by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-20

**Trigger.** Review round 2 of the C1b candidate as repaired by A3 (`gpt-6.1-sol`; staged tree `58a3dc0d2109b5d623245b6543e5f6f6e2d5a6c5` on `d935fe07`; full text `logs/review-c1b-r2.md`): NOT READY. Round 1's four findings are resolved and everything else it was asked to verify held (result shape, the BF-895 fallback, floor equivalence for static policy, root shape, per-search cache lifetime, the engines' direct callers, mutation rows 28-34 and 44-56, the ledger). Findings: (1) P2, ordinary reach, **regression introduced by A3**: `_within_floor` reuses the engines' floor, so the final check returns the cached allow for a path retargeted (junction or symlink) before the read, and the protected synthetic text came back through the real Python engine, `handle_intent()` and the DM renderer; (2) P3: A3's "never read" is false, because `iter_files(skip_binary=True)` opens every candidate and reads up to 8 KiB before the floor decides; (3) P3, validation: mutation row 33 as "delete the line" is an `IndentationError`; (4) to record, predates A3: an unexpected exception inside the floor propagates out of the whole search; (5) a measured cost: A3 pays one floor decision per WALKED file (5,000 unmatched files: round 1 1,119 ms, A3 2,821 ms).

**Apply order.** Three groups, in this order: **tests first** (A4.2: apply, run the file `-n 0`, confirm A4.6 premise 21), **source** (A4.3), **trackers** (A4.4). Every SEARCH is written against the **candidate's** files (tree `58a3dc0d`) and occurs exactly once in its file. A4.4's SEARCH blocks are fragments of single long lines in `DECISIONS.md`; replace the fragment in place.

**Supersedes:**
- A3.3's `act` (D26): the final check gets a fresh `_ReadFloor`, built after the engine ran. A4.3.1.
- A3.3's Python engine (D26: "asks it about each file before opening it, so a protected file is never read"): the engine asks at a file's first match, after the open. A4.3.2, A4.3.3.
- A3.10's cost claim ("small against the read of a public one"): withdrawn (D34).
- A3.2's J14 (counts and header); rows J17-J19 added. A4.2.
- Section 9 (as amended by A3): rows 22, 31, 32, 33, 34, 45, 46, 48, 55, 56 change; rows 57-59 added. A4.5.
- Sections 8.2, 10, 13 and 14: A4.6.
- C1b's test count: 32 cases becomes 36 (J17 x2, J18, J19).
- `PROGRESS.md`: unchanged. Its line 3 says content search "asks the floor about each file before it counts a match", which stays true; it claims neither "never read" nor an independent re-check.

### A4.1 Decisions D32-D37

| # | Decision | Rejected alternatives, and why |
|---|---|---|
| D32 | **Finding 1 (P2, ordinary reach, regression from A3): fix with a fresh floor for the final check.** `act` passes `_within_floor` a NEW `_ReadFloor(runtime)`, constructed as the call's second argument, so it is built after the engine returned (Python evaluates arguments left to right; for rg the result already exists). It caches only its own decisions, so each distinct RESULT path is resolved once, at the time of the final check: the cost is one root-list build per search plus one resolution per distinct matched path (at most `max_results`), not per walked file. `_within_floor`'s signature is unchanged (it takes a floor), so the A3 regression is exactly the one-line mutant "pass `floor`" (rows 57, 58), killed by J17 and J18. The engines keep their floor for the quota (D26). | (a) `_within_floor(result, runtime)` building the floor inside: the same behaviour, but the regression is then not a one-line mutant of `act`, and the function no longer states what it consumes. (b) Bind the read to the authorized file identity: the codebase has an identity-checked reader (`read_verified_file`, `PinnedDirectory.read_bytes`, `_same_file`, `security/file_access.py:380,561,721`), which closes the race for the Python engine, but rg opens its own files, so rg's results still need a path check; it reads bounded bytes, not text lines, so the engine's line loop and `_MAX_LINE_BYTES` rule would be rebuilt; and on Windows it queries each handle's path (`:393-463`). Deferred with the race that remains (R15). (c) Re-resolve inside the engine at open time only: D33 does move the Python engine's decision after the open, but without a final fresh check the rg engine (and any future engine) would be authorized by a decision taken before rg read the file. (d) No cache at all (round 1): 1,005 resolutions for 200 matches in one file (the reviewer's count). |
| D33 | **Finding 2 (P3; the I/O predates A3, the claim is A3's): option (c), the Python engine asks the floor at a file's FIRST MATCH.** The check moves inside the match branch; a refused file is left at once (`break`); later matches in a permitted file hit the cache. The rg engine already decides per parsed line (rg prints only matches), so both engines now decide at a file's first match, and a walk with no match makes no floor decision (J19). Because the Python engine now decides after the open, the reviewer's sequence (allowed, then retargeted before the open) is refused by the engine itself; the fresh final check (D32) covers rg. The claim becomes what is true: a refused file is read up to its first match, the walker's binary sniff reads up to 8 KiB of every candidate before either engine sees it (`substrate/file_walk.py:129-137,182`), rg reads it whole (R12), and nothing of any of it reaches a result (R14). Does not weaken a control: what a search may RETURN is unchanged; only the moment the engine asks moves. **Ranked:** (c) first: correct, removes the false claim and finding 5's cost, touches only `code_search.py`, reversible, validation one moved line, one new line, J19 and J14's counts. (a) second: reword only, correct and cheapest to validate, but keeps the measured 2.5x cost on sparse walks. (b) third: the floor before any open needs `iter_files(skip_binary=False)` plus a sniff in the engine, which makes binary files count toward `max_files` (20,000, `file_walk.py:47,186`) so a binary-heavy tree searches fewer text files, or a new pre-sniff predicate on a shared helper (`agents/file_search.py:145` is its other caller); it keeps one decision per walked file; and "never read" would still hold for one engine only, since rg reads every file (R12). | Listed in the ranking. |
| D34 | **Finding 5 (cost): reworded, and removed by D33.** A3.10's "small against the read of a public one" is withdrawn: A3 paid one floor decision per walked file (the reviewer's three-run medians: 5,000 files with no match, round 1 5 resolutions / 1 root-list build / 1,119 ms, A3 5,009 / 2 / 2,821 ms; 200 matches in 200 files, 1,005 / 201 / 189 ms vs 209 / 2 / 77 ms; 200 matches in one file, 1,005 / 201 / 164 ms vs 10 / 2 / 2.8 ms). After A4 the floor's cost is one decision per file WITH a match plus one per distinct result path, and three root-list builds per search (J14, J19 pin the counts; expected for the sparse case: 1 decision, 3 builds). The orchestrator may re-measure in round 3; it is not a gate. | Recording the sparse cost as a residual and keeping A3's shape (option (a)): D33 removes it for less than the cost of explaining it. |
| D35 | **Finding 3 (P3, validation): fix the table.** Rows 22, 33 and 48 are "replace the line with `pass`", not "delete the line": row 33's line is the sole body of an `if` (an `IndentationError` otherwise, INVALID, not killed), and rows 22 and 48 were already run that way. | None. |
| D36 | **Finding 4 (P3, injected-only, predates A3): record; the floor keeps propagating.** `resolve_read_path` already turns path-resolution failures into `FileAccessDenied` (`security/file_access.py:137-139`), so only a bug in the floor raises; propagation fails closed (no result is returned) and is the three-tier rule's tier for security. A catch-all in `permits` would turn a defect in the floor into a silently refused file, narrowing a search's results with no signal. Recorded as R16, extending F-203 (the same module's fail-open containment comparison), where the follow-up decides it with the floor's other error paths. | `except Exception: deny` in `permits`, with a test raising `RuntimeError` from a patched `resolve_read_path`: fail-closed either way, and it hides bugs in a security check. |
| D37 | **Not fixed here: the path-based race that remains (R15).** The fresh floor decides by path at the time of the final check. A link that points at a protected file when an engine reads it and at a permitted one when both checks run still returns the protected line; this holds for the Python engine (the read precedes its first-match decision) and for rg, and it predates A3 (round 1's check was path-based too). **Who can reach it:** an actor that can create and retarget a link under the search root during a search. No ProbOS tool creates symbolic links or junctions (absence below; the only links ProbOS code creates are hard links, made by the backup and by the pinned write's publish step, `infrastructure/backup.py:740` and `security/file_access.py:632-635`, and neither is aimed at a search root; orchestrator's enumeration, `rg 'symlink|os\.link|mklink|junction' src/probos`); an agent's shell can create links (`mklink` is an allowed internal command, `execution/command_gate.py:172`), and that same shell can read the config file directly (R2, pinned by K4). So the race gives no actor a route it does not already have. Fix belongs with identity binding (D32 (b)). | Binding identities now: D32 (b)'s price, for a route that is already open to the only actors who can use it. |

**Who records what.** The orchestrator posts D32-D37 and R14-R16 on #1605 and pastes R14-R16 into the #1523 register: R14 extends F-204, R16 extends F-203, R15 is a new entry (the next free F number) and joins the R9/R10 follow-up issue (F-202, F-203), since it is the same floor's next step. No new issue.

### A4.2 Tests first: `tests/test_bf908_floor_and_children.py`

Apply all four blocks, run the file with `-n 0`, and confirm premise 21 before touching the source.

#### A4.2.1 The header: J14

SEARCH:
```text
    Proves: for one public file with thirty matching lines, a search builds the floor's roots twice (the root check, the
    search) and makes three decisions (the root, the config file, the public file), never one per line.
```
REPLACE:
```text
    Proves: for one public file with thirty matching lines, a search builds the floor's roots three times (the root check,
    the engines' floor, the final check's fresh floor) and makes four decisions (the root; the config file and the public
    file, each at its first match; the public file again, in the final check), never one per line.
```

#### A4.2.2 The header: J17-J19

SEARCH:
```text
    Does not prove: a symlink's target (BF-758's tests cover resolution).
K1  no agent command's child sees the token
```
REPLACE:
```text
    Does not prove: a symlink's target (BF-758's tests cover resolution).
J17 the final check decides with a fresh floor (``python`` and ``rg``)
    Proves: when the floor the engines ask allows the loaded config file (a double, standing for a decision taken before a
    link under the root was retargeted), ``act`` builds a second, real ``_ReadFloor`` after the engine ran and drops that
    file's match: the engines' cached allows are not the final authorization (review round 2 of C1b). Runs without ``rg``.
    Detector premise: ``act`` looks ``_ReadFloor`` up on the module at call time, so the double sees every floor a search
    builds; were it bound elsewhere, ``built`` would be empty and the test would fail, not pass.
    Does not prove: a real link retargeted mid-search (none is created here: creating one needs privileges on Windows), or
    a link changed back before the final check runs (residual R15).
J18 ``handle_intent`` returns no match only the fresh floor refuses
    Proves: the same at the boundary the DM pipeline consumes, on the Python engine (the reviewer's reproduction path).
    Does not prove: the pipeline's rendering (it renders the list it is given).
J19 a walk with no match asks the floor about no file
    Proves: on the Python engine, twenty-one walked files with no match cost the root check's decision and no other: the
    engines' floor is asked at a file's first match, not before every open (A3 asked once per walked file).
    Does not prove: wall-clock cost, or that a refused file is not read (it is, up to its first match: residual R14).
K1  no agent command's child sees the token
```

#### A4.2.3 J14: a shared counter, and the new counts

SEARCH:
```python
async def test_the_floor_decides_each_file_once_per_search(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, rt, _cfg, public = _quota_root(tmp_path, public_matches=1)
    public[0].write_text("".join(f"{FILE_TOKEN} {index}\n" for index in range(30)), encoding="utf-8")
    _use_engine(monkeypatch, "python", [])
    calls = {"roots_built": 0, "decisions": 0}
    real_roots, real_resolve = file_access.protected_read_roots, file_access.resolve_read_path

    def _roots(runtime: object) -> list[Path]:
        calls["roots_built"] += 1
        return real_roots(runtime)

    def _resolve(raw: str, **kwargs: object) -> Path:
        calls["decisions"] += 1
        return real_resolve(raw, **kwargs)

    monkeypatch.setattr(file_access, "protected_read_roots", _roots)
    monkeypatch.setattr(file_access, "resolve_read_path", _resolve)

    result = await _search(CodeSearchAgent(agent_id="cs-14", runtime=rt), root, max_results=200)

    assert result["count"] == 30  # control: one public file, thirty matching lines
    # The root check builds the roots and decides once; the search builds them once more and decides once per FILE (the
    # config file and the public file), never once per matching line.
    assert calls == {"roots_built": 2, "decisions": 3}
```
REPLACE:
```python
def _count_floor_calls(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """Count the floor's root-list builds (``protected_read_roots``) and decisions (``resolve_read_path``) from now on.

    Detector premise: ``_ReadFloor`` and ``resolve_for_runtime`` look both up on ``probos.security.file_access`` at call
    time (the module's lazy-import convention); if either bound them at import, the counts would fall and a test would fail.
    """
    calls = {"roots_built": 0, "decisions": 0}
    real_roots, real_resolve = file_access.protected_read_roots, file_access.resolve_read_path

    def _roots(runtime: object) -> list[Path]:
        calls["roots_built"] += 1
        return real_roots(runtime)

    def _resolve(raw: str, **kwargs: object) -> Path:
        calls["decisions"] += 1
        return real_resolve(raw, **kwargs)

    monkeypatch.setattr(file_access, "protected_read_roots", _roots)
    monkeypatch.setattr(file_access, "resolve_read_path", _resolve)
    return calls


async def test_the_floor_decides_each_file_once_per_search(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, rt, _cfg, public = _quota_root(tmp_path, public_matches=1)
    public[0].write_text("".join(f"{FILE_TOKEN} {index}\n" for index in range(30)), encoding="utf-8")
    _use_engine(monkeypatch, "python", [])
    calls = _count_floor_calls(monkeypatch)

    result = await _search(CodeSearchAgent(agent_id="cs-14", runtime=rt), root, max_results=200)

    assert result["count"] == 30  # control: one public file, thirty matching lines
    # The root check builds the roots and decides once; the engines' floor builds them and decides once per FILE with a
    # match (the config file, the public file); the final check builds a fresh floor and decides once per distinct RESULT
    # path (the public file). Never once per matching line.
    assert calls == {"roots_built": 3, "decisions": 4}
```

#### A4.2.4 J17-J19, after J16

SEARCH:
```python
    assert decided == [_admitted(path) for path in paths]
    assert decided == [True, False, False, True, False]
```
REPLACE:
```python
    assert decided == [_admitted(path) for path in paths]
    assert decided == [True, False, False, True, False]


class _AllowAll:
    """A floor double: the engines' floor as it answered before a link under the root was retargeted (it allows every path)."""

    def __init__(self, _runtime: object) -> None:
        self.asked: list[Path] = []

    def permits(self, path: str) -> bool:
        self.asked.append(Path(path).resolve())
        return True


def _first_floor_allows_all(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """The first ``_ReadFloor`` a search builds is ``_AllowAll``; every later one is the real floor. Returns the floors built."""
    real = code_search._ReadFloor
    built: list[object] = []

    def _floor(runtime: object) -> object:
        floor = _AllowAll(runtime) if not built else real(runtime)
        built.append(floor)
        return floor

    monkeypatch.setattr(code_search, "_ReadFloor", _floor)
    return built


@pytest.mark.parametrize("engine", ["python", "rg"])
async def test_the_final_check_decides_with_a_fresh_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, engine: str,
) -> None:
    root, rt, cfg, public = _quota_root(tmp_path, public_matches=1)
    _use_engine(monkeypatch, engine, [cfg, *public])
    built = _first_floor_allows_all(monkeypatch)

    result = await _search(CodeSearchAgent(agent_id="cs-17", runtime=rt), root, max_results=5)

    assert [type(floor).__name__ for floor in built] == ["_AllowAll", "_ReadFloor"]
    # Premise: the engines' floor was asked about the config file and allowed it, so the engine kept its match.
    assert cfg.resolve() in built[0].asked
    assert result["engine"] == engine
    assert _paths(result) == [public[0].resolve()]
    assert result["count"] == 1


async def test_handle_intent_returns_no_match_only_the_fresh_floor_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, rt, cfg, public = _quota_root(tmp_path, public_matches=1)
    _use_engine(monkeypatch, "python", [])
    built = _first_floor_allows_all(monkeypatch)

    result = await CodeSearchAgent(agent_id="cs-18", runtime=rt).handle_intent(
        IntentMessage(intent="search_content", params={"path": str(root), "pattern": FILE_TOKEN, "max_results": 5})
    )

    assert [type(floor).__name__ for floor in built] == ["_AllowAll", "_ReadFloor"]
    assert cfg.resolve() in built[0].asked
    assert result is not None
    assert result.success is True
    assert [Path(match["path"]).resolve() for match in result.result] == [public[0].resolve()]


async def test_a_walk_with_no_match_asks_the_floor_about_no_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, rt, _cfg, _public = _quota_root(tmp_path, public_matches=20)
    _use_engine(monkeypatch, "python", [])
    assert len(list(code_search.iter_files(root.resolve()))) == 21  # premise: the config file and twenty others are walked
    agent = CodeSearchAgent(agent_id="cs-19", runtime=rt)
    plan = await agent.decide({"params": {"path": str(root), "pattern": "bf908-no-file-holds-this"}})
    calls = _count_floor_calls(monkeypatch)

    result = await agent.act(plan)

    assert result["engine"] == "python"
    assert result["count"] == 0
    # Only the root check decides; the engines' floor and the final check's floor are built and asked about nothing.
    assert calls == {"roots_built": 3, "decisions": 1}
```

### A4.3 Source: `src/probos/agents/code_search.py` (nothing else)

#### A4.3.1 `act`: the final check gets a fresh floor

SEARCH:
```python
        # BF-908 A3: one read floor per search. Both engines ask it about a file BEFORE they
        # count its matches, so a protected file never uses up max_results (a protected first
        # match made a legitimate search come back empty); _within_floor then re-checks what
        # an engine returned, from the same floor's cached decisions.
        floor = _ReadFloor(getattr(self, "_runtime", None))
        # Prefer the operator's ripgrep binary; fall back to pure Python.
        rg = _resolve_rg_binary()
        if rg is not None:
            rg_result = await self._search_rg(rg, plan, root, floor=floor)
            if rg_result is not None:
                return _within_floor(rg_result, floor)
            # Tier-2: rg failed -> fall through to the Python engine.
        return _within_floor(self._search_python(plan, root, floor=floor), floor)
```
REPLACE:
```python
        # BF-908 A3: one read floor per search for the engines. Both ask it about a file before
        # they count its matches, so a protected file never uses up max_results (a protected first
        # match made a legitimate search come back empty).
        floor = _ReadFloor(getattr(self, "_runtime", None))
        # Prefer the operator's ripgrep binary; fall back to pure Python.
        rg = _resolve_rg_binary()
        if rg is not None:
            rg_result = await self._search_rg(rg, plan, root, floor=floor)
            if rg_result is not None:
                # BF-908 A4: a FRESH floor, built after the engine ran, decides what is returned:
                # the engines' cached allows are not the final authorization (review round 2 of
                # C1b returned a protected line through a link retargeted during the search).
                return _within_floor(rg_result, _ReadFloor(getattr(self, "_runtime", None)))
            # Tier-2: rg failed -> fall through to the Python engine.
        return _within_floor(self._search_python(plan, root, floor=floor), _ReadFloor(getattr(self, "_runtime", None)))
```

#### A4.3.2 `_search_python`: the docstring says what is true

SEARCH:
```python
        """BF-908 A3: a file *floor* refuses is skipped before it is opened, so it is never
        read and never counted. ``floor=None`` is the raw engine (the tests' control);
        ``act`` always passes one."""
```
REPLACE:
```python
        """BF-908 A3/A4: no line of a file *floor* refuses is kept or counted. The floor is
        asked at a file's first match, so a walk pays for the files that match, not for every
        file it walks. A refused file is still read up to its first match, and ``iter_files``'s
        binary sniff reads up to 8 KiB of every file first; neither reaches a result.
        ``floor=None`` is the raw engine (the tests' control); ``act`` always passes one."""
```

#### A4.3.3 `_search_python`: ask at the first match

SEARCH:
```python
        for fp in files:
            if glob and not fp.match(glob):
                continue
            if floor is not None and not floor.permits(str(fp)):
                continue
            try:
                with fp.open("r", encoding="utf-8", errors="replace") as fh:
                    for lineno, line in enumerate(fh, start=1):
                        if len(line) > _MAX_LINE_BYTES:
                            continue
                        if rx.search(line):
                            matches.append({
```
REPLACE:
```python
        for fp in files:
            if glob and not fp.match(glob):
                continue
            try:
                with fp.open("r", encoding="utf-8", errors="replace") as fh:
                    for lineno, line in enumerate(fh, start=1):
                        if len(line) > _MAX_LINE_BYTES:
                            continue
                        if rx.search(line):
                            # BF-908 A4: asked at the file's first match, after the open; later matches hit the cache.
                            if floor is not None and not floor.permits(str(fp)):
                                break  # BF-908 A4: a refused file is left at its first match; none of its lines is kept
                            matches.append({
```

#### A4.3.4 `_within_floor`: the docstring names its input

SEARCH:
```python
    re-checks what an engine returned, so an engine that forgets the floor still
    cannot return a protected file's lines. *floor* has decided each path once.
    """
```
REPLACE:
```python
    re-checks what an engine returned, so an engine that forgets the floor still
    cannot return a protected file's lines. *floor* must be a fresh ``_ReadFloor``,
    built after the engine ran, never the one the engine asked (A4): it decides each
    distinct result path once, at this check. The decision is by path (residual R15).
    """
```

### A4.4 Trackers (after the source): `DECISIONS.md` only

Fragment 1 (D7, line 391). SEARCH:
```text
content search asks the floor about each file before it counts a match, so a protected file neither shows a line nor uses up the result quota, and re-checks every match it returns.
```
REPLACE:
```text
content search asks the floor about each file at its first match, before it counts it, so a protected file neither shows a line nor uses up the result quota, and re-checks every match it returns against a fresh floor, built after the search, not the decisions the search cached.
```

Fragment 2 (Residual, accepted, line 392). SEARCH:
```text
(`security/file_access.py:85-95`; predates BF-908; a follow-up).
```
REPLACE:
```text
(`security/file_access.py:85-95`; predates BF-908; a follow-up). The floor decides by path, so a link that points at a protected file when content search reads it and at a permitted file when the floor decides still returns that file's line; only an actor that can change links under the search root during a search can do it, and that actor's shell can read the file directly (a follow-up, with identity-checked reads). Content search reads a protected file up to its first match, and its walker's binary check reads the first 8 KiB of every file; none of it reaches a result.
```

Fragment 3 (As built, line 394; the SEARCH starts with the comma). SEARCH:
```text
, and decide each file once per search (amendment A3, D26-D31).
```
REPLACE (starts with a space):
```text
 (amendment A3, D26-D31). Review round 2 found that the final re-check reused the search's cached decisions, so a link retargeted during a search returned a protected file's line; the re-check now uses a fresh floor, and the Python engine asks at a file's first match rather than before opening each file, so a walk with no match costs no floor decision (amendment A4, D32-D37).
```

Fragment 3 leaves the sentence reading "both engines now ask the floor about a file before counting its matches (amendment A3, D26-D31). Review round 2 ...". Then regenerate the ledger (`python scripts/gen_ad_ledger.py`) and run its `--check`.

### A4.5 Mutation table (section 9): rows changed and added

| # | File | Line (stripped, exact) | Mutate to | Killed by |
|---|---|---|---|---|
| 22 (replacement restated) | `src/probos/runtime.py` | unchanged | replace the line with `pass` | E4 (unchanged; file unchanged) |
| 31 (replaced) | `src/probos/agents/code_search.py` | `return _within_floor(self._search_python(plan, root, floor=floor), _ReadFloor(getattr(self, "_runtime", None)))` | `return self._search_python(plan, root, floor=floor)` | J13[python], J17[python], J18 |
| 32 (replaced) | same | `return _within_floor(rg_result, _ReadFloor(getattr(self, "_runtime", None)))` | `return rg_result` | J13[rg], J17[rg] |
| 33 (replacement fixed) | same | `kept.append(match)` | replace the line with `pass` | J5, J7, J13, J17 |
| 34 (killers changed) | same | `if len(kept) == len(matches):` | `if True:` | J13, J17, J18 |
| 45 (killers changed) | same | `floor = _ReadFloor(getattr(self, "_runtime", None))` | `floor = _ReadFloor(None)` | J9, J10, J11 (J5 no longer: the fresh final floor drops what the engine kept) |
| 46 (line moved, text unchanged) | same | `if floor is not None and not floor.permits(str(fp)):` | `if False:` | J9[python], J10[python], J11[python] |
| 48 (replacement restated) | same | `parsed_lines += 1` | replace the line with `pass` | J9[rg], J10[rg], J11[rg] (unchanged) |
| 55 (killers widened) | same | `if isinstance(match, dict) and floor.permits(str(match.get("path", ""))):` | `if isinstance(match, dict):` | J13, J17, J18 |
| 56 (anchor moved to row 31's new line) | same | row 31's line | `return _within_floor(self._search_python(plan, root), _ReadFloor(getattr(self, "_runtime", None)))` | J9[python], J10[python], J11[python] |
| 57 (new: the A3 regression) | same | row 31's line | `return _within_floor(self._search_python(plan, root, floor=floor), floor)` | J17[python], J18 |
| 58 (new: the A3 regression) | same | row 32's line | `return _within_floor(rg_result, floor)` | J17[rg] |
| 59 (new) | same | `break  # BF-908 A4: a refused file is left at its first match; none of its lines is kept` | replace the line with `pass` | J9[python], J10[python], J11[python] |

Row 51 (`if path not in self._decided:` -> `if True:`) keeps J14 as its killer; the expected counts change (A4.2.3) and the mutant still breaks them (thirty decisions for the public file). Rows 28-30, 44, 47, 49, 50, 52-54 are unchanged, line and killers. Every new line is unique in its file after A4: rows 31 and 32's lines are the only two holding `_ReadFloor(getattr(` inside a `return`, and row 45's line is the only whole line `floor = _ReadFloor(getattr(self, "_runtime", None))`; row 59's comment makes its `break` unique (two bare `break` lines remain).

**Equivalent or excluded mutants:** row 59's `break` -> `continue` (the refused file is read on; each later match is a cache hit and is skipped; the result is the same, only more is read: equivalent for results, not a row); the comment lines in A4.3.1 and A4.3.3 (comments); A4.3.2 and A4.3.4 (docstrings).

**Campaign of record:** of the pinned files only `src/probos/agents/code_search.py` changes. Rerun rows 31-34 and 45-59 (every `code_search.py` row) on the repaired candidate, recording the base tree and the file's sha256; rows 28-30 and 44 (`security/file_access.py`, unchanged) carry over from A3's campaign if that file's sha256 matches; row 22 (`runtime.py`) carries over from C1a's.

### A4.6 Sections 8.2, 10, 13 and 14

**Section 8.2:** no change. A4 changes one file's private functions; their consumers (`tests/test_ad869_mesh_read_inline.py`, `tests/test_ad989_code_search.py`, `tests/test_bf895_rg_line_parse.py`, `tests/test_capability.py`, `tests/test_ad1260_wellness_domain.py`, `tests/test_bf892_spawn_env_guard.py`) are already listed. `python scripts/gen_ad_ledger.py --check` after A4.4.

**Section 10, rows added or replaced:**

| Test | Proves | Does not prove |
|---|---|---|
| J14 (replaced) | Three root-list builds per search and one decision per file with a match plus one per distinct result path, never one per line. | Wall-clock cost. |
| J17 | The final check uses a fresh floor built after the engine ran, on both engines: a match the engines' floor allowed is dropped when the real floor refuses it. | A real link retargeted mid-search; a link changed back before the check (R15). |
| J18 | The same through `handle_intent`. | The DM pipeline's rendering. |
| J19 | A walk with no match asks the floor about no file. | That a refused file is unread (R14). |

**Section 13:** criterion 7 becomes: "The config files are on the floor, each once (J8); content search asks the floor about a file at its first match, before it counts it, so a protected file neither leaks a line nor shortens or empties a legitimate search (J9-J12, J15), and a walk with no match costs no decision (J19); `act` re-checks what an engine returns against a fresh floor built after the engine ran (J13, J17, J18); the floor decides as `resolve_for_runtime` would, each file once per floor (J14, J16); the residuals are pinned or recorded (K4, DECISIONS.md)." Criterion 9 covers rows 1-59.

**Section 14, premises added:**
21. Tests first: against the unrepaired candidate, **red**: J14 (`{"roots_built": 2, "decisions": 3}`), J17 (both: one floor built, and the config file's match kept), J18 (the same), J19 (`{"roots_built": 2, "decisions": 22}`). **Green:** every other test in the file.
22. `act` reads `_ReadFloor` from the module's globals at call time (`code_search.py:153,159,161`), so `monkeypatch.setattr(code_search, "_ReadFloor", ...)` replaces every floor a search builds (J17's detector premise).

### A4.7 Self-check: guards the new code could trip

```
CLAIM: the SRP size trigger is not tripped
RUN:   scripts/check_architecture_principles.py:187-188 (500 body lines, 15 direct methods per class)
FOUND: CodeSearchAgent keeps its 7 methods; its body grows by about 4 lines (comments); _ReadFloor and _within_floor
       change only in a docstring
HOLDS: yes

CLAIM: no importer or layer guard is tripped
RUN:   A4.3 adds no import; A4.2 adds none (code_search.iter_files is the module's own import, code_search.py:33)
HOLDS: yes

CLAIM: the engines' direct callers keep working
RUN:   Grep "_ReadFloor|_within_floor" src tests -> code_search.py only, and this file (:76, :85, :630)
       test_bf895_rg_line_parse.py:186-226 and J5-J7 call the engines with floor=None: the moved check sits behind
       `floor is not None`, so the raw engines are unchanged
HOLDS: yes

CLAIM: BF-892's spawn census and the AD-989 suite see no change
RUN:   A4 adds no subprocess call; _search_rg is untouched
HOLDS: yes
```

### A4.8 Residuals and follow-ups (R1-R13 stay)

Worded for the #1523 register and the DECISIONS entry:

- **R14 (recorded; extends F-204; reach none to an agent).** Content search's Python engine reads a refused file up to its first match, and its walker's binary sniff (`iter_files(skip_binary=True)`, `substrate/file_walk.py:129-137,182`) opens every candidate file and reads up to 8 KiB before either engine sees it; rg reads a protected file whole (R12). None of it reaches a result.
- **R15 (new register entry; joins the R9/R10 follow-up issue; predates A3).** The floor decides by path. A link that points at a protected file when an engine reads it and at a permitted file when the engine's first-match decision and the fresh final check run still returns a protected line, on both engines. **Reach:** an actor that can create and retarget a link under the search root during a search; no ProbOS tool creates symbolic links or junctions (hard links are made only by the backup and the pinned write's publish step, `infrastructure/backup.py:740` and `security/file_access.py:632-635`), and an agent's shell, which can create links, already reads the file directly (R2, K4). Fix: identity-checked reads for the Python engine (`read_verified_file`, `security/file_access.py:721`) and a no-links rule for content search; rg needs its own answer (it opens its files itself).
- **R16 (recorded; extends F-203; P3, injected-only; predates A3).** An exception inside the floor that is not a path-resolution failure (a bug: `resolve_read_path` already turns `OSError`, `RuntimeError` and `ValueError` from `Path.resolve()` into a denial, `security/file_access.py:137-139`) propagates out of the whole search. It fails closed (nothing is returned); turning it into a per-file denial would hide the bug. Decide with F-203's error paths.

### A4.9 Repair milestone

**M5r2 (C1b repair 2), one Builder pass, tests first, about 20-28 tool calls.** (1) A4.2's four blocks; run `tests/test_bf908_floor_and_children.py -n 0` and confirm premise 21. (2) A4.3's four blocks, all in `code_search.py`. (3) Rerun the file; then section 8.2, `-n 0`. (4) A4.4's three fragments; regenerate the ledger and run its `--check`. (5) Report every SEARCH that did not match exactly once; do not improvise. Then the orchestrator: one consolidated focused check, the campaign for rows 31-34 and 45-59, and review round 3 on the **delta** (A4 changes private functions of one module; no shared contract moves).

### A4.10 Prior art and blind spots

- **Internal.** The identity-checked reader (`PinnedDirectory`, `read_verified_file`, `_same_file`, `security/file_access.py:380-735`, AD-1200) is the codebase's answer to check-then-open races: considered for D32 (b) and deferred to R15, since rg cannot use it. The three-call floor composition (A3.10) is unchanged.
- **External.** The race is CWE-367 (time-of-check, time-of-use, https://cwe.mitre.org/data/definitions/367.html); its standard mitigation, checking the opened object rather than the name, is D32 (b). A bug-fix amendment with no other outside design question: no web search; `docs/research/reference-projects.md` not consulted.
- **Blind spots checked.** A single-file root (`files = [root]`: decided at its first match, as any file); a permitted file with many matches (one decision, then cache hits: J14); an empty result (the fresh floor is built and asked nothing: J19); a refused file met before the cap (left at once, no slot taken: J9); a non-dict match (dropped by the final check, as before); the reverse retarget (a link pointing at a public file at the read and at a protected one at a check: a false refusal, safe).

### A4.11 Verified Against Codebase (2026-10-20, candidate tree `58a3dc0d` in worktree `bf908-a4`)

```
code_search.py   :33 from probos.substrate.file_walk import iter_files  :149-161 act's floor and engine calls
                 :248-251 _search_python signature, docstring  :261-265 iter_files(root, skip_binary=True, ...)
                 :267-287 walk loop (pre-open check :270-271, open :273, append :278)  :299-335 _ReadFloor (cache :319,
                 :323-335)  :338-357 _within_floor (permits :352, kept.append :353)
file_walk.py     :47 DEFAULT_MAX_FILES 20000  :48 _SNIFF_BYTES 8192  :129-137 is_binary opens "rb", reads sniff_bytes
                 :182 if skip_binary and is_binary(fp)  :186 yielded >= max_files
file_search.py   :145 iter_files(p, skip_binary=False) (the walker's other caller)
file_access.py   :98 resolve_read_path  :137-139 Path.resolve() errors -> FileAccessDenied  :380 _same_file
                 :393-463 Windows handle-path API  :561 PinnedDirectory.read_bytes  :721 read_verified_file
command_gate.py  :172 "mklink" among cmd internal commands
tests/test_bf908_floor_and_children.py  :73-78 J14 header  :86-88 J16 header end, K1  :425-470 _quota_root, _FakeRg,
                 _use_engine, _search  :571-594 J14  :630-634 J16 end
DECISIONS.md     :391 D7 fragment  :392 Residual fragment  :394 As built fragment (each once in the file)
PROGRESS.md      :3 "asks the floor about each file before it counts a match" (still true; unchanged)
#1523 register   F-202 R9, F-203 R10, F-204 R12, F-205 R13 (gh issue view 1523 --comments)
```

**Absence verified (2026-10-20):**

```
CLAIM: nothing but act and this test file uses _ReadFloor or _within_floor
RUN:   Grep "_ReadFloor|_within_floor" {src,tests}/**/*.py
FOUND: code_search.py:151,153,159,161,171,248,299,338; test_bf908_floor_and_children.py:76,85,630
HOLDS: yes

CLAIM: no ProbOS tool creates a symlink or junction (R15's reach)
RUN:   Grep "symlink_to|os\.symlink|_winapi\.CreateJunction|mklink" src/probos
FOUND: command_gate.py:172 and command_policy.py:126 ("mklink" in the cmd internal-command lists, i.e. a shell can) only
HOLDS: yes: only a shell command creates links

CLAIM: DECISIONS.md and PROGRESS.md hold no other "never read" or "independent re-check" claim for BF-908
RUN:   Grep "never read|re-check|independen|before it is opened" DECISIONS.md (BF-908 entry :381-395); Grep "content search" PROGRESS.md
FOUND: DECISIONS.md:391 (fragment 1) only within the entry; PROGRESS.md:3 two sentences, neither claiming either
HOLDS: yes
```

### A4.12 Captain

Nothing here needs the Captain. D32 and D33 restore and strengthen the final check without narrowing what the floor refuses; D33 withdraws a claim that was not true rather than weakening a control (what a search may return is unchanged); D35 fixes the table; D36 keeps the security tier's propagate rule; D37 and R14-R16 record what remains with its reach. No authority, gate or approval rule changes.

## Amendment A5 (2026-10-20, after review round 3 of slice C1b)

**Amended by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-20

**Trigger.** Review round 3 of the C1b candidate as repaired by A4 (staged tree `81c7bd8847380f10ea3d2d63adae73cd39522a44` on `dc9c3e5b`; full text `logs/review-c1b-r3.md`) found that round 2's three findings are resolved. The retarget scenario is refused, the sparse-walk cost is back to round 1's, and all 59 mutation rows are killed. It found one new problem. Finding (P3, injected-only, **regression introduced by A4**): A4.3.3 moved `floor.permits(str(fp))` inside the Python engine's `try: with fp.open(...)` (`code_search.py:274-292`). Its `except OSError: continue` therefore also catches an `OSError` raised inside the floor. A floor defect then becomes `success=true` with that file left out, and the DM renderer shows it as an ordinary result. A3 propagated it, and D36 and R16 say it must propagate. A `RuntimeError` propagated in both A3 and A4. Ordinary `Path.resolve()` failures are turned into per-file denials by `resolve_read_path` (`security/file_access.py:137-139`) and are not affected.

**Apply order.** Three groups, in this order:
1. **Tests first** (A5.2). Apply them, run the file `-n 0` and confirm premise 23.
2. **Source** (A5.3).
3. **Trackers** (A5.4).

Every SEARCH is written against the candidate's files (tree `81c7bd88`) and occurs exactly once in its file. The working tree is CRLF and the index LF, so match line by line.

**Supersedes:**
- A4.3.3's Python engine: the decision stays at a file's first match, but the file's open, read and `OSError` handler move into `_text_lines`. A5.3.
- R16's wording: A5.7.
- Section 9: rows 60-62 are added. A5.5.
- C1b's test count goes from 36 to 40 (J20 x2, J21, J22).
- `PROGRESS.md`: unchanged. Its line 3 makes no claim about error handling.

### A5.1 Decisions D38-D41

| # | Decision | Rejected alternatives, and why |
|---|---|---|
| D38 | **The finding (P3, injected-only, regression from A4): fix it by moving the file's I/O and its handler into a generator, `_text_lines(fp)`.** The engine's loop body iterates the generator: the line-length check, the regex, the floor's first-match decision, the append and the cap. Python does not throw an exception raised in a `for` body into the generator being iterated. So the generator's `except OSError` covers only its own `open` and `next`, and an `OSError` from the floor, or from any statement later added to the body, propagates unchanged in type and identity, as in A3. Real I/O behaves as before A5: an open failure skips the file, and a read failure ends it while keeping the lines already matched. J22 pins both, and no test pinned either before (Absence below). **Closing:** a `break` drops the generator. CPython's reference counting then closes it at once: `GeneratorExit` at the `yield` leaves the `with`, which closes the file. An exception unwinding `_search_python` drops it the same way. **Cost:** one generator frame per walked file and one `yield from` hop per line; measured by the orchestrator on 600,000 lines with no match (four interleaved runs of each tree, medians): A4 537 ms, A5 545 ms (+1.5%). This does not weaken a control: what a search may return is unchanged, and a floor defect fails closed again. | **(a) Flag** (`deciding = True/False` around the call; `except OSError: if deciding: raise`). This is the smallest diff (about 5 lines, no reindent) and keeps the exception type. But the handler still wraps the whole body, so the next `OSError`-capable statement added there reopens the hole. It also adds per-file state with two mutation rows; killing the reset row needs a read failure after a permitted first match in the same file. Ranked second. **(b) Re-raise the floor's `OSError` as a non-`OSError`** (a new `_FloorDefect(RuntimeError)` raised from the original). This changes the type that propagates (A3 and R16 say `OSError`), adds an exception class, and keeps (a)'s whole-body weakness for every other call. **(c) Manual `next()`** with a `try` around the open and around each `next`. It has D38's property inline, but turns the `for` into a `while True` with three handlers (open, `StopIteration`, `OSError`), adds about 10 lines and more rows; the generator is the idiomatic form of the same thing. **(d) Collect, then decide**: buffer a file's matches inside the `try` and ask the floor once after it. The decision would follow the whole file's read (a refused file is read whole, not to its first match, which widens R14). It buffers up to `max_results` lines and re-derives truncation: a larger change for the same property. **(e) `except OSError: deny` in `permits`**: rejected by D36, because it hides floor bugs. |
| D39 | **Tests.** **J20** (`act`, both engines): the floor raises a sentinel `OSError` for the config file's name, and the search raises that exact object. The Python variant is the discriminating one (red on A4). The rg variant is the control: its floor call (`code_search.py:223`) is outside every handler (the `try` at `:195-207` ends before it). **J21** (`handle_intent`, the DM boundary): the same, on the Python engine. **J22** (a guard, green before and after): an unopenable file contributes nothing, a file whose read fails after one matching line keeps that line, and the walk goes on. The injection patches `file_access.resolve_read_path`, which `_ReadFloor.permits` looks up at call time (`code_search.py:329`, J14's premise), and only for the config file's name; the root check and every other path delegate to the real function. No J20-J22 test starts a child, so the file's child-output rule is untouched. | One test with a patched `_ReadFloor.permits`: it would not exercise the floor's real lookup path, and J14's premise already shows the module lookup works. |
| D40 | **R16 is reworded** (A5.7) to say the floor's exceptions propagate from both engines whatever their type, and that J20 and J21 pin it. No new residual. | None. |
| D41 | **Round 4 reviews the delta only.** A5 changes one private method and adds one private module function in one module; no shared contract moves. A regression introduced by A5 in round 4 goes to the Captain (brake rule), not to a fifth round. | A whole-candidate round 4: the converged parts were reviewed in rounds 1-3 and are unchanged. |

**Who records what.** The orchestrator posts D38-D41 and the new R16 wording on #1605, and updates R16 in the #1523 register (F-203). No new issue.

### A5.2 Tests first: `tests/test_bf908_floor_and_children.py`

Apply all three blocks, run the file `-n 0`, and confirm premise 23 before touching the source.

#### A5.2.1 The import

SEARCH:
```python
from pathlib import Path
from types import SimpleNamespace
```
REPLACE:
```python
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
```

#### A5.2.2 The header: J20-J22

SEARCH:
```text
    Does not prove: wall-clock cost, or that a refused file is not read (it is, up to its first match: residual R14).
K1  no agent command's child sees the token
```
REPLACE:
```text
    Does not prove: wall-clock cost, or that a refused file is not read (it is, up to its first match: residual R14).
J20 an ``OSError`` inside the floor propagates from the search (``python`` and ``rg``)
    Proves: when the floor's decision raises an ``OSError`` for the loaded config file (a defect in the floor, not a
    path-resolution failure, which ``resolve_read_path`` turns into a denial), ``act`` raises that same exception object:
    the Python engine's file-I/O handler does not take it for an unreadable file (review round 3 of C1b; A4 returned the
    public match and dropped the error). The rg variant is the control: its floor call was never under a handler.
    Detector premise: ``_ReadFloor.permits`` looks ``resolve_read_path`` up on ``probos.security.file_access`` at call time
    (J14's premise); were it bound at import, nothing would raise and the test would fail, not pass.
    Does not prove: what the mesh does with the exception.
J21 ``handle_intent`` propagates an ``OSError`` inside the floor
    Proves: the same at the boundary the DM pipeline consumes, on the Python engine.
    Does not prove: the pipeline's handling of an agent that raises.
J22 a file that cannot be opened or read still degrades
    Proves: on the Python engine, a file whose text-mode open raises ``OSError`` contributes nothing, a file whose read fails
    after one matching line keeps that line, and the walk goes on to the next file: the handler still covers the file's own
    open and read. Only text-mode opens of those two names fail; the walker's binary sniff (``"rb"``) reads them as they are.
    Does not prove: a real disk or permission error (both are injected).
K1  no agent command's child sees the token
```

#### A5.2.3 J20-J22, after J19

SEARCH:
```python
    # Only the root check decides; the engines' floor and the final check's floor are built and asked about nothing.
    assert calls == {"roots_built": 3, "decisions": 1}
```
REPLACE:
```python
    # Only the root check decides; the engines' floor and the final check's floor are built and asked about nothing.
    assert calls == {"roots_built": 3, "decisions": 1}


def _floor_raises_oserror_on(monkeypatch: pytest.MonkeyPatch, target: Path) -> OSError:
    """From now on the floor's decision raises a sentinel ``OSError`` for *target*'s name and decides every other path as before.

    R16's defect: an error inside the floor that is not a path-resolution failure (``resolve_read_path`` turns those into a
    denial). ``_ReadFloor.permits`` looks ``resolve_read_path`` up on ``probos.security.file_access`` at call time (J14's
    premise), so the sentinel reaches every floor a search builds; the root check's path delegates to the real function.
    """
    injected = OSError("bf908-injected floor defect")
    real_resolve = file_access.resolve_read_path

    def _resolve(raw: str, **kwargs: object) -> Path:
        if Path(raw).name == target.name:
            raise injected
        return real_resolve(raw, **kwargs)

    monkeypatch.setattr(file_access, "resolve_read_path", _resolve)
    return injected


@pytest.mark.parametrize("engine", ["python", "rg"])
async def test_an_oserror_inside_the_floor_propagates_from_the_search(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, engine: str,
) -> None:
    root, rt, cfg, public = _quota_root(tmp_path, public_matches=1)
    _use_engine(monkeypatch, engine, [cfg, *public])
    injected = _floor_raises_oserror_on(monkeypatch, cfg)

    with pytest.raises(OSError) as raised:
        await _search(CodeSearchAgent(agent_id="cs-20", runtime=rt), root, max_results=5)

    # The floor's own exception, unchanged: not taken for an unreadable file (A4 returned the public match instead).
    assert raised.value is injected


async def test_handle_intent_propagates_an_oserror_inside_the_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, rt, cfg, _public = _quota_root(tmp_path, public_matches=1)
    _use_engine(monkeypatch, "python", [])
    injected = _floor_raises_oserror_on(monkeypatch, cfg)

    with pytest.raises(OSError) as raised:
        await CodeSearchAgent(agent_id="cs-21", runtime=rt).handle_intent(
            IntentMessage(intent="search_content", params={"path": str(root), "pattern": FILE_TOKEN, "max_results": 5})
        )

    assert raised.value is injected


class _ReadFailsAfterOneLine:
    """A text file handle that yields one matching line and then fails, as a read error part-way through a file would."""

    def __enter__(self) -> _ReadFailsAfterOneLine:
        return self

    def __exit__(self, *_exc: object) -> bool:
        return False

    def __iter__(self) -> Iterator[str]:
        yield f"{FILE_TOKEN}\n"
        raise OSError("bf908-injected read failure")


async def test_a_file_that_cannot_be_opened_or_read_still_degrades(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, rt, _cfg, public = _quota_root(tmp_path, public_matches=2)
    unopenable = root / "ab-unopenable.txt"  # walked after the config file, before note-0.txt
    breaks = root / "note-0a-breaks.txt"  # walked between note-0.txt and note-1.txt
    for path in (unopenable, breaks):
        path.write_text(f"{FILE_TOKEN}\n", encoding="utf-8")
    _use_engine(monkeypatch, "python", [])
    real_open = Path.open

    def _open(self: Path, mode: str = "r", *args: object, **kwargs: object) -> object:
        # Text-mode opens of the two names only: the walker's binary sniff ("rb") reads every file as it is.
        if mode == "r" and self.name == unopenable.name:
            raise OSError("bf908-injected open failure")
        if mode == "r" and self.name == breaks.name:
            return _ReadFailsAfterOneLine()
        return real_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", _open)

    result = await _search(CodeSearchAgent(agent_id="cs-22", runtime=rt), root, max_results=10)

    assert result["success"] is True
    assert result["engine"] == "python"
    # The unopenable file contributes nothing; the failed read keeps the line read before it; the walk goes on.
    assert _paths(result) == [public[0].resolve(), breaks.resolve(), public[1].resolve()]
    assert result["count"] == 3
```

### A5.3 Source: `src/probos/agents/code_search.py` (nothing else)

#### A5.3.1 The import

SEARCH:
```python
import sys
from pathlib import Path
from typing import Any
```
REPLACE:
```python
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any
```

#### A5.3.2 `_search_python`: the loop iterates `_text_lines`

SEARCH:
```python
            try:
                with fp.open("r", encoding="utf-8", errors="replace") as fh:
                    for lineno, line in enumerate(fh, start=1):
                        if len(line) > _MAX_LINE_BYTES:
                            continue
                        if rx.search(line):
                            # BF-908 A4: asked at the file's first match, after the open; later matches hit the cache.
                            if floor is not None and not floor.permits(str(fp)):
                                break  # BF-908 A4: a refused file is left at its first match; none of its lines is kept
                            matches.append({
                                "path": str(fp),
                                "line": lineno,
                                "text": line.rstrip("\n")[:_LINE_PREVIEW_CHARS],
                            })
                            if len(matches) >= max_results:
                                truncated = True
                                break
            except OSError:
                continue
            if truncated:
```
REPLACE:
```python
            # BF-908 A5: the file's I/O and its OSError handler live in _text_lines; nothing in this
            # body (the floor's decision included) runs under that handler, so a floor defect propagates.
            for lineno, line in _text_lines(fp):
                if len(line) > _MAX_LINE_BYTES:
                    continue
                if rx.search(line):
                    # BF-908 A4: asked at the file's first match, after the open; later matches hit the cache.
                    if floor is not None and not floor.permits(str(fp)):
                        break  # BF-908 A4: a refused file is left at its first match; none of its lines is kept
                    matches.append({
                        "path": str(fp),
                        "line": lineno,
                        "text": line.rstrip("\n")[:_LINE_PREVIEW_CHARS],
                    })
                    if len(matches) >= max_results:
                        truncated = True
                        break
            if truncated:
```

#### A5.3.3 `_text_lines`, before `_ReadFloor`

SEARCH:
```python
class _ReadFloor:
    """BF-908 A3: the read floor for one search, built once, deciding each path once.
```
REPLACE:
```python
def _text_lines(fp: Path) -> Iterator[tuple[int, str]]:
    """BF-908 A5: ``(line number, line)`` for each line of *fp*, read as UTF-8 with replacement.

    A failure to open or read the file ends it: the lines already yielded stand and the engine
    goes on to the next file, as before A5. Only this generator's own I/O sits under the handler.
    An exception raised in the caller's loop body is not thrown into the generator it iterates,
    so an ``OSError`` from the read floor's decision propagates (D36, R16; review round 3 of
    C1b). A loop that breaks out drops the generator, and CPython closes it at once, which
    closes the file.
    """
    try:
        with fp.open("r", encoding="utf-8", errors="replace") as fh:
            yield from enumerate(fh, start=1)
    except OSError:  # BF-908 A5: the file cannot be opened or read; it contributes no further line
        return


class _ReadFloor:
    """BF-908 A3: the read floor for one search, built once, deciding each path once.
```

### A5.4 Trackers (after the source): `DECISIONS.md` only

One fragment, in the BF-908 "As built" line (line 394). SEARCH:
```text
walk with no match costs no floor decision (amendment A4, D32-D37).
```
REPLACE:
```text
walk with no match costs no floor decision (amendment A4, D32-D37). Review round 3 found that A4's move put the floor's decision under the Python engine's file-I/O handler, so an `OSError` from a defect in the floor read as an unreadable file and the search returned without that file; the engine's file I/O and its handler now live in a generator the decision runs outside, so a floor defect propagates on both engines (amendment A5, D38-D41).
```
Then regenerate the ledger (`python scripts/gen_ad_ledger.py`) and run its `--check`.

### A5.5 Mutation table (section 9): rows added

| # | File | Line (stripped, exact) | Mutate to | Killed by |
|---|---|---|---|---|
| 60 (new) | `src/probos/agents/code_search.py` | `except OSError:  # BF-908 A5: the file cannot be opened or read; it contributes no further line` | `except ValueError:` | J22 |
| 61 (new: the handler removed) | same | `for lineno, line in _text_lines(fp):` | `for lineno, line in enumerate(fp.open("r", encoding="utf-8", errors="replace"), start=1):` | J22 |
| 62 (new) | same | `yield from enumerate(fh, start=1)` | `yield from ()` | J9[python], J10[python], J11[python], J22 |

Rows 31-34 and 45-59 are unchanged, line and killers. Rows 46 and 59 move (dedented) with their stripped text unchanged, and they stay unique: row 47's floor call names `parsed["path"]`, and row 59's comment sets its `break` apart.

The three new lines are unique after A5:
- Row 60's comment sets it apart from the `except OSError:` at the old `:387`.
- Row 61's line is new.
- Row 62 replaces the removed `for lineno, line in enumerate(fh, start=1):`, and the file has no other `yield` (Absence below).

**A4's regression is not a one-line mutant here.** Restoring it means wrapping the loop body back in a `try`. Premise 23 (J20[python] and J21 red on tree `81c7bd88`) is its evidence.

**Equivalent mutants:**
- Row 60's `return` -> `pass`: the generator ends either way.
- Dropping the `with`: the file is not closed, but the results are the same.
- The comment lines.

**Campaign of record:** of the pinned files, only `code_search.py` changes. Rerun rows 31-34 and 45-62 on the repaired candidate, recording the base tree and the file's sha256. Rows 28-30 and 44 (`security/file_access.py`) carry over from round 3's campaign if that file's sha256 matches. Row 22 carries over from C1a.

### A5.6 Sections 8.2, 10, 13 and 14

**Section 8.2:** no change. A5 changes one private method and adds one private function in an already-listed module. Run `python scripts/gen_ad_ledger.py --check` after A5.4.

**Section 10, rows added:**

| Test | Proves | Does not prove |
|---|---|---|
| J20 | An `OSError` inside the floor propagates from `act` as the same object, on both engines. | The mesh's handling. |
| J21 | The same through `handle_intent`. | The DM pipeline's handling. |
| J22 | An unopenable file and a failed read still degrade, and the walk goes on. | A real disk or permission error. |

**Section 13:**
- Criterion 7 gains: "a defect in the floor propagates from both engines, never taken for an unreadable file (J20, J21), while a real open or read failure still degrades (J22)".
- Criterion 9 covers rows 1-62.

**Section 14, premises added:**

23. **Tests first.** Against tree `81c7bd88`, these are **red**: J20[python] (`DID NOT RAISE`; A4 returns the public match) and J21 (the same). These are **green**: J20[rg], J22, and every other test in the file.

24. Python does not throw an exception raised in a `for` body into the generator being iterated (generator semantics: only `throw()` and `close()` enter it). J20[python] is the empirical check.

### A5.7 Residuals (R1-R15 stay; R16 reworded)

- **R16 (recorded; extends F-203; P3, injected-only; predates A3).** An exception inside the floor that is not a path-resolution failure propagates out of the whole search, on both engines and whatever its type, `OSError` included. It is a bug, because `resolve_read_path` already turns `OSError`, `RuntimeError` and `ValueError` from `Path.resolve()` into a denial (`security/file_access.py:137-139`). The Python engine's I/O handler covers only the file's own open and read (A5, J20, J21). It fails closed: nothing is returned. Turning it into a per-file denial would hide the bug. Decide it with F-203's error paths.

### A5.8 Self-check: guards the new code could trip

```
CLAIM: SRP size trigger not tripped
RUN:   scripts/check_architecture_principles.py:187-188 (500 body lines, 15 methods per class)
FOUND: CodeSearchAgent keeps 7 methods, body shrinks by ~1 line; _text_lines is a module function (~16 lines)
HOLDS: yes

CLAIM: no importer/layer guard tripped
RUN:   A5.3.1 adds collections.abc (stdlib); A5.2.1 the same in the test file
HOLDS: yes

CLAIM: BF-892 spawn census and source-scan tests see no change
RUN:   Grep "code_search\.py|getsource\(code_search" tests -> test_ad1025b_path_anchoring.py:56 (path anchoring only)
       A5 adds no subprocess call; _search_rg untouched
HOLDS: yes

CLAIM: the raw engine's direct callers keep working
RUN:   Grep "_search_python|CodeSearchAgent" tests -> test_ad989_code_search, test_bf895_rg_line_parse,
       test_bf892_spawn_env_guard, test_bf758_file_read_confinement, this file; signature unchanged
HOLDS: yes
```

### A5.9 Repair milestone

**M5r3, one Builder pass, tests first, about 15-20 tool calls:**
1. Apply A5.2's three blocks, run `tests/test_bf908_floor_and_children.py -n 0`, and confirm premise 23.
2. Apply A5.3's three blocks.
3. Rerun the file, then section 8.2 `-n 0`.
4. Apply A5.4's fragment, regenerate the ledger and run its `--check`.
5. Report every SEARCH that did not match exactly once; do not improvise.

Then the orchestrator runs:
- one consolidated focused check;
- the campaign for rows 31-34 and 45-62;
- review round 4 on the delta (D41).

### A5.10 Prior art and blind spots

- **Prior art:** none needed. This is Python exception-scoping plumbing with no outside analogue. The pattern is the standard library's own: a generator owns its I/O, and its consumer's exceptions are not thrown into it.
- **Blind spot covered:** a read failure part-way through a file was never pinned. J22 now pins both the open and the read case.
- **Considered, deferred:** `contextlib.closing` for deterministic close on non-CPython interpreters. ProbOS runs on CPython, where the close is immediate.

### A5.11 Verified Against Codebase (2026-10-20, staged tree `81c7bd88` in worktree `bf908-2b97ca11`)

```
code_search.py:27-29   import sys / from pathlib import Path / from typing import Any
code_search.py:163     return _within_floor(self._search_python(plan, root, floor=floor), ...)   (no try around it)
code_search.py:195-207 rg's try/except (OSError, TimeoutError, ValueError) ends before :223
code_search.py:223     if floor is not None and not floor.permits(parsed["path"]):   (outside every handler)
code_search.py:271-294 for fp in files: / try: / with fp.open(...) / ... :281 floor.permits / :291 except OSError: / :292 continue
code_search.py:304     class _ReadFloor:
code_search.py:329     from probos.security.file_access import FileAccessDenied, resolve_read_path   (call-time lookup)
code_search.py:387     except OSError:   (_resolve_rg_binary; the only other one)
file_access.py:137-139 resolved = candidate.resolve() / except (OSError, RuntimeError, ValueError) -> FileAccessDenied
file_walk.py:133       with path.open("rb") as fh:   (sniff is binary mode; J22's patch passes it through)
file_walk.py:164,175   sorted(dirnames) / sorted(filenames)   (J22's walk order)
test file:132-133      from pathlib import Path / from types import SimpleNamespace
test file:254-255      _paths -> [Path(match["path"]).resolve() ...]
test file:441-453,470-486  _quota_root, _use_engine, _search
test file:740          assert calls == {"roots_built": 3, "decisions": 1}   (A5.2.3 anchor, unique)
DECISIONS.md:394       "... walk with no match costs no floor decision (amendment A4, D32-D37)." (count 1)
```

### Absence Verified (2026-10-20)

```
CLAIM: no existing test pins the Python engine's degrade on an open/read OSError
RUN:   Grep "OSError|PermissionError|unreadable|\"open\"" in test_ad989_code_search, test_bf895_rg_line_parse,
       test_bf892_spawn_env_guard, test_bf758_file_read_confinement
FOUND: bf758:150,463 and bf895:201,219 (symlink-creation helpers), bf892:228 (a docstring); none drives the engine
HOLDS: yes

CLAIM: code_search.py has no yield/Iterator/collections today (row 62 and the import are unique)
RUN:   Grep "yield|Iterator|collections" src/probos/agents/code_search.py
FOUND: no matches
HOLDS: yes
```

### A5.12 Captain

Nothing here needs the Captain. D38 restores D36's propagate rule without narrowing what the floor refuses or what a search may return. No authority, gate or approval rule changes.
