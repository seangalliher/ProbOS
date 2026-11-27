# AD-1337 follow-up (#1820 R23, R7, R1): tests stand in for the credential CLI, and the secret masker reads each tier's API key from the running config

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-26
**Revised by:** claude-architect (review round 1 repair, 2026-11-27; review round 2 repair, 2026-11-27)
**Status:** ready to build. **Owning issue:** #1820 (three checklist items: ad-1337 R23, R7, R1; review round 1 adds the record item ad-1337 R28). Commits say `Refs #1820.`
**Base:** `219cb7cf92d1f27c8a0398ff5569c23da3f6ccad` (= origin/main), branch `fix/ad1337-r23-r7-r1-20261127`. **Number:** none allocated (consult `0f3f2d43`): a follow-up of AD-1337 inside #1820.
**Line endings:** the working copies may be CRLF and the blocks below are LF; match after normalising. Every SEARCH starts at the beginning of a line and occurs once in its file at its turn. All new text is ASCII.
**Estimated tests:** 8 new: 2 in a new file, 6 appended to the masking test file (44 to 50); 0 removed. One module fixture (`_no_cli`) is deleted.
**Scope:** S1 (tests only): `tests/conftest.py`, the new test file, the masking test file. S2: `security/secret_masking.py`, `startup/finalize.py`, the masking test file, `PROGRESS.md`, `DECISIONS.md`, the regenerated ledger files. `provider_setup.py` is not edited (D9).

## 1. Problem (premise table)

| Where | What it does today | Effect |
|---|---|---|
| `finalize.py`:748 starts the priming; `credential_store.py`:396-407 | with no `GH_TOKEN`/`GITHUB_TOKEN` and no store value, `_resolve` runs `["gh", "auth", "token"]` (spec at `credential_store.py`:121) through `subprocess.run` | R23: an in-process real boot in a test runs the developer's own `gh`, reads the token into the test process, and on Linux lets the CLI write under the test's HOME (PR #1846's CI) |
| the masking test file :67-77 (`_no_cli`, autouse), :459, :480 | `monkeypatch.setattr("probos.credential_store.subprocess.run", f)` | R7: the module binding is the real `subprocess`, so the patch replaces `subprocess.run` process-wide for the test |
| `secret_masking.py`:491-503 `_values` | reads the store (`masked_credential_values`), the registry and the environment | R1: a per-tier key set only in the YAML config (`config.py`:345-536, `llm_api_key_<tier>`) is in none of them; the store's `llm_api` spec covers only `cognitive.llm_api_key` (`credential_store.py`:130-135), and only when the store holds a config (:481) |

## 2. Overview

S1: an autouse fixture in `tests/conftest.py` replaces the module attribute `probos.credential_store.subprocess` for each test by `SimpleNamespace(run=<recorder>, TimeoutExpired=subprocess.TimeoutExpired, calls=<list>)`. The recorder appends `argv` and raises `FileNotFoundError(argv[0])`, the "gh not installed" path that `credential_store.py`:406 catches. A dotted `setattr("probos.credential_store.subprocess.run", f)` then lands on the stand-in. The masking test file's `_no_cli` fixture is deleted (the conftest fixture does the same thing), and its two tests that set a CLI double use the whole-module form of `test_ad1337_executor_seam.py`:80-82. The two new tests take a fixture `started` that refuses a `gh` start through `subprocess.Popen` before the process exists (D11).

S2: `SecretMasker.__init__` gains a keyword-only `config_values: Callable[[], Iterable[tuple[str, str]]] | None = None`, called on each pass as the last source in `_values`. A private helper `_configured_api_key_pairs(cognitive)` in `startup/finalize.py` yields `("llm_api_key_<tier>", key)` for each tier of `_LLM_TIERS` through `tier_config`, empty keys dropped (D9). `_wire_secret_masker` passes `lambda: _configured_api_key_pairs(runtime.config.cognitive)` when `runtime.config` is a `SystemConfig`.

Rejected, one line each:
- A production guard that skips the CLI under pytest: production code would branch on the test runner.
- A fake `GH_TOKEN` for every test: it changes what the priming resolves and hides the CLI step instead of standing in for it.
- Patching only the boot helpers: each new boot path would need its own patch.
- A fourth `*Source` class in `security/`: `security/` would need tier knowledge.
- Widening `masked_credential_values` or the credential specs: `CredentialStore` is at its 15-method SRP review trigger (`credential_store.py`:473).
- A snapshot of the pairs at wiring: a key changed after startup would stay unmasked.
- Wiring the source unconditionally: the runtime doubles of `test_ad1337_executor_seam.py` carry no `config`, so every pass would fail closed (row M10).
- The pairs in `provider_setup.py`, in `cognitive/llm_client.py` or on `CognitiveConfig`: see D9.
- A `sys.addaudithook` guard in the new tests: an audit hook cannot be removed, so it would stay for every later test in the worker (D11).

## 3. Decisions

| # | Decision | Reason |
|---|---|---|
| D1 | The stand-in replaces the module binding, and the `subprocess` module is unchanged | R7's defect is exactly a patch of the shared module |
| D2 | The stand-in carries `TimeoutExpired` (the real class) and a `calls` list | `credential_store.py` names `subprocess` at :16, :399 and :406 only; the except clause at :406 evaluates `TimeoutExpired` when `run` raises. `calls` lets a test read the recorder without requesting the fixture |
| D3 | `_no_cli` in the masking test file is deleted, not converted | it duplicates the conftest fixture; its return value is read by no test (Absence Verified). Pinned by `test_the_stand_in_answers_and_a_dotted_patch_lands_on_it` (the stand-in is present in a test that does not request it) and by the masking tests that reach the CLI step with no double of their own: `test_an_unreadable_store_withholds_the_output_until_its_file_is_repaired[truncated]` and `[directory]`, and `test_a_store_file_that_is_not_an_object_of_strings_loads_as_ad456_loaded_it[array]` |
| D4 | `config_values` is read last in `_values` | `setdefault` keeps the first label (within a source, `sorted(pairs)` puts the alphabetically first name first), so `_values` assigns the shared key the store's `llm_api` in the runtime; the label displayed is then subject to AD-1337 D3 and D9 (`_patterns`) |
| D5 | Labels are `llm_api_key_<tier>` | the config field names (`config.py`:650-657); they match `_LABEL_RE` (`secret_masking.py`:75) |
| D6 | `runtime.config.cognitive` is read inside the lambda, on each pass | a hot-reloaded field or a replaced config is masked from the next pass |
| D7 | A raising `config_values` propagates and fails the pass closed (AD-1337 D7) | as a store read that fails |
| D8 | A runtime whose `config` is not a `SystemConfig` gets no config source | the same rule as the store check at `finalize.py`:732-735; `runtime.py`:664 always sets a `SystemConfig` |
| D9 | F1: option C. The pairs come from a private helper `_configured_api_key_pairs` in `startup/finalize.py`, beside `_wire_secret_masker`, which imports `_LLM_TIERS` from `cognitive/llm_client.py` function-locally. `provider_setup.py` is not edited, and `test_provider_setup_is_imported_only_by_the_cli` passes unchanged | Ranked C, B, D, A. C: the wiring is the helper's one consumer; `finalize.py` already imports the tier list function-locally (`finalize.py`:4047, `TEXT_TIERS`); `_LLM_TIERS` is the tier list the repo asks for by name (`test_ad742a_vision_fast_tier.py`:274-295 tells an offender to import it; `routers/agents.py`:1774 marks it "AD-732: single source of truth"); the only module edited is one the batch already edits, so no new scanner applies. Its cost: a private name crosses a module boundary, as in four existing modules (`__main__.py`, `provider_setup.py`, `commands_llm.py`, `routers/agents.py`). B (a function in `cognitive/llm_client.py`) puts a config-labelling helper in the client module for one consumer and adds that module's scanners to the batch. D (a `CognitiveConfig` method) cannot import the tier list and would keep a second one beside `tier_config`'s maps. A (admit `finalize.py` in the census) contradicts `provider_setup.py`'s documented boundary and loads the operator CLI's module into every boot. The orchestrator's lean (B or C) holds; C ranks first because it edits no new module |
| D10 | F2, widened by round 2 (S2-R2-01): record, not repair. #1820 gains `ad-1337 R28` (P3, Low), text in section 12 | The trigger is a config file that spells an ASCII key other than raw: with a YAML escape, or folded across lines. Two of ProbOS's four writers of the config file (section 10) fold: the HXI save (`routers/config.py`:190, called at :346) and `probos setup --force` (`provider_setup.py`:773, called at `__main__.py`:1637) dump at PyYAML's default width (80), which folds a long plain scalar at a space, and setup accepts a printable ASCII key that holds spaces (`provider_setup.py`:193). Setup's line edit dumps each value at `width=2**31 - 1` and refuses a line break (`provider_setup.py`:632, :634); `_render_init_config` (`__main__.py`:1065) writes the key as `""` (:1093). The round 2 reviewer's 378 dumps of printable ASCII keys without a space wrote no backslash escape. It predates R1 and holds for every source (the orchestrator reproduced it with the store holding the key). P3 stands because an ordinary key, printable ASCII without a space, has no space to fold at and wrote no escape in those dumps; the fold needs a key that holds a space. The escape is one more of the "other encodings" of R3, whose recorded repair is to add a form when a measured leak shows it; the fold has a narrower repair at the two writers (section 12). A YAML-aware decoder at the render boundary would be a new capability, so no Captain decision is needed to record it |
| D11 | S1-01: confirm the orchestrator's guard. A function-scoped fixture `started` in the new test file installs a `subprocess.Popen` subclass that appends `_program(args)` and raises `FileNotFoundError(program)` before `super().__init__` when the program is `gh`; both tests take it; the pin test asserts `"gh" not in started` after the stand-in call | `subprocess.run`, `call`, `check_call`, `check_output` and `getstatusoutput` reach `Popen` through the module global at call time, so a stand-in that falls through to the real `subprocess` (rows M11, M12) is refused before the process exists, and the assertion kills it (without it, M12 passes the pin: the guard's error is the one the stand-in should raise). The orchestrator probed that raising before `super().__init__` leaves no unraisable error on CPython 3.12.13. Not covered, and not claimed: `asyncio.windows_utils.Popen` (a subclass bound at import), `os.system` and `os.spawn*` |

