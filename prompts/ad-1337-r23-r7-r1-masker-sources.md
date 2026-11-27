# AD-1337 follow-up (#1820 R23, R7, R1): tests stand in for the credential CLI, and the secret masker reads each tier's API key from the running config

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-26
**Status:** ready to build. **Owning issue:** #1820 (three checklist items: ad-1337 R23, R7, R1). Commits say `Refs #1820.`
**Base:** `219cb7cf92d1f27c8a0398ff5569c23da3f6ccad` (= origin/main), branch `fix/ad1337-r23-r7-r1-20261127`. **Number:** none allocated (consult `0f3f2d43`): a follow-up of AD-1337 inside #1820.
**Line endings:** the working copies may be CRLF and the blocks below are LF; match after normalising. Every SEARCH starts at the beginning of a line and occurs once in its file at its turn. All new text is ASCII.
**Estimated tests:** 8 new: 2 in a new file, 6 appended to the masking test file (44 to 50); 0 removed. One module fixture (`_no_cli`) is deleted.
**Scope:** S1 (tests only): `tests/conftest.py`, the new test file, the masking test file. S2: `security/secret_masking.py`, `provider_setup.py`, `startup/finalize.py`, the masking test file, `PROGRESS.md`, `DECISIONS.md`, the regenerated ledger files.

## 1. Problem (premise table)

| Where | What it does today | Effect |
|---|---|---|
| `finalize.py`:748 starts the priming; `credential_store.py`:396-407 | with no `GH_TOKEN`/`GITHUB_TOKEN` and no store value, `_resolve` runs `["gh", "auth", "token"]` (spec at `credential_store.py`:121) through `subprocess.run` | R23: every in-process real boot in a test runs the developer's own `gh`, reads the token into the test process, and on Linux lets the CLI write under the test's HOME (PR #1846's CI) |
| the masking test file :67-77 (`_no_cli`, autouse), :459, :480 | `monkeypatch.setattr("probos.credential_store.subprocess.run", f)` | R7: the module binding is the real `subprocess`, so the patch replaces `subprocess.run` process-wide for the test |
| `secret_masking.py`:491-503 `_values` | reads the store (`masked_credential_values`), the registry and the environment | R1: a per-tier key set only in the YAML config (`config.py`:345-536, `llm_api_key_<tier>`) is in none of them; the store's `llm_api` spec covers only `cognitive.llm_api_key` (`credential_store.py`:130-135), and only when the store holds a config (:481) |

## 2. Overview

S1: an autouse fixture in `tests/conftest.py` replaces the module attribute `probos.credential_store.subprocess` for each test by `SimpleNamespace(run=<recorder>, TimeoutExpired=subprocess.TimeoutExpired, calls=<list>)`. The recorder appends `argv` and raises `FileNotFoundError(argv[0])`, the "gh not installed" path that `credential_store.py`:406 catches. A dotted `setattr("probos.credential_store.subprocess.run", f)` then lands on the stand-in. The masking test file's `_no_cli` fixture is deleted (the conftest fixture does the same thing), and its two tests that set a CLI double use the whole-module form of `test_ad1337_executor_seam.py`:80-82.

S2: `SecretMasker.__init__` gains a keyword-only `config_values: Callable[[], Iterable[tuple[str, str]]] | None = None`, called on each pass as the last source in `_values`. `provider_setup.configured_api_key_pairs(cognitive)` yields `("llm_api_key_<tier>", key)` for `(*TEXT_TIERS, *OPTIONAL_TIERS)` through `tier_config`, empty keys dropped. `_wire_secret_masker` passes `lambda: configured_api_key_pairs(runtime.config.cognitive)` when `runtime.config` is a `SystemConfig`.

Rejected, one line each:
- A production guard that skips the CLI under pytest: production code would branch on the test runner.
- A fake `GH_TOKEN` for every test: it changes what the priming resolves and hides the CLI step instead of standing in for it.
- Patching only the boot helpers: each new boot path would need its own patch.
- A fourth `*Source` class in `security/`: it would import tier knowledge from `provider_setup`.
- Widening `masked_credential_values` or the credential specs: `CredentialStore` is at its 15-method SRP review trigger (`credential_store.py`:473).
- A snapshot of the pairs at wiring: a key changed after startup would stay unmasked.
- Wiring the source unconditionally: the runtime doubles of `test_ad1337_executor_seam.py` carry no `config`, so every pass would fail closed (row M10).

## 3. Decisions

| # | Decision | Reason |
|---|---|---|
| D1 | The stand-in replaces the module binding, and the `subprocess` module is unchanged | R7's defect is exactly a patch of the shared module |
| D2 | The stand-in carries `TimeoutExpired` (the real class) and a `calls` list | `credential_store.py` names `subprocess` at :16, :399 and :406 only; the except clause at :406 evaluates `TimeoutExpired` when `run` raises. `calls` lets a test read the recorder without requesting the fixture |
| D3 | `_no_cli` in the masking test file is deleted, not converted | it duplicates the conftest fixture; its return value is read by no test. Pinned by `test_no_test_patches_the_global_subprocess_run` (the stand-in is present in a test that does not request it) and by the masking tests at :601, :612, :656 and :759, which reach the CLI step with no double of their own |
| D4 | `config_values` is read last in `_values` | `setdefault` keeps the first label, so the runtime's store keeps `llm_api` for the shared key |
| D5 | Labels are `llm_api_key_<tier>` | the config field names (`config.py`:650-657); they match `_LABEL_RE` (`secret_masking.py`:75) |
| D6 | `runtime.config.cognitive` is read inside the lambda, on each pass | a hot-reloaded field or a replaced config is masked from the next pass |
| D7 | A raising `config_values` propagates and fails the pass closed (AD-1337 D7) | as a store read that fails |
| D8 | A runtime whose `config` is not a `SystemConfig` gets no config source | the same rule as the store check at `finalize.py`:732-735; `runtime.py`:664 always sets a `SystemConfig` |

## 4. Milestones and commits

- **S1:** 6.1, 6.2, 6.3. Subject: `Tests stand in for the credential CLI module binding`
- **S2:** 6.4 to 6.9, then `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py` (no `--online`); stage `docs/development/ad-ledger-snapshot.json` and `docs/development/open-ads-report.md` when they change. Subject: `Secret masker reads each tier's API key from the running config`

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
    """AD-1337 follow-up (#1820 R23): no test runs the developer's own ``gh``.

    A real boot primes the GitHub credential; with no token in the environment or the store, the credential store
    runs ``gh auth token``. For each test, ``probos.credential_store.subprocess`` is replaced by a stand-in whose
    ``run`` records the command in ``calls`` and fails it as if ``gh`` were not installed; ``TimeoutExpired`` is the
    real class. The ``subprocess`` module is unchanged. A test that sets its own stand-in, or patches the stand-in's
    ``run``, takes precedence for that test. A ProbOS started in a child process is not covered.
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
"""AD-1337 follow-up (#1820 R23, R7): no test runs the developer's own ``gh``.

``tests/conftest.py`` (``_ad1337_r23_credential_cli``) replaces ``probos.credential_store.subprocess`` for each test
with a stand-in whose ``run`` records the command and fails it as if ``gh`` were not installed. Neither test below
requests that fixture, so each fails when it is not autouse. Contract: prompts/ad-1337-r23-r7-r1-masker-sources.md.
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


def test_no_test_patches_the_global_subprocess_run(monkeypatch: pytest.MonkeyPatch) -> None:
    stand_in = credential_store.subprocess
    real_run = subprocess.run
    assert stand_in is not subprocess, "the credential store's binding is replaced, not the subprocess module"
    assert stand_in.TimeoutExpired is subprocess.TimeoutExpired, "the store's except clause names the real class"
    with pytest.raises(FileNotFoundError):
        stand_in.run(GH_TOKEN_CLI, timeout=5)
    assert stand_in.calls == [GH_TOKEN_CLI]

    def _replacement(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("not called")

    monkeypatch.setattr("probos.credential_store.subprocess.run", _replacement)
    assert credential_store.subprocess.run is _replacement, "a dotted patch lands on the stand-in"
    assert subprocess.run is real_run, "and leaves the shared subprocess.run as it was"


async def test_a_default_boot_spawns_no_gh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("PROBOS_EMBEDDINGS", "local")  # BF-657's backend, as the BF-919 boot test sets it
    monkeypatch.setattr(embeddings_module, "_embedding_available", None)
    monkeypatch.setattr(embeddings_module, "_embedding_fn", None)
    started: list[str] = []

    class _SpyPopen(subprocess.Popen):  # type: ignore[type-arg]
        def __init__(self, args: Any, *rest: Any, **kwargs: Any) -> None:
            started.append(_program(args))
            super().__init__(args, *rest, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", _SpyPopen)
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
    assert "gh" not in started, "and no process named gh started"
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
4. ``config_values``, when the runtime passes one: each LLM tier's API key in the running config, labelled
   ``llm_api_key_<tier>`` (#1820 R1). It is read last, so a value an earlier source names keeps that label.
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
        """``(value, label)`` for every value; the first source to name it wins: the store, the registry, the env,
        the config. A ``config_values`` that raises fails the pass (D7)."""
        chosen: dict[str, str] = {}
        config_values = self._config_values
        for pairs in (
            masked_credential_values(self._credential_store),
            self._registry.values(),
            self._env_source.values(),
            config_values() if config_values is not None else (),
        ):
```

### 6.5 `src/probos/provider_setup.py` (S2)

**P13.** SEARCH:
```python
    keys = {cognitive.tier_config(tier)["api_key"] for tier in (*TEXT_TIERS, *OPTIONAL_TIERS)}
    return sorted((key for key in keys if key), key=lambda key: (-len(key), key))
```
REPLACE:
```python
    keys = {cognitive.tier_config(tier)["api_key"] for tier in (*TEXT_TIERS, *OPTIONAL_TIERS)}
    return sorted((key for key in keys if key), key=lambda key: (-len(key), key))


def configured_api_key_pairs(cognitive: CognitiveConfig) -> tuple[tuple[str, str], ...]:
    """``(f"llm_api_key_{tier}", key)`` for each tier that would send a key, in tier order (AD-1337, #1820 R1).

    A tier without its own key sends the shared one, so the shared key appears once for each such tier. The secret
    masker reads these pairs on each pass (``startup/finalize.py``).
    """
    pairs: list[tuple[str, str]] = []
    for tier in (*TEXT_TIERS, *OPTIONAL_TIERS):
        key = cognitive.tier_config(tier)["api_key"]
        if key:
            pairs.append((f"llm_api_key_{tier}", key))
    return tuple(pairs)
```

### 6.6 `src/probos/startup/finalize.py` (S2)

**P14.** SEARCH:
```python
    from probos.credential_store import CredentialStore
    from probos.security.secret_masking import EnvSecretSource, SecretMasker, SecretRegistry, secret_registry_of
```
REPLACE:
```python
    from probos.config import SystemConfig
    from probos.credential_store import CredentialStore
    from probos.provider_setup import configured_api_key_pairs
    from probos.security.secret_masking import EnvSecretSource, SecretMasker, SecretRegistry, secret_registry_of
```

**P15.** SEARCH:
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
        config_values=(lambda: configured_api_key_pairs(runtime.config.cognitive)) if has_config else None,
    )
```

### 6.7 `tests/test_ad1337_secret_masking.py` (S2)

**P16.** SEARCH:
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

**P17.** SEARCH:
```python
from types import SimpleNamespace
```
REPLACE:
```python
from types import MethodType, SimpleNamespace
```

**P18.** SEARCH:
```python
from probos.credential_store import CredentialSpec, CredentialStore, masked_credential_values
from probos.execution.command_env import env_name_refusal
from probos.security import secret_masking
```
REPLACE:
```python
from probos.config import CognitiveConfig, SystemConfig
from probos.credential_store import CredentialSpec, CredentialStore, masked_credential_values
from probos.execution.command_env import env_name_refusal
from probos.provider_setup import OPTIONAL_TIERS, TEXT_TIERS, configured_api_key_pairs
from probos.runtime import ProbOSRuntime
from probos.security import secret_masking
```

**P19.** SEARCH:
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

**P20.** SEARCH:
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
    tier = OPTIONAL_TIERS[-1]
    label = f"llm_api_key_{tier}"
    key = "tier-only-key-Zq8Wd3Lp4Nc7"
    config = SystemConfig(cognitive={label: key})
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
    pairs = configured_api_key_pairs(config.cognitive)
    assert len(pairs) == len(TEXT_TIERS) + len(OPTIONAL_TIERS) and {key for _, key in pairs} == {shared}  # premise
    masker = _masker(_store(tmp_path, config=config), config_values=lambda: configured_api_key_pairs(config.cognitive))
    assert masker.mask_text(f"k={shared}") == MaskOutcome("k=<secret:llm_api>", frozenset({"llm_api"}), False)


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
    tiers = (*TEXT_TIERS, *OPTIONAL_TIERS)
    own = {f"llm_api_key_{tier}": f"own-key-{tier}-1234" for tier in tiers}
    assert configured_api_key_pairs(SystemConfig(cognitive=own).cognitive) == tuple(own.items())
    assert all(label in CognitiveConfig.model_fields and secret_label(label) == label for label in own)
    assert configured_api_key_pairs(SystemConfig().cognitive) == ()
```

### 6.8 `PROGRESS.md` (S2)

**P21.** SEARCH:
```markdown
# ProbOS Progress
```
REPLACE:
```markdown
# ProbOS Progress

**AD-1337 follow-up (2026-11-26), #1820 items ad-1337 R23, R7 and R1 -- tests stand in for the credential CLI, and the secret masker knows each LLM tier's API key from the running config.** R23: a real boot primes the GitHub credential, and with no token set the credential store ran the developer's own `gh auth token` in every in-process boot of the suite. A new autouse fixture in `tests/conftest.py` replaces the module binding `probos.credential_store.subprocess` for each test with a stand-in whose `run` records the command and fails it as if `gh` were not installed; `TimeoutExpired` is the real class and the `subprocess` module is unchanged. R7: the masking test file drops its `_no_cli` fixture, which patched the shared `subprocess.run`, and its two tests that set a CLI double replace the module binding. R1: `SecretMasker` takes an optional `config_values` callable, read on each pass after the store, the registry and the environment; `_wire_secret_masker` passes `provider_setup.configured_api_key_pairs(runtime.config.cognitive)`, labelled `llm_api_key_<tier>`, so a per-tier key that only the YAML config holds is masked, a key changed after startup is masked from the next pass, the shared key keeps the label `llm_api`, and a source that raises withholds the output. New `tests/test_ad1337_r23_hermetic_cli.py` (2 tests); 6 tests added to `tests/test_ad1337_secret_masking.py`. No new AD or BF number. Contract `prompts/ad-1337-r23-r7-r1-masker-sources.md`.
```

### 6.9 `DECISIONS.md` (S2)

**P22.** SEARCH:
```markdown
### BF-1000 -- the HXI settings store reads the save's restart_required flag and shows the live values after an applied save (2026-11-26, #1855)
```
REPLACE:
```markdown
### AD-1337 follow-up -- the secret masker reads each LLM tier's API key from the running config; tests stand in for the credential CLI (2026-11-26, #1820)

- *Scope.* #1820 items ad-1337 R1, R7 and R23. `SecretMasker.__init__` (a keyword-only `config_values`), `SecretMasker._values`, `provider_setup.configured_api_key_pairs`, `startup/finalize.py` `_wire_secret_masker`; `tests/conftest.py` (`_ad1337_r23_credential_cli`). Contract `prompts/ad-1337-r23-r7-r1-masker-sources.md`.
- *D1.* A fourth masker source: an optional callable called on each pass and read last, so a value an earlier source names keeps that label (the runtime's store names the shared key `llm_api`). Not a fourth source class (`security/` would import tier knowledge from `provider_setup`), not wider credential specs (`CredentialStore` is at its SRP review trigger), not a snapshot at wiring (a key changed after startup would stay unmasked).
- *D2.* The labels are the config field names `llm_api_key_<tier>`, for `TEXT_TIERS` then `OPTIONAL_TIERS`, read through `CognitiveConfig.tier_config`; a tier that inherits the shared key names it under its own label, and an empty key gives no pair.
- *D3.* The wiring reads `runtime.config.cognitive` at each pass; a runtime whose `config` is not a `SystemConfig` gets no config source, as one without a real store gets no masker. A source that raises fails the pass closed (AD-1337 D7).
- *D4.* The test stand-in replaces the module binding `probos.credential_store.subprocess` and carries the real `TimeoutExpired`; `subprocess.run` itself is not patched.
- *Known limits.* The fixture covers in-process boots; a ProbOS started in a child process runs the CLI there. `cognitive/scout.py` runs `gh api` through the shared `subprocess.run` and is not covered. A key shorter than the masker's floor (8) is not masked, as for any value.
- *Reversal.* Revert the two commits; no persisted format changes and no security control is weakened.

### BF-1000 -- the HXI settings store reads the save's restart_required flag and shows the live values after an applied save (2026-11-26, #1855)
```

## 7. Consumers

| Contract | Consumer | After the change |
|---|---|---|
| `SecretMasker(` (8 call lines) | `finalize.py`:736 | passes `config_values` (P15) |
| | executor-seam tests :103, :558, :643, :755; masking tests :95 (the `_masker` helper, which `test_ad1337_per_run.py`:76 and `test_ad1337_render_seam.py`:72 import), :289 (`SecretMasker(**bad)`, three bad arguments), :426 | unchanged: the new argument is keyword-only with a default |
| `SecretMasker._values` | `_patterns` (`secret_masking.py`:512), its one reader | one more source, read last |
| `_wire_secret_masker` | `finalize.py`:5817; executor-seam tests :510, :547, :689, :773, :861; `test_ad1337_per_run.py`:583 | the executor-seam doubles (`_owning_runtime`, :93-98) carry no `config`: no config source (D8); :547 and per-run :583 have no real store: no masker, as before |
| the conftest stand-in | masking tests :601, :612, :656, :759 (reach the CLI step with no double of their own) and each in-process real boot | the stand-in answers in place of `gh` |
| | overrides: executor-seam `_no_cli` :73-82 and :505, :741, :852; `test_bf908_crew_scope_token.py`:655; `test_bf919_archive_isolation.py`:100; masking :459, :480 (P4, P5) | whole-module replacement on top of the stand-in |
| | dotted patches: `test_credential_store.py`:57, :100; `test_quality_hardening.py`:32 | land on the stand-in's `run` (`mock.patch` resolves the target by `getattr`) |

## 8. Gates (the orchestrator runs all of them)

### 8.1 Oracle tree, before the Builder starts

- Every SEARCH of section 6 counted at its turn: 1 each; the new test file does not exist.
- On the base, run the dotted-patch tests of section 7 under the S1 fixture alone and without it: the same count both times (the issue reports 26 passed; confirm the figure).
- Fixture order: a temporary probe module with an autouse fixture that records `hasattr(probos.credential_store.subprocess, "calls")` on entry; expected True (the conftest fixture ran first). Delete the probe.
- The new file on the base without 6.1: both tests fail. 6.7 on the S1 candidate without 6.4 to 6.6: the masking test module fails to import (`configured_api_key_pairs` is missing); with 6.5 alone added, five new tests fail, `test_pairs_cover_every_tier_label` passes (it tests 6.5 itself) and the 44 others pass.

### 8.2 Focused checks on the candidate

```text
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1337_r23_hermetic_cli.py tests/test_ad1337_secret_masking.py tests/test_ad1337_executor_seam.py tests/test_credential_store.py tests/test_quality_hardening.py tests/test_bf919_archive_isolation.py tests/test_bf908_crew_scope_token.py tests/test_ad1337_per_run.py tests/test_ad1337_render_seam.py tests/test_ad1337_reflect_route.py tests/test_ad1137_doctor.py -n 0 -q
d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py --check
d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --preflight-only --label ad-1337-r23-r7-r1
```
Expected: green; the pre-existing tests in these files pass unchanged.

### 8.3 Mutation rows (one at a time, file restored byte for byte)

Each locator is a whole stripped line of the candidate. `@pytest.fixture(autouse=True)` occurs 4 times in `tests/conftest.py`; the fixture's is the 2nd. The other lines named below occur once in their file.

| ID | File | Line (stripped) | Becomes | Killed by |
|---|---|---|---|---|
| M1 | conftest | `@pytest.fixture(autouse=True)` (2nd of 4) | `@pytest.fixture` | both tests of the new file |
| M2 | conftest | `monkeypatch.setattr(credential_store, "subprocess", stand_in)` | `monkeypatch.setattr(subprocess, "run", _run)` | `test_no_test_patches_the_global_subprocess_run` |
| M3 | conftest | `stand_in = SimpleNamespace(run=_run, TimeoutExpired=subprocess.TimeoutExpired, calls=calls)` | `stand_in = SimpleNamespace(run=_run, calls=calls)` | `test_no_test_patches_the_global_subprocess_run` |
| M4 | secret_masking.py | `config_values() if config_values is not None else (),` | `(),` | `test_a_key_set_only_on_an_optional_tier_in_config_is_masked` |
| M5 | secret_masking.py | `self._config_values = config_values` | `self._config_values = None if config_values is None else (lambda pairs: lambda: pairs)(tuple(config_values()))` | `test_a_tier_key_changed_after_wiring_is_masked` |
| M6 | secret_masking.py | `config_values() if config_values is not None else (),` | the line moves above `masked_credential_values(self._credential_store),` | `test_the_shared_key_keeps_its_store_label` |
| M7 | secret_masking.py | `config_values() if config_values is not None else (),` | `_quiet(config_values),` plus a module function `def _quiet(source):` that returns `tuple(source())` inside `try`, `()` on `except Exception`, and `()` for None | `test_a_failing_config_source_withholds_output` |
| M8 | finalize.py | `config_values=(lambda: configured_api_key_pairs(runtime.config.cognitive)) if has_config else None,` | deleted | `test_a_key_set_only_on_an_optional_tier_in_config_is_masked` |
| M9 | provider_setup.py | `for tier in (*TEXT_TIERS, *OPTIONAL_TIERS):` | `for tier in TEXT_TIERS:` | `test_a_key_set_only_on_an_optional_tier_in_config_is_masked`, `test_pairs_cover_every_tier_label` |
| M10 | finalize.py | `config_values=(lambda: configured_api_key_pairs(runtime.config.cognitive)) if has_config else None,` | `config_values=lambda: configured_api_key_pairs(runtime.config.cognitive),` | `test_finalize_primes_github_off_the_loop_and_every_executor_waits_for_it` (executor-seam file: its double has no `config`, so the pass fails closed) |

P4 and P5 have no killer by design: under the fixture the dotted form and the whole-module form behave the same; the pin test shows the dotted form leaves `subprocess.run` untouched.

### 8.4 The batch gate

`d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label ad-1337-r23-r7-r1 --receipt logs/gates/ad-1337-r23-r7-r1.receipt.json` once on the committed head of S2.

## 9. Diff Reviewer: properties to verify

The change claims that no in-process test runs the real credential CLI, that no test patches the shared `subprocess.run` through the credential store, and that the masker masks each tier's configured API key. The consumers that must accept it: `CredentialStore._resolve` (the stand-in) and `ToolExecutor` through `_wire_secret_masker` (the masker).

1. The stand-in is a whole-module replacement of `probos.credential_store.subprocess` carrying `run` and the real `TimeoutExpired`; the `subprocess` module is not patched.
2. S1 changes no file under `src/`.
3. `config_values` is stored in `__init__` and called inside `_values`, on each pass, as the last element of the sources tuple; nothing in `__init__` calls it.
4. A raising `config_values` reaches the existing `except` of `mask_text` and `mask_result` (fail closed, type-only log).
5. `security/secret_masking.py` gains no import of `provider_setup`, `config` or `cognitive`.
6. `configured_api_key_pairs` reads keys through `tier_config`, not `getattr(..., f"llm_api_key_{tier}")`, and drops empty keys.
7. The wiring reads `runtime.config` inside the lambda; a runtime whose `config` is not a `SystemConfig` gets `config_values=None`.
8. ASCII and LF in the new text; no file outside section 4 changes.

## 10. Verified Against Codebase (2026-11-26, tree `219cb7cf`)

- `credential_store.py`: imports :11-24 (`import subprocess` :16; no alias, no `from subprocess import`); spec `github` :117-123 (`cli_command=["gh", "auth", "token"]` :121); `llm_api` :130-135 (`config_key="cognitive.llm_api_key"`); `_resolve` CLI step :396-407 (`subprocess.run(` :399, `except (FileNotFoundError, subprocess.TimeoutExpired, OSError):` :406); `masked_credential_values` :465, config read only `if spec.config_key and store._config` :481; SRP note :473.
- `secret_masking.py`: docstring sources :3-11; `from collections.abc import Callable, Mapping` :34; `_LABEL_RE` :75; `secret_label` :116; `__init__` :389-416 (`env_source: EnvSecretSource,` :394, `floor` :395, the third `TypeError` :404, `self._env_source = env_source` :409); except blocks :449-451, :486-489; `_values` :491-503 (`setdefault` :502); its reader :512.
- `provider_setup.py`: `TEXT_TIERS` :50, `OPTIONAL_TIERS` :52 (from `llm_client.py`:50 `_LLM_TIERS` and :56 `_TIER_ORDER`: OPTIONAL_TIERS is `("vision", "vision_fast", "compute_use", "image_gen", "verifier")`, its last tier has the field `llm_api_key_verifier`, `config.py`:536, default None); `configured_api_keys` :348-351.
- `config.py`: `llm_api_key: str = ""` :317; per-tier fields `str | None = None` :345, :350, :355, :367, :379, :396, :523, :536; `tier_config` :623, `key_map` :649-658, `"api_key"` :715 (a tier's own key, else the shared one, so always a `str`); `CognitiveConfig` :312 and `SystemConfig` :3908 set neither `frozen` nor `validate_assignment`.
- `finalize.py`: `_wire_secret_masker` :715-751 (imports :723-724, the store check :732-735, `SecretMasker(` :736-738); its call :5817; `SystemConfig` only under `TYPE_CHECKING` at :33. `runtime.py`:664 `self.config = config or load_config(...)`, :740-741 `CredentialStore(config=self.config, ...)`.
- Masking test file: imports :22-54 (`import logging` :28, `import threading` :29, `from types import SimpleNamespace` :32, no `import subprocess`); `_no_cli` :67-77; `_store` :80; `_masker` :88-100 (passes `**kwargs`); :459, :480; last lines :800-803; 44 tests. Executor-seam file: `_no_cli` :73-82, `_owning_runtime` :93-98. `tests/conftest.py`: `isolated_archive_path` :163-179, autouse decorators :163, :199, :236; a local `from types import SimpleNamespace` :375.
- #1820 body, items ad-1337 R1, R7, R23 (read with `gh issue view 1820 --json body --jq .body | grep -A 4`).

### Absence Verified (2026-11-26)

- CLAIM: `credential_store.py` uses no attribute of `subprocess` besides `run` and `TimeoutExpired`. RUN: Grep `subprocess|^import|^from` over the file. FOUND: :16, :399, :406. HOLDS.
- CLAIM: 8 `SecretMasker(` call lines. RUN: Grep `SecretMasker\(` over `*.py`. FOUND: `finalize.py`:736; executor-seam :103, :558, :643, :755; masking :95, :289, :426. HOLDS (the consult's "20" is wrong; the render-seam and per-run files build maskers through the masking file's `_masker`).
- CLAIM: `_values` has one reader. RUN: Grep `\._values\(` over `*.py`. FOUND: `secret_masking.py`:512. HOLDS.
- CLAIM: no test module binds `credential_store.subprocess` at import time, and none relies on the global `subprocess.run` reaching the store. RUN: Grep `credential_store.*subprocess|subprocess.*credential_store` over `tests`; Grep `patch\(\s*"subprocess\.run"|setattr\(subprocess, "run"|patch\.object\(subprocess, "run"` over `tests`, then `credential|CredentialStore` over the three files found. FOUND: the twelve setattr/patch lines of section 7 (executor-seam 4, masking 3, bf908 1, bf919 1, credential-store 2, quality-hardening 1); `test_dependency_resolver.py`, `test_ad1346_admission_subprocess_plumbing.py`, `test_ad1346_admission_build_test_sink.py` name no credential. HOLDS.
- CLAIM: `_no_cli` of the masking file is read by no test. RUN: Grep `_no_cli|from tests\.test_ad1337_secret_masking import` over `tests`. FOUND: its definition; the per-run, render-seam and reflect-route files import `_masker`, `_no_builtin_env`, `_store` only. HOLDS.
- CLAIM: `src` spawns `gh` at two places. RUN: Grep `\["gh"|\("gh"|'gh',|"gh",` over `src/probos`. FOUND: `credential_store.py`:121 (and the comment :41), `scout.py`:415. HOLDS.
- CLAIM: `security/` imports nothing from `provider_setup`, `config` or `cognitive`. RUN: Grep `provider_setup|from probos\.(config|cognitive)` over `src/probos/security`. FOUND: none. HOLDS.
- CLAIM: `provider_setup.py` may not name `masked_credential_values`. RUN: Grep in the masking file :515-522. FOUND: `test_the_secret_masker_is_the_only_reader_of_the_values` requires exactly `credential_store.py` and `security/secret_masking.py` to name it. HOLDS: P13's text does not.
- CLAIM: no source-scan test pins the edited lines. RUN: Grep `three sources|env_source=EnvSecretSource\(\)` and `"_wire_secret_masker"` over `tests`; Grep `conftest\.py` over `tests/test_*.py`. FOUND: executor-seam :616 pins the call at `finalize.py`:5817 (unchanged); conftest readers check `os.environ.setdefault` pairs (`test_ad1185_config_profiles.py`) and hook registration (`test_ad1270f_duration_scheduler.py`:1085-1091). HOLDS.
- CLAIM: no repo config sets a per-tier key. RUN: Grep `llm_api_key` over `config`. FOUND: empty strings or null in `system.yaml`, `node-1.yaml`, `node-2.yaml`. HOLDS.

## 11. What this does NOT change

- The credential store: `_resolve`, `get`, the specs, `masked_credential_values`, the CLI timeout and `trusted_command_env()`.
- BF-890's child-environment policy (`execution/command_env.py`) and `env_name_is_mask_shaped`.
- `cognitive/scout.py`, which runs `gh api` through the shared `subprocess.run` (not at boot).
- A ProbOS started in a child process by a test: the fixture is in-process.
- The masker's forms, floor, bounds, event and fail-closed text.

## 12. Issue text (#1820 wave comment, on merge)

```text
Three items of this issue shipped in one PR (contract prompts/ad-1337-r23-r7-r1-masker-sources.md; no new AD or BF number).
- ad-1337 R23: tests/conftest.py gains an autouse fixture that replaces probos.credential_store.subprocess for each test with a stand-in whose run records the command and fails it as if gh were not installed (TimeoutExpired is the real class). A real boot in a test no longer runs the developer's gh auth token. New tests/test_ad1337_r23_hermetic_cli.py: a default boot reaches the CLI step, the stand-in sees gh auth token, and no process named gh starts. A ProbOS started in a child process is not covered.
- ad-1337 R7: tests/test_ad1337_secret_masking.py drops its _no_cli fixture (the conftest stand-in replaces it) and its two tests with a CLI double replace the module binding; a pin test shows a dotted patch now lands on the stand-in and leaves subprocess.run as it was.
- ad-1337 R1: SecretMasker takes an optional config_values callable, read on each pass after the store, the registry and the environment. _wire_secret_masker passes provider_setup.configured_api_key_pairs(runtime.config.cognitive), labelled llm_api_key_<tier>. A per-tier key that only the YAML config holds is masked, a key changed after startup is masked from the next pass, the shared key keeps the label llm_api, and a source that raises withholds the output. Six tests in tests/test_ad1337_secret_masking.py; ten mutation rows killed.
```

## 13. Prior art and blind spots

- Internal: AD-1337 S1 (`prompts/ad-1337-s1-secret-masker.md`, the masker and its D7), S2 section 21 (the BF-919 boot test's hermetic CLI, the pattern this generalises), BF-890 (#1529), AD-1137 (`configured_api_keys`).
- External search skipped: ProbOS-specific test plumbing and masker wiring; no row of `docs/research/reference-projects.md` was examined.
- Blind spots: a key below the floor (8) is not masked (as for any value); a value an earlier source names keeps that source's label; a config double gets no config source (D8).

## 14. Acceptance criteria

1. The tests of 8.1 fail on the base as stated, and the 8 new tests pass on the candidate; M1 to M10 are killed as 8.3 says.
2. The focused checks of 8.2 pass; the pre-existing tests in those files pass unchanged.
3. `git diff --check` is clean, the new text is ASCII, and no file outside section 4 changes.
4. The Diff Reviewer approves against section 9.
5. One receipted broad gate on the committed head is green.
6. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 15. Results on the oracle tree (the orchestrator, 2026-11-27)

The oracle is a detached tree at `219cb7cf` with the 22 pairs and the new file of section 6 applied by `contract_tools.py apply` (every SEARCH occurred once at its turn, `git diff --check` clean). Every pytest run: the venv's interpreter with `PYTHONPATH` set to the tree's `src`, an empty HOME that stayed empty, `-n 0`.

- **Blobs after the operations:** `tests/conftest.py` `c4aada13852becbb53bf54f8847491d91f6d6fc3` (523 lines); the new test file `537c4043b57cf20159354144259f89620b39966e` (88); `tests/test_ad1337_secret_masking.py` `950df9e35dd5d0cab37dc3ccb9d6dbcd13c053e0` (884); `security/secret_masking.py` `062414fd4bdc7d8aa3be89162fcbff00af085ad7` (564); `provider_setup.py` `9075bea47118bba0b2db56f5c822237ac872e164` (974); `startup/finalize.py` `633858bbc67ca30cb46da00016e136431c5668cd` (6889); `PROGRESS.md` `b4eca458bea6fed269e9c1c31b606b12cc11492c` (1832); `DECISIONS.md` `2bfe56daca8002c6e521cc883823cf2648c94ee2` (13666). S1 alone (6.1 to 6.3): the masking test file `b59541b4aa8e070810f751e714005009c551cca3` (795).
- **8.1:** the dotted-patch tests (`test_credential_store.py` and `test_quality_hardening.py`): 26 passed on the candidate and 26 passed on the base. The order probe (an autouse fixture in a scratch test module recording `hasattr(probos.credential_store.subprocess, "calls")` on entry): 1 passed, so the conftest fixture runs first. The new file on the base: both tests fail at their `stand_in is not subprocess` premise (the new file's lines 48 and 77), before any boot, so no real `gh` ran. The S1 candidate alone: 417 passed (415 on the base plus the 2 new). S1 plus 6.7 without 6.4 to 6.6: the masking test module fails to import `configured_api_key_pairs`; with 6.5 added: 5 failed (the optional-tier, changed-after-wiring, shared-label, failing-source and callable tests) and 98 passed, `test_pairs_cover_every_tier_label` among them.
- **8.2:** the focused list of 11 files: 423 passed in 131 s on the candidate; the same list without the new file: 415 passed on the base (+8, the new tests); `gen_ad_ledger.py --check` current after the regeneration; `git diff --check` clean.
- **Mutation rows:** the selectors are the new file (2 cases, run for the conftest rows, so that no other test file reaches the developer's `gh` while the fixture is broken) and the new file with the masking and executor-seam tests (131 cases); each passed unmutated. M1 to M10 and eight rows of the orchestrator (X1 to X8) were each KILLED, and every case a row names failed; no row survived. M4 and M5 are also killed by the failing-source test, M9 by the shared-label test, and M10 by three executor-seam tests (the contract names one). The orchestrator's rows: X1 turns the callable check into `if False:`; X2 keeps empty keys in the pairs; X3 changes the label prefix to `llm_api_`; X4 binds the config object at wiring (killed by the changed-after-wiring test's second half); X5 inverts the `SystemConfig` guard (five cases); X6 drops the recorder's append; X7 makes the recorder return instead of raising; X8 makes `_values` ignore the stored callable.
- **Phantom precheck:** 8 candidates, each a false positive of the heuristic: `CognitiveConfig.model_fields` (a pydantic class attribute), `SimpleNamespace(...)` (a stdlib class) and six `mask_text(k=...)` (the f-string prefix `k=` read as a keyword). The merged contract `prompts/ad-1337-s2-producer-seam.md` has 3 such candidates.