## 4. Milestones and commits

- **S1:** 6.1, 6.2, 6.3. Subject: `Tests stand in for the credential CLI module binding`
- **S2:** 6.4 to 6.8, then `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py` (no `--online`); stage `docs/development/ad-ledger-snapshot.json` and `docs/development/open-ads-report.md` when they change. Subject: `Secret masker reads each tier's API key from the running config`

No subject carries an `AD-` or `BF-` token or the words close, fix or resolve. Stage explicit paths only.

## 5. Builder: may and may not

- **May:** apply the pairs in order, run `gen_ad_ledger.py` (S2), `git diff --check`, `git diff --stat`.
- **May not:** run tests, commit, edit an unnamed file, add `skip`/a retry, or reword an anchor. If a SEARCH does not match exactly once, stop and report.

## 6. The pairs

### 6.1 `tests/conftest.py` (S1)

**P1.** SEARCH:
```python
    refused = isolation.unreported()
    if refused:
        pytest.fail(f"BF-919: this test opened a Ship's Archive outside the temporary roots: {refused}", pytrace=False)
```
REPLACE:
```python
    refused = isolation.unreported()
    if refused:
        pytest.fail(f"BF-919: this test opened a Ship's Archive outside the temporary roots: {refused}", pytrace=False)


@pytest.fixture(autouse=True)
def _ad1337_r23_credential_cli(monkeypatch):
    """AD-1337 follow-up (#1820 R23): in-process, the credential store's CLI step meets a stand-in, not ``gh``.

    A real boot primes the GitHub credential; with no token in the environment or the store, the credential store
    runs ``gh auth token``. For each test, ``probos.credential_store.subprocess`` is replaced by a stand-in whose
    ``run`` records the command in ``calls`` and fails it as if ``gh`` were not installed; ``TimeoutExpired`` is the
    real class. The ``subprocess`` module is unchanged. A test that sets its own stand-in, or patches the stand-in's
    ``run``, takes precedence for that test. Not covered: a ProbOS started in a child process, and a ``gh`` run that
    does not go through the credential store (``cognitive/scout.py`` runs ``gh api`` through ``subprocess.run``).
    """
    import subprocess
    from types import SimpleNamespace

    import probos.credential_store as credential_store

    calls: list[list[str]] = []

    def _run(argv, **_kwargs):
        calls.append(list(argv))
        raise FileNotFoundError(argv[0])

    stand_in = SimpleNamespace(run=_run, TimeoutExpired=subprocess.TimeoutExpired, calls=calls)
    monkeypatch.setattr(credential_store, "subprocess", stand_in)
    yield calls
```

### 6.2 `tests/test_ad1337_r23_hermetic_cli.py` (New file, S1)

```python
"""AD-1337 follow-up (#1820 R23, R7): the credential store's CLI step meets a stand-in, not ``gh``.

``tests/conftest.py`` (``_ad1337_r23_credential_cli``) replaces ``probos.credential_store.subprocess`` for each test
with a stand-in whose ``run`` records the command and fails it as if ``gh`` were not installed. Neither test below
requests that fixture, so each fails when it is not autouse. Both take ``started``, which refuses a ``gh`` start
through ``subprocess.Popen`` before the process exists, so a stand-in that falls through to the real ``subprocess``
fails them before ``gh`` runs. Contract: prompts/ad-1337-r23-r7-r1-masker-sources.md.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

import probos.credential_store as credential_store
import probos.knowledge.embeddings as embeddings_module
from probos.cognitive.llm_client import MockLLMClient
from probos.config import SystemConfig
from probos.runtime import ProbOSRuntime

GH_TOKEN_CLI = ["gh", "auth", "token"]


def _boot_config() -> SystemConfig:
    """AD-1346's boot shape, as the BF-919 boot test uses it."""
    config = SystemConfig()
    config.onboarding.naming_ceremony = False
    config.proactive_cognitive.enabled = False
    config.qa.enabled = False
    return config


def _program(args: Any) -> str:
    """The program a ``Popen`` call starts: its first word, lower-case, without directory or suffix."""
    if isinstance(args, (str, bytes, os.PathLike)):
        words = os.fsdecode(args).split()
    else:
        words = [os.fsdecode(word) for word in list(args)[:1]]
    return Path(words[0]).stem.lower() if words else ""


@pytest.fixture
def started(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The program of each ``subprocess.Popen`` call; a ``gh`` start is refused before the process exists."""
    programs: list[str] = []

    class _GuardedPopen(subprocess.Popen):  # type: ignore[type-arg]
        def __init__(self, args: Any, *rest: Any, **kwargs: Any) -> None:
            program = _program(args)
            programs.append(program)
            if program == "gh":
                raise FileNotFoundError(program)
            super().__init__(args, *rest, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", _GuardedPopen)
    return programs


def test_the_stand_in_answers_and_a_dotted_patch_lands_on_it(
    monkeypatch: pytest.MonkeyPatch, started: list[str],
) -> None:
    stand_in = credential_store.subprocess
    real_run = subprocess.run
    assert stand_in is not subprocess, "the credential store's binding is replaced, not the subprocess module"
    assert stand_in.TimeoutExpired is subprocess.TimeoutExpired, "the store's except clause names the real class"
    with pytest.raises(FileNotFoundError):
        stand_in.run(GH_TOKEN_CLI, timeout=5)
    assert stand_in.calls == [GH_TOKEN_CLI]
    assert "gh" not in started, "the stand-in answered without a Popen of gh"

    def _replacement(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("not called")

    monkeypatch.setattr("probos.credential_store.subprocess.run", _replacement)
    assert credential_store.subprocess.run is _replacement, "a dotted patch lands on the stand-in"
    assert subprocess.run is real_run, "and leaves the shared subprocess.run as it was"


async def test_a_default_boot_reaches_the_stand_in_without_a_gh_popen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, started: list[str],
) -> None:
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("PROBOS_EMBEDDINGS", "local")  # BF-657's backend, as the BF-919 boot test sets it
    monkeypatch.setattr(embeddings_module, "_embedding_available", None)
    monkeypatch.setattr(embeddings_module, "_embedding_fn", None)
    stand_in = credential_store.subprocess
    assert stand_in is not subprocess, "premise: the conftest stand-in is in place without being requested"
    rt = ProbOSRuntime(config=_boot_config(), data_dir=tmp_path / "data", llm_client=MockLLMClient())
    await rt.start()
    try:
        priming = rt.secret_masking_prime_task
        assert isinstance(priming, asyncio.Task), "premise: the boot started the secret masker's priming"
        done, _ = await asyncio.wait({priming}, timeout=10.0)
        assert priming in done, "the priming finished, so its worker thread has run"
    finally:
        await rt.stop()
    assert stand_in.calls and all(argv == GH_TOKEN_CLI for argv in stand_in.calls), "the priming reached the CLI step"
    assert "gh" not in started, "and no Popen of gh was attempted"
```

### 6.3 `tests/test_ad1337_secret_masking.py` (S1)

**P2.** SEARCH:
```python
import logging
import threading
```
REPLACE:
```python
import logging
import subprocess
import threading
```

**P3.** SEARCH:
```python
@pytest.fixture(autouse=True)
def _no_cli(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """No test runs gh: the CLI step fails as if gh were not installed, and records the call."""
    calls: list[list[str]] = []

    def _run(argv: list[str], **_kwargs: Any) -> None:
        calls.append(list(argv))
        raise FileNotFoundError(argv[0])

    monkeypatch.setattr("probos.credential_store.subprocess.run", _run)
    return calls


def _store(directory: Path, entries: dict[str, str] | None = None, **kwargs: Any) -> CredentialStore:
```
REPLACE:
```python
def _store(directory: Path, entries: dict[str, str] | None = None, **kwargs: Any) -> CredentialStore:
```

**P4.** SEARCH:
```python
    monkeypatch.setattr("probos.credential_store.subprocess.run", _gh)
```
REPLACE:
```python
    monkeypatch.setattr(
        "probos.credential_store.subprocess", SimpleNamespace(run=_gh, TimeoutExpired=subprocess.TimeoutExpired),
    )
```

**P5.** SEARCH:
```python
    monkeypatch.setattr("probos.credential_store.subprocess.run", _forbidden)
```
REPLACE:
```python
    monkeypatch.setattr(
        "probos.credential_store.subprocess", SimpleNamespace(run=_forbidden, TimeoutExpired=subprocess.TimeoutExpired),
    )
```

### 6.4 `src/probos/security/secret_masking.py` (S2)

**P6.** SEARCH:
```python
``SecretMasker`` replaces every form of every known value with ``<secret:NAME>``. It reads three sources again on
```
REPLACE:
```python
``SecretMasker`` replaces every form of every known value with ``<secret:NAME>``. It reads four sources again on
```

**P7.** SEARCH:
```python
   session id or a path is not a secret, and masking one would rewrite ordinary text.
```
REPLACE:
```python
   session id or a path is not a secret, and masking one would rewrite ordinary text.
4. ``config_values``, when the runtime passes one: each LLM tier's API key in the running config, named
   ``llm_api_key_<tier>`` (#1820 R1). It is read last, so its name labels a value only when no earlier source
   names that value; the label shown is still subject to D3 and D9 (``_patterns``).
```

**P8.** SEARCH:
```python
from collections.abc import Callable, Mapping
```
REPLACE:
```python
from collections.abc import Callable, Iterable, Mapping
```

**P9.** SEARCH:
```python
        env_source: EnvSecretSource,
        floor: int = DEFAULT_FLOOR,
```
REPLACE:
```python
        env_source: EnvSecretSource,
        config_values: Callable[[], Iterable[tuple[str, str]]] | None = None,
        floor: int = DEFAULT_FLOOR,
```

**P10.** SEARCH:
```python
            raise TypeError("SecretMasker needs an EnvSecretSource")
```
REPLACE:
```python
            raise TypeError("SecretMasker needs an EnvSecretSource")
        if config_values is not None and not callable(config_values):
            raise TypeError("SecretMasker needs config_values to be callable or None")
```

**P11.** SEARCH:
```python
        self._env_source = env_source
```
REPLACE:
```python
        self._env_source = env_source
        self._config_values = config_values
```

**P12.** SEARCH:
```python
        """``(value, label)`` for every value; the first source to name it wins: the store, the registry, the env."""
        chosen: dict[str, str] = {}
        for pairs in (
            masked_credential_values(self._credential_store),
            self._registry.values(),
            self._env_source.values(),
        ):
```
REPLACE:
```python
        """``(value, label)`` for every value: the first source to name it gives the label (the store, the registry,
        the env, the config), and within a source its alphabetically first name. The label shown is then subject to
        D3 and D9 in ``_patterns``. A ``config_values`` that raises fails the pass (D7)."""
        chosen: dict[str, str] = {}
        config_values = self._config_values
        for pairs in (
            masked_credential_values(self._credential_store),
            self._registry.values(),
            self._env_source.values(),
            config_values() if config_values is not None else (),
        ):
```

### 6.5 `src/probos/startup/finalize.py` (S2)

**P13.** SEARCH:
```python
if TYPE_CHECKING:
    from probos.capability_request import CapabilityRequestStore
    from probos.config import SystemConfig
```
REPLACE:
```python
if TYPE_CHECKING:
    from probos.capability_request import CapabilityRequestStore
    from probos.config import CognitiveConfig, SystemConfig
```

**P14.** SEARCH:
```python
def _wire_secret_masker(*, runtime: Any) -> Any:
    """AD-1337 S2 (#1560): build the runtime's secret masker and start priming the GitHub value.
```
REPLACE:
```python
def _configured_api_key_pairs(cognitive: CognitiveConfig) -> tuple[tuple[str, str], ...]:
    """``(f"llm_api_key_{tier}", key)`` for each tier of ``_LLM_TIERS`` whose resolved key is not empty (#1820 R1).

    ``CognitiveConfig.tier_config`` resolves a tier without its own key to the shared one, so the shared key appears
    once for each such tier. ``_wire_secret_masker`` gives these pairs to the secret masker, which reads them on
    each pass.
    """
    from probos.cognitive.llm_client import _LLM_TIERS  # AD-732: single source of truth

    pairs: list[tuple[str, str]] = []
    for tier in _LLM_TIERS:
        key = cognitive.tier_config(tier)["api_key"]
        if key:
            pairs.append((f"llm_api_key_{tier}", key))
    return tuple(pairs)


def _wire_secret_masker(*, runtime: Any) -> Any:
    """AD-1337 S2 (#1560): build the runtime's secret masker and start priming the GitHub value.
```

**P15.** SEARCH:
```python
    from probos.credential_store import CredentialStore
    from probos.security.secret_masking import EnvSecretSource, SecretMasker, SecretRegistry, secret_registry_of
```
REPLACE:
```python
    from probos.config import SystemConfig
    from probos.credential_store import CredentialStore
    from probos.security.secret_masking import EnvSecretSource, SecretMasker, SecretRegistry, secret_registry_of
```

**P16.** SEARCH:
```python
    runtime.secret_masker = SecretMasker(
        credential_store=store, registry=runtime.secret_registry, env_source=EnvSecretSource(),
    )
```
REPLACE:
```python
    # #1820 R1: the tiers' API keys, read from runtime.config at each pass; a double without a SystemConfig gets none.
    has_config = isinstance(getattr(runtime, "config", None), SystemConfig)
    runtime.secret_masker = SecretMasker(
        credential_store=store, registry=runtime.secret_registry, env_source=EnvSecretSource(),
        config_values=(lambda: _configured_api_key_pairs(runtime.config.cognitive)) if has_config else None,
    )
```

### 6.6 `tests/test_ad1337_secret_masking.py` (S2)

**P17.** SEARCH:
```python
- N44 (review round 2): while the fallback placeholder would hold a known value, every pass is withheld.
Does not prove: any seam (AD-1337 S2, S3), the masking event (S2), or the cost of a pass (the orchestrator's probe).
```
REPLACE:
```python
- N44 (review round 2): while the fallback placeholder would hold a known value, every pass is withheld.
- N45-N50 (#1820 R1): a tier's API key from the running config, read on each pass and last; N45 and N46 run the
  runtime's wiring (``startup/finalize.py``) over an empty environment.
Does not prove: the executor and render seams (AD-1337 S2, S3), the masking event (S2), or the cost of a pass (the
orchestrator's probe).
```

**P18.** SEARCH:
```python
from types import SimpleNamespace
```
REPLACE:
```python
from types import MethodType, SimpleNamespace
```

**P19.** SEARCH:
```python
from probos.credential_store import CredentialSpec, CredentialStore, masked_credential_values
from probos.execution.command_env import env_name_refusal
from probos.security import secret_masking
```
REPLACE:
```python
from probos.cognitive.llm_client import _LLM_TIERS, TEXT_TIERS, VERIFIER_TIER
from probos.config import CognitiveConfig, SystemConfig
from probos.credential_store import CredentialSpec, CredentialStore, masked_credential_values
from probos.execution.command_env import env_name_refusal
from probos.runtime import ProbOSRuntime
from probos.security import secret_masking
```

**P20.** SEARCH:
```python
    secret_forms,
)
from probos.tools.protocol import ToolResult
```
REPLACE:
```python
    secret_forms,
    secret_label,
)
from probos.startup import finalize
from probos.tools.protocol import ToolResult
```

**P21.** SEARCH:
```python
    logged = len(caplog.records)
    assert masker.mask_text(f"x {first} y") == MaskOutcome("x <secret:unnamed> y", frozenset({"unnamed"}), False)
    assert all(record.levelno < logging.ERROR for record in caplog.records[logged:])
```
REPLACE:
```python
    logged = len(caplog.records)
    assert masker.mask_text(f"x {first} y") == MaskOutcome("x <secret:unnamed> y", frozenset({"unnamed"}), False)
    assert all(record.levelno < logging.ERROR for record in caplog.records[logged:])


# -- N45 to N50 (#1820 R1): the config source ---------------------------------------------------------------------


async def _wired(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: SystemConfig,
) -> tuple[SimpleNamespace, SecretMasker]:
    """The runtime's wiring over a real store that holds ``config`` and an empty environment, its priming awaited."""
    monkeypatch.setattr(secret_masking, "os", SimpleNamespace(environ={}))
    runtime = SimpleNamespace(
        config=config, credential_store=_store(tmp_path, config=config), _background_tasks=set(), _drain_tasks=set(),
    )
    runtime._spawn_background = MethodType(ProbOSRuntime._spawn_background, runtime)
    masker = finalize._wire_secret_masker(runtime=runtime)
    assert isinstance(masker, SecretMasker), "premise: a real store gets a masker"
    await runtime.secret_masking_prime_task
    return runtime, masker


async def test_a_key_set_only_on_an_optional_tier_in_config_is_masked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    tier = VERIFIER_TIER
    label = f"llm_api_key_{tier}"
    key = "tier-only-key-Zq8Wd3Lp4Nc7"
    config = SystemConfig(cognitive={label: key})
    assert tier in _LLM_TIERS and tier not in TEXT_TIERS  # premise: an optional tier
    assert label in CognitiveConfig.model_fields and config.cognitive.tier_config(tier)["api_key"] == key  # premise
    assert all(config.cognitive.tier_config(t)["api_key"] == "" for t in TEXT_TIERS)  # premise: no text tier sends it
    unwired = _masker(_store(tmp_path / "control", config=config))
    assert unwired.mask_text(f"k={key}").text == f"k={key}"  # premise: no other source names it
    _runtime, masker = await _wired(tmp_path / "wired", monkeypatch, config)
    assert masker.mask_text(f"k={key}") == MaskOutcome(f"k=<secret:{label}>", frozenset({label}), False)


async def test_a_tier_key_changed_after_wiring_is_masked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    first, second = "fast-key-set-after-wiring-1", "verifier-key-in-a-new-config-2"
    runtime, masker = await _wired(tmp_path, monkeypatch, SystemConfig())
    assert masker.mask_text(f"k={first}").text == f"k={first}"  # premise: the table is built without it
    runtime.config.cognitive.llm_api_key_fast = first
    assert masker.mask_text(f"k={first}").text == "k=<secret:llm_api_key_fast>"
    runtime.config = SystemConfig(cognitive={"llm_api_key_verifier": second})
    assert masker.mask_text(f"k={first} {second}").text == f"k={first} <secret:llm_api_key_verifier>"


def test_the_shared_key_keeps_its_store_label(tmp_path: Path) -> None:
    shared = "shared-llm-key-Rt5Yh8Kw2"
    config = SystemConfig(cognitive={"llm_api_key": shared})
    pairs_of = finalize._configured_api_key_pairs
    pairs = pairs_of(config.cognitive)
    assert len(pairs) == len(_LLM_TIERS) and {key for _, key in pairs} == {shared}  # premise
    masker = _masker(_store(tmp_path, config=config), config_values=lambda: pairs_of(config.cognitive))
    assert masker.mask_text(f"k={shared}") == MaskOutcome("k=<secret:llm_api>", frozenset({"llm_api"}), False)
    bare = _masker(_store(tmp_path / "bare"), config_values=lambda: pairs_of(config.cognitive))
    assert bare.mask_text(f"k={shared}").text == "k=<secret:llm_api_key_compute_use>"  # no store config: first by name


def test_a_failing_config_source_withholds_output(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    def _raise() -> tuple[tuple[str, str], ...]:
        raise RuntimeError(f"boom {TOKEN}")

    masker = _masker(_store(tmp_path, {"github": TOKEN}), config_values=_raise)
    caplog.set_level(logging.DEBUG)
    assert masker.mask_text(f"t {TOKEN}") == MaskOutcome(MASKING_FAILED_TEXT, frozenset(), True)
    masked = masker.mask_result(ToolResult(output=TOKEN, duration_ms=2.0))
    assert masked.failed is True and masked.result.output is None and masked.result.error == MASKING_FAILED_TEXT
    assert "RuntimeError" in caplog.text and TOKEN not in caplog.text and "boom" not in caplog.text


def test_config_values_must_be_callable(tmp_path: Path) -> None:
    store = _store(tmp_path, {"github": TOKEN})
    for bad in ("llm_api_key_fast", (("llm_api_key_fast", "not-callable-key-1"),)):
        with pytest.raises(TypeError):
            _masker(store, config_values=bad)
    for empty in (None, tuple):
        assert _masker(store, config_values=empty).mask_text(TOKEN).text == "<secret:github>"


def test_pairs_cover_every_tier_label() -> None:
    own = {f"llm_api_key_{tier}": f"own-key-{tier}-1234" for tier in _LLM_TIERS}
    fields = {name for name in CognitiveConfig.model_fields if name.startswith("llm_api_key_")}
    assert set(own) == fields, "each per-tier key field of the config is a label, and each label a field"
    assert finalize._configured_api_key_pairs(SystemConfig(cognitive=own).cognitive) == tuple(own.items())
    assert all(secret_label(label) == label for label in own)
    assert finalize._configured_api_key_pairs(SystemConfig().cognitive) == ()
```

### 6.7 `PROGRESS.md` (S2)

**P22.** SEARCH:
```markdown
# ProbOS Progress
```
REPLACE:
```markdown
# ProbOS Progress

**AD-1337 follow-up (2026-11-26), #1820 items ad-1337 R23, R7 and R1 -- tests stand in for the credential CLI, and the secret masker knows each LLM tier's API key from the running config.** R23: a real boot primes the GitHub credential, and with no token set the credential store ran the developer's own `gh auth token` in an in-process boot of the suite. A new autouse fixture in `tests/conftest.py` replaces the module binding `probos.credential_store.subprocess` for each test with a stand-in whose `run` records the command and fails it as if `gh` were not installed; `TimeoutExpired` is the real class and the `subprocess` module is unchanged. A ProbOS started in a child process, and the `gh api` that `cognitive/scout.py` runs through the shared `subprocess.run`, are not covered. R7: the masking test file drops its `_no_cli` fixture, which patched the shared `subprocess.run`, and its two tests that set a CLI double replace the module binding. R1: `SecretMasker` takes an optional `config_values` callable, read on each pass after the store, the registry and the environment; `_wire_secret_masker` passes `_configured_api_key_pairs(runtime.config.cognitive)` (`startup/finalize.py`, over `_LLM_TIERS`), named `llm_api_key_<tier>`, so a per-tier key that only the YAML config holds is masked, a key changed after startup is masked from the next pass, and a config source that raises withholds the output. The masker assigns a value the label of the first source that names it, and within a source its alphabetically first name, so the shared key is assigned `llm_api` when the store holds the config, as the runtime's does; the label displayed is then subject to AD-1337 D3 (a form that two values share shows the smaller label) and D9 (a label whose placeholder holds a known value's form shows as `unnamed`). `provider_setup.py` is unchanged and gains no runtime importer (AD-1135's census). A key that the config file spells with a YAML escape, or folds across lines, is not masked, as for any source; the HXI config save and `probos setup --force` fold a long key that holds a space (#1820 ad-1337 R28). New `tests/test_ad1337_r23_hermetic_cli.py` (2 tests); 6 tests added to `tests/test_ad1337_secret_masking.py`. No new AD or BF number. Contract `prompts/ad-1337-r23-r7-r1-masker-sources.md`.
```

### 6.8 `DECISIONS.md` (S2)

**P23.** SEARCH:
```markdown
### BF-1000 -- the HXI settings store reads the save's restart_required flag and shows the live values after an applied save (2026-11-26, #1855)
```
REPLACE:
```markdown
### AD-1337 follow-up -- the secret masker reads each LLM tier's API key from the running config; tests stand in for the credential CLI (2026-11-26, #1820)

- *Scope.* #1820 items ad-1337 R1, R7 and R23. `SecretMasker.__init__` (a keyword-only `config_values`), `SecretMasker._values`, `startup/finalize.py` (`_configured_api_key_pairs`, `_wire_secret_masker`); `tests/conftest.py` (`_ad1337_r23_credential_cli`). Contract `prompts/ad-1337-r23-r7-r1-masker-sources.md`.
- *D1.* A fourth masker source: an optional callable called on each pass and read last, so a value an earlier source names is assigned that source's label (the runtime's store names the shared key `llm_api`). Not a fourth source class (`security/` would need tier knowledge), not wider credential specs (`CredentialStore` is at its SRP review trigger), not a snapshot at wiring (a key changed after startup would stay unmasked).
- *D2.* The pairs come from a private helper beside the wiring, over `_LLM_TIERS` (AD-732's single tier list), not from `provider_setup`: AD-1135's census keeps that module out of the runtime, and the wiring is the helper's one consumer. Not a function in `cognitive/llm_client.py` (a config-labelling helper in the client module, for one consumer) and not a `CognitiveConfig` method (`config.py` cannot import the tier list and would keep a second one).
- *D3.* The labels are the config field names `llm_api_key_<tier>`, read through `CognitiveConfig.tier_config`; an empty key gives no pair. A tier that inherits the shared key yields it under its own name. `_values` assigns the first source's label and, within a source, the alphabetically first name, so when no earlier source names the shared key it is assigned the alphabetically first name among the tiers whose key it is. AD-1337 D3 (a form two values share shows the smaller label) and D9 (a label whose placeholder holds a form shows as `unnamed`) then apply to the label shown.
- *D4.* The wiring reads `runtime.config.cognitive` at each pass; a runtime whose `config` is not a `SystemConfig` gets no config source, as one without a real store gets no masker. A config source that raises fails the pass closed (AD-1337 D7).
- *D5.* The test stand-in replaces the module binding `probos.credential_store.subprocess` and carries the real `TimeoutExpired`; `subprocess.run` itself is not patched. Its two pin tests refuse a `gh` start through `subprocess.Popen` before the process exists, so a stand-in that falls through to the real `subprocess` fails them before `gh` runs.
- *Known limits.* The fixture covers in-process calls of the credential store's CLI step; a ProbOS started in a child process runs the CLI there, and `cognitive/scout.py` runs `gh api` through the shared `subprocess.run`. A key shorter than the masker's floor (8) is not masked, as for any value. A key that the config file spells with a YAML escape, or folds across lines, is not masked, as for any source; the HXI config save and `probos setup --force` fold a long key that holds a space (#1820 ad-1337 R28).
- *Reversal.* Revert this change's commits; no persisted format changes. A revert removes the config source, so a per-tier key that only the YAML config holds can reach the model again, and an in-process boot in a test with no token set runs the developer's `gh` again.

### BF-1000 -- the HXI settings store reads the save's restart_required flag and shows the live values after an applied save (2026-11-26, #1855)
```

## 7. Consumers

| Contract | Consumer | After the change |
|---|---|---|
| `SecretMasker(` (8 call lines) | `finalize.py`:736 | passes `config_values` (P16) |
| | executor-seam tests :103, :558, :643, :755; masking tests :95 (the `_masker` helper, which `test_ad1337_per_run.py`:76 and `test_ad1337_render_seam.py`:72 import), :289 (`SecretMasker(**bad)`, three bad arguments), :426 | unchanged: the new argument is keyword-only with a default |
| `SecretMasker._values` | `_patterns` (`secret_masking.py`:512), its one reader | one more source, read last |
| `_configured_api_key_pairs` | the lambda in `_wire_secret_masker`; `test_the_shared_key_keeps_its_store_label`, `test_pairs_cover_every_tier_label` | new |
| `_wire_secret_masker` | `finalize.py`:5817; executor-seam tests :510, :547, :689, :773, :861; `test_ad1337_per_run.py`:583 | the executor-seam doubles (`_owning_runtime`, :93-98) carry no `config`: no config source (D8); :547 and per-run :583 have no real store: no masker, as before |
| the conftest stand-in | the masking tests named in D3, the two new tests, N45 and N46, and `test_bf908_crew_scope_token.py::test_a_real_boot_reads_the_keyring_after_the_stop_record_and_before_nats` (the 8 tests that the orchestrator's probe saw reach it over the focused files), and each in-process real boot | the stand-in answers in place of `gh` |
| | overrides: executor-seam `_no_cli` :73-82 and :505, :741, :852; `test_bf908_crew_scope_token.py`:655; `test_bf919_archive_isolation.py`:100; masking :459, :480 (P4, P5) | whole-module replacement on top of the stand-in |
| | dotted patches: `test_credential_store.py`:57, :100; `test_quality_hardening.py`:32 | land on the stand-in's `run` (`mock.patch` resolves the target by `getattr`) |
| import census of `provider_setup` | `test_ad1135_provider_setup.py::test_provider_setup_is_imported_only_by_the_cli` (:678-705) | passes unchanged: no `src` module gains an import of `provider_setup` (D9) |
| tier-literal scan | `test_ad742a_vision_fast_tier.py::test_no_hardcoded_tier_tuples_outside_llm_client` (:274-295) | passes: the helper imports `_LLM_TIERS` and writes no tier literal |
| scanners of the edited modules | every test that walks `src` or names `finalize.py`, `secret_masking.py` or `conftest.py` (the `rg` command of 8.2) | must pass unchanged |

The rule, once: an added import, or an edit of a module that a test scans, runs every test that walks `src` or names the edited module's file. Round 1 missed the `provider_setup` census because the focused list named only the masker's consumers.

## 8. Gates (the orchestrator runs all of them)

### 8.1 Oracle tree, before the Builder starts

- Every SEARCH of section 6 counted at its turn: 1 each; the new test file does not exist.
- On the base, run the dotted-patch tests of section 7 under the S1 fixture alone and without it: the same count both times (the issue reports 26 passed; confirm the figure).
- Fixture order: a temporary probe module with an autouse fixture that records `hasattr(probos.credential_store.subprocess, "calls")` on entry; expected True (the conftest fixture ran first). Delete the probe.
- The new file on the base without 6.1: both tests fail at their `stand_in is not subprocess` premise, before any boot. 6.6 on the S1 candidate without 6.4 and 6.5: the six new tests fail (`config_values` is an unknown argument, `_configured_api_key_pairs` is missing, or the wiring passes no config source) and the 44 others pass.

### 8.2 Focused checks on the candidate

```text
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1337_r23_hermetic_cli.py tests/test_ad1337_secret_masking.py tests/test_ad1337_executor_seam.py tests/test_credential_store.py tests/test_quality_hardening.py tests/test_bf919_archive_isolation.py tests/test_bf908_crew_scope_token.py tests/test_ad1337_per_run.py tests/test_ad1337_render_seam.py tests/test_ad1337_reflect_route.py tests/test_ad1137_doctor.py tests/test_ad1135_provider_setup.py tests/test_ad742a_vision_fast_tier.py -n 0 -q
rg -l -g 'test_*.py' -e 'rglob\("\*\.py"\)' -e 'os\.walk\(' -e 'finalize\.py' -e 'secret_masking\.py' -e 'conftest\.py' tests
d:/ProbOS/.venv/Scripts/pytest.exe <each file the rg command lists> -n 8 -q
d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py --check
d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --preflight-only --label ad-1337-r23-r7-r1
```
The `rg` list is a superset of the 75 files of `logs/review-b2r1/census-files.txt` (it also lists files that name a module in prose); run all of it, and retriage a failure at `-n 0`. Expected: green; the pre-existing tests in these files pass unchanged.

### 8.3 Mutation rows (one at a time, file restored byte for byte)

Each locator is a whole stripped line of the candidate. `@pytest.fixture(autouse=True)` occurs 4 times in `tests/conftest.py`; the fixture's is the 2nd. The other lines named below occur once in their file. Run the conftest rows (M1 to M3, M11, M12) under the orchestrator's audit hook that refuses and counts a `subprocess.Popen` of `gh`: on the repaired candidate it must see no `gh` launch, unmutated or under any row.

| ID | File | Line (stripped) | Becomes | Killed by |
|---|---|---|---|---|
| M1 | conftest | `@pytest.fixture(autouse=True)` (2nd of 4) | `@pytest.fixture` | both tests of the new file |
| M2 | conftest | `monkeypatch.setattr(credential_store, "subprocess", stand_in)` | `monkeypatch.setattr(subprocess, "run", _run)` | `test_the_stand_in_answers_and_a_dotted_patch_lands_on_it` |
| M3 | conftest | `stand_in = SimpleNamespace(run=_run, TimeoutExpired=subprocess.TimeoutExpired, calls=calls)` | `stand_in = SimpleNamespace(run=_run, calls=calls)` | `test_the_stand_in_answers_and_a_dotted_patch_lands_on_it` |
| M4 | secret_masking.py | `config_values() if config_values is not None else (),` | `(),` | `test_a_key_set_only_on_an_optional_tier_in_config_is_masked` |
| M5 | secret_masking.py | `self._config_values = config_values` | `self._config_values = None if config_values is None else (lambda pairs: lambda: pairs)(tuple(config_values()))` | `test_a_tier_key_changed_after_wiring_is_masked` |
| M6 | secret_masking.py | `config_values() if config_values is not None else (),` | the line moves above `masked_credential_values(self._credential_store),` | `test_the_shared_key_keeps_its_store_label` |
| M7 | secret_masking.py | `config_values() if config_values is not None else (),` | `_quiet(config_values),` plus a module function `def _quiet(source):` that returns `tuple(source())` inside `try`, `()` on `except Exception`, and `()` for None | `test_a_failing_config_source_withholds_output` |
| M8 | finalize.py | `config_values=(lambda: _configured_api_key_pairs(runtime.config.cognitive)) if has_config else None,` | deleted | `test_a_key_set_only_on_an_optional_tier_in_config_is_masked` |
| M9 | finalize.py | `for tier in _LLM_TIERS:` | `for tier in _LLM_TIERS[:3]:` | `test_a_key_set_only_on_an_optional_tier_in_config_is_masked`, `test_pairs_cover_every_tier_label` |
| M10 | finalize.py | `config_values=(lambda: _configured_api_key_pairs(runtime.config.cognitive)) if has_config else None,` | `config_values=lambda: _configured_api_key_pairs(runtime.config.cognitive),` | `test_finalize_primes_github_off_the_loop_and_every_executor_waits_for_it` (executor-seam file: its double has no `config`, so the pass fails closed) |
| M11 | conftest | `stand_in = SimpleNamespace(run=_run, TimeoutExpired=subprocess.TimeoutExpired, calls=calls)` | `stand_in = SimpleNamespace(run=subprocess.run, TimeoutExpired=subprocess.TimeoutExpired, calls=calls)` | both tests of the new file (the recorder stays empty; `started` holds `gh`) |
| M12 | conftest | `raise FileNotFoundError(argv[0])` | `return subprocess.run(argv, **_kwargs)` | both tests of the new file (`started` holds `gh`) |

P4 and P5 have no killer by design: under the fixture the dotted form and the whole-module form behave the same; the pin test shows the dotted form leaves `subprocess.run` untouched. The orchestrator retargets its rows X2 and X3 to `_configured_api_key_pairs` in `finalize.py`.

### 8.4 The batch gate

`d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label ad-1337-r23-r7-r1 --receipt logs/gates/ad-1337-r23-r7-r1.receipt.json` once on the committed head of S2.

## 9. Diff Reviewer: properties to verify

The change claims that an in-process call of the credential store's CLI step reaches a stand-in instead of `gh`, that the masking test file no longer patches the shared `subprocess.run`, and that the masker masks each tier's configured API key. The consumers that must accept it: `CredentialStore._resolve` (the stand-in), `ToolExecutor` through `_wire_secret_masker` (the masker), and the import census of `provider_setup`.

1. The stand-in is a whole-module replacement of `probos.credential_store.subprocess` carrying `run` and the real `TimeoutExpired`; the `subprocess` module is not patched.
2. S1 changes no file under `src/`.
3. `config_values` is stored in `__init__` and called inside `_values`, on each pass, as the last element of the sources tuple; nothing in `__init__` calls it.
4. A raising `config_values` reaches the existing `except` of `mask_text` and `mask_result` (fail closed, type-only log).
5. `security/secret_masking.py` gains no import of `provider_setup`, `config` or `cognitive`.
6. `_configured_api_key_pairs` reads keys through `tier_config`, not `getattr(..., f"llm_api_key_{tier}")`, iterates `_LLM_TIERS` with no tier literal, and drops empty keys.
7. The wiring reads `runtime.config` inside the lambda; a runtime whose `config` is not a `SystemConfig` gets `config_values=None`.
8. ASCII and LF in the new text; no file outside section 4 changes.
9. Both new tests take `started`; its `Popen` subclass raises `FileNotFoundError` for `gh` before `super().__init__`; the pin test asserts `"gh" not in started` after the stand-in call. With M11 or M12 applied, both tests fail and no `gh` process starts.
10. `test_provider_setup_is_imported_only_by_the_cli` passes unchanged; `provider_setup.py` is byte-identical to the base; no `src` module gains an import of it.
11. Each absolute word of the new text (no, every, each, only, all, never, none) holds against the branch map: in-process calls through `probos.credential_store.subprocess` are covered; a ProbOS started in a child process and a `gh` run outside the credential store (Scout's `gh api`) are not; `_values` assigns the first source's label, and the label displayed is then subject to AD-1337 D3 and D9; when no earlier source names the shared key, it is assigned the alphabetically first name among the tiers whose key it is; two of the four config writers fold a long key that holds a space (D10).
12. The CLI-reach claims (D3, section 7) name the 8 tests the orchestrator's probe saw reach the stand-in, and no other.

## 10. Verified Against Codebase (2026-11-26, tree `219cb7cf`; revision lines 2026-11-27)

- `credential_store.py`: imports :11-24 (`import subprocess` :16; no alias, no `from subprocess import`); spec `github` :117-123 (`cli_command=["gh", "auth", "token"]` :121); `llm_api` :130-135 (`config_key="cognitive.llm_api_key"`); `_resolve` CLI step :396-407 (`subprocess.run(` :399, `except (FileNotFoundError, subprocess.TimeoutExpired, OSError):` :406); `masked_credential_values` :465, config read only `if spec.config_key and store._config` :481; SRP note :473.
- `secret_masking.py`: docstring sources :3-11, forms :13-16; `from collections.abc import Callable, Mapping` :34; `UNNAMED_LABEL` :57; `_LABEL_RE` :75; `secret_label` :116; `__init__` :389-416 (`env_source: EnvSecretSource,` :394, `floor` :395, the third `TypeError` :404, `self._env_source = env_source` :409); except blocks :449-451, :486-489; `_values` :491-503 (`for name, value in sorted(pairs):` :499, `setdefault` :502); its reader `_patterns` :505-527 (D3 `min(label, ...)` :519, D9 :521-525).
- `provider_setup.py`: `from probos.cognitive.llm_client import _LLM_TIERS, _TIER_ORDER` :44; `TEXT_TIERS` :50, `OPTIONAL_TIERS` :52; `configured_api_keys` :348-351; the key check `api_key.isascii() and api_key.isprintable()` :193; setup's tier-key labels `values[f"llm_api_key_{tier}"]` :244; the value renderer `_render_line` :630-636 (`yaml.safe_dump({"v": value}, default_flow_style=False, allow_unicode=True, width=2**31 - 1)` :632, its line-break refusal :634), used by the line edit at :666, :695, :753; `rewrite_with_managed_values` :759-781 (`yaml.safe_dump(expected, sort_keys=False, allow_unicode=True, default_flow_style=False)` :773, no `width`); `write_config_atomic` :925. (Round 2: the earlier cites :646 and :648 were wrong.)
- Config writers outside `provider_setup.py`: `routers/config.py` `_write_yaml_atomic` :186-204 (`yaml.safe_dump(data, sort_keys=False)` :190), called by the HXI save at :346; `get_config_yaml` :251-257 dumps a scrubbed copy into a response, not a file. `__main__.py`: `_render_init_config` :1065 (`llm_api_key_fast: ""` :1093), written at :1239 and used as setup's scaffold at :1323; `rewrite_with_managed_values(` :1637 (setup `--force`); `write_config_atomic(` :1849; `:2565`, `:2637`, `:2721` write `channels/telegram.yaml`, `slack.yaml` and `matrix.yaml` (:2558, :2628, :2712), not the config file.
- `cognitive/llm_client.py`: `VERIFIER_TIER: str = "verifier"` :49; `_LLM_TIERS` :50 = `("fast", "standard", "deep", "vision", "vision_fast", "compute_use", "image_gen", VERIFIER_TIER)`; `_TIER_ORDER` :56; `TEXT_TIERS = _TIER_ORDER` :59. So `(*TEXT_TIERS, *OPTIONAL_TIERS) == _LLM_TIERS` in order. Importers of `_LLM_TIERS` outside it: `__main__.py`:56, `provider_setup.py`:44, `experience/commands/commands_llm.py`:17 and :65, `routers/agents.py`:1774 (`# AD-732: single source of truth`).
- `config.py`: `llm_api_key: str = ""` :317; per-tier fields `str | None = None` :345, :350, :355, :367, :379, :396, :523, :536; `tier_config` :623, `key_map` :649-658, `"api_key"` :715 (a tier's own key, else the shared one, so always a `str`); `CognitiveConfig` :312 and `SystemConfig` :3908 set neither `frozen` nor `validate_assignment`.
- `finalize.py`: `if TYPE_CHECKING:` :31, `from probos.capability_request import CapabilityRequestStore` :32, `from probos.config import SystemConfig` :33; `_wire_secret_masker` :715-751 (docstring first line :716, imports :723-724, the store check :732-735, `SecretMasker(` :736-738); its call :5817; function-local `from probos.cognitive.llm_client import TEXT_TIERS` :4047; no `_LLM_TIERS` in the file.
- `tests/test_ad1135_provider_setup.py`:678-705 (the census; expected importers `__main__.py`, `doctor/runner.py`, `doctor/checks/llm_check.py`, `doctor/checks/verifier_check.py`). `tests/test_ad742a_vision_fast_tier.py`:274-295 (a literal `("fast", "standard", "deep", "vision")` outside `llm_client.py` fails; the message says to import `_LLM_TIERS`).
- Masking test file: imports :22-54 (`import logging` :28, `import threading` :29, `from types import SimpleNamespace` :32, `from probos.credential_store import ...` :39, `from probos.execution.command_env import env_name_refusal` :40, `from probos.security import secret_masking` :41, no `import subprocess`); `_no_cli` :67-77; `_store` :80-85 (creates its directory); `_masker` :88-100 (passes `**kwargs`); :459, :480; last lines :800-803; 44 tests. Executor-seam file: `_no_cli` :73-82, `_owning_runtime` :93-98. `tests/conftest.py`: `isolated_archive_path` :163-179, function autouse decorators :163, :199, :236; a local `from types import SimpleNamespace` :375; no `FileNotFoundError` in the base file.
- #1820 body, items ad-1337 R1, R3, R7, R23, R26, R27 (read with `gh issue view 1820 --json body --jq .body | grep -n -A 6`).

### Absence Verified (2026-11-26, revision 2026-11-27)

- CLAIM: `credential_store.py` uses no attribute of `subprocess` besides `run` and `TimeoutExpired`. RUN: Grep `subprocess|^import|^from` over the file. FOUND: :16, :399, :406. HOLDS.
- CLAIM: 8 `SecretMasker(` call lines. RUN: Grep `SecretMasker\(` over `*.py`. FOUND: `finalize.py`:736; executor-seam :103, :558, :643, :755; masking :95, :289, :426. HOLDS (the consult's "20" is wrong; the render-seam and per-run files build maskers through the masking file's `_masker`).
- CLAIM: `_values` has one reader. RUN: Grep `\._values\(` over `*.py`. FOUND: `secret_masking.py`:512. HOLDS.
- CLAIM: no test module binds `credential_store.subprocess` at import time, and none relies on the global `subprocess.run` reaching the store. RUN: Grep `credential_store.*subprocess|subprocess.*credential_store` over `tests`; Grep `patch\(\s*"subprocess\.run"|setattr\(subprocess, "run"|patch\.object\(subprocess, "run"` over `tests`, then `credential|CredentialStore` over the three files found. FOUND: the twelve setattr/patch lines of section 7 (executor-seam 4, masking 3, bf908 1, bf919 1, credential-store 2, quality-hardening 1); `test_dependency_resolver.py`, `test_ad1346_admission_subprocess_plumbing.py`, `test_ad1346_admission_build_test_sink.py` name no credential. HOLDS.
- CLAIM: `_no_cli` of the masking file is read by no test. RUN: Grep `_no_cli|from tests\.test_ad1337_secret_masking import` over `tests`. FOUND: its definition; the per-run, render-seam and reflect-route files import `_masker`, `_no_builtin_env`, `_store` only. HOLDS.
- CLAIM: `src` spawns `gh` at two places. RUN: Grep `\["gh"|\("gh"|'gh',|"gh",` over `src/probos`. FOUND: `credential_store.py`:121 (and the comment :41), `scout.py`:415. HOLDS.
- CLAIM: `security/` imports nothing from `provider_setup`, `config` or `cognitive`. RUN: Grep `provider_setup|from probos\.(config|cognitive)` over `src/probos/security`. FOUND: none. HOLDS.
- CLAIM: the helper may not name `masked_credential_values`. RUN: Grep in the masking file :515-522. FOUND: `test_the_secret_masker_is_the_only_reader_of_the_values` requires exactly `credential_store.py` and `security/secret_masking.py` to name it. HOLDS: P14's text does not.
- CLAIM: no source-scan test pins the edited lines. RUN: Grep `three sources|env_source=EnvSecretSource\(\)` and `"_wire_secret_masker"` over `tests`; Grep `conftest\.py` over `tests/test_*.py`. FOUND: executor-seam :616 pins the call at `finalize.py`:5817 (unchanged); conftest readers check `os.environ.setdefault` pairs (`test_ad1185_config_profiles.py`) and hook registration (`test_ad1270f_duration_scheduler.py`:1085-1091). HOLDS. Round 1 showed this search too narrow (it missed the import census); 8.2's `rg` list replaces it.
- CLAIM: no repo config sets a per-tier key. RUN: Grep `llm_api_key` over `config`. FOUND: empty strings or null in `system.yaml`, `node-1.yaml`, `node-2.yaml`. HOLDS.
- CLAIM: no test counts the importers of `_LLM_TIERS`. RUN: Grep `_LLM_TIERS` over `tests/*.py`. FOUND: imports and value assertions in 13 files, and the literal scan of `test_ad742a_vision_fast_tier.py`:274-295; no census of importers. HOLDS. A census of `cognitive.llm_client` importers would already list `finalize.py` (:4047).
- CLAIM: no `CognitiveConfig` field other than the eight per-tier keys begins with `llm_api_key_`. RUN: Grep `^    llm_api_key\w*:` over `src/probos`. FOUND: `config.py`:317 (`llm_api_key`, no suffix), :345, :350, :355, :367, :379, :396, :523, :536. HOLDS.
- CLAIM: no other issue tracks the YAML escape spelling. RUN: `gh issue list --state all --search "yaml escape masker"`. FOUND: #1820 only. HOLDS.
- CLAIM (round 2): ProbOS writes the config file through four renderers, two of which dump at the default width. RUN: Grep `yaml\.(safe_dump|dump)\(` over `src`; Grep `write_config_atomic\(|_render_init_config\(|cfg_path = channels_dir` over `src`; Grep `llm_api_key|json\.dumps` over `__main__.py`. FOUND: `provider_setup.py`:632 (unbounded width, one line), :773 (default width); `routers/config.py`:190 (default width), :256 (a response); `__main__.py` `_render_init_config` (an empty key, :1093) and :2565, :2637, :2721 (channel files); the other 15 dump calls write avatars, consultation documents, the gitagent export, `.shiprecords.yaml`, frontmatter, gap and procedure files and evidence, not the config file. HOLDS.
- CLAIM (round 2): no other issue tracks the fold. RUN: `gh issue list --state all --search "yaml fold width safe_dump key"`. FOUND: none. HOLDS.

## 11. What this does NOT change

- The credential store: `_resolve`, `get`, the specs, `masked_credential_values`, the CLI timeout and `trusted_command_env()`.
- `provider_setup.py` and its import census (D9).
- BF-890's child-environment policy (`execution/command_env.py`) and `env_name_is_mask_shaped`.
- `cognitive/scout.py`, which runs `gh api` through the shared `subprocess.run` (not at boot).
- A ProbOS started in a child process by a test: the fixture is in-process.
- The masker's forms, floor, bounds, event and fail-closed text; a key that the config file spells with a YAML escape, or folds across lines, stays unmasked (D10, R28).
- The config writers, the HXI save (`routers/config.py`:190) and `probos setup --force` (`provider_setup.py`:773) included: they still fold a long key that holds a space (R28).

## 12. Issue text (#1820, on merge)

Wave comment:

```text
Three items of this issue shipped in one PR (contract prompts/ad-1337-r23-r7-r1-masker-sources.md; no new AD or BF number), and its review round 1 adds one record item, ad-1337 R28.
- ad-1337 R23: tests/conftest.py gains an autouse fixture that replaces probos.credential_store.subprocess for each test with a stand-in whose run records the command and fails it as if gh were not installed (TimeoutExpired is the real class). In-process, the credential store's CLI step now meets the stand-in instead of the developer's gh auth token. New tests/test_ad1337_r23_hermetic_cli.py: a default boot reaches the CLI step and the stand-in sees gh auth token; both tests refuse a gh start through subprocess.Popen before the process exists and assert none was attempted. Not covered: a ProbOS started in a child process, and the gh api that cognitive/scout.py runs through the shared subprocess.run.
- ad-1337 R7: tests/test_ad1337_secret_masking.py drops its _no_cli fixture (the conftest stand-in replaces it) and its two tests with a CLI double replace the module binding; a pin test shows a dotted patch now lands on the stand-in and leaves subprocess.run as it was.
- ad-1337 R1: SecretMasker takes an optional config_values callable, read on each pass after the store, the registry and the environment. _wire_secret_masker passes _configured_api_key_pairs(runtime.config.cognitive) (startup/finalize.py, over _LLM_TIERS), named llm_api_key_<tier>; provider_setup.py is unchanged. A per-tier key that only the YAML config holds is masked, a key changed after startup is masked from the next pass, the masker assigns the shared key the label llm_api when the store holds the config (as the runtime's does), the label displayed is then subject to AD-1337 D3 (a form two values share shows the smaller label) and D9 (unnamed), and a config source that raises withholds the output. Six tests in tests/test_ad1337_secret_masking.py; 20 mutation rows killed.
- ad-1337 R28 (new, below): a key that the config file spells with a YAML escape, or folds across lines, is not masked, for any source; the HXI config save and probos setup --force fold a long key that holds a space; recorded, not repaired.
```

Checklist item to append after ad-1337 R27:

```text
- [ ] **ad-1337 R28 (P3, Low; reach: a config file, read by a tool, that spells an ASCII key other than raw: with a YAML escape (`\u0041`, `\x41`), or folded across lines, which ProbOS's own HXI config save and `probos setup --force` do to a key that holds a space once its line passes 80 columns, and setup accepts such a key; pre-existing, not a regression, and independent of R1; found by round 1 of the review of the R23/R7/R1 batch, finding F2, which the reviewer rated P2, and widened to the fold by round 2, finding S2-R2-01; the Architect keeps P3 because an ordinary key, printable ASCII without a space, has no space to fold at and wrote no escape in the reviewer's dumps): a key that the config file spells with a YAML escape, or folds across lines, is not masked, whichever source knows it.**
  - **Evidence (escape):** reproduced first-hand by the orchestrator over the batch's masker: with the key from the config source, the plain line `llm_api_key_verifier: <key>` is masked and the double-quoted line `"sk-s2-normal-key-8Mx3\u0041qp"` is returned unchanged; the same with the key held by the credential store (`{"github": <key>}`); `yaml.safe_load` of the escaped text returns the key. The masker matches the raw, JSON-escaped, URL-encoded and base64 forms of a value (`secret_masking.py`, `secret_forms`); a YAML escape of an ASCII character is none of them. The round 2 reviewer's 378 `safe_dump` renderings of printable ASCII keys without a space (a 6,403-character key among them, at the default and the unbounded width) wrote no backslash escape.
  - **Evidence (fold):** reproduced first-hand by the orchestrator: setup's key check (`provider_setup.py`:193, `isascii()` and `isprintable()`) accepts a 191-character key that holds spaces; `yaml.safe_dump({"cognitive": {"llm_api_key": key}}, sort_keys=False)`, the HXI save's call (`routers/config.py`:190, from :346), writes it over three lines; `yaml.safe_load` returns the key; the raw key is not a substring of the text, and the masker returns the text unmasked. `probos setup --force` (`provider_setup.py`:773, from `__main__.py`:1637) dumps at the same default width: `rewrite_with_managed_values`, run on that key, wrote it over three lines too. Setup's line edit (`provider_setup.py`:632) dumps each value at `width=2**31 - 1` and refuses a line break (:634): it wrote the key on one line. A 757-character key without a space was written on one line by all three renderings, with the raw key a substring of the text. `probos init` writes the key as `""` (`__main__.py`:1093).
  - **Smallest repair:** for the fold, the HXI save and `setup --force` pass `width=2**31 - 1`, as the line edit does (a file folded before stays folded until its next save). For the escape, as R3: add a form to the table when a measured leak shows it. Decoding YAML scalars at the render boundary would be a new capability with its own design.
  - **Nearest neighbour:** R3 (other encodings) and R1 (the config source) on this issue. The duplicate searches (`yaml escape masker`, `yaml fold width safe_dump key`) found no other.
```

## 13. Prior art and blind spots

- Internal: AD-1337 S1 (`prompts/ad-1337-s1-secret-masker.md`, the masker and its D3, D7, D9), S2 section 21 (the BF-919 boot test's hermetic CLI, the pattern this generalises), BF-890 (#1529), AD-1137 (`configured_api_keys`), AD-1135's import census of `provider_setup`, AD-732's single tier list (`test_ad742a_vision_fast_tier.py`:274-295).
- External search skipped: ProbOS-specific test plumbing and masker wiring; no row of `docs/research/reference-projects.md` was examined.
- Blind spots: a key below the floor (8) is not masked (as for any value); `_values` assigns the label of the first source, then the alphabetically first name, and the label shown is then subject to AD-1337 D3 and D9; a config double gets no config source (D8); a key that the config file spells with a YAML escape, or folds across lines, is not a form the masker builds, and the HXI save and `setup --force` fold a long key that holds a space (R28); the `started` guard covers `subprocess.Popen` and the functions built on it, not `asyncio.windows_utils.Popen`, `os.system` or `os.spawn*` (D11); round 1 showed that a focused list built from the change's consumers misses the source-tree censuses (section 7's rule).

## 14. Acceptance criteria

1. The tests of 8.1 fail on the base as stated, and the 8 new tests pass on the candidate; M1 to M12 are killed as 8.3 says, and the audit hook sees no `gh` launch.
2. The focused checks of 8.2 pass, the `rg` list included; the pre-existing tests in those files pass unchanged; `provider_setup.py` equals the base.
3. `git diff --check` is clean, the new text is ASCII, and no file outside section 4 changes.
4. The Diff Reviewer approves against section 9.
5. One receipted broad gate on the committed head is green.
6. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 15. Results on the oracle tree (the orchestrator, 2026-11-27; the revised contract, after review rounds 1 and 2)

The oracle is a detached tree at `219cb7cf` with the 23 pairs and the new file of section 6 of this revision applied by `contract_tools.py apply` (every SEARCH occurred once at its turn, `git diff --check` clean, the five Python files parse, `startup/finalize.py` imports, `gen_ad_ledger.py --check` current after the regeneration, the phantom precheck below). Every pytest run: the venv's interpreter with `PYTHONPATH` set to the tree's `src`, an empty HOME that stayed empty, `-n 0`, and the orchestrator's audit hook loaded (`sys.addaudithook`: it refuses and counts any `subprocess.Popen` of a program named `gh`; its positive control, a `gh --version` start in a child interpreter, was refused and counted once). Every run named below saw **0** `gh` launch attempts, unless it says otherwise. Round 1's results, for the first candidate, were replaced by these; the first candidate's two findings that this section measures are S1-01 (rows Z1 and Z2 of round 1 are M11 and M12 here: both tests failed, and the hook saw 2 launches in each) and F1 (the import census failed: `1 failed, 750 passed` over 12 files; one failure in 3,583 cases over the 75 files that walk `src` or scan `finalize.py`). Review round 2 (S1 approved; S2 returned two P3 wording findings, S2-R2-01 and S2-R2-02, both reproduced below) changed the replacement text of the pairs P12, P22 and P23 only; every figure below is for the contract after that change unless it names round 1.

- **Blobs after the operations** (the `checkpoints` table of `contract_tools.py`; the Builders matched every one straight after its operation): `tests/conftest.py` `90bd94a133c2e5fb907a5fba33fa9c0cba1a7f65` (524 lines); the new test file `7212d41520e15ac143c39be4bdaac46ca9a654b1` (104); `tests/test_ad1337_secret_masking.py` `aceb4d6a75acac265cc0f875c280a3ee6cb6473c` (889); `security/secret_masking.py` `09ed82d30272a19fd15de1e3c1eae8ebc2e6883f` (566); `startup/finalize.py` `82975e1500567f4e55870531c27f9097d70c9754` (6905); `PROGRESS.md` `8d55c2f8aedce11a0046d703835e37405b8f31e9` (1832); `DECISIONS.md` `38d1f3f5379afc19a00a27ec22d61bf215e572c9` (13667). `provider_setup.py` is not edited (its blob equals the base's `c828f7dd3176b4a011277f11ea70f24568f36f74`). S1 alone (6.1 to 6.3): the masking test file `b59541b4aa8e070810f751e714005009c551cca3` (795). The staged candidate is 9 files, +289 -27. (Before round 2, `secret_masking.py` was `89a9f2ea...`, `PROGRESS.md` `b0b6e65f...` and `DECISIONS.md` `a17314fe...`; round 2's one source change is the two-line docstring of `_values`.)
- **8.1:** (a) the new file on the base, without 6.1: both tests fail at their `stand_in is not subprocess` premise (the boot test's is the new file's line 93), before any boot, and the hook saw no launch. (b) S1 plus 6.6 without 6.4 and 6.5: the six new tests fail (`config_values` is an unknown argument, or `_configured_api_key_pairs` is missing) and the other 99 cases pass (6 failed, 99 passed over the masking file and the new file). (c) The dotted-patch tests (`test_credential_store.py` and `test_quality_hardening.py`): 26 passed on the base and 26 passed with the fixture alone (P1). (d) The order probe (an autouse fixture in a scratch test module recording `hasattr(probos.credential_store.subprocess, "calls")` on entry): 1 passed, so the conftest fixture runs first; the probe was deleted.
- **8.2:** the 13-file focused list: 619 passed, 1 skipped on the candidate (142 s on the oracle, 409 s on the work tree under load); the tests that reached the conftest stand-in (read from its `calls` list at each test's teardown) are the 8 named in D3 and section 7, and no other. The census list that the `rg` command of 8.2 prints: 143 files, a superset of round 1's 75, run on the candidate in six parallel groups: 5,700 cases passed and 1 failed, `tests/ablation/test_sigma_ablation.py::test_sigma_ablation_run`, which fails the same way on the base when run by path (its directory's `conftest.py` ignores `test_*.py` unless `PROBOS_ABLATION` is `structural` or `live`, so the gate never collects it: leave that file out of the list; the test of the file that sweeps its syntax, `tests/test_ad1143_ablation_gating.py`, is in the list and passes). A first run of the groups under heavy host load ended two groups without a summary, because pytest-timeout's thread method (180 s) ended the process while ten test processes shared the host; the two groups passed when run again. `gen_ad_ledger.py --check` current; `git diff --cached --check` clean; the preflight of `run_test_gate.py` refuses unstaged changes and a running pytest process, so it runs on the committed candidate: its result is in the PR body. After round 2's repair: the 13-file focused list again 619 passed, 1 skipped (157 s on the work tree), with 0 launches seen and the same 8 stand-in reaches; and the five test files that read `PROGRESS.md`, `DECISIONS.md` or the ledger files (`tests/test_ad1184_ad_ledger.py`, `tests/test_ad1250_detail_first_render_policy.py`, `tests/test_architect_agent.py`, `tests/test_codebase_index.py`, `tests/test_standing_orders_layout.py`, which the `rg` command above does not list): 175 passed on the oracle and 175 on the work tree (`tests/test_ad1184_ad_ledger.py` fails by design on an oracle whose ledger was not regenerated after the trackers changed: three failures there until `gen_ad_ledger.py` ran). A change to a tracker or to a ledger input therefore runs those files too.
- **Mutation rows:** the selectors are the new file (2 cases, run for the conftest rows, so that no other test file reaches the developer's `gh` while the fixture is broken) and the new file with the masking and executor-seam tests (131 cases); each passed unmutated, with 0 launches seen by the hook. M1 to M12 and eight rows of the orchestrator (X1 to X8), 20 rows in all, were each KILLED, every case a row names failed, and no row survived; the campaign ran as four shards on four oracle copies of the candidate. The hook saw 0 launches under every row, M11 and M12 included: with the stand-in broken, the tests' own `started` guard refuses the start before the process exists (round 1's first candidate, which had no guard, showed 2 launches under the same two edits). M4 and M5 are also killed by the failing-source test, M9 by the optional-tier test, the shared-label test and the cover test, and M10 by three executor-seam tests (the contract names one). The orchestrator's rows: X1 turns the callable check into `if False:`; X2 keeps empty keys in the helper's pairs; X3 changes the label prefix to `llm_api_`; X4 binds the config object at wiring (killed by the changed-after-wiring test's second half); X5 inverts the `SystemConfig` guard (five cases); X6 drops the recorder's append; X7 makes the recorder return instead of raising; X8 makes `_values` ignore the stored callable.
- **F2, reproduced (probe over the candidate's masker, no boot):** with the key from the config source, the plain line `llm_api_key_verifier: <key>` is masked and the double-quoted line `"sk-s2-normal-key-8Mx3\u0041qp"` (a backslash-u escape of an ASCII character) is returned unchanged; the same with the key held by the credential store; `yaml.safe_load` of the escaped text returns the key. This is the escape evidence of `ad-1337 R28` (D10).
- **S2-R2-01 and S2-R2-02, reproduced (probes over the candidate, no boot):** setup's `validate_key_transport` accepts a 191-character printable ASCII key that holds spaces; `yaml.safe_dump` as the HXI save calls it (`routers/config.py`:190) and `rewrite_with_managed_values` (`setup --force`, `provider_setup.py`:773) each write it over three lines, from which `yaml.safe_load` returns the key, in which the raw key is not a substring, and which the masker returns unmasked; setup's line edit (`_render_line`) writes it on one line; a 757-character key without a space is written on one line, with the raw key a substring, by all three. For the labels: with a registered value equal to the base64 form of the shared key and the config source naming the shared key `llm_api_key_fast`, `k=<shared key>` shows `<secret:llm_api_key_fast>` and `k=<base64 of the shared key>` shows `<secret:a_registry>` (D3: the smaller label of the two values that share that form). The Architect's round 2 revision rests on these (D4, D10, section 12).
- **Phantom precheck:** 9 candidates, each a false positive of the heuristic: `CognitiveConfig.model_fields` (a pydantic class attribute), `SimpleNamespace(...)` (a stdlib class) and seven `mask_text(k=...)` (the f-string prefix `k=` read as a keyword). The merged contract `prompts/ad-1337-s2-producer-seam.md` has 3 such candidates.
